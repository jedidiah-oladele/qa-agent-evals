from datetime import UTC, datetime
from decimal import Decimal

from shopcore import FixedClock, Money, Order, PricingEngine, Product, TaxRegion, TaxTable, default_tax_table
from shopcore.tax import compute_taxes


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


def test_half_cent_rounds_up_per_line():
    assert compute_taxes([usd("2.00")], [Decimal("0.0725")])[0].amount == Decimal("0.15")


def test_quote_for_two_dollar_item_in_california():
    order = Order("USD", "US-CA")
    order.add(Product("PEN-1", "Pen", usd("2.00")), 1)
    engine = PricingEngine(default_tax_table(), clock=FixedClock(datetime(2026, 5, 1, tzinfo=UTC)))
    quote = engine.quote(order)
    assert quote.tax_total == usd("0.15")
    assert quote.total == usd("2.15")


def test_refund_lines_round_away_from_zero():
    taxes = compute_taxes([usd("-2.00"), usd("2.00")], [Decimal("0.0725")] * 2)
    assert [t.amount for t in taxes] == [Decimal("-0.15"), Decimal("0.15")]


def test_half_unit_rounds_up_for_three_decimal_currency():
    taxes = compute_taxes([Money.of("1.000", "KWD")], [Decimal("0.0125")])
    assert taxes[0].amount == Decimal("0.013")


def test_half_unit_rounds_up_for_zero_decimal_currency():
    taxes = compute_taxes([Money.of("250", "JPY")], [Decimal("0.05")])
    assert taxes[0].amount == Decimal("13")


def test_below_half_still_rounds_down():
    # 1.94 * 0.0725 = 0.14065 -> 0.14
    assert compute_taxes([usd("1.94")], [Decimal("0.0725")])[0].amount == Decimal("0.14")


def test_per_order_rounding_unchanged():
    table = TaxTable([TaxRegion("XX", Decimal("0.0725"))])
    region = table.get("XX")
    from shopcore.tax import TaxRounding

    taxes = compute_taxes([usd("2.00"), usd("2.00")], [region.standard_rate] * 2, rounding=TaxRounding.PER_ORDER)
    assert sum(t.amount for t in taxes) == Decimal("0.29")
