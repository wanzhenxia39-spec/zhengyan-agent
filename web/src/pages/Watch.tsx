import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, waitJob } from "../api";
import { ALERT_STATUS, EVENT_LABEL } from "../components/Personal";
import { PageHead, useAskContext, useShell } from "../components/Shell";
import { fmtTime } from "../format";
import type { Alert, Subscription, WatchRow } from "../types";

/** 事件订阅与增量复核：前提变化时提醒，并指出受影响的旧结论；没有变化不打扰。 */
export default function Watch() {
  const nav = useNavigate();
  const shell = useShell();
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [intervalH, setIntervalH] = useState(0);
  const [rows, setRows] = useState<WatchRow[]>([]);
  const [busy, setBusy] = useState("");
  const [log, setLog] = useState("");
  const [error, setError] = useState("");
  const [dismiss, setDismiss] = useState<{ id: string; note: string } | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  useAskContext({ title: "订阅与复核", suggestions: ["新财报出来后，哪些旧结论最容易失效？"] }, []);

  const load = useCallback(() => {
    api.watch.overview().then((w) => { setSubs(w.subscriptions); setAlerts(w.alerts); setIntervalH(w.interval_hours); })
      .catch((e) => setError(e.message));
    api.watchlist().then(setRows).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); }
    setBusy(""); load(); shell.refresh();
  };
  const scanAll = () => act("scan", async () => {
    const { job_id } = await api.watch.scanAll();
    const j = await waitJob(job_id, (x) => setLog(x.log[x.log.length - 1] ?? "扫描中…"));
    setLog(j.log.join("；") || "没有订阅");
  });
  const review = (a: Alert) => act(a.id, async () => { const { task_id } = await api.watch.review(a.id); nav(`/tasks/${task_id}`); });

  const active = subs.filter((s) => s.active);
  const unsubscribed = rows.filter((r) => !active.some((s) => s.ticker === r.key));
  const open = alerts.filter((a) => a.status === "open" || a.status === "reviewing");
  const done = alerts.filter((a) => a.status === "resolved" || a.status === "dismissed");

  return (
    <>
      <PageHead title="订阅与复核" sub={intervalH ? `服务运行时每 ${intervalH} 小时自动扫描一次` : "手动扫描"}
        right={<button className="primary" disabled={!!busy || !active.length} onClick={scanAll}>{busy === "scan" ? "扫描中…" : "立即扫描全部"}</button>} />
      <div className="page">
        {error && <div className="error">{error}</div>}
        {log && <p className="muted small">{log}</p>}

        <h2>待处理的提醒 <span className="muted small">研究之后出现了新财报、新公告或较大价格变化，下面列出可能因此过时的旧结论</span></h2>
        {open.length === 0 ? <div className="empty">没有待处理的提醒。没有变化，就不打扰你。</div> : open.map((a) => (
          <section key={a.id} className="card">
            <div className="title-row">
              <span className={`badge st-${a.status}`}>{ALERT_STATUS[a.status]}</span>
              <b>{a.name}（{a.ticker}）</b>
              <Link className="small" to={`/dossiers/${a.dossier_key}/${a.dossier_version}`}>对照档案 v{a.dossier_version}</Link>
              <span className="muted small" style={{ marginLeft: "auto" }}>{fmtTime(a.created_at)}</span>
            </div>
            <ul className="alert-ev">
              {a.events.map((e, i) => <li key={i}><span className="tag purple">{EVENT_LABEL[e.kind]}</span> {e.title}
                {e.detail && <span className="muted"> · {e.detail}</span>}</li>)}
            </ul>
            {a.affected.length > 0 && (
              <>
                <div className="muted small">受影响的旧结论（{a.affected.length}）</div>
                <ol className="affected">{(expanded.has(a.id) ? a.affected : a.affected.slice(0, 5)).map((c) =>
                  <li key={c.claim_id}>{c.text} <span className="muted">— {c.reason}</span></li>)}</ol>
                {a.affected.length > 5 && (
                  <button className="ghost small" onClick={() => setExpanded((s) => new Set(s.has(a.id) ? [...s].filter((x) => x !== a.id) : [...s, a.id]))}>
                    {expanded.has(a.id) ? "收起" : `展开全部 ${a.affected.length} 条`}</button>
                )}
              </>
            )}
            {a.note && <p className="muted small">{a.note}</p>}
            <div className="row-btns" style={{ marginTop: 10, marginBottom: 0 }}>
              {a.status === "open" ? (
                <>
                  <button className="primary" disabled={!!busy} onClick={() => review(a)}>{busy === a.id ? "启动中…" : "用新数据重新研究"}</button>
                  {dismiss?.id === a.id ? (
                    <>
                      <input autoFocus value={dismiss.note} placeholder="忽略原因" onChange={(e) => setDismiss({ id: a.id, note: e.target.value })} />
                      <button disabled={dismiss.note.trim().length < 2} onClick={() => act(a.id, async () => { await api.watch.dismiss(a.id, dismiss.note); setDismiss(null); })}>确认忽略</button>
                    </>
                  ) : <button className="ghost" onClick={() => setDismiss({ id: a.id, note: "" })}>忽略</button>}
                </>
              ) : <Link className="button ghost" to={`/tasks/${a.review_task_id}`}>查看研究进度</Link>}
            </div>
            {a.status === "open" && <p className="muted small" style={{ marginBottom: 0 }}>
              用新数据重新研究：基于最新财报、公告和行情再研究一次，生成档案新版本，并逐条说明上面的旧结论是否还成立（旧版本保留）。忽略：你认为这批变化不影响结论，填写原因后关闭提醒，档案不变。</p>}
          </section>
        ))}

        <div className="two-col" style={{ marginTop: 12 }}>
          <section className="card">
            <h3>已订阅（{active.length}）</h3>
            {active.length === 0 ? <div className="empty">还没有订阅。下方选一只有档案的股票开始。</div> : (
              <table className="table"><tbody>
                {active.map((s) => (
                  <tr key={s.ticker}>
                    <td><Link to={`/dossiers/${s.ticker}`}>{s.name || s.ticker}</Link><div className="muted small">{s.ticker} · 价格阈值 ±{s.price_move_pct}%</div></td>
                    <td className="small">{s.last_scan_at ? <>{fmtTime(s.last_scan_at)}<div className="muted">{s.last_scan_note}</div></> : <span className="muted">未扫描</span>}</td>
                    <td><button className="ghost" disabled={!!busy} onClick={() => act(s.ticker, () => api.watch.scan(s.ticker))}>{busy === s.ticker ? "…" : "扫描"}</button>
                      <button className="ghost" onClick={() => act(s.ticker, () => api.watch.unsubscribe(s.ticker))}>退订</button></td>
                  </tr>
                ))}
              </tbody></table>
            )}
            {unsubscribed.length > 0 && (
              <div className="row-btns" style={{ marginTop: 12, marginBottom: 0 }}>
                {unsubscribed.map((r) => <button key={r.key} onClick={() => act(r.key, () => api.watch.subscribe(r.key))}>＋ 订阅 {r.name || r.ticker}</button>)}
              </div>
            )}
          </section>
          <section className="card">
            <h3>处理记录 <span className="muted small">已重新研究或已忽略的提醒，重新研究的可点开新版本档案</span></h3>
            {done.length === 0 ? <div className="empty">还没有处理过的提醒。点「用新数据重新研究」或「忽略」后会出现在这里</div> : (
              <table className="table"><tbody>
                {done.map((a) => (
                  <tr key={a.id}>
                    <td><span className={`badge st-${a.status}`}>{ALERT_STATUS[a.status]}</span></td>
                    <td>{a.name} · {a.events.map((e) => EVENT_LABEL[e.kind]).join("、")}
                      <div className="muted small">{a.status === "resolved" && a.resolved_version
                        ? <Link to={`/dossiers/${a.dossier_key}/${a.resolved_version}`}>新版本：档案 v{a.resolved_version}</Link> : a.note}</div></td>
                    <td className="muted small">{fmtTime(a.created_at)}</td>
                  </tr>
                ))}
              </tbody></table>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
