"""Stage 5ZB mutation harness — the negative audit Stage 5ZA left pending.

Five guards to break, named by the stage prompt, plus the ones that fell out of writing them:

    Calm dispatch grace          removed, and separately made unbounded
    Stress truncation            the scan end stops following the slot
    Swing / NKD truncation       the scan window stops being clipped to the frame clock
    live-source through=now      a sleeve fetches past its own slot
    paper callsite seam          the seam claims run_shadow again

Every mutation is applied IN PROCESS, and `expect_red` proves each test green BEFORE mutating.
Both rules were bought with green mutations that never ran:

  * pytest exits non-zero on an unknown test id, so a renamed test reads as a pass (5X, M13);
  * `_source_patch` only changes what `Path.read_text` returns — it cannot touch an imported
    function, so a behaviour test needs the callable replaced (5V, 5X, 5Y, 5Z).

The 5ZA seam tests use `inspect.getsource`, which reads the LINECACHE, so they cannot be
broken this way at all. That is why the targets below are the Stage 5ZB versions, which read
the file.

Run:  python scratch/track1_stage5zb_mutations_20260825.py
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

SUITE = "scratch/test_track1_stage5zb_operational_audit_20260825.py"
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
        print("         ^-- failing or absent; the mutation proves nothing")
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
    """Serve mutated SOURCE for one module. Only reaches tests that read the FILE."""
    real = Path.read_text
    original = Path(module.__file__).read_text(encoding="utf-8")
    assert replace_from in original, f"anchor not found in {module.__file__}"
    mutated = original.replace(replace_from, replace_to, 1)

    def read_text(self, *a, **kw):
        if Path(self) == Path(module.__file__):
            return mutated
        return real(self, *a, **kw)

    return patch.object(Path, "read_text", read_text)


def _regrace(**per_sleeve):
    """Replace REQUIREMENTS with copies carrying different grace / span rules."""
    import dataclasses
    import global_index.track1_intraday as intra
    out = {}
    for k, r in intra.REQUIREMENTS.items():
        out[k] = dataclasses.replace(r, **per_sleeve.get(k, {}))
    return patch.object(intra, "REQUIREMENTS", out)


def main() -> int:
    import global_index.track1_intraday as intra
    import global_index.track1_live_source as ls
    import global_index.track1_normal_r4 as normal
    import global_index.track1_paper_callsite as cs
    import global_index.track1_slots as t1
    import global_index.track1_stress_mnq as stress
    import global_index.run_live_day_track1 as rld

    print("Stage 5ZB mutations\n" + "=" * 74)
    ok = True

    # ══ 1. Calm dispatch grace ═════════════════════════════════════════════
    print("\nM1 - the Calm dispatch grace is removed")
    ok &= expect_red(
        "M1", "grace 60 -> 0: a slot three seconds late reads as a missed entry",
        _regrace(roska4_calm={"decision_grace_seconds": 0}),
        "test_6_seconds_of_dispatch_latency_are_still_the_scheduled_slot[3]")

    print("\nM2 - the grace becomes an amnesty")
    ok &= expect_red(
        "M2", "grace 60 -> 3600: an hour-late Calm entry is accepted",
        _regrace(roska4_calm={"decision_grace_seconds": 3600}),
        "test_7_materially_late_is_still_refused[3600]")
    ok &= expect_red(
        "M2b", "same mutation, at two minutes late",
        _regrace(roska4_calm={"decision_grace_seconds": 3600}),
        "test_7_materially_late_is_still_refused[120]")

    print("\nM3 - the grace boundary drifts by one second")
    ok &= expect_red(
        "M3", "grace 60 -> 61: the declared edge no longer matches behaviour",
        _regrace(roska4_calm={"decision_grace_seconds": 61}),
        "test_8_the_grace_boundary_is_exactly_where_it_is_declared")

    print("\nM4 - the grace is dropped from a sleeve that is not Calm")
    ok &= expect_red(
        "M4", "global_nkd loses its grace while Calm keeps it",
        _regrace(global_nkd={"decision_grace_seconds": 0}),
        "test_5_the_grace_is_declared_on_every_sleeve_and_is_one_minute")

    # ══ 2. span rules ══════════════════════════════════════════════════════
    print("\nM5 - Calm is dragged into the dynamic span bound")
    ok &= expect_red(
        "M5", "the 5V-1 blanket-min mistake, reintroduced",
        _regrace(roska4_calm={"today_to_follows_now": True}),
        "test_3_only_the_two_scanning_sleeves_follow_the_slot")

    print("\nM6 - a scanning sleeve stops following the slot")
    ok &= expect_red(
        "M6", "global_nkd demands the end of its window again",
        _regrace(global_nkd={"today_to_follows_now": False}),
        "test_14_no_slot_of_any_sleeve_demands_a_bar_from_its_own_future")

    print("\nM7 - Stress declares a span that reaches the session end")
    ok &= expect_red(
        "M7", "a fixed-span sleeve given an end-of-session bound",
        _regrace(roska4_stress={"today_to": "15:55"}),
        "test_4_no_sleeve_declares_a_span_that_needs_the_session_end")

    # ══ 3. detector truncation ═════════════════════════════════════════════
    print("\nM8 - Stress stops narrowing its scan end to the current slot")
    ok &= expect_red(
        "M8", "end = min(end, hhmm) removed",
        _source_patch(stress, "        end = min(end, hhmm)",
                      "        end = end"),
        "test_10_stress_narrows_its_scan_end_to_the_current_slot")

    print("\nM9 - Swing / NKD stop clipping the scan window to the frame clock")
    ok &= expect_red(
        "M9", "the widx_naive <= now_ts comparison removed",
        _source_patch(normal, "widx_naive <= now_ts", "widx_naive <= widx_naive"),
        "test_11_normal_r4_and_nkd_truncate_their_scan_to_the_frame_clock")

    print("\nM10 - the bound is computed but never applied to the window")
    ok &= expect_red(
        "M10", "the subscript on `win` dropped",
        _source_patch(normal, "win = win[widx_naive <= now_ts]",
                      "_unused = win[widx_naive <= now_ts]"),
        "test_11_normal_r4_and_nkd_truncate_their_scan_to_the_frame_clock")

    # ══ 4. live source ═════════════════════════════════════════════════════
    print("\nM11 - a sleeve fetches past its own slot instant")
    ok &= expect_red(
        "M11", "through=now replaced by an end-of-session bound",
        _source_patch(ls, "through=now", "through=session_end"),
        "test_12_the_live_source_fetches_every_sleeve_through_the_slot_instant")

    print("\nM12 - Calm goes back to the full-day replay detector")
    ok &= expect_red(
        "M12", "detect_entry_for_day swapped for the replay detector",
        _source_patch(ls, "detect_entry_for_day(", "detect("),
        "test_13_calm_uses_the_entry_only_detector_not_the_full_day_replay")

    # ══ 5. the seam ════════════════════════════════════════════════════════
    print("\nM13 - the paper callsite seam claims run_shadow again")
    ok &= expect_red(
        "M13", "the Stage 5W error, reintroduced",
        patch.object(cs, "seam", lambda root=".": {
            "function": "run_shadow", "anchor": "broker = NoOrderBroker()",
            "file": "global_index/run_live_day_track1.py",
            "function_lines": [1053, 1212], "after_line": 1069}),
        "test_16_the_seam_is_still_the_scheduler_slot_path")

    # ══ 6. the sweep itself ════════════════════════════════════════════════
    print("\nM14 - the slot inventory shrinks and the sweep covers less")
    ok &= expect_red(
        "M14", "a sleeve dropped from the registry",
        patch.object(t1, "TRACK1_SLOTS",
                     tuple(s for s in t1.TRACK1_SLOTS if s.sleeve != "global_nkd")),
        "test_1_all_seventy_strategy_slots_are_still_present_and_accounted_for")
    ok &= expect_red(
        "M14b", "same mutation, against the causal sweep",
        patch.object(t1, "TRACK1_SLOTS",
                     tuple(s for s in t1.TRACK1_SLOTS if s.sleeve != "global_nkd")),
        "test_14_no_slot_of_any_sleeve_demands_a_bar_from_its_own_future")

    print("\nM15 - the gate stops refusing a short frame, so the sweep proves nothing")
    ok &= expect_red(
        "M15", "validate() always allows",
        patch.object(intra, "validate",
                     lambda *a, **k: intra.Verdict(allow=True, checks=(), codes=())),
        "test_15_the_sweep_is_capable_of_failing")

    # ══ 7. strategy identity and the gate boundary ═════════════════════════
    print("\nM16 - the gate module reaches into a sleeve rule module")
    ok &= expect_red(
        "M16", "track1_intraday imports a strategy",
        _source_patch(intra, "from __future__ import annotations",
                      "from __future__ import annotations\n"
                      "from global_index import track1_normal_r4"),
        "test_17_the_causal_work_changed_no_strategy_rule")

    print("\nM17 - the dispatch grace leaks into the hashed params module")
    import global_index.track1_params as tp
    ok &= expect_red(
        "M17", "a gate field lands where identity is computed",
        _source_patch(tp, "from __future__ import annotations",
                      "from __future__ import annotations\n"
                      "decision_grace_seconds = 60"),
        "test_17b_the_grace_is_a_gate_field_not_a_strategy_parameter")

    # ══ 8. the 2026-08-24 Calm crash ═══════════════════════════════════════
    print("\nM18 - the slot stops catching SpliceRefused")
    ok &= expect_red(
        "M18", "the crash that left a window open forever",
        _source_patch(rld, "    except SpliceRefused", "    except NotImplementedError"),
        "test_25_the_calm_crash_of_20260824_cannot_happen_again")

    print("\nM19 - the live source stops projecting the provider's extra columns")

    def keep_extras(inst, live, frozen):
        return live, ()

    ok &= expect_red("M19", "average/barcount ride into the join again",
                     patch.object(ls, "project_to_frozen_columns", keep_extras),
                     "test_25_the_calm_crash_of_20260824_cannot_happen_again")

    # ══ 9. operational guards ══════════════════════════════════════════════
    print("\nM20 - a dangling window becomes invisible")
    ok &= expect_red(
        "M20", "an unclosed window not reported",
        patch.object(Path, "glob", lambda self, pat: iter(())),
        "test_24_every_opened_window_in_the_ledger_is_accounted_for")

    print("\nM21 - the runbook loses an artefact the operator must inspect")
    real_read = Path.read_text

    def strip_runbook(self, *a, **kw):
        text = real_read(self, *a, **kw)
        if self.name == "TRACK1_SHADOW_WINDOW_RUNBOOK.md":
            return text.replace("slot_timing", "(removed)")
        return text

    ok &= expect_red("M21", "slot_timing dropped from the checklist",
                     patch.object(Path, "read_text", strip_runbook),
                     "test_22_the_runbook_exists_and_names_every_artefact_to_inspect")

    print("\nM22 - the runbook loses the clock anchor")

    def strip_clocks(self, *a, **kw):
        text = real_read(self, *a, **kw)
        if self.name == "TRACK1_SHADOW_WINDOW_RUNBOOK.md":
            return text.replace("Calgary", "(removed)")
        return text

    ok &= expect_red("M22", "the three-clock anchor removed",
                     patch.object(Path, "read_text", strip_clocks),
                     "test_23_the_runbook_states_the_three_clocks_explicitly")

    print("\n" + "=" * 74)
    print("ALL MUTATIONS RED" if ok else "SOME MUTATIONS STAYED GREEN — tests do not bind")
    out = ROOT / "scratch" / "track1_stage5zb_mutations_20260825.json"
    out.write_text(json.dumps({"all_red": bool(ok), "results": RESULTS}, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
