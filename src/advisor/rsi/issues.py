"""① 收集坏案例：从质询裁决、核验结果、路由评测、搜索记录里自动登记，强制四要素。"""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from advisor.rsi.ledger import Ledger
from advisor.rsi.models import Issue

# 质询类型 → 可检验的假设（"我猜是因为……"）
CHALLENGE_HYPOTHESIS = {
    "alternative_explanation": "研究员把指标变化直接归因到单一原因，没有先排除同样能解释该变化的其他因素",
    "logic_gap": "研究员从指标变化跳步推出结论，缺少中间的机制或口径论证",
    "data_basis": "所用数据的口径、时点或完整性不足以支撑该结论",
    "counter_evidence": "研究员忽视了已有的反面证据",
}
WEB_MIN_CARDS = 4
C_SHARE_MAX = 0.6
EXPERT_MIN_RESULTS = 10         # 某位专家在一份档案里的搜索结果至少这么多条，才判断它的搜索词好不好
EXPERT_USABLE_MAX = 0.25        # 可用结果（权威且可抓取）占比低于此值 → 搜索侧重需要改
SITE_MIN_RESULTS = 15           # 白名单外的站点至少出现这么多次
SITE_AUTHORITY_MIN = 0.8        # 且其中被搜索引擎评为权威的占比不低于此值 → 可能是白名单漏掉的站点
_QUERY_SUFFIX = re.compile(r" (?:after:|before:|-site:)")


