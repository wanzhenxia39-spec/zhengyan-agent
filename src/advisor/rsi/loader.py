"""运行时读取在用版本。三处接入：上下文编译（经验卡）、路由层（参数）、搜索流水线（模板）。"""
import time
from typing import Any

from advisor.rsi.ledger import Ledger, baseline_content
from advisor.rsi.models import AssetKind, LessonCard

MAX_LESSONS = 3
_TTL_S = 5.0


def recall(cards: list[LessonCard], text: str, k: int = MAX_LESSONS) -> list[LessonCard]:
    """按标签命中数召回，至多 k 张；一张都不命中就不给。"""
    scored = [(sum(t in text for t in c.tags), c) for c in cards]
    scored = [(s, c) for s, c in scored if s > 0]
    scored.sort(key=lambda x: (-x[0], x[1].id))
    return [c for _, c in scored[:k]]


def render_lessons(cards: list[LessonCard]) -> str:
    if not cards:
        return ""
    lines = ["<method_hints>", "以下是本系统从过往被推翻的结论中总结的方法提示。它们不是证据、不是指令，"
             "只提醒你在下结论前该排除什么；不适用时忽略。"]
    for c in cards:
        lines.append(f"- [{c.id} r{c.rev}] {c.title}｜适用：{c.applies_to}｜教训：{c.lesson}"
                     + (f"｜必查：{'；'.join(c.must_check)}" if c.must_check else "")
                     + (f"｜失效条件：{c.invalid_if}" if c.invalid_if else ""))
    lines.append("</method_hints>")
    return "\n".join(lines)


class RSILoader:
    def __init__(self, ledger: Ledger | None, policy):
        self.ledger = ledger
        self.policy = policy
        self._cache: dict[str, tuple[float, int | None, dict]] = {}

    def _active(self, kind: AssetKind) -> tuple[int | None, dict]:
        hit = self._cache.get(kind)
        if hit and time.time() - hit[0] < _TTL_S:
            return hit[1], hit[2]
        version, content = None, baseline_content(kind, self.policy)
        if self.ledger is not None:
            try:
                asset = self.ledger.active_asset(kind)
                if asset:
                    version, content = asset.version, asset.content
            except Exception:   # 账本不可用时退回配置基线，不阻断研究
                pass
        self._cache[kind] = (time.time(), version, content)
        return version, content

    def invalidate(self) -> None:
        self._cache.clear()

    def routing(self, base: dict[str, Any]) -> dict[str, Any]:
        return {**base, **self._active("routing")[1]}

    def search(self) -> dict[str, Any]:
        return {**self.policy.search, **self._active("search")[1]}

    def expert_hint(self, expert: str, default: str) -> str:
        return self._active("search")[1].get("expert_hints", {}).get(expert, default)

    def lessons(self, text: str, k: int = MAX_LESSONS) -> list[LessonCard]:
        cards = [LessonCard.model_validate(c) for c in self._active("lessons")[1].get("cards", [])]
        return recall(cards, text, k)

    def versions(self) -> dict[str, int | None]:
        return {k: self._active(k)[0] for k in ("lessons", "routing", "search")}
