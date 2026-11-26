"""证据卡工厂：内容先快照（按哈希存），卡片 id 由来源与快照决定，引用后不可变。"""
import hashlib
from datetime import datetime, timezone
from typing import Any, Callable

from advisor.contracts import EvidenceCard


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EvidenceFactory:
    def __init__(self, snapshot_sink: Callable[[str, str], None]):
        self._sink = snapshot_sink

    def make(self, content: str, **fields: Any) -> EvidenceCard:
        digest = sha256(content)
        self._sink(digest, content)
        seed = f"{fields['source_type']}|{fields['origin_id']}|{fields['as_of']}|{digest}"
        fields.setdefault("retrieved_at", datetime.now(timezone.utc))
        return EvidenceCard(id="ev_" + sha256(seed)[:12], snapshot_hash=digest, **fields)
