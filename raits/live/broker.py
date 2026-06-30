"""
raits/live/broker.py

Broker interface + MockBroker + IBKRBroker stub.

MockBroker supports:
  - configurable slippage (pct per share, applied to fill price)
  - configurable partial-fill rate (fraction of intended qty filled)
  - configurable reject rate (fraction of orders randomly rejected)
  - configurable fill latency (seconds, logged but not actually slept)

IBKRBroker raises NotImplementedError on every method.
ib_async is NOT imported at module level — only inside IBKRBroker methods.
"""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FillStatus(str, Enum):
    FILLED    = "FILLED"
    PARTIAL   = "PARTIAL"
    REJECTED  = "REJECTED"
    PENDING   = "PENDING"


@dataclass
class Order:
    """Represents a single order submitted to a broker."""
    order_id: str
    ticker: str
    side: str            # BUY | SELL
    qty: int
    limit_price: float   # signal price (pre-slippage)
    strategy: str
    hmm_state: str
    signal_ts: float     # epoch seconds of the signal bar

    # Filled by broker
    fill_status: FillStatus = FillStatus.PENDING
    filled_qty: int = 0
    fill_price: float = 0.0
    fill_ts: float = 0.0       # epoch seconds when fill arrived
    reject_reason: str = ""


class BrokerInterface(ABC):
    """Abstract broker. All live-trading routing goes through this."""

    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        """Submit order; return updated Order with fill_status set."""

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order. Returns True if successfully cancelled."""

    @abstractmethod
    def account_equity(self) -> float:
        """Current account equity (cash + positions at market)."""


class MockBroker(BrokerInterface):
    """
    Synchronous mock broker for paper-trading verification.

    slippage_pct: price moved against you by this fraction (0.001 = 0.1%)
    partial_fill_rate: probability order is partially filled (0.0–1.0)
    partial_fill_fraction: if partial, this fraction of qty is filled
    reject_rate: probability order is outright rejected (0.0–1.0)
    fill_latency_s: simulated fill latency in seconds (logged only, not slept)
    seed: RNG seed for reproducibility (None = random)
    """

    def __init__(
        self,
        initial_equity: float = 50_000.0,
        slippage_pct: float = 0.0,
        partial_fill_rate: float = 0.0,
        partial_fill_fraction: float = 0.5,
        reject_rate: float = 0.0,
        fill_latency_s: float = 0.0,
        seed: Optional[int] = None,
    ) -> None:
        self._equity = initial_equity
        self.slippage_pct = slippage_pct
        self.partial_fill_rate = partial_fill_rate
        self.partial_fill_fraction = partial_fill_fraction
        self.reject_rate = reject_rate
        self.fill_latency_s = fill_latency_s
        self._rng = random.Random(seed)
        self._orders: dict[str, Order] = {}

    def submit_order(self, order: Order) -> Order:
        now = time.time()
        order.fill_ts = now + self.fill_latency_s

        # Reject?
        if self._rng.random() < self.reject_rate:
            order.fill_status = FillStatus.REJECTED
            order.reject_reason = "MockBroker: random reject"
            self._orders[order.order_id] = order
            return order

        # Apply slippage: buys pay more, sells receive less
        slip = order.limit_price * self.slippage_pct
        if order.side == "BUY":
            order.fill_price = order.limit_price + slip
        else:
            order.fill_price = order.limit_price - slip

        # Partial fill?
        if self._rng.random() < self.partial_fill_rate:
            order.filled_qty = max(1, int(order.qty * self.partial_fill_fraction))
            order.fill_status = FillStatus.PARTIAL
        else:
            order.filled_qty = order.qty
            order.fill_status = FillStatus.FILLED

        self._orders[order.order_id] = order
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.fill_status != FillStatus.PENDING:
            return False
        order.fill_status = FillStatus.REJECTED
        order.reject_reason = "MockBroker: cancelled"
        return True

    def account_equity(self) -> float:
        return self._equity

    def set_equity(self, equity: float) -> None:
        """For runner to update equity as P&L accumulates."""
        self._equity = equity


class IBKRBroker(BrokerInterface):
    """
    Interactive Brokers broker stub.

    Raises NotImplementedError on all methods.
    ib_async is imported lazily so mock mode never requires it installed.

    Wire this up once:
      1. pip install ib_async
      2. TWS / IB Gateway running on port 7497 (paper) or 7496 (live)
      3. Pass --i-understand-this-is-live to PaperTrader
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._ib = None  # lazy

    def _connect(self):
        try:
            import ib_async as ib  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "ib_async not installed. Run: pip install ib_async"
            ) from exc
        raise NotImplementedError("IBKRBroker._connect not yet implemented")

    def submit_order(self, order: Order) -> Order:
        raise NotImplementedError("IBKRBroker is a stub — not yet implemented")

    def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("IBKRBroker is a stub — not yet implemented")

    def account_equity(self) -> float:
        raise NotImplementedError("IBKRBroker is a stub — not yet implemented")
