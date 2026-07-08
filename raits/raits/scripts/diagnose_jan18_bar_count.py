"""
Count how many bars decide() is called on Jan 18 2019 in REFAC,
and check _circuit_breaker_active between bars via a patched engine.
"""
import sys, os, pickle, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, yaml

from raits.backtest.data_types import BacktestConfig
from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.strategies.universe_scanner import CANDIDATE_POOL

UNIVERSE = ["TSLA","NVDA","AAPL","META","AMZN","MSFT","AMD","GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
             "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX",
             "CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
PE_EXP   = ["PFE","MRK","LLY","ABBV","JNJ","BMY","BAC","WFC","C",
             "WMT","TGT","HD","LOW","MCD","NKE","PG","KO","PEP",
             "CAT","DE","BA","GE","PYPL","PANW","NOW"]
SECTOR_ETFS = ["XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD"]
TICKERS = (["SPY","QQQ","IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXP)

PICKLE_5MIN  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")
_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "final_params.yaml")
with open(_PARAMS_PATH) as f: _params = yaml.safe_load(f)

JAN18 = pd.Timestamp("2019-01-18").date()
SHORT_END = "2019-01-25"


def make_config():
    return BacktestConfig(
        account_equity=50_000.0, start_date="2017-01-03", end_date=SHORT_END,
        universe=UNIVERSE+PHASE1+PHASE2, orb_universe=list(CANDIDATE_POOL),
        vwap_universe=["SPY","QQQ","IWM"],
        orb_range_minutes=_params["orb_range_minutes"],
        vwap_bb_std=_params["vwap_bb_std"], ema_period=_params["ema_period"],
        max_risk_pct=0.015, max_position_pct=0.40, kelly_fraction=0.75,
        enable_costs=True, enable_pdt_guard=True, hmm_retrain_weekly=True,
        allow_swing_hold=True, max_hold_days=5, stress_size_fraction=0.5,
        log_level="WARNING",
    )


def main():
    print("Loading data...")
    with open(PICKLE_5MIN, "rb") as f: all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}
    with open(PICKLE_DAILY, "rb") as f: daily_data = pickle.load(f)

    market_data_short = {
        t: df[(df.index >= pd.Timestamp("2017-01-03")) & (df.index <= pd.Timestamp(SHORT_END))]
        for t, df in market_data.items()
    }

    # Capture every ctx passed to decide() on Jan 18
    jan18_ctxs = []
    def ctx_hook(ctx):
        if ctx.bar_ts.date() == JAN18:
            jan18_ctxs.append(ctx.bar_ts)

    engine = RefactoredBacktestEngine(make_config())
    engine._ctx_capture_hook = ctx_hook   # wire the hook

    print("Running REFAC engine...")
    t0 = time.time()
    result = engine.run(market_data_short, daily_data)
    print(f"Done in {time.time()-t0:.1f}s - {len(result.trade_log)} trades")

    print(f"\nJan 18 bars where decide() was called: {len(jan18_ctxs)}")
    for ts in jan18_ctxs:
        print(f"  {ts}")

    # Show engine's _circuit_breaker_active state by checking how many bars were in day_spy
    spy_short = market_data_short.get("SPY", pd.DataFrame())
    jan18_spy_bars = spy_short[spy_short.index.normalize() == pd.Timestamp("2019-01-18")]
    print(f"\nSPY bars in market_data_short for Jan 18: {len(jan18_spy_bars)}")
    if len(jan18_spy_bars) > 0:
        print(f"  First: {jan18_spy_bars.index[0]}  Last: {jan18_spy_bars.index[-1]}")


if __name__ == "__main__":
    main()