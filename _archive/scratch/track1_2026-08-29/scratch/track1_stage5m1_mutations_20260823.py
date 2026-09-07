"""Stage 5M-1 mutation harness — put the artifact law back on the live path, one way at a time.

The stage's whole claim is "no live path reaches the artifact law implicitly". A suite that
only ever sees the fixed code cannot show it would notice the unfixed code. Each mutation below
re-creates one of the five ways the artifact law used to get in, and the matching test must go
red.

Nothing is written outside `tmp_path`: the tests these drive build their own checkpoints and
their own ledger directories. Every mutation is a monkeypatch on an imported module, reverted
before the next.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from global_index import track1_normal_r4 as NR  # noqa: E402
from global_index import track1_params as tp     # noqa: E402

TEST = "scratch/test_track1_stage5m1_fill_law_identity_20260823.py"
ARTIFACT = "artifact_all_bars_gappable"


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

    # F1 — the route's own constant flipped back to the artifact law. The single edit that
    # would silently re-point every identity the route records.
    results.append(mutate(
        "F1 LIVE_FILL_LAW set back to the artifact law",
        lambda: setattr(tp, "LIVE_FILL_LAW", ARTIFACT),
        lambda: setattr(tp, "LIVE_FILL_LAW", tp.FILL_PRODUCTION),
        "test_the_route_names_the_production_law_and_only_once"))

    # F2 — the engine default flipped back. This is the state the code was actually in before
    # Stage 5M-1, and it is the one that reaches the ENGINE, not just a hash.
    orig_fields = NR.NormalR4Params.__dataclass_fields__["fill_law"].default

    def _flip(value):
        NR.NormalR4Params.__dataclass_fields__["fill_law"].default = value
        NR.NormalR4Params.__init__.__defaults__ = tuple(
            ARTIFACT if d == orig_fields else d for d in NR.NormalR4Params.__init__.__defaults__
        ) if value == ARTIFACT else tuple(
            orig_fields if d == ARTIFACT else d for d in NR.NormalR4Params.__init__.__defaults__)

    results.append(mutate(
        "F2 the engine dataclass default back to the artifact law",
        lambda: _flip(ARTIFACT),
        lambda: _flip(orig_fields),
        "test_the_engine_default_is_the_live_law"))

    # F3 — the live slot hands the artifact law to the explanation writer. The identity every
    # shadow record carries; wrong here means a checkpoint accepted under the other law.
    import global_index.run_live_day_track1 as entry
    orig_report = entry.checkpoint_report

    results.append(mutate(
        "F3 the checkpoint report defaults to the artifact law",
        lambda: setattr(entry, "checkpoint_report",
                        lambda **kw: orig_report(**{**kw, "fill_law": ARTIFACT})),
        lambda: setattr(entry, "checkpoint_report", orig_report),
        "test_the_checkpoint_report_defaults_to_the_production_identity"))

    # F4 — the fifth callsite: the engine params the live sleeve source builds. The one that
    # decides which trades exist and contains no `fill_law` token to grep for.
    from global_index import track1_sleeves as sleeves
    orig_detect = sleeves.LiveSleeveSource.detect

    def _artifact_detect(self, *, through, labels_by_inst, costs=None, params=None,
                         sleeves=None):
        params = dict(params or {})
        for inst in labels_by_inst:
            params.setdefault(inst, NR.NormalR4Params(fill_law=ARTIFACT))
        return orig_detect(self, through=through, labels_by_inst=labels_by_inst, costs=costs,
                           params=params, sleeves=sleeves)

    results.append(mutate(
        "F4 the live sleeve source runs the engine under the artifact law",
        lambda: setattr(sleeves.LiveSleeveSource, "detect", _artifact_detect),
        lambda: setattr(sleeves.LiveSleeveSource, "detect", orig_detect),
        "test_the_live_sleeve_source_runs_the_engine_under_the_production_law"))

    # F5 — the cross-law checkpoint guard stops refusing. Identity that accepts anything is
    # not an identity.
    from global_index import track1_bootstrap as boot
    orig_accepts = boot.accepts
    results.append(mutate(
        "F5 the checkpoint accepts a run under the other law",
        lambda: setattr(boot, "accepts", lambda *a, **kw: True),
        lambda: setattr(boot, "accepts", orig_accepts),
        "test_a_cross_law_checkpoint_is_refused_in_both_directions"
        "[artifact_all_bars_gappable-production_gap_after_15min_break]"))

    # F6 — the law stops reaching the identity hash at all, so both laws hash the same.
    orig_identity = tp.sleeve_identity
    results.append(mutate(
        "F6 the fill law no longer reaches the identity hash",
        lambda: setattr(tp, "sleeve_identity",
                        lambda *a, **kw: orig_identity(
                            *a, **{**kw, "fill_law": tp.FILL_PRODUCTION})),
        lambda: setattr(tp, "sleeve_identity", orig_identity),
        "test_the_live_identity_is_the_production_identity"))

    detected = sum(1 for r in results if r["detected"])
    print(f"\n{detected}/{len(results)} mutations detected")
    import json
    Path("scratch/_stage5m1_mutations.json").write_text(json.dumps(results, indent=2),
                                                        encoding="utf-8")
    return 0 if detected == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
