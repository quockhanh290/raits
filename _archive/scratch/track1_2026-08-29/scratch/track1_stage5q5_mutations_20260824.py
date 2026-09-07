"""Stage 5Q-5 mutation harness — restore each defect and each guard's absence.

    python scratch/track1_stage5q5_mutations_20260824.py

Nothing here starts a scheduler, restarts a backend, connects to a broker or writes to a real
parquet or CSV. Files edited on disk are restored and hash-verified byte-for-byte before exit.

P1 and P6 are not inventions: they put back exactly what was on disk this morning, and what
each cost is measured in the Stage 5Q-4 audit.

Each mutation re-runs pytest in a FRESH subprocess.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")

TEST = "scratch/test_track1_stage5q5_freshness_boundary_20260824.py"


def run_sub(node: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-x", node],
                       capture_output=True, text=True, cwd="d:/raits", timeout=900)
    return r.returncode


def mutate(label, apply_, revert, node) -> dict:
    baseline = run_sub(node)
    apply_()
    try:
        mutated = run_sub(node)
    finally:
        revert()
    restored = run_sub(node)
    ok = baseline == 0 and mutated != 0 and restored == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: "
          f"baseline={baseline} mutated={mutated} restored={restored}")
    return {"mutation": label, "guard": node, "baseline_exit": baseline,
            "mutated_exit": mutated, "restored_exit": restored, "detected": ok}


def main() -> int:
    results = []
    fresh_path = Path("global_index/track1_freshness.py")
    fresh_orig = fresh_path.read_text(encoding="utf-8")
    upd_path = Path("global_index/update_ibkr_daily.py")
    upd_orig = upd_path.read_text(encoding="utf-8")
    sched_path = Path("global_index/run_scheduler.py")
    sched_orig = sched_path.read_text(encoding="utf-8")
    slots_path = Path("global_index/track1_slots.py")
    slots_orig = slots_path.read_text(encoding="utf-8")

    def write(path, text):
        return lambda: path.write_text(text, encoding="utf-8")

    def sub(orig, old, new, tag):
        out = orig.replace(old, new)
        if out == orig:
            raise SystemExit(f"{tag} mutation did not apply; the target moved")
        return out

    # ── Part A ───────────────────────────────────────────────────────────────

    # P1 — the daily series is asked for the intraday day again. This is the code that was on
    # disk this morning, and it refused every instant from 13:45 onward.
    results.append(mutate(
        "P1 the daily series is asked for the intraday requirement again",
        write(fresh_path, sub(fresh_orig,
                              "    daily_through = required_daily_close_through(now_et)",
                              "    daily_through = through", "P1")),
        write(fresh_path, fresh_orig),
        f"{TEST}::test_the_measured_case_friday_afternoon_now_passes"))

    # P2 — the daily requirement stops being causal and becomes "today", so a session would be
    # asked to trade on a close taken during its own session.
    results.append(mutate(
        "P2 the daily requirement becomes today instead of the day before",
        write(fresh_path, sub(fresh_orig,
                              "    return prev_trading_day(ts.normalize())",
                              "    return ts.normalize()", "P2")),
        write(fresh_path, fresh_orig),
        f"{TEST}::test_the_two_requirements_at_each_instant"))

    # P3 — the calendar is dropped and weekends-only comes back, so the day after a holiday
    # asks for a close that can never exist.
    results.append(mutate(
        "P3 holidays stop being skipped",
        write(fresh_path, sub(
            fresh_orig, "    try:\n        from raits.live.trading_calendar import is_trading_day",
            "    if True:\n        return True\n    try:\n"
            "        from raits.live.trading_calendar import is_trading_day", "P3")),
        write(fresh_path, fresh_orig),
        f"{TEST}::test_the_day_after_a_holiday_does_not_ask_for_the_holiday"))

    # P4 — a true pre-flight record over short data stops being named as a contradiction.
    results.append(mutate(
        "P4 a successful pre-flight over short data is no longer named",
        write(fresh_path, sub(fresh_orig, "    if not stale:", "    if True:", "P4")),
        write(fresh_path, fresh_orig),
        f"{TEST}::test_a_true_preflight_over_short_data_is_named_as_a_contradiction"))

    # P5 — the consistency check fires even when the pre-flight itself failed, so a retry and a
    # contract question print as one thing.
    results.append(mutate(
        "P5 a failed pre-flight is reported as a contradiction too",
        write(fresh_path, sub(fresh_orig, "    if preflight.status != OK:",
                              "    if False:", "P5")),
        write(fresh_path, fresh_orig),
        f"{TEST}::test_the_consistency_check_is_silent_when_the_preflight_itself_failed"))

    # P6 — the post-close SPY refresh is removed. The state this morning: nothing after 13:45,
    # so the daily series can never reach the day the next morning needs.
    results.append(mutate(
        "P6 the post-close SPY refresh job is removed",
        write(sched_path, sub(sched_orig, '                         id="spy_refresh_pm",',
                              '                         id="spy_refresh_pm_DISABLED",', "P6")),
        write(sched_path, sched_orig),
        f"{TEST}::test_the_post_close_spy_job_exists_in_every_mode"))

    # P7 — the new job stops being classified, so it lands in `unclassified` and a legacy
    # retirement could take the refresher with it.
    results.append(mutate(
        "P7 the SPY refresh is no longer shared infrastructure",
        write(slots_path, sub(slots_orig, '    "spy_refresh_pm": "Stage 5Q-5.',
                              '    "spy_refresh_pm_UNLISTED": "Stage 5Q-5.', "P7")),
        write(slots_path, slots_orig),
        f"{TEST}::test_the_new_job_is_classified_as_shared_infrastructure"))

    # P8 — the job re-runs the IBKR fetch as well, opening a second Gateway client for nothing.
    results.append(mutate(
        "P8 the post-close job also re-runs update_ibkr_daily",
        write(sched_path, sub(
            sched_orig,
            '        cmd = [sys.executable, "-m", "global_index.update_spy_csv", "--csv", regime_csv]',
            '        cmd = [sys.executable, "-m", "global_index.update_ibkr_daily"]', "P8")),
        write(sched_path, sched_orig),
        f"{TEST}::test_it_refreshes_spy_only_and_writes_no_preflight_record"))

    # ── Part B ───────────────────────────────────────────────────────────────

    # P9 — the boundary bar is excluded again. The state this morning: MNQ's partial 13:45 bar
    # frozen for ever.
    results.append(mutate(
        "P9 the boundary bar is never revisited",
        write(upd_path, sub(upd_orig, "                if a.repair_boundary:",
                            "                if False:", "P9")),
        write(upd_path, upd_orig),
        f"{TEST}::test_the_appender_is_off_by_default"))

    # P10 — the monotonic completion rule is dropped, so two sources disagreeing about which
    # bar it is would be written as if one had merely finished.
    results.append(mutate(
        "P10 a bar whose open changed is accepted as a completion",
        write(upd_path, sub(
            upd_orig,
            '    if abs(float(new["open"]) - float(old["open"])) > 1e-6:',
            "    if False:", "P10")),
        write(upd_path, upd_orig),
        f"{TEST}::test_anything_that_is_not_a_completion_refuses[feed0-open_changed]"))

    results.append(mutate(
        "P11 a low that ROSE is accepted as a completion",
        write(upd_path, sub(upd_orig, '    if float(new["low"]) > float(old["low"]) + 1e-6:',
                            "    if False:", "P11")),
        write(upd_path, upd_orig),
        f"{TEST}::test_anything_that_is_not_a_completion_refuses[feed1-low_rose]"))

    results.append(mutate(
        "P12 a volume that SHRANK is accepted as a completion",
        write(upd_path, sub(
            upd_orig, '    if float(new["volume"]) < float(old["volume"]) - 1e-6:',
            "    if False:", "P12")),
        write(upd_path, upd_orig),
        f"{TEST}::test_anything_that_is_not_a_completion_refuses[feed3-volume_shrank]"))

    # P13 — the percentage net is removed, so a bar from a different contract could pass every
    # monotonic rule and be written.
    results.append(mutate(
        "P13 the percentage net on a completion is removed",
        write(upd_path, sub(
            upd_orig, "    if 100.0 * worst / base > BOUNDARY_REPLACE_MAX_PCT:",
            "    if False:", "P13")),
        write(upd_path, upd_orig),
        f"{TEST}::test_anything_that_is_not_a_completion_refuses[feed4-moved_too_far]"))

    # P14 — the history invariant is widened instead of exempting one timestamp, so a
    # replacement that moved OTHER bars would pass.
    results.append(mutate(
        "P14 the history invariant is skipped whenever a replacement happens",
        write(upd_path, sub(
            upd_orig,
            '                    old_tail = old_tail.drop(index=[last_existing], errors="ignore")',
            "                    old_tail = old_tail.iloc[:0]", "P14")),
        write(upd_path, upd_orig),
        f"{TEST}::test_the_history_invariant_exempts_only_the_boundary_timestamp"))

    # P15 — the snapshot and the post-write verification are removed.
    results.append(mutate(
        "P15 a replacement writes with no snapshot and no verify",
        write(upd_path, sub(upd_orig,
                            "                    _backup.write_bytes(parquet_path.read_bytes())",
                            "                    pass", "P15")),
        write(upd_path, upd_orig),
        f"{TEST}::test_a_replacement_snapshots_and_verifies_by_re_reading"))

    # P16 — the strictly-newer filter is dropped altogether, which would let a fetch rewrite
    # arbitrary history rather than one bounded bar.
    results.append(mutate(
        "P16 the strictly-newer filter is dropped for everything",
        write(upd_path, sub(
            upd_orig,
            "                new_only = new_bars_adj[new_bars_adj.index > last_existing]",
            "                new_only = new_bars_adj", "P16")),
        write(upd_path, upd_orig),
        f"{TEST}::test_the_strictly_newer_filter_is_still_there_for_everything_else"))

    # ── restores, verified by hash ───────────────────────────────────────────
    problems = []
    for path, orig in ((fresh_path, fresh_orig), (upd_path, upd_orig),
                       (sched_path, sched_orig), (slots_path, slots_orig)):
        now = path.read_text(encoding="utf-8")
        if hashlib.sha256(now.encode()).hexdigest() != hashlib.sha256(orig.encode()).hexdigest():
            problems.append(str(path))
    detected = sum(1 for r in results if r["detected"])
    print()
    print(f"{detected}/{len(results)} mutations detected")
    print("restores verified byte-for-byte"
          if not problems else f"RESTORE MISMATCH: {problems}")
    Path("scratch/_track1_stage5q5_mutations.json").write_text(
        json.dumps({"results": results, "detected": detected, "total": len(results),
                    "restore_mismatch": problems}, indent=2), encoding="utf-8")
    return 0 if detected == len(results) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
