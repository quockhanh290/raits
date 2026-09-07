from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "pnl": 0.0, "pf": 0.0, "exp": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = df.groupby(pd.to_datetime(df["day"]))["pnl"].sum().sort_index()
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    return {
        "n": int(len(df)),
        "pnl": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "exp": float(pnl.mean()),
        "maxdd": dd,
    }


def robustness(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"pos_years": 0, "pos_inst": 0, "top_share": 1.0}
    by_year = df.groupby("year")["pnl"].sum()
    by_inst = df.groupby("inst")["pnl"].sum()
    total = float(df["pnl"].sum())
    return {
        "pos_years": int((by_year > 0).sum()),
        "pos_inst": int((by_inst > 0).sum()),
        "top_share": float(by_year.max() / total) if total > 0 else 1.0,
    }


def eligible(df: pd.DataFrame, min_years: int) -> bool:
    required_audit_cols = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]
    missing = [c for c in required_audit_cols if c not in df.columns]
    if missing:
        raise ValueError(f"missing audit columns in WFO input: {missing}")
    st = stats(df)
    rb = robustness(df)
    return (
        st["n"] >= 100
        and st["pnl"] > 0
        and st["pf"] >= 1.10
        and rb["pos_years"] >= min_years
        and rb["pos_inst"] >= 2
        and rb["top_share"] <= 0.75
        and int(df["outside_exit_bar"].sum()) == 0
        and int(df["outside_entry_bar"].sum()) == 0
        and int(df["signal_after_entry"].sum()) == 0
    )


def choose(train: pd.DataFrame, variants: list[str], min_years: int) -> str | None:
    rows = []
    for v in variants:
        g = train[train["variant"] == v]
        if not eligible(g, min_years):
            continue
        st = stats(g)
        rb = robustness(g)
        rows.append((v, st["pnl"], st["pf"], rb["top_share"]))
    rows.sort(key=lambda x: (x[1], x[2], -x[3]), reverse=True)
    return rows[0][0] if rows else None


def fmt(st: dict) -> str:
    return f"n={st['n']:4d} pnl=${st['pnl']:8,.0f} pf={st['pf']:4.2f} exp={st['exp']:6.2f} maxdd=${st['maxdd']:7,.0f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-csv", default="scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv")
    ap.add_argument("--variants", nargs="+", default=[
        "on_neg_fade_raw_x1555",
        "on_neg_fade_mod001_010_x1555",
        "on_neg_fade_mod002_010_x1555",
    ])
    ap.add_argument("--out-csv", default="scratch/calm_neg_overnight_wfo_stability.csv")
    args = ap.parse_args()

    df = pd.read_csv(args.is_csv, parse_dates=["day", "signal_time", "entry_time", "exit_time"])
    df = df[df["variant"].isin(args.variants)].copy()
    required_audit_cols = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]
    missing = [c for c in required_audit_cols if c not in df.columns]
    if missing:
        raise ValueError(f"missing audit columns in WFO input: {missing}; regenerate the sweep CSV with the fixed probes")
    print(
        f"loaded {args.is_csv} rows={len(df)} "
        f"outside_exit_bar={int(df['outside_exit_bar'].sum())} "
        f"outside_entry_bar={int(df['outside_entry_bar'].sum())} "
        f"signal_after_entry={int(df['signal_after_entry'].sum())}"
    )

    print("\n=== full IS variants ===")
    for v in args.variants:
        g = df[df["variant"] == v]
        st = stats(g)
        rb = robustness(g)
        print(f"{v:<34} {fmt(st)} posY={rb['pos_years']} posI={rb['pos_inst']} topShare={rb['top_share']:.2f}")

    folds = [
        ("train2018_2021_test2022", 2018, 2021, 2022),
        ("train2019_2022_test2023", 2019, 2022, 2023),
        ("train2020_2023_test2024", 2020, 2023, 2024),
    ]
    rows = []
    print("\n=== rolling WFO coarse selection ===")
    for name, y0, y1, yt in folds:
        train = df[(df["year"] >= y0) & (df["year"] <= y1)]
        test = df[df["year"] == yt]
        selected = choose(train, args.variants, min_years=max(2, y1 - y0))
        print(f"\n{name} selected={selected or 'NONE'}")
        for v in args.variants:
            tr = train[train["variant"] == v]
            te = test[test["variant"] == v]
            trst = stats(tr)
            testst = stats(te)
            rb = robustness(tr)
            marker = "*" if v == selected else " "
            print(f"{marker} {v:<34} train {fmt(trst)} posY={rb['pos_years']} topShare={rb['top_share']:.2f} | test {fmt(testst)}")
            rows.append({
                "fold": name,
                "variant": v,
                "selected": v == selected,
                "train_start": y0,
                "train_end": y1,
                "test_year": yt,
                **{f"train_{k}": val for k, val in trst.items()},
                **{f"test_{k}": val for k, val in testst.items()},
                **{f"train_{k}": val for k, val in rb.items()},
            })

    out = pd.DataFrame(rows)
    out.to_csv(args.out_csv, index=False)
    print(f"\nwrote {args.out_csv}")

    picked = out[out["selected"]]
    if not picked.empty:
        print("\n=== selected fold aggregate ===")
        print(f"selected folds={len(picked)} test_pnl=${picked['test_pnl'].sum():,.0f} "
              f"test_n={int(picked['test_n'].sum())} "
              f"avg_test_pf={picked['test_pf'].replace([math.inf], pd.NA).dropna().mean():.2f}")
        print("selected variants:", ", ".join(picked["variant"].tolist()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
