"""二期出口标准：对照"单 Agent + SOP"基线，多专家质量不退化且成本可接受，否则保留单 Agent。

统一材料（同一问题、同一 as_of、同一数据）、统一核验规则；档案写入隔离命名空间，不污染用户档案。
"""
import json
import uuid
from datetime import date, datetime, timezone
from statistics import mean

from advisor.contracts import ResearchRequest
from advisor.evals.metrics import dossier_metrics
from advisor.settings import ROOT

DEFAULT_CASES = ROOT / "evals" / "cases" / "compare_cases.json"
NON_INFERIOR_MARGIN = 0.02
MAX_COST_RATIO = 5.0


def load_cases(path=DEFAULT_CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def summarize(results: list[dict], baseline: str = "standard", candidate: str = "deep") -> dict:
    by_route: dict[str, list[dict]] = {}
    for r in results:
        if r.get("metrics"):
            by_route.setdefault(r["route"], []).append(r["metrics"])
    agg = {route: {k: round(mean(m[k] for m in ms), 3) for k in
                   ("score", "verified_rate", "coverage_rate", "numeric_accuracy", "dissents", "tokens", "search_calls", "seconds")}
           for route, ms in by_route.items()}
    verdict = {"decision": "insufficient", "text": "样本不足，无法判断"}
    if baseline in agg and candidate in agg:
        delta = agg[candidate]["score"] - agg[baseline]["score"]
        ratio = agg[candidate]["tokens"] / max(agg[baseline]["tokens"], 1)
        non_inferior, affordable = delta >= -NON_INFERIOR_MARGIN, ratio <= MAX_COST_RATIO
        ok = non_inferior and affordable
        verdict = {
            "decision": "adopt_multi_expert" if ok else "keep_single_agent",
            "quality_delta": round(delta, 3), "cost_ratio": round(ratio, 2),
            "non_inferior": non_inferior, "affordable": affordable,
            "text": ("多专家通过准入：质量不退化且成本在上限内（仅用于争议深研）" if ok else
                     "保留单 Agent 基线：" + ("质量退化" if not non_inferior else "") +
                     ("、" if not non_inferior and not affordable else "") + ("成本超过上限" if not affordable else "")),
            "criteria": {"non_inferior_margin": NON_INFERIOR_MARGIN, "max_cost_ratio": MAX_COST_RATIO},
        }
    return {"routes": agg, "verdict": verdict}


def run_compare(svc, cases: list[dict], routes: list[str], run_id: str | None = None) -> str:
    repo = svc.deps.repo
    run_id = run_id or "ev_" + uuid.uuid4().hex[:8]
    run = {"run_id": run_id, "type": "compare", "status": "running", "routes": routes, "cases": cases,
           "results": [], "created_at": datetime.now(timezone.utc)}
    repo.save_eval(run)
    for case in cases:
        for route in routes:
            req = ResearchRequest(question=case["question"], ticker=case.get("ticker"), route=route,
                                  as_of=date.fromisoformat(case["as_of"]) if case.get("as_of") else None)
            entry = {"case": case["id"], "route": route}
            try:
                tid = svc.start(req, background=False, namespace=f"eval-{run_id}-{route}")
                task = repo.get_task(tid)
                entry["task_id"] = tid
                if task["status"] == "done":
                    d = repo.get_dossier(task["result"]["dossier_key"], task["result"]["version"])
                    ev = {c.id: c for c in repo.get_evidence(d.evidence_ids + [i for c in d.claims for i in c.evidence_ids])}
                    entry.update(dossier_key=d.key, version=d.version, metrics=dossier_metrics(d, ev, task))
                else:
                    entry["error"] = f"{task['status']}: {task.get('error')}"
            except Exception as e:  # noqa: BLE001  单例失败记录在案，不中断评测
                entry["error"] = f"{type(e).__name__}: {e}"
            run["results"].append(entry)
            run["summary"] = summarize(run["results"])
            repo.save_eval(run)
    run["status"] = "done"
    repo.save_eval(run)
    return run_id
