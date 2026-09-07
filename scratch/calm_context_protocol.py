from __future__ import annotations

import argparse
import math

import pandas as pd


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]
VARIANTS = [
    "all_raw_neg",
    "spy_rv20_le20",
    "spy_above50",
    "open_lower_third",
    "prior_expand20",
    "prior_up",
    "prior_down",
    "open_inside_prev_range",
    "prior_compress20",
    "seed_m005_m002",
    "seed_m005_m002_prior_up",
]


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


def meaningful_years(df: pd.DataFrame) -> tuple[int, int]:
    if df.empty:
        return 0, 0
    y = df.groupby("year").agg(trades=("pnl", "size"), days=("day", "nunique"), net=("pnl", "sum"))
    y = y[(y["trades"] >= 20) | (y["days"] >= 10)]
    return int((y["net"] > 0).sum()), int(len(y))


def mask_for(df: pd.DataFrame, variant: str) -> pd.Series:
    if variant == "all_raw_neg":
        return pd.Series(True, index=df.index)
    if variant == "seed_m005_m002":
        return df["bucket_m005_m002"] == True
    if variant == "seed_m005_m002_prior_up":
        return (df["bucket_m005_m002"] == True) & (df["prior_up"] == True)
    return df[variant] == True


def eligible(df: pd.DataFrame, min_years: int) -> bool:
    st = stats(df)
    py, _ = meaningful_years(df)
    by_inst = df.groupby("inst")["pnl"].sum() if not df.empty else pd.Series(dtype=float)
    by_year = df.groupby("year")["pnl"].sum() if not df.empty else pd.Series(dtype=float)
    top_share = float(by_year.max() / st["net"]) if st["net"] > 0 and not by_year.empty else 1.0
    return (
        st["n"] >= 100
        and st["net"] > 0
        and st["pf"] >= 1.10
        and py >= min_years
        and int((by_inst > 0).sum()) >= 2
        and top_share <= 0.75
    )


def expand(df: pd.DataFrame, variants: list[str]) -> pd.DataFrame:
    frames = []
    for variant in variants:
        g = df[mask_for(df, variant).fillna(False)].copy()
        g["variant2"] = variant
        frames.append(g)
    return pd.concat(frames, ignore_index=True)


def run(df: pd.DataFrame, variants: list[str]) -> pd.DataFrame:
    folds = [
        ("train2018_2021_test2022", 2018, 2021, 2022),
        ("train2019_2022_test2023", 2019, 2022, 2023),
        ("train2020_2023_test2024", 2020, 2023, 2024),
    ]
    rows = []
    for fold, y0, y1, yt in folds:
        train = df[(df["year"] >= y0) & (df["year"] <= y1)]
        test = df[df["year"] == yt]
        min_years = max(2, y1 - y0)
        train_exp = expand(train, variants)
        train_rows = []
        for variant, g in train_exp.groupby("variant2"):
            st = stats(g)
            train_rows.append({"variant": variant, "eligible": eligible(g, min_years), **st})
        train_rank = pd.DataFrame(train_rows)
        elig = train_rank[train_rank["eligible"]].sort_values(["net", "pf", "avg"], ascending=False)
        selected = str(elig.iloc[0]["variant"]) if not elig.empty else "NONE"
        test_exp = expand(test, variants)
        test_rows = []
        for variant, g in test_exp.groupby("variant2"):
            st = stats(g)
            test_rows.append({"variant": variant, **st})
        test_rank = pd.DataFrame(test_rows).sort_values(["net", "avg"], ascending=False)
        sel = test_exp[test_exp["variant2"] == selected] if selected != "NONE" else test_exp.iloc[0:0]
        sst = stats(sel)
        rows.append({
            "fold": fold,
            "train_start": y0,
            "train_end": y1,
            "test_year": yt,
            "selected": selected,
            "selected_test_n": sst["n"],
            "selected_test_net": sst["net"],
            "selected_test_pf": sst["pf"],
            "test_winner": str(test_rank.iloc[0]["variant"]) if not test_rank.empty else "NONE",
            "selected_rank": int(test_rank["variant"].tolist().index(selected) + 1) if selected in test_rank["variant"].tolist() else 0,
            "meaningful_test": sst["n"] >= 20,
        })
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", default="scratch/calm_context_excavation_trades.csv")
    ap.add_argument("--out-csv", default="scratch/calm_context_protocol_folds.csv")
    args = ap.parse_args()
    df = pd.read_csv(args.trades)
    missing = [c for c in AUDIT_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"missing audit columns: {missing}")
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError("audit counters not clean")
    df = df[df["window"] == "is"].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    folds = run(df, VARIANTS)
    folds.to_csv(args.out_csv, index=False)
    print(folds.to_string(index=False))
    picked = folds[folds["selected"] != "NONE"]
    print(
        f"\naggregate net=${picked['selected_test_net'].sum():,.0f} "
        f"n={int(picked['selected_test_n'].sum())} "
        f"meaningful={int(picked['meaningful_test'].sum())}/{len(picked)} "
        f"winner_matches={int((picked['selected'] == picked['test_winner']).sum())}/{len(picked)}"
    )
    if int(picked["meaningful_test"].sum()) < len(picked):
        print("verdict=reject_thin_test_fold")
    elif int((picked["selected"] == picked["test_winner"]).sum()) < 2:
        print("verdict=reject_heldout_does_not_confirm_selection")
    else:
        print("verdict=paper_candidate_only")
    print(f"wrote {args.out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
