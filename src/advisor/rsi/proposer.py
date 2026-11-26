"""② 提出小改动：一次只针对一个问题、只改一个组件。优化器只能提交候选，不能改评测器和门控，也不能自己发布。"""
import hashlib
import uuid
from datetime import date, datetime, timezone

from pydantic import BaseModel, Field

from advisor.harness import Budget
from advisor.rsi.gates import max_step
from advisor.rsi.ledger import Ledger
from advisor.rsi.models import SCENARIO_KIND, Issue, LessonCard, Run


class ProposeError(Exception):
    pass


LESSON_SYSTEM = """你是投研方法论编辑。根据一次被推翻的研究主张，写一张"经验卡"，让研究员下次遇到同类情形先排除替代解释。
硬性要求：
- 只写"怎么研究、怎么核验"，不写任何投资结论或买卖倾向；
- 不出现具体公司名、股票代码、任何数字或百分比——要能迁移到同类公司；
- applies_to 写清适用的公司类型与指标现象；tags 是 3-6 个召回关键词，不含公司名：
  一半写这类误判里常见的推理用语（如「说明」「反映」「意味着」「主要由于」），一半写涉及的指标或科目名——
  卡片按 tags 在主张文本里字面匹配召回，只写指标名会漏掉大部分同类误判；
- must_check 写 1-3 个下结论前必须查的材料类型；invalid_if 写何时这张卡不适用；
- 如果已有卡片与本案例是同一类教训，给出 revise_id 并在原卡基础上改进（保留有效内容），不要重复新建。"""


class LessonDraft(BaseModel):
    revise_id: str | None = None
    title: str = Field(max_length=40)
    applies_to: str = Field(max_length=120)
    tags: list[str] = Field(min_length=1, max_length=6)
    lesson: str = Field(max_length=200)
    must_check: list[str] = Field(default_factory=list, max_length=3)
    invalid_if: str = Field(default="", max_length=120)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pick(ledger: Ledger, scenario: str, issue_id: str | None) -> list[Issue]:
    open_ = ledger.list_issues(scenario=scenario, status="open")
    if issue_id:
        open_ = [i for i in open_ if i.id == issue_id]
        if not open_:
            raise ProposeError(f"坏案例 {issue_id} 不存在或已处理")
    if not open_:
        raise ProposeError(f"{scenario} 没有待处理的坏案例，先运行 collect")
    return open_


def _new_run(scenario: str, issues: list[Issue], base_version: int, content: dict, diff: dict, reason: str,
             direction: str, actor: str) -> Run:
    return Run(run_id="rsi_" + uuid.uuid4().hex[:8], scenario=scenario, kind=SCENARIO_KIND[scenario],
               issue_ids=[i.id for i in issues], base_version=base_version, content=content, diff=diff,
               change_reason=reason, direction=direction, triggered_by=actor, created_at=_now(), updated_at=_now())


MAX_EXAMPLES = 4


def failure_class(issue: Issue) -> str:
    """同一类误判（类型 + 假设相同）算一个问题：一张卡对应一类错误，而不是一个案例。"""
    return "S1:class:" + hashlib.sha256(f"{issue.kind}|{issue.hypothesis}".encode()).hexdigest()[:12]


