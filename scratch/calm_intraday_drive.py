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


def at_or_after(g: pd.DataFrame, hhmm: str, col: str = "open") -> tuple[pd.Timestamp, float] | None:
    sub = g[g.index.time >= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[0], float(sub.iloc[0][col])


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "pnl": 0.0, "pf": 0.0, "exp": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    return {
        "n": int(len(df)),
        "pnl": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "exp": float(pnl.mean()),
    }


def add(rows: list[dict], *, variant: str, inst: str, direction: str, day: pd.Timestamp,
        signal_time: pd.Timestamp, entry_time: pd.Timestamp, exit_time: pd.Timestamp,
        entry: float, exit_px: float, point_value: float, cost: float, meta: dict) -> None:
    pts = exit_px - entry if direction == "LONG" else entry - exit_px
    rows.append({
        "variant": variant,
        "inst": inst,
        "direction": direction,
        "day": day.date().isoformat(),
        "year": int(day.year),
        "signal_time": signal_time,
        "entry_time": entry_time,
        "exit_time": exit_time,
        "entry": entry,
        "exit": exit_px,
        "pnl": pts * point_value - cost,
        "outside_exit_bar": 0,
        **meta,
    })


def build_rows(data_dir: str, start: str, end: str, instruments: set[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for inst, contract in BASKET.items():
        if inst not in instruments:
            continue
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        s = pd.Timestamp(start).tz_localize(df.index.tz)
        e = pd.Timestamp(end).tz_localize(df.index.tz)
        df = df[(df.index >= s) & (df.index <= e)]
        records = []
        for day_ts, day in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day_ts).tz_localize(None).normalize()
            rth = day.between_time("09:30", "15:59")
            if len(rth) < 300:
                continue
            p0930 = at_or_after(rth, "09:30", "open")
            p1000_sig = at_or_after(rth, "10:00", "open")
            p1001_ent = at_or_after(rth, "10:01", "open")
            p1030_sig = at_or_after(rth, "10:30", "open")
            p1031_ent = at_or_after(rth, "10:31", "open")
            p1100_sig = at_or_after(rth, "11:00", "open")
            p1101_ent = at_or_after(rth, "11:01", "open")
            p1200 = at_or_after(rth, "12:00", "open")
            p1400 = at_or_after(rth, "14:00", "open")
            p1555 = at_or_after(rth, "15:55", "open")
            if not all([p0930, p1000_sig, p1001_ent, p1030_sig, p1031_ent, p1100_sig, p1101_ent, p1200, p1400, p1555]):
                continue
            or30 = rth.between_time("09:30", "10:00")
            or60 = rth.between_time("09:30", "10:30")
            open_px = p0930[1]
            records.append({
                "day": key,
                "t0930": p0930[0], "p0930": open_px,
                "t1000": p1000_sig[0], "p1000": p1000_sig[1],
                "t1001": p1001_ent[0], "p1001": p1001_ent[1],
                "t1030": p1030_sig[0], "p1030": p1030_sig[1],
                "t1031": p1031_ent[0], "p1031": p1031_ent[1],
                "t1100": p1100_sig[0], "p1100": p1100_sig[1],
                "t1101": p1101_ent[0], "p1101": p1101_ent[1],
                "t1200": p1200[0], "p1200": p1200[1],
                "t1400": p1400[0], "p1400": p1400[1],
                "t1555": p1555[0], "p1555": p1555[1],
                "ret30": p1000_sig[1] / open_px - 1.0,
                "ret60": p1030_sig[1] / open_px - 1.0,
                "ret90": p1100_sig[1] / open_px - 1.0,
                "or30_pct": float((or30["high"].max() - or30["low"].min()) / open_px),
                "or60_pct": float((or60["high"].max() - or60["low"].min()) / open_px),
            })
        out[inst] = pd.DataFrame(records).set_index("day").sort_index()
    return out


def run_variants(frames: dict[str, pd.DataFrame], labels: dict, slippage_ticks: float,
                 selected: set[str] | None = None) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    rows: list[dict] = []
    for inst, d in frames.items():
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for day, r in d.iterrows():
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            specs = []
            for sig_name, ret_col, sig_t, ent_t, ent_p in [
                ("30m", "ret30", "t1000", "t1001", "p1001"),
                ("60m", "ret60", "t1030", "t1031", "p1031"),
                ("90m", "ret90", "t1100", "t1101", "p1101"),
            ]:
                ret = float(r[ret_col])
                for min_abs in (0.001, 0.002, 0.003):
                    if abs(ret) < min_abs:
                        continue
                    for exit_name, exit_t, exit_p in [("noon", "t1200", "p1200"), ("1400", "t1400", "p1400"), ("1555", "t1555", "p1555")]:
                        if pd.Timestamp(r[exit_t]) <= pd.Timestamp(r[ent_t]):
                            continue
                        momo_dir = "LONG" if ret > 0 else "SHORT"
                        fade_dir = "SHORT" if ret > 0 else "LONG"
                        specs.append((f"drive_{sig_name}_momo_{min_abs:g}_to_{exit_name}", momo_dir))
                        specs.append((f"drive_{sig_name}_fade_{min_abs:g}_to_{exit_name}", fade_dir))
                        # Calm opening-range cap: only trade if first hour did not turn into a stressy range.
                        if float(r["or60_pct"]) <= 0.008:
                            specs.append((f"drive_{sig_name}_momo_{min_abs:g}_to_{exit_name}_orcap", momo_dir))
                            specs.append((f"drive_{sig_name}_fade_{min_abs:g}_to_{exit_name}_orcap", fade_dir))
                        for variant, direction in specs[-4:]:
                            if selected is not None and variant not in selected:
                                continue
                            add(rows, variant=variant, inst=inst, direction=direction, day=day,
                                signal_time=r[sig_t], entry_time=r[ent_t], exit_time=r[exit_t],
                                entry=float(r[ent_p]), exit_px=float(r[exit_p]),
                                point_value=pv, cost=cost,
                                meta={"signal_ret": ret, "or60_pct": float(r["or60_pct"])})
                        specs = []
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, title: str, limit: int = 30) -> None:
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
        print(f"{r.variant:<44} n={int(r.n):5d} pnl={r.pnl:9.0f} pf={r.pf:5.2f} "
              f"exp={r.exp:7.2f} posY={int(r.pos_years)} posI={int(r.pos_inst)} "
              f"top={int(r.top_year)}:{r.top_pnl:8.0f}")


def candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        if st["n"] >= 250 and st["pnl"] >= 5000 and st["pf"] >= 1.12 and (by_year > 0).sum() >= 5 and (by_inst > 0).sum() >= 2:
            keep.append((variant, st["pnl"], st["pf"]))
    keep.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [x[0] for x in keep[:limit]]


def detail(df: pd.DataFrame, selected: list[str], title: str) -> None:
    print(f"\n=== {title} ===")
    for v in selected:
        g = df[df.variant == v]
        st = stats(g)
        print(f"\n{v} n={st['n']} pnl={st['pnl']:.0f} pf={st['pf']:.2f} exp={st['exp']:.2f}")
        print("-- by instrument --")
        for inst, x in g.groupby("inst"):
            xs = stats(x)
            print(f"  {inst:<4} n={xs['n']:4d} pnl={xs['pnl']:8.0f} pf={xs['pf']:5.2f}")
        print("-- by year --")
        for y, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(y)} n={xs['n']:4d} pnl={xs['pnl']:8.0f}")


