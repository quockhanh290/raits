"""Stage 5ZD mutation harness — break the diagnostics, prove the right test goes red.

Five negative checks the stage named, plus the ones that fell out of building it:

    status classification cannot collapse NO_SIGNAL and SIGNAL_REJECTED
    rule_checks cannot be omitted
    accepted shadow cannot imply order_attempted
    an absent file cannot become an error
    a missed slot cannot be faked as NO_SIGNAL

Discipline carried forward from 5V / 5X / 5Y / 5Z / 5ZB, all of it bought with green
mutations that never ran:

  * `expect_red` proves each test green BEFORE mutating — pytest exits non-zero on an unknown
    test id, so a renamed test otherwise reads as a successful mutation;
  * a BEHAVIOUR test needs the callable replaced. `_source_patch` only changes what
    `Path.read_text` returns and cannot touch an imported function;
  * a source patch must stay parseable, or a test that walks files will skip it.

Run:  python scratch/track1_stage5zd_mutations_20260825.py
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scratch")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

SUITE = "scratch/test_track1_stage5zd_signal_diagnostics_20260825.py"
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


def _source_patch(module, replace_from: str, replace_to: str):
    real = Path.read_text
    original = Path(module.__file__).read_text(encoding="utf-8")
    assert replace_from in original, f"anchor not found in {module.__file__}"
    mutated = original.replace(replace_from, replace_to, 1)

    def read_text(self, *a, **kw):
        if Path(self) == Path(module.__file__):
            return mutated
        return real(self, *a, **kw)

    return patch.object(Path, "read_text", read_text)


def _file_patch(path: Path, replace_from: str, replace_to: str):
    """Same idea for a non-module file — the dashboard JS and CSS."""
    real = Path.read_text
    original = real(path, encoding="utf-8")
    assert replace_from in original, f"anchor not found in {path}"
    mutated = original.replace(replace_from, replace_to, 1)

    def read_text(self, *a, **kw):
        if Path(self).resolve() == path.resolve():
            return mutated
        return real(self, *a, **kw)

    return patch.object(Path, "read_text", read_text)


def main() -> int:
    import global_index.track1_signals as sig
    import monitor.backend.job_journal_reader as jj
    import monitor.backend.track1_runtime_reader as rr
    import global_index.run_live_day_track1 as rld

    JS = ROOT / "global_index/dash/realtime/realtime.js"
    CSS = ROOT / "global_index/dash/realtime/realtime.css"

    print("Stage 5ZD mutations\n" + "=" * 74)
    ok = True

    # ══ 1. the classification must not collapse ════════════════════════════
    print("\nM1 - NO_SIGNAL and SIGNAL_REJECTED become the same status")

    def collapsed(*, decided, reason, raw_candidates, accepted, rejected):
        if not decided:
            return sig.SLOT_REFUSED
        if accepted > 0:
            return sig.SIGNAL_ACCEPTED_SHADOW
        return sig.NO_SIGNAL            # <-- a declined candidate reads as "nothing offered"

    ok &= expect_red("M1", "a rejected candidate reported as NO_SIGNAL",
                     patch.object(sig, "classify", collapsed),
                     "test_7_no_signal_and_rejected_cannot_be_the_same_row")
    ok &= expect_red("M1b", "same mutation, against the classification matrix",
                     patch.object(sig, "classify", collapsed),
                     "test_6_classification_is_total_and_explicit[True-1-0-1-SIGNAL_REJECTED]")

    print("\nM2 - a refusal stops winning over a candidate count")

    def refusal_ignored(*, decided, reason, raw_candidates, accepted, rejected):
        if raw_candidates > 0 and accepted > 0:
            return sig.SIGNAL_ACCEPTED_SHADOW
        if not decided:
            return sig.SLOT_REFUSED
        return sig.NO_SIGNAL

    ok &= expect_red("M2", "a refused slot with a stale candidate reads as accepted",
                     patch.object(sig, "classify", refusal_ignored),
                     "test_6_classification_is_total_and_explicit[False-3-1-0-SLOT_REFUSED]")

    # ══ 2. rule_checks cannot be omitted ═══════════════════════════════════
    print("\nM3 - a row may be written with no rule checks")
    real_post = sig.SignalRow.__post_init__

    def lax(self):
        if self.status == sig.SIGNAL_ACCEPTED_SHADOW and not self.reason:
            self.reason = "shadow_only"

    ok &= expect_red("M3", "`candidates: 0` wearing a longer name",
                     patch.object(sig.SignalRow, "__post_init__", lax),
                     "test_9_a_row_without_rule_checks_is_refused")

    print("\nM4 - the builder stops emitting the sleeve's declared rules")
    ok &= expect_red("M4", "rule_checks_for returns only the gate",
                     patch.object(sig, "rule_checks_for",
                                  lambda sleeve, **kw: [sig.rule("gate_allow", True)]),
                     "test_8_no_signal_carries_rule_checks_not_just_a_zero")
    ok &= expect_red("M4b", "same mutation, against the per-sleeve catalogue",
                     patch.object(sig, "rule_checks_for",
                                  lambda sleeve, **kw: [sig.rule("gate_allow", True)]),
                     "test_20_each_sleeve_emits_every_declared_rule_on_a_real_row[global_nkd]")

    print("\nM5 - an unreported rule is reported as having passed")

    def optimistic(name, passed=None, value=None, threshold=None, comparator="",
                   detail="", source=sig.MEASURED):
        return sig.RuleCheck(rule=name, passed=True, value=value, threshold=threshold,
                             comparator=comparator, detail=detail, not_reached=False,
                             source=sig.MEASURED)

    ok &= expect_red("M5", "not_exposed_by_sleeve flattened into a pass",
                     patch.object(sig, "rule", optimistic),
                     "test_10_the_three_answer_sources_are_distinct")
    ok &= expect_red("M5b", "same mutation, against the nearest-miss report",
                     patch.object(sig, "rule", optimistic),
                     "test_11_primary_failure_reports_not_exposed_separately_from_passed")

    # ══ 3. accepted shadow cannot imply an order ═══════════════════════════
    print("\nM6 - an accepted shadow row may claim an order attempt")
    ok &= expect_red("M6", "the one claim this journal exists to make impossible",
                     patch.object(sig.SignalRow, "__post_init__", lax),
                     "test_17_accepted_shadow_cannot_claim_an_order_attempt")

    print("\nM7 - orders_enabled stops being stated on every row")
    real_as_row = sig.SignalRow.as_row

    def thin(self):
        d = real_as_row(self)
        d.pop("orders_enabled", None)
        d.pop("order_attempted", None)
        return d

    ok &= expect_red("M7", "a reader left to assume the default",
                     patch.object(sig.SignalRow, "as_row", thin),
                     "test_18_every_row_states_orders_enabled_false_explicitly")

    # ══ 4. an absent file cannot become an error ═══════════════════════════
    print("\nM8 - a missing signals file raises instead of reading as not-yet-observed")

    def strict_summary(day, *, root="."):
        p = sig.journal_path(day, root)
        if not p.exists():
            raise FileNotFoundError(str(p))
        return {"present": True, "sleeves": {}}

    ok &= expect_red("M8", "the day has not started, reported as a fault",
                     patch.object(sig, "summary", strict_summary),
                     "test_26_reader_reports_absent_file_as_not_yet_observed")

    print("\nM9 - a disabled channel reads as an empty day")

    def quiet(day, *, root="."):
        return {"present": False, "day": str(day), "route": sig.ROUTE,
                "reading": "not yet observed", "sleeves": {}, "invalid": 0}

    ok &= expect_red("M9", "channel_disabled dropped from the summary",
                     patch.object(sig, "summary", quiet),
                     "test_29_reader_reports_a_disabled_channel_rather_than_an_empty_day")

    # ══ 5. a missed slot cannot be faked ═══════════════════════════════════
    print("\nM10 - a slot that never spawned is written up as NO_SIGNAL")
    real_ann = jj._annotate_signal_diagnostics

    def fake_no_signal(jobs, day, root):
        real_ann(jobs, day, root)
        for j in jobs:
            s = j.get("signal")
            if s and s["status"] in (sig.SLOT_MISSED, sig.SLOT_NO_ROW):
                s["status"] = sig.NO_SIGNAL
                s["summary"] = sig.one_line({"status": sig.NO_SIGNAL, "raw_candidates": 0})

    ok &= expect_red("M10", "the machine was asleep, reported as the strategy declining",
                     patch.object(jj, "_annotate_signal_diagnostics", fake_no_signal),
                     "test_34_a_slot_that_never_spawned_is_missed_and_never_no_signal")
    ok &= expect_red("M10b", "same mutation, against a slot that ran with no row",
                     patch.object(jj, "_annotate_signal_diagnostics", fake_no_signal),
                     "test_33_a_slot_that_RAN_with_no_row_is_no_diagnostics_not_missed")

    print("\nM11 - MISSED and NO DIAGNOSTICS are rendered identically")

    def one_label(row):
        r = dict(row)
        if r.get("status") == sig.SLOT_NO_ROW:
            r["status"] = sig.SLOT_MISSED
        return real_one_line(r)

    real_one_line = sig.one_line
    ok &= expect_red("M11", "a slot that ran accused of never spawning",
                     patch.object(sig, "one_line", one_label),
                     "test_25_a_missed_slot_is_never_rendered_as_no_signal")

    # ══ 6. scope: only strategy slots ══════════════════════════════════════
    print("\nM12 - a non-strategy job receives signal diagnostics")

    def annotate_everything(jobs, day, root):
        for j in jobs:
            j["signal"] = {"status": sig.NO_SIGNAL, "summary": "Signal: NO SIGNAL",
                           "source": "x", "details": None}

    ok &= expect_red("M12", "a stop-repair row reading NO SIGNAL",
                     patch.object(jj, "_annotate_signal_diagnostics", annotate_everything),
                     "test_31_non_strategy_jobs_get_no_signal_key_at_all")

    print("\nM13 - a Track 1 safety job is typed as a strategy slot")
    ok &= expect_red("M13", "the prefix widened to every TRACK1_ job",
                     patch.object(jj, "TRACK1_STRATEGY_PREFIXES", ("TRACK1_",)),
                     "test_30_only_track1_strategy_jobs_are_classified_as_such")

    print("\nM14 - a non-strategy sleeve may write a row")
    ok &= expect_red("M14", "the sleeve allow-list removed",
                     patch.object(sig, "STRATEGY_SLEEVES",
                                  tuple(list(sig.STRATEGY_SLEEVES) + ["track1_stop_repair",
                                                                     "max_hold", "preflight",
                                                                     "legacy_drain"])),
                     "test_22_a_non_strategy_sleeve_cannot_write_a_row")

    # ══ 7. rejection detail ════════════════════════════════════════════════
    print("\nM15 - every rejection is filed under one layer")
    ok &= expect_red("M15", "cap, window and same-symbol flattened into admission",
                     patch.object(sig, "_layer_for", lambda v: sig.LAYER_ADMISSION),
                     "test_13_every_rejection_names_its_layer[reject_window-window]")

    print("\nM16 - a rejection may be written with no layer")
    ok &= expect_red("M16", "a rejection nobody can act on",
                     patch.object(sig.SignalRow, "__post_init__", lax),
                     "test_15_a_rejection_without_a_named_layer_is_refused")

    print("\nM17 - the candidate detail is dropped from a rejection")
    ok &= expect_red("M17", "no instrument, no risk, nothing to judge",
                     patch.object(sig, "_candidate_brief",
                                  lambda c, *, sleeve: {"instrument": "", "direction": ""}),
                     "test_14_a_rejection_carries_the_candidate_a_reader_needs")

    # ══ 8. thresholds and provenance ═══════════════════════════════════════
    print("\nM18 - thresholds become a second hardcoded copy")
    ok &= expect_red("M18", "a restated threshold that goes stale on the first tune",
                     patch.object(sig, "thresholds",
                                  lambda s: {"breadth_down_count": {"breadth_min": 99},
                                             "rr_target_computed": {"rr": 9.9}}),
                     "test_21_thresholds_come_from_the_params_not_a_second_copy")

    # ══ 9. the wiring guards ═══════════════════════════════════════════════
    print("\nM19 - diagnostics are written BEFORE the coverage row")
    ok &= expect_red(
        "M19", "a diagnostics failure could cost a slot its evidence",
        _source_patch(rld, "    wl.slot_observed(sleeve, day, slot_id, seq=seq",
                      "    sig.append(sig.build_row(sleeve=sleeve, slot_id=slot_id,\n"
                      "        slot_time='', session_date=day, mode='shadow_live',\n"
                      "        decided=True, reason='x'), root=root)\n"
                      "    wl.slot_observed(sleeve, day, slot_id, seq=seq"),
        "test_39_the_slot_writes_diagnostics_AFTER_its_coverage_row")

    print("\nM20 - the diagnostics block is no longer wrapped")
    ok &= expect_red(
        "M20", "a diagnostics bug can take a slot down",
        _source_patch(rld, "    try:\n        _slot_hhmm = next(",
                      "    if True:\n        _slot_hhmm = next("),
        "test_40_the_diagnostics_block_cannot_take_a_slot_down")

    print("\nM21 - the signals module imports the order path")
    ok &= expect_red(
        "M21", "observability reaching into the write path",
        _source_patch(sig, "from __future__ import annotations",
                      "from __future__ import annotations\n"
                      "from global_index import track1_order_journal"),
        "test_35_the_signals_module_imports_no_broker_or_order_path")

    print("\nM22 - the reader reaches for the legacy book")
    ok &= expect_red(
        "M22", "legacy state presented as Track 1 signal state",
        _source_patch(rr, "def _signals(root: Path) -> dict:",
                      "LEGACY = \"global_index/live_positions.json\"\n\n\n"
                      "def _signals(root: Path) -> dict:"),
        "test_37_the_reader_does_not_touch_the_legacy_book")

    # ══ 10. the dashboard contract ═════════════════════════════════════════
    print("\nM23 - the panel loses its compact signals row")
    ok &= expect_red("M23", "the summary disappears from the Track 1 panel",
                     _file_patch(JS, "t1Fact('Signals today'", "t1Fact('Removed'"),
                     "test_43_the_panel_has_one_compact_signals_row")

    print("\nM24 - the expanded row stops rendering the rule checks")
    ok &= expect_red("M24", "the job row loses its details",
                     _file_patch(JS, "renderJobDetails(job, snap, presentation) + signalDetails(job)",
                                 "renderJobDetails(job, snap, presentation)"),
                     "test_44_the_job_row_renders_one_line_and_the_expanded_row_renders_the_checks")

    print("\nM25 - an unreported rule is coloured like a pass")
    ok &= expect_red("M25", "false comfort in the one place it matters",
                     _file_patch(CSS, ".rule-unknown .rule-mark { color: var(--warn, #fbbf24); }",
                                 ".rule-unknown .rule-mark { color: var(--good, #4ade80); }"),
                     "test_45_an_unreported_rule_is_not_rendered_as_a_pass")

    print("\nM26 - the signal line widens the row instead of wrapping")
    ok &= expect_red("M26", "the schedule table gets wider on mobile",
                     _file_patch(CSS, "  overflow-wrap: anywhere;\n  word-break: break-word;",
                                 "  white-space: nowrap;"),
                     "test_46_the_signal_line_wraps_instead_of_widening_the_row")

    print("\nM27 - the browser composes the sentence itself")
    ok &= expect_red("M27", "two owners for the phrasing",
                     _file_patch(JS, "return `<span class=\"job-signal signal-${esc(tone)}\">${esc(sg.summary)}</span>`;",
                                 "return `<span class=\"job-signal\">Signal: NO SIGNAL</span>`;"),
                     "test_47_the_dashboard_does_not_compose_the_sentence_itself")

    print("\n" + "=" * 74)
    print("ALL MUTATIONS RED" if ok else "SOME MUTATIONS STAYED GREEN — tests do not bind")
    out = ROOT / "scratch" / "track1_stage5zd_mutations_20260825.json"
    out.write_text(json.dumps({"all_red": bool(ok), "results": RESULTS}, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
