from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from global_index import run_live_day_track1 as rl
from global_index import track1_signal_layer as sl


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _book_payload(**over):
    payload = {
        "schema_version": 2,
        "route": sl.ROUTE,
        "positions": [],
        "equity": 50000.0,
        "peak_equity": 50000.0,
        "day_start_equity": 50000.0,
    }
    payload.update(over)
    return payload


def _candidate(day="2026-09-25"):
    return sl.Candidate(
        trade_id=f"normal_r4::MES::{day}",
        sleeve=sl.SWING,
        instrument="MES",
        direction="LONG",
        qty=1,
        risk_dollars=100.0,
        entry_time=f"{day} 14:10:00",
    )


class _Joined:
    def __init__(self):
        self.frame = pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2026-09-25 14:05")]),
        )


class _FreshVerdict:
    allow = True
    checks = ()


class _OneCandidateSource:
    last_diagnostics = {}

    def candidates(self, now):
        return [_candidate()]


def _coverage_rows(root):
    rows = []
    for p in (root / "ledger").glob("window_coverage_*.jsonl"):
        rows.extend(json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
                    if line.strip())
    return rows


def _run_real_slot_row(tmp_path, monkeypatch, *, book):
    from global_index import track1_freshness as fresh
    from global_index import track1_intraday as intra
    from global_index import track1_live_source as live_source
    import global_index.window_ledger as wl

    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(ledger))
    monkeypatch.setenv("RAITS_ROUTE", sl.ROUTE)
    monkeypatch.setattr(wl, "_disabled", False, raising=False)
    monkeypatch.setattr(live_source, "sleeve_frames",
                        lambda **kw: {kw["sleeves"][0]: {"MES": _Joined()}})
    monkeypatch.setattr(rl, "_resample", lambda frame, sleeve, requirement=None: frame)
    monkeypatch.setattr(intra, "validate",
                        lambda sleeve, bars, **kw: intra.Verdict(sleeve, True, (), ()))
    monkeypatch.setattr(fresh, "evaluate", lambda **kw: _FreshVerdict())
    monkeypatch.setattr(rl, "emit_explanations",
                        lambda decisions, **kw: {"records": len(decisions)})
    _write_json(tmp_path / rl.POSITIONS_PATH, book)

    result = rl.observe_live_slot(
        sl.SWING,
        "TRACK1_SWING_1405",
        now_et=pd.Timestamp("2026-09-25 14:05", tz="America/New_York"),
        provider=object(),
        live_source=_OneCandidateSource(),
        root=str(tmp_path),
        out_dir=rl.OPERATIONAL_SHADOW_DIR,
    )
    rows = [r for r in _coverage_rows(tmp_path)
            if r.get("event") == "slot_observed" and r.get("slot_id") == "TRACK1_SWING_1405"]
    assert len(rows) == 1
    return result, rows[0]


def test_b11_kill_switch_is_checked_at_send_time(tmp_path):
    assert rl._kill_switch_send_summary(tmp_path) is None
    (tmp_path / rl.STOP_FILE).write_text("operator stop", encoding="utf-8")

    summary = rl._kill_switch_send_summary(tmp_path)

    assert summary.status == rl._ps.GATE_CLOSED
    assert summary.sent == 0
    assert rl.STOP_FILE in summary.reason
    assert "observation kept" in summary.reason


def test_b11_slot_row_records_armed_and_unarmed_breaker_state(tmp_path, monkeypatch):
    armed_result, armed_row = _run_real_slot_row(
        tmp_path / "armed",
        monkeypatch,
        book=_book_payload(equity=50000.0, peak_equity=50000.0, day_start_equity=50000.0),
    )
    unarmed_result, unarmed_row = _run_real_slot_row(
        tmp_path / "unarmed",
        monkeypatch,
        book=_book_payload(equity=0.0, peak_equity=0.0, day_start_equity=0.0),
    )

    assert armed_result["decided"] is True
    assert unarmed_result["decided"] is True
    assert armed_result["reason"] == rl.DECIDED
    assert armed_result["candidates"] == 1
    assert armed_result["accepted"] == 1
    assert armed_result["rejected"] == 0
    assert armed_row["breaker_armed"] is True
    assert armed_row["breaker_unarmed_reason"] is None
    assert unarmed_row["breaker_armed"] is False
    assert "out-of-band equity=0.0" in unarmed_row["breaker_unarmed_reason"]
    print("ARMED_ROW " + json.dumps(
        {k: armed_row.get(k) for k in (
            "slot_id", "decided", "reason", "candidates", "accepted", "rejected",
            "held_at_decision", "breaker_armed", "breaker_source",
            "breaker_unarmed_reason")},
        sort_keys=True))
    print("UNARMED_ROW " + json.dumps(
        {k: unarmed_row.get(k) for k in (
            "slot_id", "decided", "reason", "candidates", "accepted", "rejected",
            "held_at_decision", "breaker_armed", "breaker_source",
            "breaker_unarmed_reason")},
        sort_keys=True))
    print("ARMED_RESULT " + json.dumps(
        {k: armed_result.get(k) for k in (
            "decided", "reason", "candidates", "accepted", "rejected",
            "held_at_decision", "breaker")},
        sort_keys=True))


