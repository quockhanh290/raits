"""Stage 5N mutation harness — un-wire the NKD sleeve one way at a time.

Same discipline as 5M-B/C/D: each protection is shown to go red when the thing it guards is
removed, and a mutation that a test's own fixture erases is rewritten rather than the test
weakened. Two mutations edit production files on disk (the guards parse source or reload
modules); both are hash-verified restored.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from global_index import track1_intraday as intra   # noqa: E402
from global_index import track1_live_source as S    # noqa: E402
from global_index import track1_params as tp        # noqa: E402
from global_index import track1_slots as ts         # noqa: E402
from global_index import window_ledger as wl        # noqa: E402

TEST = "scratch/test_track1_stage5n_nkd_track1_ownership_20260824.py"
NKD = "global_nkd"


def run(node: str) -> int:
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-x", f"{TEST}::{node}"]))


def mutate(label, apply_, revert, node) -> dict:
    baseline = run(node)
    apply_()
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
    results = []

    # M1 — the NKD slots vanish from the table.
    saved_slots = ts.TRACK1_SLOTS
    results.append(mutate(
        "M1 the 22 NKD slots removed",
        lambda: setattr(ts, "TRACK1_SLOTS",
                        tuple(s for s in saved_slots if s.sleeve != NKD)),
        lambda: setattr(ts, "TRACK1_SLOTS", saved_slots),
        "test_the_window_is_declared_and_mirrors_the_legacy_cadence"))

    # M2 — the window (and with it the derived parser choices and sleeves_at) vanishes.
    # On DISK: the parser test runs the entry point as a subprocess, which reads source.
    params = Path("global_index/track1_params.py")
    p_orig = params.read_text(encoding="utf-8")
    p_cut = p_orig.replace('    "global_nkd":    ("01:10", "02:55"),\n', "")
    assert p_cut != p_orig
    results.append(mutate(
        "M2 the NKD window removed (parser choices lose the sleeve)",
        lambda: params.write_text(p_cut, encoding="utf-8"),
        lambda: params.write_text(p_orig, encoding="utf-8"),
        "test_the_parser_accepts_the_sleeve"))

    # M3 — the source path is un-wired and the sleeve is refused outright again.
    orig_for = S.LiveTrack1Source._for_sleeve

    def _no_nkd(self, sleeve, now, day):
        if sleeve == NKD:
            raise S.LiveSourceRefused(S.SLEEVE_NOT_LIVE, f"{sleeve} has no Track 1 slot")
        return orig_for(self, sleeve, now, day)

    results.append(mutate(
        "M3 the live source stops serving global_nkd",
        lambda: setattr(S.LiveTrack1Source, "_for_sleeve", _no_nkd),
        lambda: setattr(S.LiveTrack1Source, "_for_sleeve", orig_for),
        "test_a_candidate_is_produced_from_a_tokyo_frame"))

    # M4 — the ledger window goes, so coverage can never be judged.
    saved_wl = dict(wl.WINDOWS)
    results.append(mutate(
        "M4 the NKD ledger window removed",
        lambda: wl.WINDOWS.pop(NKD, None),
        lambda: (wl.WINDOWS.clear(), wl.WINDOWS.update(saved_wl)),
        "test_ledger_expected_slots_matches_the_registered_slots"))

    # M5 — the legacy NKD jobs survive into track1-only.
    orig_cand = ts.legacy_retirement_candidates
    results.append(mutate(
        "M5 legacy nkd_night jobs registered in track1-only",
        lambda: setattr(ts, "legacy_retirement_candidates",
                        lambda *a, **k: {i for i in orig_cand(*a, **k)
                                         if not i.startswith("nkd_night")}),
        lambda: setattr(ts, "legacy_retirement_candidates", orig_cand),
        "test_legacy_nkd_jobs_absent_in_track1_only_present_in_transitional"))

    # M6 — an order flag reaches an NKD slot body. Rebind the job closures, upstream of the
    # capture point — the lesson S7 taught in 5M-B.
    from global_index import run_scheduler as rs
    orig_make = rs.make_scheduler

    def _orders(*a, **kw):
        sched = orig_make(*a, **kw)
        for job in sched.get_jobs():
            if not job.id.startswith("track1_nkd"):
                continue
            slot = next(s for s in ts.TRACK1_SLOTS if s.id.lower() == job.id)

            def _body(sid=slot.id, sl=slot.sleeve):
                rs._run([sys.executable, "-m", "global_index.run_live_day_track1",
                         "--source", "live-shadow", "--sleeve", sl, "--slot-id", sid,
                         "--bar-provider", "ibkr", "--regime-csv", "spy_daily_live.csv",
                         "--allow-orders"],
                        label=sid, dry_run=True, route=ts.EVENT_ROUTE_VALUE)
            job.modify(func=_body)
        return sched

    results.append(mutate(
        "M6 --allow-orders added to the NKD slot body",
        lambda: setattr(rs, "make_scheduler", _orders),
        lambda: setattr(rs, "make_scheduler", orig_make),
        "test_nkd_slot_argv_in_track1_only"))

    # M7 — a stale hardcoded count. The ops count function returns yesterday's 48.
    from monitor import ops
    orig_count = ops.track1_slot_count
    results.append(mutate(
        "M7 ops slot count hardcoded to the previous stage's 48",
        lambda: setattr(ops, "track1_slot_count", lambda: 48),
        lambda: setattr(ops, "track1_slot_count", orig_count),
        "test_ops_count_is_derived_and_covers_the_new_sleeve"))

    # M8 — the NKD decision grows a dependency on legacy's book. On DISK: the guard parses
    # the function's source, so an in-process patch would be invisible to it.
    src_path = Path("global_index/track1_live_source.py")
    s_orig = src_path.read_text(encoding="utf-8")
    s_dep = s_orig.replace(
        "        labels = self._label_map()\n        if not labels:",
        '        _legacy_book = Path("live_positions.json")  # mutation M8\n'
        "        labels = self._label_map()\n        if not labels:",
        1)
    assert s_dep != s_orig
    results.append(mutate(
        "M8 the NKD decision path names the legacy positions file",
        lambda: src_path.write_text(s_dep, encoding="utf-8"),
        lambda: src_path.write_text(s_orig, encoding="utf-8"),
        "test_nkd_decisions_never_read_the_legacy_book"))

    # M9 — the window gate goes back to judging NKD stamps as ET wall text. The regression
    # this stage actually hit, kept from returning.
    from global_index import track1_signal_layer as T
    orig_hhmm = T._hhmm_on
    results.append(mutate(
        "M9 the gate reads the Tokyo stamp as bare wall text again",
        lambda: setattr(T, "_hhmm_on",
                        lambda ts_, clock: f"{pd_ts(ts_).hour:02d}:{pd_ts(ts_).minute:02d}"),
        lambda: setattr(T, "_hhmm_on", orig_hhmm),
        "test_an_aware_stamp_is_an_instant_not_a_wall_text"))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")
    ok_restore = (params.read_text(encoding="utf-8") == p_orig
                  and src_path.read_text(encoding="utf-8") == s_orig)
    print("production files restored byte-for-byte:", ok_restore)
    Path("scratch/_stage5n_mutations.json").write_text(
        json.dumps({"mutations": results, "files_restored": ok_restore}, indent=2),
        encoding="utf-8")
    return 0 if detected == len(results) and ok_restore else 1


def pd_ts(x):
    import pandas as pd
    return pd.Timestamp(x)


if __name__ == "__main__":
    raise SystemExit(main())
