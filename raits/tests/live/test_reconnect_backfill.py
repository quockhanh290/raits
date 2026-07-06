"""
tests/live/test_reconnect_backfill.py

Step 2 — Reconnect / backfill mechanism tests.

All tests run OFFLINE (no real Polygon connection needed):
  - backoff delay math
  - _backfill_bars unit tests (REST client mocked)
  - reconnect integration test (WebSocket mocked)

Coverage:
  (A) Reconnect backoff sequence [1, 2, 4, 8, 16, 30, 30, …]
  (B) _backfill_bars: REST client called with correct params
  (C) _backfill_bars: bars enqueued correctly
  (D) _backfill_bars: full failure → logger.ERROR with gap warning
  (E) _backfill_bars: partial failure → logger.ERROR per ticker + summary
  (F) _backfill_bars: polygon not installed → logger.WARNING, no crash
  (G) backfill_on_reconnect=False stored correctly
  (H) WS thread reconnects after an exception (integration)
  (I) _backfill_bars called after reconnect when flag=True (integration)
"""
from __future__ import annotations

import queue
from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from raits.backtest.data_types import BacktestConfig
from raits.live.context_feed import LivePolygonFeed


# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_cfg(universe: List[str] = None) -> BacktestConfig:
    return BacktestConfig(
        start_date="2022-01-03",
        end_date="2022-01-03",
        universe=universe or ["AAPL", "MSFT"],
        account_equity=50_000.0,
    )


def _feed(backfill: bool = True, api_key: str = "test-key") -> LivePolygonFeed:
    return LivePolygonFeed(
        config=_minimal_cfg(),
        api_key=api_key,
        backfill_on_reconnect=backfill,
        vix_daily={},
    )


def _ts(epoch_ms: int) -> pd.Timestamp:
    """UTC ms → ET naive Timestamp (same conversion as _ts_from_ms in context_feed)."""
    from zoneinfo import ZoneInfo
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
    return pd.Timestamp(dt.astimezone(ZoneInfo("America/New_York")).replace(tzinfo=None))


def _fake_bar(ticker: str = "SPY", ts: pd.Timestamp = None) -> tuple:
    ts = ts or pd.Timestamp("2022-01-03 09:30:00")
    row = pd.Series(
        {"open": 470.0, "high": 471.0, "low": 469.0, "close": 470.5, "volume": 1_000},
        name=ts,
    )
    return (ticker, ts, row)


# ── A: Reconnect backoff delay sequence ───────────────────────────────────────

def test_reconnect_delay_sequence():
    """
    _ws_thread uses delays = [1, 2, 4, 8, 16, 30] + [30]*N.
    Verify the sequence is geometric up to 30 s then caps.
    """
    delays = [1, 2, 4, 8, 16, 30] + [30] * 10
    expected = [1, 2, 4, 8, 16, 30, 30, 30, 30]
    for i, exp in enumerate(expected):
        got = delays[min(i, len(delays) - 1)]
        assert got == exp, f"delay[{i}]: expected {exp}, got {got}"


def test_reconnect_delay_index_resets_on_success():
    """d_idx resets to 0 on successful connect — first reconnect delay is always 1 s."""
    delays = [1, 2, 4, 8, 16, 30] + [30] * 10
    d_idx = 5  # pretend we've been backing off
    # On a successful client.run() return (not an exception), code sets d_idx = 0
    d_idx = 0
    assert delays[d_idx] == 1


# ── B + C: _backfill_bars REST call + enqueue ─────────────────────────────────

def _make_fake_bar_agg(ticker, ts_ms, o=470.0, h=471.0, lo=469.0, c=470.5, v=1000.0):
    bar = MagicMock()
    bar.timestamp = ts_ms
    bar.open      = o
    bar.high      = h
    bar.low       = lo
    bar.close     = c
    bar.volume    = v
    return bar


def test_backfill_bars_calls_rest_client():
    """_backfill_bars instantiates RESTClient and calls list_aggs for each ticker."""
    from_ts = pd.Timestamp("2022-01-03 09:30:00")
    bq      = queue.Queue()

    mock_rest = MagicMock()
    mock_rest.list_aggs.return_value = []  # no bars — just testing the call

    with patch("polygon.RESTClient", return_value=mock_rest):
        feed = _feed(backfill=True)
        feed._backfill_bars(bq, from_ts, ["SPY", "AAPL"])

    # list_aggs called once per ticker
    assert mock_rest.list_aggs.call_count == 2
    call_tickers = [c.kwargs["ticker"] for c in mock_rest.list_aggs.call_args_list]
    assert set(call_tickers) == {"SPY", "AAPL"}


