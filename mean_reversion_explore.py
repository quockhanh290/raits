"""
mean_reversion_explore.py — is there MEAN-REVERSION edge to find? (read-only)
============================================================================
Momentum-continuation is exhausted on equity-index intraday (TF thin,
NORMAL_MID dead, overnight random). The gap in the map is a steady engine for
the COMMON regimes (Calm/Normal). Theory says range-bound regimes favour
mean-reversion, not momentum — so before building any MR strategy, measure
whether MR edge even exists, BY REGIME.

Method — Variance Ratio (Lo & MacKinlay), the standard trending-vs-reverting test:
    VR(k) = Var(k-step return) / (k · Var(1-step return))
        VR < 1  → mean-reverting   (MR strategies have a chance)
        VR > 1  → trending         (momentum territory — already covered)
        VR ≈ 1  → random walk      (neither works — dead end)
Computed on 5-min RTH returns, grouped by regime, plus two direct checks:
    - gap fade: corr(overnight gap, RTH session return)  (<0 = gaps fade)
    - intraday reversal: corr(morning move, afternoon move) (<0 = reverts)

Reuses gate2_edge_harness; engine untouched.

    python mean_reversion_explore.py --parquet ES_8y.parquet --regime-csv spy_daily.csv
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path.cwd()))


def variance_ratio(rets: np.ndarray, k: int) -> float:
    r = rets[np.isfinite(rets)]
    if len(r) < k * 5:
        return np.nan
    var1 = np.var(r, ddof=1)
    if var1 <= 0:
        return np.nan
    # k-step overlapping returns
    csum = np.cumsum(r)
    kret = csum[k:] - csum[:-k]
    vark = np.var(kret, ddof=1)
    return float(vark / (k * var1))


def main():
    ap = argparse.ArgumentParser(description="Characterize mean-reversion edge by regime (read-only).")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--regime-csv", default=None, help="SPY daily CSV for regime labels")
    ap.add_argument("--hmm-train-end", default="2019-06-30")
    ap.add_argument("--hmm-components", type=int, default=3)
    a = ap.parse_args()

    import gate2_edge_harness as G
    df = G.load_parquet(a.parquet)
    daily = G.benchmark_daily(a.regime_csv) if a.regime_csv else G.daily_close_series(df)
    labels = G.label_regimes(daily, a.hmm_train_end, a.hmm_components)

    print(f"\n{'='*66}\nMEAN-REVERSION EDGE SCAN | {Path(a.parquet).name}\n{'='*66}")

    # build per-day RTH 5-min returns + gap + morning/afternoon moves, tagged by regime
    recs = {r: {"rets": [], "gap": [], "rth": [], "am": [], "pm": []} for r in ["Calm", "Normal", "Stress"]}
    prev_close = None
    for day, g in df.groupby(df.index.normalize()):
        key = pd.Timestamp(day).tz_localize(None).normalize()
        reg = labels.get(key)
        bars5 = G.resample_5m(g).between_time("09:30", "16:00")
        if len(bars5) < 20:
            prev_close = bars5["close"].iloc[-1] if len(bars5) else prev_close
            continue
        c = bars5["close"]
        rets = c.pct_change().dropna().to_numpy()
        op, cl = float(c.iloc[0]), float(c.iloc[-1])
        am = bars5.between_time("09:30", "11:00")["close"]
        pm = bars5.between_time("11:00", "16:00")["close"]
        if reg in recs:
            recs[reg]["rets"].append(rets)
            recs[reg]["rth"].append(cl / op - 1)
            if prev_close:
                recs[reg]["gap"].append(op / prev_close - 1)
            else:
                recs[reg]["gap"].append(np.nan)
            recs[reg]["am"].append(float(am.iloc[-1] / am.iloc[0] - 1) if len(am) > 1 else np.nan)
            recs[reg]["pm"].append(float(pm.iloc[-1] / pm.iloc[0] - 1) if len(pm) > 1 else np.nan)
        prev_close = cl

    print("\n[1] VARIANCE RATIO  (VR<1 mean-revert | VR>1 trend | ≈1 random)  on 5-min RTH")
    print(f"    {'regime':<8} {'days':>5} {'VR(6=30m)':>10} {'VR(12=60m)':>11}  read")
    for reg in ["Calm", "Normal", "Stress"]:
        if not recs[reg]["rets"]:
            continue
        allr = np.concatenate(recs[reg]["rets"])
        vr6, vr12 = variance_ratio(allr, 6), variance_ratio(allr, 12)
        read = ("mean-revert" if vr6 < 0.9 else "trend" if vr6 > 1.1 else "random")
        print(f"    {reg:<8} {len(recs[reg]['rets']):>5} {vr6:>10.3f} {vr12:>11.3f}  {read}")

    print("\n[2] GAP FADE  corr(overnight gap, RTH return)   (<0 = gaps fade → MR tradeable)")
    for reg in ["Calm", "Normal", "Stress"]:
        d = pd.DataFrame({"gap": recs[reg]["gap"], "rth": recs[reg]["rth"]}).dropna()
        c = d["gap"].corr(d["rth"]) if len(d) > 30 else np.nan
        print(f"    {reg:<8} corr {c:+.3f}  (n={len(d)})")

    print("\n[3] INTRADAY REVERSAL  corr(morning move, afternoon move)  (<0 = reverts)")
    for reg in ["Calm", "Normal", "Stress"]:
        d = pd.DataFrame({"am": recs[reg]["am"], "pm": recs[reg]["pm"]}).dropna()
        c = d["am"].corr(d["pm"]) if len(d) > 30 else np.nan
        print(f"    {reg:<8} corr {c:+.3f}  (n={len(d)})")

    # verdict
    print("\n" + "-" * 66)
    calm_vr = variance_ratio(np.concatenate(recs["Calm"]["rets"]), 6) if recs["Calm"]["rets"] else np.nan
    norm_vr = variance_ratio(np.concatenate(recs["Normal"]["rets"]), 6) if recs["Normal"]["rets"] else np.nan
    mr_calm = np.isfinite(calm_vr) and calm_vr < 0.9
    mr_norm = np.isfinite(norm_vr) and norm_vr < 0.9
    if mr_calm or mr_norm:
        where = ", ".join([r for r, ok in [("Calm", mr_calm), ("Normal", mr_norm)] if ok])
        print(f"READ: mean-reversion structure present in [{where}] (VR<1) →")
        print("      worth building an MR strategy there (then Gates 2–5).")
    else:
        print("READ: no mean-reversion edge in Calm/Normal (VR≈1 or >1) →")
        print("      MR won't rescue the common-regime gap. Momentum exhausted +")
        print("      MR absent = the intraday edge space on this instrument is thin.")
    print("      (Characterization only; any strategy still needs the full gates.)")
    print("-" * 66 + "\n")


if __name__ == "__main__":
    main()
