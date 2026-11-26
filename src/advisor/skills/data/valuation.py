"""估值快照：按披露日逐日对齐 TTM 净利润与股本，得到时点正确的 PE 区间与倍数情景。完全确定性。"""
import json
import statistics
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel, Field

from advisor.contracts import Metric
from advisor.contracts.skill import Skill, SkillSpec
from advisor.evidence import EvidenceFactory
from advisor.harness.errors import SkillFailed
from advisor.skills.compute.finance import percentile_rank, q, ttm
from advisor.skills.data.ashare import AShareSource
from advisor.skills.data.structured import CardsOut


class ValuationIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    as_of: date
    window_days: int = Field(default=730, ge=180, le=1500)


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _latest(points: list[tuple[date, Decimal]], day: date) -> Decimal | None:
    """points 按披露日升序；返回 day 当天已披露的最新值。"""
    value = None
    for notice, v in points:
        if notice > day:
            break
        value = v
    return value


def build_valuation_skill(source: AShareSource, factory: EvidenceFactory) -> Skill:
    def run(inp: ValuationIn) -> CardsOut:
        income = [r for r in source.income_rows(inp.code)
                  if _d(r.get("NOTICE_DATE")) and _d(r["NOTICE_DATE"]) <= inp.as_of and r.get("PARENT_NETPROFIT") is not None]
        if not income:
            raise SkillFailed("没有可用利润表，无法估值")
        name = income[0].get("SECURITY_NAME_ABBR") or inp.code
        cum = {r["REPORT_DATE"][:10]: Decimal(str(r["PARENT_NETPROFIT"])) for r in income}
        notice = {r["REPORT_DATE"][:10]: _d(r["NOTICE_DATE"]) for r in income}
        ttm_points = sorted(((notice[p], p, v) for p in cum if (v := ttm(cum, p)) is not None), key=lambda x: (x[0], x[1]))
        ttm_points = [(d, v) for d, _, v in ttm_points]
        balance = sorted(
            ((_d(r["NOTICE_DATE"]), r) for r in source.balance_rows(inp.code)
             if _d(r.get("NOTICE_DATE")) and _d(r["NOTICE_DATE"]) <= inp.as_of and r.get("SHARE_CAPITAL")),
            key=lambda x: (x[0], x[1]["REPORT_DATE"]),   # 同日披露多期（如年报+一季报）时按报告期排序
        )
        shares = [(d, Decimal(str(r["SHARE_CAPITAL"]))) for d, r in balance]
        equity = [(d, Decimal(str(r["TOTAL_PARENT_EQUITY"]))) for d, r in balance if r.get("TOTAL_PARENT_EQUITY")]
        if not ttm_points or not shares:
            raise SkillFailed("TTM 净利润或股本不足，无法估值")

        rows = source.daily(inp.code, inp.as_of - timedelta(days=inp.window_days), inp.as_of)
        series = []
        for r in rows:
            day = _d(r.get("date"))
            if day is None or day > inp.as_of or r.get("close") is None:
                continue
            np_ttm, sh = _latest(ttm_points, day), _latest(shares, day)
            if np_ttm is None or sh is None or np_ttm <= 0:
                continue
            series.append((day, Decimal(str(r["close"])) * sh / np_ttm))
        last_day = _d(rows[-1]["date"]) if rows else inp.as_of
        close = Decimal(str(rows[-1]["close"])) if rows else None
        np_now, sh_now, eq_now = _latest(ttm_points, inp.as_of), _latest(shares, inp.as_of), _latest(equity, inp.as_of)
        if close is None or np_now is None or sh_now is None:
            raise SkillFailed("行情或 TTM 缺失，无法估值")
        period = last_day.isoformat()
        mcap = close * sh_now
        metrics = [
            Metric(name="总市值", field="mkt_cap", value=q(mcap), unit="元", period=period, basis="point",
                   note="收盘价×股本（按面值 1 元折算股数）"),
            Metric(name="归母净利润(TTM)", field="np_ttm", value=np_now, unit="元", period=period, basis="ttm",
                   note="本期累计+上年年报-上年同期累计"),
        ]
        if np_now > 0:
            pe_now = mcap / np_now
            metrics.append(Metric(name="市盈率PE(TTM)", field="pe_ttm", value=q(pe_now), unit="倍", period=period, basis="ratio"))
        else:
            pe_now = None
            metrics.append(Metric(name="市盈率PE(TTM)", field="pe_ttm", value=Decimal(0), unit="倍", period=period, basis="ratio",
                                  note="TTM 净利润为负，PE 无意义"))
        if eq_now and eq_now > 0:
            metrics.append(Metric(name="市净率PB(MRQ)", field="pb_mrq", value=q(mcap / eq_now), unit="倍", period=period, basis="ratio"))
        pes = [v for _, v in series]
        if pe_now is not None and len(pes) >= 60:
            lo, mid, hi = min(pes), Decimal(str(statistics.median(pes))), max(pes)
            span_note = f"{series[0][0]}~{series[-1][0]}，{len(pes)} 个交易日"
            metrics += [
                Metric(name="PE(TTM)窗口分位", field="pe_pct", value=percentile_rank(pes, pe_now), unit="%", period=period,
                       basis="ratio", note=span_note),
                Metric(name="PE(TTM)窗口最低", field="pe_min", value=q(lo), unit="倍", period=period, basis="ratio", note=span_note),
                Metric(name="PE(TTM)窗口中位", field="pe_median", value=q(mid), unit="倍", period=period, basis="ratio", note=span_note),
                Metric(name="PE(TTM)窗口最高", field="pe_max", value=q(hi), unit="倍", period=period, basis="ratio", note=span_note),
            ]
            for label, band in (("最低", lo), ("中位", mid), ("最高", hi)):
                metrics.append(Metric(
                    name=f"情景：PE回到窗口{label}时价格变化", field=f"scn_pe_{label}", value=q((band / pe_now - 1) * 100),
                    unit="%", period=period, basis="change", note="假设盈利不变、只改变估值倍数；不是预测",
                ))
        card = factory.make(
            content=json.dumps({"pe_series": [[d.isoformat(), str(q(v))] for d, v in series],
                                "ttm_points": [[d.isoformat(), str(v)] for d, v in ttm_points]}, ensure_ascii=False),
            level="A", source_type="calc", title=f"{name} 估值快照与 PE 区间（确定性计算，截至 {period}）",
            site_name="系统计算", origin_id=f"valuation:{inp.code}:{period}", as_of=inp.as_of,
            published_at=datetime(last_day.year, last_day.month, last_day.day, tzinfo=timezone.utc),
            excerpt="；".join(f"{m.name} {m.value}{m.unit}" for m in metrics[:6]), metrics=metrics,
            caveats=["股数按股本/面值 1 元折算", "历史市值用前复权价格，仅作相对比较",
                     "PE 区间只覆盖窗口期，不代表合理估值", "情景只改变估值倍数，盈利假设不变，不是预测"],
            skill="valuation.snapshot", skill_version="1.0.0",
        )
        return CardsOut(cards=[card])

    return Skill(
        spec=SkillSpec(name="valuation.snapshot", version="1.0.0", category="data", permission="read",
                       description="时点正确的市值、PE(TTM)、PB 与 PE 窗口区间、倍数情景",
                       input_model=ValuationIn, output_model=CardsOut, timeout_s=90,
                       retryable=(ConnectionError, TimeoutError, OSError)),
        run=run,
    )
