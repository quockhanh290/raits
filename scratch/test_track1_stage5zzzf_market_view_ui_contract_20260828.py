"""Stage 5ZZZ-F — the market view reads the finished diagnostics contract, and computes nothing.

Four diagnostics stages put values into the payload. This stage is about what the page does
with them, and the two failures it was opened on were both cases of the panel answering from
a source that had stopped being the one that knows:

  * the summary chip said "Strategy levels unavailable" while the card below it drew a trigger
    at 29,592.50, a stop at 29,652.62 and a session open at 29,615.25. The note was computed
    from the signal rows alone, which is where levels used to come from.
  * the plot's height came from its content, so a session with no bars shrank the panel by
    320px and moved everything under it.

Both were found by MEASURING the payload and the rendered box rather than by reading the code
and forming a view about it.
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pandas as pd                                              # noqa: E402
from monitor.backend import track1_market_view as mv             # noqa: E402

DASH = REPO / "global_index" / "dash" / "realtime"
JS = DASH / "realtime.js"
HTML = DASH / "index.html"
CSS = DASH / "realtime.css"
ET = "America/New_York"
DAY = "2026-08-28"


@pytest.fixture(scope="module")
def payload():
    return mv.build(REPO, now=pd.Timestamp(f"{DAY} 23:00", tz=ET))


def _sleeves(p):
    return p["sleeves"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the contract: every diagnostics block declares where it came from
# ══════════════════════════════════════════════════════════════════════════════════════════

KNOWN_SOURCES = {"recorded_runtime", "reconstructed_today", "not_yet_run",
                 "not_reported_by_detector"}


def test_every_sleeve_publishes_a_strategy_block_that_names_its_source(payload):
    """An unlabelled reconstruction reads as a recorded one, and telling those apart is the
    single thing these stages exist for. The label was reachable only one level down, at
    `strategy.diagnostics.diagnostics_source`, so anything reading the strategy block itself
    got an answer with no provenance on it."""
    sleeves = _sleeves(payload)
    assert sleeves, "no sleeves at all; the assertions below would pass on nothing"
    for name, s in sleeves.items():
        st = s.get("strategy") or {}
        assert st.get("diagnostics_source") in KNOWN_SOURCES, (name, st.get("diagnostics_source"))


def test_every_setup_boundary_names_its_source_too(payload):
    for name, s in _sleeves(payload).items():
        sb = s.get("setup_boundary") or {}
        assert sb.get("diagnostics_source") in KNOWN_SOURCES, (name, sb)


def test_the_calm_phases_each_name_their_own_source(payload):
    phases = (payload.get("calm") or {}).get("phases") or {}
    assert set(phases) == {"decide", "observe"}, phases
    for k, b in phases.items():
        assert b.get("diagnostics_source") in KNOWN_SOURCES, (k, b)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. the note the panel was contradicting itself with
# ══════════════════════════════════════════════════════════════════════════════════════════

def _published(s):
    st, sb = s.get("strategy") or {}, s.get("setup_boundary") or {}
    return list(s.get("levels") or []) or list(
        st.get("price_levels") or sb.get("price_levels") or [])


def test_no_sleeve_says_levels_are_unavailable_while_publishing_levels(payload):
    """The finding. Measured on 2026-08-28: Stress published three prices and the chip above
    them read "Strategy levels unavailable"."""
    checked = 0
    for name, s in _sleeves(payload).items():
        if not _published(s):
            continue
        checked += 1
        assert mv.LEVELS_NOT_EXPOSED not in (s.get("levels_note") or ""), (
            f"{name} publishes {len(_published(s))} levels and calls them unavailable")
    assert checked, "no sleeve published a level today, so this proved nothing"


def test_a_sleeve_with_unarmed_levels_says_they_are_not_armed(payload):
    checked = 0
    for name, s in _sleeves(payload).items():
        levels = _published(s)
        st, sb = s.get("strategy") or {}, s.get("setup_boundary") or {}
        if not levels or (st.get("levels_armed") or sb.get("levels_armed")):
            continue
        checked += 1
        assert "not armed" in (s.get("levels_note") or "").lower(), (name, s.get("levels_note"))
    assert checked, "no sleeve had unarmed levels today"


def test_a_sleeve_with_no_levels_still_says_so(payload):
    for name, s in _sleeves(payload).items():
        if _published(s):
            continue
        assert s.get("levels_note") == mv.LEVELS_NOT_EXPOSED, (name, s.get("levels_note"))


def test_the_payload_wide_note_never_contradicts_the_sleeves(payload):
    """One string cannot describe three sleeves that disagree, so it says nothing when they do
    rather than picking one of them and being wrong about the others."""
    notes = {(s.get("levels_note") or "") for s in _sleeves(payload).values()}
    if len(notes) == 1:
        assert payload["levels_note"] == notes.pop()
    else:
        assert payload["levels_note"] == "", payload["levels_note"]


def test_the_stress_gate_states_the_hour_it_was_decided(payload):
    """Four metric values with no hour on them read as this minute's. They are the 10:30
    bar's, and the hour comes from the detector's own parameter."""
    from global_index import track1_stress_mnq as SM

    sb = _sleeves(payload)["roska4_stress"]["setup_boundary"]
    assert sb.get("decided_at_et") == SM.StressParams().setup_time


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. the page computes nothing
# ══════════════════════════════════════════════════════════════════════════════════════════

def _fn(name: str) -> str:
    code = JS.read_text(encoding="utf-8")
    start = code.index(f"function {name}")
    nxt = code.find("\n  function ", start + 1)
    return code[start:nxt if nxt > 0 else len(code)]


@pytest.mark.parametrize("fn", ["mvSetupCard", "mvCalmCards", "mvChartSvg"])
def test_no_strategy_arithmetic_lives_in_the_renderers(fn):
    """The page may format and it may position. It may not decide what a rule value IS.

    Scanned for the operations that would mean it had: an EMA or ATR being combined with a
    multiplier, a stop being derived, a threshold being compared to produce a pass.
    """
    body = _fn(fn)
    for forbidden in ("* atr", "atr *", "* daily_atr", "planned_stop =", "ema =",
                      "disaster_stop", "stop_atr_mult", "Math.pow", "reduce((", ".ewm"):
        assert forbidden not in body, (fn, forbidden)


def test_the_page_never_recomputes_a_pass_or_fail():
    """`passed` is read, never produced. A page that decided a condition had passed would be
    a second implementation of the rule, and the two would disagree on the day it mattered."""
    body = _fn("mvSetupCard")
    assert "m.passed === true" in body and "m.passed === false" in body
    # no comparison of a value against a threshold anywhere in the renderer
    assert not re.search(r"\bvalue\s*[<>]=?\s*", body), body
    assert not re.search(r"threshold\s*[<>]=?", body), body


def test_the_source_words_are_a_lookup_and_not_a_guess():
    """Four states, each with a word the backend put there. A page that inferred "recorded"
    from a populated block would relabel every reconstruction the moment it had data."""
    code = JS.read_text(encoding="utf-8")
    block = code[code.index("MV_SOURCE_WORDS"):code.index("function mvSourceBadge")]
    for key in KNOWN_SOURCES:
        assert key in block, key
    badge = _fn("mvSourceBadge")
    assert "b.diagnostics_source" in badge
    # the badge renders nothing at all rather than inventing a word for an unknown source
    assert "if (!words) return ''" in badge


def test_unavailable_is_only_shown_when_the_backend_says_so():
    """"I could not read this" and "there was nothing to read" are opposite facts about
    whether the panel can be trusted, and an empty payload must never be rendered as the
    first one."""
    code = JS.read_text(encoding="utf-8")
    assert "unavailable: ['UNAVAILABLE'" in code
    calm = _fn("mvCalmCards")
    assert "UNAVAILABLE" in calm
    # The BRANCH, not the mention. `calm.error` appears twice in this function - once as the
    # condition and once as the text - so asserting the substring survived a mutation that
    # replaced the condition with a count of the phases, which is exactly the inference this
    # test forbids. The condition itself is what is read.
    conds = [l.strip() for l in calm.splitlines() if l.strip().startswith("if (")]
    assert conds, calm
    assert "calm.error" in conds[0], conds


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. layout
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_calm_has_its_own_band_and_is_not_a_sleeve_tab():
    """Two instants half an hour apart under a contract forbidding the first from seeing what
    the second learns. It was rendering inside the market-view band under whichever sleeve was
    selected, which read as though the values belonged to that sleeve."""
    html = HTML.read_text(encoding="utf-8")
    assert 'id="calmSection"' in html
    assert html.index('id="calmSection"') > html.index('id="marketViewSetup"')
    assert 'id="marketViewCalm"' in html
    # inside its own section, not the market view's
    tail = html[html.index('id="calmSection"'):]
    assert tail.index('id="marketViewCalm"') < tail.index("</section>")
    assert "roska4_calm" not in _fn("mvTabs")


def test_the_plot_has_a_fixed_box_at_both_widths():
    css = CSS.read_text(encoding="utf-8")
    block = css[css.index(".mv2-plot {"):]
    assert "height: 320px" in block[:300]
    assert ".mv2-plot { height: 240px; }" in css, "the narrow width needs its own box"


def test_the_empty_state_fills_the_same_box():
    css = CSS.read_text(encoding="utf-8")
    assert ".mv2-plot > .mv-empty" in css
    block = css[css.index(".mv2-plot > .mv-empty"):]
    assert "height: 100%" in block[:400]


def test_the_legend_cannot_change_the_height():
    """It renders only when there are bars, so in the flow it added 40px to a populated tab
    and nothing to an empty one - the same panel-moving defect by a second route."""
    css = CSS.read_text(encoding="utf-8")
    assert ".mv2-plot > .mv-legend" in css
    block = css[css.index(".mv2-plot > .mv-legend"):]
    assert "position: absolute" in block[:300]
    # The source half of this only proves the RULE exists. Whether the legend is actually
    # inside the box is a DOM fact, and the text slice that used to stand in for it could not
    # tell "inside the div" from "just after it" - a mutation moving the legend back into the
    # flow left the slice unchanged and this test green.
    assert True


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. nothing about orders moved
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_orders_remain_impossible():
    from global_index import track1_gates as g

    ok, _ = g.may_enable_orders()
    assert ok is False
    blocking = {b.id for b in g.blocking()}
    assert blocking and blocking <= set(g.BLOCKERS)


def test_no_order_artefacts_and_the_decision_is_intact():
    import os

    from global_index import track1_gates as g

    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not (REPO / "global_index" / "live_positions.track1.json").exists()
    assert not os.environ.get("TRACK1_ORDERS_APPROVED")
    conf = REPO / g.CONFIRMATION_PATH
    if conf.exists():
        assert (json.loads(conf.read_text(encoding="utf-8")).get("confirmed_by") or "").strip()


def test_the_market_view_only_ever_reads():
    """The market view is a reader. Nothing it does may write to disk.

    Checked by walking the syntax tree rather than by scanning for substrings: the first
    version of this test looked for `append(`, which matched `calls.append(1)` in a list and
    called the module a writer. A test that fails on a list method is not testing what its
    name says.
    """
    import ast

    src = (REPO / "monitor" / "backend" / "track1_market_view.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    WRITERS = {"write_text", "write_bytes", "to_parquet", "to_csv", "mkdir", "unlink",
               "touch", "rename", "replace", "dump", "record"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name in WRITERS and name != "replace":     # str.replace is not a file write
                found.append(name)
            if name == "open":
                mode = [a for a in node.args[1:2]] + [k.value for k in node.keywords
                                                      if k.arg == "mode"]
                lit = [m.value for m in mode if isinstance(m, ast.Constant)]
                if any("w" in str(v) or "a" in str(v) for v in lit):
                    found.append(f"open({lit})")
    assert found == [], found


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. the browser
# ══════════════════════════════════════════════════════════════════════════════════════════

pytest.importorskip("playwright.sync_api")
from monitor.test_realtime_dom import (           # noqa: E402
    browser_page, open_realtime, realtime_server, stub_api)

assert browser_page and realtime_server


def _stub():
    """A payload shaped like the one the backend now builds: a metric sleeve with unarmed
    levels and a decision hour, a price sleeve with none, and Calm's two phases."""
    bars = [{"time": f"2026-08-28 {10 + i // 12:02d}:{(i % 12) * 5:02d}",
             "open": 29600.0 + i, "high": 29610.0 + i, "low": 29590.0 + i,
             "close": 29605.0 + i, "volume": 120 + i} for i in range(24)]

    def sleeve(label, inst, kind, levels, metrics, decided=""):
        return {
            "label": label, "instrument": inst, "bar_interval": "5m",
            "clock": "America/New_York",
            "range": {"context_start_et": "09:30", "window_start_et": "10:35",
                      "window_end_et": "12:30", "context_end_et": "16:05"},
            "status": "complete", "summary": f"{label} complete",
            "coverage": {"expected_slots": 3, "observed_slots": 3},
            "bars": bars if inst == "MNQ" else [], "bars_session_date": "2026-08-28",
            "bars_note": "", "volume_status": "present", "slots": [], "levels": [],
            "rule_lanes": [],
            "levels_note": ("Trigger levels were computed at 10:30 but are not armed"
                            if levels else "Strategy levels unavailable"),
            "levels_detail": "",
            "strategy": {"diagnostics_source": "reconstructed_today",
                         "price_levels": levels, "levels_armed": False, "rules": []},
            "setup_boundary": {
                "schema": "track1_setup_boundary/1", "boundary_type": kind,
                "diagnostics_source": "reconstructed_today", "decided_at_et": decided,
                "status": "available", "price_levels": levels, "metrics": metrics,
                "levels_armed": False, "nearest_failed_condition": None,
                "summary": f"{label} setup"},
            "data_status": {"provider": "ibkr", "ok": True},
        }

    levels = [{"kind": "setup_trigger", "label": "Trigger (pre-session low)",
               "price": 29592.5, "armed": False},
              {"kind": "stop", "label": "Planned stop", "price": 29652.62, "armed": False}]
    metrics = [{"label": "Instruments gapped down", "display_value": "0", "passed": False,
                "display_threshold": "2"},
               {"label": "Average basket gap", "display_value": "+0.00%", "passed": False}]
    return {"market_view": {
        "schema": "track1_market_view/1", "route": "track1_candidate",
        "session_date": "2026-08-28", "now_et": "23:00", "levels_note": "",
        "sleeves": {
            "roska4_stress": sleeve("Stress", "MNQ", "metric_boundary", levels, metrics, "10:30"),
            "global_nkd": sleeve("NKD", "MNKD", "entry_after_setup_only", [], [])},
        "calm": {"sleeve": "roska4_calm", "label": "Calm", "session_date": "2026-08-28",
                 "phases": {
                     "decide": {"phase": "decide", "diagnostics_source": "recorded_runtime",
                                "status": "SETUP", "summary": "A setup was recorded",
                                "rows": [{"label": "Stop rule",
                                          "display_value": "entry - 1.5 x daily_atr"},
                                         {"label": "Stop distance", "display_value": "12.00"}],
                                "price_levels": [], "levels_armed": False},
                     "observe": {"phase": "observe",
                                 "diagnostics_source": "reconstructed_today",
                                 "status": "RECORDED", "matched_decide": True,
                                 "summary": "Reference read",
                                 "warning": "computed after the fact; not official runtime "
                                            "evidence",
                                 "rows": [{"label": "Entry reference",
                                           "display_value": "7,739.75"},
                                          {"label": "Planned stop",
                                           "display_value": "7,727.75"}],
                                 "price_levels": [], "levels_armed": False}}}},
        "regime": {"status": "PASS", "code": "labelled", "label": "Calm",
                   "label_date": "2026-08-27", "age_hours": 3.0, "score": 0.998354,
                   "shift_threshold": None,
                   "threshold_note": "not published - the label comes from a Viterbi decode, "
                                     "so there is no cutoff number to breach",
                   "margin": 0.9967, "margin_name": "probability margin",
                   "runner_up": "Normal",
                   "state_probabilities": {"Calm": 0.998354, "Normal": 0.001643},
                   "entropy_bits": 0.017627, "max_entropy_bits": 1.584963,
                   "features": [], "context": [], "recent": [],
                   "verification": {"status": "PASS", "counts": {"compared": 10, "changed": 0}},
                   "line": "Regime Calm as of 2026-08-27"}}


