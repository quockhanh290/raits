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


def load(path: str, variant: str, label: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} missing audit columns: {missing}")
    df = df[df["variant"] == variant].copy()
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"{path} audit failed")
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["month"] = df["day"].dt.to_period("M").astype(str)
    df["candidate"] = label
    return df


def summary_by(df: pd.DataFrame, candidate: str, group: str) -> list[dict]:
    rows = []
    for key, g in df.groupby(group):
        rows.append({"candidate": candidate, "group": group, "key": str(key), **stats(g)})
    return rows


def overlap(openloc: pd.DataFrame, pcloc: pd.DataFrame) -> pd.DataFrame:
    a = openloc.rename(columns={"pnl": "openloc_pnl"})[["day", "inst", "openloc_pnl"]]
    b = pcloc.rename(columns={"pnl": "pcloc_pnl"})[["day", "inst", "pcloc_pnl"]]
    merged = a.merge(b, on=["day", "inst"], how="outer", indicator=True)
    merged["bucket"] = merged["_merge"].map({"both": "overlap", "left_only": "openloc_only", "right_only": "pcloc_only"})
    rows = []
    for bucket, g in merged.groupby("bucket"):
        if bucket == "overlap":
            pnl = g["openloc_pnl"].fillna(0.0)
        elif bucket == "openloc_only":
            pnl = g["openloc_pnl"].fillna(0.0)
        else:
            pnl = g["pcloc_pnl"].fillna(0.0)
        tmp = pd.DataFrame({"day": g["day"], "pnl": pnl})
        rows.append({"bucket": bucket, **stats(tmp)})
    return pd.DataFrame(rows).sort_values("net", ascending=False)


def yearly_presence(df: pd.DataFrame, candidate: str) -> pd.DataFrame:
    by = df.groupby("year").agg(n=("pnl", "size"), days=("day", "nunique"), net=("pnl", "sum"))
    all_years = pd.DataFrame({"year": range(2018, 2025)})
    out = all_years.merge(by.reset_index(), on="year", how="left").fillna({"n": 0, "days": 0, "net": 0.0})
    out["candidate"] = candidate
    return out[["candidate", "year", "n", "days", "net"]]


def calm_denominator(path: str, candidates: dict[str, pd.DataFrame]) -> pd.DataFrame:
    calm = pd.read_csv(path, usecols=["day"])
    calm["day"] = pd.to_datetime(calm["day"]).dt.normalize()
    calm["year"] = calm["day"].dt.year
    # The calm-day CSV has many strategy rows per day; unique day is the denominator.
    denom = calm.drop_duplicates("day").groupby("year")["day"].nunique().rename("calm_days")
    rows = []
    for cand, df in candidates.items():
        trig = df.groupby("year")["day"].nunique().rename("trigger_days")
        out = pd.DataFrame({"year": range(2018, 2025)}).merge(denom.reset_index(), on="year", how="left")
        out = out.merge(trig.reset_index(), on="year", how="left")
        out[["calm_days", "trigger_days"]] = out[["calm_days", "trigger_days"]].fillna(0)
        out["candidate"] = cand
        out["trigger_share"] = out["trigger_days"] / out["calm_days"].replace(0, np.nan)
        rows.append(out[["candidate", "year", "calm_days", "trigger_days", "trigger_share"]])
    return pd.concat(rows, ignore_index=True)


def month_extremes(df: pd.DataFrame, candidate: str) -> pd.DataFrame:
    rows = []
    by = df.groupby("month")["pnl"].agg(["size", "sum"]).reset_index().rename(columns={"size": "n", "sum": "net"})
    for _, r in by.sort_values("net").head(5).iterrows():
        rows.append({"candidate": candidate, "side": "worst", "month": r["month"], "n": int(r["n"]), "net": float(r["net"])})
    for _, r in by.sort_values("net", ascending=False).head(5).iterrows():
        rows.append({"candidate": candidate, "side": "best", "month": r["month"], "n": int(r["n"]), "net": float(r["net"])})
    return pd.DataFrame(rows)


def bootstrap_by_year(df: pd.DataFrame, candidate: str, iters: int, rng: np.random.Generator) -> dict:
    by = df.groupby("year")["pnl"].sum().reindex(range(2018, 2025), fill_value=0.0).to_numpy(dtype=float)
    draws = rng.choice(by, size=(iters, len(by)), replace=True).sum(axis=1)
    return {
        "candidate": candidate,
        "cluster": "year",
        "clusters": int(len(by)),
        "p_pos": float((draws > 0).mean()),
        "p05": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
    }


