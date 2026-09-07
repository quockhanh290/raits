"""Stage 5ZZZ-H — what changed inside the Normal/R4 artifact when swing went causal D-1.

Self-checks that must hold, or the run measured something other than what it claims:
  * NKD's trade list is BYTE-IDENTICAL. It never goes through the patched seam, so if it moved,
    the patch reached further than the swing basket and every number below is void.
  * at least one R4 instrument's list DID change. If none did, the patch did nothing and a
    "no difference" verdict would be an artefact of a no-op.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

R4 = ("MES", "MNQ", "M2K", "MYM")
WINDOWS = ("floor", "vault2025", "vault2026")


def load(which: str, variant: str) -> dict:
    p = (Path(f"scratch/normal_promotion_trades_{which}_20260821.json") if variant == "base"
         else Path(f"scratch/normal_promotion_trades_{which}_d1_20260829.json"))
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def key(t: dict) -> tuple:
    return (str(t.get("day")), str(t.get("direction")), str(t.get("entry_time")))


def churn(which: str) -> dict:
    b, d = load(which, "base"), load(which, "d1")
    if not b or not d:
        return {"window": which, "error": "artifact missing"}

    out: dict = {"window": which, "per_instrument": {}}
    nkd = b.get("nkd_instrument")
    for bucket in ("raw", "filtered"):
        shared = only_b = only_d = 0
        pnl_b = pnl_d = 0.0
        for inst in R4:
            tb = b.get(bucket, {}).get(inst, [])
            td = d.get(bucket, {}).get(inst, [])
            kb = {key(t) for t in tb}
            kd = {key(t) for t in td}
            shared += len(kb & kd)
            only_b += len(kb - kd)
            only_d += len(kd - kb)
            pb = sum(float(t["pnl"]) for t in tb)
            pd_ = sum(float(t["pnl"]) for t in td)
            pnl_b += pb
            pnl_d += pd_
            if bucket == "filtered":
                out["per_instrument"][inst] = {
                    "base_trades": len(tb), "d1_trades": len(td),
                    "shared": len(kb & kd), "only_base": len(kb - kd),
                    "only_d1": len(kd - kb),
                    "base_pnl": round(pb, 2), "d1_pnl": round(pd_, 2),
                    "pnl_delta": round(pd_ - pb, 2)}
        total = shared + only_b + only_d
        out[bucket] = {
            "shared": shared, "only_base": only_b, "only_d1": only_d,
            "union": total,
            "churn_pct": round(100.0 * (only_b + only_d) / total, 2) if total else 0.0,
            "base_pnl_presize": round(pnl_b, 2), "d1_pnl_presize": round(pnl_d, 2),
            "pnl_delta_presize": round(pnl_d - pnl_b, 2)}

    # ── the self-checks ────────────────────────────────────────────────────────────────────
    nb = json.dumps(b.get("filtered", {}).get(nkd, []), sort_keys=True)
    nd = json.dumps(d.get("filtered", {}).get(nkd, []), sort_keys=True)
    out["nkd_identical"] = (nb == nd)
    out["nkd_instrument"] = nkd
    out["any_r4_changed"] = any(v["only_base"] or v["only_d1"]
                                for v in out["per_instrument"].values())
    out["argv_identical"] = (b.get("argv") == d.get("argv"))
    out["slippage_identical"] = (b.get("slippage_ticks") == d.get("slippage_ticks"))
    return out


def main() -> int:
    results = {}
    for w in WINDOWS:
        r = churn(w)
        results[w] = r
        if r.get("error"):
            print(f"{w:11s} {r['error']}")
            continue
        f = r["filtered"]
        print(f"\n=== {w} ===")
        print(f"  argv identical  : {r['argv_identical']}   slippage identical: "
              f"{r['slippage_identical']}")
        print(f"  NKD ({r['nkd_instrument']}) identical: {r['nkd_identical']}"
              f"{'' if r['nkd_identical'] else '   <-- THE PATCH LEAKED; NUMBERS ARE VOID'}")
        print(f"  any R4 changed  : {r['any_r4_changed']}"
              f"{'' if r['any_r4_changed'] else '   <-- THE PATCH DID NOTHING'}")
        print(f"  filtered: shared={f['shared']}  only_base={f['only_base']}  "
              f"only_d1={f['only_d1']}  churn={f['churn_pct']}%")
        print(f"  pre-cap pnl: base {f['base_pnl_presize']:>12,.2f}   "
              f"d1 {f['d1_pnl_presize']:>12,.2f}   delta {f['pnl_delta_presize']:>+12,.2f}")
        for inst, v in r["per_instrument"].items():
            print(f"    {inst:5s} base={v['base_trades']:>4} d1={v['d1_trades']:>4} "
                  f"shared={v['shared']:>4} -{v['only_base']:<4} +{v['only_d1']:<4} "
                  f"pnl {v['pnl_delta']:>+11,.2f}")
    Path("scratch/track1_stage5zzzh_swing_churn_20260829.json").write_text(
        json.dumps(results, indent=1), encoding="utf-8")
    print("\nwrote scratch/track1_stage5zzzh_swing_churn_20260829.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
