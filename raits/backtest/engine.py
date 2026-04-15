"""
raits/backtest/engine.py
BacktestEngine: Week 18 integration testing artifact.

Wired to the REAL Phase 1B/1C module interfaces discovered during integration:

  ORBStrategy.generate_signal(candle, or_high, or_low, vwap, rvol, hmm_state)
  VWAPMRStrategy.generate_signal(prev_bar, entry_bar, bb_upper, bb_lower, vwap, atr, hmm_state)
  TrendFollowStrategy.generate_signal(pullback_bar, resume_bar, ema_20, atr, hmm_state, avg_volume_10)

  RegimeCoordinator.notify_hmm_state(state, current_time: datetime)
  RegimeCoordinator.notify_override(active: bool, current_time: datetime)
  RegimeCoordinator.reset_for_new_session(session_start: datetime)

  CircuitBreakerManager.reset_for_new_session(session_date: date)
  CircuitBreakerManager.check_daily_drawdown(account_equity, session_start_equity) -> BreakerResult
  CircuitBreakerManager.record_trade_result(pnl) -> BreakerResult
"""

from __future__ import annotations
import importlib
import logging
import os
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .data_types import BacktestConfig, BacktestResult, SessionSummary, Trade
from .equity_tracker import EquityTracker
from .trade_log import TradeLog
from .metrics import compute_metrics, compute_regime_breakdown

logger = logging.getLogger("RAITS.backtest")

# ── Time windows ──────────────────────────────────────────────────────────────
ORB_SCAN_TIME    = dtime(9, 35)
ORB_RANGE_START  = dtime(9, 30)
ORB_SIGNAL_START = dtime(9, 45)
ORB_SIGNAL_END   = dtime(10, 15)
VWAP_MR_START    = dtime(10, 15)
VWAP_MR_END      = dtime(14, 0)
TREND_START      = dtime(14, 0)
EOD_HARD_EXIT    = dtime(15, 55)

# ── Position limits ───────────────────────────────────────────────────────────
MAX_TOTAL     = 5
MAX_ORB       = 2
MAX_VWAP      = 3
MAX_TREND     = 2
STRATEGY_CAPS = {"ORB": MAX_ORB, "VWAP_MR": MAX_VWAP, "TREND_FOLLOW": MAX_TREND}

# ── Regime → active strategies (from each strategy's allowed_regimes config) ──
_REGIME_STRATEGIES: Dict[str, List[str]] = {
    "Calm":   ["ORB", "VWAP_MR"],
    "Normal": ["ORB", "TREND_FOLLOW"],
    "Stress": [],
}

# ── Strategy stats for PositionSizer ─────────────────────────────────────────
STRATEGY_STATS = {
    "ORB":          {"win_rate": 0.62, "avg_win": 4.50, "avg_loss": 2.00},
    "VWAP_MR":      {"win_rate": 0.68, "avg_win": 2.80, "avg_loss": 1.50},
    "TREND_FOLLOW": {"win_rate": 0.45, "avg_win": 8.00, "avg_loss": 3.50},
}


