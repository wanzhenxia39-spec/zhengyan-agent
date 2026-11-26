import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, waitJob } from "../api";
import { GateDots } from "../components/Rsi";
import { PageHead, useAskContext } from "../components/Shell";
import { RuleChips, RuleEditor } from "../components/Strategy";
import type { Rule, StrategyOverview } from "../types";

const DEFAULT_ENTRY: Rule[] = [{ field: "status", op: "==", value: "committed" }, { field: "pe_pct", op: "<=", value: 40 }];
const DEFAULT_EXIT: Rule[] = [{ field: "open_alerts", op: ">=", value: 1 }];

/** 策略卡列表 + 新建。策略卡只在前向模拟盘上运行，系统不执行任何真实交易。 */
export default function Strategy() {
  const nav = useNavigate();
  const [ov, setOv] = useState<StrategyOverview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState("");
  const [form, setForm] = useState<null | { name: string; thesis: string; universe: string; entry: Rule[]; exit: Rule[];
    max_positions: number; stop_loss_pct: number; max_drawdown_limit: number; change_reason: string }>(null);
  useAskContext({ title: "策略与模拟盘", suggestions: ["PE 分位低一定意味着便宜吗？还要核对哪些口径"] }, []);

  const load = useCallback(() => { api.strategy.overview().then(setOv).catch((e) => setError(e.message)); }, []);
  useEffect(load, [load]);

  const step = async () => {
    setBusy(true); setError("");
    try {
      const { job_id } = await api.strategy.step();
      const j = await waitJob(job_id, (x) => setLog(x.log[x.log.length - 1] ?? "推进中…"));
      setLog(j.log.join("；") || "没有模拟中的策略");
    } catch (e) { setError((e as Error).message); }
    setBusy(false); load();
  };
  const create = async () => {
    if (!form) return;
    setError("");
    try {
      const { universe, ...rest } = form;
      const v = await api.strategy.create({ ...rest, universe: universe.split(/[,，\s]+/).filter(Boolean) });
      nav(`/strategy/${v.card_id}/${v.version}`);
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <>
      <PageHead title="策略与模拟盘" sub="规则显式、只向前模拟、晋级须过门控并由你批准；不执行任何真实交易"
        right={<>
          <button disabled={busy} onClick={step}>{busy ? "推进中…" : "推进模拟盘到今天"}</button>
          <button className="primary" onClick={() => setForm({ name: "", thesis: "", universe: "", entry: DEFAULT_ENTRY, exit: DEFAULT_EXIT,
            max_positions: 5, stop_loss_pct: 15, max_drawdown_limit: 20, change_reason: "" })}>新建策略卡</button>
        </>} />
      <div className="page">
        {error && <div className="error">{error}</div>}
        {log && <p className="muted small">{log}</p>}

        {form && ov && (
          <section className="card form">
            <h3 style={{ margin: 0 }}>新建策略卡</h3>
            <div className="two-col">
              <label>名称<input value={form.name} maxLength={40} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
              <label>候选股票（空 = 全部有档案的股票）<input value={form.universe} placeholder="600519, 300750" onChange={(e) => setForm({ ...form, universe: e.target.value })} /></label>
            </div>
            <label>策略逻辑：为什么这些规则有意义<textarea rows={2} value={form.thesis} onChange={(e) => setForm({ ...form, thesis: e.target.value })} /></label>
            <div><div className="muted small" style={{ marginBottom: 6 }}>纳入条件（全部满足）</div>
              <RuleEditor rules={form.entry} fields={ov.fields} onChange={(entry) => setForm({ ...form, entry })} /></div>
            <div><div className="muted small" style={{ marginBottom: 6 }}>移出条件（任一满足）</div>
              <RuleEditor rules={form.exit} fields={ov.fields} onChange={(exit) => setForm({ ...form, exit })} /></div>
            <div className="stat-row" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
              <label>最多持有<input type="number" min={1} max={20} value={form.max_positions} onChange={(e) => setForm({ ...form, max_positions: Number(e.target.value) })} /></label>
              <label>止损 %<input type="number" value={form.stop_loss_pct} onChange={(e) => setForm({ ...form, stop_loss_pct: Number(e.target.value) })} /></label>
              <label>晋级回撤上限 %<input type="number" value={form.max_drawdown_limit} onChange={(e) => setForm({ ...form, max_drawdown_limit: Number(e.target.value) })} /></label>
            </div>
            <label>改动理由（不少于 10 个字）<input value={form.change_reason} onChange={(e) => setForm({ ...form, change_reason: e.target.value })} /></label>
            <div className="row-btns" style={{ margin: 0 }}>
              <button className="primary" disabled={form.change_reason.trim().length < 10 || form.name.trim().length < 2} onClick={create}>保存为草稿</button>
              <button className="ghost" onClick={() => setForm(null)}>取消</button>
            </div>
          </section>
        )}

        {!ov ? <p className="muted">加载中…</p> : ov.cards.length === 0 ? (
          <div className="empty">还没有策略卡。策略卡把「什么情况下纳入 / 移出观察组合」写成规则，在前向模拟盘上检验。</div>
        ) : (
          <div className="card table">
            <table className="table">
              <thead><tr><th>策略卡</th><th>状态</th><th>纳入条件</th><th className="num">模拟</th><th className="num">收益</th><th className="num">最大回撤</th><th>门控</th></tr></thead>
              <tbody>
                {ov.cards.map((c) => (
                  <tr key={`${c.card_id}-${c.version}`} style={{ cursor: "pointer" }} onClick={() => nav(`/strategy/${c.card_id}/${c.version}`)}>
                    <td><Link to={`/strategy/${c.card_id}/${c.version}`}>{c.card_id} v{c.version}</Link> {c.name}
                      <div className="muted small">{c.change_reason}</div></td>
                    <td><span className={`badge st-${c.status}`}>{ov.status_label[c.status]}</span></td>
                    <td><RuleChips rules={c.entry} fields={ov.fields} /></td>
                    <td className="num">{c.stats.days} 天</td>
                    <td className={`num ${c.stats.return_pct > 0 ? "up" : c.stats.return_pct < 0 ? "down" : ""}`}>{c.stats.return_pct.toFixed(2)}%</td>
                    <td className="num">{c.stats.max_drawdown_pct.toFixed(2)}%</td>
                    <td><GateDots gates={c.gates} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {ov && (
          <p className="muted small">晋级门控：前向模拟 ≥ {ov.gates_cfg.min_paper_days} 个交易日、无未来数据、回撤不超上限、每笔可追溯、与在用版本同期收益落后不超过 {ov.gates_cfg.regression_tolerance_pct}%。
            模拟资金 {ov.initial_cash.toLocaleString()}（虚拟），等权、整手。</p>
        )}
      </div>
    </>
  );
}
