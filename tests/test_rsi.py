"""RSI 一期：账本不可变、坏案例四要素、六道门禁、状态机（草稿 → 发布）、继承（档案记录版本）、一键回滚。"""
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from advisor.contracts import ResearchRequest
from advisor.rsi import Ledger, LedgerError, RSIRunner, TransitionError
from advisor.rsi.evaluator import JudgeItem, JudgeOut
from advisor.rsi.proposer import LessonDraft, failure_class
from tests.fakes import CODE, FakeLLM, as_of
from tests.test_phase2 import make_service


class RSILLM(FakeLLM):
    """优化器写经验卡；审稿判别器只在看到相关方法提示时才拦下"指标变化 → 直接下因果结论"的主张。"""

    def __init__(self, card: dict | None = None, **kw):
        super().__init__(wrong_number=False, **kw)
        self.card = card or {}

    def json(self, role, system, user, schema):
        if schema is LessonDraft:
            self.calls.append((role, "LessonDraft"))
            return LessonDraft(**({"title": "预收类科目变动先排除渠道政策", "applies_to": "消费品公司合同负债或预收款大幅变动",
                                   "tags": ["合同负债", "预收款", "渠道"], "lesson": "先排除打款政策和渠道结构调整，再推断需求变化",
                                   "must_check": ["业绩说明会中关于渠道和打款政策的表述"],
                                   "invalid_if": "公司已明确说明打款政策未变"} | self.card)), 100
        if schema is JudgeOut:
            self.calls.append((role, "JudgeOut"))
            items = []
            for block in user.split("\n\n"):
                m = re.match(r"\[(\w+)\]", block)
                if m:
                    items.append(JudgeItem(id=m.group(1), needs_check="相关方法提示" in block))
            return JudgeOut(items=items), 400 + 10 * user.count("<method_hints>")
        return super().json(role, system, user, schema)


def _claim(cid, text, status="verified", kind="inference"):
    return {"id": cid, "text": text, "kind": kind, "evidence_ids": ["ev_x"], "status": status}


def seed_dossiers(repo):
    now = datetime.now(timezone.utc)
    base = {"question": "q", "route": "deep", "status": "partial", "summary": "", "unknowns": [], "dissents": [],
            "review_triggers": [], "evidence_ids": [], "quality": {"decision": "partial"}, "boundary_notes": [],
            "task_id": "t", "created_at": now, "clue_ids": []}
    repo.db.dossiers.insert_one(base | {
        "key": "600001", "version": 1, "ticker": "600001", "name": "甲酒业", "as_of": "2026-10-16", "claims": [],
        "deliberation": {"team": [{"expert": "fundamental", "claims": [
            _claim("fundamental-c1", "合同负债同比大幅下降，说明终端需求走弱"),
            _claim("fundamental-c2", "上半年营业收入累计同比微增", kind="fact"),
            _claim("fundamental-c3", "毛利率保持稳定", kind="fact")]}],
            "challenges": [{"id": "ch1", "target_claim_id": "fundamental-c1", "target_expert": "fundamental",
                            "kind": "alternative_explanation", "text": "也可能是渠道打款政策调整", "evidence_ids": []}],
            "rulings": [{"challenge_id": "ch1", "verdict": "upheld", "reason": "无法排除替代解释", "severity": "mid"}]}})
    repo.db.dossiers.insert_one(base | {
        "key": "000002", "version": 1, "ticker": "000002", "name": "乙食品", "as_of": "2026-10-18", "claims": [],
        "deliberation": {"team": [{"expert": "industry", "claims": [
            _claim("industry-c1", "预收款减少说明经销商信心不足"),
            _claim("industry-c2", "行业集中度提升", kind="fact")]}],
            "challenges": [{"id": "ch1", "target_claim_id": "industry-c1", "target_expert": "industry",
                            "kind": "logic_gap", "text": "未讨论收款政策变化", "evidence_ids": []}],
            "rulings": [{"challenge_id": "ch1", "verdict": "upheld", "reason": "推理跳步", "severity": "low"}]}})


@pytest.fixture
def rsi(repo, policy):
    seed_dossiers(repo)
    svc = make_service(repo, policy, RSILLM())
    return svc, RSIRunner(svc.deps, svc.deps.ledger, svc.deps.rsi)


def test_ledger_append_only_and_reason(repo, policy):
    ledger = Ledger(repo.db)
    assert set(ledger.bootstrap(policy)) == {"lessons", "routing", "search"}
    assert ledger.bootstrap(policy) == []
    assert ledger.active_version("routing") == 1
    with pytest.raises(LedgerError):
        ledger.append_asset("routing", {"temperature": 1.0}, "太短", "me", 1)
    with pytest.raises(LedgerError):
        ledger.append_asset("routing", {"temperature": 1.0}, "没有声明 parent 的新版本资产", "me", None)


def test_collect_issues_have_four_elements(rsi):
    _, runner = rsi
    added = runner.collect()
    assert added["S1"] == 2
    assert runner.collect()["S1"] == 0                     # 指纹去重
    for i in runner.ledger.list_issues("S1"):
        assert i.case and i.evidence and len(i.hypothesis) >= 6 and i.kind == "challenge_upheld"


