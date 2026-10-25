"""Async payment capture with retries, backoff and idempotency keys.

The gateway is any object with an async ``charge`` method. Transient errors
are retried with exponential backoff and jitter; permanent errors are raised
straight away. Every attempt for one logical charge reuses the same
idempotency key, so a retry after an ambiguous failure (say, a timeout after
the gateway already captured the money) cannot charge the customer twice.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from .errors import PaymentError, PaymentRetryExhaustedError, PermanentPaymentError, TransientPaymentError
from .money import Money


class PaymentGateway(Protocol):
    async def charge(self, amount: Money, token: str, idempotency_key: str) -> str:
        """Capture ``amount`` and return the gateway's charge id."""
        ...


@dataclass(frozen=True)
class ChargeRequest:
    amount: Money
    token: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ChargeResult:
    charge_id: str
    amount: Money
    attempts: int
    idempotency_key: str


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff: ``base_delay * multiplier**(n-1)``, capped, with jitter.

    ``jitter`` is a fraction: 0.1 means each delay is scaled by a random factor
    in [0.9, 1.1]. The cap is applied before jitter.
    """

    max_attempts: int = 4
    base_delay: float = 0.2
    multiplier: float = 2.0
    max_delay: float = 5.0
    jitter: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delays cannot be negative")
        if not (0 <= self.jitter < 1):
            raise ValueError("jitter must be in [0, 1)")

    def delay_for(self, retry_number: int, rng: random.Random) -> float:
        """Delay before retry number ``retry_number`` (1 = first retry)."""
        if retry_number < 1:
            raise ValueError("retry_number starts at 1")
        delay = min(self.base_delay * self.multiplier ** (retry_number - 1), self.max_delay)
        if self.jitter:
            delay *= 1 + rng.uniform(-self.jitter, self.jitter)
        return delay


def _new_key() -> str:
    return uuid.uuid4().hex


class PaymentClient:
    def __init__(
        self,
        gateway: PaymentGateway,
        policy: RetryPolicy | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        key_factory: Callable[[], str] = _new_key,
    ) -> None:
        self.gateway = gateway
        self.policy = policy or RetryPolicy()
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._key_factory = key_factory

    async def charge(self, amount: Money, token: str, *, idempotency_key: str | None = None) -> ChargeResult:
        if amount.is_negative() or amount.is_zero():
            raise ValueError("charge amount must be positive")
        key = idempotency_key or self._key_factory()
        last_error: TransientPaymentError | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                charge_id = await self.gateway.charge(amount, token, key)
            except PermanentPaymentError:
                raise
            except TransientPaymentError as exc:
                last_error = exc
                if attempt < self.policy.max_attempts:
                    await self._sleep(self.policy.delay_for(attempt, self._rng))
                continue
            return ChargeResult(charge_id, amount, attempt, key)
        assert last_error is not None
        raise PaymentRetryExhaustedError(self.policy.max_attempts, last_error)

    async def charge_many(
        self, requests: Sequence[ChargeRequest], *, concurrency: int = 4
    ) -> list[ChargeResult | PaymentError]:
        """Charge several requests concurrently; results keep the input order.

        Payment errors are returned in place of a result instead of raised, so
        one declined card does not hide the outcome of the others.
        """
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        semaphore = asyncio.Semaphore(concurrency)

        async def one(request: ChargeRequest) -> ChargeResult | PaymentError:
            async with semaphore:
                try:
                    return await self.charge(request.amount, request.token, idempotency_key=request.idempotency_key)
                except PaymentError as exc:
                    return exc

        return list(await asyncio.gather(*(one(r) for r in requests)))
