"""
raits/decision/decision_unit.py

DecisionUnit — extracts the per-bar decision logic from BacktestEngine._run_day.

Responsibilities:
  - owns all intraday state (or_ranges, pending_orb, tf_cooldown, …)
  - reset_day(): reset intraday state, reset strategy instances, reset coordinator
  - decide(ctx): run one bar's worth of decision logic; return entries + exits
  - on_trade_opened(trade, intent): register GAP_FILL trailing stop seeds

Does NOT:
  - touch TradeLog (no open_trade / close_trade calls)
  - update equity
  - check circuit breakers for daily drawdown (engine does this)
"""
from __future__ import annotations
import logging
from datetime import time as dtime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .types import BarContext, DecisionResult, EntryIntent, ExitIntent

logger = logging.getLogger("RAITS.decision")

# ── Time constants (copied from engine.py for independence) ──────────────────
ORB_SCAN_TIME       = dtime(9, 35)
ORB_RANGE_START     = dtime(9, 30)
VWAP_MR_START       = dtime(10, 15)
VWAP_MR_END         = dtime(14, 0)
TREND_START         = dtime(14, 0)
EOD_HARD_EXIT       = dtime(15, 55)
GAP_FILL_ENTRY      = dtime(10, 30)
GAP_FILL_EXIT       = dtime(13, 30)
RS_SHORT_ENTRY      = dtime(10, 30)
RS_SHORT_EXIT       = dtime(12, 30)
RS_SHORT_ALPHA      = 0.02
RS_SHORT_ATR_MULT   = 1.5
STRESS_MID_ENTRY    = dtime(10, 15)
STRESS_MID_EXIT     = dtime(14, 0)
STRESS_MID_STOP_PAD = 0.001
STRESS_MID_MAX_STOP = 0.015
PE_SHORT_GAP_MIN    = 0.05
PE_SHORT_STOP_MULT  = 1.5
PE_SHORT_TARGET_RR  = 2.0
MAX_PE_SHORT        = 2

_ETF_STRESS_UNIVERSE = ["SPY", "QQQ", "IWM"]

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
    "GAP_FILL": MAX_GAP_FILL, "GF_SHORT": MAX_GF_SHORT,
    "RS_SHORT": MAX_RS_SHORT, "PE_SHORT": MAX_PE_SHORT,
}
STRATEGY_STATS = {
    "ORB":          {"win_rate": 0.62, "avg_win": 4.50, "avg_loss": 2.00},
    "FADE":         {"win_rate": 0.45, "avg_win": 3.00, "avg_loss": 2.00},
    "VWAP_MR":      {"win_rate": 0.42, "avg_win": 2.80, "avg_loss": 1.50},
    "TREND_FOLLOW": {"win_rate": 0.52, "avg_win": 2.00, "avg_loss": 1.00},
    "GAP_FILL":     {"win_rate": 0.78, "avg_win": 3.00, "avg_loss": 1.50},
    "GF_SHORT":     {"win_rate": 0.40, "avg_win": 3.00, "avg_loss": 1.50},
    "RS_SHORT":     {"win_rate": 0.42, "avg_win": 2.50, "avg_loss": 1.50},
    "STRESS_MID":   {"win_rate": 0.66, "avg_win": 2.00, "avg_loss": 1.00},
    "PE_SHORT":     {"win_rate": 0.72, "avg_win": 2.00, "avg_loss": 1.00},
}
_REGIME_STRATEGIES: Dict[str, List[str]] = {
    "Calm":   ["PE_SHORT"],
    "Normal": ["ORB", "TREND_FOLLOW", "GF_SHORT", "PE_SHORT"],
    "Stress": ["TREND_FOLLOW", "STRESS_ORB", "STRESS_MID", "PE_SHORT"],
    "Crisis": ["PE_SHORT"],
}


