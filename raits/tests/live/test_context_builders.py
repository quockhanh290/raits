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
import pytest
import pandas as pd
from datetime import time as dtime

import logging
from raits.backtest.data_types import BacktestConfig
from raits.live.context_feed import (
    ReplayContextFeed,
    LivePolygonFeed,
    _check_stale_and_warn,
    _STALE_SPY_BDAYS,
    _HARD_STALE_SPY_BDAYS,
    _spy_gap_bdays,
    _compute_fade_atr_top2,
    _compute_spy_bull_trend,
)


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


# ── _BarAccumulator ───────────────────────────────────────────────────────────

from raits.live.context_feed import _BarAccumulator


def _make_row(close: float, ts: pd.Timestamp) -> pd.Series:
    return pd.Series(
        {"open": close, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": 1_000_000.0},
        name=ts,
    )


def test_accumulator_add_and_retrieve():
    acc = _BarAccumulator()
    day = pd.Timestamp("2022-01-03")
    ts  = pd.Timestamp("2022-01-03 09:30:00")
    row = _make_row(100.0, ts)
    acc.add("AAPL", ts, row)
    ds = acc.get_day_stocks(day, ts)
    assert "AAPL" in ds
    assert len(ds["AAPL"]) == 1


def test_accumulator_late_bar_ordered():
    """Late bar arriving after a later bar is sorted into correct position."""
    acc = _BarAccumulator()
    day = pd.Timestamp("2022-01-03")
    ts1 = pd.Timestamp("2022-01-03 09:30:00")
    ts2 = pd.Timestamp("2022-01-03 09:35:00")
    # ts2 arrives first, then ts1 (late)
    acc.add("AAPL", ts2, _make_row(102.0, ts2))
    acc.add("AAPL", ts1, _make_row(100.0, ts1))
    ds = acc.get_day_stocks(day, ts2)
    df = ds["AAPL"]
    assert list(df.index) == [ts1, ts2]
    assert float(df.iloc[0]["close"]) == pytest.approx(100.0)
    assert float(df.iloc[1]["close"]) == pytest.approx(102.0)


def test_accumulator_duplicate_last_write_wins():
    """A corrected bar (same ts) replaces the earlier version."""
    acc = _BarAccumulator()
    day = pd.Timestamp("2022-01-03")
    ts  = pd.Timestamp("2022-01-03 09:30:00")
    acc.add("AAPL", ts, _make_row(100.0, ts))  # original
    acc.add("AAPL", ts, _make_row(101.5, ts))  # correction
    ds = acc.get_day_stocks(day, ts)
    assert len(ds["AAPL"]) == 1
    assert float(ds["AAPL"].iloc[0]["close"]) == pytest.approx(101.5)


def test_accumulator_missing_bar_ticker_absent():
    """A ticker with no bar for a slot is simply absent from day_stocks."""
    acc = _BarAccumulator()
    day = pd.Timestamp("2022-01-03")
    ts  = pd.Timestamp("2022-01-03 09:30:00")
    acc.add("AAPL", ts, _make_row(100.0, ts))
    ds = acc.get_day_stocks(day, ts)
    assert "MSFT" not in ds   # MSFT never added → missing bar → absent


def test_accumulator_as_of_filters_future_bars():
    """get_day_stocks(as_of=ts1) excludes bars for ts2 > ts1."""
    acc = _BarAccumulator()
    day = pd.Timestamp("2022-01-03")
    ts1 = pd.Timestamp("2022-01-03 09:30:00")
    ts2 = pd.Timestamp("2022-01-03 09:35:00")
    acc.add("AAPL", ts1, _make_row(100.0, ts1))
    acc.add("AAPL", ts2, _make_row(102.0, ts2))
    ds = acc.get_day_stocks(day, ts1)
    assert len(ds["AAPL"]) == 1
    assert float(ds["AAPL"].iloc[0]["close"]) == pytest.approx(100.0)


def test_accumulator_reset_clears_all_bars():
    acc = _BarAccumulator()
    day = pd.Timestamp("2022-01-03")
    ts  = pd.Timestamp("2022-01-03 09:30:00")
    acc.add("AAPL", ts, _make_row(100.0, ts))
    acc.reset()
    ds = acc.get_day_stocks(day, ts)
    assert ds == {}


def test_accumulator_excludes_other_day():
    """Only bars for the requested day are returned."""
    acc = _BarAccumulator()
    day1 = pd.Timestamp("2022-01-03")
    day2 = pd.Timestamp("2022-01-04")
    ts1  = pd.Timestamp("2022-01-03 09:30:00")
    ts2  = pd.Timestamp("2022-01-04 09:30:00")
    acc.add("AAPL", ts1, _make_row(100.0, ts1))
    acc.add("AAPL", ts2, _make_row(101.0, ts2))
    ds = acc.get_day_stocks(day1, ts1)
    assert len(ds["AAPL"]) == 1
    assert float(ds["AAPL"].iloc[0]["close"]) == pytest.approx(100.0)


# ── LivePolygonFeed — constructor ─────────────────────────────────────────────

def test_live_feed_requires_config():
    """LivePolygonFeed() with no args raises TypeError (config is required)."""
    with pytest.raises(TypeError):
        LivePolygonFeed()


def test_live_feed_test_mode_no_api_key_needed():
    """Test mode works without an API key."""
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    ctxs = list(feed)
    assert len(ctxs) == 13


# ── LivePolygonFeed — field equivalence vs ReplayContextFeed ──────────────────

def _both_feeds(mkt: dict, cfg: BacktestConfig, **kw):
    """Return (replay_contexts, live_contexts) for the same inputs."""
    replay = list(ReplayContextFeed(mkt, cfg, **kw))
    live   = list(LivePolygonFeed(config=cfg, _test_market_data=mkt, **kw))
    return replay, live


def test_live_feed_context_count_matches_replay():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    replay, live = _both_feeds(mkt, cfg, vix_daily={})
    assert len(live) == len(replay)


def test_live_feed_hmm_state_matches_replay():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    replay, live = _both_feeds(mkt, cfg, vix_daily={})
    for r, l in zip(replay, live):
        assert l.hmm_state == r.hmm_state


def test_live_feed_cur_vol_matches_replay():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    replay, live = _both_feeds(mkt, cfg, vix_daily={})
    for r, l in zip(replay, live):
        assert l.cur_vol == pytest.approx(r.cur_vol, rel=1e-9)


def test_live_feed_vix_gates_match_replay():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    vix = {pd.Timestamp("2022-01-03"): 32.0}
    replay, live = _both_feeds(mkt, cfg, vix_daily=vix)
    for r, l in zip(replay, live):
        assert l.orb_vix_ok        == r.orb_vix_ok
        assert l.stress_orb_vix_ok == r.stress_orb_vix_ok


def test_live_feed_spy_or_matches_replay():
    """
    spy_or_high / spy_or_low converge once the OR window closes (>= 9:45).

    ReplayContextFeed pre-computes OR from all 9:30-9:44 bars before the
    bar loop, so it has the final value from bar 0.  LivePolygonFeed
    accumulates incrementally, so values match only after the window closes.
    """
    mkt = _minimal_market_data()
    spy = mkt["SPY"].copy()
    spy.loc[spy.index[0], "high"] = 460.0   # 9:30 — within window
    spy.loc[spy.index[1], "high"] = 462.0   # 9:35 — within window (max)
    spy.loc[spy.index[0], "low"]  = 445.0   # 9:30 — within window
    spy.loc[spy.index[1], "low"]  = 443.0   # 9:35 — within window (min)
    mkt["SPY"] = spy
    cfg = _minimal_config()
    replay, live = _both_feeds(mkt, cfg, vix_daily={})
    # After the OR window closes (bar_ts >= 9:45), both feeds agree
    _OR_CLOSE = dtime(9, 45)
    for r, l in zip(replay, live):
        if r.bar_ts.time() >= _OR_CLOSE and r.spy_or_high is not None:
            assert l.spy_or_high == pytest.approx(r.spy_or_high, abs=0.01)
            assert l.spy_or_low  == pytest.approx(r.spy_or_low,  abs=0.01)

    # Verify the final OR values are correct (max of all window bars)
    final_r = replay[-1]
    final_l = live[-1]
    assert final_l.spy_or_high == pytest.approx(final_r.spy_or_high, abs=0.01)
    assert final_l.spy_or_low  == pytest.approx(final_r.spy_or_low,  abs=0.01)


def test_live_feed_spy_bull_trend_matches_replay():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    replay, live = _both_feeds(mkt, cfg, vix_daily={})
    for r, l in zip(replay, live):
        assert l.spy_bull_trend == r.spy_bull_trend


def test_live_feed_universes_match_replay():
    mkt = _minimal_market_data()
    cfg = _minimal_config(
        universe=["AAPL"],
        orb_universe=["AAPL"],
        vwap_universe=["SPY", "QQQ", "IWM"],
    )
    replay, live = _both_feeds(mkt, cfg, vix_daily={})
    for r, l in zip(replay, live):
        assert l.base_universe          == r.base_universe
        assert l.effective_orb_universe == r.effective_orb_universe
        assert l.effective_vwap_universe == r.effective_vwap_universe


def test_live_feed_config_fields_propagated():
    mkt = _minimal_market_data()
    cfg = _minimal_config(vwap_bb_std=2.0, ema_period=20, stress_size_fraction=0.4)
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    ctx  = next(iter(feed))
    assert ctx.vwap_bb_std          == pytest.approx(2.0)
    assert ctx.ema_period           == 20
    assert ctx.stress_size_fraction == pytest.approx(0.4)
    assert ctx.orb_signal_start     == dtime(9, 50)
    assert ctx.orb_signal_end       == dtime(10, 20)


# ── LivePolygonFeed — live semantics (incremental day_stocks) ─────────────────

def test_live_feed_day_stocks_excludes_spy():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    for ctx in feed:
        assert "SPY" not in ctx.day_stocks


def test_live_feed_day_stocks_incremental():
    """
    At bar i (0-indexed), day_stocks["AAPL"] has exactly i+1 rows.
    (ReplayContextFeed has n_bars rows at every bar; live mode is incremental.)
    """
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    for i, ctx in enumerate(feed):
        if "AAPL" in ctx.day_stocks:
            assert len(ctx.day_stocks["AAPL"]) == i + 1


def test_live_feed_spy_history_incremental():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    for i, ctx in enumerate(feed):
        assert len(ctx.spy_history) == i + 1


def test_live_feed_spy_history_last_matches_spy_bar():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    for ctx in feed:
        assert float(ctx.spy_history[-1]["close"]) == pytest.approx(
            float(ctx.spy_bar["close"])
        )


def test_live_feed_open_trades_always_empty():
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    for ctx in feed:
        assert ctx.open_trades == []


def test_live_feed_stress_stocks_contains_spy():
    """stress_stocks["SPY"] is always present (full day_spy)."""
    mkt = _minimal_market_data()
    cfg = _minimal_config()
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    ctx  = next(iter(feed))
    assert "SPY" in ctx.stress_stocks


def test_live_feed_multi_day():
    """Context count equals n_spy_bars × n_days across multiple days."""
    spy_d1  = _spy_bars("2022-01-03", n=13)
    spy_d2  = _spy_bars("2022-01-04", n=13)
    aapl_d1 = _ticker_bars("2022-01-03")
    aapl_d2 = _ticker_bars("2022-01-04")
    mkt = {
        "SPY":  pd.concat([spy_d1, spy_d2]),
        "AAPL": pd.concat([aapl_d1, aapl_d2]),
        "QQQ":  pd.concat([_ticker_bars("2022-01-03", base=300.0), _ticker_bars("2022-01-04", base=300.0)]),
        "IWM":  pd.concat([_ticker_bars("2022-01-03", base=200.0), _ticker_bars("2022-01-04", base=200.0)]),
    }
    cfg = _minimal_config(start_date="2022-01-03", end_date="2022-01-04")
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, vix_daily={})
    ctxs = list(feed)
    assert len(ctxs) == 26

    # At the first bar of day 2 (index 13), day_stocks["AAPL"] resets to 1 row
    d2_first = ctxs[13]
    assert d2_first.day == pd.Timestamp("2022-01-04")
    if "AAPL" in d2_first.day_stocks:
        assert len(d2_first.day_stocks["AAPL"]) == 1


