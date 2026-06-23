"""
post_earnings_expansion_sim.py — Earnings SHORT sim trên expanded universe

Dùng Polygon REST API để lấy daily bars trực tiếp (không cần 5-min parquet).
Sim logic giống post_earnings_short_sim.py nhưng chạy trên ~60 stocks.

Mục đích: tìm stocks nào contribute edge trước khi quyết định download 5-min data.

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\post_earnings_expansion_sim.py
"""

import sys, os, json, time, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from datetime import timedelta

# ── Config ─────────────────────────────────────────────────────────────────────
PKL_RESULTS     = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
EARNINGS_CACHE  = r'd:\raits\raits\data\cache\earnings_dates_expanded.json'
DAILY_CACHE     = r'd:\raits\raits\data\cache\daily_expanded.pkl'

BACKTEST_START  = pd.Timestamp("2020-01-01")
BACKTEST_END    = pd.Timestamp("2022-12-31")
ATR_PERIOD      = 14
STOP_ATR_MULT   = 1.5
TARGET_RR       = 2.0
RISK_PER_TRADE  = 500.0

# ── Universe ───────────────────────────────────────────────────────────────────
# Current 37-stock pool
EXISTING_POOL = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD",
    "QCOM", "INTC", "MU", "AVGO", "TXN", "AMAT",
    "ADBE", "CRM", "ORCL", "INTU", "CSCO",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX",
    "COST", "SBUX", "NFLX", "EBAY",
    "JPM", "GS", "MS", "V", "MA",
    "HON", "MMM", "XOM", "CVX",
]

# Expansion: 25 thêm — large-cap S&P500, established trước 2019
EXPANSION_POOL = [
    # Pharma/large biotech (big earnings movers)
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    # More banks (large quarterly reporters)
    "BAC", "WFC", "C",
    # Retail
    "WMT", "TGT", "HD", "LOW",
    # Consumer staples/discretionary
    "MCD", "NKE", "PG", "KO", "PEP",
    # Industrials (high earnings gap stocks)
    "CAT", "DE", "BA", "GE",
    # More tech/fintech
    "PYPL", "PANW", "NOW",
]

ALL_TICKERS = EXISTING_POOL + EXPANSION_POOL

print(f"Universe: {len(EXISTING_POOL)} existing + {len(EXPANSION_POOL)} expansion = {len(ALL_TICKERS)} total")

# ── Load API key ───────────────────────────────────────────────────────────────
sys.path.insert(0, r'd:\raits')
from config_private import POLYGON_API_KEY
from polygon import RESTClient
client = RESTClient(api_key=POLYGON_API_KEY)

# ── Load Normal regime days ────────────────────────────────────────────────────
print("Loading regime data...")
with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)

normal_days_set = set()
for w in results:
    for t in w.get('trades', []):
        if getattr(t, 'hmm_state', None) == 'Normal':
            normal_days_set.add(pd.to_datetime(t.entry_time).normalize())
print(f"Normal regime days: {len(normal_days_set)}")

# ── Fetch daily bars from Polygon (cached) ─────────────────────────────────────
def fetch_daily_bars(tickers, cache_path):
    if os.path.exists(cache_path):
        print(f"Loading daily bars from cache: {cache_path}")
        with open(cache_path, 'rb') as f:
            return pickle.load(f)

    print("Fetching daily bars from Polygon (2019-01-01 – 2022-12-31)...")
    daily = {}
    for i, tk in enumerate(tickers):
        try:
            rows = []
            for agg in client.list_aggs(
                ticker=tk,
                multiplier=1,
                timespan="day",
                from_="2019-01-01",
                to="2022-12-31",
                adjusted=True,
                sort="asc",
                limit=5000,
            ):
                rows.append({
                    'date':   pd.Timestamp(agg.timestamp, unit='ms', tz='UTC').tz_convert('US/Eastern').normalize().tz_localize(None),
                    'open':   agg.open,
                    'high':   agg.high,
                    'low':    agg.low,
                    'close':  agg.close,
                    'volume': agg.volume,
                })
            if rows:
                df = pd.DataFrame(rows).set_index('date').sort_index()
                daily[tk] = df
                print(f"  {tk:6s}: {len(df)} days  [{df.index[0].date()} – {df.index[-1].date()}]")
            else:
                print(f"  {tk:6s}: no data")
        except Exception as e:
            print(f"  {tk:6s}: ERROR — {e}")
        time.sleep(0.05)  # light rate limiting

    with open(cache_path, 'wb') as f:
        pickle.dump(daily, f)
    print(f"Cached to: {cache_path}")
    return daily

