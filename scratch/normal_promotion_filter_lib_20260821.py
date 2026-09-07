"""
scratch/normal_promotion_filter_lib_20260821.py - ONE implementation of the
Normal-R4 context filter `range_p90__vol_le_2`, shared by the lookahead audit and
by the decision-boundary regeneration. Scratch / read-only.

There is exactly one copy on purpose. Proving that a filter implementation is
causal says nothing about a second implementation that the strategy actually
runs; the audit and the run have to be the same code or the proof is decoration.

Filter definition (R4 only, never NKD):

  prior-day range   prior SESSION's RTH (09:30-16:00 ET) high-low divided by that
                    session's close, must be <= a threshold frozen from the floor
                    window.
  entry-bar rvol    the 5-minute entry bar's volume divided by the median volume
                    of the SAME time-of-day slot over the previous 20 sessions,
                    must be <= 2.0.

Both features are built with an explicit shift so that the value attached to
session D is a function of sessions strictly before D, except for the entry bar's
own volume - which is known at the decision instant because the engine enters at
that bar's CLOSE and already reads that same bar's volume in
`check_volume_pattern`. `rvol_prevbar` is provided as the stricter alternative
that does not use the entry bar at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

RTH_START = pd.Timestamp("09:30").time()
RTH_END = pd.Timestamp("16:00").time()
SLOT_WINDOW = 20
SLOT_MIN_PERIODS = 5

# Frozen on the floor window by scratch/normal_sleeve_context_combo_probe_20260821.py
# (p90 of prior-day RTH range % across R4 Normal entries, floor 2018-2024).
FLOOR_RANGE_P90 = 0.02652437134968455
VOL_LE = 2.0


def bars_5m(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"].resample("5min").first()
    h = df["high"].resample("5min").max()
    l = df["low"].resample("5min").min()
    c = df["close"].resample("5min").last()
    v = df["volume"].resample("5min").sum()
    out = pd.concat([o, h, l, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna()


def slot_volume_frame(df1m: pd.DataFrame) -> pd.DataFrame:
    """5-minute frame carrying, per bar:
        slot_med20     median volume of this time-of-day slot over the previous 20
                       sessions, EXCLUDING this session (shift(1) inside the slot).
        rvol_slot20    this bar's volume / slot_med20   (entry bar; known at close)
        rvol_prevbar   the PREVIOUS 5m bar's volume / that bar's slot_med20
                       (uses nothing from the entry bar at all)
    """
    b = bars_5m(df1m).copy()
    b["_time"] = b.index.time
    parts = []
    for _, g in b.groupby("_time", sort=False):
        parts.append(g["volume"].shift(1).rolling(SLOT_WINDOW,
                                                  min_periods=SLOT_MIN_PERIODS).median())
    b["slot_med20"] = pd.concat(parts).sort_index()
    b["rvol_slot20"] = b["volume"] / b["slot_med20"]
    # previous completed bar, in bar order, not in slot order
    b["rvol_prevbar"] = b["rvol_slot20"].shift(1)
    return b


def prev_rth_range_map(df1m: pd.DataFrame) -> dict:
    """{session day (tz-naive, normalised) -> prior session's RTH range %}."""
    idx = df1m.index.tz_localize(None) if df1m.index.tz is not None else df1m.index
    d = df1m.copy()
    d.index = idx
    rth = d[(d.index.time >= RTH_START) & (d.index.time <= RTH_END)]
    if rth.empty:
        return {}
    g = rth.groupby(rth.index.normalize())
    daily = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(),
                          "close": g["close"].last()})
    rng = (daily["high"] - daily["low"]) / daily["close"].abs().clip(lower=1e-9)
    prev = rng.shift(1)
    return {pd.Timestamp(k).normalize(): float(v)
            for k, v in prev.items() if np.isfinite(v)}


class R4ContextFilter:
    """Decision-boundary gate for one R4 instrument.

    `allow(bar_ts)` is called from inside the strategy's signal generation, with
    the timestamp of the 5-minute resume bar. It answers using only the frames
    built above, so the same object serves the audit and the run.
    """

    def __init__(self, df1m: pd.DataFrame, *, range_max: float = FLOOR_RANGE_P90,
                 vol_max: float = VOL_LE, vol_feature: str = "rvol_slot20"):
        self.vol = slot_volume_frame(df1m)
        self.prev_range = prev_rth_range_map(df1m)
        self.range_max = range_max
        self.vol_max = vol_max
        self.vol_feature = vol_feature
        self.seen = 0
        self.blocked_range = 0
        self.blocked_vol = 0
        self.blocked_missing = 0

    def features(self, bar_ts) -> dict:
        ts = pd.Timestamp(bar_ts)
        day = (ts.tz_localize(None) if ts.tz is not None else ts).normalize()
        pr = self.prev_range.get(day, np.nan)
        rv = np.nan
        if ts in self.vol.index:
            v = self.vol.loc[ts, self.vol_feature]
            rv = float(v) if pd.notna(v) else np.nan
        return {"prev_range_pct": pr, "rvol": rv, "day": day, "in_vol_index": ts in self.vol.index}

    def allow(self, bar_ts) -> bool:
        self.seen += 1
        f = self.features(bar_ts)
        pr, rv = f["prev_range_pct"], f["rvol"]
        if not np.isfinite(pr) or not np.isfinite(rv):
            # A missing feature is a BLOCK, matching the post-processing probes,
            # but it is counted separately so "the filter worked" can never be
            # confused with "the feature was not there".
            self.blocked_missing += 1
            return False
        if pr > self.range_max:
            self.blocked_range += 1
            return False
        if rv > self.vol_max:
            self.blocked_vol += 1
            return False
        return True

    def stats(self) -> dict:
        return dict(seen=self.seen, blocked_range=self.blocked_range,
                    blocked_vol=self.blocked_vol, blocked_missing=self.blocked_missing,
                    passed=self.seen - self.blocked_range - self.blocked_vol
                    - self.blocked_missing)
