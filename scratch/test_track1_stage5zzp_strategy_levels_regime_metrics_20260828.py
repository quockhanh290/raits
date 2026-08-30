"""Stage 5ZZP — "not published" was not the same as "not computed".

Stage 5ZZL read the return types and reported that neither the sleeves nor the model published
anything underneath their verdicts. Reading the implementations shows otherwise, and the
distinction is the whole stage:

    Stress   `entry_conditions` compared four named values against four named thresholds and
             returned a bool. Every value was computed; only the join between value and
             threshold was thrown away, one frame below a slot that was writing
             `not_exposed_by_sleeve` into its own record.
    Regime   `label_regimes` returns strings, so 5ZZL concluded there was no score. The ENGINE
             has `predict_proba`. A posterior exists and is real.
    Volume   present in every instrument store, and simply not aggregated.

What is genuinely absent stays absent and says why — a regime THRESHOLD does not exist, because
Viterbi compares states against each other rather than against a cut.

Nothing here connects to a broker, writes to the runtime tree, or changes a decision.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_regime_record as rr              # noqa: E402
from global_index import track1_stress_mnq as SM                 # noqa: E402
from monitor.backend import track1_market_view as mv             # noqa: E402


# ── the refactor changed no decision ────────────────────────────────────────────────────
def _original_entry_conditions(feats, params=None):
    """`entry_conditions` exactly as it stood before Stage 5ZZP.

    Kept here as the baseline the equivalence is measured against. Comparing the new code with
    a re-reading of itself would be true by construction and prove nothing.
    """
    p = params or SM.StressParams()
    if feats["below_count"] < p.breadth_min:
        return False
    if feats["gapdown_count"] < p.gapdown_min:
        return False
    if feats["wide_count"] < p.wide_min:
        return False
    if p.avg_gap_max is not None and feats["avg_gap"] > p.avg_gap_max:
        return False
    return True


def _grid():
    for b, g, w in itertools.product(range(0, 8), range(0, 6), range(0, 4)):
        for ag in (-0.02, -0.005, -0.001, -0.0009, 0.0, 0.01):
            yield {"below_count": b, "gapdown_count": g, "wide_count": w, "avg_gap": ag}


PARAMSETS = [SM.StressParams(), SM.StressParams(avg_gap_max=None),
             SM.StressParams(breadth_min=1, gapdown_min=0), SM.StressParams(wide_min=2),
             SM.StressParams(avg_gap_max=0.0)]


def test_entry_conditions_is_unchanged_across_a_swept_grid():
    """Item 1. 5,760 combinations against the pre-refactor function."""
    cases = mismatch = 0
    for ps in PARAMSETS:
        for feats in _grid():
            cases += 1
            if _original_entry_conditions(feats, ps) != SM.entry_conditions(feats, ps):
                mismatch += 1
    assert cases == 5760, cases
    assert mismatch == 0, f"{mismatch} of {cases} decisions moved"


def test_a_nullable_threshold_does_not_vote():
    """`avg_gap_max` is nullable, and the original SKIPPED that comparison when it was unset
    rather than passing it. A check that voted 'pass' would be a different rule."""
    feats = {"below_count": 9, "gapdown_count": 9, "wide_count": 9, "avg_gap": 99.0}
    ps = SM.StressParams(avg_gap_max=None)
    assert SM.entry_conditions(feats, ps) is True
    gap = [c for c in SM.entry_checks(feats, ps) if c["id"] == "avg_gap"][0]
    assert gap["applicable"] is False
    assert gap["threshold"] is None


def test_the_decision_is_derived_from_the_checks_not_stated_twice():
    """One statement of the rule. Two would drift the first time a threshold moved."""
    for ps in PARAMSETS:
        for feats in list(_grid())[::37]:
            checks = SM.entry_checks(feats, ps)
            assert SM.entry_conditions(feats, ps) == all(c["passed"] for c in checks)


# ── the values are now published ────────────────────────────────────────────────────────
def test_every_rule_carries_its_value_and_its_threshold():
    """Item 3. This is what `not_exposed_by_sleeve` used to stand in for."""
    feats = {"below_count": 3, "gapdown_count": 4, "wide_count": 1, "avg_gap": -0.0021}
    checks = SM.entry_checks(feats)
    assert [c["id"] for c in checks] == ["below_count", "gapdown_count", "wide_count", "avg_gap"]
    for c in checks:
        assert c["value"] is not None
        assert c["label"] and not c["label"].islower(), "the label is for a person"
        assert c["comparator"] in (">=", "<=")
        assert c["source"] == "sleeve_detector"
    failed = [c for c in checks if not c["passed"]]
    assert [c["id"] for c in failed] == ["below_count"]


def test_basket_state_names_three_different_failures():
    """Item 5. 'no setup' and 'no bars' are not the same fact, and this route has been bitten
    by collapsing them before."""
    empty = SM.basket_state("2026-08-27", {}, {}, SM.StressParams())
    assert empty["set_up"] is False
    assert empty["reason"] == "missing_bars"
    assert empty["features"] is None
    assert empty["checks"] == []


@pytest.fixture(scope="module")
def real_bars():
    import pandas as pd
    from global_index import run_live_day_track1 as rl

    paths = rl.default_data_paths() or {}
    need = sorted(set(SM.BREADTH_BASKET) | set(SM.StressParams().instruments))
    if any(i not in paths for i in need):
        pytest.skip("the basket's stores are not configured on this checkout")
    frames = {i: pd.read_parquet(paths[i]) for i in need}
    return SM.daily_slices(frames, SM.StressParams())


def test_a_real_no_signal_day_reports_which_rule_failed(real_bars):
    """The point of the whole stage, on a real session."""
    bars, prev_close = real_bars
    state = SM.basket_state("2026-08-27", bars, prev_close, SM.StressParams())
    assert state["features"] is not None, "the values are computed even when there is no setup"
    assert state["checks"], "and they are reported"
    if not state["set_up"]:
        assert state["reason"] == "conditions_not_met"
        assert state["first_failed"], "a failure with no named rule explains nothing"
        assert state["detail"], state


def test_a_real_setup_day_still_sets_up(real_bars):
    """Guards the extraction from the other side: the days that used to set up still do."""
    import pandas as pd
    bars, prev_close = real_bars
    days = sorted({d for (d, _i) in bars.keys()})
    setups = [d for d in days[-400:]
              if SM.basket_state(d, bars, prev_close, SM.StressParams())["set_up"]]
    assert setups, "no setup in 400 sessions — this test would pass on a broken detector"
    for d in setups[:5]:
        st = SM.basket_state(d, bars, prev_close, SM.StressParams())
        assert all(c["passed"] for c in st["checks"])
        assert st["first_failed"] is None


# ── volume ──────────────────────────────────────────────────────────────────────────────
def test_volume_is_published_when_the_store_has_it():
    """Item 6. It was there the whole time; 5ZZL aggregated only OHLC."""
    p = mv.build(ROOT, day="2026-08-27")
    for sleeve, s in p["sleeves"].items():
        assert "volume_status" in s
        if s["volume_status"] == "present":
            assert all("volume" in b for b in s["bars"]), sleeve
            assert any(b["volume"] > 0 for b in s["bars"]), sleeve


def test_volume_status_keeps_zero_apart_from_absent():
    """MNKD genuinely reports zero volume on thin bars. A pane drawn from that says 'nothing
    traded', which is a claim about the market rather than about the store."""
    assert mv._volume_status([]) == "not_available"
    assert mv._volume_status([{"time": "t"}]) == "not_available"
    assert mv._volume_status([{"volume": 0}, {"volume": 0}]) == "present_but_zero"
    assert mv._volume_status([{"volume": 0}, {"volume": 5}]) == "present"
    assert mv._volume_status([{"volume": 1}, {"time": "t"}]) == "partial"


