"""网页证据分级：B = 权威 + 已抓取快照 + 日期可知；其余为 C（只能触发补证）。A 级只来自结构化源。"""
from datetime import date

from advisor.contracts import SearchHit


def grade_web(hit: SearchHit, fetched: bool, as_of: date, authority_b_min: int = 3) -> tuple[str, list[str]]:
    caveats: list[str] = ["网页来源：数字须回到财报/公告复核后才能作为事实"]
    if hit.date is None:
        caveats.append("页面日期未知，无法确认时点")
    elif hit.date.date() > as_of:
        caveats.append("页面日期晚于研究时点")
        return "C", caveats
    if hit.authority < 0:
        caveats.append("权威度未知")
    if not fetched:
        caveats.append("仅有搜索摘要，未抓取全文快照")
    if hit.authority >= authority_b_min and fetched and hit.date is not None:
        return "B", caveats
    return "C", caveats
