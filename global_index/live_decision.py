"""
global_index/live_decision.py — per-day decision brain for the FUTURES system
=============================================================================
Belongs to the futures family (futures/ + global_index/ = Rổ4+STRESS+NKD). It uses
the futures risk layer (cluster caps + risk-high-first priority) from
net_exposure_multi, so it lives here, NOT at top level. A stocks system, if it ever
gets a validated edge, will have its OWN decision unit in raits/ (sizing by $,
universe scanner — different logic); do NOT force a shared base class before a second
live system actually exists (premature abstraction).
Backtest/deploy_sim runs a loop over all history with each trade's exit_day known
in advance. Live cannot: it gets today's bars and must decide TODAY. This module
extracts the per-day body of deploy_sim.replay into decide_day(), callable once per
day with only state-so-far — the ~80% of the runner that is NOT broker I/O.

Unification: decide_day reads pos.exit_day. In BACKTEST the engine sets exit_day at
entry (known); in LIVE the signal layer sets pos.exit_day = today when the chandelier
stop / max-hold / regime exit triggers. decide_day is byte-identical either way, so
replay_via_decision() below reproduces deploy_sim.replay trade-for-trade — that's the
correctness proof before this ever touches real money.

NOT here yet (needs IBKR / separate): the signal layer (engine on history-so-far →
today's entry candidates + exit triggers) and the runner I/O (fetch_live_bars,
send_order). decide_day is the brain they plug into.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from global_index.net_exposure_multi import MultiClusterGuard, Position, entry_priority_key


@dataclass
class OpenPos:
    """A live/held position. exit_day is set by the signal layer (live) or the
    engine (backtest); pnl_sized is filled at realization (broker in live)."""
    inst: str
    direction: str
    contracts: int
    risk_dollars: float
    cluster: str
    entry_day: pd.Timestamp
    exit_day: pd.Timestamp | None = None
    pnl_sized: float = 0.0
    exit_pending: bool = False  # True when CLOSE failed; _retry_pending_exits() retries next day

    def as_position(self) -> Position:
        return Position(self.inst, self.direction, self.contracts,
                        self.risk_dollars, self.cluster)


@dataclass
class DecisionState:
    equity: float
    open_positions: list = field(default_factory=list)
    cur_day: object = None
    breaker: object = None
    taken: dict = field(default_factory=dict)
    rejected: dict = field(default_factory=dict)
    halted: int = 0


@dataclass
class DayDecision:
    day: object
    exits: list          # OpenPos closed today
    entries: list        # entry candidate dicts admitted today
    rejected: list       # entry candidates blocked by cap
    halted: list         # entry candidates blocked by circuit breaker
    realized: float      # P&L realized today
    rejected_details: list = field(default_factory=list)  # per-rejection {inst,direction,cluster,risk_sized,reason}


def decide_day(day, state: DecisionState, entry_candidates, guard, contracts_by_inst):
    """One trading day. entry_candidates: list of dicts with inst/direction/cluster/
    risk_sized (+ exit/pnl_sized in backtest). Mutates state; returns DayDecision.
    Identical logic to deploy_sim.replay's loop body → matches it trade-for-trade."""
    realized = 0.0
    # 1. exits (positions whose exit_day is today)
    still, exits = [], []
    for p in state.open_positions:
        if p.exit_day == day:
            state.equity += p.pnl_sized; realized += p.pnl_sized; exits.append(p)
        else:
            still.append(p)
    state.open_positions = still

    # 2. circuit breaker (per-day)
    allow = True
    if state.breaker is not None:
        if state.cur_day is None or day != state.cur_day:
            state.breaker.start_day(state.equity); state.cur_day = day
        state.breaker.update(state.equity)
        allow = state.breaker.status(state.equity).get("allow_new_entries", True)

    # 3. entries — priority sort, cap, breaker (same order as deploy_sim)
    accepted, rejected, halted = [], [], []
    rejected_details = []
    for t in sorted(entry_candidates, key=entry_priority_key):
        if not allow:
            halted.append(t); state.halted += 1
            rejected_details.append({"inst": t["inst"], "direction": t["direction"],
                                     "cluster": t["cluster"],
                                     "risk_sized": round(t.get("risk_sized", 0), 2),
                                     "reason": "breaker_halt"})
            continue
        n = contracts_by_inst.get(t["inst"], 1)
        pos = Position(t["inst"], t["direction"], n, t["risk_sized"], t["cluster"])
        ok, why = guard.admits(pos, [p.as_position() for p in state.open_positions])
        if not ok:
            rejected.append(t); state.rejected[t["cluster"]] = state.rejected.get(t["cluster"], 0) + 1
            rejected_details.append({"inst": t["inst"], "direction": t["direction"],
                                     "cluster": t["cluster"],
                                     "risk_sized": round(t.get("risk_sized", 0), 2),
                                     "reason": "cap_gross" if "gross" in why else "cap_net" if "net" in why else "cap",
                                     "detail": why})
            continue
        accepted.append(t); state.taken[t["cluster"]] = state.taken.get(t["cluster"], 0) + 1
        newp = OpenPos(t["inst"], t["direction"], n, t["risk_sized"], t["cluster"],
                       day, t.get("exit"), t.get("pnl_sized", 0.0))
        if newp.exit_day == day:          # same-day entry+exit
            state.equity += newp.pnl_sized; realized += newp.pnl_sized
        else:
            state.open_positions.append(newp)
    return DayDecision(day, exits, accepted, rejected, halted, realized,
                       rejected_details=rejected_details)


def replay_via_decision(all_trades, account, guard, contracts_by_inst, breaker_cls):
    """Drive decide_day over full history — must equal deploy_sim.replay exactly.
    This is the correctness harness, not the live path."""
    breaker = breaker_cls(account=account) if breaker_cls else None
    state = DecisionState(equity=account,
                          taken={c: 0 for c in guard.clusters},
                          rejected={c: 0 for c in guard.clusters},
                          breaker=breaker)
    days = sorted({t["entry"] for t in all_trades} | {t["exit"] for t in all_trades})
    by_entry = {}
    for t in all_trades:
        by_entry.setdefault(t["entry"], []).append(t)
    realized = {}
    for day in days:
        dd = decide_day(day, state, by_entry.get(day, []), guard, contracts_by_inst)
        if dd.realized:
            realized[day] = realized.get(day, 0.0) + dd.realized
    return (pd.Series(realized).sort_index(),
            dict(taken=state.taken, rejected=state.rejected, halted=state.halted))
