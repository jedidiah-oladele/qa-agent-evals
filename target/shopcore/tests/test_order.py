import pytest

from shopcore import CurrencyMismatchError, LineItem, Money, Order, Product


def test_add_merges_lines_for_same_sku(catalog):
    order = Order("USD", "US-CA")
    order.add(catalog.get("TEE-001"), 2)
    order.add(catalog.get("MUG-001"))
    order.add(catalog.get("TEE-001"), 1)
    assert [(line.sku, line.quantity) for line in order.lines] == [("TEE-001", 3), ("MUG-001", 1)]


def test_subtotal_and_weight(catalog):
    order = Order("USD", "US-CA")
    order.add(catalog.get("TEE-001"), 2)
    order.add(catalog.get("MUG-001"), 1)
    assert order.subtotal() == Money.of("52.48", "USD")
    assert order.total_weight_grams() == 710


def test_remove_line(catalog):
    order = Order("USD", "US-CA")
    order.add(catalog.get("TEE-001"))
    order.remove("TEE-001")
    assert order.lines == []
    assert order.subtotal() == Money.zero("USD")


def test_currency_mismatch_on_add():
    order = Order("EUR", "DE")
    with pytest.raises(CurrencyMismatchError):
        order.add(Product("A", "x", Money.of("1", "USD")))


@pytest.mark.parametrize("quantity", [0, -1])
def test_line_quantity_must_be_positive(catalog, quantity):
    with pytest.raises(ValueError):
        LineItem(catalog.get("TEE-001"), quantity)


def test_line_quantity_must_be_int(catalog):
    with pytest.raises(TypeError):
        LineItem(catalog.get("TEE-001"), 1.5)  # type: ignore[arg-type]
