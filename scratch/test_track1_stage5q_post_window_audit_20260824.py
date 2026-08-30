"""Stage 5Q — the post-window / daily Track 1 audit job.

No scheduler started or stopped, no backend restarted, no IBKR connection, no order, no
confirmation file in the repo, no live state written. Every synthetic shadow day is built
under `tmp_path` and every audit run is pointed at `tmp_path` with `--root`, so the real
`global_index/track1_runtime/` tree is never written to by this suite.

What is under test
------------------
**That the audit judges by the committed gate and not by a second copy of it.** Stage 5P
committed `track1_shadow_acceptance` before any shadow day existed. 5Q adds scope — one
sleeve's window, or a whole day — and the danger of adding scope is that the new entry point
quietly re-states a threshold and the two drift. So the rules stay in the acceptance module
and the tests below degrade a green day one dimension at a time, requiring a NAMED reason
code each time.

**That "not judged yet" never reads as "passed".** Three things have to stay distinguishable:
a window that has not closed, a window that closed before the scheduler existed, and a window
that closed with the scheduler up and produced nothing. Only the third is a failure. The NKD
window of 2026-08-24 is the measured case for the second — it closed at 02:55 ET and the
track1-only scheduler started at 04:32 ET.

**That the audit cannot do anything but read and record.** No order flag, no bar provider, no
broker import, and no write outside its own audit directory.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

REPO = r"d:\raits"

from global_index import track1_shadow_acceptance as acc     # noqa: E402
from global_index import track1_shadow_audit as aud          # noqa: E402
from global_index import track1_slots as ts                  # noqa: E402
from global_index.track1_params import WINDOWS_ET            # noqa: E402
from monitor.backend import track1_runtime_reader as trr     # noqa: E402

DAY = "2026-08-25"
DAYC = DAY.replace("-", "")

#: A moment after every window of DAY has closed, and a start instant before every window
#: opened. Together they make all four sleeves judgeable.
LATE = f"{DAY}T23:00:00"
EARLY_START = f"{DAY}T00:05:00"

#: The expected slot counts, written out ONCE here so a test can read as a sentence. They are
#: asserted against the registry rather than trusted — a fixture that agrees with itself
#: proves nothing.
EXPECTED = {"roska4_calm": 1, "roska4_stress": 24, "roska4_swing": 23, "global_nkd": 22}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SWING_PROVIDER", "RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY",
              "RAITS_WINDOW_LEDGER_DIR", "RAITS_TELEMETRY_DIR"):
        monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# the synthetic shadow day
# ══════════════════════════════════════════════════════════════════════════════

def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def explanation_row(sleeve: str, day: str, *, slot_id: str = "TRACK1_X",
                    freshness: bool = True, structured: bool = True) -> dict:
    """One explanation row shaped like the ones the WRITER actually produces.

    Built through `track1_explain.no_action_record`, not by hand. The hand-written fixture
    this replaces carried a `proofs` key that no producer in the repo has ever emitted, so
    every test using it was checking a shape that does not exist — and it passed the old
    substring freshness check for the same reason a sentence would have.

    `structured=False` strips the typed freshness fields and leaves only the word in prose,
    which is exactly the row the Stage 5Q-2 check has to refuse.
    """
    from global_index import track1_explain as tx
    rec = tx.no_action_record(
        route="track1_candidate", session_date=day, sleeve=sleeve,
        instrument=tx.SLEEVE_INSTRUMENTS[sleeve][0], candidate_id=f"run:{slot_id}",
        decision_time=f"{day}T10:00:00", decision_mode=tx.SHADOW_LIVE,
        reason_code=(tx.NONE if freshness else tx.FRESHNESS_FAIL),
        rule_ids=[tx.FRESHNESS_CONTEXT_RULE],
        features=[tx.Feature("freshness_allow", bool(freshness), True, "==",
                             passed=bool(freshness), source="test fixture")],
        inputs_summary={"window": f"live_{day}/{sleeve}/{slot_id}",
                        "mode": tx.SHADOW_LIVE, "slot_id": slot_id,
                        "freshness_allow": bool(freshness)},
        outputs={}, identity=tx.Identity(route="track1_candidate"))
    if not structured:
        rec["feature_snapshot"] = []
        rec["inputs_summary"] = {"note": "the freshness of the frame was fine"}
    return rec


def _slots_by_sleeve() -> dict:
    out: dict = {}
    for s in ts.TRACK1_SLOTS:
        out.setdefault(s.sleeve, []).append(s)
    return out


def build_green_day(root: Path, *, day: str = DAY, runtime: float = 45.0) -> None:
    """A day that every sleeve passes: full coverage, every slot id, timing, explanations
    with freshness proofs, and a checkpoint naming this route and this day."""
    dayc = day.replace("-", "")
    ledger: list = []
    for sleeve, slots in _slots_by_sleeve().items():
        ledger.append({"event": "window_open", "sleeve": sleeve, "date": day,
                       "route": "track1_candidate", "expected_slots": len(slots)})
        for i, s in enumerate(slots):
            ledger.append({"event": "slot_observed", "sleeve": sleeve, "date": day,
                           "slot_id": s.id, "seq": i, "decided": True,
                           # one explained candidate on the first slot of each sleeve, so the
                           # "explanations were due" branch is exercised and not only the
                           # "nothing to explain" one
                           "explained": 1 if i == 0 else 0,
                           "route": "track1_candidate"})
        ledger.append({"event": "window_closed", "sleeve": sleeve, "date": day,
                       "outcome": "complete", "signal": "no_signal",
                       "observed_slots": len(slots), "expected_slots": len(slots),
                       "route": "track1_candidate"})
    _write_jsonl(root / acc.COVERAGE_DIR / f"window_coverage_{dayc}.jsonl", ledger)

    trows = [{"ts": f"{day}T15:00:00+00:00", "route": "track1_candidate", "slot_id": s.id,
              "outcome": "ok", "runtime_s": runtime, "phases": {}}
             for s in ts.TRACK1_SLOTS]
    _write_jsonl(root / acc.TIMING_DIR / f"slot_timing_{dayc}.jsonl", trows)

    erows = [explanation_row(sleeve, day, slot_id=f"TRACK1_{i}")
             for i, sleeve in enumerate(sorted(WINDOWS_ET))]
    _write_jsonl(root / acc.SHADOW_DIR / "explanations" / f"explanations_{dayc}.jsonl", erows)

    # Stage 5ZH: through `route_checkpoint.save_route`, and with the companion book.
    # The literal that stood here invented a flat payload the writer has never produced and
    # `route_checkpoint.load` rejects outright; it agreed with the reader, not the writer,
    # and that is exactly why the reader's defect survived three suites.
    from global_index import route_checkpoint as _rc
    _rc.save_route({}, route="track1_candidate", path=str(root / acc.CHECKPOINT_PATH))
    _bk = root / acc.CHECKPOINT_BOOK_PATH
    _bk.parent.mkdir(parents=True, exist_ok=True)
    _bk.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                               "window": "live", "cut_instant": f"{day}T15:55:01-04:00",
                               "cur_day": day, "positions": []}), encoding="utf-8")


@pytest.fixture
def green(tmp_path):
    build_green_day(tmp_path)
    return tmp_path


def _sleeve(root, sleeve, *, now=LATE, started=EARLY_START, day=DAY):
    return acc.evaluate_sleeve(day, sleeve, root, now_et=now, scheduler_started_et=started)


def _ledger_path(root, day=DAY):
    return root / acc.COVERAGE_DIR / f"window_coverage_{day.replace('-', '')}.jsonl"


def _read_ledger(root, day=DAY):
    return [json.loads(l) for l in _ledger_path(root, day).read_text(encoding="utf-8")
            .splitlines() if l.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# 1. the fixture is not agreeing with itself
# ══════════════════════════════════════════════════════════════════════════════

def test_the_expected_slot_counts_come_from_the_registry_not_from_this_file():
    """1 / 24 / 23 / 22, asserted against the slot registry AND the ledger's own table.

    Both, because they are two different declarations of the same contract: the registry is
    what the scheduler fires and the ledger table is what `complete` is measured against. A
    day can only pass when they agree, and this is where that is checked rather than assumed.
    """
    import global_index.window_ledger as wl
    by = {k: len(v) for k, v in _slots_by_sleeve().items()}
    assert by == EXPECTED
    assert {s: wl.expected_slots(s) for s in EXPECTED} == EXPECTED


def test_the_green_fixture_really_is_green_by_the_committed_gate(green):
    """If the fixture did not satisfy Stage 5P's gate, every degradation test below would be
    measuring the fixture rather than the degradation."""
    v = acc.evaluate_day(DAY, root=green)
    assert v["accepted"], v["failed"]


# ══════════════════════════════════════════════════════════════════════════════
# 2. PASS
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("sleeve", sorted(EXPECTED))
def test_a_fully_covered_window_passes(green, sleeve):
    r = _sleeve(green, sleeve)
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert r["expected_slots"] == EXPECTED[sleeve]
    assert r["observed_slots"] == EXPECTED[sleeve]
    assert r["missing_slot_ids"] == []
    assert r["route"] == "track1_candidate"


def test_the_day_roll_up_passes_and_carries_every_sleeve(green):
    r = acc.evaluate_day_audit(DAY, green, now_et=LATE, scheduler_started_et=EARLY_START)
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert set(r["sleeves"]) == set(EXPECTED)
    assert r["pending_sleeves"] == []
    assert r["acceptance_gate"]["accepted"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 3. NOT_ENOUGH_DATA_YET — the three ways a window is not judgeable
# ══════════════════════════════════════════════════════════════════════════════

def test_a_window_that_has_not_closed_is_pending_not_passed(green):
    """11:00 ET, and Normal-R4 closes at 15:55. Nothing has been proved, so the verdict must
    not be PASS; nothing has failed either, so it must not be FAIL."""
    r = _sleeve(green, "roska4_swing", now=f"{DAY}T11:00:00")
    assert r["verdict"] == acc.AUDIT_NOT_ENOUGH_DATA_YET
    assert acc.R_WINDOW_NOT_CLOSED in r["reasons"]
    assert r["judgeable"] is False


def test_a_window_that_closed_before_the_scheduler_started_is_pending_not_failed(tmp_path):
    """The measured 2026-08-24 case, with the evidence deliberately EMPTY.

    The operator started the track1-only session at 04:32 ET; the NKD window is 01:10-02:55
    ET, so all 22 slots had already passed and the ledger is empty for that sleeve. A naive
    gate calls that a failed sleeve, the operator wakes to a red banner over nothing, and
    learns to stop reading the banner.
    """
    r = acc.evaluate_sleeve(DAY, "global_nkd", tmp_path, now_et=f"{DAY}T06:53:00",
                            scheduler_started_et=f"{DAY}T04:32:00")
    assert r["verdict"] == acc.AUDIT_NOT_ENOUGH_DATA_YET
    assert acc.R_CLOSED_BEFORE_SCHEDULER_START in r["reasons"]
    assert "AFTER the window closed" in r["judgeability_reason"]


def test_a_window_the_scheduler_joined_midway_is_pending(tmp_path):
    r = acc.evaluate_sleeve(DAY, "roska4_stress", tmp_path, now_et=f"{DAY}T13:00:00",
                            scheduler_started_et=f"{DAY}T11:00:00")
    assert r["verdict"] == acc.AUDIT_NOT_ENOUGH_DATA_YET
    assert acc.R_SCHEDULER_JOINED_MIDWAY in r["reasons"]


def test_a_closed_window_with_no_evidence_and_no_readable_start_is_pending_not_failed(tmp_path):
    """The fail-open shape, closed in the safe direction.

    `scheduler_processes()` returns an empty list on ANY hiccup, and an empty list reads as
    'no scheduler'. If that became 'the scheduler was up', a window that closed before the
    process existed would be reported as a failure. So: no evidence at all AND no readable
    start instant is NOT_ENOUGH_DATA_YET, named, not PASS and not FAIL.
    """
    r = acc.evaluate_sleeve(DAY, "global_nkd", tmp_path, now_et=LATE,
                            scheduler_started_et=None)
    assert r["verdict"] == acc.AUDIT_NOT_ENOUGH_DATA_YET
    assert acc.R_UPTIME_UNKNOWN_NO_EVIDENCE in r["reasons"]


def test_an_unknown_start_does_not_excuse_a_window_that_left_partial_evidence(green):
    """The limit on the rule above: a sleeve with ledger rows HAD a process. Its incomplete
    coverage is a real gap and stays a failure whatever the process table says."""
    rows = [r for r in _read_ledger(green)
            if not (r["sleeve"] == "roska4_stress" and r["event"] == "window_closed")]
    _write_jsonl(_ledger_path(green), rows)
    r = acc.evaluate_sleeve(DAY, "roska4_stress", green, now_et=LATE,
                            scheduler_started_et=None)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_COVERAGE_UNOBSERVED in r["reasons"]


def test_the_day_roll_up_is_pending_when_no_window_is_judgeable_yet(tmp_path):
    r = acc.evaluate_day_audit(DAY, tmp_path, now_et=f"{DAY}T06:00:00",
                               scheduler_started_et=f"{DAY}T04:32:00")
    assert r["verdict"] == acc.AUDIT_NOT_ENOUGH_DATA_YET
    assert sorted(r["pending_sleeves"]) == sorted(EXPECTED)


# ══════════════════════════════════════════════════════════════════════════════
# 4. FAIL — one degradation at a time, each with a named reason
# ══════════════════════════════════════════════════════════════════════════════

def test_a_silent_slot_masked_by_a_doubled_one_fails_on_the_ids(green):
    """The check a COUNT cannot do.

    The window still closes at 24 of 24 and `observed_slots` still reads complete, because
    one slot fired twice while another never fired at all. Only the ids see it.
    """
    rows = _read_ledger(green)
    victim = None
    for r in rows:
        if r["event"] == "slot_observed" and r["sleeve"] == "roska4_stress":
            victim = r["slot_id"]
            break
    assert victim
    # Derived, not written out: a literal slot id in a test is one window change away from
    # silently selecting nothing, and an empty selection here would mask the very defect
    # this test exists for.
    doubled_id = acc.sleeve_slot_ids("roska4_stress")[-1]
    assert doubled_id != victim
    twin = [r for r in rows if r.get("slot_id") == doubled_id][0]
    rows = [r for r in rows if r.get("slot_id") != victim]
    rows.append(dict(twin))
    _write_jsonl(_ledger_path(green), rows)

    r = _sleeve(green, "roska4_stress")
    assert r["coverage_outcome"] == "complete"      # the count still says yes
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_MISSING_SLOT_IDS in r["reasons"]
    assert victim in r["missing_slot_ids"]


def test_a_ledger_incomplete_close_is_reported_but_does_not_by_itself_fail(green):
    """Stage 5Q-1 changed this test, and the change is the point.

    Before, an `incomplete` close record failed the sleeve outright. That is the committed
    daily gate's rule — it counts only slots that DECIDED — and it is the wrong rule for an
    operational audit, because a slot the intraday gate refused `too_late` ran and looked.
    Here every slot still has its row, so the observation is whole: the audit reports the
    ledger's disagreement by name and does not fail on it.

    The failures that ARE gaps are pinned by the tests either side of this one.
    """
    rows = [r for r in _read_ledger(green)
            if not (r["sleeve"] == "roska4_calm" and r["event"] == "window_closed")]
    rows.append({"event": "window_closed", "sleeve": "roska4_calm", "date": DAY,
                 "outcome": "incomplete", "signal": "no_signal",
                 "observed_slots": 0, "expected_slots": 1, "route": "track1_candidate"})
    _write_jsonl(_ledger_path(green), rows)
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert acc.R_COVERAGE_INCOMPLETE in r["reasons"]
    assert r["ledger_outcome"] == "incomplete"
    assert r["observation"]["observed"] == r["observation"]["registered"]


def test_a_window_with_no_close_record_still_fails(green):
    """The ledger's fail-closed rule, kept exactly: absence of a `window_closed` record means
    nobody can vouch for the window, whatever else is on disk."""
    rows = [r for r in _read_ledger(green)
            if not (r["sleeve"] == "roska4_calm" and r["event"] == "window_closed")]
    _write_jsonl(_ledger_path(green), rows)
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_COVERAGE_UNOBSERVED in r["reasons"]


def test_missing_timing_fails_rather_than_passing_quietly(green):
    """A window nobody measured cannot be judged fast OR slow, and 'no file' must not be the
    quickest route to a green audit."""
    (green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl").unlink()
    r = _sleeve(green, "global_nkd")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_NO_TIMING in r["reasons"]
    assert r["runtime_p95_s"] is None


def test_missing_explanations_fail_when_the_ledger_says_some_were_due(green):
    """No explanation row anywhere for the day, while the ledger says candidates were
    explained. Stage 5Q-1 narrowed this to "nowhere for the day": a sleeve's rows can also be
    absent because a LATER sleeve truncated the shared file, and that is the writer's defect
    rather than this sleeve's gap — pinned separately in the 5Q-1 suite."""
    (green / acc.SHADOW_DIR / "explanations" / f"explanations_{DAYC}.jsonl").unlink()
    r = _sleeve(green, "roska4_swing")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_EXPLANATIONS_MISSING in r["reasons"]
    assert r["explanations"]["expected_from_ledger"] == 1


