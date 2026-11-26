from datetime import date

import httpx
import pytest
import respx

from advisor.harness import SkillFailed
from advisor.skills.data.web import DeepSeekTools, build_query, build_web_skills
from tests.fakes import FakeWebTools

AS_OF = date(2026, 10, 18)


def test_build_query_enforces_time_and_length(policy):
    q = build_query("示例酒业 业绩", AS_OF, 120, policy.block_sites)
    assert "before:2026-10-19" in q and "after:2026-06-20" in q and len(q) <= 128


def test_search_filters(policy, repo):
    web = FakeWebTools()
    search = {s.spec.name: s for s in build_web_skills(web, repo, policy)}["web.search"]
    out = search.run(search.spec.input_model(query="示例酒业 业绩", as_of=AS_OF))
    urls = {h.url for h in out.hits}
    assert "https://guba.eastmoney.com/x" not in urls                # 黑名单
    assert "https://www.cls.cn/f" not in urls                       # 晚于 as_of
    assert "https://www.yicai.com/n" not in urls                    # 低相关
    assert out.dropped == {"blocked_site": 1, "after_as_of": 1, "low_relevance": 1}
    search.run(search.spec.input_model(query="示例酒业 业绩", as_of=AS_OF))
    assert len(web.searches) == 1                                   # 第二次命中缓存


def test_fetch_whitelist(policy, repo):
    fetch = {s.spec.name: s for s in build_web_skills(FakeWebTools(), repo, policy)}["web.fetch"]
    with pytest.raises(SkillFailed, match="白名单"):
        fetch.run(fetch.spec.input_model(url="https://www.example-blog.com/p"))
    assert fetch.run(fetch.spec.input_model(url="https://www.stcn.com/a/1.html")).content


@respx.mock
def test_http_error_mapping():
    tools = DeepSeekTools("k", qps=100)
    respx.post("https://api.deepseek.com/v1/tools/search").mock(side_effect=[
        httpx.Response(429, text="slow down"), httpx.Response(402, text="no money"),
        httpx.Response(200, json={"results": [{"title": "t"}]}),
    ])
    with pytest.raises(SkillFailed) as e1:
        tools.search("q", 5)
    assert e1.value.retryable
    with pytest.raises(SkillFailed) as e2:
        tools.search("q", 5)
    assert not e2.value.retryable and "余额" in str(e2.value)
    assert tools.search("q", 5) == [{"title": "t"}]


def test_fetch_url_with_long_digits_not_treated_as_sensitive(policy, repo):
    from advisor.harness import Budget, Harness, RunContext
    from advisor.skills.registry import SkillRegistry

    h = Harness(policy, SkillRegistry(build_web_skills(FakeWebTools(), repo, policy)), lambda r: None,
                Budget(limits={"fetch_calls": 1, "wall_clock_s": 60}), RunContext("t", "standard", AS_OF))
    assert h.call("web.fetch", url="https://data.eastmoney.com/report/info/AP202608161828030058.html").content
