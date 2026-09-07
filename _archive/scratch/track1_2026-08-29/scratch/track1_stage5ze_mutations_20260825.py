"""Stage 5ZE mutation harness — break the operator view, prove the right test goes red.

The stage named three that must bite: removing the chip, emptying a tooltip, and removing an
operational field. The rest fell out of building it, and the ones that matter most are the
mutations that put developer material back on the page — because that is the failure mode this
stage exists to reverse, and it is invisible until an operator is looking at it.

Discipline carried forward from 5V / 5X / 5Y / 5Z / 5ZB / 5ZD:

  * `expect_red` proves each test green BEFORE mutating;
  * a BEHAVIOUR test needs the callable replaced, not the file text;
  * a source patch must stay parseable.

The DOM tests run a real chromium and cannot be reached by patching a Python object, so those
are mutated through the FILE the browser loads.

Run:  python scratch/track1_stage5ze_mutations_20260825.py
"""
from __future__ import annotations

import io
import json
import shutil
import sys
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scratch")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

SUITE = "scratch/test_track1_stage5ze_job_view_operator_20260825.py"
RESULTS: list = []


def _run(test: str) -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        return int(pytest.main(["-q", "-p", "no:randomly", "-x", f"{SUITE}::{test}"]))


def expect_red(label: str, what: str, patcher, test: str) -> bool:
    if _run(test) != 0:
        RESULTS.append({"id": label, "mutation": what, "test": test,
                        "outcome": "BASELINE NOT GREEN"})
        print(f"  [{label}] BASELINE NOT GREEN {test}")
        return False
    with patcher:
        red = _run(test) != 0
    RESULTS.append({"id": label, "mutation": what, "test": test,
                    "outcome": "RED" if red else "STILL GREEN"})
    print(f"  [{label}] {'RED  ' if red else 'STILL GREEN'} {test}")
    if not red:
        print("         ^-- the test does not check this")
    return red


@contextmanager
def edit_asset(path: Path, replace_from: str, replace_to: str):
    """Really edit the file the browser loads, then put it back.

    A `Path.read_text` patch cannot reach chromium — it fetches the asset over HTTP from the
    Flask app, which reads the real file from disk. So this writes, and restores from a copy
    in a `finally` so a crash mid-run cannot leave the dashboard mutated.
    """
    original = path.read_text(encoding="utf-8")
    assert replace_from in original, f"anchor not found in {path.name}"
    backup = path.with_suffix(path.suffix + ".mutbak")
    shutil.copy2(path, backup)
    try:
        path.write_text(original.replace(replace_from, replace_to, 1), encoding="utf-8")
        yield
    finally:
        path.write_text(original, encoding="utf-8")
        backup.unlink(missing_ok=True)


