"""Discount rules and the stacking algorithm that combines them.

Each discount turns the *remaining* (already discounted) amount of every line
into a per-line discount. :func:`apply_discounts` runs discounts in priority
order and decides between stacking and exclusive discounts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .errors import DiscountError
from .money import Money, sum_money
from .order import LineItem

HUNDRED = Decimal(100)


@dataclass(frozen=True, kw_only=True)
class Discount(ABC):
    """Common fields for every discount rule.

    ``priority``: lower runs first. ``stackable``: whether the discount can be
    combined with others. ``auto_apply``: applied without a coupon code.
    ``expires_at``: the discount stops applying at this instant (exclusive).
    """

    code: str
    priority: int = 100
    stackable: bool = True
    auto_apply: bool = False
    expires_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at

    @abstractmethod
    def compute(self, lines: Sequence[LineItem], remaining: Sequence[Money]) -> list[Money]:
        """Return the discount for each line given each line's remaining amount."""


def _allocate(amount: Money, lines_remaining: Sequence[Money], eligible: Sequence[bool]) -> list[Money]:
    """Spread ``amount`` over eligible lines in proportion to their remaining value."""
    currency = amount.currency
    weights = [r.amount if ok else Decimal(0) for r, ok in zip(lines_remaining, eligible)]
    if amount.is_zero() or sum(weights, Decimal(0)) <= 0:
        return [Money.zero(currency) for _ in lines_remaining]
    return amount.allocate(weights)


@dataclass(frozen=True, kw_only=True)
class PercentageDiscount(Discount):
    """``percent`` off eligible lines, optionally limited to one category."""

    percent: Decimal
    category: str | None = None
    max_discount: Money | None = None
    min_subtotal: Money | None = None

    def __post_init__(self) -> None:
        if not (Decimal(0) < self.percent <= HUNDRED):
            raise DiscountError(f"{self.code}: percent must be in (0, 100], got {self.percent}")

    def compute(self, lines: Sequence[LineItem], remaining: Sequence[Money]) -> list[Money]:
        currency = remaining[0].currency
        if self.min_subtotal is not None:
            gross = sum_money([line.gross for line in lines], currency)
            if gross < self.min_subtotal:
                return [Money.zero(currency) for _ in lines]
        eligible = [self.category is None or line.product.category == self.category for line in lines]
        base = sum_money([r for r, ok in zip(remaining, eligible) if ok], currency)
        discount = (base * self.percent * Decimal("0.01")).quantize()
        if self.max_discount is not None:
            discount = discount.min(self.max_discount)
        return _allocate(discount, remaining, eligible)


@dataclass(frozen=True, kw_only=True)
class FixedAmountDiscount(Discount):
    """A fixed amount off the whole order, spread across lines by value."""

    amount: Money
    min_subtotal: Money | None = None

    def __post_init__(self) -> None:
        if self.amount.is_negative() or self.amount.is_zero():
            raise DiscountError(f"{self.code}: amount must be positive")

    def compute(self, lines: Sequence[LineItem], remaining: Sequence[Money]) -> list[Money]:
        currency = remaining[0].currency
        if self.min_subtotal is not None:
            gross = sum_money([line.gross for line in lines], currency)
            if gross < self.min_subtotal:
                return [Money.zero(currency) for _ in lines]
        available = sum_money(list(remaining), currency)
        discount = self.amount.min(available)
        return _allocate(discount, remaining, [True] * len(lines))


@dataclass(frozen=True, kw_only=True)
class BuyXGetYDiscount(Discount):
    """Buy ``buy`` units of ``sku`` and get ``get`` more of the same SKU free.

    Free units are counted per complete group of ``buy + get`` units, so with
    buy=2, get=1 a quantity of 7 gives 2 free units.
    """

    sku: str
    buy: int
    get: int

    def __post_init__(self) -> None:
        if self.buy < 1 or self.get < 1:
            raise DiscountError(f"{self.code}: buy and get must both be at least 1")

    def compute(self, lines: Sequence[LineItem], remaining: Sequence[Money]) -> list[Money]:
        result: list[Money] = []
        for line, left in zip(lines, remaining):
            if line.sku != self.sku:
                result.append(Money.zero(left.currency))
                continue
            free_units = (line.quantity // (self.buy + self.get)) * self.get
            result.append((line.product.unit_price * free_units).min(left))
        return result


@dataclass(frozen=True)
class AppliedDiscount:
    code: str
    amount: Money


@dataclass(frozen=True)
class DiscountResult:
    per_line: list[Money]
    applied: list[AppliedDiscount] = field(default_factory=list)

    def total(self, currency: str) -> Money:
        return sum_money(self.per_line, currency)


def _run(lines: Sequence[LineItem], discounts: Sequence[Discount], currency: str) -> DiscountResult:
    remaining = [line.gross for line in lines]
    per_line = [Money.zero(currency) for _ in lines]
    applied: list[AppliedDiscount] = []
    for discount in discounts:
        amounts = discount.compute(lines, remaining)
        amounts = [a.min(r) for a, r in zip(amounts, remaining)]
        total = sum_money(amounts, currency)
        if total.is_zero():
            continue
        remaining = [r - a for r, a in zip(remaining, amounts)]
        per_line = [p + a for p, a in zip(per_line, amounts)]
        applied.append(AppliedDiscount(discount.code, total))
    return DiscountResult(per_line, applied)


def apply_discounts(lines: Sequence[LineItem], discounts: Sequence[Discount], *, now: datetime) -> DiscountResult:
    """Apply ``discounts`` to ``lines`` and return per-line discount amounts.

    Expired discounts are ignored. Stackable discounts run together in
    ``(priority, code)`` order, each on what the previous ones left. Every
    non-stackable discount is evaluated on its own. The candidate that saves
    the customer the most wins; on a tie the stacked combination wins.
    """
    if not lines:
        return DiscountResult([])
    currency = lines[0].gross.currency
    active = sorted((d for d in discounts if d.is_active(now)), key=lambda d: (d.priority, d.code))
    stackable = [d for d in active if d.stackable]
    exclusive = [d for d in active if not d.stackable]

    best = _run(lines, stackable, currency)
    for discount in exclusive:
        candidate = _run(lines, [discount], currency)
        if candidate.total(currency) > best.total(currency):
            best = candidate
    return best