def propose_s1(deps, ledger: Ledger, issue_id: str | None, actor: str) -> Run:
    base = ledger.active_asset("lessons")
    cards = [LessonCard.model_validate(c) for c in base.content.get("cards", [])]
    tried = ledger.tried_directions("S1")
    pending = {i for r in ledger.list_runs("S1") if r.status in ("draft", "review", "approved") for i in r.issue_ids}
    open_ = [i for i in ledger.list_issues(scenario="S1", status="open")
             if failure_class(i) not in tried and i.id not in pending]
    candidates = [i for i in _pick(ledger, "S1", issue_id) if i in open_]
    if not candidates:
        raise ProposeError("S1 的待处理坏案例都已有在途候选或这一类已试过且被拒绝；换一个组件改")
    # 先挑同类案例最多的一类：进化集越大，噪声门控的判断越可信；但必须留出没见过的股票做留出集
    by_class: dict[str, list[Issue]] = {}
    for i in open_:
        by_class.setdefault(failure_class(i), []).append(i)
    all_tickers = {i.source.get("ticker") for i in ledger.list_issues(scenario="S1")}
    by_class = {k: v for k, v in by_class.items() if all_tickers - {i.source.get("ticker") for i in v}}
    candidates = [i for i in candidates if failure_class(i) in by_class]
    if not candidates:
        raise ProposeError("同类坏案例覆盖了全部股票，没有留出集可以验证迁移效果；先积累更多股票的研究")
    issue = max(candidates, key=lambda i: (len(by_class[failure_class(i)]), i.kind == "challenge_upheld"))
    group = sorted(by_class[failure_class(issue)], key=lambda i: i.id != issue.id)
    existing = "\n".join(f"- {c.id} r{c.rev}｜{c.title}｜适用：{c.applies_to}｜标签：{'、'.join(c.tags)}｜教训：{c.lesson}"
                         for c in cards) or "（暂无）"
    examples = "\n\n".join(
        f"案例 {k + 1}：被推翻的主张：{i.source.get('claim') or i.case}\n提出者：{i.source.get('expert', '研究员')}\n"
        + "\n".join(i.evidence) for k, i in enumerate(group[:MAX_EXAMPLES]))
    user = (f"以下 {len(group)} 个坏案例属于同一类误判（列出前 {min(len(group), MAX_EXAMPLES)} 个）：\n\n{examples}"
            f"\n\n系统假设的原因：{issue.hypothesis}\n\n已有经验卡：\n{existing}")
    h = deps.harness("rsi-propose", "quick", date.today(), Budget(limits={"tokens": 200_000, "wall_clock_s": 600}),
                     node="rsi_propose", principal="optimizer")
    draft: LessonDraft = h.llm("reason", LESSON_SYSTEM, user, LessonDraft, purpose="rsi_s1_lesson")
    target = next((c for c in cards if c.id == draft.revise_id), None)
    card = LessonCard(
        id=target.id if target else f"L-{len(cards) + 1:03d}", rev=(target.rev + 1) if target else 1,
        title=draft.title, applies_to=draft.applies_to, tags=draft.tags, lesson=draft.lesson,
        must_check=draft.must_check, invalid_if=draft.invalid_if,
        source=f"{issue.source.get('dossier')} v{issue.source.get('version')} · {issue.source.get('challenge_id') or issue.source.get('claim_id')}",
    )
    new_cards = [card if c.id == card.id else c for c in cards] + ([] if target else [card])
    action = "修订" if target else "新增"
    reason = (f"{action}经验卡 {card.id}：{'深研中被裁定成立的质询' if issue.kind == 'challenge_upheld' else '核验存疑的主张'}"
              f"暴露同类误判（{len(group)} 个案例，{issue.id} 等）")
    return _new_run("S1", group, base.version, {"cards": [c.model_dump() for c in new_cards]},
                    {"action": "revise" if target else "add", "cards": [card.model_dump()]}, reason,
                    failure_class(issue), actor)


def _grid(center: float, step: float, lo: float, hi: float) -> list[float]:
    pts = {round(min(max(center + k * step / 2, lo), hi), 3) for k in (-2, -1, 0, 1, 2)}
    return sorted(pts)


def propose_s2(deps, ledger: Ledger, issue_id: str | None, actor: str) -> Run:
    from advisor.routing import route_from_probs
    issues = _pick(ledger, "S2", issue_id)
    base = ledger.active_asset("routing")
    released = ledger.released_count("routing")
    evo_q = {i.source["question"] for i in issues}
    rows = [r for rr in deps.repo.db.eval_runs.find({"type": "routing"}) for r in rr.get("rows", [])
            if r["question"] in evo_q and r["source"] in ("model", "abstain")]
    if not rows:
        raise ProposeError("坏案例没有可回放的判别器概率记录")
    tried = ledger.tried_directions("S2")
    t0, a0 = float(base.content["temperature"]), float(base.content["abstain_below"])

    def acc(t: float, a: float) -> float:
        cfg = {**deps.policy.routing, "temperature": t, "abstain_below": a}
        return sum(route_from_probs(r["probs"], cfg, r.get("stakes"), r.get("uncertainty"), r.get("intent", "research")).route
                   == r["label"] for r in rows) / len(rows)

    best = None
    for t in _grid(t0, max_step("temperature", released), 0.3, 3.0):
        for a in _grid(a0, max_step("abstain_below", released), 0.34, 0.9):
            if (t, a) == (t0, a0) or f"S2:T={t}:A={a}" in tried:
                continue
            score = acc(t, a) - 0.01 * (abs(t - t0) + abs(a - a0))     # 同分时偏好更小的改动
            if best is None or score > best[0]:
                best = (score, t, a)
    if best is None or best[0] <= acc(t0, a0):
        raise ProposeError("在步长范围内没有找到能改善进化集的参数；长期没有进展时，换一个组件改")
    _, t, a = best
    params = {k: (old, new) for k, old, new in (("temperature", t0, t), ("abstain_below", a0, a)) if old != new}
    reason = f"路由自校准：针对 {len(issues)} 个错判案例，" + "，".join(f"{k} {o}→{n}" for k, (o, n) in params.items())
    return _new_run("S2", issues, base.version, {**base.content, "temperature": t, "abstain_below": a},
                    {"params": {k: list(v) for k, v in params.items()}}, reason, f"S2:T={t}:A={a}", actor)


