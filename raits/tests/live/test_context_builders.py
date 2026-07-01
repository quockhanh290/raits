"""
tests/live/test_context_builders.py

Unit tests for ReplayContextFeed incremental builders:
  - day_stocks accumulation (ALL bars for today, not just up to bar_ts)
  - intraday SPY history accumulation
  - OR high/low computation (9:30–9:44 window)
  - SPY bull trend (SMA50 > SMA200)
  - VIX gates (orb_vix_ok, stress_orb_vix_ok)
  - FADE ATR top-2
  - universe assembly
  - config-derived fields (orb_signal_start/end, vwap_bb_std, etc.)
  - context count matches bar count
"""
import os
import pytest
import pandas as pd
import numpy as np
from datetime import time as dtime, datetime

from raits.backtest.data_types import BacktestConfig
from raits.live.context_feed import (
    ReplayContextFeed,
    LivePolygonFeed,
    _compute_fade_atr_top2,
    _compute_spy_bull_trend,
    _to_daily_close,
)
from raits.decision.types import BarContext


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spy_bars(day: str = "2022-01-03", n: int = 13) -> pd.DataFrame:
    """n 5-min bars starting at 9:30 ET."""
    idx = pd.date_range(
        start=f"{day} 09:30:00", periods=n, freq="5min"
    )
    return pd.DataFrame({
        "open":   [450.0 + i * 0.1 for i in range(n)],
        "high":   [451.0 + i * 0.1 for i in range(n)],
        "low":    [449.0 + i * 0.1 for i in range(n)],
        "close":  [450.5 + i * 0.1 for i in range(n)],
        "volume": [1_000_000] * n,
    }, index=idx)


def _ticker_bars(day: str = "2022-01-03", n: int = 13, base: float = 100.0) -> pd.DataFrame:
    idx = pd.date_range(start=f"{day} 09:30:00", periods=n, freq="5min")
    return pd.DataFrame({
        "open":   [base + i * 0.05 for i in range(n)],
        "high":   [base + 0.5 + i * 0.05 for i in range(n)],
        "low":    [base - 0.5 + i * 0.05 for i in range(n)],
        "close":  [base + 0.2 + i * 0.05 for i in range(n)],
        "volume": [500_000] * n,
    }, index=idx)


def _minimal_config(**kwargs) -> BacktestConfig:
    defaults = dict(
        account_equity=50_000.0,
        start_date="2022-01-03",
        end_date="2022-01-03",
        universe=["AAPL"],
        orb_universe=["AAPL"],
        vwap_universe=["SPY", "QQQ", "IWM"],
        orb_range_minutes=20,
        vwap_bb_std=1.5,
        ema_period=30,
        max_risk_pct=0.015,
        max_position_pct=0.40,
        kelly_fraction=0.75,
        enable_costs=False,
        enable_pdt_guard=False,
        hmm_retrain_weekly=False,
        allow_swing_hold=False,
        stress_size_fraction=0.5,
        log_level="ERROR",
    )
    defaults.update(kwargs)
    return BacktestConfig(**defaults)


def _minimal_market_data(day: str = "2022-01-03") -> dict:
    return {
        "SPY":  _spy_bars(day),
        "AAPL": _ticker_bars(day),
        "QQQ":  _ticker_bars(day, base=300.0),
        "IWM":  _ticker_bars(day, base=200.0),
    }


# ── _compute_spy_bull_trend ───────────────────────────────────────────────────

def test_bull_trend_true_when_sma50_above_sma200():
    # Build a series with 200 days of upward trending closes
    closes = pd.Series(
        [float(i) for i in range(1, 201)],
        index=pd.date_range("2021-01-01", periods=200, freq="B"),
    )
    assert _compute_spy_bull_trend(closes) is True


def test_bull_trend_false_when_sma50_below_sma200():
    # Series that is high early and low recently (SMA50 < SMA200)
    closes = pd.Series(
        [float(200 - i) for i in range(200)],
        index=pd.date_range("2021-01-01", periods=200, freq="B"),
    )
    assert _compute_spy_bull_trend(closes) is False


def test_bull_trend_defaults_true_when_insufficient_data():
    short = pd.Series([100.0, 101.0, 102.0],
                      index=pd.date_range("2022-01-01", periods=3, freq="B"))
    assert _compute_spy_bull_trend(short) is True


# ── _compute_fade_atr_top2 ────────────────────────────────────────────────────