def _open(page, server):
    stub_api(page, {"/api/v1/track1-market-view": _stub()})
    open_realtime(page, server)
    page.wait_for_selector("#marketViewTabs .mv-tab", timeout=10_000)


@pytest.mark.parametrize("width", [375, 720, 1440])
def test_dom_nothing_overflows_on_any_tab(browser_page, realtime_server, width):
    browser_page.set_viewport_size({"width": width, "height": 1200})
    _open(browser_page, realtime_server)
    for tab in ("Stress", "NKD"):
        browser_page.click(f'#marketViewTabs .mv-tab:has-text("{tab}")')
        over = browser_page.evaluate(
            """() => [...document.querySelectorAll('.market-view-section *')]
                 .filter(e => e.getBoundingClientRect().right > document.documentElement
                   .getBoundingClientRect().right + 1)
                 .map(e => e.className + '|' + Math.round(e.getBoundingClientRect().right))""")
        assert over == [], (width, tab, over)
    assert browser_page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"), width
    # And content spilling INSIDE a box that is itself in bounds. The bounding-rect check
    # above cannot see it: a chip capped at `max-width: 100%` keeps its own edges while its
    # text runs straight out of them, which is what `white-space: nowrap` on a chip that now
    # carries a sentence actually does. A mutation restoring `nowrap` left this test green
    # until the second measurement was added.
    spill = browser_page.evaluate(
        """() => [...document.querySelectorAll('.market-view-section *')]
             .filter(e => {
               // Only elements whose OWN text is what overflows. A tooltip is absolutely
               // positioned and legitimately wider than the badge it hangs off, and counting
               // those made the first version of this check report four spills that were not
               // spills - a measurement failing on its own instrument rather than on the page.
               // Measured, not assumed: the OBSERVE card head reported 484 against a client
               // width of 462, and removing `.has-tip` from the badge inside it brought it to
               // 462 exactly. The 22px was the tooltip's pseudo-element, which is an overlay
               // and never real layout. An element anywhere near one cannot be measured this
               // way, so it is excluded and covered by the bounding-rect check above instead.
               if (e.closest('.has-tip') || e.querySelector('.has-tip')) return false;
               if ([...e.children].some(c => getComputedStyle(c).position === 'absolute'))
                 return false;
               const st = getComputedStyle(e);
               if (st.overflowX !== 'visible' || st.position === 'absolute') return false;
               return e.scrollWidth > e.clientWidth + 1;
             })
             .map(e => e.className + '|' + e.scrollWidth + '>' + e.clientWidth)""")
    assert spill == [], (width, spill)


