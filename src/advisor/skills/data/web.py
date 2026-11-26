"""DeepSeek Search / Fetch：只作为线索发现层。结果须经过滤、分级、快照后才成为证据。"""
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from advisor.contracts import SearchHit
from advisor.contracts.skill import Skill, SkillSpec
from advisor.harness.errors import SkillFailed
from advisor.harness.ratelimit import TokenBucket
from advisor.storage import Repository

MAX_QUERY = 128


class DeepSeekTools:
    """Search 与 Fetch 各自账号级 5 QPS，这里各留余量。"""

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", qps: float = 4, timeout: float = 30):
        self._http = httpx.Client(base_url=base_url, timeout=timeout,
                                  headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        self._search_bucket = TokenBucket(qps)
        self._fetch_bucket = TokenBucket(qps)

    def _post(self, path: str, payload: dict, bucket: TokenBucket) -> dict[str, Any]:
        bucket.acquire()
        try:
            resp = self._http.post(path, json=payload)
        except httpx.TransportError as e:
            raise SkillFailed(f"网络错误: {e}", retryable=True) from e
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 402:
            raise SkillFailed("DeepSeek 余额不足（402），请充值后重试", retryable=False)
        retryable = resp.status_code in (408, 429) or resp.status_code >= 500
        raise SkillFailed(f"{path} HTTP {resp.status_code}: {resp.text[:200]}", retryable=retryable)

    def search(self, query: str, count: int) -> list[dict[str, Any]]:
        return self._post("/v1/tools/search", {"query": query, "count": count}, self._search_bucket).get("results", [])

    def fetch(self, url: str) -> dict[str, Any]:
        return self._post("/v1/tools/fetch", {"url": url}, self._fetch_bucket)


def host_matches(url: str, domains: tuple[str, ...]) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in domains)


def fetch_allowlist(policy, params: dict) -> tuple[str, ...]:
    """抓取白名单 = sites.yaml + RSI 检索模板里经人工批准追加的站点（只能追加，不能删减黑名单）。"""
    extra = tuple(d for d in params.get("fetch_allow_add", []) if d not in policy.block_sites)
    return policy.fetch_allow + extra


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=80)
    as_of: date
    count: int = Field(default=10, ge=1, le=20)
    lookback_days: int = Field(default=120, ge=1, le=730)


class SearchOut(BaseModel):
    final_query: str
    hits: list[SearchHit]
    dropped: dict[str, int]


class FetchIn(BaseModel):
    url: str = Field(max_length=2000, pattern=r"^https?://")


class FetchOut(BaseModel):
    url: str
    title: str
    content: str


def build_query(query: str, as_of: date, lookback_days: int, block: tuple[str, ...]) -> str:
    """强制时点：after/before 包住 as_of；黑名单在长度允许时用 -site: 排除（结果侧还会再过滤）。"""
    q = f"{query} after:{as_of - timedelta(days=lookback_days)} before:{as_of + timedelta(days=1)}"
    for site in block:
        extra = f" -site:{site}"
        if len(q) + len(extra) > MAX_QUERY:
            break
        q += extra
    return q


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_web_skills(tools: DeepSeekTools, repo: Repository | None, policy, params=None) -> list[Skill]:
    params = params or (lambda: policy.search)      # RSI 检索模板：运行时读取在用版本
    ttl = float(policy.search.get("cache_ttl_hours", 24))

    def search(inp: SearchIn) -> SearchOut:
        rerank_min = float(params().get("rerank_min", 1.5))
        final_query = build_query(inp.query, inp.as_of, inp.lookback_days, policy.block_sites)
        key = f"ds:search:{inp.as_of}:{inp.count}:{final_query}"
        raw = repo.cache_get(key) if repo else None
        if raw is None:
            raw = tools.search(final_query, inp.count)
            if repo:
                repo.cache_set(key, raw, ttl)
        hits, dropped = [], {"blocked_site": 0, "after_as_of": 0, "low_relevance": 0}
        for r in raw:
            hit = SearchHit(
                title=r.get("title") or "", url=r.get("url") or "", site_name=r.get("site_name"),
                date=_parse_date(r.get("date")), authority=int(r["authority"]) if r.get("authority") is not None else -1,
                rerank_score=float(r.get("rerank_score") or 0), summary=r.get("summary") or "",
                snippet=r.get("snippet") or "", query=inp.query,
            )
            if not hit.url or host_matches(hit.url, policy.block_sites):
                dropped["blocked_site"] += 1
            elif hit.date and hit.date.date() > inp.as_of:
                dropped["after_as_of"] += 1
            elif hit.rerank_score < rerank_min:
                dropped["low_relevance"] += 1
            else:
                hits.append(hit)
        return SearchOut(final_query=final_query, hits=hits, dropped=dropped)

    def fetch(inp: FetchIn) -> FetchOut:
        if not host_matches(inp.url, fetch_allowlist(policy, params())):
            raise SkillFailed(f"域名不在抓取白名单: {urlparse(inp.url).netloc}")
        data = tools.fetch(inp.url)
        return FetchOut(url=inp.url, title=data.get("title") or "", content=data.get("content") or "")

    return [
        Skill(spec=SkillSpec(name="web.search", version="1.0.0", category="data", permission="read",
                             description="DeepSeek 网页搜索（强制 as_of 时点约束、站点黑名单、相关度过滤）",
                             input_model=SearchIn, output_model=SearchOut, timeout_s=40, egress_fields=("query",),
                             budget_kind="search_calls"), run=search),
        Skill(spec=SkillSpec(name="web.fetch", version="1.0.0", category="data", permission="read",
                             description="DeepSeek 网页抓取（仅白名单域名）", input_model=FetchIn, output_model=FetchOut,
                             timeout_s=40, budget_kind="fetch_calls"), run=fetch),
    ]
