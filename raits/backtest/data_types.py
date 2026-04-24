"""
raits/backtest/data_types.py
Shared dataclasses for the Week 18 backtest engine.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import pandas as pd


# ── Trade ────────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    """Single trade lifecycle — open to close."""
    trade_id: str
    ticker: str
    strategy: str           # ORB | VWAP_MR | TREND_FOLLOW
    direction: str          # LONG | SHORT
    entry_time: datetime
    entry_price: float
    shares: int
    stop: float
    target: float
    hmm_state: str          # Calm | Normal | Stress at entry
    limiting_factor: str    # KELLY | VOL_TARGET | POSITION_LIMIT

    # Set on close
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    # TARGET_HIT | STOP_HIT | TIME_STOP | EOD | SAFETY_MODE | CIRCUIT_BREAKER
    exit_reason: Optional[str] = None
    gross_pnl: Optional[float] = None
    total_costs: Optional[float] = None
    net_pnl: Optional[float] = None

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def is_winner(self) -> bool:
        return self.net_pnl is not None and self.net_pnl > 0


# ── Backtest configuration ────────────────────────────────────────────────────

@dataclass
class BacktestConfig:
    """
    All parameters for a single backtest run.
    The three WFO-optimized hyperparameters live here — this is the object
    that changes between WFO windows in Week 19.
    """
    account_equity: float = 25_000.0
    start_date: str = "2022-01-03"
    end_date: str = "2022-03-31"
    universe: List[str] = field(
        default_factory=lambda: ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]
    )
    # ORB-specific universe — volatile gappers only.
    # If empty, falls back to full universe (old behaviour).
    orb_universe: List[str] = field(default_factory=list)

    # The 3 WFO-optimized hyperparameters (Section 7.1)
    orb_range_minutes: int = 15    # 10 | 15 | 20
    vwap_bb_std: float = 2.0       # 1.5 | 2.0 | 2.5
    ema_period: int = 30           # 20 | 30 | 50

    # Fixed parameters (never optimized per blueprint)
    atr_stop_multiplier: float = 3.0
    risk_per_trade_pct: float = 0.01     # 1% of equity
    max_position_pct: float = 0.20       # 20% of equity
    kelly_fraction: float = 0.5          # Half-Kelly

    # Feature flags
    enable_costs: bool = True
    enable_pdt_guard: bool = True
    hmm_retrain_weekly: bool = True
    log_level: str = "INFO"
    bar_size_minutes: int = 5


# ── Session and result ────────────────────────────────────────────────────────

@dataclass
class SessionSummary:
    """One trading day's summary."""
    date: datetime
    starting_equity: float
    ending_equity: float
    day_trades: List[Trade] = field(default_factory=list)
    regime_bar_counts: Dict[str, int] = field(
        default_factory=lambda: {"Calm": 0, "Normal": 0, "Stress": 0}
    )
    circuit_breaker_fired: bool = False
    pdt_blocks: int = 0
    safety_mode_bars: int = 0

    @property
    def daily_pnl(self) -> float:
        return self.ending_equity - self.starting_equity

    @property
    def daily_pnl_pct(self) -> float:
        if self.starting_equity <= 0:
            return 0.0
        return self.daily_pnl / self.starting_equity


@dataclass
class BacktestResult:
    """Complete output from a single backtest run."""
    config: BacktestConfig
    equity_curve: pd.Series          # DatetimeIndex → equity value
    trade_log: List[Trade]
    session_summaries: List[SessionSummary]
    metrics: Dict[str, Any]
    regime_breakdown: Dict[str, Dict[str, Any]]

    def summary(self) -> str:
        m = self.metrics
        lines = [
            "=" * 60,
            "RAITS Backtest Result",
            f"  Period:        {self.config.start_date} → {self.config.end_date}",
            f"  Total trades:  {m.get('total_trades', 0)}",
            f"  Win rate:      {m.get('win_rate', 0):.1%}",
            f"  Profit factor: {m.get('profit_factor', 0):.2f}",
            f"  Calmar ratio:  {m.get('calmar_ratio', 0):.2f}",
            f"  Sharpe ratio:  {m.get('sharpe_ratio', 0):.2f}",
            f"  Max drawdown:  {m.get('max_drawdown', 0):.1%}",
            f"  Total return:  {m.get('total_return', 0):.1%}",
            f"  Total costs:   ${m.get('total_costs', 0):.2f}",
            "=" * 60,
        ]
        return "\n".join(lines)
