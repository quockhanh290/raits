from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))


BASE = "lag1calm_pcloc_bottom_down_long_e1000_x1555"
AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def load_spy(path: str) -> pd.DataFrame:
    spy = pd.read_csv(path)
    spy.columns = [c.lower() for c in spy.columns]
    spy["date"] = pd.to_datetime(spy["date"]).dt.normalize()
    spy = spy.sort_values("date").set_index("date")
    spy["spy_ret1"] = spy["close"].pct_change()
    spy["spy_ret3"] = spy["close"].pct_change(3)
    spy["spy_sma50"] = spy["close"].rolling(50, min_periods=50).mean()
    spy["spy_above_sma50"] = spy["close"] > spy["spy_sma50"]
    spy["spy_rv20"] = spy["spy_ret1"].rolling(20, min_periods=20).std()
    spy["spy_rv5"] = spy["spy_ret1"].rolling(5, min_periods=5).std()
    out = spy.reset_index()
    return out[
        [
            "date",
            "close",
            "spy_ret1",
            "spy_ret3",
            "spy_above_sma50",
            "spy_rv20",
            "spy_rv5",
        ]
    ].rename(columns={"date": "spy_feature_date", "close": "spy_close_d1"})


def load_trades(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    df = df[df["variant"] == BASE].copy()
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"{path} audit failed")
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


