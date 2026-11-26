"""结构化数据 Skill：财报、行情、公告。只返回研究时点（as_of）可得的信息，产出 A 级证据卡。"""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from pydantic import BaseModel, Field

from advisor.contracts import EvidenceCard, Metric
from advisor.contracts.skill import Skill, SkillSpec
from advisor.evidence import EvidenceFactory
from advisor.harness.errors import SkillFailed
from advisor.skills.compute.finance import annualized_volatility, max_drawdown, moving_average, price_change, q
from advisor.skills.data.ashare import AShareSource, exchange_prefix

STATEMENT_METRICS = [
    ("营业收入", "OPERATE_INCOME"),
    ("营业总收入", "TOTAL_OPERATE_INCOME"),
    ("归母净利润", "PARENT_NETPROFIT"),
    ("扣非归母净利润", "DEDUCT_PARENT_NETPROFIT"),
    ("经营活动现金流净额", "NETCASH_OPERATE"),
]
BALANCE_METRICS = [
    ("合同负债", "CONTRACT_LIAB"),
    ("存货", "INVENTORY"),
    ("货币资金", "MONETARYFUNDS"),
    ("应收账款", "ACCOUNTS_RECE"),
    ("归母净资产", "TOTAL_PARENT_EQUITY"),
    ("总资产", "TOTAL_ASSETS"),
    ("总负债", "TOTAL_LIABILITIES"),
    ("股本", "SHARE_CAPITAL"),
]
RESTATE_TOLERANCE = timedelta(days=7)


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s[:10]) if s else None


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


class StatementsIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    as_of: date
    periods: int = Field(default=8, ge=5, le=16)


class StatementsOut(BaseModel):
    name: str
    cards: list[EvidenceCard]


class DailyIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    as_of: date
    lookback_days: int = Field(default=400, ge=30, le=800)


class AnnouncementsIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    as_of: date
    lookback_days: int = Field(default=120, ge=7, le=400)
    limit: int = Field(default=30, ge=1, le=100)


class CardsOut(BaseModel):
    cards: list[EvidenceCard]


