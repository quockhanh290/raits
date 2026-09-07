from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]
BASE = "lag1calm_pcloc_bottom_down_long_e1000_x1555"


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


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    df = df[df["variant"] == BASE].copy()
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"{path} audit failed")
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


def masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    all_true = pd.Series(True, index=df.index)
    out = {"base_all": all_true}
    out["no_mym"] = df["inst"].isin(["MES", "MNQ"])
    out["mes_mnq"] = df["inst"].isin(["MES", "MNQ"])
    out["mnq_only"] = df["inst"].eq("MNQ")
    out["mes_only"] = df["inst"].eq("MES")
    out["loc25"] = df["prev_close_loc"] <= 0.25
    out["loc20"] = df["prev_close_loc"] <= 0.20
    out["loc25_no_mym"] = (df["prev_close_loc"] <= 0.25) & df["inst"].isin(["MES", "MNQ"])
    out["loc20_no_mym"] = (df["prev_close_loc"] <= 0.20) & df["inst"].isin(["MES", "MNQ"])
    out["no_big_gap"] = df["overnight_ret"] >= -0.010
    out["small_gap"] = (df["overnight_ret"] >= -0.010) & (df["overnight_ret"] <= 0.010)
    out["no_upper_open"] = df["open_loc"] <= 2.0 / 3.0
    out["inside_open"] = (df["open_loc"] >= 0.0) & (df["open_loc"] <= 1.0)
    out["loc25_no_big_gap"] = (df["prev_close_loc"] <= 0.25) & (df["overnight_ret"] >= -0.010)
    out["loc25_small_gap"] = (df["prev_close_loc"] <= 0.25) & (df["overnight_ret"] >= -0.010) & (df["overnight_ret"] <= 0.010)
    return out


def summarize(df: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    for name, mask in masks(df).items():
        g = df[mask.fillna(False)].copy()
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        by_inst = g.groupby("inst")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        rows.append(
            {
                "window": window,
                "variant": f"{BASE}__{name}",
                "filter": name,
                **st,
                "pos_years": int((by_year > 0).sum()),
                "years": int(len(by_year)),
                "pos_inst": int((by_inst > 0).sum()),
                "mes_net": float(by_inst.get("MES", 0.0)),
                "mnq_net": float(by_inst.get("MNQ", 0.0)),
                "mym_net": float(by_inst.get("MYM", 0.0)),
                "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 and not by_year.empty else 1.0,
                "audit": int(g[AUDIT_COLS].sum().sum()) if not g.empty else 0,
            }
        )
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def select(summary: pd.DataFrame, limit: int) -> list[str]:
    keep = summary[
        (summary["n"] >= 250)
        & (summary["net"] >= 5_000)
        & (summary["pf"] >= 1.15)
        & (summary["pos_years"] >= 5)
        & (summary["pos_inst"] >= 2)
        & (summary["top_year_share"] <= 0.75)
        & (summary["audit"] == 0)
    ].copy()
    return keep.sort_values(["net", "pf"], ascending=False)["filter"].head(limit).tolist()


def bootstrap(df: pd.DataFrame, iters: int, rng: np.random.Generator) -> dict:
    if df.empty:
        return {"p05": 0.0, "p50": 0.0, "p95": 0.0, "p_pos": 0.0}
    daily = df.groupby("day")["pnl"].sum().to_numpy(dtype=float)
    draws = rng.choice(daily, size=(iters, len(daily)), replace=True).sum(axis=1)
    return {
        "p05": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
        "p_pos": float((draws > 0).mean()),
    }


def print_summary(title: str, summary: pd.DataFrame, filters: list[str] | None = None, limit: int = 30) -> None:
    print(f"\n=== {title} ===")
    tbl = summary if filters is None else summary[summary["filter"].isin(filters)]
    for _, r in tbl.head(limit).iterrows():
        print(
            f"{r['filter']:<18} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"dd=${r['maxdd']:>7,.0f} posY={int(r['pos_years'])}/{int(r['years'])} "
            f"posI={int(r['pos_inst'])} MES/MNQ/MYM=${r['mes_net']:.0f}/${r['mnq_net']:.0f}/${r['mym_net']:.0f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-trades", default="scratch/calm_causal_lag1_excavation_is.csv")
    ap.add_argument("--oos-2025", default="scratch/calm_causal_lag1_excavation_2025.csv")
    ap.add_argument("--oos-2026", default="scratch/calm_causal_lag1_excavation_2026.csv")
    ap.add_argument("--out-prefix", default="scratch/calm_causal_pcloc_refine")
    ap.add_argument("--select-limit", type=int, default=4)
    ap.add_argument("--bootstrap-iters", type=int, default=5000)
    args = ap.parse_args()

    is_df = load(args.is_trades)
    s_is = summarize(is_df, "is")
    s_is.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print_summary("IS refine candidates", s_is)
    selected = select(s_is, args.select_limit)
    print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))
    if not selected:
        return 0

    o25 = load(args.oos_2025)
    o26 = load(args.oos_2026)
    pooled = pd.concat([o25, o26], ignore_index=True)
    for name, df in [("2025", o25), ("2026", o26), ("oos_pooled", pooled)]:
        s = summarize(df, name)
        s.to_csv(f"{args.out_prefix}_{name}_summary.csv", index=False)
        print_summary(name, s, selected)
    rng = np.random.default_rng(20260821)
    rows = []
    for filt in selected:
        g = pooled[masks(pooled)[filt].fillna(False)]
        rows.append({"filter": filt, **stats(g), **bootstrap(g, args.bootstrap_iters, rng)})
    boot = pd.DataFrame(rows).sort_values("net", ascending=False)
    boot.to_csv(f"{args.out_prefix}_oos_bootstrap.csv", index=False)
    print_summary("OOS selected bootstrap stats base fields", boot.rename(columns={"filter": "variant"}), None, 0)
    print("\n=== OOS bootstrap ===")
    print(boot.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
