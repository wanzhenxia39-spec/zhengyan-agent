"""A 股结构化数据源适配器（一期 AKShare），统一接口以便替换为 Tushare 等。"""
import math
from datetime import date
from typing import Any, Protocol

from advisor.storage import Repository

INCOME_FIELDS = ["REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE", "SECURITY_NAME_ABBR", "OPERATE_INCOME",
                 "TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "DEDUCT_PARENT_NETPROFIT"]
CASHFLOW_FIELDS = ["REPORT_DATE", "NOTICE_DATE", "NETCASH_OPERATE"]
BALANCE_FIELDS = ["REPORT_DATE", "NOTICE_DATE", "SHARE_CAPITAL", "TOTAL_PARENT_EQUITY", "CONTRACT_LIAB", "INVENTORY",
                  "MONETARYFUNDS", "ACCOUNTS_RECE", "TOTAL_ASSETS", "TOTAL_LIABILITIES"]


def exchange_prefix(code: str) -> str:
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    return "BJ"


class AShareSource(Protocol):
    def income_rows(self, code: str) -> list[dict[str, Any]]: ...
    def cashflow_rows(self, code: str) -> list[dict[str, Any]]: ...
    def balance_rows(self, code: str) -> list[dict[str, Any]]: ...
    def daily(self, code: str, start: date, end: date) -> list[dict[str, Any]]: ...
    def announcements(self, code: str, start: date, end: date) -> list[dict[str, Any]]: ...


def _plain(v: Any) -> Any:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    if isinstance(v, float):
        return repr(v)          # 保留精度，转 Decimal 时不经二进制误差放大
    return str(v) if not isinstance(v, (int, str)) else v


def _records(df, fields: list[str]) -> list[dict[str, Any]]:
    cols = [f for f in fields if f in df.columns]
    return [{k: _plain(v) for k, v in row.items()} for row in df[cols].to_dict("records")]


class AKShareSource:
    """带 Mongo 缓存的 AKShare 适配器。东财报表接口较慢（约 20s），缓存 12 小时。"""

    def __init__(self, repo: Repository | None = None, ttl_hours: float = 12):
        self.repo = repo
        self.ttl = ttl_hours

    def _cached(self, key: str, loader):
        if self.repo and (hit := self.repo.cache_get(key)) is not None:
            return hit
        value = loader()
        if self.repo:
            self.repo.cache_set(key, value, self.ttl)
        return value

    def income_rows(self, code: str) -> list[dict[str, Any]]:
        import akshare as ak
        sym = exchange_prefix(code) + code
        return self._cached(f"ak:income:{sym}", lambda: _records(ak.stock_profit_sheet_by_report_em(symbol=sym), INCOME_FIELDS))

    def cashflow_rows(self, code: str) -> list[dict[str, Any]]:
        import akshare as ak
        sym = exchange_prefix(code) + code
        return self._cached(f"ak:cashflow:{sym}", lambda: _records(ak.stock_cash_flow_sheet_by_report_em(symbol=sym), CASHFLOW_FIELDS))

    def balance_rows(self, code: str) -> list[dict[str, Any]]:
        import akshare as ak
        sym = exchange_prefix(code) + code
        return self._cached(f"ak:balance:{sym}", lambda: _records(ak.stock_balance_sheet_by_report_em(symbol=sym), BALANCE_FIELDS))

    def daily(self, code: str, start: date, end: date) -> list[dict[str, Any]]:
        import akshare as ak

        def load():
            s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
            try:
                df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=s, end_date=e, adjust="qfq")
                df = df.rename(columns={"日期": "date", "收盘": "close", "换手率": "turnover", "成交量": "volume"})
            except Exception:  # 东财接口不稳定时回退新浪；新浪换手率为小数，统一成 %
                df = ak.stock_zh_a_daily(symbol=exchange_prefix(code).lower() + code, start_date=s, end_date=e, adjust="qfq")
                df["turnover"] = df["turnover"] * 100
            return _records(df, ["date", "close", "turnover", "volume"])
        return self._cached(f"ak:daily:v2:{code}:{start}:{end}", load)

    def announcements(self, code: str, start: date, end: date) -> list[dict[str, Any]]:
        import akshare as ak

        def load():
            df = ak.stock_zh_a_disclosure_report_cninfo(symbol=code, market="沪深京", start_date=start.strftime("%Y%m%d"),
                                                        end_date=end.strftime("%Y%m%d"))
            df = df.rename(columns={"简称": "name", "公告标题": "title", "公告时间": "date", "公告链接": "url"})
            return _records(df, ["name", "title", "date", "url"])
        return self._cached(f"ak:ann:{code}:{start}:{end}", load)