def _daily_df(close_values, day_start="2021-01-01") -> pd.DataFrame:
    idx = pd.date_range(day_start, periods=len(close_values), freq="B")
    closes = pd.Series(close_values, index=idx)
    return pd.DataFrame({
        "close": closes,
        "high":  closes * 1.01,
        "low":   closes * 0.99,
        "open":  closes,
        "volume": [1_000_000] * len(closes),
    })


def test_fade_atr_top2_returns_highest_atr_tickers():
    # NVDA: high-vol base prices → high ATR%
    # AAPL: low-vol, stable prices → low ATR%
    as_of = pd.Timestamp("2022-01-03")
    daily = {
        "NVDA": _daily_df([float(i * 20 + 100) for i in range(20)]),
        "AAPL": _daily_df([float(150.0 + i * 0.01) for i in range(20)]),
        "SPY":  _daily_df([450.0] * 20),  # SPY is excluded
    }
    top2 = _compute_fade_atr_top2(daily, as_of, period=5, top_n=2)
    assert "NVDA" in top2
    assert "SPY" not in top2


def test_fade_atr_top2_excludes_spy():
    as_of = pd.Timestamp("2022-01-03")
    daily = {"SPY": _daily_df([float(i + 100) for i in range(20)])}
    top2 = _compute_fade_atr_top2(daily, as_of, period=5, top_n=2)
    assert "SPY" not in top2


def test_fade_atr_top2_returns_empty_on_insufficient_data():
    as_of = pd.Timestamp("2022-01-03")
    daily = {"AAPL": _daily_df([150.0] * 5, "2021-12-20")}  # < period+1 rows
    top2 = _compute_fade_atr_top2(daily, as_of, period=14, top_n=2)
    assert top2 == set()


# ── VIX gates ─────────────────────────────────────────────────────────────────

def test_vix_orb_ok_when_no_vix():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    assert all(c.orb_vix_ok for c in ctxs)


def test_vix_orb_ok_false_when_vix_high():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    vix = {pd.Timestamp("2022-01-03"): 30.0}  # ≥ 25 → orb blocked
    feed = ReplayContextFeed(mkt, cfg, vix_daily=vix)
    ctxs = list(feed)
    assert all(not c.orb_vix_ok for c in ctxs)


def test_vix_stress_orb_ok_when_vix_high():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    vix = {pd.Timestamp("2022-01-03"): 35.0}  # ≥ 30 → stress_orb ok
    feed = ReplayContextFeed(mkt, cfg, vix_daily=vix)
    ctxs = list(feed)
    assert all(c.stress_orb_vix_ok for c in ctxs)


# ── SPY OR high/low ───────────────────────────────────────────────────────────

def test_spy_or_high_low_computed_from_9_30_to_9_44():
    # Build SPY bars: first 3 bars (9:30, 9:35, 9:40) are within 9:30–9:44
    mkt = _minimal_market_data()
    spy = mkt["SPY"].copy()
    # Use .loc to avoid pandas CoW chained-assignment error
    spy.loc[spy.index[0], "high"] = 455.0  # 9:30
    spy.loc[spy.index[1], "high"] = 460.0  # 9:35  ← max
    spy.loc[spy.index[2], "high"] = 458.0  # 9:40
    spy.loc[spy.index[0], "low"]  = 448.0
    spy.loc[spy.index[1], "low"]  = 447.0  # ← min
    spy.loc[spy.index[2], "low"]  = 449.0
    mkt["SPY"] = spy
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    assert ctxs[0].spy_or_high == pytest.approx(460.0, abs=0.01)
    assert ctxs[0].spy_or_low  == pytest.approx(447.0, abs=0.01)


# ── day_stocks ────────────────────────────────────────────────────────────────

def test_day_stocks_contains_all_bars_for_day():
    """day_stocks must contain ALL day's bars, not just up-to-bar_ts."""
    mkt = _minimal_market_data()
    n_bars = len(mkt["AAPL"])
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    # At every bar, day_stocks["AAPL"] should have ALL n_bars (full day)
    for ctx in ctxs:
        if "AAPL" in ctx.day_stocks:
            assert len(ctx.day_stocks["AAPL"]) == n_bars, \
                f"Expected {n_bars} bars in day_stocks['AAPL'], got {len(ctx.day_stocks['AAPL'])}"


def test_day_stocks_excludes_spy():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    for ctx in ctxs:
        assert "SPY" not in ctx.day_stocks


# ── SPY history accumulation ──────────────────────────────────────────────────

def test_spy_history_grows_bar_by_bar():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    n_spy_bars = len(mkt["SPY"])
    assert len(ctxs) == n_spy_bars
    for i, ctx in enumerate(ctxs):
        assert len(ctx.spy_history) == i + 1


