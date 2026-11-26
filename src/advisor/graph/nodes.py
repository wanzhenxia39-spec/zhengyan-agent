"""主图节点（共用 + 单 Agent 标准研究）。模型提议，Harness 许可，核验器检查，提交器在复验授权后写入档案。"""
import re
from datetime import date, datetime, timezone

from langgraph.types import interrupt

from advisor.contracts import Claim, Dossier, EvidenceCard, QualityResult
from advisor.contracts.deliberation import RouteDecision
from advisor.evidence.verifier import verify_claims
from advisor.graph.deps import Deps
from advisor.graph.gather import gather_web
from advisor.graph.report import render_report
from advisor.graph.state import ResearchState
from advisor.harness import Budget, BudgetExceeded, HarnessDenied, SkillFailed, TaskCancelled
from advisor.harness.egress import EgressGuard
from advisor.routing import decide_route, should_escalate
from advisor.rsi import render_lessons
from advisor.skills.research.earnings_review import (
    DRAFT_SYSTEM, INTAKE_SYSTEM, INTENT_QUESTIONS, QUERY_SYSTEM, DraftOutput, IntakeOut, QueryPlan, derive_metrics,
    draft_user_prompt,
)

_CODE = re.compile(r"(?<!\d)([036]\d{5}|[48]\d{5}|92\d{4})(?!\d)")
_RISK = re.compile(r"风险|负面|下滑|质疑|问题|处罚|诉讼|减持|下调|反方")
MIN_VERIFIED_FACTS = 3

# 执行过程里给用户看的说法（不出现内部术语）
INTENT_LABEL = {"research": "研究分析", "explain": "解释说明", "trade_execution": "交易指令（只研究，不执行交易）", "other": "其他"}
ROUTE_LABEL = {"quick": "快查", "standard": "标准研究", "deep": "争议深研"}
ROUTE_SOURCE_LABEL = {"user": "你指定的", "rule": "按规则判断", "model": "系统根据问题判断", "abstain": "系统拿不准，选了更稳妥的方式",
                      "escalation": "中途发现争议较多，升级", "fallback": "系统判断失败，按默认方式"}
ROLE_LABEL = {"reason": "深度推理模型", "draft": "快速生成模型", "classify": "快速判断模型"}
GATE_LABEL = {"pass": "质量检查通过", "partial": "质量检查：证据不足的部分标为未完成，其余保留",
              "need_more": "质量检查：证据不够，再补充搜索一轮", "escalate": "质量检查：争议较多，升级为多专家深研"}
DOSSIER_STATUS_LABEL = {"committed": "完整结论", "partial": "部分结论"}


def _cards(state: ResearchState, ids: list[str] | None = None) -> list[EvidenceCard]:
    ev = state.get("evidence", {})
    keys = ids if ids is not None else list(ev)
    return [EvidenceCard.model_validate(ev[i]) for i in keys if i in ev]


def _dump(cards: list[EvidenceCard]) -> dict[str, dict]:
    return {c.id: c.model_dump(mode="json") for c in cards}


def lesson_query(question: str, cards: list[EvidenceCard]) -> str:
    """经验卡召回文本：问题 + 证据里出现的指标名。"""
    return question + " " + " ".join({m.name for c in cards for m in c.metrics})


def dossier_key(state: ResearchState) -> str:
    ns = state.get("namespace")
    return f"{ns}:{state['ticker']}" if ns else state["ticker"]


