"""订阅扫描与增量复核。

扫描：以今天为时点重新取财报、公告、行情，与档案当时的证据对比，找出「前提变化」：
新报告期、档案时点之后的公告、超过阈值的价格变化、被触发的复核条件。
依赖传播：主张 → 证据 → 报告期 / 行情时点。只把受影响的旧结论列为「待复核」，档案本身不改。
增量复核：带着受影响的结论发起一次标准研究，生成新版本，并在报告里逐条复核旧结论。
"""
import hashlib
import uuid
from datetime import date, datetime, timezone

from advisor.contracts import Dossier, EvidenceCard, ResearchRequest
from advisor.evidence import fact_value, metric_facts, report_periods
from advisor.graph.deps import Deps
from advisor.harness import Budget, BudgetExceeded, HarnessDenied, SkillFailed
from advisor.watch.models import EVENT_LABEL, AffectedClaim, Alert, WatchEvent
from advisor.watch.store import WatchStore

TRIGGER_WORDS = {
    "new_report": ("财报", "季报", "年报", "半年报", "业绩", "报告期", "营收", "利润"),
    "announcement": ("公告", "回购", "减持", "增持", "分红", "监管", "处罚", "诉讼", "重组"),
    "price_move": ("股价", "价格", "估值", "PE", "市盈率", "回撤", "下跌", "上涨"),
}
PRICE_SOURCES = ("market.daily", "valuation.snapshot")


class WatchError(ValueError):
    pass


