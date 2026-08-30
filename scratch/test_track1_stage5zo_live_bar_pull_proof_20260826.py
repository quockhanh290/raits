"""Stage 5ZO — a slot that decided must be able to show what it looked at.

Nothing here writes into the runtime tree; every observation file is under `tmp_path`, and the
last part proves it by mtime scoped to the paths this suite touches.

The gap, found in the evidence rather than in the code
-------------------------------------------------------
The 2026-08-26 night window passed its audit — twenty-two slots, all decided, no candidates —
and the explanation row for its last slot carried `bar_timestamps: []` and `data_time: null`.
The ledger proved the slot DECIDED; nothing proved WHAT IT LOOKED AT. On a route that has never
traded, a slot that fetched nothing and one that fetched a thousand bars produce the same row.
"""
from __future__ import annotations

import ast
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import track1_data_observation as dobs        # noqa: E402

REPO = Path(r"d:\raits")
_IMPORTED_AT = time.time()
DAY = "2026-08-26"


# ══════════════════════════════════════════════════════════════════════════════
# fakes shaped like the real objects the join produces
# ══════════════════════════════════════════════════════════════════════════════

class FakeReport:
    def __init__(self, code="ok", **kw):
        self.d = {"code": code, "frozen_rows": 2_042_000, "live_rows_offered": 1200,
                  "live_rows_appended": 1186, "frozen_last": "2026-08-25 13:45:00",
                  "live_first_kept": "2026-08-25 13:46:00", "notices": [], "detail": ""}
        self.d.update(kw)
        self.live_rows_appended = self.d["live_rows_appended"]

    def as_dict(self):
        return dict(self.d)


class FakeJoined:
    """Same surface as `track1_live_source.JoinedFrame` — the writer only reads `as_dict`."""

    def __init__(self, inst="MNKD", rows=1186, provider="ibkr", code="ok",
                 overlap=37, last="2026-08-26 02:55:00", **kw):
        import pandas as pd
        self.inst, self.provider, self.provider_rows = inst, provider, rows
        self.overlap_checked, self.dropped_columns = overlap, ("average", "barcount")
        self.report = FakeReport(code=code, **kw)
        idx = pd.date_range(end=pd.Timestamp(last), periods=max(rows, 1), freq="1min")
        self.frame = pd.DataFrame({"close": range(len(idx))}, index=idx)

    @property
    def offered_but_unused(self):
        return max(0, self.provider_rows - self.report.live_rows_appended)

    def as_dict(self):
        return {"inst": self.inst, "provider": self.provider, "rows": int(len(self.frame)),
                "provider_rows": self.provider_rows,
                "offered_but_unused": self.offered_but_unused,
                "overlap_checked": self.overlap_checked,
                "dropped_columns": list(self.dropped_columns),
                **self.report.as_dict()}


def a_row(*, decided=True, candidates=0, insts=None, slot_id="TRACK1_NKD_0255") -> dict:
    insts = insts if insts is not None else [dobs.instrument_row(
        FakeJoined(), history_symbol="NKD", tradable_symbol="MNK",
        data_path="global_index/data/NKD_continuous_1m_8y.parquet",
        data_identity="global_index/data/NKD_continuous_1m_8y.parquet:abc123")]
    return dobs.build_row(session_date=DAY, sleeve="global_nkd", slot_id=slot_id,
                          mode="shadow_live", instruments=insts,
                          decision_reached=decided, decision_reason="decided",
                          candidate_count=candidates)


# ══════════════════════════════════════════════════════════════════════════════
# A. what a row proves
# ══════════════════════════════════════════════════════════════════════════════

def test_1_a_decided_no_signal_slot_writes_a_row_proving_the_pull(tmp_path):
    dobs.record(a_row(decided=True, candidates=0), root=tmp_path, day=DAY)
    rows, bad = dobs.read(root=tmp_path, day=DAY)
    assert bad == [] and len(rows) == 1
    r = rows[0]
    assert r["decision_reached"] is True and r["candidate_count"] == 0
    assert r["outcome"] == dobs.DECIDED
    i = r["instruments"][0]
    for field in ("inst", "history_symbol", "tradable_symbol", "provider", "data_path",
                  "data_identity", "live_rows_fetched", "live_first_kept_ts",
                  "frozen_rows", "frozen_last_ts", "overlap_checked_rows", "overlap_result",
                  "splice_result", "dropped_open_final_bar", "final_frame_last_ts",
                  "final_frame_rows"):
        assert field in i, field


