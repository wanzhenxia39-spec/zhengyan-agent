"""从证据卡里取「最新时点值」：行情、估值、派生指标按字段名汇总。供订阅扫描、个人情境官、模拟盘共用。"""
from decimal import Decimal

from advisor.contracts import EvidenceCard, Metric

POINT_SOURCES = ("market", "calc")


def metric_facts(cards: list[EvidenceCard]) -> dict[str, Metric]:
    """字段 → 指标。同一字段取时点最新的一条；只看行情与计算卡（财报原始数按报告期另行处理）。"""
    out: dict[str, Metric] = {}
    for card in cards:
        if card.source_type not in POINT_SOURCES:
            continue
        for m in card.metrics:
            if m.field not in out or m.period >= out[m.field].period:
                out[m.field] = m
    return out


def fact_value(facts: dict[str, Metric], field: str) -> Decimal | None:
    m = facts.get(field)
    return m.value if m else None


def report_periods(ids: list[str], evidence: dict[str, EvidenceCard]) -> set[str]:
    """报告期：只取财报与由财报派生的计算卡（估值/行情卡的日期是交易日，不是报告期）。"""
    return {m.period[:10] for i in ids if (c := evidence.get(i))
            and (c.source_type == "filing" or (c.source_type == "calc" and c.origin_id.startswith("calc:")))
            for m in c.metrics}
