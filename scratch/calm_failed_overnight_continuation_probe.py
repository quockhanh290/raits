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
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    return {"n": int(len(df)), "pnl": float(pnl.sum()), "pf": gw / gl if gl else math.inf, "exp": float(pnl.mean())}


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


def calm_labels(calm_days_csv: str | None, regime_csv: str, train_end: str, fit_end: str) -> dict:
    if calm_days_csv and Path(calm_days_csv).exists():
        days = pd.read_csv(calm_days_csv, usecols=["day"])["day"].dropna().unique()
        return {pd.Timestamp(x).normalize(): "Calm" for x in days}
    return label_regimes(benchmark_daily(regime_csv), train_end, 3, fit_end)


def build_rows(data_dir: str, start: str, end: str, instruments: set[str]) -> dict[str, pd.DataFrame]:
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
        records = []
        for day, g in work.groupby("tday"):
            key = pd.Timestamp(day).normalize()
            if key < pd.Timestamp(start) or key > pd.Timestamp(end):
                continue
            rth = g.between_time("09:30", "15:59")
            pre = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("09:30").time())]
            if len(rth) < 160 or len(pre) < 30:
                continue
            p0930 = at_or_after(rth, "09:30", "open")
            p1100 = at_or_after(rth, "11:00", "open")
            p1200 = at_or_after(rth, "12:00", "open")
            p1400 = at_or_after(rth, "14:00", "open")
            if not all([p0930, p1100, p1200, p1400]):
                continue
            open_ts, open_px = p0930
            records.append({
                "day": key,
                "open_ts": open_ts,
                "open_px": open_px,
                "t1100": p1100[0],
                "p1100": p1100[1],
                "t1200": p1200[0],
                "p1200": p1200[1],
                "t1400": p1400[0],
                "p1400": p1400[1],
                "overnight_ret": float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0),
                "rth": rth,
            })
        out[inst] = pd.DataFrame(records).set_index("day").sort_index()
    return out


def run_variants(frames: dict[str, pd.DataFrame], labels: dict, slippage_ticks: float,
                 selected: set[str] | None = None) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    rows = []
    for inst, d in frames.items():
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for day, r in d.iterrows():
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            on = float(r["overnight_ret"])
            bands = [("mod001_008", -0.008, -0.001), ("mod002_008", -0.008, -0.002)]
            for band_name, lo, hi in bands:
                if not (lo < on <= hi):
                    continue
                rth = r["rth"]
                open_px = float(r["open_px"])
                for window_name, end_hhmm in [("fail10", "09:40"), ("fail20", "09:50"), ("fail30", "10:00")]:
                    scan = rth[(rth.index > r["open_ts"]) & (rth.index.time <= pd.Timestamp(end_hhmm).time())]
                    if scan.empty:
                        continue
                    for push in (0.0005, 0.0010, 0.0015):
                        pushed = False
                        signal_ts = None
                        for ts, bar in scan.iterrows():
                            if float(bar["low"]) <= open_px * (1.0 - push):
                                pushed = True
                            if pushed and float(bar["close"]) >= open_px:
                                signal_ts = ts
                                break
                        if signal_ts is None:
                            continue
                        later = rth[rth.index > signal_ts]
                        if later.empty:
                            continue
                        entry_ts = later.index[0]
                        entry = float(later.iloc[0]["open"])
                        for exit_name, exit_ts_col, exit_px_col in [
                            ("1100", "t1100", "p1100"),
                            ("1200", "t1200", "p1200"),
                            ("1400", "t1400", "p1400"),
                        ]:
                            if pd.Timestamp(r[exit_ts_col]) <= entry_ts:
                                continue
                            variant = f"failed_on_cont_{band_name}_{window_name}_push{push:g}_x{exit_name}"
                            if selected is not None and variant not in selected:
                                continue
                            exit_px = float(r[exit_px_col])
                            rows.append({
                                "variant": variant,
                                "inst": inst,
                                "direction": "LONG",
                                "day": day.date().isoformat(),
                                "year": int(day.year),
                                "signal_time": signal_ts,
                                "entry_time": entry_ts,
                                "exit_time": r[exit_ts_col],
                                "entry": entry,
                                "exit": exit_px,
                                "pnl": (exit_px - entry) * pv - cost,
                                "outside_exit_bar": 0,
                                "overnight_ret": on,
                                "push": push,
                            })
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, title: str, limit: int = 40) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("no trades")
        return
    print(f"fill_audit outside_exit_bar={int(df['outside_exit_bar'].sum())}")
    rows = []
    for v, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        rows.append({"variant": v, **st, "pos_years": int((by_year > 0).sum()),
                     "pos_inst": int((by_inst > 0).sum()), "top_year": int(by_year.idxmax()),
                     "top_pnl": float(by_year.max())})
    rank = pd.DataFrame(rows).sort_values(["pnl", "pf"], ascending=False).head(limit)
    for _, r in rank.iterrows():
        print(f"{r.variant:<55} n={int(r.n):5d} pnl={r.pnl:9.0f} pf={r.pf:5.2f} "
              f"exp={r.exp:7.2f} posY={int(r.pos_years)} posI={int(r.pos_inst)} "
              f"top={int(r.top_year)}:{r.top_pnl:8.0f}")


def select_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for v, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        top_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0
        if st["n"] >= 250 and st["pnl"] >= 5000 and st["pf"] >= 1.12 and (by_year > 0).sum() >= 5 and top_share <= 0.70 and (by_inst > 0).sum() >= 2:
            keep.append((v, st["pnl"], st["pf"]))
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
        print("-- by year --")
        for year, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(year)} n={xs['n']:4d} pnl={xs['pnl']:8.0f}")


