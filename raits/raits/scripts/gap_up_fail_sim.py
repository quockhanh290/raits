"""
gap_up_fail_sim.py — Earnings Gap UP + Fail SHORT

Hypothesis: stock gaps UP ≥ threshold on earnings but fails to hold (close ≤ open
by a specific time) → institutions selling into strength → SHORT for gap fill.

Setup:
  Universe : PE_SHORT expanded universe (62 stocks)
  Calendar : earnings_dates_expanded.json
  Gap      : open / prior_close - 1 ≥ threshold (UP gap)
  Fail     : close[fail_time] ≤ open[9:30]  (couldn't hold the opening print)
  Entry    : close of fail_time bar (SHORT)
  Stop     : open[9:30] + 0.5×ATR  (above the gap level)
  Target   : prior_close  OR  2R (take first)
  Exit     : same-day 15:55 EOD if neither hit

Grid: gap_threshold × fail_time × regime
Bootstrap per config.

Usage:
    cd d:\\raits\\raits
    py -3.11 raits\\scripts\\gap_up_fail_sim.py
"""
import sys, os, pickle, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings; warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from datetime import time as dtime
from itertools import product

PKL_RESULTS    = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN       = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
EARNINGS_CACHE = r'd:\raits\raits\data\cache\earnings_dates_expanded.json'

PE_UNIVERSE = [
    "AAPL","MSFT","AMZN","GOOGL","META","NVDA","TSLA","AMD",
    "QCOM","INTC","MU","AVGO","TXN","AMAT","ADBE","CRM","ORCL","INTU","CSCO",
    "AMGN","GILD","BIIB","REGN","VRTX",
    "COST","SBUX","NFLX","EBAY",
    "JPM","GS","MS","V","MA",
    "HON","MMM","XOM","CVX",
    "GE","PANW","NOW","PYPL",
]

RISK_PER_TRADE = 500.0
ATR_PERIOD     = 14
STOP_BUFFER    = 0.005   # 0.5% above open as extra stop buffer
N_BOOT         = 10_000
BACKTEST_START = pd.Timestamp("2020-01-01")
BACKTEST_END   = pd.Timestamp("2022-12-31")

print("Loading data...")
with open(PKL_RESULTS, 'rb') as f: results = pickle.load(f)
with open(PKL_5MIN, 'rb') as f:    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

if not os.path.exists(EARNINGS_CACHE):
    print(f"ERROR: earnings calendar not found at {EARNINGS_CACHE}")
    sys.exit(1)
with open(EARNINGS_CACHE) as f:
    raw_calendar = json.load(f)

# date → list of tickers reporting
earnings_by_date: dict = {}
for tk, dates in raw_calendar.items():
    if tk not in PE_UNIVERSE:
        continue
    for d in dates:
        ts = pd.Timestamp(d)
        if BACKTEST_START <= ts <= BACKTEST_END:
            earnings_by_date.setdefault(ts, []).append(tk)

print(f"Calendar: {sum(len(v) for v in earnings_by_date.values())} ticker-dates "
      f"across {len(earnings_by_date)} days")

# Regime days from engine
normal_days  = set()
all_days_set = set()
for w in results:
    for t in w.get('trades', []):
        d = pd.to_datetime(t.entry_time).normalize()
        all_days_set.add(d)
        if getattr(t, 'hmm_state', None) == 'Normal':
            normal_days.add(d)

# ATR helper
def compute_atr(bars, period=ATR_PERIOD):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015 if not bars.empty else 0.01
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())

# Bootstrap
rng = np.random.default_rng(42)
def bootstrap(pnls):
    if len(pnls) < 5:
        return float('nan'), float('nan'), float('nan')
    a = np.array(pnls)
    boot = np.array([rng.choice(a, size=len(a), replace=True).sum()
                     for _ in range(N_BOOT)])
    return (boot <= 0).mean(), *np.percentile(boot, [2.5, 97.5])

# Simulate one trade
def simulate_trade(ticker, day, bars, prior_close, fail_time):
    b930 = bars[bars.index.time == dtime(9, 30)]
    if b930.empty:
        return None
    open_px = float(b930.iloc[0]['open'])

    # Gap UP check done outside
    # Fail check: close at fail_time ≤ open
    b_fail = bars[bars.index.time == fail_time]
    if b_fail.empty:
        return None
    fail_close = float(b_fail.iloc[0]['close'])
    if fail_close > open_px:
        return None   # gap holding → no trade

    # Entry at fail bar close (SHORT)
    entry_px = fail_close
    entry_ts = b_fail.index[0]

    # ATR from bars up to entry
    atr = compute_atr(bars[bars.index <= entry_ts])
    if atr <= 0:
        return None

    stop_px   = open_px * (1 + STOP_BUFFER)  # above opening print
    stop_dist = stop_px - entry_px
    if stop_dist <= 0:
        return None

    target_gap  = prior_close                        # full gap fill
    target_2r   = entry_px - 2.0 * stop_dist        # 2R
    target_px   = max(target_gap, target_2r)         # take whichever is closer (less negative)

    shares = max(1, int(RISK_PER_TRADE / stop_dist))

    # Walk forward bars after entry
    bars_after = bars[
        (bars.index > entry_ts) & (bars.index.time <= dtime(15, 55))
    ]
    exit_px = entry_px
    reason  = 'TIME_STOP'

    for _, b in bars_after.iterrows():
        if float(b['high']) >= stop_px:
            exit_px = stop_px; reason = 'STOP_HIT'; break
        if float(b['low']) <= target_px:
            exit_px = target_px; reason = 'TARGET_HIT'; break
        exit_px = float(b['close'])

    net = (entry_px - exit_px) * shares - shares * 0.01 * 2

    return dict(
        ticker=ticker, day=day, year=str(day.year),
        gap_pct=round((open_px / prior_close - 1) * 100, 2),
        fail_time=str(fail_time), exit_reason=reason,
        net_pnl=net, win=net > 0,
    )

