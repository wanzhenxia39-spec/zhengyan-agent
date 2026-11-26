"""决策档案：列表、版本、证据、版本差异、底稿、证据快照，以及研究台的行情快照。"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from advisor.api.common import Svc
from advisor.contracts import Dossier
from advisor.evidence import metric_facts

router = APIRouter(prefix="/api")


def all_evidence_ids(d: Dossier) -> list[str]:
    ids = set(d.evidence_ids) | {i for c in d.claims for i in c.evidence_ids}
    dl = d.deliberation or {}
    for t in dl.get("team", []):
        ids |= set(t.get("own_evidence_ids", [])) | {i for c in t.get("claims", []) for i in c.get("evidence_ids", [])}
    for ch in dl.get("challenges", []):
        ids |= set(ch.get("evidence_ids", []))
    return sorted(ids)


def _dossier(svc: Svc, key: str, version: int | None = None) -> Dossier:
    d = svc.deps.repo.get_dossier(key, version)
    if not d:
        raise HTTPException(404, "档案不存在")
    return d


@router.get("/dossiers")
def dossiers(svc: Svc):
    return svc.deps.repo.list_dossiers()


@router.get("/watchlist")
def watchlist(svc: Svc):
    """档案标的的最近行情/估值快照（A 级证据，截至研究时点，不是实时行情），附订阅与待复核状态。"""
    repo, out = svc.deps.repo, []
    for d in repo.list_dossiers():
        full = repo.get_dossier(d["key"])
        facts = metric_facts(repo.get_evidence(full.evidence_ids if full else []))
        quote = {k: {"value": m.value, "unit": m.unit, "period": m.period}
                 for k, m in facts.items() if k in ("close", "chg_20d", "pe_ttm", "pe_pct")}
        sub = svc.watch.store.get_sub(d["key"])
        out.append(d | {"quote": quote, "route": full.route if full else None,
                        "rsi_versions": full.rsi_versions if full else {},
                        "subscribed": bool(sub and sub.active), "open_alerts": svc.open_alert_count(d["key"])})
    return out


@router.get("/dossiers/{key}/versions")
def versions(key: str, svc: Svc):
    return svc.deps.repo.list_dossier_versions(key)


@router.get("/dossiers/{key}/{version}")
def dossier(key: str, version: int, svc: Svc):
    d = _dossier(svc, key, version)
    evidence = svc.deps.repo.get_evidence(all_evidence_ids(d))
    return {"dossier": d.model_dump(mode="json"), "evidence": [e.model_dump(mode="json") for e in evidence]}


@router.get("/dossiers/{key}/{version}/diff")
def diff(key: str, version: int, svc: Svc):
    from advisor.memory import diff_dossiers
    new = _dossier(svc, key, version)
    if new.parent_version is None:
        raise HTTPException(404, "没有上一版本")
    old = _dossier(svc, key, new.parent_version)
    ids = sorted(set(all_evidence_ids(new)) | set(all_evidence_ids(old)))
    return diff_dossiers(new, old, {c.id: c for c in svc.deps.repo.get_evidence(ids)})


@router.get("/dossiers/{key}/{version}/markdown", response_class=PlainTextResponse)
def markdown(key: str, version: int, svc: Svc):
    return _dossier(svc, key, version).report_md


@router.get("/evidence/{evidence_id}/snapshot", response_class=PlainTextResponse)
def snapshot(evidence_id: str, svc: Svc):
    cards = svc.deps.repo.get_evidence([evidence_id])
    if not cards:
        raise HTTPException(404, "证据不存在")
    return svc.deps.repo.get_snapshot(cards[0].snapshot_hash) or ""
