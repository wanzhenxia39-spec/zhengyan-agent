"""RSI 自进化 API：闭环总览、坏案例、候选、门控、版本血缘、开/关经验库对照。耗时操作（提议、评测）在后台执行。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from advisor.api.common import OWNER, Jobs, Svc, conflict_on
from advisor.rsi import TransitionError
from advisor.rsi.models import KIND_LABEL

router = APIRouter(prefix="/api/rsi")


class ProposeIn(BaseModel):
    scenario: str
    issue_id: str | None = None


class NoteIn(BaseModel):
    note: str = ""


class RejectIn(BaseModel):
    reason: str


class RollbackIn(BaseModel):
    kind: str
    reason: str


@router.get("/overview")
def overview(svc: Svc):
    runner = svc.rsi
    led = runner.ledger
    led.bootstrap(runner.deps.policy)
    runs = led.list_runs(limit=200)
    issues = led.list_issues()
    events = led.list_events(limit=500)
    actions = {e["action"] for e in events}
    active = {}
    for kind in ("lessons", "routing", "search"):
        a = led.active_asset(kind)
        active[kind] = {"label": KIND_LABEL[kind], "version": a.version, "sha256": a.sha256, "change_reason": a.change_reason,
                        "created_at": a.created_at, "content": a.content} if a else None
    lineage = {}
    for kind in ("lessons", "routing", "search"):
        lineage[kind] = [{"version": a.version, "parent": a.parent_version, "sha256": a.sha256[:10], "run_id": a.run_id,
                          "change_reason": a.change_reason, "created_at": a.created_at,
                          "active": active[kind] and active[kind]["version"] == a.version}
                         for a in led.list_assets(kind)]
    evaluated = [x for x in runs if x.eval]
    s1 = next((x for x in evaluated if x.scenario == "S1"), None)
    counterfactual = None
    if s1:
        counterfactual = {"run_id": s1.run_id, "metric": s1.eval.get("metric"),
                          "arms": {k: {"slices": v.get("slices"), "tokens": v.get("tokens"), "cards": v.get("cards"), "note": v.get("note")}
                                   for k, v in s1.eval["arms"].items()}}
    inherit = list(runner.deps.repo.db.dossiers.aggregate([
        {"$match": {"rsi_versions": {"$exists": True, "$ne": {}}}},
        {"$group": {"_id": "$rsi_versions", "n": {"$sum": 1}, "lessons_used": {"$addToSet": "$lessons_used"},
                    "last": {"$max": "$created_at"}}},
        {"$sort": {"last": -1}}, {"$limit": 10}]))
    return {
        "loop": {
            "collect": {"done": bool(issues), "count": len(issues)},
            "propose": {"done": bool(runs), "count": len(runs)},
            "evaluate": {"done": bool(evaluated), "count": len(evaluated)},
            "gates": {"done": any(x.gates and all(g.passed for g in x.gates) for x in runs),
                      "count": sum(bool(x.gates) for x in runs)},
            "release": {"done": "release" in actions, "count": sum(e["action"] == "release" for e in events),
                        "rollback": sum(e["action"] == "rollback" for e in events)},
        },
        "active": active, "lineage": lineage, "counterfactual": counterfactual,
        "issues": {sc: {"open": sum(i.scenario == sc and i.status == "open" for i in issues),
                        "total": sum(i.scenario == sc for i in issues)} for sc in ("S1", "S2", "S3")},
        "inheritance": [{"versions": g["_id"], "dossiers": g["n"],
                         "lessons_used": sorted({x for xs in g["lessons_used"] for x in xs}), "last": g["last"]} for g in inherit],
        "self_approved": sum(e.get("self_approved", False) for e in events if e["action"] == "approve"),
    }


@router.get("/issues")
def issues(svc: Svc, scenario: str | None = None, status: str | None = None):
    return [i.model_dump(mode="json") for i in svc.rsi.ledger.list_issues(scenario, status)]


@router.get("/runs")
def runs(svc: Svc, scenario: str | None = None):
    return [x.model_dump(mode="json", exclude={"content"}) | {"eval": None, "has_eval": bool(x.eval)}
            for x in svc.rsi.ledger.list_runs(scenario)]


@router.get("/runs/{run_id}")
def run(run_id: str, svc: Svc, jobs: Jobs):
    led = svc.rsi.ledger
    x = led.get_run(run_id)
    if not x:
        raise HTTPException(404, "候选不存在")
    base = led.get_asset(x.kind, x.base_version)
    return {"run": x.model_dump(mode="json"), "base": base.model_dump(mode="json") if base else None,
            "issues": [i.model_dump(mode="json") for i in led.get_issues(x.issue_ids)],
            "events": led.list_events(run_id=run_id), "job": jobs.running(f"evaluate:{run_id}")}


@router.get("/assets/{kind}/{version}")
def asset(kind: str, version: int, svc: Svc):
    a = svc.rsi.ledger.get_asset(kind, version)
    if not a:
        raise HTTPException(404, "资产不存在")
    return a.model_dump(mode="json")


@router.get("/events")
def events(svc: Svc, limit: int = 100):
    return svc.rsi.ledger.list_events(limit)


@router.post("/collect")
def collect(svc: Svc):
    return svc.rsi.collect(OWNER)


@router.post("/propose")
def propose(body: ProposeIn, svc: Svc, jobs: Jobs):
    if body.scenario not in ("S1", "S2", "S3"):
        raise HTTPException(400, "scenario 只能是 S1/S2/S3")
    return jobs.start(svc, "propose", lambda log: svc.rsi.propose(body.scenario, body.issue_id, OWNER))


@router.post("/runs/{run_id}/evaluate")
def evaluate(run_id: str, svc: Svc, jobs: Jobs):
    return jobs.start(svc, "evaluate", lambda log: svc.rsi.evaluate(run_id, OWNER, log), key=f"evaluate:{run_id}")


@router.post("/runs/{run_id}/approve")
def approve(run_id: str, body: NoteIn, svc: Svc):
    with conflict_on(TransitionError):
        return svc.rsi.approve(run_id, OWNER, body.note).model_dump(mode="json", exclude={"content", "eval"})


@router.post("/runs/{run_id}/reject")
def reject(run_id: str, body: RejectIn, svc: Svc):
    with conflict_on(TransitionError):
        return svc.rsi.reject(run_id, OWNER, body.reason).model_dump(mode="json", exclude={"content", "eval"})


@router.post("/runs/{run_id}/release")
def release(run_id: str, svc: Svc):
    with conflict_on(TransitionError):
        return svc.rsi.release(run_id, OWNER).model_dump(mode="json", exclude={"content", "eval"})


@router.post("/rollback")
def rollback(body: RollbackIn, svc: Svc):
    with conflict_on(TransitionError):
        return svc.rsi.rollback(body.kind, OWNER, body.reason)


@router.get("/jobs/{job_id}")
def job_status(job_id: str, jobs: Jobs):
    return jobs.get(job_id)
