"""global_index/track1_stress_mnq.py — the Stress-MNQ detector, as functions. NEW FILE.

Stage 5F, closing the second half of precondition 2b by PROMOTING the rule rather than
importing scratch from a live path.

What this replaces
------------------
The rule ran only as `scratch/stress_open_search_20260821` (day cache, peer features, level
helpers) plus `scratch/stress_switch_full_replay_20260822` (the scenario and the trade builder).
Both are research scripts: they read a hard-coded window table, mutate a module-level `SETUPS`
constant, and print. A live slot must not import any of that, so the live source refused with
`stress_rule_not_in_package` and 24 of the 25 Track 1 slots could never decide.

Nothing here is re-derived from memory. Every threshold below was read out of the scratch
`Rule` that produced the measured book, and the equivalence harness compares this module's rows
against that chain trade for trade.

The rule, and where each number comes from
-------------------------------------------
Named `mnq_only_g3_q7` — MNQ only, gap-down breadth 3, quantity 7:

    setup       at 10:30 ET, on 5-minute bars built from the RTH session
    breadth     all 4 R4 instruments closed the setup bar BELOW both the day open and the
                VWAP of the session so far          (`breadth_min = 4`)
    gap down    at least 3 of the 4 gapped down by 0.4% or more against their own prior RTH
                close                                (`gapdown_min = 3`, `gap <= -0.004`)
    average     the mean gap across the four is at most -0.1%   (`avg_gap_max = -0.001`)
    entry       SHORT MNQ on the first 1-minute bar between 10:35 and 12:30 whose LOW breaks
                the 09:30-10:30 low; filled at `min(bar open, level)`
    stop        the 09:30-10:30 HIGH plus 0.1%       (`stop_pad = 0.001`)
    target      `entry - 1.5 x (stop - entry)`       (`rr = 1.5`)
    reject      a stop further than 2% of entry      (`max_stop_pct = 0.02`)
    exit        stop, target, or the 15:55 close, whichever comes first
    size        7 MNQ micros; risk is `(stop - entry) x point_value x qty`

Why 10:30 is knowable at 10:35, which is the whole causality question
----------------------------------------------------------------------
The setup bar is a FIVE-MINUTE bar labelled 10:30, and pandas labels a resampled bar with its
LEFT edge — so the bar labelled 10:30 covers 10:30 up to but not including 10:35, and its close
is not known until 10:35. That is why the entry window starts at 10:35 and not a minute earlier,
and why the scratch context carries `known_time = signal_time + 5 minutes`.

The entry scan therefore starts at the first 1-minute bar stamped 10:35, which is the first bar
that is not inside the setup bar. No bar is used twice and none is used before it closed.

There is no regime label in this rule at all. It was built deliberately to avoid the lag-0
daily-`Stress` label that an earlier candidate leaked on, so there is no D-1 lookup to get wrong.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

SHORT = "SHORT"
SLEEVE = "roska4_stress"

#: The four instruments whose behaviour the detector reads. The trade is MNQ only; the SIGNAL
#: is a statement about the whole basket, which is why all four are required present.
BREADTH_BASKET: tuple = ("MES", "MNQ", "MYM", "M2K")


@dataclass(frozen=True)
class StressParams:
    """Every threshold, at the values the measured book was produced under."""
    instruments: tuple = ("MNQ",)
    qty: int = 7
    setup_time: str = "10:30"
    rth_start: str = "09:30"
    rth_end: str = "16:00"
    bars_end: str = "15:55"
    entry_start: str = "10:35"
    entry_end: str = "12:30"
    exit_time: str = "15:55"
    rr: float = 1.5
    breadth_min: int = 4
    gapdown_min: int = 3
    gapdown_at: float = -0.004
    avg_gap_max: float | None = -0.001
    wide_min: int = 0
    wide_at: float = 0.008
    max_stop_pct: float = 0.02
    stop_pad: float = 0.001
    min_pre_bars: int = 3


@dataclass(frozen=True)
class StressSetup:
    """One detected entry. `exit_*` are absent — a live slot does not know them."""
    day: pd.Timestamp
    inst: str
    direction: str
    signal_time: pd.Timestamp
    known_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry: float
    stop: float
    target: float
    pre_high: float
    pre_low: float
    vwap: float
    gap: float
    below_count: int
    gapdown_count: int
    avg_gap: float


def _t(hhmm: str):
    return pd.Timestamp(hhmm).time()


def resample_5m(day1m: pd.DataFrame) -> pd.DataFrame:
    """5-minute OHLCV, LEFT-labelled — the convention the whole causality argument rests on."""
    o = day1m["open"].resample("5min").first()
    h = day1m["high"].resample("5min").max()
    lo = day1m["low"].resample("5min").min()
    c = day1m["close"].resample("5min").last()
    v = day1m["volume"].resample("5min").sum()
    out = pd.concat([o, h, lo, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna(subset=["open"])


def vwap(bars: pd.DataFrame) -> float:
    """Typical-price VWAP. Falls back to the last close when the window carries no volume —
    a session that traded nothing must not divide by zero, and its VWAP is its price."""
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    total = float(vol.sum())
    return float((tp * vol).sum() / total) if total > 0 else float(bars["close"].iloc[-1])


def session_context(day_bars_1m: pd.DataFrame, prev_rth_close: float | None,
                    params: StressParams | None = None) -> "dict | None":
    """Everything one instrument contributes to the 10:30 signal, from its own bars.

    `None` when the session cannot be judged: no RTH bars, no setup bar, or fewer than three
    bars before it. Never a partial dict — a missing feature must not read as a false one.

    Uses only bars at or before the setup bar. The setup bar's own close is the newest thing
    it touches, and that close is known at 10:35.
    """
    p = params or StressParams()
    rth = day_bars_1m.between_time(p.rth_start, p.rth_end)
    if rth.empty:
        return None
    bars5 = resample_5m(day_bars_1m).between_time(p.rth_start, p.bars_end)
    pre = bars5[bars5.index.time <= _t(p.setup_time)]
    sig = bars5[bars5.index.time == _t(p.setup_time)]
    if len(pre) < p.min_pre_bars or sig.empty:
        return None

    day_open = float(rth.iloc[0]["open"])
    sig_close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    hi = float(pre["high"].max())
    lo = float(pre["low"].min())
    gap = day_open / prev_rth_close - 1.0 if prev_rth_close else np.nan
    return {
        "signal_time": sig.index[-1],
        "known_time": sig.index[-1] + pd.Timedelta(minutes=5),
        "open": day_open, "signal_close": sig_close, "vwap": vw,
        "pre_high": hi, "pre_low": lo,
        "range_pct": (hi - lo) / day_open if day_open else 0.0,
        "ret_from_open": sig_close / day_open - 1.0 if day_open else 0.0,
        "gap": gap,
        "below": sig_close < day_open and sig_close < vw,
        "gapdown": bool(np.isfinite(gap) and gap <= p.gapdown_at),
        "wide": (hi - lo) / day_open >= p.wide_at if day_open else False,
    }


def peer_features(contexts: Sequence[Mapping[str, Any]]) -> dict:
    """The basket-level view the signal is actually a statement about."""
    gaps = [c["gap"] for c in contexts if np.isfinite(c["gap"])]
    return {
        "below_count": sum(1 for c in contexts if c["below"]),
        "gapdown_count": sum(1 for c in contexts if c["gapdown"]),
        "wide_count": sum(1 for c in contexts if c["wide"]),
        "avg_ret": float(np.mean([c["ret_from_open"] for c in contexts])),
        "avg_gap": float(np.mean(gaps)) if gaps else 0.0,
        "avg_range": float(np.mean([c["range_pct"] for c in contexts])),
    }


#: Stage 5ZZP. The four comparisons, as data.
#:
#: `entry_conditions` already made every one of these — it just returned a bool and dropped
#: which one failed and by how much. The values were computed (`peer_features`), the thresholds
#: were named (`StressParams`), and both were sitting at the call site; only the join between
#: them was thrown away. So a slot could report "no signal" and nothing could say the basket
#: was one instrument short of stressed.
#:
#: Expressed once, here, and the decision is DERIVED from it. Writing the breakdown as a
#: second function beside the original would have created two statements of the same rule, and
#: this repo has the scar for that: one table, three readers, or they drift.
#:
#: `unit` and `label` are for a person reading a panel. Nothing downstream branches on them.
_ENTRY_CHECKS: tuple = (
    ("below_count", "Instruments below open and VWAP", "breadth_min", ">=", "count"),
    ("gapdown_count", "Instruments gapped down", "gapdown_min", ">=", "count"),
    ("wide_count", "Instruments with a wide range", "wide_min", ">=", "count"),
    ("avg_gap", "Average basket gap", "avg_gap_max", "<=", "fraction"),
)


def entry_checks(feats: Mapping[str, Any], params: StressParams | None = None) -> list:
    """Every entry condition with its value, its threshold and its verdict.

    The ORDER and the comparisons are exactly `entry_conditions`' own, because that function
    is now `all()` over this list. A check whose threshold is `None` is reported as
    `not_applicable` and does not vote — `avg_gap_max` is nullable in `StressParams`, and the
    original skipped that comparison entirely when it was unset rather than passing it.
    """
    p = params or StressParams()
    out = []
    for key, label, thresh_name, comparator, unit in _ENTRY_CHECKS:
        threshold = getattr(p, thresh_name)
        value = feats.get(key)
        if threshold is None:
            passed, applicable = True, False
        elif comparator == ">=":
            passed, applicable = (value >= threshold), True
        else:
            passed, applicable = (value <= threshold), True
        out.append({"id": key, "label": label, "value": value,
                    "threshold": threshold, "threshold_name": thresh_name,
                    "comparator": comparator, "unit": unit,
                    "passed": passed, "applicable": applicable,
                    "source": "sleeve_detector"})
    return out


def entry_conditions(feats: Mapping[str, Any], params: StressParams | None = None) -> bool:
    """Does the basket say 'stressed' at 10:30? One place, so live and replay cannot differ.

    Stage 5ZZP made this `all()` over `entry_checks` rather than four inline comparisons. The
    comparisons, their order and their thresholds are unchanged, and the equivalence is
    asserted over a swept grid rather than argued here.
    """
    return all(c["passed"] for c in entry_checks(feats, params))


def stop_price(pre_high: float, params: StressParams | None = None) -> float:
    p = params or StressParams()
    return float(pre_high) * (1.0 + p.stop_pad)


def target_price(entry: float, stop: float, params: StressParams | None = None) -> float:
    p = params or StressParams()
    return float(entry) - p.rr * (float(stop) - float(entry))


def risk_dollars(entry: float, stop: float, point_value: float, qty: int) -> float:
    """The ACTUAL stop distance, not a multiple of anything — so moving the stop moves it."""
    return abs(float(stop) - float(entry)) * float(point_value) * int(qty)


def first_low_break(day_bars_1m: pd.DataFrame, level: float, start: str, end: str):
    """`(timestamp, fill)` for the first 1-minute bar in the window whose LOW breaks `level`.

    Filled at `min(open, level)`: a bar that gapped through fills at its open, one that traded
    down through fills at the level. Never better than the market went.
    """
    sub = day_bars_1m[(day_bars_1m.index.time >= _t(start))
                      & (day_bars_1m.index.time <= _t(end))]
    hit = sub[sub["low"] < level]
    if hit.empty:
        return None
    return hit.index[0], min(float(hit.iloc[0]["open"]), level)


def exit_conditions(day_bars_1m: pd.DataFrame, direction: str, entry_ts, stop: float,
                    target: float, end_time: str):
    """`(price, reason, timestamp)` — stop, target, or the close at `end_time`.

    Scans bars **strictly after** the entry bar, so a trade cannot exit on the bar it entered
    on. Within a bar the stop is checked before the target: when one bar spans both, the
    pessimistic side is taken rather than the convenient one.
    """
    fwd = day_bars_1m[(day_bars_1m.index > pd.Timestamp(entry_ts))
                      & (day_bars_1m.index.time <= _t(end_time))]
    if fwd.empty:
        return None
    exit_px = float(fwd.iloc[-1]["close"])
    exit_ts = fwd.index[-1]
    for ts, bar in fwd.iterrows():
        high, low, op = float(bar["high"]), float(bar["low"]), float(bar["open"])
        if direction == SHORT:
            if high >= stop:
                return (stop if low <= stop else op), "stop", ts
            if low <= target:
                return (target if high >= target else op), "target", ts
        else:
            if low <= stop:
                return (stop if high >= stop else op), "stop", ts
            if high >= target:
                return (target if low <= target else op), "target", ts
        exit_px, exit_ts = float(bar["close"]), ts
    return exit_px, "time", exit_ts


def _day_key(ts) -> pd.Timestamp:
    t = pd.Timestamp(ts)
    return (t.tz_localize(None) if t.tzinfo is not None else t).normalize()


def daily_slices(frames: Mapping[str, pd.DataFrame], params: StressParams | None = None):
    """`{(day, inst): bars}` and `{(day, inst): prior RTH close}`, in session order.

    The prior close is carried forward per instrument rather than looked up, because "the
    session before this one" is a property of the instrument's own trading calendar and a
    date-arithmetic guess gets holidays wrong.
    """
    p = params or StressParams()
    bars: dict = {}
    prev_close: dict = {}
    for inst, df in frames.items():
        last = None
        for day_ts, g in df.groupby(df.index.normalize()):
            day = _day_key(day_ts)
            rth = g.between_time(p.rth_start, p.rth_end)
            if rth.empty:
                continue
            bars[(day, inst)] = g
            prev_close[(day, inst)] = last
            last = float(rth.iloc[-1]["close"])
    return bars, prev_close


def basket_state(day, bars: Mapping, prev_close: Mapping,
                 params: StressParams | None = None) -> dict:
    """What the basket looked like at 10:30, and whether that is a setup. Stage 5ZZP.

    Extracted verbatim from `detect_entry_for_slot`'s opening, which computed exactly this and
    then threw it away on the way to `return []`. The values were never missing — measured on
    2026-08-27, every slot the route recorded said `not_exposed_by_sleeve` for
    `breadth_down_count` while the number sat in a local variable one frame down.

    Two readers, one computation. `detect_entry_for_slot` decides from it and a diagnostic
    reports from it; a second traversal of the same bars would be a second answer to the same
    question, which is the defect this repo has paid for more than once.

    `set_up` is False for three DIFFERENT reasons and each is named, because "no setup" and
    "no bars" are not the same fact and this route has been bitten by collapsing them before.
    """
    p = params or StressParams()
    day = _day_key(day)
    ctxs: dict = {}
    for inst in BREADTH_BASKET:
        g = bars.get((day, inst))
        if g is None:
            return {"set_up": False, "reason": "missing_bars",
                    "detail": f"{inst} has no bars for this session",
                    "contexts": {}, "features": None, "checks": []}
        c = session_context(g, prev_close.get((day, inst)), p)
        if c is None:
            return {"set_up": False, "reason": "session_not_judgeable",
                    "detail": f"{inst} has no setup bar, or fewer than "
                              f"{p.min_pre_bars} bars before it",
                    "contexts": {}, "features": None, "checks": []}
        ctxs[inst] = c

    feats = peer_features([ctxs[i] for i in BREADTH_BASKET])
    checks = entry_checks(feats, p)
    if not all(c["passed"] for c in checks):
        failed = [c for c in checks if not c["passed"]]
        return {"set_up": False, "reason": "conditions_not_met",
                "detail": "; ".join(f"{c['label']} {c['value']} (needs {c['comparator']} "
                                    f"{c['threshold']})" for c in failed),
                "contexts": ctxs, "features": feats, "checks": checks,
                "first_failed": failed[0]["id"] if failed else None}
    return {"set_up": True, "reason": "", "detail": "",
            "contexts": ctxs, "features": feats, "checks": checks, "first_failed": None}


def detect_entry_for_slot(frames: Mapping[str, pd.DataFrame], day, *, now=None,
                          params: StressParams | None = None,
                          bars=None, prev_close=None) -> list:
    """Every Stress setup for `day`, judged with only what exists by `now`.

    `now` bounds the entry scan: a slot firing at 11:00 may see a break that happened at 10:40
    but not one that will happen at 11:30. Left as `None` for the historical builder, which is
    entitled to the whole window.

    Returns a list — empty when the basket did not set up, or set up and never broke the low.
    Empty is an ANSWER. Anything that stops the rule from running raises in the caller instead.
    """
    p = params or StressParams()
    day = _day_key(day)
    if bars is None or prev_close is None:
        bars, prev_close = daily_slices(frames, p)

    state = basket_state(day, bars, prev_close, p)
    if not state["set_up"]:
        return []
    ctxs, feats = state["contexts"], state["features"]

    end = p.entry_end
    if now is not None:
        now_t = pd.Timestamp(now)
        hhmm = f"{now_t.hour:02d}:{now_t.minute:02d}"
        if hhmm < p.entry_start:
            return []
        end = min(end, hhmm)

    out = []
    for inst in p.instruments:
        c, g = ctxs.get(inst), bars.get((day, inst))
        if c is None or g is None or not c["below"]:
            continue
        found = first_low_break(g, c["pre_low"], p.entry_start, end)
        if found is None:
            continue
        entry_ts, entry = found
        stop = stop_price(c["pre_high"], p)
        dist = stop - entry
        if dist <= 0 or dist / entry > p.max_stop_pct:
            continue
        out.append(StressSetup(
            day=day, inst=inst, direction=SHORT,
            signal_time=c["signal_time"], known_time=c["known_time"],
            entry_time=entry_ts, entry=float(entry), stop=float(stop),
            target=float(target_price(entry, stop, p)),
            pre_high=c["pre_high"], pre_low=c["pre_low"], vwap=c["vwap"], gap=c["gap"],
            below_count=feats["below_count"], gapdown_count=feats["gapdown_count"],
            avg_gap=feats["avg_gap"]))
    return out


def build_trades(frames: Mapping[str, pd.DataFrame], costs: Mapping[str, Any],
                 point_values: Mapping[str, float],
                 params: StressParams | None = None) -> pd.DataFrame:
    """The whole historical book for this rule — the shape the measured artifact carries.

    Exists so the promoted module can be compared against the scratch chain trade for trade.
    A live slot does not call this; it calls `detect_entry_for_slot`, and both go through the
    same conditions and the same levels.
    """
    p = params or StressParams()
    bars, prev_close = daily_slices(frames, p)
    days = sorted({d for d, _i in bars})
    rows = []
    for day in days:
        for s in detect_entry_for_slot(frames, day, params=p, bars=bars, prev_close=prev_close):
            g = bars[(day, s.inst)]
            exited = exit_conditions(g, s.direction, s.entry_time, s.stop, s.target, p.exit_time)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            pv = float(point_values[s.inst])
            pnl1 = (s.entry - exit_px) * pv - costs[s.inst].round_turn_cost()
            rows.append({
                "trade_id": f"stress_{'mnq_only_g3_q7'}_{s.inst}_{day.date()}",
                "cluster": SLEEVE, "instrument": s.inst, "direction": s.direction,
                "day": day, "entry_time": s.entry_time, "signal_time": s.signal_time,
                "known_time": s.known_time, "exit_time": exit_ts,
                "entry": s.entry, "stop": s.stop, "target": s.target, "exit": float(exit_px),
                "exit_reason": reason,
                "pnl1": float(pnl1), "risk1": float((s.stop - s.entry) * pv),
                "qty": p.qty,
                "pnl_sized": float(pnl1) * p.qty,
                "risk_sized": float((s.stop - s.entry) * pv) * p.qty,
            })
    return pd.DataFrame(rows)
