import asyncio
import re

import pytest

from shopcore import ChargeRequest, Money, PaymentClient, PaymentRetryExhaustedError, PermanentPaymentError, RetryPolicy
from shopcore.errors import TransientPaymentError
from shopcore.testing import RecordingSleep, ScriptedGateway


def eur(amount: str) -> Money:
    return Money.of(amount, "EUR")


class CountingKeys:
    def __init__(self) -> None:
        self.issued: list[str] = []

    def __call__(self) -> str:
        key = f"ik-{len(self.issued) + 101}"
        self.issued.append(key)
        return key


def make_client(script, *, max_attempts=4):
    gateway = ScriptedGateway(script)
    keys = CountingKeys()
    client = PaymentClient(gateway, RetryPolicy(max_attempts=max_attempts, jitter=0), sleep=RecordingSleep(),
                           key_factory=keys)
    return client, gateway, keys


def test_exhausted_retries_use_one_key_and_next_charge_gets_a_new_one():
    client, gateway, keys = make_client(["timeout"] * 3, max_attempts=3)
    with pytest.raises(PaymentRetryExhaustedError):
        asyncio.run(client.charge(eur("40.00"), "tok_exhaust"))
    assert [c.idempotency_key for c in gateway.calls] == ["ik-101"] * 3
    result = asyncio.run(client.charge(eur("40.00"), "tok_exhaust"))
    assert result.idempotency_key == "ik-102"
    assert keys.issued == ["ik-101", "ik-102"]


def test_key_factory_not_used_when_caller_supplies_a_key():
    def forbidden() -> str:
        raise AssertionError("key_factory must not be called when a key is supplied")

    gateway = ScriptedGateway(["timeout", "ok"])
    client = PaymentClient(gateway, RetryPolicy(jitter=0), sleep=RecordingSleep(), key_factory=forbidden)
    result = asyncio.run(client.charge(eur("8.50"), "tok", idempotency_key="cart-5531"))
    assert [c.idempotency_key for c in gateway.calls] == ["cart-5531", "cart-5531"]
    assert result.attempts == 2


def test_charge_many_gives_each_unkeyed_request_its_own_key():
    client, gateway, _ = make_client([])
    requests = [ChargeRequest(eur("3.00"), "t1"), ChargeRequest(eur("4.00"), "t2"), ChargeRequest(eur("5.00"), "t3")]
    results = asyncio.run(client.charge_many(requests, concurrency=2))
    keys = [r.idempotency_key for r in results]
    assert len(set(keys)) == 3
    assert len({r.charge_id for r in results}) == 3
    assert gateway.captured_total("EUR") == eur("12.00")


def test_charge_many_survives_capture_then_timeout_without_double_charge():
    client, gateway, _ = make_client(["captured_timeout"])
    requests = [ChargeRequest(eur("19.00"), "t1", "basket-8802")]
    [result] = asyncio.run(client.charge_many(requests))
    assert result.idempotency_key == "basket-8802"
    assert result.attempts == 2
    assert gateway.captured_total("EUR") == eur("19.00")


def test_gateway_captures_on_retry_after_a_plain_timeout():
    gateway = ScriptedGateway(["timeout"])
    with pytest.raises(TransientPaymentError):
        asyncio.run(gateway.charge(eur("6.00"), "tok", "retry-key-7"))
    assert gateway.captured_total("EUR") == eur("0.00")
    charge_id = asyncio.run(gateway.charge(eur("6.00"), "tok", "retry-key-7"))
    assert charge_id == "ch_0001"
    assert gateway.captured_total("EUR") == eur("6.00")


def test_replayed_key_does_not_consume_the_script():
    client, gateway, _ = make_client(["captured_timeout", "declined"])
    first = asyncio.run(client.charge(eur("11.00"), "tok"))
    assert first.charge_id == "ch_0001"
    with pytest.raises(PermanentPaymentError):
        asyncio.run(client.charge(eur("2.00"), "tok"))
    assert gateway.captured_total("EUR") == eur("11.00")


def test_declined_key_can_be_charged_again_later():
    client, gateway, _ = make_client(["declined"])
    with pytest.raises(PermanentPaymentError):
        asyncio.run(client.charge(eur("30.00"), "tok", idempotency_key="order-4410"))
    result = asyncio.run(client.charge(eur("30.00"), "tok", idempotency_key="order-4410"))
    assert result.charge_id == "ch_0001"
    assert gateway.captured_total("EUR") == eur("30.00")


def test_default_keys_are_fresh_uuid4_hex_per_charge():
    gateway = ScriptedGateway(["timeout"])
    client = PaymentClient(gateway, RetryPolicy(jitter=0), sleep=RecordingSleep())
    first = asyncio.run(client.charge(eur("1.00"), "tok"))
    second = asyncio.run(client.charge(eur("1.00"), "tok"))
    assert first.idempotency_key != second.idempotency_key
    for key in (first.idempotency_key, second.idempotency_key):
        assert re.fullmatch(r"[0-9a-f]{32}", key)
    assert gateway.calls[0].idempotency_key == gateway.calls[1].idempotency_key == first.idempotency_key
    assert gateway.captured_total("EUR") == eur("2.00")
