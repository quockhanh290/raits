"""Stage 5ZZZ-H — baseline vs causal-D-1 swing, side by side."""
from __future__ import annotations

import json
from pathlib import Path

B = json.loads(Path("scratch/track1_stage5zzzh_full_replay_base_20260829.json").read_text())
D = json.loads(Path("scratch/track1_stage5zzzh_full_replay_d1_20260829.json").read_text())
CH = json.loads(Path("scratch/track1_stage5zzzh_swing_churn_20260829.json").read_text())

WIN = [("floor", "floor 2018-2024 (IN-SAMPLE)"),
       ("vault2025", "2025 (OOS)"),
       ("vault2026", "2026 through 08-19 (OOS)")]
POL = [("repaired_mechanics_family_cap_5_44", "full stack, Calm-NKD ON"),
       ("risk_clean_no_calm_nkd_family_cap_5_44", "risk-clean, no Calm-NKD")]
CL = [("roska4_swing", "Swing"), ("roska4_stress", "Stress"),
      ("roska4_calm", "Calm"), ("global_nkd", "NKD")]

out = {"windows": {}}
for pk, plabel in POL:
    print("\n" + "=" * 104)
    print(plabel.upper())
    print("=" * 104)
    print(f"{'window':30s} {'':9s} {'Net':>10s} {'PF':>6s} {'Sharpe':>7s} {'Calmar':>7s} "
          f"{'MaxDD':>9s} {'taken':>6s} {'rej':>5s}")
    for wk, wlabel in WIN:
        b, d = B[wk][pk], D[wk][pk]
        for tag, r in (("baseline", b), ("D-1", d)):
            print(f"{wlabel if tag == 'baseline' else '':30s} {tag:9s} "
                  f"{r['net']:>10,.0f} {r['pf']:>6.2f} {r['sharpe']:>7.2f} "
                  f"{r['calmar']:>7.2f} {r['maxdd']:>9,.0f} "
                  f"{r['taken']['roska4_swing']:>6} {r['rejected']['roska4_swing']:>5}")
        dn = d["net"] - b["net"]
        print(f"{'':30s} {'delta':9s} {dn:>+10,.0f} {d['pf'] - b['pf']:>+6.2f} "
              f"{d['sharpe'] - b['sharpe']:>+7.2f} {d['calmar'] - b['calmar']:>+7.2f} "
              f"{d['maxdd'] - b['maxdd']:>+9,.0f} "
              f"{d['taken']['roska4_swing'] - b['taken']['roska4_swing']:>+6} "
              f"{d['rejected']['roska4_swing'] - b['rejected']['roska4_swing']:>+5}"
              f"   ({100 * dn / b['net']:+.1f}%)")
        out["windows"].setdefault(wk, {})[pk] = {
            "baseline": b, "d1": d,
            "delta": {"net": round(dn, 2), "net_pct": round(100 * dn / b["net"], 2),
                      "pf": round(d["pf"] - b["pf"], 4),
                      "sharpe": round(d["sharpe"] - b["sharpe"], 4),
                      "calmar": round(d["calmar"] - b["calmar"], 4),
                      "maxdd": round(d["maxdd"] - b["maxdd"], 2)}}

print("\n" + "=" * 104)
print("SLEEVE CONTRIBUTION (booked P&L by cluster, after every cap and override)")
print("=" * 104)
for pk, plabel in POL:
    print(f"\n{plabel}")
    print(f"{'window':26s} {'variant':9s} " + " ".join(f"{n:>12s}" for _, n in CL))
    for wk, wlabel in WIN:
        for tag, src in (("baseline", B), ("D-1", D)):
            c = src[wk][pk]["pnl_by_cluster"]
            print(f"{wlabel if tag == 'baseline' else '':26s} {tag:9s} " +
                  " ".join(f"{c.get(k, 0.0):>12,.0f}" for k, _ in CL))
        cb, cd = B[wk][pk]["pnl_by_cluster"], D[wk][pk]["pnl_by_cluster"]
        print(f"{'':26s} {'delta':9s} " +
              " ".join(f"{cd.get(k, 0.0) - cb.get(k, 0.0):>+12,.0f}" for k, _ in CL))
        out["windows"][wk][pk]["cluster_delta"] = {
            k: round(cd.get(k, 0.0) - cb.get(k, 0.0), 2) for k, _ in CL}

print("\n" + "=" * 104)
print("SWING ENTRY CHURN inside the sleeve, before portfolio caps")
print("=" * 104)
print(f"{'window':26s} {'shared':>7s} {'only base':>10s} {'only D-1':>9s} {'churn':>7s} "
      f"{'pre-cap P&L delta':>19s}")
for wk, wlabel in WIN:
    f = CH[wk]["filtered"]
    print(f"{wlabel:26s} {f['shared']:>7} {f['only_base']:>10} {f['only_d1']:>9} "
          f"{f['churn_pct']:>6.1f}% {f['pnl_delta_presize']:>+19,.0f}")
    out["windows"][wk]["swing_churn"] = f
    out["windows"][wk]["nkd_identical"] = CH[wk]["nkd_identical"]

Path("scratch/track1_stage5zzzh_compare_20260829.json").write_text(
    json.dumps(out, indent=1), encoding="utf-8")
print("\nwrote scratch/track1_stage5zzzh_compare_20260829.json")
