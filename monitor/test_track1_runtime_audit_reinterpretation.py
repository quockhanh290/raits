from __future__ import annotations

import json


def _write_audit(tmp_path, *, details: list[str], reasons: list[str] | None = None):
    d = tmp_path / "global_index" / "track1_runtime" / "audits"
    d.mkdir(parents=True)
    row = {
        "route": "track1_candidate",
        "date": "2026-09-29",
        "session_day": "2026-09-29",
        "scope": "sleeve",
        "sleeve": "global_nkd",
        "verdict": "FAIL",
        "reasons": reasons if reasons is not None else ["order_mark_present"],
        "details": details,
        "ts": "2026-09-29T07:05:01+00:00",
        "expected_slots": 22,
        "observed_slots": 22,
        "missing_slot_ids": [],
    }
    (d / "track1_audit_20260929.jsonl").write_text(
        json.dumps(row) + "\n",
        encoding="utf-8",
    )


def test_runtime_reader_reinterprets_stored_order_directory_fail(tmp_path, monkeypatch):
    from global_index import track1_audit_reinterpretation as reinterpret
    from monitor.backend.track1_runtime_reader import _audits

    _write_audit(
        tmp_path,
        details=["order gate: an order journal directory exists during a shadow period"],
    )
    monkeypatch.setattr(reinterpret.acc, "evaluate_sleeve", lambda *_args, **_kwargs: {
        "verdict": "PASS",
        "reasons": [],
    })

    row = _audits(tmp_path)["latest"]["sleeves"]["global_nkd"]

    assert row["verdict"] == "PASS"
    assert row["stored_verdict"] == "FAIL"
    assert row["stored_reasons"] == ["order_mark_present"]
    assert row["reinterpretation"]["status"] == "stored_fail_reinterpreted"


def test_runtime_reader_does_not_reinterpret_real_order_mark_fail(tmp_path, monkeypatch):
    from global_index import track1_audit_reinterpretation as reinterpret
    from monitor.backend.track1_runtime_reader import _audits

    _write_audit(tmp_path, details=["order gate: 1 record(s) carry an order mark"])
    monkeypatch.setattr(reinterpret.acc, "evaluate_sleeve", lambda *_args, **_kwargs: {
        "verdict": "PASS",
        "reasons": [],
    })

    row = _audits(tmp_path)["latest"]["sleeves"]["global_nkd"]

    assert row["verdict"] == "FAIL"
    assert "stored_verdict" not in row
    assert "reinterpretation" not in row
