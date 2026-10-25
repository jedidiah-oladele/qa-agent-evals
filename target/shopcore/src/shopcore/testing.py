"""Test doubles shipped with shopcore so applications can test checkout flows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .errors import PermanentPaymentError, TransientPaymentError
from .money import Money


class CapturedThenTimeout(TransientPaymentError):
    """The gateway captured the money but the response never arrived."""


@dataclass
class GatewayCall:
    amount: Money
    token: str
    idempotency_key: str


@dataclass
class ScriptedGateway:
    """A fake gateway that replays a script of outcomes, one per call.

    Each outcome is ``"ok"``, ``"timeout"`` (transient, nothing captured),
    ``"captured_timeout"`` (money captured, then a transient error) or
    ``"declined"`` (permanent). When the script runs out every further call
    succeeds. Like real gateways, a key that already captured money returns the
    original charge id instead of capturing again.
    """

    script: Sequence[str] = ()
    calls: list[GatewayCall] = field(default_factory=list)
    captures: dict[str, tuple[str, Money]] = field(default_factory=dict)
    _position: int = 0

    async def charge(self, amount: Money, token: str, idempotency_key: str) -> str:
        self.calls.append(GatewayCall(amount, token, idempotency_key))
        if idempotency_key in self.captures:
            return self.captures[idempotency_key][0]
        outcome = self.script[self._position] if self._position < len(self.script) else "ok"
        self._position += 1
        if outcome == "timeout":
            raise TransientPaymentError("gateway timeout")
        if outcome == "declined":
            raise PermanentPaymentError("card declined")
        charge_id = f"ch_{len(self.captures) + 1:04d}"
        self.captures[idempotency_key] = (charge_id, amount)
        if outcome == "captured_timeout":
            raise CapturedThenTimeout("gateway timeout after capture")
        if outcome != "ok":
            raise ValueError(f"unknown scripted outcome {outcome!r}")
        return charge_id

    def captured_total(self, currency: str) -> Money:
        total = Money.zero(currency)
        for _, amount in self.captures.values():
            total = total + amount
        return total


@dataclass
class RecordingSleep:
    """An async ``sleep`` replacement that records delays instead of waiting."""

    delays: list[float] = field(default_factory=list)

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
