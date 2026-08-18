"""global_index/test_resume_equivalence.py — a resumed replay must equal a full one

verify_resume.py established this once, by hand, and is cited in run_scheduler as
standing evidence: "verify_resume covers MNKD 14/14". It is in no test and no schedule,
so it does not re-establish itself when the engine changes, when the parquet is
repaired, or when the checkpoint format moves. Evidence that ran once is a snapshot;
this file is the part of it that runs every time.

Deliberately thin. verify_resume walks six back-marks across five instruments off
data/cache/futures and takes minutes; this takes one instrument, one back-mark and a
420-session slice, measured at ~10s for its three replays. It is not a replacement —
it is the tripwire, and verify_resume stays the full check to run by hand when
something real changes.

MNKD rather than a Rổ 4 leg, for two reasons. Its parquet lives in global_index/data
and travels with the repo layout, while data/cache/futures does not. And it is the
instrument with the Tokyo session clock, its own engine parameters and lagged SPY
labels — the one verify_resume's own docstring says had not been checked at all, and
the one whose timezone handling has broken twice.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = Path(__file__).resolve().parent.parent
_NKD = _ROOT / "global_index" / "data" / "NKD_continuous_1m_8y.parquet"
_SPY = _ROOT / "spy_daily_live.csv"

# verify_resume refuses a back-mark with under 300 sessions of history behind it: the
# chandelier band reads a Wilder-smoothed daily ATR, which a short slice cannot carry.
_SESSIONS = 420
# How far back to look for a usable checkpoint day. Not a fixed offset: which day
# carries a position depends on the data, and a hardcoded one silently decays into a
# day that exercises nothing as the parquet grows — the same trap as pinning a calendar
# date. The day is derived below instead, at no extra replay.
_SEARCH = 40

NKD_KW = dict(ema_period=10, chandelier_atr_mult=2.5, max_hold_days=5, gap_fill=True)


def _inputs():
    from futures._validated_core import benchmark_daily, label_regimes
    from futures.basket import REGIME
    from global_index import specs as gi_specs
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index.regime import RegimeLabels

    df = gi_load(str(_NKD))
    sess = sorted(set(df.index.normalize().tz_localize(None)))
    cut = sess[-_SESSIONS]
    if df.index.tz is not None:
        cut = cut.tz_localize(df.index.tz)
    df = df[df.index >= cut]

    spy = pd.Series(label_regimes(benchmark_daily(str(_SPY)), "2018-01-01", 3,
                                  REGIME["hmm_fit_end"]))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()

    cn = gi_specs.SPECS["MNKD"]
    cost = GIFC(point_value=cn.point_value, tick=cn.tick,
                commission_rt=cn.commission_rt, slippage_ticks_per_side=2.0)
    return df, RegimeLabels(spy.sort_index(), lag_days=1), cost


def _sessions(df):
    """Session labels exactly as _swing_cache derives them — see verify_resume."""
    import numpy as np
    local = df.index.normalize().tz_localize(None)
    uniq, starts = np.unique(local.values, return_index=True)
    return pd.DatetimeIndex(uniq), starts


pytestmark = pytest.mark.skipif(
    not (_NKD.exists() and _SPY.exists()),
    reason=f"needs {_NKD.name} and {_SPY.name}; both are gitignored, so a bare "
           f"worktree skips this rather than failing (see RUNNER_AUDIT_ROUND2 §4)")


def test_resuming_from_a_checkpoint_reproduces_the_full_replay():
    """Seed the day loop at day D and it must produce what replaying from the start did.

    Compared on the WHOLE trade, not a summary: two paths that traded at different
    prices, or exited on different rules, can still agree on day and pnl. The live
    shadow compares seven fields for a reason written down there; this one has no live
    frame to be careful about, so it compares all of them, exactly as verify_resume
    does.

    The frame starts at D, not D+1 — _swing_cache reads each bar's gap flag from its
    spacing to the previous bar and forces the frame's first bar to "no gap", so D rides
    along as a lead-in and resume_after_day keeps it out of the replay. Cut it at D+1
    and a GAP exit silently becomes a CHANDELIER one, filled at the stop instead of the
    worse open.
    """
    import futures._validated_core as vc
    from futures._validated_core import backtest_swing_tf, daily_atr_series

    df, labels, cost = _inputs()
    sess, starts = _sessions(df)

    datr = daily_atr_series(df)
    vc._SWING_CACHE.clear()
    trades_full, pos_full = backtest_swing_tf(df, labels, cost, return_open=True, **NKD_KW)

    # Pick the checkpoint day off the trades already computed, so choosing it costs no
    # extra replay — and pick one that makes all three resume inputs load-bearing.
    # Measured the hard way: a day meeting only the first two conditions passed the
    # comparison even with resume_after_day and datr stripped out, because nothing in
    # the compared window depended on them. A green test that survives the mutation of
    # what it claims to check is the failure this file exists to prevent.
    #
    #   carries a position   -> resume_pos is used, and its stop and entry travel
    #   trades close after   -> the seeded trade is actually emitted and compared
    #   a CHANDELIER exit    -> the band reads the Wilder ATR, so datr must be the full
    #                           history and not the slice's own
    #   activity on D itself -> if resume_after_day stops excluding it, D is replayed
    #                           and the difference shows
    ai = None
    for back in range(1, _SEARCH + 1):
        cand_i = len(sess) - 1 - back
        if cand_i < 1:
            break
        cand = sess[cand_i]
        after = [t for t in trades_full if pd.Timestamp(t["exit_day"]) > cand]
        carried = any(pd.Timestamp(t["day"]) <= cand < pd.Timestamp(t["exit_day"])
                      for t in trades_full)
        on_day = any(pd.Timestamp(t["day"]) == cand or pd.Timestamp(t["exit_day"]) == cand
                     for t in trades_full)
        if (carried and after and on_day
                and any(t.get("reason") == "CHANDELIER" for t in after)):
            ai = cand_i
            break
    assert ai is not None, (
        f"no day in the last {_SEARCH} sessions carries a position across it, has a "
        f"chandelier exit after it and activity on the day itself. Without all three "
        f"the comparison cannot tell a working resume from a broken one — widen "
        f"_SEARCH or _SESSIONS rather than dropping a condition")
    D = sess[ai]

    vc._SWING_CACHE.clear()
    _, pos_at_D = backtest_swing_tf(df[df.index < df.index[starts[ai + 1]]], labels, cost,
                                    return_open=True, **NKD_KW)
    vc._SWING_CACHE.clear()
    got, pos_resumed = backtest_swing_tf(df[df.index >= df.index[starts[ai]]], labels,
                                         cost, datr=datr, resume_pos=pos_at_D,
                                         resume_after_day=D, return_open=True, **NKD_KW)

    want = [t for t in trades_full if pd.Timestamp(t["exit_day"]) > D]

    # Self-check before the comparison. A checkpoint with nothing open and no trades
    # after it never walks the seeding path at all, so a green result would mean the
    # test ran and proved nothing — the exact failure verify_resume was fixed for.
    assert pos_at_D is not None or want, (
        f"checkpoint at {D.date()} carries no position and no trade closes after it, "
        f"so the resume path is never exercised. Move _BACK.")

    assert got == want, (
        "the resumed replay produced different trades from the full one:\n"
        f"  full   ({len(want)}): {want[:2]}\n"
        f"  resume ({len(got)}): {got[:2]}")

    def ident(p):
        return None if p is None else (p["dir"], round(float(p["entry"]), 4),
                                       round(float(p["stop"]), 4),
                                       str(pd.Timestamp(p["entry_day"]).date()))

    assert ident(pos_resumed) == ident(pos_full), (
        f"the open position disagrees, and its stop is what becomes a live STP order: "
        f"full={ident(pos_full)} resume={ident(pos_resumed)}")
