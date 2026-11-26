import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { GateGrid } from "../components/Rsi";
import { PageHead, useShell } from "../components/Shell";
import { NavChart, RuleChips, STRATEGY_GATES } from "../components/Strategy";
import { fmtTime } from "../format";
import type { StrategyOverview } from "../types";

const ACTION: Record<string, string> = {
  create: "新建", paper: "开始模拟", gates: "门控", submit: "提交晋级", promote: "晋级", retire: "退役",
  reject: "拒绝", rollback: "回滚", restore: "恢复",
};

type Detail = Awaited<ReturnType<typeof api.strategy.detail>>;

/** 策略卡详情：规则、前向净值、晋级门控、模拟成交（每笔可追溯到档案）与状态操作。 */
export default function StrategyCard() {
  const { id = "", version = "1" } = useParams();
  const v = Number(version);
  const shell = useShell();
  const [data, setData] = useState<Detail | null>(null);
  const [meta, setMeta] = useState<StrategyOverview | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.strategy.detail(id, v).then(setData).catch((e) => setError(e.message));
    api.strategy.overview().then(setMeta).catch(() => undefined);
  }, [id, v]);
  useEffect(load, [load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (e) { setError((e as Error).message); }
    setBusy(false); load(); shell.refresh();
  };

  if (error && !data) return <div className="page"><div className="error">{error}</div></div>;
  if (!data || !meta) return <div className="page muted">加载中…</div>;
  const { card, navs, trades, versions, events } = data;
  const label = meta.status_label;
  const selfApproved = card.approvals.some((a) => a.self_approved);

  return (
    <>
      <PageHead title={<>{card.name} · <code>{card.card_id} v{card.version}</code></>} sub={<span className={`badge st-${card.status}`}>{label[card.status]}</span>}
        right={<Link to="/strategy" className="button ghost">返回策略列表</Link>} />
      <div className="page narrow">
        <section className="card">
          <div className="kv"><span>策略逻辑</span><b>{card.thesis}</b></div>
          <div className="kv"><span>纳入</span><RuleChips rules={card.entry} fields={meta.fields} /></div>
          <div className="kv"><span>移出</span><RuleChips rules={card.exit} fields={meta.fields} empty="无（只看止损与档案）" /></div>
          <div className="kv"><span>参数</span>候选 {card.universe.length ? card.universe.join("、") : "全部有档案的股票"} · 最多 {card.max_positions} 只 · 止损 {card.stop_loss_pct ?? "—"}% · 晋级回撤上限 {card.max_drawdown_limit}%</div>
          <div className="kv"><span>改动理由</span>{card.change_reason}{card.parent_version ? `（基于 v${card.parent_version}）` : ""}</div>
          <div className="kv"><span>前向模拟</span>{card.paper_start ? `自 ${card.paper_start} 起，${card.stats.days} 个交易日` : "未开始"}</div>
          {card.reject_reason && <div className="error" style={{ marginBottom: 0 }}>{card.reject_reason}</div>}
          {selfApproved && <div className="selfapp" style={{ marginTop: 10 }}>本次晋级为「自批」：创建人与批准人相同。单人阶段如实标出。</div>}
          {error && <div className="error">{error}</div>}
          <div className="row-btns" style={{ marginTop: 14, marginBottom: 0, alignItems: "center" }}>
            {card.status === "draft" && <button className="primary" disabled={busy} onClick={() => act(() => api.strategy.paper(id, v))}>从今天开始前向模拟</button>}
            {card.status === "paper" && <button className="primary" disabled={busy} onClick={() => act(() => api.strategy.submit(id, v))}>跑晋级门控</button>}
            {card.status === "review" && (
              <>
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="批准意见（可选）" style={{ flex: 1, minWidth: 180 }} />
                <button className="primary" disabled={busy} onClick={() => act(() => api.strategy.approve(id, v, note))}>批准晋级</button>
              </>
            )}
            {["draft", "paper", "review"].includes(card.status) && (
              <>
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="拒绝理由" style={{ minWidth: 140 }} />
                <button className="danger" disabled={busy || reason.trim().length < 2} onClick={() => act(() => api.strategy.reject(id, v, reason))}>拒绝</button>
              </>
            )}
            {card.status === "promoted" && (
              <>
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="回滚理由（不少于 10 个字）" style={{ flex: 1, minWidth: 200 }} />
                <button className="danger" disabled={busy || reason.trim().length < 10} onClick={() => act(() => api.strategy.rollback(id, reason))}>一键回滚</button>
              </>
            )}
          </div>
        </section>

        <h2>前向净值 <span className="muted small">收益 {card.stats.return_pct.toFixed(2)}% · 最大回撤 {card.stats.max_drawdown_pct.toFixed(2)}% · 虚线为初始资金</span></h2>
        <section className="card"><NavChart navs={navs} initial={meta.initial_cash} /></section>

        <h2>晋级门控</h2>
        <GateGrid gates={card.gates} order={STRATEGY_GATES} />

        <h2>模拟成交 <span className="muted small">每笔都记下依据的档案版本与证据</span></h2>
        {trades.length === 0 ? <div className="empty">还没有成交</div> : (
          <div className="card table">
            <table className="table">
              <thead><tr><th>日期</th><th>方向</th><th>股票</th><th className="num">股数</th><th className="num">价格</th><th>依据</th></tr></thead>
              <tbody>
                {trades.map((t, i) => (
                  <tr key={i}>
                    <td className="small">{t.date}</td>
                    <td><span className={`tag ${t.side === "open" ? "purple" : ""}`}>{t.side === "open" ? "纳入" : "移出"}</span></td>
                    <td>{t.dossier_version ? <Link to={`/dossiers/${t.ticker}/${t.dossier_version}`}>{t.ticker} · 档案 v{t.dossier_version}</Link> : t.ticker}</td>
                    <td className="num">{t.shares.toLocaleString()}</td>
                    <td className="num">{t.price.toFixed(2)}</td>
                    <td className="small">{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="two-col" style={{ marginTop: 12 }}>
          <section className="card">
            <h3>版本</h3>
            <ul className="lin-chain">
              {versions.map((x) => (
                <li key={x.version} className={x.version === v ? "active" : ""}>
                  <Link to={`/strategy/${id}/${x.version}`} className="lv">v{x.version}</Link> <span className={`badge st-${x.status}`}>{label[x.status]}</span>
                  <span className="lr">{x.change_reason}</span>
                </li>
              ))}
            </ul>
          </section>
          <section className="card">
            <h3>事件</h3>
            <ul className="events">
              {events.map((e, i) => (
                <li key={i}><span className="muted">{fmtTime(e.ts)}</span><span className="ea">{ACTION[e.action] ?? e.action}</span>
                  <span>{e.detail}<span className="muted"> · {e.actor}</span>{e.self_approved && <span className="tag warn" style={{ marginLeft: 6 }}>自批</span>}</span></li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </>
  );
}
