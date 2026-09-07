"""
Stress liquidation 10:20 candidate.

Research-only engine for the 2026-08-20 Stress finding:
wait for the full 10:15-10:19 ET 5-minute bar, then enter a same-day SHORT
around 10:20 only when broad index breadth confirms liquidation.

This module is deliberately not wired into deploy_sim, run_live_day, or the
scheduler. The live signal is basket-level because it needs peer breadth across
MES/MNQ/MYM/M2K; it is not compatible with the old per-instrument
StressMidEngine.entry_signal contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time as dtime
from typing import Literal

import pandas as pd

from futures._validated_core import resample_5m
from futures.basket import BASKET


Variant = Literal["breadth3", "wide_range3"]


def _vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def _exit_short(
    fwd: pd.DataFrame,
    stop: float,
    target: float,
    end_time: dtime = dtime(14, 0),
) -> tuple[float, str, pd.Timestamp]:
    fwd = fwd[fwd.index.time <= end_time]
    if fwd.empty:
        raise ValueError("empty forward path")

    exit_px = float(fwd.iloc[-1]["close"])
    reason = "eod"
    exit_ts = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        open_px = float(bar["open"])
        if high >= stop:
            return (stop if low <= stop else open_px), "stop", ts
        if low <= target:
            return (target if high >= target else open_px), "target", ts
        exit_px = float(bar["close"])
        exit_ts = ts
    return exit_px, reason, exit_ts


def _context(day_1m: pd.DataFrame) -> dict | None:
    bars5 = resample_5m(day_1m).between_time("09:30", "14:00")
    signal_bar = bars5[bars5.index.time == dtime(10, 15)]
    entry_bar = day_1m.between_time("10:20", "10:20")
    if len(bars5) < 10 or signal_bar.empty or entry_bar.empty:
        return None

    pre = bars5[bars5.index.time <= dtime(10, 15)]
    swing = bars5[(bars5.index.time >= dtime(9, 45)) & (bars5.index.time <= dtime(10, 15))]
    open_px = float(bars5.iloc[0]["open"])
    morning_range = float(pre["high"].max() - pre["low"].min())
    return {
        "entry": float(entry_bar.iloc[-1]["open"]),
        "entry_time": entry_bar.index[-1],
        "signal_close": float(signal_bar.iloc[-1]["close"]),
        "open": open_px,
        "vwap": _vwap(pre),
        "swing_high": float(swing["high"].max()),
        "range_pct": morning_range / open_px if open_px else 0.0,
    }


@dataclass
class StressLiquidation1020Engine:
    variant: Variant = "breadth3"
    instruments: set[str] = field(default_factory=lambda: {"MNQ", "MES"})
    target_rr: float = 2.0
    stop_pad: float = 0.001
    max_stop_pct: float = 0.015
    range_threshold_pct: float = 0.0075

    def _passes_breadth(self, peer_contexts: list[dict]) -> bool:
        below_count = sum(
            1 for c in peer_contexts
            if c["signal_close"] < c["vwap"] and c["signal_close"] < c["open"]
        )
        if self.variant == "breadth3":
            return below_count >= 3
        if self.variant == "wide_range3":
            wide_count = sum(1 for c in peer_contexts if c["range_pct"] >= self.range_threshold_pct)
            return below_count >= 3 and wide_count >= 3
        raise ValueError(f"unknown variant {self.variant}")

    def _trade_for_day(self, day_1m: pd.DataFrame, ctx: dict, cost, point_value: float) -> dict | None:
        if ctx["signal_close"] >= ctx["vwap"] or ctx["signal_close"] >= ctx["open"]:
            return None
        entry = ctx["entry"]
        stop = ctx["swing_high"] * (1.0 + self.stop_pad)
        stop_dist = stop - entry
        if stop_dist <= 0 or stop_dist / entry > self.max_stop_pct:
            return None
        target = entry - self.target_rr * stop_dist
        fwd = day_1m[(day_1m.index > ctx["entry_time"]) & (day_1m.index.time <= dtime(14, 0))]
        if fwd.empty:
            return None
        exit_px, reason, exit_ts = _exit_short(fwd, stop, target)
        points = entry - exit_px
        pnl = points * point_value - cost.round_turn_cost()
        return {
            "direction": "SHORT",
            "entry": round(entry, 2),
            "exit": round(exit_px, 2),
            "points": round(points, 2),
            "pnl": round(pnl, 2),
            "reason": f"STRESS_LIQ_{self.variant}",
            "entry_time": ctx["entry_time"],
            "exit_time": exit_ts,
            "exit_reason": reason,
        }

    def backtest_basket(self, dfs: dict, labels: dict, costs: dict):
        contexts: dict[tuple[pd.Timestamp, str], dict] = {}
        day_frames: dict[tuple[pd.Timestamp, str], pd.DataFrame] = {}

        for inst, df in dfs.items():
            for day_ts, day_1m in df.groupby(df.index.normalize()):
                day = pd.Timestamp(day_ts).tz_localize(None).normalize()
                if labels.get(day) != "Stress":
                    continue
                ctx = _context(day_1m)
                if ctx:
                    contexts[(day, inst)] = ctx
                    day_frames[(day, inst)] = day_1m

        out = {inst: [] for inst in dfs}
        for (day, inst), ctx in contexts.items():
            if inst not in self.instruments:
                continue
            peer_contexts = [contexts[(day, peer)] for peer in BASKET if (day, peer) in contexts]
            if not self._passes_breadth(peer_contexts):
                continue
            contract = BASKET[inst]
            trade = self._trade_for_day(day_frames[(day, inst)], ctx, costs[inst], contract.point_value)
            if not trade:
                continue
            out[inst].append({
                "day": day.date(),
                "exit_day": day.date(),
                "regime": "Stress",
                **trade,
            })
        return out

    def entry_signals(self, bars_by_inst: dict, regime: str) -> dict:
        """Batch live entry API for future wiring.

        bars_by_inst must include raw 1-minute bars through at least 10:20 ET for
        the full R4 basket. It returns per-instrument signal dictionaries.
        """
        if regime != "Stress":
            return {}
        contexts = {inst: _context(bars) for inst, bars in bars_by_inst.items() if bars is not None}
        contexts = {inst: ctx for inst, ctx in contexts.items() if ctx is not None}
        if not self._passes_breadth([contexts[i] for i in BASKET if i in contexts]):
            return {}
        signals = {}
        for inst in self.instruments:
            ctx = contexts.get(inst)
            if not ctx or ctx["signal_close"] >= ctx["vwap"] or ctx["signal_close"] >= ctx["open"]:
                continue
            entry = ctx["entry"]
            stop = ctx["swing_high"] * (1.0 + self.stop_pad)
            stop_dist = stop - entry
            if stop_dist <= 0 or stop_dist / entry > self.max_stop_pct:
                continue
            signals[inst] = {
                "direction": "SHORT",
                "entry": entry,
                "stop": stop,
                "target": entry - self.target_rr * stop_dist,
                "entry_time": ctx["entry_time"],
            }
        return signals
