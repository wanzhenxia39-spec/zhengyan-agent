import json
from decimal import Decimal

import pytest

from advisor.contracts import Metric
from advisor.settings import ROOT
from advisor.skills.compute.finance import BasisMismatch, annualized_volatility, price_change, ratio, same_basis_growth, single_quarter

CASES = json.loads((ROOT / "evals" / "golden" / "compute_cases.json").read_text(encoding="utf-8"))


def m(field, value, period, basis="cumulative"):
    return Metric(name=field, field=field, value=Decimal(value), unit="元", period=period, basis=basis)


@pytest.mark.parametrize("case", CASES["growth"], ids=lambda c: c["id"])
def test_growth(case):
    cur, pri = m(*case["current"]), m(*case["prior"])
    if case.get("error"):
        with pytest.raises(BasisMismatch):
            same_basis_growth(cur, pri)
    else:
        assert same_basis_growth(cur, pri).value == Decimal(case["expected"])


@pytest.mark.parametrize("case", CASES["single_quarter"], ids=lambda c: c["id"])
def test_single_quarter(case):
    cum = m(*case["cumulative"])
    prev = m(*case["previous"]) if case["previous"] else None
    if case.get("error"):
        with pytest.raises(BasisMismatch):
            single_quarter(cum, prev)
    else:
        out = single_quarter(cum, prev)
        assert out.value == Decimal(case["expected"]) and out.basis == "single_quarter"


@pytest.mark.parametrize("case", CASES["ratio"], ids=lambda c: c["id"])
def test_ratio(case):
    num, den = m(*case["numerator"]), m(*case["denominator"])
    if case.get("error"):
        with pytest.raises(BasisMismatch):
            ratio(num, den, "r", "R")
    else:
        assert ratio(num, den, "r", "R").value == Decimal(case["expected"])


def test_price_stats():
    closes = [Decimal(100), Decimal(110), Decimal(121)]
    assert price_change(closes, 2) == Decimal("21.00")
    assert price_change(closes, 5) is None
    assert annualized_volatility(closes, 5) is None
    flat = [Decimal(10)] * 70
    assert annualized_volatility(flat, 60) == Decimal("0.00")
