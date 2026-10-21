from __future__ import annotations

import json
from pathlib import Path

import pytest
from futures.circuit_breaker import CircuitBreaker
from global_index import track1_signal_layer as sl
from monitor.backend import track1_runtime_reader as rr


ROOT = Path(__file__).resolve().parents[1]


def _write_book(root: Path, payload: dict) -> Path:
    path = root / rr.BOOK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _payload(**overrides) -> dict:
    payload = {
        "schema_version": 2,
        "route": sl.ROUTE,
        "positions": [],
        "equity": 50_000.0,
        "peak_equity": 50_000.0,
        "day_start_equity": 50_000.0,
    }
    payload.update(overrides)
    return payload


def _signal_breaker(path: Path) -> dict:
    book = sl.Track1Book(
        guard=sl.make_guard(),
        breaker=CircuitBreaker(account=sl.ACCOUNT),
        enforce_windows=False,
    )
    state = sl.apply_route_book_breaker_state(book, path)
    if not state["armed"]:
        return {
            "armed": False,
            "status": "UNARMED",
            "level": "UNARMED",
            "allow_new_entries": None,
            "reason": state["reason"],
        }
    status = book.breaker.status(book.equity)
    return {
        "armed": True,
        "status": "ARMED",
        "level": status["level"],
        "allow_new_entries": status["allow_new_entries"],
        "reason": None,
    }


def _dashboard_breaker(root: Path) -> dict:
    out = rr._breaker(root)
    return {
        "armed": out["armed"],
        "status": out["status"],
        "level": out["level"],
        "allow_new_entries": out["allow_new_entries"],
        "reason": out.get("reason"),
    }


def _slot_breaker_after_day_open(path: Path, when: str = "2026-09-25 14:10:00") -> dict:
    book = sl.Track1Book(
        guard=sl.make_guard(),
        breaker=CircuitBreaker(account=sl.ACCOUNT),
        enforce_windows=False,
    )
    sl.apply_route_book_breaker_state(book, path)
    book.process_instant(when, [])
    status = book.breaker.status(book.equity)
    return {
        "armed": True,
        "status": "ARMED",
        "level": status["level"],
        "allow_new_entries": status["allow_new_entries"],
        "daily_loss_pct": round(float(status["daily_loss_pct"]) * 100, 4),
        "day_start_equity": book.breaker._day_start_equity,
    }


def _assert_same_route_breaker_answer(root: Path) -> tuple[dict, dict]:
    signal = _signal_breaker(root / rr.BOOK_PATH)
    dashboard = _dashboard_breaker(root)
    assert dashboard == signal
    return signal, dashboard


def test_signal_layer_and_dashboard_agree_on_breaker_arming_shapes(tmp_path):
    cases = {
        "plausible": _payload(equity=48_000.0, peak_equity=51_234.5,
                              day_start_equity=50_408.25),
        "broker_balance": _payload(equity=996_730.93, peak_equity=996_730.93,
                                   day_start_equity=996_730.93),
        "pnl_delta": _payload(equity=408.25, peak_equity=50_000.0,
                              day_start_equity=50_000.0),
        "zero": _payload(equity=0.0, peak_equity=0.0, day_start_equity=0.0),
    }
    pairs = {}
    for name, payload in cases.items():
        root = tmp_path / name
        _write_book(root, payload)
        pairs[name] = _assert_same_route_breaker_answer(root)

    live_pair = _assert_same_route_breaker_answer(ROOT)
    # The real book was seeded after this test was first written. Its state may legitimately
    # move from UNARMED to ARMED; what is invariant is that both readers give the same answer.
    assert live_pair[0] == live_pair[1], live_pair

    # Kept for the report: pytest prints this when the assertion above fails under the
    # old dashboard-side copy, and it documents all five compared shapes in one place.
    assert set(pairs) == {"plausible", "broker_balance", "pnl_delta", "zero"}


def test_no_durable_slot_row_is_needed_to_report_unarmed(tmp_path):
    assert not (tmp_path / rr.COVERAGE_DIR).exists()
    _write_book(tmp_path, _payload(equity=0.0, peak_equity=0.0, day_start_equity=0.0))

    signal, dashboard = _assert_same_route_breaker_answer(tmp_path)

    assert signal["armed"] is False
    assert dashboard["armed"] is False
    assert "out-of-band equity=0.0" in dashboard["reason"]


