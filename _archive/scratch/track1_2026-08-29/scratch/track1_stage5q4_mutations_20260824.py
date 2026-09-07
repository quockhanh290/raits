"""Stage 5Q-4 mutation harness — remove each guard, confirm the right test reds.

    python scratch/track1_stage5q4_mutations_20260824.py

Nothing here starts a scheduler, restarts a backend, connects to a broker, or writes to a real
parquet. Files edited on disk are restored and hash-verified byte-for-byte before it exits.

This stage's guards are almost all REFUSALS, and a refusal that has never been observed
refusing is a comment. The one that matters most is N1: the whole premise of 5Q-4 is that the
overlap guard is RIGHT and the stored data is wrong, so making the guard quieter would "fix"
today's symptom by deleting the only thing that noticed it.

Each mutation re-runs pytest in a FRESH subprocess.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")

TEST = "scratch/test_track1_stage5q4_overlap_and_repair_20260824.py"
TOOL = Path("scratch/track1_stage5q4_repair_boundary_bar_20260824.py")


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
    tool_orig = TOOL.read_text(encoding="utf-8")

    def write(path, text):
        return lambda: path.write_text(text, encoding="utf-8")

    def sub(orig, old, new, tag):
        out = orig.replace(old, new)
        if out == orig:
            raise SystemExit(f"{tag} mutation did not apply; the target moved")
        return out

    # N1 — the overlap guard gets a price tolerance wide enough to swallow today's 4.5 points.
    # This is the tempting "fix" and it is the one thing this stage may not do: it would make
    # the route join a frame it knows is wrong, silently, for ever.
    results.append(mutate(
        "N1 the overlap guard gains a price tolerance",
        write(source_path, sub(source_orig, "        bad = diff[diff > 1e-6]",
                               "        bad = diff[diff > 10.0]", "N1")),
        write(source_path, source_orig),
        f"{TEST}::test_refuse_overlap_disagreement_is_untouched"))

    # N2 — the guard stops raising and merely notes the disagreement.
    results.append(mutate(
        "N2 the overlap guard warns instead of refusing",
        write(source_path, sub(source_orig, "            raise LiveSourceRefused(\n"
                                            '                "overlap_disagreement",',
                               "            _ = LiveSourceRefused(\n"
                               '                "overlap_disagreement",', "N2")),
        write(source_path, source_orig),
        f"{TEST}::test_the_overlap_check_still_hard_refuses_a_real_disagreement"))

    # N3 — the repair tool stops defaulting to dry run.
    results.append(mutate(
        "N3 the repair tool applies by default",
        write(TOOL, sub(tool_orig, '    ap.add_argument("--apply", action="store_true",',
                        '    ap.add_argument("--apply", action="store_false", default=True,',
                        "N3")),
        write(TOOL, tool_orig),
        f"{TEST}::test_the_tool_defaults_to_dry_run_at_the_cli_level"))

    # N4 — the hash guard is removed, so a repair measured against one version of the file can
    # land on another.
    results.append(mutate(
        "N4 --apply no longer needs --expect to match",
        write(TOOL, sub(tool_orig, "    if expect is None or expect != before_hash:",
                        "    if False:", "N4")),
        write(TOOL, tool_orig),
        f"{TEST}::test_apply_without_the_hash_guard_refuses"))

    # N5 — the window bound is dropped, so a disagreement anywhere in eight years of history
    # becomes "a boundary repair".
    results.append(mutate(
        "N5 a disagreement outside the window is repaired anyway",
        write(TOOL, sub(tool_orig, "    if outside:", "    if False:", "N5")),
        write(TOOL, tool_orig),
        f"{TEST}::test_a_disagreement_outside_the_window_refuses_the_whole_run"))

    # N6 — the count bound is dropped.
    results.append(mutate(
        "N6 any number of disagreeing bars is repaired",
        write(TOOL, sub(tool_orig, "    if len(in_window) > max_bars:", "    if False:",
                        "N6")),
        write(TOOL, tool_orig),
        f"{TEST}::test_too_many_disagreeing_bars_refuses"))

    # N7 — the snapshot is skipped. The repo has already lost a baseline to an in-place
    # parquet write; this is that, restored.
    results.append(mutate(
        "N7 the repair writes without snapshotting first",
        write(TOOL, sub(tool_orig, "    backup.write_bytes(p.read_bytes())",
                        "    pass", "N7")),
        write(TOOL, tool_orig),
        f"{TEST}::test_apply_snapshots_repairs_one_bar_and_verifies"))

    # N8 — dry run stops being the default path and a measurement run writes.
    #
    # Its first form made the repair rewrite bars that already AGREED, and went undetected
    # (0/0/0) because writing a value that is already there changes nothing. There was no
    # guard to break: an over-broad write of agreeing values cannot corrupt anything. The
    # boundary that CAN be broken is the one between measuring and writing.
    results.append(mutate(
        "N8 a dry run falls through into the apply path",
        write(TOOL, sub(tool_orig, "    if not apply:\n        return report",
                        "    if False:\n        return report", "N8")),
        write(TOOL, tool_orig),
        f"{TEST}::test_a_dry_run_writes_nothing_and_says_what_it_would_do"))

    # N9 — the post-write verification is removed, so a repair that did not land reports
    # success. Its guard needed a test that could OBSERVE a write not landing; without one the
    # mutation was undetectable, because in every ordinary case the write does land and
    # `remaining` is empty whether or not anything checked.
    results.append(mutate(
        "N9 the repair does not verify by re-reading",
        write(TOOL, sub(tool_orig, "    after = src.frozen_frame(inst, path)\n"
                                   "    remaining = [d for d in compare(after, aligned, inst=inst)]",
                        "    remaining = []", "N9")),
        write(TOOL, tool_orig),
        f"{TEST}::test_a_repair_that_does_not_land_is_reported_as_a_failure"))

    # ── restores, verified by hash ───────────────────────────────────────────
    problems = []
    for path, orig in ((source_path, source_orig), (TOOL, tool_orig)):
        now = path.read_text(encoding="utf-8")
        if hashlib.sha256(now.encode()).hexdigest() != hashlib.sha256(orig.encode()).hexdigest():
            problems.append(str(path))
    detected = sum(1 for r in results if r["detected"])
    print()
    print(f"{detected}/{len(results)} mutations detected")
    print("restores verified byte-for-byte"
          if not problems else f"RESTORE MISMATCH: {problems}")
    Path("scratch/_track1_stage5q4_mutations.json").write_text(
        json.dumps({"results": results, "detected": detected, "total": len(results),
                    "restore_mismatch": problems}, indent=2), encoding="utf-8")
    return 0 if detected == len(results) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
