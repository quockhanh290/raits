"""
futures/cost.py — per-contract cost model for the futures basket
================================================================
Self-contained (no import from the equities engine). Commission + slippage in
$ per round-turn, per contract. tick_value auto-derives from tick × point_value
so it always tracks the instrument (never hardcode one product's tick value).

Matches the validated harness FuturesCost exactly (same numbers that produced
the gap-fill-correct WFO 2.29 / vault 3.18). Slippage default 1 tick/side;
backtests stress-tested at 2-3 ticks and 2× cost and still passed.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class FuturesCost:
    point_value: float = 5.0        # $ per index point (MES 5, MNQ 2, MYM 0.5, M2K 5)
    tick: float = 0.25              # index points per tick
    tick_value: float | None = None # auto = tick × point_value
    commission_rt: float = 1.24     # all-in round-turn, micro (CONFIRM with IBKR tier)
    slippage_ticks_per_side: float = 1.0

    def __post_init__(self):
        if self.tick_value is None:
            self.tick_value = self.tick * self.point_value

    def round_turn_cost(self) -> float:
        """Total $ cost for one contract entry+exit (commission + 2-sided slippage)."""
        slip = 2.0 * self.slippage_ticks_per_side * self.tick_value
        return self.commission_rt + slip

    def stressed(self, mult: float = 2.0) -> "FuturesCost":
        """Return a copy at mult× commission and slippage (for cost-stress tests)."""
        return FuturesCost(point_value=self.point_value, tick=self.tick,
                           commission_rt=self.commission_rt * mult,
                           slippage_ticks_per_side=self.slippage_ticks_per_side * mult)
