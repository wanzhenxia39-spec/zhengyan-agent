"""二期：路由决策与多专家审议记录。专家之间不直接信任彼此的结论，一切回到证据。"""
from typing import Literal

from pydantic import BaseModel, Field

from advisor.contracts.dossier import Claim

Route = Literal["quick", "standard", "deep"]


class RouteDecision(BaseModel):
    """任务轴决策（走多重的流程）；模型轴在策略里按角色配置。"""
    route: Route
    source: Literal["user", "rule", "model", "abstain", "escalation", "fallback"]
    probs: dict[str, float] = Field(default_factory=dict)       # 判别器原始概率
    calibrated: dict[str, float] = Field(default_factory=dict)  # 温度校准后
    stakes: str | None = None
    uncertainty: str | None = None
    abstain: bool = False
    reasons: list[str] = Field(default_factory=list)
    escalated_from: str | None = None
    classifier: Literal["llm", "small"] | None = None   # 实际给出概率的判别器
    shadow: dict | None = None                         # 影子模式：小模型的判断（只记录，不生效）


class ExpertResult(BaseModel):
    expert: str
    name: str
    model_role: str
    brief: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    own_evidence_ids: list[str] = Field(default_factory=list)
    seen_evidence: int = 0
    claims: list[Claim] = Field(default_factory=list)
    stance: str = ""
    confidence: str = ""
    open_questions: list[str] = Field(default_factory=list)
    usage: dict[str, float] = Field(default_factory=dict)
    lessons: list[str] = Field(default_factory=list)      # RSI 召回的经验卡
    duration_ms: int = 0
    error: str | None = None


class Challenge(BaseModel):
    id: str
    target_claim_id: str
    target_expert: str
    kind: Literal["counter_evidence", "alternative_explanation", "logic_gap", "data_basis"]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    severity: Literal["low", "mid", "high"] = "mid"
    evidence_ok: bool = True
    notes: list[str] = Field(default_factory=list)


class Response(BaseModel):
    challenge_id: str
    expert: str
    stance: Literal["concede", "rebut", "revise"]
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    revised_claim: Claim | None = None


class Ruling(BaseModel):
    challenge_id: str
    verdict: Literal["upheld", "rejected", "unresolved"]
    reason: str
    severity: Literal["low", "mid", "high"] = "mid"


class CommitteeSeat(BaseModel):
    expert: str
    position: str


class Deliberation(BaseModel):
    mode: Literal["map_reduce", "debate", "committee"]
    rationale: str = ""
    team: list[ExpertResult] = Field(default_factory=list)
    challenges: list[Challenge] = Field(default_factory=list)
    responses: list[Response] = Field(default_factory=list)
    rulings: list[Ruling] = Field(default_factory=list)
    committee: list[CommitteeSeat] = Field(default_factory=list)
    adopted_claim_ids: list[str] = Field(default_factory=list)
    needs_human_review: bool = False