def test_no_explanations_passes_only_when_the_ledger_records_none_as_due(green):
    """The other half of the same rule, and the reason it is not simply 'file must exist'.

    A sleeve that saw no candidate has nothing to explain. That passes — but it passes on a
    POSITIVE record saying zero were due, and the reason is named in the audit, so it can
    never be confused with a sleeve whose explanations went missing.
    """
    rows = []
    for r in _read_ledger(green):
        if r["event"] == "slot_observed":
            r = {**r, "explained": 0}
        rows.append(r)
    _write_jsonl(_ledger_path(green), rows)
    (green / acc.SHADOW_DIR / "explanations" / f"explanations_{DAYC}.jsonl").unlink()
    r = _sleeve(green, "roska4_swing")
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert acc.R_NO_CANDIDATES_TO_EXPLAIN in r["reasons"]


def test_an_explanation_without_a_freshness_proof_fails(green):
    """The Stage 5Z contract: a binding mode cites the gate it passed.

    Rewritten in Stage 5Q-2. It used to strip a `proofs` key — a field no producer in this
    repo has ever emitted, so it was removing something that was never there and the row
    passed the old substring check on the word appearing elsewhere. Now it strips the TYPED
    fields and leaves the word in prose, which is exactly the row the structured check exists
    to refuse.
    """
    p = green / acc.SHADOW_DIR / "explanations" / f"explanations_{DAYC}.jsonl"
    _write_jsonl(p, [explanation_row("roska4_calm", DAY, structured=False)])
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_MISSING_FRESHNESS_PROOF in r["reasons"]


