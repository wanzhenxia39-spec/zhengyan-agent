"""③ 同台对比：新版本和在用版本跑同一批案例、用同一把尺子打分。评测器是代码，优化器改不到这里。

三个测试切片：
- replay   固定回放集：首次评测时冻结，每轮都考同一套题；
- evolution 新失败集：本次候选针对的坏案例所在的样本；
- holdout  时间外留出集：没见过的标的 / 未参与进化的问题，检验能否迁移。
"""
import hashlib
import json
from datetime import date, datetime, timezone
from statistics import mean
from typing import Any, Callable

from pydantic import BaseModel, Field

from advisor.harness import Budget
from advisor.rsi.ledger import Ledger
from advisor.rsi.loader import recall, render_lessons
from advisor.rsi.models import LessonCard, Run

REPEATS = 3
GOOD_PER_BAD = 2

S1_SCORER = "s1-claim-review-v3"     # v2：方法提示每批只渲染一次；v3：新失败集只计本候选针对的同类坏主张（不混入其他类型）
S1_JUDGE_SYSTEM = """你是投研审稿人。逐条判断研究主张能否按原样进入结论：
- needs_check=true：该主张从指标变化直接推出原因或趋势，而没有排除其他解释、缺少机制论证、或证据口径不足以支撑；
- needs_check=false：该主张是可核验的事实陈述，或推断有充分依据。
只做判断，不改写主张。若某条主张附有方法提示，可参考，但提示不适用时忽略。"""
S2_SCORER = "s2-route-replay-v1"
S3_SCORER = "s3-search-replay-v2"     # v2：可用 = 权威且可抓取（白名单含已批准追加的站点）；召回分母不受白名单限制
S3_HINT_SCORER = "s3-expert-hint-live-v1"
HINT_ITEMS = 3                         # 进化集 / 留出集各取几份档案的专家问题
HINT_QUERIES = 2                       # 每份档案用前几条搜索词（与线上 search_per_expert 一致）


class JudgeItem(BaseModel):
    id: str
    needs_check: bool


class JudgeOut(BaseModel):
    items: list[JudgeItem] = Field(default_factory=list)


