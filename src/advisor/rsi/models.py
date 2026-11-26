"""RSI 契约：只改模型外面那一层——经验卡、路由参数、检索模板。资产不可变，只能追加带血缘的新版本。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

AssetKind = Literal["lessons", "routing", "search"]
Scenario = Literal["S1", "S2", "S3"]
RunStatus = Literal["draft", "review", "approved", "released", "archived", "rejected", "rolled_back"]

SCENARIO_KIND: dict[str, AssetKind] = {"S1": "lessons", "S2": "routing", "S3": "search"}
KIND_LABEL = {"lessons": "经验库", "routing": "路由参数", "search": "检索模板"}


class LessonCard(BaseModel):
    """经验卡：只沉淀"怎么研究、怎么核验"，不沉淀投资结论；作为方法提示进入提示词，不是指令，也不是证据。"""
    id: str                                   # L-001，跨版本稳定
    title: str = Field(max_length=40)
    applies_to: str = Field(max_length=120)   # 适用场景（行业类型 + 指标现象）
    tags: list[str] = Field(default_factory=list, max_length=8)   # 召回关键词（指标、行业类型）
    lesson: str = Field(max_length=200)
    must_check: list[str] = Field(default_factory=list, max_length=4)
    invalid_if: str = Field(default="", max_length=120)
    source: str = ""                          # 来源：档案/质询
    rev: int = 1                              # 卡片自身修订号


class Asset(BaseModel):
    kind: AssetKind
    version: int
    parent_version: int | None = None
    content: dict[str, Any]
    sha256: str
    change_reason: str = Field(min_length=10)
    run_id: str | None = None                 # 由哪次 RSI 运行产生（基线为 None）
    created_by: str
    created_at: datetime


class Issue(BaseModel):
    """坏案例四要素：案例、类型、证据、假设。没有假设的问题不允许登记。"""
    id: str
    scenario: Scenario
    kind: str
    case: str
    evidence: list[str] = Field(min_length=1)
    hypothesis: str = Field(min_length=6)
    source: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str
    status: Literal["open", "addressed", "dropped"] = "open"
    created_at: datetime


class GateResult(BaseModel):
    name: str
    label: str
    passed: bool
    detail: str


class Run(BaseModel):
    """一次 RSI 候选：针对一个问题、只改一个组件。"""
    run_id: str
    scenario: Scenario
    kind: AssetKind
    issue_ids: list[str]
    base_version: int
    content: dict[str, Any]
    diff: dict[str, Any] = Field(default_factory=dict)
    change_reason: str = Field(min_length=10)
    direction: str                            # 改动方向指纹：失败的方向不再重复
    status: RunStatus = "draft"
    risk: Literal["normal", "high"] = "normal"   # high：改抓取站点名单等，批准时必须写明理由
    proposer: str = "optimizer"
    triggered_by: str = "owner"
    eval: dict[str, Any] | None = None
    gates: list[GateResult] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    released_version: int | None = None
    reject_reason: str | None = None
    created_at: datetime
    updated_at: datetime
