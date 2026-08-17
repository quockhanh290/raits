"""
global_index/test_slot_overlap.py — overlapping cron slots must not double-run

Measured 2026-08-03: a run_live_day slot takes ~5.5 min (connect 12:35:16 →
disconnect 12:40:44) while slots fire every 5 min. Both children connected on
clientId=1 and collided at IBKR — the P0C_1440/1450 failures.

Two independent guards, tested here:

  scheduler level  — _slot_lock serialises _live_day_body across ALL slots.
                     APScheduler's max_instances cannot do this: it is applied per
                     job id and every slot is its own job.
  process level    — run_live_day takes the E1 PID lock BEFORE connecting to IBKR,
                     so a run started any other way still exits before touching the
                     Gateway. _acquire_lock also had to stop treating the caller's
                     own PID as a collision, since FuturesRunner takes it again.

Skipping is the correct outcome: diff_desired_vs_held is idempotent (a held
position yields cur != None, no re-entry), so the next slot does the same work.
"""
import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.runner import _acquire_lock, _release_lock, RunnerLockError

pytest.importorskip("apscheduler")
from global_index import run_scheduler as rs  # noqa: E402


# ── process level: E1 PID lock ────────────────────────────────────────────────

def test_lock_reacquire_by_same_pid_is_allowed(tmp_path):
    """run_live_day locks before connecting, then FuturesRunner locks again.
    Without this, every run would abort on its own lock file."""
    lock = tmp_path / "runner.pid"
    _acquire_lock(lock)
    _acquire_lock(lock)                      # must not raise
    assert lock.read_text().strip() == str(os.getpid())
    _release_lock(lock)


def test_lock_rejects_a_different_live_pid(tmp_path):
    """A genuinely concurrent runner must still be refused."""
    lock = tmp_path / "runner.pid"
    other = os.getppid()                     # a live PID that is not us
    if other == os.getpid() or other <= 0:
        pytest.skip("no distinct live parent PID available")
    lock.write_text(str(other))
    with pytest.raises(RunnerLockError):
        _acquire_lock(lock)


def test_stale_lock_is_overwritten(tmp_path):
    """A dead PID must not wedge the runner permanently."""
    lock = tmp_path / "runner.pid"
    lock.write_text("999999999")             # implausible, not running
    _acquire_lock(lock)
    assert lock.read_text().strip() == str(os.getpid())
    _release_lock(lock)


# ── scheduler level: slot mutex ───────────────────────────────────────────────

def _make_slot_runner():
    """Drive the REAL guard, not a copy of it.

    This used to be a "minimal stand-in for _live_day_body's guard, with the same
    semantics" — a second implementation, so it could only ever confirm that the copy
    behaved like itself. Changing the real guard would not have turned it red.

    That family has already cost this project twice: test_rollover asked the roll table
    with a key production never passes, which is how C1 survived a fully green suite,
    and the H5 work found this file testing a re-implementation of the very lock it
    claims to cover. The fix is a seam, not a better copy: _run_guarded is now a
    module-level function and _live_day_body calls it, so this test and production run
    the same code.
    """
    ran, skipped = [], []

    def body(slot_id, hold=0.0):
        def _inner():
            ran.append(slot_id)
            time.sleep(hold)

        if not rs._run_guarded(slot_id, _inner):
            skipped.append(slot_id)

    return body, ran, skipped


def test_overlapping_slot_is_skipped_not_queued():
    """The second slot must return immediately, not wait and then double-run."""
    body, ran, skipped = _make_slot_runner()
    t = threading.Thread(target=body, args=("SLOT_1410", 0.30))
    t.start()
    time.sleep(0.05)                         # 1410 is mid-flight
    t0 = time.time()
    body("SLOT_1415")                        # overlapping firing
    elapsed = time.time() - t0
    t.join()

    assert ran == ["SLOT_1410"], f"only the first slot may run, got {ran}"
    assert skipped == ["SLOT_1415"]
    assert elapsed < 0.10, f"skip must be immediate, took {elapsed:.3f}s (queued?)"


