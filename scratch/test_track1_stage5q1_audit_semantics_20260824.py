"""Stage 5Q-1 — what a slot's ledger row MEANS, and where explanations actually live.

No scheduler started or stopped, no backend restarted, no IBKR connection, no order, no
confirmation file in the repo, no live state written. Every synthetic day is built under
`tmp_path`; the one test that exercises the real explanation writer points its `root` at
`tmp_path` too, so `global_index/track1_runtime/` is never written to.

The two things 5Q left open, and a third that only showed up when the code was RUN
------------------------------------------------------------------------------------
**Observed is not the same as decided.** The window ledger counts a slot toward coverage only
when it DECIDED. Measured by running `observe_live_slot` against a temp tree: a slot that
looked and found no candidate already records `decided=True`, so "no signal" was never the
problem. What is a problem is `gate_refused` on a CLOCK code — the sleeve's own decision band
was shut at that instant. For NKD that band is the Tokyo session, and once US DST ends the
late ET slots land after 15:55 JST and are refused by design. Those slots ran and looked.

**A legitimately quiet day must not fail for want of explanations.** The requirement is
derived from the ledger's own candidate counters, so a sleeve that saw nothing owes nothing —
and says so by name rather than passing on a missing file.

**Stage 5Q-2 note.** The truncation described below was fixed in 5Q-2: each live slot now
writes into `live_<date>/<sleeve>/<slot_id>/`, so no slot can erase another's rows, and the
freshness check became structural. The tests here still pin the 5Q-1 semantics they were
written for; the 5Q-2 suite pins the new layout.

**The gate was reading a path nothing writes.** Measured the same way: `emit_explanations`
resolves to `<shadow>/explanations/<window>/explanations_<day>.jsonl`, one directory deeper
than the gate looked, and `write_shadow` is its only caller in the repo. On the first real
shadow day both the `explanations` and the `freshness_proofs` checks would have failed a route
that wrote its explanations correctly.
"""
from __future__ import annotations

import json
import sys
import tempfile
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
LATE = f"{DAY}T23:00:00"
EARLY_START = f"{DAY}T00:05:00"

SLEEVES = sorted(WINDOWS_ET)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SWING_PROVIDER", "RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY",
              "RAITS_WINDOW_LEDGER_DIR", "RAITS_TELEMETRY_DIR"):
        monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# a day builder that can produce any slot outcome, not just the green one
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


def _slots(sleeve):
    return [s for s in ts.TRACK1_SLOTS if s.sleeve == sleeve]


#: The row a slot writes for each outcome. Every field here was MEASURED by running
#: `observe_live_slot` into a temp tree on 2026-08-24, not copied from a docstring — the
#: project has been caught twice believing a docstring over the branch that runs.
OUTCOMES = {
    "decided_with_candidates": dict(decided=True, reason="decided", detail=None,
                                    candidates=2, accepted=1, rejected=1, explained=2),
    "decided_no_candidate": dict(decided=True, reason="decided", detail=None,
                                 candidates=0, accepted=0, rejected=0, explained=0),
    "window_shut": dict(decided=False, reason="gate_refused", detail="too_late"),
    "window_shut_early": dict(decided=False, reason="gate_refused", detail="too_early"),
    "gate_stale": dict(decided=False, reason="gate_refused", detail="stale"),
    "gate_mixed": dict(decided=False, reason="gate_refused", detail="too_late,stale"),
    "gate_blank": dict(decided=False, reason="gate_refused", detail=None),
    "no_bar_provider": dict(decided=False, reason="no_bar_provider",
                            detail="no bar provider was handed to the slot"),
    "live_source_not_ready": dict(decided=False, reason="live_source_not_ready",
                                  detail="the rule for this sleeve is still in scratch"),
    "freshness_refused": dict(decided=False, reason="freshness_refused",
                              detail="the freshness gate refused, yet the engine admitted"),
}


