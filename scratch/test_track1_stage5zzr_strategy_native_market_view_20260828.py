"""Stage 5ZZR — each sleeve explained by the logic it actually uses.

The redesign brief first assumed NKD was basket-driven. It is not, and that assumption would
have produced the worst possible panel: four breadth lanes on a sleeve that never evaluates
breadth, permanently empty, reading as broken data forever.

    global_nkd     track1_normal_r4, ema_period=10
    roska4_swing   the SAME detector, ema_period=50
    roska4_stress  track1_stress_mnq  — the ONLY sleeve with breadth / gapdown / basket gap

And a correction to Stage 5ZZQ, which reported that Stress had no publishable price level.
`session_context` returns `pre_low` and `pre_high` for every judgeable session, gate passed or
not, and `first_low_break` scans for a one-minute low through `pre_low`. So Stress is two-stage
— a metric gate at 10:30, then a price trigger — and the levels are real. What Stage 5ZZQ was
right about is that they must not be drawn as if tradable on a day the gate failed, which is
what `armed` is for.

Nothing here connects to a broker, writes to the runtime tree, or changes a decision.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from monitor.backend import track1_market_view as mv             # noqa: E402

DAY = "2026-08-27"
JS = ROOT / "global_index" / "dash" / "realtime" / "realtime.js"


@pytest.fixture(scope="module")
def payload():
    return mv.build(ROOT, day=DAY)


# ── the corrected premise ───────────────────────────────────────────────────────────────
def test_nkd_and_swing_share_a_detector_and_stress_does_not():
    from monitor.backend.track1_market_view import BOUNDARY_KIND
    assert BOUNDARY_KIND["global_nkd"][0] == mv.ENTRY_AFTER_SETUP_ONLY
    assert BOUNDARY_KIND["roska4_swing"][0] == mv.ENTRY_AFTER_SETUP_ONLY
    assert BOUNDARY_KIND["roska4_stress"][0] == mv.METRIC_BOUNDARY
    src = (ROOT / "global_index" / "track1_live_sleeves.py").read_text(encoding="utf-8")
    assert "track1_normal_r4" in src


def test_nkd_never_shows_stress_basket_metrics(payload):
    """The assumption this stage had to correct. Breadth belongs to one sleeve."""
    stress_only = {"below open and VWAP", "gapped down", "wide range", "basket gap"}
    for sleeve in ("global_nkd", "roska4_swing"):
        labels = [m["label"] for m in payload["sleeves"][sleeve]["setup_boundary"]["metrics"]]
        for lab in labels:
            assert not any(s.lower() in lab.lower() for s in stress_only), (sleeve, lab)


def test_nkd_and_swing_name_their_own_decision_variables(payload):
    """`make_signal_fn(prev_bar, resume_bar, ema, atr, regime, avgv)` — those four, at this
    sleeve's own EMA period."""
    for sleeve, period in (("global_nkd", 10), ("roska4_swing", 50)):
        labels = [m["label"] for m in payload["sleeves"][sleeve]["setup_boundary"]["metrics"]]
        # Stage 5ZZZ-B renamed one of these when the values arrived: "Volume vs 10-bar average"
        # was a label for a number nobody had; the detector reports the volume and the average
        # separately, so the panel shows both and their ratio.
        assert f"Trend filter (EMA {period})" in labels, labels
        assert "Volume vs average" in labels or "Volume vs 10-bar average" in labels, labels
        assert "Daily ATR" in labels and "Regime" in labels


def test_a_prerequisite_either_carries_a_number_or_says_why_it_does_not(payload):
    """Stage 5ZZZ-B inverted this test, and the inversion is the point of that stage.

    It asserted that every one of these values reads "Not reported by detector" — which was an
    accurate description of the panel and an indictment of it. The detector computed all four
    for every bar it looked at and discarded them; it reports them now.

    What survives is the property underneath: a card never shows a blank. It carries a value, or
    it names the reason there is none, and those are the only two shapes allowed.
    """
    for sleeve in ("global_nkd", "roska4_swing"):
        metrics = payload["sleeves"][sleeve]["setup_boundary"]["metrics"]
        assert metrics, sleeve
        for m in metrics:
            assert m["display_value"], (sleeve, m)
            if m["missing"]:
                assert m["value"] is None, m
            else:
                assert m["value"] is not None, m


def test_the_missingness_vocabulary_keeps_five_answers():
    """Collapsing any two is how 'nobody looked' comes to read as 'we looked and found
    nothing'."""
    vals = {mv.MISSING_NOT_YET, mv.MISSING_NO_RECORD, mv.MISSING_REFUSED,
            mv.MISSING_DATA, mv.MISSING_NOT_REPORTED}
    assert len(vals) == 5