def print_section(title: str, df: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("no rows")
        return
    print(df.to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--openloc-is", default="scratch/calm_open_location_drift_delay_sensitivity_is.csv")
    ap.add_argument("--openloc-2025", default="scratch/calm_open_location_drift_delay_sensitivity_2025.csv")
    ap.add_argument("--openloc-2026", default="scratch/calm_open_location_drift_delay_sensitivity_2026.csv")
    ap.add_argument("--pcloc-is", default="scratch/calm_prior_close_location_probe_is.csv")
    ap.add_argument("--pcloc-2025", default="scratch/calm_prior_close_location_probe_2025.csv")
    ap.add_argument("--pcloc-2026", default="scratch/calm_prior_close_location_probe_2026.csv")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--iters", type=int, default=10000)
    ap.add_argument("--out-prefix", default="scratch/calm_paper_failure_autopsy")
    args = ap.parse_args()

    openloc_v = "openloc_lower_third_long_e1000_x1555"
    pcloc_v = "pcloc_prev_bottom_third_long_e1000_x1555"
    frames = {
        "openloc_is": load(args.openloc_is, openloc_v, "openloc"),
        "openloc_2025": load(args.openloc_2025, openloc_v, "openloc"),
        "openloc_2026": load(args.openloc_2026, openloc_v, "openloc"),
        "pcloc_is": load(args.pcloc_is, pcloc_v, "pcloc"),
        "pcloc_2025": load(args.pcloc_2025, pcloc_v, "pcloc"),
        "pcloc_2026": load(args.pcloc_2026, pcloc_v, "pcloc"),
    }

    summary_rows = []
    for name, df in frames.items():
        cand, window = name.split("_", 1)
        summary_rows.append({"candidate": cand, "window": window, **stats(df)})
    summary = pd.DataFrame(summary_rows)

    by_rows = []
    for cand in ("openloc", "pcloc"):
        for window in ("is", "2025", "2026"):
            df = frames[f"{cand}_{window}"]
            by_rows.extend(summary_by(df, cand + "_" + window, "year"))
            by_rows.extend(summary_by(df, cand + "_" + window, "inst"))
    by = pd.DataFrame(by_rows)

    overlap_is = overlap(frames["openloc_is"], frames["pcloc_is"])
    overlap_oos = overlap(
        pd.concat([frames["openloc_2025"], frames["openloc_2026"]], ignore_index=True),
        pd.concat([frames["pcloc_2025"], frames["pcloc_2026"]], ignore_index=True),
    )
    overlap_is["window"] = "is"
    overlap_oos["window"] = "oos"
    overlaps = pd.concat([overlap_is, overlap_oos], ignore_index=True)

    presence = pd.concat(
        [
            yearly_presence(frames["openloc_is"], "openloc"),
            yearly_presence(frames["pcloc_is"], "pcloc"),
        ],
        ignore_index=True,
    )
    denom = calm_denominator(args.calm_days_is, {"openloc": frames["openloc_is"], "pcloc": frames["pcloc_is"]})
    months = pd.concat(
        [
            month_extremes(frames["openloc_is"], "openloc_is"),
            month_extremes(frames["pcloc_is"], "pcloc_is"),
            month_extremes(frames["openloc_2026"], "openloc_2026"),
            month_extremes(frames["pcloc_2026"], "pcloc_2026"),
        ],
        ignore_index=True,
    )
    rng = np.random.default_rng(20260821)
    boot = pd.DataFrame(
        [
            bootstrap_by_year(frames["openloc_is"], "openloc_is", args.iters, rng),
            bootstrap_by_year(frames["pcloc_is"], "pcloc_is", args.iters, rng),
        ]
    )

    summary.to_csv(f"{args.out_prefix}_summary.csv", index=False)
    by.to_csv(f"{args.out_prefix}_by.csv", index=False)
    overlaps.to_csv(f"{args.out_prefix}_overlap.csv", index=False)
    presence.to_csv(f"{args.out_prefix}_presence.csv", index=False)
    denom.to_csv(f"{args.out_prefix}_denominator.csv", index=False)
    months.to_csv(f"{args.out_prefix}_months.csv", index=False)
    boot.to_csv(f"{args.out_prefix}_boot_year.csv", index=False)

    print_section("candidate summary", summary)
    print_section("yearly presence IS", presence)
    print_section("calm denominator IS", denom)
    print_section("overlap", overlaps)
    print_section("year bootstrap IS", boot)
    print_section("month extremes", months)
    print(f"\nwrote {args.out_prefix}_*.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
