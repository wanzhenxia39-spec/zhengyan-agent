"""命令行入口：research / serve / mcp，以及 eval、rsi、profile、watch、strategy 子命令。"""
from datetime import date

import typer

app = typer.Typer(add_completion=False, help="股票投资顾问 Agent（研究与模拟，不执行交易）")


def _services():
    from advisor.services import build_services
    return build_services()


@app.command()
def research(
    question: str,
    ticker: str = typer.Option(None, help="6 位 A 股代码"),
    as_of: str = typer.Option(None, help="研究时点 YYYY-MM-DD，默认今天"),
    route: str = typer.Option("auto", help="auto / quick / standard / deep"),
    yes: bool = typer.Option(False, "--yes", help="遇到敏感信息确认时自动同意"),
):
    """同步执行一次研究，并把底稿写到 reports/。"""
    from advisor.contracts import ResearchRequest
    from advisor.settings import get_settings

    svc = _services().research
    deps = svc.deps
    req = ResearchRequest(question=question, ticker=ticker, route=route,
                          as_of=date.fromisoformat(as_of) if as_of else None)
    from advisor.llm import LLMNotConfigured
    try:
        task_id = svc.start(req, background=False)
    except LLMNotConfigured as e:
        typer.echo(str(e))
        raise typer.Exit(1) from e
    task = deps.repo.get_task(task_id)
    if task["status"] == "waiting_approval":
        typer.echo(task["interrupt"]["message"])
        approve = yes or typer.confirm("继续？")
        svc.resume(task_id, approve, background=False)
        task = deps.repo.get_task(task_id)
    for e in task["events"]:
        typer.echo(f"[{e['node']}] {e['message']}")
    if task["status"] != "done":
        typer.echo(f"任务结束：{task['status']} {task.get('error') or ''}")
        raise typer.Exit(1)
    d = deps.repo.get_dossier(task["result"]["dossier_key"], task["result"]["version"])
    out_dir = get_settings().reports_dir
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"{d.ticker}_v{d.version}_{d.as_of}.md"
    path.write_text(d.report_md, encoding="utf-8")
    typer.echo(f"\n底稿已写入 {path}")


eval_app = typer.Typer(help="评测：路由校准、单 Agent 与多专家对照")
app.add_typer(eval_app, name="eval")


def _service():
    return _services().research


@eval_app.command("routing")
def eval_routing():
    """在金标集上评测路由判别器，拟合校准温度。"""
    from advisor.evals.routing import run_routing_eval
    svc = _service()
    run = svc.deps.repo.get_eval(run_routing_eval(svc.deps))
    typer.echo(f"准确率 {run['accuracy']}，深研召回 {run['deep_recall']}，拒判率 {run['abstain_rate']}，"
               f"建议温度 {run['calibration'].get('best_temperature')}")


@eval_app.command("update")
def eval_update():
    """持续更新：已重新研究的订阅提醒里，受影响结论是否被修正、没受影响的是否保留。"""
    from advisor.evals.update import METRICS, run_update_eval
    svc = _services()
    run = svc.deps.repo.get_eval(run_update_eval(svc.deps))
    typer.echo(f"{run['run_id']}：{run['case_count']} 个案例（{run['labeled']} 个有人工金标）")
    for k, label in METRICS.items():
        v = run["update_summary"][k]
        typer.echo(f"  {label}：{'—' if v is None else f'{v:.0%}'}")


@eval_app.command("compare")
def eval_compare(routes: str = "standard,deep", case: list[str] = typer.Option(None, help="只跑指定用例 id")):
    """同一问题、同一 as_of 下对照单 Agent 与多专家。"""
    from advisor.evals.compare import load_cases, run_compare
    svc = _service()
    cases = [c for c in load_cases() if not case or c["id"] in case]
    run = svc.deps.repo.get_eval(run_compare(svc, cases, routes.split(",")))
    for r in run["results"]:
        m = r.get("metrics") or {}
        typer.echo(f"{r['case']:<12} {r['route']:<9} score={m.get('score')} tokens={m.get('tokens')} {r.get('error') or ''}")
    typer.echo(run["summary"]["verdict"]["text"])


rsi_app = typer.Typer(help="RSI 受控自进化：collect → propose → evaluate → approve → release / rollback")
app.add_typer(rsi_app, name="rsi")


def _rsi():
    return _services().rsi


def _show_run(run) -> None:
    typer.echo(f"{run.run_id} [{run.scenario}·{run.status}] {run.change_reason}")
    for g in run.gates:
        typer.echo(f"  {'✓' if g.passed else '✗'} {g.label}：{g.detail}")
    if run.reject_reason and run.status in ("rejected", "rolled_back"):
        typer.echo(f"  拒绝原因：{run.reject_reason}")


@rsi_app.command("collect")
def rsi_collect(actor: str = "owner"):
    """① 从质询裁决、核验结果、路由评测、搜索记录里收集坏案例。"""
    added = _rsi().collect(actor)
    typer.echo("新增坏案例：" + "，".join(f"{k}×{v}" for k, v in added.items()))


@rsi_app.command("propose")
def rsi_propose(scenario: str = typer.Argument(..., help="S1 经验卡 / S2 路由参数 / S3 检索模板"),
                issue: str = typer.Option(None, help="指定坏案例 id"), actor: str = "owner"):
    """② 针对一个坏案例生成一个候选（只改一个组件）。"""
    from advisor.rsi.proposer import ProposeError
    try:
        _show_run(_rsi().propose(scenario.upper(), issue, actor))
    except ProposeError as e:
        typer.echo(f"没有生成候选：{e}")
        raise typer.Exit(1) from e


