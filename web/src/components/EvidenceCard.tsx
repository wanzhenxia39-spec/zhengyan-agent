import { useState } from "react";
import { api } from "../api";
import { fmtDate, fmtMetric, SOURCE_LABEL } from "../format";
import type { Evidence } from "../types";
import { LevelBadge } from "./Badge";

export default function EvidenceCard({ ev, highlight }: { ev: Evidence; highlight?: boolean }) {
  const [snap, setSnap] = useState<string | null>(null);
  const toggleSnap = async () => setSnap(snap === null ? await api.snapshot(ev.id) : null);
  return (
    <div className={`ev ${highlight ? "ev-hl" : ""}`} id={ev.id}>
      <div className="ev-head">
        <LevelBadge level={ev.level} />
        <span className="tag">{SOURCE_LABEL[ev.source_type] ?? ev.source_type}</span>
        <span className="muted">{fmtDate(ev.published_at)}</span>
        <span className="muted">{ev.site_name}</span>
        {ev.pit === "weak" && <span className="tag warn" title="这份数据可能被事后修订过，未必是当时公布的原值">可能经过修订</span>}
        <code className="ev-id">{ev.id}</code>
      </div>
      <div className="ev-title">
        {ev.source_url ? <a href={ev.source_url} target="_blank" rel="noreferrer">{ev.title}</a> : ev.title}
      </div>
      {ev.metrics.length > 0 ? (
        <table className="mini">
          <tbody>
            {ev.metrics.map((m, i) => (
              <tr key={i}>
                <td>{m.name}</td>
                <td className="muted">{m.period.slice(0, 10)}</td>
                <td className="num">{fmtMetric(m.value, m.unit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="ev-excerpt">{ev.excerpt}</p>
      )}
      {ev.caveats.length > 0 && <ul className="caveats">{ev.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>}
      {ev.derived_from.length > 0 && <div className="muted small">由 {ev.derived_from.join("、")} 计算</div>}
      <button className="link" onClick={toggleSnap}>{snap === null ? "查看快照" : "收起快照"}</button>
      {snap !== null && <pre className="snapshot">{snap || "（空）"}</pre>}
    </div>
  );
}
