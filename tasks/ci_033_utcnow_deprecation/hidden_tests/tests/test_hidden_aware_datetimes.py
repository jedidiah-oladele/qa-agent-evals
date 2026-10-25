import time
import warnings
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from shopcore import (
    FixedClock,
    Inventory,
    LineItem,
    Money,
    Order,
    PercentageDiscount,
    PricingEngine,
    Product,
    ReservationStatus,
    default_tax_table,
)
from shopcore.clock import expiry_after, utc_now
from shopcore.discounts import parse_expiry

START = datetime(2026, 3, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def local_tz(monkeypatch):
    def use(name: str) -> None:
        monkeypatch.setenv("TZ", name)
        time.tzset()

    yield use
    monkeypatch.undo()
    time.tzset()


def deprecations(caught) -> list[str]:
    return [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]


def assert_utc(moment: datetime) -> None:
    assert moment.tzinfo is not None
    assert moment.utcoffset() == timedelta(0)


def test_utc_now_is_aware_and_emits_no_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        now = utc_now()
    assert deprecations(caught) == []
    assert_utc(now)
    assert abs(now - datetime.now(UTC)) < timedelta(minutes=1)


def test_expiry_after_without_start_is_aware(local_tz):
    local_tz("Pacific/Kiritimati")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        expiry = expiry_after(timedelta(minutes=30))
    assert deprecations(caught) == []
    assert_utc(expiry)
    assert abs(expiry - (datetime.now(UTC) + timedelta(minutes=30))) < timedelta(minutes=1)


def test_extend_uses_the_inventory_clock():
    clock = FixedClock(START)
    inventory = Inventory(clock=clock, default_ttl=timedelta(minutes=15))
    inventory.set_stock("LAMP-7", 3)
    reservation = inventory.reserve("LAMP-7", 1)
    clock.advance(timedelta(minutes=5))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        inventory.extend(reservation.id, timedelta(minutes=30))
    assert deprecations(caught) == []
    assert reservation.expires_at == datetime(2026, 3, 14, 12, 35, tzinfo=UTC)


def test_extended_reservation_expires_at_the_new_deadline():
    clock = FixedClock(START)
    inventory = Inventory(clock=clock, default_ttl=timedelta(minutes=15))
    inventory.set_stock("LAMP-7", 3)
    reservation = inventory.reserve("LAMP-7", 2)
    clock.advance(timedelta(minutes=14))
    inventory.extend(reservation.id, timedelta(minutes=10))
    clock.advance(timedelta(minutes=9))
    assert inventory.available("LAMP-7") == 1
    clock.advance(timedelta(minutes=1))
    assert inventory.expire_stale() == [reservation]
    assert reservation.status is ReservationStatus.EXPIRED
    assert inventory.available("LAMP-7") == 3


def test_extend_works_with_a_non_utc_local_time_zone(local_tz):
    local_tz("America/Los_Angeles")
    clock = FixedClock(START)
    inventory = Inventory(clock=clock)
    inventory.set_stock("LAMP-7", 1)
    reservation = inventory.reserve("LAMP-7", 1, ttl=timedelta(minutes=5))
    inventory.extend(reservation.id, timedelta(hours=2))
    clock.advance(timedelta(hours=1))
    assert inventory.active_reservations("LAMP-7") == [reservation]


@pytest.mark.parametrize("zone", ["Asia/Kolkata", "America/Los_Angeles"])
def test_offsetless_time_is_utc_whatever_the_local_zone(local_tz, zone):
    local_tz(zone)
    expiry = parse_expiry("2026-03-31T18:00")
    assert expiry == datetime(2026, 3, 31, 18, 0, tzinfo=UTC)
    assert_utc(expiry)


def test_date_only_expiry_is_the_following_utc_midnight(local_tz):
    local_tz("Pacific/Kiritimati")
    expiry = parse_expiry(" 2026-03-31 ")
    assert expiry == datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    assert_utc(expiry)


def test_naive_datetime_from_config_is_treated_as_utc(local_tz):
    local_tz("Asia/Kolkata")
    expiry = parse_expiry(datetime(2026, 3, 31, 18, 0))
    assert expiry == datetime(2026, 3, 31, 18, 0, tzinfo=UTC)
    assert_utc(expiry)


def test_offset_strings_are_normalised_to_utc():
    expiry = parse_expiry("2026-03-31T18:00:00-05:00")
    assert expiry == datetime(2026, 3, 31, 23, 0, tzinfo=UTC)


def test_pricing_engine_ignores_a_config_discount_that_has_ended():
    order = Order("USD", "US-OR")
    order.add(Product("LAMP-7", "Desk lamp", Money.of("40.00", "USD")), 1)
    expired = PercentageDiscount(code="WINTER", percent=Decimal(25), auto_apply=True, expires_at=parse_expiry("2026-03-13"))
    running = PercentageDiscount(
        code="SPRING", percent=Decimal(10), auto_apply=True, expires_at=parse_expiry("2026-03-14T12:00:01")
    )
    engine = PricingEngine(default_tax_table(), [expired, running], clock=FixedClock(START))
    quote = engine.quote(order)
    assert [a.code for a in quote.applied_discounts] == ["SPRING"]
    assert quote.total == Money.of("36.00", "USD")


def test_reserve_and_default_ttl_unchanged():
    clock = FixedClock(START)
    inventory = Inventory(clock=clock, default_ttl=timedelta(minutes=15))
    inventory.set_stock("LAMP-7", 1)
    reservation = inventory.reserve("LAMP-7", 1)
    assert reservation.expires_at == START + timedelta(minutes=15)
    with pytest.raises(ValueError):
        expiry_after(timedelta(0), START)
