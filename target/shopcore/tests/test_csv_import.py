import io
from decimal import Decimal

import pytest

from shopcore import CsvFormatError
from shopcore.csv_import import import_products, load_products, normalize_header, parse_price


def run(text: str, **kwargs):
    return import_products(io.StringIO(text), **kwargs)


def test_basic_import():
    result = run("sku,name,price,category,weight_grams\nTEE-1,Tee,19.99,apparel,180\nMUG-1,Mug,12.5,kitchen,\n")
    assert result.ok
    assert [p.sku for p in result.products] == ["TEE-1", "MUG-1"]
    assert result.products[0].unit_price.amount == Decimal("19.99")
    assert result.products[1].weight_grams == 0
    assert result.products[1].tax_category == "standard"


def test_headers_are_normalized_and_reorderable():
    result = run(" Price ,SKU,Name,Tax-Category\n3.00,A-1,Thing,food\n")
    assert result.ok
    assert result.products[0].tax_category == "food"
    assert normalize_header(" Weight Grams ") == "weight_grams"


def test_missing_required_column():
    with pytest.raises(CsvFormatError, match="price"):
        run("sku,name\nA,B\n")


def test_empty_file():
    with pytest.raises(CsvFormatError):
        run("\n\n")


def test_blank_lines_are_skipped_and_line_numbers_are_physical():
    result = run("sku,name,price\n\nA-1,Thing,1.00\n\nB-1,,2.00\n")
    assert [p.sku for p in result.products] == ["A-1"]
    assert [(e.line, e.field) for e in result.errors] == [(5, "name")]


def test_row_errors_do_not_stop_the_import():
    text = "sku,name,price\nA-1,Thing,abc\nB-1,Other,-1\nC-1,Fine,3\nD-1,Cents,1.234\n"
    result = run(text)
    assert [p.sku for p in result.products] == ["C-1"]
    assert [e.line for e in result.errors] == [2, 3, 5]
    assert "not a number" in result.errors[0].message
    assert "negative" in result.errors[1].message
    assert "decimal places" in result.errors[2].message


def test_duplicate_sku_reports_first_line():
    result = run("sku,name,price\nA-1,One,1\nA-1,Two,2\n")
    assert len(result.products) == 1
    assert str(result.errors[0]) == "line 3: sku: duplicate sku A-1 (first seen on line 2)"


def test_invalid_first_occurrence_does_not_claim_sku():
    result = run("sku,name,price\nA-1,One,oops\nA-1,Two,2\n")
    assert [p.name for p in result.products] == ["Two"]


def test_wrong_field_count():
    result = run("sku,name,price\nA-1,One\n")
    assert str(result.errors[0]) == "line 2: expected 3 fields, got 2"


def test_weight_must_be_whole_grams():
    result = run("sku,name,price,weight_grams\nA-1,One,1,12.5\n")
    assert result.errors[0].field == "weight_grams"


def test_jpy_prices_have_no_decimals():
    assert run("sku,name,price\nA,B,1200\n", currency="JPY").ok
    assert not run("sku,name,price\nA,B,1200.5\n", currency="JPY").ok


def test_parse_price_rejects_nan_and_empty():
    with pytest.raises(ValueError):
        parse_price("NaN", "USD")
    with pytest.raises(ValueError):
        parse_price("  ", "USD")


def test_load_products_from_disk(tmp_path):
    path = tmp_path / "products.csv"
    path.write_text("sku,name,price\nA-1,Café crème,4.50\n", encoding="utf-8")
    result = load_products(path)
    assert result.products[0].name == "Café crème"
