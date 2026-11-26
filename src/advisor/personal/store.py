"""用户确认档案的存储：只追加版本。研究流程没有写入入口，只有用户确认这一条路径。"""
from datetime import datetime, timezone

from pymongo import DESCENDING
from pymongo.database import Database

from advisor.personal.models import ProfileInput, ProfileVersion


class ProfileError(ValueError):
    pass


class ProfileStore:
    def __init__(self, db: Database):
        self.col = db.profiles
        self.col.create_index("version", unique=True)

    def current(self) -> ProfileVersion | None:
        doc = self.col.find_one({}, sort=[("version", DESCENDING)], projection={"_id": 0})
        return ProfileVersion.model_validate(doc) if doc else None

    def history(self, limit: int = 20) -> list[ProfileVersion]:
        cur = self.col.find({}, projection={"_id": 0}).sort("version", DESCENDING).limit(limit)
        return [ProfileVersion.model_validate(d) for d in cur]

    def confirm(self, data: ProfileInput, actor: str, confirmed: bool) -> ProfileVersion:
        """用户本人确认后写入新版本。未明确确认不写入，系统不替用户填。"""
        if not confirmed:
            raise ProfileError("个人约束必须由你本人明确确认后才能保存")
        tickers = [h.ticker for h in data.holdings]
        if len(tickers) != len(set(tickers)):
            raise ProfileError("同一只股票只能有一条记录")
        prev = self.current()
        v = ProfileVersion(**data.model_dump(), version=(prev.version if prev else 0) + 1,
                           parent_version=prev.version if prev else None,
                           confirmed_by=actor, confirmed_at=datetime.now(timezone.utc))
        self.col.insert_one(v.model_dump(mode="json"))
        return v

    def set_impact(self, version: int, impact: list[dict]) -> None:
        """只写系统算出的影响记录，不碰你确认过的约束字段。"""
        self.col.update_one({"version": version}, {"$set": {"impact": impact}})
