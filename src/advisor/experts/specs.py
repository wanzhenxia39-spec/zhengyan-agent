"""专家不是固定名单，而是按证据缺口动态召集的能力。每个专家有职责、约束、可见证据范围。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ExpertSpec:
    key: str
    name: str
    mandate: str
    constraint: str
    scope: tuple[str, ...]          # 首轮可见的结构化证据类型（共享事实快照）
    query_hint: str = ""
    searches: bool = True


EXPERTS: dict[str, ExpertSpec] = {s.key: s for s in [
    ExpertSpec("fundamental", "基本面研究员", "财报、盈利质量、经营趋势与假设核验",
               "只在同口径、同报告期上比较；不做估值判断", ("filing", "calc", "announcement"),
               "最新业绩、经营变化、管理层解释"),
    ExpertSpec("industry", "行业/产业链研究员", "景气度、上下游、竞争格局与共同因素",
               "区分相关与因果；行业判断必须注明来源", ("calc",), "行业景气、竞争格局、上下游价格"),
    ExpertSpec("valuation", "估值研究员", "估值水平、假设显式化、情景与敏感性",
               "默认假设必须写成 assumption；不给目标价；情景只能引用系统计算的估值情景",
               ("filing", "calc", "market"), "机构估值观点、市场一致预期"),
    ExpertSpec("technical", "技术与资金面研究员", "量价、波动、流动性与交易结构",
               "只描述状态，不单独推出买卖结论", ("market", "calc"), searches=False),
    ExpertSpec("event", "事件/新闻研究员", "事件聚类、增量识别、影响到哪项假设",
               "事件簇去重，不把转载数当证据数", ("announcement",), "近期公告、重大事件、监管动态"),
    ExpertSpec("risk", "风险审阅专家", "风险情景、数据质量与口径风险、行动边界",
               "提出风险与升级建议；硬阻断由 Harness 执行，不由你决定", ("filing", "calc", "market", "announcement"),
               "风险、诉讼、监管处罚、减持"),
    ExpertSpec("red_team", "反证官（红方）", "主动寻找替代解释、反例与逻辑漏洞",
               "首轮隔离取证，只写自己的候选；质询阶段才读取待反驳主张",
               ("filing", "calc", "market", "announcement"), "负面、质疑、做空、下调评级、风险"),
]}

SELECTABLE = [k for k in EXPERTS if k != "red_team"]
CHAIR_NAME = "综合主席"