# ── Stress: the two stages ──────────────────────────────────────────────────────────────
def test_stress_publishes_the_price_levels_it_computes(payload):
    """Correcting Stage 5ZZQ. `session_context` returns these whether or not the gate passed."""
    b = payload["sleeves"]["roska4_stress"]["setup_boundary"]
    if b["status"] == "missing_data":
        pytest.skip("no judgeable session")
    kinds = {l["kind"] for l in b["price_levels"]}
    assert {"setup_trigger", "stop"} <= kinds, b["price_levels"]
    for l in b["price_levels"]:
        assert isinstance(l["price"], (int, float)) and l["price"] > 0
        assert l["source"] == "sleeve_detector"
        assert "armed" in l


def test_a_failed_gate_leaves_the_levels_unarmed_and_says_so(payload):
    b = payload["sleeves"]["roska4_stress"]["setup_boundary"]
    if b["status"] == "missing_data":
        pytest.skip("no judgeable session")
    gate_passed = all(m["passed"] for m in b["metrics"])
    assert b["levels_armed"] is gate_passed
    if not gate_passed:
        assert all(l["armed"] is False for l in b["price_levels"])
        assert "not armed" in b["levels_note"]


def test_stress_metric_gate_carries_thresholds_and_the_nearest_miss(payload):
    b = payload["sleeves"]["roska4_stress"]["setup_boundary"]
    if not b["metrics"]:
        pytest.skip("no judgeable session")
    for m in b["metrics"]:
        assert m["threshold"] is not None
        assert m["display_threshold"]
    failed = [m for m in b["metrics"] if m["passed"] is False]
    if failed:
        assert b["nearest_failed_condition"], b
        assert "needs" in b["nearest_failed_condition"]["display"]


# ── line rendering rules, read off the code that draws them ─────────────────────────────
def _js_block(fn_start: str, fn_end: str) -> str:
    code = JS.read_text(encoding="utf-8")
    return code[code.index(fn_start):code.index(fn_end)]


def test_lines_are_drawn_only_from_backend_levels():
    """Scoped to the LEVELS mapping only.

    A wider slice swept in the volume pane, whose `Math.max` is a bar height — geometry, not a
    strategy value. A forbidden-token scan is only as good as its boundary, and one drawn too
    wide fails on the wrong code and teaches whoever hits it to loosen the list.
    """
    block = _js_block("const bnd = sleeve.setup_boundary", "return `<svg class=\"mv-svg\"")
    block = block[:block.index("// Volume bars")]
    assert "bnd.price_levels" in block
    assert "Number(l.price)" in block
    for invented in ("* 1.0", "+ atr", "pre_low", "stop_price", "Math."):
        assert invented not in block, invented


def test_an_unarmed_level_is_drawn_differently_from_an_armed_one():
    block = _js_block("const bnd = sleeve.setup_boundary", "return `<svg class=\"mv-svg\"")
    assert "'mv-level armed'" in block and "'mv-level muted'" in block
    assert "not armed" in block
    css = (ROOT / "global_index" / "dash" / "realtime" / "realtime.css").read_text(
        encoding="utf-8")
    assert ".mv-level.muted" in css and ".mv-level.armed" in css
    muted = css[css.index(".mv-level.muted"):css.index(".mv-level.armed")]
    assert "dasharray" in muted, "the unarmed level must be visually distinct"


def test_an_empty_level_list_draws_nothing(payload):
    for sleeve in ("global_nkd", "roska4_swing"):
        assert payload["sleeves"][sleeve]["setup_boundary"]["price_levels"] == []


# ── the page computes nothing ───────────────────────────────────────────────────────────
def test_the_page_does_not_recompute_strategy_or_model_values():
    code = JS.read_text(encoding="utf-8")
    start, end = code.index("const MV_ORDER"), code.index("function renderOpenIssues")
    block, i = [], start
    while i < end:
        if code.startswith("//", i):
            j = code.find("\n", i)
            i = end if j < 0 else j
        else:
            block.append(code[i])
            i += 1
    body = "".join(block)
    for forbidden in ("entry_conditions", "peer_features", "breadth_min", "stop_price",
                      "build_feature_matrix", "predict_proba", "Math.log"):
        assert forbidden not in body, forbidden


