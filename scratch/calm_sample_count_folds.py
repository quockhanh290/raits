from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import pandas as pd


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


@dataclass(frozen=True)
class Gate:
    min_train_trades: int = 100
    min_test_trades: int = 30
    min_pf: float = 1.10
    min_pos_inst: int = 2
    max_top_period_share: float = 0.75


FAMILIES = {
    "negon_legacy": {
        "path": "scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv",
        "variants": [
            "on_neg_fade_raw_x1555",
            "on_neg_fade_mod001_010_x1555",
            "on_neg_fade_mod002_010_x1555",
        ],
    },
    "openloc_liveable": {
        "path": "scratch/calm_open_location_drift_delay_sensitivity_is.csv",
        "variants": [
            "openloc_lower_third_long_e1000_x1555",
            "openloc_lower_spy_above_long_e1000_x1555",
        ],
    },
    "pcloc_liveable": {
        "path": "scratch/calm_prior_close_location_probe_is.csv",
        "variants": [
            "pcloc_prev_bottom_third_long_e1000_x1555",
            "pcloc_prev_bottom_down_long_e1000_x1555",
        ],
    },
    "prior_reclaim": {
        "path": "scratch/calm_prior_range_reclaim_is.csv",
        "variants": [
            "low_reclaim_long_scan1030_x15:55",
            "low_reclaim_long_scan1000_x15:55",
            "low_reclaim_long_scan1030_xtarget_mid_1555",
            "low_reclaim_long_scan1030_xtarget_close_1555",
        ],
    },
    "causal_pcloc": {
        "path": "scratch/calm_causal_lag1_excavation_is.csv",
        "variants": [
            "lag1calm_pcloc_bottom_long_e1000_x1555",
            "lag1calm_pcloc_bottom_down_long_e1000_x1555",
        ],
    },
}


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


def audit_clean(df: pd.DataFrame) -> bool:
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing audit columns: {missing}")
    return int(df[AUDIT_COLS].sum().sum()) == 0


def robustness(df: pd.DataFrame, period_col: str = "fold_period") -> dict:
    st = stats(df)
    by_inst = df.groupby("inst")["pnl"].sum() if not df.empty else pd.Series(dtype=float)
    by_period = df.groupby(period_col)["pnl"].sum() if period_col in df.columns and not df.empty else pd.Series(dtype=float)
    return {
        "pos_inst": int((by_inst > 0).sum()),
        "top_period_share": float(by_period.max() / st["net"]) if st["net"] > 0 and not by_period.empty else 1.0,
    }


def load_family(family: str, spec: dict) -> pd.DataFrame:
    df = pd.read_csv(spec["path"])
    audit_clean(df)
    df = df[df["variant"].isin(spec["variants"])].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    df["family"] = family
    df["candidate"] = family + "::" + df["variant"].astype(str)
    return df


def calm_days(path: str) -> list[pd.Timestamp]:
    df = pd.read_csv(path, usecols=["day"])
    days = pd.to_datetime(df["day"]).dt.normalize().drop_duplicates().sort_values()
    return list(days)


