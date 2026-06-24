"""
scripts/window_debug.py
-----------------------
Debug per-strategy performance for each WFO OOS window (2020 / 2021 / 2022).
Uses the same data loading as wfo_real_run.py to guarantee consistent data.

Usage:
    cd d:\raits\raits
    python raits/scripts/window_debug.py
"""

import sys, os, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import glob as _glob
import pickle
import time as _time
import pandas as pd
from collections import defaultdict
from datetime import time as dtime
from concurrent.futures import ProcessPoolExecutor

from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.strategies.universe_scanner import CANDIDATE_POOL

# Original fixed universe (kept for reference / VWAP_MR)
UNIVERSE      = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]

# Phase 1 new stocks (downloaded 2019-2022, ≥248 scanner-audit days)
PHASE1        = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]

# Phase 2 new stocks (downloaded after Phase 1 results confirmed)
PHASE2        = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]

# PE_SHORT expansion universe — fetch 5-min data to unlock these
PE_EXPANSION  = [
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C",
    "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP",
    "CAT", "DE", "BA", "GE",
    "PYPL", "PANW", "NOW",
]

# All tickers that need 5-min data loaded
SECTOR_ETFS   = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
TICKERS       = ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION
INTERVAL_MINS = 5
DATASET_START = "2017-01-03"
DATASET_END   = "2024-12-31"
CACHE_5MIN       = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "data")
CACHE_DAILY      = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "daily")
PICKLE_5MIN      = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY     = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")
PICKLE_RESULTS   = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_results.pkl")
TF_BASELINE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "tf_baseline.json")


def _cache_is_fresh(pickle_path: str, source_dir: str, pattern: str) -> bool:
    """Return True if pickle exists and is newer than all source parquets."""
    if not os.path.exists(pickle_path):
        return False
    pkl_mtime = os.path.getmtime(pickle_path)
    source_files = _glob.glob(os.path.join(source_dir, pattern))
    if not source_files:
        return False
    return all(os.path.getmtime(f) <= pkl_mtime for f in source_files)


def fetch_market_data(tickers, interval_minutes=5, rebuild=False, force_cache=False):
    """Bulk-load 5-min parquet files, with pickle cache for fast subsequent loads."""
    if not rebuild and (force_cache or _cache_is_fresh(PICKLE_5MIN, CACHE_5MIN, "*.parquet")):
        t0 = _time.time()
        print("  Loading 5-min data from pickle cache...", end=" ", flush=True)
        with open(PICKLE_5MIN, "rb") as f:
            all_data = pickle.load(f)
        # Filter to requested tickers only
        market_data = {t: df for t, df in all_data.items() if t in tickers}
        print(f"done ({_time.time()-t0:.1f}s) — {len(market_data)} tickers")
        return market_data

    print("  Building 5-min cache from parquets (first run, will be fast next time)...")
    market_data = {}
    for ticker in tickers:
        prefix = os.path.join(CACHE_5MIN, f"{ticker}_{interval_minutes}min_")
        files  = _glob.glob(prefix + "*.parquet")
        if not files:
            print(f"  {ticker}: no 5-min cache — skip")
            continue
        frames = [pd.read_parquet(f) for f in files]
        df = pd.concat(frames)
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        df = df.between_time("09:30", "16:00")
        days = len(df.index.normalize().unique())
        print(f"  {ticker}: {days} days, {len(df):,} bars")
        market_data[ticker] = df

    with open(PICKLE_5MIN, "wb") as f:
        pickle.dump(market_data, f)
    print(f"  Saved pickle -> {os.path.basename(PICKLE_5MIN)}")
    return market_data


def load_daily_data(rebuild=False):
    """Load daily OHLCV for scanner, with pickle cache for fast subsequent loads."""
    if not rebuild and _cache_is_fresh(PICKLE_DAILY, CACHE_DAILY, "*.parquet"):
        t0 = _time.time()
        print("  Loading daily data from pickle cache...", end=" ", flush=True)
        with open(PICKLE_DAILY, "rb") as f:
            daily_data = pickle.load(f)
        print(f"done ({_time.time()-t0:.1f}s) — {len(daily_data)} tickers")
        return daily_data

    print("  Building daily cache from parquets...")
    tickers = ["SPY"] + CANDIDATE_POOL
    daily_data = {}
    missing = []
    for ticker in tickers:
        files = _glob.glob(os.path.join(CACHE_DAILY, f"{ticker}_daily_*.parquet"))
        if not files:
            missing.append(ticker)
            continue
        frames = [pd.read_parquet(f) for f in files]
        df = pd.concat(frames)
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        daily_data[ticker] = df
    print(f"  Daily data: {len(daily_data)}/{len(tickers)} tickers loaded"
          + (f" (missing: {missing})" if missing else ""))

    with open(PICKLE_DAILY, "wb") as f:
        pickle.dump(daily_data, f)
    print(f"  Saved pickle -> {os.path.basename(PICKLE_DAILY)}")
    return daily_data

WINDOWS = [
    ("2017-01-03", "2017-12-29", "2017"),
    ("2018-01-02", "2018-12-31", "2018"),
    ("2019-01-02", "2019-12-31", "2019"),
    ("2020-01-02", "2020-12-31", "2020"),
    ("2021-01-04", "2021-12-31", "2021"),
    ("2022-01-03", "2022-12-30", "2022"),
]


def slice_oos(full_data, test_start, test_end, warmup_days=252):
    """SPY: full history. Stocks: 252-day warmup + test. Same logic as wfo.py."""
    spy = full_data.get("SPY", pd.DataFrame())
    spy_days   = spy.index.normalize().unique().sort_values()
    warmup_idx = int(spy_days.searchsorted(pd.Timestamp(test_start).normalize()))
    warmup_idx = max(0, warmup_idx - warmup_days)
    warmup_start = pd.Timestamp(spy_days[warmup_idx])

    result = {}
    for ticker, df in full_data.items():
        if ticker == "SPY":
            sliced = df[df.index <= pd.Timestamp(test_end) + pd.Timedelta("1D")]
        else:
            sliced = df[
                (df.index >= warmup_start)
                & (df.index <= pd.Timestamp(test_end) + pd.Timedelta("1D"))
            ]
        if not sliced.empty:
            result[ticker] = sliced
    return result


def collect_stats(trades, equity_start, equity_end, max_dd):
    """Return a dict of stats for one window."""
    by_strat  = defaultdict(list)
    by_regime = defaultdict(list)
    for t in trades:
        pnl = t.net_pnl or 0.0
        by_strat[t.strategy].append(pnl)
        by_regime[getattr(t, "hmm_state", "Unknown")].append(pnl)

    def strat_row(pnls):
        if not pnls:
            return (0, 0.0, 0.0, 0.0)
        wins = sum(1 for p in pnls if p > 0)
        return (len(pnls), wins / len(pnls) * 100,
                sum(pnls) / len(pnls), sum(pnls))

    return {
        "n":       len(trades),
        "pnl":     equity_end - equity_start,
        "ret":     (equity_end - equity_start) / equity_start,
        "dd":      max_dd,
        "orb":      strat_row(by_strat.get("ORB", [])),
        "orb_fade": strat_row(by_strat.get("ORB_FADE", [])),
        "fade":     strat_row(by_strat.get("FADE", [])),
        "tf":       strat_row(by_strat.get("TREND_FOLLOW", [])),
        "vmr":      strat_row(by_strat.get("VWAP_MR", [])),
        "gap_fill": strat_row(by_strat.get("GAP_FILL", [])),
        "gf_short":    strat_row(by_strat.get("GF_SHORT", [])),
        "rs_short":    strat_row(by_strat.get("RS_SHORT", [])),
        "stress_orb":     strat_row(by_strat.get("STRESS_ORB", [])),
        "stress_mid":     strat_row(by_strat.get("STRESS_MID", [])),
        "pe_short":    strat_row(by_strat.get("PE_SHORT", [])),
        "calm":    strat_row(by_regime.get("Calm", [])),
        "normal":  strat_row(by_regime.get("Normal", [])),
        "stress":  strat_row(by_regime.get("Stress", [])),
    }


def print_summary(results):
    """Print all windows side-by-side in one block."""
    labels = [r["label"] for r in results]
    stats  = [r["stats"] for r in results]

    W = 14  # column width per year

    def hdr(title):
        print(f"\n  {title}")
        print(f"  {'':20}" + "".join(f"{l:>{W}}" for l in labels))
        print(f"  {'-'*( 20 + W * len(labels))}")

    def row(name, vals, fmt="{}", suffix=""):
        cells = "".join(f"{(fmt.format(v) + suffix):>{W}}" for v in vals)
        print(f"  {name:<20}{cells}")

    print("\n" + "=" * (20 + W * len(labels) + 2))
    print("  WINDOW DEBUG SUMMARY")
    print("=" * (20 + W * len(labels) + 2))

    # ── Overall ──────────────────────────────────────────────────────────────
    hdr("Overall")
    row("Trades",  [s["n"]   for s in stats], "{:d}")
    row("P&L ($)", [s["pnl"] for s in stats], "{:+,.0f}")
    row("Return",  [s["ret"] for s in stats], "{:+.1%}")
    row("Max DD",  [s["dd"]  for s in stats], "{:.1%}")

    total_pnl = sum(s["pnl"] for s in stats)
    print(f"\n  {'Net P&L (all)':20}" + f"  ${total_pnl:+,.0f}")

    # ── By strategy ──────────────────────────────────────────────────────────
    for strat_key, strat_name in [("orb", "ORB"), ("orb_fade", "ORB_FADE"), ("fade", "FADE"), ("tf", "TREND_FOLLOW"), ("vmr", "VWAP_MR"), ("gap_fill", "GAP_FILL"), ("gf_short", "GF_SHORT"), ("rs_short", "RS_SHORT"), ("stress_orb", "STRESS_ORB"), ("stress_mid", "STRESS_MID"), ("pe_short", "PE_SHORT")]:
        hdr(f"{strat_name}")
        row("Trades",     [s[strat_key][0] for s in stats], "{:d}")
        row("Win %",      [s[strat_key][1] for s in stats], "{:.1f}", "%")
        row("Avg P&L ($)",[s[strat_key][2] for s in stats], "{:+.2f}")
        row("Total ($)",  [s[strat_key][3] for s in stats], "{:+.0f}")

    # ── By regime ────────────────────────────────────────────────────────────
    hdr("Regime — trades")
    for reg_key, reg_name in [("calm","Calm"),("normal","Normal"),("stress","Stress")]:
        row(reg_name, [s[reg_key][0] for s in stats], "{:d}")

    print("\n" + "=" * (20 + W * len(labels) + 2))


