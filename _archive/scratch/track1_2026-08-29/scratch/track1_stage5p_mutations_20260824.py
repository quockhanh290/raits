"""Stage 5P mutation harness — collapse each readiness guarantee, confirm the right test reds.

On-disk mutations run pytest in a fresh subprocess (the 5O lesson: an in-process run keeps
exercising the cached pre-mutation module); in-process monkeypatch mutations use pytest.main
(a subprocess would never see them). Production files edited on disk are hash-verified
restored.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from global_index import track1_shadow_acceptance as acc  # noqa: E402
from global_index import track1_slots as ts               # noqa: E402
from global_index import track1_params as tp              # noqa: E402

TEST = "scratch/test_track1_stage5p_full_shadow_readiness_20260824.py"


def run_sub(node: str) -> int:
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-x", f"{TEST}::{node}"],
                       capture_output=True, text=True, cwd="d:/raits", timeout=600)
    return r.returncode


def run_inproc(node: str) -> int:
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-x", f"{TEST}::{node}"]))


def mutate(label, apply_, revert, node, *, inproc=False) -> dict:
    runner = run_inproc if inproc else run_sub
    baseline = runner(node)
    apply_()
    try:
        mutated = runner(node)
    finally:
        revert()
    restored = runner(node)
    ok = baseline == 0 and mutated != 0 and restored == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: "
          f"baseline={baseline} mutated={mutated} restored={restored}")
    return {"mutation": label, "guard": node, "baseline_exit": baseline,
            "mutated_exit": mutated, "restored_exit": restored, "detected": ok}


def main() -> int:
    results = []
    reader_path = Path("monitor/backend/track1_runtime_reader.py")
    reader_orig = reader_path.read_text(encoding="utf-8")
    acc_path = Path("global_index/track1_shadow_acceptance.py")
    acc_orig = acc_path.read_text(encoding="utf-8")

    # P1 — the dashboard reads legacy's book as Track 1. On disk; the guard parses source.
    p1 = reader_orig.replace('BOOK_PATH = "live_positions.track1.json"',
                             'BOOK_PATH = "live_positions.json"')
    assert p1 != reader_orig
    results.append(mutate(
        "P1 the Track 1 reader opens live_positions.json",
        lambda: reader_path.write_text(p1, encoding="utf-8"),
        lambda: reader_path.write_text(reader_orig, encoding="utf-8"),
        "test_the_reader_never_opens_the_legacy_book"))

    # P2 — coverage silently omits one sleeve from judgment.
    saved_win = dict(tp.WINDOWS_ET)
    results.append(mutate(
        "P2 the gate stops judging one sleeve's coverage",
        lambda: tp.WINDOWS_ET.pop("global_nkd", None),
        lambda: (tp.WINDOWS_ET.clear(), tp.WINDOWS_ET.update(saved_win)),
        "test_the_gate_judges_all_four_sleeves", inproc=True))

    # P3 — the checkpoint path reverts to legacy's file. The green-day test cannot catch
    # this: its fixture builds the checkpoint at the SAME constant the gate reads, so the
    # mutation moves fixture and judge together and the day stays green — measured on the
    # first run of this harness (0/0/0). The guard that genuinely pins the path is the
    # cross-module equality with the dashboard reader, which the mutation does NOT move.
    results.append(mutate(
        "P3 the gate reads legacy's replay_checkpoint.json",
        lambda: setattr(acc, "CHECKPOINT_PATH", "global_index/replay_checkpoint.json"),
        lambda: setattr(acc, "CHECKPOINT_PATH",
                        "global_index/replay_checkpoint.track1.json"),
        "test_the_reader_and_the_gate_read_the_same_paths", inproc=True))

    # P4 — the safety path reverts to legacy's book.
    orig_pos = ts.TRACK1_POSITIONS_PATH
    results.append(mutate(
        "P4 Track 1 safety points at legacy's book",
        lambda: setattr(ts, "TRACK1_POSITIONS_PATH", "live_positions.json"),
        lambda: setattr(ts, "TRACK1_POSITIONS_PATH", orig_pos),
        "test_a_fully_green_day_is_accepted", inproc=True))

    # P5 — a legacy strategy job survives track1-only.
    orig_cand = ts.legacy_retirement_candidates
    results.append(mutate(
        "P5 a legacy strategy job survives track1-only",
        lambda: setattr(ts, "legacy_retirement_candidates",
                        lambda *a, **k: orig_cand(*a, **k) - {"live_day"}),
        lambda: setattr(ts, "legacy_retirement_candidates", orig_cand),
        "test_the_full_inventory_in_all_three_modes", inproc=True))

    # P6 — a hardcoded count returns: the safety table shrinks and the inventory pins catch it.
    orig_jobs = ts.track1_safety_jobs
    results.append(mutate(
        "P6 the safety job table loses a job (count drift)",
        lambda: setattr(ts, "track1_safety_jobs", lambda: orig_jobs()[:-1]),
        lambda: setattr(ts, "track1_safety_jobs", orig_jobs),
        "test_the_full_inventory_in_all_three_modes", inproc=True))

    # P7 — an order flag appears on a Track 1 strategy slot body.
    from global_index import run_scheduler as rs
    orig_make = rs.make_scheduler

    def _orders(*a, **kw):
        sched = orig_make(*a, **kw)
        strategy_ids = {s.id.lower() for s in ts.TRACK1_SLOTS}
        for job in sched.get_jobs():
            if job.id not in strategy_ids:
                continue
            slot = next(s for s in ts.TRACK1_SLOTS if s.id.lower() == job.id)

            def _body(sid=slot.id, sl=slot.sleeve):
                rs._run([sys.executable, "-m", "global_index.run_live_day_track1",
                         "--source", "live-shadow", "--sleeve", sl, "--slot-id", sid,
                         "--bar-provider", "ibkr", "--regime-csv", "spy_daily_live.csv",
                         "--allow-orders"],
                        label=sid, dry_run=True, route=ts.EVENT_ROUTE_VALUE)
            job.modify(func=_body)
            break                                      # one is enough to be caught
        return sched

    results.append(mutate(
        "P7 --allow-orders on a Track 1 strategy slot",
        lambda: setattr(rs, "make_scheduler", _orders),
        lambda: setattr(rs, "make_scheduler", orig_make),
        "test_every_track1_child_argv_and_env_in_track1_only", inproc=True))

    # P8 — the runtime paths point back into scratch, where cleanup deletes evidence.
    p8 = acc_orig.replace(
        'COVERAGE_DIR = "global_index/track1_runtime/window_coverage"',
        'COVERAGE_DIR = "scratch/track1_shadow/window_coverage"')
    assert p8 != acc_orig
    results.append(mutate(
        "P8 the gate's coverage path points into scratch",
        lambda: acc_path.write_text(p8, encoding="utf-8"),
        lambda: acc_path.write_text(acc_orig, encoding="utf-8"),
        "test_the_reader_paths_point_at_the_durable_runtime_not_scratch"))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")
    ok_restore = (reader_path.read_text(encoding="utf-8") == reader_orig
                  and acc_path.read_text(encoding="utf-8") == acc_orig)
    print("production files restored byte-for-byte:", ok_restore)
    Path("scratch/_stage5p_mutations.json").write_text(
        json.dumps({"mutations": results, "files_restored": ok_restore}, indent=2),
        encoding="utf-8")
    return 0 if detected == len(results) and ok_restore else 1


if __name__ == "__main__":
    raise SystemExit(main())
