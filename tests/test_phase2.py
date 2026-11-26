"""二期：双轴路由、估值/技术面、多专家深研、人工复核、检查点升级、工作记忆、撤销、审批绑定、追踪、评测。"""
import time
from datetime import date
from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from advisor.contracts import ResearchRequest
from advisor.evals.compare import summarize
from advisor.evals.metrics import dossier_metrics
from advisor.evals.routing import ece, fit
from advisor.graph.deps import build_deps
from advisor.graph.runner import ResearchService
from advisor.harness import Budget, Harness, RunContext
from advisor.memory import diff_dossiers
from advisor.routing import calibrate, decide_route
from tests.fakes import CODE, FakeDecision, FakeLLM, FakeSource, FakeWebTools, as_of


def make_service(repo, policy, llm=None, source=None):
    deps = build_deps(repo, llm or FakeLLM(), policy, source=source or FakeSource(), web_tools=FakeWebTools())
    return ResearchService(deps, InMemorySaver())


def run(svc, route="standard", question=f"复核 {CODE} 半年报业绩与估值"):
    tid = svc.start(ResearchRequest(question=question, as_of=as_of(), route=route), background=False)
    return tid, svc.deps.repo.get_task(tid)


# ---------- 路由 ----------
class _H:
    def __init__(self, llm, decision=None):
        self.llm_client = llm
        self.decision_client = decision

    def llm(self, role, system, user, schema, purpose):
        return self.llm_client.json(role, system, user, schema)[0]

    def decide(self, state, questions, purpose):
        return self.decision_client.choose(state, questions)[0]


CFG = {"abstain_below": 0.55, "temperature": 1.0, "deep_threshold_stakes": "high"}


def test_router_rules_and_model():
    assert decide_route(_H(FakeLLM()), "q", "research", "deep", CFG).source == "user"
    assert decide_route(_H(FakeLLM()), "什么是PE", "explain", "auto", CFG).route == "quick"
    d = decide_route(_H(FakeLLM(route_probs=(0.1, 0.8, 0.1))), "q", "research", "auto", CFG)
    assert d.route == "standard" and d.source == "model" and abs(sum(d.calibrated.values()) - 1) < 1e-3


def test_router_abstains_and_escalates():
    d = decide_route(_H(FakeLLM(route_probs=(0.2, 0.42, 0.38))), "q", "research", "auto", CFG)
    assert d.abstain and d.route == "deep" and d.source == "abstain"
    d2 = decide_route(_H(FakeLLM(route_probs=(0.1, 0.8, 0.1), stakes="high", uncertainty="high")), "q", "research", "auto", CFG)
    assert d2.route == "deep"
    d3 = decide_route(_H(FakeLLM(route_probs=(0.9, 0.05, 0.05))), "q", "trade_execution", "auto", CFG)
    assert d3.route == "standard"


def test_router_small_model_first():
    llm = FakeLLM(route_probs=(0.1, 0.8, 0.1))
    d = decide_route(_H(llm, FakeDecision(route=(0.05, 0.15, 0.8))), "茅台估值合理吗", "research", "auto",
                     {**CFG, "classifier": "small"})
    assert d.route == "deep" and d.classifier == "small" and d.source == "model"
    assert not any(n == "RouterOut" for _, n in llm.calls)          # 小模型可用时不调大模型


def test_router_small_model_falls_back_to_llm():
    d = decide_route(_H(FakeLLM(route_probs=(0.1, 0.8, 0.1)), FakeDecision(fail=True)), "q", "research", "auto",
                     {**CFG, "classifier": "small"})
    assert d.route == "standard" and d.classifier == "llm" and "小模型不可用" in d.reasons[0]
    d2 = decide_route(_H(FakeLLM(route_probs=(0.1, 0.8, 0.1))), "q", "research", "auto", {**CFG, "classifier": "small"})
    assert d2.classifier == "llm"                                     # 未配置小模型：直接用大模型


def test_router_shadow_records_small_without_using_it():
    d = decide_route(_H(FakeLLM(route_probs=(0.1, 0.8, 0.1)), FakeDecision(route=(0.05, 0.15, 0.8))), "q", "research",
                     "auto", {**CFG, "classifier": "shadow"})
    assert d.route == "standard" and d.classifier == "llm"
    assert d.shadow["route"] == "deep" and d.shadow["classifier"] == "small"


def test_router_fallback_when_classifier_fails():
    class Boom:
        def json(self, *a, **k):
            raise RuntimeError("down")
    assert decide_route(_H(Boom()), "q", "research", "auto", CFG).source == "fallback"


