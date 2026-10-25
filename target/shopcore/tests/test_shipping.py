import pytest

from shopcore import LineItem, Money, ShippingPolicy, WeightTier


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


@pytest.fixture
def policy():
    return ShippingPolicy(
        tiers=(WeightTier(2000, usd("8.00")), WeightTier(500, usd("4.00"))),
        free_over=usd("75"),
        per_extra_kg=usd("1.50"),
    )


def test_tiers_are_sorted_and_inclusive(policy, catalog):
    assert [t.max_grams for t in policy.tiers] == [500, 2000]
    lines = [LineItem(catalog.get("TEE-001"), 2)]  # 360g
    assert policy.quote(lines, usd("39.98")) == usd("4.00")


def test_exact_tier_boundary_uses_that_tier(catalog):
    policy = ShippingPolicy(tiers=(WeightTier(360, usd("3.00")), WeightTier(1000, usd("6.00"))))
    assert policy.quote([LineItem(catalog.get("TEE-001"), 2)], usd("1")) == usd("3.00")


def test_free_over_uses_given_discounted_subtotal(policy, catalog):
    lines = [LineItem(catalog.get("BOOK-042"), 4)]  # 2160g, gross 96.00
    assert policy.quote(lines, usd("74.99")) == usd("9.50")
    assert policy.quote(lines, usd("75.00")).is_zero()


def test_extra_kilograms_are_rounded_up(policy, catalog):
    lines = [LineItem(catalog.get("BOOK-042"), 6)]  # 3240g -> 1240g over -> 2 extra kg
    assert policy.quote(lines, usd("10")) == usd("11.00")


def test_weightless_orders_ship_free(policy, catalog):
    assert policy.quote([LineItem(catalog.get("GIFT-10"), 3)], usd("30")).is_zero()


def test_too_heavy_without_extra_rate(catalog):
    policy = ShippingPolicy(tiers=(WeightTier(500, usd("4.00")),))
    with pytest.raises(ValueError, match="exceeds"):
        policy.quote([LineItem(catalog.get("BOOK-042"), 2)], usd("1"))


def test_needs_a_tier():
    with pytest.raises(ValueError):
        ShippingPolicy(tiers=())
