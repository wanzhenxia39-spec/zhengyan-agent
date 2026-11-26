"""研究底稿渲染：档案的可读视图。结论都能定位到证据。"""
from advisor.contracts import Dossier, EvidenceCard
from advisor.harness import Budget
from advisor.skills.research.earnings_review import fmt_value

KIND = {"fact": "事实", "inference": "推断", "assumption": "假设", "scenario": "情景"}
BASIS = {"cumulative": "累计", "single_quarter": "单季", "point": "时点", "ratio": "比率", "change": "变化", "ttm": "滚动四季"}
STATUS = {"committed": "已通过质量门控", "partial": "部分结论（含保留与未知）"}
VERDICT = {"retained": "保留", "weakened": "削弱", "invalidated": "失效", "unverifiable": "无法判断"}
RULING = {"upheld": "质询成立", "rejected": "质询不成立", "unresolved": "未决"}
STANCE = {"concede": "承认", "rebut": "反驳", "revise": "修正"}
MODE = {"map_reduce": "并行取证", "debate": "有限对抗", "committee": "投资委员会"}


def _cell(text: str) -> str:
    return text.replace("|", "／").replace("\n", " ")


def render_report(d: Dossier, evidence: dict[str, EvidenceCard], budget: Budget) -> str:
    out = [
        f"# {d.name}（{d.ticker}）研究底稿 v{d.version}",
        "",
        f"> 研究时点 as_of：**{d.as_of}** ｜ 流程：{d.route} ｜ 状态：**{STATUS[d.status]}** ｜ 生成：{d.created_at:%Y-%m-%d %H:%M} UTC",
        ">",
        "> 仅为研究与信息整理，不构成投资建议，不承诺收益，系统不执行任何交易。",
        "",
        f"**研究问题**：{d.question}",
        "",
        "## 结论摘要",
        "",
        d.summary or "（无）",
    ]
    if d.boundary_notes:
        out += ["", "## 边界说明", ""] + [f"- {n}" for n in d.boundary_notes]
    if d.routing:
        r = d.routing
        probs = "，".join(f"{k} {v:.2f}" for k, v in (r.get("calibrated") or {}).items())
        out += ["", f"**路由**：{r['route']}（来源 {r['source']}{'，' + probs if probs else ''}"
                    f"{'，由 ' + r['escalated_from'] + ' 升级' if r.get('escalated_from') else ''}）"
                    + (f"；{'；'.join(r.get('reasons', []))}" if r.get("reasons") else "")]
    if d.rsi_versions:
        label = {"lessons": "经验库", "routing": "路由参数", "search": "检索模板"}
        vers = " · ".join(f"{label[k]} {'v' + str(v) if v else '基线'}" for k, v in d.rsi_versions.items() if k in label)
        out += ["", f"**方法版本**：{vers}" + (f"；召回经验卡 {', '.join(d.lessons_used)}（方法提示，非证据）" if d.lessons_used else "")]
    if d.prior_review:
        out += ["", "## 与上一版本对照", "", "| 上一版本结论 | 判断 | 理由 |", "|---|---|---|"]
        out += [f"| {_cell(p.prior_claim)} | {VERDICT[p.verdict]} | {_cell(p.reason)} |" for p in d.prior_review]

    ok = [c for c in d.claims if c.status == "verified"]
    out += ["", "## 已核验主张", "", "| # | 类型 | 主张 | 证据 | 备注 |", "|---|---|---|---|---|"]
    for c in ok:
        refs = " ".join(f"`{i}`({evidence[i].level})" for i in c.evidence_ids if i in evidence) or "—"
        out.append(f"| {c.id} | {KIND[c.kind]} | {_cell(c.text)} | {refs} | {_cell('；'.join(c.verify_notes))} |")

    calc = [evidence[i] for i in d.evidence_ids if i in evidence and evidence[i].source_type == "calc"]
    if calc:
        out += ["", "## 关键指标（确定性计算）", "", "| 指标 | 口径 | 报告期 | 数值 | 说明 |", "|---|---|---|---|---|"]
        for card in calc:
            for m in card.metrics:
                out.append(f"| {m.name} | {BASIS[m.basis]} | {m.period[:10]} | {fmt_value(m)} | {_cell(m.note)} |")

    if d.deliberation:
        dl = d.deliberation
        out += ["", f"## 专家团队与审议（{MODE.get(dl['mode'], dl['mode'])}）", "",
                "| 专家 | 模型角色 | 立场 | 主张（通过/总数） |", "|---|---|---|---|"]
        for t in dl.get("team", []):
            ok = sum(c["status"] == "verified" for c in t["claims"])
            out.append(f"| {t['name']} | {t['model_role']} | {_cell(t.get('stance') or t.get('error') or '—')} | {ok}/{len(t['claims'])} |")
        if dl.get("challenges"):
            out += ["", "**交叉质询与裁决**", ""]
            for ch in dl["challenges"]:
                ruling = next((r for r in dl.get("rulings", []) if r["challenge_id"] == ch["id"]), None)
                out.append(f"- `{ch['id']}` → `{ch['target_claim_id']}`（{ch['kind']}，{ch['severity']}）：{ch['text']}")
                for resp in dl.get("responses", []):
                    if resp["challenge_id"] == ch["id"]:
                        out.append(f"  - 回应（{STANCE[resp['stance']]}）：{resp['text']}")
                if ruling:
                    out.append(f"  - 主席：**{RULING[ruling['verdict']]}** —— {ruling['reason']}")
        if dl.get("committee"):
            out += ["", "**委员会立场**", ""] + [f"- {s['expert']}：{s['position']}" for s in dl["committee"]]

    if d.dissents:
        out += ["", "## 反方观点与反证", ""]
        out += [f"- {x.text}" + (f"（{', '.join(f'`{i}`' for i in x.evidence_ids)}）" if x.evidence_ids else "") for x in d.dissents]

    bad = [c for c in d.claims if c.status in ("disputed", "rejected")]
    if bad:
        out += ["", "## 未通过核验（不作为结论）", ""]
        out += [f"- ~~{c.text}~~ —— {'；'.join(c.verify_notes) or c.status}" for c in bad]

    out += ["", "## 未知与待补证据", ""] + ([f"- {u}" for u in d.unknowns] or ["- （无）"])
    out += ["", "## 下次复核条件", ""] + ([f"- **{t.condition}**：{t.reason}" for t in d.review_triggers] or ["- （无）"])

    clues = sorted((evidence[i] for i in d.clue_ids if i in evidence), key=lambda c: (c.level, -(c.rerank_score or 0)))
    if clues:
        out += ["", "## 新闻/事件线索（分级）", "", "> B 级只说明发生了什么；C 级只是线索，不支撑结论。", ""]
        out += [f"- **{c.level}** {c.published_at.date() if c.published_at else '日期未知'} {c.site_name or ''}："
                f"[{_cell(c.title)}]({c.source_url})" for c in clues[:15]]

    cited = [evidence[i] for i in d.evidence_ids if i in evidence]
    out += ["", "## 证据清单", "", "| ID | 等级 | 类型 | 日期 | 来源 | 标题 |", "|---|---|---|---|---|---|"]
    for c in sorted(cited, key=lambda c: (c.level, c.source_type)):
        title = f"[{_cell(c.title)}]({c.source_url})" if c.source_url else _cell(c.title)
        day = c.published_at.date().isoformat() if c.published_at else "未知"
        out.append(f"| `{c.id}` | {c.level} | {c.source_type} | {day} | {_cell(c.site_name or '')} | {title} |")

    q = d.quality
    used = ", ".join(f"{k}={v:g}" for k, v in budget.used.items())
    out += [
        "", "## 运行信息", "",
        f"- 质量门控：{q.decision}（通过 {q.verified} / 存疑 {q.disputed} / 驳回 {q.rejected}）" + (f"；{'；'.join(q.notes)}" if q.notes else ""),
        f"- 预算使用：{used or '—'}",
        f"- 任务：`{d.task_id}`；上一版本：{d.parent_version or '无'}",
        "- 证据等级：A=结构化财报/行情/公告/系统计算；B=权威网页且有快照；C=线索（不支撑结论）",
    ]
    return "\n".join(out) + "\n"
