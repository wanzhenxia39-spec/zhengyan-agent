"""研究质量与成本指标。满意度、报告速度不单独作数；LLM 评分不用于自我验收。"""
import re
from datetime import datetime

from advisor.contracts import Dossier, EvidenceCard
from advisor.evidence.verifier import extract_numbers

COVERAGE = {
    "累计同比": lambda d, t: bool(re.search(r"同比", t)),
    "单季口径": lambda d, t: "单季" in t,
    "利润质量": lambda d, t: bool(re.search(r"扣非|现金|合同负债", t)),
    "估值": lambda d, t: bool(re.search(r"估值|PE|市盈率|PB|市净率", t)),
    "事件/公告": lambda d, t: bool(re.search(r"公告|事件|披露|说明会", t)),
    "反方观点": lambda d, t: len(d.dissents) >= 1,
    "未知项": lambda d, t: len(d.unknowns) >= 1,
    "复核条件": lambda d, t: len(d.review_triggers) >= 2,
}


def _secs(task: dict) -> float:
    a, b = task.get("created_at"), task.get("updated_at")
    return (b - a).total_seconds() if isinstance(a, datetime) and isinstance(b, datetime) else 0.0


def dossier_metrics(d: Dossier, ev: dict[str, EvidenceCard], task: dict) -> dict:
    claims = d.claims
    verified = [c for c in claims if c.status == "verified"]
    numeric = [c for c in claims if extract_numbers(c.text) and c.kind in ("fact", "inference")]
    numeric_ok = [c for c in numeric if c.status == "verified"]
    text = " ".join(c.text for c in verified) + " " + d.summary
    coverage = {k: f(d, text) for k, f in COVERAGE.items()}
    cited = {i for c in verified for i in c.evidence_ids}
    b_publishers = {(ev[i].origin_publisher or ev[i].site_name) for i in cited if i in ev and ev[i].level == "B"}
    budget = ((task.get("result") or {}).get("budget") or {}).get("used", {})
    verified_rate = len(verified) / len(claims) if claims else 0.0
    numeric_acc = len(numeric_ok) / len(numeric) if numeric else 1.0
    cov = sum(coverage.values()) / len(coverage)
    score = (0.30 * verified_rate + 0.30 * cov + 0.25 * numeric_acc + 0.05 * min(len(d.dissents), 3) / 3
             + 0.10 * (1.0 if d.quality.decision == "pass" else 0.5))
    return {
        "claims": len(claims), "verified": len(verified), "disputed": sum(c.status == "disputed" for c in claims),
        "rejected": sum(c.status == "rejected" for c in claims), "verified_rate": round(verified_rate, 3),
        "numeric_claims": len(numeric), "numeric_accuracy": round(numeric_acc, 3),
        "coverage": coverage, "coverage_rate": round(cov, 3), "dissents": len(d.dissents), "unknowns": len(d.unknowns),
        "independent_b_sources": len(b_publishers), "quality_decision": d.quality.decision,
        "tokens": int(budget.get("tokens", 0)), "search_calls": int(budget.get("search_calls", 0)),
        "fetch_calls": int(budget.get("fetch_calls", 0)), "seconds": round(_secs(task), 1), "score": round(score, 3),
    }
