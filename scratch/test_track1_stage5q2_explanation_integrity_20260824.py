"""Stage 5Q-2 — the live explanation evidence: durable, attributable, structurally proved.

No scheduler started or stopped, no backend restarted, no IBKR connection, no order, no
confirmation file. Every write in this suite goes through `root=tmp_path`, and one test
asserts the real `global_index/track1_runtime/shadow` tree is untouched by the whole run.

The two defects this closes, both measured by RUNNING the writer rather than reading it
-----------------------------------------------------------------------------------------
**One file per session date, opened `mode="w"` by every slot.** All four sleeves shared it, so
Calm's 10:00 rows were erased by Stress at 10:35 and no reader could tell that apart from a
Calm slot that explained nothing. Truncation was never the bug — it is what stops a re-run of
one slot doubling its own rows. A shared path was. Each slot now owns a file:

    <shadow>/explanations/live_<YYYY-MM-DD>/<sleeve>/<slot_id>/explanations_<YYYYMMDD>.jsonl

**The freshness "proof" was `"freshness" in json.dumps(row).lower()`.** A row whose only
mention was a sentence passed. The structured rule is derived from the tables the records are
built from: a row owes a `freshness_allow` FEATURE exactly when a cited rule declares one, an
accepted admission in a binding mode must cite the gate that governed it, and every DECISION
row must carry the run's freshness verdict as a typed field.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

REPO = Path(r"d:\raits")

import pandas as pd                                        # noqa: E402

from global_index import run_live_day_track1 as R          # noqa: E402
from global_index import track1_explain as tx              # noqa: E402
from global_index import track1_params as tp               # noqa: E402
from global_index import track1_shadow_acceptance as acc   # noqa: E402
from monitor.backend import track1_runtime_reader as trr   # noqa: E402

DAY = "2026-08-25"
DAYC = DAY.replace("-", "")

#: The real live tree. Nothing in this suite may touch it.
REAL_TREE = REPO / "global_index" / "track1_runtime" / "shadow"

#: When this module was imported, i.e. before any test in it ran. See the real-tree test.
_IMPORTED_AT = __import__("time").time()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_WINDOW_LEDGER_DIR", "RAITS_TELEMETRY_DIR", "RAITS_TRACK1_ONLY",
              "RAITS_TRACK1_SHADOW"):
        monkeypatch.delenv(k, raising=False)


def write_slot(root: Path, sleeve: str, slot_id: str, *, day: str = DAY,
               decisions=(), freshness: bool = True) -> dict:
    """One slot's explanation write, through the REAL writer at its real call shape."""
    return R.emit_explanations(
        list(decisions), out_dir=R.OPERATIONAL_SHADOW_DIR, root=str(root),
        window=tx.live_window(day, sleeve, slot_id), slot_id=slot_id,
        regime_csv="spy_daily_live.csv", data_paths=R.default_data_paths(),
        fill_law=tp.LIVE_FILL_LAW, freshness_allow=freshness, mode=tx.SHADOW_LIVE,
        as_of=pd.Timestamp(f"{day} 10:00"), context_sleeve=sleeve)


def rows_on_disk(root: Path, day: str = DAY) -> list:
    return acc._explanation_rows(root, day.replace("-", ""))


def files_on_disk(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("explanations_*.jsonl"))


# ══════════════════════════════════════════════════════════════════════════════
# 1. no slot may erase another slot's rows
# ══════════════════════════════════════════════════════════════════════════════

def test_two_sleeves_on_one_day_both_survive(tmp_path):
    """Calm at 10:00 then Stress at 10:35 — the exact pair that used to lose Calm."""
    write_slot(tmp_path, "roska4_calm", "TRACK1_CALM_1000")
    after_first = rows_on_disk(tmp_path)
    assert len(after_first) == 1

    write_slot(tmp_path, "roska4_stress", "TRACK1_STRESS_1035")
    rows = rows_on_disk(tmp_path)
    assert len(rows) == 2, "the second slot erased the first"
    assert sorted(r["sleeve"] for r in rows) == ["roska4_calm", "roska4_stress"]