def run_window(args, data_dir: str, start: str, end: str, hmm_fit_end: str, selected: set[str] | None = None) -> pd.DataFrame:
    labels = label_regimes(benchmark_daily(args.regime_csv), args.hmm_train_end, 3, hmm_fit_end)
    frames = build_rows(data_dir, start, end, set(args.instruments))
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
    ap.add_argument("--out-prefix", default="scratch/calm_intraday_drive")
    args = ap.parse_args()

    is_df = run_window(args, args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS intraday drive")

    selected = args.select if args.select else candidates(is_df)
    print("\n=== IS SELECTION ===")
    if not selected:
        print("selected_before_oos=NONE")
        print("verdict=keep digging")
        return 0
    print("selected_before_oos=" + ",".join(selected))
    detail(is_df, selected, "2018-2024 selected")

    o25 = run_window(args, args.data_dir_2025, "2025-01-01", "2025-12-31", args.hmm_fit_end_oos, set(selected))
    p25 = f"{args.out_prefix}_2025.csv"
    o25.to_csv(p25, index=False)
    print(f"wrote {p25} rows={len(o25)}")
    detail(o25, selected, "2025 OOS selected")

    c26 = run_window(args, args.data_dir_2026, "2026-01-01", "2026-08-19", args.hmm_fit_end_oos, set(selected))
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
