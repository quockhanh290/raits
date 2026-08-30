"""Stage 5Y — what the shadow route's explanation write path must guarantee.

The scaffold's own suite (`test_track1_explain_20260823.py`) proves the record format
refuses bad records. This file proves the WIRING: that a real shadow pass produces one
validated explanation per decision, that those rows land only under the shadow root, that
the file a row lives in is named for the row's own session date, and that the decision file
everything else reads is byte-for-byte the shape it has always been.

Every run here is relocated with `root=tmp_path`, so the suite never writes into the
directory it is auditing. That matters more than it looks: a test that writes into
`scratch/track1_shadow` cannot tell its own output from the route's, and the route's real
output is evidence somebody may be reading.

Offline: no broker, no scheduler, no orders. `run_shadow` hands the route a `NoOrderBroker`
whose `send_order` raises, and the summary records that it was never called.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from global_index import track1_explain as tx  # noqa: E402
from global_index import track1_signal_layer as sl  # noqa: E402
import global_index.run_live_day_track1 as r1  # noqa: E402

WINDOW = "vault2026"
AS_OF = "2026-08-21 15:00"


# ── one shared run, because a replay pass is the expensive part ──────────────
@pytest.fixture(scope="module")
def shadow(tmp_path_factory):
    root = tmp_path_factory.mktemp("t1y")
    summary = r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv",
                            now_et=AS_OF, root=str(root))
    return {"root": root, "summary": summary,
            "dir": root / r1.SHADOW_DIR}


def _decision_rows(shadow):
    p = shadow["dir"] / f"shadow_decisions_{WINDOW}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _explanation_files(shadow):
    return sorted((shadow["dir"] / r1.EXPLAIN_SUBDIR / WINDOW).glob("explanations_*.jsonl"))


def _explanation_rows(shadow):
    """DECISION rows only.

    Stage 5Z added one run-context NO_ACTION record per run, carrying the freshness reading
    that accepted replay decisions no longer cite. It is a row in the same files and it is
    deliberately NOT a decision, so the "one explanation per decision" comparison below
    counts decisions and `_all_rows` is used where the whole file matters.
    """
    return [r for r in _all_rows(shadow) if r["record_type"] == tx.DECISION]


def _all_rows(shadow):
    rows = []
    for f in _explanation_files(shadow):
        rows += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    return rows


# ── 1. the rows land only under the shadow root ──────────────────────────────
def test_explanations_are_written_only_under_the_shadow_directory(shadow):
    files = _explanation_files(shadow)
    assert files, "no explanation files were written at all"
    allowed = (shadow["root"] / tx.SHADOW_ROOT).resolve()
    for f in files:
        assert allowed in f.resolve().parents, f


def test_nothing_was_written_outside_the_relocated_root(shadow):
    """`root` must relocate every artifact, not half of them."""
    written = {p for p in shadow["root"].rglob("*") if p.is_file()}
    assert written, "the run wrote nothing"
    shadow_root = (shadow["root"] / tx.SHADOW_ROOT).resolve()
    outside = [str(p) for p in written if shadow_root not in p.resolve().parents]
    assert outside == [], outside


def test_the_writer_still_refuses_a_destination_outside_the_shadow_root(tmp_path):
    with pytest.raises(tx.ShadowPathRefused):
        r1.emit_explanations([], out_dir="global_index", window=WINDOW,
                             regime_csv="spy_daily_live.csv", data_paths={},
                             fill_law=tx.FILL_LAWS[0], freshness_allow=True,
                             root=str(tmp_path))


# ── 2. every written row validates ───────────────────────────────────────────
def test_every_written_explanation_validates(shadow):
    rows = _explanation_rows(shadow)
    assert rows, "no explanation rows to validate"
    bad = [(r["explain_id"], tx.validate(r)) for r in rows if tx.validate(r)]
    assert bad == [], bad[:3]


def test_rows_still_validate_after_a_json_round_trip_from_disk(shadow):
    """Read back from the file, not from the in-memory objects. The re-derivation guards
    added in Stage 5X only mean something if they hold on what actually landed."""
    rows = _explanation_rows(shadow)
    assert rows
    for row in rows:
        again = json.loads(json.dumps(row))
        assert tx.validate(again) == [], again["explain_id"]


def test_every_row_is_for_this_route_and_correctly_typed(shadow):
    rows = _all_rows(shadow)
    assert rows
    assert {r["record_type"] for r in rows} == {tx.DECISION, tx.NO_ACTION}
    assert {r["route"] for r in rows} == {tx.ROUTE}
    assert {r["stage"] for r in _explanation_rows(shadow)} == {"shadow_admission"}
    # exactly one run-context record, and it is not a decision
    ctx = [r for r in rows if r["record_type"] == tx.NO_ACTION]
    assert len(ctx) == 1 and ctx[0]["rule_ids"] == ["CONTEXT.FRESHNESS_OBSERVED"]


# ── 3. one explanation per decision ──────────────────────────────────────────
def test_explanation_count_equals_decision_count(shadow):
    dec, exp = _decision_rows(shadow), _explanation_rows(shadow)
    assert len(dec) > 0, "the window produced no decisions; this test would pass vacuously"
    assert len(exp) == len(dec), f"{len(exp)} explanations vs {len(dec)} decisions"
    assert shadow["summary"]["explanations"]["records"] == len(dec)
    assert shadow["summary"]["explanations"]["decisions"] == len(dec)


def test_every_decision_is_matched_by_identity_not_by_count(shadow):
    """Counts agreeing is not the same as the right rows being there — two streams can
    match on length and disagree on every element."""
    dec, exp = _decision_rows(shadow), _explanation_rows(shadow)
    want = sorted((d["trade_id"], d["sleeve"], d["inst"], d["verdict"]) for d in dec)
    got = sorted((e["candidate_id"], e["sleeve"], e["instrument"], e["reason_code"])
                 for e in exp)
    assert got == want


def test_explain_ids_are_unique(shadow):
    rows = _explanation_rows(shadow)
    assert rows
    ids = [r["explain_id"] for r in rows]
    assert len(set(ids)) == len(ids)


def test_a_rerun_replaces_rather_than_doubles(shadow, tmp_path):
    """The decision file is opened with "w". Append-only explanations would drift to twice
    the count on a second pass, and a count that drifts is a count nobody can check."""
    first = r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                          root=str(tmp_path))
    second = r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                           root=str(tmp_path))
    assert first["explanations"]["records"] == second["explanations"]["records"]
    on_disk = sum(
        len([l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()])
        for f in sorted((tmp_path / r1.SHADOW_DIR / r1.EXPLAIN_SUBDIR / WINDOW)
                        .glob("explanations_*.jsonl")))
    assert on_disk == second["explanations"]["rows_written"]


# ── the file naming choice ───────────────────────────────────────────────────
def test_a_file_is_named_for_the_date_of_every_row_inside_it(shadow):
    """The choice: group by each record's OWN session date, one file per date.

    A replay window spans many historical sessions, so naming one file after the run date
    would produce `explanations_20260823.jsonl` holding rows from January. This repository
    has already paid for a file named for a date it did not contain — a scheduler log named
    for the day the process started collected the next day's slots, and last night's window
    looked as if it had never run.
    """
    files = _explanation_files(shadow)
    assert files, "no files to check"
    for f in files:
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        assert rows, f"{f.name} is empty"
        stamps = {r["session_date"].replace("-", "") for r in rows}
        assert stamps == {f.stem.split("_")[-1]}, (f.name, sorted(stamps))
        # true for the run-context record as well: it is filed under the session date it
        # names, never under "whenever the run happened"


def test_the_window_gets_its_own_directory(shadow):
    """Two windows can cover the same calendar date; neither may overwrite the other."""
    assert shadow["summary"]["explanations"]["dir"].endswith(
        f"{r1.EXPLAIN_SUBDIR}/{WINDOW}")
    assert shadow["summary"]["explanations"]["session_dates"] == len(
        _explanation_files(shadow))


# ── 4. the existing decision file is unchanged ───────────────────────────────
#: The exact key set `shadow_decisions_<window>.jsonl` carried before Stage 5Y. Pinned as a
#: literal on purpose: deriving it from the writer would make the test agree with whatever
#: the writer currently does, which is the "compares a value with itself" shape.
DECISION_ROW_KEYS = {"ts", "trade_id", "sleeve", "inst", "direction", "qty", "risk",
                     "verdict", "detail", "forced_closes"}


def test_the_decision_file_schema_is_unchanged(shadow):
    rows = _decision_rows(shadow)
    assert rows, "no decision rows"
    for row in rows:
        assert set(row) == DECISION_ROW_KEYS, sorted(set(row) ^ DECISION_ROW_KEYS)


def test_the_decision_file_carries_no_explanation_field(shadow):
    """Additive means beside, not inside. Anything parsing this file today keeps working."""
    text = (shadow["dir"] / f"shadow_decisions_{WINDOW}.jsonl").read_text(encoding="utf-8")
    assert "explain_id" not in text
    assert "schema_version" not in text


def test_turning_explanations_off_reproduces_the_old_artifacts_byte_for_byte(tmp_path):
    """The strongest form of "legacy behaviour unchanged": run it both ways and diff."""
    off = tmp_path / "off"
    on = tmp_path / "on"
    r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                  root=str(off), explain=False)
    r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                  root=str(on), explain=True)
    for name in (f"shadow_decisions_{WINDOW}.jsonl",
                 f"shadow_settlements_{WINDOW}.jsonl",
                 f"book_state_{WINDOW}.json"):
        a = (off / r1.SHADOW_DIR / name).read_bytes()
        b = (on / r1.SHADOW_DIR / name).read_bytes()
        assert a == b, f"{name} differs when explanations are enabled"
    assert not (off / r1.SHADOW_DIR / r1.EXPLAIN_SUBDIR).exists()


# ── 5. no legacy path is touched ─────────────────────────────────────────────
LEGACY_PATHS = (
    "live_positions.json",
    "trade_log.jsonl",
    "runner.pid",
    "global_index/live_state_data.js",
    "global_index/replay_checkpoint.json",
    "global_index/paper_history.json",
    "global_index/preflight_state.json",
    "monitor/paper_pnl_compare.json",
    "STOP_TRADING",
    "track1_go_live_confirmation.json",
)


def _fingerprint():
    out = {}
    for rel in LEGACY_PATHS:
        p = _ROOT / rel
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"
    for pattern in ("scheduler_*.log", "live_day_*.log",
                    "global_index/runner_events_*.jsonl"):
        for p in sorted(_ROOT.glob(pattern)):
            out[str(p.relative_to(_ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_no_legacy_path_is_touched_by_a_shadow_run(tmp_path):
    before = _fingerprint()
    # The comparison is worthless if the fingerprint covers nothing that exists.
    assert len(before) >= 8, before
    assert sum(v != "ABSENT" for v in before.values()) >= 3, before

    r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                  root=str(tmp_path))
    assert _fingerprint() == before


def test_the_run_places_no_order_and_writes_no_confirmation(shadow):
    s = shadow["summary"]
    assert s["send_order_calls"] == 0
    assert s["order_gate"]["state"] == "shadow"
    assert s["order_gate"]["allow_orders"] is False
    assert not (_ROOT / "track1_go_live_confirmation.json").exists()


# ── 6. the verdict mapping is complete, and the gaps are visible ─────────────
def test_every_signal_layer_verdict_has_an_explanation_mapping():
    """A verb the map does not know must stop the run, not be filed under a default."""
    assert sl.DECISIONS, "no verdicts to check"
    missing = [v for v in sl.DECISIONS if v not in r1.EXPLAIN_VERDICT_MAP]
    assert missing == [], missing


def test_an_unmapped_verdict_raises_rather_than_guessing():
    class _Cand:
        trade_id, sleeve, instrument, direction, qty = "x", "roska4_stress", "MNQ", "SHORT", 7
        risk_dollars, entry_time, entry_price, stop_price, source = 1.0, "2026-08-24 10:35", 1.0, 0.9, ""

    class _Dec:
        candidate, verdict, detail, forced_closes = _Cand(), "verdict_from_the_future", "", ()

    with pytest.raises(KeyError, match="no explanation mapping"):
        r1.explanations_for([_Dec()], regime_csv="spy_daily_live.csv", data_paths={},
                            fill_law=tx.FILL_LAWS[0], freshness_allow=True)


def test_every_cited_rule_gets_all_its_required_features(shadow):
    """The registry decides what an explanation must carry; this asserts the wiring meets
    it for every rule the run actually cited, not just the ones a fixture exercises."""
    rows = _explanation_rows(shadow)
    assert rows
    cited = {r for row in rows for r in row["rule_ids"]}
    assert cited, "no rules were cited by any row"
    for row in rows:
        names = {f["name"] for f in row["feature_snapshot"]}
        for rid in row["rule_ids"]:
            assert set(tx.RULES[rid].features) <= names, (rid, sorted(names))


def test_the_unmeasured_features_are_declared_and_counted(shadow):
    """The honest gap, made into a number.

    Three features cannot be filled with a real value today, because the cluster guard
    returns no number on success and a one-decimal sentence on failure, and the book has
    moved on by the time the decision list is written. They travel as absent values that
    say why. This test fails if that count silently drops to zero — which would mean either
    the gap was closed (good, and it should be reported) or a value was invented (bad).
    """
    e = shadow["summary"]["explanations"]
    assert e["unmeasured_total"] > 0
    assert set(e["unmeasured_features"]) <= set(r1.EXPLAIN_UNMEASURED)
    rows = _explanation_rows(shadow)
    absent = [f for row in rows for f in row["feature_snapshot"] if f["value"] is None]
    assert absent, "no absent features to check"
    for f in absent:
        assert f["name"] in r1.EXPLAIN_UNMEASURED, f["name"]
        assert f["source"] == r1.EXPLAIN_UNMEASURED[f["name"]], f["name"]
        assert f["threshold"] is not None, f["name"]
    assert sum(len(row["feature_snapshot"]) for row in rows) > len(absent), (
        "every feature is absent; nothing real is being recorded")


def test_a_measured_feature_carries_a_real_value(shadow):
    """The counterpart. If everything were absent the record would be a shell."""
    rows = _all_rows(shadow)
    real = {f["name"]: f for row in rows for f in row["feature_snapshot"]
            if f["value"] is not None}
    # `freshness_allow` moved off the decision rows in Stage 5Z and onto the run-context
    # record — it is still measured, still real, and no longer claiming to be a proof of an
    # admission it did not govern.
    assert "freshness_allow" in real
    assert "allow_new_entries" in real
    for f in real.values():
        assert f["source"], f"{f['name']} has a value but does not say where it came from"


def test_the_freshness_contradiction_no_longer_exists(shadow):
    """Stage 5Y measured 91 accepted decisions each carrying a freshness proof marked
    FAILED, and left the question open. Stage 5Z settled it: on a replay the gate reads the
    machine's CURRENT daily inputs, which cannot testify about an admission that happened
    months earlier — proved by the same decision reading True at 12:00 and False at 15:00.

    So the contradiction is not counted any more, it is GONE, and the counter that measured
    it must now read zero. The reading itself survives on the run-context record.
    """
    e = shadow["summary"]["explanations"]
    rows = _explanation_rows(shadow)
    accepted = [r for r in rows if r["status"] == tx.ACCEPTED]
    assert accepted, "no accepted rows"
    failed_proof = [f for r in accepted for f in r["feature_snapshot"]
                    if f["passed"] is False]
    assert failed_proof == [], failed_proof[:3]
    assert e["accepted_with_failed_proof_total"] == 0
    # and the reading is still on file
    ctx = [r for r in _all_rows(shadow) if r["record_type"] == tx.NO_ACTION]
    assert len(ctx) == 1
    assert any(f["name"] == "freshness_allow" for f in ctx[0]["feature_snapshot"])


# ── 7. identity ──────────────────────────────────────────────────────────────
def test_the_fill_law_in_the_records_is_the_one_the_run_reported(shadow):
    """One reading of the law per run. An identity naming a law the run did not use is the
    exact defect Stage 4B removed from track1_params."""
    rows = _explanation_rows(shadow)
    assert rows
    assert {r["fill_law"] for r in rows} == {shadow["summary"]["fill_law"]}


def test_the_params_hash_is_the_one_the_checkpoint_would_compare(shadow):
    """Same helper, so a decision and the checkpoint that would resume it cannot disagree
    about which configuration produced them."""
    from global_index import track1_params as tp
    rows = _explanation_rows(shadow)
    ck = {(r["sleeve"], r["inst"]): r["params_hash"]
          for r in shadow["summary"]["checkpoint"]}
    assert ck, "the checkpoint report named no sleeve"
    checked = 0
    for row in rows:
        key = (row["sleeve"], row["instrument"])
        if key in ck:
            assert row["track1_params_hash"] == ck[key], key
            checked += 1
    assert checked > 0, "no row shared a sleeve with the checkpoint report"
    assert all(r["track1_params_hash"].startswith("sha256:") for r in rows)


def test_identity_carries_the_data_and_regime_files_actually_read(shadow):
    rows = _explanation_rows(shadow)
    assert rows
    for row in rows:
        assert row["regime_csv_identity"].startswith("spy_daily_live.csv:")
        assert ":" in row["data_source_identity"]
        assert not row["data_source_identity"].endswith(":MISSING"), row["instrument"]


# ── the out_dir / bound conflict, resolved visibly ───────────────────────────
# A caller may aim `out_dir` anywhere, and the Stage 3 route tests do exactly that to prove
# a run touches nothing real. The explanation writer's bound is stricter and cannot know
# that directory is harmless. The conflict is resolved by SAYING so — never by loosening
# the bound, and never by silence.

def test_redirecting_out_dir_skips_explanations_and_says_why(tmp_path):
    out = tmp_path / "elsewhere"
    out.mkdir()
    s = r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                      out_dir=str(out))
    e = s["explanations"]
    assert e["written"] is False
    assert e["records"] == 0
    assert e["decisions"] > 0, "no decisions, so the skip proves nothing"
    assert "outside" in e["skipped"] and tx.SHADOW_ROOT in e["skipped"]
    assert "root=" in e["skipped"], "the message must name the supported alternative"
    # and nothing was written there
    assert not (out / r1.EXPLAIN_SUBDIR).exists()
    assert not list(out.glob("explanations_*.jsonl"))


def test_a_skip_is_never_silent(tmp_path):
    """"No explanations" must never be readable as "nothing to explain" — the exact
    conflation this route's dashboard audit found on the live decision panel."""
    out = tmp_path / "elsewhere"
    out.mkdir()
    s = r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                      out_dir=str(out))
    written = json.loads((out / f"shadow_summary_{WINDOW}.json").read_text(encoding="utf-8"))
    assert written["explanations"]["written"] is False
    assert written["explanations"]["skipped"]
    assert written["explanations"]["decisions"] == s["explanations"]["decisions"]


def test_the_route_own_directory_never_skips(shadow):
    """The escape hatch above is for a redirected out_dir only. If the route's OWN shadow
    directory were ever refused that is a defect, and it must raise rather than degrade."""
    assert shadow["summary"]["explanations"]["written"] is True
    assert "skipped" not in shadow["summary"]["explanations"]


def test_explain_false_writes_no_explanation_block_at_all(tmp_path):
    s = r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=AS_OF,
                      root=str(tmp_path), explain=False)
    assert s["explanations"] is None
    assert not (tmp_path / r1.SHADOW_DIR / r1.EXPLAIN_SUBDIR).exists()
