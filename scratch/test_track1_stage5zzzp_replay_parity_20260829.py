"""Stage 5ZZZ-P — the parity checker must not be able to flatter the route.

Every test here exists because the cheap failure mode of a parity tool is optimism: a missing
field read as agreement, a partial match read as a pass, a slot that predates the code being
checked read as evidence for it.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_replay_parity as P                # noqa: E402


def _row(**kw):
    base = {"route": P.ROUTE, "sleeve": "global_nkd", "session_date": "2026-08-28",
            "slot_id": "TRACK1_NKD_0255", "slot_time": "02:55",
            "data_source_identity": "global_index/data/NKD_continuous_1m_8y.parquet",
            "params_hash": "abc123", "_file_mtime": "2026-09-01T12:00:00"}
    base.update(kw)
    return base


def _rep(**kw):
    base = {"reconstructable": True, "sleeve": "global_nkd", "session_date": "2026-08-28",
            "data_source_identity": "NKD_continuous_1m_8y.parquet",
            "params_hash": "abc123", "regime_basis": "previous session (lag 1)"}
    base.update(kw)
    return base


def _compare(monkeypatch, row, rep, cutoff="2026-01-01T00:00:00"):
    monkeypatch.setattr(P, "replay_slot", lambda root, r: rep)
    return P.compare_slot(REPO, row, cutoff)


# ══════════════════════════════════════════════════════════════════════════════════════════
# the four verdicts behave
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_a_fully_matching_slot_passes(monkeypatch):
    """PASS has to be reachable, or every other verdict here is meaningless.

    Uses Stress, because it is the sleeve whose comparable fields are all recorded on both
    sides. NKD and Swing carry an extra regime-basis check that the live row has no field for -
    see the test below, which pins that as the structural gap it is rather than letting it
    quietly cap those two sleeves at UNKNOWN forever.
    """
    sp = _compare(monkeypatch, _row(sleeve="roska4_stress"), _rep(sleeve="roska4_stress"))
    assert sp.verdict == P.PASS, [(c.name, c.verdict) for c in sp.checks]
    assert sp.post_fix is True


def test_a_row_recording_its_basis_can_now_reach_pass(monkeypatch):
    """Stage 5ZZZ-P found this capped: the live row had no regime-basis field, so the two
    sleeves whose identity turns on it could never do better than UNKNOWN. Stage 5ZZZ-Q added
    the field, and a post-fix row that records it can now match."""
    sp = _compare(monkeypatch,
                  _row(sleeve="global_nkd", regime_basis="causal_d1"),
                  _rep(sleeve="global_nkd", regime_basis="previous session (lag 1)"))
    assert sp.verdict == P.PASS, [(c.name, c.verdict) for c in sp.checks]
    basis = [c for c in sp.checks if c.name == "regime_basis_recorded_vs_detector"]
    assert basis and basis[0].verdict == P.PASS


def test_a_row_written_before_the_field_existed_is_not_applicable(monkeypatch):
    """Old evidence is described, never judged by a rule it predates - and never rewritten."""
    sp = _compare(monkeypatch, _row(sleeve="global_nkd"), _rep(sleeve="global_nkd"),
                  cutoff="2099-01-01T00:00:00")
    basis = [c for c in sp.checks if c.name == "regime_basis_recorded_vs_detector"]
    assert basis and basis[0].verdict == P.NOT_APPLICABLE
    assert sp.verdict != P.PASS


def test_a_recorded_basis_that_contradicts_the_detector_fails(monkeypatch):
    """The check the brief asked for: a row claiming causal D-1 while the detector read the
    session's own label is a disagreement, not a match."""
    sp = _compare(monkeypatch,
                  _row(sleeve="roska4_swing", regime_basis="causal_d1"),
                  _rep(sleeve="roska4_swing", regime_basis="this session's own label"))
    assert sp.verdict == P.FAIL
    basis = [c for c in sp.checks if c.name == "regime_basis_recorded_vs_detector"]
    assert basis and basis[0].verdict == P.FAIL


