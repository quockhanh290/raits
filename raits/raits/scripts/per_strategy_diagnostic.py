"""
scripts/per_strategy_diagnostic.py
-----------------------------------
Final RAITS Phase 1D diagnostic — per-strategy attribution.

Runs ONE BacktestEngine.run() over the full OOS span (2020-2022) using the
production parameters chosen by the latest WFO (ORB=15, BB=2.5σ, EMA=30),
then breaks down the trade log by strategy to answer:

    "Are all four strategies losing money, or is one carrying the others?"

If even one strategy has positive Calmar standalone across the OOS span, RAITS
isn't dead — it just needs that strategy alone. If all four are negative, we
have full confirmation and the project is honestly shelvable.

Uses the existing Polygon cache — no new API calls.

Usage (from project root C:\\Users\\quock\\RAITS\\raits):
    python scripts/per_strategy_diagnostic.py

Outputs:
    configs/per_strategy_trades.csv   — full trade log
    configs/per_strategy_report.txt   — per-strategy breakdown
    Console: summary table + verdict
"""

from __future__ import annotations
import sys
import os
import logging
import warnings
from datetime import datetime
from typing import Dict, List
from collections import defaultdict
import math

warnings.filterwarnings("ignore")

# Project-root on path
# Add project root to sys.path
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)


import pandas as pd
import numpy as np

# -- Config / API key ----------------------------------------------------------
_api_key = None
for _cfg_path in [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config_private.py'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'config_private.py'),
    'config_private.py',
]:
    _cfg_path = os.path.abspath(_cfg_path)
    if os.path.exists(_cfg_path):
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location("config_private", _cfg_path)
        _mod = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        _api_key = getattr(_mod, 'POLYGON_API_KEY', None)
        print(f"[OK] Config loaded from: {_cfg_path}")
        break

if not _api_key:
    print("[FAIL] FATAL: config_private.py not found or POLYGON_API_KEY missing.")
    sys.exit(1)

POLYGON_API_KEY = _api_key

from raits.data.raits_polygon_fetcher import PolygonDataFetcher
from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig

# -- Logging -------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("per_strategy_diag")

# -- Diagnostic parameters -----------------------------------------------------
# Span the full OOS range used in the diagnostic WFO run (2020-2022)
OOS_START = "2020-01-06"
OOS_END   = "2022-12-29"

# Production parameters from the diagnostic WFO run
PROD_ORB_RANGE = 15
PROD_BB_STD    = 2.5
PROD_EMA       = 30

# Same universe as the diagnostic WFO run
UNIVERSE     = ["TSLA", "NFLX", "AMD", "BABA", "ROKU", "SQ"]
ORB_UNIVERSE = ["TSLA", "AMD", "NVDA", "META", "NFLX", "BABA"]
TICKERS      = ["SPY"] + UNIVERSE + [t for t in ORB_UNIVERSE if t not in UNIVERSE]

CACHE_DIR     = "./raits/data/cache"
INTERVAL_MINS = 5
ACCOUNT_EQUITY = 50_000.0


