"""
cb_trace.py — Trace CB counter per trade for Window 1 (2020) using exact
same config as window_debug. Logs to cb_trace_log.txt.

Usage:
    cd d:\raits\raits
    python raits\scripts\cb_trace.py
"""
import sys, os, logging, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig

# ── Paths (mirror window_debug) ───────────────────────────────────────────────
_SCRIPTS = os.path.dirname(__file__)
_DATA    = os.path.join(_SCRIPTS, "..", "..", "data", "cache")
PICKLE_5MIN    = os.path.join(_DATA, "window_debug_5min.pkl")
PICKLE_DAILY   = os.path.join(_DATA, "window_debug_daily.pkl")
LOG_PATH       = os.path.join(_DATA, "cb_trace_log.txt")

# ── Universe (mirror window_debug) ────────────────────────────────────────────
UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
            "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX","CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
SECTOR_ETFS = ["XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD"]
TICKERS  = ["SPY","QQQ","IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2
MR_UNIVERSE_STATIC = ["XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD","QQQ","IWM"]

def slice_oos(full_data, test_start, test_end, warmup_days=252):
    spy = full_data.get("SPY", pd.DataFrame())
    spy_days   = spy.index.normalize().unique().sort_values()
    warmup_idx = int(spy_days.searchsorted(pd.Timestamp(test_start).normalize()))
    warmup_idx = max(0, warmup_idx - warmup_days)
    warmup_start = pd.Timestamp(spy_days[warmup_idx])
    result = {}
    for ticker, df in full_data.items():
        if ticker == "SPY":
            sliced = df[df.index <= pd.Timestamp(test_end) + pd.Timedelta("1D")]
        else:
            sliced = df[
                (df.index >= warmup_start)
                & (df.index <= pd.Timestamp(test_end) + pd.Timedelta("1D"))
            ]
        if not sliced.empty:
            result[ticker] = sliced
    return result

# ── Logging setup ─────────────────────────────────────────────────────────────
log_formatter = logging.Formatter("%(asctime)s | %(name)s | %(message)s", datefmt="%H:%M:%S")
fh = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8", errors="replace")
fh.setLevel(logging.INFO)
fh.setFormatter(log_formatter)

cb_logger = logging.getLogger("RAITS.risk.circuit_breakers")
cb_logger.setLevel(logging.INFO)
cb_logger.addHandler(fh)
cb_logger.propagate = False

trace_logger = logging.getLogger("cb_trace_engine")
trace_logger.setLevel(logging.INFO)
trace_logger.addHandler(fh)
trace_logger.propagate = False

# ── Monkey-patch _close_trade ─────────────────────────────────────────────────
_orig_close = BacktestEngine._close_trade

def _patched_close(self, trade, exit_ts, exit_price, reason, circuit_breakers, coordinator, bar_dt):
    _orig_close(self, trade, exit_ts, exit_price, reason, circuit_breakers, coordinator, bar_dt)
    pnl    = trade.net_pnl or 0.0
    consec = circuit_breakers.consecutive_losses
    sign   = "WIN " if pnl > 0 else "LOSS"
    trace_logger.info(
        f"[{sign}] {exit_ts} | {trade.strategy:14} {trade.ticker:8} | "
        f"exit={reason:16} pnl={pnl:+8.2f} | consec_losses={consec}"
    )

BacktestEngine._close_trade = _patched_close

# ── Load cached data ──────────────────────────────────────────────────────────
print(f"Logging to: {LOG_PATH}")
print("Loading 5-min data from cache...")
with open(PICKLE_5MIN, "rb") as f:
    full_data = pickle.load(f)
full_data = {t: df for t, df in full_data.items() if t in TICKERS}
print(f"  {len(full_data)} tickers loaded")

print("Loading daily data from cache...")
with open(PICKLE_DAILY, "rb") as f:
    daily_data = pickle.load(f)

# ── Window 1 (2020) — exact same config as window_debug ──────────────────────
TEST_START, TEST_END = "2020-01-02", "2020-12-31"
oos_data = slice_oos(full_data, TEST_START, TEST_END)

cfg = BacktestConfig(
    start_date=TEST_START,
    end_date=TEST_END,
    universe=UNIVERSE,
    orb_universe=[],
    vwap_universe=MR_UNIVERSE_STATIC,
    orb_range_minutes=15,
    vwap_bb_std=2.0,
    ema_period=30,
    account_equity=50_000.0,
    enable_costs=True,
    enable_pdt_guard=False,
    log_level="WARNING",
    allow_swing_hold=True,
    max_hold_days=5,
    stress_size_fraction=0.5,
    use_scanner=True,
    scanner_top_n=15,
    use_mr_scanner=True,
    mr_scanner_top_n=8,
    use_orb_scanner=True,
    orb_scanner_top_n=10,
    use_fade_scanner=True,
    fade_scanner_top_n=10,
    vwap_mr_vol_threshold=0.12,
    max_risk_pct=0.01,
)

print("Running Window 1 (2020) with exact window_debug config...")
engine = BacktestEngine(config=cfg)
result = engine.run(oos_data, daily_data=daily_data)

trades  = result.get("trades", [])
total   = sum(t.net_pnl for t in trades)
tf_pnl  = sum(t.net_pnl for t in trades if t.strategy == "TREND_FOLLOW")
print(f"\nWindow 1 P&L: {total:+,.0f}  TF: {tf_pnl:+,.0f}  trades={len(trades)}")
print(f"Log: {LOG_PATH}")
print("\nFilter Jan 27 - Feb 6:")
print(f"  Select-String '2020-01-2[7-9]|2020-02-0[1-6]' {LOG_PATH}")
