"""个人情境官：把档案结论对照「用户确认过的约束」。

依赖链：用户约束（购买理由、可承受回撤、资金期限）→ 相关主张 → 证据。
纯规则、本地执行：个人信息不进提示词、不出域；没确认过的约束一律标「未知」，不猜。
"""
from advisor.contracts import Dossier, EvidenceCard
from advisor.evidence import fact_value, metric_facts
from advisor.personal.models import FitCheck, PersonalFit, ProfileVersion

RELATED_MIN = 0.25          # 主张与购买理由的字面重合度阈值
SHORT_HORIZON_MONTHS = 6
HIGH_VOL_PCT = 30


def _bigrams(text: str) -> set[str]:
    s = "".join(ch for ch in text if not ch.isspace() and ch not in "，。、；：（）()%,.;:")
    return {s[i:i + 2] for i in range(len(s) - 1)}


def related(thesis: str, text: str) -> float:
    """购买理由有多少被这条主张覆盖（字二元组召回率）。"""
    t = _bigrams(thesis)
    return len(t & _bigrams(text)) / len(t) if t else 0.0


def _thesis(d: Dossier, profile: ProfileVersion | None) -> FitCheck:
    holding = profile.holding(d.ticker) if profile else None
    if not holding:
        return FitCheck(key="thesis", label="购买理由", status="unknown",
                        detail="你还没有确认这只股票的购买理由，情境官不替你猜。")
    claims = [c for c in d.claims if related(holding.thesis, c.text) >= RELATED_MIN]
    support = [c for c in claims if c.status == "verified"]
    against = [c for c in claims if c.status in ("disputed", "rejected")]
    weakened = [p for p in d.prior_review if p.verdict in ("weakened", "invalidated")
                and related(holding.thesis, p.prior_claim) >= RELATED_MIN]
    refs = [c.id for c in support + against]
    if (against or weakened) and not support:
        return FitCheck(key="thesis", label="购买理由", status="conflict", refs=refs,
                        detail=f"与「{holding.thesis}」相关的结论被质疑或削弱 {len(against) + len(weakened)} 条，没有已核验的支持。")
    if against or weakened:
        return FitCheck(key="thesis", label="购买理由", status="attention", refs=refs,
                        detail=f"有 {len(support)} 条已核验主张支持，但也有 {len(against) + len(weakened)} 条被质疑或削弱。")
    if support:
        return FitCheck(key="thesis", label="购买理由", status="ok", refs=refs,
                        detail=f"{len(support)} 条已核验主张与你的购买理由相关，暂未见反证。")
    return FitCheck(key="thesis", label="购买理由", status="unknown",
                    detail=f"这版档案没有覆盖你的购买理由「{holding.thesis}」，可以让顾问专门复核。")


def _drawdown(facts, profile: ProfileVersion | None) -> FitCheck:
    tol = profile.risk.max_drawdown_pct if profile else None
    mdd = fact_value(facts, "mdd_250d")
    if tol is None:
        return FitCheck(key="drawdown", label="波动承受", status="unknown", detail="你还没有确认可承受的最大回撤。")
    if mdd is None:
        return FitCheck(key="drawdown", label="波动承受", status="unknown", detail="档案里没有近 250 日回撤数据。")
    seen = abs(float(mdd))
    if seen > tol:
        status, word = "conflict", "超出"
    elif seen > tol * 0.8:
        status, word = "attention", "接近"
    else:
        status, word = "ok", "在"
    return FitCheck(key="drawdown", label="波动承受", status=status,
                    detail=f"近 250 日最大回撤 {seen:.1f}%，{word}你确认的可承受回撤 {tol:g}%{'以内' if status == 'ok' else ''}。")


