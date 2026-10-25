"""Money values with explicit currency and exact decimal arithmetic.

Amounts are stored as :class:`decimal.Decimal`. Arithmetic keeps full precision;
rounding to the currency's minor unit only happens when :meth:`Money.quantize`
is called, so callers decide where rounding belongs (per line, per order, ...).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from .errors import CurrencyMismatchError, UnknownCurrencyError

#: Number of digits after the decimal point for each supported currency.
CURRENCY_EXPONENTS: dict[str, int] = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "NGN": 2,
    "JPY": 0,
    "KWD": 3,
}


def exponent_for(currency: str) -> int:
    """Return the minor-unit exponent for ``currency``."""
    try:
        return CURRENCY_EXPONENTS[currency]
    except KeyError:
        raise UnknownCurrencyError(f"unknown currency: {currency!r}") from None


def minor_unit(currency: str) -> Decimal:
    """Smallest representable amount, e.g. ``Decimal('0.01')`` for USD."""
    return Decimal(1).scaleb(-exponent_for(currency))


def round_half_up(value: Decimal, currency: str) -> Decimal:
    """Round ``value`` to the currency's minor unit, halves away from zero."""
    return value.quantize(minor_unit(currency), rounding=ROUND_HALF_UP)


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a valid money amount")
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise TypeError(f"unsupported amount type: {type(value).__name__} (floats are not accepted)")


@dataclass(frozen=True, slots=True)
class Money:
    """An immutable amount of a single currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        exponent_for(self.currency)
        object.__setattr__(self, "amount", _to_decimal(self.amount))

    @classmethod
    def of(cls, amount: Decimal | int | str, currency: str) -> Money:
        return cls(_to_decimal(amount), currency)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal(0), currency)

    # -- arithmetic -----------------------------------------------------
    def _check(self, other: object) -> Money:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatchError(self.currency, other.currency)
        return other

    def __add__(self, other: Money) -> Money:
        other = self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        other = self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __mul__(self, factor: Decimal | int) -> Money:
        if isinstance(factor, (float, bool)) or not isinstance(factor, (int, Decimal)):
            raise TypeError("Money can only be multiplied by int or Decimal")
        return Money(self.amount * factor, self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        return self.amount < self._check(other).amount

    def __le__(self, other: Money) -> bool:
        return self.amount <= self._check(other).amount

    def __gt__(self, other: Money) -> bool:
        return self.amount > self._check(other).amount

    def __ge__(self, other: Money) -> bool:
        return self.amount >= self._check(other).amount

    # -- helpers --------------------------------------------------------
    def is_zero(self) -> bool:
        return self.amount == 0

    def is_negative(self) -> bool:
        return self.amount < 0

    def quantize(self) -> Money:
        """Round to the currency's minor unit (half away from zero)."""
        return Money(round_half_up(self.amount, self.currency), self.currency)

    def min(self, other: Money) -> Money:
        return self if self <= other else other

    def max(self, other: Money) -> Money:
        return self if self >= other else other

    def allocate(self, weights: Sequence[Decimal | int]) -> list[Money]:
        """Split this amount across ``weights`` without losing a minor unit.

        The amount is first rounded to the currency's minor unit. Each share is
        rounded down, then the leftover minor units go to the shares with the
        largest remainders (ties go to the earliest share). The returned parts
        always sum exactly to the rounded amount.
        """
        if not weights:
            raise ValueError("allocate() needs at least one weight")
        weights = [_to_decimal(w) for w in weights]
        if any(w < 0 for w in weights):
            raise ValueError("weights must be non-negative")
        total_weight = sum(weights, Decimal(0))
        if total_weight == 0:
            raise ValueError("at least one weight must be positive")

        unit = minor_unit(self.currency)
        total = round_half_up(self.amount, self.currency)
        sign = -1 if total < 0 else 1
        units_total = int((abs(total) / unit).to_integral_value())

        raw = [Decimal(units_total) * w / total_weight for w in weights]
        floors = [int(r.to_integral_value(rounding=ROUND_DOWN)) for r in raw]
        leftover = units_total - sum(floors)
        order = sorted(range(len(weights)), key=lambda i: (-(raw[i] - floors[i]), i))
        for i in order[:leftover]:
            floors[i] += 1
        return [Money(sign * Decimal(units) * unit, self.currency) for units in floors]

    def __str__(self) -> str:
        return f"{self.currency} {round_half_up(self.amount, self.currency)}"


def sum_money(values: Sequence[Money], currency: str) -> Money:
    """Sum ``values``; an empty sequence gives zero in ``currency``."""
    total = Money.zero(currency)
    for value in values:
        total = total + value
    return total