def test_two_slots_of_one_sleeve_both_survive(tmp_path):
    for slot in ("TRACK1_STRESS_1035", "TRACK1_STRESS_1040", "TRACK1_STRESS_1045"):
        write_slot(tmp_path, "roska4_stress", slot)
    rows = rows_on_disk(tmp_path)
    assert len(rows) == 3
    assert sorted(r["inputs_summary"]["slot_id"] for r in rows) == [
        "TRACK1_STRESS_1035", "TRACK1_STRESS_1040", "TRACK1_STRESS_1045"]


def test_a_whole_day_of_slots_accumulates(tmp_path):
    """Every registered slot of every sleeve writes; the day ends with one file each."""
    from global_index import track1_slots as ts
    for s in ts.TRACK1_SLOTS:
        write_slot(tmp_path, s.sleeve, s.id)
    rows = rows_on_disk(tmp_path)
    assert len(rows) == len(ts.TRACK1_SLOTS) == 70
    assert len(files_on_disk(tmp_path)) == 70


def test_rerunning_one_slot_replaces_only_its_own_rows(tmp_path):
    """The documented re-run semantic, and why truncation was kept.

    A slot may be re-run — the scheduler's misfire grace allows it, and an operator may run
    one by hand. Appending would leave the day holding two records for one slot with no way
    to tell which one the slot stands by; truncating its OWN file leaves exactly one, which is
    what the decision file beside it does for the same reason. What changed in 5Q-2 is the
    SCOPE of the truncation, never that it happens.
    """
    write_slot(tmp_path, "roska4_calm", "TRACK1_CALM_1000")
    write_slot(tmp_path, "roska4_stress", "TRACK1_STRESS_1035")
    first = rows_on_disk(tmp_path)

    write_slot(tmp_path, "roska4_calm", "TRACK1_CALM_1000")     # the same slot again
    again = rows_on_disk(tmp_path)
    assert len(again) == len(first) == 2, "a re-run doubled the day's evidence"
    assert sum(1 for r in again if r["sleeve"] == "roska4_calm") == 1
    assert sum(1 for r in again if r["sleeve"] == "roska4_stress") == 1


def test_a_slot_cannot_write_outside_its_own_directory(tmp_path):
    """The layout builder refuses a name that would escape rather than sanitising it."""
    for bad in ("../evil", "a/b", ".."):
        with pytest.raises(ValueError):
            tx.live_window(DAY, bad, "TRACK1_X")
        with pytest.raises(ValueError):
            tx.live_window(DAY, "roska4_calm", bad)


# ══════════════════════════════════════════════════════════════════════════════
# 1b. the CALL SITE, not just the writer
# ══════════════════════════════════════════════════════════════════════════════

class _Frame:
    frame = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0],
                          "volume": [1]},
                         index=pd.DatetimeIndex([pd.Timestamp(f"{DAY} 10:00")]))


class _NoCandidates:
    def candidates(self, now):
        return []


@pytest.fixture
def live_slot(tmp_path, monkeypatch):
    """Drive the REAL `observe_live_slot` with the gate and the bar source stubbed.

    The stubs are the two things that need a broker; everything downstream of them — the
    window sub-path, the writer, the ledger row — is the production path. Testing
    `emit_explanations` alone would have left the call site unguarded, and the call site is
    where the shared-path defect actually lived: the S1 mutation edits `observe_live_slot`
    and the writer-level tests could not see it.
    """
    import global_index.window_ledger as wl
    from global_index import track1_intraday as intra
    from global_index import track1_live_source as src

    ledger_dir = tmp_path / acc.COVERAGE_DIR
    ledger_dir.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(ledger_dir))
    monkeypatch.setenv("RAITS_ROUTE", "track1_candidate")
    monkeypatch.setattr(wl, "_disabled", False, raising=False)
    monkeypatch.setattr(src, "sleeve_frames",
                        lambda **kw: {kw["sleeves"][0]: {"MES": _Frame()}})
    # Stage 5ZX gave `_resample` the requirement the caller already resolved, so a phased slot
    # is resampled at the size its PHASE declares rather than its sleeve's. The stub takes it
    # and ignores it, which is what it did with the sleeve.
    monkeypatch.setattr(R, "_resample", lambda f, s, requirement=None: f)
    monkeypatch.setattr(intra, "validate",
                        lambda sleeve, bars, **kw: intra.Verdict(sleeve, True, (), ()))

    def run(sleeve, slot_id):
        return R.observe_live_slot(
            sleeve, slot_id, now_et=pd.Timestamp(f"{DAY} 10:00"), provider=object(),
            live_source=_NoCandidates(), root=str(tmp_path),
            out_dir=R.OPERATIONAL_SHADOW_DIR)

    return run


