"""Stage 5X — what `global_index/track1_explain.py` must refuse.

Read this as a list of things that MUST go red, not as a list of things that pass. Every
test below was written by first constructing the bad record and confirming the module
accepts it, then adding the rule that refuses it. A test that only ever sees a good record
proves that good records work and nothing else.

Two properties this file guards that are easy to lose:

- **No legacy path is touched.** `test_no_legacy_path_is_touched` hashes every legacy
  artifact before and after building AND writing records. That is the check the Stage 3
  route suite runs for the runner, and it is here for the same reason: a `--dry-run` once
  wrote `live_day_*.log`, which `paper_evidence_reader` globs, and manufactured a
  paper-evidence episode attributed to a different session.

- **The id survives a restart.** `test_explain_id_is_stable_across_processes` runs the id
  in two child interpreters under different `PYTHONHASHSEED` values. Python's `hash()` is
  salted per process, so a module that used it would pass every in-process test and fail
  the only thing the id is for.

Offline: no broker, no scheduler, no network, and every write lands in `tmp_path` or under
`scratch/track1_shadow`.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from global_index import track1_explain as tx  # noqa: E402


# ── fixtures: one good record of each kind ───────────────────────────────────
IDENT = tx.Identity(
    params_hash="sha256:" + "0" * 64,
    fill_law="artifact_all_bars_gappable",
    data_source_identity="global_index/data/MNQ.parquet:deadbeef",
    regime_csv_identity="spy_daily_live.csv:cafe",
    git_commit="0" * 40,
)


def _accepted_decision(**over):
    # SHADOW_LIVE on purpose: it is the mode where all three gates bind, so these tests keep
    # exercising the full proof set. Stage 5Z made the set mode-dependent — a replay
    # decision does not cite the freshness gate, and `_replay_decision` below covers that.
    kw = dict(
        route=tx.ROUTE, session_date="2026-08-24", sleeve="roska4_stress",
        instrument="MNQ", candidate_id="T1-0001", decision_time="2026-08-24 10:35:00",
        decision_mode=tx.SHADOW_LIVE,
        status=tx.ACCEPTED, reason_code=tx.TAKE,
        rule_ids=["GATE.CAP_CLUSTER", "GATE.FRESHNESS", "GATE.BREAKER"],
        features=[
            tx.Feature("cluster_gross_after", 0.084, 0.100, "<=", True, "fraction"),
            tx.Feature("freshness_allow", True, True, "==", True),
            tx.Feature("allow_new_entries", True, True, "==", True),
        ],
        thresholds={"cluster_gross_cap": 0.100},
        inputs_summary={"bars": "MNQ 5m 09:30-10:35", "regime": "Stress",
                        "checkpoint": "accepted", "window_ledger": "complete"},
        outputs={"direction": "SHORT", "qty": 7, "entry_basis": "break_of_pre_window_low",
                 "stop_basis": "pre_low_break_rr", "risk_dollars": 4200.0,
                 "cap_bucket": "roska4_stress"},
        identity=IDENT,
    )
    kw.update(over)
    return tx.decision_record(**kw)


def _rejected_decision(**over):
    kw = dict(
        route=tx.ROUTE, session_date="2026-08-24", sleeve="roska4_calm",
        instrument="MES", candidate_id="T1-0002", decision_time="2026-08-24 10:00:00",
        decision_mode=tx.REPLAY,
        status=tx.REJECTED, reason_code=tx.REJECT_FAMILY_CAP,
        rule_ids=["GATE.CAP_FAMILY"],
        features=[tx.Feature("family_gross", 0.0531, 0.050, "<=", False, "fraction")],
        thresholds={"family_gross_cap": 0.050, "family_net_cap": 0.044},
        inputs_summary={"bars": "MES 5m 09:30-10:00"},
        outputs={},
        rejection={"verdict": tx.REJECT_FAMILY_CAP,
                   "detail": "family gross 5.31% > cap 5.00%",
                   "blocking_positions": ["T1-0000"]},
        identity=IDENT,
    )
    kw.update(over)
    return tx.decision_record(**kw)


def _signal(**over):
    kw = dict(
        route=tx.ROUTE, session_date="2026-08-24", sleeve="roska4_swing",
        instrument="MES", candidate_id="T1-0003", decision_time="2026-08-24 14:05:00",
        decision_mode=tx.REPLAY,
        status=tx.FAIL, reason_code=tx.FILTER_BLOCKED,
        rule_ids=["R4.RANGE_P90", "R4.RVOL_MAX"],
        features=[
            tx.Feature("prev_range_pct", 0.0311, 0.02652437134968455, "<=", False),
            tx.Feature("rvol", 1.42, 2.0, "<=", True),
        ],
        thresholds={"r4_range_threshold": 0.02652437134968455, "r4_rel_volume_max": 2.0},
        inputs_summary={"bars": "MES 1m -> 5m"},
        outputs={},
        identity=IDENT,
    )
    kw.update(over)
    return tx.signal_record(**kw)


# ── the registry itself ──────────────────────────────────────────────────────
def test_registry_is_not_empty_and_self_consistent():
    # Assert non-empty BEFORE looping: a "check every rule" test passes vacuously on an
    # empty registry, which is the shape that has already hidden ~195 assertions here.
    assert len(tx.RULES) >= 30, f"registry has only {len(tx.RULES)} rules"
    assert tx.self_check() == []


def test_every_rule_points_at_a_file_that_exists():
    assert tx.RULES, "empty registry"
    assert tx.missing_code_files(_ROOT) == []


def test_every_rule_cites_evidence_that_exists():
    cited = [(rid, e.path) for rid, r in tx.RULES.items() for e in r.evidence]
    assert cited, "no rule cites any evidence"
    assert tx.missing_evidence_files(_ROOT) == []


def test_the_five_track1_rule_families_are_all_present():
    prefixes = {rid.split(".")[0] for rid in tx.RULES}
    assert {"R4", "NKD", "CALM", "STRESS", "GATE"} <= prefixes, prefixes


def test_reason_codes_are_imported_from_the_modules_that_own_them():
    """Not retyped. If signal_layer adds a verdict, this registry gains it for free —
    which is the property that stops the two lists drifting apart."""
    from global_index.track1_signal_layer import DECISIONS
    from global_index import track1_intraday as ti
    assert DECISIONS, "no decision verbs to check"
    assert set(DECISIONS) <= set(tx.REASON_CODES)
    assert set(ti.REFUSAL_CODES) <= set(tx.REASON_CODES)


# ── explain_id ───────────────────────────────────────────────────────────────
_ID_KW = dict(route="track1_candidate", session_date="2026-08-24",
              sleeve="roska4_stress", instrument="MNQ", candidate_id="T1-0001",
              record_type=tx.DECISION, stage="admission", sequence=3)


def test_explain_id_is_deterministic():
    assert tx.explain_id(**_ID_KW) == tx.explain_id(**_ID_KW)


@pytest.mark.parametrize("field,other", [
    ("route", "legacy"), ("session_date", "2026-08-25"), ("sleeve", "roska4_calm"),
    ("instrument", "MES"), ("candidate_id", "T1-0002"), ("record_type", tx.SIGNAL),
    ("stage", "detection"), ("sequence", 4),
])
def test_explain_id_moves_when_any_component_moves(field, other):
    """Mutation, one component at a time. An id that ignores a component is an id that
    collides silently — two Stress decisions at 10:35 and 10:40 would become one row."""
    kw = dict(_ID_KW)
    kw[field] = other
    assert tx.explain_id(**kw) != tx.explain_id(**_ID_KW), f"{field} does not affect the id"


def test_explain_id_is_stable_across_processes():
    """The only thing the id is FOR. Python's hash() is salted per interpreter, so a
    module built on it passes every in-process test and fails exactly here."""
    code = (f"import sys; sys.path.insert(0, {str(_ROOT)!r});"
            "from global_index import track1_explain as tx;"
            f"print(tx.explain_id(**{_ID_KW!r}))")
    outs = []
    for seed in ("0", "12345"):
        env = {**dict(__import__("os").environ), "PYTHONHASHSEED": seed}
        res = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, env=env, cwd=str(_ROOT))
        assert res.returncode == 0, res.stderr
        outs.append(res.stdout.strip().splitlines()[-1])
    assert outs[0] == outs[1], f"id moved with PYTHONHASHSEED: {outs}"
    assert outs[0] == tx.explain_id(**_ID_KW)


def test_explain_id_refuses_an_unknown_record_type():
    kw = dict(_ID_KW, record_type="GUESS")
    with pytest.raises(ValueError):
        tx.explain_id(**kw)


# ── required fields ──────────────────────────────────────────────────────────
def test_a_good_record_validates():
    assert tx.validate(_accepted_decision()) == []
    assert tx.validate(_rejected_decision()) == []
    assert tx.validate(_signal()) == []


@pytest.mark.parametrize("field", tx.REQUIRED_FIELDS)
def test_dropping_any_required_field_is_refused(field):
    rec = _accepted_decision()
    assert field in rec, f"{field} was never emitted, so this test proves nothing"
    rec.pop(field)
    errs = tx.validate(rec)
    assert errs, f"dropping {field} was accepted"
    assert any(field in e for e in errs), errs


def test_check_raises_where_validate_reports():
    rec = _accepted_decision()
    rec.pop("fill_law")
    with pytest.raises(ValueError):
        tx.check(rec)


# ── code refs ────────────────────────────────────────────────────────────────
def test_missing_code_ref_fails():
    rec = _accepted_decision()
    assert rec["code_refs"], "no code_refs emitted, so removing them proves nothing"
    rec["code_refs"] = []
    errs = tx.validate(rec)
    assert any("code_ref" in e for e in errs), errs


def test_a_code_ref_without_a_symbol_fails():
    rec = _accepted_decision()
    rec["code_refs"][0]["symbol"] = ""
    assert any("symbol" in e for e in tx.validate(rec))


def test_a_code_ref_may_omit_the_line_number():
    """Deliberate: a line number rots on every edit above it, so it is recorded when
    known and never required."""
    rec = _accepted_decision()
    assert all(r["line"] is None for r in rec["code_refs"])
    assert tx.validate(rec) == []


def test_a_rule_that_fired_without_a_matching_code_ref_fails():
    rec = _accepted_decision()
    rec["rule_ids"].append("GATE.WINDOW")          # cited, but no ref derived for it
    errs = tx.validate(rec)
    assert any("GATE.WINDOW" in e for e in errs), errs


def test_code_refs_are_derived_not_supplied():
    """A caller cannot point a rule at the wrong file, because it never supplies the
    pointer — the builder reads it from the registry."""
    rec = _accepted_decision()
    for ref in rec["code_refs"]:
        assert ref == tx.RULES[ref["rule_id"]].code_ref.as_dict()


# ── rule ids ─────────────────────────────────────────────────────────────────
def test_an_unknown_rule_id_is_refused():
    rec = _accepted_decision(rule_ids=["GATE.CAP_CLUSTER", "GATE.FRESHNESS",
                                       "GATE.BREAKER", "R4.INVENTED"])
    errs = tx.validate(rec)
    assert any("R4.INVENTED" in e for e in errs), errs


# ── features and thresholds ──────────────────────────────────────────────────
def test_a_feature_without_a_threshold_is_refused():
    rec = _signal()
    assert rec["feature_snapshot"], "no features emitted"
    rec["feature_snapshot"][0].pop("threshold")
    assert any("threshold" in e for e in tx.validate(rec))


def test_a_feature_that_does_not_say_whether_it_passed_is_refused():
    rec = _signal()
    rec["feature_snapshot"][0]["passed"] = None
    assert any("passed" in e for e in tx.validate(rec))


def test_a_rule_whose_required_feature_is_absent_is_refused():
    """"R4.RANGE_P90 fired" without the range is a sentence, not evidence."""
    rec = _signal()
    rec["feature_snapshot"] = [f for f in rec["feature_snapshot"]
                               if f["name"] != "prev_range_pct"]
    errs = tx.validate(rec)
    assert any("prev_range_pct" in e for e in errs), errs


def test_an_absent_feature_value_is_legal_and_must_say_it_blocked():
    """The R4 context filter treats a MISSING feature as a BLOCK. A record has to be able
    to say that, which means value=None with passed=False is a valid row."""
    rec = _signal(features=[
        tx.Feature("prev_range_pct", None, 0.02652437134968455, "<=", False,
                   source="absent from prev_rth_range_map"),
        tx.Feature("rvol", None, 2.0, "<=", False, source="ts not in slot volume index"),
    ])
    assert tx.validate(rec) == []


# ── the decision rules ───────────────────────────────────────────────────────
@pytest.mark.parametrize("proof", tx.ACCEPTED_PROOF_RULES)
def test_an_accepted_decision_must_prove_each_gate(proof):
    rec = _accepted_decision()
    assert proof in rec["rule_ids"], f"{proof} was never cited"
    rec["rule_ids"] = [r for r in rec["rule_ids"] if r != proof]
    rec["code_refs"] = [r for r in rec["code_refs"] if r["rule_id"] != proof]
    errs = tx.validate(rec)
    assert any(proof in e for e in errs), errs


def test_an_accepted_decision_cannot_carry_a_refusal_reason():
    rec = _accepted_decision(reason_code=tx.REJECT_CAP)
    assert any("accepted decision" in e for e in tx.validate(rec))


def test_a_rejected_decision_must_name_a_refusal_reason():
    rec = _rejected_decision(reason_code=tx.SETUP_DETECTED)
    errs = tx.validate(rec)
    assert any("refusal reason" in e for e in errs), errs


def test_a_rejected_decision_must_carry_rejection_details():
    rec = _rejected_decision()
    assert rec["rejection"], "no rejection details emitted"
    rec["rejection"] = None
    assert any("rejection details" in e for e in tx.validate(rec))


@pytest.mark.parametrize("reason", sorted(tx.REJECTION_REASONS))
def test_every_why_not_reason_can_be_recorded(reason):
    """Cap reject, same-symbol suppress, family cap, breaker halt, freshness fail,
    intraday fail, no setup — each must round-trip as a rejected decision."""
    rec = _rejected_decision(reason_code=reason,
                             rejection={"verdict": reason, "detail": "measured"})
    assert tx.validate(rec) == [], (reason, tx.validate(rec))


def test_a_decision_cannot_use_a_gate_status():
    """'pass' is what a check says; 'accepted' is what a candidate becomes. Letting a
    DECISION say 'pass' makes the stream unfilterable."""
    rec = _accepted_decision(status=tx.PASS)
    assert any("status" in e for e in tx.validate(rec))


# ── route / sleeve / instrument / fill law ───────────────────────────────────
def test_an_instrument_the_sleeve_does_not_trade_is_refused():
    rec = _accepted_decision(sleeve="roska4_stress", instrument="MES")
    assert any("not traded by" in e for e in tx.validate(rec))


def test_an_unknown_sleeve_is_refused():
    rec = _accepted_decision(sleeve="roska4_guess")
    assert any("not a Track 1 sleeve" in e for e in tx.validate(rec))


def test_an_unrecognised_fill_law_is_refused():
    rec = _accepted_decision(identity=tx.Identity(
        params_hash=IDENT.params_hash, fill_law="whatever_the_run_did",
        git_commit=IDENT.git_commit))
    assert any("fill_law" in e for e in tx.validate(rec))


def test_a_wrong_schema_version_is_refused():
    rec = _accepted_decision()
    rec["schema_version"] = "track1_explain/0"
    assert any("schema_version" in e for e in tx.validate(rec))


# ── linking ──────────────────────────────────────────────────────────────────
def test_a_decision_can_name_the_signal_it_came_from():
    sig = _signal(status=tx.PASS, reason_code=tx.SETUP_DETECTED)
    dec = _accepted_decision(parent_explain_id=sig["explain_id"])
    assert dec["parent_explain_id"] == sig["explain_id"]
    assert dec["explain_id"] != sig["explain_id"]
    assert tx.validate(dec) == []


def test_no_signal_and_no_action_are_valid_records():
    for build in (tx.no_signal_record, tx.no_action_record):
        rec = build(route=tx.ROUTE, session_date="2026-08-24", sleeve="roska4_stress",
                    instrument="MNQ", candidate_id="window", decision_time="12:30",
                    decision_mode=tx.REPLAY,
                    rule_ids=["GATE.WINDOW_LEDGER"],
                    features=[tx.Feature("observed_slots", 24, 24, "==", True)],
                    inputs_summary={"window": "10:35-12:30"}, outputs={},
                    identity=IDENT)
        assert tx.validate(rec) == [], tx.validate(rec)


# ── JSON ─────────────────────────────────────────────────────────────────────
def test_records_serialise_and_round_trip():
    for rec in (_accepted_decision(), _rejected_decision(), _signal()):
        text = tx.to_json(rec)
        assert json.loads(text) == rec


def test_a_pandas_timestamp_does_not_break_serialisation():
    import pandas as pd
    rec = _accepted_decision(decision_time=pd.Timestamp("2026-08-24 10:35"),
                             data_time=pd.Timestamp("2026-08-24 10:30"),
                             bar_timestamps=[pd.Timestamp("2026-08-24 10:25"),
                                             pd.Timestamp("2026-08-24 10:30")])
    json.loads(tx.to_json(rec))
    assert isinstance(rec["decision_time"], str)


# ── the writer ───────────────────────────────────────────────────────────────
def test_building_a_record_writes_nothing(tmp_path):
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    _accepted_decision(); _rejected_decision(); _signal()
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    assert before == after
    assert list(tmp_path.iterdir()) == []


def test_write_shadow_lands_only_under_the_shadow_directory(tmp_path):
    (tmp_path / tx.SHADOW_ROOT).mkdir(parents=True)
    path = tx.write_shadow([_accepted_decision()], session_date="2026-08-24",
                           out_dir=tx.SHADOW_ROOT, root=tmp_path)
    assert path == tmp_path / tx.SHADOW_ROOT / "explanations_20260824.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1 and rows[0]["record_type"] == tx.DECISION


@pytest.mark.parametrize("bad", [
    "global_index", ".", "scratch", "scratch/track1_shadow/../../global_index",
    "monitor/backend",
])
def test_write_shadow_refuses_any_other_destination(tmp_path, bad):
    with pytest.raises(tx.ShadowPathRefused):
        tx.write_shadow([_accepted_decision()], session_date="2026-08-24",
                        out_dir=bad, root=tmp_path)


def test_an_invalid_record_in_a_batch_writes_nothing(tmp_path):
    """All-or-nothing. A partly written batch is a file whose tail nobody can trust."""
    (tmp_path / tx.SHADOW_ROOT).mkdir(parents=True)
    bad = _accepted_decision()
    bad.pop("fill_law")
    with pytest.raises(ValueError):
        tx.write_shadow([_accepted_decision(), bad], session_date="2026-08-24",
                        out_dir=tx.SHADOW_ROOT, root=tmp_path)
    assert list((tmp_path / tx.SHADOW_ROOT).iterdir()) == []


# ── the legacy boundary ──────────────────────────────────────────────────────
LEGACY_PATHS = (
    "live_positions.json",
    "trade_log.jsonl",
    "global_index/live_state_data.js",
    "global_index/replay_checkpoint.json",
    "global_index/paper_history.json",
    "monitor/paper_pnl_compare.json",
    "runner.pid",
)


def _fingerprint():
    out = {}
    for rel in LEGACY_PATHS:
        p = _ROOT / rel
        out[rel] = (hashlib.sha256(p.read_bytes()).hexdigest()
                    if p.exists() else "ABSENT")
    for pattern in ("scheduler_*.log", "live_day_*.log", "global_index/runner_events_*.jsonl"):
        for p in sorted(_ROOT.glob(pattern)):
            out[str(p.relative_to(_ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_no_legacy_path_is_touched(tmp_path):
    before = _fingerprint()
    # Assert the fingerprint actually covers something, or the comparison below is a
    # comparison of two empty dicts agreeing with each other.
    assert len(before) >= 5, before
    assert any(v != "ABSENT" for v in before.values()), before

    (tmp_path / tx.SHADOW_ROOT).mkdir(parents=True)
    tx.write_shadow([_accepted_decision(), _rejected_decision(), _signal()],
                    session_date="2026-08-24", out_dir=tx.SHADOW_ROOT, root=tmp_path)
    tx.registry(); tx.self_check(); tx.git_commit(_ROOT)

    assert _fingerprint() == before


def test_the_module_imports_no_broker_or_scheduler():
    """Read the module's own imports rather than trusting the docstring. A docstring is a
    description and descriptions in this repo have drifted from what they describe."""
    import ast
    src = (_ROOT / "global_index" / "track1_explain.py").read_text(encoding="utf-8")
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert names, "parsed no imports at all"
    forbidden = {"ib_insync", "global_index.runner", "global_index.run_scheduler",
                 "global_index.ibkr_broker", "global_index.broker",
                 "global_index.run_live_day", "socket", "requests", "urllib.request"}
    assert not (names & forbidden), sorted(names & forbidden)


#: The ONE entry point allowed to import this module, as of Stage 5Y. It is the Track 1
#: shadow route: it places no orders, writes no legacy path, and is not registered with any
#: scheduler. Widening this tuple is the review — a name added here has to be argued for in
#: a report, not slipped in.
ALLOWED_IMPORTERS: tuple = ("global_index/run_live_day_track1.py",)

#: Everything that must NOT import it. The legacy runner and day-runner because Track 1's
#: records must never reach legacy's files; the scheduler because this route is not
#: scheduled; the monitor because there is no route-aware reader yet and the dashboard is
#: explicitly not ready — a monitor import would be the first step of a wiring nobody
#: reviewed.
FORBIDDEN_IMPORTERS: tuple = (
    "global_index/run_live_day.py",
    "global_index/run_scheduler.py",
    "global_index/runner.py",
    "monitor/backend/app.py",
    "monitor/backend/schedule_status.py",
    "monitor/backend/paper_evidence_reader.py",
    "monitor/backend/session_event_reader.py",
    "monitor/backend/report_reader.py",
)


def test_only_the_track1_shadow_route_imports_the_module():
    """Stage 5Y deliberately opened ONE door. This test is the record of which one.

    Before 5Y it forbade every production importer including the shadow route, which was
    right while the module was a scaffold. Now the shadow route is the wiring, and the
    test's job changes from "nothing imports it" to "only that imports it" — the same
    guard, one name wider.
    """
    import re
    hits = []
    for rel in ALLOWED_IMPORTERS + FORBIDDEN_IMPORTERS:
        p = _ROOT / rel
        if p.exists() and re.search(r"\btrack1_explain\b", p.read_text(encoding="utf-8")):
            hits.append(rel)
    assert set(hits) & set(FORBIDDEN_IMPORTERS) == set(), (
        f"track1_explain is imported by {sorted(set(hits) & set(FORBIDDEN_IMPORTERS))}; "
        f"legacy, scheduler and monitor code must not carry it")
    # And the allowed door is actually open — otherwise this test would keep passing after
    # the wiring was reverted, which is the vacuous-green shape it exists to avoid.
    assert "global_index/run_live_day_track1.py" in hits, (
        "the shadow route no longer imports track1_explain; Stage 5Y wiring is gone")


def test_no_monitor_or_dashboard_file_mentions_the_module():
    """Wider than the named list: the whole monitor tree and every dashboard asset.

    The dashboard is not ready (Track 1 slots are invisible to every health signal), so a
    reference anywhere in there is a wiring that got ahead of its evidence.
    """
    import re
    hits = []
    for base, patterns in ((_ROOT / "monitor", ("**/*.py",)),
                           (_ROOT / "global_index" / "dash", ("**/*.js", "**/*.html"))):
        for pattern in patterns:
            for p in base.glob(pattern):
                if "__pycache__" in p.parts:
                    continue
                # TEST files are excluded, and that is the point rather than a convenience.
                # This guard defends a dependency boundary: no PRODUCTION monitor or
                # dashboard file may import the explanation WRITER. A monitor test that names
                # the module in order to assert it is NOT imported is the opposite of the
                # failure being guarded against — and counting it made this guard red from
                # the day that test was written (2026-08-23, measured), which is how a guard
                # nobody can act on becomes a guard people learn to skip.
                if p.name.startswith("test_") or p.name.endswith("_test.py"):
                    continue
                if re.search(r"track1_explain", p.read_text(encoding="utf-8",
                                                            errors="replace")):
                    hits.append(str(p.relative_to(_ROOT)))
    assert hits == [], f"track1_explain reached the monitor/dashboard: {hits}"


# ── derived fields must still be derived at validation time ──────────────────
# Added 2026-08-23 after review. Every case below was measured to be ACCEPTED by the
# validator before these guards existed: the builder derived explain_id, code_refs and
# evidence_refs correctly, and then nothing ever re-checked them. A record travels — through
# JSON, through a file, through an edit — and after that a derived field is just a copy
# sitting beside the thing it claims to describe, which is the drift this whole registry
# exists to remove.

@pytest.mark.parametrize("field,other", [
    ("session_date", "2026-08-25"), ("sleeve", "roska4_calm"), ("instrument", "MES"),
    ("candidate_id", "T1-9999"), ("stage", "invented"), ("sequence", 99),
    ("record_type", tx.SIGNAL),
])
def test_editing_an_id_component_after_the_build_is_refused(field, other):
    rec = _accepted_decision()
    assert rec[field] != other, f"{field} already equals the mutation; test proves nothing"
    rec[field] = other                       # id deliberately left as it was
    errs = tx.validate(rec)
    assert any("explain_id" in e for e in errs), errs


def test_a_replaced_explain_id_is_refused():
    rec = _accepted_decision()
    rec["explain_id"] = "t1x_" + "0" * 32
    assert any("explain_id" in e for e in tx.validate(rec))


def test_a_record_straight_from_the_builder_has_a_matching_id():
    """The guard must not go red on an honest record — a check that fires on good input is
    a check people switch off."""
    for rec in (_accepted_decision(), _rejected_decision(), _signal()):
        assert not any("explain_id" in e for e in tx.validate(rec))


# ── route ────────────────────────────────────────────────────────────────────
def _foreign_route_record():
    """A record for another route, built CONSISTENTLY — id and field agree.

    This is the case the id check cannot catch. Measured 2026-08-23: a record built with
    route='legacy' produces an explain_id that recomputes correctly from 'legacy', so only
    an explicit route check refuses it.
    """
    return tx.decision_record(
        route="legacy", session_date="2026-08-24", sleeve="roska4_stress",
        instrument="MNQ", candidate_id="T1-0001", decision_time="2026-08-24 10:35:00",
        decision_mode=tx.SHADOW_LIVE,
        status=tx.ACCEPTED, reason_code=tx.TAKE,
        rule_ids=list(tx.ACCEPTED_PROOF_RULES),
        features=[tx.Feature("cluster_gross_after", 0.084, 0.100, "<=", True),
                  tx.Feature("freshness_allow", True, True, "==", True),
                  tx.Feature("allow_new_entries", True, True, "==", True)],
        identity=tx.Identity(route="legacy", params_hash=IDENT.params_hash,
                             fill_law=IDENT.fill_law, git_commit=IDENT.git_commit))


def test_a_consistent_record_for_another_route_is_still_refused():
    rec = _foreign_route_record()
    assert rec["route"] == "legacy"
    # the id agrees with the record, so this must be caught by the route rule alone
    assert not any("explain_id" in e for e in tx.validate(rec))
    assert any("is not 'track1_candidate'" in e for e in tx.validate(rec))


def test_the_route_field_has_exactly_one_source():
    """It had two until 2026-08-23: the builder's `route=` fed the explain_id and the
    Identity spread overwrote the field afterwards, so a record could carry an id naming
    one route and a field naming another and pass every check."""
    assert "route" not in tx.Identity().as_dict()
    rec = _accepted_decision()
    assert rec["route"] == tx.ROUTE
    assert rec["explain_id"] == tx.explain_id(
        route=rec["route"], session_date=rec["session_date"], sleeve=rec["sleeve"],
        instrument=rec["instrument"], candidate_id=rec["candidate_id"],
        record_type=rec["record_type"], stage=rec["stage"], sequence=rec["sequence"])


def test_the_builder_refuses_a_route_that_disagrees_with_its_identity():
    with pytest.raises(ValueError, match="route disagreement"):
        _accepted_decision(route="legacy")          # IDENT still says track1_candidate


# ── code refs and evidence refs ──────────────────────────────────────────────
def test_a_code_ref_pointing_at_the_wrong_file_is_refused():
    rec = _accepted_decision()
    assert rec["code_refs"][0]["file"] != "wrong.py"
    rec["code_refs"][0]["file"] = "wrong.py"
    assert any("code_refs do not match" in e for e in tx.validate(rec))


def test_a_code_ref_pointing_at_the_wrong_symbol_is_refused():
    rec = _accepted_decision()
    rec["code_refs"][0]["symbol"] = "not_a_symbol"
    assert any("code_refs do not match" in e for e in tx.validate(rec))


def test_an_extra_code_ref_for_a_rule_that_never_fired_is_refused():
    rec = _accepted_decision()
    rec["code_refs"].append({"file": "x.py", "symbol": "y", "rule_id": "GATE.WINDOW",
                             "line": None})
    assert any("code_refs do not match" in e for e in tx.validate(rec))


def test_a_forged_evidence_path_is_refused():
    rec = _accepted_decision()
    assert rec["evidence_refs"], "no evidence emitted, so swapping one proves nothing"
    rec["evidence_refs"][0]["path"] = "does/not/exist.py"
    assert any("evidence_refs do not match" in e for e in tx.validate(rec))


def test_reordering_the_refs_is_not_treated_as_tampering():
    """Content, not order. A record that reordered its own refs on a round-trip is not
    tampered with, and a guard that went red for it is a guard people learn to disable."""
    rec = _accepted_decision()
    assert len(rec["code_refs"]) > 1, "need at least two refs to reorder"
    rec["code_refs"] = list(reversed(rec["code_refs"]))
    rec["evidence_refs"] = list(reversed(rec["evidence_refs"]))
    assert tx.validate(rec) == []


def test_the_builder_and_the_validator_share_one_derivation():
    """Not two copies of the rule. `derived_refs` is called by both, so the validator
    cannot hold a stale idea of what a rule derives."""
    rec = _accepted_decision()
    want_refs, want_ev = tx.derived_refs(rec["rule_ids"])
    assert rec["code_refs"] == want_refs
    assert rec["evidence_refs"] == want_ev


def test_a_json_round_trip_still_validates():
    """The whole point of re-deriving is that a record which has been to disk and back is
    still checkable. If the round trip itself went red, the guard would be unusable."""
    for rec in (_accepted_decision(), _rejected_decision(), _signal()):
        assert tx.validate(json.loads(tx.to_json(rec))) == []


def test_a_written_then_reread_record_still_validates(tmp_path):
    (tmp_path / tx.SHADOW_ROOT).mkdir(parents=True)
    path = tx.write_shadow([_accepted_decision(), _rejected_decision(), _signal()],
                           session_date="2026-08-24", out_dir=tx.SHADOW_ROOT,
                           root=tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    for row in rows:
        assert tx.validate(row) == [], row["explain_id"]
