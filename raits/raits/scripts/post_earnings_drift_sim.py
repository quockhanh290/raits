"""
post_earnings_drift_sim.py — Post-earnings momentum drift (1–2 day hold)

Hypothesis: after a significant earnings gap, price continues drifting
in the same direction for 1-2 sessions as the market digests the news.

Setup:
  - Earnings gap: |open_reaction_day / close_prev_day| - 1 >= GAP_MIN
  - Direction: LONG if gap up, SHORT if gap down
  - Entry: open of reaction day (assumes market-open limit or next 5-min bar)
  - Stop: STOP_ATR_MULT × ATR14 below/above entry
  - Target: TARGET_RR × stop_dist above/below entry (2:1 RR default)
  - Time stop: close of (reaction_day + hold_days)
  - Regime: Normal only (from engine results pkl)
  - Fixed $500 risk per trade (sim convention)

Reaction day logic:
  yfinance earnings date can be BMO (before market open) or AMC (after close).
  We check both the earnings date AND the next trading day, and take whichever
  shows the larger absolute gap vs prior close.

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\post_earnings_drift_sim.py
"""

import sys, os, pickle, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import timedelta
from collections import defaultdict

# ── Paths ──────────────────────────────────────────────────────────────────────
PKL_RESULTS    = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN       = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
EARNINGS_CACHE = r'd:\raits\raits\data\cache\earnings_dates.json'

# ── Universe ───────────────────────────────────────────────────────────────────
CANDIDATE_POOL = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD",
    "QCOM", "INTC", "MU", "AVGO", "TXN", "AMAT",
    "ADBE", "CRM", "ORCL", "INTU", "CSCO",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX",
    "COST", "SBUX", "NFLX", "EBAY",
    "JPM", "GS", "MS", "V", "MA",
    "HON", "MMM",
    "XOM", "CVX",
]

# ── Sim parameters ─────────────────────────────────────────────────────────────
GAP_MIN        = 0.02    # 2% minimum absolute gap to qualify
STOP_ATR_MULT  = 1.5     # stop = 1.5 × ATR14 from entry
TARGET_RR      = 2.0     # target = 2 × stop distance (2:1 RR)
RISK_PER_TRADE = 500.0   # fixed $ risk per trade (sim convention)
ATR_PERIOD     = 14
BACKTEST_START = pd.Timestamp("2020-01-01")
BACKTEST_END   = pd.Timestamp("2022-12-31")
HOLD_DAYS_LIST = [1, 2]  # test both

# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading pkl data...")
with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)
with open(PKL_5MIN, 'rb') as f:
    data_5min = pickle.load(f)

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Normal regime days from engine results
normal_days_set = set()
for w in results:
    for t in w.get('trades', []):
        if getattr(t, 'hmm_state', None) == 'Normal':
            normal_days_set.add(pd.to_datetime(t.entry_time).normalize())
print(f"Normal days from engine: {len(normal_days_set)}")

# ── Build daily OHLC from 5-min bars ──────────────────────────────────────────
print("Building daily OHLC...")
daily_ohlc = {}
for tk in CANDIDATE_POOL:
    if tk not in data_5min:
        continue
    df = data_5min[tk].sort_index().copy()
    df['date'] = df.index.normalize()
    grp = df.groupby('date')
    daily = pd.DataFrame({
        'open':   grp['open'].first(),
        'high':   grp['high'].max(),
        'low':    grp['low'].min(),
        'close':  grp['close'].last(),
        'volume': grp['volume'].sum(),
    })
    # Filter to backtest range + 1 year buffer for ATR warmup
    daily = daily[(daily.index >= "2019-01-01") & (daily.index <= BACKTEST_END)]
    daily_ohlc[tk] = daily

# Trading day set (for next_trading_day lookup)
all_trading_days = sorted(data_5min['SPY'].index.normalize().unique())
all_trading_days_set = set(all_trading_days)

def next_trading_day(date: pd.Timestamp) -> pd.Timestamp | None:
    check = date + timedelta(days=1)
    for _ in range(7):
        if check in all_trading_days_set:
            return check
        check += timedelta(days=1)
    return None

def compute_atr(daily: pd.DataFrame, before_date: pd.Timestamp) -> float | None:
    hist = daily[daily.index < before_date].tail(ATR_PERIOD + 1)
    if len(hist) < 2:
        return None
    hl  = hist['high'] - hist['low']
    hpc = (hist['high'] - hist['close'].shift(1)).abs()
    lpc = (hist['low']  - hist['close'].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(ATR_PERIOD).mean())

