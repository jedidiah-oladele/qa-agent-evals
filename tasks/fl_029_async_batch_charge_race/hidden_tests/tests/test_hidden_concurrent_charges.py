import asyncio

from shopcore import ChargeRequest, Money, PaymentClient, RetryPolicy
from shopcore.testing import ScriptedGateway


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


def sequential_keys():
    keys = iter(f"key-{n}" for n in range(1, 1000))
    return lambda: next(keys)


async def yielding_sleep(seconds):
    await asyncio.sleep(0)


class LatentGateway:
    """Every call takes a little while (it yields to the event loop once)."""

    def __init__(self):
        self.calls = []

    async def charge(self, amount, token, idempotency_key):
        self.calls.append((token, idempotency_key))
        await asyncio.sleep(0)
        return f"ch_{token}"


def test_retry_during_another_charge_reuses_its_own_key():
    gateway = ScriptedGateway(["timeout"])  # the first call times out, the rest succeed
    client = PaymentClient(gateway, RetryPolicy(jitter=0), sleep=yielding_sleep, key_factory=sequential_keys())
    requests = [ChargeRequest(usd("10"), "tok_a"), ChargeRequest(usd("25"), "tok_b")]
    first, second = asyncio.run(client.charge_many(requests, concurrency=2))
    assert (first.idempotency_key, first.attempts) == ("key-1", 2)
    assert (second.idempotency_key, second.attempts) == ("key-2", 1)
    assert [c.idempotency_key for c in gateway.calls if c.token == "tok_a"] == ["key-1", "key-1"]
    assert first.charge_id != second.charge_id
    assert gateway.captured_total("USD") == usd("35")


def test_concurrent_charges_report_the_key_they_were_charged_with():
    gateway = LatentGateway()
    client = PaymentClient(gateway, RetryPolicy(jitter=0), key_factory=sequential_keys())
    requests = [ChargeRequest(usd(str(n)), f"t{n}", None if n % 2 else f"order-{n}") for n in range(1, 9)]
    results = asyncio.run(client.charge_many(requests, concurrency=4))
    used = dict(gateway.calls)
    for request, result in zip(requests, results):
        assert result.charge_id == f"ch_{request.token}"
        assert result.idempotency_key == used[request.token]
        if request.idempotency_key is not None:
            assert result.idempotency_key == request.idempotency_key
    assert len({r.idempotency_key for r in results}) == 8


def test_timeout_after_capture_in_a_batch_is_not_charged_twice():
    gateway = ScriptedGateway(["captured_timeout", "ok", "ok"])
    client = PaymentClient(gateway, RetryPolicy(jitter=0), sleep=yielding_sleep, key_factory=sequential_keys())
    requests = [ChargeRequest(usd("5"), "a"), ChargeRequest(usd("7"), "b"), ChargeRequest(usd("9"), "c")]
    results = asyncio.run(client.charge_many(requests, concurrency=3))
    assert [r.amount for r in results] == [usd("5"), usd("7"), usd("9")]
    assert len({r.charge_id for r in results}) == 3
    assert gateway.captured_total("USD") == usd("21")
