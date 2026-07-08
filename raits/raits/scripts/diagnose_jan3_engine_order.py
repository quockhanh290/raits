"""
Run ORIG engine only through Jan 11 2019 to capture the Jan 3 trade close ordering.
Much faster than running to Jan 25.
Prints consec before/after every close in Jan 3–10.
"""
import sys, os, pickle, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import warnings; warnings.filterwarnings("ignore")
import pandas as pd, yaml

from raits.backtest.data_types import BacktestConfig
from raits.backtest.engine import BacktestEngine
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

SHORT_END = "2019-01-11"   # only run to Jan 11 — much faster


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


class PatchedEngine(BacktestEngine):
    def _close_trade(self, trade, exit_ts, exit_price, reason, circuit_breakers, coordinator, bar_dt):
        exit_dt = pd.Timestamp(exit_ts)
        show = (exit_dt.date() >= pd.Timestamp("2019-01-03").date()
                and exit_dt.date() <= pd.Timestamp("2019-01-10").date())
        if show:
            print(f"  [BEFORE] {exit_ts}  {trade.ticker:6} {trade.strategy:12}"
                  f"  reason={reason:<12}  pnl={trade.net_pnl}  consec={circuit_breakers._consecutive_losses}"
                  f"  flag={self._circuit_breaker_active}")
        super()._close_trade(trade, exit_ts, exit_price, reason, circuit_breakers, coordinator, bar_dt)
        if show:
            print(f"  [AFTER]  {exit_ts}  {trade.ticker:6} {trade.strategy:12}"
                  f"  reason={reason:<12}  pnl={trade.net_pnl:.2f}  consec={circuit_breakers._consecutive_losses}"
                  f"  flag={self._circuit_breaker_active}")


def main():
    with open(PICKLE_5MIN, "rb") as f: all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}
    with open(PICKLE_DAILY, "rb") as f: daily_data = pickle.load(f)
    market_data_short = {
        t: df[(df.index >= pd.Timestamp("2017-01-03")) & (df.index <= pd.Timestamp(SHORT_END))]
        for t, df in market_data.items()
    }
    engine = PatchedEngine(make_config())
    print("Running ORIG to 2019-01-11 only...\n")
    t0 = time.time()
    result = engine.run(market_data_short, daily_data)
    print(f"\nDone in {time.time()-t0:.1f}s -- {len(result.trade_log)} trades")

if __name__ == "__main__":
    main()