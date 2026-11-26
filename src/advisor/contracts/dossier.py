"""持续决策档案：系统围绕它工作，而不是围绕聊天记录。每次提交生成新版本，不覆盖旧版本。"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ClaimKind = Literal["fact", "inference", "assumption", "scenario"]
ClaimStatus = Literal["candidate", "verified", "disputed", "rejected", "stale"]


class Claim(BaseModel):
    id: str
    text: str
    kind: ClaimKind
    evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimStatus = "candidate"
    author: str = "researcher"
    verify_notes: list[str] = Field(default_factory=list)


class Dissent(BaseModel):
    text: str
    evidence_ids: list[str] = Field(default_factory=list)


class ReviewTrigger(BaseModel):
    condition: str      # 下一次复核条件
    reason: str


class QualityResult(BaseModel):
    decision: Literal["pass", "need_more", "partial"]
    verified: int = 0
    disputed: int = 0
    rejected: int = 0
    gaps: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PriorReview(BaseModel):
    """对上一版本结论的复核：保留、削弱、失效或无法判断。"""
    prior_claim: str
    verdict: Literal["retained", "weakened", "invalidated", "unverifiable"]
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class Dossier(BaseModel):
    key: str                          # 档案主键（一期按标的）
    version: int
    parent_version: int | None = None
    ticker: str
    name: str = ""
    as_of: date
    question: str
    route: str
    status: Literal["committed", "partial"]
    summary: str = ""
    claims: list[Claim] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    dissents: list[Dissent] = Field(default_factory=list)
    review_triggers: list[ReviewTrigger] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    quality: QualityResult
    boundary_notes: list[str] = Field(default_factory=list)
    task_id: str
    created_at: datetime
    report_md: str = ""
    # 二期
    routing: dict | None = None             # RouteDecision
    deliberation: dict | None = None        # Deliberation（深研）
    prior_review: list[PriorReview] = Field(default_factory=list)
    clue_ids: list[str] = Field(default_factory=list)   # 网页线索（B/C），不支撑结论但需可见
    # RSI：本档案用了哪些在用版本（经验库/路由参数/检索模板）与召回的经验卡，证明改进被下一轮继承
    rsi_versions: dict[str, int | None] = Field(default_factory=dict)
    lessons_used: list[str] = Field(default_factory=list)
