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


# ── Bar accumulation helper ───────────────────────────────────────────────────

class _BarAccumulator:
    """
    Thread-safe bar buffer for LivePolygonFeed's live WebSocket mode.

    Handles:
    - Late / out-of-order bars: sorted by timestamp on demand
    - Duplicates and corrections: last-write-wins by (ticker, ts)
    - Missing bars: ticker simply absent from get_day_stocks() result
    """

    def __init__(self) -> None:
        import threading
        self._lock: "threading.Lock" = threading.Lock()
        # ticker → { bar_ts → row Series }
        self._buf: Dict[str, Dict[pd.Timestamp, pd.Series]] = {}

    def add(self, ticker: str, ts: pd.Timestamp, row: pd.Series) -> None:
        """Add or overwrite a bar. Thread-safe."""
        with self._lock:
            self._buf.setdefault(ticker, {})[ts] = row

    def get_day_stocks(
        self, day: pd.Timestamp, as_of: pd.Timestamp
    ) -> Dict[str, pd.DataFrame]:
        """
        Return day_stocks for `day` up to and including `as_of`.
        Bars are sorted by timestamp; excludes SPY.
        Thread-safe (takes a snapshot).
        """
        with self._lock:
            snapshot = {tk: dict(ts_map) for tk, ts_map in self._buf.items()}

        result: Dict[str, pd.DataFrame] = {}
        for ticker, ts_map in snapshot.items():
            eligible = {
                ts: row for ts, row in ts_map.items()
                if ts.normalize() == day and ts <= as_of
            }
            if not eligible:
                continue
            rows = [eligible[ts] for ts in sorted(eligible)]
            df = pd.concat([r.to_frame().T for r in rows])
            df.index = pd.DatetimeIndex(sorted(eligible))
            result[ticker] = df
        return result

    def reset(self) -> None:
        """Clear all buffered bars (call at day boundary)."""
        with self._lock:
            self._buf.clear()

    def tickers(self) -> set:
        """All tickers with at least one buffered bar."""
        with self._lock:
            return set(self._buf)


# ── LivePolygonFeed ───────────────────────────────────────────────────────────

