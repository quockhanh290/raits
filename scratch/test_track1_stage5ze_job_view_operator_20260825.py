"""Stage 5ZE — job view: operational health first, signal chip second.

Two questions, kept apart:

    Operational  did the slot RUN correctly?
    Signal       if it reached the strategy, what did the strategy see?

The audit that opened this stage found the first one unanswered. The panel showed
started/completed/duration/outcome, an impact, an action and an event list that is always
empty for a shadow slot — and nothing about freshness, the live frame, the evidence row, or
the runtime budget.

Read-only. No order, no broker, no IBKR, no runtime write. The DOM tests drive a real chromium
against the real page with the API stubbed, because `assert "string" in file` is how every
finding in the dashboard audit got through the last time.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import pytest

from global_index import track1_signals as S
from global_index import track1_signal_layer as T
from monitor.backend import job_journal_reader as JJ

REPO = Path(__file__).resolve().parents[1]
DAY = "2026-08-25"


def cand(**kw):
    base = dict(trade_id="t1", sleeve="roska4_stress", instrument="MNQ", direction="short",
                qty=7, risk_dollars=420.0, entry_time="2026-08-25 11:55:00",
                entry_price=20100.0, stop_price=20160.0, meta={})
    base.update(kw)
    return T.Candidate(**base)


def sig_row(**kw):
    base = dict(sleeve="roska4_stress", slot_id="TRACK1_STRESS_1155", slot_time="11:55",
                session_date=DAY, mode="shadow_live", decided=True, reason="decided",
                freshness_allow=True, gate_allow=True)
    base.update(kw)
    return S.build_row(**base).as_row()


# ══════════════════════════════════════════════════════════════════════════════
# 1. the human label mapper — one owner
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("raw,human", [
    ("gate_allow", "Runtime gate"),
    ("freshness_allow", "Freshness check"),
    ("same_symbol_suppression", "Same-symbol rule"),
    ("family_cap", "Family cap"),
    ("cluster_cap", "Cluster cap"),
    ("live_frame_refused", "Live frame refused"),
    ("overlap_disagreement", "History/feed overlap disagreement"),
    ("no_bar_provider", "Bar provider unavailable"),
])
def test_1_every_operator_facing_field_has_a_human_label(raw, human):
    assert S.label(raw) == human


def test_2_an_unmapped_name_falls_back_visibly_rather_than_to_an_empty_cell():
    """A missing label should look wrong on the page so somebody adds one."""
    assert S.label("some_new_rule") == "some_new_rule"


def test_3_every_declared_sleeve_rule_has_a_label():
    missing = [r for s in S.STRATEGY_SLEEVES for r in S.rule_names(s) if r not in S.LABELS]
    assert missing == [], missing


def test_4_every_layer_has_an_operator_name():
    assert set(S.LAYER_LABELS) == set(S.LAYERS)
    assert S.LAYER_LABELS[S.LAYER_CAP] == "Position cap"


# ══════════════════════════════════════════════════════════════════════════════
# 2. the chips and their tooltips
# ══════════════════════════════════════════════════════════════════════════════

EXPECTED_CHIPS = {
    S.NO_SIGNAL: ("NO SIGNAL", "Slot ran and reached the strategy layer; no setup matched."),
    S.RAW_SIGNAL_FOUND: ("RAW SIGNAL", "A setup matched before admission/cap checks."),
    S.SIGNAL_REJECTED: ("REJECTED",
                        "A setup matched but was rejected by an admission, cap, or switch rule."),
    S.SIGNAL_ACCEPTED_SHADOW: ("ACCEPTED SHADOW",
                               "Setup passed admission in shadow; no order was attempted."),
    S.SLOT_REFUSED: ("REFUSED",
                     "Slot did not reach strategy evaluation; see operational details."),
    S.SLOT_MISSED: ("MISSED", "Expected slot did not run."),
    S.SLOT_NO_ROW: ("NO DIAGNOSTICS",
                    "Job ran before signal diagnostics existed, or no signal row was written."),
}


@pytest.mark.parametrize("status", sorted(EXPECTED_CHIPS))
def test_5_every_status_has_a_label_and_a_plain_english_tooltip(status):
    label, tip = EXPECTED_CHIPS[status]
    c = S.chip(status)
    assert c["label"] == label
    assert c["tooltip"] == tip
    assert c["tone"] in ("good", "warn", "watch", "bad", "neutral", "muted")
    # plain English: a sentence, not a field name
    assert tip.endswith(".") and "_" not in tip


def test_6_the_seven_labels_are_distinct():
    labels = [S.chip(s)["label"] for s in EXPECTED_CHIPS]
    assert len(set(labels)) == len(labels)


def test_7_tone_separates_admitted_from_declined_from_missed():
    assert S.chip(S.SIGNAL_ACCEPTED_SHADOW)["tone"] == "good"
    assert S.chip(S.SIGNAL_REJECTED)["tone"] == "warn"
    assert S.chip(S.SLOT_MISSED)["tone"] == "bad"
    assert S.chip(S.SLOT_REFUSED)["tone"] == "muted"


# ══════════════════════════════════════════════════════════════════════════════
# 3. operator language — and what must never appear in it
# ══════════════════════════════════════════════════════════════════════════════

RAW_NAMES = ("gate_allow", "freshness_allow", "breadth_down_count", "gapdown_count",
             "avg_gap", "mnq_only_short_setup", "not_exposed_by_sleeve", "rule_checks",
             "raw_candidates", "rejecting_layer")


def _all_operator_text(row) -> str:
    return " ".join(S.operator_lines(row))


def test_8_no_signal_says_what_happened_in_plain_words():
    lines = S.operator_lines(sig_row(raw_candidates=0))
    assert "No setup matched this slot." in lines
    assert "The slot reached strategy evaluation." in lines
    assert "Detailed setup measurements are not exposed yet." in lines


def test_9_no_operator_line_anywhere_contains_a_raw_field_name():
    rows = [
        sig_row(raw_candidates=0),
        sig_row(raw_candidates=1, accepted=1, candidates=[cand()],
                decisions=[T.Decision(candidate=cand(), verdict=T.TAKE)]),
        sig_row(raw_candidates=1, rejected=1, candidates=[cand()],
                decisions=[T.Decision(candidate=cand(), verdict=T.REJECT_FAMILY_CAP)]),
        sig_row(decided=False, reason="gate_refused", detail="stale", gate_allow=False),
        {"status": S.SLOT_MISSED}, {"status": S.SLOT_NO_ROW},
    ]
    for r in rows:
        text = _all_operator_text(r)
        for raw in RAW_NAMES:
            assert raw not in text, (r.get("status"), raw, text)


def test_10_no_operator_line_contains_a_json_threshold_blob():
    for r in (sig_row(raw_candidates=0), {"status": S.SLOT_REFUSED}):
        text = _all_operator_text(r)
        assert "{" not in text and "}" not in text, text


def test_11_no_wall_of_unknown_rows():
    """Thirty mapped names with no numbers beside them is a longer way of saying nothing."""
    lines = S.operator_lines(sig_row(raw_candidates=0))
    assert len(lines) <= 4, lines
    assert not any("UNKNOWN" in l.upper() for l in lines)


def test_12_a_rejection_names_the_layer_in_human_words_and_shows_the_candidate():
    lines = S.operator_lines(sig_row(
        raw_candidates=1, rejected=1, candidates=[cand()],
        decisions=[T.Decision(candidate=cand(), verdict=T.REJECT_FAMILY_CAP)]))
    assert "Setup matched." in lines
    assert "Rejected by: Position cap." in lines
    joined = " ".join(lines)
    for bit in ("MNQ", "SHORT", "entry", "stop", "risk"):
        assert bit in joined, bit


def test_13_an_accepted_shadow_row_states_no_order_was_attempted():
    lines = S.operator_lines(sig_row(
        raw_candidates=1, accepted=1, candidates=[cand()],
        decisions=[T.Decision(candidate=cand(), verdict=T.TAKE)]))
    assert "Admitted in shadow; no order attempted." in lines
    assert any("MNQ" in l for l in lines)


def test_14_a_refused_row_points_at_operational_and_does_not_repeat_the_evidence():
    lines = S.operator_lines(sig_row(decided=False, reason="gate_refused",
                                     detail="stale", gate_allow=False))
    assert "Strategy was not evaluated." in lines
    assert "See Operational details for the runtime refusal." in lines
    joined = " ".join(lines)
    # the refusal codes belong to Operational; the Signal block must not restate them
    assert "stale" not in joined and "gate_refused" not in joined


@pytest.mark.parametrize("status", [S.SLOT_MISSED, S.SLOT_NO_ROW])
def test_15_missed_and_no_row_point_at_operational_too(status):
    lines = S.operator_lines({"status": status})
    assert any("Operational" in l for l in lines)


# ══════════════════════════════════════════════════════════════════════════════
# 4. the operational block — the fields the audit found missing
# ══════════════════════════════════════════════════════════════════════════════

def _job(**kw):
    base = {"job_id": "TRACK1_STRESS_1155", "status": "completed",
            "started_at": "2026-08-25T15:55:00Z", "duration_seconds": 3}
    base.update(kw)
    return base


def test_16_a_healthy_slot_reports_run_budget_ledger_freshness_and_shadow_expectation():
    op = JJ._operational(_job(), sig_row(raw_candidates=0),
                         {"TRACK1_STRESS_1155": {"decided": True}}, {})
    text = " ".join(op["lines"])
    assert "Ran at 11:55:00 ET" in text, text
    assert "duration 3s" in text
    assert "within the 300s budget" in text
    assert "Ledger row written." in text
    assert "Freshness check passed." in text
    assert "Live frame passed." in text
    assert "No checkpoint or book write expected in shadow." in text
    assert op["over_budget"] is False and op["ledger_row"] is True


def test_17_the_runtime_budget_is_flagged_when_breached():
    op = JJ._operational(_job(duration_seconds=301), sig_row(raw_candidates=0),
                         {"TRACK1_STRESS_1155": {"decided": True}}, {})
    assert op["over_budget"] is True
    assert "OVER the 300s budget" in " ".join(op["lines"])
    assert JJ.SLOT_RUNTIME_BUDGET_S == 300


def test_18_a_missing_ledger_row_is_stated_not_omitted():
    op = JJ._operational(_job(), sig_row(raw_candidates=0), {}, {})
    assert op["ledger_row"] is False
    assert "No ledger row for this slot" in " ".join(op["lines"])


def test_19_a_refusal_is_reported_in_operator_words():
    row = sig_row(decided=False, reason="gate_refused", detail="partial_coverage,stale",
                  gate_allow=False, gate_codes=("partial_coverage", "stale"))
    op = JJ._operational(_job(), row, {"TRACK1_STRESS_1155": {"decided": False}}, {})
    text = " ".join(op["lines"])
    assert "Slot refused before strategy evaluation." in text
    assert "Runtime gate refused the slot" in text
    assert "Session bars incomplete" in text and "Bars are stale" in text
    assert op["refused"] is True


def test_20_a_missed_slot_says_the_scheduler_never_started_it():
    op = JJ._operational(_job(status="missed", reason="scheduler stall"), None, {}, {})
    assert op["ran"] == "missed"
    text = " ".join(op["lines"])
    assert "The scheduler never started this slot." in text
    assert "scheduler stall" in text


def test_21_the_audit_verdict_appears_when_one_exists():
    op = JJ._operational(_job(job_id="TRACK1_NKD_0110"), None,
                         {"TRACK1_NKD_0110": {"decided": False, "reason": "gate_refused"}},
                         {"global_nkd": "FAIL"})
    assert op["audit_verdict"] == "FAIL"
    assert "Window audit for global_nkd: FAIL." in " ".join(op["lines"])


def test_22_operational_falls_back_to_the_ledger_when_no_signal_row_exists():
    """The 33 slots that ran before the journal existed still get full diagnostics."""
    op = JJ._operational(_job(job_id="TRACK1_NKD_0110"), None,
                         {"TRACK1_NKD_0110": {"decided": False, "reason": "gate_refused",
                                              "detail": "stale"}}, {})
    text = " ".join(op["lines"])
    assert "Slot refused before strategy evaluation." in text
    assert "Bars are stale" in text


def test_23_no_operational_line_contains_a_raw_field_name():
    for row, cov, aud in ((sig_row(raw_candidates=0), {"TRACK1_STRESS_1155": {}}, {}),
                          (sig_row(decided=False, reason="gate_refused", detail="stale",
                                   gate_allow=False), {}, {}),
                          (None, {}, {})):
        text = " ".join(JJ._operational(_job(), row, cov, aud)["lines"])
        for raw in ("gate_allow", "freshness_allow", "partial_coverage", "rule_checks",
                    "live_frame_refused"):
            assert raw not in text, (raw, text)


# ══════════════════════════════════════════════════════════════════════════════
# 5. the reader payload: scope, shape, and what stays hidden
# ══════════════════════════════════════════════════════════════════════════════

def test_24_a_strategy_job_gets_a_signal_object_and_an_operational_block(tmp_path):
    S.append(S.build_row(sleeve="roska4_stress", slot_id="TRACK1_STRESS_1155",
                         slot_time="11:55", session_date=DAY, mode="shadow_live",
                         decided=True, reason="decided", raw_candidates=0,
                         freshness_allow=True, gate_allow=True), root=tmp_path)
    jobs = [_job()]
    JJ._annotate_signal_diagnostics(jobs, DAY, tmp_path)
    assert "signal" in jobs[0] and "operational" in jobs[0]
    assert jobs[0]["signal"]["chip"]["label"] == "NO SIGNAL"
    assert jobs[0]["signal"]["operator"]


def test_25_a_non_strategy_job_gets_neither(tmp_path):
    jobs = [{"job_id": "TRACK1_STOP_REPAIR_0620", "status": "completed"},
            {"job_id": "PREFLIGHT", "status": "completed"},
            {"job_id": "SPY_REFRESH_PM", "status": "completed"}]
    JJ._annotate_signal_diagnostics(jobs, DAY, tmp_path)
    for j in jobs:
        assert "signal" not in j, j["job_id"]
        assert "operational" not in j, j["job_id"]


def test_26_the_raw_material_ships_under_debug_and_nowhere_else(tmp_path):
    S.append(S.build_row(sleeve="roska4_stress", slot_id="TRACK1_STRESS_1155",
                         slot_time="11:55", session_date=DAY, mode="shadow_live",
                         decided=True, reason="decided", raw_candidates=0,
                         freshness_allow=True, gate_allow=True), root=tmp_path)
    jobs = [_job()]
    JJ._annotate_signal_diagnostics(jobs, DAY, tmp_path)
    sg = jobs[0]["signal"]
    assert sg["debug"]["rule_checks"], "the developer material must still ship"
    visible = json.dumps({k: v for k, v in sg.items() if k != "debug"})
    for raw in ("breadth_down_count", "gate_allow", "not_exposed_by_sleeve"):
        assert raw not in visible, raw


def test_27_missing_row_status_follows_the_job_status(tmp_path):
    ran = [_job(job_id="TRACK1_NKD_0110", status="completed")]
    never = [_job(job_id="TRACK1_CALM_1000", status="missed", reason="stall")]
    JJ._annotate_signal_diagnostics(ran, DAY, tmp_path)
    JJ._annotate_signal_diagnostics(never, DAY, tmp_path)
    assert ran[0]["signal"]["chip"]["label"] == "NO DIAGNOSTICS"
    assert never[0]["signal"]["chip"]["label"] == "MISSED"
    for j in (ran, never):
        assert j[0]["signal"]["details"] is None
        assert j[0]["signal"]["debug"] is None
        assert any("Operational" in l for l in j[0]["signal"]["operator"])


# ══════════════════════════════════════════════════════════════════════════════
# 6. the real page, in a real browser
# ══════════════════════════════════════════════════════════════════════════════

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

from monitor.backend.app import app  # noqa: E402


def _stub_jobs():
    """One job per chip state, built through the REAL backend annotator so the page is given
    exactly the shape production produces."""
    out = []
    specs = [
        ("TRACK1_STRESS_1155", "completed", sig_row(raw_candidates=0)),
        ("TRACK1_STRESS_1200", "completed",
         sig_row(slot_id="TRACK1_STRESS_1200", raw_candidates=1, accepted=1,
                 candidates=[cand()],
                 decisions=[T.Decision(candidate=cand(), verdict=T.TAKE)])),
        ("TRACK1_STRESS_1205", "completed",
         sig_row(slot_id="TRACK1_STRESS_1205", raw_candidates=1, rejected=1,
                 candidates=[cand()],
                 decisions=[T.Decision(candidate=cand(),
                                       verdict=T.REJECT_FAMILY_CAP)])),
        ("TRACK1_STRESS_1210", "completed",
         sig_row(slot_id="TRACK1_STRESS_1210", decided=False, reason="gate_refused",
                 detail="stale", gate_allow=False, gate_codes=("stale",))),
        ("TRACK1_CALM_1000", "missed", None),
        ("TRACK1_NKD_0110", "completed", None),
        ("TRACK1_STOP_REPAIR_0620", "completed", None),
    ]
    for i, (jid, status, row) in enumerate(specs):
        job = {"id": f"{jid}:x{i}", "job_id": jid, "job_type": JJ._job_type(jid),
               "started_at": "2026-08-25T15:55:00Z", "ended_at": "2026-08-25T15:55:03Z",
               "duration_seconds": 3, "status": status, "reason": None,
               "launch_count": 1, "failed_runs": 0, "events": [], "event_counts": {},
               "diagnostics": [], "diagnostics_omitted": 0,
               "impact": "The job completed.", "action": "No action."}
        if row is not None:
            job["signal"] = {"status": row["status"], "chip": S.chip(row["status"]),
                             "summary": S.one_line(row),
                             "operator": S.operator_lines(row),
                             "details": {"candidates": row.get("candidates") or [],
                                         "rejecting_layer": row.get("rejecting_layer") or None},
                             "debug": {"rule_checks": row.get("rule_checks") or []}}
            job["operational"] = JJ._operational(job, row, {jid: {"decided": True}}, {})
        elif JJ.is_track1_strategy_job(jid):
            st = S.SLOT_MISSED if status == "missed" else S.SLOT_NO_ROW
            job["signal"] = {"status": st, "chip": S.chip(st),
                             "summary": S.one_line({"status": st}),
                             "operator": S.operator_lines({"status": st}),
                             "details": None, "debug": None}
            job["operational"] = JJ._operational(job, None, {}, {})
        out.append(job)
    return out


@pytest.fixture(scope="module")
def page_ctx():
    from werkzeug.serving import make_server
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.socket.getsockname()[1]}"
    jobs = _stub_jobs()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1000})

        def route(r):
            u = urlparse_path(r.request.url)
            if "/api/v1/job-journal/" in u:
                r.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"source": "scheduler_log", "day": DAY,
                                           "observed_at": "2026-08-25T16:00:00Z",
                                           "jobs": jobs, "monitor_events": [],
                                           "error": None}))
            else:
                r.continue_()

        page.route("**/api/**", route)
        page.goto(f"{base}/realtime", wait_until="networkidle")
        page.wait_for_selector(".job-row", timeout=15000)
        yield page
        browser.close()
    srv.shutdown()


def urlparse_path(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).path


#: Stage 5ZP. The chip is now `.event-status` inside `.job-badges`, so it is selected by its
#: tone class rather than by a class of its own — and its text no longer carries the word
#: "Signal", which was doubling what its position already said.
CHIP_SELECTOR = ".job-badges .event-status[class*='signal-']"


def _chip_texts(page):
    """Stage 5ZP replaced `.job-signal-chip` with the dashboard's own `.event-status`, moved the chip inside `.job-badges`, and dropped the `Signal ` prefix from its text. The intent of this assertion is unchanged; only the selector and the wording moved."""
    return [e.inner_text().strip() for e in page.query_selector_all(CHIP_SELECTOR)]