def _h(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _stat(values: list[float]) -> dict:
    return {"runs": [round(v, 4) for v in values], "mean": round(mean(values), 4) if values else None,
            "spread": round(max(values) - min(values), 4) if values else None}


def frozen_replay(ledger: Ledger, scenario: str, candidates: list[str]) -> list[str]:
    """固定回放集：首次评测时冻结，此后不随数据增长而变化。"""
    doc = ledger.db.rsi_protocols.find_one({"scenario": scenario})
    if doc:
        return doc["replay_ids"]
    ids = sorted(candidates)
    ledger.db.rsi_protocols.insert_one({"scenario": scenario, "replay_ids": ids, "hash": _h(ids),
                                        "created_at": datetime.now(timezone.utc)})
    return ids


# ======================= S1：经验卡 =======================
def s1_items(repo, issues: list) -> list[dict]:
    """主张样本：被裁定成立的质询目标 / 核验存疑 = bad；同档案里已核验、未被推翻的主张 = good（按哈希稳定抽样）。"""
    bad_keys = {(i.source["dossier"], i.source["version"], i.source["claim_id"]) for i in issues}
    items: dict[str, dict] = {}
    for d in repo.db.dossiers.find({"$or": [{"deliberation": {"$ne": None}}, {"claims.status": "disputed"}]},
                                   projection={"_id": 0, "report_md": 0}):
        claims = list(d.get("claims", []))
        for t in (d.get("deliberation") or {}).get("team", []):
            claims += t.get("claims", [])
        ruled = {ch["target_claim_id"] for ch in (d.get("deliberation") or {}).get("challenges", [])}
        bad, good = [], []
        for c in claims:
            key = (d["key"], d["version"], c["id"])
            item = {"id": _h(*key)[:12], "ticker": d["ticker"], "as_of": d["as_of"], "dossier": f"{d['key']} v{d['version']}",
                    "text": c["text"], "kind": c["kind"]}
            if key in bad_keys:
                bad.append(item | {"label": "bad"})
            elif c.get("status") == "verified" and c["id"] not in ruled and c["kind"] in ("fact", "inference"):
                good.append(item | {"label": "good"})
        good.sort(key=lambda x: x["id"])
        for it in bad + good[: max(len(bad) * GOOD_PER_BAD, 2)]:
            items[it["id"]] = it
    return list(items.values())


def balanced_accuracy(rows: list[tuple[str, bool]]) -> float:
    bad = [flag for label, flag in rows if label == "bad"]
    good = [not flag for label, flag in rows if label == "good"]
    parts = [sum(x) / len(x) for x in (bad, good) if x]
    return sum(parts) / len(parts) if parts else 0.0


def _judge(h, items: list[dict], cards: list[LessonCard]) -> tuple[dict[str, bool], int]:
    used: dict[str, LessonCard] = {}
    blocks = []
    for it in items:
        hit = recall(cards, it["text"])
        used.update({c.id: c for c in hit})
        blocks.append(f"[{it['id']}] ({it['kind']}) {it['text']}" + (f"（相关方法提示：{'、'.join(c.id for c in hit)}）" if hit else ""))
    hints = render_lessons(sorted(used.values(), key=lambda c: c.id))
    before = h.budget.used.get("tokens", 0)
    out: JudgeOut = h.llm("classify", S1_JUDGE_SYSTEM, (hints + "\n\n" if hints else "") + "\n\n".join(blocks),
                          JudgeOut, purpose="rsi_s1_judge")
    return {x.id: x.needs_check for x in out.items}, int(h.budget.used.get("tokens", 0) - before)


def evaluate_s1(deps, ledger: Ledger, run: Run, base_cards: list[LessonCard], cand_cards: list[LessonCard],
                log: Callable[[str], None] = lambda m: None) -> dict:
    issues = ledger.get_issues(run.issue_ids)
    all_issues = ledger.list_issues(scenario="S1")
    items = s1_items(deps.repo, all_issues)
    evo_tickers = {i.source["ticker"] for i in issues}
    evo_dossiers = {f"{i.source['dossier']} v{i.source['version']}" for i in issues}
    targets = {_h(i.source["dossier"], i.source["version"], i.source["claim_id"])[:12] for i in issues}
    replay_ids = set(frozen_replay(ledger, "S1", [it["id"] for it in items]))
    slices = {
        # 同类错误是否减少：只计本候选针对的坏主张，好主张取同档案的（衡量误伤）
        "evolution": [it for it in items if it["dossier"] in evo_dossiers and (it["label"] == "good" or it["id"] in targets)],
        "replay": [it for it in items if it["id"] in replay_ids],
        "holdout": [it for it in items if it["ticker"] not in evo_tickers],
    }
    protocol = {"scorer": S1_SCORER, "replay_hash": _h(sorted(replay_ids)), "hash": _h(S1_SCORER, S1_JUDGE_SYSTEM, {k: sorted(x["id"] for x in v) for k, v in slices.items()}),
                "slices": {k: {"n": len(v), "bad": sum(x["label"] == "bad" for x in v)} for k, v in slices.items()}}
    h = deps.harness(f"rsi-{run.run_id}", "quick", date.today(), Budget(limits={"tokens": 2_000_000, "wall_clock_s": 3600}),
                     node="rsi_eval", principal="evaluator")
    arms_cfg = {"base": base_cards, "cand": cand_cards, "off": []}
    arms: dict[str, dict] = {}
    for arm, cards in arms_cfg.items():
        if arm == "off" and not base_cards:
            arms["off"] = arms["base"] | {"note": "在用经验库为空，关经验库即基线"}
            continue
        per_slice: dict[str, list[float]] = {k: [] for k in slices}
        tokens = 0
        for rep in range(REPEATS):
            for name, sl in slices.items():
                if not sl:
                    continue
                verdicts, t = _judge(h, sl, cards)
                tokens += t
                per_slice[name].append(balanced_accuracy([(it["label"], verdicts.get(it["id"], False)) for it in sl]))
            log(f"S1 评测 {arm} 第 {rep + 1}/{REPEATS} 轮完成")
        arms[arm] = {"slices": {k: _stat(v) for k, v in per_slice.items() if v}, "tokens": tokens,
                     "cards": [c.id for c in cards]}
    return {"scenario": "S1", "protocol": protocol, "repeats": REPEATS, "arms": arms, "primary": "evolution",
            "metric": "主张审查平衡准确率（坏主张被拦下 + 好主张不误伤）",
            "leakage": {"evolution": sorted(evo_tickers), "holdout": sorted({it["ticker"] for it in slices["holdout"]})},
            "samples": {k: [{"id": x["id"], "label": x["label"], "text": x["text"][:80], "dossier": x["dossier"]} for x in v]
                        for k, v in slices.items()}}


# ======================= S2：路由参数 =======================
def evaluate_s2(deps, ledger: Ledger, run: Run, base: dict, cand: dict, log: Callable[[str], None] = lambda m: None) -> dict:
    """在多次独立判别器运行记录下的原始概率上回放：每次评测运行就是一次独立重复，天然暴露判别器自身的随机波动。"""
    from advisor.routing import route_from_probs
    runs = list(deps.repo.db.eval_runs.find({"type": "routing"}, projection={"_id": 0}).sort("created_at", -1).limit(5))
    issues = ledger.get_issues(run.issue_ids)
    evo_q = {i.source["question"] for i in issues}
    all_q = sorted({r["question"] for rr in runs for r in rr.get("rows", [])})
    replay_q = set(frozen_replay(ledger, "S2", all_q))
    slices = {"evolution": evo_q, "replay": replay_q, "holdout": set(all_q) - evo_q}

    def score(rows: list[dict], cfg: dict) -> tuple[float, float]:
        correct, deep_hit, deep_n = 0, 0, 0
        for r in rows:
            if r["source"] in ("model", "abstain"):
                route = route_from_probs(r["probs"], {**deps.policy.routing, **cfg}, r.get("stakes"), r.get("uncertainty"),
                                         r.get("intent", "research")).route
            else:
                route = r["route"]
            correct += route == r["label"]
            if r["label"] == "deep":
                deep_n += 1
                deep_hit += route == "deep"
        return correct / max(len(rows), 1), deep_hit / max(deep_n, 1)

    arms: dict[str, dict] = {}
    for arm, cfg in (("base", base), ("cand", cand)):
        per: dict[str, list[float]] = {k: [] for k in slices}
        recall_: list[float] = []
        for rr in runs:
            for name, qs in slices.items():
                rows = [r for r in rr.get("rows", []) if r["question"] in qs]
                if rows:
                    acc, dr = score(rows, cfg)
                    per[name].append(acc)
                    if name == "replay":
                        recall_.append(dr)
        arms[arm] = {"slices": {k: _stat(v) for k, v in per.items() if v}, "deep_recall": _stat(recall_), "tokens": 0, "params": cfg}
    log(f"S2 回放 {len(runs)} 次独立判别器运行")
    return {"scenario": "S2", "repeats": len(runs), "arms": arms, "primary": "replay",
            "metric": "路由准确率（每次判别器运行算一次重复）",
            "protocol": {"scorer": S2_SCORER, "replay_hash": _h(sorted(replay_q)), "hash": _h(S2_SCORER, sorted(replay_q), sorted(r["run_id"] for r in runs)),
                         "slices": {k: {"n": len(v)} for k, v in slices.items()}, "eval_runs": [r["run_id"] for r in runs]},
            "leakage": {"evolution": sorted(evo_q), "holdout": sorted(slices["holdout"])}}


# ======================= S3：检索模板 =======================
def _cached_searches(repo) -> list[dict]:
    out = []
    for doc in repo.db.cache.find({"key": {"$regex": "^ds:search:"}}, projection={"_id": 0}):
        _, _, as_of, _, query = doc["key"].split(":", 4)
        out.append({"id": _h(doc["key"])[:12], "as_of": as_of, "query": query, "raw": doc["value"] or []})
    return out


def search_f(searches: list[dict], cfg: dict, policy) -> dict:
    """保留下来的结果里可用的占比（精确率）× 所有权威结果里被保留且能抓取的占比（召回率）。"""
    from advisor.skills.data.web import fetch_allowlist, host_matches
    allow, b_min, rr = fetch_allowlist(policy, cfg), int(cfg["authority_b_min"]), float(cfg["rerank_min"])
    kept = good_kept = good_all = 0
    for s in searches:
        for r in s["raw"]:
            url = r.get("url") or ""
            if not url or host_matches(url, policy.block_sites):
                continue
            authoritative = int(r.get("authority") or -1) >= b_min
            good_all += authoritative
            if float(r.get("rerank_score") or 0) >= rr:
                kept += 1
                good_kept += authoritative and host_matches(url, allow)
    precision = good_kept / kept if kept else 0.0
    recall_ = good_kept / good_all if good_all else 1.0
    return {"precision": precision, "recall": recall_, "kept": kept,
            "f": 2 * precision * recall_ / (precision + recall_) if precision + recall_ else 0.0}


def _s3_slices(deps, ledger: Ledger) -> tuple[dict[str, list[dict]], set[str]]:
    searches = [s for s in _cached_searches(deps.repo) if s["raw"]]
    slices = {
        "evolution": [s for s in searches if int(s["id"], 16) % 3 != 0],
        "holdout": [s for s in searches if int(s["id"], 16) % 3 == 0],
    }
    replay_ids = set(frozen_replay(ledger, "S3", [s["id"] for s in searches]))
    slices["replay"] = [s for s in searches if s["id"] in replay_ids]
    return slices, replay_ids


def evaluate_s3(deps, ledger: Ledger, run: Run, base: dict, cand: dict, log: Callable[[str], None] = lambda m: None) -> dict:
    """阈值与站点名单：在缓存的原始搜索结果上确定性回放，三次重复结果一致（噪声为 0）。
    专家搜索侧重：要重新生成搜索词并真实搜索，走 _evaluate_hint。"""
    if "hint" in run.diff:
        return _evaluate_hint(deps, ledger, run, base, cand, log)
    slices, replay_ids = _s3_slices(deps, ledger)
    full = lambda c: {**deps.policy.search, **c}     # noqa: E731
    arms: dict[str, dict] = {}
    for arm, cfg in (("base", base), ("cand", cand)):
        res = {k: search_f(v, full(cfg), deps.policy) for k, v in slices.items() if v}
        arms[arm] = {"slices": {k: _stat([v["f"]] * REPEATS) for k, v in res.items()},
                     "detail": {k: {m: round(x, 4) for m, x in v.items()} for k, v in res.items()}, "tokens": 0,
                     "params": {"rerank_min": cfg["rerank_min"], "authority_b_min": cfg["authority_b_min"],
                                "fetch_allow_add": cfg.get("fetch_allow_add", [])}}
    log(f"S3 回放 {sum(len(v) for k, v in slices.items() if k != 'replay')} 次缓存搜索")
    return {"scenario": "S3", "repeats": REPEATS, "deterministic": True, "arms": arms, "primary": "evolution",
            "metric": "可用线索的 F 值（保留结果里权威且可抓取的占比 × 权威结果被保留并可抓取的占比）",
            "protocol": {"scorer": S3_SCORER, "replay_hash": _h(sorted(replay_ids)), "hash": _h(S3_SCORER, sorted(replay_ids)),
                         "slices": {k: {"n": len(v)} for k, v in slices.items()}},
            "leakage": {"evolution": sorted(s["id"] for s in slices["evolution"]),
                        "holdout": sorted(s["id"] for s in slices["holdout"])}}


def s3_hint_items(repo, expert: str, evo_dossiers: set[tuple[str, int]]) -> dict[str, list[dict]]:
    """进化集：坏案例所在档案里这位专家拿到的问题；留出集：其他股票的档案（每只股票取最新一份）。"""
    rows = []
    for d in repo.db.dossiers.find({"deliberation": {"$ne": None}},
                                   projection={"_id": 0, "key": 1, "version": 1, "ticker": 1, "name": 1, "as_of": 1,
                                               "deliberation.team": 1}):
        t = next((t for t in (d.get("deliberation") or {}).get("team", []) if t["expert"] == expert and t.get("brief")), None)
        if t:
            rows.append({"id": _h(d["key"], d["version"], expert)[:12], "dossier": f"{d['key']} v{d['version']}",
                         "ticker": d["ticker"], "company": d.get("name") or d["ticker"], "as_of": str(d["as_of"])[:10],
                         "questions": t["brief"], "evo": (d["key"], d["version"]) in evo_dossiers})
    evo = sorted([r for r in rows if r["evo"]], key=lambda r: r["id"])[:HINT_ITEMS]
    evo_t = {r["ticker"] for r in evo}
    hold: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r["as_of"], reverse=True):
        if not r["evo"] and r["ticker"] not in evo_t:
            hold.setdefault(r["ticker"], r)
    return {"evolution": evo, "holdout": sorted(hold.values(), key=lambda r: r["id"])[:HINT_ITEMS]}


