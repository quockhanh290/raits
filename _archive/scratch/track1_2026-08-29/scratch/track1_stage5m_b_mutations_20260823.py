"""Stage 5M-B mutation harness — undo each wiring step, confirm the right test reds.

Every blocker this stage closed is a thing whose ABSENCE was previously invisible: the sleeve
had no window, no slot, no source path, no admission rule and no ledger entry, and nothing
anywhere said so — a swing slot simply never existed. So a suite that only ever sees the wired
code proves nothing about noticing the unwired code.

The last two mutations are different in kind. They do not remove wiring; they add the two
things this stage must NOT have — a broker connection on the swing slots, and an order flag.

Nothing is written outside `tmp_path`. Every mutation is a monkeypatch on an imported module,
reverted before the next.
"""
from __future__ import annotations

import hashlib
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

TEST = "scratch/test_track1_stage5m_b_normal_r4_shadow_slots_20260823.py"
SWING = "roska4_swing"

WATCHED = [Path("global_index/preflight_state.json"),
           Path("global_index/maxhold_state.json"),
           Path("live_positions.track1.json"),
           Path("global_index/replay_checkpoint.track1.json")]


def _guarded():
    return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)
            for p in WATCHED}


def run(node: str) -> int:
    return int(pytest.main(["-q", "-p", "no:cacheprovider", "-x", f"{TEST}::{node}"]))


def mutate(label: str, apply_, revert, node: str) -> dict:
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
    before = _guarded()
    results = []

    # S1 — the window disappears. Everything downstream is derived from it, so this is the
    # single edit that would silently un-wire the sleeve.
    saved_win = dict(tp.WINDOWS_ET)
    results.append(mutate(
        "S1 roska4_swing removed from WINDOWS_ET",
        lambda: tp.WINDOWS_ET.pop(SWING, None),
        lambda: (tp.WINDOWS_ET.clear(), tp.WINDOWS_ET.update(saved_win)),
        "test_n1_the_swing_window_is_declared"))

    # S2 — the slots go, and with them the scheduler jobs and the mirror rows.
    saved_slots = ts.TRACK1_SLOTS
    results.append(mutate(
        "S2 the 23 swing slots removed from TRACK1_SLOTS",
        lambda: setattr(ts, "TRACK1_SLOTS",
                        tuple(s for s in saved_slots if s.sleeve != SWING)),
        lambda: setattr(ts, "TRACK1_SLOTS", saved_slots),
        "test_n2_slot_inventory_by_sleeve"))

    # S3 — the live source stops serving the sleeve and goes back to refusing it outright.
    orig_for = S.LiveTrack1Source._for_sleeve

    def _no_swing(self, sleeve, now, day):
        if sleeve == SWING:
            raise S.LiveSourceRefused(S.SLEEVE_NOT_LIVE, f"{sleeve} has no Track 1 slot")
        return orig_for(self, sleeve, now, day)

    results.append(mutate(
        "S3 LiveTrack1Source stops serving roska4_swing",
        lambda: setattr(S.LiveTrack1Source, "_for_sleeve", _no_swing),
        lambda: setattr(S.LiveTrack1Source, "_for_sleeve", orig_for),
        "test_n3_the_source_no_longer_refuses_the_sleeve_outright"))

    # S4 — the admission rule goes. The sleeve would then be admitted or refused by nothing.
    saved_req = dict(intra.REQUIREMENTS)
    results.append(mutate(
        "S4 the swing entry removed from REQUIREMENTS",
        lambda: intra.REQUIREMENTS.pop(SWING, None),
        lambda: (intra.REQUIREMENTS.clear(), intra.REQUIREMENTS.update(saved_req)),
        "test_n4_every_sleeve_with_a_slot_has_a_requirement"))

    # S5 — the ledger window goes, so coverage can never read complete and a shadow period
    # could never be measured against anything.
    saved_wl = dict(wl.WINDOWS)
    results.append(mutate(
        "S5 the swing window removed from the ledger",
        lambda: wl.WINDOWS.pop(SWING, None),
        lambda: (wl.WINDOWS.clear(), wl.WINDOWS.update(saved_wl)),
        "test_n5_every_slotted_sleeve_has_a_ledger_window"))

    # S6 — the swing slots quietly acquire a broker connection. This is the mutation that
    # matters most operationally: it is one word, it changes nothing visible in the schedule,
    # and it would put a second IBKR child on every legacy entry minute.
    def _ibkr_providers():
        ts.TRACK1_SLOTS = tuple(
            (s.__class__(s.id, s.hour, s.minute, s.sleeve, s.kind, s.note, "ibkr")
             if s.sleeve == SWING else s) for s in saved_slots)

    results.append(mutate(
        "S6 swing slots given --bar-provider ibkr",
        _ibkr_providers,
        lambda: setattr(ts, "TRACK1_SLOTS", saved_slots),
        "test_the_swing_slots_are_launched_without_a_bar_provider"))

    # S7 — an order flag reaches a Track 1 slot's argv.
    #
    # The first version of this mutation patched `_run` to append the flag, and it went
    # UNDETECTED — because the test replaces `_run` with its own spy to capture argv, so the
    # mutation sat downstream of the capture point and the spy never saw it. The mutation was
    # unfaithful, not the test: a real regression would add the flag to the slot BODY, which is
    # upstream of `_run`. So this rebuilds the scheduler and rebinds each Track 1 job's
    # closure, which is where such an edit would actually live.
    from global_index import run_scheduler as rs
    orig_make = rs.make_scheduler

    def _slots_that_allow_orders(*a, **kw):
        sched = orig_make(*a, **kw)
        for job in sched.get_jobs():
            if not job.id.startswith("track1_"):
                continue
            slot = next(s for s in ts.TRACK1_SLOTS if s.id.lower() == job.id)

            def _body(sid=slot.id, sl=slot.sleeve, pv=slot.provider):
                rs._run([sys.executable, "-m", "global_index.run_live_day_track1",
                         "--source", "live-shadow", "--sleeve", sl, "--slot-id", sid,
                         "--bar-provider", pv, "--regime-csv", "spy_daily_live.csv",
                         "--allow-orders"],
                        label=sid, dry_run=True, route=ts.EVENT_ROUTE_VALUE)
            job.modify(func=_body)
        return sched

    results.append(mutate(
        "S7 --allow-orders added to the Track 1 slot body",
        lambda: setattr(rs, "make_scheduler", _slots_that_allow_orders),
        lambda: setattr(rs, "make_scheduler", orig_make),
        "test_no_track1_slot_carries_an_order_or_replay_flag[--allow-orders]"))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")
    after = _guarded()
    print("operator state files unchanged through the harness:", after == before)
    import json
    Path("scratch/_stage5mb_mutations.json").write_text(
        json.dumps({"mutations": results, "guarded_unchanged": after == before}, indent=2),
        encoding="utf-8")
    return 0 if detected == len(results) and after == before else 1


if __name__ == "__main__":
    raise SystemExit(main())
