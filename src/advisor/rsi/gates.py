"""④ 六道门控：纯代码，全部亮绿灯才能提交审批。优化器不能修改这里。"""
import re
from functools import lru_cache

from advisor.rsi.ledger import Ledger
from advisor.rsi.models import GateResult, LessonCard, Run
from advisor.settings import load_yaml

COST_FREE_RATIO = 0.10          # token 增幅在 10% 以内视为成本不变
_DIGITS = re.compile(r"\d")
_CONCLUSION = re.compile(r"买入|卖出|增持|减持|目标价|看多|看空|推荐|抄底|满仓|清仓|必涨|必跌")
# 自媒体 / 用户生成内容平台：即使搜索引擎给了高权威分，也不能进抓取白名单
_UGC_SITE = re.compile(r"weixin|toutiao|sohu|163\.com|baijiahao|zhihu|weibo|douyin|bilibili|xueqiu|guba|tieba|futunn|longbridge")
MAX_SITES_PER_RUN = 1
STEP = {"temperature": 0.5, "abstain_below": 0.10, "rerank_min": 0.5, "authority_b_min": 1}


def max_step(param: str, released: int) -> float:
    """前几轮允许改动大一些，后面越改越小。"""
    return STEP[param] / (1 + released)


def _arm(ev: dict, arm: str, slice_: str) -> dict:
    return (ev["arms"].get(arm) or {}).get("slices", {}).get(slice_) or {}


def protocol_gate(run: Run, ev: dict, ledger: Ledger) -> GateResult:
    frozen = ledger.db.rsi_protocols.find_one({"scenario": run.scenario}) or {}
    p = ev.get("protocol", {})
    ok = bool(frozen) and p.get("replay_hash") == frozen.get("hash") and "base" in ev["arms"] and "cand" in ev["arms"]
    return GateResult(name="protocol", label="协议一致", passed=ok,
                      detail=(f"回放集哈希 {str(p.get('replay_hash'))[:10]} 与冻结协议一致，评分器 {p.get('scorer')}，基线与候选同一次评测"
                              if ok else "回放集或评分规则与冻结协议不一致：换了尺子，结论无效"))


def leakage_gate(run: Run, ev: dict, ledger: Ledger) -> GateResult:
    evo, hold = set(ev["leakage"]["evolution"]), set(ev["leakage"]["holdout"])
    overlap = evo & hold
    ok = not overlap and bool(hold)
    detail = (f"进化集 {len(evo)} 项与留出集 {len(hold)} 项无交集" if ok else
              f"重叠 {sorted(overlap)[:3]}" if overlap else "留出集为空，无法检验迁移")
    return GateResult(name="leakage", label="防泄漏", passed=ok, detail=detail)


@lru_cache(maxsize=1)
def industry_terms() -> dict[str, dict]:
    return load_yaml("industry_terms.yaml")


def industry_hits(text: str, scope: str | None) -> list[str]:
    """文本里出现某行业专用词、而适用范围没写明该行业 → 返回「行业：词」。scope=None 表示必须对所有公司适用。"""
    out = []
    for industry, spec in industry_terms().items():
        hit = [t for t in spec.get("terms", []) if t in text]
        if hit and (scope is None or not any(a in scope for a in spec.get("aliases", []) + [industry])):
            out.append(f"{industry}：{'、'.join(hit[:3])}")
    return out


def _text_problems(who: str, text: str, names: set[str], scope: str | None) -> list[str]:
    bad = []
    if _DIGITS.search(text):
        bad.append(f"{who} 含具体数字")
    if hit := [n for n in names if n and n in text]:
        bad.append(f"{who} 含具体公司名 {hit[0]}")
    if m := _CONCLUSION.search(text):
        bad.append(f"{who} 含投资结论词「{m.group()}」")
    if hits := industry_hits(text, scope):
        bad.append(f"{who} 含行业专用词（{'；'.join(hits)}）" + ("，但适用范围没写明这个行业" if scope is not None else "，搜索侧重要对所有公司适用"))
    return bad


def _site_problems(run: Run, ledger: Ledger) -> list[str]:
    from advisor.harness import Policy
    added = run.diff["sites"].get("add", [])
    bad = [] if len(added) <= MAX_SITES_PER_RUN else [f"一次加了 {len(added)} 个站点，上限 {MAX_SITES_PER_RUN} 个"]
    if run.diff["sites"].get("remove"):
        bad.append("不允许通过自进化删减白名单")
    block = Policy.load().block_sites
    for host in added:
        if any(host == b or host.endswith("." + b) for b in block):
            bad.append(f"{host} 在黑名单里")
        elif _UGC_SITE.search(host):
            bad.append(f"{host} 是自媒体或用户生成内容平台")
    return bad


