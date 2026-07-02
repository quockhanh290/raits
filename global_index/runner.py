"""
global_index/runner.py — the futures live loop (orchestration)
==============================================================
One place that wires everything: each trading day →
    broker.fetch_bars → signal_layer.generate_today_signals → decide_day (risk brain)
    → broker.send_order (exits then entries) → state synced to broker.

The SAME runner drives MockBroker (offline verify vs deploy_sim) and IBKRBroker (live).
Swapping is one line: `FuturesRunner(broker=MockBroker(...))` → `broker=IBKRBroker(...)`.

Decision correctness (signal+decide == deploy_sim) is already proven by the signal_layer
e2e test. This file adds ORCHESTRATION: order lifecycle, broker/state reconciliation,
exit-before-entry ordering. run_history() replays through a MockBroker to check that
orchestration reproduces deploy_sim's decision stream.

CWD + encoding guards below: code must run from repo root (raits package resolves there,
not from D:\\raits\\raits), and stdout must be UTF-8 (log lines contain non-ASCII like
"Rổ 4" — cp1252 console crashes mid-run otherwise).
"""
from __future__ import annotations
import sys
from pathlib import Path

# --- CWD / path guard: ensure repo root on path regardless of launch dir ---
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# --- encoding guard: non-ASCII log lines must not crash on Windows cp1252 ---
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from global_index.broker import Order
from global_index.live_decision import decide_day, DecisionState, OpenPos


class FuturesRunner:
    """Drives the daily loop through a Broker. In verify mode, entry candidates carry
    their ledger exit_day/pnl_sized so MockBroker realizes deploy_sim-equivalent pnl."""

    def __init__(self, broker, guard, contracts_by_inst, signal_fn):
        """signal_fn(day, bars_by_inst, held) -> (entry_candidates, exit_positions)
        wraps signal_layer.generate_today_signals with the engines/labels/costs bound.
        Injecting it keeps the runner testable without real engines."""
        self.broker = broker
        self.guard = guard
        self.contracts = contracts_by_inst
        self.signal_fn = signal_fn
        self.state = DecisionState(
            equity=broker.get_equity(),
            taken={c: 0 for c in guard.clusters},
            rejected={c: 0 for c in guard.clusters})

    def run_day(self, day):
        """One trading day. Returns the DayDecision. Syncs broker to the brain's state."""
        # 1. fetch bars through today (per instrument) — causal
        insts = {p.inst for p in self.state.open_positions} | set(self.contracts)
        bars = {i: self.broker.fetch_bars(i, through=day) for i in insts}

        # 2. signals for today (entries + which held positions to exit)
        entry_candidates, exit_positions = self.signal_fn(day, bars, self.state.open_positions)

        # 3. mark exits so decide_day closes them today (live: signal sets exit_day)
        exit_keys = {(p.inst, p.cluster) for p in exit_positions}
        for p in self.state.open_positions:
            if (p.inst, p.cluster) in exit_keys:
                p.exit_day = day

        # 4. risk brain — same decide_day validated vs deploy_sim
        decision = decide_day(day, self.state, entry_candidates, self.guard, self.contracts)

        # 5. execute: CLOSE exits first, then OPEN admitted entries (order matters for cap)
        for p in decision.exits:
            self.broker.send_order(Order(
                p.inst, "CLOSE", p.direction, p.contracts, p.cluster, day,
                exit_day=day, pnl_sized=p.pnl_sized))
        for t in decision.entries:
            n = self.contracts.get(t["inst"], 1)
            self.broker.send_order(Order(
                t["inst"], "OPEN", t["direction"], n, t["cluster"], day,
                exit_day=t.get("exit"), pnl_sized=t.get("pnl_sized", 0.0)))
            # same-day entry+exit (hold=0): decide_day realizes it inline and never
            # holds it → runner must CLOSE it today so the broker realizes pnl too.
            if t.get("exit") == day:
                self.broker.send_order(Order(
                    t["inst"], "CLOSE", t["direction"], n, t["cluster"], day,
                    exit_day=day, pnl_sized=t.get("pnl_sized", 0.0)))

        return decision

    def run_history(self, days):
        """Replay a sequence of days through the broker. Returns realized-pnl series +
        taken/rejected — compare to deploy_sim for the orchestration proof."""
        import pandas as pd
        realized = {}
        for day in days:
            d = self.run_day(day)
            if d.realized:
                realized[day] = realized.get(day, 0.0) + d.realized
        return (pd.Series(realized).sort_index() if realized else pd.Series(dtype=float),
                dict(taken=self.state.taken, rejected=self.state.rejected,
                     halted=self.state.halted, final_equity=self.broker.get_equity()))
