"""Stage 5ZH — the audit reads the checkpoint the writer actually writes.

Every checkpoint in this file is produced by `route_checkpoint.save_route` or
`track1_bootstrap.write`, never by hand. That is the whole lesson of the stage: the version
of the acceptance check this replaces was written against a flat payload
(`{"schema_version": 2, "route": ..., "cut_instant": ..., "sleeves": {}}`) that the writer
has never produced and that `route_checkpoint.load` rejects outright — and three test suites
certified it green by building that same invented payload. A fixture that agrees with the
reader instead of with the writer proves the two agree, which was never in question.

Nothing here writes a real runtime file. Everything is under `tmp_path`, and the last part
proves it by mtime rather than by absence — the live system legitimately writes both
artefacts, so absence stopped being the right question.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import route_checkpoint as rc            # noqa: E402
from global_index import track1_shadow_acceptance as acc   # noqa: E402
from global_index import track1_slots as ts                # noqa: E402
from global_index import window_ledger as wl               # noqa: E402

REPO = Path(r"d:\raits")
DAY = "2026-08-25"
DAYC = DAY.replace("-", "")
LATE = "2026-08-25 23:00"
EARLY_START = "2026-08-25 01:00:00"

_IMPORTED_AT = time.time()

#: The two files `track1_bootstrap.write` produces in one call.
_PRODUCTION = (acc.CHECKPOINT_PATH, acc.CHECKPOINT_BOOK_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# fixtures — the checkpoint always comes from the writer
# ══════════════════════════════════════════════════════════════════════════════

def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def write_checkpoint(root: Path, *, entries=None, route: str = "track1_candidate") -> Path:
    """Through `save_route`, so the shape is the writer's and cannot be invented here."""
    p = root / acc.CHECKPOINT_PATH
    rc.save_route(entries or {}, route=route, path=str(p))
    return p


def write_book(root: Path, *, cut_day: str = DAY) -> Path:
    """The companion book, in the shape `write_route_checkpoint` builds for a quiet close."""
    p = root / acc.CHECKPOINT_BOOK_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schema_version": 2, "route": "track1_candidate", "window": "live",
        "cut_instant": f"{cut_day}T15:55:01.000000-04:00",
        "equity": 0.0, "cur_day": cut_day, "peak_equity": 0.0,
        "day_start_equity": 0.0, "positions": [], "booked_counter": {}, "counters": {},
    }, indent=1), encoding="utf-8")
    return p


def an_entry(*, last_day: str = DAY, route: str = "track1_candidate",
             sleeve: str = "roska4_swing") -> dict:
    """One instrument entry in `make_entry`'s shape, without needing a real frame."""
    return {"route": route, "sleeve": sleeve, "last_day": last_day,
            "fingerprint": {"rows": 10, "digest": "deadbeef"},
            "params": "p", "params_hash": "h", "data_source": "d", "pos": None}


def _swing_slots():
    return [s for s in ts.TRACK1_SLOTS if s.sleeve == "roska4_swing"]


def build_quiet_swing(root: Path, *, day: str = DAY, decided: bool = True,
                      runtime: float = 78.5, outcome: str = "complete",
                      slots=None) -> None:
    """23 slots that ran, evaluated, and admitted nothing — the 2026-08-25 window."""
    slots = _swing_slots() if slots is None else slots
    rows = [{"event": "window_open", "sleeve": "roska4_swing", "date": day,
             "route": "track1_candidate", "expected_slots": len(_swing_slots())}]
    for i, s in enumerate(slots):
        rows.append({"event": "slot_observed", "sleeve": "roska4_swing", "date": day,
                     "slot_id": s.id, "seq": i, "decided": decided,
                     "candidates": 0, "explained": 0,
                     "reason": "ok" if decided else "gate_refused",
                     "detail": "" if decided else "stale",
                     "route": "track1_candidate"})
    rows.append({"event": "window_closed", "sleeve": "roska4_swing", "date": day,
                 "outcome": outcome, "signal": "no_signal",
                 "observed_slots": len(slots),
                 "expected_slots": len(_swing_slots()),
                 "route": "track1_candidate"})
    _write_jsonl(root / acc.COVERAGE_DIR / f"window_coverage_{day.replace('-', '')}.jsonl",
                 rows)
    _write_jsonl(root / acc.TIMING_DIR / f"slot_timing_{day.replace('-', '')}.jsonl",
                 [{"ts": f"{day}T19:00:00+00:00", "route": "track1_candidate",
                   "slot_id": s.id, "outcome": "ok", "runtime_s": runtime, "phases": {}}
                  for s in slots])