# ── Fetch earnings dates from Polygon /vX/reference/financials (cached) ────────
# filing_date = 8-K press release date = reaction day (BMO: same day, AMC: next morning)
def fetch_earnings(tickers, cache_path):
    if os.path.exists(cache_path):
        print(f"Loading earnings dates from cache: {cache_path}")
        with open(cache_path) as f:
            raw = json.load(f)
        return {tk: [pd.Timestamp(d) for d in dates] for tk, dates in raw.items()}

    print("Fetching earnings dates from Polygon (quarterly financials)...")
    sys.path.insert(0, r'd:\raits')
    from config_private import POLYGON_API_KEY
    from polygon import RESTClient
    client = RESTClient(api_key=POLYGON_API_KEY)

    result = {}
    for tk in tickers:
        dates = []
        try:
            for r in client.vx.list_stock_financials(
                ticker=tk,
                timeframe="quarterly",
                filing_date_gte="2019-10-01",
                filing_date_lte="2022-12-31",
                limit=20,
            ):
                dates.append(pd.Timestamp(r.filing_date))
            result[tk] = sorted(set(dates))
            n = len(result[tk])
            rng = f"{result[tk][0].date()} – {result[tk][-1].date()}" if n else "—"
            print(f"  {tk:6s}: {n:2d} dates  [{rng}]")
        except Exception as e:
            result[tk] = []
            print(f"  {tk:6s}: ERROR — {e}")

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'w') as f:
        json.dump({tk: [str(d.date()) for d in dates] for tk, dates in result.items()}, f, indent=2)
    print(f"Cached to: {cache_path}")
    return result

earnings_map = fetch_earnings(CANDIDATE_POOL, EARNINGS_CACHE)

in_window = sum(
    1 for tk, dates in earnings_map.items()
    for d in dates if BACKTEST_START <= d <= BACKTEST_END
)
print(f"\nEarnings events in 2020–2022 backtest window: {in_window}")

# ── Simulation ─────────────────────────────────────────────────────────────────
print("\nSimulating post-earnings drift trades...")

trades = []

for tk in CANDIDATE_POOL:
    if tk not in daily_ohlc:
        continue
    daily = daily_ohlc[tk]
    e_dates = [d for d in earnings_map.get(tk, []) if BACKTEST_START <= d <= BACKTEST_END]

    for e_date in e_dates:
        # Identify reaction day: check e_date itself (BMO) and e_date+1 (AMC)
        candidates = [e_date, next_trading_day(e_date)]
        best_r_day, best_gap = None, 0.0

        for r_day in candidates:
            if r_day is None or r_day not in daily.index:
                continue
            prev_days = daily.index[daily.index < r_day]
            if len(prev_days) == 0:
                continue
            prev_close = float(daily.loc[prev_days[-1], 'close'])
            r_open     = float(daily.loc[r_day, 'open'])
            if prev_close <= 0 or r_open <= 0:
                continue
            gap = (r_open - prev_close) / prev_close
            if abs(gap) > abs(best_gap):
                best_gap, best_r_day = gap, r_day

        if best_r_day is None or abs(best_gap) < GAP_MIN:
            continue

        # Regime filter
        if best_r_day not in normal_days_set:
            continue

        # ATR from prior days
        atr = compute_atr(daily, best_r_day)
        if atr is None or atr <= 0:
            continue

        prev_days   = daily.index[daily.index < best_r_day]
        prev_close  = float(daily.loc[prev_days[-1], 'close'])
        entry_price = float(daily.loc[best_r_day, 'open'])
        direction   = 1 if best_gap > 0 else -1

        stop_dist    = STOP_ATR_MULT * atr
        target_dist  = TARGET_RR * stop_dist
        stop_price   = entry_price - direction * stop_dist
        target_price = entry_price + direction * target_dist

        if stop_dist < 0.005 * entry_price:  # skip if stop < 0.5% of price
            continue

        shares = RISK_PER_TRADE / stop_dist
        if shares > 50000 or shares <= 0:
            continue

        # Get ordered trading days starting from reaction day
        td_from_r = [d for d in all_trading_days if d >= best_r_day and d <= BACKTEST_END]

        for hold_days in HOLD_DAYS_LIST:
            if len(td_from_r) <= hold_days:
                continue
            hold_day_list = td_from_r[1 : hold_days + 1]  # days AFTER entry
            if not all(d in daily.index for d in hold_day_list):
                continue

            exit_price  = None
            exit_reason = None

            for sim_day in hold_day_list:
                day_high = float(daily.loc[sim_day, 'high'])
                day_low  = float(daily.loc[sim_day, 'low'])

                if direction == 1:   # LONG
                    if day_low <= stop_price:
                        exit_price, exit_reason = stop_price, 'STOP'
                        break
                    if day_high >= target_price:
                        exit_price, exit_reason = target_price, 'TARGET'
                        break
                else:                # SHORT
                    if day_high >= stop_price:
                        exit_price, exit_reason = stop_price, 'STOP'
                        break
                    if day_low <= target_price:
                        exit_price, exit_reason = target_price, 'TARGET'
                        break

            if exit_price is None:
                exit_price  = float(daily.loc[hold_day_list[-1], 'close'])
                exit_reason = 'TIME'

            pnl = direction * shares * (exit_price - entry_price)

            trades.append({
                'ticker':        tk,
                'earnings_date': e_date,
                'reaction_day':  best_r_day,
                'gap_pct':       best_gap,
                'direction':     'LONG' if direction == 1 else 'SHORT',
                'entry':         entry_price,
                'exit':          exit_price,
                'stop':          stop_price,
                'target':        target_price,
                'stop_dist':     stop_dist,
                'atr':           atr,
                'shares':        shares,
                'pnl':           pnl,
                'exit_reason':   exit_reason,
                'hold_days':     hold_days,
                'year':          best_r_day.year,
            })