def _fp(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _issue(scenario: str, kind: str, case: str, evidence: list[str], hypothesis: str, source: dict, *fp: str) -> Issue:
    f = _fp(scenario, kind, *fp)
    return Issue(id=f"I-{f[:8]}", scenario=scenario, kind=kind, case=case, evidence=evidence, hypothesis=hypothesis,
                 source=source, fingerprint=f, created_at=datetime.now(timezone.utc))


def s1_issues(repo) -> list[Issue]:
    out = []
    for d in repo.db.dossiers.find({"deliberation": {"$ne": None}}, projection={"_id": 0, "report_md": 0}):
        delib = d["deliberation"]
        claims = {c["id"]: c for t in delib.get("team", []) for c in t.get("claims", [])}
        rulings = {r["challenge_id"]: r for r in delib.get("rulings", [])}
        for ch in delib.get("challenges", []):
            r = rulings.get(ch["id"])
            if not r or r["verdict"] != "upheld":
                continue
            target = claims.get(ch["target_claim_id"], {})
            src = {"dossier": d["key"], "version": d["version"], "ticker": d["ticker"], "as_of": d["as_of"],
                   "challenge_id": ch["id"], "claim_id": ch["target_claim_id"], "expert": ch["target_expert"],
                   "challenge_kind": ch["kind"], "claim": target.get("text", ""), "evidence_ids": target.get("evidence_ids", [])}
            out.append(_issue("S1", "challenge_upheld", f"{ch['target_expert']} 的主张被质询推翻：{target.get('text', '')[:120]}",
                              [f"质询：{ch['text']}", f"裁决：{r['reason']}"],
                              CHALLENGE_HYPOTHESIS.get(ch["kind"], CHALLENGE_HYPOTHESIS["logic_gap"]), src,
                              d["key"], str(d["version"]), ch["id"]))
    for d in repo.db.dossiers.find({"claims.status": "disputed"}, projection={"_id": 0, "report_md": 0}):
        for c in d["claims"]:
            if c["status"] != "disputed":
                continue
            src = {"dossier": d["key"], "version": d["version"], "ticker": d["ticker"], "as_of": d["as_of"],
                   "claim_id": c["id"], "claim": c["text"], "evidence_ids": c.get("evidence_ids", [])}
            out.append(_issue("S1", "verify_disputed", f"核验存疑：{c['text'][:120]}",
                              c.get("verify_notes") or ["核验器判为存疑"],
                              "研究员引用的证据不足以复算或支撑该主张，下结论前没有回到 A 级源核对", src,
                              d["key"], str(d["version"]), c["id"]))
    return out


def s2_issues(repo) -> list[Issue]:
    out = []
    for run in repo.db.eval_runs.find({"type": "routing"}, projection={"_id": 0}):
        for r in run.get("rows", []):
            if r["correct"] or r["source"] not in ("model", "abstain"):
                continue
            probs = sorted(r["probs"].values(), reverse=True)
            margin = probs[0] - probs[1] if len(probs) > 1 else 1.0
            hyp = (f"判别器在前两类之间概率接近（差 {margin:.2f}），校准温度或拒判阈值使其落在错误一侧" if margin < 0.25
                   else "判别器对该类问题系统性偏向错误标签，需要调整升级阈值或补充金标")
            out.append(_issue("S2", "route_mislabel", f"「{r['question']}」应走 {r['label']}，实际走 {r['route']}",
                              [f"评测 {run['run_id']}：原始概率 {r['probs']}"], hyp,
                              {"eval_run": run["run_id"], "question": r["question"], "label": r["label"], "route": r["route"]},
                              r["question"], r["label"], r["route"]))
    return out


def s3_issues(repo) -> list[Issue]:
    out = []
    for d in repo.db.dossiers.find({}, projection={"_id": 0, "key": 1, "version": 1, "clue_ids": 1, "claims": 1,
                                                   "deliberation": 1, "ticker": 1, "as_of": 1}):
        clue_ids = d.get("clue_ids") or []
        if len(clue_ids) < WEB_MIN_CARDS:
            continue
        cards = list(repo.db.evidence.find({"id": {"$in": clue_ids}}, projection={"_id": 0, "id": 1, "level": 1, "caveats": 1}))
        cited = {i for c in d.get("claims", []) for i in c.get("evidence_ids", [])}
        for t in (d.get("deliberation") or {}).get("team", []):
            cited |= {i for c in t.get("claims", []) for i in c.get("evidence_ids", [])}
        n = len(cards)
        c_share = sum(c["level"] == "C" for c in cards) / n
        cite_rate = sum(c["id"] in cited for c in cards) / n
        reposts = sum(any("转载" in x for x in c.get("caveats", [])) for c in cards)
        if c_share < C_SHARE_MAX and cite_rate > 0:
            continue
        out.append(_issue("S3", "low_quality_search",
                          f"档案 {d['key']} v{d['version']} 的网页线索质量低：C 级占比 {c_share:.0%}，被引用率 {cite_rate:.0%}",
                          [f"网页证据 {n} 张，C 级 {round(c_share * n)} 张，被引用 {round(cite_rate * n)} 张，含转载簇 {reposts} 个"],
                          "相关度阈值偏低或搜索词过泛，放进来的多是低权威、不会被引用的结果",
                          {"dossier": d["key"], "version": d["version"], "c_share": round(c_share, 3),
                           "cite_rate": round(cite_rate, 3), "web_cards": n},
                          d["key"], str(d["version"])))
    return out


def host_of(url: str) -> str:
    host = urlparse(url or "").netloc.lower().split(":")[0]
    return host.removeprefix("www.")


def cached_results(repo) -> dict[str, list[dict]]:
    """缓存的原始搜索结果，按原始搜索词归并（缓存键里的搜索词带了时点与站点排除后缀）。"""
    out: dict[str, list[dict]] = {}
    for doc in repo.db.cache.find({"key": {"$regex": "^ds:search:"}}, projection={"_id": 0, "key": 1, "value": 1}):
        q = _QUERY_SUFFIX.split(doc["key"].split(":", 4)[4])[0].strip()
        out.setdefault(q, []).extend(doc.get("value") or [])
    return out


def usable(r: dict, b_min: int, allow: tuple[str, ...], block: tuple[str, ...]) -> bool:
    """可用结果：不在黑名单、被评为权威、并且能抓取原文（才可能升为 B 级证据）。"""
    from advisor.skills.data.web import host_matches
    url = r.get("url") or ""
    return bool(url) and not host_matches(url, block) and int(r.get("authority") or -1) >= b_min and host_matches(url, allow)


def s3_expert_issues(repo, b_min: int, allow: tuple[str, ...], block: tuple[str, ...]) -> list[Issue]:
    from advisor.experts.specs import EXPERTS
    results = cached_results(repo)
    out = []
    for d in repo.db.dossiers.find({"deliberation": {"$ne": None}},
                                   projection={"_id": 0, "key": 1, "version": 1, "ticker": 1, "deliberation": 1}):
        for t in (d.get("deliberation") or {}).get("team", []):
            per_q = [(q, results.get(q, [])) for q in t.get("queries", [])]
            rows = [r for _, rs in per_q for r in rs]
            if len(rows) < EXPERT_MIN_RESULTS or t["expert"] not in EXPERTS:
                continue
            rate = sum(usable(r, b_min, allow, block) for r in rows) / len(rows)
            if rate >= EXPERT_USABLE_MAX:
                continue
            name = EXPERTS[t["expert"]].name
            out.append(_issue("S3", "expert_query_weak",
                              f"档案 {d['key']} v{d['version']} 中{name}的搜索：{len(rows)} 条结果里可用的只占 {rate:.0%}",
                              [f"「{q}」：{len(rs)} 条结果，可用 {sum(usable(r, b_min, allow, block) for r in rs)} 条"
                               for q, rs in per_q if rs],
                              "这位专家的搜索侧重写得太泛或偏向非权威来源，生成的搜索词带不出可抓取的权威原文",
                              {"dossier": d["key"], "version": d["version"], "ticker": d.get("ticker"), "expert": t["expert"],
                               "queries": [q for q, _ in per_q], "usable_rate": round(rate, 3), "results": len(rows)},
                              d["key"], str(d["version"]), t["expert"]))
    return out


def s3_site_issues(repo, b_min: int, allow: tuple[str, ...], block: tuple[str, ...]) -> list[Issue]:
    from advisor.skills.data.web import host_matches
    seen: dict[str, list[dict]] = {}
    for rs in cached_results(repo).values():
        for r in rs:
            url = r.get("url") or ""
            if url and not host_matches(url, allow) and not host_matches(url, block):
                seen.setdefault(host_of(url), []).append(r)
    out = []
    for host, rs in seen.items():
        share = sum(int(r.get("authority") or -1) >= b_min for r in rs) / len(rs)
        if len(rs) < SITE_MIN_RESULTS or share < SITE_AUTHORITY_MIN:
            continue
        out.append(_issue("S3", "site_gap",
                          f"{host} 在搜索结果中出现 {len(rs)} 次，{share:.0%} 被评为权威，但不在抓取白名单",
                          [f"{r.get('title') or '（无标题）'} · {r.get('url')}" for r in rs[:3]],
                          "白名单漏掉了一个稳定提供权威内容的站点，这些结果只能停在 C 级线索、无法抓取原文",
                          {"host": host, "results": len(rs), "authority_share": round(share, 3)}, host))
    return out


def collect(ledger: Ledger, repo, actor: str = "system", policy=None) -> dict[str, int]:
    added = {"S1": 0, "S2": 0, "S3": 0}
    s3 = s3_issues(repo)
    if policy is not None:
        from advisor.skills.data.web import fetch_allowlist
        search = ledger.active_asset("search")
        content = search.content if search else {}
        b_min, allow = int(content.get("authority_b_min", 3)), fetch_allowlist(policy, content)
        s3 += s3_expert_issues(repo, b_min, allow, policy.block_sites) + s3_site_issues(repo, b_min, allow, policy.block_sites)
    for issue in s1_issues(repo) + s2_issues(repo) + s3:
        if ledger.add_issue(issue):
            added[issue.scenario] += 1
    ledger.event("collect", actor, detail=f"新增坏案例 S1×{added['S1']} S2×{added['S2']} S3×{added['S3']}", added=added)
    return added
