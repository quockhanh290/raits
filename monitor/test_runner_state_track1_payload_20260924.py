"""monitor/test_runner_state_track1_payload_20260924.py — `payload` is Track 1's, key by key.

Plan stage 2. After stage 0 labelled the legacy file stale, this replaces it as the payload. The
gate the plan set: every field EITHER has a Track 1 source OR is absent — none keeps a legacy
value — and a test lists every payload key and demands that each declare its source.

The fixture's legacy file carries values that cannot be confused with any Track 1 value
(broker equity 996,730.93, account 50,000 vs Track 1's own 50,000 is the one overlap and is
checked by source, not by value), so a legacy value that leaks through is caught by its number.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from monitor.backend import app as app_module
from monitor.backend import track1_meta_reader as tm

LEGACY = {
    "runner_health": {"last_heartbeat": "2026-08-24", "ibkr_connected": True},
    "meta": {"account": 50000.0, "broker_equity": 996730.93, "net_pnl": 408.25,
             "final_equity": 50408.25, "max_dd_pct": 0.0, "total_days": 11,
             "hard_dd_pct": 0.15, "backtest_calmar": 1.65, "system_epoch": "2026-08-10",
             "paper_start": {"date": "2026-07-08", "equity": 1000480.0},
             "clusters": {"global_nkd": {"max_gross_pct": 0.06}},
             "operational_status": {"breaker": {"level": "OK"}}},
    "snapshots": [{"date": "2026-08-24", "equity": 50408.25}],
}
LEGACY_NUMBERS = {996730.93, 408.25, 50408.25, 1000480.0, 1.65}


def _tree(tmp_path: Path) -> Path:
    """A temp root with the Track 1 artefacts the reader uses, in their real shapes."""
    live = tmp_path / "live_state_data.js"
    live.write_text("window.LIVE_DATA = " + json.dumps(LEGACY) + ";\n", encoding="utf-8")
    old = time.time() - 30 * 86400
    os.utime(live, (old, old))
    audits = tmp_path / "global_index" / "track1_runtime" / "audits"
    audits.mkdir(parents=True)
    for d in ("20260923", "20260924"):
        (audits / f"track1_audit_{d}.jsonl").write_text("{}\n", encoding="utf-8")
    base = tmp_path / "global_index" / "track1_runtime" / "account_baseline"
    base.mkdir(parents=True)
    (base / "account_baseline_20260827.jsonl").write_text(json.dumps({
        "status": "PASS", "checked_at": "2026-08-27T11:29:47+00:00",
        "inputs": {"account": {"equity": 250817.91, "currency": "USD"}}}) + "\n",
        encoding="utf-8")
    logs = tmp_path / "monitor" / "logs"
    logs.mkdir(parents=True)
    (logs / "ops_scheduler.err.log").write_text(
        "2026-09-24 18:29:00  INFO     apscheduler.executors.default — Job \"Heartbeat 60s "
        "(trigger: cron[minute='*'], next run at: 2026-09-24 20:30:00 EDT)\" executed "
        "successfully\n", encoding="utf-8")
    return live


@pytest.fixture
def body(monkeypatch, tmp_path):
    live = _tree(tmp_path)
    monkeypatch.setattr(app_module, "LIVE_STATE_PATH", live)
    monkeypatch.setattr(app_module, "ROOT", tmp_path)
    monkeypatch.setattr(app_module, "resolve_track1_only", lambda: True)
    monkeypatch.setattr(app_module, "get_schedule_status",
                        lambda *a, **k: {"freshness": "not_expected_yet",
                                         "expected_next_at": "2026-09-25T05:10:00Z"})
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(app_module.ibkr_reader, "get_cache",
                        lambda: {"connected": True, "last_update": now})
    b1 = SimpleNamespace(status="PASS", checked_at="2026-09-24T22:56:02+00:00",
                         inputs={"broker": {"equity": 251341.45}})
    import global_index.track1_b1 as b1m
    monkeypatch.setattr(b1m, "latest", lambda root, *a, **k: b1)
    return app_module.app.test_client().get("/api/v1/runner-state").get_json()


def _leaf_keys(payload: dict) -> list:
    """Dotted keys at the level `payload_sources` declares: `meta.x`, `runner_health.y`, and
    top-level non-dict keys such as `snapshots`."""
    out = []
    for top, v in payload.items():
        if isinstance(v, dict):
            out.extend(f"{top}.{k}" for k in v)
        else:
            out.append(top)
    return out


def test_every_payload_key_declares_its_source(body):
    keys = _leaf_keys(body["payload"])
    assert len(keys) >= 6, f"the walk saw almost nothing: {keys}"
    undeclared = [k for k in keys if k not in body["payload_sources"]]
    assert not undeclared, f"payload keys with no declared source: {undeclared}"
    for k in keys:
        s = body["payload_sources"][k]
        assert "source" in s, k
        if k != "snapshots":
            assert s["source"], f"{k} is present with a null source"


def test_no_source_is_a_legacy_path(body):
    legacy_paths = ("live_state_data", "live_positions.json", "trade_log.jsonl",
                    "FuturesRunner", "runner.py")
    for k, s in body["payload_sources"].items():
        text = json.dumps(s)
        for bad in legacy_paths:
            assert bad not in text, f"{k} is sourced from legacy path {bad}: {text}"


def test_no_legacy_value_survives_in_the_payload(body):
    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                yield from walk(x)
        elif isinstance(v, list):
            for x in v:
                yield from walk(x)
        else:
            yield v
    leaked = [v for v in walk(body["payload"]) if isinstance(v, float) and v in LEGACY_NUMBERS]
    assert not leaked, f"legacy values in the Track 1 payload: {leaked}"
    # and the legacy file is still there, under its own name, stamped
    assert body["legacy_payload"]["meta"]["broker_equity"] == 996730.93
    assert body["legacy_payload"]["_provenance"]["stale"] is True


def test_a_field_is_either_present_with_a_source_or_declared_absent(body):
    present = set(_leaf_keys(body["payload"]))
    absent = set(body["payload_absent"])
    assert not (present & absent), f"both present and declared absent: {present & absent}"
    # Every legacy meta key the page used to read is accounted for one way or the other.
    for k in LEGACY["meta"]:
        dotted = f"meta.{k}"
        assert dotted in present or dotted in absent, f"{dotted} silently vanished"
    for k in ("meta.hard_dd_pct", "meta.backtest_calmar", "meta.net_pnl"):
        assert k in absent and body["payload_absent"][k], f"{k} absent without a reason"


def test_the_eight_fields_carry_track1_values(body):
    meta, health = body["payload"]["meta"], body["payload"]["runner_health"]
    assert meta["broker_equity"] == 251341.45
    assert body["payload_sources"]["meta.broker_equity"]["as_of"] == "2026-09-24T22:56:02+00:00"
    assert meta["paper_start"]["equity"] == 250817.91
    assert meta["paper_start"]["currency"] == "USD"
    assert meta["total_days"] == 2
    assert set(meta["clusters"]) == {"roska4_swing", "roska4_calm", "roska4_stress",
                                     "global_nkd"}
    assert meta["account"] == 50000.0
    assert body["payload_sources"]["meta.account"]["source"].startswith(
        "global_index/track1_params.py")
    assert health["ibkr_connected"] == "connected"
    assert health["last_heartbeat"].startswith("2026-09-2")
    assert body["payload"]["snapshots"] == []


def test_ibkr_connection_is_three_states():
    now = dt.datetime(2026, 9, 24, 23, 0, tzinfo=dt.timezone.utc)
    fresh = "2026-09-24T22:59:30Z"
    assert tm.ibkr_connection({"connected": True, "last_update": fresh}, now)["state"] == "connected"
    assert tm.ibkr_connection({"connected": False, "last_update": fresh}, now)["state"] == "disconnected"
    assert tm.ibkr_connection({"connected": True, "last_update": "2026-09-24T20:00:00Z"},
                              now)["state"] == "unknown"
    assert tm.ibkr_connection({"connected": True, "last_update": None}, now)["state"] == "unknown"


def test_a_missing_heartbeat_is_declared_absent_not_invented(tmp_path):
    out = tm.build(tmp_path, ibkr_cache={}, b1_latest=lambda r: SimpleNamespace(inputs={}))
    assert "last_heartbeat" not in out["payload"]["runner_health"]
    assert "runner_health.last_heartbeat" in out["payload_absent"]
    assert "meta.broker_equity" in out["payload_absent"]
    assert "meta.paper_start" in out["payload_absent"]
