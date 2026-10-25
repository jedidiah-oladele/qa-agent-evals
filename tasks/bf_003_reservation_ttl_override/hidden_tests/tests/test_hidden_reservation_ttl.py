from datetime import UTC, datetime, timedelta

import pytest

from shopcore import FixedClock, InsufficientStockError, Inventory, ReservationStatus

START = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
WHOLESALE_HOLD = timedelta(minutes=150)


@pytest.fixture
def clock():
    return FixedClock(START)


@pytest.fixture
def store(clock):
    inv = Inventory(clock=clock, default_ttl=timedelta(minutes=15))
    inv.set_stock("CRATE-1", 5)
    inv.set_stock("PALLET-1", 3)
    return inv


def test_explicit_ttl_longer_than_default_is_used(store, clock):
    reservation = store.reserve("CRATE-1", 2, ttl=WHOLESALE_HOLD)
    assert reservation.expires_at == START + WHOLESALE_HOLD


def test_long_hold_keeps_stock_until_its_own_expiry(store, clock):
    store.reserve("CRATE-1", 4, ttl=WHOLESALE_HOLD)
    clock.advance(timedelta(minutes=30))
    assert store.available("CRATE-1") == 1
    with pytest.raises(InsufficientStockError):
        store.reserve("CRATE-1", 2)
    clock.set(START + WHOLESALE_HOLD - timedelta(seconds=1))
    assert store.available("CRATE-1") == 1
    clock.advance(timedelta(seconds=1))
    assert store.available("CRATE-1") == 5


def test_long_hold_can_be_committed_after_the_default_window(store, clock):
    reservation = store.reserve("CRATE-1", 3, ttl=WHOLESALE_HOLD)
    clock.advance(timedelta(hours=1))
    store.commit(reservation.id)
    assert reservation.status is ReservationStatus.COMMITTED
    assert store.on_hand("CRATE-1") == 2


def test_reserve_many_uses_a_longer_explicit_ttl(store, clock):
    day = timedelta(minutes=1440)
    reservations = store.reserve_many({"CRATE-1": 1, "PALLET-1": 2}, ttl=day)
    assert [r.expires_at for r in reservations] == [START + day, START + day]
    clock.advance(timedelta(hours=1))
    assert store.expire_stale() == []
    assert store.available("PALLET-1") == 1


# -- guards: behaviour that was already right must stay right ---------------


def test_shorter_explicit_ttl_still_wins_over_default(store, clock):
    reservations = store.reserve_many({"CRATE-1": 1}, ttl=timedelta(minutes=3))
    assert reservations[0].expires_at == START + timedelta(minutes=3)
    clock.advance(timedelta(minutes=3))
    assert store.available("CRATE-1") == 5


def test_default_ttl_applies_when_no_ttl_given(store):
    assert store.reserve("CRATE-1", 1).expires_at == START + timedelta(minutes=15)


@pytest.mark.parametrize("default_ttl", [None, timedelta(minutes=15)])
def test_zero_ttl_is_rejected_with_or_without_default(clock, default_ttl):
    inv = Inventory(clock=clock, default_ttl=default_ttl)
    inv.set_stock("CRATE-1", 1)
    with pytest.raises(ValueError):
        inv.reserve("CRATE-1", 1, ttl=timedelta(0))
    with pytest.raises(ValueError):
        inv.reserve_many({"CRATE-1": 1}, ttl=timedelta(seconds=-5))


def test_without_default_explicit_ttl_is_used_and_none_never_expires(clock):
    inv = Inventory(clock=clock)
    inv.set_stock("CRATE-1", 2)
    timed = inv.reserve("CRATE-1", 1, ttl=WHOLESALE_HOLD)
    forever = inv.reserve("CRATE-1", 1)
    assert timed.expires_at == START + WHOLESALE_HOLD
    assert forever.expires_at is None
