from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import BASKET
from futures.swing_tf import costs_for_basket
from scratch.calm_causal_lag1_excavation import build_daily, causal_labels, price_inside


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


def add_gap(d: pd.DataFrame) -> pd.DataFrame:
    out = d.sort_values("day").copy()
    out["prev_session_day"] = out["day"].shift(1)
    out["gap_from_prev_rth_close"] = out["p0930"] / out["prev_rth_close"] - 1.0
    return out


def build_window(
    data_dir: str,
    start: str,
    end: str,
    labels: dict[pd.Timestamp, str],
    slippage_ticks: float,
) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    daily = {inst: add_gap(build_daily(data_dir, inst, start_ts, end_ts)) for inst in ["MES", "MNQ"]}
    mes = daily["MES"].set_index("day")
    mnq = daily["MNQ"].set_index("day")
    rows = []
    for day, m in mes.iterrows():
        day = pd.Timestamp(day).normalize()
        if labels.get(day) != "Calm":
            continue
        if pd.isna(m["prev_close_loc"]) or pd.isna(m["prev_rth_ret"]):
            continue
        market_setup = bool(m["prev_close_loc"] <= 1 / 3 and m["prev_rth_ret"] <= 0)
        if not market_setup:
            continue
        for variant, market_gap_ok in [
            ("market_mes_pcloc_trade_mesmnq", True),
            ("market_mes_pcloc_mkt_notdeep_trade_mesmnq", bool(m["gap_from_prev_rth_close"] >= -0.010)),
        ]:
            if not market_gap_ok:
                continue
            for inst, table in [("MES", mes), ("MNQ", mnq)]:
                if day not in table.index:
                    continue
                r = table.loc[day]
                inst_gap_ok = bool(r["gap_from_prev_rth_close"] >= -0.010)
                for final_variant, ok in [
                    (variant, True),
                    (variant + "_inst_notdeep", inst_gap_ok),
                ]:
                    if not ok:
                        continue
                    entry = float(r["p1000"])
                    exit_px = float(r["p1555"])
                    pv = BASKET[inst].point_value
                    pnl = (exit_px - entry) * pv - costs[inst]
                    rows.append(
                        {
                            "variant": final_variant,
                            "inst": inst,
                            "direction": "LONG",
                            "day": day.date().isoformat(),
                            "year": int(day.year),
                            "market_inst": "MES",
                            "market_prev_close_loc": float(m["prev_close_loc"]),
                            "market_prev_rth_ret": float(m["prev_rth_ret"]),
                            "market_gap_from_prev_rth_close": float(m["gap_from_prev_rth_close"]),
                            "prev_session_day": pd.Timestamp(r["prev_session_day"]).date().isoformat()
                            if not pd.isna(r["prev_session_day"])
                            else "",
                            "gap_from_prev_rth_close": float(r["gap_from_prev_rth_close"]),
                            "signal_time": m["t0930"],
                            "entry_time": r["t1000"],
                            "exit_time": r["t1555"],
                            "entry": entry,
                            "exit": exit_px,
                            "pnl": pnl,
                            "outside_exit_bar": 0 if price_inside(exit_px, r["low1555"], r["high1555"]) else 1,
                            "outside_entry_bar": 0 if price_inside(entry, r["low1000"], r["high1000"]) else 1,
                            "signal_after_entry": 1 if m["t0930"] > r["t1000"] else 0,
                        }
                    )
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        rows.append(
            {
                "window": window,
                "variant": variant,
                **st,
                "pos_years": int((by_year > 0).sum()),
                "years": int(len(by_year)),
                "pos_inst": int((by_inst > 0).sum()),
                "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 and not by_year.empty else 1.0,
                "mes_net": float(by_inst.get("MES", 0.0)),
                "mnq_net": float(by_inst.get("MNQ", 0.0)),
                "audit": int(g[AUDIT_COLS].sum().sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def select(summary: pd.DataFrame) -> list[str]:
    keep = summary[
        (summary["n"] >= 250)
        & (summary["net"] >= 5_000)
        & (summary["pf"] >= 1.15)
        & (summary["pos_years"] >= 5)
        & (summary["pos_inst"] >= 2)
        & (summary["top_year_share"] <= 0.75)
        & (summary["audit"] == 0)
    ]
    return keep.sort_values(["net", "pf"], ascending=False)["variant"].head(4).tolist()


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


def print_summary(title: str, s: pd.DataFrame, selected: list[str] | None = None) -> None:
    print(f"\n=== {title} ===")
    tbl = s if selected is None else s[s["variant"].isin(selected)]
    for _, r in tbl.iterrows():
        print(
            f"{r['variant']:<52} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"dd=${r['maxdd']:>7,.0f} posY={int(r['pos_years'])}/{int(r['years'])} "
            f"posI={int(r['pos_inst'])} MES/MNQ=${r['mes_net']:.0f}/{r['mnq_net']:.0f}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--data-dir-2025", default="data/cache/futures/frozen_2025_sim")
    ap.add_argument("--data-dir-2026", default="data/cache/futures")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end-is", default="2022-12-31")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--out-prefix", default="scratch/calm_causal_marketwide_setup")
    args = ap.parse_args()

    labels_is = causal_labels(args.regime_csv, args.hmm_train_end, args.hmm_fit_end_is)
    labels_oos = causal_labels(args.regime_csv, args.hmm_train_end, args.hmm_fit_end_oos)
    is_df = build_window(args.data_dir, "2018-01-01", "2024-12-31", labels_is, args.slippage_ticks)
    is_df.to_csv(f"{args.out_prefix}_is.csv", index=False)
    s_is = summarize(is_df, "is")
    s_is.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print_summary("IS market-wide MES setup", s_is)
    selected = select(s_is)
    print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))
    if not selected:
        return 0
    o25 = build_window(args.data_dir_2025, "2025-01-01", "2025-12-31", labels_oos, args.slippage_ticks)
    o26 = build_window(args.data_dir_2026, "2026-01-01", "2026-08-19", labels_oos, args.slippage_ticks)
    pooled = pd.concat([o25, o26], ignore_index=True)
    for name, df in [("2025", o25), ("2026_sanity", o26), ("pooled_sanity", pooled)]:
        df.to_csv(f"{args.out_prefix}_{name}.csv", index=False)
        s = summarize(df, name)
        s.to_csv(f"{args.out_prefix}_{name}_summary.csv", index=False)
        print_summary(name, s, selected)
    rng = np.random.default_rng(20260821)
    rows = []
    for variant in selected:
        for name, df in [("2025", o25), ("pooled_sanity", pooled)]:
            g = df[df["variant"] == variant]
            rows.append({"window": name, "variant": variant, **stats(g), **bootstrap(g, 5000, rng)})
    boot = pd.DataFrame(rows)
    boot.to_csv(f"{args.out_prefix}_bootstrap.csv", index=False)
    print("\n=== bootstrap ===")
    print(boot.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
