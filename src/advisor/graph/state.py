import operator
from typing import Annotated, Any, TypedDict


def merge_dict(left: dict, right: dict) -> dict:
    return {**(left or {}), **(right or {})}


class ResearchState(TypedDict, total=False):
    task_id: str
    namespace: str                                        # 评测等隔离命名空间；空 = 用户档案
    question: str
    ticker: str | None
    as_of: str
    route_requested: str
    route: str
    routing: dict                                         # RouteDecision
    company_name: str
    intent: str
    focus: str
    sensitive: bool
    budget: dict[str, Any]
    iteration: int
    evidence: Annotated[dict[str, dict], merge_dict]      # id -> EvidenceCard(json)
    statement_ids: list[str]
    calc_ids: list[str]
    market_ids: list[str]
    announcement_ids: list[str]
    prior: dict | None                                    # 上一版本档案摘要（工作记忆）
    review_focus: list[str]                               # 增量复核：订阅发现受影响的旧结论
    queries: list[str]
    searched: Annotated[list[str], operator.add]
    unknowns_sys: Annotated[list[str], operator.add]      # 系统层面的缺口（取数失败等）
    boundary_notes: Annotated[list[str], operator.add]
    draft: dict
    claims: list[dict]
    quality: dict
    # 二期：多专家深研
    escalated: bool
    team: dict                                            # TeamPlan
    expert_results: Annotated[list[dict], operator.add]
    usage: Annotated[list[dict], operator.add]            # 并行专家的预算使用，汇合时折算
    challenges: list[dict]
    responses: list[dict]
    deliberation: dict
    lessons_used: Annotated[list[str], operator.add]     # RSI：本次研究召回的经验卡
    dossier_key: str
    version: int
    report_md: str
    status: str
    error: str