def test_no_raw_variable_names_in_the_rendered_vocabulary():
    code = JS.read_text(encoding="utf-8")
    start, end = code.index("const MV_ORDER"), code.index("function renderOpenIssues")
    body = code[start:end]
    # These may be READ as payload keys; what must not happen is one reaching a visible label.
    assert "'Basket gate then price trigger'" in body
    assert "'Entry after setup bar'" in body
    for raw in ("'metric_boundary'", '"metric_boundary"'):
        # allowed only as a lookup key, never as displayed text
        assert f">{raw}<" not in body


# ── regime wording ──────────────────────────────────────────────────────────────────────
def test_the_regime_says_no_published_threshold_in_the_agreed_words():
    code = JS.read_text(encoding="utf-8")
    assert "No published shift threshold" in code
    # The EXPLANATION must not be written out here. It belongs to the model — track1_regime_record
    # owns it — and a second copy in the page is a copy that will disagree one day. The page is
    # required to read it instead, which is a stronger property than containing the words.
    assert "does not expose a simple flip" not in code, "the page must not restate the model"
    assert "r.threshold_note" in code, "the page must read the note the model publishes"
    import global_index.track1_regime_record as _rr
    assert "does not expose a simple flip" in _rr.NO_THRESHOLD
    assert "distance to threshold" not in code.lower()


def test_only_the_two_real_features_can_be_shown():
    from global_index import track1_regime_record as rr
    rec = rr.latest(ROOT)
    if rec.status != rr.OK or not rec.features:
        pytest.skip("no regime record")
    assert [f["name"] for f in rec.features] == ["log_return", "realised_vol"]
    src = (ROOT / "raits" / "hmm" / "features.py").read_text(encoding="utf-8")
    assert '"log_return"' in src and '"realised_vol"' in src


# ── safety ──────────────────────────────────────────────────────────────────────────────
def test_no_order_or_gate_side_effects():
    import os
    from global_index import track1_gates as g
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    assert not (ROOT / "global_index" / "track1_runtime" / "orders").exists()
    possible, why = g.may_enable_orders()
    assert possible is False
    assert any("PAPER_SHADOW_EVIDENCE" in w for w in why)


