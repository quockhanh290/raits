from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from futures.circuit_breaker import CircuitBreaker
from global_index import run_live_day_track1 as live
from global_index import track1_paper_send as ps
from global_index import track1_signal_layer as sl
from global_index.net_exposure_multi import Position


def _book() -> sl.Track1Book:
    return sl.Track1Book(
        guard=sl.make_guard(),
        breaker=CircuitBreaker(account=sl.ACCOUNT),
        enforce_windows=False,
    )


def _closing_position(ts: str, pnl: float) -> sl.Held:
    cand = sl.Candidate(
        trade_id=f"close::{ts}",
        sleeve=sl.SWING,
        instrument="MES",
        direction="LONG",
        qty=1,
        risk_dollars=100.0,
        entry_time="2026-09-24 15:55:00",
        exit_time=ts,
        pnl_sized=pnl,
    )
    return sl.Held(cand, Position("MES", "LONG", 1, 100.0, sl.SWING))


def _old_order_daily_loss_pct(*, start_equity: float, close_pnl: float, ts: str) -> float:
    book = _book()
    book.equity = start_equity
    book.open_book.append(_closing_position(ts, close_pnl))
    book.settle_due(ts)
    book.begin_instant(ts)
    return float(book.breaker.status(book.equity)["daily_loss_pct"]) * 100


def test_first_instant_close_counts_toward_that_days_loss():
    ts = "2026-09-25 14:10:00"
    book = _book()
    book.equity = 54_000.0
    book.breaker.peak_equity = 55_000.0
    book.open_book.append(_closing_position(ts, -3_000.0))

    book.process_instant(ts, [])
    status = book.breaker.status(book.equity)

    assert _old_order_daily_loss_pct(start_equity=54_000.0, close_pnl=-3_000.0, ts=ts) == 0.0
    assert float(status["daily_loss_pct"]) * 100 == pytest.approx(5.5555555556)
    assert status["level"] == "HALT_DAY"
    assert status["allow_new_entries"] is False


def test_seeded_session_day_survives_the_day_open(tmp_path):
    path = tmp_path / "live_positions.track1.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "route": sl.ROUTE,
        "positions": [],
        "equity": 51_000.0,
        "peak_equity": 55_000.0,
        "day_start_equity": 54_000.0,
        "cur_day": "2026-09-25",
    }), encoding="utf-8")
    book = _book()

    state = sl.apply_route_book_breaker_state(book, path)
    before = book.breaker._day_start_equity
    book.process_instant("2026-09-25 14:10:00", [])
    after = book.breaker._day_start_equity

    assert state["cur_day"] == pd.Timestamp("2026-09-25")
    assert before == 54_000.0
    assert after == 54_000.0
    assert book.breaker.status(book.equity)["level"] == "HALT_DAY"


def test_fresh_carried_book_writes_absence_not_default_equity(tmp_path):
    state, carried_from = live._carry_forward_book(tmp_path / "missing.json", "2026-09-25")

    assert carried_from is None
    assert state["equity"] is None
    assert state["peak_equity"] is None
    assert state["day_start_equity"] is None
    assert state["cur_day"] is None
    assert state["broker_equity"] is None
    assert sl.ACCOUNT not in (state["equity"], state["peak_equity"], state["day_start_equity"])


def test_broker_mark_is_context_and_never_arms_the_breaker(tmp_path):
    path = tmp_path / "live_positions.track1.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "route": sl.ROUTE,
        "positions": [],
        "equity": None,
        "peak_equity": None,
        "day_start_equity": None,
        "cur_day": None,
    }), encoding="utf-8")

    class Broker:
        def get_equity(self):
            return 996_730.93

    assert ps.record_broker_equity(Broker(), book_path=path) is True
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["broker_equity"] == 996_730.93

    book = _book()
    state = sl.apply_route_book_breaker_state(book, path)

    assert state["armed"] is False
    assert state["reason"] == "route book carries no measured equity marks"
    assert book.breaker is None
