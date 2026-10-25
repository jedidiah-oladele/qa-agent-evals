from datetime import UTC, datetime
from decimal import Decimal

from shopcore import (
    FixedAmountDiscount,
    FixedClock,
    LineItem,
    Money,
    Order,
    PercentageDiscount,
    PricingEngine,
    Product,
    apply_discounts,
    default_tax_table,
)

NOW = datetime(2026, 5, 2, 9, 30, tzinfo=UTC)


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


THROW = Product("THROW-1", "Wool throw", usd("25.00"), category="home")
CANDLE = Product("CANDLE-1", "Soy candle", usd("24.99"), category="home")
PAN = Product("PAN-1", "Skillet", usd("25.00"), category="kitchen")
APRON = Product("APRON-1", "Apron", usd("25.00"), category="apparel")
SOCKS = Product("SOCKS-1", "Socks", usd("10.00"), category="apparel")


def test_percentage_discount_applies_when_subtotal_equals_minimum():
    lines = [LineItem(THROW, 2)]  # 50.00
    discount = PercentageDiscount(code="SPEND50", percent=Decimal(10), min_subtotal=usd("50.00"))
    result = apply_discounts(lines, [discount], now=NOW)
    assert result.total("USD") == usd("5.00")
    assert [a.code for a in result.applied] == ["SPEND50"]


def test_fixed_discount_applies_when_subtotal_equals_minimum():
    lines = [LineItem(THROW, 1), LineItem(PAN, 1)]  # 50.00
    discount = FixedAmountDiscount(code="TAKE7", amount=usd("7.50"), min_subtotal=usd("50.00"))
    result = apply_discounts(lines, [discount], now=NOW)
    assert result.total("USD") == usd("7.50")


def test_quote_with_threshold_coupon_exactly_met():
    coupon = PercentageDiscount(code="SPEND50", percent=Decimal(10), min_subtotal=usd("50.00"))
    engine = PricingEngine(default_tax_table(), [coupon], clock=FixedClock(NOW))
    order = Order("USD", "US-OR", coupon_codes=("spend50",))
    order.add(THROW, 2)
    quote = engine.quote(order)
    assert quote.discount_total == usd("5.00")
    assert quote.total == usd("45.00")


def test_zero_decimal_currency_threshold_is_inclusive():
    bowl = Product("BOWL-1", "Rice bowl", Money.of("2500", "JPY"))
    discount = FixedAmountDiscount(code="YEN500", amount=Money.of("500", "JPY"), min_subtotal=Money.of("5000", "JPY"))
    result = apply_discounts([LineItem(bowl, 2)], [discount], now=NOW)
    assert result.total("JPY") == Money.of("500", "JPY")


def test_threshold_uses_gross_even_after_an_earlier_discount_at_the_boundary():
    lines = [LineItem(THROW, 2)]  # gross 50.00
    first = FixedAmountDiscount(code="A-WELCOME", amount=usd("5"), priority=1)
    second = FixedAmountDiscount(code="B-SPEND50", amount=usd("5"), priority=2, min_subtotal=usd("50.00"))
    result = apply_discounts(lines, [first, second], now=NOW)
    assert [a.code for a in result.applied] == ["A-WELCOME", "B-SPEND50"]
    assert result.total("USD") == usd("10.00")


def test_category_discount_threshold_counts_the_whole_order_at_the_boundary():
    lines = [LineItem(APRON, 1), LineItem(PAN, 1)]  # 50.00, only 25.00 of it kitchen
    discount = PercentageDiscount(code="KITCHEN20", percent=Decimal(20), category="kitchen", min_subtotal=usd("50.00"))
    result = apply_discounts(lines, [discount], now=NOW)
    assert [m.amount for m in result.per_line] == [Decimal("0.00"), Decimal("5.00")]


# -- guards: behaviour that was already right must stay right ---------------


def test_one_cent_below_minimum_gets_no_discount():
    lines = [LineItem(THROW, 1), LineItem(CANDLE, 1)]  # 49.99
    percentage = PercentageDiscount(code="SPEND50", percent=Decimal(10), min_subtotal=usd("50.00"))
    fixed = FixedAmountDiscount(code="TAKE7", amount=usd("7.50"), min_subtotal=usd("50.00"))
    assert apply_discounts(lines, [percentage], now=NOW).total("USD").is_zero()
    assert apply_discounts(lines, [fixed], now=NOW).total("USD").is_zero()


def test_threshold_uses_gross_not_the_already_discounted_amount():
    lines = [LineItem(THROW, 2), LineItem(SOCKS, 1)]  # gross 60.00
    first = FixedAmountDiscount(code="A-TEN", amount=usd("10"), priority=1)
    second = PercentageDiscount(code="B-PCT", percent=Decimal(10), priority=2, min_subtotal=usd("55"))
    result = apply_discounts(lines, [first, second], now=NOW)
    # 60.00 - 10.00 leaves 50.00, below 55, but the threshold is on the gross 60.00
    assert result.total("USD") == usd("15.00")


def test_category_discount_threshold_counts_lines_outside_the_category():
    lines = [LineItem(APRON, 1), LineItem(SOCKS, 1), LineItem(PAN, 1)]  # 60.00, 25.00 of it kitchen
    discount = PercentageDiscount(code="KITCHEN20", percent=Decimal(20), category="kitchen", min_subtotal=usd("40"))
    assert apply_discounts(lines, [discount], now=NOW).total("USD") == usd("5.00")


def test_no_minimum_means_always_eligible():
    discount = FixedAmountDiscount(code="ANY", amount=usd("1"))
    assert apply_discounts([LineItem(SOCKS, 1)], [discount], now=NOW).total("USD") == usd("1.00")