df = pd.DataFrame(trades)
if df.empty:
    print("No qualifying trades found. Check: earnings dates in cache, regime overlap, gap threshold.")
    sys.exit(0)

print(f"Total sim rows (hold1 + hold2 combined): {len(df)}")

# ── Results ────────────────────────────────────────────────────────────────────
SEP = "─" * 60

for hold in HOLD_DAYS_LIST:
    sub = df[df['hold_days'] == hold].copy()
    n   = len(sub)
    if n == 0:
        print(f"\n[Hold {hold}d] No trades.")
        continue
    tot = sub['pnl'].sum()
    wr  = (sub['pnl'] > 0).mean() * 100
    avg = sub['pnl'].mean()

    print(f"\n{'═'*60}")
    print(f"  HOLD {hold} DAY(S)  —  {n} trades  |  Total ${tot:+,.0f}  |  WR {wr:.0f}%  |  Avg ${avg:.1f}")
    print(SEP)

    for yr in [2020, 2021, 2022]:
        ys = sub[sub['year'] == yr]
        if len(ys) == 0:
            print(f"  {yr}: —")
            continue
        print(f"  {yr}: {len(ys):3d}t  ${ys['pnl'].sum():+8,.0f}  WR={ys['pnl'].gt(0).mean()*100:.0f}%")

    print(SEP)
    exits = sub['exit_reason'].value_counts().to_dict()
    longs = (sub['direction'] == 'LONG').sum()
    shts  = (sub['direction'] == 'SHORT').sum()
    print(f"  Exits: {exits}   LONG={longs} SHORT={shts}")

    # Top tickers
    by_tk = sub.groupby('ticker')['pnl'].sum().sort_values(ascending=False)
    top5  = by_tk.head(5)
    bot5  = by_tk.tail(5)
    print(f"\n  Top 5 tickers:")
    for tk, v in top5.items():
        n_tk = (sub['ticker'] == tk).sum()
        print(f"    {tk:6s}  {n_tk}t  ${v:+,.0f}")
    print(f"  Bottom 5 tickers:")
    for tk, v in bot5.items():
        n_tk = (sub['ticker'] == tk).sum()
        print(f"    {tk:6s}  {n_tk}t  ${v:+,.0f}")

# ── Gap threshold grid ─────────────────────────────────────────────────────────
print(f"\n\n{'═'*60}")
print("  GAP THRESHOLD SENSITIVITY (Hold 1 day)")
print(SEP)
print(f"  {'Gap≥':>6}  {'Trades':>6}  {'Total':>8}  {'WR':>5}  {'Avg':>8}")

sub1 = df[df['hold_days'] == 1].copy()
for gap_thresh in [0.01, 0.02, 0.03, 0.04, 0.05]:
    g = sub1[sub1['gap_pct'].abs() >= gap_thresh]
    if len(g) == 0:
        print(f"  {gap_thresh*100:>5.0f}%  {'—':>6}")
        continue
    print(f"  {gap_thresh*100:>5.0f}%  {len(g):>6d}  ${g['pnl'].sum():>+8,.0f}  "
          f"{g['pnl'].gt(0).mean()*100:>4.0f}%  ${g['pnl'].mean():>+7.1f}")

# ── Direction breakdown ────────────────────────────────────────────────────────
print(f"\n\n{'═'*60}")
print("  DIRECTION BREAKDOWN (Hold 1 day)")
print(SEP)
for direction in ['LONG', 'SHORT']:
    g = sub1[sub1['direction'] == direction]
    if len(g) == 0:
        print(f"  {direction}: —")
        continue
    print(f"  {direction}: {len(g)}t  ${g['pnl'].sum():+,.0f}  WR={g['pnl'].gt(0).mean()*100:.0f}%  Avg=${g['pnl'].mean():+.1f}")
    for yr in [2020, 2021, 2022]:
        ys = g[g['year'] == yr]
        if len(ys):
            print(f"    {yr}: {len(ys)}t  ${ys['pnl'].sum():+,.0f}  WR={ys['pnl'].gt(0).mean()*100:.0f}%")