class LivePolygonFeed(ContextFeed):
    """
    Real-time Polygon WebSocket BarContext feed.

    Subscribes to Polygon 5-min aggregate bars (AM.*), accumulates day_stocks
    incrementally as each bar arrives, and yields a BarContext for every SPY
    bar slot (9:30 … 15:55 ET).

    Parameters
    ----------
    config       : BacktestConfig (universe, orb params, scanner flags, etc.)
    api_key      : Polygon.io API key used for WebSocket + REST backfill.
    daily_data   : Daily OHLCV per ticker — drives scanner universes and
                   fade_atr_top2.  Same dict as BacktestEngine.run(daily_data=…).
    pe_short_calendar : Pre-loaded {pd.Timestamp → [tickers]} dict.
                        If None, loaded from the earnings JSON cache.
    vix_daily    : Pre-loaded {pd.Timestamp → float} VIX dict.
                   If None, loaded from the VIX parquet cache.
    hmm          : Pre-trained HMMEngine. If None, trained the same way
                   ReplayContextFeed does (SPY historical parquet).
    emit_timeout : Seconds to wait for a cadence slot's bars before emitting
                   without them (handles late Polygon delivery). Default 10 s.
    backfill_on_reconnect : Whether to fetch missing bars via the REST API
                            after a WebSocket reconnect. Default True.

    Testing interface
    -----------------
    _test_market_data : Dict[str, pd.DataFrame] in the same format as the
                        `market_data` argument to BacktestEngine.  When
                        provided, replaces WebSocket delivery — bars are
                        replayed in cadence order from this dict.
                        `day_stocks` is built incrementally (bars up to
                        bar_ts only), matching true live semantics while
                        keeping all other fields byte-identical to
                        ReplayContextFeed.  Tests use this to verify context
                        output without a live Polygon connection.

    Key difference from ReplayContextFeed
    --------------------------------------
    `day_stocks[ticker]` contains only bars received so far (≤ bar_ts), not
    the full day.  All other BarContext fields are byte-identical to
    ReplayContextFeed given the same inputs: hmm_state, cur_vol, spy_or_high,
    spy_or_low, spy_bull_trend, daily_spy_close, universes, VIX gates, etc.
    This is correct for live trading — future bars are genuinely unavailable.
    """

    # Path constants mirror ReplayContextFeed
    _EARNINGS_PATH = ReplayContextFeed._EARNINGS_PATH
    _VIX_PATH      = ReplayContextFeed._VIX_PATH
    _HMM_HIST_PATH = ReplayContextFeed._HMM_HIST_PATH

    def __init__(
        self,
        config: BacktestConfig,
        api_key: str = "",
        daily_data: Optional[Dict[str, pd.DataFrame]] = None,
        pe_short_calendar: Optional[Dict] = None,
        vix_daily: Optional[Dict] = None,
        hmm: Optional[Any] = None,
        emit_timeout: float = 10.0,
        backfill_on_reconnect: bool = True,
        _test_market_data: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> None:
        self._config   = config
        self._api_key  = api_key
        self._daily    = daily_data
        self._hmm_init = hmm
        self._emit_to  = emit_timeout
        self._backfill = backfill_on_reconnect
        self._test_md  = _test_market_data

        if pe_short_calendar is not None:
            self._pe_cal: Dict = pe_short_calendar
        else:
            self._pe_cal = self._load_pe_calendar()

        if vix_daily is not None:
            self._vix_daily: Dict = vix_daily
        else:
            self._vix_daily = self._load_vix_daily()

        _base = _dt(2000, 1, 1, 9, 30)
        _sig  = _base + _td(minutes=config.orb_range_minutes)
        self._orb_signal_start = _sig.time()
        self._orb_signal_end   = (_sig + _td(minutes=30)).time()

    # ── ContextFeed interface ─────────────────────────────────────────────────

    def __iter__(self) -> Iterator[BarContext]:
        if self._test_md is not None:
            yield from self._iter_test()
        else:
            yield from self._iter_live()

    # ── Calendar / VIX loaders (identical logic to ReplayContextFeed) ─────────

    def _load_pe_calendar(self) -> Dict:
        cal: Dict[pd.Timestamp, List[str]] = {}
        if os.path.exists(self._EARNINGS_PATH):
            with open(self._EARNINGS_PATH) as f:
                raw = json.load(f)
            for tk, dates in raw.items():
                for d in dates:
                    cal.setdefault(pd.Timestamp(d), []).append(tk)
        return cal

    def _load_vix_daily(self) -> Dict:
        if os.path.exists(self._VIX_PATH):
            vix_df = pd.read_parquet(self._VIX_PATH)
            vix_df.index = pd.DatetimeIndex(vix_df.index).normalize()
            return vix_df["vix"].to_dict()
        return {}

    def _init_hmm(self, spy_data: pd.DataFrame, bt_start: pd.Timestamp) -> Any:
        """Train HMM the same way ReplayContextFeed does."""
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

    # ── Test / replay mode ────────────────────────────────────────────────────

    def _iter_test(self) -> Iterator[BarContext]:  # noqa: C901
        """Replay _test_market_data as if bars arrived live (no WebSocket)."""
        config    = self._config
        mkt       = self._test_md
        daily     = self._daily
        spy_data  = mkt["SPY"]
        vix_daily = self._vix_daily

        # ── HMM (same initialisation as ReplayContextFeed) ────────────────────
        hmm = self._hmm_init
        if hmm is None:
            bt_start = pd.Timestamp(spy_data.index.normalize().min())
            hmm = self._init_hmm(spy_data, bt_start)

        # ── Scanners ──────────────────────────────────────────────────────────
        from raits.strategies.universe_scanner import (
            DailyUniverseScanner, MRUniverseScanner,
            ORBUniverseScanner, ORBFadeUniverseScanner,
        )
        scanner      = DailyUniverseScanner(top_n=config.scanner_top_n)          if config.use_scanner      and daily else None
        mr_scanner   = MRUniverseScanner(top_n=config.mr_scanner_top_n)          if config.use_mr_scanner   and daily else None
        orb_scanner  = ORBUniverseScanner(top_n=config.orb_scanner_top_n)        if config.use_orb_scanner  and daily else None
        fade_scanner = ORBFadeUniverseScanner(top_n=config.fade_scanner_top_n)   if config.use_fade_scanner and daily else None

        _any_scanner = any(s is not None for s in (scanner, mr_scanner, orb_scanner, fade_scanner))
        spy_daily_dates = (
            sorted(daily["SPY"].index.normalize().unique())
            if _any_scanner and daily and "SPY" in daily else []
        )

        # ── Day calendar ──────────────────────────────────────────────────────
        all_days = pd.DatetimeIndex(spy_data.index.normalize().unique())
        all_days = all_days[
            (all_days >= pd.Timestamp(config.start_date))
            & (all_days <= pd.Timestamp(config.end_date))
        ]

        last_retrain: Optional[pd.Timestamp] = None

        for day in all_days:
            yield from self._iter_test_day(
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

            # ── HMM weekly retrain (mirrors ReplayContextFeed) ────────────────
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

    def _iter_test_day(  # noqa: C901
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

        # ── VIX gates ─────────────────────────────────────────────────────────
        _day_key = day.normalize()
        _day_vix: Optional[float] = (
            float(vix_daily[_day_key]) if _day_key in vix_daily else None
        )
        orb_vix_ok        = (_day_vix is None or _day_vix < 25.0)
        stress_orb_vix_ok = (_day_vix is None or _day_vix >= 30.0)

        # ── Scanner universes (same as ReplayContextFeed._iter_day) ───────────
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

        # ── FADE ATR top-2 ────────────────────────────────────────────────────
        fade_atr_top2: set = set()
        if daily:
            _spy_dd = sorted(daily["SPY"].index.normalize().unique()) if "SPY" in daily else []
            _prev_d = [d for d in _spy_dd if d < day.normalize()]
            if _prev_d:
                fade_atr_top2 = _compute_fade_atr_top2(daily, _prev_d[-1])

        # ── Universe assembly ─────────────────────────────────────────────────
        base_universe = day_universe if day_universe is not None else list(config.universe)
        _scanner_vwap = list(mr_universe) if mr_universe else []
        eff_vwap = _scanner_vwap + [t for t in config.vwap_universe if t not in _scanner_vwap]
        eff_orb  = orb_scanned if orb_scanned is not None else list(config.orb_universe)
        eff_fade = list(fade_scanned) if fade_scanned is not None else []

        all_tickers = (
            base_universe
            + [t for t in eff_orb  if t not in base_universe]
            + [t for t in eff_vwap if t not in base_universe and t not in eff_orb]
            + [t for t in eff_fade if t not in base_universe and t not in eff_orb and t not in eff_vwap]
        )

        # ── SPY day bars ──────────────────────────────────────────────────────
        day_spy = spy_data[spy_data.index.normalize() == day]
        if day_spy.empty:
            return

        # ── Daily SPY close (T-1, same formula as ReplayContextFeed) ──────────
        try:
            daily_spy_close = spy_data["close"].resample("B").last().dropna()
            daily_spy_close = daily_spy_close[
                daily_spy_close.index.normalize() < day.normalize()
            ]
        except Exception:
            daily_spy_close = pd.Series(dtype=float)

        spy_bull_trend = _compute_spy_bull_trend(daily_spy_close)

        # ── Per-bar accumulation ──────────────────────────────────────────────
        # SPY OR window: accumulates as bars arrive (incremental)
        spy_or_high: Optional[float] = None
        spy_or_low:  Optional[float] = None

        hmm_state   = "Normal"
        cur_vol     = 0.20
        _regime_set = False
        spy_history: List[pd.Series] = []

        for bar_ts, spy_bar in day_spy.iterrows():
            # OR window update
            _bt = bar_ts.time()
            if _SPY_OR_START <= _bt <= _SPY_OR_END:
                h = float(spy_bar["high"])
                l = float(spy_bar["low"])
                spy_or_high = max(spy_or_high, h) if spy_or_high is not None else h
                spy_or_low  = min(spy_or_low,  l) if spy_or_low  is not None else l

            spy_history.append(spy_bar)

            # Regime detection once per day
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

            # Incremental day_stocks: only bars up to bar_ts (live semantics)
            day_stocks: Dict[str, pd.DataFrame] = {}
            for ticker in all_tickers:
                if ticker not in mkt or ticker == "SPY":
                    continue
                tkdf = mkt[ticker]
                subset = tkdf[
                    (tkdf.index.normalize() == day) & (tkdf.index <= bar_ts)
                ]
                if not subset.empty:
                    day_stocks[ticker] = subset

            # stress_stocks always uses the full day_spy (same as ReplayContextFeed)
            stress_stocks: Dict[str, pd.DataFrame] = {"SPY": day_spy}
            for _etf in ("QQQ", "IWM"):
                if _etf in day_stocks and not day_stocks[_etf].empty:
                    stress_stocks[_etf] = day_stocks[_etf]

            yield BarContext(
                bar_ts=bar_ts,
                spy_bar=spy_bar,
                spy_history=list(spy_history),
                day_stocks=day_stocks,
                market_data=mkt,
                open_trades=[],
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

    # ── Live WebSocket mode ───────────────────────────────────────────────────

    def _iter_live(self) -> Iterator[BarContext]:  # noqa: C901
        """
        Connect to Polygon WebSocket (lazy-imported), receive AM.* bars, and
        yield BarContext at each RAITS cadence slot.

        Day-level context (universes, VIX gates, HMM state, scanner universes)
        is computed once from `daily_data` at the start of each trading day
        using the same logic as _iter_test_day.

        Bars are accumulated in a _BarAccumulator and emitted when the SPY
        bar for a cadence slot arrives.  Non-SPY bars that arrive before the
        corresponding SPY bar are held and included once SPY arrives.

        Reconnects with exponential backoff on WebSocket disconnect.
        If `backfill_on_reconnect=True`, fetches missing bars via the
        Polygon REST API after each reconnect.

        Requires `daily_data` for scanner universes / fade_atr_top2.
        Without it, universes fall back to config defaults and fade_atr_top2
        is empty.  SPY daily data (daily_data["SPY"]) is also used to compute
        HMM state and cur_vol; without it both default to "Normal" / 0.20.
        """
        import queue as _queue
        import threading as _threading

        config    = self._config
        daily     = self._daily
        vix_daily = self._vix_daily

        _RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]

        # Universe for WebSocket subscription
        all_subscribe: List[str] = list(set(
            list(config.universe)
            + list(getattr(config, "orb_universe",   []))
            + list(getattr(config, "vwap_universe",  []))
            + list(getattr(config, "fade_universe",  []))
            + ["SPY"]
        ))

        # ── Bar queue: WebSocket thread → generator ───────────────────────────
        bar_q: "_queue.Queue" = _queue.Queue()
        stop_event = _threading.Event()

        def _ts_from_ms(utc_ms: int) -> pd.Timestamp:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo
            dt = datetime.fromtimestamp(utc_ms / 1000, tz=timezone.utc)
            dt = dt.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None)
            return pd.Timestamp(dt)

        def _ws_thread() -> None:
            delays = _RECONNECT_DELAYS + [30] * 9999
            d_idx  = 0
            while not stop_event.is_set():
                try:
                    from polygon.websocket import WebSocketClient  # lazy import
                    from polygon.websocket.models import Market

                    client = WebSocketClient(
                        api_key=self._api_key,
                        market=Market.Stocks,
                        subscriptions=[f"AM.{t}" for t in all_subscribe],
                    )

                    def _handle(msgs: List) -> None:
                        for msg in msgs:
                            try:
                                ts  = _ts_from_ms(msg.start_timestamp)
                                row = pd.Series({
                                    "open":   float(msg.open),
                                    "high":   float(msg.high),
                                    "low":    float(msg.low),
                                    "close":  float(msg.close),
                                    "volume": float(msg.volume),
                                }, name=ts)
                                bar_q.put((msg.symbol, ts, row))
                            except Exception as exc:
                                logger.warning(
                                    "Malformed WS bar (ticker=%s): %s",
                                    getattr(msg, "symbol", "?"), exc,
                                )

                    d_idx = 0  # successful connect — reset backoff
                    client.run(_handle)
                    logger.warning(
                        "Polygon WebSocket closed — reconnecting in %ds",
                        delays[d_idx],
                    )
                except ImportError:
                    logger.error(
                        "polygon-api-client not installed; "
                        "LivePolygonFeed requires 'pip install polygon-api-client'"
                    )
                    bar_q.put(None)  # fatal sentinel
                    return
                except Exception as exc:
                    logger.warning(
                        "WS error: %s — reconnecting in %ds", exc, delays[d_idx]
                    )

                if not stop_event.is_set():
                    _threading.Event().wait(delays[min(d_idx, len(delays) - 1)])
                    d_idx = min(d_idx + 1, len(delays) - 1)

        ws_t = _threading.Thread(target=_ws_thread, daemon=True, name="polygon-ws")
        ws_t.start()

        # ── Per-day state ─────────────────────────────────────────────────────
        _cur_day:  Optional[pd.Timestamp] = None
        _acc = _BarAccumulator()

        # day-level fields reset each morning
        _orb_vix_ok        = True
        _stress_orb_vix_ok = False
        _eff_orb:   List[str] = list(getattr(config, "orb_universe",  []))
        _eff_vwap:  List[str] = list(getattr(config, "vwap_universe", []))
        _eff_fade:  List[str] = []
        _all_tickers: List[str] = all_subscribe
        _base_univ:   List[str] = list(config.universe)
        _fade_atr_top2: set = set()
        _daily_spy_close: pd.Series = pd.Series(dtype=float)
        _spy_bull_trend   = True
        _hmm_state  = "Normal"
        _cur_vol    = 0.20
        _orb_high:  Optional[float] = None
        _orb_low:   Optional[float] = None
        _spy_bars_today: Dict[pd.Timestamp, pd.Series] = {}
        _spy_history: List[pd.Series] = []
        _regime_set = False

        # HMM instance (shared across days, retrained weekly if configured)
        _hmm = self._hmm_init
        _last_retrain: Optional[pd.Timestamp] = None

        # ── Scanners (same flags as _iter_test) ──────────────────────────────
        from raits.strategies.universe_scanner import (
            DailyUniverseScanner, MRUniverseScanner,
            ORBUniverseScanner, ORBFadeUniverseScanner,
        )
        _scanner     = DailyUniverseScanner(top_n=config.scanner_top_n)        if config.use_scanner      and daily else None
        _mr_scanner  = MRUniverseScanner(top_n=config.mr_scanner_top_n)        if config.use_mr_scanner   and daily else None
        _orb_scanner = ORBUniverseScanner(top_n=config.orb_scanner_top_n)      if config.use_orb_scanner  and daily else None
        _fd_scanner  = ORBFadeUniverseScanner(top_n=config.fade_scanner_top_n) if config.use_fade_scanner and daily else None
        _spy_dd      = (
            sorted(daily["SPY"].index.normalize().unique())
            if daily and "SPY" in daily else []
        )

        def _setup_day(day: pd.Timestamp) -> None:
            """Compute all day-level context fields when first bar arrives."""
            nonlocal _orb_vix_ok, _stress_orb_vix_ok
            nonlocal _eff_orb, _eff_vwap, _eff_fade, _all_tickers, _base_univ
            nonlocal _fade_atr_top2, _daily_spy_close, _spy_bull_trend
            nonlocal _hmm_state, _cur_vol, _regime_set
            nonlocal _orb_high, _orb_low, _spy_bars_today, _spy_history

            # VIX gates
            _dk = day.normalize()
            _dv = float(vix_daily[_dk]) if _dk in vix_daily else None
            _orb_vix_ok        = (_dv is None or _dv < 25.0)
            _stress_orb_vix_ok = (_dv is None or _dv >= 30.0)

            # Scanners
            def _prev(dates: List) -> Optional[pd.Timestamp]:
                m = [d for d in dates if d < day.normalize()]
                return m[-1] if m else None

            _pd = _prev(_spy_dd) if _spy_dd else None
            if _scanner and _pd:
                du = _scanner.scan(daily, _pd)
            else:
                du = None
            if _mr_scanner and _pd:
                mru = _mr_scanner.scan(daily, _pd)
            else:
                mru = None
            if _orb_scanner and _pd:
                orbs = _orb_scanner.scan(daily, _pd)
            else:
                orbs = None
            if _fd_scanner and _pd:
                fds = _fd_scanner.scan(daily, _pd)
            else:
                fds = None

            _base_univ = du if du is not None else list(config.universe)
            _svwap = list(mru) if mru else []
            _eff_vwap = _svwap + [t for t in config.vwap_universe if t not in _svwap]
            _eff_orb  = orbs if orbs is not None else list(getattr(config, "orb_universe", []))
            _eff_fade = list(fds) if fds is not None else []
            _all_tickers = (
                _base_univ
                + [t for t in _eff_orb  if t not in _base_univ]
                + [t for t in _eff_vwap if t not in _base_univ and t not in _eff_orb]
                + [t for t in _eff_fade if t not in _base_univ and t not in _eff_orb and t not in _eff_vwap]
            )

            # FADE ATR
            if daily:
                _prev_d = [d for d in _spy_dd if d < day.normalize()]
                _fade_atr_top2 = (
                    _compute_fade_atr_top2(daily, _prev_d[-1]) if _prev_d else set()
                )
            else:
                _fade_atr_top2 = set()

            # Daily SPY close
            if daily and "SPY" in daily:
                try:
                    _sc = daily["SPY"]["close"].resample("B").last().dropna()
                    _daily_spy_close = _sc[_sc.index.normalize() < day.normalize()]
                except Exception:
                    _daily_spy_close = pd.Series(dtype=float)
            else:
                _daily_spy_close = pd.Series(dtype=float)
            _spy_bull_trend = _compute_spy_bull_trend(_daily_spy_close)

            # Reset intraday state
            _orb_high        = None
            _orb_low         = None
            _spy_bars_today  = {}
            _spy_history     = []
            _hmm_state       = "Normal"
            _cur_vol         = 0.20
            _regime_set      = False

        def _compute_regime() -> None:
            nonlocal _hmm_state, _cur_vol, _regime_set
            spy_daily: pd.Series = _daily_spy_close
            if _hmm is None or len(spy_daily) < 21:
                _regime_set = True
                return
            try:
                idx = _hmm.predict_current(spy_daily)
                _hmm_state = _hmm.state_name(idx)
                log_ret = np.log(spy_daily / spy_daily.shift(1)).dropna()
                rv = log_ret.rolling(5).std() * np.sqrt(252)
                rv = rv.dropna()
                if len(rv) >= 5:
                    _cur_vol = float(rv.iloc[-1])
                    if _cur_vol >= 0.50:
                        _hmm_state = "Crisis"
            except Exception as e:
                logger.debug("regime detection failed in live mode: %s", e)
            _regime_set = True

        # ── Main generator loop ───────────────────────────────────────────────
        try:
            while True:
                try:
                    item = bar_q.get(timeout=self._emit_to)
                except _queue.Empty:
                    continue

                if item is None:
                    logger.error("LivePolygonFeed: fatal WebSocket error — stopping")
                    break

                ticker, bar_ts, bar_row = item
                bar_day = bar_ts.normalize()

                # Day boundary
                if _cur_day is None or bar_day != _cur_day:
                    if _cur_day is not None:
                        # HMM weekly retrain at day boundary
                        if (config.hmm_retrain_weekly
                                and _cur_day.weekday() == 0
                                and (_last_retrain is None
                                     or (_cur_day - _last_retrain).days >= 7)
                                and _hmm is not None
                                and len(_daily_spy_close) >= 35):
                            try:
                                _hmm.retrain(_daily_spy_close)
                            except Exception as e:
                                logger.debug("HMM retrain failed: %s", e)
                            _last_retrain = _cur_day
                        _acc.reset()
                    _cur_day = bar_day
                    _setup_day(bar_day)

                # Accumulate bar
                if ticker == "SPY":
                    _spy_bars_today[bar_ts] = bar_row
                    _bt = bar_ts.time()
                    if _SPY_OR_START <= _bt <= _SPY_OR_END:
                        h, l = float(bar_row["high"]), float(bar_row["low"])
                        _orb_high = max(_orb_high, h) if _orb_high is not None else h
                        _orb_low  = min(_orb_low,  l) if _orb_low  is not None else l
                    _spy_history_snap = [_spy_bars_today[t] for t in sorted(_spy_bars_today)]

                    if not _regime_set:
                        _compute_regime()

                    # Build day_stocks from accumulator
                    _ds = _acc.get_day_stocks(bar_day, bar_ts)

                    # stress_stocks: SPY uses full day_spy if available; else accumulated
                    _spy_df = pd.DataFrame(
                        [_spy_bars_today[t] for t in sorted(_spy_bars_today)]
                    )
                    if not _spy_df.empty:
                        _spy_df.index = pd.DatetimeIndex(sorted(_spy_bars_today))
                    _ss: Dict[str, pd.DataFrame] = {"SPY": _spy_df}
                    for _etf in ("QQQ", "IWM"):
                        if _etf in _ds and not _ds[_etf].empty:
                            _ss[_etf] = _ds[_etf]

                    yield BarContext(
                        bar_ts=bar_ts,
                        spy_bar=bar_row,
                        spy_history=list(_spy_history_snap),
                        day_stocks=_ds,
                        market_data={},
                        open_trades=[],
                        hmm_state=_hmm_state,
                        cur_vol=_cur_vol,
                        day=_cur_day,
                        orb_vix_ok=_orb_vix_ok,
                        stress_orb_vix_ok=_stress_orb_vix_ok,
                        effective_orb_universe=_eff_orb,
                        effective_vwap_universe=_eff_vwap,
                        effective_fade_universe=_eff_fade,
                        all_tickers=_all_tickers,
                        base_universe=_base_univ,
                        stress_stocks=_ss,
                        spy_or_high=_orb_high,
                        spy_or_low=_orb_low,
                        spy_bull_trend=_spy_bull_trend,
                        daily_spy_close=_daily_spy_close,
                        pe_short_calendar=self._pe_cal,
                        fade_atr_top2=_fade_atr_top2,
                        vwap_bb_std=config.vwap_bb_std,
                        ema_period=config.ema_period,
                        vwap_mr_vol_threshold=config.vwap_mr_vol_threshold,
                        allow_swing_hold=config.allow_swing_hold,
                        enable_pdt_guard=config.enable_pdt_guard,
                        stress_size_fraction=config.stress_size_fraction,
                        orb_signal_start=self._orb_signal_start,
                        orb_signal_end=self._orb_signal_end,
                    )
                else:
                    # Non-SPY bar: add to accumulator for inclusion at next slot
                    _acc.add(ticker, bar_ts, bar_row)

        finally:
            stop_event.set()
