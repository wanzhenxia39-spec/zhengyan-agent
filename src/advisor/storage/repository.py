"""MongoDB 存储：档案（版本链）、证据（只插入）、快照、审计、任务、缓存。"""
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from advisor.contracts import Dossier, EvidenceCard


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean(doc: dict | None) -> dict | None:
    if doc is not None:
        doc.pop("_id", None)
    return doc


class Repository:
    def __init__(self, db: Database):
        self.db = db

    @classmethod
    def connect(cls, uri: str, db_name: str) -> "Repository":
        client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
        repo = cls(client[db_name])
        repo.ensure_indexes()
        return repo

    def ensure_indexes(self) -> None:
        self.db.evidence.create_index("id", unique=True)
        self.db.snapshots.create_index("hash", unique=True)
        self.db.dossiers.create_index([("key", ASCENDING), ("version", DESCENDING)], unique=True)
        self.db.tasks.create_index("task_id", unique=True)
        self.db.audit.create_index([("task_id", ASCENDING), ("ts", ASCENDING)])
        self.db.cache.create_index("key", unique=True)
        self.db.working_memory.create_index([("task_id", ASCENDING), ("created_at", ASCENDING)])
        self.db.working_memory.create_index("expires_at", expireAfterSeconds=0)   # 研究记忆到期自动清理
        self.db.eval_runs.create_index("run_id", unique=True)

    def ping(self) -> bool:
        self.db.command("ping")
        return True

    # ---------- 证据：插入后不可变 ----------
    def put_snapshot(self, digest: str, content: str) -> None:
        try:
            self.db.snapshots.insert_one({"hash": digest, "content": content, "created_at": _now()})
        except DuplicateKeyError:
            pass

    def get_snapshot(self, digest: str) -> str | None:
        doc = self.db.snapshots.find_one({"hash": digest})
        return doc["content"] if doc else None

    def put_evidence(self, card: EvidenceCard) -> None:
        try:
            self.db.evidence.insert_one(card.model_dump(mode="json"))
        except DuplicateKeyError:
            pass  # 同 id 即同内容（id 由内容哈希决定）

    def get_evidence(self, ids: list[str]) -> list[EvidenceCard]:
        docs = self.db.evidence.find({"id": {"$in": ids}})
        return [EvidenceCard.model_validate(_clean(d)) for d in docs]

    # ---------- 档案：版本链，不覆盖 ----------
    def latest_dossier_version(self, key: str) -> int | None:
        doc = self.db.dossiers.find_one({"key": key}, sort=[("version", DESCENDING)], projection={"version": 1})
        return doc["version"] if doc else None

    def insert_dossier(self, dossier: Dossier) -> None:
        self.db.dossiers.insert_one(dossier.model_dump(mode="json"))

    def get_dossier(self, key: str, version: int | None = None) -> Dossier | None:
        query: dict[str, Any] = {"key": key}
        if version is not None:
            query["version"] = version
        doc = self.db.dossiers.find_one(query, sort=[("version", DESCENDING)])
        return Dossier.model_validate(_clean(doc)) if doc else None

    def list_dossier_versions(self, key: str) -> list[dict]:
        cur = self.db.dossiers.find(
            {"key": key},
            projection={"_id": 0, "key": 1, "version": 1, "status": 1, "as_of": 1, "question": 1, "created_at": 1, "task_id": 1},
        ).sort("version", DESCENDING)
        return list(cur)

    def list_dossiers(self) -> list[dict]:
        pipeline = [
            {"$match": {"key": {"$not": {"$regex": ":"}}}},     # 评测等命名空间档案不进用户列表
            {"$sort": {"version": -1}},
            {"$group": {
                "_id": "$key",
                "key": {"$first": "$key"}, "ticker": {"$first": "$ticker"}, "name": {"$first": "$name"},
                "version": {"$first": "$version"}, "status": {"$first": "$status"},
                "as_of": {"$first": "$as_of"}, "summary": {"$first": "$summary"},
                "created_at": {"$first": "$created_at"},
            }},
            {"$sort": {"created_at": -1}},
            {"$project": {"_id": 0}},
        ]
        return list(self.db.dossiers.aggregate(pipeline))

    # ---------- 任务 ----------
    def create_task(self, task_id: str, request: dict) -> None:
        self.db.tasks.insert_one({
            "task_id": task_id, "request": request, "status": "queued", "events": [],
            "interrupt": None, "result": None, "error": None, "created_at": _now(), "updated_at": _now(),
        })

    def update_task(self, task_id: str, **fields: Any) -> None:
        fields["updated_at"] = _now()
        self.db.tasks.update_one({"task_id": task_id}, {"$set": fields})

    def push_event(self, task_id: str, node: str, message: str) -> None:
        self.db.tasks.update_one(
            {"task_id": task_id},
            {"$push": {"events": {"ts": _now(), "node": node, "message": message}}, "$set": {"updated_at": _now()}},
        )

    def request_cancel(self, task_id: str) -> str | None:
        """撤销授权/取消：等待确认的任务立即取消；运行中的任务在下一个检查点停止。"""
        task = self.get_task(task_id)
        if not task or task["status"] not in ("queued", "running", "waiting_approval"):
            return None
        status = "cancelled" if task["status"] == "waiting_approval" else task["status"]
        self.db.tasks.update_one({"task_id": task_id}, {"$set": {"cancel_requested": True, "status": status, "updated_at": _now()}})
        return status

    def is_cancel_requested(self, task_id: str) -> bool:
        doc = self.db.tasks.find_one({"task_id": task_id}, projection={"cancel_requested": 1})
        return bool(doc and doc.get("cancel_requested"))

    def get_task(self, task_id: str) -> dict | None:
        return _clean(self.db.tasks.find_one({"task_id": task_id}))

    def list_tasks(self, limit: int = 30) -> list[dict]:
        cur = self.db.tasks.find({}, projection={"_id": 0, "events": 0}).sort("created_at", DESCENDING).limit(limit)
        return list(cur)

    # ---------- 工作记忆（研究记忆：计划、专家产出、质询；到期清理） ----------
    def save_working(self, task_id: str, kind: str, key: str, data: Any, ttl_days: float = 30) -> None:
        self.db.working_memory.update_one(
            {"task_id": task_id, "kind": kind, "key": key},
            {"$set": {"data": data, "created_at": _now(), "expires_at": _now() + timedelta(days=ttl_days)}},
            upsert=True,
        )

    def list_working(self, task_id: str) -> list[dict]:
        cur = self.db.working_memory.find({"task_id": task_id}, projection={"_id": 0}).sort("created_at", ASCENDING)
        return list(cur)

    # ---------- 评测 ----------
    def save_eval(self, run: dict) -> None:
        self.db.eval_runs.update_one({"run_id": run["run_id"]}, {"$set": {**run, "updated_at": _now()}}, upsert=True)

    def list_evals(self, limit: int = 20) -> list[dict]:
        return list(self.db.eval_runs.find({}, projection={"_id": 0}).sort("created_at", DESCENDING).limit(limit))

    def get_eval(self, run_id: str) -> dict | None:
        return _clean(self.db.eval_runs.find_one({"run_id": run_id}))

    # ---------- 审计 ----------
    def append_audit(self, record: dict) -> None:
        self.db.audit.insert_one({**record, "ts": _now()})

    def list_audit(self, task_id: str) -> list[dict]:
        return [_clean(d) for d in self.db.audit.find({"task_id": task_id}).sort("ts", ASCENDING)]

    # ---------- 缓存 ----------
    def cache_get(self, key: str) -> Any | None:
        doc = self.db.cache.find_one({"key": key})
        if not doc:
            return None
        expires = doc["expires_at"]
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return doc["value"] if expires > _now() else None

    def cache_set(self, key: str, value: Any, ttl_hours: float) -> None:
        self.db.cache.update_one(
            {"key": key},
            {"$set": {"value": value, "expires_at": _now() + timedelta(hours=ttl_hours)}},
            upsert=True,
        )
