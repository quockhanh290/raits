"""Stage 5M-C mutation harness — undo each safety and confirm the right test reds.

This stage is mostly about things NOT happening: the swing slots not connecting unless asked,
a typo not being swallowed, a broker not being left open, an operator string not stating a fact
that can go stale. Every one of those passes by finding nothing, which is the shape of a check
that has quietly stopped looking.

No real IBKR. Every mutation is a monkeypatch reverted before the next, and the tests they drive
write only under tmp_path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from global_index import track1_slots as ts  # noqa: E402

TEST = "scratch/test_track1_stage5m_c_swing_provider_readiness_20260823.py"


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
    results = []

    # P1 — the staged switch is ignored and the swing slots connect regardless. One line, no
    # visible change to the schedule, and the first time a Track 1 slot shares a minute with a
    # connected legacy child.
    orig_provider_for = ts.provider_for
    results.append(mutate(
        "P1 provider_for ignores the switch and returns ibkr",
        lambda: setattr(ts, "provider_for", lambda slot: ts.PROVIDER_IBKR),
        lambda: setattr(ts, "provider_for", orig_provider_for),
        "test_the_scheduler_launches_swing_without_a_provider_by_default"))

    # P2 — a typo is swallowed instead of refused. The session then collects nothing and looks
    # exactly like a session that ran and found no setups.
    orig_swing = ts.swing_provider
    results.append(mutate(
        "P2 an unrecognised switch value falls back to none",
        lambda: setattr(ts, "swing_provider",
                        lambda: os.environ.get(ts.SWING_PROVIDER_ENV) or ts.PROVIDER_NONE),
        lambda: setattr(ts, "swing_provider", orig_swing),
        "test_an_unrecognised_value_is_refused_rather_than_falling_back[IBKR]"))

    # P3 — the switch reaches Calm and Stress too, so one export turns off the two sleeves that
    # have been collecting since Stage 5I.
    results.append(mutate(
        "P3 the swing switch also governs Calm and Stress",
        lambda: setattr(ts, "provider_for", lambda slot: ts.swing_provider()),
        lambda: setattr(ts, "provider_for", orig_provider_for),
        "test_calm_and_stress_are_not_reachable_by_this_switch"))

    # P4 — the broker is left connected. 23 slots a day, all holding the same client id.
    import global_index.run_live_day_track1 as entry
    from global_index import track1_live_source as S
    orig_build = S.build_bar_provider

    def _no_disconnect(kind, **kw):
        provider, broker = orig_build(kind, **kw)
        if broker is not None:
            broker.disconnect = lambda: None      # the finally runs and achieves nothing
        return provider, broker

    results.append(mutate(
        "P4 disconnect is a no-op, so the connection leaks",
        lambda: setattr(S, "build_bar_provider", _no_disconnect),
        lambda: setattr(S, "build_bar_provider", orig_build),
        "test_a_swing_slot_with_a_provider_disconnects_in_the_finally"))

    # P5 — the CLI choice list is hard-coded again. This is the defect Stage 5M-B shipped: the
    # scheduler built an argv argparse would reject, and every swing slot died at parse time.
    src = Path("global_index/run_live_day_track1.py")
    original = src.read_text(encoding="utf-8")
    hardcoded = original.replace(
        "                    choices=[None, *sorted(tp.WINDOWS_ET)],",
        '                    choices=[None, "roska4_calm", "roska4_stress"],')
    assert hardcoded != original, "the derived choices line was not found"
    results.append(mutate(
        "P5 the --sleeve choices are hard-coded to Calm and Stress again",
        lambda: src.write_text(hardcoded, encoding="utf-8"),
        lambda: src.write_text(original, encoding="utf-8"),
        "test_a_swing_slot_with_a_provider_disconnects_in_the_finally"))

    # P6 — a stale slot count is reintroduced into operator-facing text.
    ops_path = Path("monitor/ops.py")
    ops_original = ops_path.read_text(encoding="utf-8")
    ops_stale = ops_original.replace(
        "def track1_slot_count() -> int:",
        'STALE_HELP = "adds the 25 Track 1 slots"\n\n\ndef track1_slot_count() -> int:')
    assert ops_stale != ops_original
    results.append(mutate(
        "P6 a hard-coded '25 Track 1 slots' returns to operator text",
        lambda: ops_path.write_text(ops_stale, encoding="utf-8"),
        lambda: ops_path.write_text(ops_original, encoding="utf-8"),
        "test_no_operator_facing_file_states_a_slot_count_that_can_go_stale"))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")

    # The files P5 and P6 edit are production files. Prove they came back byte-identical.
    ok_restore = (src.read_text(encoding="utf-8") == original
                  and ops_path.read_text(encoding="utf-8") == ops_original)
    print("production files restored byte-for-byte:", ok_restore)

    import json
    Path("scratch/_stage5mc_mutations.json").write_text(
        json.dumps({"mutations": results, "files_restored": ok_restore}, indent=2),
        encoding="utf-8")
    return 0 if detected == len(results) and ok_restore else 1


if __name__ == "__main__":
    raise SystemExit(main())