def test_2_a_slot_that_found_a_candidate_still_writes_the_same_proof(tmp_path):
    dobs.record(a_row(decided=True, candidates=3), root=tmp_path, day=DAY)
    rows, _ = dobs.read(root=tmp_path, day=DAY)
    assert rows[0]["candidate_count"] == 3
    assert rows[0]["instruments"][0]["live_rows_fetched"] == 1186


def test_the_three_identities_are_kept_apart():
    """Runner name, history symbol, order symbol. They have already diverged once."""
    i = dobs.instrument_row(FakeJoined(inst="MNKD"), history_symbol="NKD",
                            tradable_symbol="MNK")
    assert (i["inst"], i["history_symbol"], i["tradable_symbol"]) == ("MNKD", "NKD", "MNK")


def test_the_row_carries_the_provider_the_join_reported_not_a_guess():
    i = dobs.instrument_row(FakeJoined(provider="replay"))
    assert i["provider"] == "replay"


def test_the_splice_and_overlap_outcomes_are_the_codes_the_join_produced():
    ok = dobs.instrument_row(FakeJoined(code="ok"))
    assert ok["splice_result"] == "ok" and ok["overlap_result"] == "ok"
    assert ok["overlap_checked_rows"] == 37
    trimmed = dobs.instrument_row(FakeJoined(code="overlap_trimmed",
                                             notices=["trimmed 2"], detail="two bars"))
    assert trimmed["splice_result"] == "overlap_trimmed"
    assert trimmed["splice_notices"] == ["trimmed 2"]


def test_5_an_unknown_is_an_explicit_null_with_a_reason_never_an_omission():
    i = dobs.instrument_row(FakeJoined())
    assert i["dropped_open_final_bar"] is None
    assert i["dropped_open_final_bar_null_reason"] == dobs.NOT_REPORTED_BY_JOIN


def test_a_join_that_cannot_describe_itself_is_recorded_as_such():
    class Broken:
        inst = "MES"
        def as_dict(self): raise RuntimeError("no")
    i = dobs.instrument_row(Broken())
    assert i["splice_result"] is None
    assert i["splice_result_null_reason"] == dobs.NO_FRAME
    assert "RuntimeError" in i["error"]


# ══════════════════════════════════════════════════════════════════════════════
# B. refusals
# ══════════════════════════════════════════════════════════════════════════════

def test_3_a_refused_live_frame_still_writes_an_observation_row(tmp_path):
    """'Nobody looked' and 'we looked and were refused' call for different actions."""
    dobs.record(dobs.refusal_row(session_date=DAY, sleeve="global_nkd",
                                 slot_id="TRACK1_NKD_0110", mode="shadow_live",
                                 error_code="overlap_mismatch", error="two bars disagree"),
                root=tmp_path, day=DAY)
    rows, _ = dobs.read(root=tmp_path, day=DAY)
    r = rows[0]
    assert r["outcome"] == dobs.REFUSED
    assert r["decision_reached"] is False
    assert r["error_code"] == "overlap_mismatch"
    assert r["instruments"] == []


def test_a_refusal_summary_counts_by_reason(tmp_path):
    for code in ("overlap_mismatch", "overlap_mismatch", "splice_refused"):
        dobs.record(dobs.refusal_row(session_date=DAY, sleeve="global_nkd", slot_id=code,
                                     mode="shadow_live", error_code=code, error=""),
                    root=tmp_path, day=DAY)
    rows, _ = dobs.read(root=tmp_path, day=DAY)
    s = dobs.summary(rows)
    assert s["refusals_by_reason"] == {"overlap_mismatch": 2, "splice_refused": 1}


# ══════════════════════════════════════════════════════════════════════════════
# C. no bar arrays, no prices
# ══════════════════════════════════════════════════════════════════════════════

