"""前向模拟盘：按策略卡规则逐日向前推进，只用当天以前可得的档案与行情。

- 只能向前：日期必须晚于上一个净值点，且不早于模拟开始日——没有回填，也就没有「用未来考过去」；
- 每笔模拟成交都记下依据的档案版本与证据；
- 等权、整手（100 股）、不加杠杆；系统不执行任何真实交易。
"""
from datetime import date
from typing import Any, Callable

from advisor.contracts import Dossier
from advisor.evidence import metric_facts
from advisor.graph.deps import Deps
from advisor.harness import Budget, BudgetExceeded, HarnessDenied, SkillFailed
from advisor.strategy.models import NavPoint, PaperTrade, Position, StrategyVersion
from advisor.strategy.store import StrategyStore

LOT = 100


class PaperError(ValueError):
    pass


class PaperBook:
    def __init__(self, deps: Deps, store: StrategyStore, open_alerts: Callable[[str], int] = lambda t: 0):
        self.deps = deps
        self.store = store
        self.open_alerts = open_alerts
        self.initial_cash = float(deps.policy.strategy.get("initial_cash", 1_000_000))

    # ---------- 信号：当天可见的事实 ----------
    def dossier_at(self, ticker: str, day: date) -> Dossier | None:
        """当天之前（含）研究时点最新的档案版本。"""
        for v in self.deps.repo.list_dossier_versions(ticker):
            if str(v["as_of"])[:10] <= day.isoformat():
                return self.deps.repo.get_dossier(ticker, v["version"])
        return None

    def facts(self, h, ticker: str, day: date) -> tuple[dict[str, Any], Dossier | None, list[str]]:
        d = self.dossier_at(ticker, day)
        if d is None:
            return {}, None, []
        cards = self.deps.repo.get_evidence(d.evidence_ids)
        facts: dict[str, Any] = {k: m.value for k, m in metric_facts(cards).items()}
        ev_ids = [c.id for c in cards if c.source_type in ("market", "calc")]
        try:
            live = h.call("market.daily", code=ticker, as_of=day).cards
            facts.update({k: m.value for k, m in metric_facts(live).items()})   # 行情用当天的，基本面用档案的
            ev_ids = [c.id for c in live] + ev_ids
            for c in live:
                self.deps.repo.put_evidence(c)
        except (SkillFailed, HarnessDenied, BudgetExceeded):
            facts.pop("close", None)                                          # 没有当天价格就不交易
        facts.update(status=d.status, verified=sum(c.status == "verified" for c in d.claims),
                     disputed=sum(c.status == "disputed" for c in d.claims), open_alerts=self.open_alerts(ticker))
        return facts, d, ev_ids[:6]

    def universe(self, card: StrategyVersion) -> list[str]:
        return card.universe or [d["key"] for d in self.deps.repo.list_dossiers()]

    # ---------- 推进一天 ----------
    def step(self, card: StrategyVersion, day: date) -> NavPoint:
        if card.status not in ("paper", "review", "promoted"):
            raise PaperError(f"{card.ref} 不在模拟中")
        if card.paper_start and day < card.paper_start:
            raise PaperError(f"{day} 早于模拟开始日 {card.paper_start}：模拟盘只能向前")
        navs = self.store.navs_of(card.card_id, card.version)
        if navs and day <= navs[-1].date:
            if day == navs[-1].date:
                return navs[-1]                                              # 同一天重复推进：幂等
            raise PaperError(f"{day} 不晚于上一个净值点 {navs[-1].date}：模拟盘只能向前")
        cash = navs[-1].cash if navs else self.initial_cash
        held = {p.ticker: p for p in (navs[-1].positions if navs else [])}
        h = self.deps.harness(f"paper_{card.card_id}_v{card.version}", "quick", day,
                              Budget(limits=self.deps.policy.route("quick").budget), node="paper", principal="paper")
        trades, notes = [], []
        snap = {t: self.facts(h, t, day) for t in dict.fromkeys(list(held) + self.universe(card))}

        def trade(t: str, side: str, shares: int, price: float, reason: str):
            _, d, ev = snap[t]
            trades.append(PaperTrade(card_id=card.card_id, version=card.version, date=day, ticker=t, side=side,
                                     shares=shares, price=price, reason=reason, dossier_version=d.version if d else None,
                                     dossier_as_of=d.as_of if d else None, evidence_ids=ev))

        # 1. 移出：任一退出规则满足、触发止损、或档案不可用（当天移出的不再当天纳入）
        closed_today: set[str] = set()
        for t, pos in list(held.items()):
            facts, d, _ = snap[t]
            price = float(facts["close"]) if facts.get("close") is not None else None
            if price is None:
                notes.append(f"{t} 今日无行情，持仓按上次价格计")
                continue
            pos.price = price
            hit = [r.label() for r in card.exit if r.check(facts)]
            if card.stop_loss_pct and price <= pos.cost * (1 - card.stop_loss_pct / 100):
                hit.append(f"止损 -{card.stop_loss_pct:g}%")
            if d is None:
                hit.append("档案不可用")
            if hit:
                cash += pos.shares * price
                trade(t, "close", pos.shares, price, "移出：" + "；".join(hit))
                del held[t]
                closed_today.add(t)

        # 2. 纳入：全部进入规则满足，等权、整手
        nav_now = cash + sum(p.shares * p.price for p in held.values())
        slot = nav_now / card.max_positions
        for t in self.universe(card):
            if len(held) >= card.max_positions or t in held or t in closed_today:
                continue
            facts, d, _ = snap[t]
            results = [(r, r.check(facts)) for r in card.entry]
            missing = [r.label() for r, ok in results if ok is None]
            if d is None or facts.get("close") is None or not all(ok for _, ok in results):
                if missing and d is not None:
                    notes.append(f"{t} 缺数据：{'、'.join(missing)}")
                continue
            price = float(facts["close"])
            shares = int(min(slot, cash) // (price * LOT)) * LOT
            if shares <= 0:
                notes.append(f"{t} 满足条件但资金不足一手")
                continue
            cash -= shares * price
            held[t] = Position(ticker=t, shares=shares, cost=price, price=price, opened=day)
            trade(t, "open", shares, price, "纳入：" + "；".join(r.label() for r in card.entry))

        point = NavPoint(card_id=card.card_id, version=card.version, date=day, cash=round(cash, 2),
                         nav=round(cash + sum(p.shares * p.price for p in held.values()), 2),
                         positions=list(held.values()), notes=notes)
        self.store.add_trades(trades)
        self.store.add_nav(point)
        return point


def nav_stats(navs: list[NavPoint], initial: float) -> dict:
    """累计收益与最大回撤（%）。"""
    if not navs:
        return {"days": 0, "return_pct": 0.0, "max_drawdown_pct": 0.0}
    peak, mdd = initial, 0.0
    for p in navs:
        peak = max(peak, p.nav)
        mdd = max(mdd, (peak - p.nav) / peak * 100 if peak else 0)
    return {"days": len(navs), "return_pct": round((navs[-1].nav / initial - 1) * 100, 2), "max_drawdown_pct": round(mdd, 2)}
