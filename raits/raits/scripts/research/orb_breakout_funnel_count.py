"""
ORB breakout funnel — how many setups actually exist?
(RESEARCH ONLY — raits/raits/scripts/research/. Read-only: imports the real
ORB classes, modifies nothing, writes nothing except its own report.)

WHY THIS EXISTS
---------------
ORB_RETEST_SCALP is blocked on data resolution (the equity cache is 5-minute
only). Before paying Databento for 1-minute bars, we need to know whether the
strategy could EVER reach a usable sample size — because ORB_RETEST_SCALP is a
strict SUBSET of ORB breakouts, and ORB itself books only 80 trades across
2017-2022 (measured from results_20260707_110323.pkl: 7/17/8/16/25/7 per year).

Resolution buys the ability to SEE a retest. It does not buy sample size:
ORB fires at most once per ticker-day inside a 30-minute window, so trade count
is set by (days x universe x setup rate) — all unchanged by bar frequency.

This script counts the funnel stage by stage on the EXISTING 5-minute cache and
costs nothing. The output is an upper bound on ORB_RETEST_SCALP trade count.

  breakouts ~500+  -> a 1-minute pull can plausibly reach usable n
  breakouts ~150   -> final n lands under ~80 and the study is sample-limited
                      no matter which data source is bought

WHAT IS AND IS NOT VALID AT 5-MINUTE RESOLUTION
-----------------------------------------------
VALID   : counting SETUPS. Whether a breakout occurred, whether the OR was
          valid, whether RVol cleared 2.0 — none of these depend on intrabar
          path.
INVALID : measuring the retest EDGE. Whether `low` touched OR_high while
          `close` held above it is exactly the intrabar ordering a 5-minute bar
          hides. The RETEST column below is a coarse upper-bound proxy, NOT a
          tradeable count and NOT evidence of edge.
CAVEAT  : 1-minute data would detect a somewhat different breakout set (more
          bars = more chances to poke through the boundary). Treat every number
          here as order-of-magnitude, not exact.

WHICH ENGINE GATES ARE REPLICATED
---------------------------------
Applied (mechanical, computable from the cache):
  - ORBUniverseScanner(top_n=10) daily universe from the ~37-name CANDIDATE_POOL
  - engine's 0.5% gap pre-filter in _build_orb_candidates
  - ORBStrategy.run_scanner        (gap >= 1.5%, price $10-1000, volume 2-path)
  - ORBStrategy.calculate_opening_range (0.5-5x ATR, >= $0.20 floor)
  - ORBStrategy.generate_signal    (breakout direction, RVol >= 2.0, fakeout)
  - the real 09:30 OR window / 09:45-10:15 signal window / B+1 confirmation

NOT applied (they need HMM/VIX state this script deliberately does not build):
  - regime gate. NOTE: the engine router activates ORB in **Normal only**
    (_REGIME_STRATEGIES["Calm"] = ["PE_SHORT"]) — ORB never runs in Calm or
    Stress despite orb.py's own allowed_regimes listing Calm.
  - VIX gate (day_vix < 25.0)
  - SPY bull-trend gate (SMA50 > SMA200 — blocks ALL ORB directions in a bear)
  - position caps (MAX_TOTAL=8, MAX_ORB=2, one open position per ticker)
  - PDT guard, position sizing rejections

Those omitted gates are why this funnel OVERCOUNTS. That is intentional: an
upper bound is what the decision needs. The script measures the combined effect
of the omitted gates by calibrating its CONFIRM count against the 80 real ORB
trades over 2017-2022 (see SELF-CHECKS).

SELF-CHECKS (a wrong slice still returns plausible-looking numbers, so these
are asserted rather than eyeballed):
  1. Funnel must be monotonic — each stage <= the stage above it.
  2. CONFIRM over 2017-2022 must be >= 80. This funnel is a superset of the
     engine's ORB path, so a count BELOW the realised trade count proves the
     replication is broken, not that ORB is rare.
  3. RETEST <= BREAKOUT, and every retest bar index must fall inside the
     configured window.

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\orb_breakout_funnel_count.py
    python raits\\raits\\scripts\\research\\orb_breakout_funnel_count.py --end 2018-12-31
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parents[4]   # research/ -> scripts/ -> raits/ -> raits/ -> d:\raits
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from raits.strategies.orb import ORBStrategy                      # noqa: E402
from raits.strategies.universe_scanner import ORBUniverseScanner  # noqa: E402

CACHE_5MIN = _ROOT / "raits" / "data" / "cache" / "data"
CACHE_DAILY = _ROOT / "raits" / "data" / "cache" / "daily"

# Engine constants — mirrored from raits/backtest/engine.py (lines 39-42, 84-92).
# Duplicated deliberately: importing engine.py would pull the whole backtest
# stack. Any drift shows up as self-check #2 failing.
OR_RANGE_START = pd.Timestamp("09:30").time()
ORB_SIGNAL_START = pd.Timestamp("09:45").time()
ORB_SIGNAL_END = pd.Timestamp("10:15").time()
ORB_SCANNER_TOP_N = 10
ENGINE_GAP_PREFILTER = 0.005

# Retest proxy window, in bars after the breakout bar (spec: 2-4 bars).
#
# WARNING — this proxy is OPTIMISTIC, and not by a small margin. The spec's
# "2-4 bars" is written for 1-minute bars, i.e. a 2-4 MINUTE retest window.
# Four bars of 5-minute data is a 20-MINUTE window — 5x the wall-clock time
# for price to come back and touch the boundary. Every retest count this
# script prints is therefore an upper bound on what the real 1-minute rule
# would catch, plausibly by around 2x. Discount accordingly before treating
# the calibrated n as achievable.
RETEST_MAX_BARS = 4
# Spec tolerance grid; the widest is used for the upper bound.
RETEST_TOLERANCES = (0.0010, 0.0020, 0.0030)

# Known ground truth for self-check #2 — measured, not assumed.
KNOWN_ORB_TRADES_2017_2022 = 80


# ──────────────────────────────────────────────────────────────────────────────
# Cache access — O(1) by reconstructing DataCache's md5 key
# ──────────────────────────────────────────────────────────────────────────────

def cache_path(ticker: str, day: pd.Timestamp) -> Path:
    """
    DataCache._generate_cache_key builds md5 of f"{ticker}_{start.date()}_
    {end.date()}_{interval}", and fetch_intraday_bars passes start=end=the day.
    Verified against a file on disk before this script was written — no
    directory scan of 117k files needed.
    """
    d = day.date()
    h = hashlib.md5(f"{ticker}_{d}_{d}_5min".encode()).hexdigest()
    return CACHE_5MIN / f"{ticker}_5min_{h}.parquet"


def load_daily() -> dict:
    out = {}
    if not CACHE_DAILY.is_dir():
        return out
    for f in sorted(CACHE_DAILY.glob("*_daily_*.parquet")):
        t = f.name.split("_daily_")[0]
        try:
            df = pd.read_parquet(f)
            if not df.empty:
                out[t] = df
        except Exception:
            continue
    return out


def load_ticker_window(ticker: str, days: list) -> pd.DataFrame:
    """
    Load only what the ORB funnel needs, across all days, for one ticker:
      - bars 09:30..10:20 (OR window + signal window + retest lookahead)
      - the day's LAST bar (supplies prev_close for the gap filter)
    Keeps memory at ~11 rows/day instead of ~190.
    """
    frames = []
    lo, hi = pd.Timestamp("09:30").time(), pd.Timestamp("10:20").time()
    for day in days:
        p = cache_path(ticker, day)
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p)
        except Exception:
            continue
        if df.empty:
            continue
        rth = df.between_time("09:30", "16:00")
        if rth.empty:
            continue
        head = rth[(rth.index.time >= lo) & (rth.index.time <= hi)]
        tail = rth.iloc[[-1]]
        frames.append(pd.concat([head, tail]))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    return out[~out.index.duplicated(keep="first")].sort_index()


def compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
    """Mirrors BacktestEngine._compute_atr exactly."""
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"] - bars["close"].shift(1)).abs()
    tr = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def retest_hit(bars: pd.DataFrame, i: int, direction: str,
               or_high: float, or_low: float, tol: float) -> bool:
    """
    Coarse 5-minute proxy for the spec's retest rule.
    LONG : some bar in (i, i+RETEST_MAX_BARS] has low <= or_high*(1+tol)
           while close > or_high.
    SHORT: mirror.
    Upper bound only — a 5-minute bar cannot order the touch against the close.
    """
    for j in range(i + 1, min(i + 1 + RETEST_MAX_BARS, len(bars))):
        b = bars.iloc[j]
        if direction == "LONG":
            if float(b["low"]) <= or_high * (1 + tol) and float(b["close"]) > or_high:
                return True
        else:
            if float(b["high"]) >= or_low * (1 - tol) and float(b["close"]) < or_low:
                return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Funnel
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="ORB breakout funnel counter")
    ap.add_argument("--start", default="2017-01-03")
    ap.add_argument("--end", default="2024-07-31")
    ap.add_argument("--out", default=None, help="write report here (default: stdout only)")
    a = ap.parse_args()

    t0 = datetime.now()
    print("=" * 78)
    print("ORB BREAKOUT FUNNEL — setup counting on the existing 5-minute cache")
    print("=" * 78)
    print(f"  window : {a.start} .. {a.end}")
    print(f"  cache  : {CACHE_5MIN}")

    daily = load_daily()
    if not daily:
        print(f"\n  ABORT: no daily parquet under {CACHE_DAILY}")
        return
    print(f"  daily  : {len(daily)} tickers (ORB CANDIDATE_POOL source)")

    # Trading days = union of daily-bar dates, clipped to the window.
    all_days = sorted({d.normalize() for df in daily.values() for d in df.index})
    days = [d for d in all_days
            if pd.Timestamp(a.start) <= d <= pd.Timestamp(a.end)]
    print(f"  days   : {len(days)} trading days")

    scanner = ORBUniverseScanner(top_n=ORB_SCANNER_TOP_N)
    orb = ORBStrategy()

    # ── daily universe selection (T-1 daily bars) ────────────────────────────
    print("\n  [1/3] daily ORB universe selection ...")
    universe_by_day: dict = {}
    uni_sizes = []
    for i, day in enumerate(days):
        if i == 0:
            continue
        try:
            u = scanner.scan(daily, days[i - 1])
        except Exception:
            u = []
        universe_by_day[day] = u
        uni_sizes.append(len(u))
    print(f"        mean universe size: {np.mean(uni_sizes):.1f} tickers/day"
          f"  (top_n={ORB_SCANNER_TOP_N})")

    needed = sorted({t for u in universe_by_day.values() for t in u})
    print(f"        distinct tickers ever selected: {len(needed)}")

    # ORBUniverseScanner.scan needs lookback_days+1 = 61 daily bars before it
    # returns anything. Daily cache starts 2017-01-03, so any window ending
    # before ~2017-04 yields an empty universe — a warm-up artifact, not a
    # finding. Say so explicitly rather than letting self-check #2 fail
    # cryptically on a short early slice.
    empty_frac = float(np.mean([s == 0 for s in uni_sizes])) if uni_sizes else 1.0
    if empty_frac > 0.5:
        print(f"\n        WARNING: {100 * empty_frac:.0f}% of days have an EMPTY universe.")
        print(f"        ORBUniverseScanner needs {scanner.lookback_days + 1} daily bars of")
        print(f"        history; the daily cache begins {min(all_days).date()}.")
        print(f"        A window starting before ~{(min(all_days) + pd.Timedelta(days=95)).date()}")
        print(f"        is inside the scanner warm-up — the counts below will be")
        print(f"        empty for that reason, NOT because setups are rare.")

    # ── load intraday windows once ───────────────────────────────────────────
    print(f"\n  [2/3] loading 5-min windows for {len(needed)} tickers ...")
    intraday: dict = {}
    for n, t in enumerate(needed, 1):
        intraday[t] = load_ticker_window(t, days)
        if n % 5 == 0 or n == len(needed):
            print(f"        {n}/{len(needed)}  {t:<6} "
                  f"{len(intraday[t]):>7,} rows", flush=True)

    # ── funnel ───────────────────────────────────────────────────────────────
    print("\n  [3/3] walking the funnel ...")
    S = Counter()
    by_year = defaultdict(Counter)
    retest_by_tol = {tol: Counter() for tol in RETEST_TOLERANCES}
    retest_bar_idx = []

    for day in days:
        uni = universe_by_day.get(day, [])
        if not uni:
            continue
        S["days_with_universe"] += 1
        yr = day.year

        # Build the candidate dicts run_scanner expects (mirrors
        # BacktestEngine._build_orb_candidates, gap pre-filter included).
        candidates = []
        day_bars = {}
        for t in uni:
            df = intraday.get(t)
            if df is None or df.empty:
                continue
            today = df[df.index.normalize() == day]
            if today.empty:
                continue
            sess = today[(today.index.time >= OR_RANGE_START)
                         & (today.index.time <= ORB_SIGNAL_END)]
            if len(sess) < 4:
                continue
            prior = df[df.index.normalize() < day]
            if prior.empty:
                continue
            prev_close = float(prior.iloc[-1]["close"])
            if prev_close <= 0:
                continue
            first = sess.iloc[0]
            open_p = float(first["open"])
            S["ticker_days"] += 1
            by_year[yr]["ticker_days"] += 1

            gap_pct = abs(open_p - prev_close) / prev_close
            if gap_pct < ENGINE_GAP_PREFILTER:
                continue
            S["pass_gap_prefilter"] += 1
            by_year[yr]["pass_gap_prefilter"] += 1

            # prior 20-day opening-bar volume -> scanner's avg_daily_volume
            popen = prior[prior.index.time == OR_RANGE_START]["volume"].tail(20)
            avg_open_vol = int(popen.mean()) if len(popen) else int(first["volume"])
            # prior 20-day per-slot volume -> rvol at signal time
            last20 = sorted(prior.index.normalize().unique())[-20:]
            rec = prior[prior.index.normalize().isin(last20)]
            avg_by_time = (rec.groupby(rec.index.time)["volume"].mean().to_dict()
                           if not rec.empty else {})

            candidates.append({
                "ticker": t,
                "prev_close": prev_close,
                "open_price": open_p,
                "premarket_volume": 0,          # cache holds no premarket here
                "avg_daily_volume": max(avg_open_vol * 78, 1),
                "opening_5min_volume": int(first["volume"]),
            })
            day_bars[t] = (sess, avg_by_time)

        if not candidates:
            continue

        orb.reset()
        try:
            watch = orb.run_scanner(candidates)
        except Exception:
            continue
        S["pass_scanner"] += len(watch)
        by_year[yr]["pass_scanner"] += len(watch)

        for t in watch:
            if t not in day_bars:
                continue
            sess, avg_by_time = day_bars[t]

            # OR forms 09:30 -> 09:45 (exclusive), same as the engine.
            or_bars = sess[sess.index.time < ORB_SIGNAL_START]
            if len(or_bars) < 2:
                continue
            atr = compute_atr(or_bars)
            try:
                or_high, or_low, status = orb.calculate_opening_range(or_bars, atr)
            except Exception:
                continue
            if status != "VALID":
                continue
            S["or_valid"] += 1
            by_year[yr]["or_valid"] += 1

            # Signal window 09:45..10:15
            sig_bars = sess[(sess.index.time >= ORB_SIGNAL_START)
                            & (sess.index.time <= ORB_SIGNAL_END)]
            if sig_bars.empty:
                continue

            fired = False
            for i in range(len(sig_bars)):
                if fired:
                    break     # one breakout per ticker-day, as pending_orb enforces
                bar = sig_bars.iloc[i]
                slot_avg = avg_by_time.get(sig_bars.index[i].time(), 0.0)
                hist = max(slot_avg if slot_avg > 0 else float(sess["volume"].mean()), 1.0)
                rvol = orb.calculate_intraday_rvol(int(bar["volume"]), hist)
                # VWAP over the session so far, as the engine does
                sofar = sess.loc[:sig_bars.index[i]]
                tp = (sofar["high"] + sofar["low"] + sofar["close"]) / 3
                vwap = float((tp * sofar["volume"]).sum() / max(sofar["volume"].sum(), 1))
                try:
                    sig = orb.generate_signal(bar, or_high, or_low, vwap, rvol, "Normal")
                except Exception:
                    sig = None
                if not sig:
                    continue

                fired = True
                S["breakout"] += 1
                by_year[yr]["breakout"] += 1
                if sig.get("is_fakeout"):
                    S["breakout_fakeout"] += 1
                    by_year[yr]["breakout_fakeout"] += 1

                # B+1 confirmation — the engine's actual ORB entry condition
                if i + 1 < len(sig_bars):
                    nxt = sig_bars.iloc[i + 1]
                    held = (float(nxt["close"]) > or_high if sig["direction"] == "LONG"
                            else float(nxt["close"]) < or_low)
                    if held and not sig.get("is_fakeout"):
                        S["confirm"] += 1
                        by_year[yr]["confirm"] += 1
                    elif not held:
                        S["reverted_to_fade"] += 1
                        by_year[yr]["reverted_to_fade"] += 1

                # retest proxy (upper bound)
                for tol in RETEST_TOLERANCES:
                    if retest_hit(sig_bars, i, sig["direction"], or_high, or_low, tol):
                        retest_by_tol[tol]["hit"] += 1
                        retest_by_tol[tol][f"y{yr}"] += 1
                        if tol == RETEST_TOLERANCES[-1]:
                            for j in range(i + 1, min(i + 1 + RETEST_MAX_BARS, len(sig_bars))):
                                retest_bar_idx.append(j - i)
                                break

    # ── report ───────────────────────────────────────────────────────────────
    lines: list = []

    def P(s=""):
        print(s)
        lines.append(s)

    P("\n" + "=" * 78)
    P("FUNNEL")
    P("=" * 78)
    stages = [
        ("days with an ORB universe", "days_with_universe"),
        ("ticker-days examined", "ticker_days"),
        ("pass engine 0.5% gap pre-filter", "pass_gap_prefilter"),
        ("pass ORB scanner (gap/price/vol)", "pass_scanner"),
        ("opening range VALID", "or_valid"),
        ("BREAKOUT (dir + RVol>=2.0)", "breakout"),
        ("  of which fakeout-marked", "breakout_fakeout"),
        ("CONFIRM on B+1 (= ORB entry)", "confirm"),
        ("reverted inside OR (-> FADE, dropped)", "reverted_to_fade"),
    ]
    # Percentages chain from ticker_days onward. "days with universe" is a
    # different unit (days, not ticker-days) so it is excluded from the chain.
    prev = None
    for label, k in stages:
        v = S[k]
        pct = ""
        is_sub = label.startswith("  ")
        if prev not in (None, 0) and not is_sub and k != "ticker_days":
            pct = f"  ({100.0 * v / prev:5.1f}% of prev)"
        P(f"  {label:<40} {v:>8,}{pct}")
        if not is_sub and k != "days_with_universe":
            prev = v

    P("\n  RETEST PROXY (OPTIMISTIC upper bound — 4 bars here = 20 minutes of")
    P("  lookahead; the spec's 4 bars at 1-min = 4 minutes. Expect the real")
    P("  1-minute count to be materially lower, plausibly ~half.)")
    for tol in RETEST_TOLERANCES:
        h = retest_by_tol[tol]["hit"]
        rate = 100.0 * h / S["breakout"] if S["breakout"] else 0.0
        P(f"    tolerance {tol * 100:.2f}%   {h:>6,} of {S['breakout']:,} breakouts"
          f"  ({rate:.1f}%)")

    P("\n  PER YEAR")
    P(f"    {'year':<6}{'ticker-days':>12}{'scanner':>9}{'OR ok':>8}"
      f"{'breakout':>10}{'confirm':>9}")
    for y in sorted(by_year):
        c = by_year[y]
        P(f"    {y:<6}{c['ticker_days']:>12,}{c['pass_scanner']:>9,}"
          f"{c['or_valid']:>8,}{c['breakout']:>10,}{c['confirm']:>9,}")

    # ── self-checks ──────────────────────────────────────────────────────────
    P("\n" + "=" * 78)
    P("SELF-CHECKS")
    P("=" * 78)
    ok = True

    order = ["ticker_days", "pass_gap_prefilter", "pass_scanner",
             "or_valid", "breakout", "confirm"]
    mono = all(S[order[i]] >= S[order[i + 1]] for i in range(len(order) - 1))
    P(f"  1. funnel monotonic                 : {'PASS' if mono else 'FAIL'}")
    ok &= mono

    conf_is = sum(by_year[y]["confirm"] for y in by_year if 2017 <= y <= 2022)
    # The >=80 assertion is only meaningful when the run actually spans the
    # period those 80 trades came from. On a partial window it would fail for
    # the trivial reason that fewer days were walked — that is a false alarm,
    # not a replication failure, so it is reported as N/A instead.
    covers_is = (pd.Timestamp(a.start) <= pd.Timestamp("2017-04-05")
                 and pd.Timestamp(a.end) >= pd.Timestamp("2022-12-31"))
    if covers_is:
        superset = conf_is >= KNOWN_ORB_TRADES_2017_2022
        P(f"  2. CONFIRM(2017-2022)={conf_is} >= {KNOWN_ORB_TRADES_2017_2022} real ORB trades"
          f"  : {'PASS' if superset else 'FAIL'}")
        if not superset:
            P("     -> this funnel omits gates the engine APPLIES, so it must")
            P("        overcount. A count below the realised 80 means the")
            P("        replication is broken — do NOT read the numbers above.")
        ok &= superset
    else:
        superset = False
        P(f"  2. CONFIRM(2017-2022)={conf_is} vs {KNOWN_ORB_TRADES_2017_2022} real"
          f"  : N/A (window does not span 2017-2022)")
        P("     -> the calibration below needs the full span. Rerun without")
        P("        --start/--end to get a usable estimate.")

    rt_ok = all(retest_by_tol[t]["hit"] <= S["breakout"] for t in RETEST_TOLERANCES)
    idx_ok = (not retest_bar_idx) or (1 <= min(retest_bar_idx)
                                      and max(retest_bar_idx) <= RETEST_MAX_BARS)
    P(f"  3. retest <= breakout and in-window : "
      f"{'PASS' if (rt_ok and idx_ok) else 'FAIL'}")
    ok &= rt_ok and idx_ok

    # The three tolerances collapsing to the same count is itself diagnostic:
    # at 5-minute resolution the bars are wide enough that 0.10% and 0.30%
    # select the same events. The spec's tolerance grid is unresolvable here —
    # further evidence that resolution, not parameter choice, is the blocker.
    tol_counts = {t: retest_by_tol[t]["hit"] for t in RETEST_TOLERANCES}
    if len(set(tol_counts.values())) == 1 and S["breakout"]:
        P(f"\n  NOTE: all three retest tolerances return the same count "
          f"({list(tol_counts.values())[0]}).")
        P("  At 5-min resolution 0.10% and 0.30% are not distinguishable — the")
        P("  spec's tolerance grid cannot be tested on this data at all.")

    if conf_is and superset:
        factor = KNOWN_ORB_TRADES_2017_2022 / conf_is
        P(f"\n  Calibration: the omitted gates (Normal-only regime, VIX<25,")
        P(f"  SPY bull trend, position caps) collectively pass "
          f"{100 * factor:.1f}% of")
        P(f"  confirmed breakouts ({KNOWN_ORB_TRADES_2017_2022}/{conf_is}).")
        # Report the years actually WALKED, not the requested window. The
        # 5-min cache does not necessarily cover the whole request (the ORB
        # pool stops at 2022), and labelling a 6-year result as 7.5 years
        # would overstate the per-year rate by 25%.
        yrs_walked = sorted(y for y in by_year if by_year[y]["ticker_days"])
        span = len(yrs_walked)
        P(f"\n  Years actually walked: {yrs_walked[0]}-{yrs_walked[-1]} "
          f"({span} years of data present in the cache)")
        if span < len(range(int(a.start[:4]), int(a.end[:4]) + 1)):
            P(f"  NOTE: requested {a.start[:4]}-{a.end[:4]} but the 5-min cache")
            P("  has no bars for the missing years — rates below are per the")
            P("  years walked, not the requested window.")
        for tol in RETEST_TOLERANCES:
            est = retest_by_tol[tol]["hit"] * factor
            P(f"    tol {tol * 100:.2f}% -> n ~ {est:,.0f} over {span}y "
              f"= {est / span:,.1f}/year")

    P("\n" + "=" * 78)
    P("VERDICT INPUT")
    P("=" * 78)
    P("  Read the calibrated n above, not the raw breakout count.")
    P("  n >= ~200 : a 1-minute pull can support the spec's bootstrap +")
    P("              year x direction x regime breakdown. Buying data is sound.")
    P("  n ~ 80-200: bootstrap is possible; the requested breakdowns will have")
    P("              empty cells. Narrow the spec before buying.")
    P("  n <  ~80  : sample-limited regardless of data source. 1-minute bars")
    P("              would make the strategy VISIBLE but still not TESTABLE.")
    P("              Verdict stays INSUFFICIENT DATA — do not buy.")
    P("")
    P("  Note for whatever runs next: the engine activates ORB in Normal ONLY")
    P("  (_REGIME_STRATEGIES). The spec's Calm and Stress arms would be empty")
    P("  under engine-faithful conditions.")
    P(f"\n  elapsed: {(datetime.now() - t0).total_seconds():.0f}s")
    P("=" * 78)

    if a.out:
        Path(a.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"\nreport written: {a.out}")

    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