def _hint_score(h, deps, expert: str, hint: str, item: dict, cfg: dict) -> float:
    from advisor.experts.agent import expert_queries
    from advisor.experts.specs import EXPERTS
    from advisor.harness import BudgetExceeded, HarnessDenied, SkillFailed
    from advisor.skills.data.web import fetch_allowlist, host_matches
    allow, b_min = fetch_allowlist(deps.policy, cfg), int(cfg["authority_b_min"])
    n = good = 0
    for q in expert_queries(h, EXPERTS[expert], hint, item["company"], item["ticker"], item["questions"])[:HINT_QUERIES]:
        try:
            out = h.call("web.search", query=q, as_of=date.fromisoformat(item["as_of"]), count=10,
                         lookback_days=int(cfg.get("lookback_days", 120)))
        except (SkillFailed, HarnessDenied, BudgetExceeded):
            continue
        n += len(out.hits)
        good += sum(x.authority >= b_min and host_matches(x.url, allow) for x in out.hits)
    return good / n if n else 0.0


def _evaluate_hint(deps, ledger: Ledger, run: Run, base: dict, cand: dict, log: Callable[[str], None]) -> dict:
    """同一批专家问题，分别用旧 / 新搜索侧重生成搜索词并真实搜索，比较带回来的结果里可用的占比。"""
    expert = run.diff["hint"]["expert"]
    issues = ledger.get_issues(run.issue_ids)
    live = s3_hint_items(deps.repo, expert, {(i.source["dossier"], i.source["version"]) for i in issues})
    if not live["evolution"]:
        raise ValueError("坏案例所在档案里找不到这位专家的问题，无法评测")
    slices, replay_ids = _s3_slices(deps, ledger)
    full = {**deps.policy.search, **base}
    replay_f = search_f(slices["replay"], full, deps.policy)["f"] if slices["replay"] else None
    h = deps.harness(f"rsi-{run.run_id}", "standard", date.today(),
                     Budget(limits={"tokens": 1_000_000, "search_calls": 400, "wall_clock_s": 3600}),
                     node="rsi_eval", principal="evaluator")
    arms: dict[str, dict] = {}
    for arm, cfg in (("base", base), ("cand", cand)):
        hint = cfg.get("expert_hints", {}).get(expert) or run.diff["hint"]["old"]
        per: dict[str, list[float]] = {k: [] for k in live if live[k]}
        before = h.budget.used.get("tokens", 0)
        for rep in range(REPEATS):
            for name in per:
                per[name].append(mean(_hint_score(h, deps, expert, hint, it, {**deps.policy.search, **cfg}) for it in live[name]))
            log(f"S3 评测 {arm} 第 {rep + 1}/{REPEATS} 轮完成")
        stats = {k: _stat(v) for k, v in per.items()}
        if replay_f is not None:      # 搜索侧重不影响已缓存的回放结果：两边相同，只用于确认没换尺子
            stats["replay"] = _stat([replay_f] * REPEATS)
        arms[arm] = {"slices": stats, "tokens": int(h.budget.used.get("tokens", 0) - before), "hint": hint}
    return {"scenario": "S3", "repeats": REPEATS, "arms": arms, "primary": "evolution",
            "metric": "专家搜索词带回的结果里，权威且可抓取的占比",
            "protocol": {"scorer": S3_HINT_SCORER, "replay_hash": _h(sorted(replay_ids)),
                         "hash": _h(S3_HINT_SCORER, sorted(replay_ids)),
                         "slices": {k: {"n": len(v)} for k, v in live.items()}},
            "leakage": {"evolution": sorted({r["ticker"] for r in live["evolution"]}),
                        "holdout": sorted({r["ticker"] for r in live["holdout"]})},
            "samples": {k: [{"id": r["id"], "dossier": r["dossier"], "text": "；".join(r["questions"])[:80]} for r in v]
                        for k, v in live.items()}}
