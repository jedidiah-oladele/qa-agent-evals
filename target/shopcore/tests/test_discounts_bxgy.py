from datetime import UTC, datetime
from decimal import Decimal

import pytest

from shopcore import BuyXGetYDiscount, DiscountError, LineItem, Money, PercentageDiscount, apply_discounts

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def test_buy_two_get_one_counts_complete_groups(catalog):
    lines = [LineItem(catalog.get("MUG-001"), 7)]
    result = apply_discounts(lines, [BuyXGetYDiscount(code="MUG3FOR2", sku="MUG-001", buy=2, get=1)], now=NOW)
    assert result.per_line == [Money.of("25.00", "USD")]


def test_other_skus_are_untouched(catalog):
    lines = [LineItem(catalog.get("TEE-001"), 3), LineItem(catalog.get("MUG-001"), 3)]
    result = apply_discounts(lines, [BuyXGetYDiscount(code="M", sku="MUG-001", buy=2, get=1)], now=NOW)
    assert [m.amount for m in result.per_line] == [Decimal("0"), Decimal("12.50")]


def test_incomplete_group_gives_nothing(catalog):
    lines = [LineItem(catalog.get("MUG-001"), 2)]
    result = apply_discounts(lines, [BuyXGetYDiscount(code="M", sku="MUG-001", buy=2, get=1)], now=NOW)
    assert result.total("USD").is_zero()
    assert result.applied == []


def test_bxgy_runs_before_percentage_when_prioritised(catalog):
    lines = [LineItem(catalog.get("MUG-001"), 3)]
    discounts = [
        BuyXGetYDiscount(code="M", sku="MUG-001", buy=2, get=1, priority=1),
        PercentageDiscount(code="TEN", percent=Decimal(10), priority=2),
    ]
    result = apply_discounts(lines, discounts, now=NOW)
    # 37.50 - 12.50 free = 25.00; 10% of 25.00 = 2.50
    assert result.total("USD") == Money.of("15.00", "USD")


@pytest.mark.parametrize(("buy", "get"), [(0, 1), (1, 0)])
def test_invalid_buy_get(buy, get):
    with pytest.raises(DiscountError):
        BuyXGetYDiscount(code="X", sku="A", buy=buy, get=get)
