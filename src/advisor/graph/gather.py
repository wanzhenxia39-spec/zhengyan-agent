"""搜索子系统流水线（单 Agent 与各专家共用）：搜索 → 过滤 → 聚类去转载 → 白名单抓取 → 清洗 → 分级 → 快照。"""
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from advisor.contracts import EvidenceCard, SearchHit
from advisor.evidence import assign_clusters, extract_publisher, grade_web, origin_id, sanitize
from advisor.harness import BudgetExceeded, HarnessDenied, SkillFailed
from advisor.skills.data.web import fetch_allowlist, host_matches


@dataclass
class GatherResult:
    cards: list[EvidenceCard] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    hits: int = 0
    clusters: int = 0
    fetched: int = 0


def gather_web(h, deps, queries: list[str], as_of: date, route: str, max_fetch: int,
               log: Callable[[str], None] = lambda m: None) -> GatherResult:
    cfg = deps.rsi.search() if deps.rsi else deps.policy.search
    res = GatherResult()
    hits: list[SearchHit] = []
    for q in queries:
        try:
            out = h.call("web.search", query=q, as_of=as_of, count=10, lookback_days=int(cfg.get("lookback_days", 120)))
            hits.extend(out.hits)
            res.searched.append(q)
        except BudgetExceeded as e:
            res.unknowns.append(f"搜索预算耗尽，未执行：{q}")
            log(str(e))
            break
        except (SkillFailed, HarnessDenied) as e:
            res.unknowns.append(f"搜索失败：{q}（{e}）")
    clusters = assign_clusters(hits)
    reps: dict[str, SearchHit] = {}
    sizes: dict[str, int] = {}
    for hit in sorted(hits, key=lambda x: (-x.authority, -x.rerank_score)):
        cid = clusters[hit.url]
        sizes[cid] = sizes.get(cid, 0) + 1
        reps.setdefault(cid, hit)
    b_min = int(cfg.get("authority_b_min", 3))
    can_fetch = deps.policy.is_allowed(route, "web.fetch")
    allow = fetch_allowlist(deps.policy, cfg)
    to_fetch = [
        hit for hit in reps.values()
        if can_fetch and hit.authority >= b_min and hit.date is not None and host_matches(hit.url, allow)
    ][:max_fetch]
    fetched: dict[str, str] = {}
    for hit in to_fetch:
        try:
            fetched[hit.url] = h.call("web.fetch", url=hit.url).content
        except BudgetExceeded:
            break
        except (SkillFailed, HarnessDenied) as e:
            log(f"一篇网页原文没读到（{hit.url}），跳过：{e}")
    for cid, hit in reps.items():
        raw = fetched.get(hit.url)
        content, sus_c = sanitize(raw or hit.summary or hit.snippet, max_chars=20000)
        excerpt, sus_e = sanitize(hit.summary or hit.snippet or content, max_chars=800)
        level, caveats = grade_web(hit, raw is not None, as_of, b_min)
        if sus_c or sus_e:
            level = "C"
            caveats.append("检测到疑似指令文本，已剔除并降为线索")
        if sizes[cid] > 1:
            caveats.append(f"同一事件另有 {sizes[cid] - 1} 篇相似/转载报道，未计为独立证据")
        card = deps.factory.make(
            content=content, level=level, source_type="web", title=hit.title, source_url=hit.url,
            site_name=hit.site_name, origin_id=origin_id(hit.url),
            origin_publisher=extract_publisher(hit.summary, hit.site_name), cluster_id=cid,
            published_at=hit.date, as_of=as_of, pit="weak", excerpt=excerpt, authority=hit.authority,
            rerank_score=hit.rerank_score, caveats=caveats, skill="web.search", skill_version="1.0.0",
        )
        deps.repo.put_evidence(card)
        res.cards.append(card)
    res.hits, res.clusters, res.fetched = len(hits), len(reps), len(fetched)
    return res