def test_the_real_slot_path_gives_each_slot_its_own_file(tmp_path, live_slot):
    """Calm at 10:00 then Stress at 10:35, through `observe_live_slot` itself."""
    live_slot("roska4_calm", "TRACK1_CALM_1000")
    assert len(rows_on_disk(tmp_path)) == 1

    live_slot("roska4_stress", "TRACK1_STRESS_1035")
    rows = rows_on_disk(tmp_path)
    assert len(rows) == 2, "the second slot erased the first through the production path"
    assert sorted(r["sleeve"] for r in rows) == ["roska4_calm", "roska4_stress"]
    assert sorted(r["inputs_summary"]["slot_id"] for r in rows) == [
        "TRACK1_CALM_1000", "TRACK1_STRESS_1035"]
    files = acc.explanation_files(tmp_path, DAYC)
    assert len(files) == 2
    assert {acc.explanation_attribution(f, tmp_path)["sleeve"] for f in files} == {
        "roska4_calm", "roska4_stress"}


def test_the_real_slot_path_keeps_every_slot_of_one_sleeve(tmp_path, live_slot):
    for slot in ("TRACK1_STRESS_1035", "TRACK1_STRESS_1040", "TRACK1_STRESS_1045"):
        live_slot("roska4_stress", slot)
    assert len(rows_on_disk(tmp_path)) == 3


# ══════════════════════════════════════════════════════════════════════════════
# 2. attribution
# ══════════════════════════════════════════════════════════════════════════════

def test_the_path_names_the_day_the_sleeve_and_the_slot(tmp_path):
    write_slot(tmp_path, "roska4_swing", "TRACK1_SWING_1405")
    f = acc.explanation_files(tmp_path, DAYC)[0]
    assert f.as_posix().endswith(
        f"shadow/explanations/live_{DAY}/roska4_swing/TRACK1_SWING_1405/"
        f"explanations_{DAYC}.jsonl")
    a = acc.explanation_attribution(f, tmp_path)
    assert a == {"session_date": DAY, "sleeve": "roska4_swing",
                 "slot_id": "TRACK1_SWING_1405", "shape": "live_sleeve_slot"}


def test_the_row_carries_the_slot_id_as_well_as_the_path(tmp_path):
    """A row read out of its directory — pasted into a ticket, copied into a report — keeps
    its provenance only if it carries it."""
    write_slot(tmp_path, "global_nkd", "TRACK1_NKD_0110")
    row = rows_on_disk(tmp_path)[0]
    assert row["inputs_summary"]["slot_id"] == "TRACK1_NKD_0110"
    assert row["sleeve"] == "global_nkd"
    assert row["session_date"] == DAY
    assert row["route"] == "track1_candidate"


def test_two_slots_produce_two_distinct_explain_ids(tmp_path):
    """Before 5Q-2 every context record of a day carried candidate_id `run:live_<date>` — the
    same id for all seventy slots. Distinct windows make distinct ids, which is what lets two
    records be told apart at all."""
    write_slot(tmp_path, "roska4_stress", "TRACK1_STRESS_1035")
    write_slot(tmp_path, "roska4_stress", "TRACK1_STRESS_1040")
    ids = {r["explain_id"] for r in rows_on_disk(tmp_path)}
    assert len(ids) == 2


def test_an_unrecognised_path_shape_is_None_not_a_guess(tmp_path):
    a = acc.explanation_attribution(tmp_path / "somewhere" / "else.jsonl", tmp_path)
    assert a["sleeve"] is None and a["slot_id"] is None and a["shape"] == "outside"


# ══════════════════════════════════════════════════════════════════════════════
# 3. the readers find it
# ══════════════════════════════════════════════════════════════════════════════

