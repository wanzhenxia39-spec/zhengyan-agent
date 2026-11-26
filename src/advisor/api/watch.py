"""三期：事件订阅与增量复核。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from advisor.api.common import Jobs, Svc, conflict_on
from advisor.watch import WatchError

router = APIRouter(prefix="/api/watch")


class SubscribeIn(BaseModel):
    ticker: str = Field(pattern=r"^\d{6}$")
    price_move_pct: float | None = Field(default=None, gt=0, le=100)


class DismissIn(BaseModel):
    note: str = Field(min_length=2, max_length=200)


@router.get("")
def overview(svc: Svc):
    svc.watch.sync()
    store = svc.watch.store
    return {"subscriptions": [s.model_dump(mode="json") for s in store.list_subs(active_only=False)],
            "alerts": [a.model_dump(mode="json") for a in store.list_alerts()],
            "interval_hours": svc.deps.policy.watch.get("scan_interval_hours", 0)}


@router.post("/subscriptions")
def subscribe(body: SubscribeIn, svc: Svc):
    d = svc.deps.repo.get_dossier(body.ticker)
    if d is None:
        raise HTTPException(409, "还没有这只股票的档案，先做一次研究再订阅")
    pct = body.price_move_pct or float(svc.deps.policy.watch.get("default_price_move_pct", 10))
    return svc.watch.store.subscribe(body.ticker, d.name, pct).model_dump(mode="json")


@router.delete("/subscriptions/{ticker}")
def unsubscribe(ticker: str, svc: Svc):
    svc.watch.store.unsubscribe(ticker)
    return {"ok": True}


@router.post("/scan")
def scan_all(svc: Svc, jobs: Jobs):
    return jobs.start(svc, "watch_scan", lambda log: [a.id for a in svc.watch.scan_all(log=log)])


@router.post("/scan/{ticker}")
def scan_one(ticker: str, svc: Svc):
    with conflict_on(WatchError):
        alert = svc.watch.scan(ticker)
    return {"alert": alert.model_dump(mode="json") if alert else None}


@router.post("/alerts/{alert_id}/review")
def review(alert_id: str, svc: Svc):
    """带着受影响的旧结论发起增量复核（标准研究，生成新版本）。"""
    from advisor.llm import LLMNotConfigured
    with conflict_on(WatchError, LLMNotConfigured):
        return {"task_id": svc.watch.start_review(alert_id, svc.research)}


@router.post("/alerts/{alert_id}/dismiss")
def dismiss(alert_id: str, body: DismissIn, svc: Svc):
    if svc.watch.store.get_alert(alert_id) is None:
        raise HTTPException(404, "提醒不存在")
    svc.watch.dismiss(alert_id, body.note)
    return {"ok": True}
