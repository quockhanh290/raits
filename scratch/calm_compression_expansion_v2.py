from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket


WINDOWS = {
    "is": ("data/cache/futures/frozen_sim", "2018-01-01", "2024-12-31", "scratch/calm_drift_basket_big_is.csv"),
    "2025": ("data/cache/futures/frozen_2025_sim", "2025-01-01", "2025-12-31", "scratch/calm_drift_basket_big_2025.csv"),
    "2026": ("data/cache/futures", "2026-01-01", "2026-08-19", "scratch/calm_drift_basket_big_2026.csv"),
}
AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def calm_days(path: str) -> set[pd.Timestamp]:
    days = pd.read_csv(path, usecols=["day"])["day"].dropna().unique()
    return {pd.Timestamp(x).normalize() for x in days}


def price_inside(price: float, bar: pd.Series) -> bool:
    lo = float(bar["low"])
    hi = float(bar["high"])
    px = float(price)
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def at_or_after(g: pd.DataFrame, hhmm: str) -> tuple[pd.Timestamp, pd.Series] | None:
    sub = g[g.index.time >= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[0], sub.iloc[0]


def build_daily(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rth = df.between_time("09:30", "15:59").copy()
    rth["day"] = trading_day_index(rth.index)
    rows = []
    for day, g in rth.groupby("day", sort=True):
        day = pd.Timestamp(day).normalize()
        if day < start - pd.Timedelta(days=10) or day > end:
            continue
        if len(g) < 160:
            continue
        b0930 = at_or_after(g, "09:30")
        b1000 = at_or_after(g, "10:00")
        b1030 = at_or_after(g, "10:30")
        b1031 = at_or_after(g, "10:31")
        b1400 = at_or_after(g, "14:00")
        b1555 = at_or_after(g, "15:55")
        if not all([b0930, b1000, b1030, b1031, b1400, b1555]):
            continue
        first60 = g.between_time("09:30", "10:30")
        rows.append({
            "day": day,
            "t1030": b1030[0],
            "t1031": b1031[0],
            "t1400": b1400[0],
            "t1555": b1555[0],
            "open": float(b0930[1]["open"]),
            "p1000": float(b1000[1]["open"]),
            "p1030": float(b1030[1]["open"]),
            "entry": float(b1031[1]["open"]),
            "p1400": float(b1400[1]["open"]),
            "p1555": float(b1555[1]["open"]),
            "entry_bar_low": float(b1031[1]["low"]),
            "entry_bar_high": float(b1031[1]["high"]),
            "bar1400_low": float(b1400[1]["low"]),
            "bar1400_high": float(b1400[1]["high"]),
            "bar1555_low": float(b1555[1]["low"]),
            "bar1555_high": float(b1555[1]["high"]),
            "rth_high": float(g["high"].max()),
            "rth_low": float(g["low"].min()),
            "first_high": float(first60["high"].max()),
            "first_low": float(first60["low"].min()),
        })
    out = pd.DataFrame(rows).sort_values("day")
    out["rth_range_pct"] = (out["rth_high"] - out["rth_low"]) / out["open"]
    out["first_range_pct"] = (out["first_high"] - out["first_low"]) / out["open"]
    out["drive60"] = out["p1030"] / out["open"] - 1.0
    out["prev_range_pct"] = out["rth_range_pct"].shift(1)
    out["prev_range_med20"] = out["rth_range_pct"].rolling(20, min_periods=10).median().shift(1)
    out["prev3_range_pct"] = (out["rth_high"].shift(1).rolling(3).max() - out["rth_low"].shift(1).rolling(3).min()) / out["open"]
    out["prev_high"] = out["rth_high"].shift(1)
    out["prev_low"] = out["rth_low"].shift(1)
    return out[out["day"] >= start].set_index("day")


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "days": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "maxdd": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    return {"n": int(len(df)), "days": int(df["day"].nunique()), "net": float(pnl.sum()),
            "pf": gw / gl if gl else math.inf, "avg": float(pnl.mean()),
            "maxdd": float((eq.cummax() - eq).max()) if len(eq) else 0.0}


def meaningful_years(df: pd.DataFrame) -> tuple[int, int]:
    if df.empty:
        return 0, 0
    y = df.groupby("year").agg(trades=("pnl", "size"), days=("day", "nunique"), net=("pnl", "sum"))
    y = y[(y["trades"] >= 20) | (y["days"] >= 10)]
    return int((y["net"] > 0).sum()), int(len(y))


def run_window(name: str, data_dir: str, start: str, end: str, calm_csv: str, instruments: set[str],
               selected: set[str] | None = None) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    days = calm_days(calm_csv)
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=2.0).items()}
    rows = []
    for inst, contract in BASKET.items():
        if inst not in instruments:
            continue
        print(f"[{name}] {inst}", flush=True)
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        ss = (start_ts - pd.Timedelta(days=40)).tz_localize(df.index.tz)
        ee = (end_ts + pd.Timedelta(days=2)).tz_localize(df.index.tz)
        d = build_daily(df[(df.index >= ss) & (df.index <= ee)], start_ts, end_ts)
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for day, r in d.iterrows():
            day = pd.Timestamp(day).normalize()
            if day not in days or pd.isna(r["prev_range_med20"]):
                continue
            compress1 = bool(r["prev_range_pct"] <= r["prev_range_med20"])
            compress3 = bool(r["prev3_range_pct"] <= 3.0 * r["prev_range_med20"])
            expand60 = bool(r["first_range_pct"] > r["prev_range_med20"])
            break_up = bool(r["first_high"] > r["prev_high"] and r["drive60"] > 0)
            break_dn = bool(r["first_low"] < r["prev_low"] and r["drive60"] < 0)
            configs = [
                ("c1_exp60", compress1 and expand60),
                ("c3_exp60", compress3 and expand60),
            ]
            sides = [("long", "LONG", break_up), ("short", "SHORT", break_dn)]
            for cname, ok_ctx in configs:
                if not ok_ctx:
                    continue
                for sname, direction, ok_side in sides:
                    if not ok_side:
                        continue
                    for ex_name, ex_px_col, ex_ts_col, lo_col, hi_col in [
                        ("x1400", "p1400", "t1400", "bar1400_low", "bar1400_high"),
                        ("x1555", "p1555", "t1555", "bar1555_low", "bar1555_high"),
                    ]:
                        variant = f"{cname}_{sname}_{ex_name}"
                        if selected is not None and variant not in selected:
                            continue
                        entry = float(r["entry"])
                        exit_px = float(r[ex_px_col])
                        pts = exit_px - entry if direction == "LONG" else entry - exit_px
                        entry_inside = float(r["entry_bar_low"]) <= entry <= float(r["entry_bar_high"])
                        exit_inside = float(r[lo_col]) <= exit_px <= float(r[hi_col])
                        rows.append({
                            "variant": variant,
                            "inst": inst,
                            "direction": direction,
                            "day": day.date().isoformat(),
                            "year": int(day.year),
                            "signal_time": r["t1030"],
                            "entry_time": r["t1031"],
                            "exit_time": r[ex_ts_col],
                            "entry": entry,
                            "exit": exit_px,
                            "pnl": pts * pv - cost,
                            "outside_exit_bar": 0 if exit_inside else 1,
                            "outside_entry_bar": 0 if entry_inside else 1,
                            "signal_after_entry": 1 if r["t1030"] >= r["t1031"] else 0,
                            "prev_range_pct": float(r["prev_range_pct"]),
                            "prev_range_med20": float(r["prev_range_med20"]),
                            "first_range_pct": float(r["first_range_pct"]),
                            "drive60": float(r["drive60"]),
                        })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for v, g in df.groupby("variant"):
        st = stats(g)
        py, my = meaningful_years(g)
        by_inst = g.groupby("inst")["pnl"].sum()
        by_year = g.groupby("year")["pnl"].sum()
        rows.append({"variant": v, **st, "pos_meaningful_years": py, "meaningful_years": my,
                     "pos_inst": int((by_inst > 0).sum()),
                     "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 else 1.0,
                     **{c: int(g[c].sum()) for c in AUDIT_COLS}})
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def select_candidates(summary: pd.DataFrame) -> list[str]:
    keep = summary[
        (summary["n"] >= 100)
        & (summary["net"] >= 3_000)
        & (summary["pf"] >= 1.15)
        & (summary["pos_meaningful_years"] >= 4)
        & (summary["pos_inst"] >= 2)
        & (summary["top_year_share"] <= 0.75)
        & (summary[AUDIT_COLS].sum(axis=1) == 0)
    ].copy()
    return keep.sort_values(["net", "pf"], ascending=False)["variant"].head(2).tolist()