# ── _check_stale_and_warn ─────────────────────────────────────────────────────

def _bdate_series(end: str, n: int = 40) -> pd.Series:
    """Construct a SPY-like daily close series ending on `end` with `n` points."""
    idx = pd.bdate_range(end=end, periods=n)
    return pd.Series([400.0 + i * 0.1 for i in range(n)], index=idx)


def test_stale_spy_retrain_warns_and_skips(caplog):
    """Stale daily_data['SPY'] (> 5 business days behind) triggers a WARNING."""
    stale_close = _bdate_series(end="2024-01-05", n=40)
    cur_day = pd.Timestamp("2024-02-15")  # ~29 business days later

    with caplog.at_level(logging.WARNING, logger="RAITS.live.context_feed"):
        is_stale = _check_stale_and_warn(stale_close, cur_day)

    assert is_stale is True
    assert any("STALE" in r.message for r in caplog.records), "expected STALE in warning"
    assert any("daily_data" in r.message for r in caplog.records)


def test_fresh_spy_retrain_no_warning(caplog):
    """Fresh daily_data['SPY'] (1 business day behind) does not trigger a warning."""
    # last close = 2024-01-31 (Wednesday), current = 2024-02-01 (Thursday) → gap = 1
    fresh_close = _bdate_series(end="2024-01-31", n=40)
    cur_day = pd.Timestamp("2024-02-01")

    with caplog.at_level(logging.WARNING, logger="RAITS.live.context_feed"):
        is_stale = _check_stale_and_warn(fresh_close, cur_day)

    assert is_stale is False
    assert not any("STALE" in r.message for r in caplog.records)