def _horizon(d: Dossier, facts, profile: ProfileVersion | None) -> FitCheck:
    holding = profile.holding(d.ticker) if profile else None
    months = (holding.horizon_months if holding else None) or (profile.risk.horizon_months if profile else None)
    if months is None:
        return FitCheck(key="horizon", label="资金期限", status="unknown", detail="你还没有确认这笔钱可以投多久。")
    vol = fact_value(facts, "vol_60d")
    note = f"；{profile.risk.liquidity_note}" if profile and profile.risk.liquidity_note else ""
    if months < SHORT_HORIZON_MONTHS:
        return FitCheck(key="horizon", label="资金期限", status="attention",
                        detail=f"{months} 个月内要用的钱，短期波动可能直接影响{note}。")
    if months < 12 and vol is not None and float(vol) >= HIGH_VOL_PCT:
        return FitCheck(key="horizon", label="资金期限", status="attention",
                        detail=f"期限 {months} 个月，而近 60 日年化波动率 {float(vol):.0f}%，偏高{note}。")
    return FitCheck(key="horizon", label="资金期限", status="ok", detail=f"期限 {months} 个月，与档案的复核节奏相容{note}。")


def _evidence(d: Dossier) -> FitCheck:
    unresolved = [x.text for x in d.dissents]
    if d.status == "partial" or d.unknowns:
        return FitCheck(key="evidence", label="结论完整度", status="attention",
                        detail=f"档案是部分结论：未知 {len(d.unknowns)} 项、保留分歧 {len(unresolved)} 条，按你的约束需要更多确认。")
    return FitCheck(key="evidence", label="结论完整度", status="ok", detail="档案已通过质量门控。")


def _freshness(subscribed: bool, open_alerts: list[tuple[str, str]]) -> FitCheck:
    if open_alerts:
        return FitCheck(key="freshness", label="待复核", status="attention", refs=[a for a, _ in open_alerts],
                        detail="订阅发现新变化：" + "；".join(t for _, t in open_alerts[:3]))
    if subscribed:
        return FitCheck(key="freshness", label="待复核", status="ok", detail="订阅最近一次扫描未发现影响结论的变化。")
    return FitCheck(key="freshness", label="待复核", status="unknown", detail="还没订阅这只股票，新财报和公告不会自动提醒。")


def assess(d: Dossier, evidence: list[EvidenceCard], profile: ProfileVersion | None,
           subscribed: bool = False, open_alerts: list[tuple[str, str]] | None = None) -> PersonalFit:
    facts = metric_facts(evidence)
    checks = [_thesis(d, profile), _drawdown(facts, profile), _horizon(d, facts, profile), _evidence(d),
              _freshness(subscribed, open_alerts or [])]
    n = {s: sum(c.status == s for c in checks) for s in ("conflict", "attention", "unknown")}
    summary = ("与你确认的约束有冲突，建议先复核再做决定" if n["conflict"] else
               "大体相容，但有需要留意的地方" if n["attention"] else
               "缺少你的确认，情境官无法判断" if n["unknown"] == len(checks) else "与你确认的约束相容")
    return PersonalFit(ticker=d.ticker, dossier_version=d.version, profile_version=profile.version if profile else None,
                       checks=checks, summary=summary)


def profile_impact(d: Dossier, evidence: list[EvidenceCard], old: ProfileVersion | None, new: ProfileVersion,
                   subscribed: bool = False, open_alerts: list[tuple[str, str]] | None = None) -> dict | None:
    """约束改了以后，同一份档案的个人情境结论哪里变了。只看结论状态的变化；购买理由改了也算。
    依赖链：用户约束 → 个人情境结论。档案里的研究结论不依赖你的约束，不需要重新研究。"""
    before = assess(d, evidence, old, subscribed, open_alerts)
    after = assess(d, evidence, new, subscribed, open_alerts)
    changes = []
    for b, a in zip(before.checks, after.checks):
        thesis_edit = a.key == "thesis" and b.detail != a.detail
        if b.status != a.status or thesis_edit:
            changes.append({"key": a.key, "label": a.label, "before": b.status, "after": a.status, "detail": a.detail})
    if not changes:
        return None
    return {"ticker": d.ticker, "name": d.name, "dossier_version": d.version,
            "before": before.summary, "after": after.summary, "changes": changes}
