"""
futures/_validated_core.py — internalized validated logic (refactor stage b)
===========================================================================
Verbatim copies of the validated functions previously imported from the root
scripts swing_tf_harness.py and gate2_edge_harness.py, so futures/ depends ONLY
on raits.* (raits.hmm for regimes, raits.strategies.trend_follow for the entry
signal) — NOT on root research scripts.

Extracted programmatically via ast.get_source_segment (no hand transcription).
reconcile_gd0 + reconcile_stress MUST still PASS after this change → proof the
copy is faithful and results are unchanged.

Source of truth for edits remains the validated logic; if these are ever changed,
re-run both reconciles.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import time as dtime
from typing import Dict, List, Optional
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── from gate2_edge_harness.py ──────────────────────────────────────────────
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
        except Exception as exc:
            logger.error("HMM label failed for %s: %s", pd.Timestamp(d).date(), exc)
            continue
    return labels

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

# ── from swing_tf_harness.py ───────────────────────────────────────────────
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

_SWING_CACHE = {}
# Each entry pins its frame plus ~120MB of per-day structures, so the dict has to
# be bounded: reconcile_nkd builds a frame per trade and would otherwise retain
# every one of them. Eviction is safe — dropping an entry drops the frame with
# it, and a key that is no longer present cannot be hit by a later frame that
# lands on the recycled address.
#
# Sized for the worst live case: five instruments, each keyed twice because the
# same frame is replayed once with an injected datr and once without, so ten
# entries are in play at the peak. A smaller bound would evict frames that are
# about to be used again and rebuild their prep every time — bounded memory
# bought with repeated work.
_SWING_CACHE_MAX = 16

def _swing_cache(df, datr=None):
    """Precompute per-df: daily ATR, day list, per-day high/low/open arrays (1m),
    per-day 5m frames. Keyed by id(df) so WFO reuses across param/fold calls.

    datr: daily ATR for this instrument's FULL history. Everything else in here
    is derived per-day and so survives slicing, but the chandelier band reads a
    daily ATR that is Wilder-smoothed and therefore needs history a slice does
    not carry. A caller that replays only recent days computes it once on the
    unsliced frame and passes it in. None keeps the original behaviour — derive
    it from df — so callers that pass nothing are unaffected.

    The entry holds a reference to df, and that reference is what makes the key
    sound: two live objects cannot share an address, so while the entry exists
    its id cannot be handed to a different frame. Without it a freed frame's
    address is recycled and one frame's bars are served to another — no error,
    just wrong numbers. Callers that build frames in a loop must still clear the
    cache; runner.py does so after each run_day (J2), which is what bounds
    retention here.
    """
    # datr is part of the identity: the same frame replayed against a different
    # ATR history is a different precompute, and serving the first one's entry
    # would be the id(df) bug again in a new place.
    k = (id(df), id(datr) if datr is not None else None)
    hit = _SWING_CACHE.get(k)
    if hit is not None:
        return hit[2]
    if datr is None:
        datr = daily_atr_series(df)
    # real time-gaps: a bar preceded by a break > threshold (maintenance ~60m, weekend,
    # or RTH overnight) is where an overnight PRICE gap can occur. Continuous 1m bars
    # (24h data) have ~1m spacing → no gap flagged except the daily maintenance break.
    GAP_MIN = 15.0
    deltas = df.index.to_series().diff().dt.total_seconds().to_numpy() / 60.0
    is_gap_full = deltas > GAP_MIN          # True where a real time-break precedes the bar
    is_gap_full[0] = False
    # Bound to a new name: rebinding df here would drop the caller's frame from
    # this scope, and it is that frame the entry below must keep alive.
    dfg = df.assign(_isgap=is_gap_full)
    day_hl, day_b5, day_ts = {}, {}, {}
    for d, g in dfg.groupby(dfg.index.normalize()):
        key = pd.Timestamp(d).tz_localize(None).normalize()
        day_hl[key] = (g["high"].to_numpy(), g["low"].to_numpy(),
                       g["open"].to_numpy(), g["_isgap"].to_numpy())
        day_b5[key] = resample_5m(g.drop(columns="_isgap"))
        day_ts[key] = g.index      # 1m bar timestamps — for entry_time/exit_time capture only
    days = sorted(day_hl.keys())
    cache = dict(datr=datr, days=days, hl=day_hl, b5=day_b5, ts=day_ts)
    while len(_SWING_CACHE) >= _SWING_CACHE_MAX:
        _SWING_CACHE.pop(next(iter(_SWING_CACHE)))     # oldest insertion first
    _SWING_CACHE[k] = (df, datr, cache)
    return cache

def backtest_swing_tf(df, labels, cost, *, ema_period=20, chandelier_atr_mult=3.0,
                      max_hold_days=5, entry_days=None, gap_fill=True, return_open=False,
                      datr=None, resume_pos=None, resume_after_day=None):
    """Cross-day swing TF backtest (vectorized holding). gap_fill=True models a
    stop that GAPS THROUGH: if the bar that triggers the stop OPENED beyond the
    stop, fill at the (worse) open price, not the stop — realistic for overnight
    gaps. gap_fill=False = optimistic (always fill at stop, like the RAITS engine).

    datr: daily ATR for the instrument's full history, for callers that pass a
    sliced df. See _swing_cache. None = derive it from df, i.e. the behaviour
    every existing caller already gets.

    resume_pos / resume_after_day: replay only what has not been replayed yet.
    The day loop carries exactly one thing across days — the open position — so
    seeding it and skipping days already covered reproduces a full replay
    exactly, given datr for the full history. `trades` then holds only the
    trades that CLOSED after resume_after_day; ones that closed earlier belong
    to the run that produced the checkpoint.

    The frame must still START at least one session before the first day to be
    replayed. _swing_cache flags overnight gaps from each bar's spacing to the
    bar before it, and forces the very first bar of the frame to "no gap"
    because nothing precedes it. Cut the frame exactly at the resume day and
    that day's first bar loses its gap flag, turning a GAP exit (filled at the
    open, worse) into a CHANDELIER one (filled at the stop). Pass the lead-in
    session and let resume_after_day exclude it from the replay."""
    from raits.strategies.trend_follow import TrendFollowStrategy
    s = TrendFollowStrategy({**TrendFollowStrategy().config, "ema_period": ema_period,
                             "chandelier_atr_mult": chandelier_atr_mult})
    allowed = set(s.config["allowed_regimes"])
    c = _swing_cache(df, datr)
    datr, days, hl, b5, ts = c["datr"], c["days"], c["hl"], c["b5"], c.get("ts", {})
    mult = chandelier_atr_mult
    trades = []
    # Copied: the loop ratchets pos["stop"] and pos["extreme"] in place, so
    # replaying from the same checkpoint twice would otherwise give two
    # different answers — the second run starting from the first run's leftovers.
    pos = dict(resume_pos) if resume_pos is not None else None
    _replayed_through = (pd.Timestamp(resume_after_day).normalize()
                         if resume_after_day is not None else None)

    for day in days:
        # Present in the frame so the next day's gap flags are right, but already
        # accounted for by the checkpoint — see the docstring.
        if _replayed_through is not None and day <= _replayed_through:
            continue
        exit_ts_today = None  # causal: set if exit fires within session; entry scan filters to bars after
        if pos is not None:
            hold = (day - pos["entry_day"]).days
            if hold >= max_hold_days:
                # Exit at RTH open (09:30 ET): stocks engine used iloc[0]["open"] on
                # RTH-only data = 09:30. Futures 24h port inherited hl[day][2][0] = 00:00.
                # Corrected: find first 1m bar at or after 09:30 ET on exit_day.
                _day_ts = ts.get(day)
                if _day_ts is not None and len(_day_ts):
                    _930    = day + pd.Timedelta(hours=9, minutes=30)
                    _tz_str = str(_day_ts.tzinfo) if _day_ts.tzinfo is not None else ""
                    _is_et  = _tz_str in ("", "America/New_York", "US/Eastern")
                    if _is_et:
                        # US ET futures: find first 1m bar at or after 09:30 ET.
                        # Use DatetimeIndex.searchsorted() with TZ-aware target — handles
                        # both ns and us resolution indexes without asi8/value unit mismatch.
                        if _day_ts.tzinfo is not None:
                            _930_cmp = _930.tz_localize(ET)          # TZ-aware ET
                        else:
                            _930_cmp = _930                          # naive ET (already local)
                        _idx = int(_day_ts.searchsorted(_930_cmp))
                        if _idx >= len(hl[day][2]):
                            _idx = 0
                    else:
                        _idx = 0  # non-ET (e.g. NKD/Tokyo): use first bar of day
                    op           = float(hl[day][2][_idx])
                    exit_bar_ts  = _day_ts[_idx]
                else:
                    op          = float(hl[day][2][0])
                    exit_bar_ts = None
                pts = (op - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - op)
                trades.append(dict(day=pos["entry_day"].date(), exit_day=day.date(),
                                   regime=pos["regime"], direction=pos["dir"],
                                   entry=round(pos["entry"], 2), exit=round(op, 2),
                                   points=round(pts, 2),
                                   pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                                   hold_days=hold, reason="MAX_HOLD",
                                   entry_time=pos.get("entry_time"),
                                   exit_time=exit_bar_ts))
                pos = None
                exit_ts_today = exit_bar_ts
            else:
                high, low, opn, isg = hl[day]
                da = float(datr.asof(day)) if len(datr) else np.nan
                if not np.isnan(da) and da > 0 and len(high):
                    if pos["dir"] == "LONG":
                        # stop IN FORCE at each bar's open = ratchet from extreme through PRIOR bar
                        run_full = np.maximum.accumulate(np.maximum(high, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.maximum.accumulate(np.maximum(run_prev - mult * da, pos["stop"]))
                        hit = np.where(low <= stop_prev)[0]
                    else:
                        run_full = np.minimum.accumulate(np.minimum(low, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.minimum.accumulate(np.minimum(run_prev + mult * da, pos["stop"]))
                        hit = np.where(high >= stop_prev)[0]
                    if len(hit):
                        i = hit[0]; stp = float(stop_prev[i])
                        # gap-through only when a REAL time-break precedes the hit bar
                        # (maintenance break / weekend / RTH overnight) AND it opened past stop
                        gapped = gap_fill and bool(isg[i]) and (
                            (pos["dir"] == "LONG"  and float(opn[i]) < stp) or
                            (pos["dir"] == "SHORT" and float(opn[i]) > stp))
                        if gapped:
                            ex = float(opn[i]); reason = "GAP"
                        else:
                            ex = stp; reason = "CHANDELIER"
                        pts = (ex - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - ex)
                        _ts_exit = ts.get(day)
                        trades.append(dict(day=pos["entry_day"].date(), exit_day=day.date(),
                                           regime=pos["regime"], direction=pos["dir"],
                                           entry=round(pos["entry"], 2), exit=round(ex, 2),
                                           points=round(pts, 2),
                                           pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                                           hold_days=hold, reason=reason,
                                           entry_time=pos.get("entry_time"),
                                           exit_time=(_ts_exit[i] if _ts_exit is not None and i < len(_ts_exit) else None)))
                        pos = None
                        exit_ts_today = _ts_exit[i] if _ts_exit is not None and i < len(_ts_exit) else None
                    else:
                        # carry ratcheted stop (based on ALL of today's highs) to next day
                        if pos["dir"] == "LONG":
                            pos["stop"] = float(np.maximum(pos["stop"], run_full[-1] - mult * da))
                        else:
                            pos["stop"] = float(np.minimum(pos["stop"], run_full[-1] + mult * da))
                        pos["extreme"] = float(run_full[-1])

        if pos is None:
            reg = labels.get(day)
            if reg in allowed and (entry_days is None or day in entry_days):
                bars5 = b5[day]; win = bars5.between_time("14:00", "15:55")
                if exit_ts_today is not None:
                    win = win[win.index > exit_ts_today]
                    if len(win) < 2:
                        continue
                idx = list(win.index)
                for n in range(1, len(idx)):
                    hist = bars5.loc[:idx[n]]
                    if len(hist) < max(ema_period, 14) + 1:
                        continue
                    ema = s.calculate_ema(hist, ema_period)
                    atr = atr14(hist)
                    avgv = float(win["volume"].iloc[max(0, n - 11):n - 1].mean())
                    if np.isnan(atr) or np.isnan(avgv):
                        continue
                    sig = s.generate_signal(win.loc[idx[n - 1]], win.loc[idx[n]], ema, atr, reg, avgv)
                    if sig:
                        pos = dict(dir=sig["direction"], entry=sig["entry_price"],
                                   entry_day=day, regime=reg,
                                   extreme=sig["entry_price"], stop=sig["initial_stop"],
                                   entry_time=idx[n])
                        break
    return (trades, pos) if return_open else trades