def build_day(root: Path, *, day: str = DAY, outcome: str = "decided_no_candidate",
              per_sleeve: dict | None = None, runtime: float = 45.0,
              explanations: bool = False, checkpoint: bool = True) -> None:
    """One synthetic session day. `per_sleeve` overrides the outcome for named sleeves."""
    dayc = day.replace("-", "")
    per_sleeve = per_sleeve or {}
    ledger: list = []
    timing: list = []
    for sleeve in SLEEVES:
        kind = per_sleeve.get(sleeve, outcome)
        if kind == "unobserved":
            continue
        slots = _slots(sleeve)
        ledger.append({"event": "window_open", "sleeve": sleeve, "date": day,
                       "route": "track1_candidate", "expected_slots": len(slots)})
        decided = 0
        for i, s in enumerate(slots):
            row = {"event": "slot_observed", "sleeve": sleeve, "date": day,
                   "slot_id": s.id, "seq": i, "route": "track1_candidate"}
            row.update(OUTCOMES[kind])
            decided += 1 if row.get("decided") else 0
            ledger.append(row)
            timing.append({"ts": f"{day}T15:00:00+00:00", "route": "track1_candidate",
                           "slot_id": s.id, "outcome": "ok", "runtime_s": runtime,
                           "phases": {}})
        ledger.append({"event": "window_closed", "sleeve": sleeve, "date": day,
                       "outcome": "complete" if decided >= len(slots) else "incomplete",
                       "signal": "no_signal", "observed_slots": decided,
                       "expected_slots": len(slots), "route": "track1_candidate"})
    _write_jsonl(root / acc.COVERAGE_DIR / f"window_coverage_{dayc}.jsonl", ledger)
    _write_jsonl(root / acc.TIMING_DIR / f"slot_timing_{dayc}.jsonl", timing)

    if explanations:
        # The REAL nested layout the live writer produces, not the flat one the gate used to
        # look at. `live_<day>` is the window name `observe_live_slot` passes.
        rows = [explanation_row(sleeve, day, slot_id=f"TRACK1_{i}")
                for i, sleeve in enumerate(SLEEVES)]
        _write_jsonl(root / acc.SHADOW_DIR / "explanations" / f"live_{day}"
                     / f"explanations_{dayc}.jsonl", rows)

    if checkpoint:
        # Stage 5ZH: through `route_checkpoint.save_route`, and with the companion book.
        # The literal that stood here invented a flat payload the writer has never produced
        # and `route_checkpoint.load` rejects outright.
        from global_index import route_checkpoint as _rc
        _rc.save_route({}, route="track1_candidate", path=str(root / acc.CHECKPOINT_PATH))
        _bk = root / acc.CHECKPOINT_BOOK_PATH
        _bk.parent.mkdir(parents=True, exist_ok=True)
        _bk.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                                   "window": "live",
                                   "cut_instant": f"{day}T15:55:01-04:00",
                                   "cur_day": day, "positions": []}), encoding="utf-8")


def _sleeve(root, sleeve, *, now=LATE, started=EARLY_START, day=DAY):
    return acc.evaluate_sleeve(day, sleeve, root, now_et=now, scheduler_started_et=started)


def _ledger_path(root, day=DAY):
    return root / acc.COVERAGE_DIR / f"window_coverage_{day.replace('-', '')}.jsonl"


def _read_ledger(root, day=DAY):
    return [json.loads(l) for l in _ledger_path(root, day).read_text(encoding="utf-8")
            .splitlines() if l.strip()]


# ══════════════════════════════════════════════════════════════════════════════
# 1. the classification itself
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kind,expected", [
    ("decided_with_candidates", acc.SLOT_DECISION),
    ("decided_no_candidate", acc.SLOT_NO_ACTION),
    ("window_shut", acc.SLOT_WINDOW_SHUT),
    ("window_shut_early", acc.SLOT_WINDOW_SHUT),
    ("gate_stale", acc.SLOT_HARD_REFUSAL),
    ("gate_mixed", acc.SLOT_HARD_REFUSAL),
    ("gate_blank", acc.SLOT_HARD_REFUSAL),
    ("no_bar_provider", acc.SLOT_HARD_REFUSAL),
    ("live_source_not_ready", acc.SLOT_HARD_REFUSAL),
    ("freshness_refused", acc.SLOT_HARD_REFUSAL),
])
def test_each_row_shape_lands_in_its_class(kind, expected):
    row = {"event": "slot_observed", "slot_id": "TRACK1_CALM_1000"}
    row.update(OUTCOMES[kind])
    assert acc.classify_slot_row(row) == expected


