from datetime import date, datetime, timezone
from decimal import Decimal

from advisor.contracts import Claim, EvidenceCard, Metric
from advisor.evidence.verifier import extract_numbers, verify_claim

AS_OF = date(2026, 10, 18)


def card(id, level="A", source_type="filing", metrics=(), excerpt="", published=datetime(2026, 8, 15, tzinfo=timezone.utc), **kw):
    return EvidenceCard(id=id, level=level, source_type=source_type, title=id, origin_id=id, as_of=AS_OF,
                        retrieved_at=published, published_at=published, snapshot_hash="h", excerpt=excerpt,
                        metrics=list(metrics), skill="s", skill_version="1", **kw)


EV = {
    "a": card("a", metrics=[Metric(name="营业收入", field="OPERATE_INCOME", value=Decimal("90703260000"), unit="元",
                                   period="2026-06-30", basis="cumulative"),
                            Metric(name="同比", field="X_YOY", value=Decimal("-1.21"), unit="%", period="2026-06-30", basis="change"),
                            Metric(name="毛利率", field="GM", value=Decimal("93.53"), unit="%", period="2026-06-30", basis="ratio"),
                            Metric(name="毛利率", field="GM", value=Decimal("94.06"), unit="%", period="2025-06-30", basis="ratio")]),
    "b": card("b", level="B", source_type="web", excerpt="营业收入1688.38亿元，同比下降1.21%"),
    "c": card("c", level="C", source_type="web"),
    "f": card("f", published=datetime(2026, 11, 1, tzinfo=timezone.utc)),
}


def v(text, ids, kind="fact"):
    return verify_claim(Claim(id="x", text=text, kind=kind, evidence_ids=ids), EV, AS_OF)


def test_extract_numbers_precision():
    (val, tol, kind, raw), = extract_numbers("营收907.03亿元")
    assert kind == "amount" and val == Decimal("90703000000") and tol > Decimal("400000")
    assert extract_numbers("2026年第二季度，代码600519") == []


def test_number_rounding_matches_a_level():
    assert v("上半年营业收入907.03亿元，同比下降1.21%", ["a"]).status == "verified"
    assert v("营业收入约907亿元", ["a"]).status == "verified"


def test_wrong_number_disputed():
    out = v("上半年营业收入950.00亿元", ["a"])
    assert out.status == "disputed" and "复算" in out.verify_notes[0]


def test_percentage_point_difference():
    assert v("毛利率下降0.53个百分点", ["a"]).status == "verified"


def test_number_only_in_web_is_disputed():
    out = v("全年营业收入1688.38亿元", ["a", "b"])
    assert out.status == "disputed" and "网页" in out.verify_notes[0]


def test_c_level_cannot_support():
    assert v("行业见顶", ["c"], kind="inference").status == "rejected"


def test_future_evidence_rejected():
    assert v("某事实", ["f"]).status == "rejected"


def test_missing_evidence_rejected_and_unknown_ids_dropped():
    assert v("无依据的事实", []).status == "rejected"
    out = v("营业收入907.03亿元", ["a", "ghost"])
    assert out.status == "verified" and out.evidence_ids == ["a"]


def test_assumption_passes_but_is_labeled():
    out = v("假设下半年需求平稳", [], kind="assumption")
    assert out.status == "verified" and "不是事实" in out.verify_notes[0]


def test_calc_lineage_counts_as_support():
    calc = card("k", source_type="calc", derived_from=["a"],
                metrics=[Metric(name="净利率", field="NET_MARGIN", value=Decimal("49.08"), unit="%", period="2026-06-30", basis="ratio")])
    ev = {**EV, "k": calc}
    claim = Claim(id="x", text="营业收入907.03亿元，净利率49.08%", kind="fact", evidence_ids=["k"])
    assert verify_claim(claim, ev, AS_OF).status == "verified"
