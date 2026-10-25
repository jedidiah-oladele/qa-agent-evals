import asyncio

from shopcore import ChargeRequest, Money, PaymentClient, RetryPolicy
from shopcore.testing import RecordingSleep, ScriptedGateway


def usd(amount: str) -> Money:
    return Money.of(amount, "USD")


def make_client(script):
    gateway = ScriptedGateway(script)
    keys = iter(f"key-{n}" for n in range(1, 100))
    client = PaymentClient(gateway, RetryPolicy(jitter=0), sleep=RecordingSleep(), key_factory=lambda: next(keys))
    return client, gateway


def test_all_attempts_share_one_idempotency_key():
    client, gateway = make_client(["timeout", "timeout", "ok"])
    result = asyncio.run(client.charge(usd("25"), "tok"))
    assert {call.idempotency_key for call in gateway.calls} == {"key-1"}
    assert result.idempotency_key == "key-1"


def test_timeout_after_capture_does_not_double_charge():
    client, gateway = make_client(["captured_timeout"])
    result = asyncio.run(client.charge(usd("25"), "tok"))
    assert result.attempts == 2
    assert result.charge_id == "ch_0001"
    assert gateway.captured_total("USD") == usd("25")


def test_caller_supplied_key_is_used():
    client, gateway = make_client([])
    result = asyncio.run(client.charge(usd("5"), "tok", idempotency_key="order-77"))
    assert gateway.calls[0].idempotency_key == "order-77"
    assert result.idempotency_key == "order-77"


def test_separate_charges_get_separate_keys():
    client, gateway = make_client([])
    asyncio.run(client.charge(usd("5"), "tok"))
    asyncio.run(client.charge(usd("5"), "tok"))
    assert [c.idempotency_key for c in gateway.calls] == ["key-1", "key-2"]
    assert gateway.captured_total("USD") == usd("10")


def test_replaying_a_key_returns_the_original_charge():
    client, gateway = make_client([])
    first = asyncio.run(client.charge(usd("5"), "tok", idempotency_key="order-1"))
    second = asyncio.run(client.charge(usd("5"), "tok", idempotency_key="order-1"))
    assert first.charge_id == second.charge_id
    assert gateway.captured_total("USD") == usd("5")


def test_charge_many_passes_request_keys():
    client, gateway = make_client([])
    requests = [ChargeRequest(usd("1"), "a", "k-a"), ChargeRequest(usd("2"), "b")]
    asyncio.run(client.charge_many(requests))
    assert sorted(c.idempotency_key for c in gateway.calls) == ["k-a", "key-1"]
