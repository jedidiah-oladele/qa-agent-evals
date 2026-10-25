import random
from datetime import UTC, datetime

import pytest

from shopcore import FixedClock, Inventory


@pytest.fixture
def clock():
    return FixedClock(datetime(2026, 7, 1, 9, 0, tzinfo=UTC))


def make(clock, stock=10):
    inv = Inventory(clock=clock)
    inv.set_stock("SKU-1", stock)
    return inv


def test_ids_do_not_depend_on_the_global_random_state(clock):
    # Load tests and simulations seed the global RNG for reproducible traffic.
    inventory = make(clock)
    random.seed(4242)
    first = inventory.reserve("SKU-1", 1)
    random.seed(4242)
    second = inventory.reserve("SKU-1", 1)
    assert first.id != second.id
    assert inventory.get(first.id) is first
    assert inventory.get(second.id) is second
    assert inventory.reserved("SKU-1") == 2


def test_workers_with_identically_seeded_rngs_get_distinct_ids(clock):
    workers = [make(clock), make(clock)]
    ids = []
    for worker in workers:
        random.seed(1234)
        ids += [worker.reserve("SKU-1", 1).id for _ in range(3)]
    assert len(set(ids)) == 6


def test_thousands_of_holds_are_all_tracked(clock):
    inventory = make(clock, stock=5000)
    holds = [inventory.reserve("SKU-1", 1) for _ in range(3000)]
    assert len({h.id for h in holds}) == 3000
    assert inventory.reserved("SKU-1") == 3000
    for hold in holds:
        inventory.commit(hold.id)
    assert inventory.on_hand("SKU-1") == 2000


def test_ids_keep_the_reservation_prefix(clock):
    reservation = make(clock).reserve("SKU-1", 2)
    assert isinstance(reservation.id, str)
    assert reservation.id.startswith("RSV-")