def print_summary(title: str, summary: pd.DataFrame, selected: list[str] | None = None) -> None:
    print(f"\n=== {title} ===")
    tbl = summary if selected is None else summary[summary["variant"].isin(selected)]
    if tbl.empty:
        print("no rows")
        return
    for _, r in tbl.iterrows():
        print(f"{r['variant']:<20} n={int(r['n']):>4} days={int(r['days']):>3} net=${r['net']:>8,.0f} "
              f"pf={r['pf']:>5.2f} avg=${r['avg']:>6.2f} posY={int(r['pos_meaningful_years'])}/{int(r['meaningful_years'])} "
              f"posI={int(r['pos_inst'])} audit={int(r['outside_exit_bar'])}/{int(r['outside_entry_bar'])}/{int(r['signal_after_entry'])}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", choices=["is", "2025", "2026"], default=["is", "2025", "2026"])
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--select", nargs="+", default=None)
    ap.add_argument("--out-prefix", default="scratch/calm_compression_expansion_v2")
    args = ap.parse_args()
    selected = args.select
    if "is" in args.which:
        df = run_window("is", *WINDOWS["is"], set(args.instruments))
        df.to_csv(f"{args.out_prefix}_is.csv", index=False)
        sm = summarize(df)
        sm.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
        print_summary("IS compression expansion v2", sm)
        selected = selected or select_candidates(sm)
        print("\n=== selected before OOS ===")
        print(",".join(selected) if selected else "NONE")
        if not selected:
            return 0
    for window in ["2025", "2026"]:
        if window not in args.which:
            continue
        if not selected:
            raise SystemExit("--select required when OOS without IS")
        df = run_window(window, *WINDOWS[window], set(args.instruments), set(selected))
        df.to_csv(f"{args.out_prefix}_{window}.csv", index=False)
        sm = summarize(df)
        sm.to_csv(f"{args.out_prefix}_{window}_summary.csv", index=False)
        print_summary(f"{window} selected", sm, selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
