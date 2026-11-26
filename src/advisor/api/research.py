"""研究任务：提交、进度、人在环确认、取消、工作记忆、审计、系统元信息。"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from advisor.api.common import Svc
from advisor.contracts import ResearchRequest

router = APIRouter(prefix="/api")


class ResumeIn(BaseModel):
    approve: bool


@router.get("/health")
def health(svc: Svc):
    ok = True
    try:
        svc.deps.repo.ping()
    except Exception:
        ok = False
    return {"mongo": ok, "skills": svc.deps.registry.catalog()}


@router.post("/research")
def research(req: ResearchRequest, svc: Svc):
    from advisor.llm import LLMNotConfigured
    try:
        return {"task_id": svc.research.start(req)}
    except LLMNotConfigured as e:
        raise HTTPException(400, str(e)) from e


@router.get("/tasks")
def tasks(svc: Svc, limit: int = 30):
    return svc.deps.repo.list_tasks(limit)


@router.get("/tasks/{task_id}")
def task(task_id: str, svc: Svc):
    t = svc.deps.repo.get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    return t


@router.post("/tasks/{task_id}/resume")
def resume(task_id: str, body: ResumeIn, svc: Svc):
    try:
        svc.research.resume(task_id, body.approve)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: str, svc: Svc):
    status = svc.research.cancel(task_id)
    if status is None:
        raise HTTPException(409, "任务已结束，无法取消")
    return {"status": status}


@router.get("/tasks/{task_id}/workspace")
def workspace(task_id: str, svc: Svc):
    return svc.deps.repo.list_working(task_id)


@router.get("/tasks/{task_id}/audit")
def audit(task_id: str, svc: Svc):
    return svc.deps.repo.list_audit(task_id)


@router.get("/meta")
def meta(svc: Svc):
    from advisor.experts.specs import EXPERTS
    p = svc.deps.policy
    return {
        "experts": [{"key": e.key, "name": e.name, "mandate": e.mandate, "constraint": e.constraint,
                     "role": p.experts.get("roles", {}).get(e.key)} for e in EXPERTS.values()],
        "routes": {k: {"llm_role": r.llm_role, "budget": r.budget} for k, r in p.routes.items() if k != "mcp"},
        "routing": p.routing, "expert_cfg": {k: v for k, v in p.experts.items() if k != "roles"},
    }