def test_28_dom_every_strategy_job_shows_a_signal_chip(page_ctx):
    texts = _chip_texts(page_ctx)
    assert len(texts) == 6, texts          # six strategy jobs, not the stop-repair one
    for want in ("NO SIGNAL", "ACCEPTED SHADOW", "REJECTED", "REFUSED", "MISSED",
                 "NO DIAGNOSTICS"):
        assert any(want in t for t in texts), (want, texts)


def test_29_dom_a_non_strategy_job_shows_no_chip(page_ctx):
    rows = page_ctx.query_selector_all(".job-row")
    for r in rows:
        name = r.query_selector(".job-name")
        # Stage 5ZZU moved the job id off the visible label and into the tooltip, because
        # TRACK1_STOP_REPAIR_0620 is an identifier and was being used as the row's primary
        # text. The row is still addressed by its id here - just where the id now lives.
        ident = (name.get_attribute("title") or name.inner_text()) if name else ""
        if "STOP_REPAIR" in ident:
            assert r.query_selector(CHIP_SELECTOR) is None
            return
    pytest.fail("the stop-repair row was not rendered at all")


@pytest.mark.parametrize("label,tone", [("ACCEPTED SHADOW", "signal-good"),
                                        ("REJECTED", "signal-warn"),
                                        ("MISSED", "signal-bad"),
                                        ("REFUSED", "signal-muted")])
