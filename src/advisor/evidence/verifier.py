"""独立核验器（规则，非模型）：来源存在、时点合法、证据等级足够、数字可在 A 级证据中复算。"""
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from advisor.contracts import Claim, EvidenceCard

_NUM = re.compile(r"(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*(亿元|万元|亿|万|元|%|个百分点|倍)")
_SCALE = {"亿元": Decimal(10) ** 8, "亿": Decimal(10) ** 8, "万元": Decimal(10) ** 4, "万": Decimal(10) ** 4, "元": Decimal(1)}


def extract_numbers(text: str) -> list[tuple[Decimal, Decimal, str, str]]:
    """返回 [(按基本单位的值, 允许误差, 单位类别, 原文)]；误差按书写精度的半个单位。"""
    out = []
    for raw, unit in _NUM.findall(text):
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        places = len(raw.split(".")[1]) if "." in raw else 0
        half = Decimal(5) * Decimal(10) ** (-(places + 1))
        if unit in _SCALE:
            out.append((abs(value) * _SCALE[unit], half * _SCALE[unit] + Decimal("0.0001"), "amount", raw))
        elif unit == "%":
            out.append((abs(value), half + Decimal("0.0001"), "pct", raw))
        elif unit == "倍":
            out.append((abs(value), half + Decimal("0.0001"), "multiple", raw))
        else:
            out.append((abs(value), half + Decimal("0.0001"), "pp", raw))
    return out


def _candidates(cards: list[EvidenceCard]) -> dict[str, list[Decimal]]:
    amounts, pcts, multiples = [], [], []
    for c in cards:
        for m in c.metrics:
            {"%": pcts, "倍": multiples}.get(m.unit, amounts).append(abs(m.value))
    pps = [abs(a - b) for i, a in enumerate(pcts) for b in pcts[i + 1:]]
    return {"amount": amounts, "pct": pcts, "pp": pps + pcts, "multiple": multiples + [p / 100 for p in pcts]}


def _matches(value: Decimal, tol: Decimal, pool: list[Decimal]) -> bool:
    return any(abs(value - v) <= tol for v in pool)


def verify_claim(claim: Claim, evidence: dict[str, EvidenceCard], as_of: date) -> Claim:
    notes: list[str] = []
    known = [evidence[i] for i in claim.evidence_ids if i in evidence]
    missing = [i for i in claim.evidence_ids if i not in evidence]
    if missing:
        notes.append(f"引用了不存在的证据 {missing}，已忽略")

    if claim.kind in ("assumption", "scenario"):
        notes.append("假设/情景，不是事实")
        return claim.model_copy(update={"status": "verified", "evidence_ids": [c.id for c in known], "verify_notes": notes})

    def done(status: str) -> Claim:
        return claim.model_copy(update={"status": status, "evidence_ids": [c.id for c in known], "verify_notes": notes})

    if not known:
        notes.append("没有可用证据")
        return done("rejected")
    future = [c.id for c in known if c.published_at and c.published_at.date() > as_of]
    if future:
        notes.append(f"证据晚于研究时点: {future}")
        return done("rejected")
    usable = [c for c in known if c.level in ("A", "B")]
    if not usable:
        notes.append("仅有 C 级线索，不能支撑结论")
        return done("rejected")

    numbers = extract_numbers(claim.text)
    if numbers:
        # 血缘：引用计算卡时，其来源财报也算作被引用
        lineage = [evidence[i] for c in usable if c.source_type == "calc" for i in c.derived_from if i in evidence]
        a_pool = _candidates([c for c in usable + lineage if c.level == "A"])
        b_text = " ".join(c.excerpt for c in usable if c.level == "B")
        for value, tol, kind, raw in numbers:
            if _matches(value, tol, a_pool[kind]):
                continue
            if raw in b_text:
                notes.append(f"数字 {value.normalize():f} 仅见于网页来源，须回到财报/公告复核")
            else:
                notes.append(f"数字 {value.normalize():f} 无法由引用证据复算")
            return done("disputed")

    web = [c for c in usable if c.source_type == "web"]
    if web and len(web) == len(usable) and len(web) > 1:
        groups = Counter(c.cluster_id or c.origin_publisher or c.origin_id for c in web)
        if len(groups) == 1:
            notes.append("多个网页来源属同一事件/转载，按单一来源计")
    if claim.kind == "fact" and all(c.level == "B" for c in usable):
        notes.append("依据为 B 级网页来源，仅说明发生了什么")
    return done("verified")


def verify_claims(claims: list[Claim], evidence: dict[str, EvidenceCard], as_of: date) -> list[Claim]:
    return [verify_claim(c, evidence, as_of) for c in claims]