def run_window(args, data_dir: str, start: str, end: str, fit_end: str, calm_days_csv: str,
               selected: set[str] | None = None) -> pd.DataFrame:
    labels = calm_labels(calm_days_csv, args.regime_csv, args.hmm_train_end, fit_end)
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=args.slippage_ticks).items()}
    rows = []
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    for inst, contract in BASKET.items():
        if inst not in set(args.instruments):
            continue
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        ss = s.tz_localize(df.index.tz)
        ee = e.tz_localize(df.index.tz) + pd.Timedelta(days=1)
        df = df[(df.index >= ss - pd.Timedelta(days=1)) & (df.index <= ee)]
        work = df.copy()
        work["tday"] = trading_day_index(work.index)
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for day, g in work.groupby("tday"):
            day = pd.Timestamp(day).normalize()
            if day < s or day > e or labels.get(day) != "Calm":
                continue
            rth = g.between_time("09:30", "15:59")
            pre = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("09:30").time())]
            if len(rth) < 160 or len(pre) < 30:
                continue
            p0930 = at_or_after(rth, "09:30", "open")
            exits = {
                "1100": at_or_after(rth, "11:00", "open"),
                "1200": at_or_after(rth, "12:00", "open"),
                "1400": at_or_after(rth, "14:00", "open"),
            }
            if not p0930 or any(v is None for v in exits.values()):
                continue
            open_ts, open_px = p0930
            on = float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0)
            for band_name, lo, hi in [("mod001_008", -0.008, -0.001), ("mod002_008", -0.008, -0.002)]:
                if not (lo < on <= hi):
                    continue
                for window_name, end_hhmm in [("fail10", "09:40"), ("fail20", "09:50"), ("fail30", "10:00")]:
                    scan = rth[(rth.index > open_ts) & (rth.index.time <= pd.Timestamp(end_hhmm).time())]
                    if scan.empty:
                        continue
                    lows = scan["low"].to_numpy(dtype=float)
                    closes = scan["close"].to_numpy(dtype=float)
                    idx = scan.index
                    for push in (0.0005, 0.0010, 0.0015):
                        threshold = open_px * (1.0 - push)
                        pushed = np.maximum.accumulate(lows <= threshold)
                        reclaim = pushed & (closes >= open_px)
                        hit = np.flatnonzero(reclaim)
                        if len(hit) == 0:
                            continue
                        signal_ts = idx[int(hit[0])]
                        later = rth[rth.index > signal_ts]
                        if later.empty:
                            continue
                        entry_ts = later.index[0]
                        entry = float(later.iloc[0]["open"])
                        for exit_name, ex in exits.items():
                            exit_ts, exit_px = ex
                            if pd.Timestamp(exit_ts) <= entry_ts:
                                continue
                            variant = f"failed_on_cont_{band_name}_{window_name}_push{push:g}_x{exit_name}"
                            if selected is not None and variant not in selected:
                                continue
                            rows.append({
                                "variant": variant,
                                "inst": inst,
                                "direction": "LONG",
                                "day": day.date().isoformat(),
                                "year": int(day.year),
                                "signal_time": signal_ts,
                                "entry_time": entry_ts,
                                "exit_time": exit_ts,
                                "entry": entry,
                                "exit": float(exit_px),
                                "pnl": (float(exit_px) - entry) * pv - cost,
                                "outside_exit_bar": 0,
                                "overnight_ret": on,
                                "push": push,
                            })
    return pd.DataFrame(rows)


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
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--select", nargs="+", default=None)
    ap.add_argument("--out-prefix", default="scratch/calm_failed_overnight_continuation_probe")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--calm-days-2025", default="scratch/calm_drift_basket_big_2025.csv")
    ap.add_argument("--calm-days-2026", default="scratch/calm_drift_basket_big_2026.csv")
    args = ap.parse_args()

    is_df = run_window(args, args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is, args.calm_days_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS failed overnight continuation")

    selected = args.select if args.select else select_candidates(is_df)
    print("\n=== IS SELECTION ===")
    if not selected:
        print("selected_before_oos=NONE")
        print("verdict=keep digging")
        return 0
    print("selected_before_oos=" + ",".join(selected))
    detail(is_df, selected, "2018-2024 selected")

    o25 = run_window(args, args.data_dir_2025, "2025-01-01", "2025-12-31", args.hmm_fit_end_oos, args.calm_days_2025, set(selected))
    p25 = f"{args.out_prefix}_2025.csv"
    o25.to_csv(p25, index=False)
    print(f"wrote {p25} rows={len(o25)}")
    detail(o25, selected, "2025 OOS selected")

    c26 = run_window(args, args.data_dir_2026, "2026-01-01", "2026-08-19", args.hmm_fit_end_oos, args.calm_days_2026, set(selected))
    p26 = f"{args.out_prefix}_2026.csv"
    c26.to_csv(p26, index=False)
    print(f"wrote {p26} rows={len(c26)}")
    detail(c26, selected, "2026 sanity selected")

    print("\n=== VERDICT ===")
    survivors = []
    for v in selected:
        s25 = stats(o25[o25.variant == v])
        s26 = stats(c26[c26.variant == v])
        if s25["pnl"] > 0 and s26["pnl"] >= 0 and s25["pf"] >= 1.05:
            survivors.append(v)
    if survivors:
        print("deploy_level_candidate=" + ",".join(survivors))
    else:
        print("deploy_level_candidate=NONE")
        print("verdict=keep digging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
