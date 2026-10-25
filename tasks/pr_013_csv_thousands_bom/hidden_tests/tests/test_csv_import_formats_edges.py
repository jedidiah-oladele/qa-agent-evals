import io
from decimal import Decimal

import pytest

from shopcore.csv_import import import_products, load_products, normalize_header, parse_price


@pytest.mark.parametrize(
    ("text", "currency", "expected"),
    [
        ("4,321.5", "USD", "4321.5"),
        ("7,654.321", "KWD", "7654.321"),
        ("48,000", "JPY", "48000"),
        ("3,141,592", "USD", "3141592"),
    ],
)
def test_separators_with_any_valid_decimal_places(text, currency, expected):
    assert parse_price(text, currency) == Decimal(expected)


def test_surrounding_whitespace_is_ignored_with_separators():
    assert parse_price("  2,718.28 ", "USD") == Decimal("2718.28")


def test_decimal_places_still_checked_after_removing_separators():
    with pytest.raises(ValueError, match="decimal places"):
        parse_price("6,500.125", "USD")
    with pytest.raises(ValueError, match="decimal places"):
        parse_price("6,500.5", "JPY")


@pytest.mark.parametrize("text", ["8.765,43", "8,765,4", "8,765.", "8,765.4,3"])
def test_other_comma_layouts_are_rejected(text):
    with pytest.raises(ValueError):
        parse_price(text, "USD")


def test_european_decimal_comma_mentions_separators():
    with pytest.raises(ValueError, match="thousands"):
        parse_price("8.765,43", "USD")


def test_bad_grouping_is_reported_per_row():
    source = io.StringIO('sku,name,price\nCAM-310,Camera,"1,23.00"\nCAM-311,Lens,"2,450.00"\n')
    result = import_products(source)
    assert [p.sku for p in result.products] == ["CAM-311"]
    assert len(result.errors) == 1
    error = result.errors[0]
    assert (error.line, error.field) == (2, "price")
    assert "thousands" in error.message


def test_bom_before_padded_header():
    assert normalize_header("\ufeff Unit Price ") == "unit_price"
    result = import_products(io.StringIO("\ufeff SKU , Name , Price \nCAM-312,Tripod,35.00\n"))
    assert result.ok
    assert result.products[0].unit_price.amount == Decimal("35.00")


def test_load_products_without_bom_still_works(tmp_path):
    path = tmp_path / "plain.csv"
    path.write_text("sku,name,price\nCAM-313,Bag,\"1,050.00\"\n", encoding="utf-8")
    result = load_products(path)
    assert result.ok
    assert result.products[0].sku == "CAM-313"
    assert result.products[0].unit_price.amount == Decimal("1050.00")


def test_load_products_bom_file_with_non_ascii_names(tmp_path):
    path = tmp_path / "export.csv"
    path.write_bytes("SKU,Name,Price\r\nCAM-314,Objectif grand-angle \u00e9t\u00e9,\"1,999.90\"\r\n".encode("utf-8-sig"))
    result = load_products(path, currency="EUR")
    assert result.ok
    product = result.products[0]
    assert product.sku == "CAM-314"
    assert product.name.endswith("\u00e9t\u00e9")
    assert product.unit_price.amount == Decimal("1999.90")
    assert product.unit_price.currency == "EUR"
