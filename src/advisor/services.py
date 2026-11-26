"""应用服务容器：API 与命令行共用同一套组装方式。

research  研究任务（主图、人在环、取消）
rsi       受控自进化
profiles  用户确认档案（只有用户确认这一条写入路径）
watch     事件订阅与增量复核
strategy  策略卡与前向模拟盘
"""
from dataclasses import dataclass, field

from advisor.graph.deps import Deps
from advisor.graph.runner import ResearchService
from advisor.personal import ProfileStore
from advisor.rsi import RSIRunner
from advisor.strategy import StrategyBook, StrategyStore
from advisor.watch import Watcher, WatchStore


@dataclass
class Services:
    deps: Deps
    research: ResearchService
    rsi: RSIRunner = field(init=False)
    profiles: ProfileStore = field(init=False)
    watch: Watcher = field(init=False)
    strategy: StrategyBook = field(init=False)

    def __post_init__(self):
        db = self.deps.repo.db
        self.rsi = RSIRunner(self.deps, self.deps.ledger, self.deps.rsi)
        self.profiles = ProfileStore(db)
        self.watch = Watcher(self.deps, WatchStore(db))
        self.strategy = StrategyBook(self.deps, StrategyStore(db), open_alerts=self.open_alert_count)

    def confirm_profile(self, data, actor: str, confirmed: bool):
        """保存新版本约束，并标出哪些档案的个人情境结论因此改变（个人信息只在本地比对）。"""
        from advisor.personal import profile_impact
        prev = self.profiles.current()
        v = self.profiles.confirm(data, actor, confirmed)
        repo = self.deps.repo
        impact = []
        for row in repo.list_dossiers():
            d = repo.get_dossier(row["key"])
            if d is None:
                continue
            sub = self.watch.store.get_sub(d.ticker)
            alerts = [(a.id, "、".join(e.title for e in a.events)) for a in self.watch.store.list_alerts(d.ticker, "open")]
            if hit := profile_impact(d, repo.get_evidence(d.evidence_ids), prev, v, bool(sub and sub.active), alerts):
                impact.append(hit)
        self.profiles.set_impact(v.version, impact)
        v.impact = impact
        return v

    def open_alert_count(self, ticker: str) -> int:
        return len(self.watch.store.list_alerts(ticker, "open"))

    def submit(self, fn, *args):
        return self.research.submit(fn, *args)


def build_services(deps: Deps | None = None, checkpointer=None) -> Services:
    if deps is None:
        from langgraph.checkpoint.mongodb import MongoDBSaver

        from advisor.graph.deps import build_default_deps
        deps = build_default_deps()
        checkpointer = MongoDBSaver(deps.repo.db.client, db_name=f"{deps.repo.db.name}_checkpoints")
    return Services(deps, ResearchService(deps, checkpointer))
