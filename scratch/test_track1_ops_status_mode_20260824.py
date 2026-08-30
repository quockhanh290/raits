"""Ops status reports the mode the RUNNING scheduler is actually in. 2026-08-24.

Read-only: nothing here starts, stops, connects or writes.

The bug
-------
With a scheduler genuinely running

    pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume --track1-only-shadow

`python monitor/ops.py status` printed:

    track1_mode=legacy-only
    track1_safety_routes=['legacy']

A rename boundary, one field wide. The PowerShell query selects `CommandLine`;
`scan_processes` maps it onto a dataclass attribute called `command`; `scheduler_processes`
emits dicts keyed `command`. `track1_status` asked for `CommandLine` — the name on the far
side of the boundary — and got `None`, which became `""`, and an empty string contains no
flags, which parses as legacy-only. Silent, because searching an empty string is a perfectly
successful operation.

Why no test caught it
---------------------
The Stage 5K status test builds its fixture with the key `CommandLine` — the key the *buggy
reader* wanted, not the key the *producer* emits. Test and bug agreed with each other, and
production disagreed with both. So the first test below drives the REAL
`scheduler_processes()` shape, and the second keeps the old shape working so the fallback is
deliberate rather than accidental.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from monitor import ops   # noqa: E402

BASE = "pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume"


def _row(flags: str = "", *, key: str = "command", pid: int = 1) -> dict:
    return {"pid": pid, key: f"{BASE} {flags}".strip(),
            "started": "2026-08-24 02:08:42", "age_seconds": 472}


@pytest.fixture
def procs(monkeypatch):
    def _set(rows):
        monkeypatch.setattr(ops, "scheduler_processes", lambda: rows)
    return _set


# ══════════════════════════════════════════════════════════════════════════════
# 1. the real producer shape — the case that was broken
# ══════════════════════════════════════════════════════════════════════════════

def test_track1_only_is_detected_from_the_command_key(procs):
    """The exact production shape: `scheduler_processes()` emits `command`, not
    `CommandLine`."""
    procs([_row("--track1-only-shadow")])
    t = ops.track1_status()
    assert t["scheduler_running"] is True
    assert t["scheduler_track1_only"] is True
    assert t["safety_routes"] == ["legacy", "track1"]


def test_the_printed_mode_is_track1_only(procs, capsys):
    procs([_row("--track1-only-shadow")])
    ops.print_track1_status()
    out = capsys.readouterr().out
    assert "track1_mode=track1-only-shadow" in out
    assert "legacy-only" not in out
    assert "['legacy', 'track1']" in out


def test_the_transitional_mode_still_reads_transitional(procs, capsys):
    procs([_row("--track1-shadow")])
    t = ops.track1_status()
    assert t["scheduler_track1_only"] is False
    assert t["scheduler_track1_shadow"] is True
    assert t["safety_routes"] == ["legacy"]
    ops.print_track1_status()
    assert "transitional" in capsys.readouterr().out


def test_no_flag_still_reads_legacy_only(procs, capsys):
    procs([_row()])
    t = ops.track1_status()
    assert t["scheduler_track1_only"] is False
    assert t["scheduler_track1_shadow"] is False
    assert t["safety_routes"] == ["legacy"]
    ops.print_track1_status()
    assert "track1_mode=legacy-only" in capsys.readouterr().out


def test_no_scheduler_reports_none_not_false(procs, capsys):
    """`False` would assert a fact about a process that does not exist."""
    procs([])
    t = ops.track1_status()
    assert t["scheduler_running"] is False
    assert t["scheduler_track1_only"] is None
    assert t["scheduler_track1_shadow"] is None
    assert t["safety_routes"] is None
    ops.print_track1_status()
    assert "track1_mode=n/a" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════════
# 2. the fallback, kept deliberately
# ══════════════════════════════════════════════════════════════════════════════

def test_the_legacy_commandline_key_still_resolves(procs):
    """A raw CIM row, or an older test, must keep working — but only as a FALLBACK."""
    procs([_row("--track1-only-shadow", key="CommandLine")])
    assert ops.track1_status()["scheduler_track1_only"] is True


def test_command_wins_over_commandline_when_both_are_present():
    row = {"pid": 1, "command": f"{BASE} --track1-only-shadow",
           "CommandLine": f"{BASE}"}
    assert "--track1-only-shadow" in ops.process_command(row)


def test_process_command_never_returns_none():
    assert ops.process_command({}) == ""
    assert ops.process_command({"command": None, "CommandLine": None}) == ""


def test_the_joiner_reads_every_process(procs):
    rows = [_row("--track1-only-shadow", pid=1), _row("--shadow-resume", pid=2)]
    joined = ops.scheduler_command_lines(rows)
    assert joined.count("run_scheduler") == 2
    assert "--track1-only-shadow" in joined


# ══════════════════════════════════════════════════════════════════════════════
# 3. the second field in the same payload
# ══════════════════════════════════════════════════════════════════════════════

def test_track1_only_implies_the_slots_are_registered(procs):
    """`make_scheduler` sets `track1_shadow = True` whenever `track1_only` is set, so a
    status answering the literal-flag question would report False for a scheduler running
    all 70 Track 1 slots."""
    procs([_row("--track1-only-shadow")])
    t = ops.track1_status()
    assert t["scheduler_track1_shadow"] is True, "the slots ARE registered in this mode"
    assert t["scheduler_track1_shadow_flag"] is False, "the literal flag is not on the argv"


def test_the_two_flags_do_not_overlap_as_substrings():
    """The OR above is the mode implication, not a workaround for one flag containing the
    other — if they DID overlap, the transitional check would be meaningless."""
    assert "--track1-shadow" not in "--track1-only-shadow"


def test_the_running_scheduler_is_reported_correctly_right_now():
    """Against the real process, not a fixture. Skips rather than lying when none is up."""
    real = ops.scheduler_processes()
    if not real:
        pytest.skip("no scheduler running on this machine")
    cmd = ops.scheduler_command_lines(real)
    assert cmd.strip(), "the command line resolved empty — the key mismatch is back"
    t = ops.track1_status()
    assert t["scheduler_track1_only"] == ("--track1-only-shadow" in cmd)
    assert t["safety_routes"] is not None


def test_no_kill_switch_was_created_and_any_decision_is_a_signed_one():
    """Stage 5ZZS. The confirmation file is expected on disk now; the switches still are not.

    Stage 5ZZJ placed a signed B1 decision here as a deliberate operator act. Asserting its
    absence asserted that no operator had decided anything - a claim this suite cannot make and
    was never trying to. What it CAN still hold is that nothing running has fabricated one, and
    a fabricated file is recognisable: it would carry no signatory, and an unsigned decision
    grants nothing while looking like a decision to anyone reading the path.
    """
    for name in ("STOP_TRADING", "STOP_TRADING.track1"):
        assert not Path(name).exists(), name

    conf = Path("track1_go_live_confirmation.json")
    if conf.exists():
        import json
        d = json.loads(conf.read_text(encoding="utf-8"))
        assert (d.get("confirmed_by") or "").strip(), "an unsigned decision appeared on disk"
        assert (d.get("confirmed_at") or "").strip(), "a decision with no date"
        # and it still must not be enough on its own
        from global_index import track1_gates as G
        allowed, _why = G.may_enable_orders()
        assert allowed is False, "a signed decision must not make orders possible"
