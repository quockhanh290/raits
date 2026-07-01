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

from .broker import BrokerInterface, FillStatus, Order
from .reconciliation import ReconciliationLog

logger = logging.getLogger("RAITS.live.runner")

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

    @property
    def closed_trades(self) -> List[Trade]:
        return list(self._closed_trades)

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self, feed: ContextFeed) -> RunResult:
        """Run the full paper-trading loop over the feed."""
        result = RunResult()
        current_day = None

        for ctx in feed:
            bar_day = ctx.bar_ts.normalize()

            # Day reset
            if bar_day != current_day:
                current_day = bar_day
                self._daily_pnl = 0.0
                # MAX_HOLD: mirrors engine_refactored._run_day() day-start block (lines 615-632)
                # Must run before reset_day() and before open_trades injection into ctx
                self._check_max_hold(bar_day, ctx)
                self._du.reset_day(bar_day, ctx.orb_signal_start, ctx.orb_signal_end)

            # Kill-switch check (before decide)
            if self._kill_switch_triggered(ctx.bar_ts, result):
                break

            # Inject open positions into ctx so DecisionUnit can exit them
            ctx.open_trades = list(self._open_positions.values())

            # Mirror engine behavior: swing trade tickers must be in day_stocks
            # even if today's universe scan dropped them, so exit checks work.
            for _trade in ctx.open_trades:
                _tk = _trade.ticker
                if (_tk not in ctx.day_stocks and _tk != "SPY"
                        and _tk in ctx.market_data):
                    _day_bars = ctx.market_data[_tk][
                        ctx.market_data[_tk].index.normalize() == ctx.day
                    ]
                    if not _day_bars.empty:
                        ctx.day_stocks[_tk] = _day_bars

            # === DecisionUnit call (read-only) ===
            decision: DecisionResult = self._du.decide(ctx)

            result.bars_processed += 1
            result.entries_signalled += len(decision.entries)
            result.exits_signalled   += len(decision.exits)

            # Process exits first (free up capital)
            for exit_intent in decision.exits:
                self._process_exit(exit_intent, ctx.bar_ts, result)

            # Then entries
            for entry_intent in decision.entries:
                self._process_entry(entry_intent, ctx.bar_ts, result)

        result.simulated_pnl = self._daily_pnl
        return result

    # ── Internal ──────────────────────────────────────────────────────────────

    def _process_entry(
        self, intent: EntryIntent, bar_ts: Any, result: RunResult
    ) -> None:
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
        elif filled_order.fill_status == FillStatus.PARTIAL:
            result.orders_partial += 1
            trade = _intent_to_trade(intent, filled_order, bar_ts, use_filled_qty=True)
            self._open_positions[trade.trade_id] = trade
            self._du.on_trade_opened(trade, intent)
        else:
            result.orders_rejected += 1

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

            self._daily_pnl += gross_pnl
            del self._open_positions[trade.trade_id]
            self._closed_trades.append(trade)
        else:
            result.orders_rejected += 1

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
            self._daily_pnl  += gross_pnl
            del self._open_positions[trade_id]
            self._closed_trades.append(trade)

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
