"""Stage 5Q-3 mutation harness — restore each defect, confirm the right test reds.

Run:

    python scratch/track1_stage5q3_mutations_20260824.py

Nothing here starts a scheduler, restarts a backend, connects to a broker or touches live
state. Production files edited on disk are restored and hash-verified byte-for-byte before the
harness exits.

Two of the mutations below are not inventions: **M1 and M3 put back exactly what was on disk
this morning**, and what they cost was measured — the first live Calm slot of the shadow
period died at 10:00 ET with no `slot_observed` row at all.

Each mutation re-runs pytest in a FRESH subprocess: an in-process run keeps exercising the
cached pre-mutation module, which is how a harness comes to report detections it never made.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")

TEST = "scratch/test_track1_stage5q3_live_frame_splice_20260824.py"


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
    source_path = Path("global_index/track1_live_source.py")
    source_orig = source_path.read_text(encoding="utf-8")
    runner_path = Path("global_index/run_live_day_track1.py")
    runner_orig = runner_path.read_text(encoding="utf-8")
    acc_path = Path("global_index/track1_shadow_acceptance.py")
    acc_orig = acc_path.read_text(encoding="utf-8")
    guard_path = Path("global_index/track1_live_frame.py")
    guard_orig = guard_path.read_text(encoding="utf-8")

    def write(path, text):
        return lambda: path.write_text(text, encoding="utf-8")

    def sub(orig, old, new, tag):
        out = orig.replace(old, new)
        if out == orig:
            raise SystemExit(f"{tag} mutation did not apply; the target moved")
        return out

    # M1 — the projection is removed and the wide frame goes straight to the guard. This is
    # the code that was on disk at 10:00 ET this morning, and it is what killed the slot.
    results.append(mutate(
        "M1 the live half is spliced without being projected",
        write(source_path, sub(
            source_orig,
            "    aligned, dropped = project_to_frozen_columns(inst, aligned, frozen)",
            "    dropped = ()", "M1")),
        write(source_path, source_orig),
        f"{TEST}::test_a_feed_with_the_ibkr_extras_now_splices"))

    # M2 — the projection runs but AFTER the join, which is the tempting shape and the wrong
    # one: `concat` has already made the NaN holes by the time anything is dropped.
    results.append(mutate(
        "M2 the projection is applied after the concat instead of before",
        write(source_path, sub(
            source_orig,
            "    aligned, dropped = project_to_frozen_columns(inst, aligned, frozen)\n"
            "    _refuse_bars_from_the_future(inst, aligned, through)\n"
            "    checked = _refuse_overlap_disagreement(inst, aligned, frozen)\n"
            "    frame, report = guard.splice(frozen, aligned)",
            "    dropped = ()\n"
            "    _refuse_bars_from_the_future(inst, aligned, through)\n"
            "    checked = _refuse_overlap_disagreement(inst, aligned, frozen)\n"
            "    frame = pd.concat([frozen, aligned[pd.DatetimeIndex(aligned.index) > "
            "pd.DatetimeIndex(frozen.index)[-1]]]) if aligned is not None else frozen\n"
            "    report = guard.SpliceReport(guard.OK, len(frozen), 0, 0)",
            "M2")),
        write(source_path, source_orig),
        f"{TEST}::test_the_joined_ohlcv_has_no_nan_holes"))

    # M3 — a frozen column the live half does not have is filled in rather than refused.
    results.append(mutate(
        "M3 a missing frozen column is filled instead of refused",
        write(source_path, sub(
            source_orig, "    if missing:", "    if False:", "M3")),
        write(source_path, source_orig),
        f"{TEST}::test_a_missing_frozen_column_is_refused_never_filled"))

    # M4 — a NaN the provider actually sent travels into the join.
    results.append(mutate(
        "M4 a NaN in a frozen column is allowed through",
        write(source_path, sub(
            source_orig, "    bad = [c for c in want if out[c].isna().any()]",
            "    bad = []", "M4")),
        write(source_path, source_orig),
        f"{TEST}::test_a_nan_in_a_frozen_column_is_refused"))

    # M5 — the dropped names stop travelling, so a feed that changes shape does so invisibly.
    results.append(mutate(
        "M5 the dropped column names are not reported",
        write(source_path, sub(
            source_orig, "    dropped = tuple(c for c in have if c not in want)",
            "    dropped = ()", "M5")),
        write(source_path, source_orig),
        f"{TEST}::test_extra_provider_columns_are_dropped_and_named"))

    # M6 — the guard is relaxed instead of the caller projecting. The alternative design,
    # rejected: it lets a caller that forgot to project get a WIDER frame back.
    results.append(mutate(
        "M6 the guard tolerates mismatched columns instead of the caller projecting",
        write(guard_path, sub(guard_orig,
                              "    if list(frozen.columns) != list(live.columns):",
                              "    if False:", "M6")),
        write(guard_path, guard_orig),
        f"{TEST}::test_the_guard_still_refuses_a_caller_that_skipped_the_projection"))

    # M7 — the SpliceRefused catch is removed. The slot dies before writing its row, which is
    # exactly what happened to TRACK1_CALM_1000 at 10:00 ET.
    results.append(mutate(
        "M7 SpliceRefused is not caught, so the slot writes no record",
        write(runner_path, sub(
            runner_orig, "    except SpliceRefused as exc:", "    except _NeverRaised as exc:",
            "M7")),
        write(runner_path, runner_orig),
        f"{TEST}::test_a_splice_refusal_is_written_as_a_named_slot_record"))

    # M8 — the refusal is recorded under the intraday gate's vocabulary, which would classify
    # `column_mismatch` as a CLOCK refusal and turn a hard failure into a WARN.
    results.append(mutate(
        "M8 a live-frame refusal is filed as a gate refusal",
        write(runner_path, sub(
            runner_orig,
            "        reason, detail, decided = (LIVE_FRAME_REFUSED,",
            "        reason, detail, decided = (GATE_REFUSED,", "M8")),
        write(runner_path, runner_orig),
        f"{TEST}::test_the_audit_names_the_refusal_instead_of_missing_evidence"))

    # M9 — the audit classifies a live-frame refusal as an observation rather than a hard
    # refusal, so a window nobody could join reads as a window somebody watched.
    results.append(mutate(
        "M9 the audit treats live_frame_refused as an observed no-action",
        write(acc_path, sub(
            acc_orig, '    if str(row.get("reason")) != "gate_refused":',
            '    if str(row.get("reason")) in ("live_frame_refused",):\n'
            "        return SLOT_NO_ACTION\n"
            '    if str(row.get("reason")) != "gate_refused":', "M9")),
        write(acc_path, acc_orig),
        f"{TEST}::test_a_live_frame_refusal_is_a_hard_refusal_not_an_unobserved_window"))

    # M10 — the telemetry wiring is removed again, which is the state every Track 1 slot has
    # been in since the route was built: `slot_timing/` created, variable exported, no rows.
    results.append(mutate(
        "M10 the slot stops emitting telemetry",
        write(runner_path, sub(
            runner_orig, "from global_index import slot_telemetry as _tel  # noqa: E402",
            "import global_index.slot_telemetry as _tel_unused  # noqa: E402,F401\n"
            "class _tel:  # noqa: N801 - mutation stub\n"
            "    begin = split = mark = staticmethod(lambda *a, **k: None)\n"
            "    set_outcome = emit = staticmethod(lambda *a, **k: None)", "M10")),
        write(runner_path, runner_orig),
        f"{TEST}::test_the_entry_point_actually_wires_the_telemetry"))

    # ── restores, verified by hash, not by trust ─────────────────────────────
    problems = []
    for path, orig in ((source_path, source_orig), (runner_path, runner_orig),
                       (acc_path, acc_orig), (guard_path, guard_orig)):
        now = path.read_text(encoding="utf-8")
        if hashlib.sha256(now.encode()).hexdigest() != hashlib.sha256(orig.encode()).hexdigest():
            problems.append(str(path))
    detected = sum(1 for r in results if r["detected"])
    print()
    print(f"{detected}/{len(results)} mutations detected")
    print("restores verified byte-for-byte"
          if not problems else f"RESTORE MISMATCH: {problems}")
    Path("scratch/_track1_stage5q3_mutations.json").write_text(
        json.dumps({"results": results, "detected": detected, "total": len(results),
                    "restore_mismatch": problems}, indent=2), encoding="utf-8")
    return 0 if detected == len(results) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
