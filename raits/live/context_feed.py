"""
raits/live/context_feed.py

ReplayContextFeed: builds BarContext objects from historical Polygon data,
field-for-field identical to what engine_refactored passes to decide() at
each bar.  Drives the paper-trading harness in offline / verify mode.

LivePolygonFeed: stub for a future real-time Polygon WebSocket feed.

The key invariant: ReplayContextFeed and RefactoredBacktestEngine given the
same market_data, config, and auxiliary data MUST produce identical BarContext
objects at each bar (excluding open_trades, which the runner injects).

Architecture mirrors engine_refactored._run_day exactly:
  - Per-run setup: HMM train, PE calendar, VIX daily, scanners, orb times
  - Per-day: universes, day_stocks, stress_stocks, spy OR, bull trend, daily_spy_close
  - Per-bar: spy_history, hmm_state, cur_vol, BarContext yield

open_trades is always [] here — the PaperTrader runner injects current positions.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime as _dt, time as dtime, timedelta as _td
from typing import Any, Dict, Iterator, List, Optional

import numpy as np
import pandas as pd

from raits.backtest.data_types import BacktestConfig
from raits.decision.types import BarContext
from raits.live.runner import ContextFeed

logger = logging.getLogger("RAITS.live.context_feed")

# ── Mirrors engine_refactored time constants ──────────────────────────────────
_ORB_RANGE_START  = dtime(9, 30)
_SPY_OR_START     = dtime(9, 30)
_SPY_OR_END       = dtime(9, 44)   # fixed SPY OR window (not WFO-tuned)


def _to_daily_close(bars: pd.DataFrame) -> pd.Series:
    return bars["close"].resample("B").last().dropna()


def _compute_spy_bull_trend(daily_spy_close: pd.Series) -> bool:
    """SMA50 > SMA200 on T-1 daily closes. Same formula as engine."""
    try:
        if len(daily_spy_close) >= 200:
            sma50  = float(daily_spy_close.iloc[-50:].mean())
            sma200 = float(daily_spy_close.iloc[-200:].mean())
            return sma50 > sma200
    except Exception:
        pass
    return True  # default: allow both directions


def _compute_fade_atr_top2(
    daily_data: Dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    period: int = 14,
    top_n: int = 2,
) -> set:
    """Top-N tickers by ATR% as of prior close. Byte-identical to engine's static method."""
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


