"""
grid_risk_trend.py — Grid search over max_risk_pct x MAX_TREND
Each worker process loads data ONCE via initializer, reuses across all assigned jobs.

Usage:
    cd d:\raits\raits
    python grid_risk_trend.py
"""
import sys, os, pickle, warnings, time
sys.path.insert(0, r'd:\raits'); sys.path.insert(0, r'd:\raits\raits')
warnings.filterwarnings("ignore")

import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed

ACCOUNT     = 50_000.0
CACHE_5MIN  = os.path.abspath(r'data/cache/window_debug_5min.pkl')
CACHE_DAILY = os.path.abspath(r'data/cache/window_debug_daily.pkl')

UNIVERSE = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
            "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX",
            "CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]

WINDOWS_IS = [
    ("2017-01-03","2017-12-29","2017"),
    ("2018-01-02","2018-12-31","2018"),
    ("2019-01-02","2019-12-31","2019"),
    ("2020-01-02","2020-12-31","2020"),
    ("2021-01-04","2021-12-31","2021"),
    ("2022-01-03","2022-12-30","2022"),
]

GRID_RISK  = [0.010, 0.015, 0.020, 0.025, 0.030]
GRID_TREND = [2, 3, 4]

# ── Worker globals (populated once per process by initializer) ────────────────
_full_data  = None
_daily_data = None


def _worker_init(cache5, cached):
    """Runs once per worker process — loads pkl into module-level globals."""
    global _full_data, _daily_data
    import sys, warnings, pickle
    sys.path.insert(0, r'd:\raits'); sys.path.insert(0, r'd:\raits\raits')
    warnings.filterwarnings("ignore")
    with open(cache5,  'rb') as f: _full_data  = pickle.load(f)
    with open(cached,  'rb') as f: _daily_data = pickle.load(f)


def _slice_oos(test_start, test_end):
    spy      = _full_data.get("SPY", pd.DataFrame())
    spy_days = spy.index.normalize().unique().sort_values()
    idx      = max(0, int(spy_days.searchsorted(pd.Timestamp(test_start).normalize())) - 252)
    w_start  = pd.Timestamp(spy_days[idx])
    result   = {}
    for ticker, df in _full_data.items():
        sliced = (df[df.index <= pd.Timestamp(test_end) + pd.Timedelta("1D")]
                  if ticker == "SPY"
                  else df[(df.index >= w_start) &
                          (df.index <= pd.Timestamp(test_end) + pd.Timedelta("1D"))])
        if not sliced.empty:
            result[ticker] = sliced
    return result


def _run_one(args):
    """Worker: data already in globals, just run the engine."""
    risk_pct, max_trend, test_start, test_end, label = args

    import raits.backtest.engine as eng
    eng.MAX_TREND = max_trend
    eng.STRATEGY_CAPS["TREND_FOLLOW"] = max_trend

    from raits.backtest.engine import BacktestEngine
    from raits.backtest.data_types import BacktestConfig

    oos = _slice_oos(test_start, test_end)
    cfg = BacktestConfig(
        start_date=test_start, end_date=test_end,
        universe=UNIVERSE + PHASE1 + PHASE2,
        orb_universe=[], vwap_universe=[
            "XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD","QQQ","IWM"],
        orb_range_minutes=15, vwap_bb_std=2.5, ema_period=30,
        account_equity=ACCOUNT, max_risk_pct=risk_pct,
        enable_costs=True, enable_pdt_guard=False, log_level="ERROR",
        allow_swing_hold=True, max_hold_days=5,
        use_scanner=True, scanner_top_n=15,
        use_mr_scanner=True, mr_scanner_top_n=8,
        use_orb_scanner=True, orb_scanner_top_n=10,
        use_fade_scanner=True, fade_scanner_top_n=10,
    )
    result = BacktestEngine(cfg).run(oos, daily_data=_daily_data)
    eq     = result.equity_curve
    pnl    = float(eq.iloc[-1]) - float(eq.iloc[0]) if not eq.empty else 0.0
    maxdd  = result.metrics.get("max_drawdown", 0.0)
    by_s   = {}
    for t in result.trade_log:
        by_s.setdefault(t.strategy, []).append(t.net_pnl)
    return {
        'risk_pct': risk_pct, 'max_trend': max_trend, 'label': label,
        'pnl': pnl, 'max_dd': maxdd,
        'tf_pnl':  sum(by_s.get('TREND_FOLLOW', [])),
        'tf_n':    len(by_s.get('TREND_FOLLOW', [])),
        'orb_pnl': sum(by_s.get('ORB', [])),
    }


