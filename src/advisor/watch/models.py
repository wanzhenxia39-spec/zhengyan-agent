"""三期：事件订阅与增量复核。前提变化时提醒，并指出受影响的旧结论；没有变化就不打扰。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EventKind = Literal["new_report", "announcement", "price_move", "trigger"]
AlertStatus = Literal["open", "reviewing", "resolved", "dismissed"]


class Subscription(BaseModel):
    ticker: str = Field(pattern=r"^\d{6}$")
    name: str = ""
    price_move_pct: float = Field(default=10, gt=0, le=100)     # 相对档案时点的涨跌幅提醒阈值
    active: bool = True
    created_at: datetime
    last_scan_at: datetime | None = None
    last_scan_note: str = ""


class WatchEvent(BaseModel):
    kind: EventKind
    title: str
    detail: str = ""
    date: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class AffectedClaim(BaseModel):
    claim_id: str
    text: str
    reason: str


class Alert(BaseModel):
    id: str
    ticker: str
    name: str = ""
    dossier_key: str
    dossier_version: int
    fingerprint: str
    events: list[WatchEvent]
    affected: list[AffectedClaim] = Field(default_factory=list)
    status: AlertStatus = "open"
    created_at: datetime
    review_task_id: str | None = None
    resolved_version: int | None = None
    note: str = ""


EVENT_LABEL = {"new_report": "新财报", "announcement": "新公告", "price_move": "价格异动", "trigger": "复核条件触发"}
