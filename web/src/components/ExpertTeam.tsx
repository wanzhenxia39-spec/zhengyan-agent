import { useState } from "react";
import { KIND_LABEL } from "../format";
import type { ExpertResult } from "../types";
import { StatusBadge } from "./Badge";

export default function ExpertTeam({ team, onEvidence, pending = [] }: {
  team: ExpertResult[]; onEvidence?: (id: string) => void; pending?: string[];
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div className="team-grid">
      {team.map((t) => {
        const ok = t.claims.filter((c) => c.status === "verified").length;
        return (
          <div key={t.expert} className={`card expert ${t.expert === "red_team" ? "red" : ""} ${t.error ? "failed" : ""}`}>
            <div className="title-row">
              <b>{t.name}</b>
              <span className="tag">{t.model_role}</span>
              {t.confidence && <span className="tag">信心 {t.confidence}</span>}
            </div>
            <div className="stance">{t.error ? <span className="warn-text">失败：{t.error}</span> : (t.stance || "—")}</div>
            {t.brief.length > 0 && <ul className="small brief">{t.brief.map((b, i) => <li key={i}>{b}</li>)}</ul>}
            <div className="expert-stats small muted">
              <span>结论 {ok}/{t.claims.length} 条核对成立</span>
              <span>可见证据 {t.seen_evidence}</span>
              <span>检索 {t.queries.length}</span>
              <span>{Math.round(t.usage.tokens ?? 0).toLocaleString()} tokens</span>
              <span>{(t.duration_ms / 1000).toFixed(0)}s</span>
            </div>
            <button className="link" onClick={() => setOpen(open === t.expert ? null : t.expert)}>
              {open === t.expert ? "收起结论" : "查看结论"}
            </button>
            {open === t.expert && (
              <ul className="expert-claims">
                {t.claims.map((c) => (
                  <li key={c.id} className={c.status !== "verified" ? "dim" : ""}>
                    <code>{c.id}</code> <span className={`kind k-${c.kind}`}>{KIND_LABEL[c.kind]}</span> {c.text}{" "}
                    <StatusBadge status={c.status} />
                    {c.evidence_ids.map((e) => onEvidence ? <button key={e} className="ev-chip" onClick={() => onEvidence(e)}><code>{e.slice(3, 9)}</code></button> : null)}
                    {c.verify_notes.length > 0 && <div className="muted small">{c.verify_notes.join("；")}</div>}
                  </li>
                ))}
                {t.queries.length > 0 && <li className="muted small">检索词：{t.queries.join(" / ")}</li>}
              </ul>
            )}
          </div>
        );
      })}
      {pending.map((p) => (
        <div key={p} className="card expert pending"><b>{p}</b><div className="muted small">取证中…<span className="spinner inline" /></div></div>
      ))}
    </div>
  );
}
