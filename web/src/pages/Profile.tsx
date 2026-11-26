import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ImpactChanges } from "../components/Personal";
import { PageHead, useAskContext } from "../components/Shell";
import { fmtTime } from "../format";
import type { Holding, ProfileState, ProfileVersion, RiskProfile } from "../types";

const EMPTY_RISK: RiskProfile = { max_drawdown_pct: null, horizon_months: null, liquidity_note: "" };
const num = (v: string) => (v.trim() === "" ? null : Number(v));

/** 用户确认档案：个人约束只能由你本人确认；每次保存都是新版本，旧版本保留。 */
export default function Profile() {
  const [state, setState] = useState<ProfileState | null>(null);
  const [risk, setRisk] = useState<RiskProfile>(EMPTY_RISK);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  useAskContext({ title: "我的约束", suggestions: ["合同负债大幅下降一定说明需求走弱吗？"] }, []);

  const load = () => api.profile.get().then((s) => {
    setState(s);
    setRisk(s.current?.risk ?? EMPTY_RISK);
    setHoldings(s.current?.holdings ?? []);
  });
  useEffect(() => { load(); }, []);

  const setH = (i: number, patch: Partial<Holding>) => setHoldings((hs) => hs.map((h, k) => (k === i ? { ...h, ...patch } : h)));
  const save = async () => {
    setMsg(null);
    try {
      const v = await api.profile.confirm({ risk, holdings, change_note: note, confirmed });
      const n = v.impact?.length ?? 0;
      setMsg({ ok: true, text: `已保存为 v${v.version}。` + (n ? `有 ${n} 份档案的个人情境结论因此改变，见下方版本记录。` : "没有档案的个人情境结论因此改变。") });
      setNote(""); setConfirmed(false); load();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  };

  return (
    <>
      <PageHead title="我的约束" sub="只能由你本人确认 · 只在本地对照 · 不发往模型或搜索" />
      <div className="page narrow">
        <section className="card form">
          <h3 style={{ margin: 0 }}>风险与期限</h3>
          <div className="two-col">
            <label>可承受的最大回撤（%）
              <input type="number" min={1} max={100} value={risk.max_drawdown_pct ?? ""} placeholder="例如 20"
                onChange={(e) => setRisk({ ...risk, max_drawdown_pct: num(e.target.value) })} /></label>
            <label>这笔钱可以投多久（月）
              <input type="number" min={1} value={risk.horizon_months ?? ""} placeholder="例如 36"
                onChange={(e) => setRisk({ ...risk, horizon_months: num(e.target.value) })} /></label>
          </div>
          <label>何时要用钱、用途（可选）
            <input value={risk.liquidity_note} maxLength={200} placeholder="例如：两年后换房首付"
              onChange={(e) => setRisk({ ...risk, liquidity_note: e.target.value })} /></label>

          <h3 style={{ margin: "8px 0 0" }}>关注 / 持有的股票 <span className="muted small">只记理由和期限，不记金额与账户</span></h3>
          {holdings.map((h, i) => (
            <div key={i} className="card" style={{ margin: 0, background: "var(--panel-2)" }}>
              <div className="two-col">
                <label>代码<input value={h.ticker} maxLength={6} placeholder="600519" onChange={(e) => setH(i, { ticker: e.target.value.trim() })} /></label>
                <label>期限（月，可选）<input type="number" value={h.horizon_months ?? ""} onChange={(e) => setH(i, { horizon_months: num(e.target.value) })} /></label>
              </div>
              <label>购买 / 关注理由<textarea rows={2} value={h.thesis} maxLength={300} placeholder="例如：高端白酒提价能力强，现金流稳定"
                onChange={(e) => setH(i, { thesis: e.target.value })} /></label>
              <button className="ghost" onClick={() => setHoldings(holdings.filter((_, k) => k !== i))}>移除</button>
            </div>
          ))}
          <button className="ghost" style={{ alignSelf: "flex-start" }}
            onClick={() => setHoldings([...holdings, { ticker: "", name: "", thesis: "", horizon_months: null }])}>＋ 添加股票</button>

          <label>这次改了什么（可选）<input value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} /></label>
          <label className="check"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            我确认以上信息由我本人填写。系统不会替我填写或修改这些约束。</label>
          {msg && <div className={msg.ok ? "muted" : "error"}>{msg.text}</div>}
          <button className="primary" style={{ alignSelf: "flex-start" }} disabled={!confirmed} onClick={save}>确认并保存新版本</button>
        </section>

        <h2>版本记录</h2>
        <section className="card">
          {!state?.history.length ? <div className="empty">还没有确认过任何约束。没确认的，个人情境官一律标「未知」。</div> : (
            <div className="pv-list">
              {state.history.map((h, i) => <ProfileVersionView key={h.version} v={h} prev={state.history[i + 1]} current={i === 0} />)}
            </div>
          )}
        </section>
      </div>
    </>
  );
}

