import { fmtMetric, VERDICT_LABEL } from "../format";
import type { DossierDiff } from "../types";
import { LevelBadge } from "./Badge";

export default function DiffView({ diff }: { diff: DossierDiff }) {
  const changed = diff.metrics.filter((m) => m.changed);
  return (
    <div>
      <div className="card">
        <h3>v{diff.from_version} → v{diff.to_version}</h3>
        <div className="kv"><span>研究时点</span>{diff.as_of.old} → {diff.as_of.new}</div>
        <div className="kv"><span>流程</span>{diff.route.old} → {diff.route.new}</div>
        <div className="kv"><span>状态</span>{diff.status.old} → {diff.status.new}</div>
        <p className="muted small">新版本不覆盖旧版本：先展示变化与影响。依赖旧报告期的结论自动标记"待复核"。</p>
      </div>
      {diff.stale_claims.length > 0 && (
        <div className="card warnbox">
          <h3>依赖传播：待复核的旧结论 {diff.stale_claims.length}</h3>
          <ul>{diff.stale_claims.map((s, i) => <li key={i}>{s.text} <div className="muted small">{s.reason}</div></li>)}</ul>
        </div>
      )}
      {diff.prior_review.length > 0 && (
        <div className="card">
          <h3>对上一版本结论的复核</h3>
          <table className="table"><tbody>
            {diff.prior_review.map((p, i) => (
              <tr key={i}><td>{p.prior_claim}</td><td><span className={`badge vd-${p.verdict}`}>{VERDICT_LABEL[p.verdict]}</span></td><td className="muted small">{p.reason}</td></tr>
            ))}
          </tbody></table>
        </div>
      )}
      <div className="two-col">
        <div className="card">
          <h3>新增证据 {diff.evidence_added.length}</h3>
          {diff.evidence_added.length ? <ul className="small">{diff.evidence_added.slice(0, 20).map((e) => (
            <li key={e.id}><LevelBadge level={e.level} /> {e.date ?? ""} {e.title}</li>
          ))}</ul> : <p className="muted">无</p>}
        </div>
        <div className="card">
          <h3>未知项</h3>
          <div className="small"><b>已解决</b>{diff.unknowns.resolved.length ? <ul>{diff.unknowns.resolved.map((u, i) => <li key={i}>{u}</li>)}</ul> : <span className="muted"> 无</span>}</div>
          <div className="small"><b>新增</b>{diff.unknowns.new.length ? <ul>{diff.unknowns.new.map((u, i) => <li key={i}>{u}</li>)}</ul> : <span className="muted"> 无</span>}</div>
        </div>
      </div>
      <div className="card">
        <h3>指标变化 {changed.length}</h3>
        <table className="table">
          <thead><tr><th>指标</th><th>旧</th><th>新</th></tr></thead>
          <tbody>{changed.map((m) => (
            <tr key={m.name}>
              <td>{m.name}</td>
              <td className="num">{m.old ? `${fmtMetric(m.old.value, m.old.unit)}（${m.old.period}）` : "—"}</td>
              <td className="num">{m.new ? `${fmtMetric(m.new.value, m.new.unit)}（${m.new.period}）` : "—"}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="two-col">
        <div className="card"><h3>新增结论 {diff.claims.added.length}</h3><ul className="small">{diff.claims.added.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
        <div className="card"><h3>不再出现 {diff.claims.removed.length}</h3><ul className="small">{diff.claims.removed.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
      </div>
    </div>
  );
}