@pytest.fixture
def quiet(tmp_path):
    """The 2026-08-25 Swing window, reconstructed: complete, quiet, both artefacts."""
    build_quiet_swing(tmp_path)
    write_checkpoint(tmp_path)
    write_book(tmp_path)
    return tmp_path


def _swing(root, *, day: str = DAY):
    return acc.evaluate_sleeve(day, "roska4_swing", root, now_et=LATE,
                               scheduler_started_et=EARLY_START)


# ══════════════════════════════════════════════════════════════════════════════
# A. the shape the writer writes is the shape the reader reads
# ══════════════════════════════════════════════════════════════════════════════

def test_schema_2_with_routes_track1_candidate_is_accepted(tmp_path):
    write_checkpoint(tmp_path)
    write_book(tmp_path)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK, c
    assert c["code"] == acc.CK_OK


def test_the_writer_puts_no_route_or_cut_instant_at_the_top_level(tmp_path):
    """The two keys the previous reader asked for. Neither has ever existed."""
    p = write_checkpoint(tmp_path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    assert payload.get("route") is None
    assert payload.get("cut_instant") is None
    assert list(payload["routes"]) == ["track1_candidate"]


def test_the_flat_payload_three_suites_used_as_a_fixture_is_refused(tmp_path):
    """It is not merely unrecognised — `route_checkpoint.load` throws it away as foreign,
    so nothing in the system could ever have produced or consumed it."""
    p = tmp_path / acc.CHECKPOINT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                             "cut_instant": f"{DAY}T15:55:00", "sleeves": {}}),
                 encoding="utf-8")
    assert rc.load(str(p)) == {}, "the route module now accepts the invented shape"
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_UNREADABLE, c


