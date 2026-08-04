"""
fetch_orb_news.py — Step 1 runner (EXPERIMENTAL harness, orb_stocks/)

Fetches + caches Polygon news restricted to the days the plain ORB strategy
(raits/strategies/orb.py, strategy=="ORB") actually traded, within the confirmed
dense-coverage window 2021-04-01 .. 2022-12-31.

Scope (decided with user): TRADED TICKER ONLY — for each ticker that traded, we
fetch news only for the months in which it traded. This matches the downstream
per-traded-ticker filter ("did THIS stock have pre-market news on its entry
day"), and is the cheapest cell set (~18 ticker-months).

Reusable fetch/cache/index infra lives in raits/data/raits_news.py; this file is
just the ORB-specific driver + the Step-1 cache summary. No LLM, no bootstrap.

Run:
    cd d:\\raits
    python orb_stocks\\fetch_orb_news.py
"""

from __future__ import annotations

import os
import sys
import pickle

import pandas as pd

# repo root on path so `raits.*` imports resolve when run from d:\raits
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from raits.strategies.universe_scanner import CANDIDATE_POOL
from raits.data.raits_news import fetch_news_for_universe, build_news_index
from check_news_coverage import _load_api_key  # same auth pattern, DRY

# ── Config ────────────────────────────────────────────────────────────────
SNAPSHOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "raits", "data", "cache", "snapshots", "results_20260707_110323.pkl",
)
CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "raits", "data", "cache",
)
WINDOW_START = pd.Timestamp("2021-04-01")
WINDOW_END   = pd.Timestamp("2022-12-31")


def extract_orb_signal_pairs(snapshot_path: str):
    """Return sorted unique (ticker, date) pairs where ORB traded in-window."""
    with open(snapshot_path, "rb") as f:
        windows = pickle.load(f)  # list of {label, stats, trades}
    pool = set(CANDIDATE_POOL)
    pairs = set()
    for w in windows:
        for t in w["trades"]:
            if getattr(t, "strategy", None) != "ORB":
                continue
            et = pd.Timestamp(t.entry_time).normalize()
            if not (WINDOW_START <= et <= WINDOW_END):
                continue
            tk = t.ticker
            if tk not in pool:
                # Should never happen (ORB only trades the pool) — surface it.
                print(f"  [WARN] ORB trade on non-pool ticker {tk} @ {et.date()}")
                continue
            pairs.add((tk, et.date()))
    return sorted(pairs)


def main() -> None:
    print("=" * 78)
    print("ORB STOCKS — STEP 1: fetch + cache news for ORB signal days")
    print(f"Window: {WINDOW_START.date()} .. {WINDOW_END.date()}  (dense coverage)")
    print(f"Snapshot: {os.path.basename(SNAPSHOT)}")
    print("=" * 78)

    pairs = extract_orb_signal_pairs(SNAPSHOT)
    traded_tickers = sorted({tk for tk, _ in pairs})
    trade_dates    = sorted({d for _, d in pairs})

    # Per-ticker trade-months (scope: traded ticker only).
    ticker_months: dict[str, set] = {}
    for tk, d in pairs:
        ticker_months.setdefault(tk, set()).add((d.year, d.month))

    n_cells = sum(len(m) for m in ticker_months.values())
    print(f"\nORB signal (ticker,date) pairs : {len(pairs)}")
    print(f"Traded tickers                 : {len(traded_tickers)} {traded_tickers}")
    print(f"Distinct trade dates           : {len(trade_dates)} "
          f"({trade_dates[0]} .. {trade_dates[-1]})")
    print(f"(ticker, month) cells to fetch : {n_cells}")

    # ── Fetch (idempotent), per ticker with its own trade-months ──────────
    api_key = _load_api_key()
    print(f"\n--- Fetching (cache: {CACHE_DIR}\\news) ---")
    manifest: dict = {}
    for tk in traded_tickers:
        months = sorted(ticker_months[tk])
        m = fetch_news_for_universe(
            tickers=[tk],
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            api_key=api_key,
            cache_dir=CACHE_DIR,
            months=months,
            verbose=True,
        )
        manifest.update(m)

    # ── Build index (all cached articles for traded tickers) ──────────────
    idx = build_news_index(CACHE_DIR, tickers=traded_tickers, dates=None)

    # ── Summary (item 4) ──────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print("STEP 1 CACHE SUMMARY")
    print("=" * 78)

    errors  = [k for k, v in manifest.items() if v is None]
    total   = sum(v for v in manifest.values() if isinstance(v, int))
    empties = [k for k, v in manifest.items() if v == 0]

    print(f"Total articles cached : {total}")
    print(f"(ticker,month) cells  : {len(manifest)}  "
          f"(errors={len(errors)}, empty={len(empties)})")

    if not idx.empty:
        cov_dates = idx.index.get_level_values("date")
        print(f"Article ET-date range : {cov_dates.min().date()} .. {cov_dates.max().date()}")

    print("\nPer-ticker article counts (cell months in parens):")
    for tk in traded_tickers:
        cells = sorted(ticker_months[tk])
        cnt = sum(manifest.get((tk, y, mo), 0) or 0 for (y, mo) in cells)
        cell_str = ",".join(f"{y}-{mo:02d}" for (y, mo) in cells)
        n_on_trade_days = 0
        if not idx.empty and tk in idx.index.get_level_values("ticker"):
            tk_dates = set(idx.loc[tk].index.date if hasattr(idx.loc[tk].index, "date")
                           else [pd.Timestamp(x).date() for x in idx.loc[tk].index])
            n_on_trade_days = len(
                [d for _t, d in pairs if _t == tk and d in tk_dates]
            )
        print(f"  {tk:<6} {cnt:>4} articles  [{cell_str}]  "
              f"| trade-days with >=1 article: {n_on_trade_days}/"
              f"{len([1 for _t,_ in pairs if _t==tk])}")

    # ── Anomaly flags: empty/error cells despite dense window ─────────────
    print(f"\n{'-' * 78}")
    if errors:
        print("ANOMALY — cells that ERRORED (left uncached, will retry on re-run):")
        for (tk, y, mo) in sorted(errors):
            print(f"  {tk} {y}-{mo:02d}")
    if empties:
        print("ANOMALY — cells with ZERO articles despite dense window (check):")
        for (tk, y, mo) in sorted(empties):
            print(f"  {tk} {y}-{mo:02d}")
    if not errors and not empties:
        print("FLAGS: none — every fetched (ticker,month) cell returned >=1 article.")

    # ── Trade-day coverage flag (decision-relevant for Step 2/3) ──────────
    trade_day_hits = 0
    for tk, d in pairs:
        if not idx.empty and tk in idx.index.get_level_values("ticker"):
            days = idx.loc[tk].index
            days = {pd.Timestamp(x).date() for x in days}
            if d in days:
                trade_day_hits += 1
    print(f"\nORB trade-days with >=1 article (any time that ET day): "
          f"{trade_day_hits}/{len(pairs)}")
    print("(Note: pre-09:30 / overnight filtering is Step 2/3, not applied here.)")
    print("=" * 78)


if __name__ == "__main__":
    main()
