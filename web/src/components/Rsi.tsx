import { zh } from "../format";
import type { GateResult, LessonCard, RsiEvent, SliceStat } from "../types";

export const SCEN: Record<string, { tag: string; name: string; kind: string; desc: string }> = {
  S1: { tag: "专家经验改进", name: "从被推翻的结论里总结经验", kind: "经验卡", desc: "专家被质疑成功的说法 → 写成一张经验卡，下次研究时提醒专家" },
  S2: { tag: "研究方式改进", name: "让系统更会判断查多细", kind: "路由参数", desc: "该细查却快查了的问题 → 调整判断标准" },
  S3: { tag: "搜索改进", name: "让搜索找到更有用的资料", kind: "检索模板", desc: "搜到的多是用不上的结果 → 调整搜索方向、筛选标准或可读取的网站（加网站属高风险）" },
};
export const RUN_STATUS: Record<string, string> = {
  draft: "草稿", review: "待审", approved: "已批准", released: "已发布", archived: "已归档", rejected: "已拒绝", rolled_back: "已回滚",
};
const SLICE: Record<string, string> = { evolution: "新失败集", replay: "固定回放集", holdout: "留出集" };
const SLICE_TIP: Record<string, string> = {
  evolution: "本次候选针对的坏案例所在样本", replay: "首次评测时冻结，每轮考同一套题", holdout: "没见过的标的 / 未参与进化的问题",
};
const ARM: Record<string, string> = { off: "不用经验库", base: "现在的版本", cand: "改进的版本" };
const ACTION: Record<string, string> = {
  bootstrap: "基线", collect: "收集", propose: "提议", evaluate: "评测", submit: "提交", approve: "批准", reject: "拒绝",
  release: "发布", archive: "归档", rollback: "回滚", rolled_back: "回滚",
};

export function RunStatus({ s }: { s: string }) {
  return <span className={`badge st-${s}`}>{RUN_STATUS[s] ?? s}</span>;
}

export function GateDots({ gates }: { gates: GateResult[] }) {
  if (!gates.length) return <span className="gate-dots" title="尚未评测">{Array.from({ length: 6 }, (_, i) => <i key={i} className="gdot" />)}</span>;
  return (
    <span className="gate-dots" title={gates.map((g) => `${g.passed ? "✓" : "✗"} ${g.label}`).join("\n")}>
      {gates.map((g) => <i key={g.name} className={`gdot ${g.passed ? "pass" : "fail"}`} />)}
    </span>
  );
}

const GATE_ORDER: [string, string, string][] = [
  ["protocol", "协议一致", "评测集与评分规则必须与冻结协议一致"], ["leakage", "防泄漏", "留出集不能出现在进化集里"],
  ["overfit", "防过拟合", "卡片不许有具体股票、数字或结论"], ["noise", "噪声门控", "≥3 次重复，提升须超过波动"],
  ["cost", "成本门控", "花费上涨必须换来同等质量收益"], ["regression", "回归门控", "固定回放集与留出集不能退化"],
];

/** 门控网格：order 为 [键, 名称, 说明]；默认是 RSI 六道门控。 */
export function GateGrid({ gates, order = GATE_ORDER }: { gates: GateResult[]; order?: [string, string, string][] }) {
  const by = new Map(gates.map((g) => [g.name, g]));
  return (
    <div className="gates">
      {order.map(([k, label, tip]) => {
        const g = by.get(k);
        return (
          <div key={k} className={`gate ${g ? (g.passed ? "pass" : "fail") : "idle"}`}>
            <span className="gl" aria-hidden /><span className="gn">{label} {g ? (g.passed ? "通过" : "未通过") : "待评测"}</span>
            <span className="gd">{g ? zh(g.detail) : tip}</span>
          </div>
        );
      })}
    </div>
  );
}

/** 同台对比：每个切片三条横向条（关经验库 / 在用 / 候选），须线 = 多次重复的最小～最大值。 */
export function CompareChart({ arms, metric }: { arms: Record<string, { slices: Record<string, SliceStat> } | undefined>; metric?: string }) {
  const present = (["off", "base", "cand"] as const).filter((a) => arms[a]);
  const slices = ["evolution", "replay", "holdout"].filter((s) => present.some((a) => arms[a]!.slices[s]));
  return (
    <div className="cmp">
      <div className="cmp-legend">
        {present.map((a) => <span key={a}><i className={`cmp-bar ${a}`} style={{ position: "static" }} />{ARM[a]}</span>)}
        <span className="muted">须线 = 多次重复的波动范围{metric ? ` · ${metric}` : ""}</span>
      </div>
      {slices.map((s) => (
        <div key={s} className="cmp-group">
          <div className="cg-t">{SLICE[s]} <span className="muted small">{SLICE_TIP[s]}</span></div>
          {present.map((a) => {
            const st = arms[a]!.slices[s];
            if (!st || st.mean == null) return null;
            const lo = Math.min(...st.runs), hi = Math.max(...st.runs);
            return (
              <div key={a} className="cmp-row" title={`${ARM[a]} · ${SLICE[s]}：各次 ${st.runs.map((x) => x.toFixed(3)).join(" / ")}`}>
                <span>{ARM[a]}</span>
                <span className="cmp-track">
                  <span className={`cmp-bar ${a}`} style={{ width: `${st.mean * 100}%` }} />
                  {hi > lo && <span className="cmp-spread" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />}
                </span>
                <span className="cmp-val">{st.mean.toFixed(3)}{st.spread ? <span className="muted"> ±{(st.spread / 2).toFixed(3)}</span> : null}</span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

export function LessonView({ c, badge }: { c: LessonCard; badge?: string }) {
  return (
    <div className="lesson">
      <div className="lt">经验卡 {c.id} <span className="tag purple">r{c.rev}</span>{badge && <span className="tag">{badge}</span>}{c.title}</div>
      <dl>
        <dt>适用</dt><dd>{c.applies_to}</dd>
        <dt>教训</dt><dd>{c.lesson}</dd>
        {c.must_check.length > 0 && <><dt>必查</dt><dd>{c.must_check.join("；")}</dd></>}
        {c.invalid_if && <><dt>失效条件</dt><dd>{c.invalid_if}</dd></>}
        <dt>召回标签</dt><dd>{c.tags.map((t) => <span key={t} className="tag" style={{ marginRight: 4 }}>{t}</span>)}</dd>
        <dt>来源</dt><dd className="muted">{c.source}</dd>
      </dl>
    </div>
  );
}

function shortTime(ts: string) {
  const d = new Date(ts.endsWith("Z") || ts.includes("+") ? ts : ts + "Z");
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function EventList({ events }: { events: RsiEvent[] }) {
  if (!events.length) return <div className="empty">日志里还没有记录</div>;
  return (
    <ul className="events">
      {events.map((e, i) => (
        <li key={i}>
          <span className="muted">{shortTime(e.ts)}</span>
          <span className="ea">{ACTION[e.action] ?? e.action}</span>
          <span>{zh(e.detail)}{e.actor && <span className="muted"> · {zh(e.actor)}</span>}{e.self_approved && <span className="tag warn" style={{ marginLeft: 6 }}>自批</span>}</span>
        </li>
      ))}
    </ul>
  );
}