def test_staleness_exactly_at_threshold_is_not_stale(caplog):
    """A gap of exactly _STALE_SPY_BDAYS business days is not stale (threshold is strict >)."""
    # Build a series whose last business date is exactly _STALE_SPY_BDAYS bdays before cur_day
    cur_day = pd.Timestamp("2024-02-08")  # Thursday
    last_date = pd.bdate_range(end=cur_day, periods=_STALE_SPY_BDAYS + 1)[0]
    close = _bdate_series(end=str(last_date.date()), n=40)

    with caplog.at_level(logging.WARNING, logger="RAITS.live.context_feed"):
        is_stale = _check_stale_and_warn(close, cur_day)

    assert is_stale is False


def test_staleness_one_over_threshold_is_stale(caplog):
    """A gap of _STALE_SPY_BDAYS + 1 business days triggers the warning."""
    cur_day = pd.Timestamp("2024-02-08")
    last_date = pd.bdate_range(end=cur_day, periods=_STALE_SPY_BDAYS + 2)[0]
    close = _bdate_series(end=str(last_date.date()), n=40)

    with caplog.at_level(logging.WARNING, logger="RAITS.live.context_feed"):
        is_stale = _check_stale_and_warn(close, cur_day)

    assert is_stale is True


def test_empty_spy_series_is_not_stale():
    """An empty daily SPY series returns False (no data → no assertion possible)."""
    empty = pd.Series(dtype=float)
    assert _check_stale_and_warn(empty, pd.Timestamp("2024-02-01")) is False


