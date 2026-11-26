"""「持续更新」评测：新证据出现后，系统能否修正受影响的结论、保留没受影响的结论。

案例来自真实的「订阅提醒 → 用新数据重新研究」记录：旧版本档案 + 变化事件 + 受影响结论 + 新版本档案。
每到一个新的财报季，已重新研究的提醒会自动成为新案例，不需要另外搭数据。

纯代码打分，不用模型自评：
- 有交代   受影响的旧结论，在新版本里有逐条复核结论（保留 / 削弱 / 失效 / 无法判断）
- 有判定   有交代的里面，给出了明确判定（不是「无法判断」）
- 用上新数据 提醒里的新报告期、价格变化，新版本里有已核验的结论引用了对应的新数据
- 修正有据 判为削弱或失效的，引用了旧版本时点之后的新证据
- 不无故丢失 没受影响的旧结论，在新版本里被复核过或仍然存在
可选人工金标 evals/update/labels.yaml：{提醒 id: {旧结论 id: 期望判定}}，有标注时另算判定准确率。
"""
import re
import uuid
from datetime import date, datetime, timezone

import yaml

from advisor.personal.officer import related
from advisor.settings import ROOT

LABELS = ROOT / "evals" / "update" / "labels.yaml"
MATCH_MIN = 0.6          # 复核记录 / 新结论与旧结论的字面重合度阈值
_PERIOD = re.compile(r"(\d{4}-\d{2}-\d{2}) 报告期")
METRICS = {
    "coverage": "受影响结论有交代", "decisive": "给出明确判定", "absorbed": "用上新数据",
    "grounded": "修正有新证据", "stable": "未受影响结论不无故丢失", "label_acc": "判定与人工金标一致",
}


def _ratio(hit: int, total: int) -> float | None:
    return round(hit / total, 3) if total else None


def _match(text: str, candidates: list[str]) -> int | None:
    scores = [(related(text, c), i) for i, c in enumerate(candidates)]
    best = max(scores, default=(0.0, None))
    return best[1] if best[0] >= MATCH_MIN else None


def load_labels(path=LABELS) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def score_case(alert: dict, old: dict, new: dict, evidence: dict[str, dict], labels: dict | None = None) -> dict:
    old_as_of = str(old["as_of"])[:10]
    reviews = new.get("prior_review") or []
    review_texts = [r["prior_claim"] for r in reviews]
    affected_ids = {a["claim_id"] for a in alert.get("affected", [])}
    rows = []
    for c in old.get("claims", []):
        k = _match(c["text"], review_texts)
        r = reviews[k] if k is not None else None
        rows.append({"id": c["id"], "text": c["text"], "affected": c["id"] in affected_ids,
                     "verdict": r["verdict"] if r else None, "reason": r["reason"] if r else "",
                     "evidence_ids": r.get("evidence_ids", []) if r else [],
                     "kept": _match(c["text"], [x["text"] for x in new.get("claims", [])]) is not None})
    affected = [r for r in rows if r["affected"]]
    covered = [r for r in affected if r["verdict"]]
    changed = [r for r in covered if r["verdict"] in ("weakened", "invalidated")]

    def is_new(eid: str) -> bool:
        e = evidence.get(eid) or {}
        ts = str(e.get("published_at") or e.get("as_of") or "")[:10]
        return ts > old_as_of or any(str(m.get("period", "")) > old_as_of for m in e.get("metrics", []))

    grounded = [r for r in changed if any(is_new(e) for e in r["evidence_ids"])]
    unaffected = [r for r in rows if not r["affected"]]
    stable = [r for r in unaffected if r["verdict"] or r["kept"]]

    # 用上新数据：每个新报告期 / 价格变化事件，新版本里是否有已核验结论引用了对应数据
    verified = [c for c in new.get("claims", []) if c.get("status") == "verified"]
    cited = [evidence.get(e) or {} for c in verified for e in c.get("evidence_ids", [])]
    absorbed = []
    for ev in alert.get("events", []):
        if ev["kind"] == "new_report" and (m := _PERIOD.search(ev["title"])):
            ok = any(str(x.get("period")) == m.group(1) for e in cited for x in e.get("metrics", []))
        elif ev["kind"] == "price_move":
            ok = any(e.get("source_type") == "market" and str(e.get("as_of"))[:10] > old_as_of for e in cited)
        else:
            continue
        absorbed.append({"event": ev["title"], "ok": ok})

    lab = (labels or {}).get(alert["id"], {})
    judged = [r for r in rows if r["id"] in lab]
    metrics = {
        "coverage": _ratio(len(covered), len(affected)),
        "decisive": _ratio(sum(r["verdict"] != "unverifiable" for r in covered), len(covered)),
        "absorbed": _ratio(sum(a["ok"] for a in absorbed), len(absorbed)),
        "grounded": _ratio(len(grounded), len(changed)),
        "stable": _ratio(len(stable), len(unaffected)),
        "label_acc": _ratio(sum(r["verdict"] == lab[r["id"]] for r in judged), len(judged)),
    }
    return {"alert_id": alert["id"], "ticker": alert["ticker"], "name": alert.get("name", ""),
            "from_version": old["version"], "to_version": new["version"], "old_as_of": old_as_of,
            "new_as_of": str(new["as_of"])[:10], "events": [e["title"] for e in alert.get("events", [])],
            "metrics": metrics, "absorbed": absorbed, "claims": rows}


def collect_cases(repo) -> list[tuple[dict, dict, dict]]:
    out = []
    for a in repo.db.watch_alerts.find({"status": "resolved", "resolved_version": {"$ne": None}}, projection={"_id": 0}):
        old = repo.db.dossiers.find_one({"key": a["dossier_key"], "version": a["dossier_version"]}, projection={"_id": 0})
        new = repo.db.dossiers.find_one({"key": a["dossier_key"], "version": a["resolved_version"]}, projection={"_id": 0})
        if old and new:
            out.append((a, old, new))
    return out


def run_update_eval(deps, labels: dict | None = None) -> str:
    repo = deps.repo
    labels = load_labels() if labels is None else labels
    results = []
    for a, old, new in collect_cases(repo):
        ids = {e for c in new.get("claims", []) for e in c.get("evidence_ids", [])}
        ids |= {e for r in new.get("prior_review") or [] for e in r.get("evidence_ids", [])}
        evidence = {e["id"]: e for e in repo.db.evidence.find({"id": {"$in": list(ids)}}, projection={"_id": 0})}
        results.append(score_case(a, old, new, evidence, labels))
    summary = {}
    for k in METRICS:
        vals = [r["metrics"][k] for r in results if r["metrics"][k] is not None]
        summary[k] = round(sum(vals) / len(vals), 3) if vals else None
    run_id = "up_" + uuid.uuid4().hex[:8]
    repo.save_eval({"run_id": run_id, "type": "update", "status": "done", "created_at": datetime.now(timezone.utc),
                    "case_count": len(results), "update_results": results, "update_summary": summary, "metric_labels": METRICS,
                    "labeled": sum(r["metrics"]["label_acc"] is not None for r in results),
                    "as_of": date.today().isoformat()})
    return run_id
