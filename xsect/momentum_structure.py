"""
xsect/momentum_structure.py — Gate 1: does cross-sectional momentum persist?
============================================================================
Ranks the universe by trailing return (default 12-1: 252d return skipping the last
21d to avoid short-term reversal), forms deciles, and measures the forward-return
spread top-minus-bottom over a holding period. If winners persistently beat losers
(spread > 0, significant, most periods positive), cross-sectional structure exists
→ worth a full build. Else NO-GO cheaply.

Decomposes long-leg (top vs universe mean) and short-leg (universe mean vs bottom)
so we know whether the edge survives WITHOUT shorting (the small-account constraint).

Loads a directory of per-ticker parquet files (filename stem = ticker) OR a single
panel parquet. Resamples to daily close.

    python -m xsect.momentum_structure --cache-dir path\\to\\phase1_cache --resample
    python -m xsect.momentum_structure --panel path\\to\\closes_panel.parquet \
        --lookback 252 --skip 21 --hold 21 --deciles 10
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd


def load_panel(cache_dir, panel, resample, min_days):
    """Return a (dates × tickers) daily close DataFrame."""
    if panel:
        px = pd.read_parquet(panel)
        px.index = pd.DatetimeIndex(px.index)
        return px.sort_index()
    files = sorted(Path(cache_dir).glob("*.parquet"))
    if not files:
        raise SystemExit(f"no parquet files in {cache_dir}")
    cols = {}
    for f in files:
        tkr = f.stem.split("_")[0].upper()
        try:
            d = pd.read_parquet(f)
        except Exception:
            continue
        d.columns = [c.lower() for c in d.columns]
        if "close" not in d.columns:
            continue
        if not isinstance(d.index, pd.DatetimeIndex):
            for cand in ("ts_event", "timestamp", "date", "time"):
                if cand in d.columns:
                    d = d.set_index(pd.to_datetime(d[cand])); break
        if not isinstance(d.index, pd.DatetimeIndex):
            continue
        close = (d.groupby(d.index.normalize())["close"].last() if resample else d["close"])
        close.index = pd.DatetimeIndex(close.index).tz_localize(None)
        if len(close.dropna()) >= min_days:
            cols[tkr] = close
    if not cols:
        raise SystemExit("no usable close series found")
    px = pd.DataFrame(cols).sort_index()
    return px


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir")
    ap.add_argument("--panel")
    ap.add_argument("--resample", action="store_true")
    ap.add_argument("--lookback", type=int, default=252, help="trailing window (days)")
    ap.add_argument("--skip", type=int, default=21, help="skip most-recent days (reversal)")
    ap.add_argument("--hold", type=int, default=21, help="forward holding period (days)")
    ap.add_argument("--deciles", type=int, default=10)
    ap.add_argument("--min-names", type=int, default=20, help="min stocks to rank a date")
    ap.add_argument("--min-days", type=int, default=300)
    a = ap.parse_args()
    if not (a.cache_dir or a.panel):
        raise SystemExit("need --cache-dir or --panel")

    px = load_panel(a.cache_dir, a.panel, a.resample, a.min_days)
    n_names = px.shape[1]
    print(f"\n{'='*68}\nCROSS-SECTIONAL MOMENTUM STRUCTURE (Gate 1)")
    print(f"universe {n_names} tickers | {px.index[0].date()}→{px.index[-1].date()} | "
          f"mom {a.lookback}-{a.skip}, hold {a.hold}d, {a.deciles} deciles\n{'='*68}")
    if n_names < a.min_names:
        print(f"only {n_names} tickers — too few for cross-sectional ranking. Need ≥{a.min_names}.")
        return

    # rebalance dates every `hold` trading days
    dates = px.index
    reb_idx = range(a.lookback, len(dates) - a.hold, a.hold)
    spreads, long_leg, short_leg = [], [], []
    per_year = {}
    for i in reb_idx:
        t = dates[i]
        # trailing return skipping recent `skip` days
        past = px.iloc[i - a.lookback]
        recent = px.iloc[i - a.skip]
        mom = (recent / past) - 1.0
        fwd = (px.iloc[i + a.hold] / px.iloc[i]) - 1.0
        valid = mom.notna() & fwd.notna()
        mom, fwd = mom[valid], fwd[valid]
        if len(mom) < a.min_names:
            continue
        ranks = mom.rank(pct=True)
        top = fwd[ranks > 1 - 1.0 / a.deciles]
        bot = fwd[ranks < 1.0 / a.deciles]
        uni = fwd.mean()
        if len(top) == 0 or len(bot) == 0:
            continue
        spreads.append(top.mean() - bot.mean())
        long_leg.append(top.mean() - uni)     # long alpha vs universe
        short_leg.append(uni - bot.mean())    # short alpha vs universe
        per_year.setdefault(t.year, []).append(top.mean() - bot.mean())

    if not spreads:
        print("no valid rebalance periods — check data coverage.")
        return
    s = np.array(spreads)
    t_stat = s.mean() / (s.std(ddof=1) / np.sqrt(len(s))) if s.std() > 0 else np.nan
    print(f"{'periods':>10}{'spread/reb':>12}{'ann.spread':>12}{'t-stat':>9}{'% pos':>8}")
    print("-"*68)
    ann = s.mean() * (252 / a.hold)
    print(f"{len(s):>10}{s.mean()*100:>11.2f}%{ann*100:>11.1f}%{t_stat:>9.2f}"
          f"{(s>0).mean()*100:>7.0f}%")
    print("-"*68)
    print(f"long-leg  alpha vs universe: {np.mean(long_leg)*100:+.2f}%/reb  "
          f"({np.mean(long_leg)*(252/a.hold)*100:+.1f}%/yr)")
    print(f"short-leg alpha vs universe: {np.mean(short_leg)*100:+.2f}%/reb  "
          f"({np.mean(short_leg)*(252/a.hold)*100:+.1f}%/yr)")
    print("-"*68)
    print("year-by-year mean spread/reb:")
    print("  " + "  ".join(f"{y}:{np.mean(v)*100:+.2f}%" for y, v in sorted(per_year.items())))
    print("-"*68)
    # verdict
    all_years_pos = all(np.mean(v) > 0 for v in per_year.values())
    sig = abs(t_stat) > 2 if not np.isnan(t_stat) else False
    ls, ss = np.mean(long_leg), np.mean(short_leg)
    if s.mean() > 0 and sig and all_years_pos:
        print("VERDICT: cross-sectional momentum PERSISTS (spread>0, t>2, all years+).")
        if ls > 0 and ss <= 0:
            print("  Edge is LONG-side → long-only viable (but watch beta creep).")
        elif ss > 0 and ls <= 0:
            print("  Edge is SHORT-side → needs shorting (hard for small VN account).")
        else:
            print("  Both legs contribute → full long/short would capture most.")
        print("  → worth a Gate-2 build (after-cost test still decides).")
    else:
        print("VERDICT: cross-sectional momentum does NOT persist robustly "
              f"(t={t_stat:.2f}, all-years+={all_years_pos}).")
        print("  → NO-GO cheaply. No big build.")
    print("\nCAVEAT: if the cache is survivorship-biased (only stocks alive today),")
    print("  the spread is an OPTIMISTIC upper bound — delisted losers are missing.\n")


if __name__ == "__main__":
    main()