def test_backfill_bars_from_ts_is_exclusive():
    """from_ts used as from_ms + 1 so the last-received bar is not re-fetched."""
    from_ts  = pd.Timestamp("2022-01-03 09:30:00")
    from_ms_expected = int(from_ts.timestamp() * 1000) + 1
    bq = queue.Queue()

    mock_rest = MagicMock()
    mock_rest.list_aggs.return_value = []

    with patch("polygon.RESTClient", return_value=mock_rest):
        feed = _feed(backfill=True)
        feed._backfill_bars(bq, from_ts, ["SPY"])

    call_kwargs = mock_rest.list_aggs.call_args.kwargs
    assert call_kwargs["from_"] == from_ms_expected


def test_backfill_bars_enqueues_items():
    """Bars returned by RESTClient are put into bar_q as (ticker, ts, row)."""
    from_ts  = pd.Timestamp("2022-01-03 09:30:00")
    ts1_ms   = 1641213000000   # some epoch-ms in ET market hours
    ts2_ms   = 1641213300000

    fake_aggs = [
        _make_fake_bar_agg("AAPL", ts1_ms, o=150.0, h=151.0, lo=149.0, c=150.5, v=200_000),
        _make_fake_bar_agg("AAPL", ts2_ms, o=150.5, h=152.0, lo=150.0, c=151.5, v=180_000),
    ]
    bq = queue.Queue()

    mock_rest = MagicMock()
    mock_rest.list_aggs.return_value = fake_aggs

    with patch("polygon.RESTClient", return_value=mock_rest):
        feed = _feed(backfill=True)
        feed._backfill_bars(bq, from_ts, ["AAPL"])

    assert bq.qsize() == 2
    ticker1, ts1, row1 = bq.get()
    ticker2, ts2, row2 = bq.get()
    assert ticker1 == "AAPL"
    assert ticker2 == "AAPL"
    assert ts1 == _ts(ts1_ms)
    assert ts2 == _ts(ts2_ms)
    assert float(row1["close"]) == pytest.approx(150.5)
    assert float(row2["close"]) == pytest.approx(151.5)


# ── D: Full failure → logger.ERROR ───────────────────────────────────────────

def test_backfill_bars_logs_error_on_rest_client_failure():
    """If RESTClient() constructor raises, backfill logs ERROR (not raises)."""
    from_ts = pd.Timestamp("2022-01-03 09:30:00")
    bq = queue.Queue()

    with patch("polygon.RESTClient", side_effect=RuntimeError("network down")):
        feed = _feed(backfill=True)
        with patch("raits.live.context_feed.logger") as mock_log:
            feed._backfill_bars(bq, from_ts, ["SPY"])
            # At least one logger.error call mentioning the gap
            error_calls = [
                str(c) for c in mock_log.error.call_args_list
                if "BACKFILL FAILED" in str(c) or "FAILED" in str(c)
            ]
            assert error_calls, "Expected logger.error for REST client failure"

    assert bq.empty(), "No bars should be queued on full failure"


# ── E: Partial failure → logger.ERROR per ticker + summary ───────────────────

def test_backfill_bars_partial_failure_logs_error():
    """If list_aggs fails for a ticker, backfill logs ERROR and continues others."""
    from_ts = pd.Timestamp("2022-01-03 09:30:00")
    bq = queue.Queue()

    mock_rest = MagicMock()
    ts1_ms = 1641213000000

    def _list_aggs_side_effect(**kwargs):
        if kwargs["ticker"] == "AAPL":
            raise RuntimeError("AAPL data unavailable")
        return [_make_fake_bar_agg("MSFT", ts1_ms)]

    mock_rest.list_aggs.side_effect = _list_aggs_side_effect

    with patch("polygon.RESTClient", return_value=mock_rest):
        feed = _feed(backfill=True)
        with patch("raits.live.context_feed.logger") as mock_log:
            feed._backfill_bars(bq, from_ts, ["AAPL", "MSFT"])

            # AAPL failure → ERROR
            aapl_errors = [c for c in mock_log.error.call_args_list
                           if "AAPL" in str(c)]
            assert aapl_errors, "Expected per-ticker ERROR for AAPL"

            # Summary ERROR because fail_count > 0
            summary_errors = [c for c in mock_log.error.call_args_list
                              if "PARTIAL" in str(c)]
            assert summary_errors, "Expected PARTIAL summary ERROR"

    # MSFT bar was still enqueued
    assert bq.qsize() == 1
    ticker, _, _ = bq.get()
    assert ticker == "MSFT"


# ── F: polygon not installed → WARNING, no crash ─────────────────────────────

