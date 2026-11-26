"""双轴路由的任务轴。

顺序：用户指定 → 硬规则准入 → 窄判别（System 1，只输出标签与概率；可用本地决策小模型）→ 温度校准 → 拒判则按保守方向升级。
判别器自报概率不是放行依据：校准温度与拒判阈值来自 advisor eval routing 的离线评测。
"""
import math
from typing import Literal

from pydantic import BaseModel, Field

from advisor.contracts.deliberation import RouteDecision
from advisor.harness.errors import TaskCancelled

ORDER = ("quick", "standard", "deep")

ROUTER_SYSTEM = """你是投研任务的路由判别器（System 1），只做分类，不回答问题，不写分析。
给出三类流程的概率（三者之和为 1）：
- quick：概念解释、单一数据查询、简单事实确认；
- standard：常规个股研究、业绩复核、利润质量分析；
- deep：结论分歧大或后果高、需要多角度对抗——如估值是否合理、要不要继续持有、重大负面事件/做空影响、多空观点对比。
stakes 表示潜在后果，uncertainty 表示证据可能的分歧程度。不确定时不要硬判，让概率分散。"""


class RouterOut(BaseModel):
    p_quick: float = Field(ge=0, le=1)
    p_standard: float = Field(ge=0, le=1)
    p_deep: float = Field(ge=0, le=1)
    stakes: Literal["low", "mid", "high"]
    uncertainty: Literal["low", "mid", "high"]
    reasons: list[str] = Field(default_factory=list, max_length=3)


def normalize(probs: dict[str, float]) -> dict[str, float]:
    total = sum(max(v, 0.0) for v in probs.values())
    if total <= 0:
        return {k: 1 / len(probs) for k in probs}
    return {k: max(v, 0.0) / total for k, v in probs.items()}


def calibrate(probs: dict[str, float], temperature: float) -> dict[str, float]:
    """温度缩放：T>1 让过度自信的分布变平，T<1 变尖。"""
    eps = 1e-6
    logits = {k: math.log(max(v, eps)) / temperature for k, v in probs.items()}
    m = max(logits.values())
    exp = {k: math.exp(v - m) for k, v in logits.items()}
    z = sum(exp.values())
    return {k: round(v / z, 4) for k, v in exp.items()}


# 决策小模型（Kev/Jev）的题目。Kev 只训练过英文指令（中文指令实测路由准确率低 12 个百分点），
# 所以题目用英文写；被判别的问题原文仍是中文。选项含义与 ROUTER_SYSTEM 一致。
_LEVELS = {"low": "Low", "mid": "Medium", "high": "High"}
SMALL_QUESTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "route": ("Which research workflow should this Chinese A-share stock question be routed to?", {
        "quick": "Concept explanation, a single data lookup, or a simple fact check",
        "standard": "Routine single-stock research: earnings review, profit quality, cash flow of the latest reports",
        "deep": "High-stakes or contested judgment needing a multi-angle debate: is the valuation reasonable, "
                "should I keep holding, major negative events or short-seller reports, bull vs bear views"}),
    "stakes": ("How severe would the consequences be for the investor if this question were answered wrongly?", _LEVELS),
    "uncertainty": ("How much could evidence and opinions disagree on this question?", _LEVELS),
}


def _top(probs: dict[str, float]) -> str:
    return max(probs, key=probs.get)


def _small_probs(h, question: str) -> tuple[dict[str, float], str, str]:
    a = h.decide(question, SMALL_QUESTIONS, purpose="route_classify_small")
    return normalize({k: a["route"].get(k, 0.0) for k in ORDER}), _top(a["stakes"]), _top(a["uncertainty"])