def test_calibration_temperature_and_metrics():
    p = {"quick": 0.8, "standard": 0.15, "deep": 0.05}
    assert calibrate(p, 2.0)["quick"] < 0.8 < calibrate(p, 0.5)["quick"]
    assert ece([0.9, 0.9], [True, False]) == 0.4
    rows = [{"probs": {"quick": 0.9, "standard": 0.05, "deep": 0.05}, "label": "quick"},
            {"probs": {"quick": 0.9, "standard": 0.05, "deep": 0.05}, "label": "standard"}]
    out = fit(rows, 0.55)
    assert out["best_temperature"] > 1.0          # 过度自信 → 需要升温
    t = str(out["best_temperature"])
    assert out["by_temperature"][t]["ece"] == min(v["ece"] for v in out["by_temperature"].values())   # 按 ECE 最小选温度


# ---------- 估值与技术面 ----------
def test_valuation_and_technicals(deps):
    h = deps.harness("t", "standard", as_of(), Budget(limits={"wall_clock_s": 60}))
    card = h.call("valuation.snapshot", code=CODE, as_of=as_of()).cards[0]
    m = {x.field: x for x in card.metrics}
    assert m["np_ttm"].value == Decimal(str(int((44.5 + 82 - 45) * 10 ** 9)))   # 本期累计+上年年报-上年同期
    close = Decimal(FakeSource().daily(CODE, date(2025, 1, 1), as_of())[-1]["close"])
    assert m["mkt_cap"].value == (close * 1_250_000_000).quantize(Decimal("0.01"))
    assert {"pe_ttm", "pb_mrq", "pe_pct", "scn_pe_中位"} <= set(m)
    mk = {x.field for x in h.call("market.daily", code=CODE, as_of=as_of()).cards[0].metrics}
    assert {"ma20_gap", "ma60_gap", "mdd_250d", "vol_ratio_20_60"} <= mk


def test_valuation_same_day_disclosures(deps):
    """年报与一季报同日披露：不能因排序比较 dict 而失败。"""
    src = deps.registry.get("valuation.snapshot")
    orig = FakeSource.balance_rows

    def same_day(self, code):
        rows = orig(self, code)
        for r in rows:
            if r["REPORT_DATE"].startswith(("2025-12-31", "2026-03-31")):
                r["NOTICE_DATE"] = "2026-04-25 00:00:00"
        return rows
    FakeSource.balance_rows = same_day
    try:
        h = deps.harness("t", "standard", as_of(), Budget(limits={"wall_clock_s": 60}))
        assert h.call("valuation.snapshot", code=CODE, as_of=as_of()).cards
    finally:
        FakeSource.balance_rows = orig
    assert src


# ---------- 多专家深研 ----------
def test_deep_flow(repo, policy):
    llm = FakeLLM()
    svc = make_service(repo, policy, llm)
    tid, task = run(svc, route="deep")
    assert task["status"] == "done", task.get("error")
    d = repo.get_dossier(CODE)
    dl = d.deliberation
    experts = {t["expert"] for t in dl["team"]}
    assert experts == {"fundamental", "valuation", "technical", "red_team"}          # 未知专家被丢弃，反证官自动加入
    assert dl["mode"] == "debate" and dl["challenges"] and dl["responses"]
    assert all(ch["target_claim_id"] != "ghost-c1" for ch in dl["challenges"])         # 指向不存在主张的质询被丢弃
    assert "ghost-c9" not in dl["adopted_claim_ids"]
    # 引用自己看不到的证据 → 驳回
    for t in dl["team"]:
        bad = [c for c in t["claims"] if "ev_notvisible" in c["evidence_ids"] or c["text"].startswith("不存在")]
        assert bad and all(c["status"] == "rejected" for c in bad)
    # 首轮隔离：专家提示词里没有其他专家的主张
    assert all("-c1 |" not in p for p in llm.prompts["ExpertDraft"])
    # 模型轴：主席与反证官用 reason，基本面用 draft
    roles = {t["expert"]: t["model_role"] for t in dl["team"]}
    assert roles["fundamental"] == "draft" and roles["valuation"] == "reason"
    assert ("reason", "ChairOutput") in llm.calls and ("reason", "ChallengeSet") in llm.calls
    # 并行专家预算折算进总预算
    assert task["result"]["budget"]["used"]["tokens"] > 1000
    kinds = {w["kind"] for w in repo.list_working(tid)}
    assert {"routing", "team", "expert_result", "challenges", "responses", "chair"} <= kinds
    assert "专家团队与审议" in d.report_md and "交叉质询与裁决" in d.report_md


