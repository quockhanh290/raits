"""Stage 5ZK — the checkpoint stops being an artefact that records nothing.

Every checkpoint here is produced by the real writer and read by the real reader. The frames
are the real parquets, read-only, because the one claim this stage makes that a fixture cannot
support is a runtime-budget claim: a tiny synthetic frame would load in milliseconds and prove
nothing about a 3.4-million-row store.

Nothing writes into the runtime tree. Every checkpoint, book and audit path in this file is
under `tmp_path`, and the last part proves it by mtime.

What this stage found, and why the tests look the way they do
--------------------------------------------------------------
The production call site passed no frames, so `checkpoint_entries` skipped every instrument
and wrote an empty checkpoint whatever the day did. The obvious fix — fingerprint the frames
through the cut day — does not work, and the data says why. The daily append runs at 13:45 ET,
so at a 15:55 close the store holds today through 13:44 while yesterday runs to 23:59; the
next append backfills today's afternoon, which sits below the cut a fingerprint through today
would use. Measured on MES and MNKD: through the newest stored day the fingerprint does not
survive the next append, through the day before it it does.

So a correct entry names the last COMPLETE day. Stage 5ZH's rule — entries must name the
judged day — was built on an assumption the store disproves, and is replaced here.

One claim in this file started out wrong and the data corrected it mid-stage. It read *the
frames already in the slot's memory are the wrong ones, because splicing changes the hash*.
True through the cut day; false through the last complete day, where the appended bars sit
above the cut and the two frames hash identically. Reusing them would have worked. Reloading
the parquet is a choice — see `checkpoint_frames` — and the test that was going to prove reuse
impossible now pins that it is merely unnecessary.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, r"d:\raits")

from global_index import route_checkpoint as rc                # noqa: E402
from global_index import run_live_day_track1 as R              # noqa: E402
from global_index import track1_bootstrap as boot              # noqa: E402
from global_index import track1_params as tp                   # noqa: E402
from global_index import track1_shadow_acceptance as acc       # noqa: E402
from global_index import window_ledger as wl                   # noqa: E402
from global_index import track1_slots as ts                    # noqa: E402

REPO = Path(r"d:\raits")
DAY = "2026-08-25"
LATE = "2026-08-25 23:00"
EARLY_START = "2026-08-25 01:00:00"
CUT = pd.Timestamp("2026-08-25 15:55:01")

_IMPORTED_AT = time.time()

#: Everything the real writer would touch in production.
_PRODUCTION = (acc.CHECKPOINT_PATH, acc.CHECKPOINT_BOOK_PATH)

CROSS_DAY_INSTS = sorted({i for s in rc.CHECKPOINTED_SLEEVES
                          for i in tp.SLEEVE_INSTRUMENTS.get(s, ())})


# ══════════════════════════════════════════════════════════════════════════════
# fixtures — real parquets, loaded once
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def data_paths():
    return R.default_data_paths()


@pytest.fixture(scope="module")
def real_frames(data_paths):
    frames, why = R.checkpoint_frames(data_paths)
    if why:
        pytest.skip(f"the live parquet store is not readable here: {why}")
    assert set(frames) == set(CROSS_DAY_INSTS), sorted(frames)
    # A frame small enough to be a fixture would make every timing claim below meaningless.
    assert min(len(f) for f in frames.values()) > 1_000_000, \
        {i: len(f) for i, f in frames.items()}
    return frames


def a_book(*, cut_day: str = DAY, positions=(), route: str = "track1_candidate") -> dict:
    return {"schema_version": 2, "route": route, "window": "live",
            "cut_instant": f"{cut_day}T15:55:01.000000-04:00",
            "equity": 0.0, "cur_day": cut_day, "peak_equity": 0.0,
            "day_start_equity": 0.0, "positions": list(positions),
            "booked_counter": {}, "counters": {}}


def an_open_position(inst: str = "MES", sleeve: str = "roska4_swing") -> dict:
    return {"inst": inst, "instrument": inst, "sleeve": sleeve, "cluster": sleeve,
            "direction": "long", "entry_price": 5000.0, "stop_price": 4950.0,
            "entry_time": f"{DAY}T14:05:00", "contracts": 1}


def write_ck(root: Path, *, frames, book_state, sleeve="roska4_swing", data_paths=None):
    """Through the REAL writer, into tmp_path."""
    return R.write_route_checkpoint(
        sleeve, now_et=CUT, regime_csv="spy_daily_live.csv",
        data_paths=data_paths if data_paths is not None else R.default_data_paths(),
        frames=frames, book_state=book_state,
        path=str(root / acc.CHECKPOINT_PATH),
        book_path=str(root / acc.CHECKPOINT_BOOK_PATH))


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def build_window(root: Path, *, sleeve="roska4_swing", outcome="complete", slots=None,
                 decided=True, runtime=78.5):
    all_slots = [s for s in ts.TRACK1_SLOTS if s.sleeve == sleeve]
    use = all_slots if slots is None else slots
    rows = [{"event": "window_open", "sleeve": sleeve, "date": DAY,
             "route": "track1_candidate", "expected_slots": len(all_slots)}]
    for i, s in enumerate(use):
        rows.append({"event": "slot_observed", "sleeve": sleeve, "date": DAY,
                     "slot_id": s.id, "seq": i, "decided": decided, "candidates": 0,
                     "explained": 0, "reason": "ok" if decided else "gate_refused",
                     "detail": "" if decided else "stale", "route": "track1_candidate"})
    rows.append({"event": "window_closed", "sleeve": sleeve, "date": DAY,
                 "outcome": outcome, "signal": "no_signal", "observed_slots": len(use),
                 "expected_slots": len(all_slots), "route": "track1_candidate"})
    _write_jsonl(root / acc.COVERAGE_DIR / f"window_coverage_{DAY.replace('-','')}.jsonl", rows)
    _write_jsonl(root / acc.TIMING_DIR / f"slot_timing_{DAY.replace('-','')}.jsonl",
                 [{"ts": f"{DAY}T19:00:00+00:00", "route": "track1_candidate",
                   "slot_id": s.id, "outcome": "ok", "runtime_s": runtime, "phases": {}}
                  for s in use])


def judge(root, sleeve="roska4_swing"):
    return acc.evaluate_sleeve(DAY, sleeve, root, now_et=LATE,
                               scheduler_started_et=EARLY_START)


# ══════════════════════════════════════════════════════════════════════════════
# A. the frame kind — why the in-memory frames could not be reused
# ══════════════════════════════════════════════════════════════════════════════

def test_a_spliced_frame_and_the_parquet_do_not_share_a_fingerprint(real_frames):
    """The slot has joined live frames in memory. Reusing them would have been free and would
    have produced a checkpoint that refuses every resume while looking like it works."""
    from global_index.replay_checkpoint import fingerprint
    df = real_frames["MES"]
    day = pd.Timestamp(DAY)
    base = fingerprint(df, day)
    extra = df.tail(1).copy()
    extra.index = pd.DatetimeIndex([df.index.max() + pd.Timedelta(minutes=1)])
    if df.index.tz is not None and extra.index.tz is None:
        extra.index = extra.index.tz_localize(df.index.tz)
    assert fingerprint(pd.concat([df, extra]), day) != base


def test_a_same_length_repair_still_changes_the_fingerprint(real_frames):
    """A rowcount check alone would miss it; that is why the fingerprint is content-derived."""
    from global_index.replay_checkpoint import fingerprint
    df = real_frames["MNKD"]
    day = pd.Timestamp(DAY)
    base = fingerprint(df, day)
    rep = df.copy()
    mid = len(rep) // 2
    rep.iloc[mid, 0] = float(rep.iloc[mid, 0]) + 0.25
    got = fingerprint(rep, day)
    assert got != base
    assert got.split(":")[0] == base.split(":")[0], "the rowcount is unchanged, as intended"


# ══════════════════════════════════════════════════════════════════════════════
# B. the last COMPLETE day
# ══════════════════════════════════════════════════════════════════════════════

def test_the_derived_day_is_the_one_whose_history_has_stopped_moving(real_frames):
    from global_index.replay_checkpoint import fingerprint
    for inst, df in real_frames.items():
        d = R.last_complete_day(df)
        assert d is not None and d.tz is None, (inst, d)
        newest = pd.Timestamp(pd.DatetimeIndex(df.index).normalize().max())
        newest = newest.tz_localize(None) if newest.tz is not None else newest
        assert d < newest, (inst, d, newest)

        # the whole point: the derived day survives the next append, the newest does not
        tail = df.index.max()
        extra = pd.concat([df.tail(1)] * 50)
        extra.index = pd.DatetimeIndex([tail + pd.Timedelta(minutes=k + 1) for k in range(50)])
        after = pd.concat([df, extra])
        assert fingerprint(after, d) == fingerprint(df, d), f"{inst}: derived day not stable"
        assert fingerprint(after, newest) != fingerprint(df, newest), \
            f"{inst}: the newest day looks stable, so the premise is wrong"


def test_a_frame_with_one_day_has_no_complete_day():
    idx = pd.date_range("2026-08-25", periods=10, freq="1min")
    assert R.last_complete_day(pd.DataFrame({"close": range(10)}, index=idx)) is None


def test_an_empty_or_missing_frame_is_none():
    assert R.last_complete_day(None) is None
    assert R.last_complete_day(pd.DataFrame()) is None


# ══════════════════════════════════════════════════════════════════════════════
# C. the writer
# ══════════════════════════════════════════════════════════════════════════════

def test_frames_none_means_load_them_and_empty_dict_means_deliberately_none(tmp_path,
                                                                            data_paths):
    """They used to mean the same thing, and that is exactly how production wrote an empty
    checkpoint on every window for as long as the route has been running."""
    loaded = write_ck(tmp_path / "a", frames=None, book_state=a_book())
    assert loaded["entry_count"] == len(CROSS_DAY_INSTS), loaded
    none = write_ck(tmp_path / "b", frames={}, book_state=a_book())
    assert none["entry_count"] == 0


def test_the_writer_records_what_it_could_not_load(tmp_path):
    out = write_ck(tmp_path, frames=None, book_state=a_book(),
                   data_paths={i: str(tmp_path / f"missing_{i}.parquet")
                               for i in CROSS_DAY_INSTS})
    assert out["entry_count"] == 0
    assert sorted(out["frames_unavailable"]) == CROSS_DAY_INSTS, out["frames_unavailable"]


def test_entries_name_the_last_complete_day_not_the_cut_day(tmp_path, real_frames):
    out = write_ck(tmp_path, frames=real_frames, book_state=a_book())
    assert out["entry_count"] == len(CROSS_DAY_INSTS)
    days = set(out["last_day_by_inst"].values())
    assert days and DAY not in days, (days, "an entry named the cut day")
    for d in days:
        assert d < DAY


def test_the_written_entries_carry_a_full_identity(tmp_path, real_frames):
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    payload = rc.load(str(tmp_path / acc.CHECKPOINT_PATH))
    seen = 0
    for sleeve in rc.CHECKPOINTED_SLEEVES:
        for inst in tp.SLEEVE_INSTRUMENTS.get(sleeve, ()):
            e = rc.get_entry(payload, "track1_candidate", sleeve, inst)
            assert e, (sleeve, inst)
            for k in ("route", "sleeve", "last_day", "fingerprint", "params",
                      "params_hash", "data_source", "pos"):
                assert k in e, (sleeve, inst, k)
            assert e["route"] == "track1_candidate"
            assert e["fingerprint"] and ":" in e["fingerprint"]
            assert e["params_hash"]
            seen += 1
    assert seen == len(CROSS_DAY_INSTS)


# ══════════════════════════════════════════════════════════════════════════════
# D. the round trip — the claim the whole stage exists to make
# ══════════════════════════════════════════════════════════════════════════════

def test_every_written_entry_is_accepted_by_the_real_resume_check(tmp_path, real_frames,
                                                                  data_paths):
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    ck = str(tmp_path / acc.CHECKPOINT_PATH)
    checked = 0
    for sleeve in rc.CHECKPOINTED_SLEEVES:
        for inst in tp.SLEEVE_INSTRUMENTS.get(sleeve, ()):
            res = boot.accepts(ck, sleeve=sleeve, inst=inst, frame=real_frames[inst],
                               regime_csv="spy_daily_live.csv", data_path=data_paths[inst],
                               fill_law=tp.LIVE_FILL_LAW)
            assert type(res).__name__ == "Resumed", (sleeve, inst, res)
            checked += 1
    assert checked == len(CROSS_DAY_INSTS)


def test_the_derived_day_makes_the_spliced_frame_and_the_parquet_interchangeable(
        tmp_path, real_frames, data_paths):
    """This test was written to assert the opposite, and the data corrected it.

    The claim it started as — *a checkpoint written from the joined live frame would be
    refused* — is true only under the CUT-day rule, which is what test A above measures.
    Under the last-complete-day rule the appended bars sit ABOVE the cut, so both frames hash
    the same prefix and a checkpoint written from either one resumes.

    That is worth pinning rather than quietly dropping: it means reusing the frames already
    in the slot's memory WOULD have been safe, and reloading the parquet is a choice made for
    other reasons — the parquet is what the resume path reads, the closing slot only holds
    its own sleeve's instruments, and 6s against 221s of headroom buys the simpler seam. If
    this test ever goes red, the join has started touching history below the cut and the
    choice stops being a preference.
    """
    from global_index.replay_checkpoint import fingerprint
    spliced = {}
    for inst, df in real_frames.items():
        extra = df.tail(1).copy()
        extra.index = pd.DatetimeIndex([df.index.max() + pd.Timedelta(minutes=1)])
        if df.index.tz is not None and extra.index.tz is None:
            extra.index = extra.index.tz_localize(df.index.tz)
        spliced[inst] = pd.concat([df, extra])

    for inst, df in real_frames.items():
        d = R.last_complete_day(df)
        assert fingerprint(spliced[inst], d) == fingerprint(df, d), inst
        # and through the CUT day they differ, which is test A's point restated per instrument
        assert fingerprint(spliced[inst], pd.Timestamp(DAY)) != fingerprint(df, pd.Timestamp(DAY))

    write_ck(tmp_path, frames=spliced, book_state=a_book())
    res = boot.accepts(str(tmp_path / acc.CHECKPOINT_PATH), sleeve="roska4_swing", inst="MES",
                       frame=real_frames["MES"], regime_csv="spy_daily_live.csv",
                       data_path=data_paths["MES"], fill_law=tp.LIVE_FILL_LAW)
    assert type(res).__name__ == "Resumed", res


def test_a_checkpoint_that_named_the_cut_day_would_be_refused_after_the_next_append(
        tmp_path, real_frames, data_paths):
    """The rule that was NOT adopted, kept as a live counterfactual.

    `checkpoint_entries` without `last_day_by_inst` uses the book's cut day, which is what
    the bootstrap path has always done and is correct there. Written at a window close it
    produces an entry the next daily append invalidates.
    """
    state = a_book()
    entries = boot.checkpoint_entries(state, frames=real_frames,
                                      regime_csv="spy_daily_live.csv",
                                      data_paths=data_paths, fill_law=tp.LIVE_FILL_LAW)
    rc.save_route(entries, route="track1_candidate",
                  path=str(tmp_path / acc.CHECKPOINT_PATH))

    df = real_frames["MES"]
    tail = df.index.max()
    extra = pd.concat([df.tail(1)] * 300)
    extra.index = pd.DatetimeIndex([tail + pd.Timedelta(minutes=k + 1) for k in range(300)])
    appended = pd.concat([df, extra])

    res = boot.accepts(str(tmp_path / acc.CHECKPOINT_PATH), sleeve="roska4_swing", inst="MES",
                       frame=appended, regime_csv="spy_daily_live.csv",
                       data_path=data_paths["MES"], fill_law=tp.LIVE_FILL_LAW)
    assert type(res).__name__ == "Refusal", res
    assert res.code == rc.FINGERPRINT_ROWCOUNT, res


def test_a_position_survives_the_round_trip(tmp_path, real_frames, data_paths):
    write_ck(tmp_path, frames=real_frames,
             book_state=a_book(positions=[an_open_position()]))
    res = boot.accepts(str(tmp_path / acc.CHECKPOINT_PATH), sleeve="roska4_swing", inst="MES",
                       frame=real_frames["MES"], regime_csv="spy_daily_live.csv",
                       data_path=data_paths["MES"], fill_law=tp.LIVE_FILL_LAW)
    assert type(res).__name__ == "Resumed", res
    assert res.pos is not None, "the open position did not reach the checkpoint"


# ══════════════════════════════════════════════════════════════════════════════
# E. the acceptance contract
# ══════════════════════════════════════════════════════════════════════════════

def test_1_quiet_complete_window_with_an_empty_book_passes(tmp_path, real_frames):
    build_window(tmp_path)
    write_ck(tmp_path, frames={}, book_state=a_book())
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK and c["code"] == acc.CK_OK, c
    assert c["entries"] is False
    assert judge(tmp_path)["verdict"] == acc.AUDIT_PASS


def test_2_complete_window_with_an_open_position_and_frames_passes(tmp_path, real_frames):
    build_window(tmp_path)
    write_ck(tmp_path, frames=real_frames, book_state=a_book(positions=[an_open_position()]))
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK, c
    assert c["entries"] is True
    assert c["open_positions"] == 1
    assert judge(tmp_path)["verdict"] == acc.AUDIT_PASS


def test_3_complete_window_with_an_open_position_and_no_frames_fails_closed(tmp_path):
    build_window(tmp_path)
    write_ck(tmp_path, frames={}, book_state=a_book(positions=[an_open_position()]))
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL
    assert c["code"] == acc.CK_ENTRIES_MISSING_FOR_OPEN_BOOK, c
    r = judge(tmp_path)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_CHECKPOINT_ENTRIES_MISSING_FOR_OPEN_BOOK in r["reasons"], r["reasons"]


def test_the_mirror_disagreement_also_fails_closed(tmp_path, real_frames):
    """Entries carry a position, the book says flat. Written in one call; they cannot differ."""
    build_window(tmp_path)
    write_ck(tmp_path, frames=real_frames, book_state=a_book(positions=[an_open_position()]))
    (tmp_path / acc.CHECKPOINT_BOOK_PATH).write_text(json.dumps(a_book()), encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["code"] == acc.CK_BOOK_DISAGREES_WITH_ENTRIES, c
    assert acc.R_CHECKPOINT_BOOK_DISAGREEMENT in judge(tmp_path)["reasons"]


def test_4_the_reader_rejects_a_flat_schema_1_payload(tmp_path):
    p = tmp_path / acc.CHECKPOINT_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                             "cut_instant": f"{DAY}T15:55:00", "sleeves": {}}),
                 encoding="utf-8")
    assert rc.load(str(p)) == {}, "the route module now accepts the invented shape"
    assert acc.checkpoint_check(tmp_path, DAY)["code"] == acc.CK_UNREADABLE


@pytest.mark.parametrize("break_it,code", [
    ("no_book", "day_unverifiable"),
    ("wrong_day", "wrong_day"),
    ("undated", "day_unverifiable"),
    ("corrupt", "day_unverifiable"),
])
def test_5_a_book_that_cannot_date_the_checkpoint_fails_closed(tmp_path, real_frames,
                                                               break_it, code):
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    bk = tmp_path / acc.CHECKPOINT_BOOK_PATH
    if break_it == "no_book":
        bk.unlink()
    elif break_it == "wrong_day":
        bk.write_text(json.dumps(a_book(cut_day="2026-08-19")), encoding="utf-8")
    elif break_it == "undated":
        bk.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate"}),
                      encoding="utf-8")
    else:
        bk.write_text("{ truncated", encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.FAIL and c["code"] == code, c


def test_a_route_mismatch_still_fails(tmp_path, real_frames):
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    (tmp_path / acc.CHECKPOINT_PATH).unlink()
    rc.save_route({}, route="legacy_r4", path=str(tmp_path / acc.CHECKPOINT_PATH))
    assert acc.checkpoint_check(tmp_path, DAY)["code"] == acc.CK_WRONG_ROUTE


def test_6_an_incomplete_window_produces_no_usable_checkpoint_and_is_not_asked_for_one(tmp_path,
                                                                                       real_frames):
    all_slots = [s for s in ts.TRACK1_SLOTS if s.sleeve == "roska4_swing"]
    build_window(tmp_path, outcome="incomplete", slots=all_slots[:10])
    r = judge(tmp_path)
    assert r["verdict"] == acc.AUDIT_FAIL
    assert acc.R_COVERAGE_INCOMPLETE in r["reasons"]
    assert r["checkpoint"]["expected"] is False, (
        "an incomplete window must not even be asked for a checkpoint")
    assert not any(x.startswith("checkpoint_") for x in r["reasons"]), r["reasons"]


def test_a_history_claim_from_the_future_fails(tmp_path, real_frames):
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    p = tmp_path / acc.CHECKPOINT_PATH
    payload = json.loads(p.read_text(encoding="utf-8"))
    for s in payload["routes"]["track1_candidate"]["sleeves"].values():
        for e in (s.get("instruments") or {}).values():
            e["last_day"] = "2026-08-27"
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert acc.checkpoint_check(tmp_path, DAY)["code"] == acc.CK_WRONG_DAY


def test_a_history_claim_older_than_the_allowance_fails(tmp_path, real_frames):
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    p = tmp_path / acc.CHECKPOINT_PATH
    payload = json.loads(p.read_text(encoding="utf-8"))
    for s in payload["routes"]["track1_candidate"]["sleeves"].values():
        for e in (s.get("instruments") or {}).values():
            e["last_day"] = "2026-08-01"
    p.write_text(json.dumps(payload), encoding="utf-8")
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["code"] == acc.CK_HISTORY_STALE, c
    assert c["history_lag_days"] > acc.CHECKPOINT_MAX_HISTORY_LAG_DAYS


def test_the_real_writers_lag_is_inside_the_allowance(tmp_path, real_frames):
    """The rule must not fail the artefact the writer actually produces."""
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    c = acc.checkpoint_check(tmp_path, DAY)
    assert c["status"] == acc.OK, c
    assert c["history_lag_days"] <= acc.CHECKPOINT_MAX_HISTORY_LAG_DAYS


def test_every_failing_code_maps_to_a_reason():
    for code in (acc.CK_MISSING, acc.CK_UNREADABLE, acc.CK_WRONG_ROUTE, acc.CK_WRONG_DAY,
                 acc.CK_DAY_UNVERIFIABLE, acc.CK_ENTRIES_MISSING_FOR_OPEN_BOOK,
                 acc.CK_BOOK_DISAGREES_WITH_ENTRIES, acc.CK_HISTORY_STALE):
        assert code in acc.CHECKPOINT_REASON_BY_CODE, code
    assert acc.CK_OK not in acc.CHECKPOINT_REASON_BY_CODE
    assert len(set(acc.CHECKPOINT_REASON_BY_CODE.values())) == \
        len(acc.CHECKPOINT_REASON_BY_CODE)


# ══════════════════════════════════════════════════════════════════════════════
# F. nothing else moved
# ══════════════════════════════════════════════════════════════════════════════

def test_7_the_legacy_schema_1_checkpoint_module_is_untouched():
    from global_index import replay_checkpoint as v1
    assert v1.SCHEMA == 1
    assert rc.SCHEMA == 2
    assert v1.DEFAULT_PATH != rc.DEFAULT_PATH
    assert not hasattr(v1, "save_route"), "the v1 module grew a v2 writer"


def test_7b_checkpoint_entries_without_the_new_argument_is_unchanged(real_frames, data_paths):
    """The bootstrap path has always passed complete history. It must be byte-identical."""
    state = a_book()
    old_style = boot.checkpoint_entries(state, frames=real_frames,
                                        regime_csv="spy_daily_live.csv",
                                        data_paths=data_paths, fill_law=tp.LIVE_FILL_LAW)
    explicit = boot.checkpoint_entries(state, frames=real_frames,
                                       regime_csv="spy_daily_live.csv",
                                       data_paths=data_paths, fill_law=tp.LIVE_FILL_LAW,
                                       last_day_by_inst=None)
    assert old_style == explicit
    # and it uses the CUT day, as it always did
    for per in old_style.values():
        for e in per.values():
            assert e["last_day"] == DAY, e


def test_8_the_strategy_identity_is_unaffected(real_frames, data_paths, tmp_path):
    """The identity hash is a property of the settings and the data path, not of when or
    whether a checkpoint was written."""
    before = {(s, i): tp.sleeve_identity(s, i, regime_csv="spy_daily_live.csv",
                                         data_path=data_paths[i], fill_law=tp.LIVE_FILL_LAW)
              for s in rc.CHECKPOINTED_SLEEVES for i in tp.SLEEVE_INSTRUMENTS.get(s, ())}
    write_ck(tmp_path, frames=real_frames, book_state=a_book())
    after = {(s, i): tp.sleeve_identity(s, i, regime_csv="spy_daily_live.csv",
                                        data_path=data_paths[i], fill_law=tp.LIVE_FILL_LAW)
             for s in rc.CHECKPOINTED_SLEEVES for i in tp.SLEEVE_INSTRUMENTS.get(s, ())}
    assert before == after
    # and what landed in the checkpoint is that same hash, not a recomputation
    payload = rc.load(str(tmp_path / acc.CHECKPOINT_PATH))
    for (s, i), (_readable, phash) in before.items():
        assert rc.get_entry(payload, "track1_candidate", s, i)["params_hash"] == phash


def test_8b_the_writer_imports_no_signal_or_rule_module():
    """A checkpoint writer that reached into the decision layer could change what trades."""
    import ast
    src = (REPO / "global_index" / "run_live_day_track1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "checkpoint_frames")
    imported = {a.name for n in ast.walk(fn) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = [m for m in imported
                 if "signal" in m or "normal_r4" in m or "calm" in m or "gates" in m]
    assert forbidden == [], forbidden


# ══════════════════════════════════════════════════════════════════════════════
# G. the runtime budget — measured on the real store, not on a fixture
# ══════════════════════════════════════════════════════════════════════════════

def test_9_the_reload_fits_the_slot_budget(data_paths):
    t0 = time.perf_counter()
    frames, why = R.checkpoint_frames(data_paths)
    took = time.perf_counter() - t0
    if why:
        pytest.skip(f"parquet store not readable here: {why}")
    rows = sum(len(f) for f in frames.values())
    assert rows > 5_000_000, rows
    ceiling = acc.RUNTIME_P95_REQUIRED_S
    assert took < ceiling * 0.25, (
        f"loading {len(frames)} frames ({rows:,} rows) took {took:.1f}s, over a quarter of "
        f"the {ceiling:.0f}s slot ceiling — the close-time budget claim no longer holds")
    print(f"\n  checkpoint_frames: {took:.2f}s for {len(frames)} frames, {rows:,} rows "
          f"({100*took/ceiling:.1f}% of the {ceiling:.0f}s ceiling)")


def test_9b_the_whole_write_fits_the_slot_budget(tmp_path, real_frames):
    t0 = time.perf_counter()
    out = write_ck(tmp_path, frames=None, book_state=a_book())
    took = time.perf_counter() - t0
    assert out["entry_count"] == len(CROSS_DAY_INSTS)
    assert took < acc.RUNTIME_P95_REQUIRED_S * 0.25, f"{took:.1f}s"
    print(f"\n  write_route_checkpoint (loading frames): {took:.2f}s")


# ══════════════════════════════════════════════════════════════════════════════
# H. nothing real was written
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", _PRODUCTION)
def test_no_production_artefact_was_written_by_this_run(name):
    p = REPO / name
    if not p.exists():
        return
    assert p.stat().st_mtime < _IMPORTED_AT, (
        f"{name} was written DURING this test run — every fixture must be under tmp_path")


def test_no_runtime_evidence_directory_was_written_by_this_run():
    """Scoped to what THIS suite could write, not to the whole tree.

    Stage 5ZL: the first version scanned every file under the runtime root for an mtime newer
    than this process, which is only a statement about tests when nothing else is running. It
    went red at 01:45 ET on 2026-08-26 because the live NKD window was open and its slots were
    writing explanations, coverage and timing — the system doing its job. mtime cannot tell a
    concurrent live write from a test write, so the scan asks only about the paths this suite
    touches; the parametrized test above covers the two artefacts the writer produces.
    """
    root = REPO / "global_index" / "track1_runtime"
    if not root.exists():
        return
    mine = ("trade_log.track1.jsonl", "regime_verify")
    stray = [str(p) for p in root.rglob("*")
             if p.is_file() and p.stat().st_mtime >= _IMPORTED_AT
             and any(m in str(p) for m in mine)]
    assert stray == [], stray


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
