import pytest

from shopcore import Money, Product, UnknownSkuError


def test_lookup_and_membership(catalog):
    assert "TEE-001" in catalog
    assert catalog.get("MUG-001").name == "Enamel mug"
    assert len(catalog) == 5


def test_unknown_sku_raises_keyerror_subclass(catalog):
    with pytest.raises(UnknownSkuError) as info:
        catalog.get("NOPE")
    assert isinstance(info.value, KeyError)
    assert str(info.value) == "NOPE"


def test_duplicate_sku_rejected(catalog):
    with pytest.raises(ValueError, match="duplicate"):
        catalog.add(Product("TEE-001", "Again", Money.of("1", "USD")))


def test_replace_requires_existing_sku(catalog):
    catalog.replace(Product("TEE-001", "Tee v2", Money.of("21", "USD")))
    assert catalog.get("TEE-001").name == "Tee v2"
    with pytest.raises(UnknownSkuError):
        catalog.replace(Product("NEW-1", "New", Money.of("1", "USD")))


def test_by_category(catalog):
    assert [p.sku for p in catalog.by_category("kitchen")] == ["MUG-001"]


@pytest.mark.parametrize("sku", ["", " TEE", "TEE "])
def test_invalid_skus(sku):
    with pytest.raises(ValueError):
        Product(sku, "x", Money.of("1", "USD"))


def test_negative_price_and_weight_rejected():
    with pytest.raises(ValueError):
        Product("A", "x", Money.of("-1", "USD"))
    with pytest.raises(ValueError):
        Product("A", "x", Money.of("1", "USD"), weight_grams=-5)
