from datetime import UTC, datetime
from decimal import Decimal

from shopcore import FixedClock, Money, Order, PricingEngine, Product, TaxRegion, default_tax_table


def test_default_tables_do_not_share_registrations():
    first = default_tax_table()
    first.register(TaxRegion("US-CA", Decimal("0.0975")))
    first.register(TaxRegion("ZZ-TEST", Decimal("0.11")))
    second = default_tax_table()
    assert second.get("US-CA").standard_rate == Decimal("0.0725")
    assert "ZZ-TEST" not in second
    assert "ZZ-TEST" in first


def test_customising_one_engines_table_leaves_other_engines_alone():
    clock = FixedClock(datetime(2026, 4, 1, tzinfo=UTC))
    special = PricingEngine(default_tax_table(), clock=clock)
    special.tax_table.register(TaxRegion("US-CA", Decimal("0.0975")))
    standard = PricingEngine(default_tax_table(), clock=clock)
    order = Order("USD", "US-CA")
    order.add(Product("LAMP-1", "Lamp", Money.of("40.00", "USD")), 1)
    assert special.quote(order).tax_total == Money.of("3.90", "USD")
    assert standard.quote(order).tax_total == Money.of("2.90", "USD")


def test_default_table_still_has_every_builtin_region():
    assert default_tax_table().codes() == ["DE", "GB", "JP", "NG", "US-CA", "US-NY", "US-OR"]
