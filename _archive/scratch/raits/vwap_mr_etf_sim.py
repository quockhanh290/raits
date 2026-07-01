"""
vwap_mr_etf_sim.py
------------------
Standalone sim to evaluate VWAP_MR on ETF universe vs stock universe.

VWAP_MR was removed based on IS performance that was biased:
  - Engine traded STOCKS (MR_CANDIDATE_POOL via MR scanner) because ETF data was missing
  - ETFs (XLF, XLE...) are the intended universe (range-bound, low-beta)

This sim compares both to determine if removal was justified.

Usage:
    cd d:\\raits\\raits
    python vwap_mr_etf_sim.py
"""
import sys, os, glob
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig

# ── Monkey-patch: re-enable VWAP_MR without touching engine.py ────────────────
import raits.backtest.engine as _eng
_REGIME_STRATEGIES_ORIG = {k: list(v) for k, v in _eng._REGIME_STRATEGIES.items()}
_eng._REGIME_STRATEGIES["Calm"]   = ["VWAP_MR"]
_eng._REGIME_STRATEGIES["Normal"] = ["VWAP_MR"]
# Stress/Crisis left unchanged (VWAP_MR never ran there)

# ── Universes to compare ──────────────────────────────────────────────────────
ETF_UNIVERSE   = ["XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD","QQQ","IWM"]
STOCK_UNIVERSE = [  # MR_CANDIDATE_POOL — what the zombie was actually trading
    "TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL",
    "INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
    "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX",
    "CSCO","GS","CRM","JPM",
    "MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM",
]

CACHE_5MIN = os.path.join(os.path.dirname(__file__), "data", "cache", "data")
CACHE_DAILY = os.path.join(os.path.dirname(__file__), "data", "cache", "daily")
IS_START = "2017-01-03"
IS_END   = "2022-12-31"


def load_5min(tickers):
    market_data = {}
    for t in tickers:
        files = glob.glob(os.path.join(CACHE_5MIN, f"{t}_5min_*.parquet"))
        if not files:
            continue
        frames = []
        for f in files:
            try:
                frames.append(pd.read_parquet(f))
            except Exception:
                pass
        if not frames:
            continue
        df = pd.concat(frames)
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        start_ts = pd.Timestamp(IS_START)
        end_ts   = pd.Timestamp(IS_END) + pd.Timedelta("1D")
        df = df[(df.index >= start_ts) & (df.index < end_ts)]
        df = df.between_time("09:30", "16:00")
        if not df.empty:
            market_data[t] = df
    return market_data


def load_daily():
    daily_data = {}
    from raits.strategies.universe_scanner import CANDIDATE_POOL
    for t in ["SPY"] + CANDIDATE_POOL:
        files = glob.glob(os.path.join(CACHE_DAILY, f"{t}_daily_*.parquet"))
        if not files:
            continue
        frames = [pd.read_parquet(f) for f in files]
        df = pd.concat(frames)
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index()
        df = df[~df.index.duplicated(keep="first")]
        daily_data[t] = df
    return daily_data