# Grid search
GAP_THRESHOLDS = [0.03, 0.05, 0.07]
FAIL_TIMES     = [dtime(9, 40), dtime(9, 45), dtime(10, 0), dtime(10, 15)]
REGIME_SETS    = [
    ('All regimes', all_days_set),
    ('Normal only', normal_days),
]

print("\nRunning grid search...\n")
best = []

for regime_label, regime_days in REGIME_SETS:
    print(f"\n{'='*75}")
    print(f"  REGIME: {regime_label}")
    print(f"{'='*75}")
    print(f"  {'Gap':>5}  {'Fail':>6}  {'N':>4}  {'P&L':>9}  {'WR':>5}  {'avg':>7}  {'p':>6}  {'CI'}")
    print(f"  {'-'*72}")

    for gap_thr, fail_t in product(GAP_THRESHOLDS, FAIL_TIMES):
        trades = []
        for day, tickers in sorted(earnings_by_date.items()):
            if day not in regime_days:
                continue
            for ticker in tickers:
                if ticker not in data_5min:
                    continue
                bars = data_5min[ticker]
                day_bars = bars[bars.index.normalize() == day].sort_index()
                if len(day_bars) < 6:
                    continue

                # Prior close: last bar of previous trading day
                prev_bars = bars[bars.index.normalize() < day].sort_index()
                if prev_bars.empty:
                    continue
                prior_close = float(prev_bars.iloc[-1]['close'])
                if prior_close <= 0:
                    continue

                # Gap UP check
                b930 = day_bars[day_bars.index.time == dtime(9, 30)]
                if b930.empty:
                    continue
                open_px = float(b930.iloc[0]['open'])
                gap_pct = open_px / prior_close - 1

                if gap_pct < gap_thr:
                    continue

                r = simulate_trade(ticker, day, day_bars, prior_close, fail_t)
                if r:
                    trades.append(r)

        if not trades:
            print(f"  {gap_thr*100:.0f}%    {str(fail_t)[:5]}     0      —")
            continue

        df   = pd.DataFrame(trades)
        pnl  = df['net_pnl'].sum()
        wr   = df['win'].mean()
        avg  = df['net_pnl'].mean()
        p, cl, ch = bootstrap(df['net_pnl'].tolist())
        sig  = '✓' if (not pd.isna(p) and p < 0.05) else ' '
        p_s  = f"{p:.3f}" if not pd.isna(p) else "  —  "
        ci_s = f"[${cl:+,.0f},${ch:+,.0f}]" if not pd.isna(p) else ""
        print(f"  {gap_thr*100:.0f}%    {str(fail_t)[:5]}  {len(df):>4}  ${pnl:>8,.0f}"
              f"  {wr:>4.0%}  ${avg:>6.1f}  {p_s}{sig}  {ci_s}")

        if not pd.isna(p) and p < 0.05 and pnl > 0:
            best.append((regime_label, gap_thr, fail_t, trades))

# Detail for significant configs
if best:
    print(f"\n\n{'='*75}")
    print("  SIGNIFICANT CONFIGS — DETAIL")
    print(f"{'='*75}")
    for regime_label, gap_thr, fail_t, trades in best:
        df  = pd.DataFrame(trades)
        pnl = df['net_pnl'].sum()
        wr  = df['win'].mean()
        p, cl, ch = bootstrap(df['net_pnl'].tolist())
        print(f"\n  [{regime_label}] gap≥{gap_thr*100:.0f}%  fail@{fail_t}  "
              f"{len(df)}t  ${pnl:+,.0f}  WR={wr:.0%}  p={p:.3f}")

        print(f"  By year:")
        for yr in ['2020', '2021', '2022']:
            s = df[df['year'] == yr]
            if len(s):
                print(f"    {yr}: {len(s):3d}t  ${s['net_pnl'].sum():+7,.0f}  WR={s['win'].mean():.0%}")

        print(f"  By ticker (top 8):")
        grp = df.groupby('ticker')['net_pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
        for tk, row in grp.head(8).iterrows():
            s = df[df['ticker'] == tk]
            print(f"    {tk:<6}: {int(row['n']):2d}t  ${row['total']:+7,.0f}  WR={s['win'].mean():.0%}")

        print(f"  By exit:")
        for ex in sorted(df['exit_reason'].unique()):
            s = df[df['exit_reason'] == ex]
            print(f"    {ex:<14}: {len(s):3d}t  ${s['net_pnl'].sum():+7,.0f}  WR={s['win'].mean():.0%}")

        print(f"  Bootstrap: p={p:.3f}  CI=[${cl:+,.0f}, ${ch:+,.0f}]")
else:
    print("\n  No significant configs found.")
print()