def test_30_dom_chip_tone_matches_the_meaning(page_ctx, label, tone):
    el = [e for e in page_ctx.query_selector_all(CHIP_SELECTOR)
          if label in e.inner_text()]
    assert el, label
    assert tone in (el[0].get_attribute("class") or ""), el[0].get_attribute("class")


@pytest.mark.parametrize("label,phrase", [
    ("NO SIGNAL", "no setup matched"),
    ("ACCEPTED SHADOW", "no order was attempted"),
    ("REJECTED", "rejected by an admission"),
    ("REFUSED", "see operational details"),
    ("MISSED", "did not run"),
    ("NO DIAGNOSTICS", "before signal diagnostics existed"),
])
def test_31_dom_every_chip_carries_a_plain_english_tooltip(page_ctx, label, phrase):
    el = [e for e in page_ctx.query_selector_all(CHIP_SELECTOR)
          if label in e.inner_text()]
    assert el, label
    tip = el[0].get_attribute("data-tooltip") or ""
    assert phrase in tip.lower(), (label, tip)
    assert "has-tip" in (el[0].get_attribute("class") or "")


def _expand(page, job_name):
    """Click the row open and read it back by RE-QUERYING.

    The click re-renders the journal, so the button handle held from before is detached and
    reading through it returns the pre-click markup. That is what made the first version of
    this assert fail against a panel that had in fact expanded.
    """
    def _row():
        for btn in page.query_selector_all(".job-trigger"):
            nm = btn.query_selector(".job-name")
            if nm and job_name in nm.inner_text():
                return btn
        return None

    btn = _row()
    assert btn is not None, f"{job_name} not found"
    if btn.get_attribute("aria-expanded") != "true":
        btn.click()
        page.wait_for_timeout(250)
    btn = _row()
    assert btn is not None, f"{job_name} vanished after the click"
    assert btn.get_attribute("aria-expanded") == "true", f"{job_name} did not expand"
    return btn.evaluate("e => e.closest('.job-row').innerText")


