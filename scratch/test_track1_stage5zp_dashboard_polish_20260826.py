"""Stage 5ZP — the diagnostics panel stops looking like three different pages.

Real chromium, real page, API stubbed — the same harness `monitor/test_realtime_dom.py` uses.
Structural DOM assertions throughout: where a node SITS in the tree, what classes it carries,
whether the card overflows. A substring check would pass on a chip rendered in the wrong place.

The three problems, as they were
---------------------------------
1. the signal chip read `Signal NO SIGNAL`, was a bordered pill of its own invention, and
   carried `grid-column: 1 / -1` — which is what put it on its own line and made every Track 1
   row two lines tall whether or not anything had happened;
2. the Operational and Signal blocks were concatenated AFTER `renderJobDetails(...)`, so they
   rendered as loose text outside the structured panel;
3. `Route track1_candidate` and `Orders possible no` ran together, because label and value were
   inline siblings with nothing separating them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "monitor"))

pytest.importorskip("playwright.sync_api")

from monitor.test_realtime_dom import (           # noqa: E402
    BASE_PAYLOADS, browser_page, open_realtime, realtime_server, stub_api,
)

REPO = Path(r"d:\raits")
DAY = "2026-08-26"


# ══════════════════════════════════════════════════════════════════════════════
# fixtures — payloads in the shape the real backend serves
# ══════════════════════════════════════════════════════════════════════════════

def a_slot_job(*, chip_label="NO SIGNAL", tone="neutral", op_lines=None, sig_lines=None,
               job_id="TRACK1_NKD_0255"):
    return {
        "id": job_id, "job_id": job_id, "status": "completed",
        "started_at": f"{DAY}T06:55:00Z", "ended_at": f"{DAY}T06:55:38Z",
        "duration_seconds": 38, "reason": "", "events": [], "diagnostics": [],
        "failed_runs": 0, "launch_count": 1, "job_type": "track1_strategy",
        "impact": "None — the route holds nothing.",
        "action": "No action needed.",
        "operational": {
            "ran": "ran", "duration_seconds": 38, "over_budget": False,
            "budget_seconds": 300, "ledger_row": True, "refused": None,
            "freshness_pass": False, "audit_verdict": "PASS",
            "data_observation": None,
            "lines": op_lines or [
                "Ran at 01:45 ET, duration 38s.",
                "Runtime within the 300s budget.",
                "Ledger row written.",
                "Live frame passed.",
                "Data proof: not recorded by this slot version",
                "No checkpoint or book write expected in shadow.",
                "Window audit for global_nkd: PASS.",
            ],
        },
        "signal": {
            "chip": {"label": chip_label, "tone": tone, "status": "NO_SIGNAL",
                     "tooltip": "The slot evaluated normally and found no setup."},
            "operator": sig_lines or [
                "No setup matched this slot.",
                "The slot reached strategy evaluation.",
                "Freshness check: measured as not allowing admission, but no candidate "
                "reached admission.",
            ],
            "details": None, "debug": None,
        },
    }


def journal_with(jobs):
    j = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/job-journal/"]))
    j["day"] = DAY
    j["jobs"] = jobs
    assert j["jobs"], "the fixture must exercise a non-empty job list"
    return j


def track1_payload(*, blocking=None):
    t = json.loads(json.dumps(BASE_PAYLOADS["/api/v1/track1-runtime"]))
    t["gates"]["blocking_now"] = blocking if blocking is not None else [
        "B1_broker_account_or_legacy_retirement", "PAPER_SHADOW_EVIDENCE",
        "REGIME_LABEL_VERIFICATION"]
    return t


def open_with(page, server, *, jobs=None, blocking=None):
    stub_api(page, {"/api/v1/job-journal/": journal_with(jobs or [a_slot_job()]),
                    "/api/v1/track1-runtime": track1_payload(blocking=blocking)})
    open_realtime(page, server)


def expand_first_job(page):
    page.click("#journal .job-trigger")
    page.wait_for_selector("#journal .job-detail")


# ══════════════════════════════════════════════════════════════════════════════
# B. the chip
# ══════════════════════════════════════════════════════════════════════════════

def test_1_the_chip_reads_exactly_its_label(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    texts = browser_page.eval_on_selector_all(
        "#journal .job-badges .event-status",
        "els => els.map(e => e.textContent.trim())")
    assert "NO SIGNAL" in texts, texts
    assert not any(t.startswith("Signal ") for t in texts), texts


def test_2_the_chip_sits_in_the_same_group_as_runner_and_completed(realtime_server,
                                                                   browser_page):
    """Structural: it must be a CHILD of `.job-badges`, not a sibling after it."""
    open_with(browser_page, realtime_server)
    inside = browser_page.eval_on_selector_all(
        "#journal .job-badges > *", "els => els.map(e => e.textContent.trim())")
    assert len(inside) >= 3, inside
    assert "NO SIGNAL" == inside[-1], inside
    stray = browser_page.eval_on_selector_all(
        "#journal .job-trigger > .event-status", "els => els.length")
    assert stray == 0, "the chip is a direct child of the trigger again"


def test_3_the_chip_uses_the_dashboards_own_chip_class(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    classes = browser_page.eval_on_selector_all(
        "#journal .job-badges .event-status",
        "els => els.map(e => e.className)")
    assert any("signal-" in c for c in classes), classes
    assert not any("job-signal-chip" in c for c in classes), classes


def test_4_the_chip_carries_a_plain_english_tooltip(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    tip = browser_page.eval_on_selector(
        "#journal .job-badges .event-status.signal-neutral",
        "e => e.getAttribute('data-tooltip')")
    assert tip == "The slot evaluated normally and found no setup."


def test_5_the_chip_does_not_start_its_own_grid_row(realtime_server, browser_page):
    """`grid-column: 1 / -1` is what made every Track 1 row two lines tall."""
    open_with(browser_page, realtime_server)
    col = browser_page.eval_on_selector(
        "#journal .job-badges .event-status.signal-neutral",
        "e => getComputedStyle(e).gridColumn")
    assert "1 / -1" not in col, col


def test_6_a_collapsed_track1_row_is_no_taller_than_one_without_a_chip(realtime_server,
                                                                       browser_page):
    plain = a_slot_job(job_id="OTHER_JOB")
    plain.pop("signal")
    open_with(browser_page, realtime_server, jobs=[a_slot_job(), plain])
    heights = browser_page.eval_on_selector_all(
        "#journal .job-trigger", "els => els.map(e => Math.round(e.getBoundingClientRect().height))")
    assert len(heights) == 2, heights
    assert abs(heights[0] - heights[1]) <= 2, heights


# ══════════════════════════════════════════════════════════════════════════════
# C. the expanded panel
# ══════════════════════════════════════════════════════════════════════════════

def test_7_operational_and_signal_live_inside_the_structured_panel(realtime_server,
                                                                   browser_page):
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    inside = browser_page.eval_on_selector_all(
        "#journal .job-detail .job-section > b", "els => els.map(e => e.textContent.trim())")
    assert "OPERATIONAL" in inside and "SIGNAL" in inside, inside


def test_8_neither_section_renders_outside_the_detail_block(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    outside = browser_page.evaluate(
        "() => Array.from(document.querySelectorAll('#journal .job-section'))"
        "        .filter(el => !el.closest('.job-detail')).length")
    assert outside == 0, f"{outside} section(s) rendered as loose text outside the panel"


def test_9_the_sections_come_after_the_existing_evidence_blocks(realtime_server, browser_page):
    """They read as the end of one panel, not as an interruption of it."""
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    order = browser_page.eval_on_selector_all(
        "#journal .job-detail > *", "els => els.map(e => e.className.split(' ')[0])")
    assert "job-resolution" in order and "job-section" in order, order
    assert order.index("job-resolution") < order.index("job-section"), order


def test_10_the_operational_block_carries_the_plain_english_lines(realtime_server,
                                                                  browser_page):
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    lines = browser_page.eval_on_selector_all(
        "#journal .job-operational .job-lines li",
        "els => els.map(e => e.textContent.trim())")
    assert any(l.startswith("Ran at") for l in lines), lines
    assert any("budget" in l for l in lines), lines
    assert any("Ledger row written" in l for l in lines), lines
    assert any(l.startswith("Data proof:") for l in lines), lines


# ══════════════════════════════════════════════════════════════════════════════
# D. the Track 1 Runtime panel
# ══════════════════════════════════════════════════════════════════════════════

def test_11_label_and_value_do_not_collide(realtime_server, browser_page):
    """`Route track1_candidate` was one run-on string. Label and value are now separate
    boxes stacked with a gap, so no pair shares a text baseline."""
    open_with(browser_page, realtime_server)
    boxes = browser_page.evaluate(
        "() => Array.from(document.querySelectorAll('#track1Facts .fact')).map(f => {"
        "  const l = f.querySelector('.fact-label'), v = f.querySelector('.fact-value');"
        "  if (!l || !v) return null;"
        "  const lb = l.getBoundingClientRect(), vb = v.getBoundingClientRect();"
        "  return {label: l.textContent.trim(), gap: Math.round(vb.top - lb.bottom)};"
        "}).filter(Boolean)")
    assert boxes, "no Track 1 facts rendered"
    for b in boxes:
        assert b["gap"] >= 0, b


def test_12_the_blocking_gates_read_in_plain_english(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    chips = browser_page.eval_on_selector_all(
        "#track1Facts .t1-gate", "els => els.map(e => e.textContent.trim())")
    assert "Account / legacy retirement gate" in chips, chips
    assert not any(c.startswith("B1_") for c in chips), chips


def test_13_the_raw_gate_id_is_kept_in_the_tooltip_not_dropped(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    tips = browser_page.eval_on_selector_all(
        "#track1Facts .t1-gate", "els => els.map(e => e.getAttribute('data-tooltip'))")
    assert "B1_broker_account_or_legacy_retirement" in tips, tips


def test_14_three_gates_wrap_instead_of_widening_the_panel(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    over = browser_page.evaluate(
        "() => {const h = document.querySelector('#track1Facts');"
        " return h ? h.scrollWidth - h.clientWidth : -1;}")
    assert over <= 1, f"the Track 1 panel scrolls horizontally by {over}px"


# ══════════════════════════════════════════════════════════════════════════════
# E / F. what the details say, and what they must never say
# ══════════════════════════════════════════════════════════════════════════════

def test_15_no_raw_variable_name_or_json_threshold_is_rendered(realtime_server, browser_page):
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    text = browser_page.eval_on_selector("#journal .job-detail", "e => e.innerText")
    for raw in ("breadth_down_count", "gapdown_count", "rel_volume_max", "not_exposed_by_sleeve",
                "freshness_allow", '{"', "UNKNOWN"):
        assert raw not in text, raw


def test_16_unexposed_rules_are_one_sentence_not_a_list_of_unknowns(realtime_server,
                                                                    browser_page):
    job = a_slot_job(sig_lines=["No setup matched this slot.",
                                "The slot reached strategy evaluation.",
                                "Detailed setup measurements are not exposed yet."])
    open_with(browser_page, realtime_server, jobs=[job])
    expand_first_job(browser_page)
    lines = browser_page.eval_on_selector_all(
        "#journal .job-signal-detail .job-lines li",
        "els => els.map(e => e.textContent.trim())")
    assert len(lines) <= 4, lines
    assert any("not exposed yet" in l for l in lines), lines


def test_17_an_admission_rule_is_not_blamed_when_nothing_was_admitted(realtime_server,
                                                                      browser_page):
    """Live on 2026-08-26: 22 NO_SIGNAL rows with zero candidates, every one of them printing
    'First rule that failed: Freshness check' — a cause that did not act."""
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    lines = browser_page.eval_on_selector_all(
        "#journal .job-signal-detail .job-lines li",
        "els => els.map(e => e.textContent.trim())")
    assert not any(l.startswith("First rule that failed: Freshness") for l in lines), lines
    assert any("no candidate reached admission" in l for l in lines), lines


@pytest.mark.parametrize("line,expect", [
    ("Data: IBKR · NKD · 1186 live bars checked · last 02:55 ET · splice OK", "IBKR"),
    ("Data proof: not recorded by this slot version", "not recorded"),
    ("Data refused: overlap mismatch", "refused"),
])
def test_18_the_data_proof_line_renders_in_all_three_states(realtime_server, browser_page,
                                                            line, expect):
    job = a_slot_job(op_lines=["Ran at 01:45 ET, duration 38s.", line])
    open_with(browser_page, realtime_server, jobs=[job])
    expand_first_job(browser_page)
    lines = browser_page.eval_on_selector_all(
        "#journal .job-operational .job-lines li",
        "els => els.map(e => e.textContent.trim())")
    assert any(expect in l for l in lines), (expect, lines)
    assert sum(1 for l in lines if l.startswith("Data")) == 1, lines


# ══════════════════════════════════════════════════════════════════════════════
# G. narrow viewport, and the rest of the page
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("width", [380, 720, 1024])
def test_19_no_horizontal_overflow_at_any_width(realtime_server, browser_page, width):
    browser_page.set_viewport_size({"width": width, "height": 900})
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    over = browser_page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, f"the page scrolls {over}px horizontally at {width}px"


@pytest.mark.parametrize("width", [380, 1024])
def test_20_the_chip_row_does_not_widen_the_card(realtime_server, browser_page, width):
    browser_page.set_viewport_size({"width": width, "height": 900})
    open_with(browser_page, realtime_server)
    over = browser_page.evaluate(
        "() => {const b = document.querySelector('#journal .job-badges');"
        " if (!b) return -1;"
        " const row = b.closest('.job-row');"
        " return Math.round(b.getBoundingClientRect().right - row.getBoundingClientRect().right);}")
    assert over <= 1, f"the badge group overhangs its row by {over}px at {width}px"


def test_21_a_job_without_a_signal_block_renders_unchanged(realtime_server, browser_page):
    """Non-Track1 rows must be untouched: no chip, no sections, and still expandable."""
    plain = a_slot_job(job_id="MAX_HOLD_EXIT")
    plain.pop("signal")
    plain.pop("operational")
    open_with(browser_page, realtime_server, jobs=[plain])
    chips = browser_page.eval_on_selector_all(
        "#journal .job-badges .event-status[class*='signal-']", "els => els.length")
    assert chips == 0
    expand_first_job(browser_page)
    sections = browser_page.eval_on_selector_all("#journal .job-section", "els => els.length")
    assert sections == 0
    assert browser_page.eval_on_selector_all("#journal .job-detail", "els => els.length") == 1


def test_22_the_page_logs_no_console_error(realtime_server, browser_page):
    errors = []
    browser_page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    browser_page.on("pageerror", lambda e: errors.append(str(e)))
    open_with(browser_page, realtime_server)
    expand_first_job(browser_page)
    assert errors == [], errors


# ══════════════════════════════════════════════════════════════════════════════
# H. the backend rule behind test 17, pinned where a fixture cannot flatter it
# ══════════════════════════════════════════════════════════════════════════════

def test_23_the_backend_itself_stops_blaming_an_admission_rule():
    """The DOM test above renders a fixture, so it would stay green if the backend regressed.

    This asks the composer directly, with the shape the live journal actually held on
    2026-08-26: NO_SIGNAL, zero candidates, freshness measured false.
    """
    from global_index import track1_signals as sig

    row = {"status": sig.NO_SIGNAL, "candidates": [], "freshness_allow": False,
           "rule_checks": [{"rule": "freshness_allow", "passed": False, "value": None,
                            "threshold": True, "comparator": "==", "source": sig.MEASURED,
                            "detail": "binding in shadow_live"}]}
    lines = sig.operator_lines(row)
    assert not any(l.startswith("First rule that failed: Freshness") for l in lines), lines
    assert any("no candidate reached admission" in l for l in lines), lines


def test_24_a_rule_that_really_did_block_a_candidate_is_still_named():
    """The correction must not silence the case where the rule DID act."""
    from global_index import track1_signals as sig

    row = {"status": sig.NO_SIGNAL,
           "candidates": [{"instrument": "MES", "direction": "long"}],
           "freshness_allow": False,
           "rule_checks": [{"rule": "freshness_allow", "passed": False, "value": None,
                            "threshold": True, "comparator": "==", "source": sig.MEASURED,
                            "detail": ""}]}
    lines = sig.operator_lines(row)
    assert any(l.startswith("First rule that failed:") for l in lines), lines


def test_25_a_setup_rule_is_still_named_even_with_no_candidate():
    """Only ADMISSION rules are reframed. A setup rule that failed is why there is no
    candidate, so naming it is exactly right."""
    from global_index import track1_signals as sig

    row = {"status": sig.NO_SIGNAL, "candidates": [],
           "rule_checks": [{"rule": "ema50_filter", "passed": False, "value": 1, "threshold": 2,
                            "comparator": "<", "source": sig.MEASURED, "detail": ""}]}
    lines = sig.operator_lines(row)
    assert any(l.startswith("First rule that failed:") for l in lines), lines


def test_26_the_live_2026_08_26_rows_no_longer_blame_freshness():
    """Against the real journal on this machine, not a fixture."""
    from global_index import track1_signals as sig

    p = REPO / "global_index" / "track1_runtime" / "signals" / "track1_signals_20260826.jsonl"
    if not p.exists():
        pytest.skip("no signal journal for that day on this machine")
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows, "the journal is empty — nothing was checked"
    offenders = [r["slot_id"] for r in rows
                 if any(l.startswith("First rule that failed: Freshness")
                        for l in sig.operator_lines(r))
                 and not (r.get("candidates") or [])]
    assert offenders == [], offenders