def test_the_gate_and_the_dashboard_find_the_same_rows(tmp_path):
    for sleeve, slot in (("roska4_calm", "TRACK1_CALM_1000"),
                         ("roska4_stress", "TRACK1_STRESS_1035"),
                         ("roska4_stress", "TRACK1_STRESS_1040")):
        write_slot(tmp_path, sleeve, slot)
    gate = rows_on_disk(tmp_path)
    seen = trr.read_track1_runtime(tmp_path)["explanations"]
    assert seen["present"] is True
    assert seen["days"][DAYC] == len(gate) == 3
    attrib = seen["attribution"][DAYC]
    assert attrib["files"] == 3
    assert attrib["sleeves"] == ["roska4_calm", "roska4_stress"]
    assert attrib["slots"] == 3
    assert attrib["shapes"] == ["live_sleeve_slot"]


def test_the_reader_still_finds_rows_written_in_the_older_shapes(tmp_path):
    """Rows already on disk in the 5Q layout are evidence, not litter. A reader that only
    accepts today's shape is the same brittleness that made the gate read a path nothing
    wrote to, pointing the other way."""
    d = tmp_path / acc.SHADOW_DIR / "explanations"
    for rel in (f"explanations_{DAYC}.jsonl",                       # flat
                f"live_{DAY}/explanations_{DAYC}.jsonl"):           # the 5Q layout
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(_context_row("roska4_calm")) + "\n", encoding="utf-8")
    write_slot(tmp_path, "roska4_stress", "TRACK1_STRESS_1035")     # and the 5Q-2 layout
    assert len(rows_on_disk(tmp_path)) == 3


def test_the_dashboard_reader_does_not_import_the_writer():
    """The boundary, held at the source. The dashboard reads evidence and verdicts; a panel
    that imported the writer would be one edit away from being able to produce them."""
    src = Path(trr.__file__).read_text(encoding="utf-8")
    assert "track1_explain" not in src
    assert "explanation_attribution" in src


# ══════════════════════════════════════════════════════════════════════════════
# 4. the freshness proof, structurally
# ══════════════════════════════════════════════════════════════════════════════

def _record(**kw):
    base = dict(route="track1_candidate", session_date=DAY, sleeve="roska4_calm",
                instrument="MES", candidate_id="c1",
                decision_time=pd.Timestamp(f"{DAY} 10:00"),
                data_time=pd.Timestamp(f"{DAY} 10:00"), decision_mode=tx.SHADOW_LIVE,
                thresholds={}, outputs={}, identity=tx.Identity(route="track1_candidate"))
    base.update(kw)
    return tx.decision_record(**base)


def _context_row(sleeve="roska4_calm", freshness=True):
    return tx.no_action_record(
        route="track1_candidate", session_date=DAY, sleeve=sleeve,
        instrument=tx.SLEEVE_INSTRUMENTS[sleeve][0], candidate_id="run:x",
        decision_time=f"{DAY}T10:00:00", decision_mode=tx.SHADOW_LIVE,
        reason_code=(tx.NONE if freshness else tx.FRESHNESS_FAIL),
        rule_ids=[tx.FRESHNESS_CONTEXT_RULE],
        features=[tx.Feature("freshness_allow", bool(freshness), True, "==",
                             passed=bool(freshness))],
        inputs_summary={"freshness_allow": bool(freshness)}, outputs={},
        identity=tx.Identity(route="track1_candidate"))


def test_a_rejected_decision_owes_the_run_observation_and_not_a_gate_proof(tmp_path):
    """A cap refusal never reached the freshness gate. Asking it to prove one would be asking
    it to invent a proof; asking it for the RUN's verdict is asking for something the writer
    already records."""
    rej = _record(status=tx.REJECTED, reason_code="reject_cap",
                  rule_ids=["GATE.CAP_CLUSTER"],
                  features=[tx.Feature("cluster_gross_after", None, 1.0, "<=", passed=False)],
                  inputs_summary={"freshness_allow": False})
    assert tx.check_freshness_proof(rej) == []
    p = tx.freshness_proof(rej)
    assert p["owed"] is False and p["observed"] is False and p["observed_is_bool"] is True