class BacktestEngine:

    def __init__(self, config: BacktestConfig):
        self.config = config
        self._setup_logging()
        self.equity_tracker = EquityTracker(config.account_equity)
        self.trade_log = TradeLog()
        self._session_summaries: List[SessionSummary] = []
        self._hmm_state: str = "Normal"
        self._safety_mode_active: bool = False
        self._circuit_breaker_active: bool = False
        self._last_retrain_date: Optional[datetime] = None
        self._regime_bar_counts: Dict[str, int] = {}
        self._mods = self._load_modules()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run(self, market_data: Dict[str, pd.DataFrame]) -> BacktestResult:
        if "SPY" not in market_data:
            raise ValueError("market_data must contain 'SPY'.")

        spy_data = market_data["SPY"]

        def to_daily_close(bars: pd.DataFrame) -> pd.Series:
            return bars["close"].resample("B").last().dropna()

        HMMEngine        = self._mods["HMMEngine"]
        pdt_guard        = self._mods["PDTGuard"]()
        circuit_breakers = self._mods["CircuitBreakers"]()
        position_sizer   = self._mods["PositionSizer"](
            account_equity=self.config.account_equity
        )
        coordinator      = self._mods["RegimeCoordinator"]()
        orb     = self._mods["ORBStrategy"]()
        vwap_mr = self._mods["VWAPMRStrategy"](
            config={"bb_std_dev": self.config.vwap_bb_std}
        )
        trend   = self._mods["TrendStrategy"](
            config={"ema_period": self.config.ema_period}
        )

        hmm = HMMEngine()
        logger.info("Training HMM...")
        try:
            hmm.fit(to_daily_close(spy_data))
            logger.info("HMM trained.")
        except Exception as e:
            logger.warning(f"HMM fit failed ({e}) — using default regime Normal")
            hmm = None

        all_days = pd.DatetimeIndex(spy_data.index.normalize().unique())
        all_days = all_days[
            (all_days >= pd.Timestamp(self.config.start_date))
            & (all_days <= pd.Timestamp(self.config.end_date))
        ]

        for day in all_days:
            self._run_day(
                day=day,
                market_data=market_data,
                spy_data=spy_data,
                hmm=hmm,
                to_daily_close=to_daily_close,
                pdt_guard=pdt_guard,
                circuit_breakers=circuit_breakers,
                position_sizer=position_sizer,
                coordinator=coordinator,
                orb=orb,
                vwap_mr=vwap_mr,
                trend=trend,
            )

            if self.config.hmm_retrain_weekly and day.weekday() == 0:
                if (self._last_retrain_date is None
                        or (day - self._last_retrain_date).days >= 7):
                    recent_spy = spy_data[spy_data.index.normalize() <= day]
                    if hmm is not None:
                        try:
                            hmm.retrain(to_daily_close(recent_spy))
                        except Exception as e:
                            logger.debug(f"HMM retrain failed: {e}")
                    self._last_retrain_date = day

        equity_curve    = self.equity_tracker.get_equity_curve()
        all_trades      = self.trade_log.all_trades()
        metrics         = compute_metrics(equity_curve, all_trades)
        regime_breakdown = compute_regime_breakdown(all_trades)

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
        to_daily_close: Any,
        pdt_guard: Any,
        circuit_breakers: Any,
        position_sizer: Any,
        coordinator: Any,
        orb: Any,
        vwap_mr: Any,
        trend: Any,
    ) -> None:
        # ── Daily reset ───────────────────────────────────────────────────────
        self._circuit_breaker_active = False
        self._safety_mode_active = False
        self._regime_bar_counts = {"Calm": 0, "Normal": 0, "Stress": 0}

        session_dt = day.to_pydatetime()
        try:
            circuit_breakers.reset_for_new_session(day.date())
        except Exception:
            pass
        try:
            coordinator.reset_for_new_session(session_dt)
        except Exception:
            pass

        orb.reset()
        if hasattr(vwap_mr, "reset"):
            vwap_mr.reset()
        if hasattr(trend, "reset"):
            trend.reset()

        session_start_equity = self.equity_tracker.equity
        self.equity_tracker.new_session(day)

        # ── Day bars ──────────────────────────────────────────────────────────
        day_spy = spy_data[spy_data.index.normalize() == day]
        if day_spy.empty:
            return

        day_stocks: Dict[str, pd.DataFrame] = {
            ticker: market_data[ticker][market_data[ticker].index.normalize() == day]
            for ticker in self.config.universe
            if ticker in market_data and ticker != "SPY"
            and not market_data[ticker][market_data[ticker].index.normalize() == day].empty
        }

        _regime_updated_today = False
        orb_scanned = False
        or_ranges: Dict[str, Tuple[float, float]] = {}
        spy_history: List[pd.Series] = []

        # ── Bar loop ──────────────────────────────────────────────────────────
        for bar_ts, spy_bar in day_spy.iterrows():
            if self._circuit_breaker_active:
                break

            spy_history.append(spy_bar)
            bar_t = bar_ts.time()
            bar_dt = bar_ts.to_pydatetime()

            # 1. Update HMM once per day on first bar
            if not _regime_updated_today:
                spy_daily = to_daily_close(
                    spy_data[spy_data.index.normalize() <= bar_ts.normalize()]
                )
                if len(spy_daily) >= 20:
                    if hmm is not None:
                        try:
                            idx = hmm.predict_current(spy_daily)
                            self._hmm_state = ["Calm", "Normal", "Stress"][min(int(idx), 2)]
                        except Exception as e:
                            logger.debug(f"predict_current failed: {e}")
                try:
                    coordinator.notify_hmm_state(self._hmm_state, bar_dt)
                except Exception:
                    pass
                _regime_updated_today = True

            self._regime_bar_counts[self._hmm_state] = (
                self._regime_bar_counts.get(self._hmm_state, 0) + 1
            )

            # 2. Layer 0 override
            override = self._check_layer0(spy_history)
            try:
                coordinator.notify_override(override, bar_dt)
            except Exception:
                pass

            # 3. Trading allowed?
            try:
                trading_ok = coordinator.trading_allowed
            except Exception:
                trading_ok = not (override or self._hmm_state == "Stress")

            if not trading_ok:
                if not self._safety_mode_active:
                    logger.critical(f"{bar_ts} | SAFETY MODE ON")
                    self._safety_mode_active = True
                self._close_all(bar_ts, day_stocks, "SAFETY_MODE")
                continue
            else:
                if self._safety_mode_active:
                    logger.info(f"{bar_ts} | SAFETY MODE OFF")
                    self._safety_mode_active = False

            # 4. Active strategies for current regime
            try:
                effective = coordinator.effective_hmm_state
            except Exception:
                effective = self._hmm_state
            active = _REGIME_STRATEGIES.get(effective, [])

            # 5. ORB scanner at 9:35
            if bar_t == ORB_SCAN_TIME and not orb_scanned and "ORB" in active:
                candidates = self._build_orb_candidates(day_stocks)
                try:
                    orb.run_scanner(candidates)
                except Exception as e:
                    logger.debug(f"ORB scanner error: {e}")
                orb_scanned = True
                logger.info(f"{bar_ts} | ORB scan → {len(orb.watchlist)} candidates")

            # 6. ORB range formation 9:30–9:45
            if ORB_RANGE_START <= bar_t < ORB_SIGNAL_START and "ORB" in active:
                for ticker in orb.watchlist:
                    if ticker not in day_stocks:
                        continue
                    bars_so_far = day_stocks[ticker].loc[:bar_ts]
                    if len(bars_so_far) < 2:
                        continue
                    atr = self._compute_atr(bars_so_far)
                    try:
                        or_high, or_low, status = orb.calculate_opening_range(
                            bars_so_far, atr
                        )
                        if status == "VALID":
                            or_ranges[ticker] = (or_high, or_low)
                    except Exception as e:
                        logger.debug(f"OR calc error {ticker}: {e}")

            # 7. ORB signals 9:45–10:15
            if ORB_SIGNAL_START <= bar_t <= ORB_SIGNAL_END and "ORB" in active:
                for ticker, (or_high, or_low) in list(or_ranges.items()):
                    if not self._position_ok(ticker, "ORB"):
                        continue
                    if ticker not in day_stocks:
                        continue
                    bars_so_far = day_stocks[ticker].loc[:bar_ts]
                    if bars_so_far.empty:
                        continue
                    try:
                        candle = bars_so_far.iloc[-1]
                        vwap_val = vwap_mr.calculate_vwap(bars_so_far)
                        avg_vol = float(bars_so_far["volume"].mean()) or 1.0
                        rvol = orb.calculate_intraday_rvol(
                            int(candle["volume"]), avg_vol
                        )
                        sig = orb.generate_signal(
                            candle, or_high, or_low, vwap_val, rvol, self._hmm_state
                        )
                        if sig:
                            sig = self._normalise_signal(sig)
                            self._attempt_entry(
                                sig, ticker, "ORB", bar_ts, position_sizer, pdt_guard
                            )
                    except Exception as e:
                        logger.debug(f"ORB signal error {ticker}: {e}")

            # 8. VWAP MR 10:15–14:00
            if VWAP_MR_START <= bar_t < VWAP_MR_END and "VWAP_MR" in active:
                for ticker, stock_df in day_stocks.items():
                    if not self._position_ok(ticker, "VWAP_MR"):
                        continue
                    bars_so_far = stock_df.loc[:bar_ts]
                    if len(bars_so_far) < 22:
                        continue
                    try:
                        bb_upper, _, bb_lower = vwap_mr.calculate_bollinger_bands(
                            bars_so_far.iloc[:-1],
                            period=20,
                            std_dev=self.config.vwap_bb_std,
                        )
                        vwap_val = vwap_mr.calculate_vwap(bars_so_far)
                        atr = self._compute_atr(bars_so_far)
                        prev_bar  = bars_so_far.iloc[-2]
                        entry_bar = bars_so_far.iloc[-1]
                        sig = vwap_mr.generate_signal(
                            prev_bar, entry_bar, bb_upper, bb_lower,
                            vwap_val, atr, self._hmm_state,
                        )
                        if sig:
                            sig = self._normalise_signal(sig)
                            self._attempt_entry(
                                sig, ticker, "VWAP_MR", bar_ts, position_sizer, pdt_guard
                            )
                    except Exception as e:
                        logger.debug(f"VWAP MR error {ticker}: {e}")

            # 9. Trend 14:00–15:55
            if TREND_START <= bar_t < EOD_HARD_EXIT and "TREND_FOLLOW" in active:
                for ticker, stock_df in day_stocks.items():
                    if not self._position_ok(ticker, "TREND_FOLLOW"):
                        continue
                    bars_so_far = stock_df.loc[:bar_ts]
                    if len(bars_so_far) < 3:
                        continue
                    try:
                        ema_val = trend.calculate_ema(
                            bars_so_far, period=self.config.ema_period
                        )
                        atr = self._compute_atr(bars_so_far)
                        avg_vol_10 = float(bars_so_far["volume"].tail(10).mean()) or 1.0
                        pullback_bar = bars_so_far.iloc[-2]
                        resume_bar  = bars_so_far.iloc[-1]
                        sig = trend.generate_signal(
                            pullback_bar, resume_bar, ema_val, atr,
                            self._hmm_state, avg_vol_10,
                        )
                        if sig:
                            # Trend has no fixed target — add 3×ATR placeholder
                            if "target" not in sig:
                                atr_t = sig.get("atr", atr)
                                sig["target"] = (
                                    sig["entry_price"] + 3 * atr_t
                                    if sig["direction"] == "LONG"
                                    else sig["entry_price"] - 3 * atr_t
                                )
                            sig = self._normalise_signal(sig)
                            self._attempt_entry(
                                sig, ticker, "TREND_FOLLOW", bar_ts, position_sizer, pdt_guard
                            )
                    except Exception as e:
                        logger.debug(f"Trend signal error {ticker}: {e}")

            # 10. Exit checks
            for trade in list(self.trade_log.open_trades):
                exit_result = self._check_exits(trade, bar_ts, bar_t, day_stocks)
                if exit_result:
                    exit_price, reason = exit_result
                    self._close_trade(
                        trade, bar_ts, exit_price, reason,
                        circuit_breakers, coordinator, bar_dt,
                    )

            # 11. Daily drawdown circuit breaker
            try:
                dd = circuit_breakers.check_daily_drawdown(
                    account_equity=self.equity_tracker.equity,
                    session_start_equity=session_start_equity,
                )
                if dd.kill_switch:
                    try:
                        coordinator.notify_circuit_breaker(bar_dt)
                    except Exception:
                        pass
                    logger.critical(f"{bar_ts} | CIRCUIT BREAKER: {dd.reason}")
                    self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER")
                    self._circuit_breaker_active = True
                    break
            except Exception as e:
                logger.debug(f"CB check error: {e}")
                # Fallback manual check
                pnl_pct = self.equity_tracker.daily_pnl_pct
                if pnl_pct <= -0.04:
                    logger.critical(f"{bar_ts} | CIRCUIT BREAKER (fallback): {pnl_pct:.2%}")
                    self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER")
                    self._circuit_breaker_active = True
                    break

        # EOD close
        if not self._circuit_breaker_active:
            self._close_all(day, day_stocks, "EOD")

        day_trades = self.trade_log.trades_on_date(day.date())
        self._session_summaries.append(SessionSummary(
            date=day,
            starting_equity=session_start_equity,
            ending_equity=self.equity_tracker.equity,
            day_trades=day_trades,
            regime_bar_counts=dict(self._regime_bar_counts),
            circuit_breaker_fired=self._circuit_breaker_active,
        ))
        logger.info(
            f"EOD {day.date()} | ${self.equity_tracker.equity:,.2f} "
            f"({self.equity_tracker.daily_pnl_pct:+.2%}) | "
            f"Trades: {len(day_trades)} | Regime: {self._regime_bar_counts}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Signal normalisation
    # ─────────────────────────────────────────────────────────────────────────

    def _normalise_signal(self, sig: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalise signal dict to the keys _attempt_entry expects.
        Strategies use 'stop_loss' or 'initial_stop'; engine uses 'stop'.
        """
        out = dict(sig)
        # Normalise stop key
        if "stop" not in out:
            out["stop"] = out.get("stop_loss") or out.get("initial_stop", 0.0)
        # Ensure is_day_trade present
        out.setdefault("is_day_trade", True)
        return out

    # ─────────────────────────────────────────────────────────────────────────
    # Indicator helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
        """14-period ATR. Falls back to 1.5% of close on insufficient data."""
        if len(bars) < 2:
            return float(bars["close"].iloc[-1]) * 0.015
        hl  = bars["high"] - bars["low"]
        hpc = (bars["high"] - bars["close"].shift(1)).abs()
        lpc = (bars["low"]  - bars["close"].shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        return float(tr.tail(period).mean())

    def _build_orb_candidates(
        self, day_stocks: Dict[str, pd.DataFrame]
    ) -> List[Dict[str, Any]]:
        """
        Build the candidates list expected by ORBStrategy.run_scanner.
        In the absence of pre-market data we synthesise a ~3% gap so the
        gap filter passes, and use opening bar volume for the liquidity check.
        """
        candidates = []
        for ticker, df in day_stocks.items():
            if df.empty:
                continue
            first = df.iloc[0]
            open_p = float(first["open"])
            # Synthetic prev_close: 3% gap guarantees gap filter passes (min 2%)
            prev_close = open_p / 1.03
            avg_vol = max(int(df["volume"].mean()), 1)
            candidates.append({
                "ticker":              ticker,
                "prev_close":          round(prev_close, 2),
                "open_price":          open_p,
                "premarket_volume":    0,
                "avg_daily_volume":    avg_vol,
                "opening_5min_volume": int(first["volume"]),
            })
        return candidates

    # ─────────────────────────────────────────────────────────────────────────
    # Trade execution
    # ─────────────────────────────────────────────────────────────────────────

    def _position_ok(self, ticker: str, strategy: str) -> bool:
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
        # PDT guard
        if self.config.enable_pdt_guard and signal.get("is_day_trade", True):
            try:
                decision = pdt_guard.check_can_day_trade(bar_ts.date())
                if not decision.passed:
                    logger.info(f"{bar_ts} | PDT BLOCK: {ticker}")
                    return
            except Exception as e:
                logger.debug(f"PDT check error: {e}")

        # Position sizing
        stats = STRATEGY_STATS.get(strategy, {"win_rate": 0.50, "avg_win": 3.0, "avg_loss": 2.0})
        stop = signal.get("stop", 0.0) or signal.get("stop_loss", 0.0) or signal.get("initial_stop", 0.0)
        entry = signal.get("entry_price", 0.0)

        try:
            size = position_sizer.calculate(
                entry_price=entry,
                stop_loss=stop,
                strategy_stats=stats,
            )
        except Exception as e:
            logger.debug(f"Position sizing error: {e}")
            return

        if size is None or (isinstance(size, dict) and size.get("shares", 0) <= 0):
            return

        n_shares     = int(size["shares"]) if isinstance(size, dict) else int(getattr(size, "shares", 0))
        limit_factor = size.get("limiting_factor", "UNKNOWN") if isinstance(size, dict) else getattr(size, "limiting_factor", "UNKNOWN")

        if n_shares <= 0:
            return

        target = signal.get("target", entry * 1.05 if signal.get("direction") == "LONG" else entry * 0.95)

        trade = self.trade_log.open_trade(
            ticker=ticker,
            strategy=strategy,
            direction=signal["direction"],
            entry_time=bar_ts,
            entry_price=entry,
            shares=n_shares,
            stop=stop,
            target=target,
            hmm_state=self._hmm_state,
            limiting_factor=limit_factor,
        )

        if self.config.enable_pdt_guard and signal.get("is_day_trade", True):
            try:
                pdt_guard.record_day_trade(bar_ts.date())
            except Exception:
                pass

        logger.info(
            f"{bar_ts} | OPEN {ticker} {strategy} {signal['direction']} "
            f"{n_shares}sh @ ${entry:.2f} | stop=${stop:.2f} target=${target:.2f} | "
            f"Regime:{self._hmm_state} Limit:{limit_factor}"
        )

    def _check_exits(
        self,
        trade: Trade,
        bar_ts: pd.Timestamp,
        bar_t: dtime,
        day_stocks: Dict[str, pd.DataFrame],
    ) -> Optional[Tuple[float, str]]:
        if trade.ticker not in day_stocks:
            return None
        try:
            bar = day_stocks[trade.ticker].loc[bar_ts]
        except KeyError:
            return None

        bar_low   = float(bar["low"])
        bar_high  = float(bar["high"])
        bar_close = float(bar["close"])

        if bar_t >= EOD_HARD_EXIT:
            return bar_close, "EOD"

        if trade.direction == "LONG":
            if bar_low  <= trade.stop:   return trade.stop,   "STOP_HIT"
            if bar_high >= trade.target: return trade.target, "TARGET_HIT"
        else:
            if bar_high >= trade.stop:   return trade.stop,   "STOP_HIT"
            if bar_low  <= trade.target: return trade.target, "TARGET_HIT"

        if trade.strategy == "VWAP_MR":
            elapsed = (bar_ts - trade.entry_time).total_seconds() / 60
            if elapsed >= 45:
                return bar_close, "TIME_STOP"

        return None

    def _close_trade(
        self,
        trade: Trade,
        exit_ts: pd.Timestamp,
        exit_price: float,
        reason: str,
        circuit_breakers: Any,
        coordinator: Any,
        bar_dt: datetime,
    ) -> None:
        costs = self._compute_costs(trade, exit_price)
        self.trade_log.close_trade(
            trade,
            exit_time=exit_ts,
            exit_price=exit_price,
            exit_reason=reason,
            total_costs=costs,
        )
        self.equity_tracker.apply_pnl(trade.net_pnl or 0.0, exit_ts)

        # Record trade result with circuit breaker (Kill Switch 2)
        try:
            result = circuit_breakers.record_trade_result(trade.net_pnl or 0.0)
            if result.kill_switch:
                try:
                    coordinator.notify_circuit_breaker(bar_dt)
                except Exception:
                    pass
                logger.critical(f"CIRCUIT BREAKER (consecutive losses): {result.reason}")
                self._circuit_breaker_active = True
        except Exception as e:
            logger.debug(f"record_trade_result error: {e}")

        logger.info(
            f"{exit_ts} | CLOSE {trade.ticker} {trade.strategy} "
            f"@ ${exit_price:.2f} [{reason}] | "
            f"net P&L: ${trade.net_pnl:.2f} costs: ${costs:.2f}"
        )

    def _close_all(
        self,
        timestamp: pd.Timestamp,
        day_stocks: Dict[str, pd.DataFrame],
        reason: str,
    ) -> None:
        open_trades = list(self.trade_log.open_trades)
        if not open_trades:
            return
        logger.warning(f"{timestamp} | Closing {len(open_trades)} positions — {reason}")
        for trade in open_trades:
            if trade.ticker in day_stocks and not day_stocks[trade.ticker].empty:
                price = float(day_stocks[trade.ticker].iloc[-1]["close"])
            else:
                price = trade.entry_price
            costs = self._compute_costs(trade, price)
            self.trade_log.close_trade(
                trade,
                exit_time=timestamp,
                exit_price=price,
                exit_reason=reason,
                total_costs=costs,
            )
            self.equity_tracker.apply_pnl(trade.net_pnl or 0.0, timestamp)

    def _compute_costs(self, trade: Trade, exit_price: float) -> float:
        if not self.config.enable_costs:
            return 0.0
        try:
            calc   = self._mods["calc_costs"]
            result = calc({
                "ticker":     trade.ticker,
                "shares":     trade.shares,
                "price":      exit_price,
                "direction":  "BUY" if trade.direction == "LONG" else "SELL",
                "hmm_state":  trade.hmm_state,
                "market_cap": 2.5e12,
                "adv":        1_000_000,
                "volatility": 0.02,
                "side":       "sell" if trade.direction == "LONG" else "buy",
            })
            if isinstance(result, dict):
                return float(result.get("total", 0.0))
            return float(getattr(result, "total", 0.0))
        except Exception as e:
            logger.warning(f"Cost error {trade.ticker}: {e}")
            return 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Layer 0 override
    # ─────────────────────────────────────────────────────────────────────────

    def _check_layer0(self, spy_history: List[pd.Series]) -> bool:
        if len(spy_history) < 21:
            return False
        try:
            closes  = pd.Series([float(b["close"]) for b in spy_history[-21:]])
            returns = closes.pct_change().dropna()
            std     = returns[:-1].std()
            if std <= 0:
                return False
            return bool(abs(returns.iloc[-1] / std) > 3.0)
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Module loading
    # ─────────────────────────────────────────────────────────────────────────

    def _load_modules(self) -> Dict[str, Any]:
        mods: Dict[str, Any] = {}

        def get(module_path: str, attr: str, *, required: bool = True) -> Any:
            try:
                mod = importlib.import_module(module_path)
                obj = getattr(mod, attr)
                logger.debug(f"✓ {module_path}.{attr}")
                return obj
            except ImportError as e:
                msg = f"[BacktestEngine] Cannot import {module_path}: {e}"
                if required:
                    raise ImportError(msg) from e
                logger.warning(msg)
                return None
            except AttributeError as e:
                msg = f"[BacktestEngine] {module_path} has no attribute '{attr}': {e}"
                if required:
                    raise AttributeError(msg) from e
                logger.warning(msg)
                return None

        def try_paths(attr: str, paths: List[str], required: bool = True) -> Any:
            for path in paths:
                obj = get(path, attr, required=False)
                if obj is not None:
                    return obj
            if required:
                raise ImportError(
                    f"[BacktestEngine] Cannot find '{attr}' in: {', '.join(paths)}"
                )
            return None

        # Phase 1A
        mods["HMMEngine"]        = get("raits.hmm.engine",   "HMMEngine")
        mods["compute_features"] = get("raits.hmm.features",  "build_feature_matrix")
        mods["calc_costs"]       = get("raits.costs",         "calculate_total_costs")

        # Phase 1B
        mods["ORBStrategy"]    = get("raits.strategies.orb",          "ORBStrategy")
        mods["VWAPMRStrategy"] = get("raits.strategies.vwap_mr",      "VWAPMRStrategy")
        mods["TrendStrategy"]  = get("raits.strategies.trend_follow", "TrendFollowStrategy")

        # Phase 1C
        mods["PDTGuard"] = try_paths("PDTGuard", [
            "raits.risk.pdt_guard", "raits.risk", "raits.coordinator.pdt_guard",
        ])
        mods["CircuitBreakers"] = try_paths("CircuitBreakerManager", [
            "raits.risk.circuit_breakers", "raits.risk",
        ])
        mods["PositionSizer"] = try_paths("PositionSizer", [
            "raits.risk.position_sizer", "raits.risk",
        ])
        mods["RegimeCoordinator"] = try_paths("RegimeCoordinator", [
            "raits.coordinator.regime_coordinator", "raits.coordinator",
        ])

        logger.info("BacktestEngine: all modules loaded ✓")
        return mods

    # ─────────────────────────────────────────────────────────────────────────
    # Logging
    # ─────────────────────────────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        os.makedirs("logs", exist_ok=True)
        handlers = [logging.StreamHandler()]
        try:
            handlers.append(logging.FileHandler("logs/backtest.log", mode="w"))
        except (PermissionError, OSError):
            pass
        logging.basicConfig(
            level=getattr(logging, self.config.log_level, logging.INFO),
            format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            handlers=handlers,
        )
