"""争议深研子图：编排 → 专家并行首轮（Send）→ 黑板汇合 → 交叉质询 → 回应 → 主席综合 → 独立质量门控。"""
from datetime import date

from langgraph.types import Send

from advisor.contracts import Claim, Dissent, QualityResult
from advisor.contracts.deliberation import Challenge, CommitteeSeat, Deliberation, ExpertResult, Response
from advisor.experts import agent
from advisor.experts.schemas import TeamPlan
from advisor.experts.specs import EXPERTS
from advisor.graph.nodes import GATE_LABEL, MIN_VERIFIED_FACTS, Nodes, _cards
from advisor.graph.state import ResearchState
from advisor.harness import Budget

MODE_LABEL = {"map_reduce": "各自取证后汇总", "debate": "专家互相质疑", "committee": "投资委员会讨论"}


class DeepNodes(Nodes):
    # ---------- 1. 首席编排：按证据缺口召集临时团队 ----------
    def team_plan(self, state: ResearchState) -> dict:
        h, budget = self._h(state, "team_plan")
        cards = _cards(state)
        summary = "；".join(f"{t} {sum(c.source_type == t for c in cards)} 条"
                           for t in ("filing", "calc", "market", "announcement", "web"))
        unknowns = state.get("unknowns_sys", [])
        plan = agent.plan_team(h, self.d, state["question"], f"{state.get('company_name')}（{state['ticker']}）",
                               (state.get("routing") or {}).get("stakes"),
                               summary + (f"；缺口：{'；'.join(unknowns[:3])}" if unknowns else ""))
        self.d.repo.save_working(state["task_id"], "team", "plan", plan.model_dump(mode="json"))
        names = "、".join(EXPERTS[m.expert].name for m in plan.members)
        self._event(state, "team_plan", f"请来 {names}，外加专门挑毛病的反证官；协作方式：{MODE_LABEL.get(plan.mode, plan.mode)}" +
                    ("（标准研究中途发现争议较多，升级而来）" if state.get("escalated") else ""))
        return {"team": plan.model_dump(mode="json"), "budget": budget.to_dict()}

    def dispatch(self, state: ResearchState) -> list[Send]:
        """为每位专家分配子预算并行下发；首轮只给共享事实快照（结构化证据），不给他人结论。"""
        plan = TeamPlan.model_validate(state["team"])
        cfg = self.d.policy.experts
        budget = Budget.from_dict(state["budget"])
        members = [(m.expert, m.questions) for m in plan.members] + [("red_team", ["寻找主要结论的反例、替代解释与风险"])]
        n = len(members)
        alloc = {
            "tokens": max(budget.remaining("tokens") * 0.55 / n, 1),          # 留 45% 给质询与主席
            "search_calls": min(int(cfg.get("search_per_expert", 2)), int(budget.remaining("search_calls") // n)),
            "fetch_calls": min(int(cfg.get("fetch_per_expert", 2)), int(budget.remaining("fetch_calls") // n)),
            "wall_clock_s": budget.limits.get("wall_clock_s", 1800),
        }
        shared = {i: c for i, c in state.get("evidence", {}).items() if c["source_type"] != "web"}
        return [Send("expert_round", {
            "task_id": state["task_id"], "route": state["route"], "as_of": state["as_of"], "ticker": state["ticker"],
            "company": state.get("company_name", ""), "question": state["question"], "expert": key, "questions": qs,
            "shared": shared, "allocation": alloc, "started_at": budget.started_at,
        }) for key, qs in members]

    def expert_round(self, payload: dict) -> dict:
        self.d.repo.push_event(payload["task_id"], f"expert:{payload['expert']}", f"{EXPERTS[payload['expert']].name} 开始独立取证")
        out = agent.run_expert(self.d, payload)
        r = out["expert_results"][0]
        ok = sum(c["status"] == "verified" for c in r["claims"])
        self.d.repo.push_event(payload["task_id"], f"expert:{payload['expert']}",
                               f"{r['name']}：提出 {len(r['claims'])} 条结论，核对成立 {ok} 条；搜索 {len(r['queries'])} 次"
                               + (f"；失败 {r['error']}" if r.get("error") else ""))
        return out

    # ---------- 2. 黑板汇合 ----------
    def blackboard(self, state: ResearchState) -> dict:
        budget = Budget.from_dict(state["budget"])
        for u in state.get("usage", []):
            for k, v in u.items():
                budget.charge(k, v)
        results = [ExpertResult.model_validate(r) for r in state.get("expert_results", [])]
        board = [c for r in results for c in r.claims if c.status == "verified"]
        failed = [r.name for r in results if r.error]
        self._event(state, "blackboard", f"汇总 {len(results)} 位专家核对成立的 {len(board)} 条结论"
                    + (f"（{'、'.join(failed)} 未完成）" if failed else "") + "；几位专家意见相同不等于被独立证实")
        return {"budget": budget.to_dict()}

    def after_blackboard(self, state: ResearchState) -> str:
        return "chair" if TeamPlan.model_validate(state["team"]).mode == "map_reduce" else "cross_exam"

    # ---------- 3. 交叉质询（只针对黑板主张） ----------
    def cross_exam(self, state: ResearchState) -> dict:
        h, budget = self._h(state, "cross_exam")
        h.ctx.principal = "red_team"
        results = [ExpertResult.model_validate(r) for r in state.get("expert_results", [])]
        board = [c for r in results for c in r.claims if c.status == "verified"]
        red = next((r for r in results if r.expert == "red_team"), None)
        evidence = {c.id: c for c in _cards(state)}
        try:
            challenges = agent.cross_examine(h, self.d, board, red, evidence)
        except Exception as e:  # noqa: BLE001  质询失败不阻断，但写入未知
            self._event(state, "cross_exam", f"反证官质疑环节失败：{e}")
            challenges = []
        self.d.repo.save_working(state["task_id"], "challenges", "round1", [c.model_dump(mode="json") for c in challenges])
        high = sum(c.severity == "high" for c in challenges)
        self._event(state, "cross_exam", f"反证官提出 {len(challenges)} 条质疑，其中影响较大的 {high} 条")
        return {"challenges": [c.model_dump(mode="json") for c in challenges], "budget": budget.to_dict()}

    def rebuttal(self, state: ResearchState) -> dict:
        challenges = [Challenge.model_validate(c) for c in state.get("challenges", [])]
        if not challenges:
            return {"responses": []}
        h, budget = self._h(state, "rebuttal")
        results = [ExpertResult.model_validate(r) for r in state.get("expert_results", [])]
        board = [c for r in results for c in r.claims if c.status == "verified"]
        evidence = {c.id: c for c in _cards(state)}
        responses = agent.respond(h, self.d, challenges, board, evidence, date.fromisoformat(state["as_of"]))
        self.d.repo.save_working(state["task_id"], "responses", "round1", [r.model_dump(mode="json") for r in responses])
        tally = {s: sum(r.stance == s for r in responses) for s in ("concede", "rebut", "revise")}
        self._event(state, "rebuttal", f"专家回应质疑：接受 {tally['concede']} 条，反驳 {tally['rebut']} 条，修改结论 {tally['revise']} 条")
        return {"responses": [r.model_dump(mode="json") for r in responses], "budget": budget.to_dict()}

    # ---------- 4. 主席综合 ----------
    def chair(self, state: ResearchState) -> dict:
        h, budget = self._h(state, "chair")
        h.ctx.principal = "chair"
        results = [ExpertResult.model_validate(r) for r in state.get("expert_results", [])]
        board = [c for r in results for c in r.claims if c.status == "verified"]
        challenges = [Challenge.model_validate(c) for c in state.get("challenges", [])]
        responses = [Response.model_validate(r) for r in state.get("responses", [])]
        evidence = {c.id: c for c in _cards(state)}
        as_of = date.fromisoformat(state["as_of"])
        plan = TeamPlan.model_validate(state["team"])
        try:
            out, synth, rulings, adopted = agent.chair(h, self.d, state["question"], state.get("company_name", ""), results,
                                                       board, challenges, responses, evidence, state.get("prior"), as_of)
        except Exception as e:  # noqa: BLE001
            self._event(state, "chair", f"主席汇总失败：{e}")
            return {"status": "failed", "error": f"主席汇总失败：{e}", "budget": budget.to_dict()}
        pool = {c.id: c for c in board}
        pool.update({r.revised_claim.id: r.revised_claim for r in responses if r.revised_claim})
        final = [pool[i] for i in adopted] + synth
        # 被质询成立/承认的主张保留在“未通过核验”，让分歧可见
        blocked_ids = {ch.target_claim_id for ch in challenges} - set(adopted)
        for cid in blocked_ids:
            ruling = next((r for r in rulings for ch in challenges if ch.id == r.challenge_id and ch.target_claim_id == cid), None)
            if ruling and ruling.verdict == "upheld" and cid in pool:
                final.append(pool[cid].model_copy(update={"status": "disputed",
                                                          "verify_notes": pool[cid].verify_notes + [f"反证官质询成立：{ruling.reason}"]}))
        dissents = list(out.dissents) + [
            Dissent(text=f"［未决质询 {ch.id}］{ch.text}", evidence_ids=ch.evidence_ids)
            for ch in challenges for r in rulings if r.challenge_id == ch.id and r.verdict == "unresolved"
        ]
        needs_review = any(r.verdict == "unresolved" and r.severity == "high" for r in rulings)
        delib = Deliberation(
            mode=plan.mode, rationale=plan.rationale, team=results, challenges=challenges, responses=responses,
            rulings=rulings, committee=[CommitteeSeat(expert=s.expert, position=s.position) for s in out.committee],
            adopted_claim_ids=adopted, needs_human_review=needs_review,
        )
        draft = {"summary": out.summary, "dissents": [d.model_dump(mode="json") for d in dissents], "unknowns": out.unknowns,
                 "review_triggers": [t.model_dump(mode="json") for t in out.review_triggers], "search_gaps": [],
                 "prior_review": [p.model_dump(mode="json") for p in out.prior_review]}
        self.d.repo.save_working(state["task_id"], "chair", "output", out.model_dump(mode="json"))
        verdicts = {v: sum(r.verdict == v for r in rulings) for v in ("upheld", "rejected", "unresolved")}
        self._event(state, "chair", f"主席采纳专家结论 {len(adopted)} 条，补充综合判断 {sum(c.status == 'verified' for c in synth)} 条；"
                                    f"对质疑的裁定：成立 {verdicts['upheld']}，不成立 {verdicts['rejected']}，暂无定论 {verdicts['unresolved']}")
        return {"claims": [c.model_dump(mode="json") for c in final], "draft": draft,
                "deliberation": delib.model_dump(mode="json"), "budget": budget.to_dict()}

    # ---------- 5. 独立质量门控（规则，专家不能自批） ----------
    def deep_gate(self, state: ResearchState) -> dict:
        claims = [Claim.model_validate(c) for c in state.get("claims", [])]
        delib = state.get("deliberation") or {}
        verified_facts = sum(c.status == "verified" and c.kind == "fact" for c in claims)
        disputed = sum(c.status == "disputed" for c in claims)
        failed = [r["name"] for r in delib.get("team", []) if r.get("error")]
        notes = [f"专家失败：{'、'.join(failed)}"] if failed else []
        if delib.get("needs_human_review"):
            notes.append("存在高后果未决质询，提交前需人工复核")
        ok = verified_facts >= MIN_VERIFIED_FACTS and not delib.get("needs_human_review") and len(delib.get("adopted_claim_ids", [])) >= 3
        q = QualityResult(decision="pass" if ok else "partial", verified=sum(c.status == "verified" for c in claims),
                          disputed=disputed, rejected=sum(c.status == "rejected" for c in claims),
                          gaps=[r["challenge_id"] for r in delib.get("rulings", []) if r["verdict"] == "unresolved"], notes=notes)
        self._event(state, "deep_gate", f"{GATE_LABEL[q.decision]}（核实的事实 {verified_facts} 条，存疑 {disputed} 条）")
        return {"quality": q.model_dump(mode="json") | {"next": "commit"}}