def test_spy_history_last_matches_spy_bar():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    for ctx in ctxs:
        hist_last = ctx.spy_history[-1]
        assert float(hist_last["close"]) == pytest.approx(float(ctx.spy_bar["close"]))


# ── Config fields propagated ──────────────────────────────────────────────────

def test_config_fields_propagated():
    mkt = _minimal_market_data()
    cfg = _minimal_config(vwap_bb_std=1.5, ema_period=30, stress_size_fraction=0.5)
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    assert ctx.vwap_bb_std        == pytest.approx(1.5)
    assert ctx.ema_period         == 30
    assert ctx.stress_size_fraction == pytest.approx(0.5)
    assert ctx.allow_swing_hold   is False
    assert ctx.enable_pdt_guard   is False


def test_orb_signal_times_derived_from_orb_range_minutes():
    # orb_range_minutes=20 → signal_start=9:50, signal_end=10:20
    mkt = _minimal_market_data()
    cfg = _minimal_config(orb_range_minutes=20)
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    assert ctx.orb_signal_start == dtime(9, 50)
    assert ctx.orb_signal_end   == dtime(10, 20)


def test_orb_signal_times_15min():
    # orb_range_minutes=15 → signal_start=9:45, signal_end=10:15
    mkt = _minimal_market_data()
    cfg = _minimal_config(orb_range_minutes=15)
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    assert ctx.orb_signal_start == dtime(9, 45)
    assert ctx.orb_signal_end   == dtime(10, 15)


# ── Universe assembly ─────────────────────────────────────────────────────────

def test_base_universe_is_config_universe_without_scanner():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    assert ctx.base_universe == cfg.universe


def test_effective_orb_universe_is_config_orb_universe():
    mkt = _minimal_market_data()
    cfg = _minimal_config(orb_universe=["AAPL"])
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    assert ctx.effective_orb_universe == ["AAPL"]


def test_effective_vwap_universe_includes_config_vwap_universe():
    mkt = _minimal_market_data()
    cfg = _minimal_config(vwap_universe=["SPY", "QQQ", "IWM"])
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    for t in ["SPY", "QQQ", "IWM"]:
        assert t in ctx.effective_vwap_universe


# ── stress_stocks ─────────────────────────────────────────────────────────────

def test_stress_stocks_contains_spy():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    assert "SPY" in ctx.stress_stocks


def test_stress_stocks_contains_qqq_iwm_when_available():
    mkt = _minimal_market_data()
    cfg = _minimal_config(
        universe=["AAPL"],
        orb_universe=["AAPL"],
        vwap_universe=["SPY", "QQQ", "IWM"],
    )
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctx = next(iter(feed))
    assert "QQQ" in ctx.stress_stocks
    assert "IWM" in ctx.stress_stocks


# ── open_trades is always empty ───────────────────────────────────────────────

def test_open_trades_always_empty():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    for ctx in feed:
        assert ctx.open_trades == []


# ── context count matches bar count ──────────────────────────────────────────

def test_context_count_matches_spy_bar_count():
    mkt = _minimal_market_data()  # _spy_bars default n=13
    cfg = _minimal_config()
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    assert len(ctxs) == 13


def test_multi_day_context_count():
    # Two trading days
    spy_d1 = _spy_bars("2022-01-03", n=13)
    spy_d2 = _spy_bars("2022-01-04", n=13)
    aapl_d1 = _ticker_bars("2022-01-03")
    aapl_d2 = _ticker_bars("2022-01-04")
    mkt = {
        "SPY":  pd.concat([spy_d1, spy_d2]),
        "AAPL": pd.concat([aapl_d1, aapl_d2]),
        "QQQ":  pd.concat([_ticker_bars("2022-01-03", base=300.0), _ticker_bars("2022-01-04", base=300.0)]),
        "IWM":  pd.concat([_ticker_bars("2022-01-03", base=200.0), _ticker_bars("2022-01-04", base=200.0)]),
    }
    cfg = _minimal_config(
        start_date="2022-01-03",
        end_date="2022-01-04",
    )
    feed = ReplayContextFeed(mkt, cfg, vix_daily={})
    ctxs = list(feed)
    assert len(ctxs) == 26  # 13 per day × 2


# ── LivePolygonFeed stub ──────────────────────────────────────────────────────

def test_live_polygon_feed_raises():
    with pytest.raises(NotImplementedError):
        LivePolygonFeed()
