import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { today } from "../format";
import { useAskContext } from "../components/Shell";

const EXAMPLES = [
  "复核贵州茅台 600519 最新一期半年报业绩，利润质量如何",
  "宁德时代 300750 最新业绩的同口径变化与主要风险",
  "贵州茅台 600519 当前估值是否已反映业绩下滑风险？多空分歧在哪里",
];

export default function NewResearch() {
  const nav = useNavigate();
  const [question, setQuestion] = useState("");
  const [ticker, setTicker] = useState("");
  const [asOf, setAsOf] = useState(today());
  const [route, setRoute] = useState("auto");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useAskContext({ title: "新研究", suggestions: EXAMPLES }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { task_id } = await api.research({
        question, route, as_of: asOf || undefined, ticker: ticker.trim() || undefined,
      });
      nav(`/tasks/${task_id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="page narrow">
      <h1>新建研究</h1>
      <p className="muted">
        系统会按问题的分量自动选择研究方式：快查（几十秒给出要点）、标准研究（按业绩复核步骤完整研究一遍），
        或争议深研（请几位专家分头研究，再由反证官挑毛病、主席按证据裁定）。结论存为带版本的档案，每条都能点开看依据；
        网上搜到的内容只作线索，数字以财报为准。
      </p>
      <form className="card form" onSubmit={submit}>
        <label>
          研究问题
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} required minLength={2}
            maxLength={500} placeholder="例如：复核贵州茅台 600519 最新一期业绩，利润质量如何" />
        </label>
        <div className="examples">
          {EXAMPLES.map((x) => <button type="button" key={x} className="chip" onClick={() => setQuestion(x)}>{x}</button>)}
        </div>
        <div className="row">
          <label>
            股票代码（可选）
            <input value={ticker} onChange={(e) => setTicker(e.target.value)} pattern="\d{6}" placeholder="600519" />
          </label>
          <label>
            数据截至（留空 = 今天）
            <input type="date" value={asOf} max={today()} onChange={(e) => setAsOf(e.target.value)} />
          </label>
          <label>
            流程
            <select value={route} onChange={(e) => setRoute(e.target.value)}>
              <option value="auto">自动</option>
              <option value="quick">快查（快模型，不抓全文）</option>
              <option value="standard">标准研究（单 Agent + SOP，含补证）</option>
              <option value="deep">争议深研（多专家 + 反证官 + 主席）</option>
            </select>
          </label>
        </div>
        {error && <div className="error">{error}</div>}
        <button className="primary" disabled={busy || question.trim().length < 2}>{busy ? "提交中…" : "开始研究"}</button>
      </form>
      <p className="muted small">请勿输入账户、持仓金额等个人信息；如包含，系统会先征求你的确认并脱敏。</p>
    </div>
  );
}
