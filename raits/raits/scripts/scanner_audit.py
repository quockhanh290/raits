"""
scripts/scanner_audit.py
------------------------
Pre-run DailyUniverseScanner over the full historical period to identify
which stocks actually get selected — before downloading 5-min data.

This tells us exactly which tickers need 5-min bars for the backtest.

Usage:
    cd d:\\raits\\raits
    python raits/scripts/scanner_audit.py

Output:
    - Per-ticker: how many days selected, % of trading days, date ranges
    - Recommended download list (stocks selected > threshold)
"""

import sys
import os
import warnings
warnings.filterwarnings("ignore")

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import glob
import pandas as pd
from collections import defaultdict

from raits.strategies.universe_scanner import DailyUniverseScanner, CANDIDATE_POOL

DAILY_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "data", "cache", "daily")
AUDIT_START = "2019-01-01"   # 2 years warmup before 2020 OOS window
AUDIT_END   = "2022-12-31"   # covers all 3 OOS windows (2020/2021/2022)
MIN_DAYS_THRESHOLD = 5       # must appear at least 5 days to be worth downloading


def load_daily_cache(tickers: list) -> dict:
    daily_data = {}
    for ticker in tickers:
        files = glob.glob(os.path.join(DAILY_CACHE, f"{ticker}_daily_*.parquet"))
        if not files:
            continue
        frames = [pd.read_parquet(f) for f in files]
        df = pd.concat(frames)
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        daily_data[ticker] = df
    return daily_data


def main():
    print(f"\n{'='*60}")
    print("DailyUniverseScanner — Historical Audit")
    print(f"Period: {AUDIT_START} → {AUDIT_END}")
    print(f"Pool:   {len(CANDIDATE_POOL)} stocks")
    print(f"{'='*60}\n")

    # Load all daily data
    all_tickers = ["SPY"] + CANDIDATE_POOL
    print("Loading daily cache...", end=" ", flush=True)
    daily_data = load_daily_cache(all_tickers)
    loaded = len(daily_data) - (1 if "SPY" in daily_data else 0)
    print(f"[OK] {loaded}/{len(CANDIDATE_POOL)} stocks + SPY\n")

    scanner = DailyUniverseScanner(top_n=15)

    # Get all trading days in audit range from SPY
    spy = daily_data.get("SPY", pd.DataFrame())
    if spy.empty:
        print("[FAIL] SPY daily data missing")
        return

    trading_days = spy.index.normalize().unique()
    trading_days = trading_days[
        (trading_days >= pd.Timestamp(AUDIT_START)) &
        (trading_days <= pd.Timestamp(AUDIT_END))
    ]

    print(f"Scanning {len(trading_days)} trading days...\n")

    # Track selections
    ticker_days   = defaultdict(int)          # ticker → days selected
    ticker_first  = {}                        # ticker → first date selected
    ticker_last   = {}                        # ticker → last date selected
    total_scanned = 0

    for day in trading_days:
        selected = scanner.scan(daily_data, scan_date=day)
        total_scanned += 1

        for t in selected:
            ticker_days[t] += 1
            if t not in ticker_first:
                ticker_first[t] = day
            ticker_last[t] = day

        if total_scanned % 100 == 0:
            print(f"  Scanned {total_scanned}/{len(trading_days)} days...", flush=True)

    print(f"\n  Done — {total_scanned} days scanned")

    # ── Results ────────────────────────────────────────────────────────────────
    total_days = len(trading_days)

    print(f"\n{'='*60}")
    print("SCANNER AUDIT RESULTS")
    print(f"{'='*60}")
    print(f"  {'Ticker':<8} {'Days':>6} {'Freq':>7}  {'First':>12}  {'Last':>12}  Status")
    print(f"  {'-'*58}")

    already_cached = {"TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL",
                      "SPY", "QQQ", "IWM"}

    need_download  = []
    never_selected = []

    all_tickers_sorted = sorted(CANDIDATE_POOL,
                                key=lambda t: ticker_days.get(t, 0),
                                reverse=True)

    for ticker in all_tickers_sorted:
        days = ticker_days.get(ticker, 0)
        freq = days / total_days * 100 if total_days > 0 else 0
        first = ticker_first.get(ticker, "-")
        last  = ticker_last.get(ticker, "-")

        first_str = str(first)[:10] if first != "-" else "-"
        last_str  = str(last)[:10]  if last  != "-" else "-"

        if days == 0:
            status = "never selected"
            never_selected.append(ticker)
        elif ticker in already_cached:
            status = "✓ cached"
        elif days >= MIN_DAYS_THRESHOLD:
            status = "→ DOWNLOAD"
            need_download.append((ticker, days))
        else:
            status = f"rare ({days}d)"

        print(f"  {ticker:<8} {days:>6} {freq:>6.1f}%  {first_str:>12}  {last_str:>12}  {status}")

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"  Already cached (5-min):  {len(already_cached & set(CANDIDATE_POOL))} stocks")
    print(f"  Need 5-min download:     {len(need_download)} stocks")
    print(f"  Never selected:          {len(never_selected)} stocks (skip)")

    if need_download:
        print(f"\n  Stocks to download 5-min data for:")
        for ticker, days in sorted(need_download, key=lambda x: -x[1]):
            print(f"    {ticker:<8} ({days} days selected)")

    if never_selected:
        print(f"\n  Never selected (no 5-min needed):")
        print(f"    {', '.join(never_selected)}")

    print(f"\n{'='*60}")
    print(f"  Total unique tickers needed for backtest:")
    all_needed = (already_cached & set(CANDIDATE_POOL)) | {t for t, _ in need_download}
    print(f"    {sorted(all_needed)}")
    print(f"    Count: {len(all_needed)} tickers")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