class ReplayContextFeed(ContextFeed):
    """
    Historical replay that produces BarContexts identical to engine_refactored.

    Parameters
    ----------
    market_data       : same dict engine.run() receives
    config            : BacktestConfig (same instance as engine)
    daily_data        : same daily_data engine.run() receives (for scanners + ATR)
    pe_short_calendar : pre-loaded dict {pd.Timestamp → [tickers]}
                        Pass engine's self._pe_short_calendar, or load from file.
    vix_daily         : pre-loaded dict {pd.Timestamp → float}
    hmm               : pre-trained HMMEngine instance; if None, feed trains its own
    hmm_hist_path     : path to SPY historical daily parquet for HMM initial fit
                        (same file the engine tries to load)
    """

    # path constants mirror engine_refactored.run()
    _EARNINGS_PATH = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "cache",
        "earnings_dates_expanded.json",
    ))
    _VIX_PATH = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "cache", "daily",
        "vix_daily.parquet",
    ))
    _HMM_HIST_PATH = os.path.normpath(os.path.join(
        os.path.dirname(__file__), "..", "data", "cache", "daily",
        "SPY_daily_2007_2024.parquet",
    ))

    def __init__(
        self,
        market_data: Dict[str, pd.DataFrame],
        config: BacktestConfig,
        daily_data: Optional[Dict[str, pd.DataFrame]] = None,
        pe_short_calendar: Optional[Dict] = None,
        vix_daily: Optional[Dict] = None,
        hmm: Optional[Any] = None,
    ) -> None:
        if "SPY" not in market_data:
            raise ValueError("market_data must contain 'SPY'")
        self._market_data = market_data
        self._config = config
        self._daily_data = daily_data
        self._hmm = hmm

        # ── PE short calendar ─────────────────────────────────────────────────
        if pe_short_calendar is not None:
            self._pe_cal: Dict[pd.Timestamp, List[str]] = pe_short_calendar
        else:
            self._pe_cal = self._load_pe_calendar()

        # ── VIX daily ─────────────────────────────────────────────────────────
        if vix_daily is not None:
            self._vix_daily: Dict = vix_daily
        else:
            self._vix_daily = self._load_vix_daily()

        # ── ORB signal window (same formula as engine.run()) ──────────────────
        _base = _dt(2000, 1, 1, 9, 30)
        _sig_start = _base + _td(minutes=config.orb_range_minutes)
        _sig_end   = _sig_start + _td(minutes=30)
        self._orb_signal_start = _sig_start.time()
        self._orb_signal_end   = _sig_end.time()

        # ── Scanners (same flags as engine) ───────────────────────────────────
        # Scanners are lazily constructed in __iter__ so they mirror engine exactly.
        self._scanner      = None
        self._mr_scanner   = None
        self._orb_scanner  = None
        self._fade_scanner = None

    # ── ContextFeed interface ─────────────────────────────────────────────────

    def __iter__(self) -> Iterator[BarContext]:
        yield from self._iter_all()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_pe_calendar(self) -> Dict[pd.Timestamp, List[str]]:
        cal: Dict[pd.Timestamp, List[str]] = {}
        if os.path.exists(self._EARNINGS_PATH):
            with open(self._EARNINGS_PATH) as f:
                raw = json.load(f)
            for tk, dates in raw.items():
                for d in dates:
                    ts = pd.Timestamp(d)
                    cal.setdefault(ts, []).append(tk)
        return cal

    def _load_vix_daily(self) -> Dict:
        if os.path.exists(self._VIX_PATH):
            vix_df = pd.read_parquet(self._VIX_PATH)
            vix_df.index = pd.DatetimeIndex(vix_df.index).normalize()
            return vix_df["vix"].to_dict()
        return {}

    def _init_hmm(self, spy_data: pd.DataFrame, bt_start: pd.Timestamp) -> Any:
        """Train HMM same way engine.run() does. Returns None on failure."""
        try:
            from raits.hmm.engine import HMMEngine
            hmm = HMMEngine()
            if os.path.exists(self._HMM_HIST_PATH):
                spy_hist = pd.read_parquet(self._HMM_HIST_PATH)
                spy_hist.index = pd.DatetimeIndex(spy_hist.index)
                spy_hist_close = spy_hist["close"].sort_index()
                spy_hist_close = spy_hist_close[spy_hist_close.index < bt_start]
                if len(spy_hist_close) >= 50:
                    hmm.fit(spy_hist_close)
                    return hmm
            hmm.fit(_to_daily_close(spy_data))
            return hmm
        except Exception as e:
            logger.warning("HMM init failed (%s) — hmm_state will be 'Normal'", e)
            return None

    def _iter_all(self) -> Iterator[BarContext]:  # noqa: C901
        config    = self._config
        mkt       = self._market_data
        daily     = self._daily_data
        spy_data  = mkt["SPY"]
        vix_daily = self._vix_daily

        # ── HMM ───────────────────────────────────────────────────────────────
        hmm = self._hmm
        if hmm is None:
            bt_start = pd.Timestamp(
                spy_data.index.normalize().min()
            )
            hmm = self._init_hmm(spy_data, bt_start)

        # ── Scanners (same logic as engine.run()) ─────────────────────────────
        from raits.strategies.universe_scanner import (
            DailyUniverseScanner, MRUniverseScanner,
            ORBUniverseScanner, ORBFadeUniverseScanner,
        )
        scanner     = DailyUniverseScanner(top_n=config.scanner_top_n)     if config.use_scanner      and daily else None
        mr_scanner  = MRUniverseScanner(top_n=config.mr_scanner_top_n)    if config.use_mr_scanner   and daily else None
        orb_scanner = ORBUniverseScanner(top_n=config.orb_scanner_top_n)  if config.use_orb_scanner  and daily else None
        fade_scanner= ORBFadeUniverseScanner(top_n=config.fade_scanner_top_n) if config.use_fade_scanner and daily else None

        _any_scanner = any(s is not None for s in (scanner, mr_scanner, orb_scanner, fade_scanner))
        if _any_scanner and daily and "SPY" in daily:
            spy_daily_dates = sorted(daily["SPY"].index.normalize().unique())
        else:
            spy_daily_dates = []

        # ── Day calendar (same filter as engine) ─────────────────────────────
        all_days = pd.DatetimeIndex(spy_data.index.normalize().unique())
        all_days = all_days[
            (all_days >= pd.Timestamp(config.start_date))
            & (all_days <= pd.Timestamp(config.end_date))
        ]

        # ── HMM retrain state ─────────────────────────────────────────────────
        last_retrain: Optional[pd.Timestamp] = None

        for day in all_days:
            yield from self._iter_day(
                day=day,
                spy_data=spy_data,
                mkt=mkt,
                daily=daily,
                hmm=hmm,
                vix_daily=vix_daily,
                spy_daily_dates=spy_daily_dates,
                scanner=scanner,
                mr_scanner=mr_scanner,
                orb_scanner=orb_scanner,
                fade_scanner=fade_scanner,
            )

            # ── HMM weekly retrain (mirrors engine.run() post-_run_day block) ─
            if config.hmm_retrain_weekly and day.weekday() == 0:
                if last_retrain is None or (day - last_retrain).days >= 7:
                    recent_spy  = spy_data[spy_data.index.normalize() <= day]
                    daily_close = _to_daily_close(recent_spy)
                    if hmm is not None and len(daily_close) >= 35:
                        try:
                            hmm.retrain(daily_close)
                        except Exception as e:
                            logger.debug("HMM retrain failed: %s", e)
                    last_retrain = day

    def _iter_day(  # noqa: C901
        self,
        day: pd.Timestamp,
        spy_data: pd.DataFrame,
        mkt: Dict[str, pd.DataFrame],
        daily: Optional[Dict[str, pd.DataFrame]],
        hmm: Any,
        vix_daily: Dict,
        spy_daily_dates: List,
        scanner: Any,
        mr_scanner: Any,
        orb_scanner: Any,
        fade_scanner: Any,
    ) -> Iterator[BarContext]:
        config = self._config

        # ── VIX gates (same as engine._run_day) ───────────────────────────────
        _day_key = day.normalize()
        _day_vix: Optional[float] = (
            float(vix_daily[_day_key]) if _day_key in vix_daily else None
        )
        orb_vix_ok        = (_day_vix is None or _day_vix < 25.0)
        stress_orb_vix_ok = (_day_vix is None or _day_vix >= 30.0)

        # ── Scanner universes (same logic as engine.run() day loop) ───────────
        def _prev_date(dates: List) -> Optional[pd.Timestamp]:
            matches = [d for d in dates if d < day.normalize()]
            return matches[-1] if matches else None

        if scanner and spy_daily_dates:
            _pd = _prev_date(spy_daily_dates)
            day_universe = scanner.scan(daily, _pd) if _pd else list(config.universe)
        else:
            day_universe = None

        if mr_scanner and spy_daily_dates:
            _pd = _prev_date(spy_daily_dates)
            mr_universe = mr_scanner.scan(daily, _pd) if _pd else None
        else:
            mr_universe = None

        if orb_scanner and spy_daily_dates:
            _pd = _prev_date(spy_daily_dates)
            orb_scanned = orb_scanner.scan(daily, _pd) if _pd else None
        else:
            orb_scanned = None

        if fade_scanner and spy_daily_dates:
            _pd = _prev_date(spy_daily_dates)
            fade_scanned = fade_scanner.scan(daily, _pd) if _pd else None
        else:
            fade_scanned = None

        # ── FADE ATR% top-2 ───────────────────────────────────────────────────
        fade_atr_top2: set = set()
        if daily:
            _spy_dd = sorted(daily["SPY"].index.normalize().unique()) if "SPY" in daily else []
            _prev_d = [d for d in _spy_dd if d < day.normalize()]
            if _prev_d:
                fade_atr_top2 = _compute_fade_atr_top2(daily, _prev_d[-1])

        # ── Universe assembly (mirrors engine._run_day) ───────────────────────
        base_universe = day_universe if day_universe is not None else list(config.universe)
        _scanner_vwap = list(mr_universe) if mr_universe else []
        eff_vwap = _scanner_vwap + [
            t for t in config.vwap_universe if t not in _scanner_vwap
        ]
        eff_orb  = orb_scanned if orb_scanned is not None else list(config.orb_universe)
        eff_fade = list(fade_scanned) if fade_scanned is not None else []

        all_tickers = (
            base_universe
            + [t for t in eff_orb  if t not in base_universe]
            + [t for t in eff_vwap if t not in base_universe and t not in eff_orb]
            + [t for t in eff_fade if t not in base_universe and t not in eff_orb and t not in eff_vwap]
        )

        # ── day_stocks (ALL bars for today, same as engine) ───────────────────
        day_stocks: Dict[str, pd.DataFrame] = {
            ticker: mkt[ticker][mkt[ticker].index.normalize() == day]
            for ticker in all_tickers
            if ticker in mkt and ticker != "SPY"
            and not mkt[ticker][mkt[ticker].index.normalize() == day].empty
        }

        # ── SPY day bars ──────────────────────────────────────────────────────
        day_spy = spy_data[spy_data.index.normalize() == day]
        if day_spy.empty:
            return

        # ── SPY OR high/low (9:30–9:44, fixed window) ────────────────────────
        spy_or_bars = day_spy[
            (day_spy.index.time >= _SPY_OR_START)
            & (day_spy.index.time <= _SPY_OR_END)
        ]
        spy_or_high: Optional[float] = (
            float(spy_or_bars["high"].max()) if not spy_or_bars.empty else None
        )
        spy_or_low: Optional[float] = (
            float(spy_or_bars["low"].min()) if not spy_or_bars.empty else None
        )

        # ── Stress stocks (SPY + QQQ + IWM) ──────────────────────────────────
        stress_stocks: Dict[str, pd.DataFrame] = {"SPY": day_spy}
        for _etf in ("QQQ", "IWM"):
            if _etf in day_stocks and not day_stocks[_etf].empty:
                stress_stocks[_etf] = day_stocks[_etf]

        # ── Daily SPY close (T-1) ─────────────────────────────────────────────
        try:
            daily_spy_close = spy_data["close"].resample("B").last().dropna()
            daily_spy_close = daily_spy_close[
                daily_spy_close.index.normalize() < day.normalize()
            ]
        except Exception:
            daily_spy_close = pd.Series(dtype=float)

        # ── SPY bull trend ────────────────────────────────────────────────────
        spy_bull_trend = _compute_spy_bull_trend(daily_spy_close)

        # ── Bar loop ──────────────────────────────────────────────────────────
        hmm_state   = "Normal"
        cur_vol     = 0.20
        _regime_set = False
        spy_history: List[pd.Series] = []

        for bar_ts, spy_bar in day_spy.iterrows():
            spy_history.append(spy_bar)

            # HMM + vol: computed once per day at first bar (same as engine) ──
            if not _regime_set:
                spy_daily = _to_daily_close(
                    spy_data[spy_data.index.normalize() <= bar_ts.normalize()]
                )
                if len(spy_daily) >= 20:
                    try:
                        if hmm is not None and len(spy_daily) >= 21:
                            state_idx = hmm.predict_current(spy_daily)
                            hmm_state = hmm.state_name(state_idx)
                        log_ret = np.log(spy_daily / spy_daily.shift(1)).dropna()
                        rv = log_ret.rolling(5).std() * np.sqrt(252)
                        rv = rv.dropna()
                        if len(rv) >= 5:
                            cur_vol = float(rv.iloc[-1])
                            if cur_vol >= 0.50:
                                hmm_state = "Crisis"
                    except Exception as e:
                        logger.debug("regime detection failed: %s", e)
                _regime_set = True

            ctx = BarContext(
                bar_ts=bar_ts,
                spy_bar=spy_bar,
                spy_history=list(spy_history),
                day_stocks=day_stocks,
                market_data=mkt,
                open_trades=[],              # runner injects this
                hmm_state=hmm_state,
                cur_vol=cur_vol,
                day=day,
                orb_vix_ok=orb_vix_ok,
                stress_orb_vix_ok=stress_orb_vix_ok,
                effective_orb_universe=eff_orb,
                effective_vwap_universe=eff_vwap,
                effective_fade_universe=eff_fade,
                all_tickers=all_tickers,
                base_universe=base_universe,
                stress_stocks=stress_stocks,
                spy_or_high=spy_or_high,
                spy_or_low=spy_or_low,
                spy_bull_trend=spy_bull_trend,
                daily_spy_close=daily_spy_close,
                pe_short_calendar=self._pe_cal,
                fade_atr_top2=fade_atr_top2,
                vwap_bb_std=config.vwap_bb_std,
                ema_period=config.ema_period,
                vwap_mr_vol_threshold=config.vwap_mr_vol_threshold,
                allow_swing_hold=config.allow_swing_hold,
                enable_pdt_guard=config.enable_pdt_guard,
                stress_size_fraction=config.stress_size_fraction,
                orb_signal_start=self._orb_signal_start,
                orb_signal_end=self._orb_signal_end,
            )
            yield ctx


class LivePolygonFeed(ContextFeed):
    """
    Stub for real-time Polygon WebSocket BarContext feed.
    Raises NotImplementedError — wire up in the IBKR integration step.

    When implemented, it will:
      - Subscribe to Polygon WebSocket for 5-min aggregate bars
      - Accumulate day_stocks incrementally as each bar arrives
      - Compute hmm_state / cur_vol from cached SPY daily closes
      - Reconstruct all BarContext fields the same way ReplayContextFeed does
      - Yield BarContext objects as real-time bars arrive
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "LivePolygonFeed is not yet implemented.\n"
            "Use ReplayContextFeed for paper-trading verification."
        )

    def __iter__(self) -> Iterator[BarContext]:
        raise NotImplementedError
