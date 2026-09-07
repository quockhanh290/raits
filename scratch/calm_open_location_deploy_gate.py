from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import BASKET


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "days": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    return {
        "n": int(len(df)),
        "days": int(df["day"].nunique()),
        "net": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "avg": float(pnl.mean()),
        "maxdd": float((eq.cummax() - eq).max()) if len(eq) else 0.0,
    }


def bootstrap(df: pd.DataFrame, cluster: str, iters: int, rng: np.random.Generator) -> dict:
    if df.empty:
        return {"clusters": 0, "p_pos": 0.0, "p05": 0.0, "p50": 0.0, "p95": 0.0}
    work = df.copy()
    if cluster == "day":
        key = work["day"]
    elif cluster == "month":
        key = work["day"].dt.to_period("M").astype(str)
    else:
        raise ValueError(cluster)
    clustered = work.groupby(key)["pnl"].sum().to_numpy(dtype=float)
    draws = rng.choice(clustered, size=(iters, len(clustered)), replace=True).sum(axis=1)
    return {
        "clusters": int(len(clustered)),
        "p_pos": float((draws > 0).mean()),
        "p05": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
    }


def slippage_adjust(df: pd.DataFrame, new_ticks_per_side: float, base_ticks_per_side: float) -> pd.DataFrame:
    out = df.copy()
    deltas = {}
    for inst, contract in BASKET.items():
        deltas[inst] = 2.0 * (new_ticks_per_side - base_ticks_per_side) * contract.tick * contract.point_value
    out["pnl"] = out["pnl"] - out["inst"].map(deltas).fillna(0.0)
    return out