class Nodes:
    def __init__(self, deps: Deps):
        self.d = deps
        self.guard = EgressGuard(
            deps.policy.egress.get("sensitive_patterns", []), deps.policy.egress.get("trade_intent_patterns", [])
        )

    # ---------- 工具 ----------
    def _h(self, state: ResearchState, node: str):
        budget = Budget.from_dict(state["budget"])
        route = state.get("route") or "quick"
        return self.d.harness(state["task_id"], route, date.fromisoformat(state["as_of"]), budget, node=node,
                              task_scoped_cache=True), budget

    def _event(self, state: ResearchState, node: str, msg: str) -> None:
        self.d.repo.push_event(state["task_id"], node, msg)

    # ---------- L0：任务识别 ----------
    def intake(self, state: ResearchState) -> dict:
        q = state["question"]
        if not state.get("budget"):
            state = {**state, "budget": Budget(limits=self.d.policy.route("quick").budget).to_dict()}
        h, budget = self._h(state, "intake")
        code = state.get("ticker")
        if not code and (m := _CODE.search(q)):
            code = m.group(1)
        out = None
        if self.d.policy.intake.get("classifier", "llm") == "small" and h.decision_client is not None:
            try:
                out = self._intake_small(h, q, code)
            except TaskCancelled:
                raise
            except Exception:  # 小模型不可用不致命：退回大模型
                out = None
        if out is None:
            try:
                out = h.llm("classify", INTAKE_SYSTEM, q, IntakeOut, purpose="intake")
            except TaskCancelled:
                raise
            except Exception as e:  # 识别失败不致命：退回规则
                self._event(state, "intake", f"自动识别失败，改用规则识别：{e}")
                out = IntakeOut()
        if not code and out.ticker and _CODE.fullmatch(out.ticker):
            code = out.ticker
        intent = "trade_execution" if self.guard.has_trade_intent(q) else out.intent
        sensitive = bool(self.guard.find_sensitive(q))
        upd = {
            "ticker": code, "company_name": out.company_name or "", "intent": intent, "focus": out.focus,
            "sensitive": sensitive, "budget": budget.to_dict(), "iteration": 0, "status": "running",
        }
        if not code:
            upd.update(status="failed", error="未能识别 A 股代码，请在问题中写明 6 位代码（如 600519）")
        self._event(state, "intake", f"股票 {code or '未识别'}{'（' + out.company_name + '）' if out.company_name else ''}，"
                                     f"问题类型：{INTENT_LABEL.get(intent, intent)}" + ("；问题里含个人信息，已脱敏" if sensitive else ""))
        return upd

    def _intake_small(self, h, q: str, code: str | None) -> IntakeOut | None:
        """小模型路径：意图由决策小模型四选一；代码靠正则或已有档案的简称；关注点按关键词抽取。
        识别不到代码时返回 None，交给大模型（它能从"茅台"这类简称推出代码）。"""
        known = {d["ticker"]: d.get("name") or "" for d in self.d.repo.list_dossiers() if d.get("ticker")}
        if not code:
            code = next((t for t, n in known.items() if n and n in q), None)
            if not code:
                return None
        probs = h.decide(q, INTENT_QUESTIONS, purpose="intake_small")["intent"]
        words = [w for w in self.d.policy.intake.get("focus_keywords", []) if w in q]
        words = [w for w in words if not any(w != o and w in o for o in words)]   # 去掉被更长词包含的
        return IntakeOut(company_name=known.get(code) or None, ticker=code, intent=max(probs, key=probs.get),
                         focus="、".join(words)[:20])

    def authorize(self, state: ResearchState) -> dict:
        notes = []
        if state.get("intent") == "trade_execution":
            notes.append("本系统仅做研究与模拟，不执行任何买卖或资金动作；以下只解释事实与情景。")
        if state.get("sensitive"):
            decision = interrupt({
                "type": "consent",
                "message": "问题中包含个人财务/账户信息。当前不做个人情境分析：这些信息会被脱敏，不会发往搜索，"
                           "也不会用于结论。是否继续只做公开信息研究？",
            })
            if not (isinstance(decision, dict) and decision.get("approve")):
                self._event(state, "authorize", "用户拒绝，任务停止")
                return {"status": "cancelled"}
            notes.append("问题中的个人信息已脱敏，本次只做公开信息研究，不构成个性化建议。")
        self._event(state, "authorize", "检查通过：只做公开信息研究，不涉及交易")
        return {"boundary_notes": notes}

    # ---------- L1：双轴路由（任务轴 + 模型轴） ----------
    def route(self, state: ResearchState) -> dict:
        h, budget = self._h(state, "route")
        cfg = self.d.rsi.routing(self.d.policy.routing) if self.d.rsi else self.d.policy.routing
        decision = decide_route(h, state["question"], state.get("intent", "research"),
                                state.get("route_requested", "auto"), cfg)
        rp = self.d.policy.route(decision.route)
        budget = Budget(limits=rp.budget, used=budget.used, started_at=budget.started_at)
        self.d.repo.save_working(state["task_id"], "routing", "decision", decision.model_dump(mode="json"))
        how = ROUTE_SOURCE_LABEL.get(decision.source, "")
        self._event(state, "route", f"采用「{ROUTE_LABEL[decision.route]}」{'（' + how + '）' if how else ''}，"
                                    f"使用{ROLE_LABEL.get(rp.llm_role, rp.llm_role)}")
        return {"route": decision.route, "routing": decision.model_dump(mode="json"), "budget": budget.to_dict()}

    # ---------- 计划 ----------
    def plan(self, state: ResearchState) -> dict:
        h, budget = self._h(state, "plan")
        quick = state["route"] == "quick"
        limit = 2 if quick else 3
        name = state.get("company_name") or state["ticker"]
        if state.get("iteration", 0) == 0:
            try:
                plan = h.llm("draft", QUERY_SYSTEM, f"公司：{name}（{state['ticker']}）\n关注：{state.get('focus') or '最新业绩'}",
                             QueryPlan, purpose="plan_queries")
                queries = plan.queries
            except TaskCancelled:
                raise
            except Exception as e:
                self._event(state, "plan", f"查询规划失败，使用默认查询：{e}")
                queries = []
            queries = queries or [f"{name} 业绩", f"{name} 行业 竞争", f"{name} 风险"]
        else:
            queries = list((state.get("draft") or {}).get("search_gaps", []))
        done = set(state.get("searched", []))
        clean = []
        for q in queries:
            q = re.sub(r"\s+", " ", q).strip()[:40]
            if len(q) < 2 or q in done or self.guard.find_sensitive(q):
                continue
            clean.append(q)
        clean = clean[:limit]
        if state.get("iteration", 0) == 0 and not any(_RISK.search(q) for q in clean):
            clean = clean[: limit - 1] + [f"{name} 风险 质疑"]   # 反证：至少一条风险/负面查询
        self.d.repo.save_working(state["task_id"], "plan", f"round{state.get('iteration', 0) + 1}", clean)
        self._event(state, "plan", f"第 {state.get('iteration', 0) + 1} 轮要搜索：{'；'.join(clean) or '无'}")
        return {"queries": clean, "budget": budget.to_dict()}

    # ---------- L3：结构化取数与计算 + 工作记忆 ----------
    def collect(self, state: ResearchState) -> dict:
        if state.get("statement_ids"):
            return {}                      # 补证轮次或升级深研：复用已取的事实快照
        h, budget = self._h(state, "collect")
        as_of = date.fromisoformat(state["as_of"])
        code = state["ticker"]
        upd: dict = {"evidence": {}, "unknowns_sys": []}
        try:
            st = h.call("financials.statements", code=code, as_of=as_of, periods=12)
        except (SkillFailed, HarnessDenied, BudgetExceeded) as e:
            self._event(state, "collect", f"财报取数失败：{e}")
            return {"status": "failed", "error": f"财报取数失败：{e}", "budget": budget.to_dict()}
        upd["evidence"].update(_dump(st.cards))
        upd["statement_ids"] = [c.id for c in st.cards]
        name = state.get("company_name") or ""
        if name and st.name not in name and name not in st.name:
            upd["boundary_notes"] = [f"用户提到的“{name}”与代码 {code} 对应的“{st.name}”不一致，以代码为准"]
        upd["company_name"] = st.name
        calc = derive_metrics(h, st.cards, self.d.factory, as_of)
        for skill, key, label in (("market.daily", "market_ids", "行情"), ("valuation.snapshot", "calc_extra", "估值"),
                                  ("announcements.list", "announcement_ids", "公告")):
            try:
                out = h.call(skill, code=code, as_of=as_of)
                upd["evidence"].update(_dump(out.cards))
                if key == "calc_extra":
                    calc += out.cards
                else:
                    upd[key] = [c.id for c in out.cards]
            except (SkillFailed, HarnessDenied, BudgetExceeded) as e:
                upd["unknowns_sys"].append(f"{label}数据缺失：{e}")
                if key != "calc_extra":
                    upd[key] = []
        upd["evidence"].update(_dump(calc))
        upd["calc_ids"] = [c.id for c in calc]
        for c in _cards({"evidence": upd["evidence"]}):
            self.d.repo.put_evidence(c)
        upd["prior"] = self._load_prior(state)
        upd["budget"] = budget.to_dict()
        self._event(state, "collect", f"读取{st.name}财报 {len(st.cards)} 期、公告 {len(upd['announcement_ids'])} 条，算出指标 {len(calc)} 组"
                                      + (f"；载入上一版档案 v{upd['prior']['version']} 用于对照" if upd["prior"] else ""))
        return upd

    def _load_prior(self, state: ResearchState) -> dict | None:
        prev = self.d.repo.get_dossier(dossier_key(state))
        if prev is None:
            return None
        claims = [{"kind": c.kind, "text": c.text} for c in prev.claims
                  if c.status == "verified" and c.kind in ("fact", "inference")][:12]
        return {"version": prev.version, "as_of": prev.as_of.isoformat(), "claims": claims,
                "triggers": [t.condition for t in prev.review_triggers], "focus": state.get("review_focus", [])}

    # ---------- 搜索子系统 ----------
    def search(self, state: ResearchState) -> dict:
        h, budget = self._h(state, "search")
        res = gather_web(h, self.d, state.get("queries", []), date.fromisoformat(state["as_of"]), state["route"],
                         max_fetch=int(self.d.policy.search.get("max_fetch_per_round", 4)),
                         log=lambda m: self._event(state, "search", m))
        nb = sum(c.level == "B" for c in res.cards)
        self._event(state, "search", f"搜索 {len(res.searched)} 次，{res.hits} 条结果，合并转载后 {res.clusters} 件事；"
                                     f"读取原文 {res.fetched} 篇，可信来源 {nb} 条、仅作线索 {len(res.cards) - nb} 条")
        return {"evidence": _dump(res.cards), "searched": res.searched, "unknowns_sys": res.unknowns, "budget": budget.to_dict()}

    # ---------- L2：单 Agent 研究员起草 ----------
    def draft(self, state: ResearchState) -> dict:
        h, budget = self._h(state, "draft")
        quick = state["route"] == "quick"
        all_cards = _cards(state)
        statements = sorted(_cards(state, state.get("statement_ids", [])), key=lambda c: c.metrics[0].period if c.metrics else "", reverse=True)[:5]
        web = sorted([c for c in all_cards if c.source_type == "web"], key=lambda c: (c.level, -(c.rerank_score or 0)))
        web = [c for c in web if c.level == "B"] + [c for c in web if c.level == "C"][:10]
        context = (statements + _cards(state, state.get("calc_ids", [])) + _cards(state, state.get("market_ids", []))
                   + _cards(state, state.get("announcement_ids", []))[:15] + web)
        role = self.d.policy.route(state["route"]).llm_role
        lessons = self.d.rsi.lessons(lesson_query(state["question"], context)) if self.d.rsi else []
        if lessons:
            self._event(state, "draft", f"参考了 {len(lessons)} 条以往经验（{', '.join(c.id for c in lessons)}），只作方法提示，不作为证据")
        try:
            out = h.llm(role, DRAFT_SYSTEM, draft_user_prompt(state["question"], state.get("company_name", ""), state["ticker"],
                        date.fromisoformat(state["as_of"]), context, quick, state.get("prior"), render_lessons(lessons)),
                        DraftOutput, purpose="draft")
        except TaskCancelled:
            raise
        except Exception as e:
            self._event(state, "draft", f"起草失败：{e}")
            return {"status": "failed", "error": f"起草失败：{e}", "budget": budget.to_dict()}
        claims = [Claim(id=f"c{i + 1}", text=c.text, kind=c.kind, evidence_ids=c.evidence_ids).model_dump(mode="json")
                  for i, c in enumerate(out.claims)]
        self.d.repo.save_working(state["task_id"], "draft", f"round{state.get('iteration', 0) + 1}", out.model_dump(mode="json"))
        self._event(state, "draft", f"写出 {len(claims)} 条结论，{len(out.unknowns)} 个问题暂时无法确定")
        return {"draft": out.model_dump(mode="json"), "claims": claims, "budget": budget.to_dict(),
                "lessons_used": [f"{c.id} r{c.rev}" for c in lessons]}

    # ---------- 独立核验 ----------
    def verify(self, state: ResearchState) -> dict:
        evidence = {c.id: c for c in _cards(state)}
        claims = verify_claims([Claim.model_validate(c) for c in state.get("claims", [])], evidence,
                               date.fromisoformat(state["as_of"]))
        counts = {s: sum(c.status == s for c in claims) for s in ("verified", "disputed", "rejected")}
        self._event(state, "verify", f"逐条对照数据核对结论：成立 {counts['verified']}，存疑 {counts['disputed']}，不成立 {counts['rejected']}")
        return {"claims": [c.model_dump(mode="json") for c in claims]}

    # ---------- 质量门控（规则）+ 检查点升级 ----------
    def quality_gate(self, state: ResearchState) -> dict:
        claims = [Claim.model_validate(c) for c in state.get("claims", [])]
        verified_facts = sum(c.status == "verified" and c.kind == "fact" for c in claims)
        disputed = [c for c in claims if c.status == "disputed"]
        rejected = [c for c in claims if c.status == "rejected"]
        draft = state.get("draft") or {}
        gaps = [f"复核：{c.text[:60]}" for c in disputed] + list(draft.get("search_gaps", []))
        rp = self.d.policy.route(state["route"])
        budget = Budget.from_dict(state["budget"])
        notes = [] if state.get("calc_ids") else ["缺少同口径派生指标"]
        weak = disputed or verified_facts < MIN_VERIFIED_FACTS or notes
        upd: dict = {}
        if weak and should_escalate(state.get("routing") or {}, len(disputed), len(draft.get("dissents", [])), self.d.policy.routing):
            decision = "escalate"
            routing = RouteDecision.model_validate(state["routing"])
            routing = routing.model_copy(update={
                "route": "deep", "source": "escalation", "escalated_from": "standard",
                "reasons": routing.reasons + [f"质量门控检查点：存疑 {len(disputed)}、反方观点 {len(draft.get('dissents', []))}，升级到争议深研"],
            })
            deep = self.d.policy.route("deep")
            upd.update(route="deep", escalated=True, routing=routing.model_dump(mode="json"),
                       budget=Budget(limits=deep.budget, used=budget.used, started_at=budget.started_at).to_dict())
        elif weak and state.get("iteration", 0) < rp.max_iterations and budget.remaining("search_calls") > 0 and draft.get("search_gaps"):
            decision = "need_more"
            upd["iteration"] = state.get("iteration", 0) + 1
        else:
            decision = "partial" if weak else "pass"
        q = QualityResult(decision="partial" if decision == "escalate" else decision,
                          verified=sum(c.status == "verified" for c in claims),
                          disputed=len(disputed), rejected=len(rejected), gaps=gaps, notes=notes)
        upd["quality"] = q.model_dump(mode="json") | {"next": decision}
        self._event(state, "quality_gate", f"{GATE_LABEL[decision]}（核实的事实 {verified_facts} 条，存疑 {len(disputed)} 条）")
        return upd

    # ---------- 提交：复验授权；高后果未解争议需人工复核 ----------
    def commit(self, state: ResearchState) -> dict:
        if self.d.repo.is_cancel_requested(state["task_id"]):
            return {"status": "cancelled"}
        delib = state.get("deliberation")
        boundary = []
        if delib and delib.get("needs_human_review"):
            open_items = [ch["text"] for ch in delib.get("challenges", [])
                          if any(r["challenge_id"] == ch["id"] and r["verdict"] == "unresolved" and r["severity"] == "high"
                                 for r in delib.get("rulings", []))]
            decision = interrupt({
                "type": "review",
                "message": "存在高后果且未解决的争议。确认后将以“部分结论”提交（争议保留在档案中）；拒绝则不提交。",
                "items": open_items,
            })
            if not (isinstance(decision, dict) and decision.get("approve")):
                self._event(state, "commit", "人工复核未通过，档案未提交")
                return {"status": "cancelled"}
            boundary.append("存在未解决的高后果争议，经人工确认以部分结论提交。")
        draft = state["draft"]
        quality = QualityResult.model_validate(state["quality"])
        key = dossier_key(state)
        parent = self.d.repo.latest_dossier_version(key)
        claims = [Claim.model_validate(c) for c in state["claims"]]
        used = {i for c in claims for i in c.evidence_ids}
        clue_ids = sorted(i for i, c in state.get("evidence", {}).items() if c["source_type"] == "web")
        status = "committed" if quality.decision == "pass" and not boundary else "partial"
        dossier = Dossier(
            key=key, version=(parent or 0) + 1, parent_version=parent, ticker=state["ticker"],
            name=state.get("company_name", ""), as_of=date.fromisoformat(state["as_of"]), question=state["question"],
            route=state["route"], status=status, summary=draft.get("summary", ""), claims=claims,
            unknowns=list(dict.fromkeys(draft.get("unknowns", []) + state.get("unknowns_sys", []))),
            dissents=draft.get("dissents", []), review_triggers=draft.get("review_triggers", []),
            evidence_ids=sorted(used | set(state.get("calc_ids", [])) | set(state.get("statement_ids", [])[:5])
                                | set(state.get("market_ids", [])) | set(clue_ids)),
            quality=quality, boundary_notes=state.get("boundary_notes", []) + boundary, task_id=state["task_id"],
            created_at=datetime.now(timezone.utc), routing=state.get("routing"), deliberation=delib,
            prior_review=draft.get("prior_review", []), clue_ids=clue_ids,
            rsi_versions=self.d.rsi.versions() if self.d.rsi else {},
            lessons_used=sorted(set(state.get("lessons_used", [])
                                    + [x for r in (delib or {}).get("team", []) for x in r.get("lessons", [])])),
        )
        evidence = {c.id: c for c in _cards(state)}
        report = render_report(dossier, evidence, Budget.from_dict(state["budget"]))
        dossier = dossier.model_copy(update={"report_md": report})
        self.d.repo.insert_dossier(dossier)
        self._event(state, "commit", f"已保存为档案 v{dossier.version}（{DOSSIER_STATUS_LABEL.get(dossier.status, dossier.status)}）")
        return {"dossier_key": key, "version": dossier.version, "report_md": report, "status": "done"}
