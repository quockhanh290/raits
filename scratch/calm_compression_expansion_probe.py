from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

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


def build_frames(data_dir: str, start: str, end: str, instruments: set[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for inst, contract in BASKET.items():
        if inst not in instruments:
            continue
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        s = pd.Timestamp(start).tz_localize(df.index.tz)
        e = pd.Timestamp(end).tz_localize(df.index.tz) + pd.Timedelta(days=1)
        df = df[(df.index >= s - pd.Timedelta(days=10)) & (df.index <= e)]
        records = []
        for day_ts, day in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day_ts).tz_localize(None).normalize()
            if key < pd.Timestamp(start) - pd.Timedelta(days=10) or key > pd.Timestamp(end):
                continue
            rth = day.between_time("09:30", "15:59")
            if len(rth) < 300:
                continue
            p0930 = at_or_after(rth, "09:30", "open")
            p1030 = at_or_after(rth, "10:30", "open")
            p1031 = at_or_after(rth, "10:31", "open")
            p1400 = at_or_after(rth, "14:00", "open")
            p1555 = at_or_after(rth, "15:55", "open")
            if not all([p0930, p1030, p1031, p1400, p1555]):
                continue
            first_hour = rth.between_time("09:30", "10:30")
            records.append({
                "day": key,
                "t1030": p1030[0],
                "t1031": p1031[0],
                "t1400": p1400[0],
                "t1555": p1555[0],
                "open": p0930[1],
                "p1030": p1030[1],
                "entry": p1031[1],
                "p1400": p1400[1],
                "p1555": p1555[1],
                "rth_high": float(rth["high"].max()),
                "rth_low": float(rth["low"].min()),
                "first_high": float(first_hour["high"].max()),
                "first_low": float(first_hour["low"].min()),
                "rth_range_pct": float((rth["high"].max() - rth["low"].min()) / p0930[1]),
                "drive60": p1030[1] / p0930[1] - 1.0,
            })
        d = pd.DataFrame(records).set_index("day").sort_index()
        d["prev_high"] = d["rth_high"].shift(1)
        d["prev_low"] = d["rth_low"].shift(1)
        d["prev_range_pct"] = d["rth_range_pct"].shift(1)
        out[inst] = d[d.index >= pd.Timestamp(start)]
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
            if labels.get(day) != "Calm" or pd.isna(r["prev_range_pct"]):
                continue
            for comp_cap in (0.006, 0.008, 0.010, 0.012):
                if float(r["prev_range_pct"]) > comp_cap:
                    continue
                long_break = float(r["first_high"]) > float(r["prev_high"])
                short_break = float(r["first_low"]) < float(r["prev_low"])
                for side, broke in [("long", long_break), ("short", short_break)]:
                    if not broke:
                        continue
                    for min_drive in (0.0, 0.001, 0.002):
                        if side == "long" and float(r["drive60"]) < min_drive:
                            continue
                        if side == "short" and float(r["drive60"]) > -min_drive:
                            continue
                        base_dir = "LONG" if side == "long" else "SHORT"
                        for mode in ("momo", "fade"):
                            direction = base_dir if mode == "momo" else ("SHORT" if base_dir == "LONG" else "LONG")
                            for exit_name, exit_col, exit_ts in [("1400", "p1400", "t1400"), ("1555", "p1555", "t1555")]:
                                variant = f"calm_compress_prev{comp_cap:g}_{side}_{mode}_drv{min_drive:g}_x{exit_name}"
                                if selected is not None and variant not in selected:
                                    continue
                                entry = float(r["entry"])
                                exit_px = float(r[exit_col])
                                pts = exit_px - entry if direction == "LONG" else entry - exit_px
                                rows.append({
                                    "variant": variant,
                                    "inst": inst,
                                    "direction": direction,
                                    "day": day.date().isoformat(),
                                    "year": int(day.year),
                                    "signal_time": r["t1030"],
                                    "entry_time": r["t1031"],
                                    "exit_time": r[exit_ts],
                                    "entry": entry,
                                    "exit": exit_px,
                                    "pnl": pts * pv - cost,
                                    "outside_exit_bar": 0,
                                    "prev_range_pct": float(r["prev_range_pct"]),
                                    "drive60": float(r["drive60"]),
                                })
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, title: str, limit: int = 45) -> None:
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
                     "top_pnl": float(by_year.max()), "top_share": float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0})
    rank = pd.DataFrame(rows).sort_values(["pnl", "pf"], ascending=False).head(limit)
    for _, r in rank.iterrows():
        print(f"{r.variant:<62} n={int(r.n):5d} pnl={r.pnl:9.0f} pf={r.pf:5.2f} "
              f"exp={r.exp:7.2f} posY={int(r.pos_years)} posI={int(r.pos_inst)} "
              f"top={int(r.top_year)}:{r.top_pnl:8.0f} share={r.top_share:4.2f}")


def select_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for v, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        top_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0
        if st["n"] >= 300 and st["pnl"] >= 5000 and st["pf"] >= 1.12 and (by_year > 0).sum() >= 5 and top_share <= 0.70 and (by_inst > 0).sum() >= 2:
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
    frames = build_frames(data_dir, start, end, set(args.instruments))
    return run_variants(frames, labels, args.slippage_ticks, selected)


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
    ap.add_argument("--out-prefix", default="scratch/calm_compression_expansion_probe")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--calm-days-2025", default="scratch/calm_drift_basket_big_2025.csv")
    ap.add_argument("--calm-days-2026", default="scratch/calm_drift_basket_big_2026.csv")
    args = ap.parse_args()

    is_df = run_window(args, args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is, args.calm_days_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS Calm compression expansion")

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