def add_spy(trades: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    left = trades.sort_values("day").copy()
    right = spy.sort_values("spy_feature_date").copy()
    out = pd.merge_asof(
        left,
        right,
        left_on="day",
        right_on="spy_feature_date",
        direction="backward",
        allow_exact_matches=False,
    )
    if out[["spy_ret1", "spy_rv20"]].isna().any().any():
        missing_days = sorted(out.loc[out["spy_ret1"].isna(), "day"].dt.strftime("%Y-%m-%d").unique().tolist())
        raise ValueError(f"missing SPY D-1 features for days: {missing_days[:10]}")
    return out


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


def build_thresholds(is_df: pd.DataFrame) -> dict:
    d = is_df.drop_duplicates("day").copy()
    return {
        "rv20_p50": float(d["spy_rv20"].quantile(0.50)),
        "rv20_p60": float(d["spy_rv20"].quantile(0.60)),
        "rv20_p70": float(d["spy_rv20"].quantile(0.70)),
        "rv20_p80": float(d["spy_rv20"].quantile(0.80)),
        "rv5_p70": float(d["spy_rv5"].quantile(0.70)),
        "ret1_p10": float(d["spy_ret1"].quantile(0.10)),
        "ret1_p25": float(d["spy_ret1"].quantile(0.25)),
        "ret1_p75": float(d["spy_ret1"].quantile(0.75)),
    }


def masks(df: pd.DataFrame, t: dict) -> dict[str, pd.Series]:
    mes_mnq = df["inst"].isin(["MES", "MNQ"])
    ret = df["spy_ret1"]
    ret3 = df["spy_ret3"]
    rv20 = df["spy_rv20"]
    rv5 = df["spy_rv5"]
    above = df["spy_above_sma50"].astype(bool)
    return {
        "mes_mnq": mes_mnq,
        "mes_mnq_spy_down": mes_mnq & (ret <= 0.0),
        "mes_mnq_spy_not_crash": mes_mnq & (ret >= -0.015),
        "mes_mnq_spy_mild_down": mes_mnq & (ret <= 0.0) & (ret >= -0.015),
        "mes_mnq_spy_mild_down_rv70": mes_mnq & (ret <= 0.0) & (ret >= -0.015) & (rv20 <= t["rv20_p70"]),
        "mes_mnq_spy_mild_down_rv80": mes_mnq & (ret <= 0.0) & (ret >= -0.015) & (rv20 <= t["rv20_p80"]),
        "mes_mnq_spy_above50": mes_mnq & above,
        "mes_mnq_spy_above50_mild_down": mes_mnq & above & (ret <= 0.0) & (ret >= -0.015),
        "mes_mnq_rv20_le50": mes_mnq & (rv20 <= t["rv20_p50"]),
        "mes_mnq_rv20_le60": mes_mnq & (rv20 <= t["rv20_p60"]),
        "mes_mnq_rv20_le70": mes_mnq & (rv20 <= t["rv20_p70"]),
        "mes_mnq_rv20_le80": mes_mnq & (rv20 <= t["rv20_p80"]),
        "mes_mnq_rv5_le70": mes_mnq & (rv5 <= t["rv5_p70"]),
        "mes_mnq_ret1_gt_p10": mes_mnq & (ret >= t["ret1_p10"]),
        "mes_mnq_ret1_mid": mes_mnq & (ret >= t["ret1_p25"]) & (ret <= t["ret1_p75"]),
        "mes_mnq_ret3_down": mes_mnq & (ret3 <= 0.0),
        "mes_mnq_ret3_mild_down": mes_mnq & (ret3 <= 0.0) & (ret3 >= -0.03),
        "mes_mnq_ret3_down_rv70": mes_mnq & (ret3 <= 0.0) & (rv20 <= t["rv20_p70"]),
    }


def summarize(df: pd.DataFrame, window: str, t: dict) -> pd.DataFrame:
    rows = []
    for name, mask in masks(df, t).items():
        g = df[mask.fillna(False)].copy()
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        by_inst = g.groupby("inst")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        rows.append(
            {
                "window": window,
                "filter": name,
                **st,
                "pos_years": int((by_year > 0).sum()),
                "years": int(len(by_year)),
                "pos_inst": int((by_inst > 0).sum()),
                "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 and not by_year.empty else 1.0,
                "mes_net": float(by_inst.get("MES", 0.0)),
                "mnq_net": float(by_inst.get("MNQ", 0.0)),
                "audit": int(g[AUDIT_COLS].sum().sum()) if not g.empty else 0,
                "spy_ret1_med": float(g["spy_ret1"].median()) if not g.empty else np.nan,
                "spy_rv20_med": float(g["spy_rv20"].median()) if not g.empty else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def select(summary: pd.DataFrame, limit: int) -> list[str]:
    keep = summary[
        (summary["n"] >= 200)
        & (summary["net"] >= 5_000)
        & (summary["pf"] >= 1.15)
        & (summary["pos_years"] >= 5)
        & (summary["pos_inst"] >= 2)
        & (summary["top_year_share"] <= 0.75)
        & (summary["audit"] == 0)
    ]
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


def print_summary(title: str, summary: pd.DataFrame, filters: list[str] | None = None) -> None:
    print(f"\n=== {title} ===")
    tbl = summary if filters is None else summary[summary["filter"].isin(filters)]
    for _, r in tbl.head(40).iterrows():
        print(
            f"{r['filter']:<32} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"dd=${r['maxdd']:>7,.0f} posY={int(r['pos_years'])}/{int(r['years'])} "
            f"posI={int(r['pos_inst'])} MES/MNQ=${r['mes_net']:.0f}/{r['mnq_net']:.0f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spy", default="spy_daily_live.csv")
    ap.add_argument("--is-trades", default="scratch/calm_causal_lag1_excavation_is.csv")
    ap.add_argument("--oos-2025", default="scratch/calm_causal_lag1_excavation_2025.csv")
    ap.add_argument("--oos-2026", default="scratch/calm_causal_lag1_excavation_2026.csv")
    ap.add_argument("--out-prefix", default="scratch/calm_causal_pcloc_spy_context")
    ap.add_argument("--select-limit", type=int, default=8)
    ap.add_argument("--bootstrap-iters", type=int, default=5000)
    args = ap.parse_args()

    spy = load_spy(args.spy)
    is_df = add_spy(load_trades(args.is_trades), spy)
    t = build_thresholds(is_df)
    pd.DataFrame([t]).to_csv(f"{args.out_prefix}_thresholds.csv", index=False)
    is_df.to_csv(f"{args.out_prefix}_is.csv", index=False)
    s_is = summarize(is_df, "is", t)
    s_is.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print("thresholds=" + ", ".join(f"{k}={v:.6f}" for k, v in t.items()))
    print_summary("IS SPY context", s_is)
    selected = select(s_is, args.select_limit)
    print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))
    if not selected:
        return 0

    o25 = add_spy(load_trades(args.oos_2025), spy)
    o26 = add_spy(load_trades(args.oos_2026), spy)
    pooled = pd.concat([o25, o26], ignore_index=True)
    for name, df in [("2025", o25), ("2026_sanity", o26), ("pooled_sanity", pooled)]:
        df.to_csv(f"{args.out_prefix}_{name}.csv", index=False)
        s = summarize(df, name, t)
        s.to_csv(f"{args.out_prefix}_{name}_summary.csv", index=False)
        print_summary(name, s, selected)

    rng = np.random.default_rng(20260821)
    rows = []
    for filt in selected:
        for name, df in [("2025", o25), ("pooled_sanity", pooled)]:
            g = df[masks(df, t)[filt].fillna(False)]
            rows.append({"window": name, "filter": filt, **stats(g), **bootstrap(g, args.bootstrap_iters, rng)})
    boot = pd.DataFrame(rows).sort_values(["window", "net"], ascending=[True, False])
    boot.to_csv(f"{args.out_prefix}_bootstrap.csv", index=False)
    print("\n=== Bootstrap ===")
    print(boot.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
