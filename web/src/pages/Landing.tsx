import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { chgClass, signed } from "../components/Shell";
import { IconArrowRight, Sparkle } from "../components/Icons";
import type { WatchRow } from "../types";

/** 进入视口时上浮显现。 */
function useReveal() {
  useEffect(() => {
    const els = document.querySelectorAll(".rise");
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); }
    }), { threshold: 0.15 });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
}

/** 鼠标位置 → 轻微 3D 倾斜与光斑。 */
function tilt(max = 4) {
  return {
    onMouseMove: (e: React.MouseEvent<HTMLElement>) => {
      const r = e.currentTarget.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      e.currentTarget.style.setProperty("--ry", `${(x - 0.5) * max}deg`);
      e.currentTarget.style.setProperty("--rx", `${(0.5 - y) * max}deg`);
      e.currentTarget.style.setProperty("--mx", `${x * 100}%`);
      e.currentTarget.style.setProperty("--my", `${y * 100}%`);
    },
    onMouseLeave: (e: React.MouseEvent<HTMLElement>) => {
      e.currentTarget.style.setProperty("--ry", "0deg");
      e.currentTarget.style.setProperty("--rx", "0deg");
    },
  };
}

const ENTRIES = [
  { to: "/new", t: "问顾问", d: "用一句话提问。系统自动分诊为快查、标准研究或争议深研，并在需要你确认时停下来。", go: "开始提问" },
  { to: "/dossiers", t: "决策档案", d: "每个结论都挂着证据与时点；每次研究生成新版本，旧版本永远保留，差异一目了然。", go: "查看档案" },
  { to: "/rsi", t: "RSI · 递归自我改进", d: "被推翻的结论沉淀成经验卡，过六道门控、经你批准才上线；变差就一键回滚。", go: "进入 RSI" },
];

