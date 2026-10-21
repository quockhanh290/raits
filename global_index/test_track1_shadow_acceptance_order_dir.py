from __future__ import annotations

from types import SimpleNamespace


def _install_minimal_day(monkeypatch, *, order_mark: bool = False):
    from global_index import track1_shadow_acceptance as acc
    from global_index import track1_params as tp
    from global_index import track1_slots as ts
    import global_index.window_ledger as wl
    from global_index import track1_gates as gates

    slots = [
        SimpleNamespace(id="TRACK1_NKD_0110"),
        SimpleNamespace(id="TRACK1_NKD_0115"),
    ]
    rows = [
        {"event": "slot_observed", "slot_id": "TRACK1_NKD_0110", "orders_possible": False},
        {"event": "slot_observed", "slot_id": "TRACK1_NKD_0115", "orders_possible": False},
    ]
    if order_mark:
        rows[0]["order_id"] = "123"

    monkeypatch.setattr(tp, "WINDOWS_ET", {"global_nkd": ("01:10", "01:15")})
    monkeypatch.setattr(ts, "TRACK1_SLOTS", slots)
    monkeypatch.setattr(acc, "_ledger_rows", lambda _root, _day: list(rows))
    monkeypatch.setattr(acc, "_timing_rows", lambda _root, _day: [
        {"slot_id": slot.id, "runtime_s": 1.0} for slot in slots
    ])
    monkeypatch.setattr(acc, "_explanation_rows", lambda _root, _day: [
        {"proofs": [{"name": "freshness_checked"}]},
    ])
    monkeypatch.setattr(wl, "status", lambda _rows, _sleeve, _day: {
        "outcome": "complete",
        "observed_slots": 2,
        "expected_slots": 2,
    })
    monkeypatch.setattr(gates, "as_ledger", lambda: {
        "blocking_now": ["B1_broker_account_or_legacy_retirement"],
    })
    monkeypatch.setattr(gates, "may_enable_orders", lambda: (
        False, ["B1_broker_account_or_legacy_retirement"],
    ))
    monkeypatch.setattr(acc, "checkpoint_check", lambda _root, _day: {
        "name": "checkpoint",
        "status": acc.OK,
        "detail": "checkpoint ok",
    })
    monkeypatch.setattr(acc, "safety_paths_check", lambda _root: {
        "name": "safety_paths",
        "status": acc.OK,
        "detail": "safety ok",
    }, raising=False)


def _check(result: dict, name: str) -> dict:
    return next(item for item in result["checks"] if item["name"] == name)


def test_existing_order_journal_directory_is_context_not_shadow_order_evidence(
        tmp_path, monkeypatch):
    from global_index import track1_shadow_acceptance as acc

    _install_minimal_day(monkeypatch)
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    (tmp_path / "global_index" / "track1_runtime" / "orders").mkdir(parents=True)

    result = acc.evaluate_day("2026-09-29", root=tmp_path)
    no_orders = _check(result, "no_orders")

    assert no_orders["status"] == acc.OK
    assert "order journal directory present" in no_orders["detail"]


def test_per_row_order_mark_still_fails_even_when_directory_rule_is_relaxed(
        tmp_path, monkeypatch):
    from global_index import track1_shadow_acceptance as acc

    _install_minimal_day(monkeypatch, order_mark=True)
    monkeypatch.delenv("TRACK1_ORDERS_APPROVED", raising=False)
    (tmp_path / "global_index" / "track1_runtime" / "orders").mkdir(parents=True)

    result = acc.evaluate_day("2026-09-29", root=tmp_path)
    no_orders = _check(result, "no_orders")

    assert no_orders["status"] == acc.FAIL
    assert "record(s) carry an order mark" in no_orders["detail"]


def test_orders_approved_environment_still_fails_shadow_audit(tmp_path, monkeypatch):
    from global_index import track1_shadow_acceptance as acc

    _install_minimal_day(monkeypatch)
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")

    result = acc.evaluate_day("2026-09-29", root=tmp_path)
    no_orders = _check(result, "no_orders")

    assert no_orders["status"] == acc.FAIL
    assert "TRACK1_ORDERS_APPROVED is set" in no_orders["detail"]
