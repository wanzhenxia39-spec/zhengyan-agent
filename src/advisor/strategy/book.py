"""策略卡状态机：草稿 → 模拟中 → 待晋级 → 已晋级 → 退役 / 回滚；任一阶段可拒绝。

- 改规则 = 追加新版本（带上一版本与改动理由），旧版本保留；
- 晋级只能由人批准（单人阶段如实标「自批」）；同一张卡只有一个已晋级版本；
- 回滚：当前已晋级版本标为已回滚，上一个晋级过的版本重新生效。
"""
from datetime import date, datetime, timezone
from typing import Callable

from advisor.graph.deps import Deps
from advisor.strategy.gates import promotion_gates
from advisor.strategy.models import STATUS_LABEL, NavPoint, StrategySpec, StrategyVersion
from advisor.strategy.paper import PaperBook, PaperError, nav_stats
from advisor.strategy.store import StrategyStore, spec_hash


class StrategyError(ValueError):
    pass


class StrategyBook:
    def __init__(self, deps: Deps, store: StrategyStore, open_alerts: Callable[[str], int] = lambda t: 0):
        self.deps = deps
        self.store = store
        self.paper = PaperBook(deps, store, open_alerts)
        self.cfg = deps.policy.strategy

    def _get(self, card_id: str, version: int, *allowed: str) -> StrategyVersion:
        v = self.store.get(card_id, version)
        if v is None:
            raise StrategyError(f"策略卡 {card_id} v{version} 不存在")
        if allowed and v.status not in allowed:
            raise StrategyError(f"{v.ref} 当前为「{STATUS_LABEL[v.status]}」，不能执行此操作")
        return v

    def _move(self, v: StrategyVersion, status: str, action: str, actor: str, detail: str, **extra) -> StrategyVersion:
        v = v.model_copy(update={"status": status, **{k: x for k, x in extra.items() if k in StrategyVersion.model_fields}})
        self.store.save(v)
        self.store.event(action, actor, v.card_id, v.version, detail,
                         **{k: x for k, x in extra.items() if k not in StrategyVersion.model_fields})
        return v

    def promoted(self, card_id: str) -> StrategyVersion | None:
        return next(iter(self.store.versions(card_id, ["promoted"])), None)

    # ---------- 新建 / 修订 ----------
    def create(self, spec: StrategySpec, actor: str, change_reason: str, card_id: str | None = None) -> StrategyVersion:
        parent = self.store.get(card_id) if card_id else None
        if card_id and parent is None:
            raise StrategyError(f"策略卡 {card_id} 不存在")
        sha = spec_hash(spec)
        if parent and spec_hash(parent) == sha:
            raise StrategyError("规则没有变化，不需要新版本")
        v = StrategyVersion(**spec.model_dump(), card_id=card_id or self.store.next_card_id(),
                            version=(parent.version + 1) if parent else 1, parent_version=parent.version if parent else None,
                            change_reason=change_reason, sha256=sha, created_by=actor, created_at=datetime.now(timezone.utc))
        self.store.insert(v)
        self.store.event("create", actor, v.card_id, v.version, change_reason)
        return v

    # ---------- 前向模拟 ----------
    def start_paper(self, card_id: str, version: int, actor: str, start: date | None = None) -> StrategyVersion:
        v = self._get(card_id, version, "draft")
        start = start or date.today()
        return self._move(v, "paper", "paper", actor, f"从 {start} 开始前向模拟（不回填历史）", paper_start=start)

    def step_all(self, day: date | None = None, log: Callable[[str], None] = lambda m: None) -> list[NavPoint]:
        day = day or date.today()
        out = []
        for v in self.store.versions(status=["paper", "review", "promoted"]):
            if v.paper_start and day < v.paper_start:
                continue
            try:
                p = self.paper.step(v, day)
            except PaperError as e:
                log(f"{v.ref}：{e}")
                continue
            log(f"{v.ref} {day} 净值 {p.nav:,.0f}，持仓 {len(p.positions)}")
            out.append(p)
        return out

    def stats(self, v: StrategyVersion) -> dict:
        return nav_stats(self.store.navs_of(v.card_id, v.version), self.paper.initial_cash)

    # ---------- 晋级 ----------
    def submit(self, card_id: str, version: int, actor: str) -> StrategyVersion:
        """跑晋级门控：全部通过进入待晋级；否则留在模拟中继续积累，门控结果记账。"""
        v = self._get(card_id, version, "paper")
        inc = self.promoted(card_id)
        gates = promotion_gates(v, self.store.navs_of(card_id, version), self.store.list_trades(card_id, version),
                                self.paper.initial_cash, self.cfg,
                                (inc, self.store.navs_of(card_id, inc.version)) if inc else None)
        failed = [g.label for g in gates if not g.passed]
        if failed:
            return self._move(v, "paper", "gates", actor, f"晋级门控未通过：{'、'.join(failed)}；继续模拟", gates=gates)
        return self._move(v, "review", "submit", actor, "晋级门控全部通过，等待人工批准", gates=gates)

    def approve(self, card_id: str, version: int, actor: str, note: str = "") -> StrategyVersion:
        v = self._get(card_id, version, "review")
        self_approved = any(e["action"] in ("create", "submit") and e["actor"] == actor
                            for e in self.store.list_events(card_id) if e["version"] == version)
        if inc := self.promoted(card_id):
            self._move(inc, "retired", "retire", actor, f"被 {v.ref} 取代")
        approvals = v.approvals + [{"actor": actor, "note": note, "self_approved": self_approved,
                                    "at": datetime.now(timezone.utc).isoformat()}]
        return self._move(v, "promoted", "promote", actor, note or "人工批准晋级", approvals=approvals,
                          self_approved=self_approved)

    def reject(self, card_id: str, version: int, actor: str, reason: str) -> StrategyVersion:
        v = self._get(card_id, version, "draft", "paper", "review")
        return self._move(v, "rejected", "reject", actor, reason, reject_reason=reason)

    def rollback(self, card_id: str, actor: str, reason: str) -> StrategyVersion:
        if len(reason.strip()) < 10:
            raise StrategyError("回滚理由不少于 10 个字")
        cur = self.promoted(card_id)
        if cur is None:
            raise StrategyError(f"{card_id} 没有已晋级版本")
        prev = next((v for v in self.store.versions(card_id, ["retired"]) if v.version < cur.version), None)
        self._move(cur, "rolled_back", "rollback", actor, reason)
        if prev:
            return self._move(prev, "promoted", "restore", actor, f"因回滚 {cur.ref} 重新生效")
        return cur.model_copy(update={"status": "rolled_back"})