def run_sim(label, vwap_universe, use_mr_scanner):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  Universe: {vwap_universe[:4]}... ({len(vwap_universe)} tickers)")
    print(f"  MR scanner: {use_mr_scanner}")
    print(f"{'='*60}")

    all_tickers = ["SPY"] + vwap_universe
    print(f"Loading 5-min data...")
    market_data = load_5min(all_tickers)
    daily_data  = load_daily()
    print(f"  Loaded: {list(market_data.keys())}")

    cfg = BacktestConfig(
        universe=[],
        orb_universe=[],
        vwap_universe=vwap_universe,
        orb_range_minutes=15,
        vwap_bb_std=2.0,
        ema_period=30,
        account_equity=50_000.0,
        enable_costs=True,
        enable_pdt_guard=False,
        log_level="WARNING",
        allow_swing_hold=False,
        max_hold_days=1,
        stress_size_fraction=1.0,
        use_scanner=False,
        scanner_top_n=0,
        use_mr_scanner=use_mr_scanner,
        mr_scanner_top_n=8,
        use_orb_scanner=False,
        orb_scanner_top_n=0,
        vwap_mr_vol_threshold=0.12,
        max_risk_pct=0.015,
        max_position_pct=0.40,
        kelly_fraction=0.75,
    )

    engine = BacktestEngine(cfg)
    result = engine.run(
        market_data=market_data,
        daily_data=daily_data,
    )

    trades = [t for t in result.trade_log if t.strategy == "VWAP_MR"]
    if not trades:
        print("  NO VWAP_MR trades generated.")
        return []

    rows = [{"year": t.exit_time.year, "net_pnl": t.net_pnl, "ticker": t.ticker,
             "exit_reason": t.exit_reason} for t in trades]
    df = pd.DataFrame(rows)

    print(f"\n  VWAP_MR trades: {len(df)}")
    print(f"  Total P&L:      ${df['net_pnl'].sum():,.0f}")
    print(f"  Win Rate:       {(df['net_pnl']>0).mean():.1%}")
    print(f"  Avg/trade:      ${df['net_pnl'].mean():.2f}")

    print(f"\n  Year-by-year:")
    for yr, grp in df.groupby("year"):
        wr = (grp['net_pnl'] > 0).mean()
        print(f"    {yr}: {len(grp):3d}t  ${grp['net_pnl'].sum():+,.0f}  WR={wr:.0%}  avg=${grp['net_pnl'].mean():+.1f}")

    return df['net_pnl'].tolist()


def bootstrap(pnl_list, n=10000):
    if not pnl_list:
        return None, None
    arr = np.array(pnl_list)
    means = [np.random.choice(arr, size=len(arr), replace=True).mean() for _ in range(n)]
    p = np.mean(np.array(means) <= 0)
    ci_lo, ci_hi = np.percentile(means, [2.5, 97.5])
    return p, (ci_lo * len(arr), ci_hi * len(arr))


if __name__ == "__main__":
    print("\nVWAP_MR Universe Comparison Sim")
    print("IS period: 2017-2022\n")

    # Run 1: ETF universe (intended)
    etf_pnl = run_sim(
        "RUN 1: ETF UNIVERSE (intended)",
        vwap_universe=ETF_UNIVERSE,
        use_mr_scanner=False,
    )

    # Run 2: Stock universe (what zombie was doing)
    stk_pnl = run_sim(
        "RUN 2: STOCK UNIVERSE (what zombie traded)",
        vwap_universe=STOCK_UNIVERSE,
        use_mr_scanner=True,
    )

    # Bootstrap comparison
    print(f"\n{'='*60}")
    print("  BOOTSTRAP (10,000 iterations)")
    print(f"{'='*60}")
    for label, pnl in [("ETF universe", etf_pnl), ("Stock universe", stk_pnl)]:
        p, ci = bootstrap(pnl)
        if p is not None:
            print(f"  {label}: p={p:.3f}  CI=[${ci[0]:+,.0f}, ${ci[1]:+,.0f}]")
            verdict = "CONFIRMED EDGE" if p < 0.05 else ("BORDERLINE" if p < 0.10 else "NO EDGE")
            print(f"    → {verdict}")
        else:
            print(f"  {label}: no trades")

    print(f"\n{'='*60}")
    print("  VERDICT")
    print(f"{'='*60}")
    if etf_pnl and bootstrap(etf_pnl)[0] is not None:
        p_etf = bootstrap(etf_pnl)[0]
        etf_total = sum(etf_pnl)
        if p_etf < 0.05 and etf_total > 0:
            print("  ETF universe shows edge → RE-ADD VWAP_MR to engine with ETF-only universe")
        elif p_etf < 0.10 and etf_total > 0:
            print("  ETF universe borderline → consider re-adding, needs more data")
        else:
            print("  No edge on ETF universe → REMOVAL CONFIRMED (instrument was not the issue)")
    print(f"{'='*60}\n")
