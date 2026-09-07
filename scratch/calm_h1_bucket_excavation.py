from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd


WINDOWS = {
    "is": "scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv",
    "2025": "scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2025.csv",
    "2026": "scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2026.csv",
}
RAW_VARIANT = "on_neg_fade_raw_x1555"


BUCKETS = [
    ("lt_m020", -math.inf, -0.020, "< -2.0%"),
    ("m020_m010", -0.020, -0.010, "-2.0%..-1.0%"),
    ("m010_m005", -0.010, -0.005, "-1.0%..-0.5%"),
    ("m005_m002", -0.005, -0.002, "-0.5%..-0.2%"),
    ("m002_m001", -0.002, -0.001, "-0.2%..-0.1%"),
    ("m001_000", -0.001, 0.0, "-0.1%..0.0%"),
]


def assign_bucket(x: float) -> str | None:
    for name, lo, hi, _ in BUCKETS:
        if lo < x <= hi:
            return name
    return None


def bucket_label(name: str) -> str:
    return {b[0]: b[3] for b in BUCKETS}[name]


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trades": 0, "days": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    return {
        "trades": int(len(df)),
        "days": int(df["day"].nunique()),
        "net": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "avg": float(pnl.mean()),
        "maxdd": dd,
    }


def day_bootstrap(df: pd.DataFrame, iters: int, rng: np.random.Generator) -> dict:
    if df.empty:
        return {"p_pos": 0.0, "p05": 0.0, "p50": 0.0, "p95": 0.0}
    daily = df.groupby("day")["pnl"].sum().to_numpy(dtype=float)
    draws = rng.choice(daily, size=(iters, len(daily)), replace=True).sum(axis=1)
    return {
        "p_pos": float((draws > 0).mean()),
        "p05": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
    }


def load_window(path: str, window: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"variant", "inst", "day", "year", "pnl", "overnight_ret", "outside_exit_bar", "outside_entry_bar", "signal_after_entry"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{path} missing columns: {missing}")
    audit = df[["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]].sum()
    if int(audit.sum()) != 0:
        raise ValueError(f"{path} audit failed: {audit.to_dict()}")
    df = df[df["variant"] == RAW_VARIANT].copy()
    df["window"] = window
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["bucket"] = df["overnight_ret"].astype(float).map(assign_bucket)
    df = df[df["bucket"].notna()].copy()
    return df


def summarize(df: pd.DataFrame, label: str, iters: int, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for bucket, g in df.groupby("bucket", sort=False):
        st = stats(g)
        bs = day_bootstrap(g, iters, rng)
        by_inst = g.groupby("inst")["pnl"].sum()
        by_year = g.groupby("year")["pnl"].sum()
        rows.append({
            "window": label,
            "bucket": bucket,
            "bucket_label": bucket_label(bucket),
            **st,
            "p_pos": bs["p_pos"],
            "ci05": bs["p05"],
            "ci50": bs["p50"],
            "ci95": bs["p95"],
            "pos_years": int((by_year > 0).sum()),
            "years": int(by_year.shape[0]),
            "pos_inst": int((by_inst > 0).sum()),
            "mes_net": float(by_inst.get("MES", 0.0)),
            "mnq_net": float(by_inst.get("MNQ", 0.0)),
            "mym_net": float(by_inst.get("MYM", 0.0)),
        })
    return pd.DataFrame(rows)


def print_table(title: str, tbl: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    order = [b[0] for b in BUCKETS]
    tbl = tbl.set_index("bucket").reindex([b for b in order if b in set(tbl["bucket"])]).reset_index()
    for _, r in tbl.iterrows():
        print(
            f"{r['bucket_label']:<14} n={int(r['trades']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>6.2f} "
            f"p_pos={r['p_pos']:>5.3f} ci05/50/95=${r['ci05']:>7,.0f}/${r['ci50']:>7,.0f}/${r['ci95']:>7,.0f} "
            f"posY={int(r['pos_years'])}/{int(r['years'])} posI={int(r['pos_inst'])}"
        )


def print_detail(df: pd.DataFrame, title: str) -> None:
    print(f"\n=== {title} detail ===")
    for bucket in [b[0] for b in BUCKETS]:
        g = df[df["bucket"] == bucket]
        if g.empty:
            continue
        print(f"\n-- {bucket_label(bucket)} --")
        for inst, x in g.groupby("inst"):
            st = stats(x)
            print(f"  {inst:<4} n={st['trades']:>4} net=${st['net']:>8,.0f} pf={st['pf']:>5.2f} avg=${st['avg']:>6.2f}")
        by_year = g.groupby("year")["pnl"].sum()
        yrs = " ".join(f"{int(y)}:${v:,.0f}" for y, v in by_year.items())
        print(f"  years {yrs}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap-iters", type=int, default=5000)
    ap.add_argument("--out-prefix", default="scratch/calm_h1_bucket_excavation")
    args = ap.parse_args()

    rng = np.random.default_rng(20260821)
    frames = []
    for window, path in WINDOWS.items():
        frames.append(load_window(path, window))
    all_df = pd.concat(frames, ignore_index=True)
    oos = all_df[all_df["window"].isin(["2025", "2026"])].copy()

    summaries = []
    for window in ["is", "2025", "2026"]:
        df = all_df[all_df["window"] == window]
        summary = summarize(df, window, args.bootstrap_iters, rng)
        summaries.append(summary)
        print_table(window, summary)
        print_detail(df, window)

    pooled_summary = summarize(oos, "oos_pooled", args.bootstrap_iters, rng)
    summaries.append(pooled_summary)
    print_table("oos_pooled", pooled_summary)
    print_detail(oos, "oos_pooled")

    out = pd.concat(summaries, ignore_index=True)
    out_path = f"{args.out_prefix}_summary.csv"
    trades_path = f"{args.out_prefix}_trades.csv"
    out.to_csv(out_path, index=False)
    all_df.to_csv(trades_path, index=False)
    print(f"\nwrote {out_path}")
    print(f"wrote {trades_path}")

    print("\n=== H1 read ===")
    target = out[(out["window"].isin(["is", "2025", "2026", "oos_pooled"])) & (out["bucket"] == "m010_m005")]
    stable = out[(out["window"].isin(["is", "2025", "2026", "oos_pooled"])) & (out["bucket"] == "m005_m002")]
    for name, tbl in [("-1.0%..-0.5%", target), ("-0.5%..-0.2%", stable)]:
        vals = " | ".join(f"{r.window}: net=${r.net:,.0f}, p_pos={r.p_pos:.3f}" for r in tbl.itertuples())
        print(f"{name}: {vals}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
