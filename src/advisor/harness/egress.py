"""出域检查：搜索查询词禁止含个人敏感信息；发往模型的文本先脱敏。"""
import re

from advisor.harness.errors import HarnessDenied


class EgressGuard:
    def __init__(self, sensitive_patterns: list[str], trade_patterns: list[str] | None = None):
        self._sensitive = [re.compile(p) for p in sensitive_patterns]
        self._trade = [re.compile(p) for p in (trade_patterns or [])]

    def find_sensitive(self, text: str) -> list[str]:
        return [m.group(0) for p in self._sensitive for m in p.finditer(text)]

    def has_trade_intent(self, text: str) -> bool:
        return any(p.search(text) for p in self._trade)

    def check_outbound(self, text: str) -> None:
        if self.find_sensitive(text):
            raise HarnessDenied("出域内容含个人敏感信息，已阻断")

    def redact(self, text: str) -> str:
        """先在原文上收集所有命中区间再合并替换，避免前一条规则破坏后一条的上下文。"""
        spans = sorted((m.start(), m.end()) for p in self._sensitive for m in p.finditer(text))
        merged: list[list[int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        for start, end in reversed(merged):
            text = text[:start] + "[已脱敏]" + text[end:]
        return text
