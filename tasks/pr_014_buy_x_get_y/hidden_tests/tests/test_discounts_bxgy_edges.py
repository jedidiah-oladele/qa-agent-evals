from datetime import UTC, datetime, timedelta
from decimal import Decimal

import shopcore
from shopcore import LineItem, Money, PercentageDiscount, Product, apply_discounts

NOW = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


def buy_x_get_y(**kwargs):
    # Looked up at call time, so this module still imports where the class is missing.
    return shopcore.BuyXGetYDiscount(**kwargs)


def test_get_more_than_one_per_group(catalog):
    # buy 3 get 2: 11 units hold two complete groups of 5 -> 4 free units of 9.95
    lines = [LineItem(catalog.get("BEAN-250"), 11)]
    deal = buy_x_get_y(code="BEANS5FOR3", sku="BEAN-250", buy=3, get=2)
    result = apply_discounts(lines, [deal], now=NOW)
    assert result.per_line == [usd("39.80")]


def test_get_larger_than_buy(catalog):
    lines = [LineItem(catalog.get("MUG-001"), 6)]
    deal = buy_x_get_y(code="MUG1GET2", sku="MUG-001", buy=1, get=2)
    assert apply_discounts(lines, [deal], now=NOW).per_line == [usd("50.00")]


def test_groups_are_counted_per_line_not_per_order(catalog):
    mug = catalog.get("MUG-001")
    lines = [LineItem(mug, 2), LineItem(mug, 1), LineItem(mug, 4)]
    deal = buy_x_get_y(code="MUG3FOR2", sku="MUG-001", buy=2, get=1)
    result = apply_discounts(lines, [deal], now=NOW)
    assert result.per_line == [usd("0"), usd("0"), usd("12.50")]
    assert [(a.code, a.amount) for a in result.applied] == [("MUG3FOR2", usd("12.50"))]


def test_free_units_valued_at_unit_price_after_an_earlier_percentage(catalog):
    lines = [LineItem(catalog.get("BOOK-042"), 3)]
    discounts = [
        PercentageDiscount(code="READ10", percent=Decimal(10), priority=1),
        buy_x_get_y(code="BOOK3FOR2", sku="BOOK-042", buy=2, get=1, priority=2),
    ]
    result = apply_discounts(lines, discounts, now=NOW)
    # 72.00 gross; 10% = 7.20 leaves 64.80; one free unit is worth its 24.00 unit price
    assert [(a.code, a.amount) for a in result.applied] == [("READ10", usd("7.20")), ("BOOK3FOR2", usd("24.00"))]
    assert result.total("USD") == usd("31.20")


def test_free_units_capped_by_what_is_left(catalog):
    lines = [LineItem(catalog.get("BOOK-042"), 3)]
    discounts = [
        PercentageDiscount(code="READ90", percent=Decimal(90), priority=1),
        buy_x_get_y(code="BOOK3FOR2", sku="BOOK-042", buy=2, get=1, priority=2),
    ]
    result = apply_discounts(lines, discounts, now=NOW)
    # 90% of 72.00 = 64.80 leaves 7.20, less than one free 24.00 book
    assert result.total("USD") == usd("72.00")


def test_compute_never_exceeds_remaining(catalog):
    deal = buy_x_get_y(code="MUG3FOR2", sku="MUG-001", buy=2, get=1)
    lines = [LineItem(catalog.get("MUG-001"), 6), LineItem(catalog.get("TEE-001"), 1)]
    amounts = deal.compute(lines, [usd("17.30"), usd("19.99")])
    assert amounts == [usd("17.30"), usd("0")]


def test_exclusive_bxgy_wins_only_when_it_saves_more(catalog):
    lines = [LineItem(catalog.get("TEE-001"), 4)]
    deal = buy_x_get_y(code="TEE4FOR3", sku="TEE-001", buy=3, get=1, stackable=False)
    small = PercentageDiscount(code="FIVE", percent=Decimal(5))
    big = PercentageDiscount(code="THIRTY", percent=Decimal(30))
    assert [a.code for a in apply_discounts(lines, [deal, small], now=NOW).applied] == ["TEE4FOR3"]
    assert [a.code for a in apply_discounts(lines, [deal, big], now=NOW).applied] == ["THIRTY"]


def test_expired_bxgy_is_ignored(catalog):
    lines = [LineItem(catalog.get("MUG-001"), 3)]
    deal = buy_x_get_y(code="M", sku="MUG-001", buy=2, get=1, expires_at=NOW - timedelta(seconds=1))
    assert apply_discounts(lines, [deal], now=NOW).applied == []


def test_zero_decimal_currency():
    ramen = Product("RAMEN-5", "Ramen", Money.of("480", "JPY"))
    result = apply_discounts([LineItem(ramen, 5)], [buy_x_get_y(code="R", sku="RAMEN-5", buy=1, get=1)], now=NOW)
    assert result.per_line == [Money.of("960", "JPY")]


def test_exported_from_package_root():
    from shopcore.discounts import BuyXGetYDiscount as defined

    assert "BuyXGetYDiscount" in shopcore.__all__
    assert shopcore.BuyXGetYDiscount is defined