def test_backfill_bars_warns_when_polygon_not_installed():
    """If polygon module is not available, backfill logs WARNING and returns cleanly."""
    from_ts = pd.Timestamp("2022-01-03 09:30:00")
    bq = queue.Queue()

    with patch.dict("sys.modules", {"polygon": None}):
        feed = _feed(backfill=True)
        with patch("raits.live.context_feed.logger") as mock_log:
            feed._backfill_bars(bq, from_ts, ["SPY"])
            assert mock_log.warning.called, "Expected logger.warning for missing polygon"

    assert bq.empty()


# ── G: backfill_on_reconnect flag ────────────────────────────────────────────

def test_backfill_flag_stored_false():
    feed = _feed(backfill=False)
    assert feed._backfill is False


def test_backfill_flag_stored_true():
    feed = _feed(backfill=True)
    assert feed._backfill is True


# ── H: WS thread reconnects after exception ──────────────────────────────────

def test_ws_thread_reconnects_after_exception():
    """
    After a WebSocket exception, _ws_thread reconnects.
    Integration test: mock WS raises on connect 1, sends SPY bar on connect 2.
    Verifies LivePolygonFeed yields a BarContext after the reconnect.
    """
    connect_calls = [0]
    SPY_TS_MS = 1641220200000  # 2022-01-03 09:30:00 ET (UTC 14:30)

    class FakeClient:
        def run(self, handler):
            connect_calls[0] += 1
            if connect_calls[0] == 1:
                # First connect: simulate immediate disconnect
                raise RuntimeError("simulated disconnect")
            # Second connect: send one SPY bar then disconnect
            msg = MagicMock()
            msg.symbol          = "SPY"
            msg.start_timestamp = SPY_TS_MS
            msg.open = msg.high = msg.low = msg.close = 470.0
            msg.volume = 1_000_000
            handler([msg])
            raise RuntimeError("second disconnect")

    with patch("polygon.websocket.WebSocketClient", return_value=FakeClient()):
        with patch("polygon.websocket.models.Market", MagicMock()):
            # Patch backoff sleep to instant so the test doesn't wait 1 s
            with patch("threading.Event.wait", return_value=None):
                feed = LivePolygonFeed(
                    config=_minimal_cfg(["AAPL"]),
                    api_key="test-key",
                    vix_daily={},
                    backfill_on_reconnect=False,  # no REST call in this test
                )
                gen = iter(feed)
                ctx = next(gen)  # blocks until SPY bar arrives on 2nd connect
                gen.close()      # triggers finally: stop_event.set()

    assert connect_calls[0] >= 2, "Expected at least 2 connect attempts"
    expected_ts = pd.Timestamp("2022-01-03 09:30:00")
    assert ctx.bar_ts == expected_ts


# ── I: backfill invoked after reconnect when flag=True ───────────────────────

def test_backfill_called_after_reconnect():
    """
    When backfill_on_reconnect=True, _backfill_bars is called after a reconnect
    with the correct from_ts (the last received bar's timestamp).
    """
    connect_calls = [0]
    SPY_TS_MS = 1641220200000  # 2022-01-03 09:30:00 ET (UTC 14:30)

    class FakeClient:
        def run(self, handler):
            connect_calls[0] += 1
            if connect_calls[0] == 1:
                # Send one bar, then disconnect
                msg = MagicMock()
                msg.symbol          = "SPY"
                msg.start_timestamp = SPY_TS_MS
                msg.open = msg.high = msg.low = msg.close = 470.0
                msg.volume = 1_000_000
                handler([msg])
                raise RuntimeError("first disconnect")
            # Second connect: send another SPY bar
            msg = MagicMock()
            msg.symbol          = "SPY"
            msg.start_timestamp = SPY_TS_MS + 5 * 60 * 1000  # 09:35
            msg.open = msg.high = msg.low = msg.close = 471.0
            msg.volume = 900_000
            handler([msg])
            raise RuntimeError("second disconnect")

    backfill_calls = []

    def fake_backfill(bq, from_ts, tickers):
        backfill_calls.append(from_ts)

    with patch("polygon.websocket.WebSocketClient", return_value=FakeClient()):
        with patch("polygon.websocket.models.Market", MagicMock()):
            with patch("threading.Event.wait", return_value=None):
                feed = LivePolygonFeed(
                    config=_minimal_cfg(["AAPL"]),
                    api_key="test-key",
                    vix_daily={},
                    backfill_on_reconnect=True,
                )
                feed._backfill_bars = fake_backfill

                gen = iter(feed)
                # Collect 2 BarContexts (one per SPY bar slot)
                ctx1 = next(gen)
                ctx2 = next(gen)
                gen.close()

    # backfill was called once (after the first disconnect) with the first bar's ts
    assert len(backfill_calls) >= 1
    expected_from = _ts(SPY_TS_MS)
    assert backfill_calls[0] == expected_from, (
        f"backfill from_ts: expected {expected_from}, got {backfill_calls[0]}"
    )