def _check_option_b(trade, full_data, min_move_pct: float, max_hod_dist_pct: float) -> tuple:
    """
    Retroactively check if a TF trade would pass the Option B intraday filter.

    Criteria (evaluated using data from open -> 14:00 on entry day):
      1. Stock moved >= min_move_pct from open in the trade direction
      2. At 14:00, price is within max_hod_dist_pct of HOD (long) or LOD (short)

    Returns (passes: bool, move_pct: float, hod_dist_pct: float)
    """
    ticker = trade.ticker
    if ticker not in full_data:
        return True, 0.0, 0.0   # no data -> don't filter

    entry_day = pd.Timestamp(trade.entry_time).normalize()
    df = full_data[ticker]
    day_bars = df[df.index.normalize() == entry_day]
    pre14 = day_bars[day_bars.index.time < dtime(14, 0)]
    if pre14.empty or len(pre14) < 2:
        return True, 0.0, 0.0

    open_price = float(pre14.iloc[0]["open"])
    price_at14 = float(pre14.iloc[-1]["close"])
    hod = float(pre14["high"].max())
    lod = float(pre14["low"].min())

    if open_price <= 0:
        return True, 0.0, 0.0

    move_pct = (price_at14 - open_price) / open_price * 100

    if trade.direction == "LONG":
        directional_move = move_pct          # positive = moved up ✓
        hod_dist_pct = (hod - price_at14) / hod * 100 if hod > 0 else 0.0
        passes = (directional_move >= min_move_pct) and (hod_dist_pct <= max_hod_dist_pct)
    else:  # SHORT
        directional_move = -move_pct         # positive = moved down ✓
        hod_dist_pct = (price_at14 - lod) / price_at14 * 100 if price_at14 > 0 else 0.0
        passes = (directional_move >= min_move_pct) and (hod_dist_pct <= max_hod_dist_pct)

    return passes, directional_move, hod_dist_pct


def _prev_daily_close(full_data: dict, ticker: str, entry_day: pd.Timestamp) -> float:
    """Return last daily close strictly before entry_day."""
    if ticker not in full_data:
        return float("nan")
    try:
        df = full_data[ticker]
        prev = df.loc[df.index.normalize() < entry_day]
        if prev.empty:
            return float("nan")
        return float(prev.iloc[-1]["close"])
    except Exception:
        return float("nan")


def _analyze_cooldown(results, full_data):
    """Retroactively apply dynamic cooldown: after STOP_HIT, block same direction until
    daily close crosses back past stop price."""
    print(f"\n{'='*70}")
    print(f"  DYNAMIC COOLDOWN SIMULATION")
    print(f"  Trigger: STOP_HIT  |  Unblock: daily close crosses stop price")
    print(f"{'='*70}")
    print(f"  Note: retroactive — does not account for missed setups on other stocks")
    print(f"{'='*70}\n")

    total_orig = total_kept_pnl = 0.0
    total_n_orig = total_n_kept = 0

    for r in results:
        label = r["label"]
        tf_trades = sorted(
            [t for t in r["trades"] if t.strategy == "TREND_FOLLOW"],
            key=lambda t: t.entry_time,
        )
        if not tf_trades:
            continue

        # active_blocks: {ticker: {direction: stop_price}}
        active_blocks: dict = {}
        kept, filtered = [], []

        for t in tf_trades:
            ticker    = t.ticker
            direction = t.direction
            entry_day = pd.Timestamp(t.entry_time).normalize()
            pnl       = t.net_pnl or 0.0
            blocked   = False

            if ticker in active_blocks and direction in active_blocks[ticker]:
                block_stop = active_blocks[ticker][direction]
                prev_close = _prev_daily_close(full_data, ticker, entry_day)
                if not (prev_close != prev_close):  # not NaN
                    recovered = (prev_close > block_stop) if direction == "LONG" else (prev_close < block_stop)
                else:
                    recovered = False
                if recovered:
                    active_blocks[ticker].pop(direction)
                    if not active_blocks[ticker]:
                        active_blocks.pop(ticker)
                else:
                    blocked = True

            if blocked:
                filtered.append(t)
            else:
                kept.append(t)
                # Record block on stop hit
                if t.exit_reason == "STOP_HIT":
                    active_blocks.setdefault(ticker, {})[direction] = t.stop

        kept_pnl     = sum(t.net_pnl or 0.0 for t in kept)
        filtered_pnl = sum(t.net_pnl or 0.0 for t in filtered)
        orig_pnl     = sum(t.net_pnl or 0.0 for t in tf_trades)

        print(f"  [{label}] TF trades: {len(tf_trades)} -> kept {len(kept)}, filtered {len(filtered)}")
        print(f"         Original TF P&L:  ${orig_pnl:+,.0f}")
        print(f"         Filtered out P&L: ${filtered_pnl:+,.0f}  ({'would have saved' if filtered_pnl < 0 else 'would have lost'})")
        print(f"         Adjusted TF P&L:  ${kept_pnl:+,.0f}\n")

        if filtered:
            print(f"         Trades REMOVED by filter:")
            for t in sorted(filtered, key=lambda x: x.net_pnl or 0):
                pnl = t.net_pnl or 0.0
                d   = str(t.entry_time)[:10]
                print(f"           {d} {t.ticker:<6} {t.direction:<5} stop=${t.stop:.2f}  PnL=${pnl:+.0f}")
        print()

        total_orig     += orig_pnl
        total_kept_pnl += kept_pnl
        total_n_orig   += len(tf_trades)
        total_n_kept   += len(kept)

    print(f"  {'─'*50}")
    print(f"  Total TF trades:    {total_n_orig} -> {total_n_kept} kept")
    print(f"  Total TF P&L orig:  ${total_orig:+,.0f}")
    print(f"  Total TF P&L adj:   ${total_kept_pnl:+,.0f}")
    print(f"  Difference:         ${total_kept_pnl - total_orig:+,.0f}")
    print(f"{'='*70}\n")