def load(path: str, variant: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    df = df[df["variant"] == variant].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


def contribution_rows(df: pd.DataFrame, window: str) -> list[dict]:
    rows = []
    for key_name, group_col in [("year", "year"), ("inst", "inst")]:
        for key, g in df.groupby(group_col):
            rows.append({"window": window, "group": key_name, "key": str(key), **stats(g)})
    return rows


def gate_report(
    is_df: pd.DataFrame,
    o25: pd.DataFrame,
    o26: pd.DataFrame,
    folds: pd.DataFrame,
    base_ticks: float,
    iters: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(20260821)
    pooled = pd.concat([o25, o26], ignore_index=True)
    windows = [("is", is_df), ("2025", o25), ("2026", o26), ("oos_pooled", pooled)]

    summary_rows = []
    for window, df in windows:
        row = {"window": window, **stats(df)}
        row.update({f"audit_{c}": int(df[c].sum()) for c in AUDIT_COLS})
        by_inst = df.groupby("inst")["pnl"].sum()
        row["pos_inst"] = int((by_inst > 0).sum())
        row["top_inst_share"] = float(by_inst.max() / row["net"]) if row["net"] > 0 and not by_inst.empty else 1.0
        for cluster in ("day", "month"):
            bs = bootstrap(df, cluster, iters, rng)
            for k, v in bs.items():
                row[f"boot_{cluster}_{k}"] = v
        summary_rows.append(row)
    summary = pd.DataFrame(summary_rows)

    slip_rows = []
    for ticks in (2.0, 3.0, 4.0, 6.0):
        for window, df in windows:
            adj = slippage_adjust(df, ticks, base_ticks)
            slip_rows.append({"slippage_ticks_per_side": ticks, "window": window, **stats(adj)})
    slip = pd.DataFrame(slip_rows)

    contrib = pd.DataFrame(
        contribution_rows(is_df, "is")
        + contribution_rows(o25, "2025")
        + contribution_rows(o26, "2026")
        + contribution_rows(pooled, "oos_pooled")
    )

    meaningful_folds = int(folds["meaningful_test"].sum())
    winner_matches = int((folds["selected"] == folds["test_winner"]).sum())
    oos = summary[summary["window"] == "oos_pooled"].iloc[0]
    reasons = []
    if int(summary[[f"audit_{c}" for c in AUDIT_COLS]].sum().sum()) != 0:
        reasons.append("audit_failed")
    if meaningful_folds < len(folds):
        reasons.append("protocol_has_nonmeaningful_fold")
    if winner_matches < 2:
        reasons.append("selector_not_stable")
    if float(oos["boot_day_p05"]) <= 0:
        reasons.append("oos_day_bootstrap_crosses_zero")
    if float(oos["boot_month_p05"]) <= 0:
        reasons.append("oos_month_bootstrap_crosses_zero")
    slip4 = slip[(slip["window"] == "oos_pooled") & (slip["slippage_ticks_per_side"] == 4.0)].iloc[0]
    if float(slip4["net"]) <= 0 or float(slip4["pf"]) < 1.10:
        reasons.append("slippage4_weak")
    summary["deploy_gate_reasons"] = ""
    summary.loc[summary["window"] == "oos_pooled", "deploy_gate_reasons"] = ",".join(reasons) if reasons else "PASS"
    summary.loc[summary["window"] == "oos_pooled", "deploy_gate"] = "PASS" if not reasons else "FAIL"
    return summary, slip, contrib


def print_table(summary: pd.DataFrame, slip: pd.DataFrame, contrib: pd.DataFrame) -> None:
    print("\n=== standalone deploy gate summary ===")
    for _, r in summary.iterrows():
        print(
            f"{r['window']:<10} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"dd=${r['maxdd']:>7,.0f} posI={int(r['pos_inst'])} "
            f"bootDay p05/50/95=${r['boot_day_p05']:>7,.0f}/${r['boot_day_p50']:>7,.0f}/${r['boot_day_p95']:>7,.0f} "
            f"bootMonth p05=${r['boot_month_p05']:>7,.0f} "
            f"audit={int(r['audit_outside_exit_bar'])}/{int(r['audit_outside_entry_bar'])}/{int(r['audit_signal_after_entry'])}"
        )
    oos = summary[summary["window"] == "oos_pooled"].iloc[0]
    print(f"\ndeploy_gate={oos.get('deploy_gate', '')} reasons={oos.get('deploy_gate_reasons', '')}")

    print("\n=== slippage sensitivity, oos pooled ===")
    for _, r in slip[slip["window"] == "oos_pooled"].iterrows():
        print(f"{r['slippage_ticks_per_side']:.0f} ticks/side n={int(r['n'])} net=${r['net']:,.0f} pf={r['pf']:.2f} avg=${r['avg']:.2f}")

    print("\n=== oos contribution ===")
    for _, r in contrib[contrib["window"].isin(["2025", "2026", "oos_pooled"])].iterrows():
        print(f"{r['window']:<10} {r['group']:<4} {r['key']:<6} n={int(r['n']):>4} net=${r['net']:>8,.0f} pf={r['pf']:>5.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="openloc_lower_third_long_e1000_x1555_nostop")
    ap.add_argument("--is-risk", default="scratch/calm_open_location_risk_probe_is.csv")
    ap.add_argument("--risk-2025", default="scratch/calm_open_location_risk_probe_2025.csv")
    ap.add_argument("--risk-2026", default="scratch/calm_open_location_risk_probe_2026.csv")
    ap.add_argument("--folds", default="scratch/calm_open_location_protocol_liveable_folds.csv")
    ap.add_argument("--base-slippage-ticks", type=float, default=2.0)
    ap.add_argument("--bootstrap-iters", type=int, default=10000)
    ap.add_argument("--out-prefix", default="scratch/calm_open_location_deploy_gate")
    args = ap.parse_args()

    is_df = load(args.is_risk, args.variant)
    o25 = load(args.risk_2025, args.variant)
    o26 = load(args.risk_2026, args.variant)
    folds = pd.read_csv(args.folds)
    summary, slip, contrib = gate_report(is_df, o25, o26, folds, args.base_slippage_ticks, args.bootstrap_iters)
    summary.to_csv(f"{args.out_prefix}_summary.csv", index=False)
    slip.to_csv(f"{args.out_prefix}_slippage.csv", index=False)
    contrib.to_csv(f"{args.out_prefix}_contribution.csv", index=False)
    print_table(summary, slip, contrib)
    print(f"\nwrote {args.out_prefix}_summary.csv")
    print(f"wrote {args.out_prefix}_slippage.csv")
    print(f"wrote {args.out_prefix}_contribution.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
