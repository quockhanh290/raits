"""scratch/test_track1_stage5c_shadow_readiness_20260823.py — the Stage 5C gate.

    python -m pytest scratch/test_track1_stage5c_shadow_readiness_20260823.py -q

Offline. No scheduler started, no IBKR, no order, no dashboard write. Nothing here creates
STOP_TRADING or the confirmation file; the one test that needs STOP_TRADING to exist creates it
inside pytest's temporary directory and points the probe at that directory instead.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

probe_mod = importlib.import_module("scratch.track1_stage5c_shadow_readiness_probe_20260823")
SCRIPT = Path("scratch/track1_stage5c_shadow_readiness_probe_20260823.py")


@pytest.fixture(scope="module")
def d():
    return probe_mod.probe()


# ── the probe reports the world as it is ─────────────────────────────────────
def test_the_probe_agrees_with_the_filesystem(d):
    """Every boolean is checked against the thing it claims to describe, so the probe cannot
    drift into reporting a state it merely remembers."""
    assert d["stop_trading_present"] is Path("STOP_TRADING").exists()
    assert d["confirmation_present"] is Path("track1_go_live_confirmation.json").exists()
    assert d["pid_file_present"] is Path("runner.pid").exists()
    assert d["checkpoint"]["present"] is Path(d["checkpoint"]["path"]).exists()
    assert d["orders_env_present"] is (os.environ.get("TRACK1_ORDERS_APPROVED") is not None)


def test_the_process_probe_can_say_it_does_not_know():
    """Two outcomes would be a fail-open. `scheduler_processes` returning 0 when its query
    breaks is exactly how this repo once started a second scheduler against client id 1."""
    n, how = probe_mod.scheduler_processes()
    assert n is None or isinstance(n, int)
    assert isinstance(how, str) and how

    import global_index  # noqa: F401  (import path sanity before monkeypatching subprocess)
    real = subprocess.run

    class Broken:
        returncode = 1
        stdout = ""
        stderr = "the query fell over"

    try:
        probe_mod.subprocess.run = lambda *a, **k: Broken()
        n2, how2 = probe_mod.scheduler_processes()
    finally:
        probe_mod.subprocess.run = real
    assert n2 is None, "a broken probe reported a number instead of 'unknown'"
    assert "exited 1" in how2


def test_unknown_scheduler_state_is_not_safe_to_start(monkeypatch):
    monkeypatch.setattr(probe_mod, "scheduler_processes", lambda: (None, "synthetic unknown"))
    d2 = probe_mod.probe()
    assert d2["scheduler_running"] is None
    assert d2["safe_to_start_shadow"] is False
    assert any("cannot tell" in r for r in d2["blocking_reasons"])


def test_a_running_scheduler_is_not_safe_to_start(monkeypatch):
    monkeypatch.setattr(probe_mod, "scheduler_processes", lambda: (1, "synthetic running"))
    d2 = probe_mod.probe()
    assert d2["scheduler_running"] is True
    assert d2["safe_to_start_shadow"] is False
    assert any("already running" in r for r in d2["blocking_reasons"])


def test_the_verdict_turns_green_once_the_kill_switch_is_there(tmp_path, monkeypatch):
    """The probe must be able to say yes, or it is a constant wearing a function's clothes.

    STOP_TRADING is created in tmp_path and the probe's existence check is pointed there. The
    repo root is never written to — asserted afterwards.
    """
    (tmp_path / "STOP_TRADING").write_text("", encoding="utf-8")
    real_exists = probe_mod._exists
    monkeypatch.setattr(probe_mod, "_exists",
                        lambda p: (tmp_path / p).exists() if p == "STOP_TRADING"
                        else real_exists(p))
    d2 = probe_mod.probe()
    assert d2["stop_trading_present"] is True
    assert d2["safe_to_start_shadow"] is True, d2["blocking_reasons"]
    assert not Path("STOP_TRADING").exists(), "the test created the real kill switch"


# ── the state the operator is about to act on ────────────────────────────────
def test_shadow_mode_keeps_every_legacy_entry_slot(d):
    """The fact the whole ordering rests on, re-measured rather than quoted from a report."""
    s = d["scheduler_shapes"]
    assert s["legacy_entry_slots_off"] == s["legacy_entry_slots_under_shadow"] == 23
    assert s["shadow_removes_legacy_entries"] is False
    assert s["added_by_shadow"] == 25
    assert s["removed_by_shadow"] == ["stop_repair_1220"]


def test_the_track1_slots_are_the_two_windows(d):
    s = d["scheduler_shapes"]
    assert s["track1_calm_slots"] == 1
    assert s["track1_stress_slots"] == 24          # 10:35..12:30 inclusive, every 5 minutes
    assert s["track1_first"] == "track1_calm_1000"
    assert s["track1_last"] == "track1_stress_1230"


def _without_comments(body: str) -> str:
    """The argv, without the prose about the argv.

    Repaired 2026-08-26 (Stage 5ZQ regression sweep). This test had been RED, reporting
    "a Track 1 slot asks for orders" — and it was matching a COMMENT inside the slot builder
    that says *"Still no `--allow-orders`, no `--port`, no `--window`"*. The comment asserting
    the absence was read as the presence.

    That failure message is the reason this is repaired here rather than left for a later
    sweep: a red test claiming a shadow slot can request orders is the one alarm nobody should
    have to re-derive, and it was false. Measured after the strip: neither flag appears in any
    argv the slot builds.
    """
    out = []
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line.split("  #")[0] if "  #" in line else line)
    return "\n".join(out)


def test_no_track1_slot_can_ask_for_orders():
    """Read from the shipped source rather than from a job object, because what matters is the
    argv the slot builds — the thing that would reach a broker."""
    src = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    body = src[src.index("def _track1_body("):]
    body = body[:body.index("for _s in _t1.TRACK1_SLOTS")]
    assert "run_live_day_track1" in body
    code = _without_comments(body)
    assert "run_live_day_track1" in code, "the strip removed the argv itself"
    assert "--allow-orders" not in code, "a Track 1 slot asks for orders"
    assert "--port" not in code, "a Track 1 slot carries a broker port"


def test_orders_are_impossible_in_this_state(d):
    from global_index import run_live_day_track1 as entry
    assert d["orders_possible"] is False
    # Stage 5S added PAPER_SHADOW_EVIDENCE: a MEASURED gate asking whether the shadow
    # route has produced enough judgeable days to justify an order. It cannot be signed,
    # only earned, so it holds until the evidence exists.
    assert d["track1_blockers"] == ["B1_broker_account_or_legacy_retirement",
                                   "PAPER_SHADOW_EVIDENCE"]
    assert d["gate_self_check"] == []
    gate = entry.OrderGate(True)
    assert gate.allow_orders is False
    assert set(gate.blockers) == {"B1_broker_account_or_legacy_retirement", "PAPER_SHADOW_EVIDENCE"}


def test_the_shadow_collection_targets_are_not_met_yet(d):
    """Precondition 5 and 6, as the probe sees them. Both are expected false before the first
    shadow run; this pins that they are measured rather than assumed."""
    assert d["window_coverage_present"] is False
    assert d["checkpoint"]["accepted"] is False
    assert d["checkpoint"]["code"] == "file_absent"


def test_the_probe_writes_nothing(tmp_path):
    """Run it as a subprocess and require the tree to be unchanged afterwards."""
    watched = ["STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
               "live_positions.json", "live_positions.track1.json", "runner.pid",
               "global_index/live_state_data.js", "global_index/replay_checkpoint.json"]
    before = {p: (Path(p).exists(), Path(p).stat().st_mtime if Path(p).exists() else None)
              for p in watched}
    out = subprocess.run([sys.executable, str(SCRIPT), "--json"],
                         capture_output=True, text=True, cwd=str(Path.cwd()), timeout=600)
    assert out.returncode == 0, out.stderr[-400:]
    payload = json.loads(out.stdout)
    assert payload["scheduler_shapes"]["legacy_entry_slots_under_shadow"] == 23
    after = {p: (Path(p).exists(), Path(p).stat().st_mtime if Path(p).exists() else None)
             for p in watched}
    assert before == after, "the probe changed something on disk"