# ── _spy_gap_bdays ────────────────────────────────────────────────────────────

def test_spy_gap_bdays_empty_returns_zero():
    assert _spy_gap_bdays(pd.Series(dtype=float), pd.Timestamp("2024-02-01")) == 0


def test_spy_gap_bdays_one_day():
    # last close = 2024-01-31, cur_day = 2024-02-01 → 1 bday
    idx = pd.bdate_range(end="2024-01-31", periods=5)
    close = pd.Series([430.0] * 5, index=idx)
    assert _spy_gap_bdays(close, pd.Timestamp("2024-02-01")) == 1


def test_spy_gap_bdays_hard_stale():
    idx = pd.bdate_range(end="2024-01-05", periods=40)
    close = pd.Series([430.0] * 40, index=idx)
    assert _spy_gap_bdays(close, pd.Timestamp("2024-02-15")) > _HARD_STALE_SPY_BDAYS


# ── regime_unreliable propagation via _iter_test ─────────────────────────────

def _daily_spy_df(last_date: str, n: int = 40) -> pd.DataFrame:
    """Minimal daily SPY DataFrame ending on last_date."""
    idx = pd.bdate_range(end=last_date, periods=n)
    return pd.DataFrame({
        "open":   [430.0] * n,
        "high":   [431.0] * n,
        "low":    [429.0] * n,
        "close":  [430.0 + i * 0.1 for i in range(n)],
        "volume": [1_000_000] * n,
    }, index=idx)