def test_32_dom_expanded_no_signal_shows_operator_text_and_no_raw_names(page_ctx):
    text = _expand(page_ctx, "TRACK1_STRESS_1155")
    assert "No setup matched this slot." in text
    assert "OPERATIONAL" in text and "SIGNAL" in text
    for raw in ("breadth_down_count", "gate_allow", "freshness_allow", "gapdown_count",
                "not_exposed_by_sleeve", "rule_checks"):
        assert raw not in text, raw
    assert "{" not in text.split("OPERATIONAL")[1], "a JSON blob reached the panel"


def test_33_dom_expanded_operational_answers_the_runtime_questions(page_ctx):
    text = _expand(page_ctx, "TRACK1_STRESS_1155")
    for want in ("Ran at", "budget", "Ledger row written", "Freshness check passed",
                 "No checkpoint or book write expected in shadow"):
        assert want in text, want


def test_34_dom_expanded_refused_points_at_operational_and_does_not_repeat_it(page_ctx):
    text = _expand(page_ctx, "TRACK1_STRESS_1210")
    assert "Strategy was not evaluated." in text
    assert "See Operational details for the runtime refusal." in text
    # the refusal itself is stated ONCE, in the operational block
    assert text.count("Slot refused before strategy evaluation.") == 1


def test_35_dom_expanded_accepted_shows_the_candidate_and_no_order(page_ctx):
    text = _expand(page_ctx, "TRACK1_STRESS_1200")
    assert "MNQ" in text and "SHORT" in text
    assert "Admitted in shadow; no order attempted." in text