def main() -> int:
    import global_index.track1_signals as sig
    import monitor.backend.job_journal_reader as jj

    JS = ROOT / "global_index/dash/realtime/realtime.js"
    CSS = ROOT / "global_index/dash/realtime/realtime.css"

    print("Stage 5ZE mutations\n" + "=" * 74)
    ok = True

    # ══ 1. the three the stage named ═══════════════════════════════════════
    print("\nM1 - the chip stops rendering")
    ok &= expect_red("M1", "the collapsed row loses its signal chip",
                     edit_asset(JS, "    return `<span class=\"job-signal-chip",
                                "    if (true) return '';\n    return `<span class=\"job-signal-chip"),
                     "test_28_dom_every_strategy_job_shows_a_signal_chip")

    print("\nM2 - the tooltip is emptied")
    ok &= expect_red("M2", "seven colours nobody can act on",
                     edit_asset(JS, 'data-tooltip="${esc(chip.tooltip)}"',
                                'data-tooltip=""'),
                     "test_31_dom_every_chip_carries_a_plain_english_tooltip[NO SIGNAL-no setup matched]")

    print("\nM3 - an operational field is removed")
    ok &= expect_red(
        "M3", "the ledger-row line dropped",
        patch.object(jj, "_operational",
                     lambda job, row, cov, aud: {"ran": "ran", "duration_seconds": 3,
                                                 "over_budget": False, "budget_seconds": 300,
                                                 "ledger_row": True, "freshness_pass": True,
                                                 "refused": False, "refusal_reason": None,
                                                 "audit_verdict": None,
                                                 "lines": ["Ran at 11:55:00 ET, duration 3s."]}),
        "test_16_a_healthy_slot_reports_run_budget_ledger_freshness_and_shadow_expectation")

    # ══ 2. developer material back on the page ═════════════════════════════
    print("\nM4 - raw field names return to the operator lines")

    def raw_lines(row):
        checks = row.get("rule_checks") or []
        return [f"{c['rule']}={c['passed']}" for c in checks] or ["gate_allow=True"]

    ok &= expect_red("M4", "breadth_down_count back in front of an operator",
                     patch.object(sig, "operator_lines", raw_lines),
                     "test_9_no_operator_line_anywhere_contains_a_raw_field_name")

    print("\nM5 - JSON thresholds return")
    ok &= expect_red("M5", "a threshold blob in the panel",
                     patch.object(sig, "operator_lines",
                                  lambda row: [json.dumps(sig.thresholds("roska4_stress"))]),
                     "test_10_no_operator_line_contains_a_json_threshold_blob")

    print("\nM6 - the wall of unmeasured rules returns")
    ok &= expect_red(
        "M6", "thirty mapped names with no numbers beside them",
        patch.object(sig, "operator_lines",
                     lambda row: [f"{sig.label(c['rule'])}: UNKNOWN"
                                  for c in (row.get("rule_checks") or [])] or ["x"] * 30),
        "test_11_no_wall_of_unknown_rows")

    print("\nM7 - the rule grid comes back to the render path")
    ok &= expect_red("M7", "the developer table reinstated",
                     edit_asset(JS, "  function signalDetails(job) {",
                                "  function _ruleGrid(c){return `<li class=\"rule-check\">"
                                "${JSON.stringify(c)}</li>`;}\n"
                                "  function signalDetails(job) {"),
                     "test_40_the_render_path_has_no_rule_grid_left")

    print("\nM8 - the expanded panel prints the raw names again")
    ok &= expect_red(
        "M8", "developer variables in the browser",
        edit_asset(JS, "    const lines = (sg.operator || []).map(l => `<li>${esc(l)}</li>`).join('');",
                   "    const lines = ((sg.debug && sg.debug.rule_checks) || [])"
                   ".map(c => `<li>${esc(c.rule)}</li>`).join('');"),
        "test_32_dom_expanded_no_signal_shows_operator_text_and_no_raw_names")

    # ══ 3. the two questions collapse into one ═════════════════════════════
    print("\nM9 - the Operational section disappears")
    ok &= expect_red("M9", "the runtime questions unanswered again",
                     edit_asset(JS, "  function operationalDetails(job) {\n    const op = job && job.operational;",
                                "  function operationalDetails(job) {\n    if (true) return '';\n    const op = job && job.operational;"),
                     "test_33_dom_expanded_operational_answers_the_runtime_questions")

    print("\nM10 - a REFUSED row repeats the runtime evidence in the signal block")
    ok &= expect_red(
        "M10", "two copies for the operator to reconcile",
        patch.object(sig, "operator_lines",
                     lambda row: ["Slot refused before strategy evaluation.",
                                  "Strategy was not evaluated."]),
        "test_34_dom_expanded_refused_points_at_operational_and_does_not_repeat_it")

    print("\nM11 - the refusal stops pointing at Operational")
    ok &= expect_red("M11", "a dead end for the operator",
                     patch.object(sig, "operator_lines",
                                  lambda row: ["Strategy was not evaluated."]),
                     "test_14_a_refused_row_points_at_operational_and_does_not_repeat_the_evidence")

    # ══ 4. scope ═══════════════════════════════════════════════════════════
    print("\nM12 - a non-strategy job gets a chip")

    def annotate_all(jobs, day, root):
        for j in jobs:
            j["signal"] = {"status": sig.NO_SIGNAL, "chip": sig.chip(sig.NO_SIGNAL),
                           "summary": "", "operator": [], "details": None, "debug": None}
            j["operational"] = {"ran": "ran", "lines": []}

    ok &= expect_red("M12", "a stop-repair row wearing a NO SIGNAL chip",
                     patch.object(jj, "_annotate_signal_diagnostics", annotate_all),
                     "test_25_a_non_strategy_job_gets_neither")
    # M12b must be mutated in the JS, not in Python. The DOM fixture builds its stub payload
    # directly and never calls `_annotate_signal_diagnostics`, so patching that function
    # cannot reach the browser -- it stayed green while proving nothing. Same family as the
    # source-patch-versus-behaviour mistake from 5V/5X/5Y/5Z/5ZD: the mutation has to land
    # where the thing under test actually reads from.
    ok &= expect_red("M12b", "the page fabricates a chip for a job with no signal object",
                     edit_asset(JS, "    const chip = sg && sg.chip;\n    if (!chip) return '';",
                                "    const chip = (sg && sg.chip) || "
                                "{tone:'neutral', tooltip:'x', label:'NO SIGNAL'};"),
                     "test_29_dom_a_non_strategy_job_shows_no_chip")

    # ══ 5. the operational answers themselves ══════════════════════════════
    print("\nM13 - the runtime budget stops being judged")
    ok &= expect_red("M13", "a duration printed with nothing to judge it against",
                     patch.object(jj, "SLOT_RUNTIME_BUDGET_S", 10 ** 9),
                     "test_17_the_runtime_budget_is_flagged_when_breached")

    print("\nM14 - a missing ledger row is silently omitted")
    real_op = jj._operational

    def quiet_ledger(job, row, cov, aud):
        out = real_op(job, row, cov, aud)
        out["lines"] = [l for l in out["lines"] if "No ledger row" not in l]
        return out

    ok &= expect_red("M14", "the audit cannot count it, and nobody is told",
                     patch.object(jj, "_operational", quiet_ledger),
                     "test_18_a_missing_ledger_row_is_stated_not_omitted")

    print("\nM15 - the refusal reason is left as a raw code")
    ok &= expect_red("M15", "gate_refused printed at an operator",
                     patch.object(sig, "label", lambda n: str(n)),
                     "test_19_a_refusal_is_reported_in_operator_words")

    print("\nM16 - the operational block stops falling back to the ledger")

    def no_fallback(job, row, cov, aud):
        return real_op(job, row, {}, aud)

    ok &= expect_red("M16", "the 33 pre-journal slots lose their diagnostics",
                     patch.object(jj, "_operational", no_fallback),
                     "test_22_operational_falls_back_to_the_ledger_when_no_signal_row_exists")

    print("\nM17 - a missed slot stops saying the scheduler never started it")
    ok &= expect_red("M17", "an absence with no explanation",
                     patch.object(jj, "_operational",
                                  lambda job, row, cov, aud: {"ran": "ran", "lines": []}),
                     "test_20_a_missed_slot_says_the_scheduler_never_started_it")

    # ══ 6. labels ══════════════════════════════════════════════════════════
    print("\nM18 - a layer loses its human name")
    ok &= expect_red("M18", "an operator reading `family_cap`",
                     patch.object(sig, "LAYER_LABELS", {}),
                     "test_12_a_rejection_names_the_layer_in_human_words_and_shows_the_candidate")

    print("\nM19 - a declared sleeve rule has no label")
    ok &= expect_red("M19", "a mapper that has fallen behind the catalogue",
                     patch.object(sig, "LABELS",
                                  {k: v for k, v in sig.LABELS.items()
                                   if k != "breadth_down_count"}),
                     "test_3_every_declared_sleeve_rule_has_a_label")

    print("\nM20 - two chips share a label")
    ok &= expect_red("M20", "REFUSED and MISSED become indistinguishable",
                     patch.object(sig, "CHIPS",
                                  {**sig.CHIPS,
                                   sig.SLOT_MISSED: ("REFUSED", "bad", "Expected slot did not run.")}),
                     "test_6_the_seven_labels_are_distinct")

    print("\nM21 - the accepted chip loses its positive tone")
    ok &= expect_red("M21", "an admission that looks like a refusal",
                     patch.object(sig, "CHIPS",
                                  {**sig.CHIPS,
                                   sig.SIGNAL_ACCEPTED_SHADOW: ("ACCEPTED SHADOW", "muted",
                                                                "Setup passed admission in shadow; no order was attempted.")}),
                     "test_7_tone_separates_admitted_from_declined_from_missed")

    # ══ 7. the panel and the layout ════════════════════════════════════════
    print("\nM22 - the Track 1 panel goes back to a per-slot wall")
    ok &= expect_red("M22", "a fact row that grows all day",
                     edit_asset(JS, "      const totals = {};",
                                "      const latest_slot_time = 1; const totals = {};"),
                     "test_39_the_panel_row_reports_counts_and_no_per_slot_wall")

    print("\nM23 - the chip stops reusing the existing visual language")
    ok &= expect_red("M23", "a second chip language on one page",
                     edit_asset(CSS, "  border-radius: 3px;\n  font: 700 11px/1 var(--mono);\n  white-space: nowrap;\n  position: relative;\n}",
                                "  border-radius: 12px;\n  font: 400 15px/1 sans-serif;\n  position: relative;\n}"),
                     "test_41_the_chip_reuses_the_existing_visual_language")

    print("\nM24 - the chip stops wrapping and overflows a narrow screen")
    ok &= expect_red("M24", "the page scrolls sideways on a phone",
                     edit_asset(CSS, "@media (max-width: 720px) {\n  .job-signal-chip { white-space: normal; }\n}",
                                ".job-signal-chip { min-width: 900px; }"),
                     "test_38_dom_nothing_in_a_job_row_overflows_at_narrow_width")

    print("\nM25 - the paragraph comes back to the collapsed row")
    ok &= expect_red(
        "M25", "thirty unscannable rows",
        edit_asset(JS, "      + ` data-tooltip=\"${esc(chip.tooltip)}\">Signal ${esc(chip.label)}</span>`;",
                   "      + ` data-tooltip=\"${esc(chip.tooltip)}\">Signal ${esc(chip.label)}"
                   " No setup matched this slot. Detailed setup measurements</span>`;"),
        "test_37_dom_the_collapsed_row_does_not_carry_the_paragraph")

    print("\n" + "=" * 74)
    print("ALL MUTATIONS RED" if ok else "SOME MUTATIONS STAYED GREEN — tests do not bind")
    out = ROOT / "scratch" / "track1_stage5ze_mutations_20260825.json"
    out.write_text(json.dumps({"all_red": bool(ok), "results": RESULTS}, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
