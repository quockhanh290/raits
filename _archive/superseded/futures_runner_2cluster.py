# SUPERSEDED runner (2-cluster net_exposure, pre-NKD). Risk layer replaced by
#  global_index/net_exposure_multi + live_decision. engine_signals() here is the
#  reference for the future global_index/runner.py (swing/stress live-signal).
#  NOTE: khi viết runner đầy đủ, NKD cần live-wrapper + reconcile_nkd trước khi wire live.
"""
futures/runner.py — orchestration: regime → engines → risk layer → orders
=========================================================================
Ties everything together for live/paper trading. The RISK LAYER flow is fully
implemented and testable here (sizer → net_exposure → circuit_breaker). Two
integration points are STUBS that must be wired on your machine with IBKR:

  [STUB 1] market data feed   — live bars (Polygon real-time / IBKR)
  [STUB 2] order execution    — ib_async (IB Gateway, port 7497)

ENGINE LIVE-SIGNAL APPROACH (important design choice):
The faithful way to get live signals that EXACTLY match the validated backtest is
to run the validated backtest on data-through-now and read off the latest action
— no reimplementation, no drift. swing TF (decisions in the 14:00–15:55 window,
holds days) fits a once-per-day post-15:55 run. STRESS_MID (enters 10:15, exits
by 14:00 same day) needs an intraday trigger at ~10:15. Both are marked below.

This file does NOT touch the equities engine. Self-contained + raits.hmm only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

from futures.basket import BASKET, RISK
from futures.net_exposure import NetExposureGuard, Position
from futures.circuit_breaker import CircuitBreaker
from futures.sizer import size_basket


# ── data types ────────────────────────────────────────────────────────────────
@dataclass
class Signal:
    instrument: str
    engine: str                       # "swing_tf" | "stress_mid"
    direction: Literal["LONG", "SHORT"]
    entry_price: float
    stop_price: float

    def stop_distance(self, point_value: float) -> float:
        return abs(self.entry_price - self.stop_price) * point_value  # $ per contract


@dataclass
class Order:
    instrument: str
    action: Literal["BUY", "SELL"]
    contracts: int
    kind: Literal["ENTRY", "EXIT"]
    engine: str
    note: str = ""


# ── runner ────────────────────────────────────────────────────────────────────
@dataclass
class RaitsFuturesRunner:
    contracts_per_instrument: int = 1     # from sizer (1 micro to start)
    risk_per_trade: float = field(default_factory=lambda: RISK["account"] * RISK["risk_per_trade_pct"])
    guard: NetExposureGuard = field(default_factory=NetExposureGuard)
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    open_positions: list = field(default_factory=list)   # list[Position]

    # ── per-step orchestration (call on each decision tick) ───────────────────
    def step(self, equity: float, proposed_signals: list[Signal]) -> list[Order]:
        """Given current equity + this tick's proposed entry signals from the
        engines, return the orders to send. Exits are handled separately (engines'
        own stops); this gates NEW entries through the full risk stack."""
        self.breaker.update(equity)
        cb = self.breaker.status(equity)
        orders: list[Order] = []

        if not cb["allow_new_entries"]:
            return orders   # HALT / HALT_DAY → manage open only, no new entries

        size_mult = cb["size_multiplier"]   # 0.5 on WARN, else 1.0

        # build candidate Positions (risk $ = stop distance × contracts)
        candidates = []
        for sig in proposed_signals:
            c = BASKET[sig.instrument]
            n = max(1, int(self.contracts_per_instrument * size_mult))
            risk = sig.stop_distance(c.point_value) * n
            candidates.append((sig, Position(sig.instrument, sig.direction, n, risk, sig.engine)))

        # net-exposure filter across BOTH engines + open book
        admitted, rejected = self.guard.filter_entries(
            [pos for _, pos in candidates], self.open_positions)
        admitted_keys = {(p.instrument, p.direction, p.engine) for p in admitted}

        for sig, pos in candidates:
            if (pos.instrument, pos.direction, pos.engine) in admitted_keys:
                self.open_positions.append(pos)
                orders.append(Order(
                    instrument=sig.instrument,
                    action="BUY" if sig.direction == "LONG" else "SELL",
                    contracts=pos.contracts, kind="ENTRY", engine=sig.engine,
                    note=f"{cb['level']} size×{size_mult}"))
        return orders

    def close_position(self, instrument: str, engine: str) -> Order | None:
        """Remove an open position (called when an engine's stop/exit fires)."""
        for i, p in enumerate(self.open_positions):
            if p.instrument == instrument and p.engine == engine:
                self.open_positions.pop(i)
                return Order(instrument=instrument,
                             action="SELL" if p.direction == "LONG" else "BUY",
                             contracts=p.contracts, kind="EXIT", engine=engine)
        return None

    # ── STUBS to wire on your machine ─────────────────────────────────────────
    def fetch_live_bars(self, instrument: str):
        """[STUB 1] Return recent bars for `instrument` (Polygon real-time / IBKR).
        Wire to your data feed. Should match the parquet schema used in backtest."""
        raise NotImplementedError("wire market data feed (Polygon/IBKR)")

    def send_order(self, order: Order):
        """[STUB 2] Execute via ib_async (IB Gateway, port 7497). Map micro symbol
        (MES/MNQ/MYM/M2K) to the IBKR ContFuture and place the order."""
        raise NotImplementedError("wire ib_async order execution")

    def engine_signals(self, dfs: dict, labels, costs: dict,
                       stress_bars_1015: dict | None = None,
                       today_regime: str | None = None) -> list[Signal]:
        """Produce today's ENTRY signals from BOTH engines using validated code.

        swing TF: desired_position via backtest-to-date (live == backtest). Emits
        an ENTER only for instruments where the engine wants a position we are not
        already holding.
        STRESS_MID: intraday entry_signal at 10:15 (pass stress_bars_1015: dict
        instrument -> today's bars 9:30–10:15, and today_regime). Skip otherwise.
        """
        from futures.swing_tf import SwingTFEngine
        from futures.stress_mid import StressMidEngine
        sigs: list[Signal] = []
        held = {(p.instrument, p.engine) for p in self.open_positions}

        # swing TF — reconcile to desired position
        desired = SwingTFEngine().desired_basket(dfs, labels, costs)
        for inst, d in desired.items():
            if d and (inst, "swing_tf") not in held:
                sigs.append(Signal(inst, "swing_tf", d["direction"], d["entry"], d["stop"]))

        # STRESS_MID — intraday entry at 10:15
        if stress_bars_1015 and today_regime == "Stress":
            sm = StressMidEngine()
            for inst, bars in stress_bars_1015.items():
                if (inst, "stress_mid") in held:
                    continue
                s = sm.entry_signal(bars, today_regime)
                if s:
                    sigs.append(Signal(inst, "stress_mid", s["direction"], s["entry"], s["stop"]))
        return sigs


if __name__ == "__main__":
    # offline demo of the risk-layer flow (no IBKR): swing TF long all 4 + stress short MES
    r = RaitsFuturesRunner(contracts_per_instrument=1)
    sigs = [Signal(n, "swing_tf", "LONG", 100.0, 98.0) for n in BASKET] + \
           [Signal("MES", "stress_mid", "SHORT", 100.0, 101.0)]
    orders = r.step(equity=50_000, proposed_signals=sigs)
    print(f"equity $50k, {len(sigs)} signals → {len(orders)} orders:")
    for o in orders:
        print(f"  {o.action:<4} {o.contracts} {o.instrument:<4} [{o.engine}] {o.note}")
    print(f"net-exposure state: {r.guard.state(r.open_positions)}")
    print("\nNow simulate a 15% drawdown → breaker halts new entries:")
    r2 = RaitsFuturesRunner()
    r2.breaker.update(50_000); r2.breaker.update(42_500)   # -15%
    print(f"  orders at -15% dd: {len(r2.step(42_500, sigs))} (expected 0, HALT)")