def test_tight_equity_band_rejects_account_scale_marks_and_accepts_sleeve_marks(tmp_path):
    cases = {
        "current_broker": (_payload(
            equity=251_752.25,
            peak_equity=251_752.25,
            day_start_equity=251_752.25,
            broker_equity=251_752.25,
        ), False),
        "broker_at_240k": (_payload(
            equity=240_000.0,
            peak_equity=240_000.0,
            day_start_equity=240_000.0,
        ), False),
        "broker_at_80k": (_payload(
            equity=80_000.0,
            peak_equity=80_000.0,
            day_start_equity=80_000.0,
            broker_equity=80_000.0,
        ), False),
        "largest_recorded_sleeve": (_payload(
            equity=114_902.91,
            peak_equity=114_902.91,
            day_start_equity=114_902.91,
            broker_equity=251_752.25,
        ), True),
        "operator_seed": (_payload(
            equity=50_000.0,
            peak_equity=50_000.0,
            day_start_equity=50_000.0,
            broker_equity=251_752.25,
        ), True),
    }

    results = {}
    for name, (payload, expected_armed) in cases.items():
        path = _write_book(tmp_path / name, payload)
        state = sl.route_book_breaker_state(path)
        results[name] = state
        assert state["armed"] is expected_armed, (name, state)

    upper = sl.EQUITY_MARK_UPPER
    current_margin_pct = (251_752.25 - upper) / 251_752.25 * 100.0
    assert current_margin_pct == pytest.approx(54.35873562202522, rel=1e-12)
    assert "out-of-band" in results["current_broker"]["reason"]
    assert "matches broker_equity" in results["broker_at_80k"]["reason"]
    assert results["operator_seed"]["equity"] == 50_000.0
    assert results["operator_seed"]["peak_equity"] == 50_000.0
    assert results["operator_seed"]["day_start_equity"] == 50_000.0


def test_deep_drawdowns_are_halted_not_hidden_by_the_band_floor(tmp_path):
    cases = [
        (46_000.0, True, "HALT_DAY"),
        (42_000.0, True, "HALT"),
        (40_000.0, True, "HALT"),
        (35_000.0, True, "HALT"),
        (30_000.0, True, "HALT"),
        (408.25, False, "UNARMED"),
    ]

    for mark, expected_armed, expected_level in cases:
        path = _write_book(
            tmp_path / str(mark).replace(".", "_"),
            _payload(equity=mark, peak_equity=50_000.0, day_start_equity=50_000.0),
        )
        state = sl.route_book_breaker_state(path)
        assert state["armed"] is expected_armed, (mark, state)
        if expected_armed:
            book = sl.Track1Book(
                guard=sl.make_guard(),
                breaker=CircuitBreaker(account=sl.ACCOUNT),
                enforce_windows=False,
            )
            sl.apply_route_book_breaker_state(book, path)
            status = book.breaker.status(book.equity)
            assert status["level"] == expected_level, (mark, status)
            assert status["allow_new_entries"] is (expected_level == "OK")
        else:
            assert "out-of-band equity=408.25" in state["reason"]

    admitted_drawdown_pct = (sl.ACCOUNT - sl.EQUITY_MARK_LOWER) / sl.ACCOUNT * 100.0
    assert admitted_drawdown_pct == pytest.approx(90.0)


def test_in_band_marks_without_broker_context_are_armed_with_named_identity_gap(tmp_path):
    path = _write_book(
        tmp_path,
        _payload(equity=80_000.0, peak_equity=80_000.0, day_start_equity=80_000.0),
    )

    state = sl.route_book_breaker_state(path)

    assert state["armed"] is True
    assert state["identity_check"] == "not_possible"
    assert state["identity_reason"] == (
        "broker_equity mark absent; armed without broker-identity check")


def test_dashboard_agrees_with_running_slot_after_day_open(tmp_path):
    path = _write_book(
        tmp_path,
        _payload(equity=51_000.0, peak_equity=55_000.0, day_start_equity=54_000.0,
                 cur_day="2026-09-25"),
    )

    dashboard = _dashboard_breaker(tmp_path)
    slot = _slot_breaker_after_day_open(path)

    assert dashboard["armed"] is True
    assert dashboard["level"] == slot["level"]
    assert dashboard["allow_new_entries"] == slot["allow_new_entries"]
    assert slot["daily_loss_pct"] == 5.5556
    assert slot["day_start_equity"] == 54_000.0
