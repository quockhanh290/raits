"""Stage 5V-1 mutation harness — break the causality fix, prove the right test goes red.

The danger with this fix is not that it fails to work; it is that it WIDENS something. So most
of these mutations do not remove the fix — they overshoot it, and a test must catch that too.

Run:  python scratch/track1_stage5v1_mutations_20260825.py
"""
from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scratch")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

SUITE = "scratch/test_track1_stage5v1_intraday_causality_20260825.py"
RESULTS: list = []


def expect_red(label: str, what: str, patcher, test: str) -> bool:
    with patcher:
        with redirect_stdout(io.StringIO()):
            code = pytest.main(["-q", "-p", "no:randomly", "-x", f"{SUITE}::{test}"])
    red = int(code) != 0
    RESULTS.append({"id": label, "mutation": what, "test": test,
                    "outcome": "RED" if red else "STILL GREEN"})
    print(f"  [{label}] {'RED  ' if red else 'STILL GREEN'} {test}")
    if not red:
        print("         ^-- the test does not check this")
    return red


def main() -> int:
    import global_index.track1_intraday as intra
    from dataclasses import replace

    print("Stage 5V-1 mutations\n" + "=" * 74)
    ok = True

    print("\nM1 — the fix is removed: today_span demands the end of the band again")
    reqs_off = {k: replace(v, today_to_follows_now=False)
                for k, v in intra.REQUIREMENTS.items()}
    ok &= expect_red("M1", "today_to_follows_now False everywhere",
                     patch.object(intra, "REQUIREMENTS", reqs_off),
                     "test_1_a_frame_ending_at_the_slot_passes_for_that_slot")

    print("\nM2 — the fix OVERSHOOTS: the low bound follows the slot too")
    #  a scan that no longer requires 14:00 would silently read a shorter window
    real_span = intra._span_check

    def loose_lo(name, idx, day, lo, hi, step):
        return real_span(name, idx, day, hi, hi, step)   # lo == hi: only the newest bar
    ok &= expect_red("M2", "_span_check ignores the low bound",
                     patch.object(intra, "_span_check", loose_lo),
                     "test_3b_a_frame_starting_late_still_refuses_partial_coverage")

    print("\nM3 — a hole inside the span stops refusing")
    def no_gaps(name, idx, day, lo, hi, step):
        out = [c for c in real_span(name, idx, day, lo, hi, step)
               if c.code != intra.GAP_IN_COVERAGE]
        return out or [intra.Check(name, intra.OK, "mutated")]
    ok &= expect_red("M3", "_span_check drops the gap check",
                     patch.object(intra, "_span_check", no_gaps),
                     "test_3_a_hole_inside_the_span_still_refuses")

    print("\nM4 — staleness stops firing at all (the widening that would hide a dead feed)")
    ok &= expect_red("M4", "_last_closed_bar reaches back a whole day",
                     patch.object(intra, "_last_closed_bar",
                                  lambda now, n: pd.Timestamp(now).normalize()),
                     "test_2_the_same_frame_does_not_pass_for_a_later_slot")

    print("\nM5 — the horizon uses raw `now` again (the three-second false stale)")
    ok &= expect_red("M5", "_last_closed_bar returns now unchanged",
                     patch.object(intra, "_last_closed_bar", lambda now, n: pd.Timestamp(now)),
                     "test_the_three_second_slot_latency_no_longer_reads_as_stale")

    print("\nM6 — Calm is dragged into the dynamic bound")
    reqs_calm = dict(intra.REQUIREMENTS)
    reqs_calm["roska4_calm"] = replace(reqs_calm["roska4_calm"], today_to_follows_now=True)
    ok &= expect_red("M6", "roska4_calm marked as scanning",
                     patch.object(intra, "REQUIREMENTS", reqs_calm),
                     "test_only_the_two_scanning_sleeves_follow_the_slot")

    print("\nM7 — Swing loses its 14:00 low bound")
    reqs_sw = dict(intra.REQUIREMENTS)
    reqs_sw["roska4_swing"] = replace(reqs_sw["roska4_swing"], today_from="14:15")
    ok &= expect_red("M7", "roska4_swing today_from moved to 14:15",
                     patch.object(intra, "REQUIREMENTS", reqs_sw),
                     "test_swing_scans_from_1400_to_now_and_not_beyond")

    print("\nM8 — the clock stops being the requirement's own (the 13-hour class)")
    real_validate = intra.validate

    def et_only(sleeve, bars, *, now_et, **kw):
        req = kw.get("requirement") or intra.REQUIREMENTS.get(sleeve)
        if req is not None and req.clock != intra.ET:
            kw["requirement"] = replace(req, clock=intra.ET)
        return real_validate(sleeve, bars, now_et=now_et, **kw)
    ok &= expect_red("M8", "the NKD requirement is validated on ET",
                     patch.object(intra, "validate", et_only),
                     "test_the_tokyo_clock_is_still_the_one_used")

    print("\nM9 — the last slot becomes a hard refusal instead of window-shut")
    from global_index import track1_shadow_acceptance as acc
    ok &= expect_red("M9", "too_late removed from the clock refusal codes",
                     patch.object(acc, "clock_refusal_codes", lambda: {intra.TOO_EARLY}),
                     "test_the_final_slot_of_the_band_is_window_shut_not_a_hard_refusal")

    out = Path(__file__).resolve().parent / "_track1_stage5v1_mutations.json"
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    red = sum(1 for r in RESULTS if r["outcome"] == "RED")
    green = sum(1 for r in RESULTS if r["outcome"] == "STILL GREEN")
    print("\n" + "=" * 74)
    print(f"{red} mutation(s) turned a test red, {green} did not")
    print(f"wrote {out}")
    return 0 if green == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
