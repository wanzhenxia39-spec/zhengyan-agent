"""依赖容器：组装策略、Skill 注册中心、存储、模型与证据工厂。"""
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from advisor.evidence import EvidenceFactory
from advisor.harness import Budget, Harness, Policy, RunContext
from advisor.rsi import Ledger, RSILoader
from advisor.skills.compute.skills import build_compute_skills
from advisor.skills.data.ashare import AKShareSource, AShareSource
from advisor.skills.data.structured import build_structured_skills
from advisor.skills.data.valuation import build_valuation_skill
from advisor.skills.data.web import DeepSeekTools, build_web_skills
from advisor.skills.registry import SkillRegistry
from advisor.storage import Repository


@dataclass
class Deps:
    policy: Policy
    registry: SkillRegistry
    repo: Repository
    llm: Any
    factory: EvidenceFactory
    rsi: RSILoader | None = None
    ledger: Ledger | None = None
    decision: Any = None          # 决策小模型（Kev/Jev）；None 时路由只用大模型
    _task_caches: OrderedDict = field(default_factory=OrderedDict, repr=False)
    _cache_lock: Lock = field(default_factory=Lock, repr=False)

    MAX_CACHED_TASKS = 64

    def task_cache(self, task_id: str) -> dict:
        """任务级幂等缓存：同一研究任务里相同 Skill + 版本 + 参数只执行一次、只计一次费（进程内，LRU 保留最近 64 个任务）。"""
        with self._cache_lock:
            cache = self._task_caches.pop(task_id, None)
            if cache is None:
                cache = {}
            self._task_caches[task_id] = cache
            while len(self._task_caches) > self.MAX_CACHED_TASKS:
                self._task_caches.popitem(last=False)
            return cache

    def harness(self, task_id: str, route: str, as_of, budget: Budget, node: str = "", principal: str = "researcher",
                task_scoped_cache: bool = False) -> Harness:
        return Harness(
            policy=self.policy, registry=self.registry, audit=self.repo.append_audit, budget=budget,
            ctx=RunContext(task_id=task_id, route=route, as_of=as_of, node=node, principal=principal,
                           is_cancelled=lambda: self.repo.is_cancel_requested(task_id)),
            llm=self.llm, decision=self.decision,
            cache=self.task_cache(task_id) if task_scoped_cache else None,
        )


def build_deps(repo: Repository, llm: Any, policy: Policy, source: AShareSource | None = None,
               web_tools: Any = None, decision: Any = None) -> Deps:
    factory = EvidenceFactory(snapshot_sink=repo.put_snapshot)
    ledger = Ledger(repo.db)
    rsi = RSILoader(ledger, policy)
    source = source or AKShareSource(repo)
    registry = SkillRegistry(
        build_compute_skills()
        + build_structured_skills(source, factory)
        + [build_valuation_skill(source, factory)]
        + (build_web_skills(web_tools, repo, policy, params=rsi.search) if web_tools else [])
    )
    return Deps(policy=policy, registry=registry, repo=repo, llm=llm, factory=factory, rsi=rsi, ledger=ledger,
                decision=decision)


def build_default_deps() -> Deps:
    from advisor.llm import DecisionClient, DeepSeekClient
    from advisor.settings import get_settings
    from advisor.tracing import init_tracing

    init_tracing()
    s = get_settings()
    repo = Repository.connect(s.mongo_uri, s.mongo_db)
    policy = Policy.load(s.config_dir)
    tools = DeepSeekTools(s.deepseek_api_key, s.deepseek_base_url, qps=float(policy.search.get("qps", 4)))
    decision = DecisionClient(s.decision_base_url, s.decision_model, s.decision_api_key) if s.decision_base_url else None
    return build_deps(repo, DeepSeekClient(s), policy, web_tools=tools, decision=decision)