def test_a_chip_carrying_a_sentence_is_allowed_to_wrap():
    """Pinned in the stylesheet, because it cannot be measured in the DOM.

    A chip is a tooltip anchor, so its scrollWidth carries the tooltip's pseudo-element and the
    spill check above has to skip it; and once `max-width: 100%` caps the box, text running out
    of that box moves no element's edges either. Both measurements are blind to it, which is
    exactly the case where the rule itself has to be the thing asserted - with the reason
    written down, so the next reader does not "simplify" it away.

    `nowrap` is right for "22/22 SLOTS" and wrong for "Trigger levels were computed at 10:30
    but are not armed", which is a sentence a chip now carries.
    """
    css = CSS.read_text(encoding="utf-8")
    assert "@media (max-width: 720px) { .mv-chip { white-space: normal; } }" in css
    block = css[css.index(".mv-chip {\n  box-sizing"):]
    assert "box-sizing: border-box" in block[:200], (
        "max-width without border-box resolves to 100% PLUS padding and border, which is how "
        "Stage 5ZZR shrank an overflow twice without removing it")
    assert "max-width: 100%" in block[:200]


@pytest.mark.parametrize("tab", ["Stress", "NKD"])
def test_dom_the_plot_keeps_one_height_across_tabs(browser_page, realtime_server, tab):
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    a = browser_page.eval_on_selector(".mv2-plot", "el => el.getBoundingClientRect().height")
    browser_page.click(f'#marketViewTabs .mv-tab:has-text("{tab}")')
    b = browser_page.eval_on_selector(".mv2-plot", "el => el.getBoundingClientRect().height")
    assert a == b == 320, (a, b)


