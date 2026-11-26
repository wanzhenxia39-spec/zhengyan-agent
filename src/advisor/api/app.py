"""FastAPI 服务：组装各业务路由，并在构建过前端时提供 Web 界面。

路由按业务拆分：research（研究任务）· dossiers（档案与证据）· evals（评测）· rsi（自进化）
· personal（用户确认档案、个人情境官）· watch（订阅与增量复核）· strategy（策略卡与模拟盘）
"""
import hashlib
import hmac
import secrets
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles

from advisor.api import dossiers, evals, personal, research, rsi, strategy, watch
from advisor.api.common import JobBoard, Jobs
from advisor.graph.deps import Deps
from advisor.scheduler import Scheduler
from advisor.services import build_services
from advisor.settings import ROOT, get_settings

WEB_DIST = ROOT / "web" / "dist"
ROUTERS = (research, dossiers, evals, rsi, personal, watch, strategy)


def create_app(deps: Deps | None = None, checkpointer=None, auth: tuple[str, str] | None = None) -> FastAPI:
    production = deps is None
    if production and auth is None and (cfg := get_settings()).auth_password:
        auth = (cfg.auth_user, cfg.auth_password)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = build_services(deps, checkpointer)
        app.state.services = services
        app.state.jobs = JobBoard()
        hours = float(services.deps.policy.watch.get("scan_interval_hours", 0)) if production else 0
        scheduler = Scheduler(services, hours).start()
        yield
        scheduler.stop()

    app = FastAPI(title="股票投资顾问 Agent", version="0.4.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    if auth:
        _require_login(app, *auth)
    else:
        @app.get("/api/session")
        def session():
            return {"required": False, "logged_in": True}
    for module in ROUTERS:
        app.include_router(module.router)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str, jobs: Jobs):
        return jobs.get(job_id)

    if WEB_DIST.exists():
        _mount_web(app)
    return app


SESSION_COOKIE = "advisor_session"
SESSION_DAYS = 7
PUBLIC_PATHS = {"/", "/login", "/api/login", "/api/logout", "/api/session"}


class LoginBody(BaseModel):
    user: str
    password: str


def _require_login(app: FastAPI, user: str, password: str) -> None:
    """访问账号密码：首页和登录页公开，其余页面与接口须先登录（登录后发会话 cookie）。"""
    token = hmac.new(password.encode(), f"advisor-session:{user}".encode(), hashlib.sha256).hexdigest()

    def logged_in(request: Request) -> bool:
        return secrets.compare_digest(request.cookies.get(SESSION_COOKIE, "").encode(), token.encode())

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/assets/") or logged_in(request):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "请先登录"}, status_code=401)
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target)}", status_code=303)

    @app.post("/api/login")
    def login(body: LoginBody, request: Request):
        if not (secrets.compare_digest(body.user.encode(), user.encode())
                and secrets.compare_digest(body.password.encode(), password.encode())):
            raise HTTPException(401, "账号或密码不对")
        resp = JSONResponse({"ok": True})
        https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=https)
        return resp

    @app.post("/api/logout")
    def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE)
        return resp

    @app.get("/api/session")
    def session(request: Request):
        return {"required": True, "logged_in": logged_in(request)}


def _mount_web(app: FastAPI) -> None:
    """单页应用：静态资源直接返回，其余路径回落到 index.html。只允许读取 dist 目录内的文件。"""
    root = WEB_DIST.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "接口不存在")
        file = (root / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        return FileResponse(root / "index.html")
