from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shopcore import (
    DiscountError,
    FixedAmountDiscount,
    LineItem,
    Money,
    PercentageDiscount,
    apply_discounts,
)

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


@pytest.fixture
def lines(catalog):
    return [LineItem(catalog.get("TEE-001"), 2), LineItem(catalog.get("MUG-001"), 1)]


def amounts(result):
    return [m.amount for m in result.per_line]


def test_percentage_discount_spreads_by_line_value(lines):
    result = apply_discounts(lines, [PercentageDiscount(code="TEN", percent=Decimal(10))], now=NOW)
    # 10% of 52.48 = 5.248 -> 5.25, split 39.98 : 12.50
    assert amounts(result) == [Decimal("4.00"), Decimal("1.25")]
    assert result.total("USD") == usd("5.25")


def test_percentage_discount_limited_to_category(lines):
    result = apply_discounts(
        lines, [PercentageDiscount(code="KITCHEN20", percent=Decimal(20), category="kitchen")], now=NOW
    )
    assert amounts(result) == [Decimal("0.00"), Decimal("2.50")]


def test_percentage_discount_cap(lines):
    discount = PercentageDiscount(code="HALF", percent=Decimal(50), max_discount=usd("10"))
    assert apply_discounts(lines, [discount], now=NOW).total("USD") == usd("10.00")


def test_min_subtotal_is_checked_against_gross(lines):
    discount = PercentageDiscount(code="BIG", percent=Decimal(10), min_subtotal=usd("60"))
    assert apply_discounts(lines, [discount], now=NOW).total("USD").is_zero()


@pytest.mark.parametrize("percent", ["0", "-5", "100.01"])
def test_percent_out_of_range(percent):
    with pytest.raises(DiscountError):
        PercentageDiscount(code="X", percent=Decimal(percent))


def test_fixed_amount_capped_at_order_value(catalog):
    lines = [LineItem(catalog.get("MUG-001"), 1)]
    result = apply_discounts(lines, [FixedAmountDiscount(code="OFF20", amount=usd("20"))], now=NOW)
    assert result.total("USD") == usd("12.50")


def test_fixed_amount_rejects_non_positive():
    with pytest.raises(DiscountError):
        FixedAmountDiscount(code="X", amount=usd("0"))


def test_stackable_discounts_apply_sequentially_by_priority(lines):
    first = FixedAmountDiscount(code="FIVE", amount=usd("5"), priority=10)
    second = PercentageDiscount(code="TEN", percent=Decimal(10), priority=20)
    result = apply_discounts(lines, [second, first], now=NOW)
    # 52.48 - 5.00 = 47.48; 10% of that = 4.748 -> 4.75
    assert [a.code for a in result.applied] == ["FIVE", "TEN"]
    assert result.total("USD") == usd("9.75")


def test_same_priority_breaks_ties_by_code(lines):
    a = PercentageDiscount(code="B-TEN", percent=Decimal(10))
    b = FixedAmountDiscount(code="A-FIVE", amount=usd("5"))
    assert [x.code for x in apply_discounts(lines, [a, b], now=NOW).applied] == ["A-FIVE", "B-TEN"]


def test_best_of_exclusive_or_stacked_wins(lines):
    stacked = [
        PercentageDiscount(code="FIVE-PCT", percent=Decimal(5)),
        FixedAmountDiscount(code="TWO", amount=usd("2")),
    ]
    exclusive = PercentageDiscount(code="VIP", percent=Decimal(15), stackable=False)
    result = apply_discounts(lines, [*stacked, exclusive], now=NOW)
    assert [a.code for a in result.applied] == ["VIP"]
    assert result.total("USD") == usd("7.87")


def test_stacked_wins_ties_against_exclusive(lines):
    stacked = FixedAmountDiscount(code="FIVE", amount=usd("5"))
    exclusive = FixedAmountDiscount(code="ALSO-FIVE", amount=usd("5"), stackable=False)
    assert [a.code for a in apply_discounts(lines, [exclusive, stacked], now=NOW).applied] == ["FIVE"]


def test_expired_discounts_are_ignored(lines):
    expired = PercentageDiscount(code="OLD", percent=Decimal(10), expires_at=NOW)
    live = PercentageDiscount(code="NEW", percent=Decimal(10), expires_at=NOW + timedelta(seconds=1))
    result = apply_discounts(lines, [expired, live], now=NOW)
    assert [a.code for a in result.applied] == ["NEW"]


def test_discount_never_exceeds_line_value(catalog):
    lines = [LineItem(catalog.get("MUG-001"), 1)]
    discounts = [
        FixedAmountDiscount(code="A", amount=usd("10"), priority=1),
        FixedAmountDiscount(code="B", amount=usd("10"), priority=2),
    ]
    result = apply_discounts(lines, discounts, now=NOW)
    assert result.total("USD") == usd("12.50")
    assert [(a.code, a.amount) for a in result.applied] == [("A", usd("10.00")), ("B", usd("2.50"))]


def test_no_lines_no_discount():
    assert apply_discounts([], [PercentageDiscount(code="X", percent=Decimal(5))], now=NOW).per_line == []
