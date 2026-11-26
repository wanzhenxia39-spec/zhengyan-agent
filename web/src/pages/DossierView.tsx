import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { LevelBadge, StatusBadge } from "../components/Badge";
import DebateView from "../components/DebateView";
import DiffView from "../components/DiffView";
import { PersonalPanel } from "../components/Personal";
import EvidenceCard from "../components/EvidenceCard";
import ExpertTeam from "../components/ExpertTeam";
import Markdown from "../components/Markdown";
import RoutingCard from "../components/RoutingCard";
import { useAskContext, useShell } from "../components/Shell";
import { VersionPills } from "./Workspace";
import { fmtMetric, fmtTime, KIND_LABEL, MODE_LABEL, ROUTE_LABEL, VERDICT_LABEL } from "../format";
import type { Claim, Dossier, DossierDiff, Evidence } from "../types";

type Tab = "overview" | "experts" | "evidence" | "diff" | "report" | "history";
const BASIS: Record<string, string> = { cumulative: "累计", single_quarter: "单季", point: "时点", ratio: "比率", change: "变化", ttm: "滚动四季" };

export default function DossierView() {
  const { key = "", version } = useParams();
  const nav = useNavigate();
  const [data, setData] = useState<{ dossier: Dossier; evidence: Evidence[] } | null>(null);
  const [versions, setVersions] = useState<Awaited<ReturnType<typeof api.versions>>>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [levels, setLevels] = useState<Set<string>>(new Set(["A", "B", "C"]));
  const [focus, setFocus] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [diff, setDiff] = useState<DossierDiff | null>(null);

  useEffect(() => {
    api.versions(key).then((vs) => {
      setVersions(vs);
      if (!version && vs.length) nav(`/dossiers/${key}/${vs[0].version}`, { replace: true });
    }).catch((e) => setError(e.message));
  }, [key, version, nav]);

  useEffect(() => {
    if (!version) return;
    setData(null);
    setDiff(null);
    api.dossier(key, Number(version)).then((d) => {
      setData(d);
      if (d.dossier.parent_version) api.diff(key, Number(version)).then(setDiff).catch(() => setDiff(null));
    }).catch((e) => setError(e.message));
  }, [key, version]);

  const evMap = useMemo(() => new Map((data?.evidence ?? []).map((e) => [e.id, e])), [data]);
  const shell = useShell();
  const dd = data?.dossier;
  useAskContext(dd ? {
    title: dd.name || dd.ticker, ticker: dd.ticker,
    suggestions: [
      `${dd.name} ${dd.ticker} 有新财报或公告后，上一版本的结论还成立吗？`,
      `${dd.name} ${dd.ticker} 当前估值是否已反映主要风险？多空分歧在哪里`,
      ...(dd.unknowns[0] ? [`补证：${dd.unknowns[0].slice(0, 40)}`] : []),
    ],
  } : null, [dd?.key, dd?.version]);

  useEffect(() => {
    if (tab === "evidence" && focus) document.getElementById(focus)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [tab, focus]);

  if (error) return <div className="page"><div className="error">{error}</div></div>;
  if (!data) return <div className="page muted">加载中…</div>;
  const d = data.dossier;
  const verified = d.claims.filter((c) => c.status === "verified");
  const failed = d.claims.filter((c) => c.status === "disputed" || c.status === "rejected");
  const calc = data.evidence.filter((e) => e.source_type === "calc" && d.evidence_ids.includes(e.id));
  const clues = data.evidence.filter((e) => d.clue_ids.includes(e.id));
  const dl = d.deliberation;

  const openEvidence = (id: string) => {
    const ev = evMap.get(id);
    if (ev) shell.openEvidence([ev], `${d.name} v${d.version}`);
    else { setFocus(id); setTab("evidence"); }
  };
  const EvChips = ({ ids }: { ids: string[] }) => (
    <span className="chips">
      {ids.map((id) => {
        const ev = evMap.get(id);
        return (
          <button key={id} className="ev-chip" onClick={() => openEvidence(id)} title={ev?.title}>
            {ev && <LevelBadge level={ev.level} />}<code>{id.slice(3, 9)}</code>
          </button>
        );
      })}
    </span>
  );
  const ClaimRow = ({ c }: { c: Claim }) => (
    <tr className={c.status !== "verified" ? "dim" : ""}>
      <td><span className={`kind k-${c.kind}`}>{KIND_LABEL[c.kind]}</span></td>
      <td>
        <div className={c.status === "verified" ? "" : "strike"}>{c.text}</div>
        {c.verify_notes.length > 0 && <div className="muted small">{c.verify_notes.join("；")}</div>}
      </td>
      <td><EvChips ids={c.evidence_ids} /></td>
      <td><StatusBadge status={c.status} /></td>
    </tr>
  );

  return (
    <div className="page" style={{ paddingTop: 20 }}>
      <div className="title-row">
        <h1>{d.name} <code>{d.ticker}</code></h1>
        <StatusBadge status={d.status} />
        <select value={d.version} onChange={(e) => nav(`/dossiers/${key}/${e.target.value}`)}>
          {versions.map((v) => <option key={v.version} value={v.version}>v{v.version} · 数据截至 {v.as_of}</option>)}
        </select>
      </div>
      <div className="meta muted">
        数据截至 <b>{d.as_of}</b> · 研究方式 {ROUTE_LABEL[d.route] ?? d.route}{dl ? ` · ${MODE_LABEL[dl.mode]}（${dl.team.length} 位专家）` : ""} · 生成于 {fmtTime(d.created_at)} ·
        质量门控 {d.quality.decision}（通过 {d.quality.verified} / 存疑 {d.quality.disputed} / 驳回 {d.quality.rejected}）·
        <Link to={`/tasks/${d.task_id}`}> 查看任务与审计</Link>
      </div>
      <div className="title-row small" style={{ marginBottom: 6 }}>
        <span className="muted">方法版本</span><VersionPills v={d.rsi_versions} />
        {!!d.lessons_used?.length && <span className="tag purple" title="方法提示，不是证据">召回经验卡 {d.lessons_used.join("、")}</span>}
      </div>

      <div className="tabs">
        {([["overview", "概览"], ...(dl ? [["experts", `专家与辩论 (${dl.challenges.length})`]] : []),
           ["evidence", `证据 (${data.evidence.length})`], ...(d.parent_version ? [["diff", `与 v${d.parent_version} 差异`]] : []),
           ["report", "底稿 Markdown"], ["history", `版本 (${versions.length})`]] as [Tab, string][])
          .map(([t, label]) => <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{label}</button>)}
      </div>

      {tab === "overview" && (
        <div className="overview">
          <section className="card">
            <h3>结论摘要</h3>
            <p>{d.summary}</p>
            <p className="muted small">问题：{d.question}</p>
            {d.boundary_notes.map((n, i) => <div key={i} className="notice">{n}</div>)}
          </section>
          <PersonalPanel ticker={d.ticker} />

          {d.routing && <RoutingCard r={d.routing} />}

          {d.prior_review.length > 0 && (
            <section className="card">
              <h3>与上一版本对照 <span className="muted small">工作记忆：上一版本结论逐条复核</span></h3>
              <table className="table"><tbody>
                {d.prior_review.map((p, i) => (
                  <tr key={i}>
                    <td>{p.prior_claim}</td>
                    <td><span className={`badge vd-${p.verdict}`}>{VERDICT_LABEL[p.verdict]}</span></td>
                    <td className="muted small">{p.reason}</td>
                  </tr>
                ))}
              </tbody></table>
            </section>
          )}

          {calc.length > 0 && (
            <section className="card">
              <h3>关键指标 <span className="muted small">确定性计算 · 同口径</span></h3>
              <table className="table">
                <thead><tr><th>指标</th><th>口径</th><th>报告期</th><th className="num">数值</th></tr></thead>
                <tbody>
                  {calc.flatMap((e) => e.metrics).map((m, i) => (
                    <tr key={i}>
                      <td>{m.name}</td><td>{BASIS[m.basis] ?? m.basis}</td><td>{m.period.slice(0, 10)}</td>
                      <td className={`num ${m.unit === "%" && Number(m.value) < 0 ? "neg" : ""}`}>{fmtMetric(m.value, m.unit)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          <section className="card">
            <h3>核对成立的结论 <span className="muted small">{verified.length} 条</span></h3>
            <table className="table claims"><tbody>{verified.map((c) => <ClaimRow key={c.id} c={c} />)}</tbody></table>
          </section>

          {failed.length > 0 && (
            <section className="card">
              <h3>未通过核验 <span className="muted small">不作为结论</span></h3>
              <table className="table claims"><tbody>{failed.map((c) => <ClaimRow key={c.id} c={c} />)}</tbody></table>
            </section>
          )}

          <div className="two-col">
            <section className="card">
              <h3>反方观点与反证</h3>
              {d.dissents.length ? <ul>{d.dissents.map((x, i) => <li key={i}>{x.text} <EvChips ids={x.evidence_ids} /></li>)}</ul> : <p className="muted">无</p>}
            </section>
            <section className="card">
              <h3>未知与待补证据</h3>
              {d.unknowns.length ? <ul>{d.unknowns.map((u, i) => <li key={i}>{u}</li>)}</ul> : <p className="muted">无</p>}
            </section>
          </div>

          {clues.length > 0 && (
            <section className="card">
              <h3>新闻/事件线索 <span className="muted small">B 级说明发生了什么；C 级只是线索，不支撑结论</span></h3>
              <ul className="clues">
                {clues.sort((a, b) => a.level.localeCompare(b.level)).slice(0, 12).map((c) => (
                  <li key={c.id}>
                    <LevelBadge level={c.level} /> <span className="muted small">{c.published_at?.slice(0, 10)} {c.site_name}</span>{" "}
                    <button className="link" onClick={() => openEvidence(c.id)}>{c.title}</button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="card">
            <h3>下次复核条件</h3>
            <ul>{d.review_triggers.map((t, i) => <li key={i}><b>{t.condition}</b>：{t.reason}</li>)}</ul>
          </section>
        </div>
      )}

      {tab === "experts" && dl && (
        <div>
          {dl.needs_human_review && <div className="notice">存在高后果未决质询，本版本经人工确认后以部分结论提交。</div>}
          <h2>专家团队 <span className="muted small">首轮独立取证 · 只能引用自己可见的证据</span></h2>
          <ExpertTeam team={dl.team} onEvidence={openEvidence} />
          <h2>交叉质询与主席裁决</h2>
          <DebateView d={dl} onEvidence={openEvidence} />
        </div>
      )}

      {tab === "diff" && (diff ? <DiffView diff={diff} /> : <p className="muted">加载差异…</p>)}

      {tab === "evidence" && (
        <div>
          <div className="filters">
            {["A", "B", "C"].map((l) => (
              <label key={l} className="check">
                <input type="checkbox" checked={levels.has(l)} onChange={() => {
                  const next = new Set(levels);
                  if (next.has(l)) next.delete(l); else next.add(l);
                  setLevels(next);
                }} />
                <LevelBadge level={l} /> {data.evidence.filter((e) => e.level === l).length}
              </label>
            ))}
            <span className="muted small">A=结构化来源/计算；B=权威网页有快照；C=线索</span>
          </div>
          <div className="ev-list">
            {data.evidence
              .filter((e) => levels.has(e.level))
              .sort((a, b) => a.level.localeCompare(b.level) || a.source_type.localeCompare(b.source_type))
              .map((e) => <EvidenceCard key={e.id} ev={e} highlight={e.id === focus} />)}
          </div>
        </div>
      )}

      {tab === "report" && (
        <div className="card">
          <div className="row-btns">
            <a className="button" href={`/api/dossiers/${key}/${d.version}/markdown`} download={`${d.ticker}_v${d.version}.md`}>下载 .md</a>
          </div>
          <Markdown text={d.report_md} />
        </div>
      )}

      {tab === "history" && (
        <div className="list">
          {versions.map((v) => (
            <Link key={v.version} to={`/dossiers/${key}/${v.version}`} className={`list-item ${v.version === d.version ? "current" : ""}`}>
              <span className="tag">v{v.version}</span><StatusBadge status={v.status} />
              <span className="grow">{v.question}</span>
              <span className="muted small">数据截至 {v.as_of} · {fmtTime(v.created_at)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