export default function Landing() {
  useReveal();
  const [scrolled, setScrolled] = useState(false);
  const [progress, setProgress] = useState(0);
  const [watch, setWatch] = useState<WatchRow[]>([]);
  const featRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = "证研 · 可信投研 Agent";
    const onScroll = () => {
      const h = document.documentElement;
      setScrolled(h.scrollTop > 8);
      setProgress(h.scrollTop / Math.max(h.scrollHeight - h.clientHeight, 1));
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    api.watchlist().then(setWatch).catch(() => undefined);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="lp">
      <div className="lp-progress" style={{ transform: `scaleX(${progress})`, width: "100%" }} />
      <header className={`lp-header ${scrolled ? "is-scrolled" : ""}`}>
        <div className="lp-header-in">
          <Link to="/" className="sb-logo"><Sparkle className="sb-mark" />证研</Link>
          <span className="lp-slogan">可信投研 Agent</span>
          <div className="right">
            <Link to="/workspace" className="button ghost">研究台</Link>
            <Link to="/new" className="button primary">开始研究</Link>
          </div>
        </div>
      </header>

      <section className="lp-hero">
        <div className="orb orb-purple" /><div className="orb orb-gold" /><div className="orb orb-pink" />
        <h1 className="lp-h1 rise">不预测涨跌，<br />让每个研究策略<span className="grad">有迹可循</span></h1>
        <p className="lp-sub rise">
          面向个人投资者的股票研究 AI：证据分级、多专家对质、版本化决策档案。
          每个结论都对得上口径、留得住分歧、能随新信息更新——而且同样的错，不犯第二次。
        </p>
        <div className="lp-cta rise">
          <Link to="/new" className="button primary lp-btn">立即开始研究</Link>
          <button className="lp-btn ghost" onClick={() => featRef.current?.scrollIntoView({ behavior: "smooth" })}>了解三个入口</button>
        </div>

        <div className="lp-stage rise" {...tilt(3)}>
          <div className="hero-window">
            <div className="hero-sheen" />
            <div className="hw-bar"><i /><i /><i /></div>
            <div className="hw-body">
              <div className="hw-side">
                <div className="hs on">研究台</div><div className="hs">决策档案</div><div className="hs">RSI</div>
                <div className="muted" style={{ padding: "10px 8px 2px" }}>我的档案</div>
                {(watch.length ? watch.slice(0, 4) : [{ key: "x", name: "示例标的", quote: {} } as WatchRow]).map((w) => (
                  <div className="wl" key={w.key}><span>{w.name}</span>
                    <span className={chgClass(w.quote.chg_20d?.value)}>{signed(w.quote.chg_20d?.value)}</span></div>
                ))}
              </div>
              <div className="hw-main">
                <div className="hm-t">贵州茅台 · 决策档案 v5 <span className="badge st-partial">部分结论</span></div>
                <div className="hw-claim"><span className="badge lv-A">A</span><span className="t">上半年营业收入累计同比微增，单季增速放缓（同口径复算通过）</span></div>
                <div className="hw-claim"><span className="badge lv-A">A</span><span className="t">PE(TTM) 处于近两年窗口中位附近；三档估值情景已显式写出假设</span></div>
                <div className="hw-claim struck"><span className="badge vd-upheld">质询成立</span><span className="t">合同负债同比下降，说明终端需求走弱</span></div>
                <div className="hw-claim"><span className="badge lv-B">B</span><span className="t">渠道改革相关报道（已抓取快照，转载不重复计数）</span></div>
                <div className="muted small">反证官：同一变化也可能来自渠道打款模式调整 → 主席按证据裁决，不投票</div>
              </div>
              <div className="hw-ask">
                <div className="bubble">合同负债大幅下降一定说明需求走弱吗？</div>
                <div className="muted">路由 → 标准研究 · 取证 · 核验 · 质量门控</div>
                <div className="hcard"><b>召回经验卡</b><br />预收类科目变动，先排除打款政策与渠道调整，再推断需求。<div className="muted">方法提示 · 非证据</div></div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="lp-sec" ref={featRef}>
        <div className="lp-sec-h rise">
          <h2 className="lp-h2">从一个问题，到一份档案，<br />再到下一次更好的研究</h2>
          <div className="lp-h2-sub">三个入口，共享同一套证据与记忆。</div>
        </div>
        <div className="entry-panel rise">
          {ENTRIES.map((e, i) => (
            <Link key={e.to} to={e.to} className="entry-card" {...tilt(0)}>
              <span className="entry-num">0{i + 1}</span>
              <span className="et">{e.t}</span>
              <span>{e.d}</span>
              <span className="ego">{e.go}<IconArrowRight /></span>
            </Link>
          ))}
        </div>
      </section>

      <section className="feat">
        <div className="rise">
          <div className="feat-k">证据分级</div>
          <h3>网页只是线索，<br />数字必须回到 <span className="grad">A 级源</span></h3>
          <p>公告、财报、行情和系统计算是事实；AI 搜索结果只能说明"发生了什么"或触发补证。转载与洗稿按原始来源聚类，不重复计数。</p>
          <ul>
            <li><span className="list-badge">01</span>研究时点切片，未来信息一律拦截</li>
            <li><span className="list-badge">02</span>每个数字都能在引用证据中复算</li>
            <li><span className="list-badge">03</span>网页内容清洗后入证据卡，提示注入降级为线索</li>
          </ul>
          <Link to="/dossiers" className="button primary lp-btn">看看真实档案</Link>
        </div>
        <div className="ui-card rise" {...tilt(5)}>
          <div className="backing backing-purple" /><div className="card-glow" />
          <div className="lvl-row"><span className="badge lv-A">A</span><div><b>结论与计算输入</b><div className="small">巨潮公告、结构化财报、行情、Decimal 确定性计算</div></div></div>
          <div className="lvl-row"><span className="badge lv-B">B</span><div><b>说明发生了什么</b><div className="small">权威网页（authority ≥ 3）且已抓取全文快照</div></div></div>
          <div className="lvl-row"><span className="badge lv-C">C</span><div><b>只能触发"去查证"</b><div className="small">其他网页结果；进入最终结论 0 次</div></div></div>
        </div>
      </section>

      <section className="feat rev">
        <div className="rise">
          <div className="feat-k">多专家对质</div>
          <h3>不投票，<br />按<span className="grad">证据</span>裁决分歧</h3>
          <p>争议问题按证据缺口临时召集专家，首轮隔离取证；反证官主动找替代解释，主席按来源独立性、时点和可复算性裁决，并把未决分歧写进档案。</p>
          <ul>
            <li><span className="list-badge">01</span>三档分诊：快查 / 标准研究 / 争议深研</li>
            <li><span className="list-badge">02</span>质询成立的主张不得进入结论</li>
            <li><span className="list-badge">03</span>高后果未决争议，必须由你确认后才提交</li>
          </ul>
        </div>
        <div className="ui-card rise" {...tilt(5)}>
          <div className="backing backing-gold" /><div className="card-glow" />
          <div className="debate card flat" style={{ margin: 0 }}>
            <div className="debate-target"><span className="tag">基本面研究员</span> 合同负债同比大幅下降，说明后续收入承压</div>
            <div className="debate-row red"><span className="who">反证官</span><span>替代解释：渠道打款 / 代售模式调整同样能解释该变化</span></div>
            <div className="debate-row"><span className="who">研究员回应</span><span>承认：现有证据无法排除该解释</span></div>
            <div className="debate-row chair"><span className="who">主席裁决</span><span><span className="badge vd-upheld">质询成立</span> 该主张不进入结论，教训进入 RSI 经验库</span></div>
          </div>
        </div>
      </section>

      <section className="feat">
        <div className="rise">
          <div className="feat-k">RSI · 递归自我改进</div>
          <h3>从自己的错里学习，<br />但<span className="grad">每一步都有日志</span></h3>
          <p>只改模型外面那一层：经验卡、路由参数、检索模板。候选与在用版本跑同一批案例、用同一把尺子打分，六道门控全绿、经你批准才发布。</p>
          <ul>
            <li><span className="list-badge">01</span>协议一致 · 防泄漏 · 防过拟合</li>
            <li><span className="list-badge">02</span>噪声门控 · 成本门控 · 回归门控</li>
            <li><span className="list-badge">03</span>每份档案记录所用版本，证明改进被继承</li>
          </ul>
          <Link to="/rsi" className="button primary lp-btn">打开 RSI</Link>
        </div>
        <div className="ui-card rise" {...tilt(5)}>
          <div className="backing backing-purple" /><div className="card-glow" />
          <div className="mini-loop">
            {["收集", "提议", "对比", "门控", "发布"].map((x, i) => <div key={x} className={i === 3 ? "redlamp" : ""}><span>{i + 1}</span>{x}</div>)}
          </div>
          <div className="lesson">
            <div className="lt">经验卡 L-001 <span className="tag purple">r1</span></div>
            <dl>
              <dt>适用</dt><dd>预收款/渠道打款模式的消费品公司，合同负债大幅变动时</dd>
              <dt>教训</dt><dd>先排除打款政策、渠道结构调整，再推断需求变化</dd>
              <dt>失效</dt><dd>公司已明确说明打款政策未变</dd>
            </dl>
          </div>
          <p className="small muted" style={{ margin: "12px 0 0" }}>门控亮红灯的候选会被拒绝，拒绝原因同样记入日志，失败的方向不再重复。</p>
        </div>
      </section>

      <section className="cta-panel rise">
        <div className="cta-glow" />
        <span className="cta-badge">本地运行 · 不接实盘 · 不给买卖指令</span>
        <h2>准备好让每个研究结论都经得起追问了吗？</h2>
        <p>提一个问题，系统会把它变成一份可追溯、可复核、能持续更新的决策档案。</p>
        <Link to="/new" className="button primary lp-btn">进入研究台</Link>
      </section>

      <footer className="lp-footer">
        <div><div className="sb-logo"><Sparkle className="sb-mark" />证研</div><div style={{ marginTop: 8 }}>股票投资顾问 Agent · 架构设计方案 V6</div></div>
        <div className="right">内容由 AI 生成并经规则核验，仅为研究与信息整理<br />不构成投资建议，不承诺收益，不执行任何交易</div>
      </footer>
    </div>
  );
}
