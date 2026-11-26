import { CHALLENGE_KIND, MODE_LABEL, STANCE_LABEL, VERDICT_LABEL } from "../format";
import type { Claim, Deliberation } from "../types";

export default function DebateView({ d, onEvidence }: { d: Deliberation; onEvidence?: (id: string) => void }) {
  const claims = new Map<string, Claim>();
  d.team.forEach((t) => t.claims.forEach((c) => claims.set(c.id, c)));
  d.responses.forEach((r) => r.revised_claim && claims.set(r.revised_claim.id, r.revised_claim));
  const name = (k: string) => d.team.find((t) => t.expert === k)?.name ?? k;
  const chips = (ids: string[]) => ids.map((e) => (
    <button key={e} className="ev-chip" onClick={() => onEvidence?.(e)}><code>{e.slice(3, 9)}</code></button>
  ));
  return (
    <div>
      <p className="muted small">
        协作模式：<b>{MODE_LABEL[d.mode]}</b>{d.rationale && `（${d.rationale}）`}。
        专家之间不直接采信彼此的结论：每条结论先对照数据核对，成立的才拿来汇总；反证官专门质疑这些结论，主席按证据裁定并保留不同意见，不靠少数服从多数。
      </p>
      {d.challenges.length === 0 && <p className="muted">本次没有质询。</p>}
      {d.challenges.map((ch) => {
        const target = claims.get(ch.target_claim_id);
        const ruling = d.rulings.find((r) => r.challenge_id === ch.id);
        return (
          <div key={ch.id} className={`card debate sev-${ch.severity}`}>
            <div className="debate-target">
              <span className="muted small">被质询 · {name(ch.target_expert)} · <code>{ch.target_claim_id}</code></span>
              <div>{target?.text ?? "（该结论已不存在）"}</div>
            </div>
            <div className="debate-row red">
              <span className="who">反证官</span>
              <div>
                <span className="tag">{CHALLENGE_KIND[ch.kind] ?? ch.kind}</span> <span className={`tag sev ${ch.severity}`}>严重度 {ch.severity}</span>{" "}
                {ch.text} {chips(ch.evidence_ids)}
                {ch.notes.length > 0 && <div className="muted small">{ch.notes.join("；")}</div>}
              </div>
            </div>
            {d.responses.filter((r) => r.challenge_id === ch.id).map((r, i) => (
              <div key={i} className="debate-row">
                <span className="who">{name(r.expert)}</span>
                <div>
                  <span className={`tag st-${r.stance}`}>{STANCE_LABEL[r.stance]}</span> {r.text} {chips(r.evidence_ids)}
                  {r.revised_claim && <div className="small">修正为：{r.revised_claim.text}（{r.revised_claim.status}）</div>}
                </div>
              </div>
            ))}
            {ruling && (
              <div className="debate-row chair">
                <span className="who">主席</span>
                <div><span className={`badge vd-${ruling.verdict}`}>{VERDICT_LABEL[ruling.verdict]}</span> {ruling.reason}</div>
              </div>
            )}
          </div>
        );
      })}
      {d.committee.length > 0 && (
        <div className="card">
          <h3>委员会立场</h3>
          <ul>{d.committee.map((c, i) => <li key={i}><b>{name(c.expert)}</b>：{c.position}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
