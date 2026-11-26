"""策略卡、模拟成交与净值的存储。版本只追加；成交与净值只追加；状态变化写事件。"""
import hashlib
import json
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

from advisor.strategy.models import NavPoint, PaperTrade, StrategySpec, StrategyVersion


def _now() -> datetime:
    return datetime.now(timezone.utc)


def spec_hash(spec: StrategySpec) -> str:
    raw = json.dumps(StrategySpec.model_validate(spec.model_dump()).model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class StrategyStore:
    def __init__(self, db: Database):
        self.cards = db.strategy_cards
        self.trades = db.paper_trades
        self.navs = db.paper_navs
        self.events = db.strategy_events
        self.cards.create_index([("card_id", ASCENDING), ("version", ASCENDING)], unique=True)
        self.navs.create_index([("card_id", ASCENDING), ("version", ASCENDING), ("date", ASCENDING)], unique=True)
        self.trades.create_index([("card_id", ASCENDING), ("version", ASCENDING), ("date", ASCENDING)])

    # ---------- 版本 ----------
    def next_card_id(self) -> str:
        ids = self.cards.distinct("card_id")
        return f"SC-{len(ids) + 1:03d}"

    def insert(self, v: StrategyVersion) -> None:
        self.cards.insert_one(v.model_dump(mode="json"))

    def save(self, v: StrategyVersion) -> None:
        """只更新状态类字段；规则内容由 sha256 锁定，不能原地修改。"""
        fields = v.model_dump(mode="json", include={"status", "paper_start", "gates", "approvals", "reject_reason"})
        self.cards.update_one({"card_id": v.card_id, "version": v.version, "sha256": v.sha256}, {"$set": fields})

    def get(self, card_id: str, version: int | None = None) -> StrategyVersion | None:
        q: dict = {"card_id": card_id} | ({"version": version} if version is not None else {})
        doc = self.cards.find_one(q, sort=[("version", DESCENDING)], projection={"_id": 0})
        return StrategyVersion.model_validate(doc) if doc else None

    def versions(self, card_id: str | None = None, status: list[str] | None = None) -> list[StrategyVersion]:
        q: dict = {}
        if card_id:
            q["card_id"] = card_id
        if status:
            q["status"] = {"$in": status}
        cur = self.cards.find(q, projection={"_id": 0}).sort([("card_id", ASCENDING), ("version", DESCENDING)])
        return [StrategyVersion.model_validate(d) for d in cur]

    # ---------- 模拟盘 ----------
    def add_trades(self, trades: list[PaperTrade]) -> None:
        if trades:
            self.trades.insert_many([t.model_dump(mode="json") for t in trades])

    def list_trades(self, card_id: str, version: int) -> list[PaperTrade]:
        cur = self.trades.find({"card_id": card_id, "version": version}, projection={"_id": 0}).sort("date", ASCENDING)
        return [PaperTrade.model_validate(d) for d in cur]

    def add_nav(self, p: NavPoint) -> None:
        self.navs.insert_one(p.model_dump(mode="json"))

    def navs_of(self, card_id: str, version: int) -> list[NavPoint]:
        cur = self.navs.find({"card_id": card_id, "version": version}, projection={"_id": 0}).sort("date", ASCENDING)
        return [NavPoint.model_validate(d) for d in cur]

    # ---------- 事件 ----------
    def event(self, action: str, actor: str, card_id: str, version: int, detail: str, **extra) -> None:
        self.events.insert_one({"ts": _now(), "action": action, "actor": actor, "card_id": card_id, "version": version,
                                "detail": detail, **extra})

    def list_events(self, card_id: str | None = None, limit: int = 100) -> list[dict]:
        q = {"card_id": card_id} if card_id else {}
        return list(self.events.find(q, projection={"_id": 0}).sort("ts", DESCENDING).limit(limit))