def test_a_row_whose_only_freshness_is_prose_fails(tmp_path):
    """The whole point. The check this replaces passed exactly this row."""
    prose = _record(status=tx.REJECTED, reason_code="reject_cap",
                    rule_ids=["GATE.CAP_CLUSTER"],
                    features=[tx.Feature("cluster_gross_after", None, 1.0, "<=",
                                         passed=False)],
                    inputs_summary={"note": "the freshness of the frame was fine"})
    errs = tx.check_freshness_proof(prose)
    assert errs and "prose" in errs[0]
    assert "freshness" in json.dumps(prose, default=str).lower()   # the substring is there


def test_an_accepted_binding_decision_must_cite_the_gate_and_carry_the_feature():
    ok = _record(status=tx.ACCEPTED, reason_code="take",
                 rule_ids=list(tx.ACCEPTED_PROOF_RULES_BY_MODE[tx.SHADOW_LIVE]),
                 features=[tx.Feature("freshness_allow", True, True, "==", passed=True)],
                 inputs_summary={"freshness_allow": True})
    assert tx.check_freshness_proof(ok) == []

    no_cite = _record(status=tx.ACCEPTED, reason_code="take",
                      rule_ids=["GATE.CAP_CLUSTER", "GATE.BREAKER"], features=[],
                      inputs_summary={"freshness_allow": True})
    errs = tx.check_freshness_proof(no_cite)
    assert any("does not cite" in e for e in errs)
    assert any("carries none" in e for e in errs)


def test_an_accepted_replay_decision_owes_no_gate_proof():
    """The Stage 5Z finding, kept: `fresh.evaluate` reads TODAY's inputs and did not govern an
    admission taken months ago. A proof that moves while the decision does not is not a proof
    of that decision."""
    rec = _record(status=tx.ACCEPTED, reason_code="take", decision_mode=tx.REPLAY,
                  rule_ids=list(tx.ACCEPTED_PROOF_RULES_BY_MODE[tx.REPLAY]),
                  features=[], inputs_summary={"freshness_allow": True})
    assert tx.freshness_proof(rec)["owed"] is False
    assert tx.check_freshness_proof(rec) == []


def test_the_context_record_the_writer_emits_carries_a_structured_proof(tmp_path):
    """Not a hand-built row: the one `emit_explanations` actually writes."""
    write_slot(tmp_path, "roska4_calm", "TRACK1_CALM_1000", freshness=True)
    row = rows_on_disk(tmp_path)[0]
    assert tx.check_freshness_proof(row) == []
    p = tx.freshness_proof(row)
    assert p["owed"] is True and p["present"] is True
    assert p["value"] is True and p["passed"] is True
    assert tx.freshness_context_records([row]) == [row]


def test_a_refused_freshness_run_is_recorded_as_such_not_hidden(tmp_path):
    write_slot(tmp_path, "roska4_calm", "TRACK1_CALM_1000", freshness=False)
    row = rows_on_disk(tmp_path)[0]
    p = tx.freshness_proof(row)
    assert p["present"] is True and p["value"] is False and p["passed"] is False
    assert row["reason_code"] == tx.FRESHNESS_FAIL
    # a NO_ACTION context record is not an admission, so a failed gate is a fact, not an error
    assert tx.check_freshness_proof(row) == []


def test_an_unreadable_row_cannot_pass_the_check():
    """Fails closed. A row with no `record_type` owes nothing by the rules and would sail
    through — which is how a malformed line becomes a passing check."""
    for junk in ({}, {"sleeve": "roska4_calm"}, {"record_type": "NOPE"}):
        assert tx.check_freshness_proof(junk)


def test_the_check_is_not_a_substring_test_at_the_source_level():
    """Parsed, not grepped: the acceptance gate must not go back to matching free text."""
    src = Path(acc.__file__).read_text(encoding="utf-8")
    body = src[src.index("def evaluate_sleeve("):src.index("def evaluate_day_audit(")]
    assert 'json.dumps(r' not in body.replace("json.dumps(rec", "")
    assert "check_freshness_proof" in body


