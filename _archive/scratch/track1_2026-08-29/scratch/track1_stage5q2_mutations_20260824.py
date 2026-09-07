"""Stage 5Q-2 mutation harness — restore each defect, confirm the right test reds.

Run:

    python scratch/track1_stage5q2_mutations_20260824.py

Nothing here starts a scheduler, restarts a backend, connects to a broker or touches live
state. Production files edited on disk are restored and hash-verified byte-for-byte before the
harness exits.

Every mutation below puts back something that was actually there and actually wrong. A fix
that has never been observed failing when removed is a fix nobody can tell from a coincidence.

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

TEST = "scratch/test_track1_stage5q2_explanation_integrity_20260824.py"
TEST_5Q1 = "scratch/test_track1_stage5q1_audit_semantics_20260824.py"


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
    runner_path = Path("global_index/run_live_day_track1.py")
    runner_orig = runner_path.read_text(encoding="utf-8")
    explain_path = Path("global_index/track1_explain.py")
    explain_orig = explain_path.read_text(encoding="utf-8")
    acc_path = Path("global_index/track1_shadow_acceptance.py")
    acc_orig = acc_path.read_text(encoding="utf-8")

    def write(path, text):
        return lambda: path.write_text(text, encoding="utf-8")

    def sub(orig, old, new, tag):
        out = orig.replace(old, new)
        if out == orig:
            raise SystemExit(f"{tag} mutation did not apply; the target moved")
        return out

    # S1 — the shared session-date path comes back. Every sleeve writes one file again and the
    # later slot truncates the earlier one. This is the defect exactly as it was.
    #
    # Its first form pointed at `test_two_sleeves_on_one_day_both_survive`, which drives
    # `emit_explanations` directly, and went UNDETECTED (0/0/0): the mutation edits the CALL
    # SITE in `observe_live_slot`, and a test of the writer cannot see a call site. The
    # faithful guard runs the real slot function — and the gap it exposed was in the suite,
    # not in the fix.
    results.append(mutate(
        "S1 all sleeves share one file per session date again",
        write(runner_path, sub(
            runner_orig, 'window=tx.live_window(day, sleeve, slot_id), slot_id=slot_id,',
            'window=f"live_{day}", slot_id=slot_id,', "S1")),
        write(runner_path, runner_orig),
        f"{TEST}::test_the_real_slot_path_gives_each_slot_its_own_file"))

    # S2 — the slot keeps its own directory but the sleeve level is dropped, so two sleeves
    # whose slot ids ever collided would share a file. Narrower than S1 and still wrong.
    results.append(mutate(
        "S2 the sleeve level is dropped from the layout",
        write(explain_path, sub(
            explain_orig,
            'return f"{LIVE_WINDOW_PREFIX}{session_date}/{sleeve}/{slot_id}"',
            'return f"{LIVE_WINDOW_PREFIX}{session_date}/{slot_id}"', "S2")),
        write(explain_path, explain_orig),
        f"{TEST}::test_the_path_names_the_day_the_sleeve_and_the_slot"))

    # S3 — the slot id stops travelling in the row, so a row read out of its directory has no
    # provenance.
    results.append(mutate(
        "S3 the row loses its slot_id",
        write(runner_path, sub(
            runner_orig, '"slot_id": slot_id or None},', '"slot_id": None},', "S3")),
        write(runner_path, runner_orig),
        f"{TEST}::test_the_row_carries_the_slot_id_as_well_as_the_path"))

    # S4 — a re-run of one slot appends instead of replacing, so the day holds two records for
    # one slot and no reader can tell which one it stands by.
    results.append(mutate(
        "S4 a slot re-run appends instead of replacing its own rows",
        write(runner_path, sub(
            runner_orig,
            'written.append(str(tx.write_shadow(by_date[day], session_date=day,\n'
            '                                           out_dir=target, root=root, mode="w")))',
            'written.append(str(tx.write_shadow(by_date[day], session_date=day,\n'
            '                                           out_dir=target, root=root, mode="a")))',
            "S4")),
        write(runner_path, runner_orig),
        f"{TEST}::test_rerunning_one_slot_replaces_only_its_own_rows"))

    # S5 — the freshness check falls back to the substring test over free text.
    results.append(mutate(
        "S5 the freshness proof is a substring match again",
        write(explain_path, sub(
            explain_orig,
            '    if record.get("record_type") == DECISION and not p["observed_is_bool"]:',
            '    if False:', "S5")),
        write(explain_path, explain_orig),
        f"{TEST}::test_a_row_whose_only_freshness_is_prose_fails"))

    # S6 — an accepted admission in a binding mode stops having to cite the gate that governed
    # it. The Stage 5Z contract, undone.
    results.append(mutate(
        "S6 a binding admission need not cite the freshness gate",
        write(explain_path, sub(
            explain_orig, "    owed = FRESHNESS_FEATURE in declared or binding_accept",
            "    owed = FRESHNESS_FEATURE in declared", "S6")),
        write(explain_path, explain_orig),
        f"{TEST}::test_an_accepted_binding_decision_must_cite_the_gate_and_carry_the_feature"))

    # S7 — the check stops failing closed, so a malformed row certifies itself.
    results.append(mutate(
        "S7 an unreadable row passes the freshness check",
        write(explain_path, sub(
            explain_orig, '    if record.get("record_type") not in RECORD_TYPES:',
            "    if False:", "S7")),
        write(explain_path, explain_orig),
        f"{TEST}::test_an_unreadable_row_cannot_pass_the_check"))

    # S8 — the reader goes back to a single flat path and finds nothing on any real day.
    results.append(mutate(
        "S8 the reader only looks at the flat path",
        write(explain_path, sub(
            explain_orig,
            "    out.extend(sorted(p for p in d.rglob(name) if p not in out))",
            "    pass", "S8")),
        write(explain_path, explain_orig),
        f"{TEST}::test_the_gate_and_the_dashboard_find_the_same_rows"))

    # S9 — the dashboard imports the writer directly instead of going through the gate. The
    # dependency boundary, removed.
    results.append(mutate(
        "S9 the dashboard reader reaches into the writer module",
        write(acc_path, sub(
            acc_orig, "def explanation_attribution(path, root: str | Path = \".\") -> dict:",
            "def explanation_attribution_RENAMED(path, root: str | Path = \".\") -> dict:",
            "S9")),
        write(acc_path, acc_orig),
        f"{TEST}::test_the_gate_and_the_dashboard_find_the_same_rows"))

    # S10 — the 5Q-1 guard that a duplicate slot id may never fill the gap left by a missing
    # one. Re-run here because 5Q-2 rewrote the reader those ids come from.
    results.append(mutate(
        "S10 a duplicate slot id masks a missing one",
        write(acc_path, sub(
            acc_orig,
            '        "missing_slot_ids": [s for s in registered if classes[s] == SLOT_UNOBSERVED],',
            '        "missing_slot_ids": [],', "S10")),
        write(acc_path, acc_orig),
        f"{TEST_5Q1}::test_a_missing_slot_id_fails_even_though_a_duplicate_keeps_the_count"))

    # S11 — the replay path is dragged into the live layout, which would move every committed
    # replay artefact out from under the reader that reproduces them.
    results.append(mutate(
        "S11 the replay path is migrated to the live layout",
        write(runner_path, sub(
            runner_orig,
            '    target = f"{out_dir}/{EXPLAIN_SUBDIR}/{window}"',
            '    target = f"{out_dir}/{EXPLAIN_SUBDIR}/{window}/migrated"', "S11")),
        write(runner_path, runner_orig),
        f"{TEST}::test_the_replay_path_keeps_its_flat_window_layout"))

    # S12 — the layout builder sanitises a traversing name instead of refusing it, so rows get
    # filed somewhere nobody looks.
    results.append(mutate(
        "S12 a traversing sleeve name is sanitised rather than refused",
        write(explain_path, sub(
            explain_orig,
            '        if "/" in part or "\\\\" in part or part in (".", ".."):',
            "        if False:", "S12")),
        write(explain_path, explain_orig),
        f"{TEST}::test_a_slot_cannot_write_outside_its_own_directory"))

    # ── restores, verified by hash, not by trust ─────────────────────────────
    problems = []
    for path, orig in ((runner_path, runner_orig), (explain_path, explain_orig),
                       (acc_path, acc_orig)):
        now = path.read_text(encoding="utf-8")
        if hashlib.sha256(now.encode()).hexdigest() != hashlib.sha256(orig.encode()).hexdigest():
            problems.append(str(path))
    detected = sum(1 for r in results if r["detected"])
    print()
    print(f"{detected}/{len(results)} mutations detected")
    print("restores verified byte-for-byte"
          if not problems else f"RESTORE MISMATCH: {problems}")
    Path("scratch/_track1_stage5q2_mutations.json").write_text(
        json.dumps({"results": results, "detected": detected, "total": len(results),
                    "restore_mismatch": problems}, indent=2), encoding="utf-8")
    return 0 if detected == len(results) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
