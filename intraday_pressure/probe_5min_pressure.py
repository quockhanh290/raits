"""
Intraday Pressure Probe — 5-minute bar proxies for order-flow pressure.
(EXPERIMENTAL harness, intraday_pressure/)  — RESEARCH ONLY. Costs $0.

WHY THIS EXISTS
───────────────────────────────────────────────────────────────────────────
True order-flow work (footprint imbalance, DOM/book imbalance) needs tick and
order-book data this project does not own. Measured holding periods show the
system has no scalper-horizon strategy either:

    STRESS_MID 152 min · STRESS_ORB 158 min · GF_SHORT 180 min
    ORB 350 min · PE_SHORT 1825 min · TREND_FOLLOW 6925 min

There is a gap at 5-30 minutes that no strategy occupies, and the data to test
it is already on disk (window_debug_5min.pkl: 75 tickers, 2017-01 .. 2024-12,
79 bars/day, with OHLCV + vwap + transactions).

WHAT THIS CAN AND CANNOT DO — read before interpreting anything
───────────────────────────────────────────────────────────────────────────
CANNOT:
  - book/DOM imbalance: bars contain no order book. Not approximable.
  - queue position / passive-fill simulation: needs order IDs.
  - scalper horizons (10-60 s): a bar is 300 s.
These are absent, not merely coarse. A null here does NOT close the
order-flow question, because bars destroy the microstructure the hypothesis
is about. A positive here does not prove the fine-grained version works either
— it only justifies paying for tick data.

CAN: bar-level proxies for "who won the bar"
  close_pos      (C-L)/(H-L)          where the close sits in the bar's range
  vwap_dev       (C-VWAP)/VWAP        did buyers press into the close
  avg_trade_sz   volume/transactions  large prints = institutional participation
                                      (the closest thing to order flow a bar has)
  rvol           volume / trailing-20-bar mean volume

COST HURDLE (the real gate, not statistical significance)
───────────────────────────────────────────────────────────────────────────
Round trip on a penny-spread mega-cap, taker:
    spread crossed  $0.010
    commission x2   $0.007   (IBKR tiered ~$0.0035/share)
    SEC/TAF         $0.0002
    ------------------------------
    TOTAL          ~$0.017/share

PRE-COMMITTED PASS/FAIL, fixed before any number was looked at:
    The top signal decile must show a median forward return, same-day, of
    > $0.034/share GROSS  (= 2x the round-trip cost, i.e. net > $0.017)
    at a horizon of at least 2 bars (10 min).
    Below that -> the branch closes; no strategy can be built on it.

  This is a judgment floor for this study, not a published benchmark.

STATISTICS — deliberately NOT p-value driven
───────────────────────────────────────────────────────────────────────────
There are ~4M bar observations here. Every effect will be "significant"; that
number carries no information. Two consequences, both enforced below:
  1. The decision is read off ECONOMIC MAGNITUDE in cents per share.
  2. Uncertainty is expressed with a DAY-LEVEL block bootstrap, because
     overlapping forward windows and same-day bars are heavily autocorrelated
     and event-level resampling would be meaningless.

Robustness checks are the ones that downgraded the auction-imbalance study:
per-ticker jackknife, per-year breakdown, and a held-out sample.

  IS  : 2017-2022  (the period the rest of the system was built on)
  OOS : 2023-2024  (5-min data exists but the main system never used it)

Run:
    cd d:\\raits
    python intraday_pressure\\probe_5min_pressure.py
"""

from __future__ import annotations

import os
import pickle
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BARS = os.path.join(REPO, "raits", "data", "cache", "window_debug_5min.pkl")
OUT = os.path.join(HERE, "pressure_probe.parquet")

# Universe: the CANDIDATE_POOL names, restricted to what the bar file holds.
sys.path.insert(0, REPO)

HORIZONS = [1, 2, 3, 6]          # bars ahead: 5, 10, 15, 30 minutes
COST_RT = 0.017                  # $/share round trip, taker
GROSS_HURDLE = 2 * COST_RT       # $0.034 — the pre-committed bar
MIN_HORIZON_BARS = 2             # edge must survive to >= 10 min
IS_END = "2022-12-31"
N_BOOT = 2000
SEED = 42

FEATURES = ["close_pos", "vwap_dev", "avg_trade_sz_z", "rvol", "bar_ret"]


