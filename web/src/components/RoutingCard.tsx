import { LEVEL_LABEL, ROUTE_LABEL, SOURCE_ROUTE } from "../format";
import type { RouteDecision } from "../types";

const ORDER = ["quick", "standard", "deep"];

export default function RoutingCard({ r, roleHint }: { r: RouteDecision; roleHint?: string }) {
  const probs = Object.keys(r.calibrated).length ? r.calibrated : null;
  return (
    <div className="card routing">
      <div className="title-row">
        <h3>研究方式</h3>
        <span className={`route-pill rt-${r.route}`}>{ROUTE_LABEL[r.route]}</span>
        <span className="tag">{SOURCE_ROUTE[r.source] ?? r.source}</span>
        {r.abstain && <span className="tag warn">系统拿不准，选了更稳妥的方式</span>}
        {r.escalated_from && <span className="tag warn">由{ROUTE_LABEL[r.escalated_from]}升级</span>}
      </div>
      <div className="routing-grid">
        <div>
          <div className="muted small">系统判断这个问题适合哪种方式</div>
          {probs ? ORDER.map((k) => (
            <div key={k} className="prob-row">
              <span>{ROUTE_LABEL[k]}</span>
              <div className="bar"><div className={`rt-bg-${k}`} style={{ width: `${(probs[k] ?? 0) * 100}%` }} /></div>
              <span className="num">{((probs[k] ?? 0) * 100).toFixed(0)}%</span>
            </div>
          )) : <div className="muted small">你已指定研究方式，系统没有另作判断</div>}
        </div>
        <div>
          <div className="muted small">问题的分量</div>
          <div className="kv"><span>判断错的影响</span>{r.stakes ? LEVEL_LABEL[r.stakes] ?? r.stakes : "未评估"}</div>
          <div className="kv"><span>观点分歧</span>{r.uncertainty ? LEVEL_LABEL[r.uncertainty] ?? r.uncertainty : "未评估"}</div>
          {roleHint && <div className="kv"><span>使用的模型</span>{roleHint}</div>}
        </div>
      </div>
      {r.reasons.length > 0 && r.source !== "user" && <ul className="small reasons">{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>}
    </div>
  );
}