def test_36_dom_expanded_rejected_names_the_layer_in_human_words(page_ctx):
    text = _expand(page_ctx, "TRACK1_STRESS_1205")
    assert "Setup matched." in text
    assert "Rejected by: Position cap." in text
    assert "family_cap" not in text


def test_37_dom_the_collapsed_row_does_not_carry_the_paragraph(page_ctx):
    """The chip replaced the sentence. A paragraph on every row is what made the list
    unscannable."""
    rows = page_ctx.query_selector_all(".job-row")
    for r in rows:
        if r.query_selector(CHIP_SELECTOR) is None:
            continue
        # collapsed rows must not contain the operator prose
        if "selected" in (r.get_attribute("class") or ""):
            continue
        t = r.inner_text()
        assert "No setup matched this slot." not in t
        assert "Detailed setup measurements" not in t


#: The project's own element-level detector, reused rather than reinvented. A document-level
#: `scrollWidth > clientWidth` check is too weak here and mutation M24 proved it: an oversized
#: chip inside a clipping container never makes the PAGE scroll, so the test stayed green with
#: a 900px-wide chip on a 380px screen.
_CLIPPED = r"""() => {
  const de = document.documentElement;
  const scrolls = el => {
    for (let node = el; node; node = node.parentElement) {
      const ox = getComputedStyle(node).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
    }
    return false;
  };
  return [...document.querySelectorAll('.job-row *')]
    .filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.right > de.clientWidth + 1 && !scrolls(el);
    })
    .map(el => `${el.tagName}.${(el.className || '').toString().trim().split(/\s+/)[0] || ''}`)
    .slice(0, 8);
}"""