def test_the_backend_opens_no_connection():
    text = (ROOT / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    for forbidden in ("IBKRBroker", "reqHistoricalData", "connect(", "place_order"):
        assert forbidden not in text, forbidden


# ═══════════════════════════════════════════════════════════════════════════════════════
# DOM — the redesigned panel in a real browser
# ═══════════════════════════════════════════════════════════════════════════════════════
pytest.importorskip("playwright.sync_api")
from monitor.test_realtime_dom import (           # noqa: E402
    browser_page, open_realtime, realtime_server, stub_api)
from test_track1_stage5zzq_setup_boundaries_hmm_explain_20260828 import (   # noqa: E402
    _with_boundary)

assert browser_page and realtime_server

TRIGGER = 29575.25
STOP = 29662.38


def _payload(armed=False, with_levels=True):
    p = _with_boundary()
    st = p["market_view"]["sleeves"]["roska4_stress"]
    b = st["setup_boundary"]
    # Stage 5ZZZ-F. The hour the gate was decided at, which the backend now publishes from the
    # detector's own `setup_time` rather than the page spelling "10:30" into its markup. Four
    # metric values with no hour on them read as this minute's; they are the 10:30 bar's.
    b["decided_at_et"] = "10:30"
    b["price_levels"] = ([
        {"kind": "setup_trigger", "label": "Trigger (pre-session low)", "price": TRIGGER,
         "armed": armed, "source": "sleeve_detector", "detail": ""},
        {"kind": "stop", "label": "Planned stop", "price": STOP, "armed": armed,
         "source": "sleeve_detector", "detail": ""}] if with_levels else [])
    b["levels_armed"] = armed
    b["levels_note"] = ("" if armed else
                        "Trigger levels were computed at 10:30 but are not armed - "
                        "the setup gate did not pass")
    # bars must straddle the levels or the lines fall outside the drawn price range
    for i, bar in enumerate(st["bars"]):
        base = 29560 + i * 4
        bar.update(open=base, high=base + 30, low=base - 10, close=base + 12, volume=1000 + i)
    for k, period in (("global_nkd", 10), ("roska4_swing", 50)):
        p["market_view"]["sleeves"][k]["setup_boundary"].update({
            "price_levels": [], "levels_armed": False, "levels_note": "",
            "metrics": [{"id": None, "label": lab, "value": None, "threshold": None,
                         "comparator": "", "unit": None, "passed": None, "distance": None,
                         "display_value": "Not reported by detector", "display_threshold": "",
                         "missing": "not_reported_by_detector",
                         "source": "not_reported_by_detector"}
                        for lab in (f"Trend filter (EMA {period})", "Volume vs 10-bar average",
                                    "Daily ATR", "Regime")],
            "summary": "Entry forms only after a setup bar appears"})
    return p


def _open(page, server, payload=None):
    stub_api(page, {"/api/v1/track1-market-view": payload or _payload()})
    open_realtime(page, server)
    page.wait_for_selector("#marketViewTabs .mv-tab", timeout=10_000)


def _norm(page, sel):
    """innerText, case-folded.

    The stylesheet uppercases every label, and a case-sensitive assertion against one has now
    failed in four separate stages. Normalising once here is the durable fix; patching the
    fifth occurrence would not be.
    """
    return page.eval_on_selector(sel, "el => el.innerText").lower()


def _tab(page, name):
    page.click(f'#marketViewTabs .mv-tab:has-text("{name}")')


def test_dom_nkd_shows_its_own_prerequisites_not_basket_metrics(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    _tab(browser_page, "NKD")
    text = _norm(browser_page, "#marketViewSetup")
    assert "trend filter (ema 10)" in text, text
    assert "daily atr" in text and "volume vs 10-bar average" in text
    for basket in ("gapped down", "below open and vwap", "basket gap"):
        assert basket not in text, text
    assert "setup prerequisites" in text


def test_dom_nkd_says_entry_forms_after_a_setup_bar(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    _tab(browser_page, "NKD")
    text = browser_page.eval_on_selector("#marketViewSetup", "el => el.innerText")
    assert "only after a setup bar" in text.lower(), text


def test_dom_nkd_and_swing_draw_no_trade_lines(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    for tab in ("NKD", "Swing"):
        _tab(browser_page, tab)
        assert browser_page.eval_on_selector_all(
            "#marketViewChart .mv-level", "e => e.length") == 0, tab


def test_dom_stress_renders_the_gate_cards_with_its_decision_time(browser_page,
                                                                 realtime_server):
    _open(browser_page, realtime_server)
    _tab(browser_page, "Stress")
    text = browser_page.eval_on_selector("#marketViewSetup", "el => el.innerText")
    assert "10:30" in text, "the gate's decision time must be stated once"
    # Stage 5ZZZ-F. `mv-metric-label` -> `mv2-cond-label`, and the count comes from the
    # payload rather than a literal: the old `len == 3 or len == 4` was already a literal that
    # had been widened once, which is the shape of an assertion about to be widened again.
    labels = browser_page.eval_on_selector_all(
        "#marketViewSetup .mv2-cond-label", "els => els.map(e => e.textContent.trim())")
    expected = [m["label"] for m in _payload()["market_view"]["sleeves"]["roska4_stress"]
                ["setup_boundary"]["metrics"]]
    assert expected, "the fixture published no metrics; the assertion would pass on nothing"
    joined = " | ".join(labels)
    for label in expected:
        assert label in joined, (label, labels)


def test_dom_a_failed_gate_draws_muted_lines_never_active_ones(browser_page, realtime_server):
    """The rule this stage exists for: the numbers are real, and nothing is tradable."""
    _open(browser_page, realtime_server, _payload(armed=False))
    _tab(browser_page, "Stress")
    classes = browser_page.eval_on_selector_all(
        "#marketViewChart .mv-level", "els => els.map(e => e.getAttribute('class'))")
    assert classes, "the computed levels should still be visible"
    assert all("muted" in c for c in classes), classes
    assert not any("armed" in c for c in classes), classes
    text = browser_page.eval_on_selector("#marketViewChart", "el => el.innerText")
    assert "not armed" in text.lower(), text


def test_dom_an_armed_gate_draws_active_lines(browser_page, realtime_server):
    _open(browser_page, realtime_server, _payload(armed=True))
    _tab(browser_page, "Stress")
    classes = browser_page.eval_on_selector_all(
        "#marketViewChart .mv-level", "els => els.map(e => e.getAttribute('class'))")
    assert classes and all("armed" in c for c in classes), classes
    text = browser_page.eval_on_selector("#marketViewChart", "el => el.innerText")
    assert "not armed" not in text.lower(), text


def test_dom_muted_and_active_levels_are_visually_distinct(browser_page, realtime_server):
    """Measured, not asserted from the stylesheet: the two states must actually render
    differently or the distinction exists only in the class name."""
    _open(browser_page, realtime_server, _payload(armed=False))
    _tab(browser_page, "Stress")
    muted = browser_page.eval_on_selector(
        "#marketViewChart .mv-level",
        "el => [getComputedStyle(el).stroke, getComputedStyle(el).strokeDasharray].join('|')")
    _open(browser_page, realtime_server, _payload(armed=True))
    _tab(browser_page, "Stress")
    active = browser_page.eval_on_selector(
        "#marketViewChart .mv-level",
        "el => [getComputedStyle(el).stroke, getComputedStyle(el).strokeDasharray].join('|')")
    assert muted != active, (muted, active)


def test_dom_no_levels_means_no_lines(browser_page, realtime_server):
    _open(browser_page, realtime_server, _payload(with_levels=False))
    _tab(browser_page, "Stress")
    assert browser_page.eval_on_selector_all("#marketViewChart .mv-level",
                                             "e => e.length") == 0


def test_dom_the_strategy_type_chip_is_plain_english(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    _tab(browser_page, "Stress")
    chips = browser_page.eval_on_selector_all(
        "#marketViewSummary .mv-chip", "els => els.map(e => e.textContent.trim())")
    assert any("Basket gate then price trigger".upper() == c.upper() for c in chips), chips
    _tab(browser_page, "NKD")
    chips = browser_page.eval_on_selector_all(
        "#marketViewSummary .mv-chip", "els => els.map(e => e.textContent.trim())")
    assert any("Entry after setup bar".upper() == c.upper() for c in chips), chips


def test_dom_no_raw_variable_names_are_visible(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    for tab in ("NKD", "Stress", "Swing"):
        _tab(browser_page, tab)
        for sel in (".market-view-section", ".regime-section"):
            text = browser_page.eval_on_selector(sel, "el => el.innerText")
            for raw in ("metric_boundary", "entry_after_setup_only", "not_reported_by_detector",
                        "gapdown_count", "avg_gap", "pre_low", "levels_armed", "log_return",
                        "realised_vol", "price_levels"):
                assert raw not in text, f"{raw} visible on {tab} in {sel}"


def test_dom_the_regime_uses_the_agreed_threshold_wording(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    # Stage 5ZZZ-F. The panel states the absence as a row of its own - "Shift threshold /
    # None published" - and prints the MODEL's sentence underneath rather than the page's
    # fallback. The literal this test was written for is still in the source as that fallback,
    # which the sibling source-level test pins; what the rendered page must show is the
    # absence, named, with the model's own reason under it.
    text = browser_page.eval_on_selector(".regime-section", "el => el.innerText")
    low = text.lower()
    assert "shift threshold" in low and "none published" in low, text
    assert "distance to threshold" not in low
    assert "does not expose a simple flip" in text or "no cutoff number to breach" in text, text


def test_dom_the_regime_shows_only_the_two_real_features(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    text = browser_page.eval_on_selector("#regimeFeatures", "el => el.innerText")
    assert "SPY 1-day log return" in text and "Realised volatility" in text
    for absent in ("Range", "Trend/SMA", "Drawdown", "SMA"):
        assert absent not in text, f"{absent} is not a model input"
    # Stage 5ZZZ-F. The feature table is no longer a `<table>`; it is a row of `.rg2-feat`
    # cells. The count is the property - the model is fitted on two inputs and the panel must
    # show two, so a third appearing means something is being drawn that the model never saw.
    rows = browser_page.eval_on_selector_all("#regimeFeatures .rg2-feat", "e => e.length")
    assert rows == 2, rows


@pytest.mark.parametrize("width", [375, 720, 1440])
def test_dom_no_overflow_on_any_tab(browser_page, realtime_server, width):
    browser_page.set_viewport_size({"width": width, "height": 1000})
    _open(browser_page, realtime_server)
    for tab in ("NKD", "Stress", "Swing"):
        _tab(browser_page, tab)
        over = browser_page.evaluate(
            "() => document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth")
        assert over <= 1, f"page scrolls by {over}px on {tab} at {width}px"
        for sel in ("#marketViewSetup", "#marketViewChart", ".market-view-section",
                    ".regime-section", "#regimeFeatures"):
            d = browser_page.eval_on_selector(sel, "el => el.scrollWidth - el.clientWidth")
            assert d <= 1, f"{sel} overflows {d}px on {tab} at {width}px"


def test_dom_chart_height_is_stable_across_tabs(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    hs = []
    for tab in ("NKD", "Stress", "Swing"):
        _tab(browser_page, tab)
        hs.append(browser_page.eval_on_selector(
            "#marketViewChart", "el => el.getBoundingClientRect().height"))
    assert max(hs) - min(hs) <= 2.0, hs
