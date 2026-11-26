"""四期：策略卡与前向模拟盘（只模拟，不交易）。"""
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from advisor.api.common import OWNER, Jobs, Svc, conflict_on
from advisor.strategy import FIELDS, STATUS_LABEL, PaperError, StrategyError, StrategySpec

router = APIRouter(prefix="/api/strategy")


class CreateIn(StrategySpec):
    change_reason: str = Field(min_length=10)
    card_id: str | None = None             # 有值 = 修订已有策略卡（追加新版本）


class NoteIn(BaseModel):
    note: str = ""


class ReasonIn(BaseModel):
    reason: str = Field(min_length=2)


def _summary(svc: Svc, v) -> dict:
    return v.model_dump(mode="json") | {"stats": svc.strategy.stats(v)}


@router.get("")
def overview(svc: Svc):
    versions = svc.strategy.store.versions()
    return {"cards": [_summary(svc, v) for v in versions], "fields": FIELDS, "status_label": STATUS_LABEL,
            "initial_cash": svc.strategy.paper.initial_cash, "gates_cfg": svc.deps.policy.strategy,
            "events": svc.strategy.store.list_events(limit=40)}


@router.post("")
def create(body: CreateIn, svc: Svc):
    with conflict_on(StrategyError):
        v = svc.strategy.create(StrategySpec.model_validate(body.model_dump()), OWNER, body.change_reason, body.card_id)
    return v.model_dump(mode="json")


@router.get("/{card_id}/{version}")
def detail(card_id: str, version: int, svc: Svc):
    v = svc.strategy.store.get(card_id, version)
    if v is None:
        raise HTTPException(404, "策略卡不存在")
    store = svc.strategy.store
    return {"card": _summary(svc, v), "navs": [p.model_dump(mode="json") for p in store.navs_of(card_id, version)],
            "trades": [t.model_dump(mode="json") for t in store.list_trades(card_id, version)],
            "versions": [{"version": x.version, "status": x.status, "change_reason": x.change_reason}
                         for x in store.versions(card_id)],
            "events": [e for e in store.list_events(card_id) if e["version"] == version]}


@router.post("/{card_id}/{version}/paper")
def start_paper(card_id: str, version: int, svc: Svc):
    with conflict_on(StrategyError):
        return svc.strategy.start_paper(card_id, version, OWNER).model_dump(mode="json")


@router.post("/step")
def step(svc: Svc, jobs: Jobs, day: date | None = None):
    """把所有模拟中的策略推进到今天（只能向前）。"""
    return jobs.start(svc, "paper_step", lambda log: len(svc.strategy.step_all(day, log)))


@router.post("/{card_id}/{version}/submit")
def submit(card_id: str, version: int, svc: Svc):
    with conflict_on(StrategyError, PaperError):
        return svc.strategy.submit(card_id, version, OWNER).model_dump(mode="json")


@router.post("/{card_id}/{version}/approve")
def approve(card_id: str, version: int, body: NoteIn, svc: Svc):
    with conflict_on(StrategyError):
        return svc.strategy.approve(card_id, version, OWNER, body.note).model_dump(mode="json")


@router.post("/{card_id}/{version}/reject")
def reject(card_id: str, version: int, body: ReasonIn, svc: Svc):
    with conflict_on(StrategyError):
        return svc.strategy.reject(card_id, version, OWNER, body.reason).model_dump(mode="json")


@router.post("/{card_id}/rollback")
def rollback(card_id: str, body: ReasonIn, svc: Svc):
    with conflict_on(StrategyError):
        return svc.strategy.rollback(card_id, OWNER, body.reason).model_dump(mode="json")