daily_all = fetch_daily_bars(ALL_TICKERS, DAILY_CACHE)
print(f"Daily data loaded: {len(daily_all)} tickers")

# ── Fetch earnings dates from Polygon (cached) ────────────────────────────────
def fetch_earnings(tickers, cache_path):
    if os.path.exists(cache_path):
        print(f"Loading earnings dates from cache: {cache_path}")
        with open(cache_path) as f:
            raw = json.load(f)
        return {tk: [pd.Timestamp(d) for d in dates] for tk, dates in raw.items()}

    print("Fetching earnings dates from Polygon financials...")
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
        time.sleep(0.05)

    with open(cache_path, 'w') as f:
        json.dump({tk: [str(d.date()) for d in dates] for tk, dates in result.items()}, f, indent=2)
    print(f"Cached to: {cache_path}")
    return result

earnings_map = fetch_earnings(ALL_TICKERS, EARNINGS_CACHE)

in_window = sum(
    1 for tk, dates in earnings_map.items()
    for d in dates if BACKTEST_START <= d <= BACKTEST_END
)
print(f"Earnings events in 2020–2022: {in_window} ({in_window // len(ALL_TICKERS)} avg per ticker)")

# ── Trading days from daily data ───────────────────────────────────────────────
if 'SPY' in daily_all:
    all_trading_days = sorted(daily_all['SPY'].index)
else:
    # build from union of all tickers
    all_dates = set()
    for df in daily_all.values():
        all_dates.update(df.index.tolist())
    all_trading_days = sorted(all_dates)

all_trading_days_set = set(all_trading_days)

def next_trading_day(date):
    check = date + timedelta(days=1)
    for _ in range(7):
        if check in all_trading_days_set:
            return check
        check += timedelta(days=1)
    return None