HINT_SYSTEM = """你是检索策略编辑。一位研究专家的「搜索侧重」决定了它会生成什么搜索词。
现在它生成的搜索词带回来的结果里，权威且能抓取原文的很少。请改写这段搜索侧重，让搜索词更容易命中
交易所与公司公告、监管机构、官方媒体和主流财经媒体的原文。
硬性要求：
- 只写这类专家该关注的内容与偏好的材料类型，要能用于任何公司；
- 不写具体公司名、股票代码、数字、日期、某个行业的专用词或任何投资结论；
- 不超过 60 个字，用顿号分隔要点；保留原侧重里仍然有效的方向；不要和已被拒绝的写法雷同。"""


class HintDraft(BaseModel):
    hint: str = Field(min_length=4, max_length=80)
    rationale: str = Field(default="", max_length=200)


def _s3_open(ledger: Ledger, issue_id: str | None) -> list[Issue]:
    pending = {i for r in ledger.list_runs("S3") if r.status in ("draft", "review", "approved") for i in r.issue_ids}
    issues = [i for i in _pick(ledger, "S3", issue_id) if i.id not in pending]
    if not issues:
        raise ProposeError("S3 的待处理坏案例都已有在途候选")
    return issues


def _propose_rerank(deps, ledger: Ledger, issues: list[Issue], actor: str) -> Run:
    from advisor.rsi.evaluator import _cached_searches, search_f
    base = ledger.active_asset("search")
    released = ledger.released_count("search")
    tried = ledger.tried_directions("S3")
    evo = [s for s in _cached_searches(deps.repo) if s["raw"] and int(s["id"], 16) % 3 != 0]   # 只看进化集，不碰留出集
    if not evo:
        raise ProposeError("没有可回放的搜索记录")
    f = lambda x: search_f(evo, {**deps.policy.search, **base.content, "rerank_min": x}, deps.policy)["f"]   # noqa: E731
    r0 = float(base.content["rerank_min"])
    options = [x for x in _grid(r0, max_step("rerank_min", released), 0.5, 3.0) if x != r0 and f"S3:rerank={x}" not in tried]
    scored = sorted(((f(x), x) for x in options), reverse=True)
    if not scored or scored[0][0] <= f(r0):
        raise ProposeError("在步长范围内调整相关度阈值不能改善进化集；换一个组件改")
    x = scored[0][1]
    reason = f"检索策略进化：{len(issues)} 份档案网页线索质量低，相关度阈值 {r0}→{x}"
    return _new_run("S3", issues, base.version, {**base.content, "rerank_min": x},
                    {"params": {"rerank_min": [r0, x]}}, reason, f"S3:rerank={x}", actor)


