import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, waitJob } from "../api";
import { CompareChart, EventList, GateDots, RunStatus, SCEN } from "../components/Rsi";
import { PageHead, useAskContext } from "../components/Shell";
import { fmtTime, zh } from "../format";
import type { RsiEvent, RsiIssue, RsiJob, RsiOverview, RsiRun } from "../types";
import { VersionPills } from "./Workspace";

const LOOP = [
  { k: "collect", t: "收集坏案例", s: "案例·类型·证据·假设" },
  { k: "propose", t: "提出小改动", s: "一次一个问题、一个组件" },
  { k: "evaluate", t: "同台对比", s: "同一批案例、同一把尺子" },
  { k: "gates", t: "六道门控", s: "全部亮绿灯" },
  { k: "release", t: "发布 / 回滚", s: "人工批准，一键回滚" },
] as const;
const KIND_LABEL: Record<string, string> = { lessons: "经验库", routing: "路由参数", search: "检索模板" };

export default function Rsi() {
  const nav = useNavigate();
  const [ov, setOv] = useState<RsiOverview | null>(null);
  const [runs, setRuns] = useState<RsiRun[]>([]);
  const [issues, setIssues] = useState<RsiIssue[]>([]);
  const [events, setEvents] = useState<RsiEvent[]>([]);
  const [job, setJob] = useState<RsiJob | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [rb, setRb] = useState<{ kind: string; reason: string } | null>(null);

  const load = useCallback(() => {
    Promise.all([api.rsi.overview(), api.rsi.runs(), api.rsi.issues(), api.rsi.events()])
      .then(([o, r, i, e]) => { setOv(o); setRuns(r); setIssues(i); setEvents(e); })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  useAskContext({
    title: "递归自我改进",
    suggestions: ["合同负债大幅下降一定说明需求走弱吗？", "复核贵州茅台 600519 最新一期业绩，合同负债和存货变化说明什么"],
  }, []);

  const collect = async () => {
    setBusy("collect"); setError("");
    try { await api.rsi.collect(); load(); } catch (e) { setError((e as Error).message); }
    setBusy("");
  };
  const propose = async (scenario: string) => {
    setBusy(scenario); setError("");
    try {
      const { job_id } = await api.rsi.propose(scenario);
      const j = await waitJob(job_id, setJob);
      if (j.status === "done" && j.result) nav(`/rsi/runs/${j.result}`);
      else setError(j.error ?? "生成失败");
    } catch (e) { setError((e as Error).message); }
    setBusy(""); load();
  };
  const rollback = async () => {
    if (!rb) return;
    try { await api.rsi.rollback(rb.kind, rb.reason); setRb(null); load(); } catch (e) { setError((e as Error).message); }
  };

  const cf = ov?.counterfactual;
  return (
    <>
      <PageHead title="递归自我改进" sub="RSI · 只改模型外面那一层，每一步都有日志"
        right={<button onClick={collect} disabled={!!busy}>{busy === "collect" ? "收集中…" : "收集坏案例"}</button>} />
      <div className="page">
        {error && <div className="error">{error}</div>}
        {!ov ? <p className="muted">加载中…</p> : (
          <>
            <section className="card">
              <div className="title-row">
                <h3 style={{ margin: 0 }}>RSI 链路</h3>
                <span className="muted small">节点亮起表示进度</span>
                <span style={{ marginLeft: "auto" }}>
                  <VersionPills v={{ lessons: ov.active.lessons?.version, routing: ov.active.routing?.version, search: ov.active.search?.version }} />
                </span>
              </div>
              <div className="loop">
                {LOOP.map((n, i) => {
                  const st = ov.loop[n.k];
                  return (
                    <div key={n.k} className={`loop-node ${st.done ? "lit" : ""}`}>
                      <span className="lamp">{i + 1}</span>
                      <span className="ln-t">{n.t}</span>
                      <span className="ln-s">{n.s}<br />{n.k === "release" ? `发布 ${st.count} · 回滚 ${st.rollback ?? 0}` : `${st.count} 次`}</span>
                    </div>
                  );
                })}
                <div className="loop-back"><span>下一轮从已发布的版本出发</span></div>
              </div>
              {ov.self_approved > 0 && (
                <div className="selfapp">单人阶段：{ov.self_approved} 次批准为「自批」（触发人与批准人相同），审计中如实标出，未做到角色分离。</div>
              )}
            </section>

            <div className="scen-grid">
              {(["S1", "S2", "S3"] as const).map((s) => {
                const open = issues.filter((i) => i.scenario === s && i.status === "open");
                return (
                  <section key={s} className="card scen">
                    <span className="sc-k">{s} · {SCEN[s].tag}</span>
                    <h3 style={{ margin: 0 }}>{SCEN[s].name}</h3>
                    <span className="muted small">{SCEN[s].desc}</span>
                    <div className="sc-n"><b>{ov.issues[s].open}</b><span className="muted small">待处理 / 共 {ov.issues[s].total} 个坏案例</span></div>
                    <ul className="issue-list">
                      {open.slice(0, 6).map((i) => (
                        <li key={i.id} title={zh(i.evidence.join("\n"))}><b>{i.id}</b> {zh(i.case).slice(0, 70)}<span className="hyp">假设：{zh(i.hypothesis)}</span></li>
                      ))}
                      {!open.length && <li className="muted">没有待处理的坏案例</li>}
                    </ul>
                    <button className="primary" disabled={!!busy || !open.length} onClick={() => propose(s)} style={{ alignSelf: "flex-start" }}>
                      {busy === s ? <><span className="spinner inline" />优化器生成中…</> : "生成一个改进"}
                    </button>
                    <span className="muted small">从「待处理」badcase 里挑出一个问题，让模型针对这个问题起草改进点，测试通过并经你批准才生效</span>
                    {busy === s && job && <span className="muted small">{job.log[job.log.length - 1] ?? "调用优化器…"}</span>}
                  </section>
                );
              })}
            </div>

            <h2>候选</h2>
            {runs.length === 0 ? <div className="empty">还没有候选。先收集坏案例，再生成一个改进。</div> : (
              <div className="card table">
                <table className="table">
                  <thead><tr><th>状态</th><th>场景</th><th>改动理由</th><th>门控</th><th>创建</th></tr></thead>
                  <tbody>
                    {runs.map((r) => (
                      <tr key={r.run_id} style={{ cursor: "pointer" }} onClick={() => nav(`/rsi/runs/${r.run_id}`)}>
                        <td><RunStatus s={r.status} /></td>
                        <td>{r.scenario}</td>
                        <td><Link to={`/rsi/runs/${r.run_id}`}>{zh(r.change_reason)}</Link>
                          {r.reject_reason && <div className="muted small">{zh(r.reject_reason).slice(0, 90)}</div>}</td>
                        <td><GateDots gates={r.gates} /></td>
                        <td className="muted small">{fmtTime(r.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="two-col" style={{ marginTop: 12 }}>
              <section className="card">
                <h3>有无经验库对比 <span className="muted small">把经验库关掉再跑一遍，确认分数提升来自经验卡，而不是多花了算力</span></h3>
                {cf ? (
                  <>
                    <CompareChart arms={cf.arms as never} metric={cf.metric} />
                    <p className="muted small" style={{ marginBottom: 0 }}>
                      来自 <Link to={`/rsi/runs/${cf.run_id}`}>{cf.run_id}</Link> · token：
                      {Object.entries(cf.arms).map(([k, a]) => `${({ off: "关", base: "在用", cand: "候选" } as Record<string, string>)[k]} ${a.tokens.toLocaleString()}`).join(" / ")}
                      {cf.arms.off?.note ? ` · ${cf.arms.off.note}` : ""}
                    </p>
                  </>
                ) : <div className="empty">还没有评测过 S1 候选</div>}
              </section>
              <section className="card">
                <h3>继承证明 <span className="muted small">每份档案都记录它用了哪个版本</span></h3>
                {ov.inheritance.length ? (
                  <table className="table"><tbody>
                    {ov.inheritance.map((g, i) => (
                      <tr key={i}><td><VersionPills v={g.versions} /></td><td className="num">{g.dossiers} 份</td>
                        <td className="small">{g.lessons_used.length ? `召回 ${g.lessons_used.join("、")}` : <span className="muted">未召回经验卡</span>}</td></tr>
                    ))}
                  </tbody></table>
                ) : <div className="empty">RSI 上线后的研究会出现在这里</div>}
              </section>
            </div>

            <h2>RSI 版本追踪</h2>
            <div className="lineage">
              {(["lessons", "routing", "search"] as const).map((k) => {
                const chain = ov.lineage[k];
                const active = chain.find((a) => a.active);
                return (
                  <section key={k} className="card lin-col">
                    <div className="title-row"><h3 style={{ margin: 0 }}>{KIND_LABEL[k]}</h3>
                      {active?.parent != null && <button className="danger" style={{ marginLeft: "auto", padding: "3px 10px", fontSize: 12 }} onClick={() => setRb({ kind: k, reason: "" })}>一键回滚</button>}
                    </div>
                    {rb?.kind === k && (
                      <div className="form" style={{ marginTop: 10, gap: 8 }}>
                        <input autoFocus value={rb.reason} onChange={(e) => setRb({ kind: k, reason: e.target.value })} placeholder="回滚理由（不少于 10 个字）" />
                        <div className="row-btns" style={{ margin: 0 }}>
                          <button className="danger" disabled={rb.reason.trim().length < 10} onClick={rollback}>回滚到 v{active?.parent}</button>
                          <button onClick={() => setRb(null)}>取消</button>
                        </div>
                      </div>
                    )}
                    <ul className="lin-chain" style={{ marginTop: 12 }}>
                      {[...chain].reverse().map((a) => (
                        <li key={a.version} className={a.active ? "active" : ""}>
                          <span className="lv">v{a.version}</span>{a.active && <span className="tag purple">在用</span>}
                          <span className="muted"> 基于 {a.parent ? `v${a.parent}` : "—"} · 校验码 {a.sha256}</span>
                          <span className="lr">{zh(a.change_reason)}{a.run_id && <> · <Link to={`/rsi/runs/${a.run_id}`}>{a.run_id}</Link></>}</span>
                        </li>
                      ))}
                    </ul>
                  </section>
                );
              })}
            </div>

            <h2>RSI 版本日志 <span className="muted small">只追加，不修改；失败也记录</span></h2>
            <section className="card"><EventList events={events.slice(0, 30)} /></section>
          </>
        )}
      </div>
    </>
  );
}
