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
    commission: float | None = None # broker commission if emitted by the broker API
    error_msg: str | None = None   # set on FAILED/CANCELLED (IBKRBroker only)
    # "YYYYMM" of the contract this order actually went to, as resolved by the broker.
    # The runner copies it onto the position so the book records WHICH contract it holds.
    # Reported rather than recomputed: deriving it again from _current_front_month would
    # be a second answer to the same question, read off the wall clock instead of the
    # order that was sent — the M4 two-clocks defect. MockBroker leaves it None, so the
    # verify/replay path is unchanged.
    contract_month: str | None = None

    def __post_init__(self):
        """Normalise the expiry to the YYYYMM the rest of the system speaks.

        qualifyContracts REPLACES the contract's fields with the resolved ones, and the
        resolved expiry is a full date: ask for "202609", read back "20260911".
        exercise_rollover_live compares it with .startswith() for exactly that reason,
        and backfill_nkd passes "20260910" outright.

        Left alone, the book would carry two spellings of one month — "20260911" from an
        entry, "202612" from a roll, which reads ROLL_SCHEDULE directly — and any
        comparison between them fails silently. That is the defect this field was added
        to expose, rebuilt inside the field itself.

        Done here rather than in IBKRBroker so no broker can bypass it: the book is the
        durable artefact, and it must speak one vocabulary whoever filled the order.
        Idempotent, so the roll path's YYYYMM passes through untouched. A value that is
        not a plain digit string is left as-is rather than truncated — better visibly
        odd in the book than quietly cut down to something that looks valid.
        """
        m = self.contract_month
        if isinstance(m, str) and len(m) > 6 and m.isdigit():
            self.contract_month = m[:6]


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

    def has_working_stop(self, inst: str, direction: "str | None" = None,
                         contracts: "int | None" = None) -> bool:
        """True if THIS position is already covered by live stop orders at the broker.

        Used by B4 to decide whether a position with no recorded stop_order_id can
        safely have one re-placed. Deliberately NOT abstract: a broker that cannot
        answer should raise NotImplementedError, and B4 then alerts instead of
        placing — placing blind risks a duplicate stop, which would over-close the
        position (and flip it) when both fire.

        With `inst` alone it answers the old, weaker question — "is there ANY stop on
        this symbol". That answer is wrong as soon as two sleeves hold the same
        contract: the first position's stop makes B4 refuse to place the second's, and
        one contract then rides unprotected with nothing logged (OPERATIONS.md,
        "STRESS_MID: tại sao cron 10:20 bị TẮT"). Pass `direction` and `contracts` and
        it asks whether this position's own size is covered on its own side.

        The wider signature is optional on purpose: every existing caller keeps working,
        so nothing silently changes meaning at a site that was not reviewed.
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

    def has_working_stop(self, _inst: str, direction: "str | None" = None,
                         contracts: "int | None" = None) -> bool:
        # MockBroker's place_stop never fails, so a naked position cannot arise in
        # verify mode. False keeps the B4 re-place path exercisable in tests.
        return False

    def get_working_stops(self) -> "dict | None":
        # None, not {} — MockBroker keeps no order book, so it cannot testify that a
        # position is unprotected. Returning {} would make B4 call every position naked
        # during reconcile and change verify-mode behaviour.
        return None
