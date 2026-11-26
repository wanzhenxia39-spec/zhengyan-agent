"""预算对象随图状态持久化，断点恢复后继续计数。"""
import time
from dataclasses import asdict, dataclass, field

from advisor.harness.errors import BudgetExceeded


@dataclass
class Budget:
    limits: dict[str, float]
    used: dict[str, float] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def remaining(self, kind: str) -> float:
        return self.limits.get(kind, 0) - self.used.get(kind, 0)

    def check(self, kind: str | None = None, amount: float = 1) -> None:
        elapsed = time.time() - self.started_at
        if elapsed > self.limits.get("wall_clock_s", float("inf")):
            raise BudgetExceeded(f"总时限耗尽（{elapsed:.0f}s）")
        if kind and self.remaining(kind) < amount:
            raise BudgetExceeded(f"{kind} 预算耗尽（上限 {self.limits.get(kind, 0):g}）")

    def charge(self, kind: str, amount: float = 1) -> None:
        self.used[kind] = self.used.get(kind, 0) + amount

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Budget":
        return cls(limits=dict(data["limits"]), used=dict(data.get("used", {})), started_at=data["started_at"])