def fetch_market_data(
    tickers: list,
    start: str,
    end: str,
    interval_minutes: int = 5,
) -> Dict[str, pd.DataFrame]:
    """
    Pull bars for [start, end] using PolygonDataFetcher with cache.
    Note: we still pull from DATASET_START forward so HMM has training data.
    """
    fetcher = PolygonDataFetcher(
        api_key=POLYGON_API_KEY,
        use_cache=True,
        cache_dir=CACHE_DIR,
        rate_limit_calls_per_minute=100,
    )

    # Need historical SPY back to 2017 for HMM fit; for stocks we only need OOS span
    HMM_TRAIN_START = "2017-01-03"

    start_dt_hmm = datetime.strptime(HMM_TRAIN_START, "%Y-%m-%d")
    start_dt_oos = datetime.strptime(start, "%Y-%m-%d")
    end_dt       = datetime.strptime(end, "%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"Loading cached data: HMM train from {HMM_TRAIN_START}, OOS {start}->{end}")
    print(f"Tickers: {tickers}")
    print(f"{'='*60}\n")

    market_data: Dict[str, pd.DataFrame] = {}

    for ticker in tickers:
        # SPY needs full history for HMM training; stocks only need OOS
        ticker_start = start_dt_hmm if ticker == "SPY" else start_dt_oos
        trading_days = pd.bdate_range(start=ticker_start, end=end_dt)

        print(f"  {ticker} ...", end=" ", flush=True)
        frames = []
        errors = 0

        for day in trading_days:
            try:
                hist = fetcher.fetch_intraday_bars(
                    ticker=ticker,
                    date=day.to_pydatetime(),
                    interval_minutes=interval_minutes,
                    use_cache=True,
                )
                df = hist.to_dataframe().reset_index()
                df.rename(columns={"timestamp": "datetime"}, inplace=True)
                df.set_index("datetime", inplace=True)
                df.index = pd.DatetimeIndex(df.index)
                df.columns = [c.lower() for c in df.columns]
                df = df.between_time("09:30", "16:00")
                if not df.empty:
                    frames.append(df)
            except Exception as e:
                errors += 1
                logger.debug(f"{ticker} {day.date()}: {e}")

        if frames:
            combined = pd.concat(frames).sort_index()
            combined = combined[~combined.index.duplicated(keep="first")]
            market_data[ticker] = combined
            days_loaded = len(combined.index.normalize().unique())
            print(f"[OK] {days_loaded} days, {len(combined):,} bars"
                  + (f" ({errors} errors)" if errors else ""))
        else:
            print(f"[FAIL] No data ({errors} errors)")

    return market_data


def _safe_div(num, den) -> float:
    if den == 0 or den is None or (isinstance(den, float) and math.isnan(den)):
        return 0.0
    return num / den


def aggregate_per_strategy(trades: List, account_equity: float = 50_000.0) -> Dict[str, Dict]:
    """
    Group trades by strategy and compute per-strategy stats.

    Trade objects are expected to have these attributes (per data_types.Trade):
      strategy, ticker, direction, entry_time, exit_time, entry_price,
      exit_price, shares, net_pnl, hmm_state, exit_reason
    """
    by_strategy: Dict[str, List] = defaultdict(list)

    for t in trades:
        if t.exit_time is None:
            continue  # skip still-open trades (shouldn't exist after run() finishes)
        strategy = getattr(t, "strategy", "UNKNOWN") or "UNKNOWN"
        by_strategy[strategy].append(t)

    results: Dict[str, Dict] = {}

    for strategy, ts in by_strategy.items():
        pnls = [float(t.net_pnl or 0.0) for t in ts]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        breakeven = [p for p in pnls if p == 0]

        gross_win = sum(wins) if wins else 0.0
        gross_loss = sum(losses) if losses else 0.0
        net_pnl = sum(pnls)

        # Build daily equity curve from this strategy's trades for Calmar
        # Assume start equity = account_equity, accumulate by exit_time daily
        if ts:
            df = pd.DataFrame([
                {"exit_date": pd.Timestamp(t.exit_time).normalize(),
                 "pnl": float(t.net_pnl or 0.0)}
                for t in ts
            ])
            daily_pnl = df.groupby("exit_date")["pnl"].sum().sort_index()
            equity_curve = account_equity + daily_pnl.cumsum()

            # Max drawdown
            running_max = equity_curve.cummax()
            drawdown = (equity_curve - running_max) / running_max
            max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

            # Annualized return
            n_days = max(len(daily_pnl), 1)
            total_return = float(net_pnl / account_equity)
            ann_return = total_return * (252.0 / n_days)

            # Calmar
            calmar = _safe_div(ann_return, abs(max_dd)) if max_dd != 0 else 0.0

            # Sharpe (daily)
            daily_returns = daily_pnl / account_equity
            sharpe = (
                _safe_div(daily_returns.mean(), daily_returns.std()) * np.sqrt(252.0)
                if len(daily_returns) > 1 else 0.0
            )
        else:
            max_dd = 0.0
            ann_return = 0.0
            calmar = 0.0
            sharpe = 0.0

        results[strategy] = {
            "trades": len(ts),
            "wins": len(wins),
            "losses": len(losses),
            "breakeven": len(breakeven),
            "win_rate": _safe_div(len(wins), len(ts)),
            "avg_win": _safe_div(gross_win, len(wins)) if wins else 0.0,
            "avg_loss": _safe_div(gross_loss, len(losses)) if losses else 0.0,
            "gross_win": gross_win,
            "gross_loss": gross_loss,
            "net_pnl": net_pnl,
            "profit_factor": _safe_div(gross_win, abs(gross_loss)) if gross_loss != 0 else float("inf"),
            "max_drawdown": max_dd,
            "annual_return": ann_return,
            "calmar_ratio": calmar,
            "sharpe_ratio": sharpe,
        }

    return results


def trades_to_dataframe(trades: List) -> pd.DataFrame:
    """Flatten Trade objects to a CSV-friendly DataFrame."""
    rows = []
    for t in trades:
        rows.append({
            "strategy":     getattr(t, "strategy", ""),
            "ticker":       getattr(t, "ticker", ""),
            "direction":    getattr(t, "direction", ""),
            "entry_time":   getattr(t, "entry_time", None),
            "exit_time":    getattr(t, "exit_time", None),
            "entry_price":  getattr(t, "entry_price", None),
            "exit_price":   getattr(t, "exit_price", None),
            "shares":       getattr(t, "shares", None),
            "stop":         getattr(t, "stop", None),
            "target":       getattr(t, "target", None),
            "gross_pnl":    getattr(t, "gross_pnl", None),
            "total_costs":  getattr(t, "total_costs", None),
            "net_pnl":      getattr(t, "net_pnl", None),
            "exit_reason":  getattr(t, "exit_reason", ""),
            "hmm_state":    getattr(t, "hmm_state", ""),
        })
    return pd.DataFrame(rows)


def print_breakdown(stats: Dict[str, Dict]) -> str:
    """Format per-strategy stats as a readable table. Returns the string for saving too."""
    lines = []
    lines.append("=" * 110)
    lines.append("PER-STRATEGY BREAKDOWN -- RAITS Phase 1D Final Diagnostic")
    lines.append(f"OOS span: {OOS_START} -> {OOS_END}  |  Params: ORB={PROD_ORB_RANGE}, BB={PROD_BB_STD}sigma, EMA={PROD_EMA}")
    lines.append(f"Universe: {UNIVERSE}  |  ORB universe: {ORB_UNIVERSE}")
    lines.append("=" * 110)

    header = f"{'Strategy':<14} {'Trades':>7} {'WinRt':>7} {'PF':>6} {'AvgWin':>9} {'AvgLoss':>9} {'NetPnL':>10} {'MaxDD':>8} {'Calmar':>8} {'Sharpe':>8}"
    lines.append(header)
    lines.append("-" * 110)

    # Sort by net_pnl descending so the best (or least bad) strategy is on top
    sorted_strats = sorted(stats.items(), key=lambda kv: kv[1]["net_pnl"], reverse=True)

    for strat, s in sorted_strats:
        pf_str = f"{s['profit_factor']:.2f}" if s['profit_factor'] != float("inf") else "  inf"
        lines.append(
            f"{strat:<14} "
            f"{s['trades']:>7} "
            f"{s['win_rate']:>6.1%} "
            f"{pf_str:>6} "
            f"${s['avg_win']:>7.2f} "
            f"${s['avg_loss']:>8.2f} "
            f"${s['net_pnl']:>9.2f} "
            f"{s['max_drawdown']:>7.1%} "
            f"{s['calmar_ratio']:>8.2f} "
            f"{s['sharpe_ratio']:>8.2f}"
        )

    lines.append("-" * 110)

    total_trades = sum(s["trades"] for s in stats.values())
    total_pnl = sum(s["net_pnl"] for s in stats.values())
    lines.append(
        f"{'TOTAL':<14} {total_trades:>7} {'':>7} {'':>6} {'':>9} {'':>9} ${total_pnl:>9.2f}"
    )
    lines.append("=" * 110)
    return "\n".join(lines)


def print_verdict(stats: Dict[str, Dict]) -> str:
    """Print the GO/NO-GO verdict per strategy and overall."""
    CALMAR_THRESHOLD = 2.0  # Blueprint Section 8.1 target

    lines = []
    lines.append("\n" + "=" * 110)
    lines.append("VERDICT -- Per-Strategy Standalone Viability")
    lines.append("=" * 110)

    salvageable = []
    marginal = []
    dead = []

    for strat, s in stats.items():
        calmar = s["calmar_ratio"]
        if calmar >= CALMAR_THRESHOLD:
            salvageable.append((strat, calmar))
        elif calmar > 0:
            marginal.append((strat, calmar))
        else:
            dead.append((strat, calmar))

    if salvageable:
        lines.append("\n[OK] STRATEGIES MEETING WFO TARGET (Calmar >= 2.0):")
        for strat, calmar in salvageable:
            lines.append(f"    {strat}: Calmar = {calmar:.2f}")
        lines.append("\n  RECOMMENDATION: Re-run WFO with only these strategies enabled.")
        lines.append("  RAITS may be salvageable as a single-strategy or subset system.")

    if marginal:
        lines.append("\n[WARN] STRATEGIES PROFITABLE BUT BELOW TARGET (0 < Calmar < 2.0):")
        for strat, calmar in marginal:
            lines.append(f"    {strat}: Calmar = {calmar:.2f}")
        lines.append("\n  These have edge but not enough — possibly worth refining,")
        lines.append("  but more likely a sign of weak underlying signal generation.")

    if dead:
        lines.append("\n[FAIL] STRATEGIES WITH NO EDGE (Calmar <= 0):")
        for strat, calmar in dead:
            lines.append(f"    {strat}: Calmar = {calmar:.2f}")

    lines.append("\n" + "=" * 110)

    # Overall verdict
    if salvageable:
        lines.append("OVERALL: Partial viability detected. Consider Path A (subset re-run).")
    elif marginal and not dead:
        lines.append("OVERALL: All strategies marginally profitable but none meet target.")
        lines.append("         Honest assessment: weak edge, not worth pursuing further.")
    elif marginal:
        lines.append("OVERALL: Mixed results — some strategies marginal, others dead.")
        lines.append("         Subset re-run unlikely to clear Calmar 2.0 threshold.")
    else:
        lines.append("OVERALL: NO STRATEGY HAS POSITIVE STANDALONE EDGE.")
        lines.append("         Final answer: shelve RAITS Phase 1, blueprint strategies do not work.")
        lines.append("         The system did its job — it told you the truth before you risked capital.")

    lines.append("=" * 110)
    return "\n".join(lines)


def main():
    print("\n" + "=" * 60)
    print("RAITS — Per-Strategy Attribution Diagnostic")
    print("Final Phase 1D check before GO/NO-GO decision")
    print("=" * 60)

    # Step 1: Load cached market data
    market_data = fetch_market_data(
        tickers=TICKERS,
        start=OOS_START,
        end=OOS_END,
        interval_minutes=INTERVAL_MINS,
    )

    if "SPY" not in market_data or market_data["SPY"].empty:
        print("\n[FAIL] FATAL: SPY data missing from cache.")
        sys.exit(1)

    stocks_loaded = sum(
        1 for t in UNIVERSE + ORB_UNIVERSE
        if t in market_data and not market_data[t].empty
    )
    print(f"\n[OK] Loaded SPY + {stocks_loaded} stocks")

    # Step 2: Run a single backtest with production params
    cfg = BacktestConfig(
        account_equity=ACCOUNT_EQUITY,
        start_date=OOS_START,
        end_date=OOS_END,
        universe=UNIVERSE,
        orb_universe=ORB_UNIVERSE,
        orb_range_minutes=PROD_ORB_RANGE,
        vwap_bb_std=PROD_BB_STD,
        ema_period=PROD_EMA,
        enable_costs=True,
        enable_pdt_guard=False,    # above $25k, same as WFO
        log_level="WARNING",
    )

    print(f"\n{'='*60}")
    print(f"Running BacktestEngine over OOS span...")
    print(f"  Span:   {OOS_START} -> {OOS_END}")
    print(f"  Params: ORB={PROD_ORB_RANGE}, BB={PROD_BB_STD}σ, EMA={PROD_EMA}")
    print(f"  Equity: ${ACCOUNT_EQUITY:,.0f}")
    print(f"{'='*60}\n")

    engine = BacktestEngine(cfg)
    result = engine.run(market_data)

    trades = result.trade_log
    print(f"\n[OK] Backtest complete: {len(trades)} trades")

    if not trades:
        print("\n[FAIL] No trades produced \u2014 something is wrong with strategy gating.")
        print("  Check: HMM regime distribution, scanner output, position sizing.")
        sys.exit(1)

    # Step 3: Aggregate per strategy
    stats = aggregate_per_strategy(trades, account_equity=ACCOUNT_EQUITY)

    # Step 4: Save trade log
    os.makedirs("configs", exist_ok=True)
    trades_df = trades_to_dataframe(trades)
    trades_csv = "configs/per_strategy_trades.csv"
    trades_df.to_csv(trades_csv, index=False)
    print(f"\n[OK] Trade log saved: {trades_csv}  ({len(trades_df)} rows)")

    # Step 5: Print + save breakdown and verdict
    breakdown_str = print_breakdown(stats)
    verdict_str = print_verdict(stats)

    print("\n" + breakdown_str)
    print(verdict_str)

    report_path = "configs/per_strategy_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(breakdown_str)
        f.write("\n\n")
        f.write(verdict_str)
        f.write("\n")
    print(f"\n[OK] Report saved: {report_path}")


if __name__ == "__main__":
    main()
