"""
raits/backtest/engine_refactored.py
RefactoredBacktestEngine: identical to BacktestEngine except _run_day's bar loop
delegates entry/exit decisions to DecisionUnit.decide().

NEVER modify engine.py — this is a parallel implementation.
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
from raits.strategies.universe_scanner import DailyUniverseScanner, MRUniverseScanner, ORBUniverseScanner, ORBFadeUniverseScanner
from raits.decision.decision_unit import DecisionUnit
from raits.decision.types import BarContext

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
GAP_FILL_ENTRY    = dtime(10, 30)
GAP_FILL_EXIT     = dtime(13, 30)
RS_SHORT_ENTRY    = dtime(10, 30)
RS_SHORT_EXIT     = dtime(12, 30)
RS_SHORT_ALPHA    = 0.02   # ≥2% underperformance vs SPY required
STRESS_MID_ENTRY     = dtime(10, 15)   # same bar as ORB_SIGNAL_END
STRESS_MID_EXIT      = dtime(14, 0)    # hand off to TREND_FOLLOW window
STRESS_MID_STOP_PAD  = 0.001           # 0.1% above swing high
STRESS_MID_MAX_STOP  = 0.015           # reject if stop > 1.5% of entry
RS_SHORT_ATR_MULT = 1.5    # stop = entry + 1.5×ATR

# ── POST_EARNINGS_SHORT ───────────────────────────────────────────────────────
PE_SHORT_GAP_MIN   = 0.05   # ≥5% gap-down required
PE_SHORT_STOP_MULT = 1.5    # stop = 1.5×ATR14 above entry
PE_SHORT_TARGET_RR = 2.0    # target = 2×stop_dist below entry (2:1 RR)
MAX_PE_SHORT       = 2

PE_SHORT_UNIVERSE = [
    # Existing 37-stock pool (5-min data already in pkl)
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD",
    "QCOM", "INTC", "MU", "AVGO", "TXN", "AMAT",
    "ADBE", "CRM", "ORCL", "INTU", "CSCO",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX",
    "COST", "SBUX", "NFLX", "EBAY",
    "JPM", "GS", "MS", "V", "MA",
    "HON", "MMM",
    "XOM", "CVX",
    # Expansion (Phase 2 — skipped until 5-min data is fetched)
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C",
    "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP",
    "CAT", "DE", "BA", "GE",
    "PYPL", "PANW", "NOW",
]

# ── Position limits ───────────────────────────────────────────────────────────
MAX_TOTAL     = 8
MAX_ORB       = 2
MAX_FADE      = 5
MAX_VWAP      = 3
MAX_TREND     = 3
MAX_GAP_FILL  = 3
MAX_GF_SHORT  = 3
MAX_RS_SHORT  = 2
STRATEGY_CAPS = {
    "ORB": MAX_ORB, "FADE": MAX_FADE, "VWAP_MR": MAX_VWAP,
    "TREND_FOLLOW": MAX_TREND, "STRESS_ORB": 2, "STRESS_MID": 2,
    "GAP_FILL": MAX_GAP_FILL, "GF_SHORT": MAX_GF_SHORT, "RS_SHORT": MAX_RS_SHORT,
    "PE_SHORT": MAX_PE_SHORT,
}

# ── Regime → active strategies (from each strategy's allowed_regimes config) ──
_REGIME_STRATEGIES: Dict[str, List[str]] = {
    "Calm":   ["PE_SHORT"],
    "Normal": ["ORB", "TREND_FOLLOW", "GF_SHORT", "PE_SHORT"],
    "Stress": ["TREND_FOLLOW", "STRESS_ORB", "STRESS_MID", "PE_SHORT"],
    "Crisis": ["PE_SHORT"],
}

# ETFs used for Stress-regime ORB (broad market proxies, always liquid)
_ETF_STRESS_UNIVERSE = ["SPY", "QQQ", "IWM"]


# ── Strategy stats for PositionSizer ─────────────────────────────────────────
# WFO-observed win rate 52.3%; 2:1 R:R is the target structure (stop × 2 = target).
STRATEGY_STATS = {
    "ORB":            {"win_rate": 0.62, "avg_win": 4.50, "avg_loss": 2.00},
    "FADE":           {"win_rate": 0.45, "avg_win": 3.00, "avg_loss": 2.00},
    "VWAP_MR":        {"win_rate": 0.42, "avg_win": 2.80, "avg_loss": 1.50},
    "TREND_FOLLOW":   {"win_rate": 0.52, "avg_win": 2.00, "avg_loss": 1.00},
    "GAP_FILL":       {"win_rate": 0.78, "avg_win": 3.00, "avg_loss": 1.50},
    "GF_SHORT":       {"win_rate": 0.40, "avg_win": 3.00, "avg_loss": 1.50},
    "RS_SHORT":       {"win_rate": 0.42, "avg_win": 2.50, "avg_loss": 1.50},
    "STRESS_MID":     {"win_rate": 0.66, "avg_win": 2.00, "avg_loss": 1.00},
    "PE_SHORT":       {"win_rate": 0.72, "avg_win": 2.00, "avg_loss": 1.00},
}


class RefactoredBacktestEngine:

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
        self._regime_bar_counts: Dict[str, int] = {"Calm": 0, "Normal": 0, "Stress": 0, "Crisis": 0}
        self._swing_state: Dict[int, dict] = {}  # id(trade) → {extreme, hold_days}
        # _tf_cooldown removed — now owned by DecisionUnit
        self._decision_unit: Optional[DecisionUnit] = None
        self._pe_short_calendar: Dict[pd.Timestamp, List[str]] = {}  # date → [tickers with earnings]
        # Read-only capture hook for context verification — no logic change.
        # Set to a callable(BarContext) to record every ctx before decide().
        self._ctx_capture_hook = None
        self._mods = self._load_modules()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run(
        self,
        market_data: Dict[str, pd.DataFrame],
        daily_data: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> BacktestResult:
        if "SPY" not in market_data:
            raise ValueError("market_data must contain 'SPY'.")

        spy_data = market_data["SPY"]

        def to_daily_close(bars: pd.DataFrame) -> pd.Series:
            return bars["close"].resample("B").last().dropna()

        HMMEngine        = self._mods["HMMEngine"]
        pdt_guard        = self._mods["PDTGuard"]()
        circuit_breakers = self._mods["CircuitBreakers"]()
        position_sizer   = self._mods["PositionSizer"](
            account_equity=self.config.account_equity,
            max_risk_pct=self.config.max_risk_pct,
            max_position_pct=self.config.max_position_pct,
            kelly_fraction=self.config.kelly_fraction,
        )
        coordinator      = self._mods["RegimeCoordinator"]()
        # Pass WFO-optimised hyperparameters to each strategy
        # Lower opening volume multiplier from 2.0 to 1.2
        # Blueprint default of 2.0 excludes normally high-volume stocks like NVDA/TSLA
        # 1.2x still confirms above-average participation without over-filtering
        orb     = self._mods["ORBStrategy"](config={
            "opening_vol_multiplier": 1.2,
            "min_price": 1.0,      # universe is pre-screened; disable penny-stock filter
            "max_price": 1e9,      # split-adjusted prices vary; disable price cap
            "min_gap_pct": 0.01,   # 1% gap (vs default 2%) — large-caps gap less
        })
        # Stress-regime ORB: trades SPY/QQQ/IWM only, no gap requirement.
        # Direction filter (bear/bull) is applied by the engine after signal generation.
        stress_orb = self._mods["ORBStrategy"](config={
            "allowed_regimes":        ["Stress"],
            "min_gap_pct":            0.0,    # ETFs don't need gap catalyst
            "rvol_threshold":         0.0,    # ETFs always liquid — bypass RVOL gate
            "min_price":              1.0,
            "max_price":              1e9,
            "min_range_atr_multiple": 0.2,    # more permissive OR range for ETFs
        })
        # FADE strategy: relaxed RVol — high vol = momentum = bad for fade.
        # Uses ORBFadeUniverseScanner universe which selects mean-reverting stocks.
        fade_orb = self._mods["ORBStrategy"](config={
            "opening_vol_multiplier": 1.2,
            "min_price":              1.0,
            "max_price":              1e9,
            "min_gap_pct":            0.0,   # FADE doesn't require a gap — OR breakout is the signal
            "rvol_threshold":         0.0,   # FADE fades weak breakouts — no min-rvol gate
            "fade_require_midpoint":  False,
            "fade_long_enabled":      True,  # LONG FADE filtered by ATR% rank at entry (Scenario G)
        })
        vwap_mr = self._mods["VWAPMRStrategy"](
            config={"bb_std_dev": self.config.vwap_bb_std}
        )
        trend   = self._mods["TrendStrategy"](
            config={"ema_period": self.config.ema_period}
        )

        # Dynamic ORB timing from config (WFO optimizes this)
        from datetime import datetime as _dt, timedelta as _td
        _base = _dt(2000, 1, 1, 9, 30)
        _sig_start = _base + _td(minutes=self.config.orb_range_minutes)
        _sig_end   = _sig_start + _td(minutes=30)
        orb_signal_start = _sig_start.time()
        orb_signal_end   = _sig_end.time()

        # Construct DecisionUnit with all strategy/risk instances
        self._decision_unit = DecisionUnit(
            config=self.config,
            orb=orb,
            stress_orb=stress_orb,
            fade_orb=fade_orb,
            vwap_mr=vwap_mr,
            trend=trend,
            coordinator=coordinator,
            position_sizer=position_sizer,
            pdt_guard=pdt_guard,
        )

        hmm = HMMEngine()
        logger.info("Training HMM...")
        try:
            # Prefer SPY historical daily (2007-2024) so HMM sees 2008 GFC and
            # 2020 COVID for proper Crisis state calibration.  Falls back to the
            # Polygon 5-min data resampled to daily (starts 2017) if the file is
            # not present — run raits/scripts/fetch_spy_historical.py first.
            _hist_path = os.path.join(
                os.path.dirname(__file__), "..", "data", "cache", "daily",
                "SPY_daily_2007_2024.parquet",
            )
            _hist_path = os.path.normpath(_hist_path)
            if os.path.exists(_hist_path):
                _spy_hist = pd.read_parquet(_hist_path)
                _spy_hist.index = pd.DatetimeIndex(_spy_hist.index)
                _spy_hist_close = _spy_hist["close"].sort_index()
                # Slice to data before backtest start to avoid lookahead.
                _bt_start = pd.Timestamp(min(market_data["SPY"].index.normalize()))
                _spy_hist_close = _spy_hist_close[_spy_hist_close.index < _bt_start]
                if len(_spy_hist_close) >= 50:
                    logger.info(
                        "HMM initial fit: SPY historical daily (%d days, %s–%s)",
                        len(_spy_hist_close),
                        _spy_hist_close.index[0].date(),
                        _spy_hist_close.index[-1].date(),
                    )
                    hmm.fit(_spy_hist_close)
                else:
                    logger.info("HMM initial fit: SPY historical file short — using Polygon 5-min resample")
                    hmm.fit(to_daily_close(spy_data))
            else:
                logger.info(
                    "SPY_daily_2007_2024.parquet not found — using Polygon 5-min resample. "
                    "Run raits/scripts/fetch_spy_historical.py for better HMM calibration."
                )
                hmm.fit(to_daily_close(spy_data))
            logger.info("HMM trained.")
        except Exception as e:
            logger.warning(f"HMM fit failed ({e}) — using default regime Normal")
            hmm = None

        # Load PE_SHORT earnings calendar (8-K filing dates from Polygon).
        # filing_date == reaction day open (BMO same day; AMC next morning).
        # Tickers missing 5-min data are skipped silently at entry time.
        import json as _json
        _earnings_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "data", "cache",
            "earnings_dates_expanded.json",
        ))
        self._pe_short_calendar = {}
        if os.path.exists(_earnings_path):
            with open(_earnings_path) as _ef:
                _raw_earnings = _json.load(_ef)
            for _tk, _dates in _raw_earnings.items():
                for _d in _dates:
                    _ts = pd.Timestamp(_d)
                    self._pe_short_calendar.setdefault(_ts, []).append(_tk)
            logger.info(
                "PE_SHORT calendar loaded: %d ticker-dates from %s",
                sum(len(v) for v in self._pe_short_calendar.values()),
                os.path.basename(_earnings_path),
            )
        else:
            logger.info("PE_SHORT calendar not found at %s — PE_SHORT disabled", _earnings_path)

        # Load VIX daily closes for ORB/STRESS_ORB regime gates.
        # Run raits/scripts/fetch_vix_daily.py to populate this file.
        _vix_daily: dict = {}
        _vix_path = os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "data", "cache", "daily", "vix_daily.parquet"
        ))
        if os.path.exists(_vix_path):
            _vix_df = pd.read_parquet(_vix_path)
            _vix_df.index = pd.DatetimeIndex(_vix_df.index).normalize()
            _vix_daily = _vix_df["vix"].to_dict()
            logger.info("VIX daily loaded: %d days", len(_vix_daily))
        else:
            logger.info(
                "VIX daily not found at %s — VIX gates disabled (run fetch_vix_daily.py)",
                _vix_path,
            )
        _sorted_vix_dates = sorted(_vix_daily.keys())

        # Scanner: select dynamic universe from T-1 daily bars each day.
        # Only active when use_scanner=True AND daily_data is provided.
        scanner: Optional[DailyUniverseScanner] = None
        if self.config.use_scanner and daily_data is not None:
            scanner = DailyUniverseScanner(top_n=self.config.scanner_top_n)
            logger.info(f"DailyUniverseScanner active (top_n={self.config.scanner_top_n})")

        # MR scanner: separate daily scan for VWAP_MR using range-bound stocks.
        # Uses same daily_data as TF scanner. Falls back to config.vwap_universe.
        mr_scanner: Optional[MRUniverseScanner] = None
        if self.config.use_mr_scanner and daily_data is not None:
            mr_scanner = MRUniverseScanner(top_n=self.config.mr_scanner_top_n)
            logger.info(f"MRUniverseScanner active (top_n={self.config.mr_scanner_top_n})")

        # ORB scanner: selects high-ATR stocks for ORB. Falls back to config.orb_universe.
        orb_daily_scanner: Optional[ORBUniverseScanner] = None
        if self.config.use_orb_scanner and daily_data is not None:
            orb_daily_scanner = ORBUniverseScanner(top_n=self.config.orb_scanner_top_n)
            logger.info(f"ORBUniverseScanner active (top_n={self.config.orb_scanner_top_n})")

        # FADE scanner: selects mean-reverting stocks (high gap reversal rate).
        fade_daily_scanner: Optional[ORBFadeUniverseScanner] = None
        if self.config.use_fade_scanner and daily_data is not None:
            fade_daily_scanner = ORBFadeUniverseScanner(top_n=self.config.fade_scanner_top_n)
            logger.info(f"ORBFadeUniverseScanner active (top_n={self.config.fade_scanner_top_n})")

        all_days = pd.DatetimeIndex(spy_data.index.normalize().unique())
        all_days = all_days[
            (all_days >= pd.Timestamp(self.config.start_date))
            & (all_days <= pd.Timestamp(self.config.end_date))
        ]

        # Pre-build sorted list of all daily-data dates for fast T-1 lookup.
        # Needed by any scanner that does T-1 daily lookups.
        _any_scanner = any(s is not None for s in (scanner, mr_scanner, orb_daily_scanner, fade_daily_scanner))
        if _any_scanner and daily_data is not None:
            _spy_daily_dates = sorted(
                daily_data["SPY"].index.normalize().unique()
                if "SPY" in daily_data else []
            )
        else:
            _spy_daily_dates = []

        for day in all_days:
            # Determine today's universe via scanner (T-1 scan) or static config.
            if scanner is not None and _spy_daily_dates:
                # Find the last daily-data date strictly before today.
                _prev = [d for d in _spy_daily_dates if d < day.normalize()]
                if _prev:
                    day_universe = scanner.scan(daily_data, _prev[-1])
                    logger.debug(f"{day.date()} scanner universe: {day_universe}")
                else:
                    day_universe = list(self.config.universe)
            else:
                day_universe = None  # _run_day falls back to config.universe

            # MR universe: separate daily scan for VWAP_MR (range-bound stocks).
            if mr_scanner is not None and _spy_daily_dates:
                _prev_mr = [d for d in _spy_daily_dates if d < day.normalize()]
                mr_universe: Optional[List[str]] = mr_scanner.scan(daily_data, _prev_mr[-1]) if _prev_mr else None
            else:
                mr_universe = None  # _run_day falls back to config.vwap_universe

            # ORB universe: daily scan for high-ATR ORB candidates.
            if orb_daily_scanner is not None and _spy_daily_dates:
                _prev_orb = [d for d in _spy_daily_dates if d < day.normalize()]
                orb_scanned_universe: Optional[List[str]] = orb_daily_scanner.scan(daily_data, _prev_orb[-1]) if _prev_orb else None
            else:
                orb_scanned_universe = None  # _run_day falls back to config.orb_universe

            # FADE universe: daily scan for mean-reverting FADE candidates.
            if fade_daily_scanner is not None and _spy_daily_dates:
                _prev_fade = [d for d in _spy_daily_dates if d < day.normalize()]
                fade_scanned_universe: Optional[List[str]] = fade_daily_scanner.scan(daily_data, _prev_fade[-1]) if _prev_fade else None
            else:
                fade_scanned_universe = None

            # FADE ATR% filter: compute top-2 highest-ATR% tickers for today.
            # LONG FADE on these tickers is blocked (high momentum = bad for fade).
            # Uses T-1 daily data; independent of scanner state.
            _fade_atr_top2: set = set()
            if daily_data is not None:
                _prev_d = [d for d in (
                    sorted(daily_data["SPY"].index.normalize().unique())
                    if "SPY" in daily_data else []
                ) if d < day.normalize()]
                if _prev_d:
                    _fade_atr_top2 = self._compute_fade_atr_top2(daily_data, _prev_d[-1])

            # VIX gate: use same-day close as proxy for intraday VIX at trade time.
            # (In production: use real-time intraday VIX at 9:30 ET instead.)
            _day_key = day.normalize()
            _day_vix: Optional[float] = float(_vix_daily[_day_key]) if _day_key in _vix_daily else None

            self._run_day(
                day=day,
                market_data=market_data,
                spy_data=spy_data,
                _hmm=hmm,
                to_daily_close=to_daily_close,
                circuit_breakers=circuit_breakers,
                position_sizer=position_sizer,
                coordinator=coordinator,
                orb=orb,
                stress_orb=stress_orb,
                fade_orb=fade_orb,
                vwap_mr=vwap_mr,
                trend=trend,
                orb_signal_start=orb_signal_start,
                orb_signal_end=orb_signal_end,
                day_universe=day_universe,
                mr_universe=mr_universe,
                orb_scanned_universe=orb_scanned_universe,
                fade_scanned_universe=fade_scanned_universe,
                fade_atr_top2=_fade_atr_top2,
                day_vix=_day_vix,
            )

            if self.config.hmm_retrain_weekly and day.weekday() == 0:
                if (self._last_retrain_date is None
                        or (day - self._last_retrain_date).days >= 7):
                    recent_spy = spy_data[spy_data.index.normalize() <= day]
                    daily_close = to_daily_close(recent_spy)
                    if hmm is not None and len(daily_close) >= 35:
                        try:
                            hmm.retrain(daily_close)
                        except Exception as e:
                            logger.debug(f"HMM retrain failed: {e}")
                    self._last_retrain_date = day

        # Force-close any positions still open at end of test period.
        # These arise when max_hold hasn't elapsed by the last calendar day.
        if self.trade_log.open_trades and all_days.size > 0:
            _last_day = all_days[-1]
            _last_spy = spy_data[spy_data.index.normalize() == _last_day]
            _last_ts  = _last_spy.index[-1] if not _last_spy.empty else pd.Timestamp(self.config.end_date)
            for _trade in list(self.trade_log.open_trades):
                _ticker = _trade.ticker
                _ticker_data = market_data.get(_ticker, pd.DataFrame())
                _day_bars = _ticker_data[_ticker_data.index.normalize() == _last_day] if not _ticker_data.empty else pd.DataFrame()
                _px = float(_day_bars.iloc[-1]["close"]) if not _day_bars.empty else _trade.entry_price
                self._close_trade(_trade, _last_ts, _px, "END_OF_PERIOD",
                                  circuit_breakers, coordinator,
                                  _last_ts.to_pydatetime())
                self._swing_state.pop(id(_trade), None)

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
        _hmm: Any,
        to_daily_close: Any,
        circuit_breakers: Any,
        position_sizer: Any,
        coordinator: Any,
        orb: Any,
        stress_orb: Any,
        fade_orb: Any,
        vwap_mr: Any,
        trend: Any,
        orb_signal_start: Any = None,
        orb_signal_end: Any = None,
        day_universe: Optional[List[str]] = None,
        mr_universe: Optional[List[str]] = None,
        orb_scanned_universe: Optional[List[str]] = None,
        fade_scanned_universe: Optional[List[str]] = None,
        fade_atr_top2: Optional[set] = None,
        day_vix: Optional[float] = None,
    ) -> None:
        # Use module-level defaults if not passed
        if orb_signal_start is None:
            orb_signal_start = ORB_SIGNAL_START
        if orb_signal_end is None:
            orb_signal_end = ORB_SIGNAL_END
        if fade_atr_top2 is None:
            fade_atr_top2 = set()
        _orb_vix_ok        = (day_vix is None or day_vix < 25.0)
        _stress_orb_vix_ok = (day_vix is None or day_vix >= 30.0)
        if day_vix is not None:
            logger.debug("VIX gate: %.1f  orb_ok=%s  stress_orb_ok=%s", day_vix, _orb_vix_ok, _stress_orb_vix_ok)
        # ── Daily reset ───────────────────────────────────────────────────────
        self._circuit_breaker_active = False
        self._safety_mode_active = False
        self._regime_bar_counts = {"Calm": 0, "Normal": 0, "Stress": 0, "Crisis": 0}

        session_dt = day.to_pydatetime()
        try:
            circuit_breakers.reset_for_new_session(day.date())
        except Exception:
            pass

        # DecisionUnit.reset_day() handles: orb/stress_orb/fade_orb/vwap_mr/trend resets
        # and coordinator.reset_for_new_session()
        self._decision_unit.reset_day(day, orb_signal_start, orb_signal_end)

        session_start_equity = self.equity_tracker.equity
        self.equity_tracker.new_session(day)

        # ── Day bars ──────────────────────────────────────────────────────────
        day_spy = spy_data[spy_data.index.normalize() == day]
        if day_spy.empty:
            return

        # SPY OR (9:30–9:44) used for SHORT FADE direction filter (Scenario G).
        # Fixed window, not tied to WFO orb_range_minutes.
        _spy_or_bars = day_spy[
            (day_spy.index.time >= dtime(9, 30)) & (day_spy.index.time <= dtime(9, 44))
        ]
        _spy_or_high: Optional[float] = float(_spy_or_bars["high"].max()) if not _spy_or_bars.empty else None
        _spy_or_low:  Optional[float] = float(_spy_or_bars["low"].min())  if not _spy_or_bars.empty else None

        # Build combined ticker set: dynamic scanner universe (if active) or static
        # config.universe, plus any fixed ORB/VWAP universes.
        _base_universe = day_universe if day_universe is not None else list(self.config.universe)
        # Merge: scanner picks range-bound stocks from daily data; config.vwap_universe
        # provides ETFs that have no daily data but always qualify for MR.
        _scanner_vwap = list(mr_universe) if mr_universe else []
        _effective_vwap_universe = _scanner_vwap + [
            t for t in self.config.vwap_universe if t not in _scanner_vwap
        ]
        _effective_orb_universe = orb_scanned_universe if orb_scanned_universe is not None else list(self.config.orb_universe)
        _effective_fade_universe = list(fade_scanned_universe) if fade_scanned_universe is not None else []
        _all_tickers = _base_universe + [
            t for t in _effective_orb_universe
            if t not in _base_universe
        ] + [
            t for t in _effective_vwap_universe
            if t not in _base_universe and t not in _effective_orb_universe
        ] + [
            t for t in _effective_fade_universe
            if t not in _base_universe and t not in _effective_orb_universe and t not in _effective_vwap_universe
        ]
        day_stocks: Dict[str, pd.DataFrame] = {
            ticker: market_data[ticker][market_data[ticker].index.normalize() == day]
            for ticker in _all_tickers
            if ticker in market_data and ticker != "SPY"
            and not market_data[ticker][market_data[ticker].index.normalize() == day].empty
        }

        # Log tickers silently dropped from day_stocks (missing 5-min data)
        _missing_5min = [
            t for t in _all_tickers
            if t != "SPY" and t not in day_stocks
        ]
        if _missing_5min:
            logger.debug(
                f"{day.date()} skip tickers: no 5-min bars today: {_missing_5min}"
            )

        # Ensure open swing trade tickers are always in day_stocks so exit
        # conditions (stop/target) are checked even if today's scanner didn't
        # select them. Without this, a ticker dropped from the scanner universe
        # would miss all exit checks and close at entry_price via _close_all.
        for _open_trade in self.trade_log.open_trades:
            _ot = _open_trade.ticker
            if _ot not in day_stocks and _ot in market_data and _ot != "SPY":
                _bars = market_data[_ot][market_data[_ot].index.normalize() == day]
                if not _bars.empty:
                    day_stocks[_ot] = _bars

        # Stress ETF ORB state — SPY comes from day_spy (excluded from day_stocks)
        _stress_stocks: Dict[str, pd.DataFrame] = {"SPY": day_spy}
        for _etf in ("QQQ", "IWM"):
            if _etf in day_stocks and not day_stocks[_etf].empty:
                _stress_stocks[_etf] = day_stocks[_etf]

        # ── Swing hold: pre-compute T-1 daily closes for SPY macro trend ────────
        try:
            _daily_spy_close = spy_data["close"].resample("B").last().dropna()
            _daily_spy_close = _daily_spy_close[
                _daily_spy_close.index.normalize() < day.normalize()
            ]
        except Exception:
            _daily_spy_close = pd.Series(dtype=float)

        # SPY macro trend for Stress-regime directional filter.
        # Computed once per day from T-1 daily closes (same data already fetched above).
        # True  = SPY SMA50 > SMA200 → bull trend → allow LONG in Stress
        # False = SPY SMA50 < SMA200 → bear/crash  → SHORT only in Stress
        _spy_bull_trend = True  # default: allow both directions
        try:
            if len(_daily_spy_close) >= 200:
                _sma50  = float(_daily_spy_close.iloc[-50:].mean())
                _sma200 = float(_daily_spy_close.iloc[-200:].mean())
                _spy_bull_trend = _sma50 > _sma200
        except Exception:
            pass

        if self.config.allow_swing_hold and self.trade_log.open_trades and not day_spy.empty:
            _open_ts = day_spy.index[0]
            for _trade in list(self.trade_log.open_trades):
                if _trade.strategy != "TREND_FOLLOW":
                    continue
                _hold = (day - pd.Timestamp(_trade.entry_time).normalize()).days
                _force = _hold >= self.config.max_hold_days
                if _force:
                    _reason = "MAX_HOLD"
                    _ticker = _trade.ticker
                    if _ticker in day_stocks and not day_stocks[_ticker].empty:
                        _px = float(day_stocks[_ticker].iloc[0]["open"])
                    else:
                        _px = _trade.entry_price
                    self._close_trade(_trade, _open_ts, _px, _reason,
                                      circuit_breakers, coordinator,
                                      _open_ts.to_pydatetime())
                    self._swing_state.pop(id(_trade), None)

        # ── Bar loop ──────────────────────────────────────────────────────────
        _regime_updated_today = False
        _cur_vol: float = 0.20  # default Normal; updated at first bar from SPY realized vol
        spy_history: List[pd.Series] = []

        for bar_ts, spy_bar in day_spy.iterrows():
            if self._circuit_breaker_active:
                break

            spy_history.append(spy_bar)
            bar_t  = bar_ts.time()
            bar_dt = bar_ts.to_pydatetime()

            # Compute HMM state once per day (stays in engine; result passed to DecisionUnit via BarContext)
            if not _regime_updated_today:
                spy_daily = to_daily_close(
                    spy_data[spy_data.index.normalize() <= bar_ts.normalize()]
                )
                if len(spy_daily) >= 20:
                    try:
                        if _hmm is not None and len(spy_daily) >= 21:
                            _state_idx = _hmm.predict_current(spy_daily)
                            self._hmm_state = _hmm.state_name(_state_idx)
                        _log_ret = np.log(spy_daily / spy_daily.shift(1)).dropna()
                        _rv = _log_ret.rolling(5).std() * np.sqrt(252)
                        _rv = _rv.dropna()
                        if len(_rv) >= 5:
                            _cur_vol = float(_rv.iloc[-1])
                            if _cur_vol >= 0.50:
                                self._hmm_state = "Crisis"
                    except Exception as e:
                        logger.debug(f"regime detection failed: {e}")
                _regime_updated_today = True

            self._regime_bar_counts[self._hmm_state] = (
                self._regime_bar_counts.get(self._hmm_state, 0) + 1
            )

            # Build BarContext for this bar
            ctx = BarContext(
                bar_ts=bar_ts,
                spy_bar=spy_bar,
                spy_history=list(spy_history),
                day_stocks=day_stocks,
                market_data=market_data,
                open_trades=list(self.trade_log.open_trades),
                hmm_state=self._hmm_state,
                cur_vol=_cur_vol,
                day=day,
                orb_vix_ok=_orb_vix_ok,
                stress_orb_vix_ok=_stress_orb_vix_ok,
                effective_orb_universe=_effective_orb_universe,
                effective_vwap_universe=_effective_vwap_universe,
                effective_fade_universe=_effective_fade_universe,
                all_tickers=_all_tickers,
                base_universe=_base_universe,
                stress_stocks=_stress_stocks,
                spy_or_high=_spy_or_high,
                spy_or_low=_spy_or_low,
                spy_bull_trend=_spy_bull_trend,
                daily_spy_close=_daily_spy_close,
                pe_short_calendar=self._pe_short_calendar,
                fade_atr_top2=fade_atr_top2,
                vwap_bb_std=self.config.vwap_bb_std,
                ema_period=self.config.ema_period,
                vwap_mr_vol_threshold=self.config.vwap_mr_vol_threshold,
                allow_swing_hold=self.config.allow_swing_hold,
                enable_pdt_guard=self.config.enable_pdt_guard,
                stress_size_fraction=self.config.stress_size_fraction,
                orb_signal_start=orb_signal_start,
                orb_signal_end=orb_signal_end,
            )

            # Get decisions from DecisionUnit
            if self._ctx_capture_hook is not None:
                self._ctx_capture_hook(ctx)
            result = self._decision_unit.decide(ctx)

            # Execute exits: swing strategies first, then SAFETY_MODE / intraday.
            # Mirrors engine.py ordering: section 2 (TF/PE_SHORT) runs BEFORE
            # section 4 (SAFETY_MODE check), which runs BEFORE section 10
            # (intraday exits).
            _SWING = ("TREND_FOLLOW", "PE_SHORT")
            _swing_exits    = [e for e in result.exits if e.trade.strategy in _SWING]
            _intraday_exits = [e for e in result.exits if e.trade.strategy not in _SWING]

            # Swing exits first — via _close_trade (CB updated, same as ORIG section 2)
            for exit_intent in _swing_exits:
                self._close_trade(
                    exit_intent.trade, bar_ts, exit_intent.exit_price, exit_intent.reason,
                    circuit_breakers, coordinator, bar_dt,
                )

            # If CB tripped during swing exits the coordinator is now blocked.
            if self._circuit_breaker_active:
                continue

            # SAFETY_MODE: close remaining intraday positions via _close_all (bypasses
            # CB update).  Mirrors engine.py section 4 — flash event, not strategy
            # failure; counting it toward the streak would fire CB hardest in Stress.
            if result.override_active:
                if not self._safety_mode_active:
                    logger.critical(f"{bar_ts} | SAFETY MODE ON")
                    self._safety_mode_active = True
                self._close_all(bar_ts, day_stocks, "SAFETY_MODE", skip_tf=True)
                continue

            if self._safety_mode_active:
                logger.info(f"{bar_ts} | SAFETY MODE OFF")
                self._safety_mode_active = False

            # Intraday exits — via _close_trade (CB updated, same as ORIG section 10)
            for exit_intent in _intraday_exits:
                self._close_trade(
                    exit_intent.trade, bar_ts, exit_intent.exit_price, exit_intent.reason,
                    circuit_breakers, coordinator, bar_dt,
                )

            # Execute entries
            for entry_intent in result.entries:
                trade = self.trade_log.open_trade(
                    ticker=entry_intent.ticker,
                    strategy=entry_intent.strategy,
                    direction=entry_intent.direction,
                    entry_time=bar_ts,
                    entry_price=entry_intent.entry_price,
                    shares=entry_intent.shares,
                    stop=entry_intent.stop,
                    target=entry_intent.target,
                    hmm_state=entry_intent.hmm_state,
                    limiting_factor=entry_intent.limiting_factor,
                )
                self._decision_unit.on_trade_opened(trade, entry_intent)
                logger.info(
                    f"{bar_ts} | OPEN {entry_intent.ticker} {entry_intent.strategy} "
                    f"{entry_intent.direction} {entry_intent.shares}sh "
                    f"@ ${entry_intent.entry_price:.2f} | "
                    f"stop=${entry_intent.stop:.2f} target=${entry_intent.target:.2f} | "
                    f"Regime:{entry_intent.hmm_state} Limit:{entry_intent.limiting_factor}"
                )
                # Same-bar exit check: engine.py opens trades immediately in
                # trade_log so section 10 can exit them on the entry bar.
                # DecisionUnit queues them in pending_entries → ctx.open_trades
                # misses them → exit detected one bar late.  Fix: run
                # _check_exits here for each newly opened intraday trade.
                if (entry_intent.strategy not in ("TREND_FOLLOW", "PE_SHORT")
                        and not self._circuit_breaker_active):
                    _sb_exit = self._decision_unit._check_exits(
                        trade, bar_ts, bar_t, day_stocks,
                        self.config.allow_swing_hold, spy_bar,
                    )
                    if _sb_exit:
                        _sb_price, _sb_reason = _sb_exit
                        self._close_trade(
                            trade, bar_ts, _sb_price, _sb_reason,
                            circuit_breakers, coordinator, bar_dt,
                        )
                # PDT recording is done inside DecisionUnit._attempt_entry
                # immediately when an entry is queued, so subsequent candidates
                # in the same bar see the updated count. Recording here again
                # would double-count every trade against the PDT limit.

            # Daily drawdown circuit breaker (stays in engine — needs equity).
            # Skip when SAFETY_MODE was active: engine.py uses `continue` after
            # _close_all("SAFETY_MODE"), which implicitly skips this check.
            if not result.override_active:
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
                        self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER",
                                        circuit_breakers=circuit_breakers, update_cb=True)
                        self._circuit_breaker_active = True
                        break
                except Exception as e:
                    logger.debug(f"CB check error: {e}")
                    pnl_pct = self.equity_tracker.daily_pnl_pct
                    if pnl_pct <= -0.04:
                        logger.critical(f"{bar_ts} | CIRCUIT BREAKER (fallback): {pnl_pct:.2%}")
                        self._close_all(bar_ts, day_stocks, "CIRCUIT_BREAKER",
                                        circuit_breakers=circuit_breakers, update_cb=True)
                        self._circuit_breaker_active = True
                        break

        # EOD close — skip TREND_FOLLOW swing positions
        if not self._circuit_breaker_active:
            self._close_all(day, day_stocks, "EOD",
                            skip_swing=self.config.allow_swing_hold)

        # Update Chandelier trailing stops for held swing positions
        if self.config.allow_swing_hold:
            self._update_swing_stops(day, market_data, day_stocks)

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
        """14-period ATR from intraday bars. Falls back to 1.5% of close on insufficient data."""
        if len(bars) < 2:
            return float(bars["close"].iloc[-1]) * 0.015
        hl  = bars["high"] - bars["low"]
        hpc = (bars["high"] - bars["close"].shift(1)).abs()
        lpc = (bars["low"]  - bars["close"].shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        return float(tr.tail(period).mean())

    def _build_orb_candidates(
        self,
        day_stocks: Dict[str, pd.DataFrame],
        market_data: Dict[str, pd.DataFrame],
        today: pd.Timestamp,
        effective_orb_universe: Optional[List[str]] = None,
        skip_gap_filter: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Build the candidates list expected by ORBStrategy.run_scanner.
        Uses real previous day close to compute genuine gap percentage.
        skip_gap_filter=True: bypass the 0.5% gap pre-filter (used for FADE).

        If effective_orb_universe is set, only those tickers are scanned.
        Otherwise falls back to the full universe (day_stocks).
        """
        # Determine which tickers to scan for ORB
        orb_tickers = effective_orb_universe or self.config.orb_universe
        if orb_tickers:
            # Only scan the volatile ORB-specific stocks
            scan_stocks = {
                t: df for t, df in day_stocks.items()
                if t in orb_tickers
            }
            logger.debug(
                f"ORB scanning {len(scan_stocks)} ORB-universe stocks "
                f"(not full universe of {len(day_stocks)})"
            )
        else:
            # Fallback: scan all stocks (original behaviour)
            scan_stocks = day_stocks

        candidates = []
        for ticker, df in scan_stocks.items():
            if df.empty:
                continue

            first  = df.iloc[0]
            open_p = float(first["open"])

            # ── Real previous day close ───────────────────────────────────────
            prev_close = None
            prior_bars = pd.DataFrame()
            if ticker in market_data:
                full_df   = market_data[ticker]
                prior_all = full_df[full_df.index.normalize() < today]
                if not prior_all.empty:
                    prev_close = float(prior_all.iloc[-1]["close"])
                    prior_bars = prior_all

            if prev_close is None or prev_close <= 0:
                logger.debug(f"ORB skip {ticker}: no prior day close available")
                continue

            gap_pct = abs(open_p - prev_close) / prev_close
            if not skip_gap_filter and gap_pct < 0.005:
                logger.debug(f"ORB skip {ticker}: gap {gap_pct:.2%} too small")
                continue

            # ── Historical opening bar volume (9:30-9:35) ────────────────────
            # The ORB scanner compares opening_5min_volume to avg_daily_volume/78.
            # Using all-day ADV/78 overestimates the threshold because opening
            # bars have 3-4x more volume than midday bars.
            # Instead, compute the average of the first 5-min bar across the
            # prior 20 trading days — a like-for-like comparison.
            avg_vol_by_time: dict = {}
            if not prior_bars.empty:
                # Get first bar of each prior trading day (for scanner threshold)
                prior_opening_vols = (
                    prior_bars.groupby(prior_bars.index.normalize())
                    .first()["volume"]
                    .tail(20)
                )
                avg_opening_vol = int(prior_opening_vols.mean()) if len(prior_opening_vols) > 0 else int(first["volume"])
                # avg_daily_volume used by scanner: threshold = 1.5 × (avg_daily_volume/78)
                # Set avg_daily_volume = avg_opening_vol × 78 → threshold = 1.5 × avg_opening_vol
                avg_daily_volume = avg_opening_vol * 78

                # Per-time-slot avg volume across last 20 days — used for rvol at signal time.
                # Blueprint intent: compare 9:45 bar against avg 9:45 bar, not avg opening bar.
                last_20_days = sorted(prior_bars.index.normalize().unique())[-20:]
                _recent = prior_bars[prior_bars.index.normalize().isin(last_20_days)].copy()
                if not _recent.empty:
                    _recent["_t"] = _recent.index.time
                    avg_vol_by_time = _recent.groupby("_t")["volume"].mean().to_dict()
            else:
                avg_daily_volume = int(df["volume"].mean() * 78)

            avg_daily_volume = max(avg_daily_volume, 1)

            candidates.append({
                "ticker":              ticker,
                "prev_close":          round(prev_close, 2),
                "open_price":          open_p,
                "premarket_volume":    int(df[df.index.time < dtime(9, 30)]["volume"].sum()),
                "avg_daily_volume":    avg_daily_volume,
                "opening_5min_volume": int(first["volume"]),
                "avg_vol_by_time":     avg_vol_by_time,
            })

        logger.info(f"ORB candidates: {len(candidates)} stocks with real gaps")
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
        stop = signal.get("stop", 0.0) or signal.get("stop_loss", 0.0) or signal.get("initial_stop", 0.0)
        entry = signal.get("entry_price", 0.0)

        try:
            if strategy == "FADE":
                # FADE uses VolTarget+Limit only — no Kelly gate.
                # Matches standalone test which sizes as $500/risk_per_share.
                # Kelly is excluded because bootstrap stats understate edge
                # and would limit to ~40 shares vs VolTarget's 200-600.
                vol_sh   = position_sizer.calculate_vol_target_shares(entry, stop)
                limit_sh = position_sizer.calculate_position_limit_shares(entry)
                final_sh = min(vol_sh, limit_sh)
                if final_sh < 1:
                    return
                size = {
                    "shares":                 final_sh,
                    "position_value":         round(final_sh * entry, 2),
                    "risk_dollars":           round(final_sh * abs(entry - stop), 2),
                    "risk_pct":               round(final_sh * abs(entry - stop) / position_sizer.account_equity, 6),
                    "kelly_shares":           0,
                    "vol_target_shares":      vol_sh,
                    "position_limit_shares":  limit_sh,
                    "limiting_factor":        "VOLATILITY_TARGET" if vol_sh <= limit_sh else "POSITION_LIMIT",
                }
            else:
                stats = STRATEGY_STATS.get(strategy, {"win_rate": 0.50, "avg_win": 3.0, "avg_loss": 2.0})
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

        # Reduce size in Stress regime for TREND_FOLLOW
        if strategy == "TREND_FOLLOW" and self._hmm_state in ("Stress", "Crisis"):
            n_shares = max(1, int(n_shares * self.config.stress_size_fraction))

        if n_shares <= 0:
            return

        target = signal.get("target", entry * 1.05 if signal.get("direction") == "LONG" else entry * 0.95)

        self.trade_log.open_trade(
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


    @staticmethod
    def _compute_adx(bars: pd.DataFrame, period: int = 14) -> float:
        """
        Compute 14-period Average Directional Index from 5-min bars.
        Returns 0.0 if insufficient data.
        """
        if len(bars) < period + 1:
            return 0.0
        try:
            high  = bars["high"]
            low   = bars["low"]
            close = bars["close"]

            # True Range
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low  - prev_close).abs(),
            ], axis=1).max(axis=1)

            # Directional Movement
            up   = high.diff()
            down = -low.diff()
            plus_dm  = up.where((up > down) & (up > 0), 0.0)
            minus_dm = down.where((down > up) & (down > 0), 0.0)

            # Wilder smoothing (approximate with EWM)
            atr_s      = tr.ewm(span=period, adjust=False).mean()
            plus_di    = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
            minus_di   = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
            dx         = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
            adx        = dx.ewm(span=period, adjust=False).mean()
            return float(adx.iloc[-1])
        except Exception:
            return 0.0

    def _compute_sector_strength(
        self,
        day_stocks: Dict[str, pd.DataFrame],
        bar_ts: pd.Timestamp,
        universe: List[str],
    ) -> float:
        """
        Average intraday return of universe stocks up to bar_ts.
        Positive = sector bullish, negative = sector bearish.
        """
        returns = []
        for ticker in universe:
            if ticker not in day_stocks:
                continue
            df = day_stocks[ticker].loc[:bar_ts]
            if len(df) < 2:
                continue
            open_p  = float(df.iloc[0]["open"])
            close_p = float(df.iloc[-1]["close"])
            if open_p > 0:
                returns.append((close_p - open_p) / open_p)
        return float(sum(returns) / len(returns)) if returns else 0.0

    def _build_vwap_candidates(
        self,
        day_stocks: Dict[str, pd.DataFrame],
        bar_ts: pd.Timestamp,
        universe: List[str],
    ) -> List[Dict[str, Any]]:
        """Build candidate dicts for VWAPMRStrategy.run_scanner()."""
        candidates = []
        for ticker in universe:
            if ticker not in day_stocks:
                continue
            bars = day_stocks[ticker].loc[:bar_ts]
            if len(bars) < 22:   # need 20 for SMA + 2 for ATR comparison
                continue
            try:
                current_price  = float(bars.iloc[-1]["close"])
                current_volume = float(bars.iloc[-1]["volume"])
                avg_bar_vol    = float(bars["volume"].mean())   # per-5min-bar average today
                sma_20         = float(bars["close"].rolling(20).mean().iloc[-1])
                atr_current    = self._compute_atr(bars)
                atr_5bars_ago  = self._compute_atr(bars.iloc[:-5]) if len(bars) > 19 else atr_current
                adx            = self._compute_adx(bars)

                if pd.isna(sma_20) or sma_20 <= 0:
                    continue

                candidates.append({
                    "ticker":           ticker,
                    "adx":              adx,
                    "sma_20":           sma_20,
                    "current_price":    current_price,
                    "current_volume":   current_volume,
                    "avg_daily_volume": avg_bar_vol,   # per-bar avg; scanner ratio = current_bar / avg_bar
                    "atr_current":      atr_current,
                    "atr_5bars_ago":    atr_5bars_ago,
                    "has_earnings":     False,   # no earnings data available
                })
            except Exception as e:
                logger.debug(f"VWAP candidate error {ticker}: {e}")
        return candidates

    def _build_trend_candidates(
        self,
        day_stocks: Dict[str, pd.DataFrame],
        bar_ts: pd.Timestamp,
        universe: List[str],
        sector_strength: float,
    ) -> List[Dict[str, Any]]:
        """Build candidate dicts for TrendFollowStrategy.run_scanner()."""
        candidates = []
        for ticker in universe:
            if ticker not in day_stocks:
                continue
            bars = day_stocks[ticker].loc[:bar_ts]
            if len(bars) < 3:
                continue
            try:
                current_price     = float(bars.iloc[-1]["close"])
                current_volume    = float(bars.iloc[-1]["volume"])
                hod               = float(bars["high"].max())
                lod               = float(bars["low"].min())
                atr               = self._compute_atr(bars)
                avg_intraday_vol  = float(bars["volume"].tail(10).mean())

                candidates.append({
                    "ticker":              ticker,
                    "current_price":       current_price,
                    "hod":                 hod,
                    "lod":                 lod,
                    "atr":                 atr,
                    "avg_intraday_volume": avg_intraday_vol,
                    "current_volume":      current_volume,
                    "sector_strength":     sector_strength,
                })
            except Exception as e:
                logger.debug(f"Trend candidate error {ticker}: {e}")
        return candidates


    @staticmethod
    def _compute_daily_atr(
        market_data: Dict[str, pd.DataFrame],
        ticker: str,
        as_of: pd.Timestamp,
        period: int = 14,
    ) -> float:
        """
        Compute 14-period ATR from daily closes for a ticker.
        Used to size Trend Follow stops at a meaningful scale.
        Falls back to 1% of price if insufficient data.
        """
        if ticker not in market_data:
            return 0.0
        try:
            df = market_data[ticker]
            # Get daily OHLC by resampling
            daily = df.loc[df.index < as_of].resample("B").agg({
                "open":  "first",
                "high":  "max",
                "low":   "min",
                "close": "last",
            }).dropna()

            if len(daily) < period + 1:
                # Fallback: 1% of last close
                last_close = float(df.loc[df.index < as_of]["close"].iloc[-1])
                return last_close * 0.01

            hl  = daily["high"] - daily["low"]
            hpc = (daily["high"] - daily["close"].shift(1)).abs()
            lpc = (daily["low"]  - daily["close"].shift(1)).abs()
            tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
            return float(tr.tail(period).mean())
        except Exception:
            return 0.0

    @staticmethod
    def _compute_fade_atr_top2(
        daily_data: Dict[str, pd.DataFrame],
        as_of: pd.Timestamp,
        period: int = 14,
        top_n: int = 2,
    ) -> set:
        """Return tickers with top_n highest ATR% (ATR/close) as of prior close.
        Used to block LONG FADE on high-momentum stocks (Scenario G filter)."""
        atrs: Dict[str, float] = {}
        for ticker, df in daily_data.items():
            if ticker == "SPY":
                continue
            try:
                df = df.copy()
                df.columns = [c.lower() for c in df.columns]
                df.index = pd.DatetimeIndex(df.index)
                prior = df[df.index < as_of].sort_index()
                if len(prior) < period + 1:
                    continue
                prev_close = prior["close"].shift(1)
                tr = pd.concat([
                    prior["high"] - prior["low"],
                    (prior["high"] - prev_close).abs(),
                    (prior["low"]  - prev_close).abs(),
                ], axis=1).max(axis=1)
                atr   = float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
                close = float(prior["close"].iloc[-1])
                if close > 0:
                    atrs[ticker] = atr / close
            except Exception:
                continue
        ranked = sorted(atrs.items(), key=lambda x: x[1], reverse=True)
        return {t for t, _ in ranked[:top_n]}

    def _check_exits(
        self,
        trade: Trade,
        bar_ts: pd.Timestamp,
        bar_t: dtime,
        day_stocks: Dict[str, pd.DataFrame],
        spy_bar: Optional[pd.Series] = None,
    ) -> Optional[Tuple[float, str]]:
        if trade.ticker not in day_stocks:
            # SPY STRESS_MID trades need exit checks using the current SPY bar
            if trade.ticker == "SPY" and spy_bar is not None:
                bar_low   = float(spy_bar["low"])
                bar_high  = float(spy_bar["high"])
                bar_close = float(spy_bar["close"])
            else:
                return None
        else:
            try:
                bar = day_stocks[trade.ticker].loc[bar_ts]
            except KeyError:
                return None
            bar_low   = float(bar["low"])
            bar_high  = float(bar["high"])
            bar_close = float(bar["close"])

        if bar_t >= EOD_HARD_EXIT:
            if self.config.allow_swing_hold and trade.strategy == "TREND_FOLLOW":
                return None  # TF swing — hold overnight
            if trade.strategy == "PE_SHORT":
                _pe_entry_day = pd.Timestamp(trade.entry_time).normalize()
                if _pe_entry_day == bar_ts.normalize():
                    return None  # entry day — hold overnight, exit at T+1 EOD
            return bar_close, "EOD"

        if trade.direction == "LONG":
            if bar_low  <= trade.stop:   return trade.stop,   "STOP_HIT"
            if bar_high >= trade.target: return trade.target, "TARGET_HIT"
        else:
            if bar_high >= trade.stop:   return trade.stop,   "STOP_HIT"
            if bar_low  <= trade.target: return trade.target, "TARGET_HIT"

        if trade.strategy == "VWAP_MR":
            elapsed = (bar_ts - trade.entry_time).total_seconds() / 60
            if elapsed >= 90:   # extended from 45→90 min to allow full mean reversion
                return bar_close, "TIME_STOP"

        if trade.strategy == "GAP_FILL" and bar_t >= GAP_FILL_EXIT:
            return bar_close, "TIME_STOP"

        if trade.strategy == "GF_SHORT" and bar_t >= GAP_FILL_EXIT:
            return bar_close, "TIME_STOP"

        if trade.strategy == "RS_SHORT" and bar_t >= RS_SHORT_EXIT:
            return bar_close, "TIME_STOP"

        if trade.strategy == "STRESS_MID" and bar_t >= STRESS_MID_EXIT:
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

        # TF cooldown removed — DecisionUnit.decide() owns _tf_cooldown and sets it
        # when it detects STOP_HIT in the swing exit section before returning ExitIntent.

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
        skip_swing: bool = False,
        skip_tf: bool = False,
        circuit_breakers=None,
        update_cb: bool = False,
    ) -> None:
        open_trades = list(self.trade_log.open_trades)
        if not open_trades:
            return
        _ts_day = timestamp.normalize()
        trades_to_close = [
            t for t in open_trades
            if not (
                (skip_swing and t.strategy == "TREND_FOLLOW") or
                (skip_tf   and t.strategy == "TREND_FOLLOW") or
                # PE_SHORT is always a swing — keep alive in SAFETY_MODE and on entry day EOD
                (skip_tf   and t.strategy == "PE_SHORT") or
                (t.strategy == "PE_SHORT"
                 and pd.Timestamp(t.entry_time).normalize() == _ts_day)
            )
        ]
        if not trades_to_close:
            return
        logger.warning(f"{timestamp} | Closing {len(trades_to_close)} positions — {reason}")
        for trade in trades_to_close:
            if trade.ticker in day_stocks and not day_stocks[trade.ticker].empty:
                _bar  = day_stocks[trade.ticker].iloc[-1]
                price = float(_bar["close"])
                # If stop was crossed during this bar, cap exit at stop price.
                # Prevents SAFETY_MODE from closing at a price worse than stop.
                if trade.stop is not None:
                    if trade.direction == "LONG" and float(_bar["low"]) <= trade.stop:
                        price = max(price, trade.stop)
                    elif trade.direction == "SHORT" and float(_bar["high"]) >= trade.stop:
                        price = min(price, trade.stop)
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
            if update_cb and circuit_breakers is not None:
                circuit_breakers.record_trade_result(trade.net_pnl or 0.0)

    def _update_swing_stops(
        self,
        day: pd.Timestamp,
        market_data: Dict[str, pd.DataFrame],
        day_stocks: Dict[str, pd.DataFrame],
    ) -> None:
        """Update Chandelier trailing stops EOD for open TREND_FOLLOW swing positions."""
        for trade in self.trade_log.open_trades:
            if trade.strategy != "TREND_FOLLOW":
                continue
            ticker = trade.ticker
            if ticker not in day_stocks or day_stocks[ticker].empty:
                continue

            day_high = float(day_stocks[ticker]["high"].max())
            day_low  = float(day_stocks[ticker]["low"].min())
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
            logger.debug(f"Swing stop update {ticker} {trade.direction}: "
                         f"stop={trade.stop:.2f} extreme={new_extreme:.2f}")

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
            latest_ret = returns.iloc[-1]
            # Require BOTH: statistical outlier (>3σ) AND meaningful absolute move.
            # 0.6% in a single 5-min SPY bar ≈ genuine flash event (not normal vol).
            # 0.4% was too sensitive: in a 2022 bear market with 1-2% daily SPY moves,
            # a single 5-min bar at 0.4% is common and was triggering 1-2×/week.
            return bool(abs(latest_ret / std) > 3.0 and abs(latest_ret) > 0.006)
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
