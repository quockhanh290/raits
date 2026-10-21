"""Focused gates for PLAN_ADDRESS_FINDINGS_2026-09-25 Batch 2."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from monitor.backend import paper_evidence_reader as per


def _book_row(**overrides):
    row = {
        "instrument": "MES", "sleeve": "roska4_swing", "direction": "LONG",
        "qty": 1, "entry_time": "2026-09-25 15:00:00", "entry_price": 7797.25,
        "stop_price": 7652.0,
    }
    row.update(overrides)
    return row


def _broker(*, readable=True, with_stop=True):
    return {
        "connected": readable, "last_update": "2026-09-25T20:20:16Z",
        "positions_ok": readable, "orders_ok": readable,
        "positions_error": None if readable else "portfolio unavailable",
        "orders_error": None if readable else "orders unavailable",
        "positions": [{"inst": "MESZ6", "position": 1}] if readable else [],
        "orders": ([{"inst": "MESZ6", "type": "STP", "action": "SELL", "qty": 1,
                     "order_id": 14, "status": "PreSubmitted"}]
                   if readable and with_stop else []),
        "contract_specs": {},
    }


@pytest.mark.parametrize(
    "broker, expected_status, expected_row",
    [
        (_broker(), "PASS", "PROTECTED"),
        (_broker(with_stop=False), "BREACH", "UNPROTECTED"),
        (_broker(readable=False), "UNKNOWN", "UNKNOWN"),
    ],
)
def test_b2_1_broker_protection_has_three_states(broker, expected_status, expected_row):
    protection = per._broker_protection([_book_row()], broker)
    rows = per._position_rows([_book_row()], protection)
    assert protection["status"] == expected_status
    assert rows[0]["status"] == expected_row
    if expected_status == "UNKNOWN":
        assert protection["protected"] if "protected" in protection else 0 == 0


def test_b2_1_empty_book_is_known_empty_even_when_broker_is_unreadable():
    protection = per._broker_protection([], _broker(readable=False))
    rows = per._position_rows([], protection)
    assert protection["status"] == "MISSING"
    assert protection["protected"] == 0
    assert protection["unprotected"] == 0
    assert rows == []


def test_b2_1_pending_submit_is_not_a_working_stop():
    broker = _broker()
    broker["orders"][0]["status"] = "PendingSubmit"
    assert per._broker_protection([_book_row()], broker)["status"] == "BREACH"


def test_b2_1_four_book_positions_match_four_presubmitted_broker_stops():
    positions = [
        _book_row(instrument="M2K"), _book_row(instrument="MYM"),
        _book_row(instrument="MNKD", sleeve="global_nkd"), _book_row(instrument="MES"),
    ]
    broker = {
        "connected": True, "positions_ok": True, "orders_ok": True,
        "last_update": "2026-09-25T20:20:16Z", "contract_specs": {},
        "positions": [{"inst": symbol, "position": 1}
                      for symbol in ("M2KZ6", "MYMZ6", "MNKZ6", "MESZ6")],
        "orders": [{"inst": symbol, "type": "STP", "action": "SELL", "qty": 1,
                    "order_id": order_id, "status": "PreSubmitted"}
                   for symbol, order_id in (("M2KZ6", 8), ("MYMZ6", 10),
                                             ("MNKZ6", 12), ("MESZ6", 14))],
    }
    protection = per._broker_protection(positions, broker)
    assert protection["status"] == "PASS"
    assert protection["protected"] == 4
    assert [row["status"] for row in per._position_rows(positions, protection)] == [
        "PROTECTED", "PROTECTED", "PROTECTED", "PROTECTED"]


def test_b2_2_track1_and_legacy_book_dialects_keep_identity_and_size():
    track1 = per._position_rows([_book_row()])[0]
    legacy = per._position_rows([{
        "inst": "M2K", "cluster": "roska4_swing", "direction": "SHORT",
        "contracts": 2, "entry_day": "2026-09-24", "stop_price": 2900,
    }])[0]
    assert (track1["inst"], track1["cluster"], track1["contracts"]) == (
        "MES", "roska4_swing", 1)
    assert (legacy["inst"], legacy["cluster"], legacy["contracts"]) == (
        "M2K", "roska4_swing", 2)


def _tree(root: Path) -> None:
    runtime = root / "global_index" / "track1_runtime"
    (runtime / "orders").mkdir(parents=True)
    (runtime / "audits").mkdir()
    (runtime / "orders" / "track1_orders_20260925.jsonl").write_text(
        json.dumps({"order_id": "68", "state": "filled"}) + "\n", encoding="utf-8")
    (runtime / "audits" / "track1_audit_20260925.jsonl").write_text("{}\n", encoding="utf-8")
    (runtime / "trade_log.track1.jsonl").write_text(json.dumps({
        "type": "OPEN", "route": "track1_candidate", "inst": "MES",
        "cluster": "roska4_swing", "direction": "LONG", "contracts": 1,
        "filled_qty": 1, "entry_day": "2026-09-25", "expected_entry": 7797.5,
        "fill_price": 7797.25, "slip": -0.25, "status": "FILLED",
    }) + "\n", encoding="utf-8")
    (root / "live_positions.track1.json").write_text(
        json.dumps({"positions": [_book_row()]}), encoding="utf-8")
    monitor = root / "monitor"
    logs = monitor / "logs"
    logs.mkdir(parents=True)
    (logs / "ops_scheduler.err.log").write_text("\n".join([
        "2026-09-25 14:20:12 ERROR [TRACK1_STOP_REPAIR_1620] B3: 1 mismatch(es) — new entries HALTED",
        "2026-09-25 14:20:13 INFO [TRACK1_STOP_REPAIR_1620] place_stop: accepted LONG MES STP x1 @ 7652 orderId=14 status=PreSubmitted cluster=roska4_swing",
        "2026-09-25 14:20:14 INFO [TRACK1_SLOT] REJECTED LONG MES (roska4_swing) risk_sized=$500 — roska4_swing gross 5% > cap 4%",
        "2026-09-25 14:20:15 INFO [TRACK1_RECOVERY] IBKR connection restored; track1_candidate resumed",
    ]) + "\n", encoding="utf-8")
    (logs / "ops_backend.err.log").write_text("", encoding="utf-8")
    (monitor / "paper_inputs.json").write_text(json.dumps({
        "c1_spec": {"open": {"scope": "by_inst", "min_n_per_inst": 20,
                                "max_mean_ticks": 3},
                    "stp_close": {"scope": "pooled", "min_n": 30,
                                  "max_mean_ticks": 3}, "use_absolute": True},
        "fill_quality_spec": {"min_fills": 100, "max_partial_rate": 0,
                              "max_failed_or_cancelled": 0,
                              "require_complete_fields": True},
        "stp_placement_spec": {"required_continuous_sessions": 10,
                               "max_trade_matched_failed": 0,
                               "require_defer_rule": True, "require_system_log": True,
                               "require_ibkr_accept_log": True},
        "rejection_coverage_spec": {"required_records": 25, "max_unclassified": 0,
                                    "require_candidate_identity": True,
                                    "require_reason": True,
                                    "require_cap_classification": True},
        "stp_verification_spec": {"min_distinct_sessions": 10},
        "tws_restart_spec": {"min_nights": 10},
    }), encoding="utf-8")


def _by_key(result, group):
    return {row["key"]: row for row in result["payload"][group]}


def test_b2_3_and_b2_4_wire_existing_sources_but_keep_missing_sources(monkeypatch, tmp_path):
    _tree(tmp_path)
    monkeypatch.setattr(per.ibkr_reader, "get_cache", lambda: _broker())
    expected_issues = [{"key": "track1:test", "status": "incident"}]
    monkeypatch.setattr(per, "read_open_issues", lambda _root: {"issues": expected_issues})
    per._cache.clear()
    result = per.read_paper_evidence(tmp_path)
    gates = _by_key(result, "gates")
    coverage = _by_key(result, "coverage")

    for key in ("b3_reconcile", "stp_verification"):
        assert gates[key]["status"] != "NOT_WIRED", key
        assert all(source.get("path") for source in gates[key]["sources"]), key
    for key in ("log_hygiene", "rejections", "stp_placement", "tws_restart"):
        assert coverage[key]["status"] != "NOT_WIRED", key
        assert all(source.get("path") for source in coverage[key]["sources"]), key

    assert coverage["open_incidents"]["metrics"]["issues"] == expected_issues
    assert coverage["state_persist"]["metrics"]["position_rows"][0]["inst"] == "MES"
    for key in ("data_freshness", "manual_intervention", "paper_vs_backtest",
                "pnl_thresholds", "roll_slippage", "runner_freshness",
                "tws_restart_nights"):
        row = gates.get(key) or coverage.get(key)
        assert row["status"] == "NOT_WIRED", key
        assert "Not measured for Track 1" in row["evidence"], key


def test_b2_5_absolute_correspondence_math_is_unchanged_and_label_is_specific():
    status, _evidence, _metrics = per._c1_status(
        {"open_mean": -9, "open_n": 1, "stp_close_mean": None, "stp_close_n": 0,
         "by_inst": [{"inst": "MES", "open_n": 1, "open_mean_ticks": -9,
                      "stp_close_n": 0, "stp_close_mean_ticks": None}],
         "signal_close_with_stop_ref": 0, "unknown_tick_records": 0,
         "unknown_tick_value_records": 0},
        {"open": {"scope": "by_inst", "min_n_per_inst": 20, "max_mean_ticks": 3},
         "stp_close": {"scope": "pooled", "min_n": 30, "max_mean_ticks": 3},
         "use_absolute": True},
    )
    assert status == "QUALITY_BREACH"  # API status stays compatible; only its visible label changes.
    source = Path("global_index/dash/paper/paper.js").read_text(encoding="utf-8")
    assert "C1 expected-price correspondence" in source
    assert "CORRESPONDENCE BREACH" in source
    assert "need ${specValue(openMinN)} per instrument" in source


def test_b2_6_zero_and_absent_pnl_have_distinct_renderings():
    source = Path("global_index/dash/paper/paper.js").read_text(encoding="utf-8")
    assert "if (value == null || value === '') return 'not measured';" in source
    assert "if (n === 0) return '$0.00';" in source
