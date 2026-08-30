"""Stage 5P cleanup — the operator-facing text describes the safety split correctly.

Read-only: nothing here starts a process, opens a broker, or writes outside pytest's own
temp handling.

What this guards
----------------
Stage 5O split the safety net in two, and the operator text did not follow. `ops.py` still
told an operator, in the `--track1-only-shadow` help on both `up` and `restart` and in the
start banner, that "the safety sweeps still run against live_positions.json (Stage 5O)".

That sentence was true before 5O and false after it, and its specific danger is the
unqualified plural: there are **two** safety sets now, watching **two** books, and a reader
of the old sentence concludes a Track 1 position would go unprotected — the opposite of what
5O built.

The distinction every check below is built on:

    legacy drain safety   watches live_positions.json     — CORRECT, must stay sayable
    Track 1 safety        watches live_positions.track1.json

So the guard cannot simply ban the string `live_positions.json` near the word "safety" — that
would forbid the true sentence along with the false one. It bans the *claim shape*: safety
described as running against the legacy book **without** naming legacy as its owner.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import track1_slots as ts   # noqa: E402
from monitor import ops                       # noqa: E402

OPS = Path("monitor/ops.py")
RUNBOOK = Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md")
HANDOFF = Path("docs/futures/NORMAL_STRESS_CALM_HANDOFF_2026-08-22.md")
OPERATOR_FACING = [OPS, RUNBOOK, HANDOFF]


#: When this test module was imported — i.e. before any test in it ran. Used below instead of
#: asserting a file's ABSENCE. Measured 2026-08-24: the live scheduler's TRACK1_MAX_HOLD_EXIT
#: job ran at 07:31 local (09:31 ET) and wrote `global_index/maxhold_state.track1.json`
#: (`[TRACK1_MAX_HOLD_EXIT] completed OK` in scheduler_0824.log), which is exactly what Stage
#: 5O built that marker for. Absence had been standing in for "no test wrote it", and the
#: proxy broke the moment the running system started writing it legitimately. An mtime older
#: than this process is a stronger statement than absence ever was: it says no test in this
#: run touched it, which is the thing actually being guarded.
_IMPORTED_AT = __import__("time").time()


def _assert_not_written_by_this_run(name: str) -> None:
    p = Path(name)
    if not p.exists():
        return
    assert p.stat().st_mtime < _IMPORTED_AT, (
        f"{name} was written DURING this test run — everything here must run against "
        f"tmp_path")


def _lines(path: Path):
    return list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))


# ══════════════════════════════════════════════════════════════════════════════
# 1. the stale claim shape is gone
# ══════════════════════════════════════════════════════════════════════════════

#: "safety ... live_positions.json" in one line. Matched loosely on purpose — the point is
#: the shape, not one phrasing.
_SAFETY_LEGACY_BOOK = re.compile(
    r"safety|sweep|stop.?repair|max.?hold", re.IGNORECASE)

#: Words that make the same line TRUE by naming legacy as the owner of that book.
_QUALIFIED = re.compile(
    r"\b(legacy|drain|LEGACY_PATHS|never writes|must never|Stage 5M-D|as of|"
    r"until 5P cleanup|said|was true|before 5O)\b", re.IGNORECASE)


def _offending_lines(path: Path) -> list:
    out = []
    for n, line in _lines(path):
        if "live_positions.json" not in line:
            continue
        if not _SAFETY_LEGACY_BOOK.search(line):
            continue
        if _QUALIFIED.search(line):
            continue                     # names legacy/drain — the true sentence
        out.append(f"{path.name}:{n}: {line.strip()[:100]}")
    return out


@pytest.mark.parametrize("path", OPERATOR_FACING, ids=lambda p: p.name)
def test_no_operator_line_ties_safety_to_the_legacy_book_without_saying_legacy(path):
    assert path.exists(), path
    assert _offending_lines(path) == [], _offending_lines(path)


def test_the_guard_catches_the_exact_sentence_that_was_there():
    """The check above passes by finding nothing, which is the shape of a check that has
    quietly stopped looking. Hand it the real removed sentence and its true counterpart."""
    stale = "  safety sweeps   : still run against live_positions.json — Stage 5O"
    assert _SAFETY_LEGACY_BOOK.search(stale) and "live_positions.json" in stale
    assert not _QUALIFIED.search(stale), "the stale line must NOT look qualified"

    true_line = "legacy safety   : still scheduled, watching live_positions.json — the DRAIN"
    assert _QUALIFIED.search(true_line), "the true drain sentence must stay sayable"


def test_the_specific_stale_phrase_is_absent_everywhere():
    for path in OPERATOR_FACING:
        text = path.read_text(encoding="utf-8")
        assert "safety sweeps still run against live_positions.json" not in text, path.name
        assert "The safety sweeps still run against live_positions.json" not in text, path.name


# ══════════════════════════════════════════════════════════════════════════════
# 2. the text now says the right things
# ══════════════════════════════════════════════════════════════════════════════

def test_the_help_text_describes_both_safety_sets():
    """Both `up` and `restart` carry the same corrected string, and it names both books."""
    text = OPS.read_text(encoding="utf-8")
    helps = [l for l in text.splitlines() if "TRACK 1-ONLY shadow mode" in l]
    assert len(helps) == 2, f"expected the flag on up and restart, found {len(helps)}"
    for h in helps:
        assert "live_positions.track1.json" in h, "Track 1's own book is not named"
        assert "drain" in h.lower(), "the legacy set is not described as the drain"
        assert "all four sleeves" in h, "the help still implies fewer than four sleeves"
        assert "track1_safety_count()" in h, "the safety count is hardcoded, not derived"


def test_the_help_counts_are_derived_and_correct():
    assert ops.track1_slot_count() == len(ts.TRACK1_SLOTS) == 70
    assert ops.track1_safety_count() == len(ts.track1_safety_jobs()) == 11


def test_the_start_banner_names_both_safety_sets_and_both_books():
    text = OPS.read_text(encoding="utf-8")
    block = text[text.index('print(f"  track1 safety'):]
    block = block[:block.index("swing provider")]
    assert "_t1_const('TRACK1_POSITIONS_PATH')" in block
    assert "track1_safety_count()" in block
    assert "live_positions.json" in block and "DRAIN" in block


def test_the_banner_constants_resolve_to_the_route_tables():
    """The banner prints paths through `_t1_const`; those must be the real ones, or the
    operator reads a path the safety jobs do not use."""
    assert ops._t1_const("TRACK1_POSITIONS_PATH") == "live_positions.track1.json"
    assert ops._t1_const("TRACK1_LOCK_PATH") == "runner.track1.pid"
    assert ops._t1_const("TRACK1_SAFETY_CLIENT_ID") == 90
    assert len(ops._t1_safety()) == 11


# ══════════════════════════════════════════════════════════════════════════════
# 3. the other three misreadings the brief named
# ══════════════════════════════════════════════════════════════════════════════

_ROOT_SWITCH_STOPS_TRACK1 = re.compile(
    r"STOP_TRADING\b(?!\.track1)[^.\n]{0,80}\b(stops?|halts?|disables?)\b[^.\n]{0,30}"
    r"\bTrack\s*1\b", re.IGNORECASE)


@pytest.mark.parametrize("path", OPERATOR_FACING, ids=lambda p: p.name)
def test_no_line_says_the_root_switch_stops_track1(path):
    bad = []
    for n, line in _lines(path):
        if _ROOT_SWITCH_STOPS_TRACK1.search(line) and not re.search(
                r"\b(not|does not|never|myth|wrong|false)\b", line, re.IGNORECASE):
            bad.append(f"{path.name}:{n}: {line.strip()[:100]}")
    assert bad == [], bad


def test_the_root_switch_guard_would_catch_the_claim():
    assert _ROOT_SWITCH_STOPS_TRACK1.search("STOP_TRADING stops Track 1 as well")
    assert _ROOT_SWITCH_STOPS_TRACK1.search("place STOP_TRADING to halt Track 1")
    assert not _ROOT_SWITCH_STOPS_TRACK1.search(
        "STOP_TRADING.track1 stops Track 1"), "the route's OWN switch must stay sayable"


_NKD_UNOWNED = re.compile(
    r"\bNKD\b[^.\n]{0,60}\b(no Track ?1 slot|has no slot|not traded by anyone)\b",
    re.IGNORECASE)


@pytest.mark.parametrize("path", OPERATOR_FACING, ids=lambda p: p.name)
def test_no_unqualified_line_says_nkd_is_unowned(path):
    """Stage 5N gave NKD its 22 slots. A historical line may say so if it is dated."""
    bad = []
    for n, line in _lines(path):
        if _NKD_UNOWNED.search(line) and not _QUALIFIED.search(line):
            bad.append(f"{path.name}:{n}: {line.strip()[:100]}")
    assert bad == [], bad


def test_all_four_sleeves_really_are_owned():
    """The claim the text now makes, checked against the tables rather than the prose."""
    from collections import Counter
    got = Counter(s.sleeve for s in ts.TRACK1_SLOTS)
    assert got == {"roska4_calm": 1, "roska4_stress": 24,
                   "roska4_swing": 23, "global_nkd": 22}, got


# ══════════════════════════════════════════════════════════════════════════════
# 4. nothing about the route changed
# ══════════════════════════════════════════════════════════════════════════════

def test_the_schedule_is_untouched_by_a_text_change():
    import logging
    import os
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5p-text")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from global_index import run_scheduler as rs
        assert len(rs.make_scheduler(port=4002, dry_run=True).get_jobs()) == 61
        assert len(rs.make_scheduler(port=4002, dry_run=True,
                                     track1_shadow=True).get_jobs()) == 130
        # 95 + the Stage 5Q audit jobs, counted from their own table.
        from global_index import track1_slots as _ts
        assert len(rs.make_scheduler(port=4002, dry_run=True,
                                     track1_only=True).get_jobs()) == (
            96 + len(_ts.track1_audit_jobs()))
    finally:
        logging.disable(lvl)


def test_orders_are_still_impossible():
    from global_index import track1_gates as g
    assert g.as_ledger()["blocking_now"] == ["B1_broker_account_or_legacy_retirement"]
    assert g.may_enable_orders()[0] is False


def test_no_switch_or_state_file_exists():
    for name in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
                 "live_positions.track1.json", "runner.track1.pid"):
        assert not Path(name).exists(), name
    _assert_not_written_by_this_run("global_index/maxhold_state.track1.json")