def test_deep_unresolved_high_needs_human_review(repo, policy):
    svc = make_service(repo, policy, FakeLLM(challenge_severity="high", ruling="unresolved"))
    tid, task = run(svc, route="deep")
    assert task["status"] == "waiting_approval" and task["interrupt"]["type"] == "review"
    svc.resume(tid, approve=False, background=False)
    assert repo.get_task(tid)["status"] == "cancelled" and repo.get_dossier(CODE) is None
    tid2, _ = run(svc, route="deep")
    svc.resume(tid2, approve=True, background=False)
    d = repo.get_dossier(CODE)
    assert d.status == "partial" and any("人工确认" in n for n in d.boundary_notes)
    assert any("未决质询" in x.text for x in d.dissents)


def test_upheld_challenge_blocks_claim(repo, policy):
    svc = make_service(repo, policy, FakeLLM(ruling="upheld"))
    run(svc, route="deep")
    d = repo.get_dossier(CODE)
    target = d.deliberation["challenges"][0]["target_claim_id"]
    assert target not in d.deliberation["adopted_claim_ids"]
    assert any(c.id == target and c.status == "disputed" for c in d.claims)


def test_checkpoint_escalation_to_deep(repo, policy):
    policy.routing["escalate_on"] = {"min_disputed": 1, "min_dissents": 99}
    svc = make_service(repo, policy, FakeLLM(route_probs=(0.1, 0.8, 0.1)))
    _, task = run(svc, route="auto")
    assert task["status"] == "done"
    d = repo.get_dossier(CODE)
    assert d.route == "deep" and d.routing["escalated_from"] == "standard" and d.deliberation


# ---------- 工作记忆与版本差异 ----------
def test_prior_memory_and_diff(repo, policy):
    llm = FakeLLM(wrong_number=False)
    svc = make_service(repo, policy, llm)
    run(svc)
    run(svc)
    assert "<prior_dossier" in llm.prompts["DraftOutput"][-1]
    new, old = repo.get_dossier(CODE, 2), repo.get_dossier(CODE, 1)
    assert new.prior_review and new.prior_review[0].verdict == "retained"
    ev = {c.id: c for c in repo.get_evidence(new.evidence_ids + old.evidence_ids)}
    diff = diff_dossiers(new, old, ev)
    assert diff["from_version"] == 1 and diff["claims"]["kept"]
    assert any(m["name"].startswith("营业收入同比") for m in diff["metrics"])


def test_dependency_propagation_marks_stale(repo, policy):
    svc = make_service(repo, policy, FakeLLM(wrong_number=False))
    tid = svc.start(ResearchRequest(question=f"复核 {CODE}", as_of=date(2026, 6, 1), route="standard"), background=False)
    assert repo.get_task(tid)["status"] == "done"
    run(svc)                                                      # as_of 10-18：新增 2026-06-30 报告期
    new, old = repo.get_dossier(CODE, 2), repo.get_dossier(CODE, 1)
    ev = {c.id: c for c in repo.get_evidence(new.evidence_ids + old.evidence_ids + [i for c in old.claims for i in c.evidence_ids])}
    diff = diff_dossiers(new, old, ev)
    assert diff["stale_claims"] and "2026-06-30" in diff["stale_claims"][0]["reason"]
    assert any(e["source_type"] == "filing" for e in diff["evidence_added"])


# ---------- 一期验收补齐：撤销、审批绑定、clue 可见、追踪 ----------
def test_cancel_stops_in_flight(repo, policy):
    class CancelOnDraft(FakeLLM):
        def json(self, role, system, user, schema):
            if schema.__name__ == "DraftOutput":
                repo.request_cancel(self.task_id)
            return super().json(role, system, user, schema)

    llm = CancelOnDraft()
    svc = make_service(repo, policy, llm)
    import advisor.graph.runner as runner_mod      # 固定 task_id，让假模型能在起草时触发撤销
    real_uuid = runner_mod.uuid.uuid4
    fixed = real_uuid()
    runner_mod.uuid.uuid4 = lambda: fixed
    llm.task_id = "t_" + fixed.hex[:10]
    try:
        _, task = run(svc)
    finally:
        runner_mod.uuid.uuid4 = real_uuid
    assert task["status"] == "cancelled" and repo.get_dossier(CODE) is None


