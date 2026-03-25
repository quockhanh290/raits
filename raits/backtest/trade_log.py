"""
raits/backtest/trade_log.py
Maintains the ordered list of all trades and provides querying helpers
used by the engine's position-limit and circuit-breaker logic.
"""

from __future__ import annotations
import uuid
from datetime import datetime
from typing import List, Optional, Set

from .data_types import Trade


class TradeLog:
    """
    Single source of truth for all trades in a backtest run.

    Key queries the engine uses on every bar:
    - open_tickers()          → set of tickers already in a position
    - total_open_count()      → for the global 5-position cap
    - open_count_by_strategy()→ for per-strategy caps (ORB≤2, VWAP≤3, TREND≤2)
    - consecutive_losses()    → circuit breaker trigger (≥5 consecutive)
    """

    def __init__(self):
        self._trades: List[Trade] = []

    # ── Opening / closing ─────────────────────────────────────────────────────

    def open_trade(
        self,
        *,
        ticker: str,
        strategy: str,
        direction: str,
        entry_time: datetime,
        entry_price: float,
        shares: int,
        stop: float,
        target: float,
        hmm_state: str,
        limiting_factor: str,
    ) -> Trade:
        trade = Trade(
            trade_id=str(uuid.uuid4())[:8],
            ticker=ticker,
            strategy=strategy,
            direction=direction,
            entry_time=entry_time,
            entry_price=entry_price,
            shares=shares,
            stop=stop,
            target=target,
            hmm_state=hmm_state,
            limiting_factor=limiting_factor,
        )
        self._trades.append(trade)
        return trade

    def close_trade(
        self,
        trade: Trade,
        *,
        exit_time: datetime,
        exit_price: float,
        exit_reason: str,
        total_costs: float = 0.0,
    ) -> Trade:
        """Populate all exit fields and compute P&L."""
        trade.exit_time = exit_time
        trade.exit_price = exit_price
        trade.exit_reason = exit_reason
        trade.total_costs = total_costs

        multiplier = 1 if trade.direction == "LONG" else -1
        trade.gross_pnl = multiplier * (exit_price - trade.entry_price) * trade.shares
        trade.net_pnl = trade.gross_pnl - total_costs
        return trade

    # ── Open-position queries (called every bar) ──────────────────────────────

    @property
    def open_trades(self) -> List[Trade]:
        return [t for t in self._trades if t.is_open]

    def open_tickers(self) -> Set[str]:
        return {t.ticker for t in self.open_trades}

    def total_open_count(self) -> int:
        return sum(1 for t in self._trades if t.is_open)

    def open_count_by_strategy(self, strategy: str) -> int:
        return sum(1 for t in self._trades if t.is_open and t.strategy == strategy)

    # ── Closed-trade queries ──────────────────────────────────────────────────

    @property
    def closed_trades(self) -> List[Trade]:
        return [t for t in self._trades if not t.is_open]

    def consecutive_losses(self) -> int:
        """
        Count consecutive net losses counting backward from the most recent
        closed trade. Used by CircuitBreakers to trigger the ≥5-loss halt.
        """
        count = 0
        for trade in reversed(self.closed_trades):
            if trade.net_pnl is not None and trade.net_pnl < 0:
                count += 1
            else:
                break
        return count

    def all_trades(self) -> List[Trade]:
        return list(self._trades)

    def trades_on_date(self, date) -> List[Trade]:
        return [t for t in self._trades if t.entry_time.date() == date]
