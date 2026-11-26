export const STATUS_LABEL: Record<string, string> = {
  queued: "排队中", running: "运行中", awaiting_approval: "等待审批", cache_hit: "缓存命中", waiting_approval: "等待你确认", done: "已完成",
  failed: "失败", cancelled: "已取消", committed: "已通过质量门控", partial: "部分结论",
  verified: "已核验", disputed: "存疑", rejected: "驳回", candidate: "待核验", stale: "待复核",
};
export const KIND_LABEL: Record<string, string> = { fact: "事实", inference: "推断", assumption: "假设", scenario: "情景" };
export const NODE_LABEL: Record<string, string> = {
  intake: "理解问题", authorize: "安全检查", route: "选择研究方式", plan: "规划搜索", collect: "读取财报与行情",
  search: "搜索资讯", draft: "撰写结论", verify: "核对数据", quality_gate: "质量检查", commit: "保存档案", runner: "系统",
  team_plan: "组建专家组", blackboard: "汇总观点", cross_exam: "反证质疑", rebuttal: "专家回应", chair: "主席汇总",
  deep_gate: "质量检查", approval: "人工确认", watch: "订阅扫描",
};
export const ROUTE_LABEL: Record<string, string> = { quick: "快查", standard: "标准研究", deep: "争议深研" };
export const SOURCE_ROUTE: Record<string, string> = {
  user: "你指定的", rule: "按规则", model: "系统判断", abstain: "拿不准，选稳妥方式", escalation: "中途升级", fallback: "默认方式",
};
export const LEVEL_LABEL: Record<string, string> = { low: "低", mid: "中", high: "高" };
export const ROLE_LABEL: Record<string, string> = { reason: "深度推理", draft: "快速生成", classify: "快速判断" };
export const BUDGET_LABEL: Record<string, string> = {
  tokens: "模型用量（tokens）", search_calls: "搜索次数", fetch_calls: "读取网页原文次数", llm_calls: "模型调用次数",
};
export const MODE_LABEL: Record<string, string> = { map_reduce: "各自取证后汇总", debate: "专家互相质疑", committee: "投资委员会讨论" };
export const VERDICT_LABEL: Record<string, string> = {
  upheld: "质询成立", rejected: "质询不成立", unresolved: "未决",
  retained: "保留", weakened: "削弱", invalidated: "失效", unverifiable: "无法判断",
};
export const STANCE_LABEL: Record<string, string> = { concede: "承认", rebut: "反驳", revise: "修正" };
export const CHALLENGE_KIND: Record<string, string> = {
  counter_evidence: "反面证据", alternative_explanation: "替代解释", logic_gap: "逻辑漏洞", data_basis: "口径/数据",
};
export const EXPERT_LABEL: Record<string, string> = {
  fundamental: "基本面", industry: "行业", valuation: "估值", technical: "技术面", event: "事件", risk: "风险", red_team: "反证官",
};
export function nodeLabel(node: string) {
  if (node.startsWith("expert:")) return "专家·" + (EXPERT_LABEL[node.slice(7)] ?? node.slice(7));
  return NODE_LABEL[node] ?? node;
}
export const SOURCE_LABEL: Record<string, string> = {
  filing: "财报", market: "行情", announcement: "公告", web: "网页", calc: "计算",
};

export function fmtTime(s?: string | null) {
  if (!s) return "—";
  const d = new Date(s.endsWith("Z") || s.includes("+") ? s : s + "Z");
  return d.toLocaleString("zh-CN", { hour12: false });
}

export function fmtDate(s?: string | null) {
  return s ? s.slice(0, 10) : "未知";
}

export function fmtMetric(value: string, unit: string) {
  const n = Number(value);
  if (unit === "元" && Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)} 亿元`;
  return `${value}${unit === "%" ? "%" : " " + unit}`;
}

export function today() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

/** 系统生成的文字里夹带的内部代号 → 页面显示的中文名（存档原文不变）。 */
export const TERM_LABEL: Record<string, string> = {
  fundamental: "基本面研究员", industry: "行业/产业链研究员", valuation: "估值研究员", technical: "技术与资金面研究员",
  event: "事件/新闻研究员", risk: "风险审阅专家", red_team: "反证官",
  quick: "快查", standard: "标准研究", deep: "争议深研",
  temperature: "校准温度", abstain_below: "拒判阈值",
  evolution: "新失败集", replay: "固定回放集", holdout: "留出集",
  lessons: "经验库", routing: "路由参数", search: "检索模板",
  parent: "基于", sha256: "校验码", token: "模型用量",
  challenge_upheld: "质询成立", verify_disputed: "核验存疑", route_mislabel: "研究方式选错",
  expert_query_weak: "专家搜索词不好用", low_quality_search: "搜索结果质量低", site_gap: "缺少可读取的网站",
  owner: "你", optimizer: "优化器", evaluator: "评测器", gates: "门控", system: "系统",
};
const TERM_RE = new RegExp(`(?<![\\w./:-])(${Object.keys(TERM_LABEL).join("|")})(?![\\w./:-])`, "g");
export function zh(text: string | null | undefined): string {
  if (!text) return "";
  return text.replace(TERM_RE, (w) => TERM_LABEL[w])
    .replace(/门禁/g, "门控").replace(/(质量|噪声|成本|回归|审批)门(?!控)/g, "$1门控");
}
