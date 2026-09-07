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


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def calm_days(path: str) -> set[pd.Timestamp]:
    days = pd.read_csv(path, usecols=["day"])["day"].dropna().unique()
    return {pd.Timestamp(x).normalize() for x in days}


def price_inside_bar(price: float, bar: pd.Series) -> bool:
    px = float(price)
    lo = float(bar["low"])
    hi = float(bar["high"])
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def first_at_or_after(g: pd.DataFrame, ts: pd.Timestamp | str) -> tuple[pd.Timestamp, pd.Series] | None:
    if isinstance(ts, str):
        sub = g[g.index.time >= pd.Timestamp(ts).time()]
    else:
        sub = g[g.index > ts]
    if sub.empty:
        return None
    return sub.index[0], sub.iloc[0]


def daily_context(df: pd.DataFrame) -> pd.DataFrame:
    rth = df.between_time("09:30", "15:59").copy()
    rth["day"] = trading_day_index(rth.index)
    out = rth.groupby("day", sort=True).agg(
        rth_open=("open", "first"),
        rth_high=("high", "max"),
        rth_low=("low", "min"),
        rth_close=("close", "last"),
        bars=("open", "size"),
    ).reset_index()
    out = out[out["bars"] >= 160].drop(columns=["bars"])
    prev = out[["rth_open", "rth_high", "rth_low", "rth_close"]].shift(1)
    out["prev_high"] = prev["rth_high"]
    out["prev_low"] = prev["rth_low"]
    out["prev_close"] = prev["rth_close"]
    out["prev_mid"] = (out["prev_high"] + out["prev_low"]) / 2.0
    return out.set_index("day")


def feasible_target_or_time(
    rth: pd.DataFrame,
    entry_ts: pd.Timestamp,
    direction: str,
    target_px: float | None,
    time_exit: str,
) -> tuple[pd.Timestamp, float, str, int] | None:
    later = rth[rth.index > entry_ts]
    if later.empty:
        return None
    time_bar = first_at_or_after(later, time_exit)
    if time_bar is None:
        return None
    time_ts, time_row = time_bar
    path = later[later.index <= time_ts]
    if target_px is not None and pd.notna(target_px):
        for ts, row in path.iterrows():
            op = float(row["open"])
            hi = float(row["high"])
            lo = float(row["low"])
            if direction == "LONG" and hi >= target_px:
                fill = target_px if lo <= target_px <= hi else op
                return ts, fill, "target", 0 if price_inside_bar(fill, row) else 1
            if direction == "SHORT" and lo <= target_px:
                fill = target_px if lo <= target_px <= hi else op
                return ts, fill, "target", 0 if price_inside_bar(fill, row) else 1
    px = float(time_row["open"])
    return time_ts, px, "time", 0 if price_inside_bar(px, time_row) else 1


