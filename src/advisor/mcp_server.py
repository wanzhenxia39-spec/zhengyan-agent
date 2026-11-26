"""FastMCP：把只读 Skill 暴露给外部 Agent。调用同样经过 Harness（mcp 流程白名单与预算）。"""
from datetime import date

from fastmcp import FastMCP

from advisor.graph.deps import build_default_deps
from advisor.harness import Budget


def build_server() -> FastMCP:
    deps = build_default_deps()
    mcp = FastMCP("stock-advisor-skills")

    def call(skill: str, **args):
        as_of = args.get("as_of") or date.today()
        budget = Budget(limits=deps.policy.route("mcp").budget)
        h = deps.harness("mcp", "mcp", as_of, budget)
        return h.call(skill, **args).model_dump(mode="json")

    @mcp.tool
    def financial_statements(code: str, as_of: date) -> dict:
        """as_of 时点已披露的 A 股利润表/现金流量表（A 级证据卡）。"""
        return call("financials.statements", code=code, as_of=as_of)

    @mcp.tool
    def market_daily(code: str, as_of: date) -> dict:
        """as_of 前的日线行情统计。"""
        return call("market.daily", code=code, as_of=as_of)

    @mcp.tool
    def announcements(code: str, as_of: date) -> dict:
        """as_of 前的巨潮公告标题。"""
        return call("announcements.list", code=code, as_of=as_of)

    @mcp.tool
    def web_search(query: str, as_of: date) -> dict:
        """时点约束的网页搜索（结果只是线索）。"""
        return call("web.search", query=query, as_of=as_of)

    return mcp
