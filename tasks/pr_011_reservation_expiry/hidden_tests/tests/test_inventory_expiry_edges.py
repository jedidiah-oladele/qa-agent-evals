from datetime import timedelta

import pytest

from shopcore import InsufficientStockError, Inventory, ReservationError, ReservationStatus


@pytest.fixture
def inventory(clock):
    inv = Inventory(clock=clock, default_ttl=timedelta(minutes=20))
    inv.set_stock("LAMP-077", 6)
    inv.set_stock("SHADE-078", 3)
    return inv


def test_reserve_many_applies_explicit_ttl_to_every_item(inventory, clock):
    reservations = inventory.reserve_many({"LAMP-077": 2, "SHADE-078": 1}, ttl=timedelta(minutes=3))
    assert [r.expires_at for r in reservations] == [clock.now() + timedelta(minutes=3)] * 2
    clock.advance(timedelta(minutes=3))
    assert inventory.available("LAMP-077") == 6
    assert inventory.available("SHADE-078") == 3


def test_reserve_many_uses_default_ttl_without_override(inventory, clock):
    reservations = inventory.reserve_many({"LAMP-077": 1, "SHADE-078": 1})
    assert {r.expires_at for r in reservations} == {clock.now() + timedelta(minutes=20)}


def test_reserve_many_reclaims_expired_stock(inventory, clock):
    inventory.reserve_many({"LAMP-077": 6, "SHADE-078": 3}, ttl=timedelta(minutes=1))
    clock.advance(timedelta(minutes=2))
    again = inventory.reserve_many({"LAMP-077": 6, "SHADE-078": 3})
    assert [r.status for r in again] == [ReservationStatus.ACTIVE] * 2
    assert inventory.available("LAMP-077") == 0


def test_reserve_many_rejects_non_positive_ttl_without_reserving(inventory):
    with pytest.raises(ValueError):
        inventory.reserve_many({"LAMP-077": 1, "SHADE-078": 1}, ttl=timedelta(0))
    assert inventory.active_reservations() == []
    assert inventory.available("LAMP-077") == 6


def test_active_reservations_exclude_expired_before_any_sweep(inventory, clock):
    short = inventory.reserve("LAMP-077", 1, ttl=timedelta(minutes=5))
    long = inventory.reserve("LAMP-077", 1, ttl=timedelta(minutes=30))
    clock.advance(timedelta(minutes=5))
    assert [r.id for r in inventory.active_reservations("LAMP-077")] == [long.id]
    assert [r.id for r in inventory.active_reservations()] == [long.id]
    assert inventory.reserved("LAMP-077") == 1
    # Reading never needs a sweep, but the sweep still reports the expiry once.
    assert [r.id for r in inventory.expire_stale()] == [short.id]


def test_commit_one_second_before_expiry_succeeds(inventory, clock):
    reservation = inventory.reserve("LAMP-077", 2)
    clock.advance(timedelta(minutes=19, seconds=59))
    inventory.commit(reservation.id)
    assert reservation.status is ReservationStatus.COMMITTED
    assert inventory.on_hand("LAMP-077") == 4


def test_committed_reservation_never_expires(inventory, clock):
    reservation = inventory.reserve("LAMP-077", 2)
    inventory.commit(reservation.id)
    clock.advance(timedelta(hours=2))
    assert inventory.expire_stale() == []
    assert reservation.status is ReservationStatus.COMMITTED
    assert inventory.on_hand("LAMP-077") == 4
    assert inventory.available("LAMP-077") == 4


def test_released_reservation_is_not_reported_as_expired(inventory, clock):
    reservation = inventory.reserve("LAMP-077", 2)
    inventory.release(reservation.id)
    clock.advance(timedelta(hours=1))
    assert inventory.expire_stale() == []
    assert reservation.status is ReservationStatus.RELEASED


def test_commit_of_swept_reservation_still_fails(inventory, clock):
    reservation = inventory.reserve("SHADE-078", 3)
    clock.advance(timedelta(minutes=25))
    inventory.expire_stale()
    with pytest.raises(ReservationError):
        inventory.commit(reservation.id)
    assert inventory.on_hand("SHADE-078") == 3


def test_explicit_ttl_without_default(clock):
    inventory = Inventory(clock=clock)
    inventory.set_stock("LAMP-077", 2)
    reservation = inventory.reserve("LAMP-077", 2, ttl=timedelta(seconds=90))
    assert reservation.expires_at == clock.now() + timedelta(seconds=90)
    clock.advance(timedelta(seconds=90))
    assert inventory.available("LAMP-077") == 2


def test_longer_explicit_ttl_overrides_shorter_default(inventory, clock):
    reservation = inventory.reserve("LAMP-077", 6, ttl=timedelta(hours=1))
    clock.advance(timedelta(minutes=45))
    assert reservation.status is ReservationStatus.ACTIVE
    with pytest.raises(InsufficientStockError):
        inventory.reserve("LAMP-077", 1)


def test_unexpired_reservations_still_block_stock(inventory, clock):
    inventory.reserve("SHADE-078", 3)
    clock.advance(timedelta(minutes=10))
    with pytest.raises(InsufficientStockError):
        inventory.reserve("SHADE-078", 1)
