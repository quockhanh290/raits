from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import BASKET


BASE = "lag1calm_pcloc_bottom_down_long_e1000_x1555"
AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    df = df[df["variant"] == BASE].copy()
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"{path} audit failed")
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["month"] = df["day"].dt.to_period("M").astype(str)
    df["point_value"] = df["inst"].map({k: v.point_value for k, v in BASKET.items()})
    df["tick_value"] = df["inst"].map({k: v.tick_value for k, v in BASKET.items()})
    df["est_margin"] = df["inst"].map({k: v.est_margin for k, v in BASKET.items()})
    df["gross"] = (df["exit"].astype(float) - df["entry"].astype(float)) * df["point_value"]
    df["cost"] = df["gross"] - df["pnl"].astype(float)
    df["move_pct"] = df["exit"].astype(float) / df["entry"].astype(float) - 1.0
    df["pnl_per_margin"] = df["pnl"].astype(float) / df["est_margin"]
    df["gross_per_margin"] = df["gross"] / df["est_margin"]
    return df


def maxdd_by_day(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    return float((eq.cummax() - eq).max()) if len(eq) else 0.0


def summarize_group(g: pd.DataFrame) -> dict:
    pnl = g["pnl"].astype(float)
    gross = g["gross"].astype(float)
    cost = g["cost"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    by_year = g.groupby("year")["pnl"].sum()
    by_month = g.groupby("month")["pnl"].sum()
    return {
        "n": int(len(g)),
        "days": int(g["day"].nunique()),
        "net": float(pnl.sum()),
        "gross": float(gross.sum()),
        "cost": float(cost.sum()),
        "pf": gw / gl if gl else math.inf,
        "avg": float(pnl.mean()) if len(g) else 0.0,
        "gross_avg": float(gross.mean()) if len(g) else 0.0,
        "cost_avg": float(cost.mean()) if len(g) else 0.0,
        "cost_to_gross": float(cost.sum() / gross.sum()) if gross.sum() > 0 else math.inf,
        "win_rate": float((pnl > 0).mean()) if len(g) else 0.0,
        "maxdd": maxdd_by_day(g),
        "pos_years": int((by_year > 0).sum()),
        "years": int(len(by_year)),
        "pos_months": int((by_month > 0).sum()),
        "months": int(len(by_month)),
        "avg_pnl_per_margin_bp": float(g["pnl_per_margin"].mean() * 10_000) if len(g) else 0.0,
        "avg_gross_per_margin_bp": float(g["gross_per_margin"].mean() * 10_000) if len(g) else 0.0,
        "median_move_bp": float(g["move_pct"].median() * 10_000) if len(g) else 0.0,
        "avg_abs_move_bp": float(g["move_pct"].abs().mean() * 10_000) if len(g) else 0.0,
    }


def instrument_summary(df: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    for inst, g in df.groupby("inst"):
        rows.append({"window": window, "group": inst, **summarize_group(g)})
    rows.append({"window": window, "group": "MES+MNQ", **summarize_group(df[df["inst"].isin(["MES", "MNQ"])])})
    rows.append({"window": window, "group": "ALL", **summarize_group(df)})
    return pd.DataFrame(rows).sort_values(["window", "group"])


def year_inst_matrix(df: pd.DataFrame, window: str) -> pd.DataFrame:
    piv = df.pivot_table(index="year", columns="inst", values="pnl", aggfunc="sum", fill_value=0.0)
    for col in ["MES", "MNQ", "MYM"]:
        if col not in piv.columns:
            piv[col] = 0.0
    piv["MES+MNQ"] = piv["MES"] + piv["MNQ"]
    piv["ALL"] = piv["MES"] + piv["MNQ"] + piv["MYM"]
    piv.insert(0, "window", window)
    return piv.reset_index()


def bootstrap_inst(df: pd.DataFrame, window: str, iters: int = 10_000) -> pd.DataFrame:
    rng = np.random.default_rng(20260821)
    rows = []
    for group, g in [
        ("MES", df[df["inst"].eq("MES")]),
        ("MNQ", df[df["inst"].eq("MNQ")]),
        ("MYM", df[df["inst"].eq("MYM")]),
        ("MES+MNQ", df[df["inst"].isin(["MES", "MNQ"])]),
        ("ALL", df),
    ]:
        daily = g.groupby("day")["pnl"].sum().to_numpy(dtype=float)
        if len(daily) == 0:
            draws = np.array([0.0])
        else:
            draws = rng.choice(daily, size=(iters, len(daily)), replace=True).sum(axis=1)
        rows.append(
            {
                "window": window,
                "group": group,
                "days": int(len(daily)),
                "p05": float(np.percentile(draws, 5)),
                "p50": float(np.percentile(draws, 50)),
                "p95": float(np.percentile(draws, 95)),
                "p_pos": float((draws > 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def permutation_mym_vs_mesmnq(is_df: pd.DataFrame, iters: int = 20_000) -> dict:
    """IS-only test: is MYM average trade lower than the MES+MNQ pool?"""
    g = is_df[is_df["inst"].isin(["MES", "MNQ", "MYM"])].copy()
    mym_n = int(g["inst"].eq("MYM").sum())
    observed = float(g[g["inst"].eq("MYM")]["pnl"].mean() - g[g["inst"].isin(["MES", "MNQ"])]["pnl"].mean())
    vals = g["pnl"].to_numpy(dtype=float).copy()
    rng = np.random.default_rng(20260821)
    diffs = np.empty(iters)
    for i in range(iters):
        rng.shuffle(vals)
        mym = vals[:mym_n]
        other = vals[mym_n:]
        diffs[i] = mym.mean() - other.mean()
    return {
        "observed_mym_minus_mesmnq_avg": observed,
        "p_lower_or_equal_observed": float((diffs <= observed).mean()),
        "perm_p05": float(np.percentile(diffs, 5)),
        "perm_p50": float(np.percentile(diffs, 50)),
        "perm_p95": float(np.percentile(diffs, 95)),
    }


def write(path: str, df: pd.DataFrame) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def main() -> int:
    is_df = load("scratch/calm_causal_pcloc_intraday_confirm_is.csv")
    o25 = load("scratch/calm_causal_pcloc_intraday_confirm_2025.csv")
    o26 = load("scratch/calm_causal_pcloc_intraday_confirm_2026.csv")
    oos = pd.concat([o25, o26], ignore_index=True)

    summaries = pd.concat(
        [
            instrument_summary(is_df, "is_2018_2024"),
            instrument_summary(o25, "oos_2025"),
            instrument_summary(o26, "oos_2026"),
            instrument_summary(oos, "oos_pooled"),
        ],
        ignore_index=True,
    )
    years = pd.concat(
        [
            year_inst_matrix(is_df, "is_2018_2024"),
            year_inst_matrix(o25, "oos_2025"),
            year_inst_matrix(o26, "oos_2026"),
        ],
        ignore_index=True,
    )
    boot = pd.concat(
        [
            bootstrap_inst(is_df, "is_2018_2024"),
            bootstrap_inst(oos, "oos_pooled"),
        ],
        ignore_index=True,
    )
    perm = pd.DataFrame([permutation_mym_vs_mesmnq(is_df)])

    write("scratch/calm_causal_pcloc_mym_rationale_summary.csv", summaries)
    write("scratch/calm_causal_pcloc_mym_rationale_years.csv", years)
    write("scratch/calm_causal_pcloc_mym_rationale_bootstrap.csv", boot)
    write("scratch/calm_causal_pcloc_mym_rationale_permutation.csv", perm)

    print("\n=== Instrument rationale summary ===")
    cols = [
        "window",
        "group",
        "n",
        "net",
        "pf",
        "avg",
        "gross_avg",
        "cost_avg",
        "cost_to_gross",
        "maxdd",
        "pos_years",
        "years",
        "pos_months",
        "months",
        "avg_pnl_per_margin_bp",
        "median_move_bp",
    ]
    print(summaries[cols].to_string(index=False))
    print("\n=== Year matrix ===")
    print(years.to_string(index=False))
    print("\n=== Bootstrap ===")
    print(boot.to_string(index=False))
    print("\n=== IS permutation: MYM avg vs MES+MNQ avg ===")
    print(perm.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