def test_approval_gate_bound_and_expiring(repo, policy):
    policy.approvals.setdefault("skills", {})["market.daily"] = "confirm"
    svc = make_service(repo, policy, FakeLLM(wrong_number=False))
    tid, task = run(svc)
    ticket = task["interrupt"]
    assert ticket["type"] == "approval" and ticket["skill"] == "market.daily" and ticket["args_hash"]
    svc.resume(tid, approve=True, background=False)
    t = repo.get_task(tid)
    assert t["status"] == "done"
    assert any(a["name"] == "market.daily" and a["status"] == "ok" for a in repo.list_audit(tid))
    # 过期审批：即使点了同意也失效
    tid2, _ = run(svc)
    repo.update_task(tid2, interrupt={**repo.get_task(tid2)["interrupt"], "issued_at": time.time() - 10_000})
    svc.resume(tid2, approve=True, background=False)
    assert any(a["name"] == "market.daily" and a["status"] == "HarnessDenied" for a in repo.list_audit(tid2))
    d = repo.get_dossier(CODE)
    assert any("审批" in u for u in d.unknowns)


def test_approval_mismatch_denied(policy):
    from advisor.contracts.skill import Skill, SkillSpec
    from advisor.skills.registry import SkillRegistry
    from pydantic import BaseModel

    class In(BaseModel):
        x: int = 1

    class Out(BaseModel):
        y: int

    policy.approvals.setdefault("skills", {})["t.s"] = "confirm"
    policy.routes["standard"] = policy.routes["standard"].__class__(**{**policy.routes["standard"].__dict__,
                                                                         "allowed_skills": ("t.s",)})
    sk = Skill(spec=SkillSpec(name="t.s", version="1", category="data", permission="read", description="",
                              input_model=In, output_model=Out), run=lambda i: Out(y=1))
    h = Harness(policy, SkillRegistry([sk]), lambda r: None, Budget(limits={"wall_clock_s": 60}), RunContext("t", "standard", as_of()))
    import langgraph.types as lt
    orig = lt.interrupt
    lt.interrupt = lambda ticket: {**ticket, "approve": True, "args_hash": "different"}
    try:
        with pytest.raises(Exception, match="审批未通过或已失效"):
            h.call("t.s", x=2)
    finally:
        lt.interrupt = orig


def test_clues_visible_in_dossier(repo, policy):
    svc = make_service(repo, policy, FakeLLM(wrong_number=False))
    run(svc)
    d = repo.get_dossier(CODE)
    levels = {c.level for c in repo.get_evidence(d.clue_ids)}
    assert "C" in levels and "新闻/事件线索" in d.report_md


def test_tracing_links_audit(repo, policy):
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE._done = False
    trace.set_tracer_provider(provider)
    svc = make_service(repo, policy, FakeLLM(wrong_number=False))
    tid, _ = run(svc)
    names = {s.name for s in exporter.get_finished_spans()}
    assert {"research", "node:intake", "node:commit", "skill:financials.statements", "llm:draft"} <= names
    audit = repo.list_audit(tid)
    assert all(a.get("trace_id") for a in audit) and {a["node"] for a in audit} >= {"collect", "search", "draft"}


# ---------- 评测 ----------
def test_eval_metrics_and_verdict(repo, policy):
    svc = make_service(repo, policy, FakeLLM(wrong_number=False))
    tid, task = run(svc)
    d = repo.get_dossier(CODE)
    ev = {c.id: c for c in repo.get_evidence(d.evidence_ids)}
    m = dossier_metrics(d, ev, task)
    assert 0 < m["score"] <= 1 and m["numeric_accuracy"] == 1.0
    assert m["coverage"]["累计同比"] and m["coverage"]["复核条件"] is False      # 假模型只给 1 条复核条件
    res = [{"route": "standard", "metrics": {**m, "score": 0.70, "tokens": 1000}},
           {"route": "deep", "metrics": {**m, "score": 0.71, "tokens": 3000}}]
    assert summarize(res)["verdict"]["decision"] == "adopt_multi_expert"
    res[1]["metrics"] = {**m, "score": 0.60, "tokens": 3000}
    assert summarize(res)["verdict"]["decision"] == "keep_single_agent"
    res[1]["metrics"] = {**m, "score": 0.75, "tokens": 9000}
    v = summarize(res)["verdict"]
    assert v["decision"] == "keep_single_agent" and not v["affordable"]


def test_eval_compare_isolated_namespace(repo, policy):
    from advisor.evals.compare import run_compare
    svc = make_service(repo, policy, FakeLLM(wrong_number=False))
    rid = run_compare(svc, [{"id": "x", "question": f"复核 {CODE}", "ticker": CODE, "as_of": "2026-10-18"}], ["standard", "deep"])
    r = repo.get_eval(rid)
    assert r["status"] == "done" and len(r["results"]) == 2 and all(x.get("metrics") for x in r["results"])
    assert r["summary"]["verdict"]["decision"] in ("adopt_multi_expert", "keep_single_agent")
    assert repo.list_dossiers() == []                              # 评测档案不进入用户列表