def test_an_order_mark_fails_every_sleeve_however_far_the_day_got(green):
    """An order mark during a shadow period is a failure of the ROUTE, not of one window, so
    it is judged on every audit — including on a sleeve whose window has not closed yet."""
    p = green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows[0]["order_id"] = 4711
    _write_jsonl(p, rows)
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_ORDER_MARK in r["reasons"]
    pending = _sleeve(green, "roska4_swing", now=f"{DAY}T11:00:00")
    assert pending["verdict"] == acc.AUDIT_FAIL


def test_a_confirmation_file_fails_the_audit(green):
    """`track1_go_live_confirmation.json` under the audited tree ONLY — never in the repo."""
    (green / acc.CONFIRMATION_PATH).write_text(
        json.dumps({"schema_version": 1, "legacy_retired_confirmed": True}), encoding="utf-8")
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CONFIRMATION_FILE in r["reasons"]


def test_a_checkpoint_naming_another_route_fails(green):
    # Stage 5ZH: unlink first. `save_route` merges scoped by design, so writing a second
    # route into the existing file would leave ours in place and the check would rightly
    # pass. The condition under test is a file that does not hold this route at all.
    from global_index import route_checkpoint as _rc
    ck = green / acc.CHECKPOINT_PATH
    ck.unlink()
    _rc.save_route({}, route="legacy", path=str(ck))
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_WRONG_ROUTE in r["reasons"]


