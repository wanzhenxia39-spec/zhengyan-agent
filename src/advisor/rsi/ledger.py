"""RSI 账本（MongoDB）：资产、运行、事件、坏案例。

- 资产只追加：每版带 parent、change_reason（≥10 字）、内容 sha256；同 kind 同版本号唯一。
- 事件只追加：在用版本不单独存指针，而是由最近一次 bootstrap/release/rollback 事件推出，账本即真相。
- 运行记录的状态只能经 runner 推进，每次推进都写事件。
"""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from advisor.rsi.models import Asset, AssetKind, Issue, Run

ACTIVATING = ("bootstrap", "release", "rollback")


class LedgerError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def content_hash(content: Any) -> str:
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def baseline_content(kind: AssetKind, policy) -> dict:
    """从 policies.yaml 导入的 v1 基线。"""
    from advisor.experts.specs import EXPERTS
    if kind == "lessons":
        return {"cards": []}
    if kind == "routing":
        r = policy.routing
        return {"temperature": float(r.get("temperature", 1.0)), "abstain_below": float(r.get("abstain_below", 0.55))}
    s = policy.search
    return {"rerank_min": float(s.get("rerank_min", 1.5)), "authority_b_min": int(s.get("authority_b_min", 3)),
            "expert_hints": {k: e.query_hint for k, e in EXPERTS.items() if e.query_hint}}


class Ledger:
    def __init__(self, db: Database):
        self.db = db
        db.rsi_assets.create_index([("kind", ASCENDING), ("version", ASCENDING)], unique=True)
        db.rsi_runs.create_index("run_id", unique=True)
        db.rsi_events.create_index([("ts", ASCENDING)])
        db.rsi_issues.create_index("fingerprint", unique=True)
        db.rsi_issues.create_index("id", unique=True)

    # ---------- 资产 ----------
    def append_asset(self, kind: AssetKind, content: dict, change_reason: str, created_by: str,
                     parent_version: int | None, run_id: str | None = None) -> Asset:
        if len(change_reason.strip()) < 10:
            raise LedgerError("change_reason 不少于 10 个字")
        latest = self.latest_version(kind)
        if latest is not None and parent_version is None:
            raise LedgerError("非首版资产必须声明 parent")
        asset = Asset(kind=kind, version=(latest or 0) + 1, parent_version=parent_version, content=content,
                      sha256=content_hash(content), change_reason=change_reason, run_id=run_id,
                      created_by=created_by, created_at=_now())
        try:
            self.db.rsi_assets.insert_one(asset.model_dump(mode="json"))
        except DuplicateKeyError as e:
            raise LedgerError(f"{kind} v{asset.version} 已存在（并发发布？）") from e
        return asset

    def latest_version(self, kind: AssetKind) -> int | None:
        doc = self.db.rsi_assets.find_one({"kind": kind}, sort=[("version", DESCENDING)], projection={"version": 1})
        return doc["version"] if doc else None

    def get_asset(self, kind: AssetKind, version: int) -> Asset | None:
        doc = self.db.rsi_assets.find_one({"kind": kind, "version": version}, projection={"_id": 0})
        return Asset.model_validate(doc) if doc else None

    def list_assets(self, kind: AssetKind | None = None) -> list[Asset]:
        q = {"kind": kind} if kind else {}
        return [Asset.model_validate(d) for d in self.db.rsi_assets.find(q, projection={"_id": 0}).sort("version", ASCENDING)]

    def active_version(self, kind: AssetKind) -> int | None:
        doc = self.db.rsi_events.find_one({"kind": kind, "action": {"$in": list(ACTIVATING)}},
                                          sort=[("ts", DESCENDING), ("seq", DESCENDING)])
        return doc["active_version"] if doc else None

    def active_asset(self, kind: AssetKind) -> Asset | None:
        v = self.active_version(kind)
        return self.get_asset(kind, v) if v is not None else None

    def bootstrap(self, policy, actor: str = "system") -> list[str]:
        """为尚无资产的组件登记 v1 基线并启用。"""
        done = []
        for kind in ("lessons", "routing", "search"):
            if self.latest_version(kind) is None:
                a = self.append_asset(kind, baseline_content(kind, policy), "初始基线：由 policies.yaml 导入的在用配置", actor, None)
                self.event("bootstrap", actor, kind=kind, active_version=a.version, detail=f"{kind} v1 基线启用")
                done.append(kind)
        return done

    # ---------- 事件 ----------
    def event(self, action: str, actor: str, **fields: Any) -> None:
        seq = self.db.rsi_events.count_documents({})
        self.db.rsi_events.insert_one({"action": action, "actor": actor, "ts": _now(), "seq": seq, **fields})

    def list_events(self, limit: int = 100, run_id: str | None = None) -> list[dict]:
        q = {"run_id": run_id} if run_id else {}
        cur = self.db.rsi_events.find(q, projection={"_id": 0}).sort([("ts", DESCENDING), ("seq", DESCENDING)]).limit(limit)
        return list(cur)

    # ---------- 坏案例 ----------
    def add_issue(self, issue: Issue) -> bool:
        try:
            self.db.rsi_issues.insert_one(issue.model_dump(mode="json"))
            return True
        except DuplicateKeyError:
            return False

    def list_issues(self, scenario: str | None = None, status: str | None = None) -> list[Issue]:
        q: dict = {}
        if scenario:
            q["scenario"] = scenario
        if status:
            q["status"] = status
        return [Issue.model_validate(d) for d in self.db.rsi_issues.find(q, projection={"_id": 0}).sort("created_at", ASCENDING)]

    def get_issues(self, ids: list[str]) -> list[Issue]:
        return [Issue.model_validate(d) for d in self.db.rsi_issues.find({"id": {"$in": ids}}, projection={"_id": 0})]

    def set_issue_status(self, ids: list[str], status: str) -> None:
        self.db.rsi_issues.update_many({"id": {"$in": ids}}, {"$set": {"status": status}})

    # ---------- 运行 ----------
    def insert_run(self, run: Run) -> None:
        self.db.rsi_runs.insert_one(run.model_dump(mode="json"))

    def save_run(self, run: Run) -> None:
        run.updated_at = _now()
        self.db.rsi_runs.replace_one({"run_id": run.run_id}, run.model_dump(mode="json"))

    def get_run(self, run_id: str) -> Run | None:
        doc = self.db.rsi_runs.find_one({"run_id": run_id}, projection={"_id": 0})
        return Run.model_validate(doc) if doc else None

    def list_runs(self, scenario: str | None = None, limit: int = 50) -> list[Run]:
        q = {"scenario": scenario} if scenario else {}
        cur = self.db.rsi_runs.find(q, projection={"_id": 0}).sort("created_at", DESCENDING).limit(limit)
        return [Run.model_validate(d) for d in cur]

    def tried_directions(self, scenario: str) -> dict[str, str]:
        """失败也记账：被拒绝或回滚的方向 → 原因。"""
        cur = self.db.rsi_runs.find({"scenario": scenario, "status": {"$in": ["rejected", "rolled_back"]}},
                                    projection={"direction": 1, "reject_reason": 1})
        return {d["direction"]: d.get("reject_reason") or "" for d in cur}

    def released_count(self, kind: AssetKind) -> int:
        return self.db.rsi_runs.count_documents({"kind": kind, "status": {"$in": ["released", "archived"]}})