def overfit_gate(run: Run, ev: dict, ledger: Ledger) -> GateResult:
    names = {d.get("name") for d in ledger.db.dossiers.find({}, projection={"name": 1}) if d.get("name")}
    if run.kind == "lessons":
        bad = []
        for c in run.diff.get("cards", []):
            card = LessonCard.model_validate(c)
            text = " ".join([card.title, card.applies_to, card.lesson, card.invalid_if, *card.must_check, *card.tags])
            bad += _text_problems(card.id, text, names, card.applies_to)
        return GateResult(name="overfit", label="防过拟合", passed=not bad,
                          detail="；".join(bad) if bad else "卡片不含具体股票、数字、未声明的行业专用词或投资结论，只描述方法")
    if "hint" in run.diff:
        bad = _text_problems("搜索侧重", run.diff["hint"]["new"], names, None)
        return GateResult(name="overfit", label="防过拟合", passed=not bad,
                          detail="；".join(bad) if bad else "搜索侧重不含具体公司、数字、行业专用词或投资结论")
    if "sites" in run.diff:
        bad = _site_problems(run, ledger)
        return GateResult(name="overfit", label="防过拟合", passed=not bad,
                          detail="；".join(bad) if bad else "只追加 1 个站点，不在黑名单、不是自媒体平台（高风险，须人工写明理由批准）")
    released = ledger.released_count(run.kind)
    over = []
    for k, (old, new) in run.diff.get("params", {}).items():
        if k in STEP and abs(float(new) - float(old)) > max_step(k, released) + 1e-9:
            over.append(f"{k} 改动 {old}→{new} 超过本轮步长上限 {max_step(k, released):.3f}")
    return GateResult(name="overfit", label="防过拟合", passed=not over,
                      detail="；".join(over) if over else f"改动幅度在第 {released + 1} 轮步长上限内（越改越小）")


def noise_gate(run: Run, ev: dict, ledger: Ledger) -> GateResult:
    prim = ev["primary"]
    b, c = _arm(ev, "base", prim), _arm(ev, "cand", prim)
    if ev.get("repeats", 0) < 3 or not b or not c:
        return GateResult(name="noise", label="噪声门控", passed=False,
                          detail=f"只有 {ev.get('repeats', 0)} 次重复，至少需要 3 次才能区分进步与波动")
    delta = c["mean"] - b["mean"]
    band = max(b["spread"], c["spread"])
    ok = delta > band
    det = "（确定性回放，波动为 0）" if ev.get("deterministic") else ""
    return GateResult(name="noise", label="噪声门控", passed=ok,
                      detail=f"{prim} 提升 {delta:+.3f}，波动范围 {band:.3f}{det}；" + ("超出波动，算进步" if ok else "未超出波动，可能是偶然"))


def cost_gate(run: Run, ev: dict, ledger: Ledger) -> GateResult:
    bt, ct = ev["arms"]["base"].get("tokens", 0), ev["arms"]["cand"].get("tokens", 0)
    prim = ev["primary"]
    b, c = _arm(ev, "base", prim), _arm(ev, "cand", prim)
    gain = (c.get("mean", 0) - b.get("mean", 0)) / max(b.get("mean") or 1e-9, 1e-9)
    inc = (ct - bt) / bt if bt else 0.0
    ok = inc <= COST_FREE_RATIO or gain >= inc
    return GateResult(name="cost", label="成本门控", passed=ok,
                      detail=f"token {bt}→{ct}（{inc:+.0%}），质量相对提升 {gain:+.0%}" + ("" if ok else "：花费涨幅超过质量收益"))


def regression_gate(run: Run, ev: dict, ledger: Ledger) -> GateResult:
    msgs, ok = [], True
    for sl, label in (("replay", "固定回放集"), ("holdout", "留出集")):
        b, c = _arm(ev, "base", sl), _arm(ev, "cand", sl)
        if not b or not c:
            continue
        tol = max(b["spread"], c["spread"])
        worse = c["mean"] < b["mean"] - tol
        ok &= not worse
        msgs.append(f"{label} {b['mean']:.3f}→{c['mean']:.3f}" + ("（退化）" if worse else ""))
    return GateResult(name="regression", label="回归门控", passed=ok and bool(msgs), detail="；".join(msgs) or "缺少回放集结果")


GATES = [protocol_gate, leakage_gate, overfit_gate, noise_gate, cost_gate, regression_gate]
GATE_LABELS = {"protocol": "协议一致", "leakage": "防泄漏", "overfit": "防过拟合", "noise": "噪声门控", "cost": "成本门控", "regression": "回归门控"}


def run_gates(run: Run, ev: dict, ledger: Ledger) -> list[GateResult]:
    out = []
    for g in GATES:
        try:
            out.append(g(run, ev, ledger))
        except Exception as e:      # 门控自身出错按不通过处理
            name = g.__name__.removesuffix("_gate")
            out.append(GateResult(name=name, label=GATE_LABELS[name], passed=False, detail=f"门控执行出错：{e}"))
    return out