class Watcher:
    def __init__(self, deps: Deps, store: WatchStore):
        self.deps = deps
        self.store = store

    # ---------- 扫描 ----------
    def scan(self, ticker: str, today: date | None = None) -> Alert | None:
        """有变化返回提醒（同一批变化只提醒一次），没有变化返回 None。"""
        today = today or date.today()
        repo = self.deps.repo
        d = repo.get_dossier(ticker)
        if d is None:
            raise WatchError(f"{ticker} 还没有档案，先做一次研究再订阅")
        sub = self.store.get_sub(ticker)
        threshold = sub.price_move_pct if sub else 10
        evidence = {c.id: c for c in repo.get_evidence(d.evidence_ids + [i for c in d.claims for i in c.evidence_ids])}
        h = self.deps.harness(f"watch_{ticker}", "quick", today, Budget(limits=self.deps.policy.route("quick").budget),
                              node="watch", principal="watcher")
        events, affected, notes = [], {}, []
        for detect in (self._new_report, self._announcements, self._price_move):
            try:
                found = detect(h, d, evidence, today, threshold)
            except (SkillFailed, HarnessDenied, BudgetExceeded) as e:
                notes.append(f"{detect.__name__.strip('_')} 取数失败：{e}")
                continue
            if found:
                event, claims, cards = found
                events.append(event)
                for c in cards:
                    repo.put_evidence(c)
                for a in claims:
                    affected.setdefault(a.claim_id, a)
        events += self._triggers(d, {e.kind for e in events})
        if not events:
            self.store.mark_scanned(ticker, "无变化" + (f"（{'；'.join(notes)}）" if notes else ""))
            return None
        alert, created = self.store.add_alert(Alert(
            id="al_" + uuid.uuid4().hex[:8], ticker=ticker, name=d.name, dossier_key=d.key, dossier_version=d.version,
            fingerprint=_fingerprint(d, events), events=events, affected=list(affected.values()),
            created_at=datetime.now(timezone.utc), note="；".join(notes),
        ))
        self.store.mark_scanned(ticker, alert_summary(alert, created))
        return alert

    def scan_all(self, today: date | None = None, log=lambda m: None) -> list[Alert]:
        out = []
        for sub in self.store.list_subs():
            try:
                alert = self.scan(sub.ticker, today)
            except WatchError as e:
                log(f"{sub.ticker}：{e}")
                continue
            log(f"{sub.name or sub.ticker}（{sub.ticker}）：{alert_summary(alert) if alert else '没有变化，不提醒'}")
            if alert:
                out.append(alert)
        return out

    def _new_report(self, h, d: Dossier, evidence: dict[str, EvidenceCard], today: date, _):
        st = h.call("financials.statements", code=d.ticker, as_of=today, periods=5)
        latest_new = max((m.period[:10] for c in st.cards for m in c.metrics), default="")
        latest_old = max(report_periods(d.evidence_ids, evidence), default="")
        if not latest_old or latest_new <= latest_old:
            return None
        card = next(c for c in st.cards if any(m.period[:10] == latest_new for m in c.metrics))
        claims = [AffectedClaim(claim_id=c.id, text=c.text, reason=f"依赖的报告期 {max(p)} 已有更新的 {latest_new}")
                  for c in d.claims if c.status == "verified" and (p := report_periods(c.evidence_ids, evidence))
                  and max(p) < latest_new]
        event = WatchEvent(kind="new_report", title=f"{latest_new} 报告期财报已披露", date=card.published_at.date().isoformat()
                           if card.published_at else None, detail=f"档案用的是 {latest_old}", evidence_ids=[card.id])
        return event, claims, [card]

    def _announcements(self, h, d: Dossier, evidence, today: date, _):
        days = min(max((today - d.as_of).days, 7), 400)
        out = h.call("announcements.list", code=d.ticker, as_of=today, lookback_days=days)
        new = [c for c in out.cards if c.published_at and c.published_at.date() > d.as_of]
        if not new:
            return None
        titles = "；".join(c.title for c in new[:3])
        event = WatchEvent(kind="announcement", title=f"档案时点后新增 {len(new)} 条公告", detail=titles,
                           date=max(c.published_at.date() for c in new).isoformat(), evidence_ids=[c.id for c in new])
        return event, [], new

    def _price_move(self, h, d: Dossier, evidence, today: date, threshold: float):
        old = fact_value(metric_facts([c for c in evidence.values() if c.skill == "market.daily"]), "close")
        out = h.call("market.daily", code=d.ticker, as_of=today)
        new = fact_value(metric_facts(out.cards), "close")
        if not old or new is None:
            return None
        pct = float((new / old - 1) * 100)
        if abs(pct) < threshold:
            return None
        claims = [AffectedClaim(claim_id=c.id, text=c.text, reason=f"依赖档案时点的行情/估值，价格已变化 {pct:+.1f}%")
                  for c in d.claims if c.status == "verified"
                  and any((e := evidence.get(i)) and e.skill in PRICE_SOURCES for i in c.evidence_ids)]
        event = WatchEvent(kind="price_move", title=f"价格较档案时点变化 {pct:+.1f}%", date=out.cards[0].metrics[0].period[:10],
                           detail=f"{old} → {new}（阈值 ±{threshold:g}%）", evidence_ids=[out.cards[0].id])
        return event, claims, out.cards

    @staticmethod
    def _triggers(d: Dossier, fired: set[str]) -> list[WatchEvent]:
        """档案自己写的复核条件：按关键词与本次变化类型粗匹配，只标「可能触发」，由复核确认。"""
        out = []
        for t in d.review_triggers:
            kinds = [k for k in fired if any(w in t.condition for w in TRIGGER_WORDS[k])]
            if kinds:
                out.append(WatchEvent(kind="trigger", title=t.condition,
                                      detail=f"可能因{'、'.join(EVENT_LABEL[k] for k in kinds)}而触发，复核时确认；{t.reason}"))
        return out

    # ---------- 增量复核 ----------
    def start_review(self, alert_id: str, service) -> str:
        alert = self.store.get_alert(alert_id)
        if alert is None:
            raise WatchError("提醒不存在")
        if alert.status != "open":
            raise WatchError("只有待处理的提醒可以发起复核")
        focus = [a.text for a in alert.affected][:8]
        changes = "；".join(e.title for e in alert.events)
        question = f"{alert.name}（{alert.ticker}）上次研究后有新变化：{changes}。请用新数据重新研究，说明哪些旧结论仍成立、哪些需要修正。"[:480]
        task_id = service.start(ResearchRequest(question=question, ticker=alert.ticker, route="standard"),
                                review_focus=focus)
        self.store.update_alert(alert_id, status="reviewing", review_task_id=task_id)
        return task_id

    def dismiss(self, alert_id: str, note: str) -> None:
        self.store.update_alert(alert_id, status="dismissed", note=note)

    def sync(self) -> None:
        """复核任务结束后回写提醒状态。"""
        for a in self.store.list_alerts(status="reviewing"):
            task = self.deps.repo.get_task(a.review_task_id or "")
            if not task:
                continue
            if task["status"] == "done":
                self.store.update_alert(a.id, status="resolved", resolved_version=(task.get("result") or {}).get("version"))
            elif task["status"] in ("failed", "cancelled"):
                self.store.update_alert(a.id, status="open", review_task_id=None, note=f"复核任务{task['status']}，可重试")


def alert_summary(alert: Alert, created: bool | None = None) -> str:
    """给人看的一句话：哪几类变化、影响几条旧结论。"""
    kinds = "、".join(dict.fromkeys(EVENT_LABEL[e.kind] for e in alert.events))
    head = {True: "有新变化", False: "这批变化已提醒过"}.get(created, "发现变化")
    return f"{head}（{kinds}），影响 {len(alert.affected)} 条旧结论，见下方提醒"


def _fingerprint(d: Dossier, events: list[WatchEvent]) -> str:
    parts = [d.key, str(d.version)] + sorted(f"{e.kind}|{e.title}|{e.date}" for e in events)
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:24]