def test_full_loop_release_inherit_rollback(rsi):
    svc, runner = rsi
    runner.collect()
    issue = next(i for i in runner.ledger.list_issues("S1") if i.source["ticker"] == "600001")
    run = runner.propose("S1", issue.id)
    assert run.status == "draft" and run.diff["action"] == "add" and run.content["cards"][0]["id"] == "L-001"
    run = runner.evaluate(run.run_id)
    gates = {g.name: g for g in run.gates}
    assert all(g.passed for g in run.gates), {k: g.detail for k, g in gates.items()}
    assert run.status == "review"
    ev = run.eval
    assert ev["arms"]["cand"]["slices"]["holdout"]["mean"] > ev["arms"]["base"]["slices"]["holdout"]["mean"]   # 迁移到没见过的标的
    assert ev["leakage"]["holdout"] == ["000002"]
    with pytest.raises(TransitionError):
        runner.release(run.run_id, "owner")                 # 未批准不能发布
    run = runner.approve(run.run_id, "owner")
    assert run.approvals[0]["self_approved"]                # 单人阶段明确标出自批
    run = runner.release(run.run_id, "owner")
    assert run.status == "released" and runner.ledger.active_version("lessons") == 2
    assert runner.ledger.get_issues([issue.id])[0].status == "addressed"

    # 继承：下一次研究召回经验卡，并在档案中记录所用版本
    tid = svc.start(ResearchRequest(question=f"复核 {CODE} 半年报业绩，合同负债变化说明什么", as_of=as_of(), route="standard"),
                    background=False)
    task = svc.deps.repo.get_task(tid)
    d = svc.deps.repo.get_dossier(task["result"]["dossier_key"], task["result"]["version"])
    assert d.rsi_versions == {"lessons": 2, "routing": 1, "search": 1}
    assert d.lessons_used == ["L-001 r1"]
    assert any("<method_hints>" in p for p in svc.deps.llm.prompts["DraftOutput"])
    assert "经验库 v2" in d.report_md

    # 一键回滚
    res = runner.rollback("lessons", "owner", "线上同类核验失败率反而上升")
    assert res == {"kind": "lessons", "from": 2, "to": 1}
    assert runner.ledger.active_version("lessons") == 1
    assert runner.ledger.get_run(run.run_id).status == "rolled_back"
    assert failure_class(issue) in runner.ledger.tried_directions("S1")    # 失败方向（这一类误判）记账，不再重复
    with pytest.raises(TransitionError):
        runner.rollback("lessons", "owner", "基线版本不能再回滚了吧")


def test_overfit_gate_rejects_specific_card(repo, policy):
    seed_dossiers(repo)
    svc = make_service(repo, policy, RSILLM(card={"lesson": "甲酒业合同负债下降 42% 时先排除打款政策说明"}))
    runner = RSIRunner(svc.deps, svc.deps.ledger, svc.deps.rsi)
    runner.collect()
    run = runner.evaluate(runner.propose("S1").run_id)
    gate = next(g for g in run.gates if g.name == "overfit")
    assert not gate.passed and "数字" in gate.detail and "公司名" in gate.detail
    assert run.status == "rejected" and "防过拟合" in run.reject_reason


def test_s2_noise_gate_uses_independent_runs(repo, policy):
    svc = make_service(repo, policy, RSILLM())
    runner = RSIRunner(svc.deps, svc.deps.ledger, svc.deps.rsi)
    now = datetime.now(timezone.utc)
    flip = {"quick": 0.1, "standard": 0.46, "deep": 0.44}       # 判别器在 standard/deep 之间摇摆
    for k in range(3):
        rows = [{"question": "复核业绩", "label": "standard", "route": "deep", "source": "abstain", "probs": flip,
                 "abstain": True, "correct": False},
                {"question": "估值分歧大", "label": "deep", "route": "deep", "source": "model",
                 "probs": {"quick": 0.05, "standard": 0.15, "deep": 0.8}, "abstain": False, "correct": True}]
        repo.db.eval_runs.insert_one({"run_id": f"rt_{k}", "type": "routing", "created_at": now - timedelta(minutes=k), "rows": rows})
    assert runner.collect()["S2"] == 1
    run = runner.evaluate(runner.propose("S2").run_id)
    assert run.eval["repeats"] == 3
    assert {g.name for g in run.gates} == {"protocol", "leakage", "overfit", "noise", "cost", "regression"}
    assert next(g for g in run.gates if g.name == "overfit").passed      # 步长受限


def test_rsi_api_overview_and_transitions(repo, policy):
    from fastapi.testclient import TestClient

    from advisor.api.app import create_app
    seed_dossiers(repo)
    svc = make_service(repo, policy, RSILLM())
    with TestClient(create_app(deps=svc.deps, checkpointer=None)) as client:
        assert client.post("/api/rsi/collect").json()["S1"] == 2
        ov = client.get("/api/rsi/overview").json()
        assert ov["loop"]["collect"]["done"] and not ov["loop"]["release"]["done"]
        assert ov["active"]["lessons"]["version"] == 1 and ov["issues"]["S1"]["open"] == 2
        runner = RSIRunner(svc.deps, svc.deps.ledger, svc.deps.rsi)
        run = runner.evaluate(runner.propose("S1").run_id)
        assert client.post(f"/api/rsi/runs/{run.run_id}/release").status_code == 409     # 未批准
        assert client.post(f"/api/rsi/runs/{run.run_id}/approve", json={"note": "ok"}).json()["status"] == "approved"
        assert client.post(f"/api/rsi/runs/{run.run_id}/release").json()["status"] == "released"
        ov = client.get("/api/rsi/overview").json()
        assert ov["loop"]["release"]["done"] and ov["active"]["lessons"]["version"] == 2 and ov["self_approved"] == 1
        assert [a["version"] for a in ov["lineage"]["lessons"]] == [1, 2]
        assert client.post("/api/rsi/rollback", json={"kind": "lessons", "reason": "太短"}).status_code == 409
        assert client.get("/api/watchlist").status_code == 200