const months = (n: number | null) => (n == null ? "未填" : `${n} 个月`);

/** 一个确认版本的完整内容，并列出相比上一版改了什么。 */
function ProfileVersionView({ v, prev, current }: { v: ProfileVersion; prev?: ProfileVersion; current: boolean }) {
  const changes = prev ? diffProfile(prev, v) : ["首次确认"];
  return (
    <details className="pv" open={current}>
      <summary>
        <span className="tag">v{v.version}</span>
        {current && <span className="tag purple">当前生效</span>}
        <span className="pv-sum">{v.change_note || changes.join("；")}</span>
        <span className="muted small">{fmtTime(v.confirmed_at)}</span>
      </summary>
      <div className="pv-body">
        <div className="kv"><span>可承受最大回撤</span>{v.risk.max_drawdown_pct == null ? "未填" : `${v.risk.max_drawdown_pct}%`}</div>
        <div className="kv"><span>资金可投期限</span>{months(v.risk.horizon_months)}</div>
        <div className="kv"><span>用钱时间与用途</span>{v.risk.liquidity_note || "未填"}</div>
        <div className="kv"><span>关注 / 持有</span>{v.holdings.length === 0 ? "无" : (
          <ul className="pv-holdings">{v.holdings.map((h) => (
            <li key={h.ticker}><b>{h.name || h.ticker}</b> <span className="muted small">{h.name ? `${h.ticker} · ` : ""}持有期限 {months(h.horizon_months)}</span>
              <div className="small">理由：{h.thesis || "未填"}</div></li>))}</ul>
        )}</div>
        {prev && <div className="kv"><span>相比 v{prev.version}</span>{changes.join("；")}</div>}
        {v.impact && (
          <div className="kv"><span>受影响的档案</span>{v.impact.length === 0 ? <span className="muted">没有档案的个人情境结论因此改变</span> : (
            <div className="pv-impact">{v.impact.map((x) => (
              <div key={x.ticker}>
                <Link to={`/dossiers/${x.ticker}`}><b>{x.name || x.ticker}</b></Link> <span className="muted small">{x.ticker} · 档案 v{x.dossier_version}</span>
                <ImpactChanges x={x} />
              </div>
            ))}</div>
          )}</div>
        )}
      </div>
    </details>
  );
}

function diffProfile(a: ProfileVersion, b: ProfileVersion): string[] {
  const out: string[] = [];
  if (a.risk.max_drawdown_pct !== b.risk.max_drawdown_pct) out.push(`最大回撤 ${a.risk.max_drawdown_pct ?? "未填"}% → ${b.risk.max_drawdown_pct ?? "未填"}%`);
  if (a.risk.horizon_months !== b.risk.horizon_months) out.push(`可投期限 ${months(a.risk.horizon_months)} → ${months(b.risk.horizon_months)}`);
  if (a.risk.liquidity_note !== b.risk.liquidity_note) out.push("用钱时间与用途有改动");
  const old = new Map(a.holdings.map((h) => [h.ticker, h]));
  const now = new Map(b.holdings.map((h) => [h.ticker, h]));
  for (const h of b.holdings) {
    const o = old.get(h.ticker);
    if (!o) out.push(`新增 ${h.name || h.ticker}`);
    else if (o.thesis !== h.thesis || o.horizon_months !== h.horizon_months) out.push(`修改 ${h.name || h.ticker}`);
  }
  for (const h of a.holdings) if (!now.has(h.ticker)) out.push(`移除 ${h.name || h.ticker}`);
  return out.length ? out : ["内容没有变化"];
}