def test_38_dom_nothing_in_a_job_row_overflows_at_narrow_width(page_ctx):
    page_ctx.set_viewport_size({"width": 380, "height": 900})
    page_ctx.wait_for_timeout(250)
    clipped = page_ctx.evaluate(_CLIPPED)
    wide = page_ctx.evaluate(
        "() => [...document.querySelectorAll(\".job-badges .event-status[class*='signal-']\")]"
        ".filter(c => c.getBoundingClientRect().width >"
        "             c.closest('.job-row').getBoundingClientRect().width + 1)"
        ".map(c => c.innerText.trim())")
    page_doc = page_ctx.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    page_ctx.set_viewport_size({"width": 1400, "height": 1000})
    page_ctx.wait_for_timeout(150)
    assert clipped == [], f"these extend past the viewport with no scrolling ancestor: {clipped}"
    assert page_doc <= 1, f"the page scrolls horizontally by {page_doc}px"
    # And the chip against its OWN row. Mutation M24 gave the chip a 900px min-width and both
    # checks above stayed green, because the journal list is a scrolling container and the
    # detector correctly allows content to be wide inside one. "Does not widen the row" is a
    # different claim from "does not overflow the page", and it is the one this stage made.
    assert wide == [], f"the chip is wider than its own row: {wide}"


