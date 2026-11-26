from datetime import date

import pytest
from pydantic import BaseModel

from advisor.contracts.skill import Skill, SkillSpec
from advisor.harness import Budget, BudgetExceeded, Harness, HarnessDenied, RunContext, SkillFailed
from advisor.skills.registry import SkillRegistry


class In(BaseModel):
    query: str = "x"
    as_of: date | None = None


class Out(BaseModel):
    n: int


def make(policy, skills, route="standard", limits=None, as_of=date(2026, 10, 18)):
    audit: list[dict] = []
    budget = Budget(limits=limits or {"search_calls": 2, "tokens": 100, "wall_clock_s": 60})
    h = Harness(policy, SkillRegistry(skills), audit.append, budget, RunContext("t", route, as_of))
    return h, audit, budget


def skill(name, run=lambda i: Out(n=1), **kw):
    return Skill(spec=SkillSpec(name=name, version="1", category="data", permission="read", description="",
                                input_model=In, output_model=Out, timeout_s=2, **kw), run=run)


def test_unregistered_and_not_whitelisted_denied(policy):
    h, audit, _ = make(policy, [skill("market.daily"), skill("secret.tool")])
    with pytest.raises(HarnessDenied):
        h.call("nope.tool")
    with pytest.raises(HarnessDenied, match="无权"):
        h.call("secret.tool")
    assert h.call("market.daily").n == 1
    assert [a["status"] for a in audit] == ["HarnessDenied", "HarnessDenied", "ok"]


def test_quick_route_cannot_fetch(policy):
    h, _, _ = make(policy, [skill("web.fetch")], route="quick")
    with pytest.raises(HarnessDenied):
        h.call("web.fetch")


def test_action_skills_denied_by_approval_gate(policy, monkeypatch):
    monkeypatch.setattr(policy, "is_allowed", lambda r, s: True)
    h, _, _ = make(policy, [skill("action.place_order")])
    with pytest.raises(HarnessDenied, match="审批门"):
        h.call("action.place_order")


def test_future_as_of_denied(policy):
    h, _, _ = make(policy, [skill("market.daily")])
    with pytest.raises(HarnessDenied, match="晚于研究时点"):
        h.call("market.daily", as_of=date(2026, 12, 1))


def test_egress_blocks_sensitive_query(policy):
    h, _, _ = make(policy, [skill("web.search", egress_fields=("query",), budget_kind="search_calls")])
    with pytest.raises(HarnessDenied, match="敏感"):
        h.call("web.search", query="我的持仓 账户 6222020200112233445")
    assert h.call("web.search", query="示例酒业 业绩").n == 1


def test_budget_and_idempotency(policy):
    calls = []
    s = skill("web.search", run=lambda i: calls.append(i) or Out(n=len(calls)), egress_fields=("query",), budget_kind="search_calls")
    h, _, budget = make(policy, [s])
    h.call("web.search", query="a")
    h.call("web.search", query="a")          # 幂等：命中缓存，不重复执行、不重复计费
    h.call("web.search", query="b")
    assert len(calls) == 2 and budget.used["search_calls"] == 2
    with pytest.raises(BudgetExceeded):
        h.call("web.search", query="c")


def test_idempotency_is_task_scoped_across_nodes(deps):
    """同一任务的不同节点（各自新建 Harness）共用幂等缓存；不同任务互不影响。"""
    from datetime import date as _d
    calls = []
    deps.registry.register(skill("x.echo", run=lambda i: calls.append(i) or Out(n=len(calls))))
    deps.policy.routes["standard"] = deps.policy.routes["standard"].__class__(
        **{**deps.policy.routes["standard"].__dict__, "allowed_skills": deps.policy.routes["standard"].allowed_skills + ("x.*",)})
    b = lambda: Budget(limits={"wall_clock_s": 60})   # noqa: E731
    h1 = deps.harness("t_same", "standard", _d(2026, 10, 18), b(), node="collect", task_scoped_cache=True)
    h2 = deps.harness("t_same", "standard", _d(2026, 10, 18), b(), node="search", task_scoped_cache=True)
    h3 = deps.harness("t_other", "standard", _d(2026, 10, 18), b(), node="collect", task_scoped_cache=True)
    assert h1.call("x.echo", query="q").n == 1
    assert h2.call("x.echo", query="q").n == 1          # 同任务另一个节点：命中缓存，不重复执行
    assert h3.call("x.echo", query="q").n == 2          # 另一个任务：重新执行
    assert len(calls) == 2


def test_retry_only_retryable(policy):
    attempts = []

    def flaky(i):
        attempts.append(1)
        if len(attempts) < 2:
            raise SkillFailed("429", retryable=True)
        return Out(n=7)

    h, _, _ = make(policy, [skill("market.daily", run=flaky)])
    assert h.call("market.daily").n == 7 and len(attempts) == 2

    def broken(i):
        attempts.append(1)
        raise SkillFailed("402 余额不足", retryable=False)

    attempts.clear()
    h2, _, _ = make(policy, [skill("market.daily", run=broken)])
    with pytest.raises(SkillFailed):
        h2.call("market.daily")
    assert len(attempts) == 1


def test_wall_clock_deadline(policy):
    h, _, budget = make(policy, [skill("market.daily")], limits={"wall_clock_s": 10})
    budget.started_at -= 100
    with pytest.raises(BudgetExceeded, match="时限"):
        h.call("market.daily")


def test_safety_check_failure_blocks(policy, monkeypatch):
    h, _, _ = make(policy, [skill("web.search", egress_fields=("query",))])
    monkeypatch.setattr(h.egress, "check_outbound", lambda t: 1 / 0)
    with pytest.raises(HarnessDenied, match="默认阻断"):
        h.call("web.search", query="abc")


def test_llm_redacts_and_charges(policy):
    seen = {}

    class LLM:
        def json(self, role, system, user, schema):
            seen["user"] = user
            return Out(n=1), 40

    h, audit, budget = make(policy, [])
    h.llm_client = LLM()
    h.llm("draft", "s", "我的持仓 30万元 怎么办", Out, purpose="x")
    assert "30万" not in seen["user"] and budget.used["tokens"] == 40
    assert audit[-1]["kind"] == "llm"


def test_decision_call_is_redacted_and_audited(policy):
    from tests.fakes import FakeDecision
    h, audit, _ = make(policy, [])
    h.decision_client = FakeDecision()
    out = h.decide("我的账户有 50 万元，茅台估值合理吗", {"route": ("which?", {"quick": None, "standard": None, "deep": None})},
                   purpose="route_classify_small")
    assert set(out["route"]) == {"quick", "standard", "deep"}
    assert "我的账户" not in h.decision_client.calls[0] and "[已脱敏]" in h.decision_client.calls[0]
    assert audit[-1]["kind"] == "decision" and audit[-1]["status"] == "ok" and audit[-1]["model"] == "fake-kev"
