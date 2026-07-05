"""
raits/decision/types.py
Shared data types for the DecisionUnit interface.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import time as dtime
from typing import Any, Dict, List, Optional
import pandas as pd


@dataclass
class EntryIntent:
    """An intended trade entry returned by DecisionUnit.decide()."""
    ticker: str
    strategy: str
    direction: str          # LONG | SHORT
    entry_price: float
    shares: int
    stop: float
    target: float
    is_day_trade: bool
    limiting_factor: str
    hmm_state: str
    # GAP_FILL / GF_SHORT trailing stop seed — engine stores this after open_trade
    gf_stop_dist: Optional[float] = None


@dataclass
class ExitIntent:
    """An intended trade exit returned by DecisionUnit.decide()."""
    trade: Any          # raits.backtest.data_types.Trade
    exit_price: float
    reason: str         # STOP_HIT | TARGET_HIT | TIME_STOP | EOD | SAFETY_MODE


@dataclass
class DecisionResult:
    """Output of DecisionUnit.decide() for one bar."""
    entries: List[EntryIntent] = field(default_factory=list)
    exits: List[ExitIntent] = field(default_factory=list)
    override_active: bool = False   # True = SAFETY_MODE triggered this bar


@dataclass
class BarContext:
    """All inputs needed by DecisionUnit.decide() for one 5-min bar."""
    # Current bar
    bar_ts: pd.Timestamp
    spy_bar: pd.Series
    spy_history: List[pd.Series]        # all SPY bars today so far (including current)

    # Data
    day_stocks: Dict[str, pd.DataFrame] # ticker → bars up to bar_ts
    market_data: Dict[str, pd.DataFrame]# ticker → full history (for ATR lookups)

    # Open positions — decide() may mutate .stop in-place for trailing stops
    open_trades: List[Any]              # List[Trade]

    # Regime
    hmm_state: str
    cur_vol: float                      # SPY 5-day realized vol (annualized)

    # Day-level context
    day: pd.Timestamp
    orb_vix_ok: bool
    stress_orb_vix_ok: bool

    # Universes (pre-computed by engine once per day)
    effective_orb_universe: List[str]
    effective_vwap_universe: List[str]
    effective_fade_universe: List[str]
    all_tickers: List[str]
    base_universe: List[str]
    stress_stocks: Dict[str, pd.DataFrame]

    # SPY pre-computed daily info
    spy_or_high: Optional[float]        # SPY OR high 9:30-9:44
    spy_or_low: Optional[float]
    spy_bull_trend: bool                # SMA50 > SMA200
    daily_spy_close: pd.Series          # daily closes up to yesterday

    # Earnings calendar
    pe_short_calendar: Dict[Any, List[str]]  # date → [tickers]

    # FADE ATR filter
    fade_atr_top2: set

    # Config values needed in decide()
    vwap_bb_std: float
    ema_period: int
    vwap_mr_vol_threshold: float
    allow_swing_hold: bool
    enable_pdt_guard: bool
    stress_size_fraction: float
    orb_signal_start: dtime
    orb_signal_end: dtime

    # Regime reliability flag — set by the live feed when daily_data["SPY"] is
    # hard-stale (> _HARD_STALE_SPY_BDAYS behind).  When True, PaperTrader blocks
    # new entries but keeps normal exit logic (stops/targets are pre-committed and
    # HMM-independent).  Always False in backtest / replay.
    regime_unreliable: bool = False