def test_b11_the_live_slot_send_is_conditioned_on_the_kill_switch_summary():
    import inspect

    src = inspect.getsource(rl.observe_live_slot)
    kill = src.index("_send = _kill_switch_send_summary(root)")
    guard = src.index("if _send is None:", kill)
    send = src.index("_ps.maybe_send_orders", guard)

    assert kill < guard < send


def test_b12_breaker_uses_persisted_equity_and_trips_on_measured_drawdown(tmp_path):
    p = _write_json(
        tmp_path / "live_positions.track1.json",
        _book_payload(equity=42000.0, peak_equity=50000.0, day_start_equity=50000.0),
    )
    book = sl.Track1Book(guard=sl.make_guard(), breaker=rl.CircuitBreaker(account=sl.ACCOUNT),
                         enforce_windows=False)

    state = sl.apply_route_book_breaker_state(book, p)
    (decision,) = book.process_instant("2026-09-25 14:10:00", [_candidate()])

    assert state["armed"] is True
    assert state["equity"] == pytest.approx(42000.0)
    assert decision.verdict == sl.HALT_BREAKER


def test_b12_flat_measured_day_does_not_trip_breaker(tmp_path):
    p = _write_json(tmp_path / "live_positions.track1.json", _book_payload())
    book = sl.Track1Book(guard=sl.make_guard(), breaker=rl.CircuitBreaker(account=sl.ACCOUNT),
                         enforce_windows=False)

    state = sl.apply_route_book_breaker_state(book, p)
    (decision,) = book.process_instant("2026-09-25 14:10:00", [_candidate()])

    assert state["armed"] is True
    assert decision.verdict == sl.TAKE


def test_b12_zero_placeholder_book_leaves_breaker_unarmed_and_says_so(tmp_path):
    p = _write_json(
        tmp_path / "live_positions.track1.json",
        _book_payload(equity=0.0, peak_equity=0.0, day_start_equity=0.0),
    )
    book = sl.Track1Book(guard=sl.make_guard(), breaker=rl.CircuitBreaker(account=sl.ACCOUNT),
                         enforce_windows=False)

    state = sl.apply_route_book_breaker_state(book, p)

    assert state["armed"] is False
    assert book.breaker is None
    assert "out-of-band" in state["reason"]
    assert "equity=0.0" in state["reason"]


@pytest.mark.parametrize(
    ("day_start", "armed", "expected_daily_loss"),
    [
        pytest.param(50408.25, True, 0.047774917796194076, id="plausible-system-equity"),
        pytest.param(996730.93, False, None, id="broker-balance"),
        pytest.param(408.25, False, None, id="pnl-delta"),
        pytest.param(0.0, False, None, id="zero"),
    ],
)
def test_b12_equity_mark_band_arms_only_plausible_system_marks(
        tmp_path, day_start, armed, expected_daily_loss):
    p = _write_json(
        tmp_path / "live_positions.track1.json",
        _book_payload(equity=48000.0, peak_equity=50408.25, day_start_equity=day_start),
    )
    book = sl.Track1Book(guard=sl.make_guard(), breaker=rl.CircuitBreaker(account=sl.ACCOUNT),
                         enforce_windows=False)

    state = sl.apply_route_book_breaker_state(book, p)

    assert state["armed"] is armed
    assert (book.breaker is not None) is armed
    if armed:
        status = book.breaker.status(book.equity)
        assert status["daily_loss_pct"] == pytest.approx(expected_daily_loss)
        assert status["level"] == "HALT_DAY"
        assert status["allow_new_entries"] is False
    else:
        assert "out-of-band" in state["reason"]
        assert f"day_start_equity={day_start!r}" in state["reason"]


def test_b12_absent_marks_and_implausible_marks_have_different_named_reasons(tmp_path):
    absent_path = _write_json(
        tmp_path / "absent" / "live_positions.track1.json",
        {"schema_version": 2, "route": sl.ROUTE, "positions": []},
    )
    bad_path = _write_json(
        tmp_path / "bad" / "live_positions.track1.json",
        _book_payload(equity=408.25, peak_equity=50000.0, day_start_equity=50000.0),
    )
    absent_book = sl.Track1Book(
        guard=sl.make_guard(), breaker=rl.CircuitBreaker(account=sl.ACCOUNT),
        enforce_windows=False)
    bad_book = sl.Track1Book(
        guard=sl.make_guard(), breaker=rl.CircuitBreaker(account=sl.ACCOUNT),
        enforce_windows=False)

    absent = sl.apply_route_book_breaker_state(absent_book, absent_path)
    bad = sl.apply_route_book_breaker_state(bad_book, bad_path)

    assert absent["armed"] is False
    assert bad["armed"] is False
    assert absent["reason"] == "route book carries no measured equity marks"
    assert "out-of-band equity=408.25" in bad["reason"]
    assert absent["reason"] != bad["reason"]


