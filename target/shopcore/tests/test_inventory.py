import pytest

from shopcore import InsufficientStockError, Inventory, ReservationError, ReservationStatus, UnknownSkuError


@pytest.fixture
def inventory(clock):
    inv = Inventory(clock=clock)
    inv.set_stock("TEE-001", 10)
    inv.set_stock("MUG-001", 3)
    return inv


def test_reserve_reduces_availability_not_on_hand(inventory):
    reservation = inventory.reserve("TEE-001", 4)
    assert reservation.id == "RSV-000001"
    assert reservation.status is ReservationStatus.ACTIVE
    assert inventory.on_hand("TEE-001") == 10
    assert inventory.reserved("TEE-001") == 4
    assert inventory.available("TEE-001") == 6


def test_reservation_ids_are_sequential(inventory):
    ids = [inventory.reserve("TEE-001", 1).id for _ in range(3)]
    assert ids == ["RSV-000001", "RSV-000002", "RSV-000003"]


def test_cannot_oversell(inventory):
    inventory.reserve("MUG-001", 2)
    with pytest.raises(InsufficientStockError) as info:
        inventory.reserve("MUG-001", 2)
    assert (info.value.requested, info.value.available) == (2, 1)


def test_unknown_sku(inventory):
    with pytest.raises(UnknownSkuError):
        inventory.reserve("NOPE", 1)
    with pytest.raises(UnknownSkuError):
        inventory.available("NOPE")


@pytest.mark.parametrize("qty", [0, -2])
def test_reserve_needs_positive_quantity(inventory, qty):
    with pytest.raises(ValueError):
        inventory.reserve("TEE-001", qty)


def test_release_returns_units_and_is_idempotent(inventory):
    reservation = inventory.reserve("MUG-001", 3)
    inventory.release(reservation.id)
    inventory.release(reservation.id)
    assert reservation.status is ReservationStatus.RELEASED
    assert inventory.available("MUG-001") == 3


def test_commit_removes_units_from_on_hand(inventory):
    reservation = inventory.reserve("TEE-001", 4)
    inventory.commit(reservation.id)
    assert inventory.on_hand("TEE-001") == 6
    assert inventory.reserved("TEE-001") == 0
    assert inventory.available("TEE-001") == 6


def test_commit_twice_or_after_release_fails(inventory):
    a = inventory.reserve("TEE-001", 1)
    inventory.commit(a.id)
    with pytest.raises(ReservationError):
        inventory.commit(a.id)
    with pytest.raises(ReservationError):
        inventory.release(a.id)
    b = inventory.reserve("TEE-001", 1)
    inventory.release(b.id)
    with pytest.raises(ReservationError):
        inventory.commit(b.id)


def test_unknown_reservation(inventory):
    with pytest.raises(ReservationError):
        inventory.get("RSV-999999")


def test_reserve_many_is_all_or_nothing(inventory):
    with pytest.raises(InsufficientStockError):
        inventory.reserve_many({"TEE-001": 2, "MUG-001": 4})
    assert inventory.available("TEE-001") == 10
    reservations = inventory.reserve_many({"TEE-001": 2, "MUG-001": 3})
    assert [r.sku for r in reservations] == ["TEE-001", "MUG-001"]
    assert inventory.available("MUG-001") == 0


def test_stock_management(inventory):
    inventory.add_stock("MUG-001", 2)
    inventory.add_stock("NEW-1", 1)
    assert inventory.on_hand("MUG-001") == 5
    assert inventory.on_hand("NEW-1") == 1
    with pytest.raises(ValueError):
        inventory.set_stock("MUG-001", -1)
    with pytest.raises(ValueError):
        inventory.add_stock("MUG-001", 0)


def test_active_reservations_filter(inventory):
    a = inventory.reserve("TEE-001", 1)
    inventory.reserve("MUG-001", 1)
    inventory.release(a.id)
    assert [r.sku for r in inventory.active_reservations()] == ["MUG-001"]
    assert inventory.active_reservations("TEE-001") == []