class DecisionUnit:
    """
    Wraps strategy + risk instances and exposes a clean per-bar decide() interface.
    Extracts the orchestration from BacktestEngine._run_day without reimplementing
    any strategy math.
    """

    def __init__(
        self,
        config: Any,            # BacktestConfig
        orb: Any,
        stress_orb: Any,
        fade_orb: Any,
        vwap_mr: Any,
        trend: Any,
        coordinator: Any,
        position_sizer: Any,
        pdt_guard: Any,
    ) -> None:
        self.config       = config
        self.orb          = orb
        self.stress_orb   = stress_orb
        self.fade_orb     = fade_orb
        self.vwap_mr      = vwap_mr
        self.trend        = trend
        self.coordinator  = coordinator
        self.position_sizer = position_sizer
        self.pdt_guard    = pdt_guard

        # Cross-day persistent state
        self._tf_cooldown: Dict[str, Dict[str, float]] = {}

        # Intraday state (reset each day)
        self._init_intraday()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _init_intraday(self) -> None:
        self._regime_updated_today  = False
        self.or_ranges: Dict[str, Tuple[float, float]] = {}
        self.pending_orb: Dict[str, dict]              = {}
        self.orb_hist_avg_vol: Dict[str, Any]          = {}
        self.orb_scanned                               = False
        self.fade_scanned_done                         = False
        self.fade_or_ranges: Dict[str, Tuple[float, float]] = {}
        self.pending_fades: Dict[str, dict]            = {}
        self.stress_orb_scanned                        = False
        self.stress_or_ranges: Dict[str, Tuple[float, float]] = {}
        self._gf_triggered   = False
        self._gfs_triggered  = False
        self._rs_triggered   = False
        self._stress_mid_triggered = False
        self._pe_triggered   = False
        self._gf_stop_dists:  Dict[int, float] = {}
        self._gfs_stop_dists: Dict[int, float] = {}
        self._orb_signal_start: dtime = dtime(9, 45)
        self._orb_signal_end:   dtime = dtime(10, 15)

    def reset_day(
        self,
        day: pd.Timestamp,
        orb_signal_start: dtime,
        orb_signal_end: dtime,
    ) -> None:
        """Reset intraday state and strategy instances for a new trading day."""
        self._init_intraday()
        self._orb_signal_start = orb_signal_start
        self._orb_signal_end   = orb_signal_end

        self.orb.reset()
        self.stress_orb.reset()
        self.fade_orb.reset()
        if hasattr(self.vwap_mr, "reset"):
            self.vwap_mr.reset()
        if hasattr(self.trend, "reset"):
            self.trend.reset()
        try:
            self.coordinator.reset_for_new_session(day.to_pydatetime())
        except Exception:
            pass

    def on_trade_opened(self, trade: Any, intent: EntryIntent) -> None:
        """Called by engine after trade_log.open_trade() to register trailing stop seeds."""
        if intent.gf_stop_dist is not None:
            if intent.strategy == "GAP_FILL":
                self._gf_stop_dists[id(trade)] = intent.gf_stop_dist
            elif intent.strategy == "GF_SHORT":
                self._gfs_stop_dists[id(trade)] = intent.gf_stop_dist

    # ── Main per-bar decision ──────────────────────────────────────────────────

    def decide(self, ctx: BarContext) -> DecisionResult:
        """
        Process one 5-min bar and return entries + exits.
        May mutate trade.stop in place (GAP_FILL chandelier trailing stops).
        Does NOT open or close any trades.
        """
        entries: List[EntryIntent] = []
        exits:   List[ExitIntent]  = []
        pending_entries: List[EntryIntent] = []  # entries decided this bar (for position count)

        bar_ts = ctx.bar_ts
        bar_t  = bar_ts.time()
        bar_dt = bar_ts.to_pydatetime()
        orb_signal_start = self._orb_signal_start
        orb_signal_end   = self._orb_signal_end

        # ── 1. Notify coordinator of regime (once per day, first bar) ─────────
        if not self._regime_updated_today:
            try:
                self.coordinator.notify_hmm_state(ctx.hmm_state, bar_dt)
            except Exception:
                pass
            self._regime_updated_today = True

        # ── 2. Swing exit checks (TF, PE_SHORT) — before trading_ok gate ──────
        for trade in list(ctx.open_trades):
            if trade.strategy not in ("TREND_FOLLOW", "PE_SHORT"):
                continue
            res = self._check_exits(trade, bar_ts, bar_t, ctx.day_stocks,
                                    ctx.allow_swing_hold)
            if res:
                exit_price, reason = res
                if reason == "STOP_HIT" and trade.strategy == "TREND_FOLLOW":
                    self._tf_cooldown.setdefault(trade.ticker, {})[trade.direction] = trade.stop
                exits.append(ExitIntent(trade=trade, exit_price=exit_price, reason=reason))

        # ── 3. Layer 0 override ───────────────────────────────────────────────
        override = self._check_layer0(ctx.spy_history)
        try:
            self.coordinator.notify_override(override, bar_dt)
        except Exception:
            pass

        # ── 4. Trading allowed? ───────────────────────────────────────────────
        try:
            trading_ok = self.coordinator.trading_allowed
        except Exception:
            trading_ok = not (override or ctx.hmm_state == "Stress")

        if not trading_ok:
            for trade in list(ctx.open_trades):
                if trade.strategy in ("TREND_FOLLOW", "PE_SHORT"):
                    continue
                price = self._last_close_price(trade, bar_ts, ctx.day_stocks)
                exits.append(ExitIntent(trade=trade, exit_price=price, reason="SAFETY_MODE"))
            return DecisionResult(entries=[], exits=exits, override_active=True)

        # ── 4b. Active strategies for this regime ─────────────────────────────
        try:
            effective = self.coordinator.effective_hmm_state
        except Exception:
            effective = ctx.hmm_state
        active = _REGIME_STRATEGIES.get(effective, [])

        # ── 5. ORB scanner at 9:35 ────────────────────────────────────────────
        if bar_t == ORB_SCAN_TIME and not self.orb_scanned and "ORB" in active:
            candidates = self._build_orb_candidates(
                ctx.day_stocks, ctx.market_data, ctx.day, ctx.effective_orb_universe
            )
            try:
                self.orb.run_scanner(candidates)
            except Exception as e:
                logger.debug(f"ORB scanner error: {e}")
            self.orb_hist_avg_vol = {
                c["ticker"]: c.get("avg_vol_by_time", {}) for c in candidates
            }
            self.orb_scanned = True

        # ── 5b. FADE scanner at 9:35 ─────────────────────────────────────────
        if (bar_t == ORB_SCAN_TIME and not self.fade_scanned_done
                and "FADE" in active and ctx.effective_fade_universe):
            fade_cands = self._build_orb_candidates(
                ctx.day_stocks, ctx.market_data, ctx.day,
                ctx.effective_fade_universe, skip_gap_filter=True
            )
            try:
                self.fade_orb.run_scanner(fade_cands)
            except Exception as e:
                logger.debug(f"FADE scanner error: {e}")
            self.fade_scanned_done = True

        # ── 6. ORB range formation 9:30–signal_start ─────────────────────────
        if ORB_RANGE_START <= bar_t < orb_signal_start and "ORB" in active and ctx.orb_vix_ok:
            for ticker in self.orb.watchlist:
                if ticker not in ctx.day_stocks:
                    continue
                bars_so_far = ctx.day_stocks[ticker].loc[:bar_ts]
                if len(bars_so_far) < 2:
                    continue
                atr = self._compute_atr(bars_so_far)
                try:
                    or_high, or_low, status = self.orb.calculate_opening_range(bars_so_far, atr)
                    if status == "VALID":
                        self.or_ranges[ticker] = (or_high, or_low)
                except Exception as e:
                    logger.debug(f"OR calc error {ticker}: {e}")

        # ── 6a. FADE OR range formation ───────────────────────────────────────
        if ORB_RANGE_START <= bar_t < orb_signal_start and "FADE" in active:
            for ticker in self.fade_orb.watchlist:
                if ticker not in ctx.day_stocks:
                    continue
                bars_so_far = ctx.day_stocks[ticker].loc[:bar_ts]
                if len(bars_so_far) < 2:
                    continue
                atr = self._compute_atr(bars_so_far)
                try:
                    or_high, or_low, status = self.fade_orb.calculate_opening_range(bars_so_far, atr)
                    if status == "VALID":
                        self.fade_or_ranges[ticker] = (or_high, or_low)
                except Exception as e:
                    logger.debug(f"FADE OR calc error {ticker}: {e}")

        # ── 6b. ORB delayed-entry confirm ─────────────────────────────────────
        if orb_signal_start < bar_t <= orb_signal_end and "ORB" in active and self.pending_orb:
            for _pticker, _psig in list(self.pending_orb.items()):
                self.pending_orb.pop(_pticker)
                if _pticker not in self.or_ranges or _pticker not in ctx.day_stocks:
                    continue
                _pbars = ctx.day_stocks[_pticker].loc[:bar_ts]
                if _pbars.empty:
                    continue
                try:
                    _pcandle = _pbars.iloc[-1]
                    _por_high, _por_low = self.or_ranges[_pticker]
                    _result = self.orb.confirm_or_cancel(_pcandle, _por_high, _por_low, _psig)
                    if not _result or _result.get("type") == "FADE":
                        continue
                    if not ctx.spy_bull_trend:
                        continue
                    if not self._position_ok(_pticker, "ORB", ctx.open_trades, pending_entries):
                        continue
                    _result = self._normalise_signal(_result)
                    self._attempt_entry(_result, _pticker, "ORB", bar_ts,
                                        ctx, pending_entries, entries)
                except Exception as e:
                    logger.debug(f"ORB confirm error {_pticker}: {e}")

        # ── 6c. FADE delayed-entry confirm ────────────────────────────────────
        if orb_signal_start < bar_t <= orb_signal_end and "FADE" in active and self.pending_fades:
            for _fticker, _fsig in list(self.pending_fades.items()):
                self.pending_fades.pop(_fticker)
                if _fticker not in self.fade_or_ranges or _fticker not in ctx.day_stocks:
                    continue
                _fbars = ctx.day_stocks[_fticker].loc[:bar_ts]
                if _fbars.empty:
                    continue
                try:
                    _fcandle = _fbars.iloc[-1]
                    _for_high, _for_low = self.fade_or_ranges[_fticker]
                    _fresult = self.fade_orb.confirm_or_cancel(_fcandle, _for_high, _for_low, _fsig)
                    if not _fresult or _fresult.get("type") != "FADE":
                        continue
                    _fade_dir = _fresult.get("direction", "")
                    if _fade_dir == "SHORT" and ctx.spy_or_high is not None:
                        _spy_now = [b for b in ctx.spy_history if pd.Timestamp(b.name) <= bar_ts]
                        if _spy_now and float(_spy_now[-1]["close"]) > ctx.spy_or_high:
                            continue
                    if _fade_dir == "LONG" and _fticker in ctx.fade_atr_top2:
                        continue
                    if not self._position_ok(_fticker, "FADE", ctx.open_trades, pending_entries):
                        continue
                    _fresult = self._normalise_signal(_fresult)
                    self._attempt_entry(_fresult, _fticker, "FADE", bar_ts,
                                        ctx, pending_entries, entries)
                except Exception as e:
                    logger.debug(f"FADE confirm error {_fticker}: {e}")

        # ── 7. ORB signals (detect breakouts → pending) ────────────────────────
        if orb_signal_start <= bar_t <= orb_signal_end and "ORB" in active and ctx.orb_vix_ok:
            for ticker, (or_high, or_low) in list(self.or_ranges.items()):
                if ticker in self.pending_orb:
                    continue
                if not self._position_ok(ticker, "ORB", ctx.open_trades, pending_entries):
                    continue
                if ticker not in ctx.day_stocks:
                    continue
                bars_so_far = ctx.day_stocks[ticker].loc[:bar_ts]
                if bars_so_far.empty:
                    continue
                try:
                    candle   = bars_so_far.iloc[-1]
                    vwap_val = self.vwap_mr.calculate_vwap(bars_so_far)
                    _time_avgs = self.orb_hist_avg_vol.get(ticker, {})
                    _slot_avg  = _time_avgs.get(bar_ts.time(), 0.0) if isinstance(_time_avgs, dict) else 0.0
                    hist_avg   = max(_slot_avg if _slot_avg > 0 else float(bars_so_far["volume"].mean()), 1.0)
                    rvol       = self.orb.calculate_intraday_rvol(int(candle["volume"]), hist_avg)
                    sig = self.orb.generate_signal(candle, or_high, or_low, vwap_val, rvol, ctx.hmm_state)
                    if sig:
                        if not ctx.spy_bull_trend:
                            continue
                        self.pending_orb[ticker] = sig
                except Exception as e:
                    logger.debug(f"ORB signal error {ticker}: {e}")

        # ── 7b. FADE signals ──────────────────────────────────────────────────
        if orb_signal_start <= bar_t <= orb_signal_end and "FADE" in active:
            for ticker, (or_high, or_low) in list(self.fade_or_ranges.items()):
                if ticker in self.pending_fades:
                    continue
                if not self._position_ok(ticker, "FADE", ctx.open_trades, pending_entries):
                    continue
                if ticker not in ctx.day_stocks:
                    continue
                bars_so_far = ctx.day_stocks[ticker].loc[:bar_ts]
                if bars_so_far.empty:
                    continue
                try:
                    candle   = bars_so_far.iloc[-1]
                    vwap_val = self.vwap_mr.calculate_vwap(bars_so_far)
                    hist_avg = max(float(bars_so_far["volume"].mean()), 1.0)
                    rvol     = self.fade_orb.calculate_intraday_rvol(int(candle["volume"]), hist_avg)
                    sig = self.fade_orb.generate_signal(candle, or_high, or_low, vwap_val, rvol, ctx.hmm_state)
                    if sig:
                        self.pending_fades[ticker] = sig
                except Exception as e:
                    logger.debug(f"FADE signal error {ticker}: {e}")

        # ── 7c. STRESS_ORB scanner at 9:35 ────────────────────────────────────
        if (bar_t == ORB_SCAN_TIME and not self.stress_orb_scanned
                and "STRESS_ORB" in active and ctx.stress_orb_vix_ok):
            self.stress_orb.watchlist = list(ctx.stress_stocks.keys())
            self.stress_orb_scanned = True

        # ── 7c'. STRESS_ORB OR range formation ───────────────────────────────
        if (ORB_RANGE_START <= bar_t < orb_signal_start
                and "STRESS_ORB" in active and ctx.stress_orb_vix_ok):
            for ticker in self.stress_orb.watchlist:
                if ticker not in ctx.stress_stocks:
                    continue
                bars_so_far = ctx.stress_stocks[ticker].loc[:bar_ts]
                if len(bars_so_far) < 2:
                    continue
                atr = self._compute_atr(bars_so_far)
                try:
                    or_high, or_low, status = self.stress_orb.calculate_opening_range(bars_so_far, atr)
                    if status == "VALID":
                        self.stress_or_ranges[ticker] = (or_high, or_low)
                except Exception as e:
                    logger.debug(f"Stress OR calc error {ticker}: {e}")

        # ── 7d. STRESS_ORB signals ────────────────────────────────────────────
        if (orb_signal_start <= bar_t <= orb_signal_end
                and "STRESS_ORB" in active and ctx.stress_orb_vix_ok):
            for ticker, (or_high, or_low) in list(self.stress_or_ranges.items()):
                if not self._position_ok(ticker, "STRESS_ORB", ctx.open_trades, pending_entries):
                    continue
                if ticker not in ctx.stress_stocks:
                    continue
                bars_so_far = ctx.stress_stocks[ticker].loc[:bar_ts]
                if bars_so_far.empty:
                    continue
                try:
                    candle   = bars_so_far.iloc[-1]
                    vwap_val = self.vwap_mr.calculate_vwap(bars_so_far)
                    hist_avg = max(float(bars_so_far["volume"].mean()), 1.0)
                    rvol     = self.stress_orb.calculate_intraday_rvol(int(candle["volume"]), hist_avg)
                    sig = self.stress_orb.generate_signal(candle, or_high, or_low, vwap_val, rvol, ctx.hmm_state)
                    if sig:
                        if sig.get("direction") == "LONG":
                            continue
                        sig = self._normalise_signal(sig)
                        self._attempt_entry(sig, ticker, "STRESS_ORB", bar_ts,
                                            ctx, pending_entries, entries)
                except Exception as e:
                    logger.debug(f"Stress ORB signal error {ticker}: {e}")

        # ── 7e. STRESS_MID at 10:15 ───────────────────────────────────────────
        if bar_t == STRESS_MID_ENTRY and not self._stress_mid_triggered and "STRESS_MID" in active:
            self._stress_mid_triggered = True
            _sm_setups = []
            for _sm_ticker in _ETF_STRESS_UNIVERSE:
                _sm_all = ctx.stress_stocks.get(_sm_ticker, pd.DataFrame())
                if _sm_all.empty:
                    continue
                _sm_bars = _sm_all[_sm_all.index <= bar_ts]
                if len(_sm_bars) < 3:
                    continue
                try:
                    _sm_entry = float(_sm_bars.iloc[-1]["close"])
                    _sm_open  = float(_sm_bars.iloc[0]["open"])
                    _sm_vwap  = self.vwap_mr.calculate_vwap(_sm_bars)
                    if _sm_entry >= _sm_vwap or _sm_entry >= _sm_open:
                        continue
                    _sm_swing = _sm_bars[_sm_bars.index.time >= dtime(9, 45)]
                    if _sm_swing.empty:
                        continue
                    _sm_stop  = float(_sm_swing["high"].max()) * (1 + STRESS_MID_STOP_PAD)
                    _sm_sdist = _sm_stop - _sm_entry
                    if _sm_sdist <= 0 or _sm_sdist / _sm_entry > STRESS_MID_MAX_STOP:
                        continue
                    _sm_setups.append({
                        "ticker":   _sm_ticker,
                        "entry_px": _sm_entry,
                        "stop":     _sm_stop,
                        "target":   _sm_entry - 2.0 * _sm_sdist,
                        "vwap_gap": _sm_vwap - _sm_entry,
                    })
                except Exception as e:
                    logger.debug(f"STRESS_MID error {_sm_ticker}: {e}")
            _sm_setups.sort(key=lambda x: -x["vwap_gap"])
            for _sm in _sm_setups:
                if not self._position_ok(_sm["ticker"], "STRESS_MID", ctx.open_trades, pending_entries):
                    continue
                sig = {
                    "direction": "SHORT", "entry_price": _sm["entry_px"],
                    "stop": _sm["stop"], "target": _sm["target"], "is_day_trade": True,
                }
                self._attempt_entry(sig, _sm["ticker"], "STRESS_MID", bar_ts,
                                    ctx, pending_entries, entries)

        # ── 7f. PE_SHORT at 9:30 ─────────────────────────────────────────────
        if bar_t == dtime(9, 30) and not self._pe_triggered:
            self._pe_triggered = True
            _pe_today = ctx.pe_short_calendar.get(ctx.day.normalize(), [])
            for _pe_ticker in _pe_today:
                if _pe_ticker not in ctx.market_data:
                    continue
                if not self._position_ok(_pe_ticker, "PE_SHORT", ctx.open_trades, pending_entries):
                    continue
                # Inject into ctx.day_stocks so exit checks work for the rest of
                # today. engine.py writes day_stocks[_pe_ticker] in-place; a local
                # copy (_pe_day_stocks = dict(...)) is discarded after this bar and
                # section 2 on the next bar finds no GE — missing the stop hit.
                if _pe_ticker not in ctx.day_stocks:
                    _pe_bars_today = ctx.market_data[_pe_ticker][
                        ctx.market_data[_pe_ticker].index.normalize() == ctx.day
                    ]
                    if not _pe_bars_today.empty:
                        ctx.day_stocks[_pe_ticker] = _pe_bars_today
                if _pe_ticker not in ctx.day_stocks:
                    continue
                try:
                    _pe_today_bars = ctx.day_stocks[_pe_ticker]
                    _pe_first = _pe_today_bars[_pe_today_bars.index.time >= dtime(9, 30)]
                    if _pe_first.empty:
                        continue
                    _pe_open = float(_pe_first.iloc[0]["open"])
                    _pe_prev = ctx.market_data[_pe_ticker][
                        ctx.market_data[_pe_ticker].index.normalize() < ctx.day
                    ]
                    if _pe_prev.empty:
                        continue
                    _pe_prev_close = float(_pe_prev["close"].iloc[-1])
                    if _pe_prev_close <= 0:
                        continue
                    _pe_gap = (_pe_open - _pe_prev_close) / _pe_prev_close
                    if _pe_gap >= -PE_SHORT_GAP_MIN:
                        continue
                    _pe_atr = self._compute_daily_atr(ctx.market_data, _pe_ticker, ctx.day)
                    if _pe_atr <= 0:
                        continue
                    _pe_stop_dist = PE_SHORT_STOP_MULT * _pe_atr
                    _pe_sig = {
                        "direction": "SHORT", "entry_price": _pe_open,
                        "stop":   round(_pe_open + _pe_stop_dist, 2),
                        "target": round(_pe_open - PE_SHORT_TARGET_RR * _pe_stop_dist, 2),
                        "is_day_trade": False,
                    }
                    self._attempt_entry(_pe_sig, _pe_ticker, "PE_SHORT", bar_ts,
                                        ctx, pending_entries, entries)
                except Exception as _pe_err:
                    logger.debug(f"PE_SHORT error {_pe_ticker}: {_pe_err}")

        # ── 8. VWAP MR 10:15–14:00 ────────────────────────────────────────────
        _vwap_mr_vol_ok    = ctx.cur_vol <= ctx.vwap_mr_vol_threshold
        _vwap_mr_regime_ok = "VWAP_MR" in _REGIME_STRATEGIES.get(ctx.hmm_state, [])
        if (VWAP_MR_START <= bar_t < VWAP_MR_END
                and _vwap_mr_vol_ok and _vwap_mr_regime_ok
                and (ctx.effective_vwap_universe)):
            vwap_cands = self._build_vwap_candidates(
                ctx.day_stocks, bar_ts, ctx.effective_vwap_universe
            )
            self.vwap_mr.run_scanner(vwap_cands)
            for ticker in self.vwap_mr.watchlist:
                if not self._position_ok(ticker, "VWAP_MR", ctx.open_trades, pending_entries):
                    continue
                if ticker not in ctx.day_stocks:
                    continue
                bars_so_far = ctx.day_stocks[ticker].loc[:bar_ts]
                if len(bars_so_far) < 22:
                    continue
                try:
                    bb_upper, _, bb_lower = self.vwap_mr.calculate_bollinger_bands(
                        bars_so_far.iloc[:-1], period=20, std_dev=ctx.vwap_bb_std,
                    )
                    vwap_val  = self.vwap_mr.calculate_vwap(bars_so_far)
                    atr       = self._compute_atr(bars_so_far)
                    prev_bar  = bars_so_far.iloc[-2]
                    entry_bar = bars_so_far.iloc[-1]
                    sig = self.vwap_mr.generate_signal(
                        prev_bar, entry_bar, bb_upper, bb_lower, vwap_val, atr, "Calm"
                    )
                    if sig:
                        # F2: skip SHORT when SPY > VWAP after 12:30
                        if sig.get("direction") == "SHORT" and bar_t >= dtime(12, 30):
                            _spy_pre = ctx.day_stocks.get("SPY") or ctx.stress_stocks.get("SPY")
                            if _spy_pre is not None and not _spy_pre.empty:
                                _spy_slice = _spy_pre.loc[_spy_pre.index <= bar_ts]
                                if not _spy_slice.empty:
                                    _spy_vwap_f2 = self.vwap_mr.calculate_vwap(_spy_slice)
                                    _spy_close_f2 = float(_spy_slice.iloc[-1]["close"])
                                    if _spy_vwap_f2 is not None and _spy_close_f2 > _spy_vwap_f2:
                                        continue
                        # F3: skip LONG 12:00-13:00
                        if sig.get("direction") == "LONG" and dtime(12, 0) <= bar_t < dtime(13, 0):
                            continue
                        sig = self._normalise_signal(sig)
                        self._attempt_entry(sig, ticker, "VWAP_MR", bar_ts,
                                            ctx, pending_entries, entries)
                except Exception as e:
                    logger.debug(f"VWAP MR error {ticker}: {e}")

        # ── 8b. GAP_FILL LONG at 10:30 ────────────────────────────────────────
        if bar_t == GAP_FILL_ENTRY and not self._gf_triggered and "GAP_FILL" in active:
            self._gf_triggered = True
            # Use actual DataFrame (not list) for SPY VWAP calculation
            _spy_df_gf = ctx.day_stocks.get("SPY") or ctx.stress_stocks.get("SPY")
            if _spy_df_gf is not None and not _spy_df_gf.empty:
                _spy_bars_pre = _spy_df_gf.loc[_spy_df_gf.index <= bar_ts]
                _spy_vwap = self.vwap_mr.calculate_vwap(_spy_bars_pre) if not _spy_bars_pre.empty else None
                _spy_above_vwap = (
                    _spy_vwap is not None and not _spy_bars_pre.empty
                    and float(_spy_bars_pre.iloc[-1]["close"]) > _spy_vwap
                )
            else:
                # Fall back to spy_history list
                _spy_bars_pre_list = [b for b in ctx.spy_history if pd.Timestamp(b.name) <= bar_ts]
                _spy_df_fallback = pd.DataFrame(_spy_bars_pre_list) if _spy_bars_pre_list else pd.DataFrame()
                _spy_vwap = self.vwap_mr.calculate_vwap(_spy_df_fallback) if not _spy_df_fallback.empty else None
                _spy_above_vwap = (
                    _spy_vwap is not None and _spy_bars_pre_list
                    and float(_spy_bars_pre_list[-1]["close"]) > _spy_vwap
                )
            if _spy_above_vwap:
                for ticker in ctx.all_tickers:
                    if ticker == "SPY":
                        continue
                    if not self._position_ok(ticker, "GAP_FILL", ctx.open_trades, pending_entries):
                        continue
                    if ticker not in ctx.day_stocks:
                        continue
                    _gf_day_bars = ctx.day_stocks[ticker]
                    bars_pre = _gf_day_bars[_gf_day_bars.index <= bar_ts]
                    if len(bars_pre) < 4:
                        continue
                    try:
                        first_bar = bars_pre[bars_pre.index.time >= dtime(9, 30)]
                        if first_bar.empty:
                            continue
                        session_open = float(first_bar.iloc[0]["open"])
                        _prev_bars = ctx.market_data[ticker][
                            ctx.market_data[ticker].index.normalize() < ctx.day
                        ]
                        if _prev_bars.empty:
                            continue
                        prev_c = float(_prev_bars["close"].iloc[-1])
                        if prev_c <= 0:
                            continue
                        gap_pct  = (session_open - prev_c) / prev_c
                        gap_size = session_open - prev_c
                        if gap_pct >= 0 or abs(gap_pct) < 0.015 or abs(gap_pct) > 0.03:
                            continue
                        px_1030  = float(bars_pre.iloc[-1]["close"])
                        retrace  = (session_open - px_1030) / gap_size
                        if not (0.50 <= retrace <= 0.85):
                            continue
                        morning_lod = float(bars_pre["low"].min())
                        atr = self._compute_atr(bars_pre)
                        if atr <= 0:
                            continue
                        stop_px   = morning_lod - 0.1 * atr
                        stop_dist = abs(px_1030 - stop_px)
                        if stop_dist <= 0:
                            continue
                        target_px = prev_c + 0.50 * abs(gap_size)
                        sig = {
                            "direction": "LONG", "entry_price": px_1030,
                            "stop": stop_px, "target": target_px, "is_day_trade": True,
                        }
                        self._attempt_entry(sig, ticker, "GAP_FILL", bar_ts,
                                            ctx, pending_entries, entries,
                                            gf_stop_dist=stop_dist)
                    except Exception as e:
                        logger.debug(f"GAP_FILL entry error {ticker}: {e}")

        # ── 8c. GF_SHORT at 10:30 ────────────────────────────────────────────
        if bar_t == GAP_FILL_ENTRY and not self._gfs_triggered and "GF_SHORT" in active:
            self._gfs_triggered = True
            # Use actual DataFrame (not list) for SPY VWAP calculation
            _spy_df_gfs = ctx.day_stocks.get("SPY") or ctx.stress_stocks.get("SPY")
            if _spy_df_gfs is not None and not _spy_df_gfs.empty:
                _spy_bars_pre_s = _spy_df_gfs.loc[_spy_df_gfs.index <= bar_ts]
                _spy_vwap_s = self.vwap_mr.calculate_vwap(_spy_bars_pre_s) if not _spy_bars_pre_s.empty else None
                _spy_below_vwap = (
                    _spy_vwap_s is not None and not _spy_bars_pre_s.empty
                    and float(_spy_bars_pre_s.iloc[-1]["close"]) < _spy_vwap_s
                )
            else:
                # Fall back to spy_history list
                _spy_bars_pre_s_list = [b for b in ctx.spy_history if pd.Timestamp(b.name) <= bar_ts]
                _spy_df_s_fallback = pd.DataFrame(_spy_bars_pre_s_list) if _spy_bars_pre_s_list else pd.DataFrame()
                _spy_vwap_s = self.vwap_mr.calculate_vwap(_spy_df_s_fallback) if not _spy_df_s_fallback.empty else None
                _spy_below_vwap = (
                    _spy_vwap_s is not None and _spy_bars_pre_s_list
                    and float(_spy_bars_pre_s_list[-1]["close"]) < _spy_vwap_s
                )
            if _spy_below_vwap:
                for ticker in ctx.all_tickers:
                    if ticker == "SPY":
                        continue
                    if not self._position_ok(ticker, "GF_SHORT", ctx.open_trades, pending_entries):
                        continue
                    if ticker not in ctx.day_stocks:
                        continue
                    _gfs_day_bars = ctx.day_stocks[ticker]
                    bars_pre = _gfs_day_bars[_gfs_day_bars.index <= bar_ts]
                    if len(bars_pre) < 4:
                        continue
                    try:
                        first_bar = bars_pre[bars_pre.index.time >= dtime(9, 30)]
                        if first_bar.empty:
                            continue
                        session_open = float(first_bar.iloc[0]["open"])
                        _prev_bars = ctx.market_data[ticker][
                            ctx.market_data[ticker].index.normalize() < ctx.day
                        ]
                        if _prev_bars.empty:
                            continue
                        prev_c = float(_prev_bars["close"].iloc[-1])
                        if prev_c <= 0:
                            continue
                        gap_pct  = (session_open - prev_c) / prev_c
                        gap_size = session_open - prev_c
                        if gap_pct <= 0 or abs(gap_pct) < 0.015 or abs(gap_pct) > 0.03:
                            continue
                        px_1030  = float(bars_pre.iloc[-1]["close"])
                        retrace  = (session_open - px_1030) / gap_size
                        if not (0.50 <= retrace <= 0.85):
                            continue
                        morning_hod = float(bars_pre["high"].max())
                        atr = self._compute_atr(bars_pre)
                        if atr <= 0:
                            continue
                        stop_px   = morning_hod + 0.1 * atr
                        stop_dist = abs(stop_px - px_1030)
                        if stop_dist <= 0:
                            continue
                        target_px = prev_c - 0.50 * abs(gap_size)
                        sig = {
                            "direction": "SHORT", "entry_price": px_1030,
                            "stop": stop_px, "target": target_px, "is_day_trade": True,
                        }
                        self._attempt_entry(sig, ticker, "GF_SHORT", bar_ts,
                                            ctx, pending_entries, entries,
                                            gf_stop_dist=stop_dist)
                    except Exception as e:
                        logger.debug(f"GF_SHORT entry error {ticker}: {e}")

        # ── 8d. RS_SHORT at 10:30 ────────────────────────────────────────────
        if bar_t == RS_SHORT_ENTRY and not self._rs_triggered and "RS_SHORT" in active:
            self._rs_triggered = True
            spy_open_bars = [b for b in ctx.spy_history if b.name.time() >= dtime(9, 30)]
            if spy_open_bars:
                _spy_open_px = float(spy_open_bars[0]["open"])
                _spy_now_px  = float(ctx.spy_bar["close"])
                _spy_ret     = (_spy_now_px - _spy_open_px) / _spy_open_px if _spy_open_px > 0 else 0.0
                _rs_candidates = []
                for ticker in ctx.all_tickers:
                    if ticker not in ctx.day_stocks:
                        continue
                    bars_pre = ctx.day_stocks[ticker].loc[:bar_ts]
                    if len(bars_pre) < 4:
                        continue
                    try:
                        first_bar = bars_pre[bars_pre.index.time >= dtime(9, 30)]
                        if first_bar.empty:
                            continue
                        stk_open = float(first_bar.iloc[0]["open"])
                        stk_now  = float(bars_pre.iloc[-1]["close"])
                        stk_ret  = (stk_now - stk_open) / stk_open if stk_open > 0 else 0.0
                        alpha    = stk_ret - _spy_ret
                        if alpha > -RS_SHORT_ALPHA:
                            continue
                        atr = self._compute_atr(bars_pre)
                        if atr <= 0:
                            continue
                        _rs_candidates.append((alpha, ticker, stk_now, atr))
                    except Exception as e:
                        logger.debug(f"RS_SHORT scan error {ticker}: {e}")
                _rs_candidates.sort(key=lambda x: x[0])
                for _alpha_val, ticker, entry_px, atr in _rs_candidates[:1]:
                    if not self._position_ok(ticker, "RS_SHORT", ctx.open_trades, pending_entries):
                        continue
                    stop_px   = entry_px + RS_SHORT_ATR_MULT * atr
                    target_px = entry_px * 0.70
                    sig = {
                        "direction": "SHORT", "entry_price": entry_px,
                        "stop": stop_px, "target": target_px, "is_day_trade": True,
                    }
                    self._attempt_entry(sig, ticker, "RS_SHORT", bar_ts,
                                        ctx, pending_entries, entries)

        # ── 9. TREND_FOLLOW 14:00–15:55 ──────────────────────────────────────
        if TREND_START <= bar_t < EOD_HARD_EXIT and "TREND_FOLLOW" in active:
            if bar_t == TREND_START:
                sector_str = self._compute_sector_strength(ctx.day_stocks, bar_ts, ctx.base_universe)
                trend_eligible = list(ctx.base_universe) + [
                    t for t in ctx.effective_orb_universe if t not in ctx.base_universe
                ]
                trend_cands = self._build_trend_candidates(
                    ctx.day_stocks, bar_ts, trend_eligible, sector_str
                )
                self.trend.run_scanner(trend_cands)

            # Mirror engine.py: _close_trade() removes trade from live log BEFORE
            # section-9 position check. Replicate by excluding already-queued exits
            # so _position_ok sees the post-exit open count, not the pre-exit snapshot.
            _exited_ids = {id(e.trade) for e in exits}
            _effective_open = [t for t in ctx.open_trades if id(t) not in _exited_ids]

            # TRACE: dump capacity+cooldown state at 2017-02-07 14:00 only
            _TRACE_BAR = (bar_ts.year == 2017 and bar_ts.month == 2 and bar_ts.day == 7 and bar_ts.hour == 14 and bar_ts.minute == 0)
            if _TRACE_BAR:
                print(f"\n[DU_TRACE] *** bar_ts={bar_ts} ***", flush=True)
                print(f"[DU_TRACE] open_trades={len(ctx.open_trades)} exits_sec2={len(exits)} effective_open={len(_effective_open)} pending_start={len(pending_entries)}", flush=True)
                print(f"[DU_TRACE] effective_open tickers: {[t.ticker for t in _effective_open]}", flush=True)
                print(f"[DU_TRACE] _tf_cooldown state: {dict(self._tf_cooldown)}", flush=True)
                print(f"[DU_TRACE] watchlist ({len(self.trend.watchlist)}): {self.trend.watchlist}", flush=True)

            for ticker in self.trend.watchlist:
                _pos_ok = self._position_ok(ticker, "TREND_FOLLOW", _effective_open, pending_entries)
                if _TRACE_BAR:
                    _tot = len(_effective_open) + len(pending_entries)
                    _sc  = (sum(1 for t in _effective_open if t.strategy=="TREND_FOLLOW")
                            + sum(1 for e in pending_entries if e.strategy=="TREND_FOLLOW"))
                    if not _pos_ok:
                        print(f">>> TF_BLOCK_CAP {ticker} total={_tot} tf_strat={_sc}", flush=True)
                    else:
                        print(f"[DU_TRACE]   check {ticker}: pos_ok=True total={_tot} tf_strat={_sc}", flush=True)
                if not _pos_ok:
                    continue
                if ticker not in ctx.day_stocks:
                    continue
                bars_so_far = ctx.day_stocks[ticker].loc[:bar_ts]
                if len(bars_so_far) < 3:
                    continue
                try:
                    ema_val    = self.trend.calculate_ema(bars_so_far, period=ctx.ema_period)
                    atr        = self._compute_atr(bars_so_far)
                    avg_vol_10 = float(bars_so_far["volume"].tail(10).mean()) or 1.0
                    pb_bar     = bars_so_far.iloc[-2]
                    res_bar    = bars_so_far.iloc[-1]
                    sig = self.trend.generate_signal(pb_bar, res_bar, ema_val, atr, ctx.hmm_state, avg_vol_10)
                    if not sig:
                        if _TRACE_BAR:
                            print(f"[DU_TRACE]   {ticker}: SKIP signal=None", flush=True)
                        continue
                    _intent = self.trend.watchlist_directions.get(ticker)
                    if _intent and sig.get("direction") != _intent:
                        if _TRACE_BAR:
                            print(f"[DU_TRACE]   {ticker}: SKIP direction_mismatch sig={sig.get('direction')} intent={_intent}", flush=True)
                        continue
                    if ctx.hmm_state in ("Stress", "Crisis") and not ctx.spy_bull_trend:
                        if sig.get("direction") == "LONG":
                            if _TRACE_BAR:
                                print(f"[DU_TRACE]   {ticker}: SKIP stress_bear_filter", flush=True)
                            continue
                    direction = sig.get("direction", "LONG")
                    _cd = self._tf_cooldown.get(ticker, {}).get(direction)
                    if _cd is not None:
                        _prev_close = float(
                            ctx.market_data[ticker].loc[
                                ctx.market_data[ticker].index < bar_ts
                            ]["close"].iloc[-1]
                        ) if ticker in ctx.market_data else None
                        _recovered = (
                            (_prev_close > _cd) if direction == "LONG"
                            else (_prev_close < _cd)
                        ) if _prev_close is not None else False
                        if _recovered:
                            self._tf_cooldown[ticker].pop(direction)
                            if not self._tf_cooldown[ticker]:
                                self._tf_cooldown.pop(ticker)
                        else:
                            if _TRACE_BAR:
                                print(f"[DU_TRACE]   {ticker}: SKIP cooldown block_stop={_cd} prev_close={_prev_close}", flush=True)
                            logger.debug(
                                "TF skip %s %s: cooldown (block_stop=%.2f, prev_close=%s)",
                                ticker, direction, _cd, _prev_close,
                            )
                            continue
                    daily_atr = self._compute_daily_atr(ctx.market_data, ticker, bar_ts)
                    entry_p   = sig.get("entry_price", 0.0)
                    direction = sig.get("direction", "LONG")
                    _atr_mult = {"Calm": 0.5, "Normal": 1.0, "Stress": 1.5, "Crisis": 2.0}
                    stop_dist   = max(daily_atr * _atr_mult.get(ctx.hmm_state, 1.0), entry_p * 0.005)
                    target_dist = stop_dist * 2.0
                    if direction == "LONG":
                        sig["initial_stop"] = round(entry_p - stop_dist, 2)
                        sig["target"]       = round(entry_p + target_dist, 2)
                    else:
                        sig["initial_stop"] = round(entry_p + stop_dist, 2)
                        sig["target"]       = round(entry_p - target_dist, 2)
                    sig = self._normalise_signal(sig)
                    _pe_before = len(pending_entries)
                    self._attempt_entry(sig, ticker, "TREND_FOLLOW", bar_ts,
                                        ctx, pending_entries, entries)
                    if _TRACE_BAR:
                        _added = len(pending_entries) > _pe_before
                        if _added:
                            print(f">>> TF_ADMIT {ticker} pending_now={len(pending_entries)}", flush=True)
                        else:
                            print(f"[DU_TRACE]   {ticker}: attempt_entry REJECTED (sizing/PDT)", flush=True)
                except Exception as e:
                    logger.debug(f"Trend signal error {ticker}: {e}")

        # ── 10. Exit checks for intraday strategies ────────────────────────────
        # Update GAP_FILL chandelier trailing stops first
        if bar_t > GAP_FILL_ENTRY:
            for trade in ctx.open_trades:
                if trade.strategy == "GAP_FILL":
                    sd = self._gf_stop_dists.get(id(trade))
                    if sd is not None and trade.ticker in ctx.day_stocks:
                        try:
                            gf_bar     = ctx.day_stocks[trade.ticker].loc[bar_ts]
                            new_trail  = float(gf_bar["high"]) - sd
                            if new_trail > (trade.stop or 0):
                                trade.stop = new_trail
                        except Exception:
                            pass
                elif trade.strategy == "GF_SHORT":
                    sd = self._gfs_stop_dists.get(id(trade))
                    if sd is not None and trade.ticker in ctx.day_stocks:
                        try:
                            gfs_bar   = ctx.day_stocks[trade.ticker].loc[bar_ts]
                            new_trail = float(gfs_bar["low"]) + sd
                            if new_trail < (trade.stop or float("inf")):
                                trade.stop = new_trail
                        except Exception:
                            pass

        # Exit checks for intraday strategies
        already_exiting_ids = {id(e.trade) for e in exits}
        for trade in list(ctx.open_trades):
            if id(trade) in already_exiting_ids:
                continue
            if trade.strategy in ("TREND_FOLLOW", "PE_SHORT"):
                continue
            res = self._check_exits(trade, bar_ts, bar_t, ctx.day_stocks,
                                    ctx.allow_swing_hold, spy_bar=ctx.spy_bar)
            if res:
                exit_price, reason = res
                self._gf_stop_dists.pop(id(trade), None)
                self._gfs_stop_dists.pop(id(trade), None)
                exits.append(ExitIntent(trade=trade, exit_price=exit_price, reason=reason))

        # Merge pending_entries into final entries list
        entries.extend(pending_entries)
        return DecisionResult(entries=entries, exits=exits, override_active=False)

    # ── Position check ────────────────────────────────────────────────────────

    def _position_ok(
        self,
        ticker: str,
        strategy: str,
        open_trades: List[Any],
        pending_entries: List[EntryIntent],
    ) -> bool:
        open_tickers = {t.ticker for t in open_trades} | {e.ticker for e in pending_entries}
        if ticker in open_tickers:
            return False
        total = len(open_trades) + len(pending_entries)
        if total >= MAX_TOTAL:
            return False
        strat_count = (
            sum(1 for t in open_trades if t.strategy == strategy)
            + sum(1 for e in pending_entries if e.strategy == strategy)
        )
        return strat_count < STRATEGY_CAPS.get(strategy, 2)

    # ── Entry builder ─────────────────────────────────────────────────────────

    def _attempt_entry(
        self,
        signal: dict,
        ticker: str,
        strategy: str,
        bar_ts: pd.Timestamp,
        ctx: BarContext,
        pending_entries: List[EntryIntent],
        entries: List[EntryIntent],
        gf_stop_dist: Optional[float] = None,
    ) -> None:
        if ctx.enable_pdt_guard and signal.get("is_day_trade", True):
            try:
                decision = self.pdt_guard.check_can_day_trade(bar_ts.date())
                if not decision.passed:
                    return
            except Exception as e:
                logger.debug(f"PDT check error: {e}")

        stop  = signal.get("stop", 0.0) or signal.get("stop_loss", 0.0) or signal.get("initial_stop", 0.0)
        entry = signal.get("entry_price", 0.0)

        try:
            if strategy == "FADE":
                vol_sh   = self.position_sizer.calculate_vol_target_shares(entry, stop)
                limit_sh = self.position_sizer.calculate_position_limit_shares(entry)
                final_sh = min(vol_sh, limit_sh)
                if final_sh < 1:
                    return
                size = {
                    "shares":                final_sh,
                    "position_value":        round(final_sh * entry, 2),
                    "risk_dollars":          round(final_sh * abs(entry - stop), 2),
                    "risk_pct":              round(final_sh * abs(entry - stop) / self.position_sizer.account_equity, 6),
                    "kelly_shares":          0,
                    "vol_target_shares":     vol_sh,
                    "position_limit_shares": limit_sh,
                    "limiting_factor":       "VOLATILITY_TARGET" if vol_sh <= limit_sh else "POSITION_LIMIT",
                }
            else:
                stats = STRATEGY_STATS.get(strategy, {"win_rate": 0.50, "avg_win": 3.0, "avg_loss": 2.0})
                size  = self.position_sizer.calculate(
                    entry_price=entry, stop_loss=stop, strategy_stats=stats,
                )
        except Exception as e:
            logger.debug(f"Sizing error {ticker}: {e}")
            return

        if size is None or (isinstance(size, dict) and size.get("shares", 0) <= 0):
            return

        n_shares     = int(size["shares"]) if isinstance(size, dict) else int(getattr(size, "shares", 0))
        limit_factor = (size.get("limiting_factor", "UNKNOWN") if isinstance(size, dict)
                        else getattr(size, "limiting_factor", "UNKNOWN"))

        if strategy == "TREND_FOLLOW" and ctx.hmm_state in ("Stress", "Crisis"):
            n_shares = max(1, int(n_shares * ctx.stress_size_fraction))

        if n_shares <= 0:
            return

        target = signal.get("target", entry * 1.05 if signal.get("direction") == "LONG" else entry * 0.95)

        intent = EntryIntent(
            ticker=ticker,
            strategy=strategy,
            direction=signal["direction"],
            entry_price=entry,
            shares=n_shares,
            stop=stop,
            target=target,
            is_day_trade=signal.get("is_day_trade", True),
            limiting_factor=limit_factor,
            hmm_state=ctx.hmm_state,
            gf_stop_dist=gf_stop_dist,
        )
        pending_entries.append(intent)

        # Record against PDT guard immediately so subsequent candidates in the
        # same bar see the updated count — matching engine.py's behaviour exactly.
        if ctx.enable_pdt_guard and intent.is_day_trade:
            try:
                self.pdt_guard.record_day_trade(bar_ts.date())
            except Exception:
                pass

    # ── Exit checker ──────────────────────────────────────────────────────────

    def _check_exits(
        self,
        trade: Any,
        bar_ts: pd.Timestamp,
        bar_t: dtime,
        day_stocks: Dict[str, Any],
        allow_swing_hold: bool = False,
        spy_bar: Optional[pd.Series] = None,
    ) -> Optional[Tuple[float, str]]:
        if trade.ticker not in day_stocks:
            if trade.ticker == "SPY" and spy_bar is not None:
                bar_low   = float(spy_bar["low"])
                bar_high  = float(spy_bar["high"])
                bar_close = float(spy_bar["close"])
            else:
                return None
        else:
            try:
                bar       = day_stocks[trade.ticker].loc[bar_ts]
                bar_low   = float(bar["low"])
                bar_high  = float(bar["high"])
                bar_close = float(bar["close"])
            except KeyError:
                return None

        # --- TRACE helper (remove after exit-price bug resolved) ---
        _is_traced = (
            str(bar_ts.date()) in ("2019-08-01", "2019-01-03", "2020-10-30")
            and getattr(trade, "ticker", None) in ("VRTX", "QQQ")
            and getattr(trade, "strategy", None) in ("ORB", "STRESS_MID", "STRESS_ORB")
        )
        def _tr(price, reason):
            if _is_traced:
                print(f"[CE] {bar_ts} {trade.ticker}/{trade.strategy} bar_t={bar_t}"
                      f" -> {price:.4f}/{reason}  stop={trade.stop:.4f} tgt={trade.target:.4f}",
                      flush=True)
            return price, reason
        # --- end TRACE helper ---

        if bar_t >= EOD_HARD_EXIT:
            if allow_swing_hold and trade.strategy == "TREND_FOLLOW":
                return None
            if trade.strategy == "PE_SHORT":
                _pe_entry_day = pd.Timestamp(trade.entry_time).normalize()
                if _pe_entry_day == bar_ts.normalize():
                    return None
            return _tr(bar_close, "EOD")

        if trade.direction == "LONG":
            if bar_low  <= trade.stop:   return _tr(trade.stop,   "STOP_HIT")
            if bar_high >= trade.target: return _tr(trade.target, "TARGET_HIT")
        else:
            if bar_high >= trade.stop:   return _tr(trade.stop,   "STOP_HIT")
            if bar_low  <= trade.target: return _tr(trade.target, "TARGET_HIT")

        if trade.strategy == "VWAP_MR":
            elapsed = (bar_ts - trade.entry_time).total_seconds() / 60
            if elapsed >= 90:
                return _tr(bar_close, "TIME_STOP")
        if trade.strategy == "GAP_FILL"  and bar_t >= GAP_FILL_EXIT:  return _tr(bar_close, "TIME_STOP")
        if trade.strategy == "GF_SHORT"  and bar_t >= GAP_FILL_EXIT:  return _tr(bar_close, "TIME_STOP")
        if trade.strategy == "RS_SHORT"  and bar_t >= RS_SHORT_EXIT:   return _tr(bar_close, "TIME_STOP")
        if trade.strategy == "STRESS_MID" and bar_t >= STRESS_MID_EXIT: return _tr(bar_close, "TIME_STOP")
        return None

    # ── Helpers (static, mirror engine.py methods exactly) ────────────────────

    @staticmethod
    def _normalise_signal(sig: dict) -> dict:
        out = dict(sig)
        if "stop" not in out:
            out["stop"] = out.get("stop_loss") or out.get("initial_stop", 0.0)
        out.setdefault("is_day_trade", True)
        return out

    @staticmethod
    def _check_layer0(spy_history: List[pd.Series]) -> bool:
        if len(spy_history) < 21:
            return False
        try:
            closes     = pd.Series([float(b["close"]) for b in spy_history[-21:]])
            returns    = closes.pct_change().dropna()
            std        = returns[:-1].std()
            if std <= 0:
                return False
            latest_ret = returns.iloc[-1]
            return bool(abs(latest_ret / std) > 3.0 and abs(latest_ret) > 0.006)
        except Exception:
            return False

    @staticmethod
    def _last_close_price(trade: Any, bar_ts: pd.Timestamp, day_stocks: Dict[str, Any]) -> float:
        if trade.ticker in day_stocks and not day_stocks[trade.ticker].empty:
            try:
                bar   = day_stocks[trade.ticker].loc[bar_ts]
                price = float(bar["close"])
                if trade.stop is not None:
                    if trade.direction == "LONG" and float(bar["low"]) <= trade.stop:
                        price = max(price, trade.stop)
                    elif trade.direction == "SHORT" and float(bar["high"]) >= trade.stop:
                        price = min(price, trade.stop)
                return price
            except KeyError:
                pass
        return trade.entry_price

    @staticmethod
    def _compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
        if len(bars) < 2:
            return float(bars["close"].iloc[-1]) * 0.015
        hl  = bars["high"] - bars["low"]
        hpc = (bars["high"] - bars["close"].shift(1)).abs()
        lpc = (bars["low"]  - bars["close"].shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        return float(tr.tail(period).mean())

    @staticmethod
    def _compute_daily_atr(
        market_data: Dict[str, pd.DataFrame],
        ticker: str,
        as_of: pd.Timestamp,
        period: int = 14,
    ) -> float:
        if ticker not in market_data:
            return 0.0
        try:
            df    = market_data[ticker]
            daily = df.loc[df.index < as_of].resample("B").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last"}
            ).dropna()
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

    @staticmethod
    def _compute_adx(bars: pd.DataFrame, period: int = 14) -> float:
        if len(bars) < period + 1:
            return 0.0
        try:
            high, low, close = bars["high"], bars["low"], bars["close"]
            prev_close = close.shift(1)
            tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()],
                           axis=1).max(axis=1)
            up   = high.diff()
            down = -low.diff()
            plus_dm  = up.where((up > down) & (up > 0), 0.0)
            minus_dm = down.where((down > up) & (down > 0), 0.0)
            atr_s    = tr.ewm(span=period, adjust=False).mean()
            plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
            minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
            dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
            return float(dx.ewm(span=period, adjust=False).mean().iloc[-1])
        except Exception:
            return 0.0

    def _compute_sector_strength(
        self,
        day_stocks: Dict[str, pd.DataFrame],
        bar_ts: pd.Timestamp,
        universe: List[str],
    ) -> float:
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

    def _build_orb_candidates(
        self,
        day_stocks: Dict[str, pd.DataFrame],
        market_data: Dict[str, pd.DataFrame],
        today: pd.Timestamp,
        effective_orb_universe: Optional[List[str]] = None,
        skip_gap_filter: bool = False,
    ) -> List[Dict[str, Any]]:
        orb_tickers  = effective_orb_universe or []
        scan_stocks  = {t: df for t, df in day_stocks.items() if t in orb_tickers} if orb_tickers else day_stocks
        candidates   = []
        for ticker, df in scan_stocks.items():
            if df.empty:
                continue
            first      = df.iloc[0]
            open_p     = float(first["open"])
            prev_close = None
            prior_bars = pd.DataFrame()
            if ticker in market_data:
                full_df   = market_data[ticker]
                prior_all = full_df[full_df.index.normalize() < today]
                if not prior_all.empty:
                    prev_close = float(prior_all.iloc[-1]["close"])
                    prior_bars = prior_all
            if prev_close is None or prev_close <= 0:
                continue
            gap_pct = abs(open_p - prev_close) / prev_close
            if not skip_gap_filter and gap_pct < 0.005:
                continue
            avg_vol_by_time: dict = {}
            if not prior_bars.empty:
                prior_opening_vols = (
                    prior_bars.groupby(prior_bars.index.normalize()).first()["volume"].tail(20)
                )
                avg_opening_vol  = int(prior_opening_vols.mean()) if len(prior_opening_vols) > 0 else int(first["volume"])
                avg_daily_volume = avg_opening_vol * 78
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
        return candidates

    def _build_vwap_candidates(
        self,
        day_stocks: Dict[str, pd.DataFrame],
        bar_ts: pd.Timestamp,
        universe: List[str],
    ) -> List[Dict[str, Any]]:
        candidates = []
        for ticker in universe:
            if ticker not in day_stocks:
                continue
            bars = day_stocks[ticker].loc[:bar_ts]
            if len(bars) < 22:
                continue
            try:
                current_price  = float(bars.iloc[-1]["close"])
                current_volume = float(bars.iloc[-1]["volume"])
                avg_bar_vol    = float(bars["volume"].mean())
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
                    "avg_daily_volume": avg_bar_vol,
                    "atr_current":      atr_current,
                    "atr_5bars_ago":    atr_5bars_ago,
                    "has_earnings":     False,
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
        candidates = []
        for ticker in universe:
            if ticker not in day_stocks:
                continue
            bars = day_stocks[ticker].loc[:bar_ts]
            if len(bars) < 3:
                continue
            try:
                candidates.append({
                    "ticker":              ticker,
                    "current_price":       float(bars.iloc[-1]["close"]),
                    "hod":                 float(bars["high"].max()),
                    "lod":                 float(bars["low"].min()),
                    "atr":                 self._compute_atr(bars),
                    "avg_intraday_volume": float(bars["volume"].tail(10).mean()),
                    "current_volume":      float(bars.iloc[-1]["volume"]),
                    "sector_strength":     sector_strength,
                })
            except Exception as e:
                logger.debug(f"Trend candidate error {ticker}: {e}")
        return candidates