def test_a_mixed_gate_refusal_is_hard_not_shut():
    """`too_late,stale` is a stale frame that ALSO happened to be late. Treating the clock
    code as licence to ignore the data code is how a real gap gets waved through."""
    assert acc.classify_slot_row(dict(OUTCOMES["gate_mixed"])) == acc.SLOT_HARD_REFUSAL


def test_an_unreadable_row_is_a_hard_refusal_not_an_observation():
    """Fails closed. A row this function cannot read is not evidence that somebody looked."""
    for junk in (None, "", 42, {}, {"decided": False, "reason": "gate_refused"}):
        assert acc.classify_slot_row(junk) == acc.SLOT_HARD_REFUSAL


def test_the_clock_codes_come_from_the_gate_module_not_from_a_local_copy():
    from global_index import track1_intraday as intra
    assert acc.clock_refusal_codes() == {intra.TOO_EARLY, intra.TOO_LATE}
    assert "stale" not in acc.clock_refusal_codes()


def test_the_observed_classes_are_exactly_the_three_that_prove_somebody_looked():
    assert acc.OBSERVED_CLASSES == {acc.SLOT_DECISION, acc.SLOT_NO_ACTION,
                                    acc.SLOT_WINDOW_SHUT}
    assert acc.SLOT_HARD_REFUSAL not in acc.OBSERVED_CLASSES
    assert acc.SLOT_UNOBSERVED not in acc.OBSERVED_CLASSES


# ══════════════════════════════════════════════════════════════════════════════
# 2. a window whose slots all ran — four ways
# ══════════════════════════════════════════════════════════════════════════════

def test_a_full_window_of_decisions_passes(tmp_path):
    build_day(tmp_path, outcome="decided_with_candidates", explanations=True)
    r = _sleeve(tmp_path, "roska4_stress")
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert r["observation"]["counts"][acc.SLOT_DECISION] == 24
    assert r["ledger_outcome"] == "complete"


def test_a_full_window_of_no_candidate_slots_passes_and_says_why(tmp_path):
    """The prompt's case 2: every slot ran, evaluated, and found nothing. Not a failure, and
    not a silent pass either — the reason is in the record by name."""
    build_day(tmp_path, outcome="decided_no_candidate")
    r = _sleeve(tmp_path, "roska4_swing")
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert acc.R_ALL_SLOTS_NO_ACTION in r["reasons"]
    assert acc.R_NO_CANDIDATES_TO_EXPLAIN in r["reasons"]
    assert r["observation"]["counts"][acc.SLOT_NO_ACTION] == 23
    assert r["observation"]["observed"] == r["observation"]["registered"]


def test_a_full_window_the_decision_band_was_shut_for_warns_and_does_not_fail(tmp_path):
    """The NKD-in-winter case. The ET slot grid is fixed and the Tokyo session is not, so
    after US DST ends the late slots fire outside the band the rule may decide in. They ran
    and they looked; the ledger will not count them, and the audit says both things."""
    build_day(tmp_path, outcome="window_shut")
    r = _sleeve(tmp_path, "global_nkd")
    assert r["verdict"] == acc.AUDIT_WARN, r["reasons"]
    assert acc.R_ALL_SLOTS_WINDOW_SHUT in r["reasons"]
    assert acc.R_COVERAGE_INCOMPLETE in r["reasons"]      # the committed rule, reported
    assert r["ledger_outcome"] == "incomplete"
    assert r["observation"]["observed"] == 22
    assert r["missing_slot_ids"] == []


@pytest.mark.parametrize("kind", ["no_bar_provider", "live_source_not_ready",
                                  "gate_stale", "freshness_refused"])
