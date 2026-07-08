"""
Instrument engine.py (ORIG) to print circuit_breaker consecutive_losses
and _circuit_breaker_active for every trade close and every Jan 18 bar start.

Runs ORIG up to 2019-01-25 for speed.
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


class PatchedEngine(BacktestEngine):
    """Subclass that intercepts _close_trade to print CB state around closures."""

    def _close_trade(self, trade, exit_ts, exit_price, reason, circuit_breakers, coordinator, bar_dt):
        is_near_jan18 = (
            pd.Timestamp(exit_ts).date() >= pd.Timestamp("2019-01-03").date()
            and pd.Timestamp(exit_ts).date() <= pd.Timestamp("2019-01-22").date()
        )
        if is_near_jan18:
            cb_before = circuit_breakers._consecutive_losses
            flag_before = self._circuit_breaker_active
            print(f"  [CLOSE-BEFORE] {exit_ts}  {trade.ticker}  {trade.strategy}"
                  f"  pnl={trade.net_pnl}  consec={cb_before}  cb_flag={flag_before}")

        super()._close_trade(trade, exit_ts, exit_price, reason, circuit_breakers, coordinator, bar_dt)

        if is_near_jan18:
            cb_after = circuit_breakers._consecutive_losses
            flag_after = self._circuit_breaker_active
            print(f"  [CLOSE-AFTER]  {exit_ts}  {trade.ticker}  {trade.strategy}"
                  f"  pnl={trade.net_pnl}  consec={cb_after}  cb_flag={flag_after}")


def main():
    print("Loading data...")
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data = {t: df for t, df in all_data.items() if t in TICKERS}
    with open(PICKLE_DAILY, "rb") as f:
        daily_data = pickle.load(f)

    market_data_short = {
        t: df[(df.index >= pd.Timestamp("2017-01-03")) & (df.index <= pd.Timestamp(SHORT_END))]
        for t, df in market_data.items()
    }

    engine = PatchedEngine(make_config())
    print("Running patched ORIG engine (up to 2019-01-25)...\n")
    t0 = time.time()
    result = engine.run(market_data_short, daily_data)
    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s -- {len(result.trade_log)} trades")
    jan18_entries = [t for t in result.trade_log if pd.Timestamp(t.entry_time).date() == JAN18]
    print(f"Trades entering on Jan 18: {len(jan18_entries)}")
    for t in sorted(jan18_entries, key=lambda x: x.entry_time):
        print(f"  {t.entry_time}  {t.ticker}  {t.strategy}  pnl={t.net_pnl}")


if __name__ == "__main__":
    main()