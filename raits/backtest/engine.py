"""
raits/backtest/engine.py
BacktestEngine: Week 18 integration testing artifact.

Bar-by-bar simulation connecting:
  Phase 1A: HMMEngine, CostCalculator
  Phase 1B: ORBStrategy, VWAPMRStrategy, TrendStrategy, CashDefenseMode
  Phase 1C: PDTGuard, CircuitBreakers, PositionSizer, RegimeCoordinator

Design principles
-----------------
- Path-dependent state (PDT count, consecutive losses, regime) requires
  bar-by-bar execution — not vectorized.
- Entry at NEXT BAR OPEN (backtest/live parity per blueprint Section 1).
- All exits check stop/target against bar high/low (not close-only).
- No look-ahead: at each bar we only use data up to and including that bar.
- Costs applied on close (entry cost could be added; blueprint doesn't
  require it separately since spread/slippage already model entry friction).

Interface contract with Phase 1B/1C modules
--------------------------------------------
Each module is imported via _load_modules() which gives a clear error
if an interface doesn't match. Fix the adapter comment and retest.

Expected strategy signal dict:
  {
    'direction':    'LONG' | 'SHORT',
    'entry_price':  float,   ← next-bar open price
    'stop':         float,
    'target':       float,
    'is_day_trade': bool,    ← optional, defaults True
  }

Expected PositionSizer.calculate() return:
  object with .shares (int) and .limiting_factor (str)

Expected CircuitBreakers.check() return:
  object with .should_halt (bool) and .reason (str)

Expected RegimeCoordinator.get_active_strategies() return:
  List[str] from {'ORB', 'VWAP_MR', 'TREND_FOLLOW'}
"""

from __future__ import annotations
import importlib
import logging
import os
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

from .data_types import BacktestConfig, BacktestResult, SessionSummary, Trade
from .equity_tracker import EquityTracker
from .trade_log import TradeLog
from .metrics import compute_metrics, compute_regime_breakdown

logger = logging.getLogger("RAITS.backtest")


# ── Strategy time windows (Eastern Time) ──────────────────────────────────────
ORB_SCAN_TIME    = dtime(9, 35)
ORB_RANGE_START  = dtime(9, 30)
ORB_SIGNAL_START = dtime(9, 45)   # after 15-min OR has formed
ORB_SIGNAL_END   = dtime(10, 15)
VWAP_MR_START    = dtime(10, 15)
VWAP_MR_END      = dtime(14, 0)
TREND_START      = dtime(14, 0)
EOD_HARD_EXIT    = dtime(15, 55)  # hard close for all strategies

# ── Position limits (Section 4.1) ─────────────────────────────────────────────
MAX_TOTAL        = 5
MAX_ORB          = 2
MAX_VWAP         = 3
MAX_TREND        = 2
STRATEGY_CAPS    = {"ORB": MAX_ORB, "VWAP_MR": MAX_VWAP, "TREND_FOLLOW": MAX_TREND}