def compute_atr(daily, before_date):
    hist = daily[daily.index < before_date].tail(ATR_PERIOD + 1)
    if len(hist) < 2:
        return None
    hl  = hist['high'] - hist['low']
    hpc = (hist['high'] - hist['close'].shift(1)).abs()
    lpc = (hist['low']  - hist['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(ATR_PERIOD).mean())

# ── Simulation ─────────────────────────────────────────────────────────────────
print("\nSimulating SHORT trades...")

rows = []

for tk in ALL_TICKERS:
    if tk not in daily_all:
        continue
    daily = daily_all[tk]
    e_dates = [d for d in earnings_map.get(tk, []) if BACKTEST_START <= d <= BACKTEST_END]

    for e_date in e_dates:
        # Reaction day: check e_date and e_date+1, pick larger abs gap
        best_r_day, best_gap = None, 0.0

        for r_day in [e_date, next_trading_day(e_date)]:
            if r_day is None or r_day not in daily.index:
                continue
            prev_days = daily.index[daily.index < r_day]
            if len(prev_days) == 0:
                continue
            pc = float(daily.loc[prev_days[-1], 'close'])
            ro = float(daily.loc[r_day, 'open'])
            if pc <= 0 or ro <= 0:
                continue
            gap = (ro - pc) / pc
            if abs(gap) > abs(best_gap):
                best_gap, best_r_day = gap, r_day

        # SHORT only (gap down)
        if best_r_day is None or best_gap >= 0:
            continue

        regime = 'Normal' if best_r_day in normal_days_set else 'Other'

        atr = compute_atr(daily, best_r_day)
        if atr is None or atr <= 0:
            continue

        entry     = float(daily.loc[best_r_day, 'open'])
        stop_dist = STOP_ATR_MULT * atr
        if stop_dist < 0.005 * entry:
            continue

        stop_p  = entry + stop_dist
        tgt_p   = entry - TARGET_RR * stop_dist
        shares  = RISK_PER_TRADE / stop_dist

        td_from = [d for d in all_trading_days if d >= best_r_day and d <= BACKTEST_END]
        if len(td_from) <= 1:
            continue
        hold_day = td_from[1]
        if hold_day not in daily.index:
            continue

        dh = float(daily.loc[hold_day, 'high'])
        dl = float(daily.loc[hold_day, 'low'])

        if dh >= stop_p:
            ep, reason = stop_p,  'STOP'
        elif dl <= tgt_p:
            ep, reason = tgt_p,   'TARGET'
        else:
            ep, reason = float(daily.loc[hold_day, 'close']), 'TIME'

        pnl = -shares * (ep - entry)
        pool = 'existing' if tk in EXISTING_POOL else 'expansion'

        rows.append({
            'ticker':      tk,
            'pool':        pool,
            'reaction_day': best_r_day,
            'gap_pct':     best_gap,
            'regime':      regime,
            'pnl':         pnl,
            'exit_reason': reason,
            'year':        best_r_day.year,
        })

df = pd.DataFrame(rows)
if df.empty:
    print("No qualifying trades.")
    sys.exit(0)

print(f"Total events collected (all gap sizes, all regimes): {len(df)}")

SEP = "─" * 72

# ── Full grid: gap threshold × regime ─────────────────────────────────────────
print(f"\n{'═'*72}")
print("  GAP THRESHOLD × REGIME — Full universe (existing + expansion), Hold 1d")
print(SEP)
print(f"  {'Gap≥':>5}  {'Regime':>8}  {'N':>4}  {'Total':>9}  {'WR':>5}  {'Avg':>8}  "
      f"{'2020':>8}  {'2021':>8}  {'2022':>8}")
print(SEP)

for gap in [0.01, 0.02, 0.03, 0.05]:
    for regime_label, mask in [("Normal", df['regime'] == 'Normal'),
                                ("All",    pd.Series(True, index=df.index))]:
        g = df[(df['gap_pct'].abs() >= gap) & mask]
        if len(g) == 0:
            print(f"  {gap*100:>4.0f}%  {regime_label:>8}  {'—':>4}")
            continue
        y = {yr: g[g['year'] == yr]['pnl'].sum() for yr in [2020, 2021, 2022]}
        print(f"  {gap*100:>4.0f}%  {regime_label:>8}  {len(g):>4}  "
              f"${g['pnl'].sum():>+9,.0f}  {g['pnl'].gt(0).mean()*100:>4.0f}%  "
              f"${g['pnl'].mean():>+7.1f}  "
              f"${y[2020]:>+7,.0f}  ${y[2021]:>+7,.0f}  ${y[2022]:>+7,.0f}")
    print(SEP)

# ── Existing vs Expansion split ────────────────────────────────────────────────
print(f"\n{'═'*72}")
print("  EXISTING vs EXPANSION — Normal ≥1%, Hold 1d")
print(SEP)
base = df[(df['gap_pct'].abs() >= 0.01) & (df['regime'] == 'Normal')]
for pool in ['existing', 'expansion']:
    g = base[base['pool'] == pool]
    if len(g) == 0:
        print(f"  {pool}: no trades")
        continue
    y = {yr: g[g['year']==yr]['pnl'].sum() for yr in [2020, 2021, 2022]}
    print(f"  {pool:>10}: {len(g):3d}t  ${g['pnl'].sum():>+8,.0f}  "
          f"WR={g['pnl'].gt(0).mean()*100:.0f}%  Avg=${g['pnl'].mean():>+.1f}")
    for yr in [2020, 2021, 2022]:
        ys = g[g['year']==yr]
        if len(ys):
            print(f"             {yr}: {len(ys):2d}t  ${y[yr]:>+8,.0f}  WR={ys['pnl'].gt(0).mean()*100:.0f}%")

# ── Ticker breakdown: expansion only, Normal ≥1% ──────────────────────────────
print(f"\n{'═'*72}")
print("  EXPANSION TICKER BREAKDOWN — Normal ≥1%, Hold 1d")
print(SEP)
exp_base = df[(df['pool'] == 'expansion') & (df['gap_pct'].abs() >= 0.01) & (df['regime'] == 'Normal')]
if len(exp_base):
    by_tk = exp_base.groupby('ticker').agg(
        n=('pnl', 'count'),
        total=('pnl', 'sum'),
        wr=('pnl', lambda x: (x > 0).mean() * 100),
        avg=('pnl', 'mean'),
    ).sort_values('total', ascending=False)
    for tk, r in by_tk.iterrows():
        print(f"  {tk:6s}  {int(r['n']):2d}t  ${r['total']:>+8,.0f}  WR={r['wr']:.0f}%  Avg=${r['avg']:>+.1f}")
else:
    print("  No expansion trades in Normal regime ≥1%")

# ── Combined ticker breakdown (all tickers, Normal ≥1%) ───────────────────────
print(f"\n{'═'*72}")
print("  ALL TICKERS BREAKDOWN — Normal ≥1%, Hold 1d (sorted by P&L)")
print(SEP)
all_base = df[(df['gap_pct'].abs() >= 0.01) & (df['regime'] == 'Normal')]
by_tk_all = all_base.groupby('ticker').agg(
    n=('pnl', 'count'),
    total=('pnl', 'sum'),
    wr=('pnl', lambda x: (x > 0).mean() * 100),
    pool=('pool', 'first'),
).sort_values('total', ascending=False)
for tk, r in by_tk_all.iterrows():
    tag = '' if r['pool'] == 'existing' else ' [NEW]'
    print(f"  {tk:6s}{tag:<7}  {int(r['n']):2d}t  ${r['total']:>+8,.0f}  WR={r['wr']:.0f}%")

# ── All reg ≥5%: ticker breakdown ─────────────────────────────────────────────
print(f"\n{'═'*72}")
print("  ALL REG ≥5% TICKER BREAKDOWN (the real winner config)")
print(SEP)
g5 = df[df['gap_pct'].abs() >= 0.05].copy()
print(f"  Total: {len(g5)}t  ${g5['pnl'].sum():>+,.0f}  WR={g5['pnl'].gt(0).mean()*100:.0f}%")
for yr in [2020, 2021, 2022]:
    ys = g5[g5['year'] == yr]
    print(f"  {yr}: {len(ys):2d}t  ${ys['pnl'].sum():>+8,.0f}  WR={ys['pnl'].gt(0).mean()*100:.0f}%")
print(SEP)
by5 = g5.groupby('ticker').agg(
    n=('pnl', 'count'),
    total=('pnl', 'sum'),
    wr=('pnl', lambda x: (x > 0).mean() * 100),
    gap_avg=('gap_pct', lambda x: x.mean() * 100),
    pool=('pool', 'first'),
).sort_values('total', ascending=False)
for tk, r in by5.iterrows():
    tag = ' [NEW]' if r['pool'] == 'expansion' else ''
    print(f"  {tk:6s}{tag:<7} {int(r['n']):2d}t  ${r['total']:>+8,.0f}  "
          f"WR={r['wr']:.0f}%  avg_gap={r['gap_avg']:.1f}%")

# ── All reg ≥5%: exclude defensive bounce-back stocks ─────────────────────────
EXCLUDE_DEFENSIVES = ['PG', 'KO', 'PEP', 'JNJ', 'MRK', 'PFE', 'BMY', 'ABBV', 'WMT', 'MCD']
g5_filtered = g5[~g5['ticker'].isin(EXCLUDE_DEFENSIVES)]
print(f"\n  After excluding defensives (PG/KO/PEP/JNJ/pharma/WMT/MCD):")
print(f"  {len(g5_filtered)}t  ${g5_filtered['pnl'].sum():>+,.0f}  WR={g5_filtered['pnl'].gt(0).mean()*100:.0f}%")
for yr in [2020, 2021, 2022]:
    ys = g5_filtered[g5_filtered['year'] == yr]
    print(f"  {yr}: {len(ys):2d}t  ${ys['pnl'].sum():>+8,.0f}  WR={ys['pnl'].gt(0).mean()*100:.0f}%")

# ── Verdict ────────────────────────────────────────────────────────────────────
print(f"\n{'═'*72}")
print("  VERDICT")
print(SEP)
full_n1   = df[(df['gap_pct'].abs() >= 0.01) & (df['regime'] == 'Normal')]
exist_n1  = full_n1[full_n1['pool'] == 'existing']
g5_all    = df[df['gap_pct'].abs() >= 0.05]
g5_nodef  = g5_all[~g5_all['ticker'].isin(EXCLUDE_DEFENSIVES)]
print(f"  Normal ≥1% (existing only):  {len(exist_n1):3d}t  ${exist_n1['pnl'].sum():>+8,.0f}  WR={exist_n1['pnl'].gt(0).mean()*100:.0f}%  engine≈${exist_n1['pnl'].sum()*0.41:>+,.0f}")
print(f"  Normal ≥1% (full universe):  {len(full_n1):3d}t  ${full_n1['pnl'].sum():>+8,.0f}  WR={full_n1['pnl'].gt(0).mean()*100:.0f}%  engine≈${full_n1['pnl'].sum()*0.41:>+,.0f}")
print(f"  All reg ≥5% (all 62):        {len(g5_all):3d}t  ${g5_all['pnl'].sum():>+8,.0f}  WR={g5_all['pnl'].gt(0).mean()*100:.0f}%  engine≈${g5_all['pnl'].sum()*0.41:>+,.0f}")
print(f"  All reg ≥5% (no defensives): {len(g5_nodef):3d}t  ${g5_nodef['pnl'].sum():>+8,.0f}  WR={g5_nodef['pnl'].gt(0).mean()*100:.0f}%  engine≈${g5_nodef['pnl'].sum()*0.41:>+,.0f}")
