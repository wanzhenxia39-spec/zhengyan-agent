"""端到端：虚构数据 + 假模型，验证 SOP、核验、质量门、版本链、人在环与审计。"""
from advisor.contracts import ResearchRequest
from tests.fakes import CODE, as_of


def run(service, question=f"复核 {CODE} 半年报业绩", route="standard"):
    tid = service.start(ResearchRequest(question=question, as_of=as_of(), route=route), background=False)
    return tid, service.deps.repo.get_task(tid)


def test_standard_flow_partial_with_disputed_claim(service, fakes):
    tid, task = run(service)
    assert task["status"] == "done", task
    repo = service.deps.repo
    d = repo.get_dossier(CODE)
    assert d.version == 1 and d.status == "partial"          # 有存疑主张 → 保留未知
    status = {c.text: c.status for c in d.claims}
    assert status["上半年营业收入950.00亿元。"] == "disputed"
    assert status["行业已经见顶。"] == "rejected"
    assert all(s == "verified" for t, s in status.items() if t not in ("上半年营业收入950.00亿元。", "行业已经见顶。"))
    # 补证轮次：第二轮只搜缺口
    assert any("渠道库存" in q for q in fakes["web"].searches)
    assert d.quality.decision == "partial"
    # 时点：晚于 as_of 的三季报不得出现
    ev = repo.get_evidence(d.evidence_ids)
    assert not any("2026-09-30" in c.title for c in ev)
    restated = [c for c in ev if c.source_type == "filing" and "2025-06-30" in c.title]
    assert restated and restated[0].pit == "weak"            # 追溯调整被标注
    # 网页：注入内容降为 C，转载合并
    web = list(repo.db.evidence.find({"source_type": "web"}))
    inj = [w for w in web if "inj" in w["source_url"]]
    assert inj and all(w["level"] == "C" for w in inj)
    assert not any("立即买入" in w["excerpt"] for w in web)
    assert sum("910亿元" in w["title"] for w in web) == 1
    # 报告
    assert "未通过核验" in d.report_md and "不构成投资建议" in d.report_md
    # 审计覆盖 Skill 与模型
    kinds = {a["kind"] for a in repo.list_audit(tid)}
    assert kinds == {"skill", "llm"}


def test_pass_and_version_chain(service, fakes):
    fakes["llm"].wrong_number = False
    run(service)
    _, task = run(service)
    d = service.deps.repo.get_dossier(CODE)
    assert d.version == 2 and d.parent_version == 1
    assert d.status == "committed" and d.quality.decision == "pass"
    assert service.deps.repo.get_dossier(CODE, 1) is not None       # 旧版本保留


def test_quick_route_no_fetch(service, fakes):
    _, task = run(service, route="quick")
    assert task["status"] == "done"
    assert fakes["web"].fetches == []
    assert len(fakes["web"].searches) <= 2
    roles = {r for r, _ in fakes["llm"].calls}
    assert "reason" not in roles


def test_sensitive_info_requires_consent(service):
    tid, task = run(service, question=f"我的持仓有 30万元 {CODE}，要不要卖？")
    assert task["status"] == "waiting_approval" and task["interrupt"]["type"] == "consent"
    service.resume(tid, approve=False, background=False)
    assert service.deps.repo.get_task(tid)["status"] == "cancelled"
    assert service.deps.repo.get_dossier(CODE) is None

    tid2, _ = run(service, question=f"我的持仓有 30万元 {CODE}，要不要卖？")
    service.resume(tid2, approve=True, background=False)
    assert service.deps.repo.get_task(tid2)["status"] == "done"
    d = service.deps.repo.get_dossier(CODE)
    assert any("脱敏" in n for n in d.boundary_notes)


def test_trade_intent_gets_boundary_note(service):
    run(service, question=f"帮我直接买入 {CODE}")
    d = service.deps.repo.get_dossier(CODE)
    assert any("不执行任何买卖" in n for n in d.boundary_notes)


def test_unknown_ticker_fails_visibly(service, fakes):
    _, task = run(service, question="随便聊聊白酒")
    assert task["status"] == "failed" and "代码" in task["error"]