# ══════════════════════════════════════════════════════════════════════════════
# 5. the audit end to end, on rows the writer produced
# ══════════════════════════════════════════════════════════════════════════════

def _ledger_and_timing(root: Path, sleeve: str, *, candidates: int, day: str = DAY):
    from global_index import track1_slots as ts
    slots = [s for s in ts.TRACK1_SLOTS if s.sleeve == sleeve]
    dayc = day.replace("-", "")
    led, tim = [], []
    led.append({"event": "window_open", "sleeve": sleeve, "date": day,
                "route": "track1_candidate", "expected_slots": len(slots)})
    for i, s in enumerate(slots):
        led.append({"event": "slot_observed", "sleeve": sleeve, "date": day,
                    "slot_id": s.id, "seq": i, "decided": True, "reason": "decided",
                    "candidates": candidates, "accepted": 0, "rejected": candidates,
                    "explained": candidates, "route": "track1_candidate"})
        tim.append({"ts": f"{day}T15:00:00+00:00", "route": "track1_candidate",
                    "slot_id": s.id, "outcome": "ok", "runtime_s": 45.0, "phases": {}})
    led.append({"event": "window_closed", "sleeve": sleeve, "date": day,
                "outcome": "complete", "signal": "no_signal",
                "observed_slots": len(slots), "expected_slots": len(slots),
                "route": "track1_candidate"})
    for rel, rows in ((acc.COVERAGE_DIR + f"/window_coverage_{dayc}.jsonl", led),
                      (acc.TIMING_DIR + f"/slot_timing_{dayc}.jsonl", tim)):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
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


def test_a_sleeve_whose_slots_all_wrote_their_own_rows_passes(tmp_path):
    from global_index import track1_slots as ts
    _ledger_and_timing(tmp_path, "roska4_stress", candidates=1)
    for s in ts.TRACK1_SLOTS:
        if s.sleeve == "roska4_stress":
            write_slot(tmp_path, s.sleeve, s.id)
    r = acc.evaluate_sleeve(DAY, "roska4_stress", tmp_path, now_et=f"{DAY}T23:00:00",
                            scheduler_started_et=f"{DAY}T00:05:00")
    assert r["verdict"] == acc.AUDIT_PASS, r["reasons"]
    assert r["explanations"]["rows"] == 24
    assert acc.R_EXPLANATIONS_OVERWRITTEN not in r["reasons"]
    assert acc.R_MISSING_FRESHNESS_PROOF not in r["reasons"]


def test_the_overwrite_reason_no_longer_fires_for_a_normal_day(tmp_path):
    """The 5Q-1 workaround becomes unreachable on a healthy day, which is the measure of the
    fix. Calm and Stress both keep their rows, so neither is 'overwritten by a later sleeve'."""
    from global_index import track1_slots as ts
    for sleeve in ("roska4_calm", "roska4_stress"):
        _ledger_and_timing(tmp_path, sleeve, candidates=1)
        for s in ts.TRACK1_SLOTS:
            if s.sleeve == sleeve:
                write_slot(tmp_path, s.sleeve, s.id)
    for sleeve in ("roska4_calm", "roska4_stress"):
        r = acc.evaluate_sleeve(DAY, sleeve, tmp_path, now_et=f"{DAY}T23:00:00",
                                scheduler_started_et=f"{DAY}T00:05:00")
        assert r["verdict"] == acc.AUDIT_PASS, (sleeve, r["reasons"])
        assert acc.R_EXPLANATIONS_OVERWRITTEN not in r["reasons"]
        assert r["notes"] == []


def test_a_prose_only_row_fails_the_sleeve(tmp_path):
    _ledger_and_timing(tmp_path, "roska4_calm", candidates=1)
    write_slot(tmp_path, "roska4_calm", "TRACK1_CALM_1000")
    f = acc.explanation_files(tmp_path, DAYC)[0]
    bad = _record(status=tx.REJECTED, reason_code="reject_cap",
                  rule_ids=["GATE.CAP_CLUSTER"],
                  features=[tx.Feature("cluster_gross_after", None, 1.0, "<=", passed=False)],
                  inputs_summary={"note": "freshness was fine"})
    f.write_text(json.dumps(bad, default=str) + "\n", encoding="utf-8")
    r = acc.evaluate_sleeve(DAY, "roska4_calm", tmp_path, now_et=f"{DAY}T23:00:00",
                            scheduler_started_et=f"{DAY}T00:05:00")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_MISSING_FRESHNESS_PROOF in r["reasons"]


