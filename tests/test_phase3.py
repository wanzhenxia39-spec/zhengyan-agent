"""三期：用户确认档案（只能本人确认）、个人情境官（只对照已确认约束）、事件订阅与增量复核（无变化不打扰）。"""
from datetime import date

import pytest

from advisor.contracts import ResearchRequest
from advisor.personal import Holding, ProfileError, ProfileInput, RiskProfile, assess
from advisor.services import Services
from tests.fakes import CODE, as_of


@pytest.fixture
def services(service):
    svc = Services(service.deps, service)
    tid = service.start(ResearchRequest(question=f"复核 {CODE} 半年报业绩", as_of=as_of(), route="standard"),
                        background=False)
    assert service.deps.repo.get_task(tid)["status"] == "done"
    return svc


def _fit(svc: Services):
    d = svc.deps.repo.get_dossier(CODE)
    return {c.key: c for c in assess(d, svc.deps.repo.get_evidence(d.evidence_ids), svc.profiles.current()).checks}


# ---------- 用户确认档案 ----------
def test_profile_requires_explicit_confirmation_and_keeps_versions(services):
    store = services.profiles
    data = ProfileInput(risk=RiskProfile(max_drawdown_pct=20, horizon_months=36),
                        holdings=[Holding(ticker=CODE, thesis="高端白酒提价能力强，现金流稳定")])
    with pytest.raises(ProfileError):
        store.confirm(data, "owner", confirmed=False)              # 未确认不写入
    assert store.current() is None
    v1 = store.confirm(data, "owner", confirmed=True)
    v2 = store.confirm(data.model_copy(update={"change_note": "调整期限"}), "owner", confirmed=True)
    assert (v1.version, v2.version, v2.parent_version) == (1, 2, 1)
    assert [v.version for v in store.history()] == [2, 1]          # 旧版本保留
    with pytest.raises(ProfileError):
        store.confirm(ProfileInput(holdings=[Holding(ticker=CODE, thesis="理由一二"), Holding(ticker=CODE, thesis="理由三四")]),
                      "owner", confirmed=True)


# ---------- 个人情境官 ----------
def test_officer_marks_unconfirmed_as_unknown(services):
    checks = _fit(services)
    assert checks["thesis"].status == "unknown" and "不替你猜" in checks["thesis"].detail
    assert checks["drawdown"].status == "unknown" and checks["horizon"].status == "unknown"


def test_officer_compares_against_confirmed_constraints(services):
    services.profiles.confirm(ProfileInput(
        risk=RiskProfile(max_drawdown_pct=5, horizon_months=3, liquidity_note="明年初付首付"),
        holdings=[Holding(ticker=CODE, thesis="上半年营业收入增长")]), "owner", confirmed=True)
    checks = _fit(services)
    assert checks["drawdown"].status == "conflict"                # 回撤超出确认的 5%
    assert checks["horizon"].status == "attention" and "首付" in checks["horizon"].detail
    # 购买理由 → 相关主张（含被核验为存疑的营收主张）
    assert checks["thesis"].status in ("attention", "conflict") and checks["thesis"].refs
    assert checks["evidence"].status == "attention"               # 档案是部分结论


def test_profile_change_marks_affected_dossiers(services):
    """改约束 → 标出个人情境结论变了的档案；没变的不打扰。"""
    v1 = services.confirm_profile(ProfileInput(risk=RiskProfile(max_drawdown_pct=90, horizon_months=36)), "owner", True)
    assert {c["key"] for x in v1.impact for c in x["changes"]} >= {"drawdown"}      # 从「未知」变为已对照
    v2 = services.confirm_profile(ProfileInput(risk=RiskProfile(max_drawdown_pct=90, horizon_months=36),
                                               change_note="只改备注"), "owner", True)
    assert v2.impact == []
    v3 = services.confirm_profile(ProfileInput(risk=RiskProfile(max_drawdown_pct=5, horizon_months=36)), "owner", True)
    hit = next(x for x in v3.impact if x["ticker"] == CODE)
    assert [(c["key"], c["before"], c["after"]) for c in hit["changes"]] == [("drawdown", "ok", "conflict")]
    assert services.profiles.current().impact == v3.impact                         # 写进了这个版本的记录


def test_officer_never_calls_model(services, fakes):
    services.profiles.confirm(ProfileInput(risk=RiskProfile(max_drawdown_pct=30)), "owner", confirmed=True)
    before = len(fakes["llm"].calls)
    _fit(services)
    assert len(fakes["llm"].calls) == before                       # 个人信息不出域


# ---------- 订阅与增量复核 ----------
def test_scan_without_changes_does_not_alert(services):
    services.watch.store.subscribe(CODE, price_move_pct=50)
    assert services.watch.scan(CODE, as_of()) is None
    assert services.watch.store.get_sub(CODE).last_scan_note.startswith("无变化")
    assert services.watch.store.list_alerts() == []


def test_new_report_marks_dependent_claims_and_dedupes(services):
    services.watch.store.subscribe(CODE, price_move_pct=50)
    today = date(2026, 10, 30)                                     # 三季报 10-28 披露
    alert = services.watch.scan(CODE, today)
    assert alert and alert.events[0].kind == "new_report" and "2026-09-30" in alert.events[0].title
    assert alert.affected and all("2026-09-30" in a.reason for a in alert.affected)
    assert any(e.kind == "trigger" and "三季报" in e.title for e in alert.events)    # 档案自己的复核条件被触发
    assert services.watch.scan(CODE, today).id == alert.id                           # 同一批变化只提醒一次
    assert len(services.watch.store.list_alerts()) == 1
    # 档案本身不被改写
    assert services.deps.repo.get_dossier(CODE).version == 1


def test_price_move_alert_uses_threshold(services):
    services.watch.store.subscribe(CODE, price_move_pct=1)
    alert = services.watch.scan(CODE, date(2026, 10, 25))
    assert alert and any(e.kind == "price_move" for e in alert.events)


def test_incremental_review_creates_new_version(services, fakes):
    services.watch.store.subscribe(CODE, price_move_pct=50)
    alert = services.watch.scan(CODE, date(2026, 10, 30))
    task_id = services.watch.start_review(alert.id, _SyncService(services.research))
    task = services.deps.repo.get_task(task_id)
    assert task["status"] == "done", task
    assert any("本次重点复核" in u for u in fakes["llm"].prompts["DraftOutput"])                  # 受影响结论进入提示词
    services.watch.sync()
    a = services.watch.store.get_alert(alert.id)
    assert a.status == "resolved" and a.resolved_version == 2
    d2 = services.deps.repo.get_dossier(CODE)
    assert d2.version == 2 and d2.prior_review                     # 新版本逐条复核旧结论
    assert services.watch.scan(CODE, date(2026, 10, 30)) is None   # 复核后不再提醒


class _SyncService:
    """测试里同步执行研究任务。"""

    def __init__(self, svc):
        self.svc = svc

    def start(self, req, **kw):
        req = req.model_copy(update={"as_of": date(2026, 10, 30)})
        return self.svc.start(req, background=False, **kw)
