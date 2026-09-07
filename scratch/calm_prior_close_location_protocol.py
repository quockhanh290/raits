from __future__ import annotations

import argparse
import math
from dataclasses import dataclass

import pandas as pd


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


@dataclass(frozen=True)
class Gate:
    min_train_trades: int = 100
    min_test_trades: int = 20
    min_pf: float = 1.10
    min_pos_inst: int = 2
    max_top_year_share: float = 0.70


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


def robustness(df: pd.DataFrame) -> dict:
    st = stats(df)
    by_year = df.groupby("year")["pnl"].sum() if not df.empty else pd.Series(dtype=float)
    by_inst = df.groupby("inst")["pnl"].sum() if not df.empty else pd.Series(dtype=float)
    return {
        "pos_years": int((by_year > 0).sum()),
        "years": int(len(by_year)),
        "pos_inst": int((by_inst > 0).sum()),
        "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 and not by_year.empty else 1.0,
    }


def eligible(df: pd.DataFrame, gate: Gate, min_pos_years: int) -> tuple[bool, str]:
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
    if rb["pos_years"] < min_pos_years:
        reasons.append("few_pos_years")
    if rb["pos_inst"] < gate.min_pos_inst:
        reasons.append("few_pos_inst")
    if rb["top_year_share"] > gate.max_top_year_share:
        reasons.append("top_year_concentration")
    return not reasons, ",".join(reasons)


def rank_variants(df: pd.DataFrame, variants: list[str], gate: Gate, min_pos_years: int) -> pd.DataFrame:
    rows = []
    for variant in variants:
        g = df[df["variant"] == variant]
        ok, reasons = eligible(g, gate, min_pos_years)
        rows.append({"variant": variant, "eligible": ok, "reasons": reasons, **stats(g), **robustness(g)})
    return pd.DataFrame(rows).sort_values(["eligible", "net", "pf", "avg"], ascending=False)


def run_protocol(df: pd.DataFrame, variants: list[str], gate: Gate) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = [
        ("train2018_2021_test2022", 2018, 2021, 2022),
        ("train2019_2022_test2023", 2019, 2022, 2023),
        ("train2020_2023_test2024", 2020, 2023, 2024),
    ]
    rows = []
    ranks = []
    for fold, y0, y1, yt in folds:
        train = df[(df["year"] >= y0) & (df["year"] <= y1)]
        test = df[df["year"] == yt]
        min_pos_years = max(2, y1 - y0)
        train_rank = rank_variants(train, variants, gate, min_pos_years)
        train_rank["fold"] = fold
        train_rank["phase"] = "train"
        ranks.append(train_rank)
        candidates = train_rank[train_rank["eligible"]]
        selected = str(candidates.iloc[0]["variant"]) if not candidates.empty else "NONE"
        test_rows = []
        for variant in variants:
            g = test[test["variant"] == variant]
            test_rows.append({"variant": variant, **stats(g), **robustness(g)})
        test_rank = pd.DataFrame(test_rows).sort_values(["net", "pf", "avg"], ascending=False)
        test_rank["fold"] = fold
        test_rank["phase"] = "test"
        test_rank["eligible"] = pd.NA
        test_rank["reasons"] = ""
        ranks.append(test_rank)
        selected_test = test[test["variant"] == selected] if selected != "NONE" else test.iloc[0:0]
        st = stats(selected_test)
        rows.append(
            {
                "fold": fold,
                "train_start": y0,
                "train_end": y1,
                "test_year": yt,
                "selected": selected,
                "selected_test_n": st["n"],
                "selected_test_days": st["days"],
                "selected_test_net": st["net"],
                "selected_test_pf": st["pf"],
                "selected_test_avg": st["avg"],
                "test_winner": str(test_rank.iloc[0]["variant"]),
                "selected_rank_by_net": int(test_rank["variant"].tolist().index(selected) + 1)
                if selected in test_rank["variant"].tolist()
                else 0,
                "meaningful_test": st["n"] >= gate.min_test_trades,
            }
        )
    return pd.DataFrame(rows), pd.concat(ranks, ignore_index=True)


def load(path: str, variants: list[str]) -> pd.DataFrame:
    df = pd.read_csv(path)
    audit_clean(df)
    df = df[df["variant"].isin(variants)].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


def print_folds(folds: pd.DataFrame) -> None:
    print("\n=== prior-close-location protocol ===")
    for _, r in folds.iterrows():
        print(
            f"{r['fold']:<27} selected={r['selected']:<50} "
            f"test={int(r['test_year'])} n={int(r['selected_test_n']):>4} "
            f"net=${r['selected_test_net']:>8,.0f} pf={r['selected_test_pf']:>5.2f} "
            f"winner={r['test_winner']:<50} rank={int(r['selected_rank_by_net'])} "
            f"meaningful={bool(r['meaningful_test'])}"
        )
    picked = folds[folds["selected"] != "NONE"]
    print(
        f"aggregate selected: net=${picked['selected_test_net'].sum():,.0f} "
        f"n={int(picked['selected_test_n'].sum())} "
        f"meaningful_folds={int(picked['meaningful_test'].sum())}/{len(picked)} "
        f"winner_matches={int((picked['selected'] == picked['test_winner']).sum())}/{len(picked)}"
    )


def print_oos(title: str, df: pd.DataFrame, selected: list[str]) -> None:
    print(f"\n=== {title} ===")
    for variant in selected:
        g = df[df["variant"] == variant]
        st = stats(g)
        rb = robustness(g)
        print(
            f"{variant:<50} n={st['n']:>4} days={st['days']:>3} "
            f"net=${st['net']:>8,.0f} pf={st['pf']:>5.2f} avg=${st['avg']:>7.2f} "
            f"posI={rb['pos_inst']} audit={int(g[AUDIT_COLS].sum().sum())}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-trades", default="scratch/calm_prior_close_location_probe_is.csv")
    ap.add_argument("--oos-2025", default="scratch/calm_prior_close_location_probe_2025.csv")
    ap.add_argument("--oos-2026", default="scratch/calm_prior_close_location_probe_2026.csv")
    ap.add_argument("--out-prefix", default="scratch/calm_prior_close_location_protocol")
    ap.add_argument("--variants", nargs="+", default=[
        "pcloc_prev_bottom_third_long_e1000_x1555",
        "pcloc_prev_bottom_down_long_e1000_x1555",
    ])
    args = ap.parse_args()

    gate = Gate()
    is_df = load(args.is_trades, args.variants)
    folds, ranks = run_protocol(is_df, args.variants, gate)
    print_folds(folds)
    folds.to_csv(f"{args.out_prefix}_folds.csv", index=False)
    ranks.to_csv(f"{args.out_prefix}_ranks.csv", index=False)
    print(f"\nwrote {args.out_prefix}_folds.csv")
    print(f"wrote {args.out_prefix}_ranks.csv")

    selected = [x for x in folds["selected"].unique().tolist() if x != "NONE"]
    if selected:
        o25 = load(args.oos_2025, selected)
        o26 = load(args.oos_2026, selected)
        print_oos("2025 OOS protocol-selected", o25, selected)
        print_oos("2026 sanity protocol-selected", o26, selected)
        print_oos("2025+2026 pooled", pd.concat([o25, o26], ignore_index=True), selected)
    meaningful = int(folds["meaningful_test"].sum())
    matches = int((folds["selected"] == folds["test_winner"]).sum())
    print("\nverdict=" + ("paper_candidate_protocol_survives" if meaningful == len(folds) and matches >= 2 else "keep_digging_protocol_not_decisive"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