def build_panel(bars: dict, tickers: list) -> pd.DataFrame:
    """One row per (ticker, bar) with features and same-day forward returns."""
    frames = []
    for tk in tickers:
        df = bars[tk].copy()
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        need = {"open", "high", "low", "close", "volume", "vwap", "transactions"}
        if not need.issubset(df.columns):
            continue
        d = pd.DataFrame(index=df.index)
        d["ticker"] = tk
        d["date"] = df.index.normalize()
        d["close"] = df["close"]

        rng = (df["high"] - df["low"]).replace(0, np.nan)
        d["close_pos"] = (df["close"] - df["low"]) / rng
        d["vwap_dev"] = (df["close"] - df["vwap"]) / df["vwap"]
        d["bar_ret"] = (df["close"] - df["open"]) / df["open"]

        ats = df["volume"] / df["transactions"].replace(0, np.nan)
        # z-score within ticker against a trailing window — an absolute trade
        # size is meaningless across tickers with different price/lot norms.
        m = ats.rolling(390, min_periods=60).mean()
        s = ats.rolling(390, min_periods=60).std()
        d["avg_trade_sz_z"] = (ats - m) / s.replace(0, np.nan)

        vm = df["volume"].rolling(20, min_periods=10).mean()
        d["rvol"] = df["volume"] / vm.replace(0, np.nan)

        # Forward returns must stay SAME-DAY: crossing the overnight gap would
        # measure the gap, not intraday pressure.
        for h in HORIZONS:
            fwd_close = df["close"].shift(-h)
            fwd_date = pd.Series(df.index.normalize(), index=df.index).shift(-h)
            same_day = fwd_date.eq(d["date"])
            d[f"fwd_{h}"] = np.where(same_day, fwd_close - df["close"], np.nan)
        frames.append(d)
    return pd.concat(frames, ignore_index=False).reset_index(drop=True)


def day_block_ci(vals: np.ndarray, days: np.ndarray, seed=SEED, n=N_BOOT):
    """
    DAY-clustered statistic + bootstrap CI.

    Bars inside a day are heavily autocorrelated and overlapping forward
    windows make it worse, so the unit of resampling must be the DAY. The
    statistic is therefore the median ACROSS per-day medians: each day gets
    one vote regardless of how many bars it contributed, which also stops a
    few high-activity days from dominating.

    Resampling days (O(n_days)) rather than pooled observations (O(n_obs))
    is what makes this tractable at ~4M rows.
    """
    s = pd.Series(vals).groupby(pd.Series(days)).median()
    per_day = s.to_numpy()
    nd = len(per_day)
    if nd < 20:
        return float(np.median(per_day)), np.nan, np.nan
    rng = np.random.default_rng(seed)
    draws = per_day[rng.integers(0, nd, (n, nd))]
    boot = np.median(draws, axis=1)
    return (float(np.median(per_day)),
            float(np.percentile(boot, 2.5)),
            float(np.percentile(boot, 97.5)))


def evaluate(df: pd.DataFrame, feat: str, h: int, label: str, quiet=False):
    """Top/bottom decile of `feat` vs forward return at horizon h, in cents."""
    sub = df[df[feat].notna() & df[f"fwd_{h}"].notna()]
    if len(sub) < 5000:
        return None
    lo, hi = sub[feat].quantile([0.10, 0.90])
    top = sub[sub[feat] >= hi]
    bot = sub[sub[feat] <= lo]
    # LONG the top decile; SHORT the bottom decile. Signed so both are "with signal".
    lv = top[f"fwd_{h}"].values
    bv = -bot[f"fwd_{h}"].values
    both = np.concatenate([lv, bv])
    bothd = np.concatenate([top["date"].values, bot["date"].values])
    med, cl, ch = day_block_ci(both, bothd)
    if not quiet:
        print(f"    {label:<10} h={h}({h * 5:2d}m)  n={len(both):>8,}  "
              f"median={med * 100:+.3f}c  CI[{cl * 100:+.3f},{ch * 100:+.3f}]c  "
              f"net={med * 100 - COST_RT * 100:+.3f}c"
              f"{'   <== clears hurdle' if med >= GROSS_HURDLE else ''}")
    return dict(feature=feat, horizon=h, sample=label, n=len(both),
                median=med, ci_lo=cl, ci_hi=ch, clears=bool(med >= GROSS_HURDLE))


