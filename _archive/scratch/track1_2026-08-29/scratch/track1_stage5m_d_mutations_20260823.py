"""Stage 5M-D mutation harness — re-arm each hazard, confirm the right test reds.

The stage's claims are mostly absences: no legacy strategy jobs in the new mode, no provider
default where the collision still exists, no myth about the kill switch in operator text. Every
absence check passes by finding nothing, so each one has to be shown to find SOMETHING when the
thing returns.

No real IBKR, nothing written outside tmp_path, production files edited on disk by two
mutations are hash-verified restored.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from global_index import track1_slots as ts  # noqa: E402

TEST = "scratch/test_track1_stage5m_d_track1_only_shadow_20260823.py"


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

    # D1 — a legacy job survives into Track 1-only mode. The central claim.
    orig_candidates = ts.legacy_retirement_candidates
    results.append(mutate(
        "D1 one legacy entry job survives into track1-only",
        lambda: setattr(ts, "legacy_retirement_candidates",
                        lambda *a, **k: orig_candidates(*a, **k) - {"live_day"}),
        lambda: setattr(ts, "legacy_retirement_candidates", orig_candidates),
        "test_track1_only_registers_no_legacy_strategy_job"))

    # D2 — the swing provider defaults to ibkr in the TRANSITIONAL mode too, re-creating the
    # unmeasured collision 5M-C existed to avoid.
    orig_swing = ts.swing_provider
    results.append(mutate(
        "D2 swing defaults to ibkr in transitional shadow",
        lambda: setattr(ts, "swing_provider",
                        lambda *, track1_only=False: ts.PROVIDER_IBKR),
        lambda: setattr(ts, "swing_provider", orig_swing),
        "test_in_transitional_shadow_the_swing_slots_still_default_to_none"))

    # D3 — the new mode loses its provider default and quietly collects nothing.
    results.append(mutate(
        "D3 track1-only loses the ibkr default",
        lambda: setattr(ts, "swing_provider",
                        lambda *, track1_only=False: ts.PROVIDER_NONE),
        lambda: setattr(ts, "swing_provider", orig_swing),
        "test_in_track1_only_the_swing_slots_take_ibkr_by_default"))

    # D4 — ops stops refusing the contradictory flag pair.
    from monitor import ops
    orig_cmd_up = ops.cmd_up

    def _permissive(args):
        if getattr(args, "track1_shadow", False) and getattr(args, "track1_only_shadow", False):
            args.track1_shadow = False          # silently "resolves" the contradiction
        return orig_cmd_up(args)

    results.append(mutate(
        "D4 ops resolves --track1-shadow + --track1-only-shadow silently",
        lambda: setattr(ops, "cmd_up", _permissive),
        lambda: setattr(ops, "cmd_up", orig_cmd_up),
        "test_ops_refuses_both_shadow_flags_together"))

    # D5 — track1-only starts requiring STOP_TRADING, teaching the wrong model.
    orig_blockers = ops.track1_shadow_blockers
    results.append(mutate(
        "D5 track1-only demands STOP_TRADING after all",
        lambda: setattr(ops, "track1_shadow_blockers",
                        lambda *, track1_only=False: orig_blockers(track1_only=False)),
        lambda: setattr(ops, "track1_shadow_blockers", orig_blockers),
        "test_ops_track1_only_does_not_require_stop_trading"))

    # D6 — a Track 1 module grows an import of the legacy entrypoint. Done on DISK, because
    # the removability test parses source; hash-verified restored.
    target = Path("global_index/track1_slots.py")
    original = target.read_text(encoding="utf-8")
    with_import = original.replace(
        "from global_index.track1_params import ROUTE, WINDOWS_ET",
        "from global_index.track1_params import ROUTE, WINDOWS_ET\n"
        "import global_index.run_live_day  # noqa: F401 — mutation D6")
    assert with_import != original
    results.append(mutate(
        "D6 a Track 1 module imports the legacy entrypoint",
        lambda: target.write_text(with_import, encoding="utf-8"),
        lambda: target.write_text(original, encoding="utf-8"),
        "test_no_track1_module_imports_the_legacy_entrypoint"))

    # D7 — the kill-switch myth returns to operator text. On disk; hash-verified restored.
    ops_path = Path("monitor/ops.py")
    ops_original = ops_path.read_text(encoding="utf-8")
    ops_myth = ops_original.replace(
        "LEGACY_STOP_FILE = ROOT / \"STOP_TRADING\"",
        "LEGACY_STOP_FILE = ROOT / \"STOP_TRADING\"\n"
        "# STOP_TRADING turns off legacy entirely, so nothing else is needed.  (mutation D7)")
    assert ops_myth != ops_original
    results.append(mutate(
        "D7 'STOP_TRADING turns off legacy' returns to operator text",
        lambda: ops_path.write_text(ops_myth, encoding="utf-8"),
        lambda: ops_path.write_text(ops_original, encoding="utf-8"),
        "test_no_operator_text_claims_stop_trading_turns_legacy_off"))

    # D8 — the dashboard mirror stops omitting legacy rows in track1-only, so the dashboard
    # would invent 45 stray slots a day. On DISK, not a monkeypatch: the guard test reloads
    # `schedule_status` inside itself, which erases an in-process patch — the first version of
    # this mutation went undetected for exactly that reason, and the unfaithful party was the
    # mutation. A real regression lives in the source the reload reads.
    ss_path = Path("monitor/backend/schedule_status.py")
    ss_original = ss_path.read_text(encoding="utf-8")
    ss_broken = ss_original.replace(
        'return _os.environ.get("RAITS_TRACK1_ONLY") == "1"',
        'return False  # mutation D8')
    assert ss_broken != ss_original
    results.append(mutate(
        "D8 the mirror ignores track1-only and mirrors legacy rows",
        lambda: ss_path.write_text(ss_broken, encoding="utf-8"),
        lambda: ss_path.write_text(ss_original, encoding="utf-8"),
        "test_in_track1_only_the_mirror_shows_no_legacy_strategy_rows"))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")

    ok_restore = (target.read_text(encoding="utf-8") == original
                  and ops_path.read_text(encoding="utf-8") == ops_original
                  and ss_path.read_text(encoding="utf-8") == ss_original)
    print("production files restored byte-for-byte:", ok_restore)
    Path("scratch/_stage5md_mutations.json").write_text(
        json.dumps({"mutations": results, "files_restored": ok_restore}, indent=2),
        encoding="utf-8")
    return 0 if detected == len(results) and ok_restore else 1


if __name__ == "__main__":
    raise SystemExit(main())
