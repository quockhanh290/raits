"""Stage 5ZZZ-I — four routes, one replay, three windows.

    base      the current Swing identity, same-day regime label   (NOT live-tradable)
    d1        causal D-1 label, the frozen ema30/mult2.5 params
    d1r       causal D-1 label, the parameters this stage's WFO selected on the floor
    noswing   the same book with the Swing sleeve removed

floor is in-sample; 2025 and 2026 are out-of-sample and were never read during selection.
"""
from __future__ import annotations

import json
from pathlib import Path

ARMS = [("base", "same-day Swing (current, not live-tradable)"),
        ("d1", "D-1 Swing, old params"),
        ("d1r", "D-1 Swing, retuned"),
        ("noswing", "no Swing")]
WIN = [("floor", "floor 2018-2024 (IN-SAMPLE)"),
       ("vault2025", "2025 (OOS)"),
       ("vault2026", "2026 to 08-19 (OOS)")]
POL = [("repaired_mechanics_family_cap_5_44", "full stack, Calm-NKD ON"),
       ("risk_clean_no_calm_nkd_family_cap_5_44", "risk-clean, no Calm-NKD")]
CL = [("roska4_swing", "Swing"), ("roska4_stress", "Stress"),
      ("roska4_calm", "Calm"), ("global_nkd", "NKD")]


def load(arm: str):
    p = Path(f"scratch/track1_stage5zzzh_full_replay_{arm}_20260829.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    data = {a: load(a) for a, _ in ARMS}
    have = [(a, lbl) for a, lbl in ARMS if data[a]]
    print("arms present:", [a for a, _ in have])

    out: dict = {"arms": {a: lbl for a, lbl in have}, "windows": {}}
    for pk, plabel in POL:
        print("\n" + "=" * 112)
        print(plabel.upper())
        print("=" * 112)
        print(f"{'window':28s} {'arm':38s} {'Net':>10s} {'PF':>6s} {'Sharpe':>7s} "
              f"{'Calmar':>7s} {'MaxDD':>8s} {'trades':>7s} {'Swing$':>10s}")
        for wk, wlabel in WIN:
            base_net = data["base"][wk][pk]["net"] if data.get("base") else None
            for a, lbl in have:
                r = data[a][wk][pk]
                sw = r["pnl_by_cluster"].get("roska4_swing", 0.0)
                tot = sum(r["taken"].values())
                d = f"  ({r['net'] - base_net:+,.0f})" if base_net is not None else ""
                print(f"{wlabel if a == have[0][0] else '':28s} {lbl:38s} "
                      f"{r['net']:>10,.0f} {r['pf']:>6.2f} {r['sharpe']:>7.2f} "
                      f"{r['calmar']:>7.2f} {r['maxdd']:>8,.0f} {tot:>7} {sw:>10,.0f}{d}")
                out["windows"].setdefault(wk, {}).setdefault(pk, {})[a] = {
                    "net": r["net"], "pf": r["pf"], "sharpe": r["sharpe"],
                    "calmar": r["calmar"], "maxdd": r["maxdd"],
                    "trades_taken": tot,
                    "trades_rejected": sum(r["rejected"].values()),
                    "swing_taken": r["taken"]["roska4_swing"],
                    "swing_rejected": r["rejected"]["roska4_swing"],
                    "pnl_by_cluster": r["pnl_by_cluster"],
                    "delta_vs_base": round(r["net"] - base_net, 2) if base_net is not None else None,
                }
            print()

    print("=" * 112)
    print("SLEEVE CONTRIBUTION (booked, after caps)")
    print("=" * 112)
    for pk, plabel in POL:
        print(f"\n{plabel}")
        print(f"{'window':26s} {'arm':38s} " + " ".join(f"{n:>11s}" for _, n in CL))
        for wk, wlabel in WIN:
            for a, lbl in have:
                c = data[a][wk][pk]["pnl_by_cluster"]
                print(f"{wlabel if a == have[0][0] else '':26s} {lbl:38s} " +
                      " ".join(f"{c.get(k, 0.0):>11,.0f}" for k, _ in CL))
            print()

    Path("scratch/track1_stage5zzzi_compare_20260829.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print("wrote scratch/track1_stage5zzzi_compare_20260829.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
