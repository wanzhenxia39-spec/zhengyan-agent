import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { StatusBadge } from "../components/Badge";
import { fmtTime, ROUTE_LABEL } from "../format";
import type { EvalRun } from "../types";

const METRIC_ROWS: [string, string, (v: number) => string][] = [
  ["score", "综合质量分", (v) => v.toFixed(3)],
  ["verified_rate", "主张核验通过率", (v) => `${(v * 100).toFixed(0)}%`],
  ["coverage_rate", "关键项覆盖率", (v) => `${(v * 100).toFixed(0)}%`],
  ["numeric_accuracy", "数字可复算率", (v) => `${(v * 100).toFixed(0)}%`],
  ["dissents", "反方观点数", (v) => v.toFixed(1)],
  ["tokens", "Token", (v) => Math.round(v).toLocaleString()],
  ["search_calls", "搜索次数", (v) => v.toFixed(1)],
  ["seconds", "耗时（秒）", (v) => v.toFixed(0)],
];

export default function Evals() {
  const { id } = useParams();
  const nav = useNavigate();
  const [runs, setRuns] = useState<EvalRun[] | null>(null);
  const [run, setRun] = useState<EvalRun | null>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => { api.evals().then(setRuns); }, [msg]);
  useEffect(() => {
    if (!id) { setRun(null); return; }
    let timer: number | undefined;
    const load = async () => {
      const r = await api.evalRun(id);
      setRun(r);
      if (r.status === "running") timer = window.setTimeout(load, 4000);
    };
    load();
    return () => window.clearTimeout(timer);
  }, [id]);

  const startCompare = async () => {
    if (!confirm("对照评测会对每个用例分别跑标准研究与争议深研（约 10-20 分钟，消耗 DeepSeek 额度）。继续？")) return;
    const { run_id } = await api.startCompare({ routes: ["standard", "deep"] });
    nav(`/evals/${run_id}`);
  };
  const startUpdate = async () => {
    const { run_id } = await api.startUpdateEval();
    nav(`/evals/${run_id}`);
    api.evals().then(setRuns);
  };
  const startRouting = async () => {
    await api.startRoutingEval();
    setMsg("路由校准已提交，约 1 分钟后刷新列表。");
    setTimeout(() => setMsg(""), 60000);
  };

  return (
    <div className="page">
      <h1>评测</h1>
      <p className="muted">
        二期出口标准：对照"单 Agent + SOP"基线，多专家<b>质量不退化且成本可接受</b>，否则保留单 Agent。
        同一问题、同一 as_of、同一数据与核验规则；评测档案写入隔离命名空间，不进入用户档案。LLM 评分不用于自我验收。
      </p>
      <div className="row-btns">
        <button className="primary" onClick={startCompare}>运行对照评测</button>
        <button onClick={startRouting}>运行路由校准</button>
        <button onClick={startUpdate}>运行持续更新评测</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>

      {run && (run.type === "compare" ? <CompareView run={run} /> : run.type === "update" ? <UpdateView run={run} /> : <RoutingView run={run} />)}

      <h2>历史评测</h2>
      {runs === null ? <p className="muted">加载中…</p> : runs.length === 0 ? <p className="muted">还没有评测。</p> : (
        <div className="list">
          {runs.map((r) => (
            <Link key={r.run_id} to={`/evals/${r.run_id}`} className={`list-item ${r.run_id === id ? "current" : ""}`}>
              <span className="tag">{({ compare: "对照评测", routing: "路由校准", update: "持续更新" } as Record<string, string>)[r.type]}</span>
              <StatusBadge status={r.status === "running" ? "running" : "done"} />
              <span className="grow">
                {r.type === "compare" ? (r.summary?.verdict.text ?? "运行中") : r.type === "update" ? updateLine(r) :
                  `准确率 ${(r.accuracy ?? 0) * 100}% · 深研召回 ${((r.deep_recall ?? 0) * 100).toFixed(0)}% · 建议温度 ${r.calibration?.best_temperature ?? "—"}`}
              </span>
              <span className="muted small">{fmtTime(r.created_at)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function CompareView({ run }: { run: EvalRun }) {
  const s = run.summary;
  const routes = run.routes ?? [];
  const v = s?.verdict;
  return (
    <div>
      {v && v.decision !== "insufficient" && (
        <div className={`card ${v.decision === "adopt_multi_expert" ? "success" : "warnbox"}`}>
          <div>
            <h3>{v.text}</h3>
            <div className="small">
              质量差（深研 − 标准）<b>{v.quality_delta}</b>（非劣界 −{v.criteria?.non_inferior_margin}）·
              成本倍数 <b>{v.cost_ratio}×</b>（上限 {v.criteria?.max_cost_ratio}×）
            </div>
          </div>
        </div>
      )}
      {run.status === "running" && <p className="muted"><span className="spinner inline" /> 评测进行中：已完成 {run.results?.length ?? 0} / {(run.cases?.length ?? 0) * routes.length}</p>}
      {s && Object.keys(s.routes).length > 0 && (
        <div className="card">
          <h3>汇总（均值）</h3>
          <table className="table">
            <thead><tr><th>指标</th>{routes.map((r) => <th key={r} className="num">{ROUTE_LABEL[r]}</th>)}</tr></thead>
            <tbody>
              {METRIC_ROWS.map(([k, label, f]) => (
                <tr key={k}><td>{label}</td>{routes.map((r) => <td key={r} className="num">{s.routes[r] ? f(s.routes[r][k]) : "—"}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="card">
        <h3>逐例结果</h3>
        <table className="table">
          <thead><tr><th>用例</th><th>流程</th><th className="num">质量分</th><th className="num">核验</th><th>覆盖</th><th className="num">Token</th><th>档案</th></tr></thead>
          <tbody>
            {(run.results ?? []).map((r, i) => (
              <tr key={i}>
                <td>{r.case}</td><td>{ROUTE_LABEL[r.route]}</td>
                <td className="num">{r.metrics?.score ?? "—"}</td>
                <td className="num">{r.metrics ? `${r.metrics.verified}/${r.metrics.claims}` : "—"}</td>
                <td className="small">{r.metrics ? Object.entries(r.metrics.coverage).map(([k, ok]) => (
                  <span key={k} className={`cov ${ok ? "ok" : "miss"}`}>{k}</span>)) : <span className="warn-text">{r.error}</span>}</td>
                <td className="num">{r.metrics?.tokens.toLocaleString() ?? "—"}</td>
                <td>{r.dossier_key ? <Link to={`/dossiers/${encodeURIComponent(r.dossier_key)}/${r.version}`}>查看</Link> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const pct = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const VERDICT: Record<string, string> = { retained: "保留", weakened: "削弱", invalidated: "失效", unverifiable: "无法判断" };

function updateLine(r: EvalRun): string {
  const s = r.update_summary ?? {};
  return `${r.case_count ?? 0} 个案例 · 受影响结论有交代 ${pct(s.coverage)} · 用上新数据 ${pct(s.absorbed)} · 未受影响不丢失 ${pct(s.stable)}`;
}

/** 持续更新：新证据出现后，受影响的结论有没有被修正、没受影响的有没有被保留。 */
function UpdateView({ run }: { run: EvalRun }) {
  const labels = run.metric_labels ?? {};
  const s = run.update_summary ?? {};
  return (
    <div>
      <p className="muted">
        案例来自「订阅提醒 → 用新数据重新研究」的真实记录，每个新财报季会自动增加。纯代码打分，不用模型自评；
        人工金标可选（<code>evals/update/labels.yaml</code>，目前 {run.labeled ?? 0} 个案例有标注）。
      </p>
      <div className="stat-row">
        {Object.entries(labels).map(([k, label]) => (
          <div key={k} className="card stat"><div className="muted small">{label}</div><b>{pct(s[k])}</b></div>
        ))}
      </div>
      {!run.update_results?.length && <div className="empty">还没有已重新研究的订阅提醒。在「订阅与复核」里对提醒点「用新数据重新研究」后，就会成为案例。</div>}
      {run.update_results?.map((c) => (
        <div key={c.alert_id} className="card">
          <h3>{c.name || c.ticker} <span className="muted small">{c.ticker} · 档案 v{c.from_version}（{c.old_as_of}）→ v{c.to_version}（{c.new_as_of}）· 提醒 {c.alert_id}</span></h3>
          <p className="small">变化：{c.events.join("；")}</p>
          {c.absorbed.length > 0 && (
            <p className="small">新数据：{c.absorbed.map((a) => `${a.event}${a.ok ? "（已用上）" : "（没用上）"}`).join("；")}</p>
          )}
          <table className="table">
            <thead><tr><th>旧结论</th><th>受影响</th><th>新版本的复核</th><th>仍在新版本</th></tr></thead>
            <tbody>{c.claims.map((x) => {
              const lost = !x.affected && !x.verdict && !x.kept;
              return (
                <tr key={x.id}>
                  <td><span className="muted small">{x.id}</span> {x.text}</td>
                  <td>{x.affected ? "是" : "否"}</td>
                  <td className={x.affected && !x.verdict ? "warn-text" : ""}>{x.verdict ? VERDICT[x.verdict] ?? x.verdict : x.affected ? "没有交代" : "—"}</td>
                  <td className={lost ? "warn-text" : ""}>{x.kept ? "是" : lost ? "否，且没有说明" : "否"}</td>
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

function RoutingView({ run }: { run: EvalRun }) {
  const labels = ["quick", "standard", "deep"];
  const cal = run.calibration;
  return (
    <div>
      <div className="stat-row">
        <div className="card stat"><div className="muted small">准确率</div><b>{((run.accuracy ?? 0) * 100).toFixed(0)}%</b></div>
        <div className="card stat"><div className="muted small">深研召回</div><b>{((run.deep_recall ?? 0) * 100).toFixed(0)}%</b></div>
        <div className="card stat"><div className="muted small">拒判率</div><b>{((run.abstain_rate ?? 0) * 100).toFixed(0)}%</b></div>
        <div className="card stat"><div className="muted small">建议温度</div><b>{cal?.best_temperature ?? "—"}</b>
          <div className="muted small">当前 {run.current?.temperature}</div></div>
      </div>
      <div className="two-col">
        <div className="card">
          <h3>混淆矩阵 <span className="muted small">行=人工标签，列=路由结果</span></h3>
          <table className="table">
            <thead><tr><th></th>{labels.map((l) => <th key={l} className="num">{ROUTE_LABEL[l]}</th>)}</tr></thead>
            <tbody>{labels.map((a) => (
              <tr key={a}><td>{ROUTE_LABEL[a]}</td>{labels.map((b) => (
                <td key={b} className={`num ${a === b ? "diag" : ""}`}>{run.confusion?.[a]?.[b] ?? 0}</td>))}</tr>
            ))}</tbody>
          </table>
        </div>
        <div className="card">
          <h3>温度校准 <span className="muted small">按 NLL 选温度；ECE 越低越可信</span></h3>
          <table className="table">
            <thead><tr><th>温度</th><th className="num">NLL</th><th className="num">ECE</th><th className="num">拒判率</th></tr></thead>
            <tbody>{cal && Object.entries(cal.by_temperature).map(([t, m]) => (
              <tr key={t} className={Number(t) === cal.best_temperature ? "best" : ""}>
                <td>{t}</td><td className="num">{m.nll}</td><td className="num">{m.ece}</td><td className="num">{(m.abstain_rate * 100).toFixed(0)}%</td>
              </tr>))}</tbody>
          </table>
        </div>
      </div>
      <div className="card">
        <h3>逐题</h3>
        <table className="table">
          <thead><tr><th>问题</th><th>标签</th><th>路由</th><th>来源</th><th>概率 快/标/深</th></tr></thead>
          <tbody>{(run.rows ?? []).map((r, i) => (
            <tr key={i} className={r.correct ? "" : "dim"}>
              <td>{r.question}</td><td>{ROUTE_LABEL[r.label]}</td>
              <td className={r.correct ? "" : "warn-text"}>{ROUTE_LABEL[r.route]}{r.abstain ? "（拒判）" : ""}</td>
              <td className="muted small">{r.source}</td>
              <td className="num small">{labels.map((l) => (r.probs[l] ?? 0).toFixed(2)).join(" / ")}</td>
            </tr>))}</tbody>
        </table>
      </div>
    </div>
  );
}
