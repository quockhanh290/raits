"""Which slots run the dual-path comparison (--shadow-verify).

`--shadow-verify` replays the frame in full so the checkpoint-resumed target has
something to be compared against. Without it a slot logs only the resume result,
which proves the path RUNS but never that it AGREES.

Until 2026-08-10 the night NKD slots passed no `verify` at all — the parameter
simply defaulted to False at the `add_job` call — so the night path was never
compared on live data. MNKD was compared, but only on the 15:55 ET slot, which is
a different frame: the night run passes `--clusters nkd` and splices live bars
through `_splice_nkd_live`, and it is the night run that places NKD orders.

These assert on the command actually built, not on the source text, because the
bug was in the plumbing between the job registration and the command — exactly
what a source-text check would have read straight past.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from global_index import run_scheduler as rs


def _commands(monkeypatch) -> dict[str, list[str]]:
    """{slot_id: argv} for every day/night slot, with the pre-flight gate open.

    Both dates are seeded: night slots read the PREVIOUS business day's flag
    (prev_preflight=True), day slots read today's.
    """
    seen: dict[str, list[str]] = {}

    def _fake_run(args, label, dry_run, **kw):
        seen[label] = list(args)
        return True

    monkeypatch.setattr(rs, "_run", _fake_run)

    today = rs._et_today()
    prev = today
    from datetime import timedelta
    prev -= timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    monkeypatch.setitem(rs._preflight_ok, today.isoformat(), True)
    monkeypatch.setitem(rs._preflight_ok, prev.isoformat(), True)

    sched = rs.make_scheduler(port=4002, dry_run=False, shadow_resume=True)
    for job in sched.get_jobs():
        if job.id.startswith(("live_day_", "nkd_night_")):
            job.func()
    return seen


def _verified(seen: dict[str, list[str]], prefix: str) -> set[str]:
    return {sid for sid, argv in seen.items()
            if sid.startswith(prefix) and "--shadow-verify" in argv}


def test_sv1_exactly_one_night_slot_verifies(monkeypatch):
    """One comparison per night window, on the LAST slot.

    Not every slot: a full replay is the ~5 minutes the checkpoint exists to
    avoid, and slots are 5 minutes apart, so verifying on each would skip two
    slots in three — worse entry latency to prove latency could be better.
    """
    seen = _commands(monkeypatch)
    assert _verified(seen, "NKD_NIGHT_") == {"NKD_NIGHT_0255"}


def test_sv2_night_window_is_covered_at_all(monkeypatch):
    """The regression itself: zero verified night slots is the pre-fix state.

    Stated separately from sv1 so a future change that moves the slot still
    fails loudly here rather than looking like a naming quibble.
    """
    seen = _commands(monkeypatch)
    assert _verified(seen, "NKD_NIGHT_"), (
        "no night slot runs --shadow-verify; the NKD path that places orders "
        "would go uncompared on live data")


def test_sv3_verify_lands_after_the_entry_window_closes(monkeypatch):
    """02:55 ET is past NKD's 01:00-02:55 entry window, so the replay costs no fill.

    This is the whole reason the last slot is the safe one. If the verified slot
    ever moves earlier, the comparison starts competing with entries.
    """
    seen = _commands(monkeypatch)
    verified = _verified(seen, "NKD_NIGHT_")
    assert verified
    latest = max(int(sid.rsplit("_", 1)[1]) for sid in seen if sid.startswith("NKD_NIGHT_"))
    assert {int(sid.rsplit("_", 1)[1]) for sid in verified} == {latest}


def test_sv4_day_slots_unchanged(monkeypatch):
    """The night fix must not disturb the day family's single 15:55 comparison."""
    seen = _commands(monkeypatch)
    assert _verified(seen, "LIVE_DAY_") == {"LIVE_DAY_1555"}


def test_sv5_night_slots_keep_their_other_flags(monkeypatch):
    """--shadow-verify rides along; it does not replace the night slot's identity.

    The verified slot is built by the same lambda as the other 21, so a mistake
    there would silently drop `--clusters nkd` and every night slot would start
    closing Rổ 4 positions (signal_layer.py:110-112).
    """
    seen = _commands(monkeypatch)
    argv = seen["NKD_NIGHT_0255"]
    assert "--clusters" in argv and argv[argv.index("--clusters") + 1] == "nkd"
    assert "--shadow-resume" in argv


def test_sv6_verify_requires_shadow_resume(monkeypatch):
    """Without --shadow-resume there is no resumed target, so --shadow-verify is moot.

    run_live_day would replay in full and compare against nothing.
    """
    seen: dict[str, list[str]] = {}
    monkeypatch.setattr(rs, "_run",
                        lambda args, label, dry_run, **kw: seen.setdefault(label, list(args)))
    today = rs._et_today()
    from datetime import timedelta
    prev = today - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    monkeypatch.setitem(rs._preflight_ok, today.isoformat(), True)
    monkeypatch.setitem(rs._preflight_ok, prev.isoformat(), True)

    sched = rs.make_scheduler(port=4002, dry_run=False, shadow_resume=False)
    for job in sched.get_jobs():
        if job.id.startswith(("live_day_", "nkd_night_")):
            job.func()
    assert not any("--shadow-verify" in argv for argv in seen.values())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
