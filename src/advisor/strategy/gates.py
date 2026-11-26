"""策略卡晋级门控（纯代码）：前向时长、无未来数据、回撤上限、可解释、相对在用版本不退化。"""
from advisor.rsi.models import GateResult
from advisor.strategy.models import NavPoint, PaperTrade, StrategyVersion
from advisor.strategy.paper import nav_stats


def _gate(name: str, label: str, passed: bool, detail: str) -> GateResult:
    return GateResult(name=name, label=label, passed=passed, detail=detail)


def promotion_gates(card: StrategyVersion, navs: list[NavPoint], trades: list[PaperTrade], initial: float,
                    cfg: dict, incumbent: tuple[StrategyVersion, list[NavPoint]] | None = None) -> list[GateResult]:
    min_days = int(cfg.get("min_paper_days", 10))
    tol = float(cfg.get("regression_tolerance_pct", 2))
    st = nav_stats(navs, initial)
    out = [_gate("forward", "前向时长", st["days"] >= min_days,
                 f"已前向模拟 {st['days']} 个交易日，要求 ≥ {min_days}")]

    leaks = [t for t in trades if (card.paper_start and t.date < card.paper_start)
             or (t.dossier_as_of and t.dossier_as_of > t.date)]
    out.append(_gate("lookahead", "无未来数据", not leaks,
                     f"{len(leaks)} 笔成交用到了成交日之后的信息" if leaks else
                     f"{len(trades)} 笔成交都只用了当日可见的档案与行情"))

    out.append(_gate("drawdown", "回撤上限", st["max_drawdown_pct"] <= card.max_drawdown_limit,
                     f"模拟最大回撤 {st['max_drawdown_pct']}%，上限 {card.max_drawdown_limit:g}%"))

    opened = [t for t in trades if t.side == "open"]
    traced = [t for t in opened if t.dossier_version and t.evidence_ids]
    out.append(_gate("explain", "可解释", bool(opened) and len(traced) == len(opened),
                     f"{len(opened)} 笔纳入，{len(traced)} 笔可追溯到档案版本与证据" if opened else "还没有发生过纳入，无法评估"))

    if incumbent is None:
        out.append(_gate("regression", "不退化", True, "没有在用版本，首个版本无需对比"))
    else:
        inc_card, inc_navs = incumbent
        days = {p.date for p in navs} & {p.date for p in inc_navs}
        if len(days) < min_days:
            out.append(_gate("regression", "不退化", False,
                             f"与在用 {inc_card.ref} 同期只有 {len(days)} 天，要求 ≥ {min_days}"))
        else:
            mine = _period_return([p for p in navs if p.date in days])
            theirs = _period_return([p for p in inc_navs if p.date in days])
            out.append(_gate("regression", "不退化", mine >= theirs - tol,
                             f"同期 {len(days)} 天：候选 {mine:+.2f}% vs 在用 {inc_card.ref} {theirs:+.2f}%（容忍 {tol:g}%）"))
    return out


def _period_return(navs: list[NavPoint]) -> float:
    return (navs[-1].nav / navs[0].nav - 1) * 100 if len(navs) >= 2 and navs[0].nav else 0.0
