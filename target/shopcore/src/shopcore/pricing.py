"""Turn an :class:`~shopcore.order.Order` into a fully priced quote.

Pipeline: gross line amounts -> discounts -> shipping (on the discounted
subtotal) -> tax per line -> totals.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .clock import Clock, SystemClock
from .discounts import AppliedDiscount, Discount, apply_discounts
from .errors import CurrencyMismatchError
from .money import Money, sum_money
from .order import Order
from .shipping import ShippingPolicy
from .tax import TaxRounding, TaxTable, compute_taxes


@dataclass(frozen=True)
class PricedLine:
    sku: str
    quantity: int
    gross: Money
    discount: Money
    net: Money
    tax: Money
    tax_included: bool = False

    @property
    def total(self) -> Money:
        """What the customer pays for this line (net plus tax on top, if any)."""
        return self.net if self.tax_included else self.net + self.tax


@dataclass(frozen=True)
class Quote:
    currency: str
    lines: tuple[PricedLine, ...]
    subtotal: Money
    discount_total: Money
    shipping: Money
    tax_total: Money
    total: Money
    tax_included: bool
    applied_discounts: tuple[AppliedDiscount, ...] = ()


class PricingEngine:
    def __init__(
        self,
        tax_table: TaxTable,
        discounts: Sequence[Discount] = (),
        *,
        shipping: ShippingPolicy | None = None,
        rounding: TaxRounding = TaxRounding.PER_LINE,
        clock: Clock | None = None,
    ) -> None:
        self.tax_table = tax_table
        self.discounts = list(discounts)
        self.shipping = shipping
        self.rounding = rounding
        self.clock = clock or SystemClock()

    def eligible_discounts(self, order: Order) -> list[Discount]:
        """Auto-applied discounts plus those whose code the customer entered."""
        entered = {code.strip().upper() for code in order.coupon_codes}
        return [d for d in self.discounts if d.auto_apply or d.code.upper() in entered]

    def quote(self, order: Order) -> Quote:
        currency = order.currency
        region = self.tax_table.get(order.region)
        for line in order.lines:
            if line.gross.currency != currency:
                raise CurrencyMismatchError(currency, line.gross.currency)

        result = apply_discounts(order.lines, self.eligible_discounts(order), now=self.clock.now())
        gross = [line.gross for line in order.lines]
        discounts = result.per_line
        nets = [g - d for g, d in zip(gross, discounts)]
        rates = [region.rate_for(line.product.tax_category) for line in order.lines]
        taxes = compute_taxes(nets, rates, inclusive=region.prices_include_tax, rounding=self.rounding)

        discounted_subtotal = sum_money(nets, currency)
        shipping = Money.zero(currency)
        if self.shipping is not None:
            shipping = self.shipping.quote(order.lines, discounted_subtotal)

        tax_total = sum_money(taxes, currency)
        total = discounted_subtotal + shipping
        if not region.prices_include_tax:
            total = total + tax_total

        priced = tuple(
            PricedLine(line.sku, line.quantity, g, d, n, t, tax_included=region.prices_include_tax)
            for line, g, d, n, t in zip(order.lines, gross, discounts, nets, taxes)
        )
        return Quote(
            currency=currency,
            lines=priced,
            subtotal=sum_money(gross, currency),
            discount_total=sum_money(discounts, currency),
            shipping=shipping,
            tax_total=tax_total,
            total=total,
            tax_included=region.prices_include_tax,
            applied_discounts=tuple(result.applied),
        )
