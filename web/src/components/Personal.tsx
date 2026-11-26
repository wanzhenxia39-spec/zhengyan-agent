import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Alert, FitStatus, PersonalFit, ProfileImpact } from "../types";

export const FIT_LABEL: Record<FitStatus, string> = { ok: "相容", attention: "留意", conflict: "冲突", unknown: "未知" };
export const EVENT_LABEL: Record<Alert["events"][number]["kind"], string> = {
  new_report: "新财报", announcement: "新公告", price_move: "价格异动", trigger: "复核条件（可能触发）",
};
export const ALERT_STATUS: Record<Alert["status"], string> = { open: "待处理", reviewing: "重新研究中", resolved: "已重新研究", dismissed: "已忽略" };

/** 一份档案因修改约束而变化的个人情境结论：之前 → 现在。 */
export function ImpactChanges({ x }: { x: ProfileImpact }) {
  return (
    <ul className="fit">
      {x.changes.map((c) => (
        <li key={c.key} className={c.after}>
          <span className="dot" aria-hidden /><span className="fl">{c.label} · {FIT_LABEL[c.before]} → {FIT_LABEL[c.after]}</span><span>{c.detail}</span>
        </li>
      ))}
    </ul>
  );
}

export function FitList({ fit }: { fit: PersonalFit }) {
  return (
    <>
      <p className="fit-sum">{fit.summary}</p>
      <ul className="fit">
        {fit.checks.map((c) => (
          <li key={c.key} className={c.status}>
            <span className="dot" aria-hidden /><span className="fl">{c.label} · {FIT_LABEL[c.status]}</span><span>{c.detail}</span>
          </li>
        ))}
      </ul>
      <p className="muted small" style={{ marginBottom: 0 }}>{fit.disclaimer}</p>
    </>
  );
}

/** 档案页里的「个人情境」卡：对照你确认过的约束，附订阅入口。 */
export function PersonalPanel({ ticker }: { ticker: string }) {
  const [fit, setFit] = useState<PersonalFit | null>(null);
  const [change, setChange] = useState<(ProfileImpact & { profile_version: number }) | null>(null);
  const [subscribed, setSubscribed] = useState<boolean | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => {
    api.profile.fit(ticker).then((r) => { setFit(r.fit); setChange(r.profile_change); }).catch(() => setFit(null));
    api.watch.overview().then((w) => setSubscribed(w.subscriptions.some((s) => s.ticker === ticker && s.active))).catch(() => undefined);
  };
  useEffect(load, [ticker]);
  const subscribe = async () => {
    try { await api.watch.subscribe(ticker); setMsg("已订阅：新财报、新公告、价格异动会提醒你"); load(); }
    catch (e) { setMsg((e as Error).message); }
  };
  return (
    <section className="card">
      <div className="title-row">
        <h3 style={{ margin: 0 }}>个人情境</h3>
        <span className="muted small">个人情境官只对照你确认过的约束</span>
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {subscribed === false && <button onClick={subscribe}>订阅变化</button>}
          {subscribed && <Link className="button ghost" to="/watch">已订阅 · 查看提醒</Link>}
          <Link className="button ghost" to="/profile">编辑我的约束</Link>
        </span>
      </div>
      {msg && <p className="muted small">{msg}</p>}
      {change && (
        <div className="impact-note">
          <b>你在约束 v{change.profile_version} 里做了修改，这份档案的个人情境结论因此变了：</b>
          <ImpactChanges x={change} />
          <span className="muted small">档案里的研究结论不依赖你的约束，不需要重新研究；需要重新判断的是它和你的情况是否还相容。</span>
        </div>
      )}
      <div style={{ marginTop: 10 }}>{fit ? <FitList fit={fit} /> : <span className="muted">加载中…</span>}</div>
    </section>
  );
}