def test_a_sleeve_that_reported_nothing_is_not_told_it_found_nothing(tmp_path):
    """Measured on the live tree, 2026-08-24 10:07 ET.

    The first real Calm slot crashed inside the live-frame splice before writing a
    `slot_observed` row. The audit correctly FAILED it on coverage, timing and the missing
    slot id — and alongside those it printed "it observed its window and found nothing to
    admit", which is a claim about a slot that never reported. The verdict was right and one
    of its sentences was about the wrong thing.
    """
    dayc = DAY.replace("-", "")
    p = tmp_path / acc.COVERAGE_DIR / f"window_coverage_{dayc}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"event": "window_open", "sleeve": "roska4_calm", "date": DAY,
                             "route": "track1_candidate", "expected_slots": 1}) + "\n",
                 encoding="utf-8")
    r = acc.evaluate_sleeve(DAY, "roska4_calm", tmp_path, now_et=f"{DAY}T23:00:00",
                            scheduler_started_et=f"{DAY}T00:05:00")
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_COVERAGE_UNOBSERVED in r["reasons"]
    assert acc.R_MISSING_SLOT_IDS in r["reasons"]
    assert acc.R_NO_CANDIDATES_TO_EXPLAIN not in r["reasons"]


# ══════════════════════════════════════════════════════════════════════════════
# 6. the replay path is untouched, and the real tree is never written
# ══════════════════════════════════════════════════════════════════════════════

def test_the_replay_path_keeps_its_flat_window_layout(tmp_path):
    """Explicitly scoped rather than migrated. A replay writes one window from one process,
    which is the case truncation was designed for, and every committed replay artefact on
    disk is in this shape."""
    out = R.emit_explanations(
        [], out_dir=tx.SHADOW_ROOT, root=str(tmp_path), window="vault2026",
        regime_csv="spy_daily_live.csv", data_paths=R.default_data_paths(),
        fill_law=tp.LIVE_FILL_LAW, freshness_allow=True, mode=tx.REPLAY,
        as_of=pd.Timestamp(f"{DAY} 10:00"), context_sleeve="roska4_swing")
    assert out["dir"] == "scratch/track1_shadow/explanations/vault2026"
    assert (tmp_path / "scratch/track1_shadow/explanations/vault2026"
            / f"explanations_{DAYC}.jsonl").exists()


def test_the_writer_still_refuses_a_destination_outside_the_approved_roots(tmp_path):
    with pytest.raises(tx.ShadowPathRefused):
        R.emit_explanations(
            [], out_dir="global_index/dash", root=str(tmp_path), window="x",
            regime_csv="spy_daily_live.csv", data_paths=R.default_data_paths(),
            fill_law=tp.LIVE_FILL_LAW, freshness_allow=True, mode=tx.SHADOW_LIVE,
            as_of=pd.Timestamp(f"{DAY} 10:00"), context_sleeve="roska4_calm")


def test_this_suite_never_wrote_into_the_real_runtime_tree():
    """Asserted, not assumed. A suite that writes evidence into the tree a go-live gate reads
    is the failure mode this whole route was built to avoid.

    Stage 5ZH: asked by mtime, not by filename. This suite's DAY is a real calendar date, and
    on 2026-08-25 the live shadow slots wrote their own `explanations_20260825.jsonl` files
    into this very tree — forty of them, between 11:11 and 14:11 ET, which is the running
    system doing its job. A name match said "a test wrote this"; it only ever meant "a file
    for that day exists". Written-during-this-process is the thing actually being guarded,
    and unlike the name it cannot be satisfied by the system working correctly.
    """
    if not REAL_TREE.exists():
        return
    stray = [str(p) for p in REAL_TREE.rglob("*")
             if p.is_file() and p.stat().st_mtime >= _IMPORTED_AT]
    assert stray == [], stray
