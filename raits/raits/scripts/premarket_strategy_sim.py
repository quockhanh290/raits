"""
premarket_strategy_sim.py — Pre-market bar strategy exploration

Tests three hypotheses using 04:00–09:29 ET pre-market bars from parquet cache:

  H1 — PM-Aligned GAP_FILL filter
       Current GAP_FILL: stock gaps DOWN 1.5-3% at regular open → LONG
       New filter: only take trade when pm_direction == +1
                   (stock recovering in pre-market before open)
       Compare vs baseline: 21t +$1,163 WR=81% (results_20260622_094328.pkl)

  H2 — Pre-market Gap-and-Go (new strategy, LONG)
       Signal: pm_return > +1.5% AND pm_fade == False
       Entry:  9:35 bar open (LONG)
       Stop:   pm_low - 0.1×ATR
       Target: pm_high + 50% × (pm_high - prev_close)
       Exit:   11:00 time stop
       Filter: Normal regime, SPY above VWAP at 9:35

  H3 — Pre-market Fade reversal (new strategy, SHORT)
       Signal: pm_return > +1.5% AND pm_fade == True
       Entry:  9:35 bar open (SHORT)
       Stop:   pm_high + 0.1×ATR
       Target: prev_close
       Exit:   11:00 time stop
       Filter: Normal regime, SPY above VWAP at 9:35

All sims use:
  - Fixed $500 risk per trade (sim convention)
  - $0.01/share × 2 commission
  - Normal regime days from results PKL
  - Bootstrap: resample-with-replacement, P(sum ≤ 0), N=10,000

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\premarket_strategy_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

# ── paths ────────────────────────────────────────────────────────────────────
PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_20260622_094328.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
CACHE_DIR   = r'd:\raits\raits\data\cache'

# ── sim constants ─────────────────────────────────────────────────────────────
RISK_PER_TRADE = 500.0
COMM_PER_SHARE = 0.01
N_BOOT         = 10_000

# H1 — GAP_FILL parameters (mirrors engine)
H1_GAP_MIN     = 0.015
H1_GAP_MAX     = 0.030
H1_RETRACE_MIN = 0.50
H1_RETRACE_MAX = 0.85
H1_ENTRY_TIME  = dtime(10, 30)
H1_EXIT_TIME   = dtime(13, 30)

# H2 / H3 entry / exit
H2H3_PM_RETURN_MIN = 0.015    # +1.5% pm move
H2H3_ENTRY_TIME    = dtime(9, 35)
H2H3_EXIT_TIME     = dtime(11, 0)


# ── load data ─────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_RESULTS, 'rb') as f:
    results = pickle.load(f)
with open(PKL_5MIN, 'rb') as f:
    data_5min = pickle.load(f)

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# ── Normal regime days ────────────────────────────────────────────────────────
normal_days = sorted({
    pd.to_datetime(t.entry_time).normalize()
    for w in results for t in w.get('trades', [])
    if getattr(t, 'hmm_state', None) == 'Normal'
})
print(f"Normal days: {len(normal_days)}")

available_tickers = [tk for tk in data_5min if tk != 'SPY']

# ── SPY VWAP lookup ───────────────────────────────────────────────────────────
spy = data_5min['SPY'].sort_index().copy()
spy['tp']      = (spy['high'] + spy['low'] + spy['close']) / 3
spy['tpv']     = spy['tp'] * spy['volume']
spy['date']    = spy.index.normalize()
spy['cum_tpv'] = spy.groupby('date')['tpv'].cumsum()
spy['cum_vol'] = spy.groupby('date')['volume'].cumsum()
spy['vwap']    = spy['cum_tpv'] / spy['cum_vol']
spy['above']   = spy['close'] > spy['vwap']
_spy_dict = (
    spy['above']
    .reindex(pd.date_range(spy.index[0], spy.index[-1], freq='5min'), method='ffill')
    .to_dict()
)
def spy_bull(ts):
    return _spy_dict.get(pd.Timestamp(ts).floor('5min'), None)


# ── ATR helper ────────────────────────────────────────────────────────────────
def compute_atr(bars, period=14):
    if len(bars) < 2:
        return float(bars['close'].iloc[-1]) * 0.015
    hl  = bars['high'] - bars['low']
    hpc = (bars['high'] - bars['close'].shift(1)).abs()
    lpc = (bars['low']  - bars['close'].shift(1)).abs()
    return float(pd.concat([hl, hpc, lpc], axis=1).max(axis=1).tail(period).mean())


# ── prev_close map ────────────────────────────────────────────────────────────
print("Precomputing prev_close map...")
prev_close_map = {}
for ticker in available_tickers:
    bars = data_5min[ticker].sort_index()
    bars_date = bars.index.normalize()
    daily_last = bars.groupby(bars_date)['close'].last()
    dates = daily_last.index.tolist()
    for i in range(1, len(dates)):
        prev_close_map[(ticker, dates[i])] = float(daily_last.iloc[i - 1])


# ── cache day bars for Normal days ────────────────────────────────────────────
print("Caching day bars...")
day_bars_cache = {}
for day in normal_days:
    for ticker in available_tickers:
        db = data_5min[ticker]
        db_day = db[db.index.normalize() == day].sort_index()
        if len(db_day) >= 8:
            day_bars_cache[(ticker, day)] = db_day


# ── build pre-market DataFrame ────────────────────────────────────────────────
PM_CACHE = r'd:\raits\raits\data\cache\premarket_features.pkl'
if os.path.exists(PM_CACHE):
    print("Loading pre-market features from cache...")
    pm_df = pd.read_pickle(PM_CACHE)
else:
    print("Building pre-market features from parquet (first run, ~30s)...")
    from raits.data.raits_premarket import build_premarket_df
    pm_df = build_premarket_df(data_5min, CACHE_DIR, dates=normal_days)
    pm_df.to_pickle(PM_CACHE)
    print(f"  Saved to {PM_CACHE}")
print(f"Pre-market rows: {len(pm_df):,}  tickers: {pm_df.index.get_level_values('ticker').nunique()}")

# Quick lookup: pm.loc[(ticker, day)] → row
def get_pm(ticker, day):
    try:
        return pm_df.loc[(ticker, pd.Timestamp(day))]
    except KeyError:
        return None


# ── bootstrap helper ──────────────────────────────────────────────────────────
def bootstrap(pnls, label):
    if not pnls:
        print(f"\n  {label}: no trades — skip bootstrap")
        return
    outcomes = np.array(pnls)
    observed = outcomes.sum()
    rng  = np.random.default_rng(42)
    boot = np.array([
        rng.choice(outcomes, size=len(outcomes), replace=True).sum()
        for _ in range(N_BOOT)
    ])
    p_val = (boot <= 0).mean()
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])
    sig = "✓ significant" if p_val < 0.05 else "✗ NOT significant"
    print(f"  Bootstrap (N={N_BOOT:,}): p={p_val:.3f}  CI=[${ci_lo:+,.0f}, ${ci_hi:+,.0f}]  {sig}")


# ╔══════════════════════════════════════════════════════════════════════════════
# ║  H1 — PM-Aligned GAP_FILL
# ╚══════════════════════════════════════════════════════════════════════════════
def run_h1(require_pm_direction):
    """
    Simulate GAP_FILL with optional pm_direction filter.
    If require_pm_direction=True: only trade when pm_direction == +1.
    Returns list of trade dicts.
    """
    trades = []
    for day in normal_days:
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None:
                continue

            prev_c = prev_close_map.get((ticker, day))
            if prev_c is None or prev_c <= 0:
                continue

            # ── pre-market filter ────────────────────────────────────────────
            if require_pm_direction:
                pm = get_pm(ticker, day)
                if pm is None or pm['pm_direction'] != 1:
                    continue

            # ── gap check ────────────────────────────────────────────────────
            first_bar = db[db.index.time >= dtime(9, 30)]
            if first_bar.empty:
                continue
            session_open = float(first_bar.iloc[0]['open'])
            gap_pct  = (session_open - prev_c) / prev_c
            gap_size = session_open - prev_c

            if gap_pct >= 0 or abs(gap_pct) < H1_GAP_MIN or abs(gap_pct) > H1_GAP_MAX:
                continue

            # ── retrace check at 10:30 ────────────────────────────────────────
            pre_entry = db[db.index.time <= H1_ENTRY_TIME]
            if pre_entry.empty:
                continue
            px_entry = float(pre_entry.iloc[-1]['close'])
            retrace  = (session_open - px_entry) / gap_size if gap_size != 0 else 0
            if not (H1_RETRACE_MIN <= retrace <= H1_RETRACE_MAX):
                continue

            # ── SPY filter ────────────────────────────────────────────────────
            if spy_bull(pre_entry.index[-1]) is False:
                continue

            # ── position sizing ───────────────────────────────────────────────
            morning_lod = float(pre_entry['low'].min())
            atr         = compute_atr(pre_entry)
            if atr <= 0:
                continue
            stop_px   = morning_lod - 0.1 * atr
            stop_dist = abs(px_entry - stop_px)
            if stop_dist <= 0:
                continue
            shares    = max(1, int(RISK_PER_TRADE / stop_dist))
            target_px = prev_c + 0.50 * abs(gap_size)

            # ── execution ─────────────────────────────────────────────────────
            bars_after = db[
                (db.index.time > H1_ENTRY_TIME) & (db.index.time < H1_EXIT_TIME)
            ]
            trailing = stop_px
            exit_px  = px_entry
            reason   = 'TIME_STOP'
            for _, b in bars_after.iterrows():
                trailing = max(trailing, float(b['high']) - stop_dist)
                if float(b['low']) <= trailing:
                    exit_px = trailing; reason = 'STOP_HIT'; break
                if float(b['high']) >= target_px:
                    exit_px = target_px; reason = 'TARGET_HIT'; break
                exit_px = float(b['close'])

            net = (exit_px - px_entry) * shares - shares * COMM_PER_SHARE * 2
            trades.append(dict(
                ticker=ticker, day=day, year=str(day.year),
                exit_reason=reason, net_pnl=net, win=net > 0,
            ))
    return trades


# ╔══════════════════════════════════════════════════════════════════════════════
# ║  H2 — Pre-market Gap-and-Go (LONG)
# ╚══════════════════════════════════════════════════════════════════════════════
def run_h2():
    trades = []
    for day in normal_days:
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None:
                continue

            pm = get_pm(ticker, day)
            if pm is None:
                continue

            # Signal: strong PM move, not fading
            if pm['pm_return'] <= H2H3_PM_RETURN_MIN:
                continue
            if pm['pm_fade']:
                continue

            prev_c = prev_close_map.get((ticker, day))
            if prev_c is None or prev_c <= 0:
                continue

            # Entry: 9:35 bar open
            entry_bars = db[db.index.time >= H2H3_ENTRY_TIME]
            if entry_bars.empty:
                continue
            entry_bar = entry_bars.iloc[0]
            px_entry  = float(entry_bar['open'])

            # SPY filter
            if spy_bull(entry_bar.name) is False:
                continue

            # ATR from pre-market bars — fall back to 1.5% if too few
            atr = float(pm['pm_range_pct'] * px_entry) if pm['pm_range_pct'] > 0 else px_entry * 0.015

            pm_low    = float(pm['pm_low'])
            pm_high   = float(pm['pm_high'])
            stop_px   = pm_low - 0.1 * atr
            stop_dist = abs(px_entry - stop_px)
            if stop_dist <= 0 or px_entry <= stop_px:
                continue
            shares    = max(1, int(RISK_PER_TRADE / stop_dist))
            target_px = pm_high + 0.50 * abs(pm_high - prev_c)

            # Execution
            bars_after = db[
                (db.index.time > H2H3_ENTRY_TIME) & (db.index.time < H2H3_EXIT_TIME)
            ]
            trailing = stop_px
            exit_px  = px_entry
            reason   = 'TIME_STOP'
            for _, b in bars_after.iterrows():
                trailing = max(trailing, float(b['high']) - stop_dist)
                if float(b['low']) <= trailing:
                    exit_px = trailing; reason = 'STOP_HIT'; break
                if float(b['high']) >= target_px:
                    exit_px = target_px; reason = 'TARGET_HIT'; break
                exit_px = float(b['close'])

            net = (exit_px - px_entry) * shares - shares * COMM_PER_SHARE * 2
            trades.append(dict(
                ticker=ticker, day=day, year=str(day.year),
                pm_return=round(pm['pm_return'] * 100, 2),
                pm_fade=pm['pm_fade'],
                exit_reason=reason, net_pnl=net, win=net > 0,
            ))
    return trades


# ╔══════════════════════════════════════════════════════════════════════════════
# ║  H3 — Pre-market Fade reversal (SHORT)
# ╚══════════════════════════════════════════════════════════════════════════════
def run_h3():
    trades = []
    for day in normal_days:
        for ticker in available_tickers:
            db = day_bars_cache.get((ticker, day))
            if db is None:
                continue

            pm = get_pm(ticker, day)
            if pm is None:
                continue

            # Signal: strong PM move but fading
            if pm['pm_return'] <= H2H3_PM_RETURN_MIN:
                continue
            if not pm['pm_fade']:
                continue

            prev_c = prev_close_map.get((ticker, day))
            if prev_c is None or prev_c <= 0:
                continue

            # Entry: 9:35 bar open
            entry_bars = db[db.index.time >= H2H3_ENTRY_TIME]
            if entry_bars.empty:
                continue
            entry_bar = entry_bars.iloc[0]
            px_entry  = float(entry_bar['open'])

            # SPY filter — for SHORT we want SPY NOT strongly above VWAP?
            # Keep symmetric with H2: SPY above VWAP (market still up, fade is stock-specific)
            if spy_bull(entry_bar.name) is False:
                continue

            atr = float(pm['pm_range_pct'] * px_entry) if pm['pm_range_pct'] > 0 else px_entry * 0.015

            pm_high   = float(pm['pm_high'])
            stop_px   = pm_high + 0.1 * atr          # stop above pm high
            stop_dist = abs(stop_px - px_entry)
            if stop_dist <= 0 or px_entry >= stop_px:
                continue
            shares    = max(1, int(RISK_PER_TRADE / stop_dist))
            target_px = prev_c                         # target: fill gap back to prev close

            if target_px >= px_entry:                  # already below prev close → skip
                continue

            # Execution (SHORT)
            bars_after = db[
                (db.index.time > H2H3_ENTRY_TIME) & (db.index.time < H2H3_EXIT_TIME)
            ]
            trailing = stop_px
            exit_px  = px_entry
            reason   = 'TIME_STOP'
            for _, b in bars_after.iterrows():
                trailing = min(trailing, float(b['low']) + stop_dist)
                if float(b['high']) >= trailing:
                    exit_px = trailing; reason = 'STOP_HIT'; break
                if float(b['low']) <= target_px:
                    exit_px = target_px; reason = 'TARGET_HIT'; break
                exit_px = float(b['close'])

            net = (px_entry - exit_px) * shares - shares * COMM_PER_SHARE * 2
            trades.append(dict(
                ticker=ticker, day=day, year=str(day.year),
                pm_return=round(pm['pm_return'] * 100, 2),
                pm_fade=pm['pm_fade'],
                exit_reason=reason, net_pnl=net, win=net > 0,
            ))
    return trades


# ── print helper ──────────────────────────────────────────────────────────────
def print_results(label, trades, compare_label=None, compare_n=None, compare_pnl=None):
    print(f"\n{'='*65}")
    print(f"  {label}")
    print(f"{'='*65}")

    if compare_label:
        print(f"  Baseline {compare_label}: {compare_n}t  ${compare_pnl:+,.0f}")

    if not trades:
        print("  No trades generated.")
        return

    df  = pd.DataFrame(trades)
    pnl = df['net_pnl'].sum()
    wr  = df['win'].mean()
    avg = df['net_pnl'].mean()
    n   = len(df)
    print(f"  This sim: {n}t  P&L=${pnl:+,.0f}  WR={wr:.0%}  avg=${avg:+.1f}/t")

    print(f"\n  By year:")
    for yr in ['2020', '2021', '2022']:
        s = df[df['year'] == yr]
        if len(s):
            p = s['net_pnl'].sum()
            w = s['win'].mean()
            print(f"    {yr}: {len(s):3d}t  P&L=${p:+7,.0f}  WR={w:.0%}  avg=${p/len(s):+.1f}")
        else:
            print(f"    {yr}:   0t  (no trades)")

    print(f"\n  By exit reason:")
    for ex in sorted(df['exit_reason'].unique()):
        s = df[df['exit_reason'] == ex]
        p = s['net_pnl'].sum()
        w = s['win'].mean()
        print(f"    {ex:<14}: {len(s):3d}t  ${p:+7,.0f}  WR={w:.0%}")

    print(f"\n  By ticker (top 10):")
    tk_grp = df.groupby('ticker')['net_pnl'].agg(n='count', total='sum').sort_values('total', ascending=False)
    for ticker, row in tk_grp.head(10).iterrows():
        s = df[df['ticker'] == ticker]
        w = s['win'].mean()
        print(f"    {ticker:<6}: {int(row['n']):2d}t  ${row['total']:+7,.0f}  WR={w:.0%}")

    bootstrap(df['net_pnl'].tolist(), label)


# ── run all ───────────────────────────────────────────────────────────────────
baseline_gf = [t for w in results for t in w.get('trades', []) if t.strategy == 'GAP_FILL']
baseline_pnl = sum(t.net_pnl for t in baseline_gf)
baseline_n   = len(baseline_gf)

print("\n\nRunning H1 baseline (no PM filter)...")
h1_base   = run_h1(require_pm_direction=False)
print("Running H1 with PM direction filter...")
h1_filter = run_h1(require_pm_direction=True)
print("Running H2 (PM Gap-and-Go)...")
h2_trades = run_h2()
print("Running H3 (PM Fade SHORT)...")
h3_trades = run_h3()

# ── engine baseline for H1 ────────────────────────────────────────────────────
print_results(
    "H1 GAP_FILL — NO PM filter (sim baseline)",
    h1_base,
    compare_label="engine GAP_FILL",
    compare_n=baseline_n,
    compare_pnl=baseline_pnl,
)

print_results(
    "H1 GAP_FILL — PM direction == +1 filter",
    h1_filter,
    compare_label="H1 no-filter sim",
    compare_n=len(h1_base),
    compare_pnl=sum(t['net_pnl'] for t in h1_base),
)

# H1 delta: what the filter removes
if h1_base and h1_filter:
    df_base   = pd.DataFrame(h1_base)
    df_filter = pd.DataFrame(h1_filter)
    removed   = len(df_base) - len(df_filter)
    pnl_removed = df_base['net_pnl'].sum() - df_filter['net_pnl'].sum()
    print(f"\n  Filter removes {removed} trades worth ${pnl_removed:+,.0f}")
    wr_kept    = df_filter['win'].mean() if len(df_filter) else 0
    wr_removed = (
        pd.DataFrame([t for t in h1_base if not any(
            t['ticker'] == f['ticker'] and t['day'] == f['day'] for f in h1_filter
        )])['win'].mean()
        if removed > 0 else float('nan')
    )
    print(f"  WR kept={wr_kept:.0%}  WR removed={wr_removed:.0%}" if not pd.isna(wr_removed) else f"  WR kept={wr_kept:.0%}")

print_results("H2 — Pre-market Gap-and-Go (LONG, entry 9:35)", h2_trades)
print_results("H3 — Pre-market Fade reversal (SHORT, entry 9:35)", h3_trades)

print(f"\n{'='*65}")
print("  SUMMARY")
print(f"{'='*65}")
print(f"  H1 no-filter sim:   {len(h1_base)}t  ${sum(t['net_pnl'] for t in h1_base):+,.0f}")
print(f"  H1 PM-filter:       {len(h1_filter)}t  ${sum(t['net_pnl'] for t in h1_filter):+,.0f}")
print(f"  H2 Gap-and-Go:      {len(h2_trades)}t  ${sum(t['net_pnl'] for t in h2_trades):+,.0f}")
print(f"  H3 PM Fade SHORT:   {len(h3_trades)}t  ${sum(t['net_pnl'] for t in h3_trades):+,.0f}")
print()
