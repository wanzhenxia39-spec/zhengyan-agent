"""Harness：所有 Skill 与模型调用的唯一入口。

顺序：撤销检查 → 注册检查 → 流程白名单 → 输入校验 → 前置检查（时点/出域）→ 审批门控
→ 预算 → 幂等缓存 → 超时执行与有限重试 → 输出校验 → 审计（含 trace_id、节点）。
任一安全关键检查异常时默认阻断。
"""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from langgraph.errors import GraphInterrupt
from pydantic import BaseModel, ValidationError

from advisor.harness.budget import Budget
from advisor.harness.egress import EgressGuard
from advisor.harness.errors import ApprovalRequired, BudgetExceeded, HarnessDenied, SkillFailed, TaskCancelled
from advisor.harness.policy import Policy
from advisor.tracing import span

_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="skill")
MAX_RETRIES = 2


@dataclass
class RunContext:
    task_id: str
    route: str
    as_of: date
    principal: str = "researcher"
    node: str = ""
    is_cancelled: Callable[[], bool] = field(default=lambda: False)


class Harness:
    def __init__(
        self,
        policy: Policy,
        registry: Any,
        audit: Callable[[dict], None],
        budget: Budget,
        ctx: RunContext,
        llm: Any = None,
        decision: Any = None,
        cache: dict | None = None,
    ):
        self.policy = policy
        self.registry = registry
        self.audit = audit
        self.budget = budget
        self.ctx = ctx
        self.llm_client = llm
        self.decision_client = decision
        self.egress = EgressGuard(
            policy.egress.get("sensitive_patterns", []),
            policy.egress.get("trade_intent_patterns", []),
        )
        # 幂等缓存：研究任务传入"任务级"字典（同一 task_id 的所有节点、并行专家共用）；不传则只在本实例内有效
        self._cache: dict[str, BaseModel] = cache if cache is not None else {}

    def _base_record(self, kind: str, name: str) -> dict:
        return {"task_id": self.ctx.task_id, "kind": kind, "name": name, "route": self.ctx.route,
                "node": self.ctx.node, "principal": self.ctx.principal}

    def check_cancelled(self) -> None:
        if self.ctx.is_cancelled():
            raise TaskCancelled("任务已被取消或授权已撤销，停止执行")

    # ---------- Skill 调用 ----------
    def call(self, name: str, /, **args: Any) -> BaseModel:
        started = time.time()
        record = self._base_record("skill", name)
        with span(f"skill:{name}", task_id=self.ctx.task_id, node=self.ctx.node, principal=self.ctx.principal) as ids:
            record.update(ids)
            try:
                self.check_cancelled()
                skill = self._admit(name)
                inp = skill.spec.input_model(**args)
                self._pre_tool_use(skill.spec, inp)
                key = self._idempotency_key(skill.spec, inp)
                record.update(version=skill.spec.version, args_hash=key[:16])
                self._approval_gate(skill.spec, key[:16])
                if key in self._cache:
                    record["status"] = "cache_hit"
                    return self._cache[key]
                if skill.spec.budget_kind:
                    self.budget.check(skill.spec.budget_kind)
                out = self._run_with_retry(skill, inp)
                if not isinstance(out, skill.spec.output_model):
                    raise HarnessDenied(f"{name} 输出不符合契约")
                if skill.spec.budget_kind:
                    self.budget.charge(skill.spec.budget_kind)
                self._cache[key] = out
                record["status"] = "ok"
                return out
            except (HarnessDenied, ApprovalRequired, BudgetExceeded, SkillFailed, TaskCancelled) as e:
                record.update(status=type(e).__name__, error=str(e))
                raise
            except ValidationError as e:
                record.update(status="invalid_input", error=str(e)[:300])
                raise HarnessDenied(f"{name} 参数不符合契约: {e.errors()[0]['msg']}") from e
            except GraphInterrupt:
                record["status"] = "awaiting_approval"
                raise
            finally:
                record["duration_ms"] = int((time.time() - started) * 1000)
                self.audit(record)

    def _admit(self, name: str):
        skill = self.registry.get(name)
        if skill is None:
            raise HarnessDenied(f"未注册的 Skill: {name}")
        if not self.policy.is_allowed(self.ctx.route, name):
            raise HarnessDenied(f"流程 {self.ctx.route} 无权调用 {name}")
        if self.policy.approval_level(name) == "deny":
            raise HarnessDenied(f"{name} 被审批门控禁止")
        self.budget.check()
        return skill

    def _approval_gate(self, spec, args_hash: str) -> None:
        """confirm 级调用暂停等人确认。审批绑定 Skill、版本与参数，参数或版本变化即失效。"""
        if self.policy.approval_level(spec.name) != "confirm":
            return
        ticket = {
            "type": "approval", "skill": spec.name, "version": spec.version, "args_hash": args_hash,
            "ttl_s": int(self.policy.approvals.get("ttl_s", 600)),
            "message": f"调用 {spec.name}（v{spec.version}）需要你确认",
        }
        try:
            from langgraph.types import interrupt
            decision = interrupt(ticket)
        except RuntimeError as e:  # 不在图内运行（如 MCP）：无法等待人，直接拒绝
            raise ApprovalRequired(spec.name) from e
        bound = all(decision.get(k) == ticket[k] for k in ("skill", "version", "args_hash"))
        if not (decision.get("approve") and bound):
            raise HarnessDenied(f"{spec.name} 审批未通过或已失效：{decision.get('reason', '版本/参数与审批时不一致')}")

    def _pre_tool_use(self, spec, inp: BaseModel) -> None:
        try:
            as_of = getattr(inp, "as_of", None)
            if as_of is not None and as_of > self.ctx.as_of:
                raise HarnessDenied(f"{spec.name} 请求的时点 {as_of} 晚于研究时点 {self.ctx.as_of}")
            for field_name in spec.egress_fields:
                value = getattr(inp, field_name)
                if isinstance(value, str):
                    self.egress.check_outbound(value)
        except HarnessDenied:
            raise
        except Exception as e:  # 安全检查自身出错：默认阻断
            raise HarnessDenied(f"前置检查不可用，默认阻断: {e}") from e

    def _run_with_retry(self, skill, inp: BaseModel) -> BaseModel:
        last: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            future = _POOL.submit(skill.run, inp)
            try:
                return future.result(timeout=skill.spec.timeout_s)
            except FutureTimeout:
                last = SkillFailed(f"{skill.spec.name} 超时（{skill.spec.timeout_s}s）", retryable=True)
            except SkillFailed as e:
                last = e
            except Exception as e:
                retry = isinstance(e, skill.spec.retryable)
                last = SkillFailed(f"{skill.spec.name} 失败: {e}", retryable=retry)
            if not getattr(last, "retryable", False) or attempt == MAX_RETRIES:
                break
            self.check_cancelled()
            time.sleep(min(2 ** attempt, 8))
        raise last  # type: ignore[misc]

    @staticmethod
    def _idempotency_key(spec, inp: BaseModel) -> str:
        payload = json.dumps(
            {"skill": spec.name, "v": spec.version, "in": inp.model_dump(mode="json")},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    # ---------- 模型调用 ----------
    def llm(self, role: str, system: str, user: str, schema: type[BaseModel], purpose: str) -> BaseModel:
        """模型调用同样受撤销、预算、脱敏与审计约束。"""
        started = time.time()
        record = {**self._base_record("llm", purpose), "role": role}
        with span(f"llm:{purpose}", task_id=self.ctx.task_id, node=self.ctx.node, role=role) as ids:
            record.update(ids)
            try:
                self.check_cancelled()
                self.budget.check("tokens", 1)
                obj, usage = self.llm_client.json(
                    role=role, system=system, user=self.egress.redact(user), schema=schema
                )
                self.budget.charge("tokens", usage)
                record.update(status="ok", tokens=usage)
                return obj
            except Exception as e:
                record.update(status=type(e).__name__, error=str(e)[:300])
                raise
            finally:
                record["duration_ms"] = int((time.time() - started) * 1000)
                self.audit(record)

    def decide(self, state: str, questions: dict[str, tuple[str, dict[str, str]]], purpose: str) -> dict[str, dict[str, float]]:
        """决策小模型调用：同样受撤销、脱敏与审计约束；本地模型不计 token 预算。"""
        if self.decision_client is None:
            raise RuntimeError("未配置决策小模型")
        started = time.time()
        record = {**self._base_record("decision", purpose), "role": "decision"}
        with span(f"decision:{purpose}", task_id=self.ctx.task_id, node=self.ctx.node) as ids:
            record.update(ids)
            try:
                self.check_cancelled()
                answers, meta = self.decision_client.choose(self.egress.redact(state), questions)
                record.update(status="ok", tokens=0, model=meta.get("model"))
                return answers
            except Exception as e:
                record.update(status=type(e).__name__, error=str(e)[:300])
                raise
            finally:
                record["duration_ms"] = int((time.time() - started) * 1000)
                self.audit(record)
