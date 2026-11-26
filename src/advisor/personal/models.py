"""三期：用户确认档案。个人约束只能由用户本人确认，系统只读；每次修改生成新版本，旧版本保留。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RiskProfile(BaseModel):
    max_drawdown_pct: float | None = Field(default=None, gt=0, le=100, description="可承受的最大回撤（%）")
    horizon_months: int | None = Field(default=None, ge=1, le=600, description="这笔钱可以投多久（月）")
    liquidity_note: str = Field(default="", max_length=200, description="何时要用钱、用途")


class Holding(BaseModel):
    """一只关注或持有的股票：为什么买、打算拿多久。不记金额与账户。"""
    ticker: str = Field(pattern=r"^\d{6}$")
    name: str = ""
    thesis: str = Field(min_length=4, max_length=300, description="购买理由 / 关注理由")
    horizon_months: int | None = Field(default=None, ge=1, le=600)


class ProfileInput(BaseModel):
    risk: RiskProfile = Field(default_factory=RiskProfile)
    holdings: list[Holding] = Field(default_factory=list)
    change_note: str = Field(default="", max_length=200)


class ProfileVersion(ProfileInput):
    version: int
    parent_version: int | None = None
    confirmed_by: str
    confirmed_at: datetime
    impact: list[dict] = Field(default_factory=list)   # 系统计算：这次修改让哪些档案的个人情境结论变了（不改你的约束）

    def holding(self, ticker: str) -> Holding | None:
        return next((h for h in self.holdings if h.ticker == ticker), None)


FitStatus = Literal["ok", "attention", "conflict", "unknown"]


class FitCheck(BaseModel):
    key: str
    label: str
    status: FitStatus
    detail: str
    refs: list[str] = Field(default_factory=list)       # 关联的主张 / 证据 / 复核提醒


class PersonalFit(BaseModel):
    """个人情境官的对照结果：结论与「你确认过的约束」是否相容。不是买卖建议。"""
    ticker: str
    dossier_version: int
    profile_version: int | None
    checks: list[FitCheck]
    summary: str
    disclaimer: str = "只对照你本人确认的约束，不猜测未确认的信息；不构成买卖建议；个人信息只在本地比对，不发往模型或搜索。"
