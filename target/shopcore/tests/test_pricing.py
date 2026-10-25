from datetime import timedelta
from decimal import Decimal

import pytest

from shopcore import (
    CurrencyMismatchError,
    FixedAmountDiscount,
    LineItem,
    Money,
    Order,
    PercentageDiscount,
    PricingEngine,
    Product,
    ShippingPolicy,
    TaxConfigError,
    TaxRounding,
    WeightTier,
    default_tax_table,
)


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


@pytest.fixture
def shipping():
    return ShippingPolicy(tiers=(WeightTier(1000, usd("5.00")), WeightTier(5000, usd("9.00"))), free_over=usd("50"))


def make_order(catalog, region="US-CA", coupons=(), **quantities):
    order = Order("USD", region, coupon_codes=tuple(coupons))
    for sku, qty in quantities.items():
        order.add(catalog.get(sku.replace("_", "-")), qty)
    return order


def test_simple_exclusive_tax_quote(catalog, clock):
    engine = PricingEngine(default_tax_table(), clock=clock)
    quote = engine.quote(make_order(catalog, TEE_001=2, MUG_001=1))
    assert quote.subtotal == usd("52.48")
    # 39.98 * 0.0725 = 2.89855 -> 2.90 ; 12.50 * 0.0725 = 0.90625 -> 0.91
    assert [line.tax.amount for line in quote.lines] == [Decimal("2.90"), Decimal("0.91")]
    assert quote.tax_total == usd("3.81")
    assert quote.total == usd("56.29")
    assert not quote.tax_included


def test_food_is_exempt_in_california(catalog, clock):
    quote = PricingEngine(default_tax_table(), clock=clock).quote(make_order(catalog, BEAN_250=2))
    assert quote.tax_total.is_zero()
    assert quote.total == usd("19.90")


def test_inclusive_region_does_not_add_tax_on_top(catalog, clock):
    order = Order("USD", "GB")
    order.add(catalog.get("MUG-001"), 2)
    quote = PricingEngine(default_tax_table(), clock=clock).quote(order)
    # 25.00 includes 20% VAT: 25 * 0.2 / 1.2 = 4.1666.. -> 4.17
    assert quote.tax_total == usd("4.17")
    assert quote.total == usd("25.00")
    assert quote.lines[0].total == usd("25.00")
    assert quote.tax_included


def test_coupon_codes_are_case_insensitive_and_required(catalog, clock):
    coupon = PercentageDiscount(code="SPRING10", percent=Decimal(10))
    engine = PricingEngine(default_tax_table(), [coupon], clock=clock)
    assert engine.quote(make_order(catalog, MUG_001=2)).discount_total.is_zero()
    quote = engine.quote(make_order(catalog, coupons=[" spring10 "], MUG_001=2))
    assert quote.discount_total == usd("2.50")
    assert [a.code for a in quote.applied_discounts] == ["SPRING10"]


def test_auto_apply_discount_needs_no_code(catalog, clock):
    auto = FixedAmountDiscount(code="WELCOME", amount=usd("3"), auto_apply=True)
    quote = PricingEngine(default_tax_table(), [auto], clock=clock).quote(make_order(catalog, MUG_001=1))
    assert quote.discount_total == usd("3.00")


def test_tax_is_charged_on_discounted_amount(catalog, clock):
    auto = FixedAmountDiscount(code="TEN", amount=usd("10"), auto_apply=True)
    quote = PricingEngine(default_tax_table(), [auto], clock=clock).quote(make_order(catalog, BOOK_042=1))
    assert quote.lines[0].net == usd("14.00")
    assert quote.tax_total == usd("1.02")  # 14.00 * 0.0725 = 1.015 -> 1.02


def test_shipping_threshold_uses_discounted_subtotal(catalog, clock, shipping):
    auto = FixedAmountDiscount(code="FIVE", amount=usd("5"), auto_apply=True)
    order = make_order(catalog, BOOK_042=2)  # gross 48.00, 1080g
    order.add(catalog.get("GIFT-10"), 1)  # gross 58.00
    engine = PricingEngine(default_tax_table(), [auto], shipping=shipping, clock=clock)
    quote = engine.quote(order)
    assert quote.subtotal == usd("58.00")
    assert quote.shipping.is_zero()
    big = FixedAmountDiscount(code="TEN", amount=usd("10"), auto_apply=True)
    quote = PricingEngine(default_tax_table(), [big], shipping=shipping, clock=clock).quote(order)
    assert quote.shipping == usd("9.00")


def test_per_order_rounding_option(catalog, clock):
    order = Order("USD", "US-NY")
    for i in range(3):
        order.add(Product(f"PIN-{i}", "Pin", usd("0.13")), 1)
    per_line = PricingEngine(default_tax_table(), clock=clock).quote(order)
    per_order = PricingEngine(default_tax_table(), rounding=TaxRounding.PER_ORDER, clock=clock).quote(order)
    assert per_line.tax_total == usd("0.03")  # 0.0052 -> 0.01 each
    assert per_order.tax_total == usd("0.02")  # 0.0156 -> 0.02


def test_expired_coupon_is_not_applied(catalog, clock):
    coupon = PercentageDiscount(code="FLASH", percent=Decimal(30), expires_at=clock.now() + timedelta(minutes=5))
    engine = PricingEngine(default_tax_table(), [coupon], clock=clock)
    order = make_order(catalog, coupons=["FLASH"], MUG_001=1)
    assert not engine.quote(order).discount_total.is_zero()
    clock.advance(timedelta(minutes=5))
    assert engine.quote(order).discount_total.is_zero()


def test_unknown_region(catalog, clock):
    with pytest.raises(TaxConfigError):
        PricingEngine(default_tax_table(), clock=clock).quote(make_order(catalog, region="FR", MUG_001=1))


def test_currency_mismatch_line_is_rejected(clock):
    order = Order("USD", "US-CA")
    order.lines.append(LineItem(Product("E-1", "Euro item", Money.of("1", "EUR")), 1))
    with pytest.raises(CurrencyMismatchError):
        PricingEngine(default_tax_table(), clock=clock).quote(order)


def test_empty_order_quotes_zero(clock):
    quote = PricingEngine(default_tax_table(), clock=clock).quote(Order("USD", "US-CA"))
    assert quote.total == usd("0") and quote.lines == ()


def test_line_totals_add_up_to_quote_total(catalog, clock):
    coupon = PercentageDiscount(code="ODD", percent=Decimal("12.5"), auto_apply=True)
    quote = PricingEngine(default_tax_table(), [coupon], clock=clock).quote(
        make_order(catalog, TEE_001=3, MUG_001=2, BOOK_042=1)
    )
    assert sum((line.total.amount for line in quote.lines), Decimal(0)) == quote.total.amount
