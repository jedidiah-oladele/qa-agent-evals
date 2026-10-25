import os
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from shopcore import (
    FixedAmountDiscount,
    FixedClock,
    Money,
    Order,
    PercentageDiscount,
    PricingEngine,
    Product,
    default_tax_table,
)

LAST_DAY = date(2026, 3, 14)
NEXT_MIDNIGHT_UTC = datetime(2026, 3, 15, 0, 0, tzinfo=UTC)


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


@pytest.fixture
def local_zone():
    """Switch the process-local time zone for one test, then restore it."""
    saved = os.environ.get("TZ")

    def switch(name: str) -> None:
        os.environ["TZ"] = name
        time.tzset()

    yield switch
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


@pytest.mark.parametrize(
    "zone", ["Pacific/Kiritimati", "Pacific/Pago_Pago", "Asia/Kolkata", "America/Los_Angeles", "Europe/Berlin"]
)
def test_valid_through_ends_at_midnight_utc_in_any_local_zone(local_zone, zone):
    local_zone(zone)
    coupon = PercentageDiscount(code="SPRING", percent=Decimal(10), valid_through=LAST_DAY)
    assert coupon.ends_at() == NEXT_MIDNIGHT_UTC
    assert coupon.is_active(datetime(2026, 3, 14, 0, 0, tzinfo=UTC))
    assert coupon.is_active(datetime(2026, 3, 14, 12, 0, tzinfo=UTC))
    assert coupon.is_active(NEXT_MIDNIGHT_UTC - timedelta(microseconds=1))
    assert not coupon.is_active(NEXT_MIDNIGHT_UTC)


def test_last_second_of_the_day_still_counts():
    coupon = FixedAmountDiscount(code="LATE", amount=usd("2"), valid_through=LAST_DAY)
    assert coupon.is_active(datetime(2026, 3, 14, 23, 59, 30, tzinfo=UTC))
    assert not coupon.is_active(datetime(2026, 3, 15, 0, 0, 1, tzinfo=UTC))


def test_quote_on_the_last_day_from_a_far_east_server(local_zone):
    local_zone("Pacific/Kiritimati")
    coupon = PercentageDiscount(code="SPRING", percent=Decimal(10), valid_through=LAST_DAY, auto_apply=True)
    clock = FixedClock(datetime(2026, 3, 14, 15, 30, tzinfo=UTC))
    engine = PricingEngine(default_tax_table(), [coupon], clock=clock)
    order = Order("USD", "US-OR")
    order.add(Product("KITE-1", "Kite", usd("30.00")), 1)
    assert engine.quote(order).discount_total == usd("3.00")
    clock.set(NEXT_MIDNIGHT_UTC)
    assert engine.quote(order).discount_total.is_zero()


def test_expires_at_still_wins_when_earlier(local_zone):
    local_zone("Pacific/Pago_Pago")
    cutoff = datetime(2026, 3, 14, 18, 0, tzinfo=UTC)
    coupon = FixedAmountDiscount(code="FLASH", amount=usd("5"), expires_at=cutoff, valid_through=LAST_DAY)
    assert coupon.ends_at() == cutoff
    later = FixedAmountDiscount(code="SLOW", amount=usd("5"), expires_at=cutoff + timedelta(days=3), valid_through=LAST_DAY)
    assert later.ends_at() == NEXT_MIDNIGHT_UTC


def test_discounts_without_an_end_never_expire():
    coupon = FixedAmountDiscount(code="EVER", amount=usd("1"))
    assert coupon.ends_at() is None
    assert coupon.is_active(datetime(2099, 1, 1, tzinfo=UTC))
