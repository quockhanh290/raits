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
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional


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

    @abstractmethod
    def get_open_positions(self) -> Dict[str, float]:
        """Return {ticker: shares} for all currently open positions.

        Used by PaperTrader at startup to detect state↔broker mismatch.
        A fresh MockBroker has no positions; IBKRBroker queries the gateway.
        """


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

    def get_open_positions(self) -> Dict[str, float]:
        """MockBroker tracks no real positions — always returns empty."""
        return {}


class IBKRConnectionError(RuntimeError):
    """Raised when IBKRBroker is called without a live IB Gateway connection."""
    pass


class IBKRBroker(BrokerInterface):
    """
    Interactive Brokers equity broker via ib_async.

    Not yet tested against live IBKR — pending account approval.
    Verified only that it imports and instantiates without ib_async present
    (lazy import), and that calling a method without connect() raises
    IBKRConnectionError (not ImportError).

    Wire-up checklist
    -----------------
    1. pip install ib_async
    2. IB Gateway (or TWS) running — paper port 7497, live port 7496
    3. Pass ibkr_port=7497 to PaperTrader (or 7496 + live_flag=True for live)
    4. Call broker.connect() before PaperTrader.run()
    5. Call broker.disconnect() in a finally block after the run

    Parameters
    ----------
    host          : IB Gateway host (default 127.0.0.1)
    port          : IB Gateway port (7497 paper, 7496 live)
    client_id     : IB API client ID — must be unique per simultaneous connection
    fill_timeout_s: seconds to wait for order fill before marking PENDING (default 30)
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        fill_timeout_s: float = 30.0,
    ) -> None:
        self._host         = host
        self._port         = port
        self._client_id    = client_id
        self._fill_timeout = fill_timeout_s
        self._ib           = None  # ib_async.IB instance; None until connect()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    def connect(self) -> None:
        """Connect to IB Gateway. Call once before PaperTrader.run()."""
        try:
            import ib_async  # type: ignore  # lazy import
        except ImportError as exc:
            raise ImportError(
                "ib_async not installed. Run: pip install ib_async"
            ) from exc
        ib = ib_async.IB()
        ib.connect(self._host, self._port, clientId=self._client_id)
        self._ib = ib

    def disconnect(self) -> None:
        """Disconnect from IB Gateway. Call in a finally block after run()."""
        if self._ib is not None:
            try:
                self._ib.disconnect()
            except Exception:
                pass
            self._ib = None

    def _require_connection(self):
        """Return connected IB instance, or raise IBKRConnectionError."""
        if self._ib is None or not self._ib.isConnected():
            raise IBKRConnectionError(
                "IBKRBroker is not connected — call broker.connect() first.\n"
                f"  host={self._host}, port={self._port}, clientId={self._client_id}"
            )
        return self._ib

    # ── BrokerInterface ───────────────────────────────────────────────────────

    def submit_order(self, order: Order) -> Order:
        """
        Submit an equity market order to IBKR and wait for fill.

        Uses MarketOrder to guarantee fill (accepts market impact on illiquid
        names; acceptable for RAITS's liquid large-cap universe).

        Waits up to fill_timeout_s for execution; marks PENDING on timeout.

        TODOs (for production hardening)
        ---------------------------------
        - Add LimitOrder fallback for large qty / low-liquidity names
        - Maintain a UUID→IBKR orderId mapping so cancel_order works
        - Subscribe to orderStatus events instead of polling
        - Handle partial fills: IBKR can partially fill large market orders
        - Retry / cancel zombie orders on fill timeout
        """
        ib = self._require_connection()  # IBKRConnectionError if not connected
        try:
            import ib_async  # type: ignore  # lazy import

            contract = ib_async.Stock(order.ticker, "SMART", "USD")
            ib_order = ib_async.MarketOrder(order.side, order.qty)
            trade    = ib.placeOrder(contract, ib_order)

            # Poll for fill
            elapsed  = 0.0
            interval = 0.1
            while not trade.isDone() and elapsed < self._fill_timeout:
                ib.sleep(interval)
                elapsed += interval

            if trade.isDone() and trade.fills:
                total_shares = sum(f.execution.shares for f in trade.fills)
                avg_price    = (
                    sum(f.execution.price * f.execution.shares for f in trade.fills)
                    / total_shares
                )
                order.filled_qty = int(total_shares)
                order.fill_price = float(avg_price)
                order.fill_ts    = time.time()
                if order.filled_qty >= order.qty:
                    order.fill_status = FillStatus.FILLED
                else:
                    order.fill_status = FillStatus.PARTIAL
            elif trade.isDone():
                order.fill_status   = FillStatus.REJECTED
                order.reject_reason = (
                    f"IBKR rejected/cancelled: {trade.orderStatus.status}"
                )
            else:
                # Timeout — still in-flight
                order.fill_status   = FillStatus.PENDING
                order.reject_reason = f"Fill timeout after {self._fill_timeout}s"

        except IBKRConnectionError:
            raise
        except Exception as exc:
            order.fill_status   = FillStatus.REJECTED
            order.reject_reason = f"IBKR submit_order error: {exc}"

        return order

    def cancel_order(self, _order_id: str) -> bool:
        """
        Cancel a pending order by our UUID order_id.

        TODO: maintain self._order_map[uuid] = ib_trade in submit_order so
        we can look up the IBKR trade object here.
        For now, raises NotImplementedError with a clear message.
        """
        self._require_connection()  # raises IBKRConnectionError if not connected
        raise NotImplementedError(
            "cancel_order requires a UUID→IBKR orderId map. "
            "TODO: populate self._order_map in submit_order."
        )

    def account_equity(self) -> float:
        """
        Return current NetLiquidation (USD) from IBKR account values.

        TODO: subscribe to accountValue updates and cache locally rather than
        requesting a fresh update on every call.
        """
        try:
            import ib_async  # type: ignore  # lazy import
            ib = self._require_connection()
            ib.reqAccountUpdates()
            ib.sleep(1.0)  # allow account values to populate
            for av in ib.accountValues():
                if av.tag == "NetLiquidation" and av.currency == "USD":
                    return float(av.value)
            raise IBKRConnectionError(
                "NetLiquidation not found in IBKR account values — "
                "check that the account is fully logged in."
            )
        except IBKRConnectionError:
            raise
        except Exception as exc:
            raise IBKRConnectionError(
                f"account_equity() failed: {exc}"
            ) from exc

    def get_open_positions(self) -> Dict[str, float]:
        """Return {ticker: shares} for all open positions at IBKR.

        Queries the gateway portfolio; used at startup to detect
        state↔IBKR mismatches before generating any entry signals.
        """
        try:
            import ib_async  # type: ignore  # lazy import
            ib = self._require_connection()
            ib.reqAccountUpdates()
            ib.sleep(1.0)  # allow portfolio to populate
            result: Dict[str, float] = {}
            for item in ib.portfolio():
                if item.position != 0:
                    result[item.contract.symbol] = float(item.position)
            return result
        except IBKRConnectionError:
            raise
        except Exception as exc:
            raise IBKRConnectionError(
                f"get_open_positions() failed: {exc}"
            ) from exc
