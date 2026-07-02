"""
raits/live/runner.py

Paper-trading orchestration loop.

Components
----------
MockContextFeed   -- replays a list of pre-built BarContext objects (backtest replay)
LiveContextFeed   -- stub; raises NotImplementedError (wired up later)
PaperTrader       -- main loop: DecisionUnit → intents → Orders → Broker → Recon

Discipline guards
-----------------
DISCIPLINE_LOCK   -- hash locked config params; assert match at startup
PAPER_ONLY        -- refuse live IBKR port (7496) without --i-understand-this-is-live
KILL_SWITCH       -- halt if simulated daily net P&L falls below cap

Usage (mock / replay)
---------------------
    feed   = MockContextFeed(bar_contexts)
    broker = MockBroker(slippage_pct=0.001)
    recon  = ReconciliationLog(out_dir="data/recon/today")
    trader = PaperTrader(decision_unit, broker, recon, config,
                         live_mode=False)
    result = trader.run(feed)
    print(recon.analyze())
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional

from raits.decision.types import BarContext, DecisionResult, EntryIntent, ExitIntent
from raits.backtest.data_types import Trade
from raits.risk.circuit_breakers import CircuitBreakerManager

from .broker import BrokerInterface, FillStatus, Order
from .reconciliation import ReconciliationLog

logger = logging.getLogger("RAITS.live.runner")

# Sentinel to detect stale bytecode — changed each fix iteration
_RUNNER_VERSION = "EOD+EOP+CB-v5-same-bar-exit"
print(f"[RUNNER] loaded runner.py version={_RUNNER_VERSION} from {__file__}")

# Default kill-switch threshold: -4% daily drawdown (matches circuit-breaker)
DEFAULT_KILL_SWITCH_PCT = 0.04


# ── Context feeds ─────────────────────────────────────────────────────────────

class ContextFeed(ABC):
    """Yields BarContext objects one by one."""

    @abstractmethod
    def __iter__(self) -> Iterator[BarContext]:
        ...


class MockContextFeed(ContextFeed):
    """
    Replay a pre-built sequence of BarContext objects.
    Source: build them from an existing backtest run's bar loop.
    """

    def __init__(self, bar_contexts: List[BarContext]) -> None:
        self._contexts = bar_contexts

    def __iter__(self) -> Iterator[BarContext]:
        return iter(self._contexts)


class LiveContextFeed(ContextFeed):
    """
    Stub for live-market context feed (Polygon WebSocket / IBKR feed).
    Raises NotImplementedError — not yet implemented.
    """

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "LiveContextFeed is not yet implemented. "
            "Use MockContextFeed for paper-trading verification."
        )

    def __iter__(self) -> Iterator[BarContext]:
        raise NotImplementedError


# ── Discipline guards ─────────────────────────────────────────────────────────

def _config_hash(config_params: Dict[str, Any]) -> str:
    """Stable hash of the locked WFO config params for discipline-lock."""
    serialized = json.dumps(config_params, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


class DisciplineLockError(RuntimeError):
    pass


class KillSwitchTripped(RuntimeError):
    pass


class PaperOnlyViolation(RuntimeError):
    pass


def check_discipline_lock(config_params: Dict[str, Any], expected_hash: str) -> None:
    """
    Raise DisciplineLockError if the hash of config_params does not match
    expected_hash.  Call at PaperTrader startup with the locked production params.
    """
    actual = _config_hash(config_params)
    if actual != expected_hash:
        raise DisciplineLockError(
            f"DISCIPLINE_LOCK FAILED: config hash mismatch.\n"
            f"  expected: {expected_hash}\n"
            f"  actual:   {actual}\n"
            f"Re-lock with the correct params or update the stored hash."
        )


def check_paper_only(ibkr_port: int, live_flag: bool) -> None:
    """
    Raise PaperOnlyViolation if the live IBKR port (7496) is used without
    the --i-understand-this-is-live flag.
    """
    LIVE_PORT = 7496
    if ibkr_port == LIVE_PORT and not live_flag:
        raise PaperOnlyViolation(
            f"PAPER_ONLY GUARD: port {ibkr_port} is the LIVE IBKR port.\n"
            "Pass --i-understand-this-is-live to the runner to override.\n"
            "Paper port is 7497."
        )


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    """Summary returned by PaperTrader.run()."""
    bars_processed: int = 0
    entries_signalled: int = 0
    exits_signalled: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_partial: int = 0
    orders_rejected: int = 0
    kill_switch_tripped: bool = False
    kill_switch_bar: Optional[Any] = None    # bar_ts when tripped
    simulated_pnl: float = 0.0


# ── PaperTrader ───────────────────────────────────────────────────────────────

class PaperTrader:
    """
    Orchestrates the paper-trading loop.

      for ctx in feed:
          result = decision_unit.decide(ctx)     # READ-ONLY call
          convert intents → Orders
          route through BrokerInterface
          write ReconRecord per order
          apply fills to simulated portfolio
          check kill-switch

    DecisionUnit is imported read-only: PaperTrader never modifies
    decision_unit internals.  Engine and DecisionUnit logic is UNCHANGED.

    Parameters
    ----------
    decision_unit       : DecisionUnit instance (already initialised)
    broker              : BrokerInterface (MockBroker or IBKRBroker)
    recon               : ReconciliationLog
    account_equity      : starting simulated equity
    live_mode           : True only with --i-understand-this-is-live
    ibkr_port           : IBKR port (checked by PAPER_ONLY guard)
    kill_switch_pct     : halt if daily P&L / equity < -kill_switch_pct
    discipline_params   : dict of locked WFO params; pass expected_hash to enforce
    expected_hash       : SHA-256 of discipline_params; None = skip check
    """

    def __init__(
        self,
        decision_unit: Any,           # raits.decision.decision_unit.DecisionUnit
        broker: BrokerInterface,
        recon: ReconciliationLog,
        account_equity: float = 50_000.0,
        live_mode: bool = False,
        ibkr_port: int = 7497,
        kill_switch_pct: float = DEFAULT_KILL_SWITCH_PCT,
        discipline_params: Optional[Dict[str, Any]] = None,
        expected_hash: Optional[str] = None,
        cost_fn: Optional[Any] = None,
        allow_swing_hold: bool = False,
        max_hold_days: int = 5,
    ) -> None:
        # Guards
        check_paper_only(ibkr_port, live_mode)
        if discipline_params is not None and expected_hash is not None:
            check_discipline_lock(discipline_params, expected_hash)

        self._du = decision_unit
        self._broker = broker
        self._recon = recon
        self._equity = account_equity
        self._kill_switch_pct = kill_switch_pct
        self._cost_fn = cost_fn  # Optional[Callable[[Trade, float], float]]
        self._allow_swing_hold = allow_swing_hold
        self._max_hold_days = max_hold_days

        # Simulated portfolio: trade_id → Trade (open positions)
        self._open_positions: Dict[str, Trade] = {}
        self._daily_pnl: float = 0.0
        # Completed trades (entry + exit fully populated)
        self._closed_trades: List[Trade] = []
        # Chandelier trailing-stop state for TF swing positions:
        # id(trade) → {"extreme": float}  (mirrors engine._swing_state)
        self._swing_state: Dict[int, dict] = {}

        # Circuit breaker — mirrors engine's circuit_breakers object.
        # Two triggers: daily drawdown (-4%) and consecutive losses (5).
        self._cb = CircuitBreakerManager()
        # Running equity: updated via net_pnl on every close (mirrors equity_tracker).
        self._running_equity: float = account_equity
        self._session_start_equity: float = account_equity
        # Per-day flag: True once CB fires; causes bar loop to skip remaining bars.
        self._cb_active: bool = False

    @property
    def closed_trades(self) -> List[Trade]:
        return list(self._closed_trades)

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self, feed: ContextFeed) -> RunResult:
        """Run the full paper-trading loop over the feed.

        Bar-loop order mirrors engine_refactored._run_day() exactly:
          1. Swing exits (TF + PE_SHORT) — may trigger consecutive-loss CB
          2. Skip remainder if CB fired (engine: `continue`)
          3. Intraday exits
          4. Entries
          5. Daily-drawdown CB check → _close_all_cb() if triggered
        """
        result = RunResult()
        current_day = None
        _prev_ctx = None  # last ctx of previous day — needed for EOD swing-stop update
        _SWING = ("TREND_FOLLOW", "PE_SHORT")

        for ctx in feed:
            bar_day = ctx.bar_ts.normalize()

            # ── Day reset ────────────────────────────────────────────────────
            if bar_day != current_day:
                # EOD swing-stop update for the previous day
                if _prev_ctx is not None and self._allow_swing_hold:
                    self._update_swing_stops(
                        _prev_ctx.day, _prev_ctx.market_data, _prev_ctx.day_stocks
                    )
                # EOD force-close for previous day's non-swing positions.
                # Mirrors engine._close_all(day, day_stocks, "EOD", skip_swing=True).
                # No-op on normal days (intraday positions already closed by TIME_STOP
                # signal from decide()). Fires on half-days (13:00 close) where the
                # 15:55 TIME_STOP bar never exists.
                if _prev_ctx is not None:
                    _prev_day_str = str(_prev_ctx.day.date()) if hasattr(_prev_ctx.day, "date") else str(_prev_ctx.day)[:10]
                    if _prev_day_str == "2020-11-27":
                        _open_now = [(t.ticker, t.strategy) for t in self._open_positions.values()]
                        print(f"[TRACE EOD] day={_prev_day_str}: {len(_open_now)} open positions: {_open_now}")
                    self._close_all_eod(_prev_ctx.day, _prev_ctx.day_stocks)
                current_day = bar_day
                self._daily_pnl = 0.0
                # Reset CB for new session (consecutive-loss counter carries forward)
                self._cb_active = False
                self._session_start_equity = self._running_equity
                self._cb.reset_for_new_session(bar_day.date())
                # MAX_HOLD pre-bar close (mirrors engine lines 615-632)
                self._check_max_hold(bar_day, ctx)
                self._du.reset_day(bar_day, ctx.orb_signal_start, ctx.orb_signal_end)

            # If CB fired earlier this day, skip all bar processing
            if self._cb_active:
                _prev_ctx = ctx
                continue

            # Harness kill-switch (separate from engine CB; disabled during verify)
            if self._kill_switch_triggered(ctx.bar_ts, result):
                break

            # Inject open positions into ctx so DecisionUnit can exit them
            ctx.open_trades = list(self._open_positions.values())

            # Mirror engine: swing trade tickers must remain in day_stocks even if
            # scanner dropped them today, so stop/target exit checks work.
            for _trade in ctx.open_trades:
                _tk = _trade.ticker
                if (_tk not in ctx.day_stocks and _tk != "SPY"
                        and _tk in ctx.market_data):
                    _day_bars = ctx.market_data[_tk][
                        ctx.market_data[_tk].index.normalize() == ctx.day
                    ]
                    if not _day_bars.empty:
                        ctx.day_stocks[_tk] = _day_bars

            # === DecisionUnit call ===
            decision: DecisionResult = self._du.decide(ctx)

            result.bars_processed += 1
            result.entries_signalled += len(decision.entries)
            result.exits_signalled   += len(decision.exits)

            # ── Step 1: Swing exits first (TF + PE_SHORT) ───────────────────
            # Mirrors engine: swing exits run before intraday; consecutive-loss
            # CB may fire here, causing `continue` to skip the rest of the bar.
            for exit_intent in decision.exits:
                if exit_intent.trade.strategy in _SWING:
                    self._process_exit(exit_intent, ctx.bar_ts, result)

            # ── Step 2: Skip if consecutive-loss CB fired during swing exits ─
            if self._cb_active:
                _prev_ctx = ctx
                continue

            # ── Step 3: Intraday exits ───────────────────────────────────────
            for exit_intent in decision.exits:
                if exit_intent.trade.strategy not in _SWING:
                    self._process_exit(exit_intent, ctx.bar_ts, result)

            # ── Step 4: Entries ──────────────────────────────────────────────
            # Pre-compute spy_bar once per bar for same-bar exit check below.
            _bar_t = ctx.bar_ts.time()
            _spy_bar = None
            if "SPY" in ctx.day_stocks:
                try:
                    _spy_bar = ctx.day_stocks["SPY"].loc[ctx.bar_ts]
                except (KeyError, TypeError):
                    pass
            for entry_intent in decision.entries:
                new_trade = self._process_entry(entry_intent, ctx.bar_ts, result)
                # Same-bar exit check: mirrors engine_refactored lines 778-789.
                # Engine calls _check_exits immediately after entry so the entry
                # bar's high/low can trigger stop/target before the next bar.
                # PaperTrader must do the same or it holds the trade one bar too long.
                if (new_trade is not None
                        and new_trade.strategy not in _SWING
                        and not self._cb_active):
                    _sb = self._du._check_exits(
                        new_trade, ctx.bar_ts, _bar_t, ctx.day_stocks,
                        self._allow_swing_hold, _spy_bar,
                    )
                    if _sb:
                        _sb_price, _sb_reason = _sb
                        self._process_exit(
                            ExitIntent(trade=new_trade, exit_price=_sb_price,
                                       reason=_sb_reason),
                            ctx.bar_ts, result,
                        )

            # ── Step 5: Daily-drawdown CB check ──────────────────────────────
            # Mirrors engine lines 795-820; skipped when SAFETY_MODE was active.
            if not decision.override_active:
                try:
                    dd = self._cb.check_daily_drawdown(
                        account_equity=self._running_equity,
                        session_start_equity=self._session_start_equity,
                    )
                    if dd.kill_switch:
                        self._close_all_cb(ctx.bar_ts, bar_day, ctx.day_stocks)
                        self._cb_active = True
                        _prev_ctx = ctx
                        continue
                except Exception:
                    # Fallback: same -4% threshold
                    if self._session_start_equity > 0:
                        pnl_pct = (self._running_equity - self._session_start_equity) / self._session_start_equity
                        if pnl_pct <= -0.04:
                            self._close_all_cb(ctx.bar_ts, bar_day, ctx.day_stocks)
                            self._cb_active = True
                            _prev_ctx = ctx
                            continue

            _prev_ctx = ctx

        # ── Post-loop: mirror engine's end-of-day + end-of-period cleanup ──────
        if _prev_ctx is not None:
            # EOD swing-stop update for the final day
            if self._allow_swing_hold:
                self._update_swing_stops(
                    _prev_ctx.day, _prev_ctx.market_data, _prev_ctx.day_stocks
                )
            # EOD force-close for any remaining non-swing positions on the final day
            # (mirrors engine._close_all(day, day_stocks, "EOD", skip_swing=True))
            self._close_all_eod(_prev_ctx.day, _prev_ctx.day_stocks)
            # END_OF_PERIOD: close remaining swing positions still open at IS end
            # (mirrors engine lines 438-452 — uses _close_trade so updates CB)
            self._close_end_of_period(_prev_ctx)

        result.simulated_pnl = self._daily_pnl
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _process_entry(
        self, intent: EntryIntent, bar_ts: Any, result: RunResult
    ) -> Optional[Any]:
        """Return the opened Trade (or None if order was rejected)."""
        side = "BUY" if intent.direction == "LONG" else "SELL"
        order = Order(
            order_id=str(uuid.uuid4()),
            ticker=intent.ticker,
            side=side,
            qty=intent.shares,
            limit_price=intent.entry_price,
            strategy=intent.strategy,
            hmm_state=intent.hmm_state,
            signal_ts=time.time(),
        )
        filled_order = self._broker.submit_order(order)
        result.orders_submitted += 1
        self._recon.record(filled_order)

        if filled_order.fill_status == FillStatus.FILLED:
            result.orders_filled += 1
            trade = _intent_to_trade(intent, filled_order, bar_ts)
            self._open_positions[trade.trade_id] = trade
            self._du.on_trade_opened(trade, intent)
            return trade
        elif filled_order.fill_status == FillStatus.PARTIAL:
            result.orders_partial += 1
            trade = _intent_to_trade(intent, filled_order, bar_ts, use_filled_qty=True)
            self._open_positions[trade.trade_id] = trade
            self._du.on_trade_opened(trade, intent)
            return trade
        else:
            result.orders_rejected += 1
            return None

    def _process_exit(
        self, exit_intent: ExitIntent, bar_ts: Any, result: RunResult
    ) -> None:
        trade: Trade = exit_intent.trade
        if trade.trade_id not in self._open_positions:
            return  # already closed (e.g. same-bar entry+exit in mock replay)

        side = "SELL" if trade.direction == "LONG" else "BUY"
        order = Order(
            order_id=str(uuid.uuid4()),
            ticker=trade.ticker,
            side=side,
            qty=trade.shares,
            limit_price=exit_intent.exit_price,
            strategy=trade.strategy,
            hmm_state=trade.hmm_state,
            signal_ts=time.time(),
        )
        filled_order = self._broker.submit_order(order)
        result.orders_submitted += 1
        self._recon.record(filled_order)

        if filled_order.fill_status in (FillStatus.FILLED, FillStatus.PARTIAL):
            if filled_order.fill_status == FillStatus.FILLED:
                result.orders_filled += 1
            else:
                result.orders_partial += 1

            fill_qty   = filled_order.filled_qty
            fill_price = filled_order.fill_price
            multiplier = 1 if trade.direction == "LONG" else -1
            gross_pnl  = multiplier * (fill_price - trade.entry_price) * fill_qty

            # Populate exit fields — mirrors trade_log.close_trade()
            total_costs = self._cost_fn(trade, fill_price) if self._cost_fn else 0.0
            trade.exit_time   = bar_ts
            trade.exit_price  = fill_price
            trade.exit_reason = exit_intent.reason
            trade.gross_pnl   = gross_pnl
            trade.total_costs = total_costs
            trade.net_pnl     = gross_pnl - total_costs

            self._daily_pnl      += gross_pnl
            self._running_equity += trade.net_pnl
            self._swing_state.pop(id(trade), None)
            del self._open_positions[trade.trade_id]
            self._closed_trades.append(trade)
            # Consecutive-loss CB (mirrors engine._close_trade → record_trade_result)
            cb_res = self._cb.record_trade_result(trade.net_pnl or 0.0)
            if cb_res.kill_switch:
                self._cb_active = True
        else:
            result.orders_rejected += 1

    def _close_all_eod(self, prev_day: Any, day_stocks: Any) -> None:
        """Force-close non-swing positions remaining after a day's bar loop.

        Mirrors engine._close_all(day, day_stocks, "EOD", skip_swing=True):
        - TF excluded (skip_swing=True with allow_swing_hold=True)
        - PE_SHORT entered on prev_day excluded (entry-day EOD hold)
        - exit_time = prev_day midnight (engine uses day timestamp, not bar_ts)
        - exit_price = day_stocks[ticker].iloc[-1]["close"] with stop-cap
        - Does NOT call record_trade_result (engine._close_all bypasses _close_trade)
        No-op on normal days (intraday positions closed by TIME_STOP from decide()).
        Active on half-days where 15:55 bar never exists.
        """
        import pandas as pd
        _prev_day_str = str(prev_day.date()) if hasattr(prev_day, "date") else str(prev_day)[:10]
        if _prev_day_str == "2020-11-27":
            _open_tickers = [(t.ticker, t.strategy) for t in self._open_positions.values()]
            print(f"[TRACE _close_all_eod] entered for {_prev_day_str}: {len(_open_tickers)} positions: {_open_tickers}")
        for trade_id in list(self._open_positions):
            trade = self._open_positions[trade_id]
            # Mirror engine._close_all(skip_swing=True): skip TF (when swing hold on)
            # and ALL PE_SHORT regardless of entry day — engine never EOD-closes PE_SHORT
            if self._allow_swing_hold and trade.strategy == "TREND_FOLLOW":
                continue
            if trade.strategy == "PE_SHORT":
                continue
            ticker = trade.ticker
            if _prev_day_str == "2020-11-27":
                print(f"[TRACE _close_all_eod] closing {ticker} {trade.strategy}")
            if ticker in day_stocks and not day_stocks[ticker].empty:
                _bar = day_stocks[ticker].iloc[-1]
                _px  = float(_bar["close"])
                if trade.stop is not None:
                    if trade.direction == "LONG" and float(_bar["low"]) <= trade.stop:
                        _px = max(_px, trade.stop)
                    elif trade.direction == "SHORT" and float(_bar["high"]) >= trade.stop:
                        _px = min(_px, trade.stop)
            else:
                _px = trade.entry_price
            multiplier  = 1 if trade.direction == "LONG" else -1
            gross_pnl   = multiplier * (_px - trade.entry_price) * trade.shares
            total_costs = self._cost_fn(trade, _px) if self._cost_fn else 0.0
            trade.exit_time   = prev_day   # midnight timestamp, matches engine
            trade.exit_price  = _px
            trade.exit_reason = "EOD"
            trade.gross_pnl   = gross_pnl
            trade.total_costs = total_costs
            trade.net_pnl     = gross_pnl - total_costs
            self._running_equity += trade.net_pnl
            self._daily_pnl     += gross_pnl
            self._swing_state.pop(id(trade), None)
            del self._open_positions[trade_id]
            self._closed_trades.append(trade)
            # No record_trade_result — engine._close_all doesn't call _close_trade

    def _close_end_of_period(self, last_ctx: Any) -> None:
        """Force-close all positions remaining at the end of the IS period.

        Mirrors engine lines 438-452 (END_OF_PERIOD force-close after the run loop):
        - exit_time = last bar timestamp of the final day (not midnight)
        - exit_price = last bar's close for each ticker
        - Uses _close_trade equivalent (calls record_trade_result, updates CB)
        Covers swing positions (TF, PE_SHORT) still open after the final day's EOD.
        """
        import pandas as pd
        last_bar_ts = last_ctx.bar_ts
        last_day    = last_ctx.day
        day_stocks  = last_ctx.day_stocks
        market_data = last_ctx.market_data

        for trade_id in list(self._open_positions):
            trade = self._open_positions[trade_id]
            ticker = trade.ticker
            # Engine: uses market_data[ticker][normalize == last_day].iloc[-1]["close"]
            if ticker in day_stocks and not day_stocks[ticker].empty:
                _px = float(day_stocks[ticker].iloc[-1]["close"])
            elif ticker in market_data:
                _day_bars = market_data[ticker][
                    market_data[ticker].index.normalize() == last_day
                ]
                _px = float(_day_bars.iloc[-1]["close"]) if not _day_bars.empty else trade.entry_price
            else:
                _px = trade.entry_price
            multiplier  = 1 if trade.direction == "LONG" else -1
            gross_pnl   = multiplier * (_px - trade.entry_price) * trade.shares
            total_costs = self._cost_fn(trade, _px) if self._cost_fn else 0.0
            trade.exit_time   = last_bar_ts
            trade.exit_price  = _px
            trade.exit_reason = "END_OF_PERIOD"
            trade.gross_pnl   = gross_pnl
            trade.total_costs = total_costs
            trade.net_pnl     = gross_pnl - total_costs
            self._running_equity += trade.net_pnl
            self._daily_pnl     += gross_pnl
            self._swing_state.pop(id(trade), None)
            del self._open_positions[trade_id]
            self._closed_trades.append(trade)
            # Engine uses _close_trade → record_trade_result (updates consecutive-loss CB)
            cb_res = self._cb.record_trade_result(trade.net_pnl or 0.0)
            if cb_res.kill_switch:
                self._cb_active = True

    def _close_all_cb(self, bar_ts: Any, bar_day: Any, day_stocks: Any) -> None:
        """Force-close all eligible positions at last-bar close with reason CIRCUIT_BREAKER.

        Mirrors engine_refactored._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER"):
        - exit price = day_stocks[ticker].iloc[-1]["close"]  (last bar of day = 15:55)
        - stop-cap applied if stop was breached on that bar
        - PE_SHORT entered the same day is excluded (same as engine)
        - Does NOT go through broker (engine's _close_all bypasses broker too)
        - Does NOT call record_trade_result (engine's _close_all doesn't call _close_trade)
        """
        import pandas as pd
        for trade_id in list(self._open_positions):
            trade = self._open_positions[trade_id]
            # PE_SHORT entered same day: excluded (engine exclusion condition)
            if (trade.strategy == "PE_SHORT"
                    and pd.Timestamp(trade.entry_time).normalize() == bar_day):
                continue
            if trade.ticker in day_stocks and not day_stocks[trade.ticker].empty:
                _bar = day_stocks[trade.ticker].iloc[-1]
                _px  = float(_bar["close"])
                # Stop-cap: prevent close worse than stop (engine _close_all lines 1436-1440)
                if trade.stop is not None:
                    if trade.direction == "LONG" and float(_bar["low"]) <= trade.stop:
                        _px = max(_px, trade.stop)
                    elif trade.direction == "SHORT" and float(_bar["high"]) >= trade.stop:
                        _px = min(_px, trade.stop)
            else:
                _px = trade.entry_price
            multiplier  = 1 if trade.direction == "LONG" else -1
            gross_pnl   = multiplier * (_px - trade.entry_price) * trade.shares
            total_costs = self._cost_fn(trade, _px) if self._cost_fn else 0.0
            trade.exit_time   = bar_ts
            trade.exit_price  = _px
            trade.exit_reason = "CIRCUIT_BREAKER"
            trade.gross_pnl   = gross_pnl
            trade.total_costs = total_costs
            trade.net_pnl     = gross_pnl - total_costs
            self._running_equity += trade.net_pnl
            self._daily_pnl     += gross_pnl
            self._swing_state.pop(id(trade), None)
            del self._open_positions[trade_id]
            self._closed_trades.append(trade)

    def _update_swing_stops(
        self,
        day: Any,
        market_data: Any,
        day_stocks: Any,
    ) -> None:
        """EOD chandelier trailing-stop update for open TREND_FOLLOW swing positions.

        Mirrors engine_refactored._update_swing_stops() exactly:
        - daily ATR recomputed each day (using bars BEFORE `day` midnight)
        - running extreme (highest high / lowest low) tracked in _swing_state
        - stop advances in the trade's favour; never retreats
        """
        import pandas as pd
        for trade in list(self._open_positions.values()):
            if trade.strategy != "TREND_FOLLOW":
                continue
            ticker = trade.ticker
            if ticker not in day_stocks or day_stocks[ticker].empty:
                continue

            day_high  = float(day_stocks[ticker]["high"].max())
            day_low   = float(day_stocks[ticker]["low"].min())
            daily_atr = self._compute_daily_atr(market_data, ticker, day)
            if daily_atr <= 0:
                continue

            state = self._swing_state.get(id(trade), {})

            if trade.direction == "LONG":
                prev_extreme = state.get("extreme", day_high)
                new_extreme  = max(prev_extreme, day_high)
                new_stop     = round(new_extreme - 3.0 * daily_atr, 2)
                if new_stop > (trade.stop or 0.0):
                    trade.stop = new_stop
            else:
                prev_extreme = state.get("extreme", day_low)
                new_extreme  = min(prev_extreme, day_low)
                new_stop     = round(new_extreme + 3.0 * daily_atr, 2)
                if new_stop < (trade.stop or float("inf")):
                    trade.stop = new_stop

            state["extreme"] = new_extreme
            self._swing_state[id(trade)] = state

    @staticmethod
    def _compute_daily_atr(
        market_data: Any,
        ticker: str,
        as_of: Any,
        period: int = 14,
    ) -> float:
        """14-period ATR from daily bars strictly before `as_of`.

        Mirrors engine_refactored._compute_daily_atr() exactly.
        """
        import pandas as pd
        if ticker not in market_data:
            return 0.0
        try:
            df = market_data[ticker]
            daily = df.loc[df.index < as_of].resample("B").agg({
                "open":  "first",
                "high":  "max",
                "low":   "min",
                "close": "last",
            }).dropna()

            if len(daily) < period + 1:
                last_close = float(df.loc[df.index < as_of]["close"].iloc[-1])
                return last_close * 0.01

            hl  = daily["high"] - daily["low"]
            hpc = (daily["high"] - daily["close"].shift(1)).abs()
            lpc = (daily["low"]  - daily["close"].shift(1)).abs()
            tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
            return float(tr.tail(period).mean())
        except Exception:
            return 0.0

    def _check_max_hold(self, bar_day: Any, ctx: Any) -> None:
        """Force-close TREND_FOLLOW positions held >= max_hold_days calendar days.

        Mirrors engine_refactored._run_day() lines 615-632:
        - exit price = first bar's open of the expiry day
        - exit_time  = ctx.bar_ts (first bar of day == engine's day_spy.index[0])
        - only fires when allow_swing_hold is True
        """
        if not self._allow_swing_hold:
            return
        import pandas as pd
        for trade_id in list(self._open_positions):
            trade = self._open_positions[trade_id]
            if trade.strategy != "TREND_FOLLOW":
                continue
            _hold = (bar_day - pd.Timestamp(trade.entry_time).normalize()).days
            if _hold < self._max_hold_days:
                continue
            if trade.ticker in ctx.day_stocks and not ctx.day_stocks[trade.ticker].empty:
                _exit_px = float(ctx.day_stocks[trade.ticker].iloc[0]["open"])
            else:
                _exit_px = trade.entry_price
            multiplier  = 1 if trade.direction == "LONG" else -1
            gross_pnl   = multiplier * (_exit_px - trade.entry_price) * trade.shares
            total_costs = self._cost_fn(trade, _exit_px) if self._cost_fn else 0.0
            trade.exit_time   = ctx.bar_ts
            trade.exit_price  = _exit_px
            trade.exit_reason = "MAX_HOLD"
            trade.gross_pnl   = gross_pnl
            trade.total_costs = total_costs
            trade.net_pnl     = gross_pnl - total_costs
            self._daily_pnl      += gross_pnl
            self._running_equity += trade.net_pnl
            self._swing_state.pop(id(trade), None)
            del self._open_positions[trade_id]
            self._closed_trades.append(trade)
            # Consecutive-loss CB (mirrors engine._close_trade → record_trade_result)
            cb_res = self._cb.record_trade_result(trade.net_pnl or 0.0)
            if cb_res.kill_switch:
                self._cb_active = True

    def _kill_switch_triggered(self, bar_ts: Any, result: RunResult) -> bool:
        if self._equity <= 0:
            return False
        loss_pct = -self._daily_pnl / self._equity
        if loss_pct >= self._kill_switch_pct:
            result.kill_switch_tripped = True
            result.kill_switch_bar = bar_ts
            logger.warning(
                "KILL_SWITCH tripped at %s: daily P&L $%.2f (%.1f%% of equity)",
                bar_ts, self._daily_pnl, loss_pct * 100,
            )
            return True
        return False


# ── Helper ────────────────────────────────────────────────────────────────────

def _intent_to_trade(
    intent: EntryIntent, order: Order, bar_ts: Any, use_filled_qty: bool = False
) -> Trade:
    """Convert EntryIntent + filled Order → a Trade in the simulated portfolio.

    entry_time is set to bar_ts (not the broker fill timestamp) so it matches
    the engine's convention: engine.trade_log.open_trade(entry_time=bar_ts).
    """
    qty = order.filled_qty if use_filled_qty else intent.shares
    return Trade(
        trade_id=order.order_id,
        ticker=intent.ticker,
        strategy=intent.strategy,
        direction=intent.direction,
        entry_time=bar_ts,
        entry_price=order.fill_price,
        shares=qty,
        stop=intent.stop,
        target=intent.target,
        hmm_state=intent.hmm_state,
        limiting_factor=intent.limiting_factor,
    )