def _propose_hint(deps, ledger: Ledger, issues: list[Issue], actor: str) -> Run:
    from advisor.experts.specs import EXPERTS
    from advisor.rsi.issues import cached_results, usable
    from advisor.skills.data.web import fetch_allowlist
    base = ledger.active_asset("search")
    tried = ledger.tried_directions("S3")
    by_expert: dict[str, list[Issue]] = {}
    for i in issues:
        by_expert.setdefault(i.source["expert"], []).append(i)
    expert, group = max(by_expert.items(), key=lambda kv: (len(kv[1]), kv[0]))
    spec = EXPERTS[expert]
    hints = dict(base.content.get("expert_hints", {}))
    current = hints.get(expert, spec.query_hint)
    # 对照：其他专家带回可用结果多的搜索词（只作写法参考）
    b_min, allow = int(base.content.get("authority_b_min", 3)), fetch_allowlist(deps.policy, base.content)
    rates = sorted(((sum(usable(r, b_min, allow, deps.policy.block_sites) for r in rs) / len(rs), q)
                    for q, rs in cached_results(deps.repo).items() if len(rs) >= 5), reverse=True)
    good = "\n".join(f"- 「{q}」可用 {x:.0%}" for x, q in rates[:5] if x >= 0.5) or "（暂无）"
    weak = "\n".join(f"- {e}" for i in group[:4] for e in i.evidence[:3])
    rejected = [r.diff["hint"]["new"] for r in ledger.list_runs("S3")
                if r.status in ("rejected", "rolled_back") and r.diff.get("hint", {}).get("expert") == expert]
    user = (f"专家：{spec.name}（职责：{spec.mandate}）\n当前搜索侧重：{current}\n\n"
            f"它在 {len(group)} 份档案里的搜索词与结果（可用 = 权威且能抓取原文）：\n{weak}\n\n"
            f"可用率高的搜索词（写法参考）：\n{good}\n\n已被拒绝的写法：{'；'.join(rejected) or '（无）'}")
    h = deps.harness("rsi-propose", "quick", date.today(), Budget(limits={"tokens": 100_000, "wall_clock_s": 300}),
                     node="rsi_propose", principal="optimizer")
    draft: HintDraft = h.llm("reason", HINT_SYSTEM, user, HintDraft, purpose="rsi_s3_hint")
    new = draft.hint.strip()
    direction = f"S3:hint:{expert}:{hashlib.sha256(new.encode()).hexdigest()[:8]}"
    if new == current or direction in tried:
        raise ProposeError(f"优化器给出的{spec.name}搜索侧重与在用版本或已被拒绝的写法相同")
    hints[expert] = new
    reason = f"检索策略进化：{spec.name}的搜索词在 {len(group)} 份档案里带回的可用结果过少，改写搜索侧重"
    return _new_run("S3", group, base.version, {**base.content, "expert_hints": hints},
                    {"hint": {"expert": expert, "name": spec.name, "old": current, "new": new, "rationale": draft.rationale}},
                    reason, direction, actor)


def _propose_site(deps, ledger: Ledger, issues: list[Issue], actor: str) -> Run:
    """改抓取站点名单：高风险。一次只加一个站点，只加不删；批准时必须写明理由。"""
    base = ledger.active_asset("search")
    tried = ledger.tried_directions("S3")
    added = list(base.content.get("fetch_allow_add", []))
    cands = [i for i in issues if i.source["host"] not in added and f"S3:site:+{i.source['host']}" not in tried]
    if not cands:
        raise ProposeError("白名单外的权威站点都已加入或试过且被拒绝")
    issue = max(cands, key=lambda i: (i.source["results"], i.source["host"]))
    host = issue.source["host"]
    reason = (f"抓取站点名单：追加 {host}（搜索结果中出现 {issue.source['results']} 次、"
              f"{issue.source['authority_share']:.0%} 被评为权威）。高风险改动，须人工写明理由批准")
    run = _new_run("S3", [issue], base.version, {**base.content, "fetch_allow_add": added + [host]},
                   {"sites": {"add": [host]}}, reason, f"S3:site:+{host}", actor)
    run.risk = "high"
    return run


S3_KINDS = {"expert_query_weak": _propose_hint, "low_quality_search": _propose_rerank, "site_gap": _propose_site}


def propose_s3(deps, ledger: Ledger, issue_id: str | None, actor: str) -> Run:
    """S3 三种改法：专家搜索侧重、相关度阈值、抓取站点名单（高风险，排最后）。指定坏案例时按它的类型改。"""
    issues = _s3_open(ledger, issue_id)
    errors = []
    for kind, fn in S3_KINDS.items():
        group = [i for i in issues if i.kind == kind]
        if not group:
            continue
        try:
            return fn(deps, ledger, group, actor)
        except ProposeError as e:
            errors.append(str(e))
    raise ProposeError("；".join(errors) or "S3 没有可处理的坏案例")


PROPOSERS = {"S1": propose_s1, "S2": propose_s2, "S3": propose_s3}
