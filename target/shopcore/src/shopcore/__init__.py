"""shopcore: order pricing, discounts, tax, inventory, payments and CSV import."""

from .catalog import Catalog, Product
from .clock import Clock, FixedClock, SystemClock
from .discounts import (
    AppliedDiscount,
    BuyXGetYDiscount,
    Discount,
    FixedAmountDiscount,
    PercentageDiscount,
    apply_discounts,
)
from .errors import (
    CsvFormatError,
    CurrencyMismatchError,
    DiscountError,
    InsufficientStockError,
    PaymentError,
    PaymentRetryExhaustedError,
    PermanentPaymentError,
    ReservationError,
    ShopcoreError,
    TaxConfigError,
    TransientPaymentError,
    UnknownCurrencyError,
    UnknownSkuError,
)
from .inventory import Inventory, Reservation, ReservationStatus
from .money import Money, sum_money
from .order import LineItem, Order
from .payments import ChargeRequest, ChargeResult, PaymentClient, RetryPolicy
from .pricing import PricedLine, PricingEngine, Quote
from .shipping import ShippingPolicy, WeightTier
from .tax import TaxRegion, TaxRounding, TaxTable, default_tax_table

__version__ = "0.9.0"

__all__ = [
    "AppliedDiscount",
    "BuyXGetYDiscount",
    "Catalog",
    "ChargeRequest",
    "ChargeResult",
    "Clock",
    "CsvFormatError",
    "CurrencyMismatchError",
    "Discount",
    "DiscountError",
    "FixedAmountDiscount",
    "FixedClock",
    "InsufficientStockError",
    "Inventory",
    "LineItem",
    "Money",
    "Order",
    "PaymentClient",
    "PaymentError",
    "PaymentRetryExhaustedError",
    "PercentageDiscount",
    "PermanentPaymentError",
    "PricedLine",
    "PricingEngine",
    "Product",
    "Quote",
    "Reservation",
    "ReservationError",
    "ReservationStatus",
    "RetryPolicy",
    "ShippingPolicy",
    "ShopcoreError",
    "SystemClock",
    "TaxConfigError",
    "TaxRegion",
    "TaxRounding",
    "TaxTable",
    "TransientPaymentError",
    "UnknownCurrencyError",
    "UnknownSkuError",
    "WeightTier",
    "apply_discounts",
    "default_tax_table",
    "sum_money",
]