def main() -> None:
    print("=" * 78)
    print("INTRADAY PRESSURE PROBE — 5-min bar proxies  (RESEARCH ONLY, $0)")
    print("=" * 78)
    print(f"  cost round-trip = ${COST_RT:.3f}/share  |  "
          f"PRE-COMMITTED gross hurdle = ${GROSS_HURDLE:.3f}/share "
          f"at h>={MIN_HORIZON_BARS} ({MIN_HORIZON_BARS * 5} min)")

    with open(BARS, "rb") as f:
        bars = pickle.load(f)
    from raits.strategies.universe_scanner import CANDIDATE_POOL
    tickers = [t for t in CANDIDATE_POOL if t in bars]
    print(f"\n  universe: {len(tickers)} tickers with bar data")

    df = build_panel(bars, tickers)
    df["year"] = df["date"].dt.year
    print(f"  panel: {len(df):,} bar-observations, "
          f"{df['date'].nunique():,} days, "
          f"{df['date'].min().date()} .. {df['date'].max().date()}")

    IS = df[df["date"] <= IS_END]
    OOS = df[df["date"] > IS_END]
    print(f"  IS  2017-2022: {len(IS):,} obs on {IS['date'].nunique():,} days")
    print(f"  OOS 2023-2024: {len(OOS):,} obs on {OOS['date'].nunique():,} days")
    print(f"\n  NOTE: with ~{len(df) // 1_000_000}M observations p-values are")
    print("  meaningless — everything is 'significant'. Decision is read off")
    print("  cents/share only. CIs below are DAY-clustered.")

    results = []
    print(f"\n{'=' * 78}")
    print("IN-SAMPLE 2017-2022 — top-decile long / bottom-decile short, in cents")
    print("=" * 78)
    for feat in FEATURES:
        print(f"\n  feature: {feat}")
        for h in HORIZONS:
            r = evaluate(IS, feat, h, "IS")
            if r:
                results.append(r)

    res = pd.DataFrame(results)
    if res.empty:
        print("\n  no evaluable cell. STOP.")
        return

    # ── verdict against the pre-committed hurdle ─────────────────────────
    ok = res[(res["horizon"] >= MIN_HORIZON_BARS) & res["clears"]]
    print(f"\n{'=' * 78}")
    print("VERDICT (pre-committed hurdle)")
    print("=" * 78)
    best = res[res["horizon"] >= MIN_HORIZON_BARS].sort_values("median", ascending=False)
    print(f"  best cells at h>={MIN_HORIZON_BARS}:")
    for _, r in best.head(5).iterrows():
        print(f"    {r.feature:<15} h={int(r.horizon)} "
              f"median={r['median'] * 100:+.3f}c  "
              f"net={r['median'] * 100 - COST_RT * 100:+.3f}c")
    print(f"\n  cells clearing ${GROSS_HURDLE:.3f} at h>={MIN_HORIZON_BARS}: {len(ok)}")

    if len(ok) == 0:
        print("\n  TIER: DEAD")
        print("  No bar-level pressure proxy clears the cost hurdle at a tradeable")
        print("  horizon. Do not build a strategy on this data.")
        print("\n  IMPORTANT: this does NOT close the order-flow question. Bars")
        print("  destroy the microstructure the hypothesis is about. It only means")
        print("  the cheap proxy shows nothing, so tick data would be a bet, not")
        print("  a follow-up on evidence.")
        res.to_parquet(OUT, index=False)
        print(f"\n  written: {OUT}")
        print("=" * 78)
        return

    # Only reached if something cleared — then robustness matters.
    print("\n  Something cleared. Running robustness before believing it.")
    top = ok.sort_values("median", ascending=False).iloc[0]
    feat, h = top["feature"], int(top["horizon"])
    print(f"\n{'-' * 78}")
    print(f"ROBUSTNESS on best cell: {feat} @ h={h}")
    print(f"{'-' * 78}")

    print("  per-year (IS):")
    for y, g in IS.groupby("year"):
        r = evaluate(g, feat, h, str(y), quiet=True)
        if r:
            print(f"    {y}: median={r['median'] * 100:+.3f}c  n={r['n']:,}"
                  f"{'  BREAKS' if r['median'] < GROSS_HURDLE else ''}")

    print("  leave-one-ticker-out (IS):")
    worst = None
    for tk in tickers:
        r = evaluate(IS[IS["ticker"] != tk], feat, h, tk, quiet=True)
        if r and (worst is None or r["median"] < worst[1]):
            worst = (tk, r["median"])
    if worst:
        print(f"    worst: dropping {worst[0]} -> median={worst[1] * 100:+.3f}c"
              f"{'  BREAKS' if worst[1] < GROSS_HURDLE else '  holds'}")

    print("  OUT-OF-SAMPLE 2023-2024:")
    r = evaluate(OOS, feat, h, "OOS", quiet=True)
    if r:
        print(f"    median={r['median'] * 100:+.3f}c  net={r['median'] * 100 - COST_RT * 100:+.3f}c"
              f"  n={r['n']:,}"
              f"{'  HOLDS' if r['median'] >= GROSS_HURDLE else '  FAILS OOS'}")

    res.to_parquet(OUT, index=False)
    print(f"\n  written: {OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
