from decimal import Decimal

import pytest

from shopcore import CurrencyMismatchError, Money, UnknownCurrencyError, sum_money
from shopcore.money import minor_unit, round_half_up


def test_money_converts_int_and_str_to_decimal():
    assert Money.of(5, "USD").amount == Decimal(5)
    assert Money.of("1.10", "USD").amount == Decimal("1.10")


def test_money_rejects_floats_and_bools():
    with pytest.raises(TypeError):
        Money.of(1.1, "USD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money.of(True, "USD")  # type: ignore[arg-type]


def test_unknown_currency_is_rejected():
    with pytest.raises(UnknownCurrencyError):
        Money.of("1", "XYZ")


def test_addition_and_subtraction_keep_currency():
    assert Money.of("1.25", "EUR") + Money.of("2.50", "EUR") == Money.of("3.75", "EUR")
    assert Money.of("1.25", "EUR") - Money.of("2.50", "EUR") == Money.of("-1.25", "EUR")


def test_mixing_currencies_raises():
    with pytest.raises(CurrencyMismatchError):
        Money.of("1", "USD") + Money.of("1", "EUR")
    with pytest.raises(CurrencyMismatchError):
        _ = Money.of("1", "USD") < Money.of("1", "EUR")


def test_multiplication_by_int_and_decimal():
    assert Money.of("2.50", "USD") * 3 == Money.of("7.50", "USD")
    assert 3 * Money.of("2.50", "USD") == Money.of("7.50", "USD")
    assert Money.of("10", "USD") * Decimal("0.075") == Money.of("0.750", "USD")
    with pytest.raises(TypeError):
        Money.of("1", "USD") * 1.5  # type: ignore[operator]


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("2.345", "USD", "2.35"),
        ("2.344", "USD", "2.34"),
        ("-2.345", "USD", "-2.35"),
        ("0.005", "USD", "0.01"),
        ("1234.5", "JPY", "1235"),
        ("1.2345", "KWD", "1.235"),
    ],
)
def test_quantize_rounds_half_away_from_zero(amount, currency, expected):
    assert Money.of(amount, currency).quantize().amount == Decimal(expected)


def test_minor_unit_per_currency():
    assert minor_unit("USD") == Decimal("0.01")
    assert minor_unit("JPY") == Decimal("1")
    assert minor_unit("KWD") == Decimal("0.001")
    assert round_half_up(Decimal("0.125"), "USD") == Decimal("0.13")


def test_comparisons_and_min_max():
    a, b = Money.of("1", "USD"), Money.of("2", "USD")
    assert a < b and b > a and a <= a and b >= b
    assert a.min(b) == a and a.max(b) == b


def test_allocate_even_split():
    parts = Money.of("9", "USD").allocate([1, 1, 1])
    assert parts == [Money.of("3.00", "USD")] * 3


def test_allocate_gives_leftover_cents_to_largest_remainders():
    parts = Money.of("10", "USD").allocate([1, 1, 1])
    assert [p.amount for p in parts] == [Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]
    assert sum_money(parts, "USD") == Money.of("10.00", "USD")


def test_allocate_by_weights_never_loses_a_cent():
    parts = Money.of("100.00", "USD").allocate([Decimal("19.99"), Decimal("12.50"), Decimal("9.95")])
    assert sum_money(parts, "USD").amount == Decimal("100.00")
    assert [p.amount for p in parts] == [Decimal("47.10"), Decimal("29.45"), Decimal("23.45")]


def test_allocate_negative_amount_and_zero_weight():
    parts = Money.of("-1.00", "USD").allocate([1, 0, 2])
    assert [p.amount for p in parts] == [Decimal("-0.33"), Decimal("0.00"), Decimal("-0.67")]


def test_allocate_jpy_uses_whole_units():
    parts = Money.of("1000", "JPY").allocate([1, 1, 1])
    assert [p.amount for p in parts] == [Decimal("334"), Decimal("333"), Decimal("333")]


def test_allocate_rejects_bad_weights():
    with pytest.raises(ValueError):
        Money.of("1", "USD").allocate([])
    with pytest.raises(ValueError):
        Money.of("1", "USD").allocate([0, 0])
    with pytest.raises(ValueError):
        Money.of("1", "USD").allocate([1, -1])


def test_str_shows_rounded_amount():
    assert str(Money.of("3.456", "USD")) == "USD 3.46"
    assert str(Money.of("12", "JPY")) == "JPY 12"


def test_sum_money_of_empty_list_is_zero():
    assert sum_money([], "GBP") == Money.zero("GBP")
