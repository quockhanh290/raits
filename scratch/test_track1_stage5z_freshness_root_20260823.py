"""Stage 5Z — the freshness contract, and the writer's root bound.

Two separate things settled here, both by measurement rather than preference.

**Freshness.** Stage 5Y measured that 91 of 91 accepted vault2026 decisions carried a
freshness proof marked FAILED. The cause was not a bug in the records: `fresh.evaluate`
reads the machine's CURRENT daily inputs, and nothing consults its verdict before
`run_candidates`. The decisive control is `test_the_same_replay_decision_gets_two_different
_freshness_readings` below — the SAME 2026-01-02 decision, same explain_id, same accepted
status, carries `passed=True` when the replay runs at 12:00 and `passed=False` at 15:00 on
one afternoon, with 91 accepted either way. A field that moves while the thing it describes
does not is run context, not proof of that thing.

So: replay records the reading as CONTEXT and does not cite the gate; live and armed bind
it, and no accepted record in any mode may carry a failed proof.

**The root bound.** `write_shadow` refuses anything outside `scratch/track1_shadow`.
Relocating with `root=` moves the bound with it, which is how a test writes to a temp
directory without a flag that switches the bound off. There is deliberately no such flag.

Offline: no broker, no scheduler, no orders. Every run is relocated to a temp root, so the
real `scratch/track1_shadow` — where a parallel session is working — is never written.
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
import global_index.run_live_day_track1 as r1  # noqa: E402

WINDOW = "vault2026"
FRESH_AT = "2026-08-21 12:00"     # measured: the freshness gate PASSES here
STALE_AT = "2026-08-21 15:00"     # the SAME instant's requirement, against a SHORT csv

#: How the refusing run is produced, and why it changed in Stage 5Q-5.
#:
#: This suite needs one run whose freshness gate ALLOWS and one whose gate REFUSES, so that the
#: same replay decision can be shown reading two different ways. Until 5Q-5 the refusing run was
#: made with the CLOCK: at 15:00 the gate asked the daily series for today's close, which does
#: not exist until 16:00, so it refused. That refusal was a BUG — the requirement was wrong for
#: that data source — and 5Q-5 removed it.
#:
#: The property this suite exists for is untouched: a replay decision must not cite a gate whose
#: reading moves while the decision does not. Only the way of producing a refusing gate changes,
#: from a clock artefact to genuinely short data, which is the honest way to produce it anyway.
STALE_CSV_DROP_ROWS = 2


def _rows(root, window=WINDOW):
    out = []
    for f in sorted((root / r1.SHADOW_DIR / r1.EXPLAIN_SUBDIR / window).glob("*.jsonl")):
        out += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    return out


def _decisions(rows):
    return [r for r in rows if r["record_type"] == tx.DECISION]


def _context(rows):
    return [r for r in rows if r["record_type"] == tx.NO_ACTION]


@pytest.fixture(scope="module")
def fresh_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("z_fresh")
    s = r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=FRESH_AT,
                      root=str(root))
    return {"root": root, "summary": s, "rows": _rows(root)}


def _short_regime_csv(root) -> str:
    """A copy of the real regime CSV with its last sessions removed. Read-only on the original."""
    import pandas as _pd
    df = _pd.read_csv(_ROOT / "spy_daily_live.csv")
    out = root / "spy_daily_short.csv"
    df.iloc[:-STALE_CSV_DROP_ROWS].to_csv(out, index=False)
    return str(out)


@pytest.fixture(scope="module")
def stale_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("z_stale")
    s = r1.run_shadow(window=WINDOW, regime_csv=_short_regime_csv(root), now_et=STALE_AT,
                      root=str(root))
    return {"root": root, "summary": s, "rows": _rows(root)}


# ── the measurement that settles the replay contract ─────────────────────────
def test_the_two_runs_really_do_disagree_about_freshness(fresh_run, stale_run):
    """The premise. If both runs agreed, everything below would prove nothing.

    Renamed in Stage 5Q-5: it was `..._two_clocks_...` when the refusing run was produced by
    the clock, and that clock behaviour was the bug 5Q-5 removed. The disagreement is now
    produced by short data, which is what it should always have been.
    """
    assert fresh_run["summary"]["freshness"]["allow"] is True
    assert stale_run["summary"]["freshness"]["allow"] is False
    refusing = [c["name"] for c in stale_run["summary"]["freshness"]["checks"]
                if c["status"] in ("stale", "missing", "unreadable")]
    # `preflight_consistency` joins it, and that is the new check doing its job: the record for
    # this day says the 13:45 run SUCCEEDED while the series it wrote is short. Two true
    # statements, and naming the contradiction is the whole point of that check.
    assert refusing == ["regime_csv", "preflight_consistency"], refusing


def test_the_same_replay_decision_gets_two_different_freshness_readings(fresh_run,
                                                                       stale_run):
    """The finding, stated as a test.

    Same historical decision, same identifier, same accepted status, two clocks — and under
    the OLD contract, two different answers about whether it was allowed to happen. That is
    what disqualifies the reading as a proof about that decision.
    """
    a = {r["explain_id"]: r for r in _decisions(fresh_run["rows"])}
    b = {r["explain_id"]: r for r in _decisions(stale_run["rows"])}
    assert a and b, "no decisions in one of the runs"
    shared = set(a) & set(b)
    assert len(shared) == len(a) == len(b), "the decision stream itself moved between runs"
    # the decisions are identical...
    for eid in shared:
        assert a[eid]["status"] == b[eid]["status"]
        assert a[eid]["reason_code"] == b[eid]["reason_code"]
        assert a[eid]["session_date"] == b[eid]["session_date"]
    # ...while the run-level freshness reading is not
    fa = _context(fresh_run["rows"])[0]
    fb = _context(stale_run["rows"])[0]
    va = next(f for f in fa["feature_snapshot"] if f["name"] == "freshness_allow")
    vb = next(f for f in fb["feature_snapshot"] if f["name"] == "freshness_allow")
    assert va["value"] is True and vb["value"] is False
    assert va["passed"] is True and vb["passed"] is False


# ── the replay contract ──────────────────────────────────────────────────────
@pytest.mark.parametrize("run", ["fresh_run", "stale_run"])
def test_accepted_replay_decisions_never_cite_the_freshness_gate(run, request):
    rows = request.getfixturevalue(run)["rows"]
    acc = [r for r in _decisions(rows) if r["status"] == tx.ACCEPTED]
    assert acc, "no accepted decisions; this test would pass vacuously"
    offenders = [r["explain_id"] for r in acc if "GATE.FRESHNESS" in r["rule_ids"]]
    assert offenders == [], offenders


@pytest.mark.parametrize("run", ["fresh_run", "stale_run"])
def test_no_accepted_decision_carries_a_failed_proof(run, request):
    """The Stage 5Y number was 91 of 91. It must now be 0, in BOTH runs — including the one
    whose freshness gate refused."""
    rows = request.getfixturevalue(run)["rows"]
    acc = [r for r in _decisions(rows) if r["status"] == tx.ACCEPTED]
    assert acc
    failed = [(r["explain_id"], f["name"]) for r in acc
              for f in r["feature_snapshot"] if f["passed"] is False]
    assert failed == [], failed[:5]


@pytest.mark.parametrize("run", ["fresh_run", "stale_run"])
def test_the_freshness_reading_is_still_recorded_somewhere(run, request):
    """Not cited as proof is not the same as thrown away. Losing it would replace one
    wrong answer with no answer."""
    rows = request.getfixturevalue(run)["rows"]
    ctx = _context(rows)
    assert len(ctx) == 1, f"expected exactly one run-context record, got {len(ctx)}"
    assert ctx[0]["rule_ids"] == ["CONTEXT.FRESHNESS_OBSERVED"]
    f = next(f for f in ctx[0]["feature_snapshot"] if f["name"] == "freshness_allow")
    assert f["value"] is request.getfixturevalue(run)["summary"]["freshness"]["allow"]
    assert ctx[0]["inputs_summary"]["binding"] is False


def test_the_context_record_names_the_refusal_when_the_gate_refused(stale_run):
    ctx = _context(stale_run["rows"])[0]
    assert ctx["reason_code"] == tx.FRESHNESS_FAIL


def test_the_context_record_says_none_when_the_gate_passed(fresh_run):
    assert _context(fresh_run["rows"])[0]["reason_code"] == tx.NONE


@pytest.mark.parametrize("run", ["fresh_run", "stale_run"])
def test_every_row_still_validates(run, request):
    rows = request.getfixturevalue(run)["rows"]
    assert rows
    bad = [(r["explain_id"], tx.validate(r)) for r in rows if tx.validate(r)]
    assert bad == [], bad[:3]


# ── the binding contract ─────────────────────────────────────────────────────
class _Cand:
    trade_id, sleeve, instrument, direction, qty = "T1", "roska4_stress", "MNQ", "SHORT", 7
    risk_dollars, entry_time, exit_time = 100.0, "2026-08-24 10:35", None
    entry_price, stop_price, source, meta = 1.0, 0.9, "", {}


class _Take:
    candidate, verdict, detail, forced_closes = _Cand(), "take", "", ()


def _build(mode, allow):
    return r1.explanations_for([_Take()], regime_csv="spy_daily_live.csv",
                               data_paths=r1.default_data_paths(),
                               fill_law="artifact_all_bars_gappable",
                               freshness_allow=allow, mode=mode)


@pytest.mark.parametrize("mode", sorted(tx.FRESHNESS_BINDING_MODES))
def test_a_binding_mode_refuses_to_record_an_admission_while_freshness_failed(mode):
    """Refused, not downgraded to a rejection. A candidate the engine admitted is not the
    same thing as one it refused, and writing the second would invent a decision."""
    with pytest.raises(r1.FreshnessRefused, match="freshness gate refused"):
        _build(mode, allow=False)


@pytest.mark.parametrize("mode", sorted(tx.FRESHNESS_BINDING_MODES))
def test_a_binding_mode_cites_and_passes_the_gate_when_it_allowed(mode):
    rec = _build(mode, allow=True)[0]
    assert "GATE.FRESHNESS" in rec["rule_ids"]
    f = next(f for f in rec["feature_snapshot"] if f["name"] == "freshness_allow")
    assert f["value"] is True and f["passed"] is True
    assert tx.validate(rec) == []


def test_replay_is_not_a_binding_mode_and_builds_either_way():
    for allow in (True, False):
        rec = _build(tx.REPLAY, allow)[0]
        assert "GATE.FRESHNESS" not in rec["rule_ids"]
        assert tx.validate(rec) == []


# ── the validator invariants that hold in every mode ─────────────────────────
def _hand_built(mode, *, freshness_passed=True, cite_freshness=None):
    rules = list(tx.ACCEPTED_PROOF_RULES_BY_MODE[mode])
    if cite_freshness and "GATE.FRESHNESS" not in rules:
        rules.append("GATE.FRESHNESS")
    feats = [tx.Feature("cluster_gross_after", 0.01, 0.1, "<=", True),
             tx.Feature("allow_new_entries", True, True, "==", True)]
    if "GATE.FRESHNESS" in rules:
        feats.append(tx.Feature("freshness_allow", freshness_passed, True, "==",
                                freshness_passed))
    return tx.decision_record(
        route=tx.ROUTE, session_date="2026-08-24", sleeve="roska4_stress",
        instrument="MNQ", candidate_id="X", decision_time="2026-08-24 10:35",
        decision_mode=mode, status=tx.ACCEPTED, reason_code=tx.TAKE,
        rule_ids=rules, features=feats,
        identity=tx.Identity(params_hash="x", fill_law=tx.FILL_LAWS[0], git_commit=None))


@pytest.mark.parametrize("mode", sorted(tx.FRESHNESS_BINDING_MODES))
def test_a_live_record_with_a_failed_freshness_proof_cannot_validate(mode):
    rec = _hand_built(mode, freshness_passed=False)
    errs = tx.validate(rec)
    assert any("marked FAILED" in e for e in errs), errs


def test_a_replay_record_that_cites_the_freshness_gate_is_refused():
    rec = _hand_built(tx.REPLAY, cite_freshness=True)
    errs = tx.validate(rec)
    assert any("may not cite GATE.FRESHNESS" in e for e in errs), errs


@pytest.mark.parametrize("mode", tx.DECISION_MODES)
def test_the_mode_specific_proof_set_is_enforced(mode):
    for missing in tx.ACCEPTED_PROOF_RULES_BY_MODE[mode]:
        rec = _hand_built(mode)
        rec["rule_ids"] = [r for r in rec["rule_ids"] if r != missing]
        rec["code_refs"] = [r for r in rec["code_refs"] if r["rule_id"] != missing]
        rec["evidence_refs"] = [r for r in rec["evidence_refs"]
                                if r["rule_id"] != missing]
        errs = tx.validate(rec)
        assert any(missing in e for e in errs), (mode, missing, errs)


def test_an_unknown_decision_mode_is_refused():
    rec = _hand_built(tx.REPLAY)
    rec["decision_mode"] = "whatever"
    assert any("decision_mode" in e for e in tx.validate(rec))


def test_decision_mode_is_a_required_field():
    rec = _hand_built(tx.REPLAY)
    assert "decision_mode" in tx.REQUIRED_FIELDS
    rec.pop("decision_mode")
    assert any("decision_mode" in e for e in tx.validate(rec))


def test_the_schema_version_was_bumped_for_the_new_required_field():
    assert tx.SCHEMA_VERSION == "track1_explain/2"
    rec = _hand_built(tx.REPLAY)
    assert rec["schema_version"] == "track1_explain/2"


# ── Part C: the root / write bound ───────────────────────────────────────────
def test_a_relocated_root_is_allowed_only_under_its_own_shadow_directory(tmp_path):
    got = tx.resolve_shadow_dir(root=tmp_path)
    assert got == (tmp_path / tx.SHADOW_ROOT).resolve()


@pytest.mark.parametrize("bad", [
    "global_index", "monitor", "monitor/backend", ".", "..",
    "scratch", "scratch/track1_shadow/../../global_index",
    "scratch/track1_shadow/../..", "../scratch/track1_shadow",
])
def test_every_other_destination_is_refused_even_under_a_temp_root(tmp_path, bad):
    with pytest.raises(tx.ShadowPathRefused):
        tx.resolve_shadow_dir(bad, root=tmp_path)


def test_an_absolute_path_outside_the_root_is_refused(tmp_path):
    other = tmp_path.parent / "somewhere_else"
    with pytest.raises(tx.ShadowPathRefused):
        tx.resolve_shadow_dir(str(other), root=tmp_path)


def test_a_subdirectory_of_the_shadow_root_is_allowed(tmp_path):
    """The per-window layout depends on this, so it is pinned rather than assumed."""
    got = tx.resolve_shadow_dir(f"{tx.SHADOW_ROOT}/explanations/{WINDOW}", root=tmp_path)
    assert (tmp_path / tx.SHADOW_ROOT).resolve() in got.parents


def test_there_is_no_flag_that_switches_the_bound_off():
    """A guard with an override is a guard that will be overridden. Read the signature
    rather than trusting the docstring."""
    import inspect
    for fn in (tx.resolve_shadow_dir, tx.write_shadow, tx._resolve_shadow):
        params = set(inspect.signature(fn).parameters)
        assert not (params & {"allow_any_path", "force", "unsafe", "override",
                              "allow_outside", "bypass"}), (fn.__name__, params)


def test_the_writer_lands_under_a_temp_root_and_nowhere_else(tmp_path):
    rec = _hand_built(tx.SHADOW_LIVE)
    path = tx.write_shadow([rec], session_date="2026-08-24",
                           out_dir=f"{tx.SHADOW_ROOT}/explanations/{WINDOW}",
                           root=tmp_path)
    assert (tmp_path / tx.SHADOW_ROOT).resolve() in path.resolve().parents
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == [path]


# ── Part C: zero decisions must still resolve and still report ───────────────
def test_a_zero_decision_run_resolves_the_destination_and_reports_zero(tmp_path):
    out = r1.emit_explanations([], out_dir=r1.SHADOW_DIR, window=WINDOW,
                               regime_csv="spy_daily_live.csv",
                               data_paths=r1.default_data_paths(),
                               fill_law="artifact_all_bars_gappable",
                               freshness_allow=True, root=str(tmp_path))
    assert out["explanations_written"] == 0
    assert out["records"] == 0
    assert out["destination_resolved"].endswith(str(Path(WINDOW)))
    # the run context record is still written — "the gate was read and said X" is a fact
    # about the run, and a run that recorded nothing cannot be told from one that never ran
    assert out["context_records"] == 1
    assert out["rows_written"] == 1


def test_a_zero_decision_run_aimed_at_a_legacy_directory_is_still_refused(tmp_path):
    """The fail-open shape Stage 5Y caught: with no rows the destination was never
    resolved, so a run pointed at a legacy directory passed quietly."""
    with pytest.raises(tx.ShadowPathRefused):
        r1.emit_explanations([], out_dir="global_index", window=WINDOW,
                             regime_csv="spy_daily_live.csv", data_paths={},
                             fill_law="artifact_all_bars_gappable",
                             freshness_allow=True, root=str(tmp_path))


def test_the_summary_always_carries_the_written_count(fresh_run):
    e = fresh_run["summary"]["explanations"]
    for field in ("explanations_written", "rows_written", "context_records",
                  "destination_resolved", "mode", "freshness_binding", "freshness_allow"):
        assert field in e, field
    assert e["explanations_written"] == e["decisions"]


# ── legacy boundary, again ───────────────────────────────────────────────────
LEGACY_PATHS = (
    "live_positions.json", "trade_log.jsonl", "runner.pid",
    "global_index/live_state_data.js", "global_index/replay_checkpoint.json",
    "global_index/paper_history.json", "monitor/paper_pnl_compare.json",
    "STOP_TRADING", "track1_go_live_confirmation.json",
)


def _fingerprint():
    out = {}
    for rel in LEGACY_PATHS:
        p = _ROOT / rel
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT"
    for pattern in ("live_day_*.log", "global_index/runner_events_*.jsonl"):
        for p in sorted(_ROOT.glob(pattern)):
            out[str(p.relative_to(_ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
    # `scheduler_*.log` is deliberately NOT fingerprinted, and the reason is measured rather
    # than assumed. On 2026-08-24 this test failed on `scheduler_0824.log` changing between
    # the two fingerprints — because the LIVE scheduler was running and its Stress slots
    # append to it every five minutes. That is a different process doing its job, not this
    # route touching a legacy path, and a guard that goes red whenever the system is running
    # is a guard people learn to skip.
    #
    # The property is kept, by a stronger check that another process cannot disturb: the
    # shadow entry point must not NAME the file at all. See the test below.
    return out


def test_the_shadow_path_cannot_write_the_scheduler_log():
    """The half of `_fingerprint` that had to move out of it.

    Source-level, because a live scheduler appending to its own log makes the runtime check
    unusable on a running box — and because this asks the sharper question anyway: not "did
    the file change" but "could this route write it at all".
    """
    import ast
    src = (_ROOT / "global_index" / "run_live_day_track1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    # STRING LITERALS only, and docstrings excluded. The first version of this assertion was
    # `".log" not in src` and it went red on the module DOCSTRING, which describes the very
    # files the route must not write. That is a substring test over free text — the same
    # shape as the freshness check Stage 5Q-2 replaced — and it fails on prose while proving
    # nothing about code.
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr)                 and isinstance(body[0].value, ast.Constant)                 and isinstance(body[0].value.value, str):
            docstrings.add(id(body[0].value))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings]
    bad = [v for v in literals if "scheduler_" in v or v.endswith(".log")]
    assert bad == [], f"the shadow entry point names a scheduler/log file: {bad}"


def test_no_legacy_path_is_touched(tmp_path):
    before = _fingerprint()
    assert len(before) >= 8 and sum(v != "ABSENT" for v in before.values()) >= 3
    r1.run_shadow(window=WINDOW, regime_csv="spy_daily_live.csv", now_et=STALE_AT,
                  root=str(tmp_path))
    assert _fingerprint() == before


def test_the_real_shadow_directory_is_not_written_by_this_suite():
    """A parallel session is working in `scratch/track1_shadow`. Nothing here may write
    there, and the per-window explanations directory must not appear under it."""
    real = _ROOT / r1.SHADOW_DIR / r1.EXPLAIN_SUBDIR
    assert not real.exists(), f"this suite wrote into the real shadow tree: {real}"