def test_a_window_that_could_not_evaluate_fails(tmp_path, kind):
    """The prompt's cases 3 and 4, and the classification decision written down.

    `freshness_refused` is a FAILURE, not a protective no-action. Measured at its raise site:
    it fires only when a binding mode caught the engine ADMITTING a candidate while the daily
    inputs were refused. That is the route about to act on data it does not trust — the
    loudest thing in the evidence, not a quiet skip.
    """
    build_day(tmp_path, outcome=kind)
    r = _sleeve(tmp_path, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL, r["reasons"]
    assert acc.R_HARD_REFUSAL in r["reasons"]
    assert r["observation"]["counts"][acc.SLOT_HARD_REFUSAL] == 1
    # and the reported "somebody looked" count does NOT include it. This is the number the
    # record means by observation, and a slot that could not evaluate did not observe.
    assert r["observation"]["observed"] == 0
    # The reason string the audit reports is the LEDGER's vocabulary, not this file's
    # fixture key: `gate_stale` here is written to the ledger as `gate_refused` with the
    # gate's own code in `detail`, and the audit surfaces both. Asserting the fixture key
    # would be asserting against my own naming.
    want = OUTCOMES[kind]["reason"]
    if want == "gate_refused":
        want += ":" + OUTCOMES[kind]["detail"]
    assert r["observation"]["hard_refusal_reasons"] == [want]


def test_one_hard_refusal_among_healthy_slots_still_fails(tmp_path):
    """Not a majority vote. One slot that could not evaluate is one slot of the window
    missing, and the sleeve's entry may have been in exactly that slot."""
    build_day(tmp_path, outcome="decided_no_candidate")
    rows = _read_ledger(tmp_path)
    for r in rows:
        if r.get("slot_id") == "TRACK1_STRESS_1100":
            r.update(OUTCOMES["no_bar_provider"])
            r.pop("candidates", None)
    _write_jsonl(_ledger_path(tmp_path), rows)
    v = _sleeve(tmp_path, "roska4_stress")
    assert v["verdict"] == acc.AUDIT_FAIL
    assert v["observation"]["hard_refusal_slot_ids"] == ["TRACK1_STRESS_1100"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. the checks a count cannot do
# ══════════════════════════════════════════════════════════════════════════════

def test_a_missing_slot_id_fails_even_though_a_duplicate_keeps_the_count(tmp_path):
    build_day(tmp_path, outcome="decided_no_candidate")
    rows = _read_ledger(tmp_path)
    ids = acc.sleeve_slot_ids("roska4_stress")
    victim, twin = ids[0], ids[-1]
    keep = [r for r in rows if r.get("slot_id") != victim]
    keep.append(dict(next(r for r in rows if r.get("slot_id") == twin)))
    _write_jsonl(_ledger_path(tmp_path), keep)

    r = _sleeve(tmp_path, "roska4_stress")
    assert len([x for x in keep if x.get("sleeve") == "roska4_stress"
                and x.get("event") == "slot_observed"]) == 24    # the count still says 24
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_MISSING_SLOT_IDS in r["reasons"]
    assert victim in r["missing_slot_ids"]
    assert acc.R_DUPLICATE_SLOT_IDS in r["reasons"]
    assert twin in r["observation"]["duplicate_slot_ids"]
    assert r["observation"]["observed"] == 23                     # never 24


def test_a_duplicate_alone_warns_rather_than_failing(tmp_path):
    """A doubled row with nothing missing is odd, not a gap. Naming it is what stops it from
    ever being read as filling one."""
    build_day(tmp_path, outcome="decided_no_candidate")
    rows = _read_ledger(tmp_path)
    twin = acc.sleeve_slot_ids("roska4_calm")[0]
    rows.append(dict(next(r for r in rows if r.get("slot_id") == twin)))
    _write_jsonl(_ledger_path(tmp_path), rows)
    r = _sleeve(tmp_path, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_WARN
    assert acc.R_DUPLICATE_SLOT_IDS in r["reasons"]
    assert r["missing_slot_ids"] == []


def test_a_row_for_a_slot_this_sleeve_does_not_register_is_named(tmp_path):
    build_day(tmp_path, outcome="decided_no_candidate")
    rows = _read_ledger(tmp_path)
    # A SLOT_OBSERVED row, not the window_open one: the first roska4_calm record in the file
    # is `window_open`, and giving that a slot_id produces a row the reader correctly ignores
    # — a test that passes by exercising nothing.
    stray = dict(next(r for r in rows if r.get("sleeve") == "roska4_calm"
                      and r.get("event") == "slot_observed"))
    stray["slot_id"] = "TRACK1_CALM_9999"
    rows.append(stray)
    _write_jsonl(_ledger_path(tmp_path), rows)
    r = _sleeve(tmp_path, "roska4_calm")
    assert acc.R_UNREGISTERED_SLOT_IDS in r["reasons"]
    assert r["observation"]["unregistered_slot_ids"] == ["TRACK1_CALM_9999"]


# ══════════════════════════════════════════════════════════════════════════════
# 4. ledger and timing must account for each other, both directions
# ══════════════════════════════════════════════════════════════════════════════

def test_a_slot_with_a_ledger_row_and_no_timing_fails(tmp_path):
    """It ran without being measured. The p95 gate is the only thing standing between the
    route and slots that overrun their cadence, and it cannot judge a slot it never saw."""
    build_day(tmp_path, outcome="decided_no_candidate")
    p = tmp_path / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    victim = acc.sleeve_slot_ids("roska4_swing")[3]
    _write_jsonl(p, [r for r in rows if r["slot_id"] != victim])
    r = _sleeve(tmp_path, "roska4_swing")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_SLOT_WITHOUT_TIMING in r["reasons"]
    assert r["slots_without_timing"] == [victim]


def test_a_slot_with_timing_and_no_ledger_row_fails(tmp_path):
    """The crash shape, and the mutex-skip shape.

    Telemetry registers an atexit net, so a slot that started and died still leaves a timing
    record; the scheduler writes one itself when it skips a slot because the previous Track 1
    child was still in flight. Neither is an observation, and the missing ledger row is the
    only thing that says so.
    """
    build_day(tmp_path, outcome="decided_no_candidate")
    rows = _read_ledger(tmp_path)
    victim = acc.sleeve_slot_ids("roska4_swing")[5]
    _write_jsonl(_ledger_path(tmp_path), [r for r in rows if r.get("slot_id") != victim])
    r = _sleeve(tmp_path, "roska4_swing")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_TIMING_WITHOUT_LEDGER_ROW in r["reasons"]
    assert acc.R_MISSING_SLOT_IDS in r["reasons"]
    assert r["timing_without_ledger_row"] == [victim]


# ══════════════════════════════════════════════════════════════════════════════
# 5. explanations — where they live, and when they are owed
# ══════════════════════════════════════════════════════════════════════════════

def test_the_gate_finds_rows_written_by_the_REAL_writer(tmp_path):
    """The format-drift guard, and the test that would have caught this on day one.

    It does not hand-write a fixture in the layout the reader expects — that is a fixture
    agreeing with itself. It drives `run_live_day_track1.emit_explanations`, the only producer
    of explanation rows in the repo, and requires the acceptance gate's reader to find what it
    wrote. Before 5Q-1 the gate found ZERO: the writer nests under the window name and the
    gate globbed one directory too shallow.
    """
    from global_index import run_live_day_track1 as R
    from global_index import track1_params as tp
    import pandas as pd

    out = R.emit_explanations(
        [], out_dir=R.OPERATIONAL_SHADOW_DIR, root=str(tmp_path), window=f"live_{DAY}",
        regime_csv="spy_daily_live.csv", data_paths=R.default_data_paths(),
        fill_law=tp.LIVE_FILL_LAW, freshness_allow=True, mode="shadow_live",
        as_of=pd.Timestamp(f"{DAY} 10:00"), context_sleeve="roska4_calm")
    assert out["rows_written"] == 1

    files = acc.explanation_files(tmp_path, DAYC)
    assert files, "the acceptance gate cannot see what the real writer just wrote"
    rows = acc._explanation_rows(tmp_path, DAYC)
    assert len(rows) == 1
    assert rows[0]["route"] == "track1_candidate"


def test_the_writer_path_is_nested_and_the_flat_one_has_no_producer(tmp_path):
    """States the measurement rather than only relying on it.

    A row written at the flat path is still read — dropping that would be the same
    brittleness pointing the other way — but nothing in the repo writes there.
    """
    flat = tmp_path / acc.SHADOW_DIR / "explanations" / f"explanations_{DAYC}.jsonl"
    _write_jsonl(flat, [explanation_row("roska4_calm", DAY)])
    assert len(acc._explanation_rows(tmp_path, DAYC)) == 1

    src = Path(REPO, "global_index", "run_live_day_track1.py").read_text(encoding="utf-8")
    assert "write_shadow(" in src            # the only caller of the explanation path
    assert 'f"{out_dir}/{EXPLAIN_SUBDIR}/{window}"' in src


def test_the_dashboard_reader_and_the_gate_agree_on_where_rows_live(tmp_path):
    """Two readers guessing at a layout independently is how they came to disagree with the
    writer. They now share one resolver, and this asserts the counts match."""
    build_day(tmp_path, outcome="decided_no_candidate", explanations=True)
    gate_rows = acc._explanation_rows(tmp_path, DAYC)
    seen = trr.read_track1_runtime(tmp_path)["explanations"]
    assert seen["present"] is True
    assert seen["days"][DAYC] == len(gate_rows) == len(SLEEVES)


def test_a_sleeve_that_saw_candidates_and_left_no_row_anywhere_fails(tmp_path):
    build_day(tmp_path, outcome="decided_with_candidates", explanations=False)
    r = _sleeve(tmp_path, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_EXPLANATIONS_MISSING in r["reasons"]
    assert r["explanations"]["expected_from_ledger"] == 1


def test_a_sleeve_whose_rows_a_later_sleeve_overwrote_is_named_not_failed(tmp_path):
    """The writer defect, surfaced by name instead of charged to the sleeve.

    **Stage 5Q-2 fixed the writer** — each live slot now owns its own file, so this shape is
    no longer produced. The branch stays and this test stays with it, for two reasons: rows
    written in the old layout before the fix are still readable evidence, and a rule that can
    no longer be observed refusing is a rule nobody can trust. What is asserted here is the
    handling, not the defect's continued existence.
    """
    build_day(tmp_path, outcome="decided_with_candidates", explanations=False)
    _write_jsonl(tmp_path / acc.SHADOW_DIR / "explanations" / f"live_{DAY}"
                 / f"explanations_{DAYC}.jsonl",
                 [explanation_row("roska4_swing", DAY)])
    r = _sleeve(tmp_path, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert acc.R_EXPLANATIONS_OVERWRITTEN in r["reasons"]
    assert acc.R_EXPLANATIONS_MISSING not in r["reasons"]
    # and it does NOT pass silently: the record carries the named not-checked note
    assert [n["name"] for n in r["notes"]] == ["explanations_attribution"]
    assert r["notes"][0]["status"] == acc.NOT_CHECKED


def test_a_row_without_a_freshness_reference_still_fails(tmp_path):
    build_day(tmp_path, outcome="decided_with_candidates", explanations=False)
    _write_jsonl(tmp_path / acc.SHADOW_DIR / "explanations" / f"live_{DAY}"
                 / f"explanations_{DAYC}.jsonl",
                 [explanation_row("roska4_calm", DAY, structured=False)])
    r = _sleeve(tmp_path, "roska4_calm")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_MISSING_FRESHNESS_PROOF in r["reasons"]


# ══════════════════════════════════════════════════════════════════════════════
# 6. the day roll-up
# ══════════════════════════════════════════════════════════════════════════════

def test_a_day_on_which_every_sleeve_found_nothing_is_not_a_failure(tmp_path):
    """The prompt's case 10, and the second thing 5Q left open.

    The committed daily gate requires explanation rows for the DAY, so it refuses this day.
    That verdict is reported verbatim and by name — it is not softened and it is not what the
    audit's operational roll-up returns.
    """
    build_day(tmp_path, outcome="decided_no_candidate", explanations=False)
    r = acc.evaluate_day_audit(DAY, tmp_path, now_et=LATE, scheduler_started_et=EARLY_START)
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert acc.R_NO_CANDIDATES_TO_EXPLAIN in r["reasons"]
    assert acc.R_ACCEPTANCE_GATE_REFUSED in r["reasons"]
    assert r["acceptance_gate"]["accepted"] is False
    assert "explanations" in r["acceptance_gate"]["failed"]
    assert all(v["verdict"] == acc.AUDIT_PASS for v in r["sleeves"].values())


def test_one_unobserved_sleeve_fails_the_day_even_when_the_rest_were_quiet(tmp_path):
    """The prompt's case 11. A quiet day and a day with a hole must not look the same."""
    build_day(tmp_path, outcome="decided_no_candidate",
              per_sleeve={"global_nkd": "unobserved"})
    r = acc.evaluate_day_audit(DAY, tmp_path, now_et=LATE, scheduler_started_et=EARLY_START)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert r["sleeves"]["global_nkd"]["verdict"] == acc.AUDIT_FAIL
    assert acc.R_COVERAGE_UNOBSERVED in r["sleeves"]["global_nkd"]["reasons"]
    assert all(r["sleeves"][s]["verdict"] == acc.AUDIT_PASS
               for s in SLEEVES if s != "global_nkd")


def test_a_warning_sleeve_does_not_hide_a_failing_one(tmp_path):
    build_day(tmp_path, outcome="decided_no_candidate",
              per_sleeve={"global_nkd": "window_shut", "roska4_calm": "no_bar_provider"})
    r = acc.evaluate_day_audit(DAY, tmp_path, now_et=LATE, scheduler_started_et=EARLY_START)
    assert r["sleeves"]["global_nkd"]["verdict"] == acc.AUDIT_WARN
    assert r["sleeves"]["roska4_calm"]["verdict"] == acc.AUDIT_FAIL
    assert r["verdict"] == acc.AUDIT_FAIL


def test_the_day_record_carries_the_observation_counts_per_sleeve(tmp_path):
    build_day(tmp_path, outcome="window_shut")
    r = acc.evaluate_day_audit(DAY, tmp_path, now_et=LATE, scheduler_started_et=EARLY_START)
    for s in SLEEVES:
        entry = r["sleeves"][s]
        assert entry["observation"]["counts"][acc.SLOT_WINDOW_SHUT] == entry["expected_slots"]
        assert entry["ledger_outcome"] == "incomplete"


# ══════════════════════════════════════════════════════════════════════════════
# 7. the audit runner and the dashboard carry the new vocabulary through
# ══════════════════════════════════════════════════════════════════════════════

def test_the_written_record_carries_the_observation_block_and_reason_codes(tmp_path):
    build_day(tmp_path, outcome="window_shut")
    rc = aud.main(["--root", str(tmp_path), "--date", DAY, "--all",
                   "--scheduler-started", EARLY_START, "--now", LATE])
    assert rc == 0
    recs = aud.read_records(DAY, tmp_path)
    sleeve_recs = [r for r in recs if r["scope"] == "sleeve"]
    assert sleeve_recs and all(r["route"] == "track1_candidate" for r in recs)
    for r in sleeve_recs:
        assert r["verdict"] == acc.AUDIT_WARN
        assert acc.R_ALL_SLOTS_WINDOW_SHUT in r["reasons"]
        assert r["observation"]["counts"][acc.SLOT_WINDOW_SHUT] == r["expected_slots"]
        assert r["ledger_outcome"] == "incomplete"


def test_the_audit_runner_still_owns_no_rule(tmp_path):
    """Orchestration only. Every threshold and every class name lives in the acceptance
    module; the runner may not carry a second copy."""
    src = Path(aud.__file__).read_text(encoding="utf-8")
    for owned in ("observed_no_action", "observed_window_shut", "too_late", "gate_refused",
                  "RUNTIME_P95", "300", "240"):
        assert owned not in src, owned


def test_the_dashboard_surfaces_the_reason_codes_not_just_the_verdict(tmp_path):
    build_day(tmp_path, outcome="window_shut")
    aud.main(["--root", str(tmp_path), "--date", DAY, "--all",
              "--scheduler-started", EARLY_START, "--now", LATE])
    a = trr.read_track1_runtime(tmp_path)["audits"]
    assert a["latest_day"] == DAY
    assert a["latest"]["day"]["verdict"] == acc.AUDIT_WARN
    for s in SLEEVES:
        assert acc.R_ALL_SLOTS_WINDOW_SHUT in a["latest"]["sleeves"][s]["reasons"]
    assert a["not_audited_yet"] == []


def test_an_absent_audit_is_still_not_a_pass(tmp_path):
    build_day(tmp_path, outcome="decided_no_candidate")
    a = trr.read_track1_runtime(tmp_path)["audits"]
    assert a["present"] is False
    assert "not judged yet" in a["reading"]


def test_the_ui_renders_reason_codes_beside_the_verdict():
    js = Path(REPO, "global_index", "dash", "realtime", "realtime.js").read_text(
        encoding="utf-8")
    assert "Audit verdict" in js
    assert "audit not run yet" in js
    assert "auditReasons" in js, "the panel shows a verdict with no reason behind it"
