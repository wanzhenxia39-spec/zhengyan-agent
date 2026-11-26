import type { NavPoint, Rule } from "../types";

export const STRATEGY_GATES: [string, string, string][] = [
  ["forward", "前向时长", "至少前向模拟规定的交易日数"], ["lookahead", "无未来数据", "每笔成交只用当天可见的档案与行情"],
  ["drawdown", "回撤上限", "模拟净值最大回撤不超过卡片上限"], ["explain", "可解释", "每笔纳入都能追溯到档案版本与证据"],
  ["regression", "不退化", "与在用版本同期对比，收益不落后超过容忍度"],
];
export const OPS: Rule["op"][] = [">=", ">", "<=", "<", "==", "!="];

export function RuleChips({ rules, fields, empty = "—" }: { rules: Rule[]; fields: Record<string, string>; empty?: string }) {
  if (!rules.length) return <span className="muted small">{empty}</span>;
  return (
    <span className="rule-chips">
      {rules.map((r, i) => <span key={i} className="tag">{fields[r.field] ?? r.field} {r.op} {String(r.value)}</span>)}
    </span>
  );
}

/** 规则编辑：字段 / 比较 / 阈值，一行一条。 */
export function RuleEditor({ rules, fields, onChange }: { rules: Rule[]; fields: Record<string, string>; onChange: (r: Rule[]) => void }) {
  const set = (i: number, patch: Partial<Rule>) => onChange(rules.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  return (
    <div className="form" style={{ gap: 6 }}>
      {rules.map((r, i) => (
        <div key={i} className="rule-row">
          <select value={r.field} onChange={(e) => set(i, { field: e.target.value })}>
            {Object.entries(fields).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
          </select>
          <select value={r.op} onChange={(e) => set(i, { op: e.target.value as Rule["op"] })}>{OPS.map((o) => <option key={o}>{o}</option>)}</select>
          <input value={String(r.value)} onChange={(e) => set(i, { value: r.field === "status" ? e.target.value : e.target.value === "" ? "" : Number(e.target.value) })} />
          <button className="ghost" onClick={() => onChange(rules.filter((_, k) => k !== i))} aria-label="删除规则">删除</button>
        </div>
      ))}
      <button className="ghost" style={{ alignSelf: "flex-start" }} onClick={() => onChange([...rules, { field: "pe_pct", op: "<=", value: 50 }])}>＋ 添加规则</button>
    </div>
  );
}

/** 模拟净值曲线（单序列，不需要图例）；虚线为初始资金。 */
export function NavChart({ navs, initial }: { navs: NavPoint[]; initial: number }) {
  if (navs.length < 2) return <div className="empty">净值点不足两个，推进几天模拟盘后显示曲线</div>;
  const W = 640, H = 180, P = 28;
  const vals = navs.map((p) => p.nav).concat(initial);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const x = (i: number) => P + (i / (navs.length - 1)) * (W - 2 * P);
  const y = (v: number) => H - P - ((v - lo) / span) * (H - 2 * P);
  const d = navs.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.nav).toFixed(1)}`).join("");
  return (
    <svg className="nav-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="模拟净值曲线">
      <line className="base" x1={P} x2={W - P} y1={y(initial)} y2={y(initial)} />
      <path className="ln" d={d}>{navs.map((p) => <title key={p.date}>{`${p.date} 净值 ${p.nav.toLocaleString()}`}</title>)}</path>
      <text x={P} y={H - 8}>{navs[0].date}</text>
      <text x={W - P} y={H - 8} textAnchor="end">{navs[navs.length - 1].date}</text>
      <text x={P} y={14}>{hi.toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
    </svg>
  );
}