@pytest.mark.parametrize("field", ["equity", "peak_equity", "day_start_equity"])
def test_b12_band_names_each_invalid_breaker_field(tmp_path, field):
    payload = _book_payload(broker_equity=996730.93)
    payload[field] = 408.25
    p = _write_json(tmp_path / f"{field}.json", payload)
    book = sl.Track1Book(guard=sl.make_guard(), breaker=rl.CircuitBreaker(account=sl.ACCOUNT),
                         enforce_windows=False)

    state = sl.apply_route_book_breaker_state(book, p)

    assert state["armed"] is False
    assert book.breaker is None
    assert f"out-of-band {field}=408.25" in state["reason"]
    assert "broker_equity" not in state["reason"]


def test_b12_plausible_marks_are_preserved_and_broker_mark_is_not_applied(tmp_path):
    p = _write_json(
        tmp_path / "live_positions.track1.json",
        _book_payload(
            equity=48000.0,
            peak_equity=51234.5,
            day_start_equity=50408.25,
            broker_equity=996730.93,
        ),
    )
    breaker = rl.CircuitBreaker(account=sl.ACCOUNT)
    book = sl.Track1Book(guard=sl.make_guard(), breaker=breaker, enforce_windows=False)

    state = sl.apply_route_book_breaker_state(book, p)

    assert state == {
        "armed": True,
        "source": str(p),
        "equity": 48000.0,
        "peak_equity": 51234.5,
        "day_start_equity": 50408.25,
        "identity_check": "checked",
    }
    assert book.equity == 48000.0
    assert breaker.peak_equity == 51234.5
    assert breaker._day_start_equity == 50408.25


def test_b13_recorded_reconcile_failure_blocks_new_entries_only(tmp_path):
    row = {
        "schema": "track1_b1/1",
        "status": "FAIL",
        "code": "broker_has_positions",
        "detail": "broker/file mismatch: broker holds MES not in book",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {},
        "findings": {},
    }
    _write_json(tmp_path / "global_index" / "track1_b1" / "track1_b1_20260925.jsonl", {})
    p = tmp_path / "global_index" / "track1_b1" / "track1_b1_20260925.jsonl"
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")

    reason = rl._entry_reconcile_halt(tmp_path, now=datetime.now(timezone.utc))
    book = sl.Track1Book(guard=sl.make_guard(), breaker=rl._EntryHaltBreaker(reason),
                         enforce_windows=False)
    (decision,) = book.process_instant("2026-09-25 14:10:00", [_candidate()])

    assert "broker/file mismatch" in reason
    assert decision.verdict == sl.HALT_BREAKER


def test_b13_clean_reconcile_does_not_block_new_entries(tmp_path):
    row = {
        "schema": "track1_b1/1",
        "status": "PASS",
        "code": "legacy_and_broker_flat",
        "detail": "clean",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {},
        "findings": {},
    }
    p = tmp_path / "global_index" / "track1_b1" / "track1_b1_20260925.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(row) + "\n", encoding="utf-8")

    assert rl._entry_reconcile_halt(tmp_path, now=datetime.now(timezone.utc)) == ""


def test_b14_existing_book_without_positions_key_raises(tmp_path):
    p = _write_json(tmp_path / "live_positions.track1.json", {"route": sl.ROUTE})

    with pytest.raises(sl.BootstrapRefused, match="no `positions` key"):
        sl.read_route_positions(p)


def test_b14_non_dictionary_position_row_raises(tmp_path):
    p = _write_json(
        tmp_path / "live_positions.track1.json",
        {"route": sl.ROUTE, "positions": [{"trade_id": "ok"}, "bad-row"]},
    )

    with pytest.raises(sl.BootstrapRefused, match="non-object positions\\[1\\]"):
        sl.read_route_positions(p)


def test_b14_absent_book_still_returns_empty(tmp_path):
    assert sl.read_route_positions(tmp_path / "absent.json") == []


def test_b14_rows_that_load_keep_identical_values(tmp_path):
    row = {
        "trade_id": "normal_r4::MES::2026-09-25",
        "sleeve": sl.SWING,
        "instrument": "MES",
        "direction": "LONG",
        "qty": 1,
        "risk_dollars": 123.45,
        "entry_time": "2026-09-25 14:10:00",
        "exit_time": None,
        "entry_price": 6700.25,
        "stop_price": 6650.25,
    }
    closed = dict(row, trade_id="closed", exit_time="2026-09-25 15:00:00")
    p = _write_json(
        tmp_path / "live_positions.track1.json",
        {"route": sl.ROUTE, "positions": [row, closed]},
    )

    assert sl.read_route_positions(p) == [row]