def build_inst(
    df: pd.DataFrame,
    inst: str,
    days: set[pd.Timestamp],
    start: pd.Timestamp,
    end: pd.Timestamp,
    cost: float,
) -> list[dict]:
    ctx = daily_context(df)
    work = df.copy()
    work["day"] = trading_day_index(work.index)
    wanted_days = {d for d in days if start <= d <= end}
    work = work[work["day"].isin(wanted_days)]
    pv = BASKET[inst].point_value
    rows = []
    scan_ends = ["10:00", "10:30"]
    exits = ["15:55", "target_mid_1555", "target_close_1555"]
    for day, g in work.groupby("day", sort=True):
        day = pd.Timestamp(day).normalize()
        if day < start or day > end or day not in days or day not in ctx.index:
            continue
        c = ctx.loc[day]
        if pd.isna(c["prev_high"]) or pd.isna(c["prev_low"]):
            continue
        rth = g.between_time("09:30", "15:59")
        if len(rth) < 160:
            continue
        for scan_end in scan_ends:
            scan = rth.between_time("09:30", scan_end)
            if len(scan) < 5:
                continue
            broke_low = False
            broke_high = False
            long_signal_ts = None
            short_signal_ts = None
            for ts, bar in scan.iterrows():
                if float(bar["low"]) < float(c["prev_low"]):
                    broke_low = True
                if float(bar["high"]) > float(c["prev_high"]):
                    broke_high = True
                if broke_low and long_signal_ts is None and float(bar["close"]) >= float(c["prev_low"]):
                    long_signal_ts = ts
                if broke_high and short_signal_ts is None and float(bar["close"]) <= float(c["prev_high"]):
                    short_signal_ts = ts
            signals = []
            if long_signal_ts is not None:
                signals.append(("low_reclaim_long", "LONG", long_signal_ts))
            if short_signal_ts is not None:
                signals.append(("high_fail_short", "SHORT", short_signal_ts))
            for setup, direction, sig_ts in signals:
                entry = first_at_or_after(rth, sig_ts)
                if entry is None:
                    continue
                entry_ts, entry_row = entry
                entry_px = float(entry_row["open"])
                outside_entry = 0 if price_inside_bar(entry_px, entry_row) else 1
                signal_after_entry = 1 if sig_ts >= entry_ts else 0
                for ex in exits:
                    target = None
                    if ex == "target_mid_1555":
                        target = float(c["prev_mid"])
                    elif ex == "target_close_1555":
                        target = float(c["prev_close"])
                    result = feasible_target_or_time(rth, entry_ts, direction, target, "15:55")
                    if result is None:
                        continue
                    exit_ts, exit_px, reason, outside_exit = result
                    if exit_ts <= entry_ts:
                        continue
                    points = exit_px - entry_px if direction == "LONG" else entry_px - exit_px
                    rows.append({
                        "variant": f"{setup}_scan{scan_end.replace(':', '')}_x{ex}",
                        "inst": inst,
                        "direction": direction,
                        "day": day.date().isoformat(),
                        "year": int(day.year),
                        "signal_time": sig_ts,
                        "entry_time": entry_ts,
                        "exit_time": exit_ts,
                        "entry": entry_px,
                        "exit": float(exit_px),
                        "pnl": points * pv - cost,
                        "exit_reason": reason,
                        "outside_exit_bar": outside_exit,
                        "outside_entry_bar": outside_entry,
                        "signal_after_entry": signal_after_entry,
                        "prev_high": float(c["prev_high"]),
                        "prev_low": float(c["prev_low"]),
                        "prev_mid": float(c["prev_mid"]),
                        "prev_close": float(c["prev_close"]),
                    })
    return rows


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


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        rows.append({
            "variant": variant,
            **st,
            "pos_years": int((by_year > 0).sum()),
            "years": int(len(by_year)),
            "pos_inst": int((by_inst > 0).sum()),
            "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 else 1.0,
            "outside_exit_bar": int(g["outside_exit_bar"].sum()),
            "outside_entry_bar": int(g["outside_entry_bar"].sum()),
            "signal_after_entry": int(g["signal_after_entry"].sum()),
        })
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def select_candidates(summary: pd.DataFrame, limit: int) -> list[str]:
    keep = summary[
        (summary["n"] >= 100)
        & (summary["net"] >= 3_000)
        & (summary["pf"] >= 1.15)
        & (summary["pos_years"] >= 4)
        & (summary["pos_inst"] >= 2)
        & (summary["top_year_share"] <= 0.75)
        & (summary["outside_exit_bar"] == 0)
        & (summary["outside_entry_bar"] == 0)
        & (summary["signal_after_entry"] == 0)
    ].copy()
    return keep.sort_values(["net", "pf"], ascending=False)["variant"].head(limit).tolist()


def print_summary(title: str, summary: pd.DataFrame, selected: list[str] | None = None) -> None:
    print(f"\n=== {title} ===")
    tbl = summary if selected is None else summary[summary["variant"].isin(selected)]
    if tbl.empty:
        print("no rows")
        return
    for _, r in tbl.head(30).iterrows():
        print(
            f"{r['variant']:<46} n={int(r['n']):>4} days={int(r['days']):>3} "
            f"net=${r['net']:>8,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>6.2f} "
            f"posY={int(r['pos_years'])}/{int(r['years'])} posI={int(r['pos_inst'])} "
            f"audit={int(r['outside_exit_bar'])}/{int(r['outside_entry_bar'])}/{int(r['signal_after_entry'])}"
        )


def run_window(name: str, data_dir: str, start: str, end: str, calm_csv: str, instruments: set[str]) -> pd.DataFrame:
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
        ss = (start_ts - pd.Timedelta(days=10)).tz_localize(df.index.tz)
        ee = (end_ts + pd.Timedelta(days=2)).tz_localize(df.index.tz)
        df = df[(df.index >= ss) & (df.index <= ee)].copy()
        rows.extend(build_inst(df, inst, days, start_ts, end_ts, costs[inst]))
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-prefix", default="scratch/calm_prior_range_reclaim")
    ap.add_argument("--select-limit", type=int, default=2)
    ap.add_argument("--which", nargs="+", choices=["is", "2025", "2026"], default=["is", "2025", "2026"])
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--select", nargs="+", default=None)
    args = ap.parse_args()

    selected = args.select
    if "is" in args.which:
        is_df = run_window("is", *WINDOWS["is"], set(args.instruments))
        is_path = f"{args.out_prefix}_is.csv"
        is_df.to_csv(is_path, index=False)
        is_summary = summarize(is_df)
        is_summary.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
        print_summary("IS prior range reclaim/failure", is_summary)
        selected = selected or select_candidates(is_summary, args.select_limit)
        print("\n=== selected before OOS ===")
        print(",".join(selected) if selected else "NONE")
        if not selected:
            return 0

    for name in ["2025", "2026"]:
        if name not in args.which:
            continue
        if not selected:
            raise SystemExit("--select is required when running OOS without IS")
        df = run_window(name, *WINDOWS[name], set(args.instruments))
        path = f"{args.out_prefix}_{name}.csv"
        df.to_csv(path, index=False)
        summary = summarize(df)
        summary.to_csv(f"{args.out_prefix}_{name}_summary.csv", index=False)
        print_summary(f"{name} selected", summary, selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
