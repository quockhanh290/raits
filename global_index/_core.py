"""
nonequity/_core.py — self-contained validated primitives (verbatim copies)
==========================================================================
These are VERBATIM copies of the validated functions in
futures/_validated_core.py and futures/cost.py, copied here so nonequity/ runs
standalone (no root-script / no equity-RTH import). If the validated originals
ever change, re-sync these and re-run any reconcile.

Copied:
  load_parquet, atr14, resample_5m, daily_atr_series, Trade  (from _validated_core)
  FuturesCost                                                 (from cost.py)

NOT copied: backtest_swing_tf / StressMidAdapter — those are the equity power-hour
entry (between_time 14:00-15:55 / 09:30-14:00) and are deliberately excluded; the
daily-bar entry lives in swing_tf_daily.py.
"""
# COPY of futures/_validated_core primitives (canonical = futures/_validated_core.py).
# Sync thu cong + re-run futures.reconcile_gd0 / reconcile_stress neu source doi.
# NOTE: docstring tren ghi "nonequity/_core.py" la copy artifact — day la global_index/_core.py.
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

ET = "America/New_York"


def load_parquet(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df.columns = [c.lower() for c in df.columns]
    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        raise ValueError(f"parquet missing columns {need - set(df.columns)}")
    idx = pd.to_datetime(df.index, utc=True)
    df = df.set_index(idx).sort_index()
    df.index = df.index.tz_convert(ET)        # <-- the Phase-1 UTC→ET danger zone
    return df[["open", "high", "low", "close", "volume"]]


def atr14(bars: pd.DataFrame) -> float:
    if len(bars) < 2:
        return float("nan")
    h, l, c = bars["high"], bars["low"], bars["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.tail(14).mean())


def resample_5m(day1m: pd.DataFrame) -> pd.DataFrame:
    o = day1m["open"].resample("5min").first()
    h = day1m["high"].resample("5min").max()
    l = day1m["low"].resample("5min").min()
    c = day1m["close"].resample("5min").last()
    v = day1m["volume"].resample("5min").sum()
    out = pd.concat([o, h, l, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna()


def daily_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """14-period ATR on daily-resampled OHLC, indexed by (tz-naive) day."""
    d = df.resample("B").agg({"open": "first", "high": "max",
                              "low": "min", "close": "last"}).dropna()
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                    (d["low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    atr.index = pd.DatetimeIndex(atr.index).tz_localize(None).normalize()
    return atr.dropna()


def daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Daily-resampled OHLC (business day), tz-naive day index. Session-agnostic:
    one bar per calendar trading day across the full ~23h continuous session —
    no equity-RTH window is imposed. This is the bar the daily-trend entry uses."""
    d = df.resample("B").agg({"open": "first", "high": "max", "low": "min",
                              "close": "last", "volume": "sum"}).dropna()
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    return d


@dataclass
class Trade:
    day: pd.Timestamp
    regime: str
    direction: str
    entry: float
    exit: float
    points: float
    pnl: float          # dollars after cost
    entry_time: Optional[pd.Timestamp] = None
    exit_time: Optional[pd.Timestamp] = None
    meta: dict = field(default_factory=dict)


@dataclass
class FuturesCost:
    point_value: float = 5.0
    tick: float = 0.25
    tick_value: float | None = None
    commission_rt: float = 1.24
    slippage_ticks_per_side: float = 1.0

    def __post_init__(self):
        if self.tick_value is None:
            self.tick_value = self.tick * self.point_value

    def round_turn_cost(self) -> float:
        slip = 2.0 * self.slippage_ticks_per_side * self.tick_value
        return self.commission_rt + slip

    def stressed(self, mult: float = 2.0) -> "FuturesCost":
        return FuturesCost(point_value=self.point_value, tick=self.tick,
                           commission_rt=self.commission_rt * mult,
                           slippage_ticks_per_side=self.slippage_ticks_per_side * mult)
