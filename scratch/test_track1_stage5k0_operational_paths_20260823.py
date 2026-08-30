"""scratch/test_track1_stage5k0_operational_paths_20260823.py — the Stage 5K0 gate.

    python -m pytest scratch/test_track1_stage5k0_operational_paths_20260823.py -q

Offline. No scheduler, no IBKR, no order, no dashboard write. Nothing here writes the real
operational runtime root or the real scratch shadow directory — both are asserted clean.

The split this suite holds
--------------------------
    scratch/track1_shadow            REPLAY and TEST artifacts. Reproducible from the measured
                                     windows; losing them costs a re-run.
    global_index/track1_runtime/     LIVE-SHADOW operational evidence. NOT reproducible — nobody
                                     can re-observe a window that has closed — and it is what a
                                     go-live gate is read from. Sweeping scratch must not delete
                                     it.

Stage 5J's runbook told the operator to export the ledger into `scratch/track1_ledger`, which
would have put a multi-day shadow period's only copy inside the directory this project treats as
disposable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import run_live_day_track1 as r1  # noqa: E402
from global_index import track1_explain as tx  # noqa: E402

REAL_SCRATCH = Path("scratch/track1_shadow")
REAL_RUNTIME = Path("global_index/track1_runtime")


# ── the split ────────────────────────────────────────────────────────────────
def test_live_shadow_defaults_to_the_operational_root_not_scratch():
    import inspect

    default = inspect.signature(r1.observe_live_slot).parameters["out_dir"].default
    assert default == r1.OPERATIONAL_SHADOW_DIR
    assert not default.startswith("scratch"), default
    assert default.startswith("global_index/track1_runtime")


def test_replay_still_defaults_to_scratch():
    """Deliberate, not an oversight: a replay is research and is reproducible."""
    import inspect

    default = inspect.signature(r1.run_shadow).parameters["out_dir"].default
    assert default == r1.SHADOW_DIR == "scratch/track1_shadow"


def test_the_two_roots_are_distinct_and_neither_contains_the_other():
    a = Path(r1.SHADOW_DIR).resolve()
    b = Path(r1.OPERATIONAL_SHADOW_DIR).resolve()
    assert a != b
    assert a not in b.parents and b not in a.parents


def test_the_recommended_env_paths_are_operational_and_named_in_code():
    """So the runbook and the code cannot drift into naming different directories."""
    assert r1.RECOMMENDED_LEDGER_DIR == "global_index/track1_runtime/window_coverage"
    assert r1.RECOMMENDED_TELEMETRY_DIR == "global_index/track1_runtime/slot_timing"
    for p in (r1.RECOMMENDED_LEDGER_DIR, r1.RECOMMENDED_TELEMETRY_DIR):
        assert not p.startswith("scratch"), p


# ── the guard still has teeth ────────────────────────────────────────────────
def test_both_approved_roots_are_permitted():
    assert tx.APPROVED_ROOTS == (tx.SHADOW_ROOT, tx.OPERATIONAL_ROOT)
    for root in tx.APPROVED_ROOTS:
        assert tx.resolve_shadow_dir(root)
        assert tx.resolve_shadow_dir(f"{root}/explanations/live_2026-08-24")


@pytest.mark.parametrize("bad", [
    "global_index",                      # the package itself
    "scratch",                           # the sweep root itself
    "global_index/track1_runtime",       # the runtime root, but not the shadow subtree
    "monitor/backend",
    ".",
    "trade_log.jsonl",
])
def test_everything_outside_the_two_roots_is_still_refused(bad):
    """Widening the bound to a SET must not have widened it to anything else. The writer that
    could be aimed at a legacy path once manufactured a paper-evidence episode."""
    with pytest.raises(tx.ShadowPathRefused):
        tx.resolve_shadow_dir(bad)


def test_the_refusal_names_both_roots():
    try:
        tx.resolve_shadow_dir("monitor")
    except tx.ShadowPathRefused as exc:
        assert tx.SHADOW_ROOT in str(exc) and tx.OPERATIONAL_ROOT in str(exc)
    else:
        raise AssertionError("monitor/ was not refused")


# ── .gitignore ───────────────────────────────────────────────────────────────
def _ignored(path: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", path],
                          cwd=str(Path.cwd()), capture_output=True).returncode == 0


@pytest.mark.parametrize("path", [
    "live_positions.track1.json",
    "runner.track1.pid",
    "global_index/replay_checkpoint.track1.json",
    "STOP_TRADING.track1",
    "track1_go_live_confirmation.json",
    "global_index/track1_runtime/shadow/explanations/x.jsonl",
    "global_index/track1_runtime/window_coverage/window_coverage_20260824.jsonl",
    "global_index/track1_runtime/slot_timing/slot_timing_20260824.jsonl",
])
def test_track1_runtime_output_is_ignored(path):
    assert _ignored(path), f"{path} would be offered for commit"


@pytest.mark.parametrize("path", [
    "global_index/run_live_day_track1.py",
    "global_index/track1_explain.py",
    "global_index/track1_live_source.py",
    "docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md",
    "scratch/test_track1_stage5k0_operational_paths_20260823.py",
])
def test_source_docs_and_tests_are_not_ignored(path):
    """The other direction. An over-broad rule that swallowed a module would be worse than the
    gap it closed."""
    assert not _ignored(path), f"{path} is ignored and should not be"


def test_the_confirmation_file_can_never_arrive_by_checkout():
    """It is the file that ARMS the route. Ignoring it means a checkout cannot create one."""
    assert _ignored("track1_go_live_confirmation.json")
    assert not Path("track1_go_live_confirmation.json").exists()


# ── nothing real was written ─────────────────────────────────────────────────
def test_this_suite_wrote_neither_real_root():
    assert not REAL_RUNTIME.exists(), f"{REAL_RUNTIME} was created by a test"
    for p in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
              "live_positions.track1.json", "runner.track1.pid"):
        assert not Path(p).exists(), p
    assert not (REAL_SCRATCH / "explanations").exists()
