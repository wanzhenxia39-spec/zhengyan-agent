"""订阅与提醒的存储。提醒按指纹去重：同一批变化只提醒一次。"""
from datetime import datetime, timezone

from pymongo import DESCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from advisor.watch.models import Alert, Subscription


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WatchStore:
    def __init__(self, db: Database):
        self.subs = db.watch_subscriptions
        self.alerts = db.watch_alerts
        self.subs.create_index("ticker", unique=True)
        self.alerts.create_index("id", unique=True)
        self.alerts.create_index("fingerprint", unique=True)

    # ---------- 订阅 ----------
    def subscribe(self, ticker: str, name: str = "", price_move_pct: float = 10) -> Subscription:
        existing = self.get_sub(ticker)
        sub = Subscription(ticker=ticker, name=name or (existing.name if existing else ""), price_move_pct=price_move_pct,
                           created_at=existing.created_at if existing else _now(),
                           last_scan_at=existing.last_scan_at if existing else None,
                           last_scan_note=existing.last_scan_note if existing else "")
        self.subs.update_one({"ticker": ticker}, {"$set": sub.model_dump(mode="json")}, upsert=True)
        return sub

    def unsubscribe(self, ticker: str) -> None:
        self.subs.update_one({"ticker": ticker}, {"$set": {"active": False}})

    def get_sub(self, ticker: str) -> Subscription | None:
        doc = self.subs.find_one({"ticker": ticker}, projection={"_id": 0})
        return Subscription.model_validate(doc) if doc else None

    def list_subs(self, active_only: bool = True) -> list[Subscription]:
        q = {"active": True} if active_only else {}
        return [Subscription.model_validate(d) for d in self.subs.find(q, projection={"_id": 0}).sort("ticker", 1)]

    def mark_scanned(self, ticker: str, note: str) -> None:
        self.subs.update_one({"ticker": ticker}, {"$set": {"last_scan_at": _now().isoformat(), "last_scan_note": note}})

    # ---------- 提醒 ----------
    def add_alert(self, alert: Alert) -> tuple[Alert, bool]:
        """返回 (提醒, 是否新建)。指纹相同说明这批变化已经提醒过。"""
        try:
            self.alerts.insert_one(alert.model_dump(mode="json"))
            return alert, True
        except DuplicateKeyError:
            doc = self.alerts.find_one({"fingerprint": alert.fingerprint}, projection={"_id": 0})
            return Alert.model_validate(doc), False

    def get_alert(self, alert_id: str) -> Alert | None:
        doc = self.alerts.find_one({"id": alert_id}, projection={"_id": 0})
        return Alert.model_validate(doc) if doc else None

    def list_alerts(self, ticker: str | None = None, status: str | None = None, limit: int = 100) -> list[Alert]:
        q = {k: v for k, v in (("ticker", ticker), ("status", status)) if v}
        cur = self.alerts.find(q, projection={"_id": 0}).sort("created_at", DESCENDING).limit(limit)
        return [Alert.model_validate(d) for d in cur]

    def update_alert(self, alert_id: str, **fields) -> None:
        self.alerts.update_one({"id": alert_id}, {"$set": fields})