def main():
    t0    = time.time()
    jobs  = [(r, t, s, e, l)
             for r in GRID_RISK
             for t in GRID_TREND
             for s, e, l in WINDOWS_IS]
    total = len(jobs)
    N_WORKERS = 6
    print("Grid: %d risk x %d trend x %d windows = %d jobs, %d workers" % (
        len(GRID_RISK), len(GRID_TREND), len(WINDOWS_IS), total, N_WORKERS), flush=True)
    print("Starting workers (each loads pkl once, ~15s)...", flush=True)
    print()

    results, done = [], 0
    with ProcessPoolExecutor(
        max_workers=N_WORKERS,
        initializer=_worker_init,
        initargs=(CACHE_5MIN, CACHE_DAILY),
    ) as ex:
        futs = {ex.submit(_run_one, j): j for j in jobs}
        for fut in as_completed(futs):
            try:
                results.append(fut.result())
            except Exception as e:
                j = futs[fut]
                print("  ERROR risk=%.1f%% trend=%d %s: %s" % (j[0]*100, j[1], j[4], e))
            done += 1
            el  = time.time() - t0
            if done % 6 == 0 or done == 1:
                eta = el / done * (total - done)
                print("  %d/%d  elapsed=%.0fs  ETA=~%.0fs" % (done, total, el, eta), flush=True)

    df  = pd.DataFrame(results)
    grp = df.groupby(['risk_pct','max_trend']).agg(
        total_pnl=('pnl','sum'), worst_dd=('max_dd','max'),
        tf_pnl=('tf_pnl','sum'), tf_trades=('tf_n','sum'),
    ).reset_index()
    grp['ann_ret'] = grp['total_pnl'] / 6 / ACCOUNT * 100
    grp['calmar']  = (grp['ann_ret'] / 100) / grp['worst_dd'].replace(0, 1e-9)
    grp = grp.sort_values(['risk_pct','max_trend'])

    best_c = grp['calmar'].idxmax()
    best_r = grp['ann_ret'].idxmax()

    print()
    print("=" * 72)
    print("  GRID RESULTS — IS 2017-2022  ($50k)")
    print("=" * 72)
    print("%-7s %-5s %10s %7s %10s %8s %8s" % (
        "risk%","TF","total_PL","ann%","worst_DD%","Calmar","TF_n"))
    print("-" * 72)
    for i, r in grp.iterrows():
        tag = (" <<Calmar" if i==best_c else "") + (" <<Return" if i==best_r else "")
        print("%-7s %-5d %+10.0f %7.1f %10.1f %8.2f %8d%s" % (
            "%.1f%%" % (r['risk_pct']*100), int(r['max_trend']),
            r['total_pnl'], r['ann_ret'], r['worst_dd']*100,
            r['calmar'], int(r['tf_trades']), tag))

    print()
    print("=" * 72)
    print("  YEAR-BY-YEAR: baseline vs best Calmar vs best Return")
    print("=" * 72)
    bc = grp.loc[best_c]; br = grp.loc[best_r]
    base = df[(df.risk_pct==0.010)&(df.max_trend==2)].sort_values('label')
    dbc  = df[(df.risk_pct==bc['risk_pct'])&(df.max_trend==int(bc['max_trend']))].sort_values('label')
    dbr  = df[(df.risk_pct==br['risk_pct'])&(df.max_trend==int(br['max_trend']))].sort_values('label')
    print("%-6s %14s %14s %14s" % ("Year","Base 1%/2",
          "Calmar %.0f%%/%d"%(bc['risk_pct']*100,int(bc['max_trend'])),
          "Return %.0f%%/%d"%(br['risk_pct']*100,int(br['max_trend']))))
    print("-" * 52)
    for i in range(len(WINDOWS_IS)):
        lbl = WINDOWS_IS[i][2]
        print("%-6s %+14.0f %+14.0f %+14.0f" % (
            lbl, base.iloc[i]['pnl'], dbc.iloc[i]['pnl'], dbr.iloc[i]['pnl']))
    print("-" * 52)
    print("%-6s %+14.0f %+14.0f %+14.0f" % (
        "TOT", base['pnl'].sum(), dbc['pnl'].sum(), dbr['pnl'].sum()))
    print()
    print("Total elapsed: %.0fs" % (time.time()-t0))


if __name__ == '__main__':
    main()
