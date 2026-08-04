"""
harvest_stress_orb_stk_days.py — STRESS_ORB_STK trigger-day harvester (EXPERIMENTAL)

Purpose (ONLY this): harvest the (ticker, date) TRIGGER list from the reverted
STRESS_ORB_STK stock variant, to use as candidate event-days for the news-catalyst
pilot. We do NOT care about P&L / edge / win-rate — only "on which days did a
CANDIDATE_POOL stock have a Stress-regime opening-range breakdown setup."

Method: import raits/raits/scripts/stress_orb_stk_sim.py UNMODIFIED and read its
result globals (t_v1..t_v5). That runs the exact committed sim (5 variants) once,
so the trigger logic is reused verbatim — nothing re-implemented, engine/orb.py
untouched, STRESS_ORB_STK NOT re-enabled anywhere.

Variants harvested:
  V1  no ETF co-confirm, fixed $500 sizing  → MAXIMAL candidate set (every
      gap-down OR-low breakdown that got an entry slot; sizing never rejects)
  V3  ETF co-confirm + Kelly                → engine-faithful ("Engine-best")
  V4  ETF co-confirm + Kelly + stop=1.0xATR → engine-faithful ("Engine-wide")

ISOLATION NOTE (SCRATCHPAD root-cause #1): the sim is fully standalone. It builds
its own local STOCK_UNIVERSE and runs ONLY the STRESS_ORB short logic; it never
injects _STOCK_STRESS_UNIVERSE into any shared _all_tickers/day_stocks, and does
not run FADE/GAP_FILL. So these trigger dates are from an ISOLATED run and are NOT
evidence that merging this universe into production is collateral-safe.

Run:
    cd d:\\raits
    python orb_stocks\\harvest_stress_orb_stk_days.py
"""

from __future__ import annotations

import os
import sys
import io
import pickle
import contextlib
import collections

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 chokes on non-ASCII
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "raits", "raits", "scripts"))

from raits.strategies.universe_scanner import CANDIDATE_POOL

WINDOW_START = pd.Timestamp("2021-04-01")
WINDOW_END   = pd.Timestamp("2022-12-31")
ORB_SNAPSHOT = os.path.join(REPO, "raits", "data", "cache", "snapshots",
                            "results_20260707_110323.pkl")
POOL = set(CANDIDATE_POOL)


def orb_baseline_pairs():
    """The existing 18 plain-ORB (ticker,date) events (same method as Step 1)."""
    with open(ORB_SNAPSHOT, "rb") as f:
        windows = pickle.load(f)
    pairs = set()
    for w in windows:
        for t in w["trades"]:
            if getattr(t, "strategy", None) != "ORB":
                continue
            et = pd.Timestamp(t.entry_time).normalize()
            if WINDOW_START <= et <= WINDOW_END and t.ticker in POOL:
                pairs.add((t.ticker, et.date()))
    return pairs


def pairs_from_trades(trades, in_window=True):
    """(ticker,date) set from a sim trade list, pool-restricted; optional window."""
    out = set()
    for t in trades:
        d = pd.Timestamp(t["day"]).normalize()
        if t["ticker"] not in POOL:
            continue
        if in_window and not (WINDOW_START <= d <= WINDOW_END):
            continue
        out.add((t["ticker"], d.date()))
    return out


def main():
    print("=" * 78)
    print("STRESS_ORB_STK — TRIGGER-DAY HARVEST (candidate event generator only)")
    print("=" * 78)

    # ── Run the committed sim once (suppress its verbose stdout) ──────────
    print("Running stress_orb_stk_sim.py (unmodified, ~30-60s incl. bootstrap)...")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        import stress_orb_stk_sim as sim  # auto-runs all 5 variants on import
    print("  sim run complete.\n")

    stress_days = sim.stress_days
    sd_by_yr = collections.Counter(d.year for d in stress_days)
    print(f"Sim Stress days: {len(stress_days)} total  "
          f"(range {stress_days[0].date()}..{stress_days[-1].date()})")
    print(f"  by year: {dict(sorted(sd_by_yr.items()))}")

    orb18 = orb_baseline_pairs()
    print(f"\nExisting plain-ORB events (baseline): {len(orb18)}")

    variants = [
        ("V1 no-confirm/$500 (MAXIMAL candidate set)", sim.t_v1),
        ("V3 co-confirm/Kelly (engine-faithful)",      sim.t_v3),
        ("V4 co-confirm/Kelly/stop1.0x (engine-wide)", sim.t_v4),
    ]

    # ── Engine count comparison (step 4): full-range trade counts vs 224 ──
    print(f"\n{'-'*78}")
    print("STEP 4 — sim trade COUNTS over full sim range (2020-2022) vs documented")
    print("         reverted-engine figure (SCRATCHPAD: 224 trades across 2020-2022):")
    for label, tr in variants:
        full = [t for t in tr if t["ticker"] in POOL]
        yc = collections.Counter(pd.Timestamp(t["day"]).year for t in full)
        print(f"  {label:<44} {len(full):>4} trades  by-year={dict(sorted(yc.items()))}")
    print("  (STRESS_ORB_STK is reverted → no engine trades in any current results")
    print("   pkl to diff day-by-day; this is a rough COUNT check only.)")

    # ── Candidate lists in the dense window (2021-04 .. 2022-12) ──────────
    for label, tr in variants:
        pairs = pairs_from_trades(tr, in_window=True)
        new = pairs - orb18
        dup = pairs & orb18
        dates = sorted({d for _, d in pairs})
        print(f"\n{'='*78}")
        print(f"CANDIDATE SET — {label}")
        print(f"{'='*78}")
        if not pairs:
            print("  (no in-window pairs)")
            continue
        print(f"  in-window (ticker,date) events : {len(pairs)}")
        print(f"    NEW vs the 18 ORB events     : {len(new)}")
        print(f"    overlap with ORB events      : {len(dup)}  {sorted(dup) if dup else ''}")
        print(f"    distinct dates               : {len(dates)} "
              f"({dates[0]}..{dates[-1]})")

        # per-ticker
        tk = collections.Counter(t for t, _ in pairs)
        print(f"  per-ticker (events):")
        line = "    " + "  ".join(f"{t}:{n}" for t, n in tk.most_common())
        print(line)

        # per-month
        mo = collections.Counter((d.year, d.month) for _, d in pairs)
        print(f"  per-month (events):")
        for k in sorted(mo):
            print(f"    {k[0]}-{k[1]:02d}: {mo[k]}")

    print(f"\n{'='*78}")
    print("NOTES")
    print(f"{'='*78}")
    print("- Report uses V1 as the maximal candidate generator; V3/V4 are the")
    print("  engine-faithful (co-confirm) subsets. Choose per how close to engine")
    print("  behaviour the pilot wants its event set to be.")
    print("- Sim caps entries at MAX_SLOTS=3 stocks/day, so >=4th breakdown on a")
    print("  busy day is NOT in the list (strategy behaviour, but a coverage limit).")
    print("- ISOLATED run: sim does not inject its universe into shared day_stocks;")
    print("  trigger days are safe to HARVEST but NOT proof of collateral-safety")
    print("  for any future production merge (SCRATCHPAD root-cause #1 unresolved).")
    print("- No news fetched. Candidate list only, per instruction.")
    print("=" * 78)


if __name__ == "__main__":
    main()