def _compute_daily_adx(full_data: dict, ticker: str, as_of: pd.Timestamp, period: int = 14) -> float:
    """Compute ADX(period) from daily bars resampled from intraday data, up to (not including) as_of."""
    if ticker not in full_data:
        return 0.0
    try:
        df = full_data[ticker]
        daily = df.loc[df.index < as_of].resample("B").agg({
            "open": "first", "high": "max", "low": "min", "close": "last",
        }).dropna()
        if len(daily) < period + 1:
            return 0.0
        high, low, close = daily["high"], daily["low"], daily["close"]
        prev_close = close.shift(1)
        tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        up, down = high.diff(), -low.diff()
        plus_dm  = up.where((up > down) & (up > 0), 0.0)
        minus_dm = down.where((down > up) & (down > 0), 0.0)
        atr_s    = tr.ewm(span=period, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
        adx      = float(dx.ewm(span=period, adjust=False).mean().iloc[-1])
        return adx
    except Exception:
        return 0.0


def _analyze_adx(results, full_data, threshold: float = 20.0, period: int = 14):
    """Retroactively apply daily ADX filter to TF trades and show P&L impact."""
    print(f"\n{'='*70}")
    print(f"  ADX SIMULATION  (daily ADX({period}) >= {threshold:.0f})")
    print(f"{'='*70}")
    print(f"  Note: retroactive — does not account for missed setups on other stocks")
    print(f"{'='*70}\n")

    total_orig = total_kept_pnl = 0.0
    total_n_orig = total_n_kept = 0

    for r in results:
        label = r["label"]
        tf_trades = [t for t in r["trades"] if t.strategy == "TREND_FOLLOW"]
        if not tf_trades:
            continue

        kept, filtered = [], []
        kept_pnl = filtered_pnl = 0.0

        for t in tf_trades:
            entry_day = pd.Timestamp(t.entry_time).normalize()
            adx_val = _compute_daily_adx(full_data, t.ticker, entry_day, period)
            pnl = t.net_pnl or 0.0
            if adx_val >= threshold:
                kept.append((t, adx_val))
                kept_pnl += pnl
            else:
                filtered.append((t, adx_val))
                filtered_pnl += pnl

        orig_pnl = sum(t.net_pnl or 0.0 for t in tf_trades)
        print(f"  [{label}] TF trades: {len(tf_trades)} -> kept {len(kept)}, filtered {len(filtered)}")
        print(f"         Original TF P&L:  ${orig_pnl:+,.0f}")
        print(f"         Filtered out P&L: ${filtered_pnl:+,.0f}  ({'would have saved' if filtered_pnl < 0 else 'would have lost'})")
        print(f"         Adjusted TF P&L:  ${kept_pnl:+,.0f}\n")

        if filtered:
            print(f"         Trades REMOVED by filter:")
            for t, adx_val in sorted(filtered, key=lambda x: x[0].net_pnl or 0):
                pnl = t.net_pnl or 0.0
                d = str(t.entry_time)[:10]
                print(f"           {d} {t.ticker:<6} {t.direction:<5} ADX={adx_val:.1f}  PnL=${pnl:+.0f}")
        print()

        total_orig     += orig_pnl
        total_kept_pnl += kept_pnl
        total_n_orig   += len(tf_trades)
        total_n_kept   += len(kept)

    print(f"  {'─'*50}")
    print(f"  Total TF trades:    {total_n_orig} -> {total_n_kept} kept")
    print(f"  Total TF P&L orig:  ${total_orig:+,.0f}")
    print(f"  Total TF P&L adj:   ${total_kept_pnl:+,.0f}")
    print(f"  Difference:         ${total_kept_pnl - total_orig:+,.0f}")
    print(f"{'='*70}\n")


def _analyze_option_b(results, full_data, min_move_pct: float, max_hod_dist_pct: float):
    """Print what happens to TF P&L if Option B filter is applied retroactively."""
    print(f"\n{'='*70}")
    print(f"  OPTION B SIMULATION  (min_move={min_move_pct:.1f}%  max_hod_dist={max_hod_dist_pct:.1f}%)")
    print(f"{'='*70}")
    print(f"  Note: retroactive — does not account for missed setups on other stocks")
    print(f"{'='*70}\n")

    total_orig = total_filtered = 0.0
    total_n_orig = total_n_kept = 0

    for r in results:
        label = r["label"]
        tf_trades = [t for t in r["trades"] if t.strategy == "TREND_FOLLOW"]
        if not tf_trades:
            continue

        kept = filtered = []
        kept_pnl = filtered_pnl = 0.0
        kept, filtered = [], []

        for t in tf_trades:
            passes, move, dist = _check_option_b(t, full_data, min_move_pct, max_hod_dist_pct)
            pnl = t.net_pnl or 0.0
            if passes:
                kept.append((t, move, dist))
                kept_pnl += pnl
            else:
                filtered.append((t, move, dist))
                filtered_pnl += pnl

        orig_pnl = sum(t.net_pnl or 0.0 for t in tf_trades)
        print(f"  [{label}] TF trades: {len(tf_trades)} -> kept {len(kept)}, filtered {len(filtered)}")
        print(f"         Original TF P&L:  ${orig_pnl:+,.0f}")
        print(f"         Filtered out P&L: ${filtered_pnl:+,.0f}  ({'would have saved' if filtered_pnl < 0 else 'would have lost'})")
        print(f"         Adjusted TF P&L:  ${kept_pnl:+,.0f}\n")

        if filtered:
            print(f"         Trades REMOVED by filter:")
            for t, move, dist in sorted(filtered, key=lambda x: x[0].net_pnl or 0):
                pnl = t.net_pnl or 0.0
                d = str(t.entry_time)[:10]
                print(f"           {d} {t.ticker:<6} {t.direction:<5} "
                      f"move={move:+.1f}% hod_dist={dist:.1f}%  PnL=${pnl:+.0f}")
        print()

        total_orig      += orig_pnl
        total_filtered  += kept_pnl
        total_n_orig    += len(tf_trades)
        total_n_kept    += len(kept)

    print(f"  {'─'*50}")
    print(f"  Total TF trades:    {total_n_orig} -> {total_n_kept} kept")
    print(f"  Total TF P&L orig:  ${total_orig:+,.0f}")
    print(f"  Total TF P&L adj:   ${total_filtered:+,.0f}")
    print(f"  Difference:         ${total_filtered - total_orig:+,.0f}")
    print(f"{'='*70}\n")


def _analyze_orb_spy_alignment(results, full_data):
    """Retroactive sim: filter ORB trades where direction mismatches SPY intraday move."""
    print(f"\n{'='*70}")
    print(f"  ORB SPY ALIGNMENT SIMULATION")
    print(f"  Rule: LONG ORB only when SPY > open; SHORT ORB only when SPY < open")
    print(f"{'='*70}\n")

    spy_data = full_data.get("SPY", pd.DataFrame())
    total_orig = total_kept_pnl = 0.0
    total_n_orig = total_n_kept = 0

    for r in results:
        label = r["label"]
        orb_trades = [t for t in r["trades"] if t.strategy == "ORB"]
        if not orb_trades:
            continue

        kept, filtered = [], []
        for t in orb_trades:
            entry_ts  = pd.Timestamp(t.entry_time)
            entry_day = entry_ts.normalize()
            day_spy   = spy_data[spy_data.index.normalize() == entry_day]
            if day_spy.empty:
                kept.append(t); continue

            spy_open = float(day_spy.iloc[0]["open"])
            bars_to_entry = day_spy[day_spy.index <= entry_ts]
            if bars_to_entry.empty:
                kept.append(t); continue

            spy_at_entry = float(bars_to_entry.iloc[-1]["close"])
            spy_up = spy_at_entry > spy_open

            aligned = (t.direction == "LONG" and spy_up) or \
                      (t.direction == "SHORT" and not spy_up)
            (kept if aligned else filtered).append(t)

        orig_pnl = sum(t.net_pnl or 0 for t in orb_trades)
        kept_pnl = sum(t.net_pnl or 0 for t in kept)
        filt_pnl = sum(t.net_pnl or 0 for t in filtered)

        print(f"  [{label}] {len(orb_trades)} trades -> kept {len(kept)}, filtered {len(filtered)}")
        print(f"         Original P&L:  ${orig_pnl:+,.0f}")
        print(f"         Filtered P&L:  ${filt_pnl:+,.0f}")
        print(f"         Adjusted P&L:  ${kept_pnl:+,.0f}\n")

        if filtered:
            print(f"         Removed trades:")
            for t in sorted(filtered, key=lambda x: x.net_pnl or 0):
                d   = str(t.entry_time)[:10]
                pnl = t.net_pnl or 0
                print(f"           {d} {t.ticker:<6} {t.direction:<5} ${pnl:+.0f}")
        print()

        total_orig     += orig_pnl
        total_kept_pnl += kept_pnl
        total_n_orig   += len(orb_trades)
        total_n_kept   += len(kept)

    print(f"  {'─'*50}")
    print(f"  Total ORB: {total_n_orig} -> {total_n_kept} kept")
    print(f"  P&L orig:  ${total_orig:+,.0f}")
    print(f"  P&L adj:   ${total_kept_pnl:+,.0f}")
    print(f"  Delta:     ${total_kept_pnl - total_orig:+,.0f}")
    print(f"{'='*70}\n")


def _analyze_vmr_etf(results):
    """Retroactive sim: keep only VWAP_MR trades on ETF tickers."""
    ETF_TICKERS = {"QQQ", "IWM", "XLF", "XLE", "XLV", "XLU", "XLI"}

    print(f"\n{'='*70}")
    print(f"  VWAP_MR ETF-ONLY SIMULATION")
    print(f"  Keep: {sorted(ETF_TICKERS)}")
    print(f"{'='*70}\n")

    total_orig = total_kept = 0.0
    total_n_orig = total_n_kept = 0

    for r in results:
        label      = r["label"]
        vmr_trades = [t for t in r["trades"] if t.strategy == "VWAP_MR"]
        if not vmr_trades:
            continue

        kept     = [t for t in vmr_trades if t.ticker in ETF_TICKERS]
        filtered = [t for t in vmr_trades if t.ticker not in ETF_TICKERS]

        orig_pnl = sum(t.net_pnl or 0 for t in vmr_trades)
        kept_pnl = sum(t.net_pnl or 0 for t in kept)
        filt_pnl = sum(t.net_pnl or 0 for t in filtered)
        orig_wr  = sum(1 for t in vmr_trades if (t.net_pnl or 0) > 0) / len(vmr_trades) * 100
        kept_wr  = sum(1 for t in kept if (t.net_pnl or 0) > 0) / len(kept) * 100 if kept else 0

        # Exit reason breakdown for kept trades
        from collections import Counter
        kept_reasons = Counter(t.exit_reason for t in kept)

        print(f"  [{label}] {len(vmr_trades)} trades -> ETF {len(kept)}, stocks {len(filtered)}")
        print(f"         Original  P&L: ${orig_pnl:>+7,.0f}   WR: {orig_wr:.0f}%")
        print(f"         ETF-only  P&L: ${kept_pnl:>+7,.0f}   WR: {kept_wr:.0f}%  exits: {dict(kept_reasons)}")
        print(f"         Stocks    P&L: ${filt_pnl:>+7,.0f}")
        print()

        total_orig   += orig_pnl
        total_kept   += kept_pnl
        total_n_orig += len(vmr_trades)
        total_n_kept += len(kept)

    print(f"  {'─'*50}")
    print(f"  Total VMR:  {total_n_orig} -> ETF {total_n_kept}, stocks {total_n_orig - total_n_kept}")
    print(f"  P&L orig:   ${total_orig:+,.0f}")
    print(f"  P&L ETF:    ${total_kept:+,.0f}")
    print(f"  Delta:      ${total_kept - total_orig:+,.0f}")
    print(f"{'='*70}\n")


def _analyze_vmr_spy(results, full_data):
    """
    Retroactive sim: filter VWAP_MR trades where SPY direction opposes trade.
    Rule: LONG only when SPY >= SPY_VWAP at entry time (market not pulling stock down).
          SHORT only when SPY <= SPY_VWAP at entry time (market not pushing stock up).
    VWAP computed from session open (9:30) to entry bar.
    """
    spy_data = full_data.get("SPY", pd.DataFrame())
    spy_idx  = spy_data.index.tz_localize(None) if spy_data.index.tzinfo else spy_data.index

    print(f"\n{'='*70}")
    print(f"  VWAP_MR SPY VWAP ALIGNMENT SIMULATION")
    print(f"  Rule: LONG only when SPY >= SPY_VWAP; SHORT only when SPY <= SPY_VWAP")
    print(f"{'='*70}\n")

    total_orig = total_kept = 0.0
    total_n_orig = total_n_kept = 0

    for r in results:
        label      = r["label"]
        vmr_trades = [t for t in r["trades"] if t.strategy == "VWAP_MR"]
        if not vmr_trades:
            continue

        kept, filtered = [], []
        for t in vmr_trades:
            entry_ts  = pd.Timestamp(t.entry_time)
            if entry_ts.tzinfo:
                entry_ts = entry_ts.tz_localize(None)
            entry_day = entry_ts.normalize()

            # SPY bars from session open to entry bar
            session_start = entry_day + pd.Timedelta(hours=9, minutes=30)
            spy_session   = spy_data[(spy_idx >= session_start) & (spy_idx <= entry_ts)]
            if spy_session.empty:
                kept.append(t); continue

            # SPY VWAP from open to entry
            tp  = (spy_session["high"] + spy_session["low"] + spy_session["close"]) / 3
            spy_vwap     = float((tp * spy_session["volume"]).sum() / spy_session["volume"].sum())
            spy_price    = float(spy_session.iloc[-1]["close"])

            spy_above_vwap = spy_price >= spy_vwap
            aligned = (t.direction == "LONG"  and spy_above_vwap) or \
                      (t.direction == "SHORT" and not spy_above_vwap)
            (kept if aligned else filtered).append(t)

        orig_pnl = sum(t.net_pnl or 0 for t in vmr_trades)
        kept_pnl = sum(t.net_pnl or 0 for t in kept)
        filt_pnl = sum(t.net_pnl or 0 for t in filtered)
        orig_wr  = sum(1 for t in vmr_trades if (t.net_pnl or 0) > 0) / len(vmr_trades) * 100
        kept_wr  = sum(1 for t in kept if (t.net_pnl or 0) > 0) / len(kept) * 100 if kept else 0

        print(f"  [{label}] {len(vmr_trades)} trades -> kept {len(kept)}, filtered {len(filtered)}")
        print(f"         Original  P&L: ${orig_pnl:>+7,.0f}   WR: {orig_wr:.0f}%")
        print(f"         Aligned   P&L: ${kept_pnl:>+7,.0f}   WR: {kept_wr:.0f}%")
        print(f"         Filtered  P&L: ${filt_pnl:>+7,.0f}")
        print()

        total_orig   += orig_pnl
        total_kept   += kept_pnl
        total_n_orig += len(vmr_trades)
        total_n_kept += len(kept)

    print(f"  {'─'*50}")
    print(f"  Total VMR: {total_n_orig} -> {total_n_kept} kept")
    print(f"  P&L orig:  ${total_orig:+,.0f}")
    print(f"  P&L adj:   ${total_kept:+,.0f}")
    print(f"  Delta:     ${total_kept - total_orig:+,.0f}")
    print(f"{'='*70}\n")


def _analyze_vmr_stop(results, full_data):
    """
    Retroactive sim: replay VWAP_MR trades with wider stops, using intraday bars.
    Tests vs current 1.5×ATR(5min):
      - atr_3x      : 3.0×ATR  (same basis, 2× wider, position halved)
      - structural  : prev_bar extreme + 0.5×ATR buffer (signal invalidation level)
    Position sizing adjusted proportionally to maintain same dollar risk.
    """
    import pandas as pd

    sim_keys = ["atr_3x", "structural"]

    print("\n" + "=" * 72)
    print("  VWAP_MR STOP SIMULATION")
    print("  Current: 1.5×ATR(5min)  |  Test: 3.0×ATR, Structural (prev_bar extreme)")
    print("=" * 72)

    grand = {"orig": 0.0, **{k: 0.0 for k in sim_keys}}
    grand_stop_hits = {"orig": 0, **{k: 0 for k in sim_keys}}
    grand_n = 0

    for r in results:
        vmr_trades = [t for t in r["trades"] if t.strategy == "VWAP_MR"]
        if not vmr_trades:
            continue

        label    = r["label"]
        orig_pnl = sum(t.net_pnl or 0 for t in vmr_trades)
        orig_wr  = sum(1 for t in vmr_trades if (t.net_pnl or 0) > 0) / len(vmr_trades) * 100
        orig_sh  = sum(1 for t in vmr_trades if t.exit_reason == "STOP_HIT")
        grand["orig"] += orig_pnl
        grand_n += len(vmr_trades)
        grand_stop_hits["orig"] += orig_sh

        sim_pnls      = {k: [] for k in sim_keys}
        sim_stop_hits = {k: 0  for k in sim_keys}

        for t in vmr_trades:
            dir_sign  = 1 if t.direction == "LONG" else -1
            stop_dist = abs(t.entry_price - t.stop)   # current = 1.5×ATR
            atr       = stop_dist / 1.5                # back-compute 5-min ATR

            bars = full_data.get(t.ticker, pd.DataFrame())
            if bars.empty or atr < 1e-6:
                for k in sim_keys:
                    sim_pnls[k].append(t.net_pnl or 0)
                continue

            bars_idx = bars.index.tz_localize(None) if bars.index.tzinfo else bars.index
            entry_ts = pd.Timestamp(t.entry_time)
            if entry_ts.tzinfo:
                entry_ts = entry_ts.tz_localize(None)

            # Prev bar: 5-min bar immediately before entry (confirmation bar)
            prev_ts   = entry_ts - pd.Timedelta(minutes=5)
            same_day  = bars_idx.normalize() == entry_ts.normalize()
            prev_bars = bars[(bars_idx <= prev_ts) & same_day]

            # Session: from entry to end of VWAP_MR window (14:00)
            day_end = entry_ts.normalize() + pd.Timedelta(hours=14)
            session = bars[(bars_idx >= entry_ts) & (bars_idx <= day_end)]

            # Build new stop levels
            stops = {}
            stops["atr_3x"] = t.entry_price - dir_sign * (3.0 * atr)
            if not prev_bars.empty:
                pb = prev_bars.iloc[-1]
                if dir_sign == 1:   # LONG: stop below prev_bar low
                    stops["structural"] = pb["low"] - 0.5 * atr
                else:               # SHORT: stop above prev_bar high
                    stops["structural"] = pb["high"] + 0.5 * atr
            else:
                stops["structural"] = stops["atr_3x"]

            for k in sim_keys:
                new_stop      = stops[k]
                new_stop_dist = abs(t.entry_price - new_stop)
                if new_stop_dist < 1e-6:
                    sim_pnls[k].append(t.net_pnl or 0)
                    continue

                # Proportional share adjustment to keep dollar risk constant
                new_shares = max(1, min(t.shares, round(t.shares * stop_dist / new_stop_dist)))

                new_exit_px   = None
                new_exit_rsn  = "TIME_STOP"
                for _, bar in session.iterrows():
                    if dir_sign == 1:   # LONG
                        if bar["low"] <= new_stop:
                            new_exit_px = new_stop;  new_exit_rsn = "STOP_HIT"; break
                        if bar["high"] >= t.target:
                            new_exit_px = t.target;  new_exit_rsn = "TARGET_HIT"; break
                    else:               # SHORT
                        if bar["high"] >= new_stop:
                            new_exit_px = new_stop;  new_exit_rsn = "STOP_HIT"; break
                        if bar["low"] <= t.target:
                            new_exit_px = t.target;  new_exit_rsn = "TARGET_HIT"; break

                if new_exit_px is None:
                    # Neither stop nor target hit by 14:00 — exit at last bar close
                    new_exit_px = float(session.iloc[-1]["close"]) if not session.empty else t.exit_price

                if new_exit_rsn == "STOP_HIT":
                    sim_stop_hits[k] += 1

                new_gross = new_shares * (new_exit_px - t.entry_price) * dir_sign
                new_net   = new_gross - (t.total_costs or 0)
                sim_pnls[k].append(new_net)
                grand_stop_hits[k] += (1 if new_exit_rsn == "STOP_HIT" else 0)

        print(f"\n  [{label}] VWAP_MR — {len(vmr_trades)} trades  (original STOP_HIT: {orig_sh})")
        print(f"  {'':28} {'P&L':>9} {'Avg/trade':>10} {'WR':>7} {'STOP_HIT':>10}  {'vs orig':>9}")
        print(f"  {'─'*76}")
        print(f"  {'Original (1.5×ATR stop)':<28} ${orig_pnl:>+8,.0f} ${orig_pnl/len(vmr_trades):>+9,.0f} {orig_wr:>6.1f}% {orig_sh:>10}")
        for k in sim_keys:
            pnls  = sim_pnls[k]
            total = sum(pnls)
            wr    = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            sh    = sim_stop_hits[k]
            delta = total - orig_pnl
            grand[k] += total
            print(f"  {k:<28} ${total:>+8,.0f} ${total/len(pnls):>+9,.0f} {wr:>6.1f}% {sh:>10}  {delta:>+9,.0f}")

    print(f"\n  {'─'*76}")
    print(f"  {'TOTAL ({} trades)'.format(grand_n):<28} ${grand['orig']:>+8,.0f}  STOP_HIT: {grand_stop_hits['orig']}")
    for k in sim_keys:
        delta = grand[k] - grand["orig"]
        sh    = grand_stop_hits[k]
        print(f"  {'  ' + k:<28} ${grand[k]:>+8,.0f}   ({delta:>+,.0f} vs orig)  STOP_HIT: {sh}")
    print(f"{'='*72}\n")


def _analyze_vmr_rr(results, full_data, rr_ratios=(1.5, 2.0)):
    """Sim VWAP_MR with fixed R:R targets instead of VWAP, using intraday bars."""
    import pandas as pd

    print("\n" + "=" * 72)
    print("  VWAP_MR R:R SIMULATION")
    print("  Current: VWAP target (variable R:R)  |  Test: fixed 1.5R and 2.0R")
    print("=" * 72)

    grand = {"orig": 0.0, **{rr: 0.0 for rr in rr_ratios}}
    grand_n = 0

    for r in results:
        vmr_trades = [t for t in r["trades"] if t.strategy == "VWAP_MR"]
        if not vmr_trades:
            continue

        label = r["label"]
        orig_pnl = sum(t.net_pnl or 0 for t in vmr_trades)
        orig_wr  = sum(1 for t in vmr_trades if (t.net_pnl or 0) > 0) / len(vmr_trades) * 100
        grand["orig"] += orig_pnl
        grand_n       += len(vmr_trades)

        sim_pnls = {rr: [] for rr in rr_ratios}

        for t in vmr_trades:
            stop_dist = abs(t.entry_price - t.stop)
            dir_sign  = 1 if t.direction == "LONG" else -1

            # Get intraday bars from entry bar onward (same day until 15:55)
            bars = full_data.get(t.ticker, pd.DataFrame())
            if bars.empty or stop_dist < 1e-6:
                for rr in rr_ratios:
                    sim_pnls[rr].append(t.net_pnl or 0)
                continue

            entry_ts = pd.Timestamp(t.entry_time).tz_localize(None) if pd.Timestamp(t.entry_time).tzinfo else pd.Timestamp(t.entry_time)
            bars_idx  = bars.index.tz_localize(None) if bars.index.tzinfo else bars.index
            day_end   = entry_ts.normalize() + pd.Timedelta(hours=15, minutes=55)
            session   = bars[(bars_idx >= entry_ts) & (bars_idx <= day_end)]

            for rr in rr_ratios:
                new_tgt = t.entry_price + dir_sign * rr * stop_dist
                new_exit_px = t.exit_price  # fallback: same exit as actual

                for _, bar in session.iterrows():
                    if dir_sign == 1:  # LONG: stop below, target above
                        if bar["low"] <= t.stop:
                            new_exit_px = t.stop; break
                        if bar["high"] >= new_tgt:
                            new_exit_px = new_tgt; break
                    else:              # SHORT: stop above, target below
                        if bar["high"] >= t.stop:
                            new_exit_px = t.stop; break
                        if bar["low"] <= new_tgt:
                            new_exit_px = new_tgt; break

                new_gross = t.shares * (new_exit_px - t.entry_price) * dir_sign
                new_net   = new_gross - (t.total_costs or 0)
                sim_pnls[rr].append(new_net)

        # Print per-window table
        print(f"\n  [{label}] VWAP_MR — {len(vmr_trades)} trades")
        print(f"  {'':28} {'P&L':>9} {'Avg/trade':>10} {'WR':>7}  {'vs VWAP':>9}")
        print(f"  {'─'*68}")
        print(f"  {'Original (VWAP target)':<28} ${orig_pnl:>+8,.0f} ${orig_pnl/len(vmr_trades):>+9,.0f} {orig_wr:>6.1f}%")
        for rr in rr_ratios:
            pnls  = sim_pnls[rr]
            total = sum(pnls)
            wr    = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            delta = total - orig_pnl
            grand[rr] += total
            print(f"  {'Fixed R:R ' + str(rr):<28} ${total:>+8,.0f} ${total/len(pnls):>+9,.0f} {wr:>6.1f}%  {delta:>+9,.0f}")

    print(f"\n  {'─'*68}")
    print(f"  {'TOTAL ({} trades)'.format(grand_n):<28} ${grand['orig']:>+8,.0f}")
    for rr in rr_ratios:
        delta = grand[rr] - grand["orig"]
        print(f"  {'  Fixed R:R ' + str(rr):<28} ${grand[rr]:>+8,.0f}   ({delta:>+,.0f} vs VWAP)")
    print(f"{'='*72}\n")


def _analyze_orb_fade_stop(results, full_data):
    """
    Retroactive sim: replay ORB_FADE trades with stop anchored to bar-B breakout close.

    Current stop: or_high * 1.005 (FADE SHORT) / or_low * 0.995 (FADE LONG)
    New stop:     bar_B_close * 1.005 / * 0.995  — bar immediately before FADE entry.

    Bar B is 5 min before entry_time. Stop is wider when the breakout bar closed
    significantly outside the OR, narrower when close to the boundary.
    Target recalculated as 2R from new risk. Shares scaled to maintain same $ risk.
    """
    import pandas as pd

    print("\n" + "=" * 72)
    print("  ORB_FADE STOP SIMULATION")
    print("  Current: or_high/low * 1.005/0.995  (OR boundary + 0.5%)")
    print("  New:     bar_B_close * 1.005/0.995  (breakout-bar close + 0.5%)")
    print("=" * 72)

    grand_orig = grand_new = 0.0
    grand_n = grand_sh_orig = grand_sh_new = 0
    grand_skip = 0

    for r in results:
        fade_trades = [t for t in r["trades"] if t.strategy == "ORB_FADE"]
        if not fade_trades:
            continue

        label    = r["label"]
        orig_pnl = sum(t.net_pnl or 0 for t in fade_trades)
        orig_wr  = sum(1 for t in fade_trades if (t.net_pnl or 0) > 0) / len(fade_trades) * 100
        orig_sh  = sum(1 for t in fade_trades if t.exit_reason == "STOP_HIT")
        grand_orig  += orig_pnl
        grand_n     += len(fade_trades)
        grand_sh_orig += orig_sh

        new_pnls = []
        new_sh   = 0
        skip     = 0

        for t in fade_trades:
            dir_sign = 1 if t.direction == "LONG" else -1

            bars = full_data.get(t.ticker, pd.DataFrame())
            if bars.empty:
                new_pnls.append(t.net_pnl or 0); skip += 1; continue

            bars_idx = bars.index.tz_localize(None) if bars.index.tzinfo else bars.index
            entry_ts = pd.Timestamp(t.entry_time)
            if entry_ts.tzinfo:
                entry_ts = entry_ts.tz_localize(None)

            # Bar B: 5-min bar immediately before FADE entry (the breakout bar)
            bar_b_ts      = entry_ts - pd.Timedelta(minutes=5)
            bar_b_matches = bars[bars_idx == bar_b_ts]
            if bar_b_matches.empty:
                new_pnls.append(t.net_pnl or 0); skip += 1; continue

            bar_b_close = float(bar_b_matches.iloc[-1]["close"])

            # New stop: 0.5% beyond the breakout bar close
            if t.direction == "SHORT":   # LONG breakout failed → fade SHORT
                new_stop = bar_b_close * 1.005
            else:                        # SHORT breakout failed → fade LONG
                new_stop = bar_b_close * 0.995

            current_risk = abs(t.entry_price - t.stop)
            new_risk     = abs(t.entry_price - new_stop)

            if new_risk < 1e-6:
                new_pnls.append(t.net_pnl or 0); skip += 1; continue

            # 2R target from new risk
            new_target = round(t.entry_price - dir_sign * 2.0 * new_risk, 2)

            # Scale shares to maintain same dollar risk
            new_shares = max(1, round(t.shares * current_risk / new_risk))

            # Replay from FADE entry to EOD
            day_end = entry_ts.normalize() + pd.Timedelta(hours=16)
            session = bars[(bars_idx >= entry_ts) & (bars_idx <= day_end)]

            new_exit_px  = None
            new_exit_rsn = "EOD"

            for _, bar in session.iterrows():
                if t.direction == "SHORT":
                    if bar["high"] >= new_stop:
                        new_exit_px = new_stop;   new_exit_rsn = "STOP_HIT";   break
                    if bar["low"]  <= new_target:
                        new_exit_px = new_target; new_exit_rsn = "TARGET_HIT"; break
                else:
                    if bar["low"]  <= new_stop:
                        new_exit_px = new_stop;   new_exit_rsn = "STOP_HIT";   break
                    if bar["high"] >= new_target:
                        new_exit_px = new_target; new_exit_rsn = "TARGET_HIT"; break

            if new_exit_px is None:
                new_exit_px = float(session.iloc[-1]["close"]) if not session.empty else t.exit_price

            if new_exit_rsn == "STOP_HIT":
                new_sh += 1; grand_sh_new += 1

            new_gross = new_shares * (new_exit_px - t.entry_price) * dir_sign
            new_net   = new_gross - (t.total_costs or 0)
            new_pnls.append(new_net)

        new_total = sum(new_pnls)
        new_wr    = sum(1 for p in new_pnls if p > 0) / len(new_pnls) * 100 if new_pnls else 0
        grand_new  += new_total
        grand_skip += skip

        W = 34
        print(f"\n  [{label}] ORB_FADE — {len(fade_trades)} trades  (orig STOP_HIT: {orig_sh}, skipped: {skip})")
        print(f"  {'':>{W}} {'P&L':>9} {'Avg/trade':>10} {'WR':>7} {'SH':>5}  {'Δ vs orig':>10}")
        print(f"  {'─'*76}")
        print(f"  {'Original (or_high/low boundary)':<{W}} ${orig_pnl:>+8,.0f} ${orig_pnl/len(fade_trades):>+9,.0f} {orig_wr:>6.1f}% {orig_sh:>4}")
        print(f"  {'New (bar_B_close ±0.5%)':<{W}} ${new_total:>+8,.0f} ${new_total/max(len(new_pnls),1):>+9,.0f} {new_wr:>6.1f}% {new_sh:>4}  {new_total-orig_pnl:>+9,.0f}")

    print(f"\n  {'─'*76}")
    print(f"  TOTAL ({grand_n} trades, {grand_skip} skipped — bar B not found)")
    print(f"  {'Original':<34} ${grand_orig:>+8,.0f}  STOP_HIT: {grand_sh_orig}")
    print(f"  {'New (bar_B_close ±0.5%)':<34} ${grand_new:>+8,.0f}  STOP_HIT: {grand_sh_new}  ({grand_new-grand_orig:>+,.0f} vs orig)")
    print(f"{'='*72}\n")


def _analyze_orb_fade_mfe(results, full_data):
    """
    MFE/MAE analysis for ORB_FADE trades using 5-min intraday bars.

    For each trade, measures how far price moved in the favorable vs adverse
    direction from entry to exit. Expressed in both $ and R (multiples of stop dist).

    Key question: does price ever go in our direction meaningfully before stopping out?
    If avg MFE_R < 1.0 across losing trades → no intraday edge, direction is wrong.
    If avg MFE_R > 1.0 → trades have favorable excursions but exit logic is suboptimal.
    """
    import pandas as pd

    print("\n" + "=" * 80)
    print("  ORB_FADE MFE / MAE ANALYSIS")
    print("  MFE = Max Favorable Excursion  |  MAE = Max Adverse Excursion")
    print("  Expressed in R (multiples of stop distance).  Target = 2.0R.")
    print("=" * 80)

    all_mfe_r, all_mae_r = [], []
    all_mfe_r_wins, all_mfe_r_losses = [], []

    for r in results:
        fade_trades = [t for t in r["trades"] if t.strategy == "ORB_FADE"]
        if not fade_trades:
            continue

        label = r["label"]
        print(f"\n  [{label}] — {len(fade_trades)} trades")
        print(f"  {'Date':<12} {'Ticker':<6} {'Dir':<6} {'Stop_R':>7} {'MFE_R':>7} {'MAE_R':>7} {'Exit':<14} {'PnL':>8}")
        print(f"  {'─'*72}")

        for t in fade_trades:
            dir_sign  = 1 if t.direction == "LONG" else -1
            stop_dist = abs(t.entry_price - t.stop)
            if stop_dist < 1e-6:
                continue

            bars = full_data.get(t.ticker, pd.DataFrame())
            if bars.empty:
                print(f"  {str(t.entry_time.date()):<12} {t.ticker:<6} {t.direction:<6}  (no bar data)")
                continue

            bars_idx = bars.index.tz_localize(None) if bars.index.tzinfo else bars.index
            entry_ts = pd.Timestamp(t.entry_time)
            if entry_ts.tzinfo:
                entry_ts = entry_ts.tz_localize(None)

            exit_ts = pd.Timestamp(t.exit_time) if t.exit_time else None
            if exit_ts and exit_ts.tzinfo:
                exit_ts = exit_ts.tz_localize(None)

            # Bars from entry to exit (inclusive)
            if exit_ts:
                session = bars[(bars_idx >= entry_ts) & (bars_idx <= exit_ts)]
            else:
                day_end = entry_ts.normalize() + pd.Timedelta(hours=16)
                session = bars[(bars_idx >= entry_ts) & (bars_idx <= day_end)]

            if session.empty:
                print(f"  {str(t.entry_time.date()):<12} {t.ticker:<6} {t.direction:<6}  (no session bars)")
                continue

            # MFE: furthest price went in favorable direction (vs entry)
            # MAE: furthest price went in adverse direction (vs entry)
            if t.direction == "LONG":
                mfe = float((session["high"] - t.entry_price).clip(lower=0).max())
                mae = float((t.entry_price - session["low"]).clip(lower=0).max())
            else:  # SHORT
                mfe = float((t.entry_price - session["low"]).clip(lower=0).max())
                mae = float((session["high"] - t.entry_price).clip(lower=0).max())

            mfe_r = mfe / stop_dist
            mae_r = mae / stop_dist
            is_win = (t.net_pnl or 0) > 0

            all_mfe_r.append(mfe_r)
            all_mae_r.append(mae_r)
            if is_win:
                all_mfe_r_wins.append(mfe_r)
            else:
                all_mfe_r_losses.append(mfe_r)

            win_tag = "W" if is_win else " "
            print(f"  {str(t.entry_time.date()):<12} {t.ticker:<6} {t.direction:<6} {1.0:>6.1f}R {mfe_r:>6.2f}R {mae_r:>6.2f}R {t.exit_reason:<14} ${t.net_pnl:>+6.0f} {win_tag}")

        # Per-window summary
        wins  = [t for t in fade_trades if (t.net_pnl or 0) > 0]
        losses= [t for t in fade_trades if (t.net_pnl or 0) <= 0]
        if fade_trades:
            w_mfe = [all_mfe_r[-(len(fade_trades)-i)] for i in range(len(fade_trades)) if (fade_trades[i].net_pnl or 0) > 0]
            l_mfe = [all_mfe_r[-(len(fade_trades)-i)] for i in range(len(fade_trades)) if (fade_trades[i].net_pnl or 0) <= 0]

    # Global summary
    print(f"\n  {'─'*72}")
    print(f"  AGGREGATE ({len(all_mfe_r)} trades total)")
    if all_mfe_r:
        print(f"  Avg MFE_R : {sum(all_mfe_r)/len(all_mfe_r):.2f}R   (how far price went IN our favor)")
        print(f"  Avg MAE_R : {sum(all_mae_r)/len(all_mae_r):.2f}R   (how far price went AGAINST us)")
        print(f"  MFE≥1R    : {sum(1 for x in all_mfe_r if x >= 1.0)}/{len(all_mfe_r)} trades price reached ≥1R favorable")
        print(f"  MFE≥2R    : {sum(1 for x in all_mfe_r if x >= 2.0)}/{len(all_mfe_r)} trades price reached target (≥2R)")
        print(f"  MAE≥1R    : {sum(1 for x in all_mae_r if x >= 1.0)}/{len(all_mae_r)} trades price hit stop or beyond")
    if all_mfe_r_wins:
        print(f"\n  Wins  ({len(all_mfe_r_wins)}): avg MFE_R = {sum(all_mfe_r_wins)/len(all_mfe_r_wins):.2f}R")
    if all_mfe_r_losses:
        print(f"  Losses({len(all_mfe_r_losses)}): avg MFE_R = {sum(all_mfe_r_losses)/len(all_mfe_r_losses):.2f}R  ← key diagnostic")
        print(f"  {'':10} If avg MFE_R (losses) < 0.5R → price barely moved in our favor → no directional edge")
    print(f"{'='*80}\n")


def save_tf_baseline(results):
    """Save current TF per-window stats as the locked baseline."""
    baseline = {}
    for r in results:
        tf = r["stats"]["tf"]  # (n, win_pct, avg_pnl, total_pnl)
        baseline[r["label"]] = {"trades": tf[0], "win_pct": round(tf[1], 1), "total_pnl": round(tf[3], 0)}
    with open(TF_BASELINE_FILE, "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"\n  [TF baseline saved -> {os.path.basename(TF_BASELINE_FILE)}]")
    for label, b in baseline.items():
        print(f"  {label}: {b['trades']} trades, {b['win_pct']}% WR, ${b['total_pnl']:+,.0f}")


def check_tf_baseline(results):
    """Compare current TF results vs saved baseline. Warn on regression."""
    if not os.path.exists(TF_BASELINE_FILE):
        return
    with open(TF_BASELINE_FILE) as f:
        baseline = json.load(f)

    W = 10
    print(f"\n  {'─'*55}")
    print(f"  TF BASELINE CHECK")
    print(f"  {'':22}" + "".join(f"{l:>{W}}" for l in [r['label'] for r in results]))
    print(f"  {'─'*55}")

    regressions = []
    for metric, key, fmt, tol in [
        ("Trades (base)",   "trades",    "{:>10}",    2),
        ("Trades (now)",    None,        "{:>10}",    None),
        ("P&L (base) $",   "total_pnl", "{:>+10,.0f}", 150),
        ("P&L (now)  $",   None,        "{:>+10,.0f}", None),
    ]:
        if key is not None:
            vals = [baseline.get(r["label"], {}).get(key, "?") for r in results]
        else:
            prev_key = "trades" if "Trades" in metric else "total_pnl"
            now_vals, base_vals = [], []
            for r in results:
                tf = r["stats"]["tf"]
                now = tf[0] if prev_key == "trades" else tf[3]
                base = baseline.get(r["label"], {}).get(prev_key, now)
                now_vals.append(now)
                base_vals.append(base)
            vals = now_vals
            for i, (r, now, base) in enumerate(zip(results, now_vals, base_vals)):
                delta = now - base
                if tol and delta < -tol:
                    regressions.append(f"{r['label']} {prev_key}: {base} -> {now} ({delta:+})")

        cells = "".join(fmt.format(v) for v in vals)
        print(f"  {metric:<22}{cells}")

    if regressions:
        print(f"\n  *** TF REGRESSION DETECTED ***")
        for msg in regressions:
            print(f"  ! {msg}")
    else:
        print(f"\n  TF baseline OK")
    print(f"  {'─'*55}")


def _run_window(args):
    """Top-level worker for ProcessPoolExecutor (must be picklable on Windows)."""
    test_start, test_end, label, cfg_base, oos_data, daily_data = args
    cfg = BacktestConfig(start_date=test_start, end_date=test_end, **cfg_base)
    result = BacktestEngine(cfg).run(oos_data, daily_data=daily_data)
    eq    = result.equity_curve
    eq_s  = float(eq.iloc[0])  if not eq.empty else cfg_base.get("account_equity", 50_000.0)
    eq_e  = float(eq.iloc[-1]) if not eq.empty else eq_s
    max_dd = result.metrics.get("max_drawdown", 0.0)
    return {
        "label":  label,
        "stats":  collect_stats(result.trade_log, eq_s, eq_e, max_dd),
        "trades": result.trade_log,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-swing", action="store_true",
                        help="Disable swing hold — TF closes EOD every day (Option A)")
    parser.add_argument("--no-scanner", action="store_true",
                        help="Use fixed 8-stock universe (disable DailyUniverseScanner)")
    parser.add_argument("--rebuild-cache", action="store_true",
                        help="Force reload from parquets and rebuild pickle cache")
    parser.add_argument("--year", type=int, default=None,
                        help="Run only a specific year (e.g. --year 2021). Skips the other windows.")
    parser.add_argument("--top-n", type=int, default=15,
                        help="Scanner top-N stocks per day (default: 15)")
    parser.add_argument("--analyze-b", action="store_true",
                        help="Retroactively apply Option B intraday filter to TF trades")
    parser.add_argument("--min-move-pct", type=float, default=0.5,
                        help="Option B: min %% move from open by 14:00 (default: 0.5)")
    parser.add_argument("--max-hod-dist-pct", type=float, default=1.0,
                        help="Option B: max %% from HOD/LOD at 14:00 (default: 1.0)")
    parser.add_argument("--analyze-adx", action="store_true",
                        help="Retroactively apply daily ADX filter to TF trades")
    parser.add_argument("--adx-threshold", type=float, default=20.0,
                        help="ADX: minimum daily ADX(14) required for TF entry (default: 20)")
    parser.add_argument("--analyze-cooldown", action="store_true",
                        help="Retroactively apply dynamic cooldown: block same direction after STOP_HIT until daily close crosses stop price")
    parser.add_argument("--use-results-cache", action="store_true",
                        help="Skip engine run — load cached results from previous run (fast analysis only)")
    parser.add_argument("--label", type=str, default=None,
                        help="Label for auto-snapshot (e.g. --label baseline). Default: timestamp.")
    parser.add_argument("--save-tf-baseline", action="store_true",
                        help="Save current TF results as the locked baseline for regression checks")
    parser.add_argument("--analyze-vmr-rr", action="store_true",
                        help="Sim VWAP_MR with fixed R:R target (1.5R and 2.0R) vs current VWAP target")
    parser.add_argument("--analyze-vmr-stop", action="store_true",
                        help="Sim VWAP_MR with wider stops (3×ATR and structural) vs current 1.5×ATR")
    parser.add_argument("--analyze-vmr-spy", action="store_true",
                        help="Sim VWAP_MR with SPY VWAP alignment filter (LONG only above SPY VWAP, etc.)")
    parser.add_argument("--analyze-vmr-etf", action="store_true",
                        help="Sim VWAP_MR ETF-only universe (QQQ, IWM, XLF, XLE, XLV, XLU, XLI)")
    parser.add_argument("--analyze-orb-spy", action="store_true",
                        help="Retroactive sim: filter ORB trades where direction mismatches SPY intraday move")
    parser.add_argument("--analyze-orb-fade-stop", action="store_true",
                        help="Sim ORB_FADE with stop at bar-B breakout close ±0.5%% vs current OR boundary ±0.5%%")
    parser.add_argument("--analyze-orb-fade-mfe", action="store_true",
                        help="MFE/MAE analysis for ORB_FADE: how far did price move in favorable vs adverse direction")
    parser.add_argument("--vmr-vol-threshold", type=float, default=0.12,
                        help="VWAP_MR vol gate: allow trades when SPY 5-day realized vol <= threshold (default: 0.12=Calm)")
    parser.add_argument("--max-risk-pct", type=float, default=0.01,
                        help="Max loss per trade as %% of account (default: 0.01=1%%). Raise to increase position sizes.")
    parser.add_argument("--profile", action="store_true",
                        help="Run cProfile on the engine and print top-30 slowest functions.")
    args = parser.parse_args()

    use_scanner = not args.no_scanner

    # ORB, MR, and FADE scanners need the full CANDIDATE_POOL (= TICKERS).
    tickers_to_load = TICKERS

    rebuild = args.rebuild_cache

    force_cache = args.use_results_cache and os.path.exists(PICKLE_5MIN)
    print("\nLoading 5-min data...")
    full_data = fetch_market_data(tickers_to_load, interval_minutes=INTERVAL_MINS, rebuild=rebuild, force_cache=force_cache)

    # ── Results: load from cache or run engine ────────────────────────────────
    if args.use_results_cache and os.path.exists(PICKLE_RESULTS):
        print(f"\nLoading cached results from {PICKLE_RESULTS} ...")
        with open(PICKLE_RESULTS, "rb") as f:
            results = pickle.load(f)
        print_summary(results)
    else:
        # MR, ORB, and FADE scanners all require daily data — load unconditionally.
        print("\nLoading daily data for scanners...")
        daily_data = load_daily_data(rebuild=rebuild)

        mode_label = f"SCANNER top-{args.top_n}" if use_scanner else "FIXED 8-stock universe"
        print(f"\nMode: {mode_label}")

        # vwap_universe = static fallback when MR scanner disabled or returns empty.
        # Must be low-beta, range-bound stocks — NOT the TF momentum universe.
        MR_UNIVERSE_STATIC = ["XLF", "XLE", "XLV", "XLU", "XLI",
                              "XLK", "XLP", "XLB", "XLY", "GLD", "QQQ", "IWM"]

        cfg_base = dict(
            universe=UNIVERSE,
            orb_universe=[],
            vwap_universe=MR_UNIVERSE_STATIC,
            orb_range_minutes=15,
            vwap_bb_std=2.0,
            ema_period=30,
            account_equity=50_000.0,
            enable_costs=True,
            enable_pdt_guard=False,
            log_level="WARNING",
            allow_swing_hold=not args.no_swing,
            max_hold_days=5,
            stress_size_fraction=0.5,
            use_scanner=use_scanner,
            scanner_top_n=args.top_n,
            use_mr_scanner=True,
            mr_scanner_top_n=8,
            use_orb_scanner=True,
            orb_scanner_top_n=10,
            use_fade_scanner=True,
            fade_scanner_top_n=10,
            vwap_mr_vol_threshold=args.vmr_vol_threshold,
            max_risk_pct=args.max_risk_pct,
            max_position_pct=0.30,
        )

        windows = [(s, e, l) for s, e, l in WINDOWS if args.year is None or l == str(args.year)]
        if not windows:
            print(f"No windows match --year {args.year}. Available: {[l for _,_,l in WINDOWS]}")
            return

        worker_args = [
            (s, e, l, cfg_base, slice_oos(full_data, s, e), daily_data)
            for s, e, l in windows
        ]

        n_workers = len(worker_args)
        if args.profile:
            import cProfile, pstats, io
            pr = cProfile.Profile()
            pr.enable()
            results = [_run_window(worker_args[0])]
            pr.disable()
            s = io.StringIO()
            ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
            ps.print_stats(30)
            print("\n── cProfile top-30 (cumulative) ──")
            print(s.getvalue())
        elif n_workers == 1:
            results = [_run_window(worker_args[0])]
        else:
            print(f"\nRunning {n_workers} windows in parallel...")
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                results = list(ex.map(_run_window, worker_args))

        print_summary(results)

        with open(PICKLE_RESULTS, "wb") as f:
            pickle.dump(results, f)
        print(f"  [cache saved -> {PICKLE_RESULTS}]")

        # Auto-snapshot: copy to snapshots/ with label arg or timestamp
        _snap_dir = os.path.join(os.path.dirname(PICKLE_RESULTS), "snapshots")
        os.makedirs(_snap_dir, exist_ok=True)
        _snap_label = getattr(args, "label", None) or __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        _snap_path = os.path.join(_snap_dir, f"results_{_snap_label}.pkl")
        import shutil
        shutil.copy2(PICKLE_RESULTS, _snap_path)
        print(f"  [snapshot -> snapshots/results_{_snap_label}.pkl]")

    # ── TF baseline save / check ──────────────────────────────────────────────
    if args.save_tf_baseline:
        save_tf_baseline(results)
    else:
        check_tf_baseline(results)

    # ── Option B retroactive analysis ────────────────────────────────────────
    if args.analyze_b:
        _analyze_option_b(results, full_data, args.min_move_pct, args.max_hod_dist_pct)

    # ── ADX retroactive analysis ──────────────────────────────────────────────
    if args.analyze_adx:
        _analyze_adx(results, full_data, args.adx_threshold)

    # ── Dynamic cooldown retroactive analysis ─────────────────────────────────
    if args.analyze_cooldown:
        _analyze_cooldown(results, full_data)

    # ── VWAP_MR R:R sim ───────────────────────────────────────────────────────
    if args.analyze_vmr_rr:
        _analyze_vmr_rr(results, full_data)

    # ── VWAP_MR stop sim ──────────────────────────────────────────────────────
    if args.analyze_vmr_stop:
        _analyze_vmr_stop(results, full_data)

    # ── VWAP_MR ETF-only sim ──────────────────────────────────────────────────
    if args.analyze_vmr_etf:
        _analyze_vmr_etf(results)

    # ── VWAP_MR SPY alignment sim ─────────────────────────────────────────────
    if args.analyze_vmr_spy:
        _analyze_vmr_spy(results, full_data)

    # ── ORB SPY alignment sim ─────────────────────────────────────────────────
    if args.analyze_orb_spy:
        _analyze_orb_spy_alignment(results, full_data)

    # ── ORB_FADE stop sim ─────────────────────────────────────────────────────
    if args.analyze_orb_fade_stop:
        _analyze_orb_fade_stop(results, full_data)

    # ── ORB_FADE MFE/MAE analysis ─────────────────────────────────────────────
    if args.analyze_orb_fade_mfe:
        _analyze_orb_fade_mfe(results, full_data)

    # ── Per-trade detail for ORB (all windows) ───────────────────────────────
    all_orb = []
    for r in results:
        if r["label"] not in ("2017", "2018", "2019", "2020", "2021", "2022"):
            continue
        orb_trades = sorted(
            [t for t in r["trades"] if t.strategy == "ORB"],
            key=lambda x: x.entry_time,
        )
        if not orb_trades:
            print(f"\n[{r['label']}] No ORB trades found.")
            continue
        all_orb.extend(orb_trades)
        print(f"\n{'='*90}")
        print(f"  {r['label']} ORB — {len(orb_trades)} trades")
        print(f"{'='*90}")
        hdr = (f"  {'Date':<12} {'Ticker':<6} {'Dir':<5} {'Entry':>7} "
               f"{'Stop':>7} {'Target':>7} {'Exit':>7} {'Exit$':>7} "
               f"{'PnL':>8}  Exit Reason")
        print(hdr)
        print(f"  {'-'*86}")
        for t in orb_trades:
            entry_d   = str(t.entry_time)[:10] if t.entry_time else "?"
            pnl_s     = f"${t.net_pnl:+.0f}" if t.net_pnl is not None else "?"
            ep        = f"${t.entry_price:.2f}" if t.entry_price else "?"
            st        = f"${t.stop:.2f}"        if t.stop       else "?"
            tgt       = f"${t.target:.2f}"      if t.target     else "?"
            xp        = f"${t.exit_price:.2f}"  if t.exit_price else "?"
            stop_dist = abs(t.entry_price - t.stop) if t.entry_price and t.stop else 0
            tgt_dist  = abs(t.target - t.entry_price) if t.target and t.entry_price else 0
            rr_s      = f"1:{tgt_dist/stop_dist:.1f}R" if stop_dist > 0 else ""
            print(f"  {entry_d:<12} {t.ticker:<6} {t.direction:<5} {ep:>7} "
                  f"{st:>7} {tgt:>7} {xp:>7} {rr_s:>7} "
                  f"{pnl_s:>8}  {t.exit_reason or '?'}")
        print(f"{'='*90}")

    # ── ORB exit reason breakdown ─────────────────────────────────────────────
    if all_orb:
        from collections import Counter
        orb_reasons  = Counter(t.exit_reason for t in all_orb)
        orb_wins_by  = Counter(t.exit_reason for t in all_orb if (t.net_pnl or 0) > 0)
        orb_pnl_by: dict = {}
        for t in all_orb:
            orb_pnl_by.setdefault(t.exit_reason, []).append(t.net_pnl or 0)
        print(f"\n{'='*60}")
        print(f"  ORB Exit Reason Breakdown — {len(all_orb)} total trades")
        print(f"{'='*60}")
        print(f"  {'Reason':<20} {'Count':>6} {'WR':>6} {'AvgPnL':>8} {'Total':>8}")
        print(f"  {'-'*56}")
        for reason, cnt in orb_reasons.most_common():
            wins   = orb_wins_by.get(reason, 0)
            wr     = wins / cnt if cnt else 0
            pnls   = orb_pnl_by.get(reason, [])
            avg_p  = sum(pnls) / len(pnls) if pnls else 0
            tot    = sum(pnls)
            print(f"  {reason:<20} {cnt:>6} {wr:>6.0%} {avg_p:>+8.2f} {tot:>+8.0f}")
        print(f"{'='*60}")

    # ── Per-trade detail for TREND_FOLLOW (all windows) ──────────────────────
    for r in results:
        if r["label"] not in ("2017", "2018", "2019", "2020", "2021", "2022"):
            continue
        tf_trades = [t for t in r["trades"] if t.strategy == "TREND_FOLLOW"]
        if not tf_trades:
            print(f"\n[{r['label']}] No TREND_FOLLOW trades found.")
            continue
        print(f"\n{'='*90}")
        print(f"  {r['label']} TREND_FOLLOW — {len(tf_trades)} trades")
        print(f"{'='*90}")
        hdr = (f"  {'Date':<12} {'Ticker':<6} {'Dir':<5} {'Rgm':<7} {'Entry':>7} "
               f"{'Stop':>7} {'Target':>7} {'Exit':>7} {'Exit$':>7} "
               f"{'PnL':>8}  Exit Reason")
        print(hdr)
        print(f"  {'-'*93}")
        for t in sorted(tf_trades, key=lambda x: x.entry_time):
            entry_d  = str(t.entry_time)[:10] if t.entry_time else "?"
            pnl_s    = f"${t.net_pnl:+.0f}" if t.net_pnl is not None else "?"
            ep       = f"${t.entry_price:.2f}" if t.entry_price else "?"
            st       = f"${t.stop:.2f}"        if t.stop       else "?"
            tgt      = f"${t.target:.2f}"      if t.target     else "?"
            xp       = f"${t.exit_price:.2f}"  if t.exit_price else "?"
            regime   = getattr(t, "hmm_state", "?")[:6]
            stop_dist = abs(t.entry_price - t.stop) if t.entry_price and t.stop else 0
            tgt_dist  = abs(t.target - t.entry_price) if t.target and t.entry_price else 0
            rr_s = f"1:{tgt_dist/stop_dist:.1f}R" if stop_dist > 0 else ""
            print(f"  {entry_d:<12} {t.ticker:<6} {t.direction:<5} {regime:<7} {ep:>7} "
                  f"{st:>7} {tgt:>7} {xp:>7} {rr_s:>7} "
                  f"{pnl_s:>8}  {t.exit_reason or '?'}")
        print(f"{'='*90}")

    # ── Per-trade detail for VWAP_MR (all windows) ───────────────────────────
    all_vmr = []
    for r in results:
        if r["label"] not in ("2017", "2018", "2019", "2020", "2021", "2022"):
            continue
        vmr_trades = sorted(
            [t for t in r["trades"] if t.strategy == "VWAP_MR"],
            key=lambda x: x.entry_time,
        )
        if not vmr_trades:
            continue
        all_vmr.extend(vmr_trades)
        print(f"\n{'='*90}")
        print(f"  {r['label']} VWAP_MR — {len(vmr_trades)} trades")
        print(f"{'='*90}")
        hdr = (f"  {'Date':<12} {'Ticker':<6} {'Dir':<5} {'Entry':>7} "
               f"{'Stop':>7} {'VWAP':>7} {'Exit':>7} {'R:R':>6} "
               f"{'PnL':>8}  Exit Reason")
        print(hdr)
        print(f"  {'-'*88}")
        for t in vmr_trades:
            entry_d   = str(t.entry_time)[:10] if t.entry_time else "?"
            pnl_s     = f"${t.net_pnl:+.0f}" if t.net_pnl is not None else "?"
            ep        = f"${t.entry_price:.2f}" if t.entry_price else "?"
            st        = f"${t.stop:.2f}"        if t.stop       else "?"
            tgt       = f"${t.target:.2f}"      if t.target     else "?"
            xp        = f"${t.exit_price:.2f}"  if t.exit_price else "?"
            stop_dist = abs(t.entry_price - t.stop) if t.entry_price and t.stop else 0
            tgt_dist  = abs(t.target - t.entry_price) if t.target and t.entry_price else 0
            rr_s      = f"1:{tgt_dist/stop_dist:.1f}R" if stop_dist > 0 else ""
            print(f"  {entry_d:<12} {t.ticker:<6} {t.direction:<5} {ep:>7} "
                  f"{st:>7} {tgt:>7} {xp:>7} {rr_s:>6} "
                  f"{pnl_s:>8}  {t.exit_reason or '?'}")
        print(f"{'='*90}")

    # ── VWAP_MR exit reason breakdown ────────────────────────────────────────
    if all_vmr:
        from collections import Counter
        reasons = Counter(t.exit_reason for t in all_vmr)
        wins_by_reason    = Counter(t.exit_reason for t in all_vmr if (t.net_pnl or 0) > 0)
        pnl_by_reason: dict = {}
        for t in all_vmr:
            pnl_by_reason.setdefault(t.exit_reason, []).append(t.net_pnl or 0)

        print(f"\n{'='*60}")
        print(f"  VWAP_MR Exit Reason Breakdown — {len(all_vmr)} total trades")
        print(f"{'='*60}")
        print(f"  {'Reason':<20} {'Count':>6} {'WR':>7} {'AvgPnL':>9} {'Total':>9}")
        print(f"  {'-'*56}")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            wr     = wins_by_reason.get(reason, 0) / count * 100
            pnls   = pnl_by_reason[reason]
            avg    = sum(pnls) / len(pnls)
            total  = sum(pnls)
            print(f"  {reason:<20} {count:>6} {wr:>6.0f}% {avg:>+9.2f} {total:>+9.0f}")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
