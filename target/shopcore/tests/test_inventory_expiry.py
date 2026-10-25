from datetime import timedelta

import pytest

from shopcore import Inventory, ReservationError, ReservationStatus


@pytest.fixture
def inventory(clock):
    inv = Inventory(clock=clock, default_ttl=timedelta(minutes=15))
    inv.set_stock("TEE-001", 5)
    return inv


def test_reservation_gets_default_ttl(inventory, clock):
    reservation = inventory.reserve("TEE-001", 2)
    assert reservation.created_at == clock.now()
    assert reservation.expires_at == clock.now() + timedelta(minutes=15)


def test_explicit_ttl_overrides_default(inventory, clock):
    reservation = inventory.reserve("TEE-001", 1, ttl=timedelta(minutes=2))
    assert reservation.expires_at == clock.now() + timedelta(minutes=2)


def test_no_ttl_means_no_expiry(clock):
    inventory = Inventory(clock=clock)
    inventory.set_stock("TEE-001", 1)
    reservation = inventory.reserve("TEE-001", 1)
    clock.advance(timedelta(days=30))
    assert reservation.expires_at is None
    assert inventory.available("TEE-001") == 0


def test_expired_reservations_stop_counting(inventory, clock):
    inventory.reserve("TEE-001", 4)
    clock.advance(timedelta(minutes=14, seconds=59))
    assert inventory.available("TEE-001") == 1
    clock.advance(timedelta(seconds=1))
    assert inventory.available("TEE-001") == 5


def test_reserve_reclaims_expired_stock(inventory, clock):
    first = inventory.reserve("TEE-001", 5)
    clock.advance(timedelta(minutes=16))
    second = inventory.reserve("TEE-001", 5)
    assert first.status is ReservationStatus.EXPIRED
    assert second.status is ReservationStatus.ACTIVE


def test_commit_after_expiry_fails_and_marks_expired(inventory, clock):
    reservation = inventory.reserve("TEE-001", 2)
    clock.advance(timedelta(minutes=15))
    with pytest.raises(ReservationError, match="expired"):
        inventory.commit(reservation.id)
    assert reservation.status is ReservationStatus.EXPIRED
    assert inventory.on_hand("TEE-001") == 5


def test_release_after_expiry_is_a_noop(inventory, clock):
    reservation = inventory.reserve("TEE-001", 2)
    clock.advance(timedelta(hours=1))
    inventory.release(reservation.id)
    assert reservation.status is ReservationStatus.EXPIRED
    assert inventory.available("TEE-001") == 5


def test_expire_stale_returns_newly_expired_only(inventory, clock):
    a = inventory.reserve("TEE-001", 1, ttl=timedelta(minutes=1))
    inventory.reserve("TEE-001", 1, ttl=timedelta(minutes=10))
    clock.advance(timedelta(minutes=5))
    assert [r.id for r in inventory.expire_stale()] == [a.id]
    assert inventory.expire_stale() == []


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
def test_ttl_must_be_positive(inventory, ttl):
    with pytest.raises(ValueError):
        inventory.reserve("TEE-001", 1, ttl=ttl)


def test_default_ttl_must_be_positive(clock):
    with pytest.raises(ValueError):
        Inventory(clock=clock, default_ttl=timedelta(0))
