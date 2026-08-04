"""
Opening Imbalance Research — POWER FIX: extended event index.
(EXPERIMENTAL harness, orb_stocks/imbalance_research/)  — RESEARCH ONLY.

WHY THIS EXISTS
───────────────────────────────────────────────────────────────────────────
The Polygon study (FINDINGS.md) landed on MONITOR, and the binding constraint
was NOT event count — it was MIXED-DATE COUNT (23 dates / 63 events carrying
the deciding within-date permutation). Better-measured imbalance data does not
move that number. More dates carrying BOTH arms does.

The existing event population (`orb_event_index.parquet`, 155 events,
2021-04-28 .. 2022-12-27) is windowed that way for ONE reason: the catalyst
study needed Polygon NEWS, and Polygon's news history only begins ~2021-04
(measured by check_news_coverage.py's onset scan).

**The imbalance study does not use news at all.** That window is an inherited
constraint that does not apply here. Measured directly from the sim:

    stress_orb_stk_sim.t_v3 : 237 trades on 121 dates, 2018-02-02 .. 2022-12-27
    window_debug_5min.pkl   : all 75 tickers, 2017-01-03 .. 2024-12-31 (no gap)
    Stress days available   : 283, 2018-02-02 .. 2022-12-29
                              (2018:38 2019:25 2020:60 2021:47 2022:113)

So ~60% more events and ~50% more dates are available at zero data cost, using
the SAME committed sim, the SAME trigger logic, and price data already on disk.

WHAT THIS SCRIPT DOES
───────────────────────────────────────────────────────────────────────────
Rebuilds the event index over the widened window, reusing the committed sim
unmodified (imported, never re-implemented — same isolation guarantee as
harvest_stress_orb_stk_days.py), and derives outcomes with the SAME definition
the catalyst study used, so old and new results stay comparable:

    pct_return = (entry_px - exit_px) / entry_px      # SHORT: +ve = profit
    R_multiple = (entry_px - exit_px) / stop_dist
    data-quality gate: drop |pct_return| > 0.25 (corrupt bars)

Window default starts 2018-05-01 to match Databento's imbalance history
(2018-05-01 ..), so every event in the extended index is one we can actually
buy real auction-imbalance data for. Events from 2018-02..2018-04 are dropped
for that reason and the loss is reported, not hidden.

OUTPUT
    extended_event_index.parquet   — ticker, date, source, outcomes, window flag
    plus a printed before/after on the metric that actually matters:
    events-per-date, and how many dates can possibly host both arms.

NOTE ON WHAT THIS CANNOT DO
Mixed-date count is only knowable once imbalance labels exist. What this
script bounds is the CEILING: dates with >=2 events. A date with 1 event can
never be mixed. That ceiling is the honest thing to report now.

Run:
    cd d:\\raits
    python orb_stocks\\imbalance_research\\build_extended_event_index.py
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import io
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
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "raits", "raits", "scripts"))

CACHE = os.path.join(REPO, "raits", "data", "cache")
ORB_SNAPSHOT = os.path.join(CACHE, "snapshots", "results_20260707_110323.pkl")
OLD_INDEX = os.path.join(CACHE, "news", "orb_event_index.parquet")
OUT = os.path.join(HERE, "extended_event_index.parquet")

# Databento imbalance history begins 2018-05-01 — no point harvesting events we
# cannot buy the real variable for.
DEFAULT_START = "2018-05-01"
DEFAULT_END = "2022-12-31"

# The old (catalyst-inherited) window, for the before/after comparison.
OLD_START, OLD_END = "2021-04-01", "2022-12-31"

PCT_MAX = 0.25          # corrupt-bar gate, identical to bootstrap_catalyst.py


def load_pool():
    from raits.strategies.universe_scanner import CANDIDATE_POOL
    return set(CANDIDATE_POOL)


def stress_events(sim, pool, ws, we):
    """(ticker, date) -> outcome dict from the committed sim's t_v3 records."""
    out = {}
    for t in sim.t_v3:
        d = pd.Timestamp(t["day"]).normalize()
        if t["ticker"] not in pool or not (ws <= d <= we):
            continue
        out[(t["ticker"], d.date().isoformat())] = {
            "entry_px": float(t["entry_px"]),
            "exit_px": float(t["exit_px"]),
            "stop_dist": float(t["stop_dist"]),
            "source": "STRESS_ORB_STK",
        }
    return out


def orb_events(pool, ws, we):
    """(ticker, date) -> outcome dict from snapshot plain-ORB SHORT trades."""
    with open(ORB_SNAPSHOT, "rb") as f:
        windows = pickle.load(f)
    out = {}
    for w in windows:
        for t in w["trades"]:
            if getattr(t, "strategy", None) != "ORB":
                continue
            if getattr(t, "direction", None) != "SHORT":
                continue
            d = pd.Timestamp(t.entry_time).normalize()
            if t.ticker not in pool or not (ws <= d <= we):
                continue
            entry, exitp, stop = float(t.entry_price), float(t.exit_price), float(t.stop)
            out[(t.ticker, d.date().isoformat())] = {
                "entry_px": entry, "exit_px": exitp,
                "stop_dist": stop - entry,          # SHORT: stop above entry
                "source": "ORB",
            }
    return out


