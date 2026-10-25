from decimal import Decimal

import pytest

from shopcore import Money, TaxConfigError, TaxRegion, TaxRounding, TaxTable, default_tax_table
from shopcore.tax import compute_taxes, unrounded_tax


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


def test_rate_for_categories():
    region = default_tax_table().get("GB")
    assert region.rate_for("standard") == Decimal("0.20")
    assert region.rate_for("energy") == Decimal("0.05")
    assert region.rate_for("food") == Decimal(0)


def test_unknown_region_raises():
    with pytest.raises(TaxConfigError):
        default_tax_table().get("FR")


def test_default_table_is_fresh_each_call():
    table = default_tax_table()
    table.register(TaxRegion("FR", Decimal("0.20")))
    assert "FR" not in default_tax_table()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"standard_rate": Decimal("-0.01")},
        {"standard_rate": Decimal("1")},
        {"standard_rate": Decimal("0.1"), "reduced_rate": Decimal("1.5")},
        {
            "standard_rate": Decimal("0.1"),
            "reduced_categories": frozenset({"food"}),
            "exempt_categories": frozenset({"food"}),
        },
    ],
)
def test_invalid_region_config(kwargs):
    with pytest.raises(TaxConfigError):
        TaxRegion("XX", **kwargs)


def test_exclusive_and_inclusive_unrounded_tax():
    assert unrounded_tax(usd("100"), Decimal("0.20"), inclusive=False) == Decimal("20.00")
    assert unrounded_tax(usd("120"), Decimal("0.20"), inclusive=True) == Decimal("20")


def test_per_line_rounding_half_up():
    taxes = compute_taxes([usd("1.50"), usd("1.50")], [Decimal("0.0725")] * 2)
    # 0.10875 each -> 0.11 each
    assert [t.amount for t in taxes] == [Decimal("0.11"), Decimal("0.11")]


def test_per_order_rounding_rounds_once_and_spreads():
    taxes = compute_taxes([usd("1.50"), usd("1.50")], [Decimal("0.0725")] * 2, rounding=TaxRounding.PER_ORDER)
    # 0.2175 -> 0.22 total
    assert sum(t.amount for t in taxes) == Decimal("0.22")
    assert [t.amount for t in taxes] == [Decimal("0.11"), Decimal("0.11")]


def test_per_order_rounding_differs_from_per_line():
    nets = [usd("0.05")] * 3
    per_line = compute_taxes(nets, [Decimal("0.10")] * 3)
    per_order = compute_taxes(nets, [Decimal("0.10")] * 3, rounding=TaxRounding.PER_ORDER)
    assert sum(t.amount for t in per_line) == Decimal("0.03")
    assert sum(t.amount for t in per_order) == Decimal("0.02")


def test_zero_rate_lines_get_zero_tax():
    taxes = compute_taxes([usd("10"), usd("5")], [Decimal("0"), Decimal("0")], rounding=TaxRounding.PER_ORDER)
    assert all(t.is_zero() for t in taxes)


def test_length_mismatch():
    with pytest.raises(ValueError):
        compute_taxes([usd("1")], [])


def test_table_codes_sorted():
    table = TaxTable([TaxRegion("B", Decimal("0.1")), TaxRegion("A", Decimal("0.1"))])
    assert table.codes() == ["A", "B"]
