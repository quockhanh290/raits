"""
gate2_edge_harness.py — RAITS × MES Gate 2 edge-validation harness
===================================================================
STANDALONE, READ-ONLY. Answers the kill question of the Edge Validation Plan:

    "Does any strategy have positive expectancy IN ITS OWN REGIME on a single
     index-futures instrument, AFTER futures costs?"

It imports and runs the *real* RAITS components being validated:
    - raits.hmm.engine.HMMEngine            (regime labels)
    - raits.strategies.trend_follow.TrendFollowStrategy
    - raits.strategies.orb.ORBStrategy
    - raits.strategies.vwap_mr.VWAPMRStrategy

WHAT THIS FILE DELIBERATELY DOES **NOT** TOUCH (engine-safety guarantee)
-----------------------------------------------------------------------
    * Does NOT import or run raits.backtest.engine.BacktestEngine.
    * Does NOT modify ANY project file. Strategies/HMM are imported read-only.
    * Does NOT write HMM model files  (HMMEngine.fit(..., save=False)).
    * Does NOT read or write the vault, configs, or production parameters.
    * Implements its OWN minimal single-instrument backtest loop here, so the
      production engine's already-locked stock edge is never disturbed.

The strategy *decision logic* (generate_signal) is the real code. Only the
single-instrument replay loop (entry windows, indicator inputs, exit handling)
is reimplemented locally — because the production engine bakes in the
universe-scan + stock assumptions we are explicitly leaving untouched.

VALIDATION STATUS (from sandbox smoke run against the real modules)
------------------------------------------------------------------
    trend_follow : FULLY EXERCISED — real HMM labels regimes, real
                   generate_signal fires, entry→Chandelier-exit→record→
                   per-regime table→verdict all run. (Synthetic P&L is
                   meaningless; only the plumbing is proven.)
    vwap_mr      : entry→exit→record path EXERCISED (fired on smoke data).
                   Eyeball once on real data before trusting its verdict.
    orb          : imports/wires/calls cleanly (no crash) but did NOT fire on
                   the trend-only smoke data, so its entry/exit branch is
                   UNPROVEN. Feed ORB-friendly data (gap + opening-range break
                   + RVol surge) and eyeball before trusting its verdict.
    stress_mid   : REIMPLEMENTED from stress_mid_sim.py (no engine class exists);
                   entry/exit path verified on a constructed Stress down-day
                   (fires SHORT at 10:15, skips up-days). Eyeball on real ES.

    => For the decisive first Gate-2 run, use trend_follow. Validate orb/vwap_mr
       wiring on real ES data (a few eyeballed trades) before relying on them.

Usage
-----
    # plumbing check, no data/credit needed (synthetic bars):
    python gate2_edge_harness.py --smoke-test --strategy trend_follow

    # real run on Databento ES 1-min continuous parquet:
    python gate2_edge_harness.py --parquet data/cache/futures/ES_continuous_1m.parquet \\
        --strategy trend_follow --hmm-train-end 2022-06-30 --point-value 5.0

Point value defaults to MES ($5/pt). Pass --point-value 50 to score as full ES.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import time as dtime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

# ── Project import path ───────────────────────────────────────────────────────
# Run from project root so `raits` package resolves. We insert CWD defensively.
sys.path.insert(0, str(Path.cwd()))

ET = "America/New_York"


# ══════════════════════════════════════════════════════════════════════════════
# 1. Futures cost model (configurable; defaults verified June 2026, MES)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class FuturesCost:
    point_value: float = 5.0       # MES $5/pt  (ES = 50, MNQ = 2, NQ = 20)
    tick: float = 0.25             # index points per tick
    tick_value: float = None       # auto = tick × point_value (MES 1.25, MNQ 0.50, ES 12.50)
    commission_rt: float = 1.24    # all-in round-turn, micro (broker-dependent)
    slippage_ticks_per_side: float = 1.0

    def __post_init__(self):
        # tick_value must track the instrument; never hardcode MES's $1.25 for MNQ
        if self.tick_value is None:
            self.tick_value = self.tick * self.point_value

    def round_turn_cost(self) -> float:
        """Total $ cost for one contract entry+exit."""
        slip = 2.0 * self.slippage_ticks_per_side * self.tick_value
        return self.commission_rt + slip


# ══════════════════════════════════════════════════════════════════════════════
# 2. Data loading  (real parquet  OR  synthetic smoke data)
# ══════════════════════════════════════════════════════════════════════════════
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


def make_smoke_data(n_days: int = 160, seed: int = 7) -> pd.DataFrame:
    """
    Synthetic 1-min RTH bars engineered ONLY to light up the full pipeline.
    Design trick (so signals actually fire):
      * Day-to-day return magnitude varies by block → HMM sees high *daily*
        realized vol on some blocks → labels Normal/Stress (TF's regimes).
      * WITHIN a trending day, the intraday path is a smooth drift with tiny
        noise → close stays within EMA-proximity (0.5%) so TF can trigger.
      * In the 14:00-15:55 window we stamp explicit pullback(low-vol)→
        resume(high-vol) bar pairs in the trend direction.
    NOT realistic. A verdict on this data only proves plumbing, never edge.
    """
    rng = np.random.default_rng(seed)
    rows = []
    price = 4000.0
    day0 = pd.Timestamp("2022-01-03 09:30", tz=ET)
    d = made = 0
    while made < n_days:
        day = day0 + pd.Timedelta(days=d); d += 1
        if day.weekday() >= 5:
            continue
        made += 1
        block = (made // 20) % 3                       # 0 calm, 1 normal, 2 stress
        # daily move size drives the HMM (day-to-day vol); big on higher blocks
        day_ret = rng.normal(0, {0: 0.0015, 1: 0.010, 2: 0.022}[block])
        base_open = price
        target = base_open * (1 + day_ret)
        minutes = pd.date_range(day, periods=390, freq="1min")
        trending = block >= 1 and abs(day_ret) > 0.004
        sgn = 1 if day_ret > 0 else -1
        # 5-min buckets to stamp: (pullback_bucket_start, resume_bucket_start)
        pull_buckets = {dtime(14, 30), dtime(15, 0), dtime(15, 30)}
        res_buckets = {dtime(14, 35), dtime(15, 5), dtime(15, 35)}
        for k, ts in enumerate(minutes):
            frac = k / 389.0
            base = base_open + (target - base_open) * frac        # smooth intraday drift
            noise = rng.normal(0, base * 0.0006)                  # tiny → EMA proximity ok
            close = max(50.0, base + noise)
            op = close - rng.normal(0, base * 0.0004)
            hi = max(op, close) + abs(rng.normal(0, base * 0.0004))
            lo = min(op, close) - abs(rng.normal(0, base * 0.0004))
            vol = int(rng.integers(1200, 1800))                   # ~7500 per 5-min bucket
            bstart = ts.floor("5min").time()
            if trending and bstart in pull_buckets:
                vol = 400                                         # 5×400=2000 « avg → pullback
                close = base - sgn * base * 0.0008                # dip back toward EMA
                lo = min(lo, close - base * 0.0003); hi = max(hi, close)
            elif trending and bstart in res_buckets:
                vol = 2600                                        # 5×2600=13000 » 1.3×avg → resume
                close = base + sgn * base * 0.0012                # push in trend direction
                hi = max(hi, close + base * 0.0003); lo = min(lo, op)
            price = close
            rows.append((ts, op, hi, lo, close, vol))
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    return df


# ══════════════════════════════════════════════════════════════════════════════
# 3. Regime labelling via the REAL HMMEngine  (one label per trading day)
# ══════════════════════════════════════════════════════════════════════════════
def daily_close_series(df1m: pd.DataFrame) -> pd.Series:
    """RTH daily close (last bar at/under 16:00 ET) indexed by date."""
    rth = df1m.between_time("09:30", "16:00")
    daily = rth["close"].groupby(rth.index.normalize()).last()
    daily.index = pd.DatetimeIndex(daily.index).tz_localize(None)
    return daily.dropna()


def benchmark_daily(path: str) -> pd.Series:
    """Load a SPY (or other benchmark) daily close CSV (cols date,close) for
    INSTRUMENT-AGNOSTIC regime labeling. Regime must be defined by the broad
    market (SPY), not by the instrument being traded — matching production."""
    b = pd.read_csv(path)
    b.columns = [c.lower() for c in b.columns]
    dcol = "date" if "date" in b.columns else b.columns[0]
    ccol = "close" if "close" in b.columns else b.columns[-1]
    s = pd.Series(b[ccol].values, index=pd.to_datetime(b[dcol]).dt.normalize()).sort_index()
    return s.dropna()


def label_regimes(daily: pd.Series, train_end: Optional[str], n_components: int,
                  hmm_fit_end: Optional[str] = None) -> Dict[pd.Timestamp, str]:
    """
    Fit HMM on [start : hmm_fit_end] (default = train_end), then label every day
    AFTER train_end by expanding-window predict_current (no look-ahead in the
    prediction itself).

    Why hmm_fit_end exists: an HMM cannot learn what 'Stress' looks like from a
    window that contains no stress. Fitting on a calm year (e.g. 2017 only)
    under-defines the Stress state and makes the Stress-day count collapse
    (25 vs 261 depending on train window). Pass --hmm-fit-end to fit the regime
    model ONCE on a diverse span (incl. 2018 selloff + COVID) and freeze it,
    while strategy WFO still rolls forward on train_end. This decouples regime
    labeling (needs diverse data) from parameter optimization (must be walk-forward).
    """
    from raits.hmm.engine import HMMEngine

    if train_end is None:
        cut = int(len(daily) * 0.6)
        train_end_ts = daily.index[cut]
    else:
        train_end_ts = pd.Timestamp(train_end)
    fit_end_ts = pd.Timestamp(hmm_fit_end) if hmm_fit_end else train_end_ts

    train = daily[daily.index <= fit_end_ts]
    if len(train) < 40:
        raise ValueError(f"Not enough HMM-fit days ({len(train)}); need >=40.")

    eng = HMMEngine(n_components=n_components)
    eng.fit(train, version_tag="gate2_spike", save=False)   # save=False → read-only

    labels: Dict[pd.Timestamp, str] = {}
    test_days = daily[daily.index > train_end_ts].index
    for d in test_days:
        window = daily[daily.index <= d]
        try:
            state = eng.predict_current(window)
            labels[pd.Timestamp(d).normalize()] = eng.state_name(state)
        except Exception:
            continue
    return labels


# ══════════════════════════════════════════════════════════════════════════════
# 4. Indicator helpers (local; do not touch engine)
# ══════════════════════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════════════════════
# 5. Trade record + per-regime aggregation
# ══════════════════════════════════════════════════════════════════════════════
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
    meta: dict = field(default_factory=dict)   # strategy-specific eyeball fields


def aggregate(trades: List[Trade]) -> pd.DataFrame:
    regimes = ["Calm", "Normal", "Stress"]
    rows = []
    for r in regimes + ["ALL"]:
        ts = [t for t in trades if (r == "ALL" or t.regime == r)]
        if not ts:
            rows.append([r, 0, np.nan, np.nan, np.nan, np.nan, np.nan, 0.0]); continue
        pnls = np.array([t.pnl for t in ts])
        wins = pnls[pnls > 0]; losses = pnls[pnls <= 0]
        gw, gl = wins.sum(), abs(losses.sum())
        pf = (gw / gl) if gl > 0 else float("inf")
        rows.append([
            r, len(ts), len(wins) / len(ts),
            wins.mean() if len(wins) else 0.0,
            losses.mean() if len(losses) else 0.0,
            pf, pnls.mean(), pnls.sum(),
        ])
    return pd.DataFrame(rows, columns=["Regime", "Trades", "WinRt", "AvgWin", "AvgLoss", "PF", "Expect$", "NetPnL$"])


# ══════════════════════════════════════════════════════════════════════════════
# 6. Strategy adapters — call REAL generate_signal, manage local exit
# ══════════════════════════════════════════════════════════════════════════════
class TFAdapter:
    """TrendFollow: 5-min bars, 14:00-15:55 ET, Chandelier trailing exit."""
    name = "trend_follow"
    bar_freq = "5m"

    def __init__(self, params: dict | None = None):
        from raits.strategies.trend_follow import TrendFollowStrategy
        cfg = {}
        if params:
            if "ema_period" in params: cfg["ema_period"] = int(params["ema_period"])
            if "chandelier_atr_mult" in params: cfg["chandelier_atr_mult"] = float(params["chandelier_atr_mult"])
        self.s = TrendFollowStrategy(config=cfg or None)
        self.allowed = set(self.s.config["allowed_regimes"])
        self.ema_p = self.s.config["ema_period"]

    def run_day(self, bars: pd.DataFrame, regime: str, cost: FuturesCost) -> List[Trade]:
        out: List[Trade] = []
        win = bars.between_time("14:00", "15:55")
        if len(win) < 22:
            return out
        idx = list(win.index)
        in_pos = False
        d = entry = stop = atr_e = 0.0; entry_i = 0
        # need >= ema_p bars of history for EMA; use full day's bars up to i
        for n in range(1, len(idx)):
            cur = win.loc[idx[n]]
            hist = bars.loc[:idx[n]]
            if len(hist) < max(self.ema_p, 14) + 1:
                continue
            if not in_pos:
                pullback = win.loc[idx[n - 1]]
                resume = cur
                ema = self.s.calculate_ema(hist, self.ema_p)
                atr = atr14(hist)
                avgv = float(win["volume"].iloc[max(0, n - 11):n - 1].mean())
                if np.isnan(atr) or np.isnan(avgv):
                    continue
                sig = self.s.generate_signal(pullback, resume, ema, atr, regime, avgv)
                if sig:
                    in_pos = True; d = sig["direction"]; entry = sig["entry_price"]
                    stop = sig["initial_stop"]; atr_e = sig["atr"]; entry_i = n
            else:
                seg = win.iloc[entry_i:n + 1]
                stop = self.s.calculate_chandelier_stop(seg, atr_e, d)
                hit = (cur["low"] <= stop) if d == "LONG" else (cur["high"] >= stop)
                last = (n == len(idx) - 1)
                if hit or last:
                    ex = stop if hit else float(cur["close"])
                    pts = (ex - entry) if d == "LONG" else (entry - ex)
                    out.append(Trade(bars.index[0].normalize(), regime, d, entry, ex,
                                     pts, pts * cost.point_value - cost.round_turn_cost()))
                    in_pos = False
        return out


class ORBAdapter:
    """ORB: 1-min bars, OR=9:30-9:45, entries 9:45-10:15, fixed 2R stop/target.
    VALIDATION STATUS: wired from real signature; smoke-eyeball before trusting."""
    name = "orb"
    bar_freq = "1m"

    def __init__(self):
        from raits.strategies.orb import ORBStrategy
        self.s = ORBStrategy()
        self.allowed = set(self.s.config["allowed_regimes"])

    def run_day(self, bars: pd.DataFrame, regime: str, cost: FuturesCost) -> List[Trade]:
        out: List[Trade] = []
        opening = bars.between_time("09:30", "09:44")
        if len(opening) < 5:
            return out
        or_high = float(opening["high"].max()); or_low = float(opening["low"].min())
        sess = bars.between_time("09:45", "15:55")
        cum_pv = (sess["close"] * sess["volume"]).cumsum()
        cum_v = sess["volume"].cumsum().replace(0, np.nan)
        vwap_s = cum_pv / cum_v
        avg_vol = float(opening["volume"].mean()) or 1.0
        idx = list(sess.index); in_pos = False; traded_today = False
        d = entry = stop = target = 0.0; entry_ts = None
        for n, ts in enumerate(idx):
            cur = sess.loc[ts]
            if not in_pos and not traded_today and ts.time() <= dtime(10, 15):
                rvol = float(cur["volume"]) / avg_vol
                sig = self.s.generate_signal(cur, or_high, or_low, float(vwap_s.iloc[n]), rvol, regime)
                if sig:
                    in_pos = True; d = sig["direction"]; entry = sig["entry_price"]
                    stop = sig["stop_loss"]; target = sig["target"]; entry_ts = ts
            elif in_pos:
                if d == "LONG":
                    hit_s, hit_t = cur["low"] <= stop, cur["high"] >= target
                else:
                    hit_s, hit_t = cur["high"] >= stop, cur["low"] <= target
                last = (n == len(idx) - 1)
                if hit_s or hit_t or last:
                    ex = stop if hit_s else target if hit_t else float(cur["close"])
                    reason = "stop" if hit_s else "target" if hit_t else "eod"
                    pts = (ex - entry) if d == "LONG" else (entry - ex)
                    out.append(Trade(bars.index[0].normalize(), regime, d, entry, ex,
                                     pts, pts * cost.point_value - cost.round_turn_cost(),
                                     entry_time=entry_ts, exit_time=ts,
                                     meta={"or_high": round(or_high, 2), "or_low": round(or_low, 2),
                                           "stop": round(stop, 2), "target": round(target, 2),
                                           "reason": reason}))
                    in_pos = False; traded_today = True
        return out


class VWAPMRAdapter:
    """VWAP_MR: 5-min bars, 10:15-14:00 ET, BB(period,std), exit at VWAP / ATR stop.
    VALIDATION STATUS: wired from real signature; smoke-eyeball before trusting."""
    name = "vwap_mr"
    bar_freq = "5m"

    def __init__(self):
        from raits.strategies.vwap_mr import VWAPMRStrategy
        self.s = VWAPMRStrategy()
        self.allowed = set(self.s.config["allowed_regimes"])
        self.bb_p = self.s.config["bb_period"]; self.bb_sd = self.s.config["bb_std_dev"]

    def run_day(self, bars: pd.DataFrame, regime: str, cost: FuturesCost) -> List[Trade]:
        out: List[Trade] = []
        day = bars.between_time("09:30", "15:55")
        if len(day) < self.bb_p + 2:
            return out
        cum_pv = (day["close"] * day["volume"]).cumsum()
        cum_v = day["volume"].cumsum().replace(0, np.nan)
        vwap_s = cum_pv / cum_v
        win = day.between_time("10:15", "14:00"); idx = list(win.index)
        in_pos = False; d = entry = stop = 0.0; vwap_at = 0.0
        for n in range(1, len(idx)):
            ts = idx[n]; cur = win.loc[ts]; pos = day.index.get_loc(ts)
            hist = day["close"].iloc[:pos + 1]
            if len(hist) < self.bb_p:
                continue
            ma = hist.tail(self.bb_p).mean(); sd = hist.tail(self.bb_p).std()
            bb_u = ma + self.bb_sd * sd; bb_l = ma - self.bb_sd * sd
            vwap = float(vwap_s.iloc[pos]); atr = atr14(day.iloc[:pos + 1])
            if not in_pos:
                prev = win.loc[idx[n - 1]]
                sig = self.s.generate_signal(prev, cur, bb_u, bb_l, vwap, atr, regime)
                if sig:
                    in_pos = True; d = sig["direction"]; entry = sig["entry_price"]
                    stop = sig.get("stop_loss", entry - atr if d == "LONG" else entry + atr)
                    vwap_at = vwap
            else:
                tgt = vwap_at
                if d == "LONG":
                    hit_s, hit_t = cur["low"] <= stop, cur["high"] >= tgt
                else:
                    hit_s, hit_t = cur["high"] >= stop, cur["low"] <= tgt
                last = (n == len(idx) - 1)
                if hit_s or hit_t or last:
                    ex = stop if hit_s else tgt if hit_t else float(cur["close"])
                    pts = (ex - entry) if d == "LONG" else (entry - ex)
                    out.append(Trade(bars.index[0].normalize(), regime, d, entry, ex,
                                     pts, pts * cost.point_value - cost.round_turn_cost()))
                    in_pos = False
        return out


class StressMidAdapter:
    """STRESS_MID: 5-min bars, Stress regime, one SHORT at 10:15 held to 14:00.
    Signal (ported from stress_mid_sim.py — NO importable class exists):
      at 10:15  close < VWAP(9:30-10:15) AND close < day-open  -> SHORT
      stop  = swing-high(9:45-10:15) * (1 + 0.1%); reject if stop_dist > 1.5%
      target = entry - 2R; exit first stop/target hit, else 14:00 close.
    VALIDATION STATUS: reimplemented (not real engine code) — eyeball on real ES."""
    name = "stress_mid"
    bar_freq = "5m"
    ENTRY = dtime(10, 15); EXIT = dtime(14, 0); SWING_START = dtime(9, 45)
    STOP_PAD = 0.001; TARGET_RR = 2.0; MAX_STOP_PCT = 0.015

    def __init__(self, params: dict | None = None):
        self.allowed = {"Stress"}
        p = params or {}
        self.STOP_PAD = float(p.get("stop_pad", 0.001))
        self.TARGET_RR = float(p.get("target_rr", 2.0))
        self.MAX_STOP_PCT = float(p.get("max_stop_pct", 0.015))

    @staticmethod
    def _vwap(bars: pd.DataFrame) -> float:
        tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
        v = bars["volume"]
        return float((tp * v).sum() / v.sum()) if v.sum() > 0 else float(bars["close"].iloc[-1])

    def run_day(self, bars: pd.DataFrame, regime: str, cost: FuturesCost) -> List[Trade]:
        day = bars.between_time("09:30", "14:00")
        if len(day) < 5:
            return []
        open_px = float(day.iloc[0]["open"])
        at_entry = day[day.index.time == self.ENTRY]
        if at_entry.empty:
            return []
        entry = float(at_entry.iloc[-1]["close"])
        pre = day[day.index.time <= self.ENTRY]
        vwap = self._vwap(pre)
        if entry >= vwap or entry >= open_px:           # signal: below VWAP AND below open
            return []
        swing = day[(day.index.time >= self.SWING_START) & (day.index.time <= self.ENTRY)]
        ref = float(swing["high"].max()) if not swing.empty else entry * 1.005
        stop = ref * (1 + self.STOP_PAD)
        stop_dist = stop - entry
        if stop_dist <= 0 or stop_dist / entry > self.MAX_STOP_PCT:
            return []
        target = entry - self.TARGET_RR * stop_dist
        fwd = day[(day.index.time > self.ENTRY) & (day.index.time <= self.EXIT)]
        if fwd.empty:
            return []
        ex, reason = float(fwd.iloc[-1]["close"]), "eod"
        for ts, bar in fwd.iterrows():
            if float(bar["high"]) >= stop:
                ex, reason = stop, "stop"; exit_ts = ts; break
            if float(bar["low"]) <= target:
                ex, reason = target, "target"; exit_ts = ts; break
        else:
            exit_ts = fwd.index[-1]
        pts = entry - ex                                 # SHORT
        return [Trade(bars.index[0].normalize(), regime, "SHORT", entry, ex,
                      pts, pts * cost.point_value - cost.round_turn_cost(),
                      entry_time=at_entry.index[-1], exit_time=exit_ts,
                      meta={"vwap": round(vwap, 2), "open": round(open_px, 2),
                            "stop": round(stop, 2), "target": round(target, 2),
                            "reason": reason})]


class NormalMidAdapter:
    """NORMAL_MID: mirror of STRESS_MID into the Normal regime, TWO-directional.
    Fills the untested 10:15-14:00 midday gap in Normal (TF starts 14:00).
      at 10:15:  close > VWAP AND close > open  -> LONG  (stop = swing-low - 0.1%)
                 close < VWAP AND close < open  -> SHORT (stop = swing-high + 0.1%)
                 mixed (above one, below other)  -> no trade
      target = entry ± 2R; reject if stop_dist > 1.5%; exit first hit else 14:00.
    VALIDATION STATUS: new mirror — eyeball both LONG and SHORT on real ES."""
    name = "normal_mid"
    bar_freq = "5m"
    ENTRY = dtime(10, 15); EXIT = dtime(14, 0); SWING_START = dtime(9, 45)
    STOP_PAD = 0.001; TARGET_RR = 2.0; MAX_STOP_PCT = 0.015

    def __init__(self):
        self.allowed = {"Normal"}

    @staticmethod
    def _vwap(bars: pd.DataFrame) -> float:
        tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
        v = bars["volume"]
        return float((tp * v).sum() / v.sum()) if v.sum() > 0 else float(bars["close"].iloc[-1])

    def run_day(self, bars: pd.DataFrame, regime: str, cost: FuturesCost) -> List[Trade]:
        day = bars.between_time("09:30", "14:00")
        if len(day) < 5:
            return []
        open_px = float(day.iloc[0]["open"])
        at_entry = day[day.index.time == self.ENTRY]
        if at_entry.empty:
            return []
        entry = float(at_entry.iloc[-1]["close"])
        pre = day[day.index.time <= self.ENTRY]
        vwap = self._vwap(pre)

        # two-directional signal: price must agree with BOTH VWAP and open
        if entry > vwap and entry > open_px:
            d = "LONG"
        elif entry < vwap and entry < open_px:
            d = "SHORT"
        else:
            return []   # mixed signal → skip

        swing = day[(day.index.time >= self.SWING_START) & (day.index.time <= self.ENTRY)]
        if d == "LONG":
            ref = float(swing["low"].min()) if not swing.empty else entry * 0.995
            stop = ref * (1 - self.STOP_PAD)
            stop_dist = entry - stop
            target = entry + self.TARGET_RR * stop_dist
        else:
            ref = float(swing["high"].max()) if not swing.empty else entry * 1.005
            stop = ref * (1 + self.STOP_PAD)
            stop_dist = stop - entry
            target = entry - self.TARGET_RR * stop_dist
        if stop_dist <= 0 or stop_dist / entry > self.MAX_STOP_PCT:
            return []

        fwd = day[(day.index.time > self.ENTRY) & (day.index.time <= self.EXIT)]
        if fwd.empty:
            return []
        ex, reason, exit_ts = float(fwd.iloc[-1]["close"]), "eod", fwd.index[-1]
        for ts, bar in fwd.iterrows():
            if d == "LONG":
                if float(bar["low"]) <= stop:
                    ex, reason, exit_ts = stop, "stop", ts; break
                if float(bar["high"]) >= target:
                    ex, reason, exit_ts = target, "target", ts; break
            else:
                if float(bar["high"]) >= stop:
                    ex, reason, exit_ts = stop, "stop", ts; break
                if float(bar["low"]) <= target:
                    ex, reason, exit_ts = target, "target", ts; break
        pts = (ex - entry) if d == "LONG" else (entry - ex)
        return [Trade(bars.index[0].normalize(), regime, d, entry, ex,
                      pts, pts * cost.point_value - cost.round_turn_cost(),
                      entry_time=at_entry.index[-1], exit_time=exit_ts,
                      meta={"vwap": round(vwap, 2), "open": round(open_px, 2),
                            "stop": round(stop, 2), "target": round(target, 2),
                            "reason": reason})]


ADAPTERS = {"trend_follow": TFAdapter, "orb": ORBAdapter,
            "vwap_mr": VWAPMRAdapter, "stress_mid": StressMidAdapter,
            "normal_mid": NormalMidAdapter}


# ══════════════════════════════════════════════════════════════════════════════
# 7. Backtest driver
# ══════════════════════════════════════════════════════════════════════════════
def run(df1m: pd.DataFrame, strategy: str, labels: Dict[pd.Timestamp, str],
        cost: FuturesCost) -> List[Trade]:
    adapter = ADAPTERS[strategy]()
    trades: List[Trade] = []
    for day, g in df1m.groupby(df1m.index.normalize()):
        key = pd.Timestamp(day).tz_localize(None) if day.tzinfo else pd.Timestamp(day)
        regime = labels.get(key.normalize())
        if regime is None:
            continue
        bars = resample_5m(g) if adapter.bar_freq == "5m" else g
        if regime not in adapter.allowed:
            continue   # real strategy would gate anyway; skip for speed
        trades.extend(adapter.run_day(bars, regime, cost))
    return trades


def verdict(table: pd.DataFrame, adapter_allowed: set) -> str:
    alive = []
    for r in adapter_allowed:
        row = table[table["Regime"] == r]
        if row.empty or row["Trades"].iloc[0] == 0:
            continue
        if row["Expect$"].iloc[0] > 0 and row["PF"].iloc[0] > 1.0:
            alive.append(r)
    if alive:
        return f"[ALIVE] positive expectancy & PF>1 in: {', '.join(alive)} (after futures costs)"
    return "[KILL] no positive-expectancy regime in this strategy's allowed set"


# ══════════════════════════════════════════════════════════════════════════════
# 8. main
# ══════════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="RAITS Gate 2 edge harness (read-only).")
    ap.add_argument("--parquet", help="ES/MES 1-min continuous parquet")
    ap.add_argument("--smoke-test", action="store_true", help="use synthetic data")
    ap.add_argument("--strategy", choices=list(ADAPTERS), default="trend_follow")
    ap.add_argument("--hmm-train-end", default=None, help="YYYY-MM-DD; default 60%% split")
    ap.add_argument("--hmm-components", type=int, default=3)
    ap.add_argument("--point-value", type=float, default=5.0)
    ap.add_argument("--tick-value", type=float, default=None,
                    help="$/tick; default auto = 0.25 × point_value (MES 1.25, MNQ 0.50)")
    ap.add_argument("--regime-csv", default=None,
                    help="SPY daily CSV (date,close) for instrument-agnostic regime labeling "
                         "(recommended: regime should be SPY-based, not the traded instrument)")
    ap.add_argument("--commission-rt", type=float, default=1.24)
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    ap.add_argument("--dump-trades", type=int, default=0, metavar="N",
                    help="print details of the first N trades for eyeballing (0=off)")
    ap.add_argument("--dump-csv", default=None, metavar="PATH",
                    help="write full trade log to CSV (for Gate 3 alpha/beta analysis)")
    a = ap.parse_args()

    if not a.smoke_test and not a.parquet:
        ap.error("provide --parquet PATH or --smoke-test")

    cost = FuturesCost(point_value=a.point_value, tick_value=a.tick_value,
                       commission_rt=a.commission_rt, slippage_ticks_per_side=a.slippage_ticks)

    print(f"\n{'='*68}\nGate 2 edge harness | strategy={a.strategy} | "
          f"{'SMOKE' if a.smoke_test else a.parquet}\n{'='*68}")
    df = make_smoke_data() if a.smoke_test else load_parquet(a.parquet)
    print(f"Bars: {len(df):,} | span {df.index[0]} → {df.index[-1]}")

    daily = benchmark_daily(a.regime_csv) if a.regime_csv else daily_close_series(df)
    if a.regime_csv:
        print(f"Regime source: SPY benchmark {a.regime_csv} (instrument-agnostic)")
    labels = label_regimes(daily, a.hmm_train_end, a.hmm_components)
    dist = pd.Series(list(labels.values())).value_counts().to_dict()
    print(f"Labelled {len(labels)} test days | regime dist: {dist}")

    trades = run(df, a.strategy, labels, cost)
    print(f"Trades generated: {len(trades)} | round-turn cost ${cost.round_turn_cost():.2f}/contract\n")

    if a.dump_trades and trades:
        print(f"── First {min(a.dump_trades, len(trades))} trades (eyeball) ──")
        hdr = (f"{'#':>3} {'day':<10} {'reg':<6} {'dir':<5} {'entry_t':<8} {'exit_t':<8} "
               f"{'entry':>9} {'exit':>9} {'pts':>7} {'pnl$':>8}  detail")
        print(hdr)
        for i, t in enumerate(trades[:a.dump_trades], 1):
            et = t.entry_time.strftime("%H:%M") if t.entry_time is not None else "—"
            xt = t.exit_time.strftime("%H:%M") if t.exit_time is not None else "—"
            detail = " ".join(f"{k}={v}" for k, v in t.meta.items())
            print(f"{i:>3} {str(t.day.date()):<10} {t.regime:<6} {t.direction:<5} {et:<8} {xt:<8} "
                  f"{t.entry:>9.2f} {t.exit:>9.2f} {t.points:>7.2f} {t.pnl:>8.2f}  {detail}")
        print()

    table = aggregate(trades)
    with pd.option_context("display.float_format", lambda x: f"{x:,.3f}"):
        print(table.to_string(index=False))

    if a.dump_csv and trades:
        rows = []
        for t in trades:
            rows.append({
                "day": t.day.date(), "regime": t.regime, "direction": t.direction,
                "entry": t.entry, "exit": t.exit, "points": t.points, "pnl": t.pnl,
                "entry_time": t.entry_time, "exit_time": t.exit_time, **t.meta,
            })
        pd.DataFrame(rows).to_csv(a.dump_csv, index=False)
        print(f"\nWrote trade log: {a.dump_csv} ({len(trades)} trades)")

    allowed = ADAPTERS[a.strategy]().allowed
    print(f"\nStrategy '{a.strategy}' allowed regimes: {sorted(allowed)}")
    print(verdict(table, allowed))
    print("\nNOTE: smoke data is synthetic — a verdict here only proves the\n"
          "pipeline runs end-to-end. The real kill decision uses Databento ES data.\n")


if __name__ == "__main__":
    main()
