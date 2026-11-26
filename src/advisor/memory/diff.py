"""版本差异与依赖传播：新版本不覆盖旧版本，而是先展示变化与影响。

依赖图用显式关系实现：主张 → 证据 → 报告期。最新报告期前移后，依赖旧报告期的旧结论标记"待复核"。
"""
from difflib import SequenceMatcher

from advisor.contracts import Dossier, EvidenceCard
from advisor.evidence.facts import report_periods


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _calc_metrics(d: Dossier, ev: dict[str, EvidenceCard]) -> dict[str, dict]:
    out = {}
    for i in d.evidence_ids:
        card = ev.get(i)
        if card and card.source_type in ("calc", "market"):
            for m in card.metrics:
                out[m.name] = {"value": str(m.value), "unit": m.unit, "period": m.period[:10], "basis": m.basis}
    return out


def diff_dossiers(new: Dossier, old: Dossier, ev: dict[str, EvidenceCard]) -> dict:
    om, nm = _calc_metrics(old, ev), _calc_metrics(new, ev)
    metrics = [
        {"name": k, "old": om.get(k), "new": nm.get(k),
         "changed": (om.get(k) or {}).get("value") != (nm.get(k) or {}).get("value")}
        for k in dict.fromkeys(list(nm) + list(om))
    ]
    old_ok = [c for c in old.claims if c.status == "verified"]
    new_ok = [c for c in new.claims if c.status == "verified"]
    matched, kept = set(), []
    for c in new_ok:
        best = max(old_ok, key=lambda o: _similar(o.text, c.text), default=None)
        if best is not None and _similar(best.text, c.text) >= 0.6:
            matched.add(best.id)
            kept.append({"old": best.text, "new": c.text, "similarity": round(_similar(best.text, c.text), 2)})
    added = [c.text for c in new_ok if not any(k["new"] == c.text for k in kept)]
    removed = [c.text for c in old_ok if c.id not in matched]

    latest_new = max(report_periods([i for i in new.evidence_ids], ev), default="")
    stale = []
    for c in old_ok:
        periods = report_periods(c.evidence_ids, ev)
        if periods and latest_new and max(periods) < latest_new:
            stale.append({"text": c.text, "reason": f"依赖的报告期 {max(periods)} 已被 {latest_new} 取代，需复核"})

    old_ids = set(old.evidence_ids)
    evidence_added = [
        {"id": c.id, "title": c.title, "level": c.level, "source_type": c.source_type,
         "date": c.published_at.date().isoformat() if c.published_at else None}
        for i in new.evidence_ids if i not in old_ids and (c := ev.get(i)) and c.source_type in ("filing", "announcement", "web")
        and (c.published_at is None or c.published_at.date() > old.as_of)
    ]
    return {
        "from_version": old.version, "to_version": new.version,
        "as_of": {"old": old.as_of.isoformat(), "new": new.as_of.isoformat()},
        "route": {"old": old.route, "new": new.route},
        "status": {"old": old.status, "new": new.status},
        "metrics": metrics,
        "claims": {"kept": kept, "added": added, "removed": removed},
        "stale_claims": stale,
        "evidence_added": evidence_added,
        "unknowns": {"resolved": [u for u in old.unknowns if u not in new.unknowns],
                     "new": [u for u in new.unknowns if u not in old.unknowns]},
        "triggers": {"old": [t.condition for t in old.review_triggers], "new": [t.condition for t in new.review_triggers]},
        "prior_review": [p.model_dump(mode="json") for p in new.prior_review],
    }
