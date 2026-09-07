"""scratch/track1_fill_shortgate_regen_20260822.py — Stage 2C prep. Offline. Scratch only.

Regenerates the Normal-R4 + NKD trade tables that Track 1 is built on, under a 2x2 of the
two settings that Stage 2 could not source:

    fill law     artifact  = every bar gap-eligible (force_all_bars_gappable)
                 production = fill at the open only after a real >15-minute break (GAP_MIN)
    SPY gate     on  = SHORT only when SPY D-1 close < SMA50   (the shipped Normal config)
                 off = shorts unconditional

Nothing is re-implemented. Both axes are flipped by monkeypatching the ONE generator that
produced the committed artifacts, `normal_promotion_regen_audit_20260821`, in process. A
second implementation of a filter proves nothing about the first, and this project has
already paid for that lesson: the generator's own header says there is exactly one copy on
purpose.

The anchor comes first
----------------------
Variant `artifact_gate_on` IS the shipped configuration. Its regenerated trade table must
match the committed `normal_promotion_trades_<window>_20260821.json` exactly — same trade
count and same ordered rows per instrument. If it does not, the harness is not measuring
what shipped and every delta below it is noise. The run stops there.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd  # noqa: E402

import scratch.normal_promotion_regen_audit_20260821 as regen  # noqa: E402
from scratch.directional_market_filter_probe import feature_frame  # noqa: E402

OUT_DIR = Path("scratch/track1_variants_20260822")
COMMITTED = "scratch/normal_promotion_trades_{}_20260821.json"

FILL_ARTIFACT = "artifact_all_bars_gappable"
FILL_PRODUCTION = "production_gap_after_15min_break"

VARIANTS = {
    "artifact_gate_on": (FILL_ARTIFACT, True),        # <- what shipped; the anchor
    "production_gate_on": (FILL_PRODUCTION, True),
    "artifact_gate_off": (FILL_ARTIFACT, False),
    "production_gate_off": (FILL_PRODUCTION, False),
}


def _no_fill_patch():
    """Stand in for force_all_bars_gappable() without patching anything.

    The generator calls it for its return value and restores that value in a finally
    block, so handing back the live `_swing_cache` leaves the production law in force and
    keeps the restore a no-op.
    """
    import futures._validated_core as VC
    return VC._swing_cache


def _all_days_allowed(spy_frame, _name):
    """Every session allowed, so the SHORT gate can never reject.

    Flipping the gate this way rather than editing `gated_generate` keeps the rest of that
    function — the R4 context filter, the timestamp normalisation — byte-identical between
    variants. Changing two things at once would make the delta unattributable.
    """
    return {pd.Timestamp(d).normalize() for d in spy_frame.index}


def run_variant(name: str, which: str, spy_csv: str) -> dict:
    fill, gate_on = VARIANTS[name]
    orig_fill, orig_gate = regen.force_all_bars_gappable, regen.allowed_short_days
    if fill == FILL_PRODUCTION:
        regen.force_all_bars_gappable = _no_fill_patch
    if not gate_on:
        regen.allowed_short_days = _all_days_allowed
    try:
        cap = regen.run_engine(which, spy_csv, apply_filter=True)
    finally:
        regen.force_all_bars_gappable, regen.allowed_short_days = orig_fill, orig_gate

    return {"variant": name, "fill_law": fill, "spy_short_gate": gate_on,
            "which": which, "argv": cap["argv"], "nkd_instrument": cap["nkd"],
            "trades": {k: [{kk: str(vv) for kk, vv in t.items()} for t in v]
                       for k, v in cap["trades"].items()},
            "filter_stats": cap.get("filter_stats", {})}


# ---------------------------------------------------------------------------
# anchor
# ---------------------------------------------------------------------------
_KEYS = ("day", "exit_day", "direction", "entry", "exit", "pnl")


def _rows(trades: list) -> list:
    return [tuple(str(t.get(k)) for k in _KEYS) for t in trades]


def anchor(result: dict, which: str) -> dict:
    """Compare the regenerated shipped configuration with the committed artifact."""
    ref = json.loads(Path(COMMITTED.format(which)).read_text(encoding="utf-8"))["filtered"]
    got = result["trades"]
    rows = []
    for inst in sorted(set(ref) | set(got)):
        a, b = _rows(ref.get(inst, [])), _rows(got.get(inst, []))
        first = next((i for i in range(max(len(a), len(b)))
                      if (a[i] if i < len(a) else None) != (b[i] if i < len(b) else None)),
                     None)
        rows.append({"inst": inst, "committed": len(a), "regenerated": len(b),
                     "ok": a == b, "first_diff": first})
    total = sum(r["committed"] for r in rows)
    return {"rows": rows, "all_ok": all(r["ok"] for r in rows) and total > 0,
            "committed_total": total}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["vault2026"])
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS))
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--skip-anchor", action="store_true",
                    help="only for windows already anchored in an earlier run")
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for which in a.which:
        print(f"\n=== window {which} ===", flush=True)
        if not a.skip_anchor and "artifact_gate_on" not in a.variants:
            print("REFUSED: the anchor variant artifact_gate_on must run first.")
            return 2
        for name in a.variants:
            res = run_variant(name, which, a.spy_csv)
            n = sum(len(v) for v in res["trades"].values())
            out = OUT_DIR / f"{which}__{name}.json"
            out.write_text(json.dumps(res, indent=1), encoding="utf-8")
            print(f"  {name:22s} trades={n:5d}  -> {out.name}", flush=True)

            if name == "artifact_gate_on" and not a.skip_anchor:
                anc = anchor(res, which)
                for r in anc["rows"]:
                    print(f"    {'OK ' if r['ok'] else 'XX '}{r['inst']:5s} "
                          f"committed={r['committed']:4d} regenerated={r['regenerated']:4d}"
                          + ("" if r["ok"] else f"  first diff at {r['first_diff']}"))
                (OUT_DIR / f"{which}__anchor.json").write_text(
                    json.dumps(anc, indent=1), encoding="utf-8")
                if not anc["all_ok"]:
                    print("\nREFUSED: the shipped configuration did not reproduce. "
                          "Every delta measured against it would be noise.")
                    return 1
                print(f"    ANCHOR OK — {anc['committed_total']} committed trades reproduced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
