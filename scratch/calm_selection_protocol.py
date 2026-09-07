from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


@dataclass(frozen=True)
class Gate:
    min_train_trades: int = 100
    min_year_trades: int = 20
    min_year_days: int = 10
    min_test_trades: int = 20
    min_pf: float = 1.10
    max_top_year_share: float = 0.75
    min_pos_instruments: int = 2
    separation_net_pct: float = 0.10
    separation_avg_pct: float = 0.10


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "days": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    maxdd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    return {
        "n": int(len(df)),
        "days": int(df["day"].nunique()),
        "net": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "avg": float(pnl.mean()),
        "maxdd": maxdd,
    }


def meaningful_years(df: pd.DataFrame, gate: Gate) -> tuple[int, int]:
    if df.empty:
        return 0, 0
    counts = df.groupby("year").agg(trades=("pnl", "size"), days=("day", "nunique"), net=("pnl", "sum"))
    meaningful = counts[(counts["trades"] >= gate.min_year_trades) | (counts["days"] >= gate.min_year_days)]
    pos = int((meaningful["net"] > 0).sum())
    return pos, int(len(meaningful))


def robustness(df: pd.DataFrame, gate: Gate) -> dict:
    st = stats(df)
    by_year = df.groupby("year")["pnl"].sum() if not df.empty else pd.Series(dtype=float)
    by_inst = df.groupby("inst")["pnl"].sum() if not df.empty else pd.Series(dtype=float)
    pos_meaningful, meaningful = meaningful_years(df, gate)
    return {
        "pos_meaningful_years": pos_meaningful,
        "meaningful_years": meaningful,
        "pos_inst": int((by_inst > 0).sum()),
        "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 and not by_year.empty else 1.0,
        "top_inst_share": float(by_inst.max() / st["net"]) if st["net"] > 0 and not by_inst.empty else 1.0,
    }


def audit_clean(df: pd.DataFrame) -> bool:
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing audit columns: {missing}")
    return int(df[AUDIT_COLS].sum().sum()) == 0


def eligible_train(df: pd.DataFrame, gate: Gate, min_years: int) -> tuple[bool, list[str]]:
    reasons = []
    if not audit_clean(df):
        reasons.append("audit")
    st = stats(df)
    rb = robustness(df, gate)
    if st["n"] < gate.min_train_trades:
        reasons.append("few_train_trades")
    if st["net"] <= 0:
        reasons.append("nonpositive_train")
    if st["pf"] < gate.min_pf:
        reasons.append("low_pf")
    if rb["pos_meaningful_years"] < min_years:
        reasons.append("few_pos_meaningful_years")
    if rb["pos_inst"] < gate.min_pos_instruments:
        reasons.append("few_pos_inst")
    if rb["top_year_share"] > gate.max_top_year_share:
        reasons.append("top_year_concentration")
    return len(reasons) == 0, reasons


def choose(train: pd.DataFrame, variants: list[str], gate: Gate, min_years: int) -> tuple[str | None, pd.DataFrame]:
    rows = []
    for variant in variants:
        g = train[train["variant"] == variant]
        ok, reasons = eligible_train(g, gate, min_years)
        st = stats(g)
        rb = robustness(g, gate)
        rows.append({"variant": variant, "eligible": ok, "reasons": ",".join(reasons), **st, **rb})
    rank = pd.DataFrame(rows)
    candidates = rank[rank["eligible"]].copy()
    if candidates.empty:
        return None, rank
    candidates = candidates.sort_values(["net", "pf", "avg"], ascending=False)
    return str(candidates.iloc[0]["variant"]), rank


def separable(test_rows: pd.DataFrame, gate: Gate) -> tuple[bool, str]:
    if test_rows.empty or test_rows["net"].max() <= 0:
        return False, "no_positive_test"
    top = test_rows.sort_values(["net", "avg"], ascending=False).iloc[0]
    second = test_rows.sort_values(["net", "avg"], ascending=False).iloc[1] if len(test_rows) > 1 else None
    if second is None:
        return True, "single"
    net_gap = float(top["net"] - second["net"])
    avg_gap = float(top["avg"] - second["avg"])
    if net_gap < abs(float(top["net"])) * gate.separation_net_pct and avg_gap < abs(float(top["avg"])) * gate.separation_avg_pct:
        return False, "top_two_too_close"
    return True, "separable"


