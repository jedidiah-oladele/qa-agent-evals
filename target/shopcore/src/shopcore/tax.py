"""Tax regions, rates and rounding.

Rates are fractions (``Decimal('0.0725')`` is 7.25%). Regions can quote prices
tax-exclusive (tax is added on top) or tax-inclusive (the price already
contains tax, which is extracted for reporting).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from .errors import TaxConfigError
from .money import Money, round_half_up


class TaxRounding(StrEnum):
    PER_LINE = "per_line"
    """Round each line's tax to the minor unit, then add the rounded amounts."""
    PER_ORDER = "per_order"
    """Add unrounded line taxes, round once, then spread back over the lines."""


@dataclass(frozen=True, slots=True)
class TaxRegion:
    code: str
    standard_rate: Decimal
    reduced_rate: Decimal = Decimal(0)
    reduced_categories: frozenset[str] = field(default_factory=frozenset)
    exempt_categories: frozenset[str] = field(default_factory=frozenset)
    prices_include_tax: bool = False

    def __post_init__(self) -> None:
        for rate in (self.standard_rate, self.reduced_rate):
            if not (Decimal(0) <= rate < Decimal(1)):
                raise TaxConfigError(f"{self.code}: rate {rate} must be in [0, 1)")
        overlap = self.reduced_categories & self.exempt_categories
        if overlap:
            raise TaxConfigError(f"{self.code}: categories both reduced and exempt: {sorted(overlap)}")

    def rate_for(self, tax_category: str) -> Decimal:
        if tax_category in self.exempt_categories:
            return Decimal(0)
        if tax_category in self.reduced_categories:
            return self.reduced_rate
        return self.standard_rate


class TaxTable:
    """Lookup of tax regions by code."""

    def __init__(self, regions: Iterable[TaxRegion] = ()) -> None:
        self._regions: dict[str, TaxRegion] = {}
        for region in regions:
            self.register(region)

    def register(self, region: TaxRegion) -> None:
        self._regions[region.code] = region

    def get(self, code: str) -> TaxRegion:
        try:
            return self._regions[code]
        except KeyError:
            raise TaxConfigError(f"no tax region configured for {code!r}") from None

    def __contains__(self, code: object) -> bool:
        return code in self._regions

    def codes(self) -> list[str]:
        return sorted(self._regions)


DEFAULT_REGIONS: tuple[TaxRegion, ...] = (
    TaxRegion("US-CA", Decimal("0.0725"), exempt_categories=frozenset({"food"})),
    TaxRegion("US-NY", Decimal("0.04"), exempt_categories=frozenset({"food"})),
    TaxRegion("US-OR", Decimal("0")),
    TaxRegion(
        "GB",
        Decimal("0.20"),
        reduced_rate=Decimal("0.05"),
        reduced_categories=frozenset({"energy"}),
        exempt_categories=frozenset({"food", "books", "children"}),
        prices_include_tax=True,
    ),
    TaxRegion(
        "DE",
        Decimal("0.19"),
        reduced_rate=Decimal("0.07"),
        reduced_categories=frozenset({"food", "books"}),
        prices_include_tax=True,
    ),
    TaxRegion("NG", Decimal("0.075"), exempt_categories=frozenset({"food", "medical"})),
    TaxRegion(
        "JP",
        Decimal("0.10"),
        reduced_rate=Decimal("0.08"),
        reduced_categories=frozenset({"food"}),
        prices_include_tax=True,
    ),
)


def default_tax_table() -> TaxTable:
    """A fresh table with the built-in example regions."""
    return TaxTable(DEFAULT_REGIONS)


def unrounded_tax(net: Money, rate: Decimal, *, inclusive: bool) -> Decimal:
    """Tax contained in (inclusive) or owed on top of (exclusive) ``net``."""
    if inclusive:
        return net.amount * rate / (Decimal(1) + rate)
    return net.amount * rate


def compute_taxes(
    nets: Sequence[Money],
    rates: Sequence[Decimal],
    *,
    inclusive: bool = False,
    rounding: TaxRounding = TaxRounding.PER_LINE,
) -> list[Money]:
    """Return the rounded tax for every line."""
    if len(nets) != len(rates):
        raise ValueError("nets and rates must have the same length")
    if not nets:
        return []
    currency = nets[0].currency
    raw = [unrounded_tax(net, rate, inclusive=inclusive) for net, rate in zip(nets, rates)]
    if rounding is TaxRounding.PER_LINE:
        return [Money(round_half_up(r, currency), currency) for r in raw]
    total = Money(sum(raw, Decimal(0)), currency)
    if total.is_zero() or sum(raw, Decimal(0)) <= 0:
        return [Money.zero(currency) for _ in nets]
    return total.allocate(raw)
