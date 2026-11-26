"""证据契约：所有结论的最小依据单元。证据卡一经写入即不可变。"""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Basis = Literal["cumulative", "single_quarter", "point", "ratio", "change", "ttm"]
Level = Literal["A", "B", "C"]


class Metric(BaseModel):
    """带口径的数值。比较前必须 name/unit/basis 一致。"""
    model_config = ConfigDict(frozen=True)

    name: str                 # 展示名，如 营业收入
    field: str                # 数据源字段，如 OPERATE_INCOME
    value: Decimal
    unit: str                 # 元 / % / 倍 / 元/股
    period: str               # 报告期或时点，如 2026-06-30
    basis: Basis              # 累计 / 单季 / 时点 / 比率 / 变化率
    note: str = ""


class EvidenceCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    level: Level
    source_type: Literal["filing", "market", "announcement", "web", "calc"]
    title: str
    source_url: str | None = None
    site_name: str | None = None
    origin_id: str                         # 原始来源指纹（去重/独立性）
    origin_publisher: str | None = None    # 原始发布方（识别转载）
    cluster_id: str | None = None          # 事件簇
    published_at: datetime | None = None
    retrieved_at: datetime
    as_of: date
    pit: Literal["strong", "weak"] = "strong"
    snapshot_hash: str
    excerpt: str
    metrics: list[Metric] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    authority: int | None = None
    rerank_score: float | None = None
    caveats: list[str] = Field(default_factory=list)
    skill: str
    skill_version: str


class SearchHit(BaseModel):
    """搜索原始结果：只是线索，还不是证据。"""
    title: str
    url: str
    site_name: str | None = None
    date: datetime | None = None
    authority: int = -1
    rerank_score: float = 0.0
    summary: str = ""
    snippet: str = ""
    query: str = ""
