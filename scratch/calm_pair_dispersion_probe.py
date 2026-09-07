from __future__ import annotations

import argparse
import itertools
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
        df = df[(df.index >= s) & (df.index <= e)]
        rows = []
        for day_ts, day in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day_ts).tz_localize(None).normalize()
            rth = day.between_time("09:30", "15:59")
            if len(rth) < 300:
                continue
            p0930 = at_or_after(rth, "09:30")
            p1030 = at_or_after(rth, "10:30")
            p1031 = at_or_after(rth, "10:31")
            p1200 = at_or_after(rth, "12:00")
            p1555 = at_or_after(rth, "15:55")
            if not all([p0930, p1030, p1031, p1200, p1555]):
                continue
            rows.append({
                "day": key,
                "signal_ts": p1030[0],
                "entry_ts": p1031[0],
                "exit_noon_ts": p1200[0],
                "exit_1555_ts": p1555[0],
                "p0930": p0930[1],
                "p1030": p1030[1],
                "entry": p1031[1],
                "exit_noon": p1200[1],
                "exit_1555": p1555[1],
                "ret60": p1030[1] / p0930[1] - 1.0,
            })
        out[inst] = pd.DataFrame(rows).set_index("day").sort_index()
    return out


def leg_pnl(direction: str, entry: float, exit_px: float, inst: str) -> float:
    pts = exit_px - entry if direction == "LONG" else entry - exit_px
    return pts * BASKET[inst].point_value


def run_variants(frames: dict[str, pd.DataFrame], labels: dict, slippage_ticks: float,
                 selected: set[str] | None = None) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    rows = []
    for a, b in itertools.combinations(sorted(frames), 2):
        joined = frames[a].join(frames[b], lsuffix=f"_{a}", rsuffix=f"_{b}", how="inner")
        for day, r in joined.iterrows():
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            spread = float(r[f"ret60_{a}"] - r[f"ret60_{b}"])
            for threshold in (0.0015, 0.0025, 0.0035, 0.0050):
                if abs(spread) < threshold:
                    continue
                leader, laggard = (a, b) if spread > 0 else (b, a)
                for mode in ("mr", "momo"):
                    if mode == "mr":
                        dirs = {leader: "SHORT", laggard: "LONG"}
                    else:
                        dirs = {leader: "LONG", laggard: "SHORT"}
                    for exit_name in ("noon", "1555"):
                        variant = f"calm_pair_disp60_{a}_{b}_{mode}_thr{threshold:g}_x{exit_name}"
                        if selected is not None and variant not in selected:
                            continue
                        exit_col = "exit_noon" if exit_name == "noon" else "exit_1555"
                        exit_ts_col = "exit_noon_ts" if exit_name == "noon" else "exit_1555_ts"
                        pnl_gross = (
                            leg_pnl(dirs[a], float(r[f"entry_{a}"]), float(r[f"{exit_col}_{a}"]), a)
                            + leg_pnl(dirs[b], float(r[f"entry_{b}"]), float(r[f"{exit_col}_{b}"]), b)
                        )
                        rows.append({
                            "variant": variant,
                            "inst": f"{a}-{b}",
                            "direction": mode,
                            "day": day.date().isoformat(),
                            "year": int(day.year),
                            "signal_time": r[f"signal_ts_{a}"],
                            "entry_time": r[f"entry_ts_{a}"],
                            "exit_time": r[f"{exit_ts_col}_{a}"],
                            "pnl": pnl_gross - costs[a] - costs[b],
                            "outside_exit_bar": 0,
                            "pair_a": a,
                            "pair_b": b,
                            "leader": leader,
                            "laggard": laggard,
                            "spread60": spread,
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
        by_pair = g.groupby("inst")["pnl"].sum()
        rows.append({"variant": v, **st, "pos_years": int((by_year > 0).sum()),
                     "pos_pairs": int((by_pair > 0).sum()), "top_year": int(by_year.idxmax()),
                     "top_pnl": float(by_year.max())})
    rank = pd.DataFrame(rows).sort_values(["pnl", "pf"], ascending=False).head(limit)
    for _, r in rank.iterrows():
        print(f"{r.variant:<58} n={int(r.n):5d} pnl={r.pnl:9.0f} pf={r.pf:5.2f} "
              f"exp={r.exp:7.2f} posY={int(r.pos_years)} posPair={int(r.pos_pairs)} "
              f"top={int(r.top_year)}:{r.top_pnl:8.0f}")


def select_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for v, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_pair = g.groupby("inst")["pnl"].sum()
        top_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0
        if st["n"] >= 250 and st["pnl"] >= 5000 and st["pf"] >= 1.12 and (by_year > 0).sum() >= 5 and top_share <= 0.70 and (by_pair > 0).sum() >= 2:
            keep.append((v, st["pnl"], st["pf"]))
    keep.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [x[0] for x in keep[:limit]]


def detail(df: pd.DataFrame, selected: list[str], title: str) -> None:
    print(f"\n=== {title} ===")
    for v in selected:
        g = df[df.variant == v]
        st = stats(g)
        print(f"\n{v} n={st['n']} pnl={st['pnl']:.0f} pf={st['pf']:.2f} exp={st['exp']:.2f} outside_exit_bar={int(g['outside_exit_bar'].sum())}")
        print("-- by pair --")
        for pair, x in g.groupby("inst"):
            xs = stats(x)
            print(f"  {pair:<8} n={xs['n']:4d} pnl={xs['pnl']:8.0f} pf={xs['pf']:5.2f}")
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
    ap.add_argument("--out-prefix", default="scratch/calm_pair_dispersion_probe")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--calm-days-2025", default="scratch/calm_drift_basket_big_2025.csv")
    ap.add_argument("--calm-days-2026", default="scratch/calm_drift_basket_big_2026.csv")
    args = ap.parse_args()

    is_df = run_window(args, args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is, args.calm_days_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS Calm pair dispersion")

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
