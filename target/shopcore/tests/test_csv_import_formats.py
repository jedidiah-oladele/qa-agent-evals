import io
from decimal import Decimal

import pytest

from shopcore.csv_import import import_products, load_products, parse_price


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1,234.50", "1234.50"), ("12,345", "12345"), ("1,000,000.00", "1000000.00"), ("999.99", "999.99")],
)
def test_thousands_separators(text, expected):
    assert parse_price(text, "USD") == Decimal(expected)


@pytest.mark.parametrize("text", ["1,23.00", "12,3456", ",123", "1,,234", "1234,567"])
def test_malformed_thousands_separators(text):
    with pytest.raises(ValueError, match="thousands"):
        parse_price(text, "USD")


def test_quoted_price_with_separator_in_csv():
    result = import_products(io.StringIO('sku,name,price\nTV-1,Television,"1,299.00"\n'))
    assert result.products[0].unit_price.amount == Decimal("1299.00")


def test_bom_in_header_is_ignored_for_text_input():
    result = import_products(io.StringIO("\ufeffsku,name,price\nA-1,Thing,1.00\n"))
    assert result.ok
    assert result.products[0].sku == "A-1"


def test_load_products_handles_bom_file(tmp_path):
    path = tmp_path / "export.csv"
    path.write_bytes("sku,name,price\r\nA-1,Thing,\"2,500.00\"\r\n".encode("utf-8-sig"))
    result = load_products(path)
    assert result.ok
    assert result.products[0].unit_price.amount == Decimal("2500.00")
