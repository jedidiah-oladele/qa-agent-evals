from datetime import UTC, datetime
from decimal import Decimal

import pytest

from shopcore import Catalog, FixedClock, Money, Product


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 3, 14, 12, 0, tzinfo=UTC))


@pytest.fixture
def catalog() -> Catalog:
    return Catalog(
        [
            Product("TEE-001", "Plain tee", usd("19.99"), category="apparel", weight_grams=180),
            Product("MUG-001", "Enamel mug", usd("12.50"), category="kitchen", weight_grams=350),
            Product(
                "BEAN-250", "Coffee beans 250g", usd("9.95"), category="grocery", tax_category="food", weight_grams=260
            ),
            Product("BOOK-042", "Field guide", usd("24.00"), category="books", tax_category="books", weight_grams=540),
            Product("GIFT-10", "Gift card", usd("10.00"), category="gift", tax_category="exempt", weight_grams=0),
        ]
    )
