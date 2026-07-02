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
    pnl_sized: float = 0.0   # realized on CLOSE (verify mode: from ledger)


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
