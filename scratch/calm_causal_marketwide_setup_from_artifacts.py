from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures.basket import BASKET
from futures.swing_tf import costs_for_basket
from scratch.calm_causal_lag1_excavation import build_daily, price_inside


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


def market_days(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["inst"].eq("MES")].copy()
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"audit failed in market source {path}")
    return df[
        [
            "day",
            "prev_session_day",
            "prev_close_loc",
            "prev_rth_ret",
            "gap_from_prev_rth_close",
        ]
    ].rename(
        columns={
            "prev_session_day": "market_prev_session_day",
            "prev_close_loc": "market_prev_close_loc",
            "prev_rth_ret": "market_prev_rth_ret",
            "gap_from_prev_rth_close": "market_gap_from_prev_rth_close",
        }
    )


def build_window(market_path: str, data_dir: str, start: str, end: str, slippage_ticks: float) -> pd.DataFrame:
    mkt = market_days(market_path).set_index("day")
    daily = {
        inst: add_gap(build_daily(data_dir, inst, pd.Timestamp(start), pd.Timestamp(end))).set_index("day")
        for inst in ["MES", "MNQ"]
    }
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    rows = []
    for day, m in mkt.iterrows():
        for inst in ["MES", "MNQ"]:
            if day not in daily[inst].index:
                continue
            r = daily[inst].loc[day]
            for variant, ok in [
                ("market_mes_pcloc_trade_mesmnq", True),
                ("market_mes_pcloc_mkt_notdeep_trade_mesmnq", bool(m["market_gap_from_prev_rth_close"] >= -0.010)),
                ("market_mes_pcloc_inst_notdeep_trade_mesmnq", bool(r["gap_from_prev_rth_close"] >= -0.010)),
                (
                    "market_mes_pcloc_both_notdeep_trade_mesmnq",
                    bool(m["market_gap_from_prev_rth_close"] >= -0.010)
                    and bool(r["gap_from_prev_rth_close"] >= -0.010),
                ),
            ]:
                if not ok:
                    continue
                entry = float(r["p1000"])
                exit_px = float(r["p1555"])
                pnl = (exit_px - entry) * BASKET[inst].point_value - costs[inst]
                rows.append(
                    {
                        "variant": variant,
                        "inst": inst,
                        "direction": "LONG",
                        "day": pd.Timestamp(day).date().isoformat(),
                        "year": int(pd.Timestamp(day).year),
                        "market_inst": "MES",
                        "market_prev_session_day": m["market_prev_session_day"],
                        "market_prev_close_loc": float(m["market_prev_close_loc"]),
                        "market_prev_rth_ret": float(m["market_prev_rth_ret"]),
                        "market_gap_from_prev_rth_close": float(m["market_gap_from_prev_rth_close"]),
                        "prev_session_day": pd.Timestamp(r["prev_session_day"]).date().isoformat()
                        if not pd.isna(r["prev_session_day"])
                        else "",
                        "gap_from_prev_rth_close": float(r["gap_from_prev_rth_close"]),
                        "signal_time": r["t0930"],
                        "entry_time": r["t1000"],
                        "exit_time": r["t1555"],
                        "entry": entry,
                        "exit": exit_px,
                        "pnl": pnl,
                        "outside_exit_bar": 0 if price_inside(exit_px, r["low1555"], r["high1555"]) else 1,
                        "outside_entry_bar": 0 if price_inside(entry, r["low1000"], r["high1000"]) else 1,
                        "signal_after_entry": 1 if r["t0930"] > r["t1000"] else 0,
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


def select(s: pd.DataFrame) -> list[str]:
    keep = s[
        (s["n"] >= 250)
        & (s["net"] >= 5_000)
        & (s["pf"] >= 1.15)
        & (s["pos_years"] >= 5)
        & (s["pos_inst"] >= 2)
        & (s["top_year_share"] <= 0.75)
        & (s["audit"] == 0)
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


def main() -> int:
    windows = [
        ("is", "scratch/calm_causal_pcloc_shape_gap_is.csv", "data/cache/futures/frozen_sim", "2018-01-01", "2024-12-31"),
        ("2025", "scratch/calm_causal_pcloc_shape_gap_2025.csv", "data/cache/futures/frozen_2025_sim", "2025-01-01", "2025-12-31"),
        ("2026_sanity", "scratch/calm_causal_pcloc_shape_gap_2026_sanity.csv", "data/cache/futures", "2026-01-01", "2026-08-19"),
    ]
    prefix = "scratch/calm_causal_marketwide_setup_artifact"
    all_frames = {}
    selected: list[str] | None = None
    for name, market_path, data_dir, start, end in windows:
        df = build_window(market_path, data_dir, start, end, 2.0)
        df.to_csv(f"{prefix}_{name}.csv", index=False)
        s = summarize(df, name)
        s.to_csv(f"{prefix}_{name}_summary.csv", index=False)
        if name == "is":
            selected = select(s)
            print("\n=== IS ===")
            print(s.to_string(index=False))
            print("\nselected_before_oos=" + (",".join(selected) if selected else "NONE"))
            if not selected:
                return 0
        else:
            print(f"\n=== {name} ===")
            print(s[s["variant"].isin(selected)].to_string(index=False))
        all_frames[name] = df
    pooled = pd.concat([all_frames["2025"], all_frames["2026_sanity"]], ignore_index=True)
    pooled.to_csv(f"{prefix}_pooled_sanity.csv", index=False)
    sp = summarize(pooled, "pooled_sanity")
    sp.to_csv(f"{prefix}_pooled_sanity_summary.csv", index=False)
    rows = []
    rng = np.random.default_rng(20260821)
    for variant in selected or []:
        for name, df in [("2025", all_frames["2025"]), ("pooled_sanity", pooled)]:
            g = df[df["variant"] == variant]
            rows.append({"window": name, "variant": variant, **stats(g), **bootstrap(g, 5000, rng)})
    boot = pd.DataFrame(rows)
    boot.to_csv(f"{prefix}_bootstrap.csv", index=False)
    print("\n=== pooled_sanity selected ===")
    print(sp[sp["variant"].isin(selected or [])].to_string(index=False))
    print("\n=== bootstrap ===")
    print(boot.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
