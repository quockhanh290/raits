"""global_index/track1_normal_filters.py — the Normal-R4 context filters, promoted.

Stage 4. Pure and offline: frames in, booleans out. No engine import, no monkeypatch,
nothing that can decide a trade on its own.

Why this file exists rather than an import from scratch
-------------------------------------------------------
`scratch/normal_promotion_filter_lib_20260821.py` opens with a rule this promotion has to
respect rather than break:

    "There is exactly one implementation on purpose. Proving that a filter implementation is
     causal says nothing about a second implementation that the strategy actually runs."

So this is a **promotion, not a re-derivation**: the code below is the same code, moved into
the package, and `scratch/test_track1_stage4_production_clean_20260823.py` asserts that this
module and the scratch original return the SAME verdict for every 5-minute bar of a real
instrument. Two copies that agree on every bar of eight years are one implementation with two
addresses; two copies nobody compared are two implementations.

The three gates, and what each reads
-------------------------------------
    prior-day range   the PRIOR session's RTH (09:30-16:00 ET) high-low over its close, and
                      it must be <= a threshold frozen on the floor window.
    entry-bar rvol    the 5-minute entry bar's volume over the median volume of the SAME
                      time-of-day slot across the previous 20 sessions, <= 2.0.
    SPY short gate    SHORT entries only, and only when SPY's D-1 close is below its 50-day
                      SMA. LONG is never gated.

Causality, stated where it can be checked
------------------------------------------
Every feature is built with an explicit shift so the value attached to session D is a
function of sessions strictly before D — except the entry bar's own volume, which is known at
the decision instant because the engine enters at that bar's CLOSE and `check_volume_pattern`
already reads it. `rvol_prevbar` is kept as the stricter alternative that touches nothing from
the entry bar.

The SPY gate shifts both the close and the rolling mean, so the D-1 wording is literal. It was
proved by mutation rather than by reading: scaling SPY's close at D by ten leaves D's own
verdict unchanged and moves only days after D.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

RTH_START = pd.Timestamp("09:30").time()
RTH_END = pd.Timestamp("16:00").time()
SLOT_WINDOW = 20
SLOT_MIN_PERIODS = 5

#: p90 of prior-day RTH range % across R4 Normal entries on the floor window (2018-2024),
#: frozen by scratch/normal_sleeve_context_combo_probe_20260821.py. A threshold, not a table
#: of answers — and it travels in the route identity, so a change to it changes the hash.
FLOOR_RANGE_P90 = 0.02652437134968455
VOL_LE = 2.0

SPY_SHORT_LOOKBACK = 50
SPY_SHORT_LAG_DAYS = 1


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

        slot_med20     median volume of this time-of-day slot over the previous 20 sessions,
                       EXCLUDING this session (shift(1) inside the slot)
        rvol_slot20    this bar's volume / slot_med20   (the entry bar; known at its close)
        rvol_prevbar   the PREVIOUS 5m bar's volume / that bar's slot_med20
    """
    b = bars_5m(df1m).copy()
    b["_time"] = b.index.time
    parts = []
    for _, g in b.groupby("_time", sort=False):
        parts.append(g["volume"].shift(1).rolling(SLOT_WINDOW,
                                                  min_periods=SLOT_MIN_PERIODS).median())
    b["slot_med20"] = pd.concat(parts).sort_index()
    b["rvol_slot20"] = b["volume"] / b["slot_med20"]
    b["rvol_prevbar"] = b["rvol_slot20"].shift(1)
    return b


def prev_rth_range_map(df1m: pd.DataFrame) -> dict:
    """{session day (tz-naive, normalised) -> the PRIOR session's RTH range %}."""
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
    """The decision-boundary gate for one R4 instrument.

    `allow(bar_ts)` is asked with the timestamp of the 5-minute resume bar. It answers from
    the frames built above and nothing else, so the same object can serve an audit and a run.
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
        return {"prev_range_pct": pr, "rvol": rv, "day": day,
                "in_vol_index": ts in self.vol.index}

    def allow(self, bar_ts) -> bool:
        self.seen += 1
        f = self.features(bar_ts)
        pr, rv = f["prev_range_pct"], f["rvol"]
        if not np.isfinite(pr) or not np.isfinite(rv):
            # A missing feature is a BLOCK — counted separately so "the filter worked" can
            # never be confused with "the feature was not there".
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


# ---------------------------------------------------------------------------
# the SPY short gate
# ---------------------------------------------------------------------------
def spy_feature_frame(spy_csv: str | Path) -> pd.DataFrame:
    """The D-1 market-context features, every one of them shifted.

    Only `above_sma50` is read by the shipped Normal config; the rest are kept because the
    original computes them together and dropping columns here would make the promoted copy
    and the scratch original diverge on something other than the rule under test.
    """
    spy = pd.read_csv(spy_csv, parse_dates=["date"]).set_index("date")["close"].sort_index()
    ret = spy.pct_change()
    c = spy.shift(SPY_SHORT_LAG_DAYS)
    f = pd.DataFrame(index=spy.index)
    f["ret20"] = c / spy.shift(21) - 1.0
    f["rv20"] = ret.rolling(20).std().shift(1) * (252 ** 0.5)
    f["dd63"] = c / spy.rolling(63).max().shift(1) - 1.0
    f["above_sma50"] = c > spy.rolling(SPY_SHORT_LOOKBACK).mean().shift(1)
    f["above_sma200"] = c > spy.rolling(200).mean().shift(1)
    return f


def allowed_short_days(f: pd.DataFrame, name: str = "below_sma50") -> set:
    """The set of session days on which a SHORT entry is permitted.

    `below_sma50` is the shipped Normal configuration — applied unconditionally by the
    generator that wrote the promotion artifacts, ahead of the R4 context filter. The other
    names are the alternatives that were measured against it and not chosen; they are kept so
    this function is the same function, not a narrowed one.
    """
    if name == "dd63_le_-3":
        m = f["dd63"] <= -0.03
    elif name == "dd63_le_-5":
        m = f["dd63"] <= -0.05
    elif name == "ret20_le_0":
        m = f["ret20"] <= 0
    elif name == "below_sma50":
        m = ~f["above_sma50"]
    elif name == "weak_combo":
        m = (f["dd63"] <= -0.03) | (f["ret20"] <= 0) | (~f["above_sma50"])
    elif name == "not_strong_bull":
        m = (f["dd63"] <= -0.03) | (~f["above_sma50"])
    else:
        raise ValueError(f"unknown short filter {name}")
    return {pd.Timestamp(d).normalize() for d in f.index[m.fillna(False)]}


def short_days_from_csv(spy_csv: str | Path, name: str = "below_sma50") -> set:
    return allowed_short_days(spy_feature_frame(spy_csv), name)
