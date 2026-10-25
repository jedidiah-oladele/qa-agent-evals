import asyncio
import random

import pytest

from shopcore import (
    ChargeRequest,
    Money,
    PaymentClient,
    PaymentRetryExhaustedError,
    PermanentPaymentError,
    RetryPolicy,
)
from shopcore.testing import RecordingSleep, ScriptedGateway


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


def make_client(script, policy=None):
    gateway = ScriptedGateway(script)
    sleep = RecordingSleep()
    client = PaymentClient(gateway, policy or RetryPolicy(jitter=0), sleep=sleep, rng=random.Random(7))
    return client, gateway, sleep


def test_successful_first_attempt():
    client, gateway, sleep = make_client([])
    result = asyncio.run(client.charge(usd("10"), "tok_visa"))
    assert result.charge_id == "ch_0001"
    assert result.attempts == 1
    assert sleep.delays == []
    assert len(gateway.calls) == 1


def test_transient_errors_are_retried_with_exponential_backoff():
    client, gateway, sleep = make_client(["timeout", "timeout", "ok"])
    result = asyncio.run(client.charge(usd("10"), "tok_visa"))
    assert result.attempts == 3
    assert sleep.delays == pytest.approx([0.2, 0.4])


def test_permanent_error_is_not_retried():
    client, gateway, sleep = make_client(["declined"])
    with pytest.raises(PermanentPaymentError):
        asyncio.run(client.charge(usd("10"), "tok_visa"))
    assert len(gateway.calls) == 1
    assert sleep.delays == []


def test_retries_exhausted():
    client, gateway, sleep = make_client(["timeout"] * 4)
    with pytest.raises(PaymentRetryExhaustedError) as info:
        asyncio.run(client.charge(usd("10"), "tok_visa"))
    assert info.value.attempts == 4
    assert len(gateway.calls) == 4
    assert len(sleep.delays) == 3  # no sleep after the final attempt


def test_backoff_is_capped():
    policy = RetryPolicy(max_attempts=6, base_delay=1, multiplier=3, max_delay=5, jitter=0)
    rng = random.Random(0)
    assert [policy.delay_for(n, rng) for n in range(1, 6)] == [1, 3, 5, 5, 5]


def test_jitter_stays_within_bounds():
    policy = RetryPolicy(base_delay=1, jitter=0.25)
    rng = random.Random(42)
    delays = [policy.delay_for(1, rng) for _ in range(200)]
    assert all(0.75 <= d <= 1.25 for d in delays)
    assert len(set(delays)) > 1


@pytest.mark.parametrize(
    "kwargs", [{"max_attempts": 0}, {"base_delay": -1}, {"jitter": 1}, {"jitter": -0.1}]
)
def test_invalid_policy(kwargs):
    with pytest.raises(ValueError):
        RetryPolicy(**kwargs)


def test_delay_for_needs_positive_retry_number():
    with pytest.raises(ValueError):
        RetryPolicy().delay_for(0, random.Random())


@pytest.mark.parametrize("amount", ["0", "-1"])
def test_amount_must_be_positive(amount):
    client, _, _ = make_client([])
    with pytest.raises(ValueError):
        asyncio.run(client.charge(usd(amount), "tok"))


def test_charge_many_keeps_order_and_returns_errors_in_place():
    client, gateway, _ = make_client(["ok", "declined", "ok"])
    requests = [ChargeRequest(usd(str(n)), f"tok_{n}") for n in (1, 2, 3)]
    results = asyncio.run(client.charge_many(requests, concurrency=1))
    assert [type(r).__name__ for r in results] == ["ChargeResult", "PermanentPaymentError", "ChargeResult"]
    assert results[0].amount == usd("1") and results[2].amount == usd("3")


def test_charge_many_respects_concurrency_limit():
    in_flight = 0
    peak = 0

    class SlowGateway:
        async def charge(self, amount, token, idempotency_key=None):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            in_flight -= 1
            return f"ch_{token}"

    client = PaymentClient(SlowGateway())
    requests = [ChargeRequest(usd("1"), str(n)) for n in range(10)]
    results = asyncio.run(client.charge_many(requests, concurrency=3))
    assert [r.charge_id for r in results] == [f"ch_{n}" for n in range(10)]
    assert peak == 3


def test_charge_many_validates_concurrency():
    client, _, _ = make_client([])
    with pytest.raises(ValueError):
        asyncio.run(client.charge_many([], concurrency=0))
