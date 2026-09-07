"""Stage 5Q-1 mutation harness — break each new semantic guard, confirm the right test reds.

Run:

    python scratch/track1_stage5q1_mutations_20260824.py

Nothing here starts a scheduler, restarts a backend, connects to a broker or touches live
state. Production files edited on disk are restored and hash-verified byte-for-byte before the
harness exits.

Stage 5Q-1 relaxed one thing — a window is now complete when every slot LOOKED, not only when
every slot DECIDED — and every mutation below asks the same question about that relaxation:
**can it still say no?** A loosened rule that has never been observed refusing is not a rule.

Every mutation re-runs pytest in a FRESH subprocess: an in-process run keeps exercising the
cached pre-mutation module, which is how a mutation harness comes to report detections it
never made.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")

TEST = "scratch/test_track1_stage5q1_audit_semantics_20260824.py"


def run_sub(node: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-x", f"{TEST}::{node}"],
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
    acc_path = Path("global_index/track1_shadow_acceptance.py")
    acc_orig = acc_path.read_text(encoding="utf-8")
    reader_path = Path("monitor/backend/track1_runtime_reader.py")
    reader_orig = reader_path.read_text(encoding="utf-8")

    def write(path, text):
        return lambda: path.write_text(text, encoding="utf-8")

    def sub(orig, old, new, tag):
        out = orig.replace(old, new)
        if out == orig:
            raise SystemExit(f"{tag} mutation did not apply; the target moved")
        return out

    # R1 — the relaxation goes too far: a slot that could NOT evaluate is counted as having
    # observed. This is the whole risk of 5Q-1 in one line.
    #
    # It breaks the reported `observed` COUNT, not a verdict branch — the verdict fails on
    # `hard_refusal_slot_ids` independently. That is worth knowing rather than papering over
    # with a second rule for one thing: `OBSERVED_CLASSES` is what the record means by
    # "somebody looked", and the guard is a test that reads that number.
    results.append(mutate(
        "R1 a hard refusal counts as an observation",
        write(acc_path, sub(
            acc_orig,
            "OBSERVED_CLASSES = frozenset({SLOT_DECISION, SLOT_NO_ACTION, SLOT_WINDOW_SHUT})",
            "OBSERVED_CLASSES = frozenset({SLOT_DECISION, SLOT_NO_ACTION, SLOT_WINDOW_SHUT,\n"
            "                              SLOT_HARD_REFUSAL})", "R1")),
        write(acc_path, acc_orig),
        "test_a_window_that_could_not_evaluate_fails[no_bar_provider]"))

    # R2 — no_bar_provider stops failing the window. The prompt's own worked example.
    results.append(mutate(
        "R2 the audit stops failing a window that could not evaluate",
        write(acc_path, sub(acc_orig, '        if obs["hard_refusal_slot_ids"]:',
                            "        if False:", "R2")),
        write(acc_path, acc_orig),
        "test_a_window_that_could_not_evaluate_fails[live_source_not_ready]"))

    # R3 — every gate refusal is treated as "the window was shut", so a STALE frame reads as
    # a designed no-action. The clock codes are the whole distinction.
    results.append(mutate(
        "R3 any gate refusal counts as the decision band being shut",
        write(acc_path, sub(
            acc_orig,
            "    if codes and all(c in clock_refusal_codes() for c in codes):",
            "    if True:", "R3")),
        write(acc_path, acc_orig),
        "test_a_window_that_could_not_evaluate_fails[gate_stale]"))

    # R4 — a blank gate_refused detail is read charitably instead of failing closed.
    results.append(mutate(
        "R4 an unreadable gate refusal is read as a window-shut",
        write(acc_path, sub(acc_orig, "    if not isinstance(row, dict):\n"
                                      "        return SLOT_HARD_REFUSAL",
                            "    if not isinstance(row, dict):\n"
                            "        return SLOT_WINDOW_SHUT", "R4")),
        write(acc_path, acc_orig),
        "test_an_unreadable_row_is_a_hard_refusal_not_an_observation"))

    # R5 — freshness_refused is quietly reclassified as a designed no-action. It is not: it
    # fires only when the engine ADMITTED a candidate while the daily inputs were refused.
    #
    # The first form of R5 added "freshness_refused" to the reason test and was UNFAITHFUL:
    # such a row carries prose in `detail`, so it fell through the code check to HARD anyway
    # and the mutation changed nothing (0/0/0). The faithful form reclassifies it outright.
    results.append(mutate(
        "R5 freshness_refused is treated as a valid no-action",
        write(acc_path, sub(
            acc_orig, '    if str(row.get("reason")) != "gate_refused":',
            '    if str(row.get("reason")) == "freshness_refused":\n'
            '        return SLOT_WINDOW_SHUT\n'
            '    if str(row.get("reason")) != "gate_refused":',
            "R5")),
        write(acc_path, acc_orig),
        "test_a_window_that_could_not_evaluate_fails[freshness_refused]"))

    # R6 — the slot-id guard is dropped and only the count is judged. The doubled slot keeps
    # the count at 24 while one slot never fired.
    results.append(mutate(
        "R6 slot IDS stop being checked and the count is trusted",
        write(acc_path, sub(
            acc_orig,
            '        "missing_slot_ids": [s for s in registered if classes[s] == SLOT_UNOBSERVED],',
            '        "missing_slot_ids": [],', "R6")),
        write(acc_path, acc_orig),
        "test_a_missing_slot_id_fails_even_though_a_duplicate_keeps_the_count"))

    # R7 — a duplicate row silently fills the gap left by a missing one.
    results.append(mutate(
        "R7 a duplicate slot id compensates for a missing one",
        write(acc_path, sub(
            acc_orig,
            '        cls = classify_slot_row(got[-1]) if got else SLOT_UNOBSERVED',
            '        cls = classify_slot_row(got[-1]) if got else (\n'
            '            classify_slot_row(list(by_id.values())[0][-1]) if by_id\n'
            '            else SLOT_UNOBSERVED)', "R7")),
        write(acc_path, acc_orig),
        "test_a_missing_slot_id_fails_even_though_a_duplicate_keeps_the_count"))

    # R8 — a slot that ran without being measured stops failing. The p95 gate cannot judge a
    # slot it never saw.
    results.append(mutate(
        "R8 a ledger row with no timing record is ignored",
        write(acc_path, sub(acc_orig, "        if slots_without_timing:",
                            "        if False:", "R8")),
        write(acc_path, acc_orig),
        "test_a_slot_with_a_ledger_row_and_no_timing_fails"))

    # R9 — a crash or a mutex skip stops failing: telemetry exists, no ledger row does.
    results.append(mutate(
        "R9 a timing record with no ledger row is ignored",
        write(acc_path, sub(acc_orig, "        if timing_without_row:",
                            "        if False:", "R9")),
        write(acc_path, acc_orig),
        "test_a_slot_with_timing_and_no_ledger_row_fails"))

    # R10 — the gate goes back to the flat explanation path nothing writes. Re-aimed in
    # Stage 5Q-2: the layout moved into `track1_explain`, and the harness FAILED LOUDLY on the
    # vanished target rather than reporting a detection it had not made. The mutation now
    # breaks the delegation, which is where the acceptance module's half of the bug lived.
    results.append(mutate(
        "R10 the gate reads the flat explanation path nothing writes",
        write(acc_path, sub(
            acc_orig,
            "    return tx.explanation_files(root, day_compact, out_dir=SHADOW_DIR)",
            "    return [q for q in [Path(root) / SHADOW_DIR / 'explanations' "
            "/ ('explanations_%s.jsonl' % day_compact)] if q.exists()]",
            "R10")),
        write(acc_path, acc_orig),
        "test_the_gate_finds_rows_written_by_the_REAL_writer"))

    # R11 — a sleeve whose rows a later sleeve overwrote is charged with the gap instead of
    # the writer. A false FAIL every day the route sees a candidate before 15:55.
    results.append(mutate(
        "R11 a sleeve is failed for rows a later sleeve overwrote",
        write(acc_path, sub(acc_orig, "        elif expected_expl > 0 and not erows:",
                            "        elif False:", "R11")),
        write(acc_path, acc_orig),
        "test_a_sleeve_whose_rows_a_later_sleeve_overwrote_is_named_not_failed"))

    # R12 — a legitimately quiet day is failed because the committed daily gate refused it.
    # The second thing 5Q left open, restored.
    results.append(mutate(
        "R12 the committed daily gate is enforced on the operational roll-up",
        write(acc_path, sub(
            acc_orig, "    full = evaluate_day(day, root=root)\n"
                      "    if not full[\"accepted\"]:\n"
                      "        reasons.append(R_ACCEPTANCE_GATE_REFUSED)",
            "    full = evaluate_day(day, root=root)\n"
            "    if not full[\"accepted\"]:\n"
            "        reasons.append(R_ACCEPTANCE_GATE_REFUSED)\n"
            "        judged = judged + [{\"verdict\": AUDIT_FAIL}]", "R12")),
        write(acc_path, acc_orig),
        "test_a_day_on_which_every_sleeve_found_nothing_is_not_a_failure"))

    # R13 — one unobserved sleeve stops failing the day, so a hole and a quiet day look alike.
    results.append(mutate(
        "R13 an unobserved sleeve no longer fails the day",
        write(acc_path, sub(acc_orig, "        if st[\"outcome\"] == wl.UNOBSERVED:",
                            "        if False:", "R13")),
        write(acc_path, acc_orig),
        "test_one_unobserved_sleeve_fails_the_day_even_when_the_rest_were_quiet"))

    # R14 — the dashboard reader stops sharing the acceptance module's path resolver and
    # guesses again.
    results.append(mutate(
        "R14 the dashboard reader guesses at the explanation layout again",
        write(reader_path, sub(
            reader_orig,
            '    days = sorted({f.stem.replace("explanations_", "")\n'
            '                   for f in d.rglob("explanations_*.jsonl")})',
            '    days = sorted({f.stem.replace("explanations_", "")\n'
            '                   for f in d.glob("explanations_*.jsonl")})', "R14")),
        write(reader_path, reader_orig),
        "test_the_dashboard_reader_and_the_gate_agree_on_where_rows_live"))

    # R15 — a window every slot was shut out of passes silently instead of warning.
    results.append(mutate(
        "R15 a window whose decision band never opened passes without a word",
        write(acc_path, sub(
            acc_orig,
            "            if c[SLOT_WINDOW_SHUT] == obs[\"registered\"] and obs[\"registered\"]:",
            "            if False:", "R15")),
        write(acc_path, acc_orig),
        "test_a_full_window_the_decision_band_was_shut_for_warns_and_does_not_fail"))

    # ── restores, verified by hash, not by trust ─────────────────────────────
    problems = []
    for path, orig in ((acc_path, acc_orig), (reader_path, reader_orig)):
        now = path.read_text(encoding="utf-8")
        if hashlib.sha256(now.encode()).hexdigest() != hashlib.sha256(orig.encode()).hexdigest():
            problems.append(str(path))
    detected = sum(1 for r in results if r["detected"])
    print()
    print(f"{detected}/{len(results)} mutations detected")
    print("restores verified byte-for-byte"
          if not problems else f"RESTORE MISMATCH: {problems}")
    Path("scratch/_track1_stage5q1_mutations.json").write_text(
        json.dumps({"results": results, "detected": detected, "total": len(results),
                    "restore_mismatch": problems}, indent=2), encoding="utf-8")
    return 0 if detected == len(results) and not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
