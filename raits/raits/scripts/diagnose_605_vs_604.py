"""
diagnose_605_vs_604.py
-----------------------
Find exactly WHY corrected-CB gives 605 trades / $15,019.79 instead of
old-CB 604 / $15,952.15.

Both baselines use window_debug_5min.pkl (same data).
Old CB = ORIG before fix: only STOP/TARGET/TIME_STOP count toward streak.
New CB = after fix: daily-drawdown-CB also counts; SAFETY_MODE does not.

This script:
  1. Re-runs OLD CB (subclass disabling update_cb) to reconstruct 604 baseline
  2. Loads new 605 baseline from committed CSV
  3. Diffs them: which trades are in one but not the other
  4. Traces streak evolution around each differing trade
  5. Shows P&L breakdown

Usage:
    cd d:\\raits\\raits
    python raits/scripts/diagnose_605_vs_604.py
"""

import sys, os, csv, pickle, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import warnings; warnings.filterwarnings('ignore')
import pandas as pd

from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE = os.path.join(os.path.dirname(__file__), '..', '..')
PICKLE_5MIN  = os.path.join(_BASE, 'data', 'cache', 'window_debug_5min.pkl')
PICKLE_DAILY = os.path.join(_BASE, 'data', 'cache', 'window_debug_daily.pkl')
NEW_CSV      = os.path.join(_BASE, '..', '..', 'baselines',
                             'is_baseline_cb_fixed_2026-07-08.csv')

# Fall back: look for the pkl
NEW_PKL = os.path.join(_BASE, 'data', 'cache', 'verify_cb_fixed_baseline.pkl')

import yaml as _yaml
_PARAMS = os.path.join(_BASE, 'configs', 'final_params.yaml')
with open(_PARAMS) as f:
    params = _yaml.safe_load(f)

IS_START = '2017-01-03'
IS_END   = '2022-12-30'

UNIVERSE     = ['TSLA','NVDA','AAPL','META','AMZN','MSFT','AMD','GOOGL']
PHASE1       = ['INTU','COST','VRTX','AMAT','REGN','AVGO','ADBE','MS',
                'SBUX','TXN','XOM','AMGN','ORCL','EBAY','QCOM','CVX',
                'CSCO','GS','CRM','JPM']
PHASE2       = ['MU','HON','MA','NFLX','INTC','V','GILD','BIIB','MMM']
PE_EXPANSION = ['PFE','MRK','LLY','ABBV','JNJ','BMY','BAC','WFC','C',
                'WMT','TGT','HD','LOW','MCD','NKE','PG','KO','PEP',
                'CAT','DE','BA','GE','PYPL','PANW','NOW']
SECTOR_ETFS  = ['XLF','XLE','XLV','XLU','XLI','XLK','XLP','XLB','XLY','GLD']
TICKERS      = ['SPY','QQQ','IWM'] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION


def make_config():
    return BacktestConfig(
        account_equity=50_000.0, start_date=IS_START, end_date=IS_END,
        universe=UNIVERSE+PHASE1+PHASE2, orb_universe=list(CANDIDATE_POOL),
        vwap_universe=['SPY','QQQ','IWM'],
        orb_range_minutes=params['orb_range_minutes'],
        vwap_bb_std=params['vwap_bb_std'], ema_period=params['ema_period'],
        max_risk_pct=0.015, max_position_pct=0.40, kelly_fraction=0.75,
        enable_costs=True, enable_pdt_guard=True, hmm_retrain_weekly=True,
        allow_swing_hold=True, max_hold_days=5, stress_size_fraction=0.5,
        log_level='WARNING',
    )


# ── Old CB engine: disables update_cb for CIRCUIT_BREAKER ────────────────────

class OldCBEngine(BacktestEngine):
    """
    Replicates pre-fix ORIG behavior:
    - daily-drawdown-CB exits do NOT update consecutive-loss streak
    - SAFETY_MODE already uses _close_all (unchanged from ORIG)
    This reconstructs the old 604-trade baseline.
    """
    def _close_all(self, timestamp, day_stocks, reason,
                   skip_swing=False, skip_tf=False,
                   circuit_breakers=None, update_cb=False):
        # Force update_cb=False regardless of what caller passes
        super()._close_all(timestamp, day_stocks, reason,
                            skip_swing=skip_swing, skip_tf=skip_tf,
                            circuit_breakers=circuit_breakers, update_cb=False)


