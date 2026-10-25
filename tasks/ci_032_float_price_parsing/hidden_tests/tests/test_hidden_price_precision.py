import io
from decimal import Decimal

import pytest

from shopcore import Money
from shopcore.csv_import import import_products, parse_price


@pytest.mark.parametrize("text", ["0.10", "0.29", "4.35", "19.99", "999.99", "1,299.99"])
def test_cent_prices_are_exact(text):
    value = parse_price(text, "USD")
    assert value == Decimal(text.replace(",", ""))
    assert str(value) == text.replace(",", "")


def test_imported_prices_add_up_exactly():
    result = import_products(io.StringIO('sku,name,price\nSOAP-1,Soap,4.35\nLAMP-2,Lamp,"1,299.99"\n'))
    assert result.ok
    soap, lamp = (p.unit_price for p in result.products)
    assert soap * 3 == Money.of("13.05", "USD")
    assert soap + lamp == Money.of("1304.34", "USD")


@pytest.mark.parametrize(
    ("text", "currency", "expected"),
    [("98,765,432,109,876.54", "USD", "98765432109876.54"), ("9,007,199,254,740,993", "JPY", "9007199254740993")],
)
def test_prices_beyond_double_precision_are_exact(text, currency, expected):
    assert str(parse_price(text, currency)) == expected


def test_nonzero_digits_beyond_float_precision_are_rejected():
    with pytest.raises(ValueError, match="decimal places"):
        parse_price("19.9900000000000000001", "USD")


@pytest.mark.parametrize(
    ("text", "currency", "expected"),
    [("4.5000", "USD", "4.50"), ("7", "USD", "7.00"), ("1200.000", "JPY", "1200"), ("0.500", "KWD", "0.500")],
)
def test_result_has_the_currency_decimal_places(text, currency, expected):
    assert str(parse_price(text, currency)) == expected


@pytest.mark.parametrize(("text", "currency"), [("4.5001", "USD"), ("12.5", "JPY"), ("0.0001", "KWD")])
def test_padding_with_a_nonzero_digit_is_still_rejected(text, currency):
    with pytest.raises(ValueError, match="decimal places"):
        parse_price(text, currency)


@pytest.mark.parametrize("text", ["abc", "NaN", "Infinity", "-1.00", "1,23.00", ""])
def test_invalid_prices_are_still_rejected(text):
    with pytest.raises(ValueError):
        parse_price(text, "USD")
