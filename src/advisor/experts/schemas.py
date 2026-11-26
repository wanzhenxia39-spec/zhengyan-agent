"""专家、反证官、主席的模型输出契约。"""
from typing import Literal

from pydantic import BaseModel, Field

from advisor.contracts import Dissent, PriorReview, ReviewTrigger
from advisor.skills.research.earnings_review import DraftClaim


class TeamMember(BaseModel):
    expert: str
    questions: list[str] = Field(description="1-3 个具体待查问题")
    why: str = ""


class TeamPlan(BaseModel):
    members: list[TeamMember]
    mode: Literal["map_reduce", "debate", "committee"]
    rationale: str = ""


class ExpertQueries(BaseModel):
    queries: list[str] = Field(description="1-2 个中文搜索词，每个不超过 40 字")


class ExpertDraft(BaseModel):
    stance: str = Field(description="一句话立场，40 字内")
    confidence: Literal["low", "mid", "high"] = "mid"
    claims: list[DraftClaim]
    open_questions: list[str] = Field(default_factory=list)


class ChallengeDraft(BaseModel):
    target_claim_id: str
    kind: Literal["counter_evidence", "alternative_explanation", "logic_gap", "data_basis"]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity: Literal["low", "mid", "high"] = "mid"


class ChallengeSet(BaseModel):
    challenges: list[ChallengeDraft]


class ResponseDraft(BaseModel):
    challenge_id: str
    stance: Literal["concede", "rebut", "revise"]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    revised_claim: DraftClaim | None = None


class ResponseSet(BaseModel):
    responses: list[ResponseDraft]


class RulingDraft(BaseModel):
    challenge_id: str
    verdict: Literal["upheld", "rejected", "unresolved"]
    reason: str
    severity: Literal["low", "mid", "high"] = "mid"


class SeatDraft(BaseModel):
    expert: str
    position: str


class ChairOutput(BaseModel):
    summary: str = Field(description="250 字内，含主要分歧与保留意见")
    rulings: list[RulingDraft] = Field(default_factory=list)
    adopted_claim_ids: list[str] = Field(default_factory=list, description="采纳的已核验专家主张 id")
    synthesis_claims: list[DraftClaim] = Field(default_factory=list, description="主席的综合推断，必须引用证据")
    dissents: list[Dissent] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    review_triggers: list[ReviewTrigger] = Field(default_factory=list)
    committee: list[SeatDraft] = Field(default_factory=list)
    prior_review: list[PriorReview] = Field(default_factory=list)
