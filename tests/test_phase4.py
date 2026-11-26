"""四期：策略卡晋级与前向模拟盘——只能向前、不用未来数据、晋级须过门禁并人工批准、可回滚。"""
from datetime import date, timedelta

import pytest

from advisor.contracts import ResearchRequest
from advisor.services import Services
from advisor.strategy import PaperError, Rule, StrategyError, StrategySpec
from tests.fakes import CODE, as_of

START = date(2026, 10, 19)


@pytest.fixture
def services(service):
    service.start(ResearchRequest(question=f"复核 {CODE} 半年报业绩", as_of=as_of(), route="standard"), background=False)
    return Services(service.deps, service)


def spec(**kw) -> StrategySpec:
    base = dict(name="已核验低波动", thesis="档案有足够已核验事实、价格在均线附近时纳入观察",
                universe=[CODE], entry=[Rule(field="verified", op=">=", value=3), Rule(field="close", op=">", value=0)],
                exit=[Rule(field="disputed", op=">=", value=5)], max_positions=5, stop_loss_pct=30, max_drawdown_limit=20)
    return StrategySpec(**(base | kw))


def run_days(book, start: date, n: int):
    for i in range(n):
        book.step_all(start + timedelta(days=i))


def test_lifecycle_draft_paper_promote(services):
    book = services.strategy
    v = book.create(spec(), "owner", "首个策略卡：只纳入核验充分的档案")
    assert (v.card_id, v.version, v.status) == ("SC-001", 1, "draft")
    with pytest.raises(StrategyError):
        book.submit(v.card_id, 1, "owner")                       # 草稿不能直接晋级
    book.start_paper(v.card_id, 1, "owner", start=START)
    run_days(book, START, 22)
    trades = book.store.list_trades(v.card_id, 1)
    assert trades and trades[0].side == "open" and trades[0].shares % 100 == 0
    assert trades[0].dossier_version == 1 and trades[0].evidence_ids          # 每笔可追溯到档案与证据
    v = book.submit(v.card_id, 1, "owner")
    assert v.status == "review", [g.detail for g in v.gates if not g.passed]
    assert {g.name for g in v.gates} == {"forward", "lookahead", "drawdown", "explain", "regression"}
    v = book.approve(v.card_id, 1, "owner", "试点通过")
    assert v.status == "promoted" and v.approvals[-1]["self_approved"]        # 单人阶段如实标出自批
    assert book.stats(v)["days"] == 22


def test_paper_is_forward_only(services):
    book = services.strategy
    v = book.create(spec(), "owner", "测试只能向前推进的模拟盘")
    v = book.start_paper(v.card_id, 1, "owner", start=START)
    p = book.paper.step(v, START + timedelta(days=2))
    assert book.paper.step(v, START + timedelta(days=2)) == p                 # 同一天幂等
    with pytest.raises(PaperError):
        book.paper.step(v, START + timedelta(days=1))                         # 不能回填
    with pytest.raises(PaperError):
        book.paper.step(v, START - timedelta(days=1))                         # 不能早于开始日


def test_no_lookahead_before_dossier_exists(services):
    book = services.strategy
    v = book.create(spec(), "owner", "开始日早于档案研究时点")
    v = book.start_paper(v.card_id, 1, "owner", start=date(2026, 10, 10))
    p = book.paper.step(v, date(2026, 10, 12))                                # 档案 as_of 是 10-18
    assert not p.positions and not book.store.list_trades(v.card_id, 1)


def test_gates_keep_card_in_paper_when_failing(services):
    book = services.strategy
    v = book.create(spec(), "owner", "模拟天数不够时不能晋级")
    book.start_paper(v.card_id, 1, "owner", start=START)
    run_days(book, START, 5)
    v = book.submit(v.card_id, 1, "owner")
    assert v.status == "paper"
    assert not next(g for g in v.gates if g.name == "forward").passed


def test_revision_regression_and_rollback(services):
    book = services.strategy
    v1 = book.create(spec(), "owner", "第一版：核验事实不少于三条")
    book.start_paper(v1.card_id, 1, "owner", start=START)
    with pytest.raises(StrategyError):
        book.create(spec(), "owner", "规则完全相同不应产生新版本", card_id=v1.card_id)
    v2 = book.create(spec(stop_loss_pct=20), "owner", "第二版：止损从 30% 收紧到 20%", card_id=v1.card_id)
    assert (v2.version, v2.parent_version) == (2, 1)
    book.start_paper(v1.card_id, 2, "owner", start=START)
    run_days(book, START, 22)
    book.submit(v1.card_id, 1, "owner")
    book.approve(v1.card_id, 1, "owner")
    v2 = book.submit(v1.card_id, 2, "owner")
    reg = next(g for g in v2.gates if g.name == "regression")
    assert "同期" in reg.detail and reg.passed
    book.approve(v1.card_id, 2, "owner")
    assert book.store.get(v1.card_id, 1).status == "retired"
    with pytest.raises(StrategyError):
        book.rollback(v1.card_id, "owner", "太短")
    restored = book.rollback(v1.card_id, "owner", "第二版止损过紧，回到第一版")
    assert restored.version == 1 and restored.status == "promoted"
    assert book.store.get(v1.card_id, 2).status == "rolled_back"


def test_closed_ticker_is_not_rebought_same_day(services):
    book = services.strategy
    v = book.create(spec(exit=[Rule(field="close", op=">", value=0)]), "owner", "退出条件总成立，验证当天不再回补")
    v = book.start_paper(v.card_id, 1, "owner", start=START)
    run_days(book, START, 4)
    trades = book.store.list_trades(v.card_id, 1)
    closed = {(t.ticker, t.date) for t in trades if t.side == "close"}
    assert closed, "应该至少移出一次"
    assert not any((t.ticker, t.date) in closed for t in trades if t.side == "open")
    assert "3" in Rule(field="verified", op=">=", value=3.0).label() and "3.0" not in Rule(field="verified", op=">=", value=3.0).label()
