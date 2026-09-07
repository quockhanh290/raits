"""
ORB_RETEST_SCALP — does waiting for a retest beat chasing the breakout?
(RESEARCH ONLY — raits/raits/scripts/research/. Imports production classes
read-only; modifies nothing outside this directory and its own outputs.)

THE QUESTION
------------
Current ORB: breakout on bar B, confirm on B+1, enter.
Tested here:  breakout on bar B, wait for price to retest the OR boundary,
              enter only if the boundary holds.

Both arms fire off the SAME breakout events, so the comparison is PAIRED —
every setup produces an R for each rule and the statistic is the difference.
That matters: at n in the low hundreds a paired test has far lower variance
than two independent samples, and it is the question the spec called primary
("does retest improve ORB execution?"), not whether the strategy wins outright.

PRE-COMMITTED BEFORE ANY P&L WAS SEEN
-------------------------------------
Universe   top_n=25 from the point-in-time ORBUniverseScanner.
           Primary   = C+O   (common stock + foreign ordinary), 273 names.
           Robustness= C+O+A (adds ADRs), 289 names.
           ETFs/ETNs, preferreds, warrants, units, MLPs, CEFs and royalty
           trusts excluded — 55% of the nominal pool, nearly half of it ETFs.
           The scanner ranks on gap FREQUENCY and leveraged ETFs gap by
           construction, so it selected them systematically. Bias in the rule,
           not noise in the data.
Grid       6 combinations: retest window {2,3,4} bars x tolerance {0.20%, 0.30%}.
           The spec's full grid was 3x3x2x2x4x3 = 432, which at this n is
           guaranteed overfitting and which the spec itself forbids.
           The 0.10% tolerance arm is DROPPED: measured feed residual at p95 is
           0.85% in-band, so a 0.10% band is finer than the data's own error.
Fixed      confirmation A (close > open), stop B (other side of the OR plus a
           buffer), target 1.5R, time stop 10 minutes. Chosen a priori.
Costs      2 bps and 5 bps per side. Gross and net both reported.
Stats      10,000-resample bootstrap on the PAIRED difference, 95% CI,
           P(mean difference <= 0).
Breakdown  LONG/SHORT and year only. Ticker and time-bucket cells would hold
           under two trades each.

KNOWN DEVIATIONS — read before quoting any number
-------------------------------------------------
1. REGIME IS NOT APPLIED. The engine activates ORB in Normal only
   (_REGIME_STRATEGIES), but faithful HMM labels for 2023-2026 do not exist:
   the equity HMM is fit on a SPY history that this project's data does not
   cover end to end, and inventing a proxy would silently change the gate.
   Results therefore MIX regimes and are not directly comparable to the
   engine's 2017-2022 ORB numbers. Pass --regime-csv to apply a real label
   series if one becomes available.
2. MERGED open/close ARE APPROXIMATE. Across venues, high=max and low=min are
   exact; open and close are taken from one venue's bar within the minute
   because OHLCV carries no trade timestamps. The retest trigger tests `low`
   against the boundary (exact); the `close` confirmation is approximate.
3. Bars come from 5 lit venues, which measured a 0.0135% median / 0.85% p95
   residual against a consolidated reference on in-band names. Off-exchange
   prints are absent by construction.

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\orb_retest_scalp_test.py
    python raits\\raits\\scripts\\research\\orb_retest_scalp_test.py --universe COA
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[3]
for p in (str(_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from raits.strategies.orb import ORBStrategy                       # noqa: E402
from orb_universe_sizing_databento import (                        # noqa: E402
    vectorised_scores, select_topn, MIN_PRICE, MAX_PRICE, MAX_REAL_GAP,
)

RESEARCH = _ROOT / "raits" / "data" / "cache" / "research_daily"
BARS = _ROOT / "raits" / "data" / "cache" / "orb_1min" / "_consolidated_1m.parquet"
DAILY = RESEARCH / "databento_ohlcv1d.parquet"
CLASS = RESEARCH / "universe_classification.parquet"

TOP_N = 25
OR_START, OR_END = "09:30", "09:45"      # OR forms 09:30 up to (not incl.) 09:45
SIG_END = "10:15"                        # breakout window closes
HARD_END = "10:45"                       # data ends here

RETEST_WINDOWS = (2, 3, 4)               # bars after the breakout bar
TOLERANCES = (0.0020, 0.0030)            # 0.10% dropped: below the feed's own p95 error
TARGET_R = 1.5
TIME_STOP_MIN = 10
STOP_BUFFER = 0.0010                     # stop variant B: 0.10% beyond the OR boundary
RVOL_MIN = 2.0
COSTS_BPS = (2.0, 5.0)
N_BOOT = 10_000
SEED = 42

EXCLUDE_PRIMARY = {"Q", "P", "S", "L", "W", "U", "V", "A"}   # C+O
EXCLUDE_ROBUST = {"Q", "P", "S", "L", "W", "U", "V"}         # C+O+A


# ──────────────────────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────────────────────

def load_universe_by_day(exclude: set) -> dict:
    """Rebuild the point-in-time daily universe with the SAME vectorised
    scorer that --verify-scanner proved identical to ORBUniverseScanner."""
    d = pd.read_parquet(DAILY).reset_index()
    tc = next(c for c in ("ts_event", "index", "date") if c in d.columns)
    d["date"] = pd.to_datetime(d[tc]).dt.tz_localize(None).dt.normalize()
    d = d.sort_values(["symbol", "date"])
    d["prev_close"] = d.groupby("symbol")["close"].shift(1)
    d = d[d["prev_close"] > 0]
    d["gap"] = (d["open"] - d["prev_close"]).abs() / d["prev_close"]
    d = d[(d["close"] >= MIN_PRICE) & (d["close"] <= MAX_PRICE)
          & (d["gap"] <= MAX_REAL_GAP)]

    cnt = d.groupby("symbol").size()
    pool = sorted(cnt[cnt >= 100].index.astype(str))

    cls = pd.read_parquet(CLASS)
    sc = "raw_symbol" if "raw_symbol" in cls.columns else "symbol"
    types = dict(zip(cls[sc].astype(str), cls["security_type"].astype(str)))
    pool = [s for s in pool if types.get(s) not in exclude]

    pool_ix = {s: i for i, s in enumerate(pool)}
    scores = vectorised_scores(
        d[d["symbol"].isin(pool)][["symbol", "date", "open", "high", "low",
                                   "close", "volume"]], pool_ix)
    by_day = {k: g for k, g in scores.groupby("date")}
    dates = sorted(d["date"].unique())
    empty = scores.iloc[0:0]
    # T-1 selection: the universe for day i is ranked on data through day i-1.
    return ({pd.Timestamp(dates[i]): select_topn(
        by_day.get(dates[i - 1], empty), TOP_N) for i in range(1, len(dates))},
        len(pool))


def load_bars() -> pd.DataFrame:
    b = pd.read_parquet(BARS)
    b["ts"] = pd.to_datetime(b["ts"])
    b["date"] = b["ts"].dt.normalize()
    b["t"] = b["ts"].dt.strftime("%H:%M")
    return b.sort_values(["symbol", "ts"])


# ──────────────────────────────────────────────────────────────────────────────
# Simulation
# ──────────────────────────────────────────────────────────────────────────────

def _atr(bars: pd.DataFrame, period: int = 14) -> float:
    """Mirrors BacktestEngine._compute_atr."""
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"] - bars["close"].shift(1)).abs()
    tr = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def _walk(bars: pd.DataFrame, i0: int, direction: str, entry: float,
          stop: float, target: float, minutes: int) -> tuple:
    """Walk forward from bar i0 (already entered) to stop / target / time stop.

    Stop is checked BEFORE target within a bar. When a single bar spans both,
    the true order is unknown at 1-minute resolution, and assuming the target
    first would flatter the strategy. The pessimistic choice is the honest one.
    """
    for j in range(i0, min(i0 + minutes, len(bars))):
        b = bars.iloc[j]
        if direction == "LONG":
            if float(b["low"]) <= stop:
                return stop, "STOP", j
            if float(b["high"]) >= target:
                return target, "TARGET", j
        else:
            if float(b["high"]) >= stop:
                return stop, "STOP", j
            if float(b["low"]) <= target:
                return target, "TARGET", j
    j = min(i0 + minutes, len(bars)) - 1
    return float(bars.iloc[j]["close"]), "TIME", j


def find_breakout(day, ticker, bars, orb, hist_slot_vol):
    """Breakout detection + ARM A. Neither depends on (window, tol), so this
    runs ONCE per ticker-day and all six grid combinations reuse it. Detecting
    the breakout inside the grid loop would repeat identical work six times."""
    sess = bars[bars["t"] <= HARD_END]
    if len(sess) < 20:
        return None
    or_bars = sess[sess["t"] < OR_END]
    if len(or_bars) < 5:
        return None
    try:
        or_high, or_low, status = orb.calculate_opening_range(or_bars, _atr(or_bars))
    except Exception:
        return None
    if status != "VALID":
        return None

    sig = sess[(sess["t"] >= OR_END) & (sess["t"] <= SIG_END)].reset_index(drop=True)
    if len(sig) < 5:
        return None

    # Running VWAP over the whole session so far — computed once, not re-summed
    # per candidate bar (that inner re-slice was O(n^2) per ticker-day).
    tp = (sess["high"] + sess["low"] + sess["close"]) / 3
    cum_pv = (tp * sess["volume"]).cumsum()
    cum_v = sess["volume"].cumsum().clip(lower=1)
    vwap_by_ts = dict(zip(sess["ts"], cum_pv / cum_v))
    mean_vol = float(sess["volume"].mean())

    bo = None
    for i in range(len(sig)):
        bar = sig.iloc[i]
        slot = hist_slot_vol.get(bar["t"], 0.0)
        hist = max(slot if slot > 0 else mean_vol, 1.0)
        rvol = orb.calculate_intraday_rvol(int(bar["volume"]), hist)
        vwap = float(vwap_by_ts.get(bar["ts"], bar["close"]))
        s = orb.generate_signal(bar, or_high, or_low, vwap, rvol, "Normal")
        if s and not s.get("is_fakeout"):
            bo = (i, s, vwap, rvol)
            break
    if bo is None:
        return None
    i, s, vwap, rvol = bo
    direction = s["direction"]

    # ── ARM A: ORB as the engine trades it — confirm on B+1, fill next open ──
    a = None
    if i + 2 < len(sig):
        c = sig.iloc[i + 1]
        held = (float(c["close"]) > or_high if direction == "LONG"
                else float(c["close"]) < or_low)
        if held:
            e = float(sig.iloc[i + 2]["open"])
            st = min(or_low, vwap) if direction == "LONG" else max(or_high, vwap)
            risk = abs(e - st)
            if risk > 0:
                tg = e + TARGET_R * risk if direction == "LONG" else e - TARGET_R * risk
                px, why, j = _walk(sig, i + 2, direction, e, st, tg, TIME_STOP_MIN)
                a = dict(entry=e, stop=st, risk=risk, exit=px, why=why,
                         bars_held=j - (i + 2) + 1)

    return dict(date=day, ticker=ticker, direction=direction, rvol=rvol,
                or_high=or_high, or_low=or_low, arm_a=a, sig=sig, i=i)


def find_retest(rec, window, tol):
    """ARM B for one (window, tol). Same breakout bar as ARM A by construction."""
    sig, i, direction = rec["sig"], rec["i"], rec["direction"]
    or_high, or_low = rec["or_high"], rec["or_low"]
    bound = or_high if direction == "LONG" else or_low
    b = None
    for k in range(i + 1, min(i + 1 + window, len(sig))):
        r = sig.iloc[k]
        if direction == "LONG":
            touched = float(r["low"]) <= bound * (1 + tol)
            held = float(r["close"]) > or_high
            confirm = float(r["close"]) > float(r["open"])     # variant A
        else:
            touched = float(r["high"]) >= bound * (1 - tol)
            held = float(r["close"]) < or_low
            confirm = float(r["close"]) < float(r["open"])
        if not (touched and held and confirm):
            continue
        if k + 1 >= len(sig):
            break
        e = float(sig.iloc[k + 1]["open"])
        # stop variant B: just the other side of the OR boundary
        st = (bound * (1 - STOP_BUFFER) if direction == "LONG"
              else bound * (1 + STOP_BUFFER))
        risk = abs(e - st)
        if risk <= 0:
            break
        tg = e + TARGET_R * risk if direction == "LONG" else e - TARGET_R * risk
        px, why, j = _walk(sig, k + 1, direction, e, st, tg, TIME_STOP_MIN)
        b = dict(entry=e, stop=st, risk=risk, exit=px, why=why,
                 bars_held=j - (k + 1) + 1, wait=k - i)
        break
    return b


def _r(arm, direction, bps):
    if arm is None:
        return np.nan
    sgn = 1.0 if direction == "LONG" else -1.0
    gross = sgn * (arm["exit"] - arm["entry"])
    cost = (arm["entry"] + arm["exit"]) * bps / 10_000.0
    return (gross - cost) / arm["risk"]


def _pct(arm, direction, bps):
    """Net return as a percentage of entry price.

    R is NOT comparable across the two arms here: measured risk distance is
    ~3.07% for the ORB arm (stop = min(or_low, vwap)) against ~0.52% for the
    retest arm (stop just beyond the OR boundary). Dividing each arm's P&L by
    its own six-times-different denominator makes 'R' mean two different
    things, so the same comparison is also run on a common denominator.
    """
    if arm is None:
        return np.nan
    sgn = 1.0 if direction == "LONG" else -1.0
    gross = sgn * (arm["exit"] - arm["entry"])
    cost = (arm["entry"] + arm["exit"]) * bps / 10_000.0
    return 100.0 * (gross - cost) / arm["entry"]


# ──────────────────────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────────────────────

def bootstrap(x: np.ndarray, n_boot=N_BOOT, seed=SEED):
    x = x[~np.isnan(x)]
    if len(x) < 5:
        return None
    rng = np.random.default_rng(seed)
    m = rng.choice(x, size=(n_boot, len(x)), replace=True).mean(axis=1)
    return dict(n=len(x), mean=float(x.mean()),
                lo=float(np.percentile(m, 2.5)), hi=float(np.percentile(m, 97.5)),
                p_le0=float((m <= 0).mean()))


def describe(rs: np.ndarray, label: str):
    rs = rs[~np.isnan(rs)]
    if not len(rs):
        print(f"  {label:<22} (no trades)")
        return
    wins = rs > 0
    pf_num = rs[wins].sum()
    pf_den = -rs[~wins].sum()
    eq = np.cumsum(rs)
    dd = float((np.maximum.accumulate(eq) - eq).max()) if len(eq) else 0.0
    print(f"  {label:<22}{len(rs):>6}{100 * wins.mean():>8.1f}%"
          f"{rs.mean():>9.3f}{np.median(rs):>9.3f}"
          f"{(pf_num / pf_den if pf_den > 0 else np.inf):>8.2f}{dd:>9.2f}")


# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--universe", choices=["CO", "COA"], default="CO",
                    help="CO = primary (common + ordinary); COA adds ADRs")
    ap.add_argument("--regime-csv", default=None,
                    help="optional date,regime CSV; without it NO regime gate is applied")
    a = ap.parse_args()

    print("=" * 78)
    print("ORB_RETEST_SCALP — paired test vs the ORB confirmation rule")
    print("=" * 78)
    if not BARS.exists():
        print(f"  Missing {BARS}\n  Run orb_fetch_1min_databento.py --consolidate first.")
        return

    exclude = EXCLUDE_PRIMARY if a.universe == "CO" else EXCLUDE_ROBUST
    print(f"  universe : {a.universe}  (exclude security_type {sorted(exclude)})")
    print(f"  top_n    : {TOP_N}")
    if a.regime_csv:
        reg = pd.read_csv(a.regime_csv)
        reg["date"] = pd.to_datetime(reg["date"]).dt.normalize()
        regime = dict(zip(reg["date"], reg["regime"].astype(str)))
        print(f"  regime   : {a.regime_csv} — Normal only")
    else:
        regime = None
        print("  regime   : NOT APPLIED — results mix regimes (see docstring)")

    uni_by_day, pool_n = load_universe_by_day(exclude)
    print(f"  pool     : {pool_n:,} symbols after exclusion")
    bars = load_bars()
    print(f"  bars     : {len(bars):,} rows, {bars['symbol'].nunique():,} symbols, "
          f"{bars['date'].nunique():,} days")

    by_sym = {s: g for s, g in bars.groupby("symbol")}
    orb = ORBStrategy()

    # Prior-20-day volume by minute-of-day, for RVol at signal time.
    slot = {}
    for s, g in by_sym.items():
        piv = g.pivot_table(index="date", columns="t", values="volume", aggfunc="sum")
        slot[s] = piv.rolling(20, min_periods=5).mean().shift(1)

    print(f"\n  grid: windows {RETEST_WINDOWS} x tolerances "
          f"{[f'{t:.2%}' for t in TOLERANCES]} = "
          f"{len(RETEST_WINDOWS) * len(TOLERANCES)} combinations\n")

    # Position index per (symbol, date) so a day's bars are an iloc slice.
    # Boolean-masking the symbol's whole 64k-row frame once per ticker-day was
    # the other O(n^2): 126k scans of 64k rows.
    bounds = {}
    for s, g in by_sym.items():
        dd = g["date"].values
        edges = np.searchsorted(dd, np.unique(dd), side="left")
        ends = np.append(edges[1:], len(dd))
        for dt, i0, i1 in zip(np.unique(dd), edges, ends):
            bounds[(s, pd.Timestamp(dt))] = (i0, i1)

    print("  detecting breakouts (once; the grid reuses them) ...", flush=True)
    breakouts = []
    for day, tickers in uni_by_day.items():
        if regime is not None and regime.get(day) != "Normal":
            continue
        for t in tickers:
            g = by_sym.get(t)
            if g is None:
                continue
            rng = bounds.get((t, day))
            if rng is None:
                continue
            d = g.iloc[rng[0]:rng[1]]
            if d.empty:
                continue
            sv = slot.get(t)
            hv = (sv.loc[day].to_dict()
                  if sv is not None and day in sv.index else {})
            r = find_breakout(day, t, d, orb, hv)
            if r:
                breakouts.append(r)
    n_a = sum(1 for r in breakouts if r["arm_a"])
    print(f"  breakouts {len(breakouts):,}  |  ORB arm filled {n_a:,}")

    results = {}
    for window in RETEST_WINDOWS:
        for tol in TOLERANCES:
            recs = []
            for r in breakouts:
                b = find_retest(r, window, tol)
                recs.append({**{k: v for k, v in r.items() if k not in ("sig", "i")},
                             "arm_b": b})
            results[(window, tol)] = recs
            n_b = sum(1 for r in recs if r["arm_b"])
            n_both = sum(1 for r in recs if r["arm_a"] and r["arm_b"])
            print(f"  window={window} tol={tol:.2%}: retest {n_b:>4}, "
                  f"paired {n_both:>4}")

    # ── report ──────────────────────────────────────────────────────────────
    for bps in COSTS_BPS:
        print("\n" + "=" * 78)
        print(f"RESULTS @ {bps:.0f} bps per side")
        print("=" * 78)
        print(f"  {'combo / arm':<22}{'n':>6}{'win%':>8}{'meanR':>9}"
              f"{'medR':>9}{'PF':>8}{'maxDD':>9}")
        for key, recs in results.items():
            w, tol = key
            both = [r for r in recs if r["arm_a"] and r["arm_b"]]
            if not both:
                continue
            ra = np.array([_r(r["arm_a"], r["direction"], bps) for r in both])
            rb = np.array([_r(r["arm_b"], r["direction"], bps) for r in both])
            print(f"\n  -- window={w} tol={tol:.2%}  (paired n={len(both)}) --")
            describe(ra, "ORB (confirm B+1)")
            describe(rb, "RETEST")
            diff = rb - ra
            bs = bootstrap(diff)
            if bs:
                print(f"  paired diff (retest - ORB): mean {bs['mean']:+.3f}R  "
                      f"95% CI [{bs['lo']:+.3f}, {bs['hi']:+.3f}]  "
                      f"P(diff<=0) = {bs['p_le0']:.3f}")
            # Same comparison on a common denominator — see _pct().
            pa = np.array([_pct(r["arm_a"], r["direction"], bps) for r in both])
            pb = np.array([_pct(r["arm_b"], r["direction"], bps) for r in both])
            bsp = bootstrap(pb - pa)
            if bsp:
                print(f"  paired diff, %-of-entry     : mean {bsp['mean']:+.4f}%  "
                      f"95% CI [{bsp['lo']:+.4f}, {bsp['hi']:+.4f}]  "
                      f"P(diff<=0) = {bsp['p_le0']:.3f}")
            sa, sb = bootstrap(pa), bootstrap(pb)
            if sa and sb:
                print(f"  standalone %-of-entry       : ORB {sa['mean']:+.4f}% "
                      f"[{sa['lo']:+.4f},{sa['hi']:+.4f}]   "
                      f"RETEST {sb['mean']:+.4f}% "
                      f"[{sb['lo']:+.4f},{sb['hi']:+.4f}]  "
                      f"P(retest<=0) = {sb['p_le0']:.3f}")
            ea = np.nanmean([abs(r["arm_a"]["entry"] - r["arm_a"]["stop"])
                             / r["arm_a"]["entry"] for r in both])
            eb = np.nanmean([abs(r["arm_b"]["entry"] - r["arm_b"]["stop"])
                             / r["arm_b"]["entry"] for r in both])
            print(f"  avg risk distance: ORB {100 * ea:.3f}%  retest {100 * eb:.3f}%")
            for arm, lbl in ((("arm_a"), "ORB"), (("arm_b"), "RETEST")):
                whys = pd.Series([r[arm]["why"] for r in both]).value_counts()
                held = np.mean([r[arm]["bars_held"] for r in both])
                print(f"  {lbl:<8} exits: "
                      + ", ".join(f"{k} {100 * v / len(both):.0f}%"
                                  for k, v in whys.items())
                      + f"   mean hold {held:.1f} min")

    # ── stability + breakdowns on the middle combo ──────────────────────────
    print("\n" + "=" * 78)
    print("PARAMETER STABILITY (paired mean diff, 2 bps)")
    print("=" * 78)
    print(f"  {'':<10}" + "".join(f"{f'tol {t:.2%}':>14}" for t in TOLERANCES))
    for w in RETEST_WINDOWS:
        row = f"  win {w:<6}"
        for tol in TOLERANCES:
            both = [r for r in results[(w, tol)] if r["arm_a"] and r["arm_b"]]
            if not both:
                row += f"{'-':>14}"
                continue
            d = np.array([_r(r["arm_b"], r["direction"], 2.0)
                          - _r(r["arm_a"], r["direction"], 2.0) for r in both])
            row += f"{np.nanmean(d):>+13.3f}R"
        print(row)
    print("\n  A single positive cell is not evidence. The spec's bar is that")
    print("  NEIGHBOURING parameter values are positive too — read the block,")
    print("  not the best number in it.")

    mid = (RETEST_WINDOWS[1], TOLERANCES[0])
    both = [r for r in results[mid] if r["arm_a"] and r["arm_b"]]
    if both:
        print("\n" + "=" * 78)
        print(f"BREAKDOWN — window={mid[0]} tol={mid[1]:.2%}, 2 bps")
        print("=" * 78)
        df = pd.DataFrame([{
            "year": r["date"].year, "dir": r["direction"],
            "diff": _r(r["arm_b"], r["direction"], 2.0)
                    - _r(r["arm_a"], r["direction"], 2.0)} for r in both])
        for key in ("dir", "year"):
            print(f"\n  by {key}:")
            g = df.groupby(key)["diff"].agg(["size", "mean", "median"])
            for k, row in g.iterrows():
                print(f"    {str(k):<8}{int(row['size']):>6}"
                      f"{row['mean']:>+9.3f}R{row['median']:>+9.3f}R")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