def trade_key(t):
    """Unique key for a trade (handles both object and dict forms)."""
    if isinstance(t, dict):
        return (str(t.get('entry_time','')), t.get('ticker',''), t.get('strategy',''))
    return (str(getattr(t,'entry_time','')), getattr(t,'ticker',''), getattr(t,'strategy',''))


def load_new_605():
    """Load new 605-trade baseline from committed CSV (preferred) or pkl."""
    if os.path.exists(NEW_CSV):
        trades = []
        with open(NEW_CSV, newline='') as f:
            for row in csv.DictReader(f):
                trades.append(row)
        print(f'New baseline loaded from CSV: {len(trades)} trades')
        return trades
    # Fall back to pkl
    with open(NEW_PKL, 'rb') as f:
        result = pickle.load(f)
    trades = result.trade_log
    print(f'New baseline loaded from pkl: {len(trades)} trades')
    return trades


def get_pnl(t):
    if isinstance(t, dict):
        v = t.get('net_pnl')
        return float(v) if v not in (None, '') else 0.0
    return getattr(t, 'net_pnl', 0.0) or 0.0


def main():
    print('=' * 65)
    print('DIAGNOSE: 605 (new CB) vs 604 (old CB) — same window_debug data')
    print('=' * 65)
    print('\nData source: window_debug_5min.pkl (BOTH baselines use this)')
    print('Difference is CB semantics only, not dataset.\n')

    # Step 1: Load new 605 baseline
    new_trades = load_new_605()
    new_pnl    = sum(get_pnl(t) for t in new_trades)
    new_keys   = {trade_key(t): t for t in new_trades}

    # Step 2: Run OLD CB to reconstruct 604
    print('Loading market data...')
    with open(PICKLE_5MIN, 'rb') as f:
        all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}
    for t in list(market_data):
        df = market_data[t]
        market_data[t] = df[(df.index >= pd.Timestamp(IS_START)) &
                            (df.index <= pd.Timestamp(IS_END))]
    with open(PICKLE_DAILY, 'rb') as f:
        daily_data = pickle.load(f)
    config = make_config()

    print('\nRunning OldCBEngine (pre-fix, no daily-CB streak update)...')
    t0 = time.time()
    old_engine = OldCBEngine(config)
    old_result = old_engine.run(market_data, daily_data)
    old_trades = old_result.trade_log
    old_pnl    = sum(t.net_pnl or 0 for t in old_trades)
    print(f'  OldCB: {len(old_trades)} trades | P&L ${old_pnl:,.2f} | {time.time()-t0:.1f}s')

    old_keys = {trade_key(t): t for t in old_trades}

    # Step 3: Diff
    only_in_new = [k for k in new_keys if k not in old_keys]
    only_in_old = [k for k in old_keys if k not in new_keys]

    print(f'\n{"─"*65}')
    print(f'DIFF SUMMARY')
    print(f'  Old CB: {len(old_trades)} trades | ${old_pnl:,.2f}')
    print(f'  New CB: {len(new_trades)} trades | ${new_pnl:,.2f}')
    print(f'  Delta: {len(new_trades)-len(old_trades):+d} trades | ${new_pnl-old_pnl:+,.2f}')
    print(f'  In new only: {len(only_in_new)} trade(s)')
    print(f'  In old only: {len(only_in_old)} trade(s)')

    if only_in_new:
        print(f'\nTRADES IN NEW (605) BUT NOT IN OLD (604) — unblocked by CB fix:')
        for k in only_in_new:
            t = new_keys[k]
            pnl = get_pnl(t)
            print(f'  entry={k[0]}  ticker={k[1]}  strategy={k[2]}  pnl=${pnl:.2f}')

    if only_in_old:
        print(f'\nTRADES IN OLD (604) BUT NOT IN NEW (605) — blocked by CB fix:')
        for k in only_in_old:
            t = old_keys[k]
            pnl = t.net_pnl or 0
            print(f'  entry={k[0]}  ticker={k[1]}  strategy={k[2]}  pnl=${pnl:.2f}')

    # Step 4: P&L breakdown — where is the $932 difference?
    print(f'\n{"─"*65}')
    print('P&L BREAKDOWN — where does the delta come from?')
    print(f'  Total delta: ${new_pnl - old_pnl:+,.2f}')

    # Trades only in new (extra P&L contribution)
    if only_in_new:
        extra_pnl = sum(get_pnl(new_keys[k]) for k in only_in_new)
        print(f'  Extra trades in new:  ${extra_pnl:+,.2f}')
    if only_in_old:
        missing_pnl = sum((old_keys[k].net_pnl or 0) for k in only_in_old)
        print(f'  Missing trades in new: ${-missing_pnl:+,.2f} (these were in old but not new)')

    # Common trades — do any have different fields? (shouldn't if both engines are identical)
    common_keys = [k for k in old_keys if k in new_keys]
    common_delta = sum(
        get_pnl(new_keys[k]) - (old_keys[k].net_pnl or 0)
        for k in common_keys
    )
    print(f'  Common trades P&L delta: ${common_delta:+,.2f}')
    # Find largest common-trade deltas
    common_diffs = []
    for k in common_keys:
        d = get_pnl(new_keys[k]) - (old_keys[k].net_pnl or 0)
        if abs(d) > 0.01:
            common_diffs.append((k, d))
    if common_diffs:
        common_diffs.sort(key=lambda x: abs(x[1]), reverse=True)
        print(f'  Common trades with P&L diff (top 10):')
        for k, d in common_diffs[:10]:
            new_pnl_t = get_pnl(new_keys[k])
            old_pnl_t = old_keys[k].net_pnl or 0
            print(f'    {k[0]}  {k[1]}  {k[2]}  old=${old_pnl_t:.2f}  new=${new_pnl_t:.2f}  delta=${d:+.2f}')
    else:
        print('  No per-trade P&L differences in common trades.')

    # Step 5: Streak trace around the divergence point
    print(f'\n{"─"*65}')
    print('STREAK TRACE — around first diverging trade')
    if only_in_new:
        # Find the entry date of the first extra trade
        target_key = sorted(only_in_new)[0]
        target_date = pd.Timestamp(target_key[0]).date()
        print(f'  Tracing streak in OLD engine around {target_date}')
        # Find old trades in the window ±10 days
        window_start = pd.Timestamp(target_date) - pd.Timedelta(days=30)
        window_end   = pd.Timestamp(target_date) + pd.Timedelta(days=10)
        nearby = [t for t in old_trades
                  if window_start <= pd.Timestamp(t.entry_time) <= window_end]
        print(f'  Old trades within ±30d of target:')
        # Also need the streak values — re-instrument OldCBEngine to capture them
        # (can't get from the already-run result; report trade list as proxy)
        for t in sorted(nearby, key=lambda x: x.entry_time):
            marker = '<-- extra in new' if (str(t.entry_time), t.ticker, t.strategy) in {k for k in only_in_old} else ''
            print(f'    {t.entry_time}  {t.ticker:6}  {t.strategy:14}  pnl=${t.net_pnl:.2f}  exit={t.exit_reason}  {marker}')
        # Show in new baseline
        nearby_new = [t for t in new_trades
                      if window_start <= pd.Timestamp(t.get('entry_time','1900') if isinstance(t,dict) else t.entry_time) <= window_end]
        print(f'  New trades within ±30d of target:')
        for t in sorted(nearby_new, key=lambda x: x.get('entry_time') if isinstance(x,dict) else x.entry_time):
            marker = '<-- only in new' if trade_key(t) in {k for k in only_in_new} else ''
            pnl = get_pnl(t)
            et = t.get('entry_time') if isinstance(t,dict) else str(t.entry_time)
            tk = t.get('ticker') if isinstance(t,dict) else t.ticker
            st = t.get('strategy') if isinstance(t,dict) else t.strategy
            er = t.get('exit_reason') if isinstance(t,dict) else t.exit_reason
            print(f'    {et}  {tk:6}  {st:14}  pnl=${pnl:.2f}  exit={er}  {marker}')

    print(f'\n{"─"*65}')
    print('SUMMARY')
    print(f'  Dataset:   SAME — both use window_debug_5min.pkl')
    print(f'  Difference: CB semantics only (daily-CB counting new for both)')
    print(f'  Old CB P&L: ${old_pnl:,.2f}  New CB P&L: ${new_pnl:,.2f}  delta: ${new_pnl-old_pnl:+,.2f}')


if __name__ == '__main__':
    main()