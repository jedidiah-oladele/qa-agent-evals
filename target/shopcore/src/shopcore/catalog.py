"""Products and the catalog that holds them."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .errors import UnknownSkuError
from .money import Money


@dataclass(frozen=True, slots=True)
class Product:
    sku: str
    name: str
    unit_price: Money
    category: str = "general"
    tax_category: str = "standard"
    weight_grams: int = 0

    def __post_init__(self) -> None:
        if not self.sku or self.sku != self.sku.strip():
            raise ValueError(f"invalid sku: {self.sku!r}")
        if self.unit_price.is_negative():
            raise ValueError(f"{self.sku}: unit price cannot be negative")
        if self.weight_grams < 0:
            raise ValueError(f"{self.sku}: weight cannot be negative")


class Catalog:
    """An in-memory product catalog keyed by SKU."""

    def __init__(self, products: list[Product] | None = None) -> None:
        self._products: dict[str, Product] = {}
        for product in products or []:
            self.add(product)

    def add(self, product: Product) -> None:
        if product.sku in self._products:
            raise ValueError(f"duplicate sku: {product.sku}")
        self._products[product.sku] = product

    def replace(self, product: Product) -> None:
        if product.sku not in self._products:
            raise UnknownSkuError(product.sku)
        self._products[product.sku] = product

    def get(self, sku: str) -> Product:
        try:
            return self._products[sku]
        except KeyError:
            raise UnknownSkuError(sku) from None

    def by_category(self, category: str) -> list[Product]:
        return [p for p in self._products.values() if p.category == category]

    def __contains__(self, sku: object) -> bool:
        return sku in self._products

    def __len__(self) -> int:
        return len(self._products)

    def __iter__(self) -> Iterator[Product]:
        return iter(self._products.values())
