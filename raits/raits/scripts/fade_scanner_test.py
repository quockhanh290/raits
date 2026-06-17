"""
fade_scanner_test.py — Standalone test for FADE strategy with dedicated FADE scanner.

Compares two universes applied to the same FADE trade logic:
  - ORB Scanner  (score = gap_freq × followthrough):      current engine approach
  - FADE Scanner (score = gap_freq × (1-followthrough)):  proposed approach

Optimization: gap_freq and followthrough computed ONCE for all tickers/days,
then reused for both scanner modes.

Uses window_debug pkl caches — no API calls needed.
"""

import os, sys, pickle
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Config ─────────────────────────────────────────────────────────────────────
OR_PERIOD_MIN = 15      # Opening range: first 15 min
LOOKBACK_DAYS = 60      # Scanner lookback for gap stats
GAP_THRESHOLD = 0.01    # ≥1% gap counts as a gap day
MIN_GAP_FREQ  = 0.05    # Ticker must gap ≥5% of days to qualify
RVOL_MULT     = 1.5     # Breakout bar volume > 1.5× rolling avg
TOP_N         = 10      # Scanner selects top N stocks per day
STOP_PCT      = 0.005   # 0.5% beyond OR boundary
ACCOUNT       = 50_000
MAX_RISK_PCT  = 0.01    # 1% of account = $500 max risk per trade
COMMISSION    = 0.005   # $ per share

WINDOWS = [
    ("2020-01-01", "2020-12-31", "2020"),
    ("2021-01-01", "2021-12-31", "2021"),
    ("2022-01-01", "2022-12-31", "2022"),
]

CANDIDATE_POOL = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD",
    "QCOM", "INTC", "MU", "AVGO", "TXN", "AMAT",
    "ADBE", "CRM", "ORCL", "INTU", "CSCO",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX",
    "COST", "SBUX", "NFLX", "EBAY",
    "JPM", "GS", "MS", "V", "MA",
    "HON", "MMM", "XOM", "CVX",
]

