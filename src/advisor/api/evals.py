"""评测：路由校准、单 Agent 与多专家对照。"""
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from advisor.api.common import Svc

router = APIRouter(prefix="/api/evals")


class CompareIn(BaseModel):
    case_ids: list[str] | None = None
    routes: list[str] = ["standard", "deep"]


@router.get("")
def evals(svc: Svc):
    return [{k: v for k, v in r.items() if k not in ("rows", "update_results")} for r in svc.deps.repo.list_evals()]


@router.get("/{run_id}")
def eval_run(run_id: str, svc: Svc):
    r = svc.deps.repo.get_eval(run_id)
    if not r:
        raise HTTPException(404, "评测不存在")
    return r


@router.post("/routing")
def eval_routing(svc: Svc):
    from advisor.evals.routing import run_routing_eval
    svc.submit(run_routing_eval, svc.deps)
    return {"submitted": True}


@router.post("/update")
def eval_update(svc: Svc):
    """持续更新评测：纯代码打分，几秒内完成。"""
    from advisor.evals.update import run_update_eval
    return {"run_id": run_update_eval(svc.deps)}


@router.post("/compare")
def eval_compare(body: CompareIn, svc: Svc):
    from advisor.evals.compare import load_cases, run_compare
    cases = [c for c in load_cases() if not body.case_ids or c["id"] in body.case_ids]
    if not cases:
        raise HTTPException(400, "没有匹配的评测用例")
    run_id = "ev_" + uuid.uuid4().hex[:8]
    svc.submit(run_compare, svc.research, cases, body.routes, run_id)
    return {"run_id": run_id}