def test_volume_is_never_synthesised():
    text = (ROOT / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    for forbidden in ("volume\" : 0", "volume=0", "fillna(0)", "or 0}"):
        assert forbidden not in body, forbidden


# ── regime metrics ──────────────────────────────────────────────────────────────────────
def test_a_real_score_is_published():
    """Item 7. 5ZZL reported `not exposed by model` from the return type of `label_regimes`.
    `HMMEngine.predict_proba` exists and the posterior is real."""
    rec = rr.latest(ROOT)
    if rec.status != rr.OK:
        pytest.skip("no regime record on this checkout")
    assert rec.score is not None
    assert 0.0 <= rec.score <= 1.0, rec.score
    assert rec.score_name == rr.SCORE_NAME
    assert rec.state_probabilities, "a single number in isolation is not evidence"
    assert abs(sum(rec.state_probabilities.values()) - 1.0) < 1e-3, rec.state_probabilities
    assert rec.label in rec.state_probabilities


def test_the_margin_is_named_a_margin_and_not_a_threshold_distance():
    rec = rr.latest(ROOT)
    if rec.status != rr.OK:
        pytest.skip("no regime record")
    assert rec.margin is not None
    assert rec.runner_up and rec.runner_up != rec.label
    assert "margin" in rec.margin_name
    assert "threshold" not in rec.margin_name


def test_the_absent_threshold_says_why_from_the_mechanism():
    """Item 7's other half. Not 'we could not find one' — there is none to find."""
    rec = rr.latest(ROOT)
    assert rec.shift_threshold is None
    assert "Viterbi" in rec.threshold_note
    assert "against a cut" in rec.threshold_note


def test_the_claim_about_viterbi_is_true_of_the_engine():
    """Proof from source, so the sentence above cannot quietly become wrong."""
    src = (ROOT / "raits" / "hmm" / "engine.py").read_text(encoding="utf-8")
    assert "def predict_current" in src and "self._model.predict(X)" in src
    assert "def predict_proba" in src and "predict_proba(X)" in src
    block = src[src.index("def predict_current"):src.index("def predict_proba")]
    assert "threshold" not in block.lower(), "predict_current compares against something"


def test_the_posterior_is_flagged_when_it_disagrees_with_the_label():
    """Viterbi decides; the posterior is a separate view. 'Usually agrees' is not 'is the same
    thing', so the record carries the flag rather than assuming."""
    rec = rr.latest(ROOT)
    if rec.status != rr.OK:
        pytest.skip("no regime record")
    assert rec.posterior_agrees_with_label in (True, False)


def test_the_regime_probe_is_still_recorded_not_computed_per_request():
    """The 8.54s reason from Stage 5ZZL still holds, and the score did not change it."""
    text = (ROOT / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    assert "label_regimes" not in text
    assert "rr.latest" in text or "latest(root)" in text


# ── the payload ─────────────────────────────────────────────────────────────────────────
def test_every_sleeve_reports_a_strategy_block():
    p = mv.build(ROOT, day="2026-08-27")
    for sleeve, s in p["sleeves"].items():
        st = s["strategy"]
        assert st["status"], sleeve
        assert "rules" in st and "detail" in st


def test_the_unwired_sleeves_say_so_rather_than_showing_nothing():
    """Item 4. An empty rule list means four different things; this names which."""
    p = mv.build(ROOT, day="2026-08-27")
    for sleeve in ("global_nkd", "roska4_swing"):
        st = p["sleeves"][sleeve]["strategy"]
        assert st["status"] == mv.NOT_COMPUTED_UNTIL_ENTRY
        assert "when a setup exists" in st["detail"]


def test_the_stress_block_carries_real_rule_values():
    p = mv.build(ROOT, day="2026-08-27")
    st = p["sleeves"]["roska4_stress"]["strategy"]
    if st["status"] in ("missing_bars", "session_not_judgeable"):
        pytest.skip(f"no judgeable session: {st['detail']}")
    assert st["rules"], st
    for c in st["rules"]:
        assert c["value"] is not None and c["threshold"] is not None or \
               c["source"] == mv.NOT_APPLICABLE


def test_the_payload_never_raises_on_a_broken_root(tmp_path):
    p = mv.build(tmp_path, day="2026-08-27")
    for s in p["sleeves"].values():
        assert s["strategy"]["status"]


# ── safety ──────────────────────────────────────────────────────────────────────────────
def test_no_order_or_gate_side_effects():
    import os
    from global_index import track1_gates as g
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    assert not (ROOT / "global_index" / "track1_runtime" / "orders").exists()
    possible, why = g.may_enable_orders()
    assert possible is False
    assert any("PAPER_SHADOW_EVIDENCE" in w for w in why)


def test_the_detector_still_opens_no_connection():
    text = (ROOT / "global_index" / "track1_stress_mnq.py").read_text(encoding="utf-8")
    for forbidden in ("IBKRBroker", "reqHistoricalData", "place_order", "send_order"):
        assert forbidden not in text, forbidden
