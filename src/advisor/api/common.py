"""各路由共用：服务容器注入、后台作业看板、业务错误 → HTTP 状态码。"""
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Annotated, Callable

from fastapi import Depends, HTTPException, Request

from advisor.services import Services

OWNER = "owner"            # 单人阶段的操作人；审计里如实标出「自批」


def get_services(request: Request) -> Services:
    return request.app.state.services


Svc = Annotated[Services, Depends(get_services)]


class JobBoard:
    """耗时操作（RSI 提议/评测、订阅扫描、模拟盘推进）在后台线程执行，前端轮询日志。"""

    def __init__(self):
        self.jobs: dict[str, dict] = {}

    def start(self, svc: Services, kind: str, fn: Callable[[Callable[[str], None]], object],
              key: str | None = None) -> dict:
        """key 相同的作业还在跑时不重复启动，直接返回那一个（刷新页面后重复点击不会并行跑两次）。"""
        if key and (existing := self.running(key)):
            return {"job_id": existing["job_id"]}
        jid = "job_" + uuid.uuid4().hex[:8]
        job = {"job_id": jid, "kind": kind, "key": key, "status": "running", "log": [], "result": None, "error": None,
               "started_at": datetime.now(timezone.utc)}
        self.jobs[jid] = job

        def run():
            try:
                out = fn(job["log"].append)
                job.update(status="done", result=getattr(out, "run_id", None) or out)
            except Exception as e:      # 失败可见
                job.update(status="failed", error=f"{type(e).__name__}: {e}")
        svc.submit(run)
        return {"job_id": jid}

    def running(self, key: str) -> dict | None:
        return next((j for j in self.jobs.values() if j.get("key") == key and j["status"] == "running"), None)

    def get(self, job_id: str) -> dict:
        if job_id not in self.jobs:
            raise HTTPException(404, "作业不存在")
        return self.jobs[job_id]


def get_jobs(request: Request) -> JobBoard:
    return request.app.state.jobs


Jobs = Annotated[JobBoard, Depends(get_jobs)]


@contextmanager
def conflict_on(*errors: type[Exception]):
    """状态机拒绝的操作返回 409，带上原因。"""
    try:
        yield
    except errors as e:
        raise HTTPException(409, str(e)) from e