def test_hard_stale_daily_spy_sets_regime_unreliable(capfd):
    """daily_data['SPY'] >10 bdays stale → all BarContexts carry regime_unreliable=True
    and a TRADING HALTED box appears on stderr."""
    mkt = _minimal_market_data("2022-01-03")
    # last close ~2021-06-01, test day 2022-01-03 → ~150 bdays gap >> _HARD_STALE_SPY_BDAYS
    daily = {"SPY": _daily_spy_df("2021-06-01")}
    cfg = _minimal_config(start_date="2022-01-03", end_date="2022-01-03")
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, daily_data=daily, vix_daily={})

    ctxs = list(feed)

    assert len(ctxs) > 0, "feed produced no bars"
    assert all(ctx.regime_unreliable for ctx in ctxs), (
        "expected every bar to have regime_unreliable=True"
    )
    captured = capfd.readouterr()
    assert "TRADING HALTED" in captured.err, "expected HALTED box on stderr"


def test_soft_stale_daily_spy_no_regime_unreliable():
    """daily_data['SPY'] 7 bdays stale (soft only, ≤ hard threshold) → regime_unreliable=False."""
    mkt = _minimal_market_data("2022-01-03")
    # 7-bday gap: > _STALE_SPY_BDAYS (5) but ≤ _HARD_STALE_SPY_BDAYS (10)
    last_date = pd.bdate_range(end="2022-01-03", periods=9)[0]  # 8 bdays before → gap = 8
    # Verify the gap is in the soft zone
    assert _STALE_SPY_BDAYS < _spy_gap_bdays(
        pd.Series([1.0], index=[last_date]), pd.Timestamp("2022-01-03")
    ) <= _HARD_STALE_SPY_BDAYS
    daily = {"SPY": _daily_spy_df(str(last_date.date()))}
    cfg = _minimal_config(start_date="2022-01-03", end_date="2022-01-03")
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, daily_data=daily, vix_daily={})

    ctxs = list(feed)

    assert len(ctxs) > 0
    assert not any(ctx.regime_unreliable for ctx in ctxs), (
        "soft-stale should NOT set regime_unreliable"
    )


def test_fresh_daily_spy_no_regime_unreliable():
    """Fresh daily_data['SPY'] (1 bday gap) → regime_unreliable=False on all bars."""
    mkt = _minimal_market_data("2022-01-03")
    # last close = 2021-12-31 (prior business day to 2022-01-03 Monday) → gap = 1
    daily = {"SPY": _daily_spy_df("2021-12-31")}
    cfg = _minimal_config(start_date="2022-01-03", end_date="2022-01-03")
    feed = LivePolygonFeed(config=cfg, _test_market_data=mkt, daily_data=daily, vix_daily={})

    ctxs = list(feed)

    assert len(ctxs) > 0
    assert not any(ctx.regime_unreliable for ctx in ctxs)