# ── Load caches ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR    = os.path.join(SCRIPT_DIR, "..", "..", "data", "cache")
PICKLE_5MIN  = os.path.join(CACHE_DIR, "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(CACHE_DIR, "window_debug_daily.pkl")

print("Loading 5-min cache...")
with open(PICKLE_5MIN, "rb") as f:
    data_5min = pickle.load(f)

print("Loading daily cache...")
with open(PICKLE_DAILY, "rb") as f:
    data_daily = pickle.load(f)

print(f"Loaded {len(data_5min)} tickers (5-min), {len(data_daily)} tickers (daily)")


# ── Pre-compute scanner stats for all days × all tickers ──────────────────────
# Result: {day_str → {ticker → (gap_freq, followthrough)}}
# Computed once, reused for both ORB and FADE scanner modes.

def precompute_scanner(daily_data, pool, window_days):
    """
    For each day in window_days, compute gap_freq and followthrough per ticker.
    Returns dict: {day_str: {ticker: (gap_freq, followthrough)}} for tickers that pass filters.
    """
    # Normalize daily data index once per ticker
    normed = {}
    for ticker in pool:
        df = daily_data.get(ticker, pd.DataFrame())
        if df.empty:
            continue
        if df.index.tzinfo:
            df = df.copy(); df.index = df.index.tz_localize(None)
        normed[ticker] = df

    result = {}
    total = len(window_days)
    for i, day in enumerate(window_days):
        if i % 50 == 0:
            print(f"  Pre-computing scanner... {i}/{total} days", end="\r")
        day_str = str(day.date())
        result[day_str] = {}

        for ticker, df in normed.items():
            df_cut = df[df.index.normalize() <= day]
            if len(df_cut) < LOOKBACK_DAYS + 1:
                continue
            if float(df_cut["volume"].iloc[-20:].mean()) < 500_000:
                continue

            window     = df_cut.iloc[-(LOOKBACK_DAYS + 1):]
            prev_close = window["close"].shift(1)
            gap_pct    = (window["open"] - prev_close).abs() / prev_close
            gap_dir    = window["open"] - prev_close
            intraday   = window["close"] - window["open"]
            gap_pct    = gap_pct.iloc[1:]
            gap_dir    = gap_dir.iloc[1:]
            intraday   = intraday.iloc[1:]

            is_gap   = gap_pct >= GAP_THRESHOLD
            gap_freq = float(is_gap.mean())
            if gap_freq < MIN_GAP_FREQ:
                continue

            followthrough = float(
                ((gap_dir * intraday) > 0)[is_gap].mean()
            ) if is_gap.any() else 0.0

            result[day_str][ticker] = (gap_freq, followthrough)

    print(f"  Pre-computing scanner... {total}/{total} days — done.   ")
    return result


def get_universe(scanner_data, day_str, top_n, fade_mode):
    """Derive top N tickers from pre-computed stats for given day and mode."""
    stats = scanner_data.get(day_str, {})
    scored = []
    for ticker, (gap_freq, followthrough) in stats.items():
        score = gap_freq * (1 - followthrough) if fade_mode else gap_freq * followthrough
        scored.append((ticker, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored[:top_n]]


# ── Collect all trading days across windows ────────────────────────────────────
all_days = set()
for ticker in CANDIDATE_POOL:
    df = data_5min.get(ticker, pd.DataFrame())
    if df.empty:
        continue
    idx = df.index.tz_localize(None) if df.index.tzinfo else df.index
    all_days.update(idx.normalize().unique())

window_start = min(pd.Timestamp(s) for s, _, _ in WINDOWS)
window_end   = max(pd.Timestamp(e) for _, e, _ in WINDOWS)
window_days  = sorted(d for d in all_days if window_start <= d <= window_end)

print(f"\nPre-computing scanner stats for {len(window_days)} trading days × {len(CANDIDATE_POOL)} tickers...")
scanner_data = precompute_scanner(data_daily, CANDIDATE_POOL, window_days)


# ── Per-day simulation ─────────────────────────────────────────────────────────
# Normalize 5-min data index once per ticker
normed_5min = {}
for ticker in CANDIDATE_POOL:
    df = data_5min.get(ticker, pd.DataFrame())
    if df.empty:
        continue
    if df.index.tzinfo:
        df = df.copy(); df.index = df.index.tz_localize(None)
    normed_5min[ticker] = df


def simulate_day(ticker, day):
    df = normed_5min.get(ticker)
    if df is None:
        return []

    day_bars = df[df.index.normalize() == day]
    if len(day_bars) < OR_PERIOD_MIN // 5 + 2:
        return []

    market_open  = day + pd.Timedelta(hours=9, minutes=30)
    or_end       = market_open + pd.Timedelta(minutes=OR_PERIOD_MIN)
    signal_end   = day + pd.Timedelta(hours=14)          # cap at 14:00 ET
    or_bars      = day_bars[day_bars.index < or_end]
    post_or_bars = day_bars[(day_bars.index >= or_end) & (day_bars.index < signal_end)].reset_index()
    _ts_col = post_or_bars.columns[0]  # first col after reset_index = datetime

    if len(or_bars) == 0 or len(post_or_bars) < 2:
        return []

    or_high  = float(or_bars["high"].max())
    or_low   = float(or_bars["low"].min())
    if or_high <= or_low:
        return []

    all_prior = df[df.index < market_open]
    vol_avg   = float(all_prior["volume"].tail(20).mean()) if len(all_prior) >= 5 else 0.0

    for i, bar_b in post_or_bars.iterrows():
        close_b = float(bar_b["close"])
        vol_b   = float(bar_b["volume"])

        if close_b > or_high:
            direction = "LONG_BREAK"
        elif close_b < or_low:
            direction = "SHORT_BREAK"
        else:
            continue

        if vol_avg > 0 and vol_b < RVOL_MULT * vol_avg:
            continue

        if i + 1 >= len(post_or_bars):
            continue
        bar_b1   = post_or_bars.iloc[i + 1]
        close_b1 = float(bar_b1["close"])

        if direction == "LONG_BREAK"  and close_b1 >= or_high:
            continue
        if direction == "SHORT_BREAK" and close_b1 <= or_low:
            continue

        if direction == "LONG_BREAK":
            fade_dir  = "SHORT"
            stop_loss = or_high * (1 + STOP_PCT)
            target    = or_low   # revert to opposite OR boundary
        else:
            fade_dir  = "LONG"
            stop_loss = or_low  * (1 - STOP_PCT)
            target    = or_high  # revert to opposite OR boundary

        entry    = close_b1
        risk     = abs(entry - stop_loss)
        if risk <= 0:
            continue
        if abs(target - entry) <= 0:
            continue
        dir_sign = 1 if fade_dir == "LONG" else -1
        shares   = max(1, int((ACCOUNT * MAX_RISK_PCT) / risk))

        remaining = post_or_bars.iloc[i + 2:]
        exit_px, exit_rsn = None, "EOD"

        for _, rb in remaining.iterrows():
            if fade_dir == "SHORT":
                if float(rb["high"]) >= stop_loss:
                    exit_px = stop_loss; exit_rsn = "STOP_HIT";   break
                if float(rb["low"])  <= target:
                    exit_px = target;   exit_rsn = "TARGET_HIT"; break
            else:
                if float(rb["low"])  <= stop_loss:
                    exit_px = stop_loss; exit_rsn = "STOP_HIT";   break
                if float(rb["high"]) >= target:
                    exit_px = target;   exit_rsn = "TARGET_HIT"; break

        if exit_px is None:
            exit_px = float(remaining.iloc[-1]["close"]) if not remaining.empty else entry

        gross = shares * (exit_px - entry) * dir_sign
        net   = gross - shares * COMMISSION * 2

        return [{
            "date": day, "ticker": ticker, "direction": fade_dir,
            "entry": entry, "stop": stop_loss, "target": target,
            "exit_px": exit_px, "exit_rsn": exit_rsn,
            "shares": shares, "net_pnl": net,
            "entry_time": bar_b1[_ts_col],
        }]

    return []


# ── Run simulation for one mode ────────────────────────────────────────────────
def run_mode(fade_mode, max_per_day=None):
    all_trades = []
    for start, end, yr in WINDOWS:
        yr_trades = []
        yr_days = [d for d in window_days if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
        for day in yr_days:
            day_str   = str(day.date())
            universe  = get_universe(scanner_data, day_str, TOP_N, fade_mode)
            day_trades = []
            for ticker in universe:
                day_trades.extend(simulate_day(ticker, day))
            if max_per_day is not None and len(day_trades) > max_per_day:
                day_trades.sort(key=lambda t: t["entry_time"])
                day_trades = day_trades[:max_per_day]
            yr_trades.extend(day_trades)
        print_results(yr, yr_trades, show_time_breakdown=False)
        all_trades.extend(yr_trades)
    print_results("TOTAL", all_trades, show_time_breakdown=False)


ENGINE_WINDOW_END = pd.Timestamp("1970-01-01 10:15:00")  # engine cuts off here

HOUR_BUCKETS = [
    ("09:45-10:15", pd.Timestamp("1970-01-01 09:45"), pd.Timestamp("1970-01-01 10:15")),
    ("10:15-11:00", pd.Timestamp("1970-01-01 10:15"), pd.Timestamp("1970-01-01 11:00")),
    ("11:00-12:00", pd.Timestamp("1970-01-01 11:00"), pd.Timestamp("1970-01-01 12:00")),
    ("12:00-13:00", pd.Timestamp("1970-01-01 12:00"), pd.Timestamp("1970-01-01 13:00")),
    ("13:00-14:00", pd.Timestamp("1970-01-01 13:00"), pd.Timestamp("1970-01-01 14:00")),
]

def _time_key(ts):
    """Strip date, keep time on 1970-01-01 for bucket comparison."""
    return pd.Timestamp(f"1970-01-01 {ts.strftime('%H:%M:%S')}")


def print_results(label, trades, show_time_breakdown=False):
    if not trades:
        print(f"  [{label}]: 0 trades")
        return
    total   = sum(t["net_pnl"] for t in trades)
    wins    = [t for t in trades if t["net_pnl"] > 0]
    wr      = len(wins) / len(trades) * 100
    avg     = total / len(trades)
    sh_hits = sum(1 for t in trades if t["exit_rsn"] == "STOP_HIT")
    tgt_hit = sum(1 for t in trades if t["exit_rsn"] == "TARGET_HIT")
    print(f"  [{label}]: {len(trades):>4} trades  WR={wr:>5.1f}%  "
          f"Avg=${avg:>+7.1f}  Total=${total:>+8,.0f}  "
          f"STOP={sh_hits}  TGT={tgt_hit}")
    if show_time_breakdown:
        print(f"    {'Window':<14}  {'N':>4}  {'WR':>6}  {'Total':>10}")
        for bucket_lbl, b_start, b_end in HOUR_BUCKETS:
            bucket = [t for t in trades
                      if b_start <= _time_key(t["entry_time"]) < b_end]
            if not bucket:
                continue
            b_total = sum(t["net_pnl"] for t in bucket)
            b_wr    = sum(1 for t in bucket if t["net_pnl"] > 0) / len(bucket) * 100
            marker  = " ← engine" if bucket_lbl == "09:45-10:15" else ""
            print(f"    {bucket_lbl:<14}  {len(bucket):>4}  {b_wr:>5.1f}%  {b_total:>+10,.0f}{marker}")


# ── Main ───────────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("  FADE SCANNER TEST — OOS 2020 / 2021 / 2022")
print("=" * 70)

print(f"\n  FADE Scanner — cap simulation")
print(f"  {'─'*60}")
for cap in [None, 10, 5, 3, 2]:
    label = f"cap=unlimited" if cap is None else f"cap={cap}/day    "
    print(f"\n  {label}")
    run_mode(fade_mode=True, max_per_day=cap)

print(f"\n{'='*70}")