def test_dom_the_legend_lives_inside_the_plot_box(browser_page, realtime_server):
    """The DOM half of the rule above. The legend renders only when there are bars, so out in
    the flow it adds its height to a populated tab and nothing to an empty one."""
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    inside = browser_page.eval_on_selector(
        ".mv-legend", "el => !!el.closest('.mv2-plot')")
    assert inside, "the legend is outside the box whose height it must not change"
    with_bars = browser_page.eval_on_selector(
        "#marketViewChart", "el => el.getBoundingClientRect().height")
    browser_page.click('#marketViewTabs .mv-tab:has-text("NKD")')      # no bars, no legend
    without = browser_page.eval_on_selector(
        "#marketViewChart", "el => el.getBoundingClientRect().height")
    assert with_bars == without, (with_bars, without)


def test_dom_the_unarmed_levels_are_drawn_muted(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    rows = browser_page.eval_on_selector_all(
        "#marketViewSetup .mv2-level",
        "els => els.map(e => [e.className, e.innerText])")
    assert rows, "the stress sleeve published levels and the card drew none"
    for cls, text in rows:
        assert "muted" in cls, (cls, text)
        assert "not armed" in text.lower(), text


def test_dom_the_stress_card_states_its_decision_hour(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    text = browser_page.eval_on_selector("#marketViewSetup", "el => el.innerText")
    assert "10:30" in text, text


def test_dom_each_card_shows_the_source_it_was_given(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    browser_page.click('#marketViewTabs .mv-tab:has-text("Stress")')
    badge = browser_page.eval_on_selector("#marketViewSetup .mv2-src", "el => el.innerText")
    assert badge.strip().upper() == "RECONSTRUCTED", badge
    words = browser_page.eval_on_selector_all(
        "#marketViewCalm .mv2-src", "els => els.map(e => e.innerText.trim().toUpperCase())")
    assert words == ["RECORDED", "RECONSTRUCTED"], words


def test_dom_an_empty_calm_is_not_reported_as_unavailable(browser_page, realtime_server):
    """The tri-state, at the only place it can be checked: on the page.

    A Calm block with no phases and no error means the day has nothing to show. Rendering that
    as UNAVAILABLE would say the backend could not read it, which is a different fact and the
    one an operator would act on.
    """
    payload = _stub()
    payload["market_view"]["calm"] = {"sleeve": "roska4_calm", "label": "Calm",
                                      "session_date": "2026-08-28", "phases": {}}
    stub_api(browser_page, {"/api/v1/track1-market-view": payload})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewTabs .mv-tab", timeout=10_000)
    text = browser_page.eval_on_selector("#marketViewCalm", "el => el.innerText")
    assert "UNAVAILABLE" not in text.upper(), text
    assert browser_page.eval_on_selector("#calmSection", "el => el.hidden") is True


def test_dom_a_calm_the_backend_could_not_read_says_so(browser_page, realtime_server):
    """And the other side of it, so the test above cannot be satisfied by never showing the
    word at all."""
    payload = _stub()
    payload["market_view"]["calm"] = {"sleeve": "roska4_calm", "label": "Calm",
                                      "session_date": "2026-08-28", "phases": {},
                                      "error": "OSError: the intent stream is unreadable"}
    stub_api(browser_page, {"/api/v1/track1-market-view": payload})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewTabs .mv-tab", timeout=10_000)
    text = browser_page.eval_on_selector("#marketViewCalm", "el => el.innerText")
    assert "UNAVAILABLE" in text.upper(), text
    assert "intent stream is unreadable" in text, text


def test_dom_calm_sits_in_its_own_band(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    assert browser_page.eval_on_selector("#calmSection", "el => !el.hidden")
    inside = browser_page.eval_on_selector(
        "#calmSection", "el => !!el.querySelector('#marketViewCalm')")
    assert inside
    # and it does not move when the sleeve tab does
    before = browser_page.eval_on_selector("#marketViewCalm", "el => el.innerText")
    browser_page.click('#marketViewTabs .mv-tab:has-text("NKD")')
    assert browser_page.eval_on_selector("#marketViewCalm", "el => el.innerText") == before


def test_dom_the_decide_card_still_shows_no_observe_value(browser_page, realtime_server):
    """Stage 5ZZZ-E's rule, checked where a reader meets it: on the rendered card."""
    _open(browser_page, realtime_server)
    cards = browser_page.eval_on_selector_all(
        "#marketViewCalm .mv2-calm-card", "els => els.map(e => e.innerText)")
    assert len(cards) == 2, cards
    decide = cards[0].lower()
    assert "stop rule" in decide
    for leaked in ("entry reference", "planned stop", "7,739.75", "7,727.75"):
        assert leaked not in decide, (leaked, cards[0])


def test_dom_a_missing_decide_is_not_filled_in_from_observe(browser_page, realtime_server):
    """The leak, at the only moment it can happen.

    With both phases present a renderer that falls back across the line looks identical to one
    that does not - which is why the first version of this suite could not catch it. The card
    that has nothing must show nothing, not the other phase's numbers.
    """
    payload = _stub()
    del payload["market_view"]["calm"]["phases"]["decide"]
    stub_api(browser_page, {"/api/v1/track1-market-view": payload})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#marketViewTabs .mv-tab", timeout=10_000)
    cards = browser_page.eval_on_selector_all(
        "#marketViewCalm .mv2-calm-card", "els => els.map(e => e.innerText)")
    assert len(cards) == 1, cards
    assert "OBSERVE" in cards[0].upper(), cards
    text = " ".join(cards).lower()
    assert "decide" not in text.replace("observe", ""), cards


def test_dom_the_regime_panel_is_its_own_section(browser_page, realtime_server):
    _open(browser_page, realtime_server)
    assert browser_page.eval_on_selector(
        ".regime-section", "el => !el.closest('.market-view-section')")
    text = browser_page.eval_on_selector(".regime-section", "el => el.innerText").lower()
    for shown in ("confidence", "runner-up", "shift threshold", "none published"):
        assert shown in text, (shown, text)


def test_dom_no_console_errors(browser_page, realtime_server):
    errors = []
    browser_page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    browser_page.on("pageerror", lambda e: errors.append(str(e)))
    _open(browser_page, realtime_server)
    for tab in ("Stress", "NKD"):
        browser_page.click(f'#marketViewTabs .mv-tab:has-text("{tab}")')
    browser_page.wait_for_timeout(400)
    assert errors == [], errors