def test_a_fixture_built_by_hand_must_match_the_writer_byte_for_byte(tmp_path):
    """The anti-recurrence guard. If the two ever diverge, this stage's defect is back."""
    a = write_checkpoint(tmp_path / "a")
    b = tmp_path / "b" / acc.CHECKPOINT_PATH
    b.parent.mkdir(parents=True, exist_ok=True)
    b.write_text(json.dumps(rc.empty_payload("track1_candidate"), indent=1, default=str)
                 + "", encoding="utf-8")
    assert json.loads(a.read_text(encoding="utf-8")) == \
        json.loads(b.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# B. the quiet-window contract (Option C)
# ══════════════════════════════════════════════════════════════════════════════

def test_empty_instruments_under_a_valid_route_pass_when_the_book_agrees(tmp_path):
    write_checkpoint(tmp_path)
    write_book(tmp_path, cut_day=DAY)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK
    assert c["entries"] is False
    assert "quiet window" in c["detail"]


def test_empty_instruments_with_no_book_cannot_be_dated_and_fail(tmp_path):
    """'I could not check' is not 'I checked and it was fine'."""
    write_checkpoint(tmp_path)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_DAY_UNVERIFIABLE
    assert acc.CHECKPOINT_BOOK_PATH in c["detail"]


def test_empty_instruments_with_a_book_from_another_day_fail_as_wrong_day(tmp_path):
    write_checkpoint(tmp_path)
    write_book(tmp_path, cut_day="2026-08-19")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_WRONG_DAY


def test_empty_instruments_with_an_undateable_book_fail_rather_than_pass(tmp_path):
    write_checkpoint(tmp_path)
    p = tmp_path / acc.CHECKPOINT_BOOK_PATH
    p.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate"}),
                 encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_DAY_UNVERIFIABLE


def test_a_corrupt_book_fails_rather_than_passing_the_quiet_branch(tmp_path):
    write_checkpoint(tmp_path)
    (tmp_path / acc.CHECKPOINT_BOOK_PATH).write_text("{not json", encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_DAY_UNVERIFIABLE


# ══════════════════════════════════════════════════════════════════════════════
# C. entries present — REVISED BY STAGE 5ZK
#
# As written on 2026-08-25 this section asserted that entries carry their own day, that the
# day must equal the day under judgment, and that the book is not consulted when entries
# exist. Stage 5ZK measured the parquet store and the first of those is right while the other
# two are not: the daily append runs at 13:45 ET, so at a 15:55 close the store holds today
# only through 13:44 and the next append backfills the rest. A fingerprint through the cut day
# does not survive that append; one through the last COMPLETE day does. So a correct entry
# names the PREVIOUS trading day, and the old rule would have failed every real checkpoint the
# writer can produce — including the first one it ever produced.
#
# The book is now the day proof in both cases, which is simpler than the split rule it
# replaces. What the entries are still asked is that their history is not from the future and
# not stale.
# ══════════════════════════════════════════════════════════════════════════════

def test_entries_dated_before_the_judged_day_pass_when_the_book_agrees(tmp_path):
    """The shape the real writer produces: history through the last complete day."""
    write_checkpoint(tmp_path,
                     entries={"roska4_swing": {"MES": an_entry(last_day="2026-08-24")}})
    write_book(tmp_path, cut_day=DAY)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK, c
    assert c["entries"] is True
    assert c["history_lag_days"] == 1


def test_entries_without_a_book_can_no_longer_date_themselves(tmp_path):
    """Superseded: this used to pass. The book is written in the same call, so its absence is
    a fact about the artefact rather than an inconvenience to route around."""
    write_checkpoint(tmp_path, entries={"roska4_swing": {"MES": an_entry(last_day=DAY)}})
    assert not (tmp_path / acc.CHECKPOINT_BOOK_PATH).exists()
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_DAY_UNVERIFIABLE, c


def test_entries_dated_after_the_judged_day_still_fail(tmp_path):
    """A history claim from the future means something other than this run wrote it."""
    write_checkpoint(tmp_path,
                     entries={"roska4_swing": {"MES": an_entry(last_day="2026-08-27")}})
    write_book(tmp_path, cut_day=DAY)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_WRONG_DAY
    assert "2026-08-27" in c["detail"]


def test_entries_spread_over_two_recent_days_are_fine(tmp_path):
    """Instruments have their own calendars — MNKD runs on Tokyo's — so two adjacent days is a
    real state, not a fault. It was failed by the old rule for naming anything but the cut."""
    write_checkpoint(tmp_path, entries={
        "roska4_swing": {"MES": an_entry(last_day="2026-08-24")},
        "global_nkd": {"MNKD": an_entry(last_day="2026-08-22", sleeve="global_nkd")}})
    write_book(tmp_path, cut_day=DAY)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK, c
    assert c["history_lag_days"] == 3


def test_entries_older_than_the_allowance_fail(tmp_path):
    write_checkpoint(tmp_path,
                     entries={"roska4_swing": {"MES": an_entry(last_day="2026-08-01")}})
    write_book(tmp_path, cut_day=DAY)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_HISTORY_STALE, c
    assert c["history_lag_days"] > acc.CHECKPOINT_MAX_HISTORY_LAG_DAYS


def test_a_book_that_disagrees_about_the_day_fails_even_with_entries(tmp_path):
    write_checkpoint(tmp_path,
                     entries={"roska4_swing": {"MES": an_entry(last_day="2026-08-24")}})
    write_book(tmp_path, cut_day="2026-08-19")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_WRONG_DAY


# ══════════════════════════════════════════════════════════════════════════════
# D. wrong route, wrong schema, missing
# ══════════════════════════════════════════════════════════════════════════════

def test_a_checkpoint_for_another_route_still_fails(tmp_path):
    write_checkpoint(tmp_path, route="legacy_r4")
    write_book(tmp_path)
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_WRONG_ROUTE
    assert "legacy_r4" in c["detail"], "the failure must name what it DID find"


def test_another_routes_entries_do_not_stand_in_for_this_route(tmp_path):
    write_checkpoint(tmp_path, route="legacy_r4",
                     entries={"roska4_swing": {"MES": an_entry(route="legacy_r4")}})
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["code"] == acc.CK_WRONG_ROUTE


def test_a_second_route_beside_ours_does_not_disturb_the_check(tmp_path):
    """`save_route` merges scoped, so a shared file holding both routes is a real state."""
    write_checkpoint(tmp_path)
    write_checkpoint(tmp_path, route="legacy_r4")
    write_book(tmp_path)
    payload = json.loads((tmp_path / acc.CHECKPOINT_PATH).read_text(encoding="utf-8"))
    assert sorted(payload["routes"]) == ["legacy_r4", "track1_candidate"]
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK


@pytest.mark.parametrize("payload,code", [
    ({"schema_version": 1, "instruments": {}}, "unreadable"),
    ({"schema_version": 2, "sleeves": {}}, "unreadable"),
    ([1, 2, 3], "unreadable"),
    ({}, "unreadable"),
])
def test_a_payload_of_the_wrong_shape_is_named_as_such_not_as_a_wrong_day(tmp_path,
                                                                         payload, code):
    """The old `else` branch called every shape problem `checkpoint_wrong_day`."""
    p = tmp_path / acc.CHECKPOINT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == code


@pytest.mark.parametrize("schema", [1, 3, "2", None])
def test_a_routes_shaped_payload_of_another_schema_is_still_refused(tmp_path, schema):
    """The schema guard is load-bearing on its own, not covered by the `routes` guard.

    A future schema that keeps `routes` and changes what an entry means would otherwise be
    read as if it were schema 2 — the same class of mistake this whole stage is about, one
    version later. `route_checkpoint.load` refuses these outright; so does this.
    """
    p = tmp_path / acc.CHECKPOINT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"routes": {"track1_candidate": {"sleeves": {
        "roska4_swing": {"instruments": {"MES": an_entry()}}}}}}
    if schema is not None:
        payload["schema_version"] = schema
    p.write_text(json.dumps(payload), encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL, c
    assert c["code"] == acc.CK_UNREADABLE, c
    assert rc.load(str(p)) == {}, "the route module now accepts this schema too"


def test_a_missing_checkpoint_still_fails(tmp_path):
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_MISSING


def test_an_unparseable_checkpoint_still_fails(tmp_path):
    p = tmp_path / acc.CHECKPOINT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ truncated", encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_UNREADABLE


# ══════════════════════════════════════════════════════════════════════════════
# E. the audit verdict — the 2026-08-25 Swing window
# ══════════════════════════════════════════════════════════════════════════════

def test_the_quiet_complete_swing_window_passes(quiet):
    r = _swing(quiet)
    assert r["verdict"] == acc.AUDIT_PASS, (r["verdict"], r["reasons"], r["details"])
    assert r["checkpoint"]["status"] == acc.OK
    assert r["checkpoint"]["expected"] is True
    assert r["ledger_outcome"] == wl.COMPLETE
    assert r["observed_slots"] == 23
    assert "checkpoint_wrong_route" not in r["reasons"]


def test_the_quiet_window_still_says_out_loud_that_it_admitted_nothing(quiet):
    """A PASS must not become silence: the sentence stays, it just stops being a failure."""
    r = _swing(quiet)
    assert acc.R_ALL_SLOTS_NO_ACTION in r["reasons"]
    assert any("found no candidate" in d for d in r["details"])


def test_the_same_window_without_a_checkpoint_fails(quiet):
    (quiet / acc.CHECKPOINT_PATH).unlink()
    r = _swing(quiet)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_MISSING in r["reasons"]


def test_the_same_window_with_a_foreign_route_checkpoint_fails(quiet):
    # unlink first: `save_route` merges by design, so writing a second route into the
    # existing file would leave ours in place — and that scoped merge is the behaviour the
    # route module exists to guarantee. The condition under test is a checkpoint that does
    # not contain this route at all.
    (quiet / acc.CHECKPOINT_PATH).unlink()
    write_checkpoint(quiet, route="legacy_r4")
    r = _swing(quiet)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_WRONG_ROUTE in r["reasons"]


def test_the_same_window_with_yesterdays_book_fails_as_wrong_day(quiet):
    write_book(quiet, cut_day="2026-08-24")
    r = _swing(quiet)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_WRONG_DAY in r["reasons"]


def test_the_same_window_with_no_book_fails_as_unverifiable_not_as_ok(quiet):
    (quiet / acc.CHECKPOINT_BOOK_PATH).unlink()
    r = _swing(quiet)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_DAY_UNVERIFIABLE in r["reasons"]


# ══════════════════════════════════════════════════════════════════════════════
# F. an incomplete window cannot be rescued by a perfect checkpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_an_incomplete_window_still_fails_with_a_valid_checkpoint(tmp_path):
    build_quiet_swing(tmp_path, outcome="incomplete", slots=_swing_slots()[:10])
    write_checkpoint(tmp_path)
    write_book(tmp_path)
    r = _swing(tmp_path)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_COVERAGE_INCOMPLETE in r["reasons"]
    assert r["checkpoint"]["expected"] is False, (
        "an incomplete window must not even be asked for a checkpoint")


def test_a_hard_refused_window_still_fails_with_a_valid_checkpoint(tmp_path):
    build_quiet_swing(tmp_path, decided=False, outcome="incomplete")
    write_checkpoint(tmp_path)
    write_book(tmp_path)
    r = _swing(tmp_path)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_HARD_REFUSAL in r["reasons"]
    assert acc.R_CHECKPOINT_MISSING not in r["reasons"]


def test_a_checkpoint_is_only_required_of_a_window_that_completed(tmp_path):
    """Missing checkpoint, incomplete window: named as coverage, not as a checkpoint fault."""
    build_quiet_swing(tmp_path, outcome="incomplete", slots=_swing_slots()[:10])
    r = _swing(tmp_path)
    assert not any(x.startswith("checkpoint_") for x in r["reasons"]), r["reasons"]
    assert r["checkpoint"]["status"] == acc.FAIL
    assert r["checkpoint"]["expected"] is False


# ══════════════════════════════════════════════════════════════════════════════
# G. the code, not the sentence
# ══════════════════════════════════════════════════════════════════════════════

def test_every_failing_code_maps_to_a_reason():
    for code in (acc.CK_MISSING, acc.CK_UNREADABLE, acc.CK_WRONG_ROUTE,
                 acc.CK_WRONG_DAY, acc.CK_DAY_UNVERIFIABLE):
        assert code in acc.CHECKPOINT_REASON_BY_CODE, code
    assert acc.CK_OK not in acc.CHECKPOINT_REASON_BY_CODE
    assert len(set(acc.CHECKPOINT_REASON_BY_CODE.values())) == \
        len(acc.CHECKPOINT_REASON_BY_CODE), "two codes share one reason"


def test_rewording_a_detail_cannot_change_the_reason(quiet, monkeypatch):
    """The classification used to read `'route is' in detail`. It no longer reads prose."""
    real = acc.checkpoint_check

    def reworded(root, day):
        c = dict(real(root, day))
        c["status"] = acc.FAIL
        c["code"] = acc.CK_WRONG_ROUTE
        c["detail"] = "a sentence nobody has ever grepped for"
        return c

    monkeypatch.setattr(acc, "checkpoint_check", reworded)
    r = _swing(quiet)
    assert acc.R_CHECKPOINT_WRONG_ROUTE in r["reasons"]


def test_the_check_is_reported_with_its_code_on_the_audit_row(quiet):
    r = _swing(quiet)
    assert r["checkpoint"]["code"] == acc.CK_OK


# ══════════════════════════════════════════════════════════════════════════════
# H. the dashboard reader — the same defect, read a second time
# ══════════════════════════════════════════════════════════════════════════════

def _summary(root):
    from monitor.backend import track1_runtime_reader as trr
    return trr.read_track1_runtime(root)["checkpoint"]["summary"]


def test_the_panel_names_the_route_the_checkpoint_actually_carries(tmp_path):
    write_checkpoint(tmp_path)
    s = _summary(tmp_path)
    assert s["route"] == "track1_candidate", (
        "the panel reported no route for a file that names one under `routes`")
    assert s["routes"] == ["track1_candidate"]
    assert s["schema_version"] == 2


def test_the_panel_lists_the_sleeves_the_checkpoint_holds(tmp_path):
    write_checkpoint(tmp_path)
    s = _summary(tmp_path)
    assert sorted(s["sleeves"]) == sorted(ts.SLEEVES if hasattr(ts, "SLEEVES")
                                          else rc.SLEEVES)
    assert s["entry_count"] == 0


def test_the_panel_counts_entries_and_reports_their_cut_day(tmp_path):
    write_checkpoint(tmp_path, entries={
        "roska4_swing": {"MES": an_entry(), "MNQ": an_entry()},
        "global_nkd": {"MNKD": an_entry(sleeve="global_nkd")}})
    s = _summary(tmp_path)
    assert s["entry_count"] == 3
    assert s["entries"]["roska4_swing"] == ["MES", "MNQ"]
    assert s["cut_instant"] == DAY


def test_the_panel_reports_no_route_when_the_checkpoint_is_another_routes(tmp_path):
    write_checkpoint(tmp_path, route="legacy_r4")
    s = _summary(tmp_path)
    assert s["route"] is None
    assert s["routes"] == ["legacy_r4"]


def test_the_panel_says_no_day_rather_than_inventing_one_for_a_quiet_checkpoint(tmp_path):
    write_checkpoint(tmp_path)
    assert _summary(tmp_path)["cut_instant"] is None


# ══════════════════════════════════════════════════════════════════════════════
# I. nothing real was written
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", _PRODUCTION)
def test_no_production_artefact_was_written_by_this_run(name):
    p = REPO / name
    if not p.exists():
        return
    assert p.stat().st_mtime < _IMPORTED_AT, (
        f"{name} was written DURING this test run — every fixture must be under tmp_path")


def test_the_two_production_artefacts_are_still_the_ones_the_live_system_wrote():
    """Both were written by the 15:55 ET close on 2026-08-25, in one call, seconds apart."""
    ck, book = REPO / acc.CHECKPOINT_PATH, REPO / acc.CHECKPOINT_BOOK_PATH
    if not (ck.exists() and book.exists()):
        pytest.skip("the live artefacts are not present on this machine")
    assert abs(ck.stat().st_mtime - book.stat().st_mtime) < 5.0, (
        "the checkpoint and its book no longer share a write instant — they are supposed "
        "to come from one call to track1_bootstrap.write")


def test_no_order_switch_or_confirmation_file_appeared():
    # Stage 5ZZZ-A. The confirmation file leaves this list, for the reason Stage 5ZZS restated
    # it in four other suites and Stage 5ZZW in two more: the operator signed it deliberately on
    # 2026-08-27, and asserting its absence asserts that nobody decided anything.
    #
    # What still must not exist is anything that would ARM an order — the approval marker and
    # the order journal — and if a decision IS on disk it has to be a signed one, because an
    # unsigned file appearing here would be something a run had dropped.
    for name in ("TRACK1_ORDERS_APPROVED", "global_index/track1_runtime/orders"):
        assert not (REPO / name).exists(), f"{name} exists — orders must remain impossible"
    _conf = REPO / "track1_go_live_confirmation.json"
    if _conf.exists():
        import json as _json
        _d = _json.loads(_conf.read_text(encoding="utf-8"))
        assert (_d.get("confirmed_by") or "").strip(), "an unsigned decision appeared on disk"
