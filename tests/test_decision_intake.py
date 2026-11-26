"""意图识别切换到决策小模型：小模型优先，识别不到代码或小模型不可用时退回大模型；交易意图规则始终生效。"""
from advisor.graph.deps import build_deps
from advisor.graph.nodes import Nodes
from tests.fakes import CODE, NAME, FakeDecision, FakeLLM, FakeSource, FakeWebTools, as_of


def _intake(repo, policy, question, decision, llm=None):
    llm = llm or FakeLLM()
    deps = build_deps(repo, llm, policy, source=FakeSource(), web_tools=FakeWebTools(), decision=decision)
    out = Nodes(deps).intake({"task_id": "t-intake", "question": question, "as_of": as_of().isoformat()})
    return out, llm


def _llm_intake_calls(llm):
    return [n for _, n in llm.calls if n == "IntakeOut"]


def test_intake_uses_small_model_when_code_present(repo, policy):
    dec = FakeDecision(intent="explain")
    out, llm = _intake(repo, policy, f"{CODE} 最新一期利润质量和现金流怎么样", dec)
    assert out["ticker"] == CODE and out["intent"] == "explain"
    assert out["focus"] == "利润质量、现金流"                     # "利润"被"利润质量"包含，去掉
    assert dec.calls and not _llm_intake_calls(llm)              # 没有调大模型


def test_intake_finds_code_from_known_dossier_name(repo, policy):
    repo.db.dossiers.insert_one({"key": CODE, "ticker": CODE, "name": NAME, "version": 1})
    out, llm = _intake(repo, policy, f"{NAME}最近业绩怎么样", FakeDecision())
    assert out["ticker"] == CODE and out["company_name"] == NAME and not _llm_intake_calls(llm)


def test_intake_falls_back_to_llm(repo, policy):
    out, llm = _intake(repo, policy, "茅台最近业绩怎么样", FakeDecision())          # 无代码、无已知档案 → 大模型
    assert _llm_intake_calls(llm)
    out2, llm2 = _intake(repo, policy, f"{CODE} 业绩", FakeDecision(fail=True))      # 小模型挂了 → 大模型
    assert out2["ticker"] == CODE and _llm_intake_calls(llm2)


def test_trade_rule_overrides_small_model(repo, policy):
    for q in (f"以市价卖出 300 股 {CODE}", f"把 {CODE} 仓位降到三成"):
        out, _ = _intake(repo, policy, q, FakeDecision(intent="research"))
        assert out["intent"] == "trade_execution", q
    out, _ = _intake(repo, policy, f"{CODE} 现在适合加仓吗", FakeDecision(intent="research"))
    assert out["intent"] == "research"                           # 提问不是下单
