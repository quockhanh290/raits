"""Prove the corrected-fill law is an ENGINE-LEVEL rule change, not bookkeeping.

The engine fills a stop at the bar OPEN only when a >15-minute time break precedes
the hit bar (`GAP_MIN = 15.0` inside `_swing_cache`); otherwise it fills at the stop
level, which is how a price that never traded gets booked.

`normal_sleeve_fill_audit.correct_trades` rewrites those fills afterwards as
  LONG  min(stop, bar open) / SHORT max(stop, bar open).

Claim under test: that post-hoc rewrite is IDENTICAL to running the engine with the
time-break requirement removed -- i.e. with every bar eligible for gap-through. The
engine's own `gapped` test already requires the open to be on the adverse side of
the stop, so forcing the flag on cannot turn a favourable open into a gap fill.

Method: run the same window twice, once normally and once with every bar's gap flag
forced True, and compare trade-for-trade against the post-hoc-corrected table.
A mismatch means the post-hoc correction is NOT the rule change it claims to be.

    python scratch/nsfa_correction_equivalence_20260821.py --which vault2026
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.normal_sleeve_fill_audit import (R4, _nkd_instrument, _round_turn,
                                              _slip_ticks, correct_trades, run_window)


def force_all_bars_gappable():
    """Patch _swing_cache so every bar carries the overnight-gap flag."""
    import futures._validated_core as VC
    orig = VC._swing_cache

    def patched(df, datr=None):
        c = orig(df, datr)
        if not c.get("_all_gap"):
            for day, (high, low, opn, isg) in list(c["hl"].items()):
                c["hl"][day] = (high, low, opn, np.ones(len(isg), dtype=bool))
            c["_all_gap"] = True
        return c

    VC._swing_cache = patched
    return orig


def clear_caches():
    import futures._validated_core as VC
    VC._SWING_CACHE.clear()
    H._CACHE.clear()


def key(t):
    return (str(t["day"]), str(t["exit_day"]), str(t.get("entry_time")),
            str(t.get("exit_time")), t["direction"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", default="vault2026")
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    args = ap.parse_args()

    import futures._validated_core as VC
    from futures.basket import BASKET
    from global_index import specs as gi_specs

    print("=" * 96)
    print("EQUIVALENCE PROOF - post-hoc corrected fill vs engine with the time-break")
    print("requirement removed.   window = " + args.which)
    print("=" * 96)

    clear_caches()
    cap_a = run_window(args.which, args.spy_csv)
    argv = cap_a["argv"]
    nkd = _nkd_instrument(argv)
    slip = _slip_ticks(argv)

    posthoc = {}
    for name, d in cap_a["inst"].items():
        is_nkd = (name == nkd)
        c = gi_specs.SPECS[nkd] if is_nkd else BASKET[name]
        posthoc[name] = correct_trades(d["raw"], d["df"], float(c.point_value),
                                       _round_turn(c, is_nkd, slip))[0]

    orig = force_all_bars_gappable()
    try:
        clear_caches()
        cap_b = run_window(args.which, args.spy_csv)
    finally:
        VC._swing_cache = orig
        clear_caches()

    engine = {name: d["raw"] for name, d in cap_b["inst"].items()}

    print()
    print("  {:<6} {:>8} {:>8} {:>10} {:>10} {:>12} {:>12}".format(
        "inst", "n_post", "n_eng", "same keys", "px match", "post net$", "eng net$"))
    all_ok = True
    for name in list(R4) + [nkd]:
        p, e = posthoc.get(name), engine.get(name)
        if p is None or e is None:
            continue
        kp = [key(t) for t in p]
        ke = [key(t) for t in e]
        same_keys = (kp == ke)
        px_ok = same_keys and all(abs(float(a["exit"]) - float(b["exit"])) < 0.011
                                  and abs(float(a["pnl"]) - float(b["pnl"])) < 0.02
                                  for a, b in zip(p, e))
        all_ok = all_ok and same_keys and px_ok
        print("  {:<6} {:>8} {:>8} {:>10} {:>10} {:>12,.0f} {:>12,.0f}".format(
            name, len(p), len(e), "YES" if same_keys else "NO",
            "YES" if px_ok else "NO",
            sum(float(t["pnl"]) for t in p), sum(float(t["pnl"]) for t in e)))
        if not px_ok and same_keys:
            for a, b in zip(p, e):
                if abs(float(a["exit"]) - float(b["exit"])) >= 0.011:
                    print("      MISMATCH {} {} post exit {:.2f} ({}) vs engine {:.2f} ({})".format(
                        name, a["exit_day"], float(a["exit"]), a.get("reason"),
                        float(b["exit"]), b.get("reason")))
                    break

    print()
    print("  VERDICT: " + ("PASS - the post-hoc correction IS the engine-level rule change"
                           if all_ok else
                           "FAIL - the post-hoc correction is not equivalent; do not use it"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
