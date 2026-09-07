"""Verification for the additive slot telemetry. SCRATCH-ONLY.

Connects to nothing, starts nothing, writes only into a tmp_path.

The claim under test is not "it records things" — it is "it records things AND is
provably inert when switched off". Both halves are asserted, and each assertion is
written so it can actually go red.

    python -m pytest scratch/test_slot_telemetry_20260822.py -q
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import global_index.slot_telemetry as tel


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    """Reload the module per test so the disabled-latch and _state do not leak."""
    for k in ("RAITS_TELEMETRY_DIR", "RAITS_SLOT_ID", "RAITS_ROUTE"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(tel)
    yield
    importlib.reload(tel)


def _lines(d: Path):
    files = list(d.glob("slot_timing_*.jsonl"))
    return [json.loads(x) for f in files for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── the half that matters most: OFF means OFF ───────────────────────────────
def test_disabled_writes_nothing_at_all(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tel.begin()
    tel.split("a")
    tel.mark("k", 1)
    with tel.timer("b"):
        pass
    tel.emit("ok")
    tel.record_skip("LIVE_DAY_1410", "skipped_mutex")
    assert not tel.enabled()
    # nothing anywhere under the cwd, not just no slot_timing file
    assert list(tmp_path.rglob("*")) == [], f"telemetry wrote files while disabled: {list(tmp_path.rglob('*'))}"


def test_enabled_writes_one_line_per_call(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    monkeypatch.setenv("RAITS_SLOT_ID", "LIVE_DAY_1410")
    importlib.reload(tel)
    assert tel.enabled()
    tel.begin()
    tel.split("data_load")
    tel.emit("ok")
    recs = _lines(tmp_path)
    assert len(recs) == 1, f"expected exactly one record, got {len(recs)}"
    r = recs[0]
    assert r["slot_id"] == "LIVE_DAY_1410"
    assert r["route"] == "legacy", "route must default to legacy"
    assert r["outcome"] == "ok"
    assert "data_load" in r["phases"]
    assert isinstance(r["runtime_s"], (int, float)) and r["runtime_s"] >= 0


def test_route_default_is_legacy_and_overridable(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    assert tel.route() == "legacy"
    monkeypatch.setenv("RAITS_ROUTE", "track1_candidate")
    assert tel.route() == "track1_candidate"


def test_phases_accumulate_and_are_ordered_by_split(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.begin()
    tel.split("one")
    tel.split("two")
    tel.add("two", 1.5)
    tel.emit("ok")
    r = _lines(tmp_path)[0]
    assert set(r["phases"]) == {"one", "two"}
    assert r["phases"]["two"] >= 1.5, "add() must accumulate onto an existing phase"


def test_skip_record_is_distinguishable_from_a_real_run(tmp_path, monkeypatch):
    """The gap the timing audit had to paper over with a ~0s threshold."""
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.record_skip("LIVE_DAY_1420", "skipped_mutex", inflight_s=311.0)
    tel.record_skip("LIVE_DAY_1430", "skipped_preflight", reason="preflight_missing")
    recs = _lines(tmp_path)
    assert [r["outcome"] for r in recs] == ["skipped_mutex", "skipped_preflight"]
    assert recs[0]["inflight_s"] == 311.0
    assert recs[1]["reason"] == "preflight_missing"
    assert all(r["runtime_s"] == 0.0 for r in recs)


def test_never_raises_when_the_directory_is_unwritable(tmp_path, monkeypatch):
    """A telemetry failure must not escape into a trading path."""
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path / "does-not-exist"))
    importlib.reload(tel)
    tel.begin()
    tel.emit("ok")            # must not raise
    tel.record_skip("X", "skipped_mutex")
    assert not tel.enabled()


def test_write_failure_disables_the_channel_without_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", boom)
    tel.begin()
    tel.emit("ok")            # must swallow
    monkeypatch.undo()
    assert tel._disabled is True
    tel.emit("ok")
    assert _lines(tmp_path) == [], "channel must stay disabled after a write failure"


# ── mutation checks: prove the assertions above can go red ──────────────────
def test_mutation_disabled_check_can_fail(tmp_path, monkeypatch):
    """If the OFF guard were removed, test_disabled_writes_nothing_at_all would fail.
    Simulate that by forcing the directory on, and confirm a file does appear."""
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.begin()
    tel.emit("ok")
    assert list(tmp_path.rglob("slot_timing_*.jsonl")), (
        "the disabled-test would be vacuous if enabling still wrote nothing")


# ── outcome semantics: the three the first revision got wrong ───────────────
def test_sticky_mode_is_not_relabelled_by_a_later_success(tmp_path, monkeypatch):
    """A dry run still executes run_day, so the success path used to relabel it "ok"
    and hide that no order could ever have been sent."""
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.begin()
    tel.set_outcome("dry_run", sticky=True)
    tel.set_outcome("ok")                      # the success path, later
    tel.emit(tel._state["outcome"])
    assert _lines(tmp_path)[0]["outcome"] == "dry_run"


def test_error_overrides_even_a_sticky_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.begin()
    tel.set_outcome("lock_held", sticky=True)
    tel.set_outcome("error", force=True)
    tel.emit(tel._state["outcome"])
    assert _lines(tmp_path)[0]["outcome"] == "error"


def test_plain_outcome_still_overwrites_a_plain_one(tmp_path, monkeypatch):
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.begin()
    tel.set_outcome("incomplete")
    tel.set_outcome("ok")
    tel.emit(tel._state["outcome"])
    assert _lines(tmp_path)[0]["outcome"] == "ok"


def test_atexit_net_writes_whatever_stands(tmp_path, monkeypatch):
    """The paths that matter most for diagnosing a slow day are the ones that returned
    early. They must still leave a record."""
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.begin()
    tel.set_outcome("lock_held", sticky=True)
    tel._atexit_emit()
    assert _lines(tmp_path)[0]["outcome"] == "lock_held"
    tel._atexit_emit()                          # must not double-write
    assert len(_lines(tmp_path)) == 1


# ── the call sites in run_live_day actually set what the docs claim ─────────
@pytest.mark.parametrize("outcome,sticky", [
    ("dry_run", True), ("print_signals", True), ("lock_held", True),
    ("error", True), ("ok", False),
])
def test_every_documented_outcome_has_a_call_site(outcome, sticky):
    """Documented-but-never-emitted was the exact defect in the first revision:
    `lock_held` and `error` appeared in the docstring and nowhere in the code."""
    src = Path("global_index/run_live_day.py").read_text(encoding="utf-8")
    assert f'set_outcome("{outcome}"' in src, f"{outcome} is documented but never set"


def test_module_docstring_outcomes_all_reachable():
    doc = tel.__doc__ or ""
    live = Path("global_index/run_live_day.py").read_text(encoding="utf-8")
    sched = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    for name in ("ok", "error", "dry_run", "print_signals", "lock_held",
                 "skipped_mutex", "skipped_preflight"):
        assert name in doc, f"{name} missing from the module docstring"
        assert (f'"{name}"' in live) or (f'"{name}"' in sched), (
            f"{name} is documented but no production call site emits it")


# ── scheduler wiring: off by default must mean off in the CHILD too ────────
def _child_env(monkeypatch, tmp_path, parent_env: dict):
    """Drive the real _run() with a captured subprocess.run, so the assertion is about
    production code rather than a re-implementation of it."""
    import global_index.run_scheduler as rs
    seen = {}

    class _Res:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kw):
        seen["args"] = list(args)
        seen["env"] = dict(kw.get("env") or {})
        return _Res()

    for k in ("RAITS_TELEMETRY_DIR", "RAITS_SLOT_ID", "RAITS_ROUTE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in parent_env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(rs.subprocess, "run", fake_run)
    rs._run(["python", "-m", "global_index.run_live_day", "--port", "4002"],
            label="LIVE_DAY_1410", dry_run=False)
    return seen


def test_scheduler_does_not_invent_a_telemetry_dir(tmp_path, monkeypatch):
    """The first revision did `_env.setdefault("RAITS_TELEMETRY_DIR", str(_CWD))`,
    which switched child telemetry on for every spawn while the module still claimed to
    be off by default — and left the parent off."""
    seen = _child_env(monkeypatch, tmp_path, {})
    assert "RAITS_TELEMETRY_DIR" not in seen["env"], (
        "scheduler must not enable child telemetry when its own env has none")


def test_scheduler_forwards_telemetry_dir_when_the_parent_has_one(tmp_path, monkeypatch):
    seen = _child_env(monkeypatch, tmp_path, {"RAITS_TELEMETRY_DIR": str(tmp_path)})
    assert seen["env"]["RAITS_TELEMETRY_DIR"] == str(tmp_path)


def test_scheduler_always_passes_identity_but_identity_enables_nothing(tmp_path, monkeypatch):
    seen = _child_env(monkeypatch, tmp_path, {})
    assert seen["env"]["RAITS_SLOT_ID"] == "LIVE_DAY_1410"
    assert seen["env"]["RAITS_ROUTE"] == "legacy"
    assert "RAITS_TELEMETRY_DIR" not in seen["env"], "identity alone must not enable writes"


def test_scheduler_never_touches_argv(tmp_path, monkeypatch):
    """argv is logged one line before the spawn and must stay byte-identical."""
    argv = ["python", "-m", "global_index.run_live_day", "--port", "4002"]
    seen = _child_env(monkeypatch, tmp_path, {"RAITS_TELEMETRY_DIR": str(tmp_path)})
    assert seen["args"] == argv


def test_parent_skip_records_follow_the_parent_env(tmp_path, monkeypatch):
    """Parent and child are on or off together, which is the point of removing the
    invented default."""
    monkeypatch.delenv("RAITS_TELEMETRY_DIR", raising=False)
    importlib.reload(tel)
    tel.record_skip("LIVE_DAY_1420", "skipped_mutex")
    assert not list(tmp_path.rglob("*"))
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tmp_path))
    importlib.reload(tel)
    tel.record_skip("LIVE_DAY_1420", "skipped_mutex")
    assert [r["outcome"] for r in _lines(tmp_path)] == ["skipped_mutex"]
