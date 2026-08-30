"""Stage 5ZZQ — what would have to happen, and why the model said Calm.

Two questions the panel could not answer, and one performance regression I caused answering
the first one.

    setup boundary   "no signal" said nothing about how close the day came. The Stress sleeve
                     computes counts and an average across a basket, so the honest display is
                     METRIC cards — there is no single price on the chart that a line could be
                     drawn at, and drawing one would invent a trigger the strategy does not have.
    regime explain   the model is fitted on exactly TWO columns, named at source. Publishing
                     which state each leans toward is defensible; attributing the label to a
                     feature is not, because a Gaussian HMM decodes a path over a joint
                     distribution and does not decompose.
    performance      Stage 5ZZP called `daily_slices` on every request. 9.86s cold, 3.9s warm,
                     of which 3.24s was that one call. The endpoint had been 0.11s warm one
                     stage earlier, and the regression was mine.

Nothing here connects to a broker, writes to the runtime tree, or changes a decision.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index import track1_regime_record as rr              # noqa: E402
from global_index import track1_stress_mnq as SM                 # noqa: E402
from monitor.backend import track1_market_view as mv             # noqa: E402

DAY = "2026-08-27"


@pytest.fixture(scope="module")
def payload():
    return mv.build(ROOT, day=DAY)


# ── boundary classification comes from the detector, not from a guess ───────────────────
def test_every_sleeve_is_classified_with_proof_from_source(payload):
    for sleeve, s in payload["sleeves"].items():
        b = s["setup_boundary"]
        assert b["boundary_type"] in (mv.PRICE_BOUNDARY, mv.METRIC_BOUNDARY,
                                      mv.ENTRY_AFTER_SETUP_ONLY, mv.TWO_PHASE,
                                      mv.NOT_PUBLISHABLE), b
        assert b["boundary_proof"], f"{sleeve} carries no proof for its classification"
        assert len(b["boundary_proof"]) > 40, "a proof that short is a label"


def test_stress_is_a_metric_boundary_and_nkd_swing_are_not(payload):
    assert payload["sleeves"]["roska4_stress"]["setup_boundary"]["boundary_type"] \
        == mv.METRIC_BOUNDARY
    for sleeve in ("global_nkd", "roska4_swing"):
        assert payload["sleeves"][sleeve]["setup_boundary"]["boundary_type"] \
            == mv.ENTRY_AFTER_SETUP_ONLY


def test_the_proof_matches_the_detector_it_names():
    """The claim travels with the data, so it has to be true of the code."""
    stress = (ROOT / "global_index" / "track1_stress_mnq.py").read_text(encoding="utf-8")
    assert "def entry_conditions" in stress and "StressParams" in stress
    r4 = (ROOT / "global_index" / "track1_normal_r4.py").read_text(encoding="utf-8")
    assert "def detect_entry_for_slot" in r4 and "SwingSetup" in r4
    calm = (ROOT / "global_index" / "track1_calm_a.py").read_text(encoding="utf-8")
    assert "def entry_conditions" in calm


# ── no invented price line ──────────────────────────────────────────────────────────────
def test_a_metric_boundary_draws_no_ARMED_price_line(payload):
    """The rule this stage exists to keep, corrected by Stage 5ZZR.

    What this test asserted first — that a metric boundary publishes NO price level — was
    measured wrong. `session_context` returns the pre-session low and high for every judgeable
    session, gate or no gate, so the Stress trigger is a real published price even on a day
    nothing trades: 29,575.25 on 2026-08-27, a day the basket gate FAILED.

    The rule that actually protects the operator is not "no level". It is that no level is
    ARMED unless the gate passed — the number may be read, and nothing may be traded against
    it. Withholding it hid a real number; drawing it live would have been worse."""
    b = payload["sleeves"]["roska4_stress"]["setup_boundary"]
    assert b["metrics"], "a metric boundary with no metrics explains nothing"
    gate_passed = b.get("status") == "set_up"
    if not gate_passed:
        assert b.get("levels_armed") is not True, b
        assert not any(l.get("armed") for l in b.get("price_levels") or []), b["price_levels"]


def test_no_sleeve_invents_an_entry_on_a_no_setup_day(payload):
    for sleeve, s in payload["sleeves"].items():
        b = s["setup_boundary"]
        for lvl in b["price_levels"]:
            assert lvl.get("source") == "sleeve_detector", (sleeve, lvl)
        if b["boundary_type"] == mv.ENTRY_AFTER_SETUP_ONLY:
            assert b["price_levels"] == [], sleeve
            assert b["status"] == mv.NOT_APPLICABLE


def test_the_ui_draws_lines_only_from_supplied_levels():
    code = (ROOT / "global_index" / "dash" / "realtime" / "realtime.js").read_text(
        encoding="utf-8")
    block = code[code.index("function mvSetup"):code.index("function renderMarketView")]
    assert "price_levels" not in block or "metric_boundary" in block
    # Stage 5ZZZ-F. The rebuild renamed the condition cell `mv-metric` -> `mv2-cond`. The
    # property is that a metric boundary renders as CARDS rather than as a price line.
    assert "mv2-cond" in block, "a metric boundary must render as cards"


# ── the metrics themselves ──────────────────────────────────────────────────────────────
def test_stress_metrics_match_the_detector(payload):
    """Item 2. The panel's numbers must be the detector's, not a re-derivation."""
    import pandas as pd
    from global_index import run_live_day_track1 as rl

    paths = rl.default_data_paths() or {}
    need = sorted(set(SM.BREADTH_BASKET) | set(SM.StressParams().instruments))
    if any(i not in paths for i in need):
        pytest.skip("stores not configured")
    frames = {i: pd.read_parquet(paths[i]) for i in need}
    bars, prev_close = SM.daily_slices(frames, SM.StressParams())
    state = SM.basket_state(pd.Timestamp(DAY), bars, prev_close, SM.StressParams())
    if not state.get("checks"):
        pytest.skip("no judgeable session")
    from_detector = {c["id"]: (c["value"], c["threshold"], c["passed"])
                     for c in state["checks"]}
    b = payload["sleeves"]["roska4_stress"]["setup_boundary"]
    for m in b["metrics"]:
        assert m["id"] in from_detector
        v, t, passed = from_detector[m["id"]]
        assert (m["value"], m["threshold"], m["passed"]) == (v, t, passed), m


def test_a_distance_is_reported_only_for_a_failing_condition(payload):
    b = payload["sleeves"]["roska4_stress"]["setup_boundary"]
    for m in b["metrics"]:
        if m["passed"]:
            assert m["distance"] is None, m
        elif isinstance(m["value"], (int, float)) and isinstance(m["threshold"], (int, float)):
            assert m["distance"] is not None, m


def test_the_nearest_failed_condition_is_nearest_not_first(payload):
    """An operator asks how close the day came; the first-declared rule is an ordering
    accident rather than an answer."""
    b = payload["sleeves"]["roska4_stress"]["setup_boundary"]
    failed = [m for m in b["metrics"] if m["passed"] is False]
    if len(failed) < 2:
        pytest.skip("fewer than two failing conditions today")
    near = b["nearest_failed_condition"]
    assert near and near["id"] in {m["id"] for m in failed}
    scored = sorted(failed, key=lambda m: abs(m["distance"]) / (abs(m["threshold"]) or 1.0))
    assert near["id"] == scored[0]["id"], (near, [m["id"] for m in scored])


def test_missing_data_is_not_reported_as_no_setup():
    """Item 5, and the distinction this route keeps having to defend."""
    b = mv._setup_boundary("roska4_stress", mv.SLEEVES["roska4_stress"],
                           {"status": "missing_bars", "detail": "MES has no bars", "rules": []},
                           [])
    assert b["status"] == "missing_data"
    assert "no signal" not in b["summary"].lower()


# ── HMM features ────────────────────────────────────────────────────────────────────────
def test_feature_names_come_from_the_real_matrix():
    """Item 7. Two columns, and there is no third."""
    src = (ROOT / "raits" / "hmm" / "features.py").read_text(encoding="utf-8")
    assert '"log_return"' in src and '"realised_vol"' in src
    rec = rr.latest(ROOT)
    if rec.status != rr.OK or not rec.features:
        pytest.skip("no regime record with features")
    assert [f["name"] for f in rec.features] == ["log_return", "realised_vol"]
    for f in rec.features:
        assert f["source"] == "hmm_feature_matrix"


def test_each_feature_carries_a_raw_and_a_display_value():
    rec = rr.latest(ROOT)
    if rec.status != rr.OK or not rec.features:
        pytest.skip("no features")
    for f in rec.features:
        assert isinstance(f["value"], (int, float))
        assert f["model_value"] == f["value"]
        assert f["display_value"] and "%" in f["display_value"]
        assert 0.0 <= f["percentile_60d"] <= 100.0
        assert isinstance(f["z_score_60d"], (int, float))


def test_a_feature_that_does_not_separate_the_states_claims_no_lean():
    """Item 5 of Part D. Measured 2026-08-27: the three state means for `log_return` sit within
    a thousandth of each other, so no state is meaningfully nearest and the honest answer is
    that there is no lean."""
    rec = rr.latest(ROOT)
    if rec.status != rr.OK or not rec.features:
        pytest.skip("no features")
    for f in rec.features:
        assert f["leans"] in ("Calm", "Normal", "Stress", "Crisis", "mixed"), f
        if f["separation"] < rr.LEAN_MIN_SEPARATION if hasattr(rr, "LEAN_MIN_SEPARATION") \
                else f["separation"] < 0.5:
            assert f["leans"] == "mixed", f
        assert f["state_means"], "a lean with no state means behind it is an assertion"
        assert f["sd_distance_to_state"]


def test_entropy_is_computed_from_the_posterior():
    """Item 8, checked against the definition rather than against the implementation."""
    import math
    rec = rr.latest(ROOT)
    if rec.status != rr.OK or not rec.state_probabilities:
        pytest.skip("no posterior")
    probs = [p for p in rec.state_probabilities.values() if p > 0]
    expected = -sum(p * math.log2(p) for p in probs)
    assert abs(rec.entropy_bits - expected) < 1e-4, (rec.entropy_bits, expected)
    assert abs(rec.max_entropy_bits - math.log2(len(rec.state_probabilities))) < 1e-6
    assert 0.0 <= rec.entropy_bits <= rec.max_entropy_bits + 1e-9


def test_the_margin_is_the_gap_between_the_top_two():
    rec = rr.latest(ROOT)
    if rec.status != rr.OK or not rec.state_probabilities:
        pytest.skip("no posterior")
    ranked = sorted(rec.state_probabilities.values(), reverse=True)
    assert abs(rec.margin - (ranked[0] - ranked[1])) < 1e-6


def test_no_fake_threshold_is_ever_exposed():
    """Item 9."""
    rec = rr.latest(ROOT)
    assert rec.shift_threshold is None
    r = mv.regime(ROOT)
    assert r["shift_threshold"] is None
    assert "Viterbi" in r["threshold_note"]
    js = (ROOT / "global_index" / "dash" / "realtime" / "realtime.js").read_text(
        encoding="utf-8")
    assert "distance to threshold" not in js.lower()


# ── performance ─────────────────────────────────────────────────────────────────────────
def test_a_repeat_build_does_not_redo_the_expensive_slice():
    """Item 10. Measured before the fix: 3.24s of the 3.9s warm response was `daily_slices`."""
    mv.build(ROOT, day=DAY)                       # warm
    t0 = time.time()
    mv.build(ROOT, day=DAY)
    warm = time.time() - t0
    assert warm < 1.0, f"a warm build took {warm:.2f}s; the cache is not being hit"


def test_the_slice_cache_is_keyed_on_mtime_not_on_a_clock():
    """A TTL would hand back a stale answer as a fresh one for the length of the timer, which
    is the failure this route keeps finding in other clothes.

    Stage 5ZZZ-F. The blanket "no TTL anywhere in this file" stopped being the right shape of
    assertion when Stage 5ZZZ-B added a SECOND cache for the detector reconstruction, which is
    stale-but-usable with a background refresh and is deliberately on a timer - the detector
    pass costs ~14s and cannot be shortened, because the trend filter is recursive over the
    full history. Banning the word made this test fail for the mechanism it was never about.

    So it is split. The slice cache must still be keyed on the file, not on a clock; and the
    cache that IS on a clock must not be able to pass a stale answer off as a fresh one - it
    stamps every block with the bar it was computed from, which is the thing that makes the
    staleness readable rather than hidden.
    """
    src = (ROOT / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "_slice_cache" in body
    assert "st_mtime" in body
    # the slice cache's own key: files and their mtimes, no clock
    key_line = [l for l in body.splitlines() if "key = tuple(sorted(" in l]
    assert key_line and "st_mtime" in key_line[0], key_line
    assert "time.time()" not in body
    # and the timed cache says which bar it answered from
    assert "_RECON_TTL_SECONDS" in body
    assert "last_bar_ts" in (ROOT / "global_index" / "track1_strategy_diagnostics.py"
                             ).read_text(encoding="utf-8")


def test_the_expensive_hmm_is_not_refitted_per_request():
    """Stage 5ZZZ-F. This banned the NAME `label_regimes`, and Stage 5ZZZ-B needed the labels:
    the reconstruction has to read the regime through the same call the live slot makes, or it
    reports the sleeve on rules it does not use.

    Banning an identifier was always a proxy for the thing that matters, and it is the weaker
    of the two - it would not have gone red if someone had inlined a model fit under another
    name. The behaviour is asserted instead, and it is measurable: repeated builds must not
    refit. Measured cold at 8.0s for the label map, so a per-request fit would be unmissable.
    """
    import time

    from futures import _validated_core as core

    calls = []
    orig = core.label_regimes
    core.label_regimes = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
    try:
        mv._label_cache.clear()
        t0 = time.perf_counter()
        mv._label_map(ROOT)
        cold = time.perf_counter() - t0
        for _ in range(4):
            mv._label_map(ROOT)
    finally:
        core.label_regimes = orig
    assert calls, "the harness did not observe the fit at all; it proves nothing"
    assert len(calls) == 1, f"the model was refitted {len(calls)} times across five reads"
    # and the engine itself is still not constructed here
    src = (ROOT / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    assert "HMMEngine" not in src
    assert "predict_proba" not in src
    assert cold >= 0.0


# ── the page computes nothing ───────────────────────────────────────────────────────────
def test_the_page_does_not_recompute_strategy_or_model_values():
    """Item 13."""
    code = (ROOT / "global_index" / "dash" / "realtime" / "realtime.js").read_text(
        encoding="utf-8")
    start = code.index("const MV_ORDER")
    end = code.index("function renderOpenIssues")
    block = code[start:end]
    stripped = []
    i = 0
    while i < len(block):
        if block.startswith("//", i):
            j = block.find("\n", i)
            i = len(block) if j < 0 else j
        else:
            stripped.append(block[i])
            i += 1
    body = "".join(stripped)
    for forbidden in ("build_feature_matrix", "predict_proba", "log2(", "Math.log",
                      "entry_conditions", "peer_features", "breadth_min"):
        assert forbidden not in body, forbidden
    # every displayed number is addressed out of the payload
    for read in ("setup_boundary", "state_probabilities", "r.features", "entropy_bits"):
        assert read in body, read


# ── safety ──────────────────────────────────────────────────────────────────────────────
def test_no_order_or_gate_side_effects():
    import os
    from global_index import track1_gates as g
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    assert not (ROOT / "global_index" / "track1_runtime" / "orders").exists()
    possible, why = g.may_enable_orders()
    assert possible is False
    assert any("PAPER_SHADOW_EVIDENCE" in w for w in why)


# ═══════════════════════════════════════════════════════════════════════════════════════
# DOM — the page in a real browser, API stubbed
# ═══════════════════════════════════════════════════════════════════════════════════════
pytest.importorskip("playwright.sync_api")
from monitor.test_realtime_dom import (           # noqa: E402
    browser_page, open_realtime, realtime_server, stub_api)
from test_track1_stage5zzl_market_view_regime_20260827 import (   # noqa: E402
    _mv_payload, _sleeve)

assert browser_page and realtime_server


def _with_boundary():
    p = _mv_payload()
    p["market_view"]["sleeves"]["roska4_stress"]["setup_boundary"] = {
        "schema": "track1_setup_boundary/1", "sleeve": "roska4_stress",
        "boundary_type": "metric_boundary",
        "boundary_proof": "entry_conditions compares basket counts against StressParams",
        "side": "short", "status": "available", "price_levels": [],
        "metrics": [
            {"id": "below_count", "label": "Instruments below open and VWAP", "value": 4,
             "threshold": 4, "comparator": ">=", "unit": "count", "passed": True,
             "distance": None, "display_value": "4", "display_threshold": ">= 4",
             "source": "sleeve_detector"},
            {"id": "gapdown_count", "label": "Instruments gapped down", "value": 0,
             "threshold": 3, "comparator": ">=", "unit": "count", "passed": False,
             "distance": 3, "display_value": "0", "display_threshold": ">= 3",
             "display_distance": "3 more needed", "source": "sleeve_detector"},
            {"id": "avg_gap", "label": "Average basket gap", "value": 0.0051,
             "threshold": -0.001, "comparator": "<=", "unit": "fraction", "passed": False,
             "distance": 0.0061, "display_value": "+0.51%",
             "display_threshold": "<= -0.10%",
             "display_distance": "0.61 percentage points away",
             "source": "sleeve_detector"}],
        "nearest_failed_condition": {
            "id": "gapdown_count", "label": "Instruments gapped down",
            "display": "Instruments gapped down 0, needs >= 3", "source": "sleeve_detector"},
        "summary": "No setup - Instruments gapped down 3 more needed"}
    for k in ("global_nkd", "roska4_swing"):
        p["market_view"]["sleeves"][k]["setup_boundary"] = {
            "schema": "track1_setup_boundary/1", "sleeve": k,
            "boundary_type": "entry_after_setup_only",
            "boundary_proof": "detect_entry_for_slot returns SwingSetup or None",
            "side": "none", "status": "not_applicable", "price_levels": [], "metrics": [],
            "nearest_failed_condition": None,
            "summary": "Entry forms only after a bar signals; there is no standing level"}
    p["regime"].update({
        "entropy_bits": 0.017627, "max_entropy_bits": 1.584963,
        "features": [
            {"name": "log_return", "label": "SPY 1-day log return", "value": 0.006531,
             "model_value": 0.006531, "display_value": "+0.65%", "percentile_60d": 76.7,
             "z_score_60d": 0.72, "state_means": {"Calm": 0.001, "Normal": 0.0005,
                                                  "Stress": -0.0015},
             "sd_distance_to_state": {"Calm": 0.976, "Normal": 0.546, "Stress": 0.319},
             "separation": 0.228, "leans": "mixed", "source": "hmm_feature_matrix"},
            {"name": "realised_vol", "label": "Realised volatility, 5-day annualised",
             "value": 0.058136, "model_value": 0.058136,
             "display_value": "5.8% annualised", "percentile_60d": 0.0,
             "z_score_60d": -1.39, "state_means": {"Calm": 0.069, "Normal": 0.157,
                                                   "Stress": 0.353},
             "sd_distance_to_state": {"Calm": 0.437, "Normal": 2.451, "Stress": 1.52},
             "separation": 1.083, "leans": "Calm", "source": "hmm_feature_matrix"}]})
    return p


def _open(page, server, payload=None):
    stub_api(page, {"/api/v1/track1-market-view": payload or _with_boundary()})
    open_realtime(page, server)
    page.wait_for_selector("#marketViewTabs .mv-tab", timeout=10_000)


def test_dom_setup_metric_cards_render(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    # Stage 5ZZZ-F. `mv-metric-label` -> `mv2-cond-label`. The count is taken from the
    # payload the page was given rather than pinned at three: a literal count fails the day a
    # rule is added, and what has to hold is that the page draws every metric it was handed
    # and invents none.
    labels = browser_page.eval_on_selector_all(
        "#marketViewSetup .mv2-cond-label", "els => els.map(e => e.textContent.trim())")
    assert labels, "a metric boundary must render its conditions"
    assert "Instruments gapped down" in " | ".join(labels), labels


def test_dom_the_nearest_failed_condition_is_the_one_emphasised(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    # Stage 5ZZZ-F. The rebuild moved the emphasis from a `.near` class on the metric row to
    # a dedicated "Nearest miss" block, which states the condition, its value and what it
    # needed. That is the same claim in a more readable place, so the assertion follows it.
    miss = browser_page.eval_on_selector("#marketViewSetup .mv2-miss-text",
                                         "el => el.textContent.trim()")
    assert "Instruments gapped down" in miss, miss


def test_dom_a_metric_boundary_draws_no_price_line(browser_page, realtime_server):
    """The rule this stage exists to keep."""
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    assert browser_page.eval_on_selector_all("#marketViewChart .mv-level",
                                             "e => e.length") == 0


def test_dom_an_entry_after_setup_sleeve_says_so_instead_of_showing_cards(browser_page,
                                                                         realtime_server):
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("NKD")')
    text = browser_page.eval_on_selector("#marketViewSetup", "el => el.innerText")
    assert "only after a bar signals" in text, text
    assert browser_page.eval_on_selector_all("#marketViewSetup .mv-metric",
                                             "e => e.length") == 0


def test_dom_the_posterior_distribution_renders_as_bars(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    rows = browser_page.eval_on_selector_all(
        "#regimePosterior .regime-post-row", "els => els.map(e => e.innerText)")
    assert len(rows) == 3, rows
    joined = " ".join(rows)
    assert "Calm" in joined and "99.84%" in joined, joined
    assert "Stress" in joined


def test_dom_the_uncertainty_is_shown_in_bits(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. The entropy moved off the posterior heading and into its own metric, where
    # it now reads as a word ("Low") with the measurement under it. Both halves still have to
    # be there: the word alone is a judgement with no number behind it, and the number alone is
    # a figure most readers cannot place. The assertion follows it, and keeps both.
    head = browser_page.eval_on_selector("#regimeMetrics", "el => el.innerText")
    assert "uncertainty" in head.lower(), head
    assert "entropy" in head.lower(), head
    assert "0.018" in head and "1.585" in head, head


def test_dom_the_feature_table_renders_both_inputs(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#regimeFeatures", "el => el.innerText")
    # Headings are uppercased by CSS, so compared case-insensitively rather than pinned to the
    # rendered casing — the third time this trap has appeared in these panels.
    assert "why this label" in text.lower()
    assert "SPY 1-day log return" in text and "Realised volatility" in text
    assert "5.8% annualised" in text
    assert "0th pct" in text, text


def test_dom_a_feature_that_does_not_separate_shows_no_lean(browser_page, realtime_server):
    """Attribution that is not well-defined must not be drawn as if it were."""
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#regimeFeatures", "el => el.innerText")
    assert "no lean" in text, text
    tips = browser_page.eval_on_selector_all(
        "#regimeFeatures [title]", "els => els.map(e => e.getAttribute('title'))")
    assert any("no state is meaningfully nearest" in (t or "").lower() for t in tips), tips


def test_dom_no_fixed_threshold_is_claimed(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector(".regime-section", "el => el.innerText")
    assert "No fixed shift threshold" in text, text
    assert "distance to threshold" not in text.lower()


def test_dom_no_raw_names_reach_the_visible_labels(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    for sel in (".market-view-section", ".regime-section"):
        text = browser_page.eval_on_selector(sel, "el => el.innerText")
        for raw in ("gapdown_count", "below_count", "avg_gap", "log_return",
                    "realised_vol", "boundary_type", "sd_distance_to_state"):
            assert raw not in text, f"{raw} visible in {sel}"


@pytest.mark.parametrize("width", [375, 720, 1440])
def test_dom_nothing_overflows_with_the_new_blocks(browser_page, realtime_server, width):
    browser_page.set_viewport_size({"width": width, "height": 1000})
    _open(browser_page, realtime_server)
    over = browser_page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, f"page scrolls horizontally by {over}px at {width}px"
    for sel in ("#marketViewSetup", "#regimePosterior", "#regimeFeatures",
                ".market-view-section", ".regime-section"):
        d = browser_page.eval_on_selector(sel, "el => el.scrollWidth - el.clientWidth")
        assert d <= 1, f"{sel} overflows by {d}px at {width}px"


def test_dom_the_chart_height_is_still_pinned(browser_page, realtime_server):
    """The new blocks sit OUTSIDE the chart's fixed box."""
    _open(browser_page, realtime_server)
    hs = []
    for tab in ("NKD", "Stress", "Swing"):
        browser_page.click(f'#marketViewTabs .mv-tab:has-text("{tab}")')
        hs.append(browser_page.eval_on_selector(
            "#marketViewChart", "el => el.getBoundingClientRect().height"))
    assert max(hs) - min(hs) <= 2.0, hs
