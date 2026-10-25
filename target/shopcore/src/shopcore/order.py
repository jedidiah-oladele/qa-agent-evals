"""Orders and their line items."""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Product
from .errors import CurrencyMismatchError
from .money import Money, sum_money


@dataclass(frozen=True, slots=True)
class LineItem:
    product: Product
    quantity: int

    def __post_init__(self) -> None:
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise TypeError("quantity must be an int")
        if self.quantity <= 0:
            raise ValueError(f"{self.product.sku}: quantity must be positive")

    @property
    def sku(self) -> str:
        return self.product.sku

    @property
    def gross(self) -> Money:
        """Unit price times quantity, before discounts and tax."""
        return self.product.unit_price * self.quantity

    @property
    def weight_grams(self) -> int:
        return self.product.weight_grams * self.quantity


@dataclass
class Order:
    """A mutable shopping order. Pricing happens in :mod:`shopcore.pricing`."""

    currency: str
    region: str
    lines: list[LineItem] = field(default_factory=list)
    coupon_codes: tuple[str, ...] = ()

    def add(self, product: Product, quantity: int = 1) -> None:
        """Add ``quantity`` units of ``product``, merging with an existing line."""
        if product.unit_price.currency != self.currency:
            raise CurrencyMismatchError(self.currency, product.unit_price.currency)
        for index, line in enumerate(self.lines):
            if line.sku == product.sku:
                self.lines[index] = LineItem(product, line.quantity + quantity)
                return
        self.lines.append(LineItem(product, quantity))

    def remove(self, sku: str) -> None:
        self.lines = [line for line in self.lines if line.sku != sku]

    def subtotal(self) -> Money:
        return sum_money([line.gross for line in self.lines], self.currency)

    def total_weight_grams(self) -> int:
        return sum(line.weight_grams for line in self.lines)
