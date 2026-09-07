from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd


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


def meaningful_years(df: pd.DataFrame) -> tuple[int, int]:
    if df.empty:
        return 0, 0
    y = df.groupby("year").agg(trades=("pnl", "size"), days=("day", "nunique"), net=("pnl", "sum"))
    y = y[(y["trades"] >= 20) | (y["days"] >= 10)]
    return int((y["net"] > 0).sum()), int(len(y))


def load_trades(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing audit columns: {missing}")
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError("audit counters not clean")
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    for c in [
        "prior_up",
        "open_lower_third",
        "bucket_m005_m002",
        "open_inside_prev_range",
        "spy_above50",
        "spy_rv20_le20",
    ]:
        df[c] = df[c] == True
    return df


def pick(g: pd.DataFrame, rule: str) -> pd.DataFrame:
    if g.empty:
        return g
    if rule == "all":
        return g
    if rule == "most_negative_on":
        return g.sort_values(["overnight_ret", "inst"], ascending=[True, True]).head(1)
    if rule == "least_negative_on":
        return g.sort_values(["overnight_ret", "inst"], ascending=[False, True]).head(1)
    if rule == "lowest_open_loc":
        return g.sort_values(["open_loc_prev_range", "inst"], ascending=[True, True]).head(1)
    if rule == "highest_prior_ret":
        return g.sort_values(["prev_ret", "inst"], ascending=[False, True]).head(1)
    if rule == "prior_up_most_negative":
        h = g[g["prior_up"]]
        return pick(h, "most_negative_on")
    if rule == "open_lower_most_negative":
        h = g[g["open_lower_third"]]
        return pick(h, "most_negative_on")
    if rule == "seed_m005_m002_most_negative":
        h = g[g["bucket_m005_m002"]]
        return pick(h, "most_negative_on")
    if rule == "seed_m005_m002_lowest_open":
        h = g[g["bucket_m005_m002"]]
        return pick(h, "lowest_open_loc")
    if rule == "max2_most_negative":
        return g.sort_values(["overnight_ret", "inst"], ascending=[True, True]).head(2)
    if rule == "max2_lowest_open":
        return g.sort_values(["open_loc_prev_range", "inst"], ascending=[True, True]).head(2)
    raise KeyError(rule)


RULES = [
    "all",
    "most_negative_on",
    "least_negative_on",
    "lowest_open_loc",
    "highest_prior_ret",
    "prior_up_most_negative",
    "open_lower_most_negative",
    "seed_m005_m002_most_negative",
    "seed_m005_m002_lowest_open",
    "max2_most_negative",
    "max2_lowest_open",
]


def apply_rule(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    parts = []
    for _, g in df.groupby("day", sort=True):
        p = pick(g, rule)
        if not p.empty:
            parts.append(p)
    if not parts:
        return df.iloc[0:0].copy()
    out = pd.concat(parts, ignore_index=True)
    out["variant"] = rule
    return out


def summarize(df: pd.DataFrame, window: str, iters: int, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for rule in RULES:
        g = apply_rule(df, rule)
        st = stats(g)
        bs = day_bootstrap(g, iters, rng)
        py, my = meaningful_years(g)
        by_inst = g.groupby("inst")["pnl"].sum() if not g.empty else pd.Series(dtype=float)
        rows.append({
            "window": window,
            "variant": rule,
            **st,
            "p_pos": bs["p_pos"],
            "ci05": bs["p05"],
            "ci50": bs["p50"],
            "ci95": bs["p95"],
            "pos_meaningful_years": py,
            "meaningful_years": my,
            "pos_inst": int((by_inst > 0).sum()),
            "mes_net": float(by_inst.get("MES", 0.0)),
            "mnq_net": float(by_inst.get("MNQ", 0.0)),
            "mym_net": float(by_inst.get("MYM", 0.0)),
        })
    return pd.DataFrame(rows)


def select_is(summary: pd.DataFrame, limit: int) -> list[str]:
    s = summary[summary["window"] == "is"].copy()
    keep = s[
        (s["n"] >= 200)
        & (s["net"] >= 4_000)
        & (s["pf"] >= 1.15)
        & (s["pos_meaningful_years"] >= 5)
        & (s["pos_inst"] >= 2)
    ].copy()
    return keep.sort_values(["net", "pf"], ascending=False)["variant"].head(limit).tolist()


def print_rows(title: str, summary: pd.DataFrame, variants: list[str]) -> None:
    print(f"\n=== {title} ===")
    for window in ["is", "2025", "2026", "oos_pooled"]:
        print(f"-- {window} --")
        tbl = summary[(summary["window"] == window) & (summary["variant"].isin(variants))].sort_values("net", ascending=False)
        for _, r in tbl.iterrows():
            print(
                f"{r['variant']:<30} n={int(r['n']):>4} days={int(r['days']):>3} "
                f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>6.2f} "
                f"p={r['p_pos']:>5.3f} ci05/95=${r['ci05']:>7,.0f}/${r['ci95']:>7,.0f} "
                f"posY={int(r['pos_meaningful_years'])}/{int(r['meaningful_years'])} posI={int(r['pos_inst'])}"
            )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", default="scratch/calm_context_excavation_trades.csv")
    ap.add_argument("--bootstrap-iters", type=int, default=5000)
    ap.add_argument("--select-limit", type=int, default=5)
    ap.add_argument("--out-prefix", default="scratch/calm_rotation_probe")
    args = ap.parse_args()
    rng = np.random.default_rng(20260821)
    df = load_trades(args.trades)
    summaries = []
    for window in ["is", "2025", "2026"]:
        summaries.append(summarize(df[df["window"] == window], window, args.bootstrap_iters, rng))
    summaries.append(summarize(df[df["window"].isin(["2025", "2026"])], "oos_pooled", args.bootstrap_iters, rng))
    summary = pd.concat(summaries, ignore_index=True)
    selected = select_is(summary, args.select_limit)
    print("\n=== selected before OOS ===")
    print(",".join(selected) if selected else "NONE")
    display = list(dict.fromkeys(selected + ["all", "max2_most_negative", "seed_m005_m002_most_negative"]))
    print_rows("rotation selected", summary, display)
    summary_path = f"{args.out_prefix}_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"\nwrote {summary_path}")
    print("\n=== verdict ===")
    survivors = []
    for v in selected:
        o = summary[(summary["window"] == "oos_pooled") & (summary["variant"] == v)].iloc[0]
        if o["net"] > 0 and o["pf"] >= 1.10 and o["p_pos"] >= 0.80 and o["pos_inst"] >= 2:
            survivors.append(v)
            print(f"paper_seed={v} oos_net=${o['net']:,.0f} pf={o['pf']:.2f} p={o['p_pos']:.3f}")
        else:
            print(f"reject_oos={v} oos_net=${o['net']:,.0f} pf={o['pf']:.2f} p={o['p_pos']:.3f}")
    if not survivors:
        print("survivors=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