def test_a_params_hash_mismatch_fails(monkeypatch):
    sp = _compare(monkeypatch, _row(params_hash="aaa"), _rep(params_hash="bbb"))
    assert sp.verdict == P.FAIL
    assert any(c.name == "params_hash" and c.verdict == P.FAIL for c in sp.checks)


def test_a_missing_params_hash_is_unknown_never_pass(monkeypatch):
    """The live rows on disk record an empty hash. That is a gap, not agreement."""
    sp = _compare(monkeypatch, _row(params_hash=""), _rep(params_hash="bbb"))
    assert sp.verdict == P.UNKNOWN
    assert any(c.name == "params_hash" and c.verdict == P.UNKNOWN for c in sp.checks)


def test_a_data_identity_mismatch_fails(monkeypatch):
    sp = _compare(monkeypatch, _row(), _rep(data_source_identity="MES_other_file.parquet"))
    assert sp.verdict == P.FAIL
    assert any(c.name == "data_source_identity" and c.verdict == P.FAIL for c in sp.checks)


def test_the_same_file_spelled_two_ways_is_not_a_mismatch(monkeypatch):
    """Live records a full path, the reconstruction a basename. Same file. A false FAIL is
    worse than an honest UNKNOWN because someone acts on it."""
    sp = _compare(monkeypatch,
                  _row(data_source_identity="global_index/data/NKD_continuous_1m_8y.parquet"),
                  _rep(data_source_identity="NKD_continuous_1m_8y.parquet"))
    assert any(c.name == "data_source_identity" and c.verdict == P.PASS for c in sp.checks)


def test_an_unreconstructable_context_is_unknown(monkeypatch):
    sp = _compare(monkeypatch, _row(),
                  {"reconstructable": False, "reason": "no persisted bar store"})
    assert sp.verdict == P.UNKNOWN
    assert "reconstruct" in sp.reason or "bar store" in sp.reason


def test_a_partial_match_is_unknown_not_pass(monkeypatch):
    """The single most important rule in the module."""
    sp = _compare(monkeypatch, _row(params_hash=""), _rep(params_hash=""))
    assert sp.verdict == P.UNKNOWN
    assert P.PASS in {c.verdict for c in sp.checks}, "some fields did match"
    assert "not a pass" in sp.reason


