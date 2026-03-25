"""
raits/backtest/equity_tracker.py
Tracks account equity bar-by-bar. Used by BacktestEngine.
"""

from __future__ import annotations
from datetime import datetime
from typing import List, Tuple
import pandas as pd


class EquityTracker:
    """
    Maintains the running equity value throughout a backtest.

    Design rules:
    - Only realized P&L (closed trades) updates equity. Mark-to-market
      on open positions is NOT tracked — keeps the engine simple and
      prevents look-ahead bias in metrics.
    - Records are kept as (timestamp, equity) pairs and converted to a
      pd.Series on request.
    - new_session() must be called at the start of each trading day to
      anchor the daily drawdown calculation.
    """

    def __init__(self, initial_equity: float):
        if initial_equity <= 0:
            raise ValueError(f"initial_equity must be positive, got {initial_equity}")
        self._initial = initial_equity
        self._equity = initial_equity
        self._session_start = initial_equity
        self._records: List[Tuple[datetime, float]] = []
        self._session_pdt_blocks = 0

    # ── Session control ───────────────────────────────────────────────────────

    def new_session(self, timestamp: datetime) -> None:
        """Call at the start of each trading day."""
        self._session_start = self._equity
        self._session_pdt_blocks = 0
        self._records.append((timestamp, self._equity))

    # ── P&L application ───────────────────────────────────────────────────────

    def apply_pnl(self, net_pnl: float, timestamp: datetime) -> None:
        """Apply realized net P&L (after costs) from a closed trade."""
        self._equity += net_pnl
        self._records.append((timestamp, self._equity))

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def initial_equity(self) -> float:
        return self._initial

    @property
    def session_start_equity(self) -> float:
        return self._session_start

    @property
    def daily_pnl_pct(self) -> float:
        """Current session P&L as a fraction of session-start equity."""
        if self._session_start <= 0:
            return 0.0
        return (self._equity - self._session_start) / self._session_start

    @property
    def total_return_pct(self) -> float:
        return (self._equity - self._initial) / self._initial

    # ── Output ────────────────────────────────────────────────────────────────

    def get_equity_curve(self) -> pd.Series:
        """
        Return the equity curve as a pd.Series.
        Index is DatetimeIndex; values are equity at each recorded point.
        Deduplicated by keeping the last value at each timestamp.
        """
        if not self._records:
            return pd.Series(dtype=float, name="equity")
        timestamps, values = zip(*self._records)
        s = pd.Series(list(values), index=pd.DatetimeIndex(list(timestamps)), name="equity")
        # Keep last value at each timestamp (multiple trades can close in same bar)
        return s.groupby(s.index).last()
