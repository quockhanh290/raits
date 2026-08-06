"""
global_index/broker.py — Broker interface + MockBroker for the futures runner
=============================================================================
The runner talks to a Broker interface, never to IBKR directly. Swap the implementation
to go from offline verification to live:
    MockBroker  → offline replay of historical bars, fills from a known ledger
                  (verify runner orchestration == deploy_sim)
    IBKRBroker  → ib_async / IB Gateway 7497 (live; written when IBKR account is up)

WHAT runner+MockBroker VERIFIES: the orchestration loop is correct — order lifecycle
(entry → open position → exit), state via the broker (get_positions == internal), exit
timing, cap/priority applied in the live day-by-day flow. The DECISION correctness
(taken/rejected/pnl == deploy_sim) is already proven by the signal_layer e2e test.

WHAT it does NOT verify: real fill quality (slippage, partial fills, latency) — that is
deploy_sim's assumption (1-tick) and only real paper/live tests it. MockBroker in verify
mode realizes pnl from the backtest ledger so the loop can be checked against deploy_sim
apples-to-apples; it does not re-derive pnl from bars (that would change the fill model
and break the comparison for reasons unrelated to orchestration).
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Order:
    inst: str
    action: str          # "OPEN" | "CLOSE"
    direction: str       # "LONG" | "SHORT"
    contracts: int
    cluster: str
    ref_day: object      # trading day this order belongs to
    # verify-mode metadata: lets MockBroker realize the backtest pnl for this trade
    exit_day: object = None
    pnl_sized: float = 0.0


@dataclass
class Fill:
    inst: str
    action: str
    direction: str
    contracts: int
    cluster: str
    pnl_sized: float = 0.0        # realized on CLOSE (verify mode: from ledger)
    status: str = "FILLED"         # "FILLED" | "PARTIAL" | "CANCELLED" | "FAILED"
    filled_qty: int = 0            # 0 = full fill; IBKRBroker sets from execution report
    avg_price: float = 0.0         # fill price; IBKRBroker sets from execution report
    error_msg: str | None = None   # set on FAILED/CANCELLED (IBKRBroker only)


@dataclass
class BrokerPosition:
    inst: str
    direction: str
    contracts: int
    cluster: str
    entry_day: object
    exit_day: object = None
    pnl_sized: float = 0.0


class Broker(ABC):
    """Interface the runner depends on. IBKRBroker implements the same methods later."""
    @abstractmethod
    def fetch_bars(self, inst: str, through) -> pd.DataFrame: ...
    @abstractmethod
    def send_order(self, order: Order) -> Fill: ...
    @abstractmethod
    def get_positions(self) -> list: ...
    @abstractmethod
    def get_equity(self) -> float: ...
    @abstractmethod
    def place_stop(self, inst: str, direction: str, contracts: int,
                   stop_price: float, cluster: str) -> str:
        """Place a GTC stop order for exit protection on a multi-day position.
        Returns the broker order ID string on success, '' on failure.
        LONG → SELL STP at stop_price; SHORT → BUY STP at stop_price."""
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by ID. Returns True if cancelled, False if not found/failed."""
    @abstractmethod
    def get_order_status(self, order_id: str) -> str:
        """Returns 'FILLED' | 'CANCELLED' | 'PENDING' | 'NOT_FOUND'."""

    def get_working_stops(self) -> "dict | None":
        """{inst: order_id} for every stop currently working at the broker.

        None means "this broker cannot answer" — callers must not read that as
        "no stops exist". The distinction matters: B4 uses a populated dict to
        overrule a locally recorded stop_order_id, and must fall back to the
        recorded field when the broker is silent rather than declaring every
        position naked.

        One round trip for all instruments, unlike has_working_stop() which costs
        a query each — B4 runs on every 5-minute slot.
        """
        raise NotImplementedError

    def has_working_stop(self, inst: str) -> bool:
        """True if a live (working) stop order exists at the broker for `inst`.

        Used by B4 to decide whether a position with no recorded stop_order_id can
        safely have one re-placed. Deliberately NOT abstract: a broker that cannot
        answer should raise NotImplementedError, and B4 then alerts instead of
        placing — placing blind risks a duplicate stop, which would over-close the
        position (and flip it) when both fire.
        """
        raise NotImplementedError


class MockBroker(Broker):
    """Offline replay broker. fetch_bars serves historical bars up to `through`.
    send_order records positions; CLOSE realizes pnl from the order's ledger metadata
    (verify mode) so runner output can be compared to deploy_sim trade-for-trade."""

    def __init__(self, bars_by_inst: dict, account: float):
        self._bars = bars_by_inst              # {inst: full historical DataFrame}
        self._equity = float(account)
        self._positions: list = []             # list[BrokerPosition] (allows >1 per inst)
        self.fills: list = []

    def fetch_bars(self, inst: str, through) -> pd.DataFrame:
        df = self._bars.get(inst)
        if df is None:
            return pd.DataFrame()
        return df[df.index <= through]         # causal: only bars through `through`

    def send_order(self, order: Order) -> Fill:
        if order.action == "OPEN":
            self._positions.append(BrokerPosition(
                order.inst, order.direction, order.contracts, order.cluster,
                order.ref_day, order.exit_day, order.pnl_sized))
            f = Fill(order.inst, "OPEN", order.direction, order.contracts, order.cluster)
        else:  # CLOSE — remove one matching position; realize the order's pnl (verify:
               # runner passes the closed position's ledger pnl → equity is exact)
            for i, p in enumerate(self._positions):
                if (p.inst, p.cluster, p.direction) == (order.inst, order.cluster, order.direction):
                    self._positions.pop(i)
                    break
            self._equity += order.pnl_sized
            f = Fill(order.inst, "CLOSE", order.direction, order.contracts,
                     order.cluster, pnl_sized=order.pnl_sized)
        self.fills.append(f)
        return f

    def get_positions(self) -> list:
        return list(self._positions)

    def get_equity(self) -> float:
        return self._equity

    def place_stop(self, inst, _direction, _contracts, _stop_price, _cluster) -> str:
        return f"mock-stp-{inst}"

    def cancel_order(self, _order_id) -> bool:
        return True

    def get_order_status(self, _order_id) -> str:
        return "PENDING"

    def has_working_stop(self, _inst: str) -> bool:
        # MockBroker's place_stop never fails, so a naked position cannot arise in
        # verify mode. False keeps the B4 re-place path exercisable in tests.
        return False

    def get_working_stops(self) -> "dict | None":
        # None, not {} — MockBroker keeps no order book, so it cannot testify that a
        # position is unprotected. Returning {} would make B4 call every position naked
        # during reconcile and change verify-mode behaviour.
        return None
