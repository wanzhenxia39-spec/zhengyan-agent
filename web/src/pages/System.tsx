import { useEffect, useState } from "react";
import { api } from "../api";
import { ROUTE_LABEL } from "../format";
import type { Meta } from "../types";

const STEPS = [
  { t: "你提一个问题", d: "例如「宁德时代最新一季业绩怎么样？」，可以带股票代码，也可以不带。" },
  { t: "系统决定查多细", d: "简单问题快速回答；复杂或有争议的问题，会请多位「专家」分头去查。" },
  { t: "专家找证据", d: "查财报、行情、公告和新闻，每条结论都要挂上出处，没出处的不算数。" },
  { t: "互相挑错", d: "专家之间互相质疑，专门有一位「反证官」找反面证据，站不住的说法会被拿掉。" },
  { t: "整理成档案", d: "最后汇总成一份决策档案：结论、依据、分歧和还不确定的地方都写清楚。" },
];

const ROUTE_DESC: Record<string, { when: string; how: string }> = {
  quick: { when: "问概念、问一个简单事实", how: "直接回答，少量搜索，不抓原文" },
  standard: { when: "问某家公司的业绩、估值等", how: "取数据、搜资料、核对每条结论；发现争议多会自动升级成争议深研" },
  deep: { when: "问题有争议、影响大，或你主动要求", how: "多位专家分头取证，互相质询辩论，最后由主席综合" },
};

export default function System() {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => { api.meta().then(setMeta); }, []);
  if (!meta) return <div className="page muted">加载中…</div>;
  const ec = meta.expert_cfg;
  return (
    <div className="page">
      <h1>系统介绍</h1>
      <p className="muted">这是一个帮你研究 A 股公司的助手。它只帮你查资料、核对事实、讲清楚利弊，不会替你买卖股票，也不构成投资建议。</p>

      <h2>一个问题是怎么被回答的</h2>
      <div className="grid">
        {STEPS.map((s, i) => (
          <div key={s.t} className="card">
            <div className="title-row"><span className="tag">第 {i + 1} 步</span><b>{s.t}</b></div>
            <p className="small" style={{ margin: 0 }}>{s.d}</p>
          </div>
        ))}
      </div>

      <h2>三种研究方式</h2>
      <p className="muted small">系统会按问题自动选一种，你也可以在「新研究」里自己指定。越细的方式越慢，但查得越多。</p>
      <table className="table card">
        <thead><tr><th>方式</th><th>适合什么问题</th><th>怎么做</th><th>上限</th></tr></thead>
        <tbody>
          {Object.entries(meta.routes).filter(([k]) => k in ROUTE_DESC).map(([k, r]) => (
            <tr key={k}>
              <td><span className={`route-pill rt-${k}`}>{ROUTE_LABEL[k] ?? k}</span></td>
              <td>{ROUTE_DESC[k].when}</td>
              <td className="small">{ROUTE_DESC[k].how}</td>
              <td className="small">搜索 {r.budget.search_calls ?? 0} 次 · 读原文 {r.budget.fetch_calls ?? 0} 篇 · 最长 {Math.round((r.budget.wall_clock_s ?? 0) / 60)} 分钟</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        拿不准该用哪种时，系统会选更稳妥（查得更细）的那种。标准研究中途如果发现有 {meta.routing.escalate_on?.min_disputed} 条以上存疑结论，
        或 {meta.routing.escalate_on?.min_dissents} 条以上反对意见，会自动升级为争议深研，已经查到的资料继续沿用。
      </p>

      <h2>专家团队</h2>
      <p className="muted small">
        争议深研时，系统按缺什么证据来请专家，最多 {ec.max_team} 位，外加一位反证官。每位专家最多搜索 {ec.search_per_expert} 次、
        读 {ec.fetch_per_expert} 篇原文；之后互相质询，辩论 {ec.debate_rounds} 轮。
      </p>
      <table className="table card">
        <thead><tr><th>专家</th><th>负责什么</th><th>必须遵守</th></tr></thead>
        <tbody>
          {meta.experts.map((e) => (
            <tr key={e.key}><td><b>{e.name}</b></td><td>{e.mandate}</td><td className="small">{e.constraint}</td></tr>
          ))}
          <tr><td><b>综合主席</b></td><td>汇总各位专家的证据，写出最终结论，并保留不同意见</td><td className="small">看证据不看人数；被质疑成功的说法不能写进结论</td></tr>
        </tbody>
      </table>

      <h2>哪些事 AI 自己改不了</h2>
      <div className="card small">
        <ul style={{ margin: 0 }}>
          <li>能用哪些数据源、最多花多少钱和时间、结论要过哪些质量检查——这些写在配置文件里，AI 无权修改。</li>
          <li>系统会从做错的案例里总结改进（见 RSI 页），但每一项改进都要经过测试，并由你批准后才会生效，随时可以撤回。</li>
          <li>侧栏和档案里的行情是研究当时取到的数据，不是实时行情。</li>
        </ul>
      </div>
    </div>
  );
}