def run_protocol(df: pd.DataFrame, variants: list[str], gate: Gate, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = [
        ("train2018_2021_test2022", 2018, 2021, 2022),
        ("train2019_2022_test2023", 2019, 2022, 2023),
        ("train2020_2023_test2024", 2020, 2023, 2024),
    ]
    rows = []
    fold_rows = []
    for fold, y0, y1, yt in folds:
        train = df[(df["year"] >= y0) & (df["year"] <= y1)]
        test = df[df["year"] == yt]
        min_years = max(2, y1 - y0)
        selected, rank = choose(train, variants, gate, min_years)
        rank["fold"] = fold
        rank["label"] = label
        rank["phase"] = "train"
        fold_rows.append(rank)
        test_rank = []
        for variant in variants:
            g = test[test["variant"] == variant]
            st = stats(g)
            rb = robustness(g, gate)
            test_rank.append({"variant": variant, **st, **rb})
        test_rank_df = pd.DataFrame(test_rank).sort_values(["net", "avg"], ascending=False)
        sep_ok, sep_reason = separable(test_rank_df, gate)
        selected_test = test[test["variant"] == selected] if selected else test.iloc[0:0]
        selected_st = stats(selected_test)
        rows.append({
            "label": label,
            "fold": fold,
            "train_start": y0,
            "train_end": y1,
            "test_year": yt,
            "selected": selected or "NONE",
            "selected_test_n": selected_st["n"],
            "selected_test_days": selected_st["days"],
            "selected_test_net": selected_st["net"],
            "selected_test_pf": selected_st["pf"],
            "selected_test_avg": selected_st["avg"],
            "test_separable": sep_ok,
            "separation_reason": sep_reason,
            "test_winner": str(test_rank_df.iloc[0]["variant"]) if not test_rank_df.empty else "NONE",
            "selected_rank_by_net": int((test_rank_df["variant"].tolist().index(selected) + 1) if selected in test_rank_df["variant"].tolist() else 0),
            "meaningful_test": selected_st["n"] >= gate.min_test_trades,
        })
        for _, r in test_rank_df.iterrows():
            fold_rows.append(pd.DataFrame([{
                "label": label,
                "fold": fold,
                "phase": "test",
                "variant": r["variant"],
                "eligible": np.nan,
                "reasons": "",
                **{k: r[k] for k in r.index if k != "variant"},
            }]))
    return pd.DataFrame(rows), pd.concat(fold_rows, ignore_index=True)


def load_variant_family(path: str, variants: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    audit_clean(df)
    df = df[df["variant"].isin(variants)].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


def load_bucket_family(path: str, buckets: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    audit_clean(df)
    df = df[(df["window"] == "is") & (df["bucket"].isin(buckets))].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["variant"] = "bucket_" + df["bucket"].astype(str)
    return df


def print_protocol(title: str, folds: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    for _, r in folds.iterrows():
        print(
            f"{r['fold']:<27} selected={r['selected']:<28} "
            f"test={int(r['test_year'])} n={int(r['selected_test_n']):>4} "
            f"net=${r['selected_test_net']:>8,.0f} pf={r['selected_test_pf']:>5.2f} "
            f"winner={r['test_winner']:<28} rank={int(r['selected_rank_by_net'])} "
            f"meaningful={bool(r['meaningful_test'])} separable={bool(r['test_separable'])}/{r['separation_reason']}"
        )
    picked = folds[folds["selected"] != "NONE"]
    if not picked.empty:
        print(
            f"aggregate selected: net=${picked['selected_test_net'].sum():,.0f} "
            f"n={int(picked['selected_test_n'].sum())} "
            f"meaningful_folds={int(picked['meaningful_test'].sum())}/{len(picked)} "
            f"winner_matches={int((picked['selected'] == picked['test_winner']).sum())}/{len(picked)}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep-is", default="scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv")
    ap.add_argument("--bucket-trades", default="scratch/calm_h1_bucket_excavation_trades.csv")
    ap.add_argument("--out-prefix", default="scratch/calm_selection_protocol")
    args = ap.parse_args()

    gate = Gate()
    finalist_variants = [
        "on_neg_fade_raw_x1555",
        "on_neg_fade_mod001_010_x1555",
        "on_neg_fade_mod002_010_x1555",
    ]
    bucket_variants = ["m010_m005", "m005_m002", "m002_m001", "m001_000"]

    finalist_df = load_variant_family(args.sweep_is, finalist_variants)
    bucket_df = load_bucket_family(args.bucket_trades, bucket_variants)

    finalist_folds, finalist_rank = run_protocol(finalist_df, finalist_variants, gate, "finalists")
    bucket_names = ["bucket_" + b for b in bucket_variants]
    bucket_folds, bucket_rank = run_protocol(bucket_df, bucket_names, gate, "buckets")

    print_protocol("finalist protocol", finalist_folds)
    print_protocol("bucket protocol", bucket_folds)

    folds = pd.concat([finalist_folds, bucket_folds], ignore_index=True)
    ranks = pd.concat([finalist_rank, bucket_rank], ignore_index=True)
    folds_path = f"{args.out_prefix}_folds.csv"
    ranks_path = f"{args.out_prefix}_ranks.csv"
    folds.to_csv(folds_path, index=False)
    ranks.to_csv(ranks_path, index=False)
    print(f"\nwrote {folds_path}")
    print(f"wrote {ranks_path}")

    print("\n=== protocol verdict ===")
    for label, g in folds.groupby("label"):
        picked = g[g["selected"] != "NONE"]
        if picked.empty:
            verdict = "reject_no_selection"
        elif int(picked["meaningful_test"].sum()) < len(picked):
            verdict = "reject_thin_test_fold"
        elif int((picked["selected"] == picked["test_winner"]).sum()) < 2:
            verdict = "reject_heldout_does_not_confirm_selection"
        elif not bool(picked["test_separable"].all()):
            verdict = "not_separable"
        else:
            verdict = "paper_candidate_only"
        print(f"{label}: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