def test_a_checkpoint_cut_on_another_day_fails(green):
    # Stage 5ZH: the day of an EMPTY checkpoint comes from the book written beside it, so
    # that is what gets moved. The checkpoint itself carries no day when it has no entries.
    bk = green / acc.CHECKPOINT_BOOK_PATH
    bk.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                              "window": "live", "cut_instant": "2026-08-19T15:55:01-04:00",
                              "cur_day": "2026-08-19", "positions": []}), encoding="utf-8")
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_WRONG_DAY in r["reasons"]


def test_a_missing_checkpoint_fails_a_completed_window(green):
    (green / acc.CHECKPOINT_PATH).unlink()
    r = _sleeve(green, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_MISSING in r["reasons"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. runtime — the WARN band, and both ways to fail it
# ══════════════════════════════════════════════════════════════════════════════

def test_p95_between_the_target_and_the_ceiling_warns_and_does_not_fail(tmp_path):
    build_green_day(tmp_path, runtime=250.0)
    r = _sleeve(tmp_path, "roska4_stress")
    assert r["verdict"] == acc.AUDIT_WARN, r["reasons"]
    assert acc.R_P95_OVER_TARGET in r["reasons"]
    assert 240.0 <= r["runtime_p95_s"] < 300.0


def test_p95_at_the_ceiling_fails(tmp_path):
    build_green_day(tmp_path, runtime=310.0)
    r = _sleeve(tmp_path, "roska4_stress")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_P95_OVER_CEILING in r["reasons"]


def test_a_single_slot_over_the_ceiling_fails_even_with_a_healthy_p95(green):
    """An overrun IS a stall inside a window. One slot at 301s against a p95 of 45s must not
    be averaged away — the slot after it was due 300 seconds later."""
    p = green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    for row in rows:
        if row["slot_id"].startswith("TRACK1_NKD"):
            row["runtime_s"] = 301.0
            break
    _write_jsonl(p, rows)
    r = _sleeve(green, "global_nkd")
    assert r["runtime_p95_s"] < 300.0
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_SLOT_STALL in r["reasons"]


def test_a_warning_on_one_sleeve_does_not_become_a_failure_of_the_day(tmp_path):
    build_green_day(tmp_path, runtime=250.0)
    r = acc.evaluate_day_audit(DAY, tmp_path, now_et=LATE, scheduler_started_et=EARLY_START)
    assert r["verdict"] == acc.AUDIT_WARN
    assert r["acceptance_gate"]["accepted"] is True


def test_one_failing_sleeve_makes_the_day_fail(green):
    (green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl").unlink()
    r = acc.evaluate_day_audit(DAY, green, now_et=LATE, scheduler_started_et=EARLY_START)
    assert r["verdict"] == acc.AUDIT_FAIL


# ══════════════════════════════════════════════════════════════════════════════
# 6. the vocabulary, and the acceptance module's own consistency
# ══════════════════════════════════════════════════════════════════════════════

def test_the_audit_and_the_live_verdicts_spell_the_same_words_the_same_way():
    """Two entry points, one vocabulary. If someone renames one the other has to move."""
    assert acc.AUDIT_FAIL == acc.VERDICT_FAIL == "FAIL"
    assert acc.AUDIT_NOT_ENOUGH_DATA_YET == acc.NOT_ENOUGH_DATA_YET == "NOT_ENOUGH_DATA_YET"
    assert acc.AUDIT_PASS == "PASS" and acc.AUDIT_WARN == "WARN"
    # and they are NOT the per-check statuses, which is the confusion the module docstring
    # already records having very nearly shipped
    assert acc.AUDIT_FAIL != acc.FAIL and acc.AUDIT_WARN != acc.WARN


def test_pending_is_not_a_degree_of_badness():
    """`NOT_ENOUGH_DATA_YET` is off the PASS/WARN/FAIL ladder on purpose. Ranking it would
    let a window nobody has judged be printed as a mild failure."""
    assert acc.AUDIT_NOT_ENOUGH_DATA_YET not in acc._SEVERITY
    assert acc._worse(acc.AUDIT_PASS, acc.AUDIT_WARN) == acc.AUDIT_WARN
    assert acc._worse(acc.AUDIT_WARN, acc.AUDIT_FAIL) == acc.AUDIT_FAIL
    assert acc._worse(acc.AUDIT_FAIL, acc.AUDIT_PASS) == acc.AUDIT_FAIL


def test_windows_status_still_answers_for_today_when_no_day_is_given():
    """The `day` argument is additive. Every pre-5Q caller passes none and must be unmoved."""
    a = acc.windows_status(f"{DAY}T23:00:00", EARLY_START)
    b = acc.windows_status(f"{DAY}T23:00:00", EARLY_START, day=DAY)
    assert a == b


def test_the_sleeve_ids_come_from_the_registry(green):
    for sleeve, n in EXPECTED.items():
        assert len(acc.sleeve_slot_ids(sleeve)) == n
        assert all(i in ts.track1_slot_ids() for i in acc.sleeve_slot_ids(sleeve))


# ══════════════════════════════════════════════════════════════════════════════
# 7. the runner: what it writes, and what it must not
# ══════════════════════════════════════════════════════════════════════════════

def _tree(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_the_audit_writes_only_into_its_own_audit_directory(green):
    before = _tree(green)
    rc = aud.main(["--root", str(green), "--date", DAY, "--all",
                   "--scheduler-started", EARLY_START, "--now", LATE])
    assert rc == 0
    new = _tree(green) - before
    assert new, "the audit wrote nothing at all"
    assert all(p.startswith("global_index/track1_runtime/audits/") for p in new), new


def test_the_audit_never_edits_the_evidence_it_judges(green):
    """A judge that can edit the exhibits is not a judge. Byte-for-byte, not mtime."""
    watched = {p: p.read_bytes() for p in green.rglob("*")
               if p.is_file() and "track1_runtime" in p.as_posix()}
    assert watched
    aud.main(["--root", str(green), "--date", DAY, "--all",
              "--scheduler-started", EARLY_START, "--now", LATE])
    for p, blob in watched.items():
        assert p.read_bytes() == blob, p


def test_every_record_is_route_stamped_and_carries_the_reason_codes(green):
    aud.main(["--root", str(green), "--date", DAY, "--all",
              "--scheduler-started", EARLY_START, "--now", LATE])
    recs = aud.read_records(DAY, green)
    assert len(recs) == len(EXPECTED) + 1          # four sleeves plus the day roll-up
    assert {r["route"] for r in recs} == {"track1_candidate"}
    assert all(r["schema"] == aud.SCHEMA for r in recs)
    assert all(r["ts"] for r in recs)
    assert all("reasons" in r for r in recs)
    assert all(r["scheduler_start_source"] == aud.SRC_ARGV for r in recs)
    day_rec = [r for r in recs if r["scope"] == "day"][0]
    assert day_rec["verdict"] == acc.AUDIT_PASS
    assert set(day_rec["sleeves"]) == set(EXPECTED)


def test_a_second_audit_of_the_same_day_appends_rather_than_replacing(green):
    """Calm is judged at 10:10 and Stress at 12:40. If the second run overwrote the file, the
    morning's record of whether Calm was ever judged would vanish at lunchtime."""
    aud.main(["--root", str(green), "--date", DAY, "--sleeve", "roska4_calm",
              "--scheduler-started", EARLY_START, "--now", LATE])
    aud.main(["--root", str(green), "--date", DAY, "--sleeve", "roska4_stress",
              "--scheduler-started", EARLY_START, "--now", LATE])
    recs = aud.read_records(DAY, green)
    assert [r["sleeve"] for r in recs] == ["roska4_calm", "roska4_stress"]


def test_one_sleeve_can_be_audited_on_its_own(green):
    aud.main(["--root", str(green), "--date", DAY, "--sleeve", "global_nkd",
              "--scheduler-started", EARLY_START, "--now", LATE])
    recs = aud.read_records(DAY, green)
    assert len(recs) == 1 and recs[0]["sleeve"] == "global_nkd"
    assert recs[0]["verdict"] == acc.AUDIT_PASS


def test_a_period_of_several_days_writes_one_file_per_day(tmp_path):
    days = ["2026-08-25", "2026-08-26"]
    for d in days:
        build_green_day(tmp_path, day=d)
    rc = aud.main(["--root", str(tmp_path), "--from", days[0], "--to", days[1], "--all",
                   "--scheduler-started", "2026-08-25T00:05:00",
                   "--now", "2026-08-27T23:00:00"])
    assert rc == 0
    for d in days:
        assert aud.audit_path(d, tmp_path).exists()
        assert len(aud.read_records(d, tmp_path)) == len(EXPECTED) + 1


def test_latest_picks_the_most_recent_session_day_the_evidence_knows(tmp_path):
    for d in ("2026-08-24", "2026-08-25"):
        build_green_day(tmp_path, day=d)
    assert aud.latest_session_day(tmp_path, now_et="2026-08-25T23:00:00") == "2026-08-25"
    # and it never audits a stale day when today has evidence-free windows: today wins
    assert aud.latest_session_day(tmp_path, now_et="2026-08-27T23:00:00") == "2026-08-27"


def test_dry_run_writes_nothing(green):
    before = _tree(green)
    aud.main(["--root", str(green), "--date", DAY, "--all", "--dry-run",
              "--scheduler-started", EARLY_START, "--now", LATE])
    assert _tree(green) == before


def test_the_exit_code_is_zero_on_a_failing_verdict_by_default(green):
    """A shadow window with a gap and a broken audit tool must not share one red light in the
    scheduler log."""
    (green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl").unlink()
    assert aud.main(["--root", str(green), "--date", DAY, "--all",
                     "--scheduler-started", EARLY_START, "--now", LATE]) == 0
    assert aud.main(["--root", str(green), "--date", DAY, "--all", "--exit-nonzero-on-fail",
                     "--scheduler-started", EARLY_START, "--now", LATE]) == 2


def test_the_headline_never_says_pass_about_a_set_that_judged_nothing(tmp_path, capsys):
    """The bug this test was written for, measured on the live tree at 07:43 ET 2026-08-24.

    Four windows pending, and the last line of the report read `WORST VERDICT: PASS` —
    because the roll-up seeded itself at PASS and then skipped every pending record. The line
    an operator reads first must not be able to claim a pass over a day nobody judged.
    """
    rc = aud.main(["--root", str(tmp_path), "--date", DAY, "--all", "--dry-run",
                   "--no-process-probe", "--now", f"{DAY}T06:00:00"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WORST VERDICT: NOT_ENOUGH_DATA_YET" in out
    assert "WORST VERDICT: PASS" not in out


def test_the_headline_still_says_pass_when_something_actually_passed(green, capsys):
    aud.main(["--root", str(green), "--date", DAY, "--all", "--dry-run",
              "--no-process-probe", "--scheduler-started", EARLY_START, "--now", LATE])
    assert "WORST VERDICT: PASS" in capsys.readouterr().out


def test_the_report_survives_a_codepage_that_cannot_encode_it(green):
    """A scheduled child writes into a PIPE, and on Windows a pipe takes the locale codepage.

    The report carries em dashes; cp1252 cannot encode them. `deploy_sim` once ran a full
    simulation for 3m51s and then died on its last print for exactly this reason, and a
    verdict lost to a dash would look identical to an audit that crashed.
    """
    import os
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "cp1252"
    r = subprocess.run(
        [sys.executable, "-m", "global_index.track1_shadow_audit", "--root", str(green),
         "--date", DAY, "--all", "--dry-run", "--no-process-probe",
         "--scheduler-started", EARLY_START, "--now", LATE],
        cwd=REPO, capture_output=True, text=True, errors="replace", env=env,
        timeout=300)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "WORST VERDICT" in r.stdout


# ══════════════════════════════════════════════════════════════════════════════
# 8. the scheduler start resolver — three outcomes, never two
# ══════════════════════════════════════════════════════════════════════════════

def test_an_explicit_start_is_used_and_labelled():
    ts_, src, _note = aud.scheduler_start_et("2026-08-25T04:32:00")
    assert src == aud.SRC_ARGV and str(ts_).startswith("2026-08-25 04:32")


def test_an_unparseable_start_is_unknown_not_absent():
    """`unknown` and `no scheduler` must not collapse: the second would turn a window that
    closed before the process existed into a manufactured incident."""
    _ts, src, note = aud.scheduler_start_et("not-a-time")
    assert src == aud.SRC_UNKNOWN and "could not parse" in note


def test_an_unreadable_process_table_is_unknown_not_absent(monkeypatch):
    import monitor.ops as ops
    monkeypatch.setattr(ops, "scheduler_processes",
                        lambda: (_ for _ in ()).throw(RuntimeError("CIM failed")))
    _ts, src, note = aud.scheduler_start_et(None)
    assert src == aud.SRC_UNKNOWN and "unreadable" in note


def test_an_empty_process_table_says_not_seen_rather_than_not_running(monkeypatch):
    import monitor.ops as ops
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [])
    _ts, src, note = aud.scheduler_start_et(None)
    assert src == aud.SRC_UNKNOWN and "not seen" in note


def test_the_probe_can_be_switched_off_without_touching_the_process_table(monkeypatch):
    import monitor.ops as ops
    monkeypatch.setattr(ops, "scheduler_processes",
                        lambda: pytest.fail("the probe was disabled and ran anyway"))
    _ts, src, _note = aud.scheduler_start_et(None, probe=False)
    assert src == aud.SRC_UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
# 9. the audit cannot reach a broker or an order
# ══════════════════════════════════════════════════════════════════════════════

def test_the_audit_module_imports_no_broker_in_a_fresh_interpreter():
    """Measured in a SEPARATE process, not by reading the import list: a transitive import
    three modules down is exactly what a source scan misses."""
    out = subprocess.run(
        [sys.executable, "-c",
         "import sys; import global_index.track1_shadow_audit as a; "
         "bad=[m for m in sys.modules if 'ib_insync' in m or 'ibkr_broker' in m "
         "or m.endswith('.broker')]; print(bad)"],
        cwd=r"d:\raits", capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "[]", out.stdout


def test_the_audit_source_names_no_order_flag_and_no_bar_provider():
    src = Path(aud.__file__).read_text(encoding="utf-8")
    for nope in ("--allow-orders", "--bar-provider", "TRACK1_ORDERS_APPROVED",
                 "send_order", "ib_insync"):
        assert nope not in src.replace("`--allow-orders`", "").replace(
            "`--bar-provider`", ""), nope


def test_the_audit_writes_only_under_the_audits_directory_at_the_source_level():
    """Parsed, not grepped. Every write call in the module must go through the one path
    builder, so a future edit cannot open a file beside the evidence by accident."""
    import ast
    src = Path(aud.__file__).read_text(encoding="utf-8")
    writes = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", getattr(n.func, "id", ""))
            if name in {"open", "write_text", "write_bytes", "unlink", "rmtree", "rename"}:
                writes.append((name, n.lineno))
    assert [w[0] for w in writes] == ["open"], writes
    assert "def audit_path(" in src and "AUDITS_DIR" in src


def test_the_audit_directory_constant_is_durable_and_shared():
    assert acc.AUDITS_DIR.startswith("global_index/track1_runtime/")
    assert not acc.AUDITS_DIR.startswith("scratch")
    assert aud.AUDITS_DIR == acc.AUDITS_DIR == trr.AUDITS_DIR


# ══════════════════════════════════════════════════════════════════════════════
# 10. the scheduler inventory
# ══════════════════════════════════════════════════════════════════════════════

def _sched(**kw):
    import os
    from global_index import run_scheduler as rs
    os.environ.setdefault("PYTEST_CURRENT_TEST", "track1-5q")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return rs.make_scheduler(port=4002, dry_run=True, **kw)
    finally:
        logging.disable(lvl)


def test_the_audit_jobs_fire_after_their_windows_close_with_a_measured_buffer():
    """Times DERIVED from the window table, not written down.

    The buffer is not taste: the last slot of a window fires AT the close minute and may run
    to the 300 s cadence ceiling the acceptance gate enforces, so close + 5 min is the
    earliest the window is guaranteed to have finished writing. The rest is margin.
    """
    jobs = {j.sleeve or "day": (j.hour, j.minute) for j in ts.track1_audit_jobs()}
    assert jobs == {"roska4_calm": (10, 10), "roska4_stress": (12, 40),
                    "roska4_swing": (16, 5), "global_nkd": (3, 5), "day": (16, 15)}
    for sleeve, (lo, hi) in WINDOWS_ET.items():
        h, m = (int(x) for x in hi.split(":"))
        close = h * 60 + m
        at = jobs[sleeve][0] * 60 + jobs[sleeve][1]
        assert (at - close) % (24 * 60) >= acc.RUNTIME_P95_REQUIRED_S / 60


def test_track1_only_gains_exactly_the_audit_jobs_and_no_legacy_strategy():
    ids = {j.id for j in _sched(track1_only=True).get_jobs()}
    audit = {j.id for j in ts.track1_audit_jobs()}
    assert audit <= ids
    assert len(ids) == 96 + len(audit) == 101  # Stage 5Q-5 added the 16:20 post-close SPY refresh (shared infra, all modes): 60->61, 129->130, 100->101
    assert [i for i in ids if i.startswith(("live_day", "nkd_night"))] == []
    # and the two other modes are untouched
    assert len(_sched().get_jobs()) == 61
    assert len(_sched(track1_shadow=True).get_jobs()) == 130
    assert audit.isdisjoint({j.id for j in _sched(track1_shadow=True).get_jobs()})


def test_the_audit_jobs_are_classified_as_track1_not_unclassified():
    c = ts.route_classification(track1_shadow=True)
    assert c["unclassified"] == []
    for j in ts.track1_audit_jobs():
        assert ts._bucket_for(j.id) == "track1"


def test_the_scheduler_and_the_dashboard_mirror_agree_in_every_mode():
    """One table, two readers. A job the scheduler runs and the mirror does not know about
    shows up on the operator's screen as a phantom overdue row every day."""
    for kw in ({}, {"track1_shadow": True}, {"track1_only": True}):
        r = ts.parity_report(**kw)
        assert r["in_parity"], (kw, r["only_in_scheduler"], r["only_in_dashboard_mirror"])


def test_the_audit_job_argv_carries_no_order_or_broker_flag():
    started = "2026-08-25T04:32:00"
    for j in ts.track1_audit_jobs():
        argv = ts.audit_job_argv(j, scheduler_started_et=started)
        assert argv[1:3] == ["-m", "global_index.track1_shadow_audit"]
        for nope in ("--allow-orders", "--bar-provider", "--port", "--window",
                     "--persist-book"):
            assert nope not in argv, (j.id, nope)
        assert argv[argv.index("--scheduler-started") + 1] == started
        if j.scope == "sleeve":
            assert argv[argv.index("--sleeve") + 1] == j.sleeve
        else:
            assert "--all" in argv


def test_the_scheduler_spawns_the_audit_children_it_registered():
    """Fires every Track 1 job with the subprocess runner replaced, and checks what each
    child WOULD have been. Nothing executes and no process is started."""
    import os
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    os.environ.setdefault("PYTEST_CURRENT_TEST", "track1-5q")
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args), "route": route}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_only=True)
        for j in sched.get_jobs():
            if j.id.startswith("track1_audit"):
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    assert len(seen) == len(ts.track1_audit_jobs())
    assert {r["route"] for r in seen} == {"track1_candidate"}
    for r in seen:
        a = r["args"]
        assert a[1:3] == ["-m", "global_index.track1_shadow_audit"]
        for nope in ("--allow-orders", "--bar-provider", "--port", "--window"):
            assert nope not in a, (r["label"], nope)
        # the scheduler hands the child its OWN start instant rather than making it guess
        assert "--scheduler-started" in a
        assert rs._PROCESS_START_ET == a[a.index("--scheduler-started") + 1]


# ══════════════════════════════════════════════════════════════════════════════
# 11. the dashboard reads the audit, and says so when it is absent
# ══════════════════════════════════════════════════════════════════════════════

def test_the_reader_says_not_run_yet_rather_than_leaving_it_blank(tmp_path):
    r = trr.read_track1_runtime(tmp_path)["audits"]
    assert r["present"] is False
    assert "not judged yet" in r["reading"]
    assert "pass" in r["reading"].lower()


def test_an_empty_audit_directory_is_still_not_a_pass(tmp_path):
    (tmp_path / trr.AUDITS_DIR).mkdir(parents=True)
    r = trr.read_track1_runtime(tmp_path)["audits"]
    assert r["present"] is True and r["latest_day"] is None
    assert "not been judged" in r["reading"]


def test_the_reader_surfaces_the_latest_verdict_per_sleeve_and_per_day(green):
    aud.main(["--root", str(green), "--date", DAY, "--all",
              "--scheduler-started", EARLY_START, "--now", LATE])
    r = trr.read_track1_runtime(green)["audits"]
    assert r["latest_day"] == DAY
    assert r["latest"]["day"]["verdict"] == acc.AUDIT_PASS
    assert {s: v["verdict"] for s, v in r["latest"]["sleeves"].items()} == {
        s: acc.AUDIT_PASS for s in EXPECTED}
    assert r["not_audited_yet"] == []


def test_a_partly_audited_day_names_the_sleeves_nobody_judged(green):
    aud.main(["--root", str(green), "--date", DAY, "--sleeve", "roska4_calm",
              "--scheduler-started", EARLY_START, "--now", LATE])
    r = trr.read_track1_runtime(green)["audits"]
    assert sorted(r["not_audited_yet"]) == ["global_nkd", "roska4_stress", "roska4_swing"]
    assert r["latest"]["day"] is None


def test_the_endpoint_serves_the_audit_block():
    src = Path(trr.__file__).read_text(encoding="utf-8")
    assert '"audits": _audits(root)' in src
    app_src = Path(r"d:\raits\monitor\backend\app.py").read_text(encoding="utf-8")
    assert "/api/v1/track1-runtime" in app_src


def test_the_reader_stays_read_only_after_the_audit_block_was_added():
    """The Stage 5P guard, re-run here because 5Q edited the module it protects."""
    import ast
    src = Path(trr.__file__).read_text(encoding="utf-8")
    banned = {"write_text", "write_bytes", "mkdir", "unlink", "rename", "dump", "open"}
    hits = [(getattr(n.func, "attr", getattr(n.func, "id", "")), n.lineno)
            for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
            and getattr(n.func, "attr", getattr(n.func, "id", "")) in banned]
    assert hits == [], hits


def test_the_ui_renders_the_audit_verdict_and_never_calls_absence_a_pass():
    js = Path(r"d:\raits\global_index\dash\realtime\realtime.js").read_text(encoding="utf-8")
    assert "Audit verdict" in js
    assert "audit not run yet" in js
    # the tone is driven by the verdict, and a missing audit is never green
    assert "audDayVerdict === 'FAIL'" in js