def make_folds(days: list[pd.Timestamp], train_n: int, test_n: int) -> list[dict]:
    folds = []
    start = train_n
    i = 1
    while start < len(days):
        end = min(start + test_n, len(days))
        train_days = set(days[:start])
        test_days = set(days[start:end])
        if len(test_days) < max(30, test_n // 2):
            break
        folds.append(
            {
                "fold": f"calm_count_f{i}",
                "train_days": train_days,
                "test_days": test_days,
                "train_start": min(train_days),
                "train_end": max(train_days),
                "test_start": min(test_days),
                "test_end": max(test_days),
                "train_calm_days": len(train_days),
                "test_calm_days": len(test_days),
            }
        )
        start = end
        i += 1
    return folds


def add_period_labels(df: pd.DataFrame, fold: dict) -> pd.DataFrame:
    out = df.copy()
    test_days_sorted = sorted(fold["test_days"])
    chunks = {}
    for i, day in enumerate(test_days_sorted):
        chunks[day] = f"q{min(4, int(i / max(1, len(test_days_sorted) / 4)) + 1)}"
    out["fold_period"] = out["day"].map(chunks).fillna("train")
    return out


def eligible(df: pd.DataFrame, gate: Gate) -> tuple[bool, str]:
    reasons = []
    if not audit_clean(df):
        reasons.append("audit")
    st = stats(df)
    rb = robustness(df)
    if st["n"] < gate.min_train_trades:
        reasons.append("few_train_trades")
    if st["net"] <= 0:
        reasons.append("nonpositive")
    if st["pf"] < gate.min_pf:
        reasons.append("low_pf")
    if rb["pos_inst"] < gate.min_pos_inst:
        reasons.append("few_pos_inst")
    return not reasons, ",".join(reasons)


def choose(train: pd.DataFrame, candidates: list[str], gate: Gate) -> tuple[str, pd.DataFrame]:
    rows = []
    for c in candidates:
        g = train[train["candidate"] == c]
        ok, reasons = eligible(g, gate)
        rows.append({"candidate": c, "eligible": ok, "reasons": reasons, **stats(g), **robustness(g)})
    rank = pd.DataFrame(rows).sort_values(["eligible", "net", "pf", "avg"], ascending=False)
    elig = rank[rank["eligible"]]
    return (str(elig.iloc[0]["candidate"]) if not elig.empty else "NONE"), rank


def run_protocol(df: pd.DataFrame, folds: list[dict], candidates: list[str], gate: Gate, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    ranks = []
    for fold in folds:
        train = df[df["day"].isin(fold["train_days"])].copy()
        test = add_period_labels(df[df["day"].isin(fold["test_days"])].copy(), fold)
        selected, train_rank = choose(train, candidates, gate)
        train_rank["label"] = label
        train_rank["fold"] = fold["fold"]
        train_rank["phase"] = "train"
        ranks.append(train_rank)

        test_rows = []
        for c in candidates:
            g = test[test["candidate"] == c]
            test_rows.append({"candidate": c, **stats(g), **robustness(g)})
        test_rank = pd.DataFrame(test_rows).sort_values(["net", "pf", "avg"], ascending=False)
        test_rank["label"] = label
        test_rank["fold"] = fold["fold"]
        test_rank["phase"] = "test"
        test_rank["eligible"] = pd.NA
        test_rank["reasons"] = ""
        ranks.append(test_rank)

        selected_test = test[test["candidate"] == selected] if selected != "NONE" else test.iloc[0:0]
        st = stats(selected_test)
        rows.append(
            {
                "label": label,
                "fold": fold["fold"],
                "train_start": fold["train_start"].date().isoformat(),
                "train_end": fold["train_end"].date().isoformat(),
                "test_start": fold["test_start"].date().isoformat(),
                "test_end": fold["test_end"].date().isoformat(),
                "train_calm_days": fold["train_calm_days"],
                "test_calm_days": fold["test_calm_days"],
                "selected": selected,
                "selected_test_n": st["n"],
                "selected_test_days": st["days"],
                "selected_test_net": st["net"],
                "selected_test_pf": st["pf"],
                "selected_test_avg": st["avg"],
                "test_winner": str(test_rank.iloc[0]["candidate"]),
                "selected_rank_by_net": int(test_rank["candidate"].tolist().index(selected) + 1)
                if selected in test_rank["candidate"].tolist()
                else 0,
                "meaningful_test": st["n"] >= gate.min_test_trades,
            }
        )
    return pd.DataFrame(rows), pd.concat(ranks, ignore_index=True)


def print_protocol(title: str, folds: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    for _, r in folds.iterrows():
        print(
            f"{r['fold']:<13} test={r['test_start']}..{r['test_end']} "
            f"selected={r['selected']:<62} n={int(r['selected_test_n']):>4} "
            f"net=${r['selected_test_net']:>8,.0f} pf={r['selected_test_pf']:>5.2f} "
            f"winner={r['test_winner']:<62} rank={int(r['selected_rank_by_net'])} "
            f"meaningful={bool(r['meaningful_test'])}"
        )
    picked = folds[folds["selected"] != "NONE"]
    if not picked.empty:
        print(
            f"aggregate: net=${picked['selected_test_net'].sum():,.0f} "
            f"n={int(picked['selected_test_n'].sum())} "
            f"meaningful={int(picked['meaningful_test'].sum())}/{len(picked)} "
            f"winner_matches={int((picked['selected'] == picked['test_winner']).sum())}/{len(picked)}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--train-calm-days", type=int, default=300)
    ap.add_argument("--test-calm-days", type=int, default=150)
    ap.add_argument("--out-prefix", default="scratch/calm_sample_count_folds")
    args = ap.parse_args()

    gate = Gate()
    days = calm_days(args.calm_days_is)
    folds = make_folds(days, args.train_calm_days, args.test_calm_days)
    print(f"calm_days={len(days)} folds={len(folds)} train={args.train_calm_days} test={args.test_calm_days}")

    family_frames = {family: load_family(family, spec) for family, spec in FAMILIES.items()}
    all_df = pd.concat(family_frames.values(), ignore_index=True)

    all_folds = []
    all_ranks = []
    for family, df in family_frames.items():
        candidates = sorted(df["candidate"].unique().tolist())
        f, r = run_protocol(df, folds, candidates, gate, family)
        print_protocol(family, f)
        all_folds.append(f)
        all_ranks.append(r)

    global_candidates = sorted(all_df["candidate"].unique().tolist())
    gf, gr = run_protocol(all_df, folds, global_candidates, gate, "global_all_strong")
    print_protocol("global_all_strong", gf)
    all_folds.append(gf)
    all_ranks.append(gr)

    fold_out = pd.concat(all_folds, ignore_index=True)
    rank_out = pd.concat(all_ranks, ignore_index=True)
    fold_out.to_csv(f"{args.out_prefix}_folds.csv", index=False)
    rank_out.to_csv(f"{args.out_prefix}_ranks.csv", index=False)
    print(f"\nwrote {args.out_prefix}_folds.csv")
    print(f"wrote {args.out_prefix}_ranks.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