# ══════════════════════════════════════════════════════════════════════════════
# 7. the Track 1 panel stays compact
# ══════════════════════════════════════════════════════════════════════════════

def _js():
    return (REPO / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")


def test_39_the_panel_row_reports_counts_and_no_per_slot_wall():
    js = _js()
    seg = js.split("function signalsRow() {")[1].split("\n    }")[0]
    assert "totals" in seg and "counts" in seg
    for gone in ("latest_slot_time", "latest_accepted", "latest_status"):
        assert gone not in seg, gone


def test_40_the_render_path_has_no_rule_grid_left():
    js = _js()
    assert "rule-checks" not in js
    assert "JSON.stringify" not in js
    css = (REPO / "global_index/dash/realtime/realtime.css").read_text(encoding="utf-8")
    assert ".rule-check" not in css


def test_41_the_chip_reuses_the_existing_visual_language():
    """Rewritten by Stage 5ZP, and the rewrite makes the claim STRONGER rather than weaker.

    This used to check that a chip of its own invention had borrowed three properties from the
    dashboard's look. It now checks that the chip IS the dashboard's chip: `.event-status`,
    the same class RUNNER and COMPLETED use, carrying nothing but a tone.
    """
    css = (REPO / "global_index/dash/realtime/realtime.css").read_text(encoding="utf-8")
    js = _js()
    assert ".job-signal-chip" not in css, "the bespoke pill is back"
    assert "job-signal-chip" not in js
    for tone in ("good", "bad", "warn", "watch", "neutral", "muted"):
        assert f".event-status.signal-{tone}" in css, tone
    # rendered with the shared class, and only the tone is its own
    assert 'class="event-status signal-${esc(chip.tone)}' in js


def test_42_no_new_card_or_column_was_added():
    js = _js()
    assert js.count("t1Fact('Signals today'") == 1
    # the chip and both sections live INSIDE the existing job row / detail panel
    assert "job-badges" in js and "job-section" in js
    assert "<table" not in js.split("function signalDetails")[1][:1500]