def test_6_the_row_contains_no_raw_bar_array(tmp_path):
    """The evidence is provenance, not prices. A row that embedded bars would grow with the
    market and would put price data into a stream whose purpose is proof of a fetch."""
    dobs.record(a_row(), root=tmp_path, day=DAY)
    raw = dobs.path_for(tmp_path, DAY).read_text(encoding="utf-8")
    payload = json.loads(raw.splitlines()[0])

    def scalars_only(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                scalars_only(v, f"{path}.{k}")
        elif isinstance(node, list):
            assert len(node) < 20, f"{path} holds {len(node)} items — looks like bar data"
            for j, v in enumerate(node):
                scalars_only(v, f"{path}[{j}]")
        else:
            assert node is None or isinstance(node, (str, int, float, bool)), path

    scalars_only(payload)
    assert len(raw) < 4000, f"one row is {len(raw)} bytes — something large is embedded"


def test_the_writer_module_never_touches_a_price_column():
    tree = ast.parse((REPO / "global_index" / "track1_data_observation.py").read_text(
        encoding="utf-8"))
    lits = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    for price in ("open", "high", "low", "close", "volume"):
        assert not any(l == price for l in lits), price


# ══════════════════════════════════════════════════════════════════════════════
# D. it computes nothing about the strategy
# ══════════════════════════════════════════════════════════════════════════════

def test_7_the_writer_imports_no_signal_rule_or_detector_module():
    tree = ast.parse((REPO / "global_index" / "track1_data_observation.py").read_text(
        encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    bad = [m for m in mods
           if any(k in m for k in ("signal", "normal_r4", "calm", "sleeves", "detector",
                                   "params"))]
    assert bad == [], bad


def test_7b_the_slot_writes_the_row_after_the_ledger_row(tmp_path):
    """Ordering is the safety property: the ledger row is what the audit counts, and a
    diagnostics failure must never be the reason a slot loses it."""
    src = (REPO / "global_index" / "run_live_day_track1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    ledger = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
              and getattr(n.func, "attr", "") == "slot_observed"]
    obs = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
           and getattr(n.func, "id", "") == "_write_data_observation"]
    assert ledger and obs, (ledger, obs)
    assert min(obs) > max(ledger), "the observation row is written before the ledger row"


def test_7c_the_observation_write_cannot_take_the_slot_down():
    """Wrapped, like the signal diagnostics beside it."""
    src = (REPO / "global_index" / "run_live_day_track1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    guarded = [t for t in ast.walk(fn) if isinstance(t, ast.Try)
               and any(isinstance(n, ast.Call) and getattr(n.func, "id", "") ==
                       "_write_data_observation" for n in ast.walk(t))]
    assert guarded, "the observation write is not wrapped"


def test_7d_the_writer_reads_the_join_and_recomputes_nothing():
    """No feature, no detector, no arithmetic on prices — it reads `as_dict` and an index."""
    tree = ast.parse((REPO / "global_index" / "track1_data_observation.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "instrument_row")
    calls = {getattr(n.func, "attr", getattr(n.func, "id", ""))
             for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "as_dict" in calls
    assert not (calls & {"mean", "std", "rolling", "ewm", "resample", "label_regimes"}), calls


def test_the_slot_writer_produces_a_real_row_end_to_end(tmp_path):
    """The wiring itself, not just the schema. Without this the writer is a mechanism nobody
    has watched run — which is the trap this project has already paid for twice."""
    from global_index import run_live_day_track1 as R

    R._write_data_observation(
        sleeve="global_nkd", day=DAY, slot_id="TRACK1_NKD_0255",
        joined={"MNKD": FakeJoined(inst="MNKD")}, refusal=None,
        decided=True, reason="decided", candidates=0,
        data_paths={"MNKD": "global_index/data/NKD_continuous_1m_8y.parquet"},
        root=str(tmp_path))

    rows, bad = dobs.read(root=tmp_path, day=DAY)
    assert bad == [] and len(rows) == 1, (rows, bad)
    r = rows[0]
    assert r["slot_id"] == "TRACK1_NKD_0255" and r["decision_reached"] is True
    i = r["instruments"][0]
    assert (i["inst"], i["history_symbol"], i["tradable_symbol"]) == ("MNKD", "NKD", "MNK")
    assert i["live_rows_fetched"] == 1186 and i["splice_result"] == "ok"
    # the identity is the same `<path>:<sha256>` shape the explanation record already carries
    assert i["data_identity"].startswith("global_index/data/NKD_continuous_1m_8y.parquet:")


def test_the_slot_writer_records_a_refusal_end_to_end(tmp_path):
    from global_index import run_live_day_track1 as R
    R._write_data_observation(
        sleeve="global_nkd", day=DAY, slot_id="TRACK1_NKD_0110", joined=None,
        refusal=("overlap_mismatch", "two bars disagree"), decided=False,
        reason="live_frame_refused", candidates=0, data_paths={}, root=str(tmp_path))
    rows, _ = dobs.read(root=tmp_path, day=DAY)
    assert rows[0]["outcome"] == dobs.REFUSED
    assert rows[0]["error_code"] == "overlap_mismatch"


def test_a_slot_that_never_reached_either_writes_nothing(tmp_path):
    """Rule three: if the slot never spawns or never got as far as a frame, no row. A row
    claiming an observation nobody made is worse than no row."""
    from global_index import run_live_day_track1 as R
    R._write_data_observation(sleeve="global_nkd", day=DAY, slot_id="x", joined=None,
                              refusal=None, decided=False, reason="", candidates=0,
                              data_paths={}, root=str(tmp_path))
    assert dobs.read(root=tmp_path, day=DAY) == ([], [])


# ══════════════════════════════════════════════════════════════════════════════
# E. the audit
# ══════════════════════════════════════════════════════════════════════════════

def _build_window(root: Path, *, slots, decided=True, day=DAY, sleeve="global_nkd"):
    from global_index import track1_shadow_acceptance as acc
    cov = [{"event": "window_open", "sleeve": sleeve, "date": day,
            "route": "track1_candidate", "expected_slots": len(slots)}]
    for i, sid in enumerate(slots):
        cov.append({"event": "slot_observed", "sleeve": sleeve, "date": day, "slot_id": sid,
                    "seq": i, "decided": decided, "candidates": 0, "explained": 0,
                    "reason": "decided" if decided else "gate_refused",
                    "detail": "" if decided else "stale", "route": "track1_candidate"})
    cov.append({"event": "window_closed", "sleeve": sleeve, "date": day, "outcome": "complete",
                "signal": "no_signal", "observed_slots": len(slots),
                "expected_slots": len(slots), "route": "track1_candidate"})
    d = root / acc.COVERAGE_DIR
    d.mkdir(parents=True, exist_ok=True)
    (d / f"window_coverage_{day.replace('-','')}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in cov), encoding="utf-8")
    t = root / acc.TIMING_DIR
    t.mkdir(parents=True, exist_ok=True)
    (t / f"slot_timing_{day.replace('-','')}.jsonl").write_text(
        "".join(json.dumps({"ts": f"{day}T06:00:00+00:00", "route": "track1_candidate",
                            "slot_id": s, "outcome": "ok", "runtime_s": 30.0,
                            "phases": {}}) + "\n" for s in slots), encoding="utf-8")
    # A complete window also writes its checkpoint and book, and without them the verdict is
    # FAIL for a reason that has nothing to do with this stage — which would make every
    # assertion below about the wrong thing.
    from global_index import route_checkpoint as _rc
    _rc.save_route({}, route="track1_candidate", path=str(root / acc.CHECKPOINT_PATH))
    bk = root / acc.CHECKPOINT_BOOK_PATH
    bk.parent.mkdir(parents=True, exist_ok=True)
    bk.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                              "window": "live", "cut_instant": f"{day}T02:55:01-04:00",
                              "cur_day": day, "equity": 0.0, "positions": []}),
                  encoding="utf-8")


def _judge(root, sleeve="global_nkd", day=DAY):
    from global_index import track1_shadow_acceptance as acc
    return acc.evaluate_sleeve(day, sleeve, root, now_et=f"{day} 23:00",
                               scheduler_started_et=f"{day} 00:30:00")


def test_4_a_decided_slot_missing_its_observation_is_caught(tmp_path):
    from global_index import track1_shadow_acceptance as acc
    slots = [s.id for s in __import__("global_index.track1_slots", fromlist=["x"]).TRACK1_SLOTS
             if s.sleeve == "global_nkd"]
    _build_window(tmp_path, slots=slots)
    # one slot proves its data, the rest do not
    dobs.record(a_row(slot_id=slots[0]), root=tmp_path, day=DAY)
    r = _judge(tmp_path)
    assert acc.R_DECIDED_WITHOUT_DATA_OBSERVATION in r["reasons"], r["reasons"]
    assert r["verdict"] == acc.AUDIT_WARN, r["verdict"]
    d = r["data_observation"]
    assert d["schema_state"] == "present"
    assert d["records"] == 1
    assert len(d["slots_without_data_observation"]) == len(slots) - 1


def test_4b_every_decided_slot_proving_its_data_leaves_no_warning(tmp_path):
    from global_index import track1_shadow_acceptance as acc
    slots = [s.id for s in __import__("global_index.track1_slots", fromlist=["x"]).TRACK1_SLOTS
             if s.sleeve == "global_nkd"]
    _build_window(tmp_path, slots=slots)
    for sid in slots:
        dobs.record(a_row(slot_id=sid), root=tmp_path, day=DAY)
    r = _judge(tmp_path)
    assert acc.R_DECIDED_WITHOUT_DATA_OBSERVATION not in r["reasons"], r["reasons"]
    assert r["data_observation"]["slots_without_data_observation"] == []
    assert r["data_observation"]["live_rows_fetched_total"] == 1186 * len(slots)
    assert r["data_observation"]["providers"] == {"ibkr": len(slots)}


def test_5b_a_window_with_no_observation_stream_is_pre_schema_not_accused(tmp_path):
    """A day recorded before this writer existed is a fact about the software."""
    from global_index import track1_shadow_acceptance as acc
    slots = [s.id for s in __import__("global_index.track1_slots", fromlist=["x"]).TRACK1_SLOTS
             if s.sleeve == "global_nkd"]
    _build_window(tmp_path, slots=slots)
    r = _judge(tmp_path)
    assert acc.R_DECIDED_WITHOUT_DATA_OBSERVATION not in r["reasons"], r["reasons"]
    assert r["data_observation"]["schema_state"] == dobs.PRE_SCHEMA
    assert r["data_observation"]["slots_without_data_observation"] == []
    assert r["data_observation"]["decided_slots"] == len(slots)


def test_the_missing_observation_is_a_warning_not_a_failure(tmp_path):
    """Justified: the ledger row already proves the slot ran and decided. A missing
    observation weakens the evidence without contradicting it, and making it fatal would fail
    every window recorded before this stage existed."""
    from global_index import track1_shadow_acceptance as acc
    assert acc._worse(acc.AUDIT_PASS, acc.AUDIT_WARN) == acc.AUDIT_WARN
    assert acc.AUDIT_WARN != acc.AUDIT_FAIL


def test_the_live_2026_08_26_window_is_classified_not_accused():
    """The real evidence on this machine: 22 decided slots, no observation stream."""
    from global_index import track1_shadow_acceptance as acc
    r = acc.evaluate_sleeve("2026-08-26", "global_nkd", REPO,
                            scheduler_started_et="2026-08-25 22:03:38")
    d = r["data_observation"]
    if d["records"]:
        pytest.skip("this machine has already recorded observations for that day")
    assert d["schema_state"] == dobs.PRE_SCHEMA
    assert d["decided_slots"] > 0
    assert acc.R_DECIDED_WITHOUT_DATA_OBSERVATION not in r["reasons"]
    assert r["verdict"] == acc.AUDIT_PASS, "the audit was downgraded for a pre-schema day"


# ══════════════════════════════════════════════════════════════════════════════
# F. the panel line
# ══════════════════════════════════════════════════════════════════════════════

def test_9_the_panel_line_has_three_shapes():
    ok = dobs.operator_line(a_row())
    assert ok.startswith("Data: ") and "IBKR" in ok and "NKD" in ok
    assert "1186 live bars checked" in ok and "splice OK" in ok
    assert "02:55 ET" in ok

    missing = dobs.operator_line(None)
    assert missing == "Data proof: not recorded by this slot version"

    refused = dobs.operator_line(dobs.refusal_row(
        session_date=DAY, sleeve="global_nkd", slot_id="x", mode="shadow_live",
        error_code="overlap_mismatch", error=""))
    assert refused.startswith("Data refused:") and "overlap mismatch" in refused


def test_the_panel_line_shows_no_variable_names_or_json():
    for row in (a_row(), None, dobs.refusal_row(session_date=DAY, sleeve="s", slot_id="x",
                                                mode="shadow_live", error_code="c", error="")):
        line = dobs.operator_line(row)
        for forbidden in ("_", "{", "}", "[", "]", "live_rows", "splice_result", "None",
                          "null"):
            if forbidden == "_" and "not recorded" in line:
                continue
            assert forbidden not in line, (forbidden, line)


def test_the_panel_line_stays_short_enough_for_a_narrow_row():
    """It sits in the Operational block beside the other one-liners; a sentence that wrapped
    to three lines on a phone would push the block past the fold."""
    assert len(dobs.operator_line(a_row())) <= 90, dobs.operator_line(a_row())


def test_9b_the_job_reader_renders_the_line_for_each_state(tmp_path):
    from monitor.backend import job_journal_reader as jr
    job = {"job_id": "TRACK1_NKD_0255", "status": "completed", "duration_seconds": 30,
           "started_at": f"{DAY}T06:55:00Z", "ended_at": f"{DAY}T06:55:30Z",
           "reason": "", "events": [], "diagnostics": [], "failed_runs": 0,
           "launch_count": 1}
    for row, expect in ((a_row(), "Data: "),
                        (None, "Data proof: not recorded"),
                        (dobs.refusal_row(session_date=DAY, sleeve="global_nkd",
                                          slot_id="TRACK1_NKD_0255", mode="shadow_live",
                                          error_code="splice_refused", error=""),
                         "Data refused:")):
        op = jr._operational(dict(job), None, {}, {}, data_observation=row)
        assert any(l.startswith(expect) for l in op["lines"]), (expect, op["lines"])
        assert op["data_observation"] is row


def test_9c_the_panel_gains_no_new_section():
    """One line inside Operational, not a fourth heading for a single sentence."""
    from monitor.backend import job_journal_reader as jr
    op = jr._operational({"job_id": "TRACK1_NKD_0255", "status": "completed",
                          "duration_seconds": 30, "started_at": f"{DAY}T06:55:00Z",
                          "ended_at": f"{DAY}T06:55:30Z", "reason": "", "events": [],
                          "diagnostics": [], "failed_runs": 0, "launch_count": 1},
                         None, {}, {}, data_observation=a_row())
    assert isinstance(op["lines"], list)
    assert sum(1 for l in op["lines"] if l.startswith("Data")) == 1


# ══════════════════════════════════════════════════════════════════════════════
# G. nothing armed, nothing legacy, nothing real written
# ══════════════════════════════════════════════════════════════════════════════

def test_8_no_order_path_is_imported_or_enabled():
    for rel in ("global_index/track1_data_observation.py",):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(k in m for m in mods
                       for k in ("paper_executor", "ibkr_broker", "ib_insync")), sorted(mods)
        lits = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any("--allow-orders" in l for l in lits)


def test_orders_are_still_impossible():
    from global_index import track1_gates as g
    # Stage 5ZZZ-A. The ROSTER is no longer pinned. B1 closed in Stage 5ZZK and reopens with the
    # age of the account baseline record; REGIME_LABEL_VERIFICATION closed when its measurement
    # started passing. Naming them here pins states that change on a timer and on evidence, and
    # every such pin in this repo has gone red for a reason that had nothing to do with its test.
    #
    # What the test's NAME claims is that orders are impossible and that something MEASURED is
    # holding them. That is what it asserts.
    allowed, reasons = g.may_enable_orders()
    assert allowed is False
    ids = [r.split(":")[0] for r in reasons]
    assert "PAPER_SHADOW_EVIDENCE" in ids, ids


def test_10_the_legacy_runner_knows_nothing_about_this_stream():
    for rel in ("global_index/run_live_day.py", "global_index/run_stop_repair.py",
                "global_index/run_maxhold_exit.py", "global_index/session_report.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any("data_observation" in (m or "") for m in mods), rel


def test_no_real_observation_file_was_created():
    d = REPO / dobs.DIR
    if not d.exists():
        return
    stray = [str(p) for p in d.rglob("*")
             if p.is_file() and p.stat().st_mtime >= _IMPORTED_AT]
    assert stray == [], stray


def test_no_existing_runtime_evidence_was_rewritten():
    for name in ("global_index/track1_runtime/window_coverage",
                 "global_index/track1_runtime/slot_timing",
                 "global_index/track1_runtime/signals",
                 "global_index/track1_runtime/audits",
                 "global_index/track1_runtime/shadow/explanations"):
        d = REPO / name
        if not d.exists():
            continue
        stray = [str(p) for p in d.rglob("*")
                 if p.is_file() and p.stat().st_mtime >= _IMPORTED_AT]
        assert stray == [], stray


def test_the_preflight_record_still_holds_the_operator_restored_seven_days():
    p = REPO / "global_index" / "preflight_state.json"
    if not p.exists():
        pytest.skip("no pre-flight record on this machine")
    assert sorted(json.loads(p.read_text(encoding="utf-8"))) == [
        "2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20",
        "2026-08-21", "2026-08-24", "2026-08-25"]
