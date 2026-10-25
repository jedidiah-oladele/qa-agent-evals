"""Exception hierarchy for shopcore.

Every error raised on purpose by the library derives from :class:`ShopcoreError`,
so callers can catch library failures without swallowing programming errors.
"""


class ShopcoreError(Exception):
    """Base class for all shopcore errors."""


class CurrencyMismatchError(ShopcoreError, ValueError):
    """Raised when an operation mixes two different currencies."""

    def __init__(self, left: str, right: str) -> None:
        super().__init__(f"currency mismatch: {left} vs {right}")
        self.left = left
        self.right = right


class UnknownCurrencyError(ShopcoreError, ValueError):
    """Raised for currency codes shopcore has no exponent for."""


class UnknownSkuError(ShopcoreError, KeyError):
    """Raised when a SKU is not present in the catalog or inventory."""

    def __str__(self) -> str:  # KeyError quotes its message; keep it readable.
        return str(self.args[0]) if self.args else "unknown sku"


class DiscountError(ShopcoreError, ValueError):
    """Raised when a discount is configured with invalid parameters."""


class TaxConfigError(ShopcoreError, ValueError):
    """Raised when a tax region or rate is missing or invalid."""


class InsufficientStockError(ShopcoreError):
    """Raised when a reservation asks for more units than are available."""

    def __init__(self, sku: str, requested: int, available: int) -> None:
        super().__init__(f"insufficient stock for {sku}: requested {requested}, available {available}")
        self.sku = sku
        self.requested = requested
        self.available = available


class ReservationError(ShopcoreError):
    """Raised for invalid reservation state transitions."""


class PaymentError(ShopcoreError):
    """Base class for payment failures."""


class TransientPaymentError(PaymentError):
    """A failure that may succeed if retried (timeouts, 5xx, rate limits)."""


class PermanentPaymentError(PaymentError):
    """A failure that will not succeed on retry (card declined, invalid token)."""


class PaymentRetryExhaustedError(PaymentError):
    """Raised when every retry attempt failed with a transient error."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        super().__init__(f"payment failed after {attempts} attempts: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


class CsvFormatError(ShopcoreError, ValueError):
    """Raised when a CSV file cannot be imported at all (e.g. missing columns)."""
