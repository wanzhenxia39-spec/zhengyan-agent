"""确定性计算：全部用 Decimal，比较前强制校验口径。可金标回归。"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, getcontext

from advisor.contracts import Metric

getcontext().prec = 28


class BasisMismatch(ValueError):
    """口径不一致，拒绝计算。"""


def q(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _period(m: Metric) -> date:
    return date.fromisoformat(m.period[:10])


def same_basis_growth(current: Metric, prior: Metric) -> Metric:
    """同比增长：同字段、同单位、同口径、同报告期（相差一年）。"""
    if (current.field, current.unit, current.basis) != (prior.field, prior.unit, prior.basis):
        raise BasisMismatch(f"口径不一致: {current.field}/{current.basis} vs {prior.field}/{prior.basis}")
    cp, pp = _period(current), _period(prior)
    if (cp.month, cp.day) != (pp.month, pp.day) or cp.year - pp.year != 1:
        raise BasisMismatch(f"报告期不可比: {cp} vs {pp}")
    if prior.value == 0:
        raise BasisMismatch("基期为 0，增长率无意义")
    growth = (current.value - prior.value) / abs(prior.value) * 100
    label = {"single_quarter": "单季", "point": "时点"}.get(current.basis, "累计")
    return Metric(
        name=f"{current.name}同比({label})", field=f"{current.field}_YOY", value=q(growth),
        unit="%", period=current.period, basis="change",
        note=f"{current.period[:10]} vs {prior.period[:10]}",
    )


def single_quarter(cumulative: Metric, previous_cumulative: Metric | None) -> Metric:
    """由累计值推单季：Q1=累计；其余=本期累计-同年上期累计。"""
    if cumulative.basis != "cumulative":
        raise BasisMismatch("单季推算需要累计口径")
    cp = _period(cumulative)
    if cp.month == 3:
        value = cumulative.value
    else:
        if previous_cumulative is None:
            raise BasisMismatch(f"缺少 {cp.year} 年上一报告期累计值")
        pp = _period(previous_cumulative)
        if previous_cumulative.field != cumulative.field or pp.year != cp.year or cp.month - pp.month != 3:
            raise BasisMismatch(f"上期累计不匹配: {pp}")
        value = cumulative.value - previous_cumulative.value
    return Metric(
        name=f"{cumulative.name}(单季)", field=cumulative.field, value=value, unit=cumulative.unit,
        period=cumulative.period, basis="single_quarter", note=f"Q{(cp.month - 1) // 3 + 1} 由累计值推算",
    )


def ratio(numerator: Metric, denominator: Metric, name: str, field: str) -> Metric:
    """比率（%）：分子分母须同报告期、同单位、同口径。"""
    if numerator.period != denominator.period or numerator.unit != denominator.unit or numerator.basis != denominator.basis:
        raise BasisMismatch(f"比率口径不一致: {numerator.name} vs {denominator.name}")
    if denominator.value == 0:
        raise BasisMismatch("分母为 0")
    return Metric(
        name=name, field=field, value=q(numerator.value / denominator.value * 100), unit="%",
        period=numerator.period, basis="ratio", note=f"{numerator.name}/{denominator.name}",
    )


def price_change(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) <= window or closes[-window - 1] == 0:
        return None
    return q((closes[-1] / closes[-window - 1] - 1) * 100)


def annualized_volatility(closes: list[Decimal], window: int = 60) -> Decimal | None:
    if len(closes) <= window:
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - window, len(closes))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return q(var.sqrt() * Decimal(252).sqrt() * 100)


def moving_average(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def max_drawdown(closes: list[Decimal]) -> Decimal | None:
    """区间最大回撤（%，负数）。"""
    if len(closes) < 2:
        return None
    peak, worst = closes[0], Decimal(0)
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            worst = min(worst, c / peak - 1)
    return q(worst * 100)


def ttm(cumulative: dict[str, Decimal], period: str) -> Decimal | None:
    """滚动四季度：年报直接用；否则 = 本期累计 + 上年年报 - 上年同期累计。缺任一项返回 None。"""
    y, md = int(period[:4]), period[4:]
    if md == "-12-31":
        return cumulative.get(period)
    cur, fy, prior = cumulative.get(period), cumulative.get(f"{y - 1}-12-31"), cumulative.get(f"{y - 1}{md}")
    if cur is None or fy is None or prior is None:
        return None
    return cur + fy - prior


def percentile_rank(values: list[Decimal], x: Decimal) -> Decimal | None:
    if not values:
        return None
    below = sum(1 for v in values if v <= x)
    return q(Decimal(below) / Decimal(len(values)) * 100)
