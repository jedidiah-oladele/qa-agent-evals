from datetime import UTC, datetime
from decimal import Decimal

import pytest

from shopcore import (
    FixedAmountDiscount,
    FixedClock,
    LineItem,
    Money,
    Order,
    PercentageDiscount,
    PricingEngine,
    Product,
    TaxRounding,
    apply_discounts,
    default_tax_table,
    sum_money,
)
from shopcore.tax import compute_taxes

NOW = datetime(2026, 5, 2, 10, 0, tzinfo=UTC)


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


def amounts(values):
    return [m.amount for m in values]


TOTE = Product("TOTE-0", "Free tote bag", usd("0.00"))
TEE = Product("TEE-1", "Tee", usd("19.99"), category="apparel")
MUG = Product("MUG-1", "Mug", usd("12.50"), category="kitchen")
BEANS = Product("BEAN-1", "Coffee beans", usd("9.95"), category="grocery", tax_category="food")
APRON = Product("APRON-1", "Apron", usd("25.00"), category="apparel")
PAN = Product("PAN-1", "Pan", usd("7.99"), category="kitchen")
KNIFE = Product("KNIFE-1", "Knife", usd("12.49"), category="kitchen")


# -- Money.allocate -----------------------------------------------------------


def test_allocate_leftover_goes_to_largest_remainder_after_a_zero_weight():
    assert amounts(usd("1.00").allocate([0, 1, 2])) == [Decimal("0.00"), Decimal("0.33"), Decimal("0.67")]


def test_allocate_never_gives_units_to_zero_weights():
    parts = Money.of("1000", "JPY").allocate([0, 0, 1, 1, 1])
    assert amounts(parts) == [Decimal("0"), Decimal("0"), Decimal("334"), Decimal("333"), Decimal("333")]


@pytest.mark.parametrize(
    "weights",
    [
        [0, 3, 3, 3],
        [Decimal("0"), Decimal("19.99"), Decimal("12.50")],
        [5, 0, 7, 0, 11],
        [0, 0, Decimal("0.0725"), Decimal("1.449275"), Decimal("0.90625")],
    ],
)
def test_allocate_sums_exactly_and_zero_weights_get_nothing(weights):
    for amount in ("1.00", "5.00", "10.01", "123.45"):
        parts = usd(amount).allocate(weights)
        assert sum_money(parts, "USD") == usd(amount)
        assert all(p.is_zero() for p, w in zip(parts, weights) if w == 0)


# -- discounts -------------------------------------------------------------------


def test_fixed_coupon_with_free_gift_first_takes_the_full_amount():
    lines = [LineItem(TOTE, 1), LineItem(TEE, 1), LineItem(MUG, 1)]
    result = apply_discounts(lines, [FixedAmountDiscount(code="FIVE", amount=usd("5.00"))], now=NOW)
    assert amounts(result.per_line) == [Decimal("0.00"), Decimal("3.08"), Decimal("1.92")]
    assert [(a.code, a.amount) for a in result.applied] == [("FIVE", usd("5.00"))]


def test_category_discount_cents_stay_inside_the_category():
    lines = [LineItem(APRON, 1), LineItem(PAN, 1), LineItem(KNIFE, 1)]
    discount = PercentageDiscount(code="KITCHEN15", percent=Decimal(15), category="kitchen")
    result = apply_discounts(lines, [discount], now=NOW)
    # 15% of 20.48 = 3.072 -> 3.07, split 7.99 : 12.49
    assert amounts(result.per_line) == [Decimal("0.00"), Decimal("1.20"), Decimal("1.87")]


# -- per-order tax ----------------------------------------------------------------


def test_per_order_tax_gives_exempt_lines_nothing():
    taxes = compute_taxes(
        [usd("9.95"), usd("12.50"), usd("19.99")],
        [Decimal(0), Decimal("0.0725"), Decimal("0.0725")],
        rounding=TaxRounding.PER_ORDER,
    )
    assert amounts(taxes) == [Decimal("0.00"), Decimal("0.91"), Decimal("1.45")]


def test_quote_with_coupon_and_per_order_tax_keeps_exempt_line_untaxed():
    coupon = FixedAmountDiscount(code="FIVE", amount=usd("5.00"), auto_apply=True)
    engine = PricingEngine(default_tax_table(), [coupon], rounding=TaxRounding.PER_ORDER, clock=FixedClock(NOW))
    order = Order("USD", "US-CA")
    for product in (BEANS, TEE, MUG):
        order.add(product, 1)
    quote = engine.quote(order)
    assert [line.tax.amount for line in quote.lines] == [Decimal("0.00"), Decimal("1.28"), Decimal("0.80")]
    assert quote.tax_total == usd("2.08")
    assert quote.total == usd("39.52")


def test_quote_with_free_gift_coupon_and_per_order_tax_does_not_drift():
    coupon = FixedAmountDiscount(code="FIVE", amount=usd("5.00"))
    engine = PricingEngine(default_tax_table(), [coupon], rounding=TaxRounding.PER_ORDER, clock=FixedClock(NOW))
    order = Order("USD", "US-CA", coupon_codes=("five",))
    order.add(TOTE, 1)
    order.add(TEE, 1)
    order.add(MUG, 1)
    order.add(BEANS, 2)
    quote = engine.quote(order)
    assert quote.subtotal == usd("52.39")
    assert quote.discount_total == usd("5.00")
    assert [line.discount.amount for line in quote.lines] == [
        Decimal("0.00"), Decimal("1.91"), Decimal("1.19"), Decimal("1.90")
    ]
    assert [line.tax.amount for line in quote.lines] == [
        Decimal("0.00"), Decimal("1.31"), Decimal("0.82"), Decimal("0.00")
    ]
    assert quote.total == usd("49.52")
    assert sum((line.total.amount for line in quote.lines), Decimal(0)) == quote.total.amount


# -- guards: behaviour that was already right must stay right -----------------------


def test_allocate_without_zero_weights_is_unchanged():
    assert amounts(usd("10").allocate([1, 1, 1])) == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert amounts(usd("-1.00").allocate([1, 2, 0])) == [Decimal("-0.33"), Decimal("-0.67"), Decimal("0.00")]


def test_per_line_tax_is_unaffected():
    taxes = compute_taxes([usd("9.95"), usd("12.50"), usd("19.99")], [Decimal(0), Decimal("0.0725"), Decimal("0.0725")])
    assert amounts(taxes) == [Decimal("0.00"), Decimal("0.91"), Decimal("1.45")]
