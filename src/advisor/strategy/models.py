"""四期：策略卡与前向模拟盘。

策略卡把「什么情况下纳入 / 移出观察组合」写成显式规则，只读档案与 A 级证据，不读模型的自由发挥。
策略卡只在模拟盘上运行，系统不执行任何真实交易；晋级须过门控并由人批准，可回滚。
"""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from advisor.rsi.models import GateResult

Op = Literal["<", "<=", ">", ">=", "==", "!="]
CardStatus = Literal["draft", "paper", "review", "promoted", "rejected", "retired", "rolled_back"]

# 规则可用字段：档案里的 A 级指标、档案状态、订阅提醒
FIELDS: dict[str, str] = {
    "pe_pct": "PE(TTM) 窗口分位 %", "pe_ttm": "PE(TTM)", "pb_mrq": "PB(MRQ)",
    "chg_20d": "近 20 日涨跌 %", "chg_60d": "近 60 日涨跌 %", "chg_250d": "近 250 日涨跌 %",
    "vol_60d": "近 60 日年化波动 %", "mdd_250d": "近 250 日最大回撤 %", "ma60_gap": "相对 MA60 %",
    "status": "档案状态（committed / partial）", "verified": "已核验主张数", "disputed": "存疑主张数",
    "open_alerts": "待复核提醒数",
}
STATUS_LABEL = {"draft": "草稿", "paper": "模拟中", "review": "待晋级", "promoted": "已晋级", "rejected": "已拒绝",
                "retired": "已退役", "rolled_back": "已回滚"}


class Rule(BaseModel):
    field: str
    op: Op
    value: float | str

    def check(self, facts: dict[str, Any]) -> bool | None:
        """满足返回 True；缺数据返回 None（视为不满足，且如实记录）。"""
        v = facts.get(self.field)
        if v is None:
            return None
        if isinstance(self.value, str) or isinstance(v, str):
            a, b = str(v), str(self.value)
        else:
            a, b = float(v), float(self.value)
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b, "==": a == b, "!=": a != b}[self.op]

    def label(self) -> str:
        value = f"{self.value:g}" if isinstance(self.value, float) else self.value
        return f"{FIELDS.get(self.field, self.field)} {self.op} {value}"


class StrategySpec(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    thesis: str = Field(min_length=6, max_length=300, description="策略逻辑：为什么这些规则有意义")
    universe: list[str] = Field(default_factory=list, description="候选股票；空 = 全部有档案的股票")
    entry: list[Rule] = Field(min_length=1, description="全部满足才纳入")
    exit: list[Rule] = Field(default_factory=list, description="任一满足即移出")
    max_positions: int = Field(default=5, ge=1, le=20)
    stop_loss_pct: float | None = Field(default=15, gt=0, le=80)
    max_drawdown_limit: float = Field(default=20, gt=0, le=100, description="晋级门控：模拟净值最大回撤上限 %")


class StrategyVersion(StrategySpec):
    card_id: str
    version: int
    parent_version: int | None = None
    status: CardStatus = "draft"
    change_reason: str = Field(min_length=10)
    sha256: str
    created_by: str
    created_at: datetime
    paper_start: date | None = None
    gates: list[GateResult] = Field(default_factory=list)
    approvals: list[dict] = Field(default_factory=list)
    reject_reason: str = ""

    @property
    def ref(self) -> str:
        return f"{self.card_id} v{self.version}"


class PaperTrade(BaseModel):
    card_id: str
    version: int
    date: date
    ticker: str
    side: Literal["open", "close"]
    shares: int
    price: float
    reason: str
    dossier_version: int | None = None
    dossier_as_of: date | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class Position(BaseModel):
    ticker: str
    shares: int
    cost: float
    price: float
    opened: date


class NavPoint(BaseModel):
    card_id: str
    version: int
    date: date
    nav: float
    cash: float
    positions: list[Position] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