def test_a_slot_older_than_the_fixes_is_not_yet_observed(monkeypatch):
    """The rule that makes this stage's answer honest: matching an old slot proves nothing
    about code written after it ran."""
    monkeypatch.setattr(P, "replay_slot", lambda root, r: _rep())
    monkeypatch.setattr(P, "newest_slot",
                        lambda root, sleeve: _row(sleeve=sleeve,
                                                  _file_mtime="2026-08-01T00:00:00"))
    monkeypatch.setattr(P, "fix_cutoff",
                        lambda root: {"per_file": {}, "cutoff": "2026-08-29T00:00:00"})
    r = P.parity(REPO)
    for sleeve, v in r["sleeves"].items():
        assert v["verdict"] == P.NOT_YET, (sleeve, v["verdict"])
        assert "before the newest relevant fix" in v["reason"]
    assert r["summary"][P.PASS] == 0
    assert r["all_post_fix_observed"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════
# the sleeve-specific claims
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_swing_reading_the_sessions_own_label_fails(monkeypatch):
    """The declared paper identity is causal D-1. A detector on the session's own label is not
    that, and the parity check must say so rather than shrug."""
    sp = _compare(monkeypatch, _row(sleeve="roska4_swing"),
                  _rep(sleeve="roska4_swing", regime_basis="this session's own label"))
    assert sp.verdict == P.FAIL
    bad = [c for c in sp.checks if c.name == "swing_regime_basis_is_causal_d1"]
    assert bad and bad[0].verdict == P.FAIL


def test_swing_on_a_lagged_basis_passes_that_check(monkeypatch):
    sp = _compare(monkeypatch, _row(sleeve="roska4_swing"),
                  _rep(sleeve="roska4_swing", regime_basis="previous session (lag 1)"))
    good = [c for c in sp.checks if c.name == "swing_regime_basis_is_causal_d1"]
    assert good and good[0].verdict == P.PASS


def test_a_calm_observe_value_in_decide_fails(monkeypatch):
    rep = _rep(sleeve="roska4_calm",
               phases={"decide": {"rows": ["Stop rule", "Planned stop"], "price_levels": 0},
                       "observe": {"rows": [], "price_levels": 0}})
    sp = _compare(monkeypatch, _row(sleeve="roska4_calm"), rep)
    assert sp.verdict == P.FAIL
    leak = [c for c in sp.checks if c.name == "calm_decide_has_no_observe_value"]
    assert leak and leak[0].verdict == P.FAIL


def test_a_calm_price_level_in_decide_fails(monkeypatch):
    rep = _rep(sleeve="roska4_calm",
               phases={"decide": {"rows": ["Stop rule"], "price_levels": 1},
                       "observe": {"rows": [], "price_levels": 0}})
    sp = _compare(monkeypatch, _row(sleeve="roska4_calm"), rep)
    assert sp.verdict == P.FAIL
    lvl = [c for c in sp.checks if c.name == "calm_decide_has_no_price_level"]
    assert lvl and lvl[0].verdict == P.FAIL


def test_a_clean_calm_decide_passes_both_phase_checks(monkeypatch):
    rep = _rep(sleeve="roska4_calm",
               phases={"decide": {"rows": ["Stop rule", "Stop distance"], "price_levels": 0},
                       "observe": {"rows": ["Entry reference"], "price_levels": 0}})
    sp = _compare(monkeypatch, _row(sleeve="roska4_calm"), rep)
    for name in ("calm_decide_has_no_observe_value", "calm_decide_has_no_price_level"):
        c = [x for x in sp.checks if x.name == name]
        assert c and c[0].verdict == P.PASS, name


# ══════════════════════════════════════════════════════════════════════════════════════════
# read-only, and honest about what it is
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_module_never_writes_and_never_reaches_a_broker():
    import ast

    src = (REPO / "global_index" / "track1_replay_parity.py").read_text(encoding="utf-8")
    for forbidden in ("IBKRBroker", "ib_insync", "place_order", "submit_order",
                      "TRACK1_ORDERS_APPROVED", "allow_orders"):
        assert forbidden not in src, forbidden
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            assert name not in {"write_text", "write_bytes", "mkdir", "unlink", "touch",
                                "rename", "dump"}, name
            if name == "open":
                lits = [a.value for a in node.args[1:2] if isinstance(a, ast.Constant)]
                assert not any("w" in str(v) or "a" in str(v) for v in lits), lits


def test_it_never_claims_to_satisfy_shadow_evidence():
    r = P.parity(REPO)
    assert r["counts_toward_paper_shadow_evidence"] is False
    from global_index import track1_gates as g

    assert "PAPER_SHADOW_EVIDENCE" in {b.id for b in g.blocking()}
    ok, _ = g.may_enable_orders()
    assert ok is False


def test_the_gates_do_not_import_the_parity_module():
    import inspect

    from global_index import track1_gates as g

    assert "track1_replay_parity" not in inspect.getsource(g)


# ══════════════════════════════════════════════════════════════════════════════════════════
# the live run, as it actually stands
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_real_run_reports_no_post_fix_slot_for_any_sleeve():
    """Recorded as the state of the world on 2026-08-29. If a session runs after the fixes,
    this test changes - and it should be re-read rather than deleted."""
    r = P.parity(REPO)
    assert set(r["sleeves"]) == set(P.SLEEVES)
    assert r["summary"][P.PASS] == 0, "a PASS appeared; re-read before trusting it"
    assert r["summary"][P.NOT_YET] == 4
    assert r["runtime_diagnostics_store_present"] is False


def test_the_fix_cutoff_is_after_the_newest_live_slot():
    r = P.parity(REPO)
    cutoff = r["fix_cutoff"]["cutoff"]
    assert cutoff
    for sleeve, v in r["sleeves"].items():
        ran = (v.get("newest_live_slot") or {}).get("live_ran_at")
        if ran:
            assert ran < cutoff, (sleeve, ran, cutoff)
