"""monitor/test_track1_paper_evidence_20260924.py — /paper describes the route that trades.

Plan stage 4, the paper-evidence half. On 2026-09-24 `/api/v1/paper-evidence` was built only from
legacy artefacts — live_state_data.js 760 hours old, trade_log.jsonl, live_positions.json,
paper_history.json, the legacy scheduler/live-day logs — and the /paper page presented it as the
paper evidence. The gate: either route may be served, but no legacy number is presented as the
current route's.

The strongest form of that, used here: every legacy artefact in the fixture carries SENTINEL
numbers that appear nowhere else, and the Track 1 answer must contain none of them.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from monitor.backend import app as app_module
from monitor.backend import paper_evidence_reader as per

SENTINELS = (777777.77, 424242.0, 31337.0, 8675.309)


def _legacy_tree(root: Path) -> None:
    gi = root / "global_index"
    gi.mkdir(parents=True, exist_ok=True)
    (gi / "live_state_data.js").write_text("window.LIVE_DATA = " + json.dumps({
        "meta": {"system_epoch": "2026-08-10", "broker_equity": SENTINELS[0]},
        "snapshots": [{"date": "2026-08-24", "equity": SENTINELS[1],
                       "operational_status": {"positions": {"persist_match": True}}}]}) + ";",
        encoding="utf-8")
    (gi / "paper_history.json").write_text(json.dumps({
        "epoch": "2026-08-10",
        "days": {f"2026-08-{d:02d}": {"equity": SENTINELS[1]} for d in range(10, 25)}}),
        encoding="utf-8")
    rows = [{"type": "OPEN", "inst": "MES", "direction": "LONG", "contracts": 1,
             "entry_day": "2026-08-12", "expected_entry": SENTINELS[2], "fill_price": SENTINELS[3],
             "slip": SENTINELS[2], "regime": "Stress", "status": "FILLED"},
            {"type": "CLOSE", "inst": "MES", "direction": "LONG", "contracts": 1,
             "exit_day": "2026-08-13", "exit_reason": "STP", "fill_price": SENTINELS[3],
             "expected_stop": SENTINELS[2], "status": "FILLED"}]
    (root / "trade_log.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                                          encoding="utf-8")
    (root / "slip_stats.json").write_text(json.dumps({"open_sum": SENTINELS[2]}), encoding="utf-8")
    (root / "live_positions.json").write_text(json.dumps({"positions": [
        {"inst": "MNQ", "stop_order_id": "L-1", "entry_price": SENTINELS[0]}]}),
        encoding="utf-8")
    (root / "live_day_0812.log").write_text(
        "2026-08-12 14:05:00  CRITICAL  global_index.runner — B3: 3 mismatch(es) — new entries "
        "HALTED until resolved.\n", encoding="utf-8")


def _track1_tree(root: Path) -> None:
    rt = root / "global_index" / "track1_runtime"
    (rt / "orders").mkdir(parents=True, exist_ok=True)
    (rt / "audits").mkdir(parents=True, exist_ok=True)
    (rt / "orders" / "track1_orders_20260923.jsonl").write_text(json.dumps(
        {"state": "intended", "order_id": ""}) + "\n", encoding="utf-8")
    (rt / "orders" / "track1_orders_20260924.jsonl").write_text(json.dumps(
        {"state": "filled", "order_id": "28", "candidate_id": "normal_r4::MYM::2026-09-24"})
        + "\n", encoding="utf-8")
    for d in ("20260922", "20260923", "20260924"):
        (rt / "audits" / f"track1_audit_{d}.jsonl").write_text("{}\n", encoding="utf-8")
    (rt / "trade_log.track1.jsonl").write_text(json.dumps({
        "type": "OPEN", "route": "track1_candidate", "inst": "MYM", "direction": "LONG",
        "contracts": 1, "filled_qty": 1, "entry_day": "2026-09-24", "expected_entry": 51747.0,
        "fill_price": 51732.0, "slip": -15.0, "status": "FILLED", "cluster": "roska4_swing"})
        + "\n", encoding="utf-8")
    (root / "live_positions.track1.json").write_text(json.dumps({
        "schema_version": 2, "route": "track1_candidate",
        "positions": [{"trade_id": "normal_r4::MYM::2026-09-24", "instrument": "MYM",
                       "direction": "LONG", "qty": 1}]}), encoding="utf-8")


@pytest.fixture
def tree(tmp_path):
    _legacy_tree(tmp_path)
    _track1_tree(tmp_path)
    return tmp_path


def _all_numbers(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _all_numbers(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _all_numbers(x)
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        yield float(v)


def test_the_legacy_fixture_really_carries_the_sentinels(tree):
    """Without this the sentinel test below could pass because the legacy reader read nothing."""
    legacy = per.read_paper_evidence(tree, route="legacy")
    got = set(_all_numbers(legacy))
    assert any(s in got for s in SENTINELS), "the legacy answer holds no sentinel — test is blind"


def test_no_legacy_number_reaches_the_track1_answer(tree):
    t1 = per.read_paper_evidence(tree)
    assert t1["route"] == "track1_candidate"
    leaked = sorted(set(_all_numbers(t1)) & set(SENTINELS))
    assert not leaked, f"legacy sentinel values in the Track 1 evidence: {leaked}"


def test_the_epoch_is_the_first_day_an_order_was_sent(tree):
    t1 = per.read_paper_evidence(tree)
    assert t1["payload"]["epoch"] == "2026-09-24"
    gate = {g["key"]: g for g in t1["payload"]["gates"]}["paper_duration"]
    assert gate["metrics"]["observed"] == 1 and gate["metrics"]["days"] == ["2026-09-24"]


def test_every_row_is_either_track1_sourced_or_not_wired(tree):
    t1 = per.read_paper_evidence(tree)
    rows = [*t1["payload"]["gates"], *t1["payload"]["coverage"]]
    assert len(rows) > 10, "the walk saw almost nothing"
    for row in rows:
        statuses = {s.get("status") for s in row["sources"]}
        if row["status"] == "NOT_WIRED":
            assert "not_wired" in statuses, row["key"]
            assert row["metrics"] == {"not_wired": row["metrics"]["not_wired"]}, row["key"]
        else:
            assert "not_wired" not in statuses, f"{row['key']} computed on an unwired source"
            for s in row["sources"]:
                assert s.get("path") not in ("trade_log.jsonl", "live_positions.json",
                                             "global_index/live_state_data.js",
                                             "global_index/paper_history.json"), row["key"]


def test_a_log_count_is_never_a_zero_for_track1(tree):
    """The legacy log in the fixture holds a real B3 mismatch. For Track 1 the log is not
    scanned, and the summary must say None — a 0 would read as 'no mismatches'."""
    t1 = per.read_paper_evidence(tree)
    for k in ("b3_episodes", "cold_starts", "stp_failed"):
        assert t1["payload"]["summary"][k] is None, k
    gate = {g["key"]: g for g in t1["payload"]["gates"]}["b3_reconcile"]
    assert gate["status"] == "NOT_WIRED"


def test_the_track1_trade_counts_come_from_its_own_log(tree):
    t1 = per.read_paper_evidence(tree)
    assert t1["payload"]["summary"]["c1_open_n"] == 1
    assert t1["payload"]["summary"]["regimes"] == []          # the Stress row was legacy's


def test_the_endpoint_defaults_to_track1_and_serves_legacy_only_by_name(monkeypatch, tree):
    monkeypatch.setattr(app_module, "ROOT", tree)
    client = app_module.app.test_client()
    assert client.get("/api/v1/paper-evidence").get_json()["route"] == "track1_candidate"
    assert client.get("/api/v1/paper-evidence?route=legacy").get_json()["route"] == "legacy"


def test_the_track1_paths_match_the_writers():
    from global_index.track1_report import BOOK, ORDERS_DIR, TRADE_LOG
    assert per.T1_PATHS["trade_log"] == TRADE_LOG
    assert per.T1_PATHS["live_positions"] == BOOK
    assert per.T1_PATHS["orders"] == ORDERS_DIR
