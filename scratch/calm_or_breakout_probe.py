from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "pnl": 0.0, "pf": 0.0, "exp": 0.0}
    pnl = df["pnl"].astype(float)
    gross_win = float(pnl[pnl > 0].sum())
    gross_loss = float(-pnl[pnl < 0].sum())
    return {
        "n": int(len(df)),
        "pnl": float(pnl.sum()),
        "pf": gross_win / gross_loss if gross_loss else math.inf,
        "exp": float(pnl.mean()),
    }


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def at_or_after(g: pd.DataFrame, hhmm: str, col: str = "open") -> tuple[pd.Timestamp, float] | None:
    sub = g[g.index.time >= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[0], float(sub.iloc[0][col])


def feasible_exit(g: pd.DataFrame, direction: str, entry_ts: pd.Timestamp, stop: float,
                  target: float | None, time_exit: str) -> tuple[pd.Timestamp, float, str, int] | None:
    later = g[g.index > entry_ts]
    if later.empty:
        return None
    time_hit = at_or_after(later, time_exit, "open")
    time_ts = time_hit[0] if time_hit else later.index[-1]
    time_px = time_hit[1] if time_hit else float(later.iloc[-1]["close"])

    for ts, bar in later.iterrows():
        if ts > time_ts:
            break
        opened = float(bar["open"])
        low = float(bar["low"])
        high = float(bar["high"])
        if direction == "LONG":
            stop_hit = low <= stop
            target_hit = target is not None and high >= target
            if stop_hit or target_hit:
                if stop_hit and target_hit:
                    level, reason = stop, "stop_first_tiebreak"
                elif stop_hit:
                    level, reason = stop, "stop"
                else:
                    level, reason = float(target), "target"
                feasible = low <= level <= high
                return ts, level if feasible else opened, reason, 0 if feasible or opened == float(bar["open"]) else 1
        else:
            stop_hit = high >= stop
            target_hit = target is not None and low <= target
            if stop_hit or target_hit:
                if stop_hit and target_hit:
                    level, reason = stop, "stop_first_tiebreak"
                elif stop_hit:
                    level, reason = stop, "stop"
                else:
                    level, reason = float(target), "target"
                feasible = low <= level <= high
                return ts, level if feasible else opened, reason, 0 if feasible or opened == float(bar["open"]) else 1
    return time_ts, time_px, "time", 0


def add_trade(rows: list[dict], *, variant: str, inst: str, direction: str, day: pd.Timestamp,
              signal_ts: pd.Timestamp, entry_ts: pd.Timestamp, exit_ts: pd.Timestamp,
              entry: float, exit_px: float, point_value: float, cost: float,
              outside_exit_bar: int, meta: dict) -> None:
    pnl_pts = exit_px - entry if direction == "LONG" else entry - exit_px
    rows.append({
        "variant": variant,
        "inst": inst,
        "direction": direction,
        "day": day.date().isoformat(),
        "year": int(day.year),
        "signal_time": signal_ts,
        "entry_time": entry_ts,
        "exit_time": exit_ts,
        "entry": entry,
        "exit": exit_px,
        "pnl": pnl_pts * point_value - cost,
        "outside_exit_bar": outside_exit_bar,
        **meta,
    })


def load_days(data_dir: str, start: str, end: str, instruments: set[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for inst, contract in BASKET.items():
        if inst not in instruments:
            continue
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        s = pd.Timestamp(start).tz_localize(df.index.tz)
        e = pd.Timestamp(end).tz_localize(df.index.tz) + pd.Timedelta(days=1)
        df = df[(df.index >= s - pd.Timedelta(days=1)) & (df.index <= e)]
        work = df.copy()
        work["tday"] = trading_day_index(work.index)
        out[inst] = work
    return out


def run_variants(days: dict[str, pd.DataFrame], labels: dict, slippage_ticks: float,
                 selected: set[str] | None = None) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    rows: list[dict] = []
    for inst, df in days.items():
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for day, g in df.groupby("tday"):
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            rth = g.between_time("09:30", "15:59")
            if len(rth) < 300:
                continue
            open_px = float(rth.iloc[0]["open"])
            # Candidate-hunter pass: keep this tight so it does not collide with
            # other research runs. Wider sweeps belong in a follow-up after an
            # IS survivor appears.
            for or_name, or_end, scan_start in [("or60", "10:30", "10:31")]:
                or_bars = rth.between_time("09:30", or_end)
                scan = rth[rth.index.time >= pd.Timestamp(scan_start).time()]
                if len(or_bars) < 20 or len(scan) < 30:
                    continue
                hi = float(or_bars["high"].max())
                lo = float(or_bars["low"].min())
                rng = hi - lo
                if rng <= 0:
                    continue
                rng_pct = rng / open_px
                mid = (hi + lo) / 2.0
                for cap in (0.008, 0.010):
                    if rng_pct > cap:
                        continue
                    for direction in ("LONG", "SHORT"):
                        level = hi if direction == "LONG" else lo
                        cross = scan[scan["high"] >= level] if direction == "LONG" else scan[scan["low"] <= level]
                        if cross.empty:
                            continue
                        sig_ts = cross.index[0]
                        later = scan[scan.index > sig_ts]
                        if later.empty:
                            continue
                        entry_ts = later.index[0]
                        entry = float(later.iloc[0]["open"])
                        for stop_name, stop in [("midstop", mid)]:
                            if direction == "LONG" and stop >= entry:
                                continue
                            if direction == "SHORT" and stop <= entry:
                                continue
                            for target_mult in (1.00, 1.50):
                                target = entry + rng * target_mult if direction == "LONG" else entry - rng * target_mult
                                for time_exit in ("15:55",):
                                    variant = f"calm_orbo_{or_name}_{direction.lower()}_cap{cap:g}_{stop_name}_t{target_mult:g}_x{time_exit.replace(':', '')}"
                                    if selected is not None and variant not in selected:
                                        continue
                                    ex = feasible_exit(rth, direction, entry_ts, stop, target, time_exit)
                                    if not ex:
                                        continue
                                    exit_ts, exit_px, reason, outside = ex
                                    add_trade(rows, variant=variant, inst=inst, direction=direction, day=day,
                                              signal_ts=sig_ts, entry_ts=entry_ts, exit_ts=exit_ts,
                                              entry=entry, exit_px=float(exit_px), point_value=pv, cost=cost,
                                              outside_exit_bar=outside,
                                              meta={"or_range_pct": rng_pct, "exit_reason": reason,
                                                    "stop": stop, "target": target})
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, title: str, limit: int = 35) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("no trades")
        return
    print(f"fill_audit outside_exit_bar={int(df['outside_exit_bar'].sum())}")
    rows = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        rows.append({
            "variant": variant,
            **st,
            "pos_years": int((by_year > 0).sum()),
            "pos_inst": int((by_inst > 0).sum()),
            "top_year": int(by_year.idxmax()) if len(by_year) else 0,
            "top_pnl": float(by_year.max()) if len(by_year) else 0.0,
        })
    rank = pd.DataFrame(rows).sort_values(["pnl", "pf"], ascending=False).head(limit)
    for _, r in rank.iterrows():
        print(f"{r.variant:<72} n={int(r.n):5d} pnl={r.pnl:9.0f} pf={r.pf:5.2f} "
              f"exp={r.exp:7.2f} posY={int(r.pos_years)} posI={int(r.pos_inst)} "
              f"top={int(r.top_year)}:{r.top_pnl:8.0f}")


def select_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        top_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0
        if (st["n"] >= 300 and st["pnl"] >= 5000 and st["pf"] >= 1.12
                and (by_year > 0).sum() >= 5 and top_share <= 0.70 and (by_inst > 0).sum() >= 2
                and int(g["outside_exit_bar"].sum()) == 0):
            keep.append((variant, st["pnl"], st["pf"]))
    keep.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [x[0] for x in keep[:limit]]


def detail(df: pd.DataFrame, selected: list[str], title: str) -> None:
    print(f"\n=== {title} ===")
    for v in selected:
        g = df[df.variant == v]
        st = stats(g)
        print(f"\n{v} n={st['n']} pnl={st['pnl']:.0f} pf={st['pf']:.2f} exp={st['exp']:.2f} outside_exit_bar={int(g['outside_exit_bar'].sum())}")
        print("-- by instrument --")
        for inst, x in g.groupby("inst"):
            xs = stats(x)
            print(f"  {inst:<4} n={xs['n']:4d} pnl={xs['pnl']:8.0f} pf={xs['pf']:5.2f}")
        print("-- by direction --")
        for direction, x in g.groupby("direction"):
            xs = stats(x)
            print(f"  {direction:<5} n={xs['n']:4d} pnl={xs['pnl']:8.0f} pf={xs['pf']:5.2f}")
        print("-- by year --")
        for year, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(year)} n={xs['n']:4d} pnl={xs['pnl']:8.0f}")


def run_window(args, data_dir: str, start: str, end: str, hmm_fit_end: str,
               selected: set[str] | None = None, calm_days_csv: str | None = None) -> pd.DataFrame:
    if calm_days_csv and Path(calm_days_csv).exists():
        days = pd.read_csv(calm_days_csv, usecols=["day"])["day"].dropna().unique()
        labels = {pd.Timestamp(x).normalize(): "Calm" for x in days}
    else:
        labels = label_regimes(benchmark_daily(args.regime_csv), args.hmm_train_end, 3, hmm_fit_end)
    days = load_days(data_dir, start, end, set(args.instruments))
    return run_variants(days, labels, args.slippage_ticks, selected)


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
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM", "M2K"])
    ap.add_argument("--select", nargs="+", default=None)
    ap.add_argument("--out-prefix", default="scratch/calm_or_breakout_probe")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--calm-days-2025", default="scratch/calm_drift_basket_big_2025.csv")
    ap.add_argument("--calm-days-2026", default="scratch/calm_drift_basket_big_2026.csv")
    args = ap.parse_args()

    is_df = run_window(args, args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is,
                       calm_days_csv=args.calm_days_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS Calm OR breakout")

    selected = args.select if args.select else select_candidates(is_df)
    print("\n=== IS SELECTION ===")
    if not selected:
        print("selected_before_oos=NONE")
        print("verdict=keep digging")
        return 0
    print("selected_before_oos=" + ",".join(selected))
    detail(is_df, selected, "2018-2024 selected")

    o25 = run_window(args, args.data_dir_2025, "2025-01-01", "2025-12-31", args.hmm_fit_end_oos, set(selected),
                     calm_days_csv=args.calm_days_2025)
    p25 = f"{args.out_prefix}_2025.csv"
    o25.to_csv(p25, index=False)
    print(f"wrote {p25} rows={len(o25)}")
    detail(o25, selected, "2025 OOS selected")

    c26 = run_window(args, args.data_dir_2026, "2026-01-01", "2026-08-19", args.hmm_fit_end_oos, set(selected),
                     calm_days_csv=args.calm_days_2026)
    p26 = f"{args.out_prefix}_2026.csv"
    c26.to_csv(p26, index=False)
    print(f"wrote {p26} rows={len(c26)}")
    detail(c26, selected, "2026 sanity selected")

    survivors = []
    for v in selected:
        s25 = stats(o25[o25.variant == v])
        s26 = stats(c26[c26.variant == v])
        if s25["pnl"] > 0 and s26["pnl"] >= 0 and s25["pf"] >= 1.05:
            survivors.append(v)
    print("\n=== VERDICT ===")
    if survivors:
        print("deploy_level_candidate=" + ",".join(survivors))
    else:
        print("deploy_level_candidate=NONE")
        print("verdict=keep digging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
