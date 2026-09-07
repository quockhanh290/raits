"""Stage 5L mutation harness — break each protection in-process, confirm the right test reds.

A green suite proves nothing until each assertion has been shown to fail when the thing it
guards is removed. Nothing is written to disk: every mutation is a monkeypatch on an imported
module, reverted before the next one.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, r"d:\raits")
os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5l-mutation")

import pytest  # noqa: E402

TEST = "scratch/test_track1_stage5l_shared_preflight_20260823.py"


def run(node: str) -> int:
    logging.disable(logging.NOTSET)
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-x", f"{TEST}::{node}"]))


def mutate(label: str, apply, revert, node: str) -> dict:
    baseline = run(node)
    apply()
    try:
        mutated = run(node)
    finally:
        revert()
    restored = run(node)
    ok = baseline == 0 and mutated != 0 and restored == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: "
          f"baseline={baseline} mutated={mutated} restored={restored}")
    return {"mutation": label, "guard": node, "baseline_exit": baseline,
            "mutated_exit": mutated, "restored_exit": restored, "detected": ok}


def main() -> int:
    from global_index import run_scheduler as rs
    from global_index import track1_freshness as fresh
    from global_index import track1_slots as ts
    from monitor.backend import job_journal_reader as jjr

    results = []

    # M1 — the pre-flight stops being shared infrastructure.
    saved = dict(ts.SHARED_INFRA_JOBS)
    results.append(mutate(
        "M1 pre-flight dropped from the shared-infra table",
        lambda: ts.SHARED_INFRA_JOBS.pop("preflight", None),
        lambda: (ts.SHARED_INFRA_JOBS.clear(), ts.SHARED_INFRA_JOBS.update(saved)),
        "test_every_registered_job_is_classified[False]"))

    # M2 — the retirement set widens to swallow everything that is not Track 1. This is the
    # exact shape of the L6 accident: "delete the legacy jobs" taking the data refresh too.
    orig_bucket = ts._bucket_for
    results.append(mutate(
        "M2 retirement widened to every non-Track-1 job",
        lambda: setattr(ts, "_bucket_for",
                        lambda j: "track1" if j.startswith("track1_") else "legacy_entry"),
        lambda: setattr(ts, "_bucket_for", orig_bucket),
        "test_preflight_is_shared_infra_not_legacy_entry"))

    # M3 — the job is renamed to something clearer, and the journal silently loses it.
    orig_name = jjr._job_id_from_name
    results.append(mutate(
        "M3 job renamed so the journal no longer maps it",
        lambda: setattr(jjr, "_job_id_from_name",
                        lambda n: None if n.startswith("Pre-flight") else orig_name(n)),
        lambda: setattr(jjr, "_job_id_from_name", orig_name),
        "test_the_job_name_is_unchanged_because_the_journal_reads_it"))

    # M4 — the 13:45 boundary moves on the gate side only.
    orig_req = fresh.required_data_through
    results.append(mutate(
        "M4 freshness boundary moved off 13:45",
        lambda: setattr(fresh, "required_data_through",
                        lambda t: orig_req(t) - __import__("pandas").Timedelta(days=0)
                        if str(t)[11:16] != "13:45" else fresh.prev_business_day(t)),
        lambda: setattr(fresh, "required_data_through", orig_req),
        "test_the_boundary_is_exactly_1345_and_not_a_minute_either_side"))

    # M5 — the pre-flight body stops writing the record it is the sole writer of.
    orig_save = rs._save_preflight_state
    results.append(mutate(
        "M5 pre-flight stops recording success",
        lambda: setattr(rs, "_save_preflight_state", lambda: None),
        lambda: setattr(rs, "_save_preflight_state", orig_save),
        "test_the_preflight_body_still_runs_the_same_two_updates_and_writes_the_record"))

    # M6 — a new job appears that no classification rule covers.
    orig_ids = ts.scheduler_slot_ids
    results.append(mutate(
        "M6 an unclassified job joins the schedule",
        lambda: setattr(ts, "scheduler_slot_ids",
                        lambda *a, **k: orig_ids(*a, **k) | {"premarket_refresh_0900"}),
        lambda: setattr(ts, "scheduler_slot_ids", orig_ids),
        "test_every_registered_job_is_classified"))

    # M7 — the redirect a probe uses stops working and the body writes to the operator's
    # state file after all. The production paths are swapped for temp copies FIRST, so the
    # mutation cannot touch the real files even while it is proving the guard reds.
    import json as _json
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.mkdtemp())
    fake_pf, fake_mh = tmp / "preflight_state.json", tmp / "maxhold_state.json"
    fake_pf.write_text(_json.dumps({"2026-08-21": True}), encoding="utf-8")
    fake_mh.write_text(_json.dumps({"2026-08-21": True}), encoding="utf-8")
    real_pf, real_mh = rs._PREFLIGHT_STATE, rs._MAXHOLD_STATE
    rs._PREFLIGHT_STATE, rs._MAXHOLD_STATE = fake_pf, fake_mh
    orig_save_pf = rs._save_preflight_state

    def _ignores_the_redirect():
        fake_pf.write_text(_json.dumps(dict(rs._preflight_ok)), encoding="utf-8")

    try:
        results.append(mutate(
            "M7 a fired job body writes past the redirect into the guarded file",
            lambda: setattr(rs, "_save_preflight_state", _ignores_the_redirect),
            lambda: setattr(rs, "_save_preflight_state", orig_save_pf),
            "test_firing_the_preflight_body_never_touches_the_operator_s_state_files"))
    finally:
        rs._PREFLIGHT_STATE, rs._MAXHOLD_STATE = real_pf, real_mh

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")
    import json
    from pathlib import Path
    Path("scratch/_stage5l_mutations.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8")
    return 0 if detected == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
