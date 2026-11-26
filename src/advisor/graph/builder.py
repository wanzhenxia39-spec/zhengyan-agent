"""LangGraph 主图。

标准/快查：intake → authorize → route → plan → collect → search → draft → verify → quality_gate → commit
争议深研：intake → authorize → route → collect → team_plan ⇉ expert_round×N → blackboard → cross_exam → rebuttal → chair → deep_gate → commit
检查点升级：标准研究的 quality_gate 可把流程升级到 team_plan（复用已取证据，只升级一次）。
"""
from langgraph.graph import END, START, StateGraph

from advisor.graph.deep import DeepNodes
from advisor.graph.deps import Deps
from advisor.graph.state import ResearchState
from advisor.harness import TaskCancelled
from advisor.tracing import span


def _guard(name: str, fn, deps: Deps):
    """每个节点：先检查撤销，再在 span 内执行。"""
    def run(state):
        task_id = state["task_id"]
        if deps.repo.is_cancel_requested(task_id):
            raise TaskCancelled("任务已被取消")
        with span(f"node:{name}", task_id=task_id):
            return fn(state)
    run.__name__ = name
    return run


def _stop_if(*bad: str):
    def check(state: ResearchState) -> str:
        return "stop" if state.get("status") in bad else "go"
    return check


def build_graph(deps: Deps, checkpointer=None):
    n = DeepNodes(deps)
    g = StateGraph(ResearchState)
    for name in ("intake", "authorize", "route", "plan", "collect", "search", "draft", "verify", "quality_gate",
                 "team_plan", "expert_round", "blackboard", "cross_exam", "rebuttal", "chair", "deep_gate", "commit"):
        g.add_node(name, _guard(name, getattr(n, name), deps))

    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", _stop_if("failed"), {"go": "authorize", "stop": END})
    g.add_conditional_edges("authorize", _stop_if("cancelled"), {"go": "route", "stop": END})
    g.add_conditional_edges("route", lambda s: "collect" if s["route"] == "deep" else "plan",
                            {"collect": "collect", "plan": "plan"})
    g.add_edge("plan", "collect")
    g.add_conditional_edges(
        "collect",
        lambda s: "stop" if s.get("status") == "failed" else ("team_plan" if s["route"] == "deep" else "search"),
        {"stop": END, "team_plan": "team_plan", "search": "search"},
    )
    g.add_edge("search", "draft")
    g.add_conditional_edges("draft", _stop_if("failed"), {"go": "verify", "stop": END})
    g.add_edge("verify", "quality_gate")
    g.add_conditional_edges(
        "quality_gate",
        lambda s: {"need_more": "plan", "escalate": "team_plan"}.get(s["quality"].get("next"), "commit"),
        {"plan": "plan", "team_plan": "team_plan", "commit": "commit"},
    )
    # 深研
    g.add_conditional_edges("team_plan", n.dispatch, ["expert_round"])
    g.add_edge("expert_round", "blackboard")
    g.add_conditional_edges("blackboard", n.after_blackboard, {"cross_exam": "cross_exam", "chair": "chair"})
    g.add_edge("cross_exam", "rebuttal")
    g.add_edge("rebuttal", "chair")
    g.add_conditional_edges("chair", _stop_if("failed"), {"go": "deep_gate", "stop": END})
    g.add_edge("deep_gate", "commit")
    g.add_edge("commit", END)
    return g.compile(checkpointer=checkpointer)
