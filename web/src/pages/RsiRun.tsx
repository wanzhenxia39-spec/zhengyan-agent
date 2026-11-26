import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, waitJob } from "../api";
import { CompareChart, EventList, GateGrid, LessonView, RunStatus, SCEN } from "../components/Rsi";
import { PageHead, useShell } from "../components/Shell";
import { fmtTime, zh } from "../format";
import type { LessonCard, RsiAsset, RsiEvent, RsiIssue, RsiJob, RsiRun as Run } from "../types";

const PARAM: Record<string, string> = { temperature: "校准温度", abstain_below: "拒判阈值", rerank_min: "相关度阈值", authority_b_min: "B 级权威下限" };

export default function RsiRun() {
  const { id = "" } = useParams();
  const shell = useShell();
  const [data, setData] = useState<{ run: Run; base: RsiAsset | null; issues: RsiIssue[]; events: RsiEvent[]; job: RsiJob | null } | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [job, setJob] = useState<RsiJob | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.rsi.run(id).then(setData).catch((e) => setError(e.message)), [id]);
  useEffect(() => { load(); }, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await fn(); await load(); shell.refresh(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  };
  const follow = async (jobId: string) => {
    const j = await waitJob(jobId, setJob);
    if (j.status === "failed") throw new Error(j.error ?? "评测失败");
  };
  const evaluate = () => act(async () => follow((await api.rsi.evaluate(id)).job_id));
  // 刷新页面后，后台仍在跑的评测要重新接上进度，而不是显示成可以再点一次
  const runningJob = data?.job?.status === "running" ? data.job.job_id : null;
  useEffect(() => { if (runningJob && !busy) act(() => follow(runningJob)); }, [runningJob]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !data) return <div className="page"><div className="error">{error}</div></div>;
  if (!data) return <div className="page muted">加载中…</div>;
  const { run, base, issues, events } = data;
  const ev = run.eval;
  const baseCards = (base?.content.cards ?? []) as LessonCard[];
  const selfApproved = run.approvals.some((a) => a.self_approved);

  return (
    <>
      <PageHead title={<>{SCEN[run.scenario].name} · 候选 <code>{run.run_id}</code></>} sub={<RunStatus s={run.status} />}
        right={<Link to="/rsi" className="button ghost">返回 RSI</Link>} />
      <div className="page narrow">
        <section className="card">
          <div className="kv"><span>改动理由</span><b>{zh(run.change_reason)}</b></div>
          <div className="kv"><span>改哪个组件</span>{SCEN[run.scenario].kind}（基于在用 v{run.base_version}{run.released_version ? `，发布为 v${run.released_version}` : ""}）</div>
          <div className="kv"><span>提议 / 触发</span>{zh(run.proposer)} / {zh(run.triggered_by)} · {fmtTime(run.created_at)}</div>
          {run.reject_reason && <div className="error" style={{ marginBottom: 0 }}>{zh(run.reject_reason)}</div>}
          {run.risk === "high" && run.status !== "rejected" && (
            <div className="error" style={{ marginTop: 10, marginBottom: 0 }}>高风险改动：会改变系统能抓取哪些网站的原文。批准前请先打开几条该站点的链接人工抽查，并写明批准理由（不少于 10 个字）。</div>
          )}
          {selfApproved && <div className="selfapp" style={{ marginTop: 10 }}>本次为「自批」：触发人与批准人相同。单人阶段如实标出，未做到角色分离。</div>}

          {error && <div className="error">{error}</div>}
          <div className="row-btns" style={{ marginTop: 14, marginBottom: 0, alignItems: "center" }}>
            {run.status === "draft" && (
              <button className="primary" disabled={busy} onClick={evaluate}>{busy ? <><span className="spinner inline" />评测中…</> : "运行同台对比与六道门控"}</button>
            )}
            {run.status === "review" && (
              <>
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={run.risk === "high" ? "批准理由（必填，不少于 10 个字）" : "批准意见（可选）"} style={{ flex: 1, minWidth: 180 }} />
                <button className="primary" disabled={busy || (run.risk === "high" && note.trim().length < 10)} onClick={() => act(() => api.rsi.approve(id, note))}>批准</button>
              </>
            )}
            {run.status === "approved" && (
              <button className="primary" disabled={busy} onClick={() => act(() => api.rsi.release(id))}>发布为新版本</button>
            )}
            {["draft", "review", "approved"].includes(run.status) && (
              <>
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="拒绝理由" style={{ minWidth: 140 }} />
                <button className="danger" disabled={busy || reason.trim().length < 2} onClick={() => act(() => api.rsi.reject(id, reason))}>拒绝</button>
              </>
            )}
            {busy && job && <span className="muted small">{job.log[job.log.length - 1]}</span>}
          </div>
        </section>

        <h2>坏案例 <span className="muted small">四要素：案例 · 类型 · 证据 · 假设</span></h2>
        {issues.map((i) => (
          <section key={i.id} className="card">
            <div className="title-row"><code>{i.id}</code><span className="tag">{zh(i.kind)}</span><span className={`badge st-${i.status === "open" ? "draft" : "done"}`}>{i.status === "open" ? "待处理" : i.status === "addressed" ? "已处理" : i.status}</span></div>
            <div className="kv" style={{ marginTop: 8 }}><span>案例</span><span>{zh(i.case)}</span></div>
            <div className="kv"><span>证据</span><span>{i.evidence.map((x, k) => <div key={k}>{zh(x)}</div>)}</span></div>
            <div className="kv"><span>假设</span><b>{zh(i.hypothesis)}</b></div>
            {i.source.dossier && !String(i.source.dossier).includes(":") && (
              <div className="kv"><span>出处</span><Link to={`/dossiers/${i.source.dossier}/${i.source.version}`}>档案 {i.source.dossier} v{i.source.version}</Link></div>
            )}
          </section>
        ))}

        <h2>改动 <span className="muted small">一次只改一个组件</span></h2>
        {run.scenario === "S1" ? (
          <>
            {run.diff.cards?.map((c) => <LessonView key={c.id} c={c} badge={run.diff.action === "revise" ? "修订" : "新增"} />)}
            <p className="muted small">在用经验库 v{run.base_version} 共 {baseCards.length} 张卡{baseCards.length ? `（${baseCards.map((c) => `${c.id} r${c.rev}`).join("、")}）` : ""}；
              研究时按标签召回至多 3 张，作为「方法提示」进入提示词，不是指令，也不是证据。</p>
          </>
        ) : run.diff.hint ? (
          <section className="card">
            <div className="kv"><span>专家</span><b>{run.diff.hint.name}</b></div>
            <div className="kv"><span>原搜索侧重</span><span className="muted">{run.diff.hint.old}</span></div>
            <div className="kv"><span>新搜索侧重</span><b>{run.diff.hint.new}</b></div>
            {run.diff.hint.rationale && <div className="kv"><span>优化器说明</span>{run.diff.hint.rationale}</div>}
            <p className="muted small" style={{ marginBottom: 0 }}>这位专家做深研时，会按「搜索侧重」生成搜索词。评测时用同一批问题分别按新旧侧重真实搜索，比较带回来的结果里权威且能抓取原文的占比。</p>
          </section>
        ) : run.diff.sites ? (
          <section className="card">
            <div className="kv"><span>追加抓取站点</span><b>{run.diff.sites.add?.join("、")}</b></div>
            <p className="muted small" style={{ marginBottom: 0 }}>加入后，这个站点的网页可以被抓取原文，并可能升为 B 级证据。只加不删，黑名单和自媒体平台不能加入。</p>
          </section>
        ) : (
          <div className="param-diff">
            {Object.entries(run.diff.params ?? {}).map(([k, [o, n]]) => (
              <div key={k} className="pd"><div className="muted small">{PARAM[k] ?? k}</div><span className="muted">{o}</span> → <b>{n}</b></div>
            ))}
          </div>
        )}

        <h2>同台对比</h2>
        {ev ? (
          <section className="card">
            <CompareChart arms={ev.arms} metric={ev.metric} />
            <table className="table" style={{ marginTop: 14 }}>
              <tbody>
                <tr><td className="muted">评分器</td><td><code>{ev.protocol.scorer}</code> · 回放集哈希 <code>{ev.protocol.replay_hash.slice(0, 10)}</code></td></tr>
                <tr><td className="muted">样本</td><td>{Object.entries(ev.protocol.slices).map(([k, v]) => `${({ evolution: "新失败集", replay: "固定回放集", holdout: "留出集" } as Record<string, string>)[k] ?? k} ${v.n}${v.bad != null ? `（坏 ${v.bad}）` : ""}`).join(" · ")}</td></tr>
                <tr><td className="muted">重复</td><td>{ev.repeats} 次{ev.deterministic ? "（确定性回放）" : ""}</td></tr>
                <tr><td className="muted">模型用量（token）</td><td>{Object.entries(ev.arms).map(([k, a]) => `${({ off: "不用经验库", base: "现在的", cand: "改进的" } as Record<string, string>)[k]} ${(a.tokens ?? 0).toLocaleString()}`).join(" / ")}</td></tr>
                <tr><td className="muted">防泄漏</td><td>进化集 {ev.leakage.evolution.slice(0, 4).join("、")}{ev.leakage.evolution.length > 4 ? "…" : ""} ｜ 留出集 {ev.leakage.holdout.slice(0, 4).join("、")}{ev.leakage.holdout.length > 4 ? "…" : ""}</td></tr>
              </tbody>
            </table>
          </section>
        ) : <div className="empty">尚未评测。评测器会让候选与在用版本（以及关经验库）跑同一批案例，至少重复 3 次。</div>}

        <h2>六道门控</h2>
        <GateGrid gates={run.gates} />

        <h2>日志</h2>
        <section className="card"><EventList events={events} /></section>
      </div>
    </>
  );
}