def decide_route(h, question: str, intent: str, requested: str, cfg: dict) -> RouteDecision:
    """cfg["classifier"]：llm = 只用大模型；small = 小模型优先，不可用时退回大模型；
    shadow = 大模型生效，小模型同时判一次只记录，用于上线前对比。"""
    if requested != "auto":
        return RouteDecision(route=requested, source="user", reasons=["用户指定流程"])
    if intent == "explain":
        return RouteDecision(route="quick", source="rule", reasons=["概念解释类问题走快查"])
    mode = cfg.get("classifier", "llm")
    small, notes = None, []
    if mode in ("small", "shadow") and getattr(h, "decision_client", None) is not None:
        try:
            small = _small_probs(h, question)
        except TaskCancelled:
            raise
        except Exception as e:  # 小模型不可用不致命：退回大模型
            notes.append(f"小模型不可用，改用大模型判别：{str(e)[:60]}")
    if mode == "small" and small:
        probs, stakes, uncertainty = small
        decision = route_from_probs(probs, cfg, stakes, uncertainty, intent)
        decision.classifier = "small"
        decision.reasons = [f"小模型判别：{ {k: round(v, 2) for k, v in probs.items()} }"] + decision.reasons
        return decision
    try:
        out: RouterOut = h.llm("classify", ROUTER_SYSTEM, question, RouterOut, purpose="route_classify")
    except TaskCancelled:
        raise
    except Exception as e:  # 判别器不可用：走默认标准流程，不硬判
        return RouteDecision(route="standard", source="fallback", reasons=notes + [f"判别器不可用：{str(e)[:80]}"])
    probs = normalize({"quick": out.p_quick, "standard": out.p_standard, "deep": out.p_deep})
    decision = route_from_probs(probs, cfg, out.stakes, out.uncertainty, intent)
    decision.classifier = "llm"
    decision.reasons = notes + list(out.reasons) + decision.reasons
    if mode == "shadow" and small:
        sp, ss, su = small
        decision.shadow = {"classifier": "small", "probs": {k: round(v, 4) for k, v in sp.items()}, "stakes": ss,
                           "uncertainty": su, "route": route_from_probs(sp, cfg, ss, su, intent).route}
    return decision


def route_from_probs(probs: dict[str, float], cfg: dict, stakes: str | None = None, uncertainty: str | None = None,
                     intent: str = "research") -> RouteDecision:
    """判别器原始概率 → 校准 → 拒判/升级。纯函数：RSI 用它在记录下的概率上回放不同参数。"""
    cal = calibrate(probs, float(cfg.get("temperature", 1.0)))
    ranked = sorted(cal, key=cal.get, reverse=True)
    top = ranked[0]
    reasons: list[str] = []
    decision = RouteDecision(route=top, source="model", probs={k: round(v, 4) for k, v in probs.items()},
                             calibrated=cal, stakes=stakes, uncertainty=uncertainty, reasons=reasons)
    if cal[top] < float(cfg.get("abstain_below", 0.55)):
        deeper = max(ranked[:2], key=ORDER.index)            # 拒判：在前两名里取更重的流程
        decision.route, decision.source, decision.abstain = deeper, "abstain", True
        decision.reasons = reasons + [f"最高校准概率 {cal[top]:.2f} 低于阈值，拒判并升级到 {deeper}"]
    elif stakes == cfg.get("deep_threshold_stakes", "high") and uncertainty == "high" and top != "deep":
        decision.route = "deep"
        decision.reasons = reasons + ["高后果且高分歧：升级到争议深研"]
    if intent == "trade_execution" and decision.route == "quick":
        decision.route = "standard"
        decision.reasons.append("含交易意图：至少走标准研究解释事实与情景")
    return decision


def should_escalate(decision: dict, disputed: int, dissents: int, cfg: dict) -> bool:
    """标准研究在质量门控检查点：分歧明显且路由不是用户指定 → 升级到深研（只升级一次）。"""
    if decision.get("source") == "user" or decision.get("route") != "standard" or decision.get("escalated_from"):
        return False
    rule = cfg.get("escalate_on", {})
    return disputed >= int(rule.get("min_disputed", 2)) or dissents >= int(rule.get("min_dissents", 3))
