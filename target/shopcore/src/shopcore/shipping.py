"""Weight-based shipping with a free-shipping threshold."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .money import Money
from .order import LineItem


@dataclass(frozen=True, slots=True)
class WeightTier:
    max_grams: int
    price: Money


@dataclass(frozen=True)
class ShippingPolicy:
    """Price shipping by total weight.

    ``tiers`` are matched by the smallest ``max_grams`` that is at least the
    order weight (inclusive). Heavier orders pay the last tier plus
    ``per_extra_kg`` for every started kilogram above it. Orders whose
    *discounted* subtotal reaches ``free_over`` ship free.
    """

    tiers: tuple[WeightTier, ...]
    free_over: Money | None = None
    per_extra_kg: Money | None = None

    def __post_init__(self) -> None:
        if not self.tiers:
            raise ValueError("at least one weight tier is required")
        ordered = tuple(sorted(self.tiers, key=lambda t: t.max_grams))
        object.__setattr__(self, "tiers", ordered)

    def quote(self, lines: Sequence[LineItem], discounted_subtotal: Money) -> Money:
        currency = discounted_subtotal.currency
        weight = sum(line.weight_grams for line in lines)
        if weight == 0:
            return Money.zero(currency)
        if self.free_over is not None and discounted_subtotal >= self.free_over:
            return Money.zero(currency)
        for tier in self.tiers:
            if weight <= tier.max_grams:
                return tier.price
        last = self.tiers[-1]
        if self.per_extra_kg is None:
            raise ValueError(f"order weight {weight}g exceeds the heaviest tier ({last.max_grams}g)")
        extra_kg = math.ceil((weight - last.max_grams) / 1000)
        return last.price + self.per_extra_kg * extra_kg
