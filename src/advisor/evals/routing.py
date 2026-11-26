"""路由判别器离线评测与温度校准：准确率、ECE、NLL、拒判率。模型自报置信度不能直接作为放行依据。"""
import json
import math
import uuid
from datetime import date, datetime, timezone

from advisor.harness import Budget
from advisor.routing import calibrate, decide_route
from advisor.routing.router import ORDER
from advisor.settings import ROOT

CASES = ROOT / "evals" / "golden" / "routing_cases.json"
TEMPERATURES = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]


def ece(confs: list[float], correct: list[bool], bins: int = 5) -> float:
    total, err = len(confs), 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, c in enumerate(confs) if lo < c <= hi or (b == 0 and c == 0)]
        if idx:
            acc = sum(correct[i] for i in idx) / len(idx)
            conf = sum(confs[i] for i in idx) / len(idx)
            err += len(idx) / total * abs(acc - conf)
    return round(err, 4)


def fit(rows: list[dict], abstain_below: float) -> dict:
    out = {}
    for t in TEMPERATURES:
        nll, confs, correct, abstain = 0.0, [], [], 0
        for r in rows:
            cal = calibrate(r["probs"], t)
            nll -= math.log(max(cal[r["label"]], 1e-6))
            top = max(cal, key=cal.get)
            confs.append(cal[top])
            correct.append(top == r["label"])
            abstain += cal[top] < abstain_below
        out[t] = {"nll": round(nll / len(rows), 4), "ece": ece(confs, correct), "abstain_rate": round(abstain / len(rows), 3)}
    # 目标：ECE（期望校准误差）最小；ECE 相同时取 NLL 更小的温度
    best = min(out, key=lambda t: (out[t]["ece"], out[t]["nll"]))
    return {"by_temperature": {str(k): v for k, v in out.items()}, "best_temperature": best}


def run_routing_eval(deps, path=CASES) -> str:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    run_id = "rt_" + uuid.uuid4().hex[:8]
    # 评测线上实际在用的参数：policies.yaml 叠加 RSI 账本里已发布的路由参数（S2）
    cfg = deps.rsi.routing(deps.policy.routing) if deps.rsi else dict(deps.policy.routing)
    rows = []
    for i, case in enumerate(cases):
        h = deps.harness(f"eval-{run_id}", "quick", date.today(), Budget(limits={"tokens": 20000, "wall_clock_s": 120}),
                         node="route_eval", principal="evaluator")
        d = decide_route(h, case["question"], case.get("intent", "research"), "auto", cfg)
        rows.append({"id": i, "question": case["question"], "label": case["label"], "route": d.route,
                     "source": d.source, "classifier": d.classifier, "probs": d.probs or {k: (1.0 if k == d.route else 0.0) for k in ORDER},
                     "stakes": d.stakes, "uncertainty": d.uncertainty, "intent": case.get("intent", "research"),
                     "abstain": d.abstain, "correct": d.route == case["label"]})
    model_rows = [r for r in rows if r["source"] in ("model", "abstain")]
    confusion = {a: {b: sum(1 for r in rows if r["label"] == a and r["route"] == b) for b in ORDER} for a in ORDER}
    deep_recall = (confusion["deep"]["deep"] / max(sum(confusion["deep"].values()), 1))
    run = {
        "run_id": run_id, "type": "routing", "status": "done", "created_at": datetime.now(timezone.utc),
        "rows": rows, "confusion": confusion,
        "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 3),
        "deep_recall": round(deep_recall, 3),
        "abstain_rate": round(sum(r["abstain"] for r in rows) / len(rows), 3),
        "calibration": fit(model_rows, float(cfg.get("abstain_below", 0.55))) if model_rows else {},
        "current": {"temperature": cfg.get("temperature", 1.0), "abstain_below": cfg.get("abstain_below", 0.55)},
    }
    deps.repo.save_eval(run)
    return run_id
