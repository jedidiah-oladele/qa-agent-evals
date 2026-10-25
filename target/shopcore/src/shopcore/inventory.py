"""Stock levels and time-limited reservations.

A reservation holds units for a checkout. It is either committed (the units
leave the warehouse), released (the units go back), or it expires after its
time-to-live and stops counting against availability.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .clock import Clock, SystemClock
from .errors import InsufficientStockError, ReservationError, UnknownSkuError


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"


@dataclass
class Reservation:
    id: str
    sku: str
    quantity: int
    created_at: datetime
    expires_at: datetime | None = None
    status: ReservationStatus = ReservationStatus.ACTIVE

    def is_expired(self, now: datetime) -> bool:
        """True once an active reservation has reached its expiry time."""
        if self.status is ReservationStatus.EXPIRED:
            return True
        return (
            self.status is ReservationStatus.ACTIVE
            and self.expires_at is not None
            and now >= self.expires_at
        )


class Inventory:
    def __init__(self, *, clock: Clock | None = None, default_ttl: timedelta | None = None) -> None:
        if default_ttl is not None and default_ttl <= timedelta(0):
            raise ValueError("default_ttl must be positive")
        self._clock = clock or SystemClock()
        self._default_ttl = default_ttl
        self._on_hand: dict[str, int] = {}
        self._reservations: dict[str, Reservation] = {}
        self._ids = itertools.count(1)

    # -- stock -----------------------------------------------------------
    def set_stock(self, sku: str, quantity: int) -> None:
        if quantity < 0:
            raise ValueError("stock cannot be negative")
        self._on_hand[sku] = quantity

    def add_stock(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._on_hand[sku] = self._on_hand.get(sku, 0) + quantity

    def on_hand(self, sku: str) -> int:
        try:
            return self._on_hand[sku]
        except KeyError:
            raise UnknownSkuError(sku) from None

    def reserved(self, sku: str) -> int:
        """Units held by active, unexpired reservations."""
        self.on_hand(sku)
        now = self._clock.now()
        return sum(
            r.quantity
            for r in self._reservations.values()
            if r.sku == sku and r.status is ReservationStatus.ACTIVE and not r.is_expired(now)
        )

    def available(self, sku: str) -> int:
        return self.on_hand(sku) - self.reserved(sku)

    # -- reservations ----------------------------------------------------
    def _new_id(self) -> str:
        return f"RSV-{next(self._ids):06d}"

    def _expiry(self, now: datetime, ttl: timedelta | None) -> datetime | None:
        ttl = ttl if ttl is not None else self._default_ttl
        if ttl is None:
            return None
        if ttl <= timedelta(0):
            raise ValueError("ttl must be positive")
        return now + ttl

    def reserve(self, sku: str, quantity: int, *, ttl: timedelta | None = None) -> Reservation:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self.expire_stale()
        available = self.available(sku)
        if quantity > available:
            raise InsufficientStockError(sku, quantity, available)
        now = self._clock.now()
        reservation = Reservation(self._new_id(), sku, quantity, now, self._expiry(now, ttl))
        self._reservations[reservation.id] = reservation
        return reservation

    def reserve_many(self, items: Mapping[str, int], *, ttl: timedelta | None = None) -> list[Reservation]:
        """Reserve several SKUs at once. Either every SKU is reserved or none is."""
        self.expire_stale()
        for sku, quantity in items.items():
            if quantity <= 0:
                raise ValueError(f"{sku}: quantity must be positive")
            available = self.available(sku)
            if quantity > available:
                raise InsufficientStockError(sku, quantity, available)
        return [self.reserve(sku, quantity, ttl=ttl) for sku, quantity in items.items()]

    def get(self, reservation_id: str) -> Reservation:
        try:
            return self._reservations[reservation_id]
        except KeyError:
            raise ReservationError(f"unknown reservation {reservation_id}") from None

    def release(self, reservation_id: str) -> None:
        """Give the units back. Releasing twice, or after expiry, is a no-op."""
        reservation = self.get(reservation_id)
        if reservation.status is ReservationStatus.COMMITTED:
            raise ReservationError(f"{reservation_id} is already committed")
        if reservation.status is ReservationStatus.ACTIVE:
            if reservation.is_expired(self._clock.now()):
                reservation.status = ReservationStatus.EXPIRED
            else:
                reservation.status = ReservationStatus.RELEASED

    def commit(self, reservation_id: str) -> None:
        """Ship the reserved units: they leave ``on_hand`` permanently."""
        reservation = self.get(reservation_id)
        if reservation.status is not ReservationStatus.ACTIVE:
            raise ReservationError(f"{reservation_id} is {reservation.status}, not active")
        if reservation.is_expired(self._clock.now()):
            reservation.status = ReservationStatus.EXPIRED
            raise ReservationError(f"{reservation_id} expired at {reservation.expires_at.isoformat()}")
        self._on_hand[reservation.sku] -= reservation.quantity
        reservation.status = ReservationStatus.COMMITTED

    def expire_stale(self) -> list[Reservation]:
        """Mark every reservation past its expiry as expired and return them."""
        now = self._clock.now()
        expired = []
        for reservation in self._reservations.values():
            if reservation.status is ReservationStatus.ACTIVE and reservation.is_expired(now):
                reservation.status = ReservationStatus.EXPIRED
                expired.append(reservation)
        return expired

    def active_reservations(self, sku: str | None = None) -> list[Reservation]:
        now = self._clock.now()
        return [
            r
            for r in self._reservations.values()
            if r.status is ReservationStatus.ACTIVE and not r.is_expired(now) and (sku is None or r.sku == sku)
        ]
