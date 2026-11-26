"""⑤ 状态机：草稿 → 待审 → 已批准 → 已发布 → 归档 / 回滚。每次推进都写事件；发布必须由人批准。

单人开发阶段，触发人和批准人是同一个人：审批记录会明确标出「自批」，不伪装成已经做到了角色分离。
"""
from typing import Callable

from advisor.rsi.evaluator import evaluate_s1, evaluate_s2, evaluate_s3
from advisor.rsi.gates import run_gates
from advisor.rsi.issues import collect
from advisor.rsi.ledger import Ledger, LedgerError
from advisor.rsi.loader import RSILoader
from advisor.rsi.models import KIND_LABEL, LessonCard, Run
from advisor.rsi.proposer import PROPOSERS

MIN_ROUTING_RUNS = 3


class TransitionError(Exception):
    pass


class RSIRunner:
    def __init__(self, deps, ledger: Ledger, loader: RSILoader):
        self.deps, self.ledger, self.loader = deps, ledger, loader

    def _get(self, run_id: str, *allowed: str) -> Run:
        run = self.ledger.get_run(run_id)
        if not run:
            raise TransitionError(f"运行 {run_id} 不存在")
        if allowed and run.status not in allowed:
            raise TransitionError(f"{run_id} 当前为 {run.status}，不能执行该操作（需要 {'/'.join(allowed)}）")
        return run

    def _move(self, run: Run, status: str, action: str, actor: str, detail: str, **extra) -> Run:
        old = run.status
        run.status = status
        self.ledger.save_run(run)
        self.ledger.event(action, actor, run_id=run.run_id, kind=run.kind, scenario=run.scenario,
                          from_status=old, to_status=status, detail=detail, **extra)
        return run

    # ① 收集
    def collect(self, actor: str = "owner") -> dict:
        self.ledger.bootstrap(self.deps.policy)
        return collect(self.ledger, self.deps.repo, actor, self.deps.policy)

    # ② 提议
    def propose(self, scenario: str, issue_id: str | None = None, actor: str = "owner") -> Run:
        self.ledger.bootstrap(self.deps.policy)
        run = PROPOSERS[scenario](self.deps, self.ledger, issue_id, actor)
        self.ledger.insert_run(run)
        self.ledger.event("propose", "optimizer", run_id=run.run_id, kind=run.kind, scenario=scenario,
                          to_status="draft", detail=run.change_reason, triggered_by=actor)
        return run

    # ③ 对比 + ④ 门控
    def evaluate(self, run_id: str, actor: str = "owner", log: Callable[[str], None] = lambda m: None) -> Run:
        run = self._get(run_id, "draft")
        base = self.ledger.get_asset(run.kind, run.base_version)
        if run.scenario == "S1":
            cards = lambda c: [LessonCard.model_validate(x) for x in c.get("cards", [])]   # noqa: E731
            ev = evaluate_s1(self.deps, self.ledger, run, cards(base.content), cards(run.content), log)
        elif run.scenario == "S2":
            self._top_up_routing(log)
            ev = evaluate_s2(self.deps, self.ledger, run, base.content, run.content, log)
        else:
            ev = evaluate_s3(self.deps, self.ledger, run, base.content, run.content, log)
        run.eval = ev
        run.gates = run_gates(run, ev, self.ledger)
        failed = [g for g in run.gates if not g.passed]
        self.ledger.event("evaluate", "evaluator", run_id=run.run_id, kind=run.kind, scenario=run.scenario,
                          detail="六道门控：" + " ".join(f"{g.label}{'✓' if g.passed else '✗'}" for g in run.gates),
                          gates={g.name: g.passed for g in run.gates})
        if failed:
            run.reject_reason = "；".join(f"{g.label}：{g.detail}" for g in failed)
            return self._move(run, "rejected", "reject", "gates", f"门控未通过：{run.reject_reason}")
        return self._move(run, "review", "submit", actor, "六道门控全部通过，提交人工审批")

    def _top_up_routing(self, log: Callable[[str], None]) -> None:
        """噪声门控至少需要 3 次独立的判别器运行。"""
        from advisor.evals.routing import run_routing_eval
        have = self.deps.repo.db.eval_runs.count_documents({"type": "routing"})
        for i in range(max(MIN_ROUTING_RUNS - have, 0)):
            log(f"补跑路由评测 {i + 1}/{MIN_ROUTING_RUNS - have}（噪声门控需要 ≥{MIN_ROUTING_RUNS} 次独立运行）")
            run_routing_eval(self.deps)

    # ⑤ 人工批准 / 发布 / 回滚
    def approve(self, run_id: str, actor: str, note: str = "") -> Run:
        run = self._get(run_id, "review")
        if run.risk == "high" and len(note.strip()) < 10:
            raise TransitionError("高风险改动（改抓取站点名单）必须写明批准理由，不少于 10 个字")
        self_approved = actor == run.triggered_by
        run.approvals.append({"by": actor, "note": note, "self_approved": self_approved})
        return self._move(run, "approved", "approve", actor,
                          f"人工批准{'（自批：触发人与批准人相同，单人阶段未做到角色分离）' if self_approved else ''}"
                          + (f"：{note}" if note else ""), self_approved=self_approved)

    def reject(self, run_id: str, actor: str, reason: str) -> Run:
        run = self._get(run_id, "draft", "review", "approved")
        run.reject_reason = reason
        return self._move(run, "rejected", "reject", actor, f"人工拒绝：{reason}")

    def release(self, run_id: str, actor: str) -> Run:
        run = self._get(run_id, "approved")
        active = self.ledger.active_version(run.kind)
        if active != run.base_version:
            raise TransitionError(f"{KIND_LABEL[run.kind]}在用版本已从 v{run.base_version} 变为 v{active}，候选需重新评测")
        try:
            asset = self.ledger.append_asset(run.kind, run.content, run.change_reason, actor, run.base_version, run.run_id)
        except LedgerError as e:
            raise TransitionError(str(e)) from e
        for prev in self.ledger.list_runs():
            if prev.kind == run.kind and prev.status == "released":
                self._move(prev, "archived", "archive", "system", f"被 {run.run_id} 发布的 v{asset.version} 取代")
        run.released_version = asset.version
        self.ledger.set_issue_status(run.issue_ids, "addressed")
        self.loader.invalidate()
        return self._move(run, "released", "release", actor,
                          f"发布{KIND_LABEL[run.kind]} v{asset.version}（parent v{run.base_version}，sha256 {asset.sha256[:10]}）",
                          active_version=asset.version)

    def rollback(self, kind: str, actor: str, reason: str) -> dict:
        current = self.ledger.active_asset(kind)
        if not current or current.parent_version is None:
            raise TransitionError(f"{KIND_LABEL[kind]}已是基线版本，无法回滚")
        if len(reason.strip()) < 10:
            raise TransitionError("回滚理由不少于 10 个字")
        self.ledger.event("rollback", actor, kind=kind, active_version=current.parent_version,
                          detail=f"{KIND_LABEL[kind]} v{current.version} → v{current.parent_version}：{reason}")
        if current.run_id and (run := self.ledger.get_run(current.run_id)):
            run.reject_reason = f"发布后回滚：{reason}"
            self._move(run, "rolled_back", "rolled_back", actor, f"已回滚：{reason}")
            self.ledger.set_issue_status(run.issue_ids, "open")
        self.loader.invalidate()
        return {"kind": kind, "from": current.version, "to": current.parent_version}
