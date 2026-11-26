"""RSI S3：专家搜索侧重的进化、抓取站点名单（高风险，批准须写理由）、防过拟合门控的行业专用词检测。"""
from datetime import datetime, timezone

import pytest

from advisor.experts.schemas import ExpertQueries
from advisor.graph.deps import build_deps
from advisor.rsi import RSIRunner, TransitionError
from advisor.rsi.gates import overfit_gate
from advisor.rsi.models import Run
from advisor.rsi.proposer import HintDraft
from advisor.skills.data.web import fetch_allowlist
from tests.fakes import FakeLLM, FakeSource

NEW_HINT = "公司公告、交易所披露原文、主流财经媒体报道"
SITE = "data.authority-site.cn"


class S3LLM(FakeLLM):
    def json(self, role, system, user, schema):
        if schema is HintDraft:
            self.calls.append((role, "HintDraft"))
            return HintDraft(hint=NEW_HINT, rationale="偏向能抓取的原文"), 50
        if schema is ExpertQueries:      # 搜索侧重写了「公告」才会生成指向公告原文的搜索词
            company = user.split("公司：")[1].split("（")[0]
            return ExpertQueries(queries=[f"{company} {'公告原文' if '公告' in system else '业绩 传闻'}"]), 20
        return super().json(role, system, user, schema)


class S3Web:
    def __init__(self):
        self.searches: list[str] = []

    def search(self, query, count):
        self.searches.append(query)
        if "公告原文" in query:
            return [{"title": f"公告{i}", "url": f"https://www.cninfo.com.cn/a/{i}", "authority": 5,
                     "rerank_score": 2.5, "date": "2026-08-01T00:00:00+00:00", "summary": "公告"} for i in range(5)]
        return [{"title": f"传闻{i}", "url": f"https://www.example-blog.com/p/{i}", "authority": 1,
                 "rerank_score": 2.0, "date": "2026-08-01T00:00:00+00:00", "summary": "传闻"} for i in range(5)]

    def fetch(self, url):
        return {"title": "正文", "content": "正文"}


def _dossier(key, name, queries):
    return {"key": key, "version": 1, "ticker": key, "name": name, "as_of": "2026-10-16", "question": "q", "route": "deep",
            "status": "committed", "summary": "", "unknowns": [], "dissents": [], "review_triggers": [], "evidence_ids": [],
            "quality": {}, "boundary_notes": [], "task_id": "t", "created_at": datetime.now(timezone.utc), "clue_ids": [],
            "claims": [], "deliberation": {"team": [{"expert": "fundamental", "queries": queries,
                                                     "brief": ["业绩是否放缓？"], "claims": []}]}}


def _cache(repo, query, rows):
    repo.db.cache.insert_one({"key": f"ds:search:2026-10-16:10:{query} after:2026-06-18 before:2026-10-17",
                              "value": rows, "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc)})


@pytest.fixture
def s3(repo, policy):
    repo.db.dossiers.insert_many([_dossier("600001", "甲公司", ["甲公司 业绩 传闻"]), _dossier("000002", "乙公司", [])])
    _cache(repo, "甲公司 业绩 传闻", [{"title": f"传闻{i}", "url": f"https://www.example-blog.com/q/{i}", "authority": 1,
                                   "rerank_score": 2.0} for i in range(12)])
    for k in range(9):      # 白名单外、几乎全是权威结果的站点，分散在多次搜索里
        _cache(repo, f"行业动态 {k}", [{"title": f"数据{k}-{i}", "url": f"https://{SITE}/n/{k}{i}", "authority": 4,
                                    "rerank_score": 2.0} for i in range(2)])
    deps = build_deps(repo, S3LLM(), policy, source=FakeSource(), web_tools=S3Web())
    runner = RSIRunner(deps, deps.ledger, deps.rsi)
    runner.collect()
    return deps, runner


def test_collect_finds_weak_expert_queries_and_site_gap(s3):
    _, runner = s3
    kinds = {i.kind: i for i in runner.ledger.list_issues("S3")}
    assert kinds["expert_query_weak"].source["expert"] == "fundamental"
    assert kinds["expert_query_weak"].source["usable_rate"] == 0
    assert kinds["site_gap"].source["host"] == SITE


def test_hint_evolution_released_and_used_by_experts(s3):
    deps, runner = s3
    run = runner.propose("S3")
    assert run.diff["hint"]["expert"] == "fundamental" and run.diff["hint"]["new"] == NEW_HINT and run.risk == "normal"
    run = runner.evaluate(run.run_id)
    assert run.status == "review", run.reject_reason
    assert run.eval["arms"]["cand"]["slices"]["evolution"]["mean"] > run.eval["arms"]["base"]["slices"]["evolution"]["mean"]
    assert run.eval["leakage"] == {"evolution": ["600001"], "holdout": ["000002"]}
    runner.approve(run.run_id, "owner")
    runner.release(run.run_id, "owner")
    assert deps.rsi.expert_hint("fundamental", "旧") == NEW_HINT


def test_site_change_is_high_risk_and_needs_written_reason(s3, policy):
    deps, runner = s3
    issue = next(i for i in runner.ledger.list_issues("S3") if i.kind == "site_gap")
    run = runner.propose("S3", issue.id)
    assert run.risk == "high" and run.diff == {"sites": {"add": [SITE]}}
    run = runner.evaluate(run.run_id)
    assert run.status == "review", run.reject_reason
    with pytest.raises(TransitionError, match="理由"):
        runner.approve(run.run_id, "owner", "")
    runner.approve(run.run_id, "owner", "该站点为权威数据发布方，已人工抽查")
    runner.release(run.run_id, "owner")
    assert SITE in fetch_allowlist(policy, deps.rsi.search())


def _lesson_run(applies_to: str, lesson: str) -> Run:
    now = datetime.now(timezone.utc)
    card = {"id": "L-001", "title": "先排除替代解释", "applies_to": applies_to, "tags": ["说明"], "lesson": lesson}
    return Run(run_id="r", scenario="S1", kind="lessons", issue_ids=[], base_version=1, content={},
               diff={"cards": [card]}, change_reason="测试行业专用词检测用例", direction="d", created_at=now, updated_at=now)


def test_overfit_gate_flags_undeclared_industry_terms(s3):
    _, runner = s3
    generic = _lesson_run("消费品公司存货大幅变动", "存货上升时先区分基酒储备与渠道压货")
    g = overfit_gate(generic, {}, runner.ledger)
    assert not g.passed and "白酒" in g.detail and "基酒" in g.detail
    declared = _lesson_run("白酒企业存货大幅变动", "存货上升时先区分基酒储备与渠道压货")
    assert overfit_gate(declared, {}, runner.ledger).passed