def test_slot_after_previous_finishes_runs_normally():
    """The guard must not latch — the next slot has to work."""
    body, ran, skipped = _make_slot_runner()
    body("SLOT_1410")
    body("SLOT_1415")
    assert ran == ["SLOT_1410", "SLOT_1415"]
    assert skipped == []


def test_lock_released_even_when_body_raises():
    """A crashing slot must not wedge every later slot."""
    lock = threading.Lock()
    ran = []

    def body(slot_id, boom=False):
        if not lock.acquire(blocking=False):
            return "skipped"
        try:
            if boom:
                raise RuntimeError("Gateway down")
            ran.append(slot_id)
        finally:
            lock.release()

    with pytest.raises(RuntimeError):
        body("SLOT_1410", boom=True)
    body("SLOT_1415")
    assert ran == ["SLOT_1415"], "guard must not latch after a failure"


def test_stop_repair_sweeps_share_the_slot_mutex():
    """All three entry points connect on the SAME IBKR clientId — they must not overlap.

    The mutex was written for the live_day slots and wrapped only those. The stop-repair
    sweeps run ten times a day through _run directly, holding no lock, and the guard's
    own message names the hazard: "overlapping children collide on IBKR clientId".

    The schedule keeps them apart on paper, but the margin is not what it looks like.
    Measured against the worst case a live_day slot is allowed (20-minute subprocess
    ceiling + 5-minute misfire grace on top of the 15:55 start):

        STOP_REPAIR_1620   0 minutes of clearance
        STOP_REPAIR_0420  60 minutes

    Zero. The 15:55 slot also runs a full shadow replay, which is the run most likely to
    reach that ceiling.

    Skipping a sweep costs nothing: they run every two hours and the repair they do is
    idempotent, so the next one does whatever this one would have.
    """
    ran = []
    rs._run = lambda *a, **k: ran.append(k.get("label"))       # replaced below anyway
    sched = rs.make_scheduler(port=4002, dry_run=True)
    job = sched.get_job("stop_repair_1620")
    assert job is not None and job.func is not None, (
        "no 16:20 sweep registered — the locator is broken, not satisfied")

    calls = []
    original_run, rs._run = rs._run, lambda *a, **k: calls.append(k.get("label"))
    try:
        assert rs._slot_lock.acquire(blocking=False), "lock must start free"
        try:
            job.func()                       # a live_day slot is still in flight
            assert calls == [], (
                f"the sweep launched a second child on clientId 1 while a run_live_day "
                f"child was still going: {calls}")
        finally:
            rs._slot_lock.release()
            rs._slot_started_at[0] = None

        job.func()                           # lock free again
        assert calls, "with the lock free the sweep must actually run"
    finally:
        rs._run = original_run


def test_the_max_hold_exit_is_deliberately_not_gated():
    """And the one job that must NOT be skipped stays outside the mutex.

    Nothing else performs the max-hold exit — run_day does not — so a skipped 09:31
    leaves a position open past its limit until the next day, with no retry path. That
    is a worse outcome than the collision the mutex prevents, and 09:31 has no schedule
    adjacency anyway: the nearest lock-holding window ends more than two hours earlier.

    Pinned so the split stays a decision rather than an oversight, and so anyone
    tempted to "finish the job" by wrapping this one has to read why first.
    """
    import ast
    src = (Path(__file__).resolve().parent / "run_scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "job_maxhold"), None)
    assert fn is not None, "job_maxhold is gone or renamed — the locator is broken"

    parents = {c: p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}
    launch = next((n for n in ast.walk(fn)
                   if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_run"), None)
    assert launch is not None, "job_maxhold no longer launches a child — locator broken"

    chain, node = [], launch
    while node in parents:
        node = parents[node]
        chain.append(getattr(getattr(node, "func", None), "id", None))
    assert "_run_guarded" not in chain, (
        "the max-hold exit was put behind the slot mutex. Nothing else performs this "
        "exit — run_day does not — so a skip leaves a position open past its limit "
        "with no retry path, and 09:31 has no schedule adjacency to protect it from. "
        "If this is intended, change the reasoning in this test first.")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