def date_structure(df: pd.DataFrame, label: str):
    per = df.groupby("date").size()
    dist = dict(sorted(collections.Counter(per.values).items()))
    ge2 = int((per >= 2).sum())
    print(f"  {label:<22} events={len(df):4}  dates={len(per):4}  "
          f"events/date={len(df) / len(per):.2f}")
    print(f"  {'':<22} dates with >=2 events (mixed-date CEILING) = {ge2}")
    print(f"  {'':<22} events-per-date distribution = {dist}")
    return ge2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START)
    ap.add_argument("--end", default=DEFAULT_END)
    a = ap.parse_args()

    ws, we = pd.Timestamp(a.start), pd.Timestamp(a.end)
    pool = load_pool()

    print("=" * 78)
    print("POWER FIX — EXTENDED EVENT INDEX  (RESEARCH ONLY, no production change)")
    print("=" * 78)
    print(f"  target window : {a.start} .. {a.end}")
    print(f"  old window    : {OLD_START} .. {OLD_END}  (set by Polygon NEWS onset,")
    print(f"                  a catalyst-study constraint that does NOT apply here)")
    print(f"\n  running committed sim (unmodified import, ~60s)...")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import stress_orb_stk_sim as sim
    print("  sim complete.")

    # Report what the sim actually offers, before any windowing.
    all_days = sorted({pd.Timestamp(t["day"]).normalize() for t in sim.t_v3})
    yrs = collections.Counter(pd.Timestamp(t["day"]).year for t in sim.t_v3)
    print(f"\n  sim t_v3 full range: {len(sim.t_v3)} trades on {len(all_days)} "
          f"dates, {all_days[0].date()} .. {all_days[-1].date()}")
    print(f"  by year: {dict(sorted(yrs.items()))}")

    # Events lost to the Databento history floor — reported, not hidden.
    pre = [t for t in sim.t_v3
           if pd.Timestamp(t["day"]).normalize() < ws and t["ticker"] in pool]
    if pre:
        pre_dates = {pd.Timestamp(t["day"]).date() for t in pre}
        print(f"\n  DROPPED before {a.start} (no Databento imbalance history): "
              f"{len(pre)} events on {len(pre_dates)} dates")

    # ── Build the extended population ─────────────────────────────────────
    ev = {}
    ev.update(stress_events(sim, pool, ws, we))
    orb = orb_events(pool, ws, we)
    n_orb_new = sum(1 for k in orb if k not in ev)
    ev.update({k: v for k, v in orb.items() if k not in ev})

    recs = []
    for (tk, d), o in ev.items():
        entry, exitp, sd = o["entry_px"], o["exit_px"], o["stop_dist"]
        pct = (entry - exitp) / entry if entry else np.nan
        rm = (entry - exitp) / sd if sd and sd > 0 else np.nan
        recs.append({"ticker": tk, "date": d, "source": o["source"],
                     "direction": "SHORT",
                     "entry_px": entry, "exit_px": exitp, "stop_dist": sd,
                     "pct_return": pct, "R_multiple": rm})
    df = pd.DataFrame(recs).sort_values(["date", "ticker"]).reset_index(drop=True)

    # Same corrupt-bar gate as the catalyst study.
    df["outcome_suspect"] = df["pct_return"].abs() > PCT_MAX
    n_susp = int(df["outcome_suspect"].sum())
    print(f"\n  corrupt-bar gate |pct_return|>{PCT_MAX:.0%}: {n_susp} dropped")
    for _, r in df[df["outcome_suspect"]].iterrows():
        print(f"    DROP {r['ticker']} {r['date']}: entry={r['entry_px']:.2f} "
              f"exit={r['exit_px']:.2f} pct={r['pct_return'] * 100:+.0f}%")
    clean = df[~df["outcome_suspect"]].copy()

    df["in_old_window"] = (df["date"] >= OLD_START) & (df["date"] <= OLD_END)
    df.to_parquet(OUT, index=False)

    # ── The comparison that matters ───────────────────────────────────────
    print(f"\n{'=' * 78}")
    print("BEFORE / AFTER — the metric that actually binds")
    print("=" * 78)
    old = clean[(clean["date"] >= OLD_START) & (clean["date"] <= OLD_END)]
    ceil_old = date_structure(old, "OLD (2021-04 on)")
    print()
    ceil_new = date_structure(clean, f"EXTENDED ({a.start} on)")

    print(f"\n  mixed-date CEILING: {ceil_old} -> {ceil_new}  "
          f"(x{ceil_new / ceil_old:.2f})" if ceil_old else "")
    print(f"  events            : {len(old)} -> {len(clean)}  "
          f"(x{len(clean) / len(old):.2f})")

    print(f"\n  by year (clean events):")
    yc = collections.Counter(pd.Timestamp(d).year for d in clean["date"])
    for y, n in sorted(yc.items()):
        dn = clean[pd.to_datetime(clean["date"]).dt.year == y]["date"].nunique()
        print(f"    {y}: {n:4} events on {dn:3} dates")
    print(f"\n  by source: {dict(clean['source'].value_counts())}")
    print(f"  distinct tickers: {clean['ticker'].nunique()}")

    print(f"\n{'-' * 78}")
    print("HONEST BOUND")
    print(f"{'-' * 78}")
    print("  'dates with >=2 events' is a CEILING on mixed dates, not a forecast.")
    print("  A date hosts both arms only if its events actually split on the")
    print(f"  imbalance sign. In the Polygon study {23}/{45} such dates were mixed")
    print("  (51%). Applying that same rate to the extended ceiling gives a")
    print(f"  rough expectation of ~{int(ceil_new * 23 / 45)} mixed dates, vs 23 now.")
    print("  Treat it as an estimate; the real number is only known after labels.")

    print(f"\n  written: {OUT}")
    print("  next: fetch Databento imbalance for these dates, then re-run")
    print("        bootstrap_imbalance.py / robustness_imbalance.py against it.")
    print("=" * 78)


if __name__ == "__main__":
    main()
