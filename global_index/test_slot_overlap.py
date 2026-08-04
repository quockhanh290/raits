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
    """Minimal stand-in for _live_day_body's guard, with the same semantics."""
    lock = threading.Lock()
    ran, skipped = [], []

    def body(slot_id, hold=0.0):
        if not lock.acquire(blocking=False):
            skipped.append(slot_id)
            return
        try:
            ran.append(slot_id)
            time.sleep(hold)
        finally:
            lock.release()

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
