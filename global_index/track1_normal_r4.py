"""global_index/track1_normal_r4.py — the Normal-R4 sleeve, production-clean.

Stage 4, closing SLEEVE_normal_r4 by PROMOTION rather than by accepting isolation.

**Nothing here monkeypatches anything.** It imports `TrendFollowStrategy` and
`futures._validated_core` and calls them; it never replaces a symbol in either. That is the
whole point: the scratch generator's correctness was never in doubt — it reproduces the
committed rows exactly — but it got there by substituting five production symbols for the
duration of its run, so while it ran, the production engine WAS the patched one and anything
else in the process reading `futures._validated_core` got the wrong answer.

What the scratch path did, and where each piece went
-----------------------------------------------------
    scratch/harness.patched_engine(Cfg(ema=50, stop_basis=2.0, ratchet=False,
                                       arm_hours=ARM_LIVE))
        -> the parameters are now `NormalR4Params`, passed in rather than patched in.

    tf.TrendFollowStrategy.generate_signal = gated_generate
        -> `_gated_signal()` below. The gates are applied by the CALLER to the strategy's
           own return value, instead of the method being replaced. Same predicate, same
           order — SHORT gate first, then the R4 context filter — and no global mutation.

    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
        -> `ALLOWED_REGIMES` here, a local constant handed to the scan.

    force_all_bars_gappable()   (replaces futures._validated_core._swing_cache)
        -> `_gap_flags()` below post-processes the cache the real function returned, into a
           copy this module owns. The production cache is left exactly as it was found.

    model_sameday_stop.run_loop(...)
        -> `_replay()` below, the day loop, with only the branches this sleeve reaches:
           ratchet off, no same-day stop, no entry latency, no disaster stop, no widening.

    ST.SwingTFEngine / SM.StressMidEngine replacements
        -> not needed. This module is the sleeve; nothing else has to be silenced to keep it
           from running.

The fill law is a parameter, not a patch
-----------------------------------------
`_swing_cache` flags a bar as gap-eligible when a break longer than 15 minutes precedes it.
The committed promotion artifacts were built with EVERY bar gap-eligible. Both laws were
measured across all three windows and differ by $0 to +$6 at book level, but they are not the
same law and this module will not pretend they are: `fill_law` selects one, and the default is
the artifact law because that is what the committed rows were built under and what an
equivalence test therefore has to reproduce.

Exactness is the acceptance test, not an aspiration
----------------------------------------------------
`scratch/test_track1_stage4_production_clean_20260823.py` compares this module's output to the
committed rows, per instrument, row for row. If it diverges the honest result is the first
divergence, not a tuned parameter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from global_index.track1_normal_filters import (FLOOR_RANGE_P90, VOL_LE, R4ContextFilter,
                                                short_days_from_csv)

#: The sleeve trades this regime and no other. A local constant, because the scratch path
#: got here by mutating `trend_follow.DEFAULT_CONFIG` for the duration of a run.
ALLOWED_REGIMES: frozenset = frozenset({"Normal"})

#: Arm the stop at 14:05 ET on the session AFTER entry. Expressed in hours because that is
#: what the day loop compares against; 14 + 5/60 is 14:05.
ARM_HOURS: float = 14 + 5 / 60

FILL_ARTIFACT = "artifact_all_bars_gappable"
FILL_PRODUCTION = "production_gap_after_15min_break"
FILL_LAWS = (FILL_ARTIFACT, FILL_PRODUCTION)


@dataclass(frozen=True)
class NormalR4Params:
    """Every setting that decides which trades exist.

    `chandelier_atr_mult` is here and is NOT a stop width: with `ratchet=False` the day loop
    never recomputes the stop, so the multiple is only what the strategy config carries into
    `generate_signal`. Naming it honestly is cheaper than explaining later why sweeping it
    moved three things at once.
    """
    ema_period: int = 50
    stop_basis_atr_mult: float = 2.0          # entry -+ 2.0 x DAILY ATR, anchored at entry
    chandelier_atr_mult: float = 2.5          # strategy config only; not a stop width here
    max_hold_days: int = 5
    ratchet: bool = False
    arm_hours: float = ARM_HOURS
    range_max: float = FLOOR_RANGE_P90
    rel_volume_max: float = VOL_LE
    vol_feature: str = "rvol_slot20"
    spy_short_filter: str = "below_sma50"

    #: The law the LIVE route runs — Stage 5M-1. This default was `FILL_ARTIFACT` until
    #: 2026-08-23, and that was the wrong way round.
    #:
    #: The artifact law treats every bar as gappable and fills at the worse open. The
    #: production law fills at the stop unless a real break of more than 15 minutes preceded
    #: the bar, which is what the live engine actually does. The three-blockers report of
    #: 2026-08-22 measured both on the shipped generator across floor/vault2025/vault2026 and
    #: adopted the production law as the Track 1 identity: the book-level difference over
    #: seven years is $0 to +$6, and it moves in the SAFE direction — the published Track 1
    #: numbers were measured under the more conservative of the two.
    #:
    #: Why the DEFAULT had to move, rather than each live callsite being patched: a default is
    #: what gets taken. Four places in the route read `NormalR4Params().fill_law` for the
    #: identity they record, and a fifth — `track1_sleeves.LiveSleeveSource.detect` — built
    #: `NormalR4Params(ema_period=...)` and got the artifact law into the ENGINE, not just
    #: into a hash. That fifth site does not contain the string `fill_law` anywhere, so the
    #: search that found the other four walked straight past it. Patching callsites leaves the
    #: trap armed for the next one nobody greps up.
    #:
    #: Reproducing a committed artifact is now the explicit case, which is the right way round:
    #: pass `fill_law=FILL_ARTIFACT` and say so. The Stage 4 reproduction does exactly that and
    #: still matches the committed rows exactly.
    fill_law: str = FILL_PRODUCTION

    def __post_init__(self) -> None:
        if self.fill_law not in FILL_LAWS:
            raise ValueError(f"fill_law must be one of {FILL_LAWS}, got {self.fill_law!r}")


def _strategy(params: NormalR4Params):
    """A TrendFollowStrategy configured for this sleeve, built per call.

    Built rather than shared, and configured through its constructor rather than by editing
    `DEFAULT_CONFIG`: a module-level strategy whose config someone else can reach is the
    same hazard as the monkeypatch, one indirection further away.
    """
    from raits.strategies.trend_follow import TrendFollowStrategy
    base = dict(TrendFollowStrategy().config)
    base["ema_period"] = params.ema_period
    base["chandelier_atr_mult"] = params.chandelier_atr_mult
    base["allowed_regimes"] = sorted(ALLOWED_REGIMES)
    return TrendFollowStrategy(base)


def _cache_for(df: pd.DataFrame, params: NormalR4Params) -> dict:
    """The per-instrument precompute, with the fill law applied to a COPY.

    `_swing_cache` memoises by `id(df)` and hands back the live dict. Rewriting the gap flags
    in place would change what every other reader of that frame sees — which is exactly the
    class of damage this module exists to avoid — so the arrays are copied first.
    """
    from futures._validated_core import _swing_cache, daily_atr_series
    datr = daily_atr_series(df)
    src = _swing_cache(df, datr)
    if params.fill_law == FILL_PRODUCTION:
        return {"datr": src["datr"], "days": src["days"], "hl": src["hl"],
                "b5": src["b5"], "ts": src.get("ts", {})}
    hl = {}
    for day, (high, low, opn, isg) in src["hl"].items():
        hl[day] = (high, low, opn, np.ones(len(isg), dtype=bool))
    return {"datr": src["datr"], "days": src["days"], "hl": hl,
            "b5": src["b5"], "ts": src.get("ts", {})}


def make_signal_fn(strat, params: NormalR4Params, datr: pd.Series, *,
                   short_days: set, context: "R4ContextFilter | None", observer=None):
    """One callable that answers "what does this bar signal", gates included.

    This is the seam that replaces the monkeypatch. The scratch path reached the same
    behaviour by replacing `TrendFollowStrategy.generate_signal` on the CLASS — twice over,
    once for the gates and once for the stop basis — which is why anything else in the
    process saw a different engine while it ran. Here the strategy is asked, and the answer
    is then gated and re-anchored by the caller.

    The order is inherited and it matters:

      1. the strategy's own signal
      2. the SPY short gate — unconditional, and ahead of the context filter, because it
         predates the filter rather than arriving with it
      3. the R4 context filter, whose counters attribute the block to this bar
      4. the stop re-anchor

    Step 4 lives HERE rather than in a pass over the signal cache, and that is not a
    stylistic choice: the day loop rescans from scratch after a same-day exit, and a
    re-anchor applied only to the cache would leave those rescanned entries carrying the
    strategy's 5-minute band instead of this sleeve's daily-ATR stop. The scratch code has
    a comment saying exactly that, and the same trap is avoided the same way.

    A day whose daily ATR is missing or non-positive keeps its ORIGINAL stop rather than
    being dropped — matching the wrapper, which returns the signal untouched.
    """
    def signal_for(prev_bar, resume_bar, ema, atr, regime, avgv):
        # Stage 5ZZZ-AL. OBSERVABILITY ONLY, and only on the LIVE path.
        #
        # `make_signal_fn` has exactly two callers in this file: `run_instrument`, which is
        # the backtest, and `detect_entry_for_slot`, which is the live slot. Only the second
        # passes an observer, so the backtest reaches every line below with `observer is
        # None` and allocates nothing — the row-for-row comparison against the committed
        # artifacts is unchanged BY CONSTRUCTION rather than by having been checked.
        #
        # Reported as `bar_gate`, never as `gate`: these fire once per bar and the slot-level
        # list feeds "nearest failed condition", which must keep describing the session.
        on_gate = None
        if observer is not None:
            _ts0 = resume_bar.name

            def on_gate(name, passed, value, threshold, comparator):   # noqa: F811
                try:
                    observer({"kind": "bar_gate", "gate": name, "passed": bool(passed),
                              "value": value, "threshold": threshold,
                              "comparator": comparator, "bar_ts": _ts0})
                except Exception:                                  # noqa: BLE001
                    pass

        sig = strat.generate_signal(prev_bar, resume_bar, ema, atr, regime, avgv,
                                    on_gate=on_gate)
        if not sig:
            return None
        ts = pd.Timestamp(resume_bar.name)
        day = (ts.tz_localize(None) if ts.tz is not None else ts).normalize()
        # Each of the three below keeps its ORIGINAL predicate and derives the report from it.
        # The reverse — phrasing the report first and testing its negation — is how the EMA
        # gate in the engine nearly started refusing a NaN it had always admitted.
        short_blocked = sig.get("direction") == "SHORT" and day not in short_days
        if on_gate is not None:
            # Comparator left empty on purpose: this gate is a membership test against a
            # day set, not an inequality, and printing an operator beside a filter NAME made
            # the panel read "needs long or short-allowed day below_sma50".
            on_gate("spy_short_gate", not short_blocked, sig.get("direction"),
                    {"spy_short_filter": params.spy_short_filter}, "")
        if short_blocked:
            return None
        context_blocked = context is not None and not context.allow(ts)
        # Reported ONLY when the sleeve actually has a context filter. NKD runs with
        # `apply_context_filter=False`, so `context is None` and the gate is not applied at
        # all — announcing it as "passed" would be the same lie as drawing a gate that never
        # ran as a pass, which is the distinction this whole stage exists to keep. Caught by
        # the vocabulary test, which found NKD reporting a filter it does not use.
        if on_gate is not None and context is not None:
            on_gate("r4_context_filter", not context_blocked, str(ts),
                    {"range_max": params.range_max, "rel_volume_max": params.rel_volume_max},
                    "")
        if context_blocked:
            return None
        try:
            da = float(datr.asof(day))
        except Exception:
            if on_gate is not None:
                on_gate("fixed_stop_daily_atr", False, None,
                        {"stop_basis_atr_mult": params.stop_basis_atr_mult}, "")
            return sig
        if not np.isfinite(da) or da <= 0:
            if on_gate is not None:
                on_gate("fixed_stop_daily_atr", False, da,
                        {"stop_basis_atr_mult": params.stop_basis_atr_mult}, "")
            return sig
        if on_gate is not None:
            on_gate("fixed_stop_daily_atr", True, da,
                    {"stop_basis_atr_mult": params.stop_basis_atr_mult}, "")
        sig = dict(sig)
        ep = float(sig["entry_price"])
        band = params.stop_basis_atr_mult * da
        sig["initial_stop"] = (ep - band) if sig["direction"] == "LONG" else (ep + band)
        return sig

    return signal_for


def _scan_window(strat, bars5, win, regime, signal_for, ema_period: int, *, observer=None):
    """First admitted signal inside `win`, or None. Shared by the cache pass and the rescan.

    `avgv` is taken by POSITION inside `win`, so a truncated window genuinely produces
    different averages — which is the whole reason a day that already exited cannot be served
    from the cache and has to be rescanned.

    `observer` — Stage 5ZZZ-B, OBSERVABILITY ONLY. The trend filter, the ATR and the ten-bar
    average volume are computed here and, until this stage, discarded: the dashboard could name
    the four variables this sleeve decides on and had to print "not reported by detector" beside
    every one of them.

    A listener is passed IN rather than the values being returned, and the reason is the rule
    this file already states twice: everything that decides anything is reused, never
    re-derived. A diagnostics module that recomputed an EMA would be a second implementation of
    the thing the artifacts were generated with, and it would drift.

    It cannot change a decision. It is called after `signal_for` has already answered, its
    return value is discarded, and every call is wrapped — a diagnostics bug must not be the
    reason a slot fails to find its entry.
    """
    from futures._validated_core import atr14
    idx = list(win.index)
    for k in range(1, len(idx)):
        hist = bars5.loc[:idx[k]]
        if len(hist) < max(ema_period, 14) + 1:
            continue
        ema = strat.calculate_ema(hist, ema_period)
        atr = atr14(hist)
        avgv = float(win["volume"].iloc[max(0, k - 11):k - 1].mean())
        if np.isnan(atr) or np.isnan(avgv):
            continue
        sig = signal_for(win.loc[idx[k - 1]], win.loc[idx[k]], ema, atr, regime, avgv)
        if observer is not None:
            try:
                observer({"kind": "bar", "bar_ts": idx[k], "ema": ema, "atr": atr,
                          "avgv": avgv, "regime": regime, "ema_period": ema_period,
                          "prev_bar": win.loc[idx[k - 1]], "resume_bar": win.loc[idx[k]],
                          "signal": sig})
            except Exception:                                  # noqa: BLE001
                pass
        if sig:
            return idx[k], sig
    return None


def scan_signals(strat, cache: dict, labels, params: NormalR4Params, signal_for) -> dict:
    """{day: (bar_ts, signal)} — the first admitted signal of each session.

    One pass per instrument, and valid only for a day with NO earlier exit. That caveat is
    inherited rather than invented: `avgv` is positional inside the 14:00-15:55 window, so
    after an exit truncates the window the averages shift and the signal can differ. The day
    loop rescans such days instead of reading this.
    """
    datr = cache["datr"]
    out = {}
    for day in cache["days"]:
        reg = labels.get(day)
        if reg not in ALLOWED_REGIMES:
            continue
        bars5 = cache["b5"][day]
        hit = _scan_window(strat, bars5, bars5.between_time("14:00", "15:55"), reg,
                           signal_for, params.ema_period)
        if hit is None:
            continue
        # A day with no usable DAILY ATR is dropped from the cache, and this asymmetry is
        # inherited rather than invented: the signal wrapper keeps such a signal with its
        # original 5-minute stop, while the cache builder drops it. Since almost every entry
        # comes through the cache, dropping is the effective rule.
        #
        # It matters at the START of a clipped window, where `daily_atr_series` has no 14
        # sessions behind it. Measured on vault2025: without this the port produced trades on
        # 2025-01-02 and 2025-01-10 that the record does not have, and the record's first
        # trade is 2025-01-21 — about fourteen sessions in, which is exactly the warm-up.
        try:
            da = float(datr.asof(pd.Timestamp(day)))
        except Exception:
            continue
        if not np.isfinite(da) or da <= 0:
            continue
        out[day] = hit
    return out


def _replay(strat, labels, cost, params: NormalR4Params, *, cache: dict, signals: dict,
            signal_for) -> list:
    """The day loop, with only the branches this sleeve reaches.

    Deliberately NOT a general engine. `run_loop` also carries same-day stops, entry latency,
    disaster stops, stop widening and MAE bookkeeping; this sleeve uses none of them, and
    carrying dead branches into production is how a branch nobody exercises ends up running.

    Three things it does keep, because each decides money:

    * **the arming window.** The stop is not live until 14:05 on the session after entry, in
      the sleeve's OWN session clock. Hits before that instant are discarded — the engine
      would have exited, live could not have, and that difference is the whole reason this
      sleeve arms late rather than at the fill.
    * **gap fill.** When the bar that triggers the stop OPENED beyond it, the fill is the
      open rather than the stop. Which bars are eligible is the `fill_law`.
    * **same-day re-entry.** A day that already exited is RESCANNED over the window after
      that exit, not served from the signal cache. Leaving this out was measured to lose real
      trades: MES exits MAX_HOLD at 09:30 on 2026-01-26 and re-enters at 15:20 the same
      session, and a first pass without it produced 20 trades where the record has 22.
    """
    datr, days, hl, b5, ts = (cache["datr"], cache["days"], cache["hl"],
                              cache["b5"], cache.get("ts", {}))
    from futures._validated_core import ET

    trades: list = []
    pos = None

    def _close(pos, day, ex, reason, hold, exit_ts):
        pts = (ex - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - ex)
        trades.append(dict(day=pos["entry_day"].date(), exit_day=day.date(),
                           regime=pos["regime"], direction=pos["dir"],
                           entry=round(pos["entry"], 2), exit=round(ex, 2),
                           points=round(pts, 2),
                           pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                           hold_days=hold, reason=reason,
                           entry_time=pos.get("entry_time"), exit_time=exit_ts))

    def _open(day, regime, ts_, sig):
        return dict(dir=sig["direction"], entry=float(sig["entry_price"]), entry_day=day,
                    regime=regime, extreme=float(sig["entry_price"]),
                    stop=float(sig["initial_stop"]), stop0=float(sig["initial_stop"]),
                    entry_time=ts_,
                    _act=day + pd.Timedelta(days=1) + pd.Timedelta(hours=params.arm_hours))

    for day in days:
        exit_ts_today = None

        if pos is not None:
            hold = (day - pos["entry_day"]).days
            if hold >= params.max_hold_days:
                # MAX_HOLD leaves at the 09:30 bar — the convention every recorded figure was
                # produced under.
                _day_ts = ts.get(day)
                if _day_ts is not None and len(_day_ts):
                    _930 = day + pd.Timedelta(hours=9, minutes=30)
                    _tz = str(_day_ts.tzinfo) if _day_ts.tzinfo is not None else ""
                    if _tz in ("", "America/New_York", "US/Eastern"):
                        _cmp = _930.tz_localize(ET) if _day_ts.tzinfo is not None else _930
                        _idx = int(_day_ts.searchsorted(_cmp))
                        if _idx >= len(hl[day][2]):
                            _idx = 0
                    else:
                        _idx = 0
                    op, exit_bar_ts = float(hl[day][2][_idx]), _day_ts[_idx]
                else:
                    op, exit_bar_ts = float(hl[day][2][0]), None
                _close(pos, day, op, "MAX_HOLD", hold, exit_bar_ts)
                pos, exit_ts_today = None, exit_bar_ts
            else:
                high, low, opn, isg = hl[day]
                da = float(datr.asof(day)) if len(datr) else np.nan
                if not np.isnan(da) and da > 0 and len(high):
                    if pos["dir"] == "LONG":
                        run_full = np.maximum.accumulate(np.maximum(high, pos["extreme"]))
                        stop_prev = np.full(len(high), pos["stop"])
                        hit = np.where(low <= stop_prev)[0]
                    else:
                        run_full = np.minimum.accumulate(np.minimum(low, pos["extreme"]))
                        stop_prev = np.full(len(high), pos["stop"])
                        hit = np.where(high >= stop_prev)[0]

                    if pos.get("_act") is not None:
                        _dts = ts.get(day)
                        if _dts is not None and len(_dts):
                            _naive = (_dts.tz_localize(None) if _dts.tz is not None
                                      else _dts)
                            _before = np.asarray(_naive < pos["_act"])
                            if _before.any():
                                hit = hit[hit >= int(_before.sum())]
                            if not _before.all():
                                pos["_act"] = None      # armed; ordinary from here on

                    if len(hit):
                        i = hit[0]
                        stp = float(stop_prev[i])
                        gapped = bool(isg[i]) and (
                            (pos["dir"] == "LONG" and float(opn[i]) < stp) or
                            (pos["dir"] == "SHORT" and float(opn[i]) > stp))
                        ex, reason = (float(opn[i]), "GAP") if gapped else (stp, "CHANDELIER")
                        _ts_exit = ts.get(day)
                        _et = (_ts_exit[i] if _ts_exit is not None and i < len(_ts_exit)
                               else None)
                        _close(pos, day, ex, reason, hold, _et)
                        pos, exit_ts_today = None, _et
                    else:
                        pos["extreme"] = float(run_full[-1])

        if pos is None:
            reg = labels.get(day)
            if reg in ALLOWED_REGIMES:
                bars5 = b5[day]
                if exit_ts_today is None:
                    hit = signals.get(day)
                    if hit is not None:
                        pos = _open(day, reg, hit[0], hit[1])
                else:
                    win = bars5.between_time("14:00", "15:55")
                    win = win[win.index > exit_ts_today]
                    if len(win) >= 2:
                        hit = _scan_window(strat, bars5, win, reg, signal_for,
                                           params.ema_period)
                        if hit is not None:
                            pos = _open(day, reg, hit[0], hit[1])

    return trades


def run_instrument(df: pd.DataFrame, labels, cost, params: NormalR4Params, *,
                   short_days: set, apply_context_filter: bool = True) -> tuple:
    """One instrument, end to end. Returns `(trades, filter_stats)`.

    `apply_context_filter=False` is for the NKD sleeve, which runs the same machinery without
    the R4 context gate — that filter is an R4 thing and applying it to a Tokyo session would
    be inventing a rule. The SPY short gate DOES apply to both, because the generator that
    wrote the artifacts applied it on the strategy class and therefore to every instrument.
    """
    cache = _cache_for(df, params)
    context = (R4ContextFilter(df, range_max=params.range_max, vol_max=params.rel_volume_max,
                               vol_feature=params.vol_feature)
               if apply_context_filter else None)
    strat = _strategy(params)
    signal_for = make_signal_fn(strat, params, cache["datr"], short_days=short_days,
                                context=context)
    signals = scan_signals(strat, cache, labels, params, signal_for)
    trades = _replay(strat, labels, cost, params, cache=cache, signals=signals,
                     signal_for=signal_for)
    return trades, (context.stats() if context is not None else None)


#: What a live slot needs to know about one admitted Normal-R4 entry. Deliberately a small
#: record rather than the raw signal dict: the live source builds a `Candidate` from this, and
#: a dict would let a key be renamed on one side without the other noticing.
@dataclass(frozen=True)
class SwingSetup:
    inst: str
    direction: str
    entry: float
    stop: float
    entry_time: str
    signal_bar: Any
    daily_atr: float
    regime: str


def _observe_clock(observer, now_ts) -> None:
    """Tell the observer WHEN the slot ran. Not whether anything had closed -- see below.

    Stage 5ZZZ-AW. The truncation admits every bar whose bucket STARTS at or before `now`, so
    the newest bar is normally still forming. NKD slots fire every five minutes on the
    boundary, which makes it a few seconds old at essentially every slot: measured on
    2026-08-31, slot 02:05 ET evaluated the 15:05 Tokyo bar and read its volume as 0 against a
    ten-bar average of 3.2. The reading is TRUE -- it is what the detector saw -- and the
    decision is unharmed, because the next slot re-reads the same bar complete. What was
    missing is any way for the page to SAY so.

    This reports the clock and nothing else. The first version also computed whether the bar
    had closed, from the last bar in the WINDOW -- and the window's last bar is not the last
    bar the detector EVALUATED. Measured on 2026-08-28 at 15:52: the detector's last evaluated
    bar was 15:25, closed twenty-seven minutes earlier, and the flag still said "still
    forming". Only the block sees both, so only the block can answer it.

    Deliberately its own event kind. `gates` is what `first_failed_gate` walks in order and
    `bar_gates` is what the grid is built from; a clock is neither, and putting it in either
    would change a meaning that is currently preserved by construction.
    """
    if observer is None:
        return
    try:
        observer({"kind": "clock", "now": str(now_ts)})
    except Exception:                                          # noqa: BLE001
        pass


def observe_window_only(df, labels, day, now, params: NormalR4Params, *,
                        apply_context_filter: bool, observer) -> None:
    """Walk the session window through the detector's own scan, deciding NOTHING.

    Stage 5ZZZ-AV. Promoted from the dashboard, which had grown its own copy of this
    set-up -- same cache, same strategy, same signal function, same window, same truncation.
    Two copies of the window logic is two chances to drift, and the clock handling here is the
    one-keystroke trap that once overwrote 1,050 frozen NKD bars.

    Why a slot needs it. The gates run in order and the first refusal returns, so on a day the
    regime is wrong the detector stops before it looks at a single bar -- and the panel's
    condition rows, which are only written from inside the scan, come back empty. Measured on
    2026-08-31: the slot fetched today's bars from IBKR and reported `bars_evaluated: 0`,
    because nothing had examined them, and every condition read "Data unavailable".

    The replay could fill those rows and its numbers came from the PERSISTED store, which is
    appended after a session closes -- so during a live session it holds the previous day. Old
    numbers under a card labelled with today's session is worse than an empty card.

    So the walk runs here, on the bars the slot already has. It is called AFTER the decision
    has been made and its result is discarded; every call is guarded by the caller so a
    backtest, which passes no observer, never pays for it.
    """
    cache = _cache_for(df, params)
    d = pd.Timestamp(day).normalize()
    b5 = cache["b5"].get(d)
    if b5 is None or not len(b5):
        return
    regime = labels.get(d) if hasattr(labels, "get") else None
    win = b5.between_time("14:00", "15:55")
    now_ts = pd.Timestamp(now)
    widx = win.index
    if now_ts.tz is not None and widx.tz is not None:
        now_ts = now_ts.tz_convert(widx.tz).tz_localize(None)
    elif now_ts.tz is not None:
        now_ts = now_ts.tz_convert("America/New_York").tz_localize(None)
    widx_naive = widx.tz_localize(None) if widx.tz is not None else widx
    win = win[widx_naive <= now_ts]
    if len(win) < 2:
        return
    ctx = (R4ContextFilter(df, range_max=params.range_max, vol_max=params.rel_volume_max,
                           vol_feature=params.vol_feature) if apply_context_filter else None)
    strat = _strategy(params)
    # Stage 5ZZZ-AW. The observer has to reach the SIGNAL function, not only the scan. Without
    # it this walk filled the panel's measurement rows and left the per-bar grid empty --
    # measured on 2026-08-31: 12 bars evaluated, `bar_gate_grid()` returning no rows -- because
    # every per-bar verdict is emitted from inside `make_signal_fn`. The deciding path twenty
    # lines down has always passed it; this copy was promoted from the dashboard, which had no
    # grid to fill and so never noticed the omission.
    signal_for = make_signal_fn(strat, params, cache["datr"], short_days=set(), context=ctx,
                                observer=observer)
    _observe_clock(observer, now_ts)
    _scan_window(strat, b5, win, regime, signal_for, params.ema_period, observer=observer)


def detect_entry_for_slot(df: pd.DataFrame, labels, inst: str, day, now, params: NormalR4Params,
                          *, short_days: set,
                          apply_context_filter: bool = True,
                          observer=None) -> "SwingSetup | None":
    """The first admitted Normal-R4 entry on `day` at or before `now`, or None. Stage 5M-B.

    The live counterpart of one iteration of `scan_signals`, and it exists for the same reason
    `track1_calm_a.detect_entry_for_day` does: the backtest entry point runs a whole day loop
    and needs the 15:55 bar, so a slot at 14:05 cannot call it.

    Everything that decides anything is REUSED, not re-derived — `_cache_for`, `_strategy`,
    `make_signal_fn`, `_scan_window`. A second implementation of an entry rule proves nothing
    about the first, and this sleeve already has committed artifacts that a second
    implementation would silently stop reproducing.

    Truncating at `now` is causally sound rather than merely convenient, and the reason is
    worth stating because it is the one thing that could have gone wrong here: `_scan_window`
    takes `avgv` from `win["volume"].iloc[k-11:k-1]`, which looks BACKWARD from each bar.
    Cutting the tail off the window therefore cannot change the average at any bar that
    survives the cut, so the signal a slot finds at `now` is the same signal the full-day scan
    finds — as long as the full-day scan's first hit is at or before `now`. That equivalence is
    asserted by the Stage 5M-B suite rather than left as a claim here.

    Returns None — not a refusal — when the regime is wrong, the day has no bars, or no bar in
    the window signalled. Those are ordinary "no trade today" outcomes. Refusals belong to the
    caller, which knows whether a missing input was supposed to be there.
    """
    def _say(kind, **fields):
        """Stage 5ZZZ-B. Report a gate to `observer`, never to the caller. See `_scan_window`."""
        if observer is None:
            return
        try:
            observer({"kind": kind, **fields})
        except Exception:                                      # noqa: BLE001
            pass

    cache = _cache_for(df, params)
    day = pd.Timestamp(day).normalize()
    b5 = cache["b5"].get(day)
    if b5 is None or not len(b5):
        _say("gate", gate="session_bars", passed=False,
             detail="no five-minute bars for this session")
        return None
    _say("gate", gate="session_bars", passed=True, detail=f"{len(b5)} bar(s) for the session")

    regime = labels.get(day) if hasattr(labels, "get") else None
    _say("gate", gate="regime", passed=regime in ALLOWED_REGIMES, value=regime,
         threshold=sorted(ALLOWED_REGIMES),
         detail=f"regime {regime!r}; this sleeve trades {sorted(ALLOWED_REGIMES)}")
    if regime not in ALLOWED_REGIMES:
        # Stage 5ZZZ-AV. The decision is already made and does not change. This only records
        # what the session looked like, on the bars this call already holds, so a panel can say
        # "no entry because the regime is wrong -- and here is the market it was wrong in".
        # Guarded on the observer, so the backtest never reaches it.
        if observer is not None:
            try:
                observe_window_only(df, labels, day, now, params,
                                    apply_context_filter=apply_context_filter,
                                    observer=observer)
            except Exception:                                  # noqa: BLE001
                pass
        return None

    # A day with no usable DAILY ATR is dropped, matching `scan_signals`. The asymmetry with
    # `make_signal_fn` — which keeps such a signal at its original stop — is inherited from the
    # generator that wrote the artifacts, and reproducing the sleeve means reproducing it.
    try:
        da = float(cache["datr"].asof(day))
    except Exception:
        _say("gate", gate="daily_atr", passed=False, detail="daily ATR could not be read")
        return None
    if not np.isfinite(da) or da <= 0:
        _say("gate", gate="daily_atr", passed=False, value=da,
             detail="daily ATR is missing or not positive")
        return None
    _say("gate", gate="daily_atr", passed=True, value=da, detail="daily ATR available")

    win = b5.between_time("14:00", "15:55")
    now_ts = pd.Timestamp(now)
    widx = win.index
    # Truncate on the FRAME's clock, not on ET unconditionally. This read
    # `tz_convert("America/New_York")` until Stage 5N, which was correct for every frame it
    # had ever been handed — R4 frames are ET — and a 13-hour error for the one it was about
    # to be handed: the MNKD frame is carried on Asia/Tokyo, and an ET-naive `now` compared
    # against Tokyo-naive stamps would have admitted bars from thirteen hours ahead. The same
    # one-keystroke trap that once overwrote 1,050 frozen NKD bars, one layer up.
    if now_ts.tz is not None and widx.tz is not None:
        now_ts = now_ts.tz_convert(widx.tz).tz_localize(None)
    elif now_ts.tz is not None:
        # A naive frame declares no clock, so ET is assumed — the convention every naive
        # frame in this repo's backtests actually carries for this sleeve family.
        now_ts = now_ts.tz_convert("America/New_York").tz_localize(None)
    widx_naive = widx.tz_localize(None) if widx.tz is not None else widx
    win = win[widx_naive <= now_ts]
    _observe_clock(observer, now_ts)
    _say("gate", gate="bars_so_far", passed=len(win) >= 2, value=len(win), threshold=2,
         detail=f"{len(win)} bar(s) in the window up to {now_ts}")
    if len(win) < 2:
        return None

    context = (R4ContextFilter(df, range_max=params.range_max, vol_max=params.rel_volume_max,
                               vol_feature=params.vol_feature)
               if apply_context_filter else None)
    strat = _strategy(params)
    # Stage 5ZZZ-AL. The observer reaches the per-bar gates HERE and only here. The backtest
    # builder twenty lines up is deliberately left without one, so `run_instrument` cannot
    # start reporting — and cannot start allocating — no matter what this path does.
    signal_for = make_signal_fn(strat, params, cache["datr"], short_days=short_days,
                                context=context, observer=observer)
    hit = _scan_window(strat, b5, win, regime, signal_for, params.ema_period,
                       observer=observer)
    _say("gate", gate="setup_bar", passed=hit is not None,
         detail=("a bar signalled" if hit is not None
                 else "no bar in the window so far signalled"))
    if hit is None:
        return None

    bar_ts, sig = hit
    entry = float(sig["entry_price"])
    stop = sig.get("initial_stop")
    if stop is None or not np.isfinite(float(stop)):
        return None
    return SwingSetup(inst=inst, direction=str(sig["direction"]), entry=entry,
                      stop=float(stop), entry_time=str(pd.Timestamp(bar_ts).time())[:5],
                      signal_bar=bar_ts, daily_atr=da, regime=str(regime))


def generate(dfs: Mapping[str, pd.DataFrame], labels_by_inst: Mapping[str, Any],
             costs: Mapping[str, Any], params_by_inst: Mapping[str, NormalR4Params], *,
             spy_csv: str = "spy_daily_live.csv",
             context_filter_for: set | None = None) -> dict:
    """Every instrument. Returns `{inst: {"trades": [...], "filter_stats": {...}}}`.

    Labels and params are PER INSTRUMENT rather than shared, because they genuinely differ:
    R4 reads the SPY labels directly at ema 50, while MNKD reads them through
    `RegimeLabels(lag_days=1)` at ema 10. Handing one of each to both is how a sleeve ends up
    running the other's engine — measured here on the first attempt, where MNKD ran at ema 50
    and produced a LONG where the record says SHORT.
    """
    short_days = short_days_from_csv(
        spy_csv, next(iter(params_by_inst.values())).spy_short_filter)
    want_filter = set(dfs) if context_filter_for is None else set(context_filter_for)
    out = {}
    for inst, df in dfs.items():
        trades, stats = run_instrument(df, labels_by_inst[inst], costs[inst],
                                       params_by_inst[inst], short_days=short_days,
                                       apply_context_filter=inst in want_filter)
        out[inst] = {"trades": trades, "filter_stats": stats}
    return out