@rsi_app.command("evaluate")
def rsi_evaluate(run_id: str, actor: str = "owner"):
    """③④ 与在用版本同台对比，并跑六道门控；全部通过则提交待审，否则拒绝并记账。"""
    _show_run(_rsi().evaluate(run_id, actor, log=typer.echo))


@rsi_app.command("approve")
def rsi_approve(run_id: str, actor: str = "owner", note: str = ""):
    """人工批准（单人阶段会标出自批）。"""
    _show_run(_rsi().approve(run_id, actor, note))


@rsi_app.command("reject")
def rsi_reject(run_id: str, reason: str, actor: str = "owner"):
    _show_run(_rsi().reject(run_id, actor, reason))


@rsi_app.command("release")
def rsi_release(run_id: str, actor: str = "owner"):
    """⑤ 发布：追加新版本资产并启用。"""
    _show_run(_rsi().release(run_id, actor))


@rsi_app.command("rollback")
def rsi_rollback(kind: str = typer.Argument(..., help="lessons / routing / search"), reason: str = typer.Option(...),
                 actor: str = "owner"):
    """一键回滚到上一版本。"""
    r = _rsi().rollback(kind, actor, reason)
    typer.echo(f"{r['kind']} v{r['from']} → v{r['to']}")


@rsi_app.command("status")
def rsi_status():
    """在用版本、坏案例与最近的候选。"""
    runner = _rsi()
    runner.ledger.bootstrap(runner.deps.policy)
    typer.echo("在用版本：" + " · ".join(f"{k} v{runner.ledger.active_version(k)}" for k in ("lessons", "routing", "search")))
    for sc in ("S1", "S2", "S3"):
        issues = runner.ledger.list_issues(sc)
        typer.echo(f"{sc} 坏案例 {len(issues)}（待处理 {sum(i.status == 'open' for i in issues)}）")
    for run in runner.ledger.list_runs(limit=10):
        _show_run(run)


watch_app = typer.Typer(help="事件订阅与增量复核：前提变化时提醒，没有变化不打扰")
app.add_typer(watch_app, name="watch")


@watch_app.command("add")
def watch_add(ticker: str, price_move_pct: float = 10):
    """订阅一只已有档案的股票。"""
    svc = _services()
    d = svc.deps.repo.get_dossier(ticker)
    if d is None:
        typer.echo("还没有这只股票的档案，先做一次研究再订阅")
        raise typer.Exit(1)
    svc.watch.store.subscribe(ticker, d.name, price_move_pct)
    typer.echo(f"已订阅 {d.name}（{ticker}），价格提醒阈值 ±{price_move_pct:g}%")


@watch_app.command("scan")
def watch_scan():
    """扫描全部订阅（可放进 cron 定时执行）。"""
    alerts = _services().watch.scan_all(log=typer.echo)
    for a in alerts:
        typer.echo(f"{a.id} {a.name}：{'、'.join(e.title for e in a.events)}；受影响结论 {len(a.affected)} 条")


@watch_app.command("review")
def watch_review(alert_id: str):
    """带着受影响的结论发起增量复核。"""
    svc = _services()
    task_id = svc.watch.start_review(alert_id, svc.research)
    typer.echo(f"已发起复核任务 {task_id}（在 Web 研究任务页查看进度）")


strategy_app = typer.Typer(help="策略卡与前向模拟盘：只模拟，不交易；晋级须过门控并人工批准")
app.add_typer(strategy_app, name="strategy")


@strategy_app.command("list")
def strategy_list():
    book = _services().strategy
    for v in book.store.versions():
        st = book.stats(v)
        typer.echo(f"{v.ref} [{v.status}] {v.name}：模拟 {st['days']} 天，收益 {st['return_pct']:+.2f}%，"
                   f"最大回撤 {st['max_drawdown_pct']:.2f}%")


@strategy_app.command("step")
def strategy_step(day: str = typer.Option(None, help="推进到哪天，默认今天（只能向前）")):
    """把模拟中的策略推进一天。"""
    _services().strategy.step_all(date.fromisoformat(day) if day else None, log=typer.echo)


@strategy_app.command("submit")
def strategy_submit(card_id: str, version: int, actor: str = "owner"):
    """跑晋级门控。"""
    v = _services().strategy.submit(card_id, version, actor)
    for g in v.gates:
        typer.echo(f"  {'✓' if g.passed else '✗'} {g.label}：{g.detail}")
    typer.echo(f"{v.ref} → {v.status}")


@strategy_app.command("approve")
def strategy_approve(card_id: str, version: int, actor: str = "owner", note: str = ""):
    v = _services().strategy.approve(card_id, version, actor, note)
    typer.echo(f"{v.ref} 已晋级" + ("（自批）" if v.approvals[-1]["self_approved"] else ""))


@strategy_app.command("rollback")
def strategy_rollback(card_id: str, reason: str = typer.Option(...), actor: str = "owner"):
    v = _services().strategy.rollback(card_id, actor, reason)
    typer.echo(f"{card_id} 当前生效：{v.ref}（{v.status}）")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000):
    """启动 API（若已构建前端，同时提供 Web 界面）。"""
    import uvicorn

    from advisor.api.app import create_app
    uvicorn.run(create_app(), host=host, port=port)


@app.command()
def mcp():
    """以 MCP（stdio）暴露只读 Skill。"""
    from advisor.mcp_server import build_server
    build_server().run()


if __name__ == "__main__":
    app()