def build_structured_skills(source: AShareSource, factory: EvidenceFactory) -> list[Skill]:
    def statements(inp: StatementsIn) -> StatementsOut:
        income = [r for r in source.income_rows(inp.code) if _d(r.get("NOTICE_DATE")) and _d(r["NOTICE_DATE"]) <= inp.as_of]
        if not income:
            raise SkillFailed(f"{inp.code} 在 {inp.as_of} 之前没有已披露的利润表")
        cash = {r["REPORT_DATE"][:10]: r for r in source.cashflow_rows(inp.code)
                if _d(r.get("NOTICE_DATE")) and _d(r["NOTICE_DATE"]) <= inp.as_of}
        balance = {r["REPORT_DATE"][:10]: r for r in source.balance_rows(inp.code)
                   if _d(r.get("NOTICE_DATE")) and _d(r["NOTICE_DATE"]) <= inp.as_of}
        income.sort(key=lambda r: r["REPORT_DATE"], reverse=True)
        name = income[0].get("SECURITY_NAME_ABBR") or inp.code
        sym = exchange_prefix(inp.code) + inp.code
        cards = []
        for row in income[: inp.periods]:
            period = row["REPORT_DATE"][:10]
            merged = {**row, **{k: v for k, v in cash.get(period, {}).items() if k == "NETCASH_OPERATE"},
                      **{k: v for k, v in balance.get(period, {}).items() if k not in ("REPORT_DATE", "NOTICE_DATE")}}
            metrics = [
                Metric(name=n, field=f, value=Decimal(str(merged[f])), unit="元", period=period, basis="cumulative")
                for n, f in STATEMENT_METRICS if merged.get(f) is not None
            ] + [
                Metric(name=n, field=f, value=Decimal(str(merged[f])), unit="元", period=period, basis="point")
                for n, f in BALANCE_METRICS if merged.get(f) is not None
            ]
            notice, updated = _d(row["NOTICE_DATE"]), _d(row.get("UPDATE_DATE"))
            caveats = ["利润表与现金流量表为报告期累计值，资产负债表为期末时点值；营业总收入含利息等收入，与营业收入不是同一口径"]
            pit = "strong"
            if updated and notice and updated - notice > RESTATE_TOLERANCE:
                pit = "weak"
                caveats.append(f"数据源在 {updated} 更新过，数值可能为追溯调整后口径")
            cards.append(factory.make(
                content=json.dumps(merged, ensure_ascii=False, sort_keys=True),
                level="A", source_type="filing",
                title=f"{name} {period} 定期报告财务数据（利润表/现金流量表/资产负债表）",
                source_url=f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code={sym}",
                site_name="东方财富（结构化财报）", origin_id=f"filing:{inp.code}:{period}", origin_publisher=name,
                published_at=_dt(notice), as_of=inp.as_of, pit=pit,
                excerpt="；".join(f"{m.name} {m.value} 元" for m in metrics),
                metrics=metrics, caveats=caveats, skill="financials.statements", skill_version="1.1.0",
            ))
        return StatementsOut(name=name, cards=cards)

    def daily(inp: DailyIn) -> CardsOut:
        rows = source.daily(inp.code, inp.as_of - timedelta(days=inp.lookback_days), inp.as_of)
        rows = [r for r in rows if r.get("close") is not None and _d(r["date"]) <= inp.as_of]
        if len(rows) < 21:
            raise SkillFailed(f"{inp.code} 行情数据不足")
        closes = [Decimal(str(r["close"])) for r in rows]
        last = rows[-1]["date"][:10]
        metrics = [Metric(name="收盘价(前复权)", field="close", value=closes[-1], unit="元", period=last, basis="point")]
        for w in (20, 60, 250):
            if (chg := price_change(closes, w)) is not None:
                metrics.append(Metric(name=f"近{w}个交易日涨跌幅", field=f"chg_{w}d", value=chg, unit="%", period=last, basis="change"))
        if (vol := annualized_volatility(closes, 60)) is not None:
            metrics.append(Metric(name="近60日年化波动率", field="vol_60d", value=vol, unit="%", period=last, basis="ratio"))
        for w in (20, 60, 120):
            if (ma := moving_average(closes, w)) is not None and ma != 0:
                metrics.append(Metric(name=f"收盘价相对MA{w}", field=f"ma{w}_gap", value=q((closes[-1] / ma - 1) * 100),
                                      unit="%", period=last, basis="ratio", note=f"MA{w}={q(ma)}"))
        if (dd := max_drawdown(closes[-250:])) is not None:
            metrics.append(Metric(name="近250日最大回撤", field="mdd_250d", value=dd, unit="%", period=last, basis="change"))
        vols = [Decimal(str(r["volume"])) for r in rows if r.get("volume") is not None]
        if len(vols) >= 60 and sum(vols[-60:]) > 0:
            ratio_v = (sum(vols[-20:]) / 20) / (sum(vols[-60:]) / 60)
            metrics.append(Metric(name="近20日/近60日均量比", field="vol_ratio_20_60", value=q(ratio_v * 100), unit="%",
                                  period=last, basis="ratio"))
        turnovers = [Decimal(str(r["turnover"])) for r in rows[-20:] if r.get("turnover") is not None]
        if turnovers:
            metrics.append(Metric(name="近20日平均换手率", field="turnover_20d", value=q(sum(turnovers) / len(turnovers)),
                                  unit="%", period=last, basis="ratio"))
        card = factory.make(
            content=json.dumps(rows[-260:], ensure_ascii=False), level="A", source_type="market",
            title=f"{inp.code} 日线行情（截至 {last}）", site_name="AKShare/东方财富行情",
            origin_id=f"market:{inp.code}:{last}", published_at=_dt(_d(last)), as_of=inp.as_of,
            excerpt="；".join(f"{m.name} {m.value}{m.unit}" for m in metrics), metrics=metrics,
            caveats=["前复权价格；行情只描述状态，不单独推出买卖结论"],
            skill="market.daily", skill_version="1.1.0",
        )
        return CardsOut(cards=[card])

    def announcements(inp: AnnouncementsIn) -> CardsOut:
        rows = source.announcements(inp.code, inp.as_of - timedelta(days=inp.lookback_days), inp.as_of)
        rows = [r for r in rows if r.get("date") and _d(r["date"]) <= inp.as_of][: inp.limit]
        cards = [
            factory.make(
                content=json.dumps(r, ensure_ascii=False, sort_keys=True), level="A", source_type="announcement",
                title=r["title"], source_url=r.get("url"), site_name="巨潮资讯",
                origin_id=f"cninfo:{r.get('url') or r['title']}", origin_publisher=r.get("name"),
                published_at=_dt(_d(r["date"])), as_of=inp.as_of, excerpt=f"{r['date'][:10]} 公告：{r['title']}",
                caveats=["仅公告标题，一期未解析正文"], skill="announcements.list", skill_version="1.0.0",
            )
            for r in rows
        ]
        return CardsOut(cards=cards)

    return [
        Skill(spec=SkillSpec(name="financials.statements", version="1.1.0", category="data", permission="read",
                             description="as_of 时点已披露的利润表、现金流量表（累计）与资产负债表（时点）",
                             input_model=StatementsIn, output_model=StatementsOut, timeout_s=90,
                             retryable=(ConnectionError, TimeoutError, OSError)), run=statements),
        Skill(spec=SkillSpec(name="market.daily", version="1.1.0", category="data", permission="read",
                             description="as_of 前的日线行情、区间统计与技术状态（均线偏离、回撤、量比）", input_model=DailyIn, output_model=CardsOut,
                             timeout_s=60, retryable=(ConnectionError, TimeoutError, OSError)), run=daily),
        Skill(spec=SkillSpec(name="announcements.list", version="1.0.0", category="data", permission="read",
                             description="as_of 前的巨潮公告标题列表", input_model=AnnouncementsIn, output_model=CardsOut,
                             timeout_s=60, retryable=(ConnectionError, TimeoutError, OSError)), run=announcements),
    ]
