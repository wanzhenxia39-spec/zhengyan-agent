import { useState } from "react";
import { fmtTime, nodeLabel, ROLE_LABEL } from "../format";
import type { AuditRecord } from "../types";

const CALL_STATUS: Record<string, string> = { ok: "成功", cache_hit: "用了缓存", error: "失败", denied: "被拒绝", timeout: "超时" };
const callKind = (a: AuditRecord) => a.kind === "llm" ? `模型（${ROLE_LABEL[a.role ?? ""] ?? a.role}）` : "数据工具";

/** 按节点聚合的执行血缘（Trace 只证明谁在何时用了什么，不证明结论成立）。 */
export default function TraceView({ audit }: { audit: AuditRecord[] }) {
  const [flat, setFlat] = useState(false);
  const groups: { node: string; items: AuditRecord[] }[] = [];
  for (const a of audit) {
    const node = a.node || "—";
    const g = groups.find((x) => x.node === node);
    if (g) g.items.push(a); else groups.push({ node, items: [a] });
  }
  const total = (xs: AuditRecord[]) => xs.reduce((s, a) => s + a.duration_ms, 0);
  const tokens = (xs: AuditRecord[]) => xs.reduce((s, a) => s + (a.tokens ?? 0), 0);
  const max = Math.max(1, ...groups.map((g) => total(g.items)));
  const traceId = audit.find((a) => a.trace_id)?.trace_id;
  return (
    <div>
      <div className="row-btns">
        {traceId && <span className="muted small" title={traceId}>追踪编号 {traceId.slice(0, 8)}</span>}
        <button className="link" onClick={() => setFlat(!flat)}>{flat ? "按步骤汇总" : "逐条查看"}</button>
      </div>
      {!flat ? groups.map((g) => (
        <details key={g.node} className="trace-node">
          <summary>
            <span className="tl-node">{nodeLabel(g.node)}</span>
            <div className="bar trace-bar"><div style={{ width: `${(total(g.items) / max) * 100}%` }} /></div>
            <span className="muted small">{g.items.length} 次调用 · {(total(g.items) / 1000).toFixed(1)} 秒{tokens(g.items) ? ` · 模型用量 ${tokens(g.items).toLocaleString()} tokens` : ""}</span>
            {g.items.some((a) => !["ok", "cache_hit"].includes(a.status)) && <span className="tag warn">有异常</span>}
          </summary>
          <table className="table">
            <tbody>
              {g.items.map((a, i) => (
                <tr key={i}>
                  <td>{callKind(a)}</td>
                  <td><code>{a.name}</code>{a.version && <span className="muted small"> v{a.version}</span>}</td>
                  <td className={["ok", "cache_hit"].includes(a.status) ? "" : "warn-text"}>{CALL_STATUS[a.status] ?? a.status}</td>
                  <td className="num">{a.duration_ms} ms</td>
                  <td className="muted small">{a.error ?? (a.tokens ? `${a.tokens} tokens` : "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )) : (
        <table className="table">
          <thead><tr><th>时间</th><th>步骤</th><th>类型</th><th>名称</th><th>结果</th><th>耗时</th></tr></thead>
          <tbody>
            {audit.map((a, i) => (
              <tr key={i}>
                <td className="muted">{fmtTime(a.ts).slice(-8)}</td><td>{nodeLabel(a.node || "—")}</td>
                <td>{callKind(a)}</td><td><code>{a.name}</code></td>
                <td className={["ok", "cache_hit"].includes(a.status) ? "" : "warn-text"}>{CALL_STATUS[a.status] ?? a.status}</td>
                <td className="num">{a.duration_ms} ms</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