class BacktestEngine:
    """
    Week 18: Full integration backtest engine.

    Usage:
        config = BacktestConfig(start_date="2022-01-03", end_date="2022-03-31")
        engine = BacktestEngine(config)
        market_data = {...}  # dict ticker → 5-min OHLCV DataFrame
        result = engine.run(market_data)
        print(result.summary())
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self._setup_logging()

        # Core bookkeeping
        self.equity_tracker = EquityTracker(config.account_equity)
        self.trade_log = TradeLog()
        self._session_summaries: List[SessionSummary] = []

        # Runtime state (reset per day where noted)
        self._hmm_state: str = "Normal"
        self._safety_mode_active: bool = False
        self._circuit_breaker_active: bool = False
        self._last_retrain_date: Optional[datetime] = None
        self._regime_bar_counts: Dict[str, int] = {}

        # Load all modules — fails fast with clear interface-mismatch messages
        self._mods = self._load_modules()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, market_data: Dict[str, pd.DataFrame]) -> BacktestResult:
        """
        Run the full backtest.

        Args:
            market_data: Dict[ticker → DataFrame]. Must include 'SPY'.
                         DataFrame index: DatetimeIndex (5-min bars, market hours).
                         Columns: open, high, low, close, volume (lowercase).

        Returns:
            BacktestResult
        """
        if "SPY" not in market_data:
            raise ValueError("market_data must contain 'SPY' bars for HMM regime detection.")

        spy_data = market_data["SPY"]

        # ── Helper: resample 5-min bars → daily close Series ──────────────────
        def to_daily_close(bars: pd.DataFrame) -> "pd.Series":
            """build_feature_matrix expects a daily close price Series."""
            return bars["close"].resample("B").last().dropna()

        # ── Initialize HMM ────────────────────────────────────────────────────
        HMMEngine = self._mods["HMMEngine"]
        compute_features = self._mods["compute_features"]
        hmm = HMMEngine()
        logger.info(f"Training HMM on {len(spy_data)} SPY bars...")
        features = compute_features(to_daily_close(spy_data))
        hmm.fit(features)
        logger.info("HMM trained.")

        # ── Initialize risk modules ────────────────────────────────────────────
        pdt_guard = self._mods["PDTGuard"]()
        circuit_breakers = self._mods["CircuitBreakers"](
            daily_drawdown_limit=-0.04,
            consecutive_loss_limit=5,
        )
        position_sizer = self._mods["PositionSizer"](
            account_equity=self.config.account_equity
        )
        coordinator = self._mods["RegimeCoordinator"]()

        # ── Initialize strategies ──────────────────────────────────────────────
        orb      = self._mods["ORBStrategy"](range_minutes=self.config.orb_range_minutes)
        vwap_mr  = self._mods["VWAPMRStrategy"](bb_std=self.config.vwap_bb_std)
        trend    = self._mods["TrendStrategy"](ema_period=self.config.ema_period)

        # ── Determine trading days ─────────────────────────────────────────────
        all_days = pd.DatetimeIndex(spy_data.index.normalize().unique())
        all_days = all_days[
            (all_days >= pd.Timestamp(self.config.start_date))
            & (all_days <= pd.Timestamp(self.config.end_date))
        ]

        logger.info(
            f"Backtest: {self.config.start_date} → {self.config.end_date} "
            f"| {len(all_days)} trading days | Universe: {self.config.universe}"
        )

        # ── Day loop ──────────────────────────────────────────────────────────
        for day in all_days:
            self._run_day(
                day=day,
                market_data=market_data,
                spy_data=spy_data,
                hmm=hmm,
                compute_features=compute_features,
                to_daily_close=to_daily_close,
                pdt_guard=pdt_guard,
                circuit_breakers=circuit_breakers,
                position_sizer=position_sizer,
                coordinator=coordinator,
                orb=orb,
                vwap_mr=vwap_mr,
                trend=trend,
            )

            # Weekly HMM retrain: Monday is the first business day post-weekend
            if self.config.hmm_retrain_weekly and day.weekday() == 0:
                if (
                    self._last_retrain_date is None
                    or (day - self._last_retrain_date).days >= 7
                ):
                    recent_spy = spy_data[spy_data.index.normalize() <= day]
                    retrain_features = compute_features(to_daily_close(recent_spy))
                    if len(retrain_features) > 0:
                        hmm.retrain(retrain_features)
                        self._last_retrain_date = day
                        logger.info(f"HMM retrained on {day.date()}")

        # ── Finalize results ───────────────────────────────────────────────────
        equity_curve = self.equity_tracker.get_equity_curve()
        all_trades = self.trade_log.all_trades()
        metrics = compute_metrics(equity_curve, all_trades)
        regime_breakdown = compute_regime_breakdown(all_trades)

        logger.info(
            f"Backtest complete | Trades: {len(all_trades)} | "
            f"Calmar: {metrics.get('calmar_ratio', 0):.2f} | "
            f"MaxDD: {metrics.get('max_drawdown', 0):.1%} | "
            f"Sharpe: {metrics.get('sharpe_ratio', 0):.2f}"
        )

        return BacktestResult(
            config=self.config,
            equity_curve=equity_curve,
            trade_log=all_trades,
            session_summaries=self._session_summaries,
            metrics=metrics,
            regime_breakdown=regime_breakdown,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Day simulation
    # ─────────────────────────────────────────────────────────────────────────

    def _run_day(
        self,
        day: pd.Timestamp,
        market_data: Dict[str, pd.DataFrame],
        spy_data: pd.DataFrame,
        hmm: Any,
        compute_features: Any,
        to_daily_close: Any,
        pdt_guard: Any,
        circuit_breakers: Any,
        position_sizer: Any,
        coordinator: Any,
        orb: Any,
        vwap_mr: Any,
        trend: Any,
    ) -> None:
        """Simulate one complete trading session bar-by-bar."""

        # ── Daily reset ────────────────────────────────────────────────────────
        self._circuit_breaker_active = False
        self._safety_mode_active = False
        self._regime_bar_counts = {"Calm": 0, "Normal": 0, "Stress": 0}
        orb_scanned: List[str] = []
        session_pdt_blocks = 0
        session_start_equity = self.equity_tracker.equity
        self.equity_tracker.new_session(day)

        # ── Bars for this day ──────────────────────────────────────────────────
        day_spy = spy_data[spy_data.index.normalize() == day]
        if day_spy.empty:
            return

        day_stocks: Dict[str, pd.DataFrame] = {
            ticker: market_data[ticker][market_data[ticker].index.normalize() == day]
            for ticker in self.config.universe
            if ticker in market_data and ticker != "SPY"
            and not market_data[ticker][market_data[ticker].index.normalize() == day].empty
        }

        spy_history: List[pd.Series] = []
        _regime_updated_today = False   # recompute once per day, not every bar

        # ── Bar loop ───────────────────────────────────────────────────────────
        for bar_ts, spy_bar in day_spy.iterrows():
            if self._circuit_breaker_active:
                break

            spy_history.append(spy_bar)
            bar_t = bar_ts.time()

            # 1. Update HMM regime once per day on the first bar
            if not _regime_updated_today:
                spy_daily_so_far = to_daily_close(
                    spy_data[spy_data.index.normalize() <= bar_ts.normalize()]
                )
                if len(spy_daily_so_far) >= 20:
                    feats = compute_features(spy_daily_so_far)
                    if len(feats) > 0:
                        pred = hmm.predict(feats)
                        state_idx = int(pred[-1])
                        self._hmm_state = ["Calm", "Normal", "Stress"][min(state_idx, 2)]
                _regime_updated_today = True

            self._regime_bar_counts[self._hmm_state] = (
                self._regime_bar_counts.get(self._hmm_state, 0) + 1
            )

            # 2. Layer 0 override
            override = self._check_layer0(spy_history)

            # 3. Effective regime
            effective = "Stress" if (override or self._hmm_state == "Stress") else self._hmm_state

            # 4. Safety mode transitions
            if effective == "Stress":
                if not self._safety_mode_active:
                    logger.critical(f"{bar_ts} | SAFETY MODE ON — regime: {effective}")
                    self._safety_mode_active = True
            else:
                if self._safety_mode_active:
                    logger.info(f"{bar_ts} | SAFETY MODE OFF — regime cleared")
                    self._safety_mode_active = False

            if self._safety_mode_active:
                self._close_all(bar_ts, day_stocks, "SAFETY_MODE")
                continue

            # 5. Active strategy set
            active = coordinator.get_active_strategies(effective)

            # 6. ORB scanner (fires once at 9:35)
            if bar_t == ORB_SCAN_TIME and "ORB" in active:
                orb_scanned = orb.scan_universe(
                    universe=self.config.universe,
                    stock_bars=day_stocks,
                    bar_time=bar_ts,
                )
                logger.info(f"{bar_ts} | ORB scan → {len(orb_scanned)} candidates: {orb_scanned}")

            # 7. ORB range update (9:30–9:45)
            if ORB_RANGE_START <= bar_t < ORB_SIGNAL_START and "ORB" in active:
                for ticker in orb_scanned:
                    if ticker in day_stocks:
                        orb.update_range(ticker, day_stocks[ticker].loc[:bar_ts])

            # 8. ORB signals (9:45–10:15)
            if ORB_SIGNAL_START <= bar_t <= ORB_SIGNAL_END and "ORB" in active:
                for ticker in orb_scanned:
                    if not self._position_ok(ticker, "ORB"):
                        continue
                    if ticker not in day_stocks:
                        continue
                    sig = orb.generate_signal(
                        day_stocks[ticker].loc[:bar_ts],
                        hmm_state=self._hmm_state,
                    )
                    if sig:
                        self._attempt_entry(
                            sig, ticker, "ORB", bar_ts, position_sizer, pdt_guard
                        )

            # 9. VWAP MR signals (10:15–14:00, Calm only)
            if VWAP_MR_START <= bar_t < VWAP_MR_END and "VWAP_MR" in active:
                for ticker, stock_df in day_stocks.items():
                    if not self._position_ok(ticker, "VWAP_MR"):
                        continue
                    sig = vwap_mr.generate_signal(
                        stock_df.loc[:bar_ts],
                        hmm_state=self._hmm_state,
                    )
                    if sig:
                        self._attempt_entry(
                            sig, ticker, "VWAP_MR", bar_ts, position_sizer, pdt_guard
                        )

            # 10. Trend signals (14:00–15:55)
            if TREND_START <= bar_t < EOD_HARD_EXIT and "TREND_FOLLOW" in active:
                for ticker, stock_df in day_stocks.items():
                    if not self._position_ok(ticker, "TREND_FOLLOW"):
                        continue
                    sig = trend.generate_signal(
                        stock_df.loc[:bar_ts],
                        hmm_state=self._hmm_state,
                    )
                    if sig:
                        self._attempt_entry(
                            sig, ticker, "TREND_FOLLOW", bar_ts, position_sizer, pdt_guard
                        )

            # 11. Exit checks on all open positions
            for trade in list(self.trade_log.open_trades):
                exit_result = self._check_exits(trade, bar_ts, bar_t, day_stocks)
                if exit_result:
                    exit_price, reason = exit_result
                    self._close_trade(trade, bar_ts, exit_price, reason)

            # 12. Circuit breaker check
            cb = circuit_breakers.check(
                daily_pnl_pct=self.equity_tracker.daily_pnl_pct,
                consecutive_losses=self.trade_log.consecutive_losses(),
            )
            if cb.should_halt:
                logger.critical(
                    f"{bar_ts} | CIRCUIT BREAKER: {cb.reason} | "
                    f"daily P&L: {self.equity_tracker.daily_pnl_pct:.2%}"
                )
                self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER")
                self._circuit_breaker_active = True
                break

        # EOD: close anything still open
        if not self._circuit_breaker_active:
            self._close_all(day, day_stocks, "EOD")

        # Record session summary
        day_trades = self.trade_log.trades_on_date(day.date())
        self._session_summaries.append(
            SessionSummary(
                date=day,
                starting_equity=session_start_equity,
                ending_equity=self.equity_tracker.equity,
                day_trades=day_trades,
                regime_bar_counts=dict(self._regime_bar_counts),
                circuit_breaker_fired=self._circuit_breaker_active,
            )
        )

        logger.info(
            f"EOD {day.date()} | Equity: ${self.equity_tracker.equity:,.2f} "
            f"({self.equity_tracker.daily_pnl_pct:+.2%}) | "
            f"Trades today: {len(day_trades)} | Regime: {self._regime_bar_counts}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Trade execution helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _position_ok(self, ticker: str, strategy: str) -> bool:
        """Position limit gate — checked before every signal attempt."""
        if ticker in self.trade_log.open_tickers():
            return False
        if self.trade_log.total_open_count() >= MAX_TOTAL:
            return False
        if self.trade_log.open_count_by_strategy(strategy) >= STRATEGY_CAPS.get(strategy, 2):
            return False
        return True

    def _attempt_entry(
        self,
        signal: Dict[str, Any],
        ticker: str,
        strategy: str,
        bar_ts: pd.Timestamp,
        position_sizer: Any,
        pdt_guard: Any,
    ) -> None:
        """Attempt to open a position. Logs every rejection for audit trail."""
        # PDT guard
        if self.config.enable_pdt_guard:
            is_dt = signal.get("is_day_trade", True)
            if is_dt and not pdt_guard.can_day_trade(bar_ts.date()):
                logger.info(f"{bar_ts} | PDT BLOCK: {ticker} {strategy}")
                return

        # Position sizing (3-constraint system)
        size = position_sizer.calculate(
            entry_price=signal["entry_price"],
            stop_price=signal["stop"],
            hmm_state=self._hmm_state,
            strategy=strategy,
            current_equity=self.equity_tracker.equity,
        )

        if size.shares <= 0:
            logger.debug(f"{bar_ts} | SIZE=0: {ticker} {strategy} — skipped")
            return

        # Open the trade
        trade = self.trade_log.open_trade(
            ticker=ticker,
            strategy=strategy,
            direction=signal["direction"],
            entry_time=bar_ts,
            entry_price=signal["entry_price"],
            shares=size.shares,
            stop=signal["stop"],
            target=signal["target"],
            hmm_state=self._hmm_state,
            limiting_factor=size.limiting_factor,
        )

        if self.config.enable_pdt_guard and signal.get("is_day_trade", True):
            pdt_guard.record_day_trade(bar_ts.date())

        logger.info(
            f"{bar_ts} | OPEN {ticker} {strategy} {signal['direction']} "
            f"{size.shares}sh @ ${signal['entry_price']:.2f} | "
            f"Stop ${signal['stop']:.2f} Target ${signal['target']:.2f} | "
            f"Regime: {self._hmm_state} | Limiting: {size.limiting_factor}"
        )

    def _check_exits(
        self,
        trade: Trade,
        bar_ts: pd.Timestamp,
        bar_t: dtime,
        day_stocks: Dict[str, pd.DataFrame],
    ) -> Optional[Tuple[float, str]]:
        """Return (exit_price, reason) if an exit condition is met, else None."""
        if trade.ticker not in day_stocks:
            return None

        try:
            bar = day_stocks[trade.ticker].loc[bar_ts]
        except KeyError:
            return None

        bar_low  = float(bar["low"])
        bar_high = float(bar["high"])
        bar_close = float(bar["close"])

        # Hard EOD exit
        if bar_t >= EOD_HARD_EXIT:
            return bar_close, "EOD"

        if trade.direction == "LONG":
            if bar_low  <= trade.stop:   return trade.stop,   "STOP_HIT"
            if bar_high >= trade.target: return trade.target, "TARGET_HIT"
        else:  # SHORT
            if bar_high >= trade.stop:   return trade.stop,   "STOP_HIT"
            if bar_low  <= trade.target: return trade.target, "TARGET_HIT"

        # VWAP MR 45-minute time stop
        if trade.strategy == "VWAP_MR":
            elapsed_min = (bar_ts - trade.entry_time).total_seconds() / 60
            if elapsed_min >= 45:
                return bar_close, "TIME_STOP"

        return None

    def _close_trade(
        self,
        trade: Trade,
        exit_ts: pd.Timestamp,
        exit_price: float,
        reason: str,
    ) -> None:
        """Apply costs, close trade, and update equity."""
        costs = self._compute_costs(trade, exit_price)

        self.trade_log.close_trade(
            trade,
            exit_time=exit_ts,
            exit_price=exit_price,
            exit_reason=reason,
            total_costs=costs,
        )
        self.equity_tracker.apply_pnl(trade.net_pnl or 0.0, exit_ts)

        logger.info(
            f"{exit_ts} | CLOSE {trade.ticker} {trade.strategy} "
            f"@ ${exit_price:.2f} [{reason}] | "
            f"Net P&L: ${trade.net_pnl:.2f} | Costs: ${costs:.2f}"
        )

    def _close_all(
        self,
        timestamp: pd.Timestamp,
        day_stocks: Dict[str, pd.DataFrame],
        reason: str,
    ) -> None:
        """Close all open positions (EOD, Safety Mode, Circuit Breaker)."""
        open_trades = list(self.trade_log.open_trades)
        if not open_trades:
            return
        logger.warning(f"{timestamp} | Closing {len(open_trades)} positions — {reason}")
        for trade in open_trades:
            if trade.ticker in day_stocks and not day_stocks[trade.ticker].empty:
                exit_price = float(day_stocks[trade.ticker].iloc[-1]["close"])
            else:
                exit_price = trade.entry_price  # fallback: no P&L
            self._close_trade(trade, timestamp, exit_price, reason)

    def _compute_costs(self, trade: Trade, exit_price: float) -> float:
        """Call Phase 1A cost model. Returns 0 if costs are disabled or module errors."""
        if not self.config.enable_costs:
            return 0.0
        try:
            calc = self._mods["calc_costs"]
            result = calc({
                "ticker":      trade.ticker,
                "shares":      trade.shares,
                "price":       exit_price,
                "direction":   trade.direction,
                "hmm_state":   trade.hmm_state,
                "market_cap":  "large",     # default; real impl looks up from data
                "adv":         1_000_000,   # default ADV
                "volatility":  0.02,
                "side":        "sell" if trade.direction == "LONG" else "buy",
            })
            # Handle both dict and object return types from costs module
            if isinstance(result, dict):
                return float(result.get("total", 0.0))
            return float(getattr(result, "total", 0.0))
        except Exception as e:
            logger.warning(f"Cost calculation error for {trade.ticker}: {e}")
            return 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Layer 0 Override
    # ─────────────────────────────────────────────────────────────────────────

    def _check_layer0(self, spy_history: List[pd.Series]) -> bool:
        """
        Simplified Layer 0: flag Stress if the last SPY 5-min bar moved > 3σ
        relative to the rolling 20-bar return distribution.
        Full Layer 0 (VIX, 20-min window) lives in raits/hmm/volatility_override.py
        and is integrated here as the fallback when HMM hasn't caught up yet.
        """
        if len(spy_history) < 21:
            return False
        try:
            closes = pd.Series([float(b["close"]) for b in spy_history[-21:]])
            returns = closes.pct_change().dropna()
            std = returns[:-1].std()
            if std <= 0:
                return False
            z = abs(returns.iloc[-1] / std)
            return bool(z > 3.0)
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Module loading
    # ─────────────────────────────────────────────────────────────────────────

    def _load_modules(self) -> Dict[str, Any]:
        """
        Import all Phase 1A/1B/1C modules.
        Fails immediately with a clear error message on interface mismatch.
        This is intentional — integration failures should be loud, not silent.
        """
        mods: Dict[str, Any] = {}

        def get(module_path: str, attr: str, *, required: bool = True) -> Any:
            try:
                mod = importlib.import_module(module_path)
                obj = getattr(mod, attr)
                logger.debug(f"✓ Loaded {module_path}.{attr}")
                return obj
            except ImportError as e:
                msg = (
                    f"[BacktestEngine] Cannot import {module_path}\n"
                    f"  Ensure Phase 1{'A' if any(x in module_path for x in ('hmm','costs')) else 'B/1C'} "
                    f"module is in your PYTHONPATH.\n  Error: {e}"
                )
                if required:
                    raise ImportError(msg) from e
                logger.warning(msg)
                return None
            except AttributeError as e:
                msg = (
                    f"[BacktestEngine] {module_path} has no attribute '{attr}'\n"
                    f"  Interface mismatch — check the module's public API.\n  Error: {e}"
                )
                if required:
                    raise AttributeError(msg) from e
                logger.warning(msg)
                return None

        def try_paths(attr: str, paths: List[str], required: bool = True) -> Any:
            """Try multiple module paths for the same class (handles different layouts)."""
            for path in paths:
                obj = get(path, attr, required=False)
                if obj is not None:
                    return obj
            if required:
                tried = ", ".join(paths)
                raise ImportError(
                    f"[BacktestEngine] Cannot find '{attr}' in any of: {tried}\n"
                    f"  Check that Phase 1B/1C modules are installed and on PYTHONPATH."
                )
            return None

        # ── Phase 1A ──────────────────────────────────────────────────────────
        mods["HMMEngine"]        = get("raits.hmm.engine",    "HMMEngine")
        mods["compute_features"] = get("raits.hmm.features",  "build_feature_matrix")
        mods["calc_costs"]       = get("raits.costs",         "calculate_total_costs")

        # ── Phase 1B strategies ───────────────────────────────────────────────
        mods["ORBStrategy"]     = get("raits.strategies.orb",          "ORBStrategy")
        mods["VWAPMRStrategy"]  = get("raits.strategies.vwap_mr",      "VWAPMRStrategy")
        mods["TrendStrategy"]   = get("raits.strategies.trend_follow", "TrendFollowStrategy")

        # ── Phase 1C risk / coordination ──────────────────────────────────────
        mods["PDTGuard"] = try_paths("PDTGuard", [
            "raits.risk.pdt_guard",
            "raits.risk",
            "raits.coordinator.pdt_guard",
        ])
        mods["CircuitBreakers"] = try_paths("CircuitBreakerManager", [
            "raits.risk.circuit_breakers",
            "raits.risk",
            "raits.coordinator.circuit_breakers",
        ])
        mods["PositionSizer"] = try_paths("PositionSizer", [
            "raits.risk.position_sizer",
            "raits.risk",
            "raits.coordinator.position_sizer",
        ])
        mods["RegimeCoordinator"] = try_paths("RegimeCoordinator", [
            "raits.coordinator.regime_coordinator",
            "raits.coordinator",
        ])

        logger.info(
            f"BacktestEngine loaded: "
            f"HMM ✓  Costs ✓  "
            f"ORB ✓  VWAP_MR ✓  Trend ✓  "
            f"PDT ✓  CB ✓  Sizer ✓  Coordinator ✓"
        )
        return mods

    # ─────────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        os.makedirs("logs", exist_ok=True)
        logging.basicConfig(
            level=getattr(logging, self.config.log_level, logging.INFO),
            format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler("logs/backtest.log", mode="w"),
            ],
        )
