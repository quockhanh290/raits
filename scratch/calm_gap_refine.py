from __future__ import annotations

import argparse
import math
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes, load_parquet
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from scratch.calm_strategy_excavation import Fill, exit_scan, prior_rth_context, rth, spy_features


def one_min_at(day: pd.DataFrame, t: dtime) -> pd.DataFrame:
    return day.between_time(t.strftime("%H:%M"), t.strftime("%H:%M"))


def next_open_after(day: pd.DataFrame, ts: pd.Timestamp, until: dtime) -> tuple[pd.Timestamp, float] | None:
    fwd = day[(day.index > ts) & (day.index.time <= until)]
    if fwd.empty:
        return None
    return fwd.index[0], float(fwd.iloc[0]["open"])


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "exp": 0.0}
    pnl = df["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    return {
        "n": int(len(df)),
        "pnl": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "wr": float((pnl > 0).mean() * 100.0),
        "exp": float(pnl.mean()),
    }


def add(rows: list[dict], *, variant: str, inst: str, day_key: pd.Timestamp, direction: str,
        signal_ts: pd.Timestamp, entry_ts: pd.Timestamp, entry: float, fill: Fill,
        stop: float, target: float, point_value: float, cost: float, day: pd.DataFrame,
        meta: dict) -> None:
    pts = fill.price - entry if direction == "LONG" else entry - fill.price
    exit_bar = day.loc[fill.time]
    rows.append({
        "variant": variant,
        "inst": inst,
        "direction": direction,
        "day": day_key.date().isoformat(),
        "year": int(day_key.year),
        "signal_time": signal_ts,
        "entry_time": entry_ts,
        "exit_time": fill.time,
        "entry": entry,
        "exit": fill.price,
        "stop": stop,
        "target": target,
        "reason": fill.reason,
        "pnl": pts * point_value - cost,
        "exit_bar_low": float(exit_bar["low"]),
        "exit_bar_high": float(exit_bar["high"]),
        **meta,
    })


def day_features(day: pd.DataFrame, prev_ctx: dict) -> dict | None:
    day_rth = rth(day)
    if len(day_rth) < 180 or not prev_ctx:
        return None
    open_px = float(day_rth.iloc[0]["open"])
    prev_close = float(prev_ctx["prev_close"])
    gap = open_px / prev_close - 1.0
    if abs(gap) < 1e-9:
        return None
    b0945 = one_min_at(day, dtime(9, 45))
    b1000 = one_min_at(day, dtime(10, 0))
    if b0945.empty or b1000.empty:
        return None
    or15 = day.between_time("09:30", "09:45")
    or30 = day.between_time("09:30", "10:00")
    if or15.empty or or30.empty:
        return None
    ret15 = float(b0945.iloc[0]["close"] / open_px - 1.0)
    ret30 = float(b1000.iloc[0]["close"] / open_px - 1.0)
    prev_ret = np.nan
    if "prev_open" in prev_ctx and prev_ctx["prev_open"]:
        prev_ret = prev_close / prev_ctx["prev_open"] - 1.0
    return {
        "open": open_px,
        "prev_close": prev_close,
        "gap": gap,
        "gap_abs": abs(gap),
        "gap_sign": 1 if gap > 0 else -1,
        "ret15": ret15,
        "ret30": ret30,
        "or15_high": float(or15["high"].max()),
        "or15_low": float(or15["low"].min()),
        "or15_pct": float((or15["high"].max() - or15["low"].min()) / open_px),
        "or30_high": float(or30["high"].max()),
        "or30_low": float(or30["low"].min()),
        "or30_pct": float((or30["high"].max() - or30["low"].min()) / open_px),
        "prev_ret": prev_ret,
    }


def prior_ctx_with_open(prev_day: pd.DataFrame | None) -> dict | None:
    ctx = prior_rth_context(prev_day)
    if ctx is None or prev_day is None:
        return ctx
    prev = rth(prev_day)
    if not prev.empty:
        ctx["prev_open"] = float(prev.iloc[0]["open"])
    return ctx


def gap_fill_variants(rows: list[dict], *, inst: str, day_key: pd.Timestamp, day: pd.DataFrame,
                      feat: dict, cost: float, point_value: float, spy_rv20: float | None,
                      same_sign_count: int, gap_bin: tuple[float, float], reclaim: float,
                      scan_end: dtime, exit_end: dtime, stop_mode: str, rv_cap: float | None,
                      opening_filter: str) -> None:
    lo, hi = gap_bin
    if not (lo <= feat["gap_abs"] <= hi):
        return
    if rv_cap is not None and (spy_rv20 is None or spy_rv20 > rv_cap):
        return
    if opening_filter == "counter15":
        if feat["gap"] < 0 and feat["ret15"] <= 0:
            return
        if feat["gap"] > 0 and feat["ret15"] >= 0:
            return
    elif opening_filter == "counter30":
        if feat["gap"] < 0 and feat["ret30"] <= 0:
            return
        if feat["gap"] > 0 and feat["ret30"] >= 0:
            return
    elif opening_filter == "calm_or30":
        if feat["or30_pct"] > 0.006:
            return
    elif opening_filter == "broad_gap":
        if same_sign_count < 3:
            return
    elif opening_filter != "none":
        raise ValueError(opening_filter)

    scan = day[(day.index.time >= dtime(9, 45)) & (day.index.time <= scan_end)]
    if scan.empty:
        return
    direction = "LONG" if feat["gap"] < 0 else "SHORT"
    target = feat["prev_close"]
    if feat["gap"] < 0:
        trigger = feat["open"] + reclaim * (feat["prev_close"] - feat["open"])
        crossed = scan[scan["close"] >= trigger]
        if crossed.empty:
            return
        sig_ts = crossed.index[0]
        nxt = next_open_after(day, sig_ts, exit_end)
        if not nxt:
            return
        entry_ts, entry = nxt
        if stop_mode == "open_extreme":
            stop = min(feat["open"], float(scan.loc[:sig_ts, "low"].min()))
        elif stop_mode == "or15":
            stop = feat["or15_low"]
        elif stop_mode == "half_gap":
            stop = feat["open"] - 0.50 * abs(feat["prev_close"] - feat["open"])
        else:
            raise ValueError(stop_mode)
        if stop >= entry:
            return
    else:
        trigger = feat["open"] - reclaim * (feat["open"] - feat["prev_close"])
        crossed = scan[scan["close"] <= trigger]
        if crossed.empty:
            return
        sig_ts = crossed.index[0]
        nxt = next_open_after(day, sig_ts, exit_end)
        if not nxt:
            return
        entry_ts, entry = nxt
        if stop_mode == "open_extreme":
            stop = max(feat["open"], float(scan.loc[:sig_ts, "high"].max()))
        elif stop_mode == "or15":
            stop = feat["or15_high"]
        elif stop_mode == "half_gap":
            stop = feat["open"] + 0.50 * abs(feat["open"] - feat["prev_close"])
        else:
            raise ValueError(stop_mode)
        if stop <= entry:
            return

    fill = exit_scan(day, entry_ts, direction, stop, target, exit_end)
    if not fill:
        return
    name = (
        f"gap2_{lo:g}-{hi:g}_r{reclaim:g}_scan{scan_end.strftime('%H%M')}_"
        f"exit{exit_end.strftime('%H%M')}_{stop_mode}_{opening_filter}"
    )
    if rv_cap is not None:
        name += f"_rv{rv_cap:g}"
    add(rows, variant=name, inst=inst, day_key=day_key, direction=direction,
        signal_ts=sig_ts, entry_ts=entry_ts, entry=entry, fill=fill, stop=stop,
        target=target, point_value=point_value, cost=cost, day=day,
        meta={
            "gap": feat["gap"],
            "gap_abs": feat["gap_abs"],
            "ret15": feat["ret15"],
            "ret30": feat["ret30"],
            "or30_pct": feat["or30_pct"],
            "spy_rv20": np.nan if spy_rv20 is None else spy_rv20,
            "same_sign_count": same_sign_count,
        })


def load_day_maps(data_dir: str, start: str, end: str,
                  instruments: set[str] | None = None) -> dict[str, dict[pd.Timestamp, pd.DataFrame]]:
    out = {}
    for inst, contract in BASKET.items():
        if instruments is not None and inst not in instruments:
            continue
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        s = pd.Timestamp(start).tz_localize(df.index.tz)
        e = pd.Timestamp(end).tz_localize(df.index.tz)
        df = df[(df.index >= s) & (df.index <= e)]
        out[inst] = {
            pd.Timestamp(day_ts).tz_localize(None).normalize(): day
            for day_ts, day in df.groupby(df.index.normalize())
        }
    return out


def run_window(args, *, data_dir: str, start: str, end: str, hmm_fit_end: str,
               selected: set[str] | None = None) -> pd.DataFrame:
    labels = label_regimes(benchmark_daily(args.regime_csv), args.hmm_train_end, 3, hmm_fit_end)
    spy = spy_features(args.regime_csv)
    instruments = set(args.instruments)
    day_maps = load_day_maps(data_dir, start, end, instruments)
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=args.slippage_ticks).items()}
    days = sorted({d for m in day_maps.values() for d in m})
    prev_by_inst: dict[str, pd.DataFrame | None] = {k: None for k in BASKET}
    rows: list[dict] = []

    gap_bins = [(0.0025, 0.010), (0.0025, 0.005), (0.005, 0.010)]
    reclaims = [0.25, 0.35, 0.50]
    scan_ends = [dtime(11, 30)]
    exit_ends = [dtime(14, 0)]
    stop_modes = ["open_extreme", "or15"]
    rv_caps = [None]
    opening_filters = ["none", "counter15", "calm_or30", "broad_gap"]

    for day_key in days:
        day_by_inst = {inst: m[day_key] for inst, m in day_maps.items() if day_key in m}
        if labels.get(day_key) != "Calm":
            for inst, day in day_by_inst.items():
                prev_by_inst[inst] = day
            continue
        feats = {}
        for inst, day in day_by_inst.items():
            ctx = prior_ctx_with_open(prev_by_inst.get(inst))
            feat = day_features(day, ctx)
            if feat:
                feats[inst] = feat
        if not feats:
            continue
        for inst, feat in feats.items():
            same_sign_count = sum(1 for f in feats.values() if f["gap_sign"] == feat["gap_sign"])
            rv = None
            if day_key in spy.index:
                rv = float(spy.loc[day_key, "spy_rv20_d1"])
                if math.isnan(rv):
                    rv = None
            for gap_bin in gap_bins:
                for reclaim in reclaims:
                    for scan_end in scan_ends:
                        for exit_end in exit_ends:
                            if exit_end <= scan_end:
                                continue
                            for stop_mode in stop_modes:
                                for rv_cap in rv_caps:
                                    for opening_filter in opening_filters:
                                        before = len(rows)
                                        gap_fill_variants(
                                            rows, inst=inst, day_key=day_key, day=day_by_inst[inst],
                                            feat=feat, cost=costs[inst], point_value=BASKET[inst].point_value,
                                            spy_rv20=rv, same_sign_count=same_sign_count, gap_bin=gap_bin,
                                            reclaim=reclaim, scan_end=scan_end, exit_end=exit_end,
                                            stop_mode=stop_mode, rv_cap=rv_cap,
                                            opening_filter=opening_filter,
                                        )
                                        if selected is not None and len(rows) > before:
                                            if rows[-1]["variant"] not in selected:
                                                rows.pop()
        for inst, day in day_by_inst.items():
            prev_by_inst[inst] = day

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["outside_exit_bar"] = (
        (out["exit"] < out["exit_bar_low"] - 1e-9) |
        (out["exit"] > out["exit_bar_high"] + 1e-9)
    ).astype(int)
    return out


def robust_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    rows = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        pos_years = int((by_year > 0).sum())
        neg_years = int((by_year < 0).sum())
        top_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0
        pos_insts = int((by_inst > 0).sum())
        pre21 = float(by_year[by_year.index <= 2020].sum()) if len(by_year) else 0.0
        if (
            st["n"] >= 80 and st["pnl"] > 0 and st["pf"] >= 1.12 and
            pos_years >= 4 and neg_years <= 3 and top_share <= 0.65 and
            pos_insts >= 2 and pre21 >= -250 and int(g["outside_exit_bar"].sum()) == 0
        ):
            rows.append((variant, st["pnl"], st["pf"], st["exp"], pos_years, pre21))
    rows.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)
    return [r[0] for r in rows[:limit]]


def print_top(df: pd.DataFrame, title: str, n: int = 30) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("no trades")
        return
    print(f"fill_audit outside_exit_bar={int(df['outside_exit_bar'].sum())}")
    rows = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        rows.append({
            "variant": variant,
            **st,
            "pos_years": int((by_year > 0).sum()),
            "pre21": float(by_year[by_year.index <= 2020].sum()) if len(by_year) else 0.0,
            "top_year": int(by_year.idxmax()) if len(by_year) else 0,
            "top_year_pnl": float(by_year.max()) if len(by_year) else 0.0,
        })
    rank = pd.DataFrame(rows).sort_values(["pnl", "pf"], ascending=False).head(n)
    for _, r in rank.iterrows():
        print(
            f"{r.variant:<86} n={int(r.n):4d} pnl={r.pnl:9.0f} "
            f"pf={r.pf:5.2f} exp={r.exp:7.2f} posY={int(r.pos_years)} "
            f"pre21={r.pre21:8.0f} top={int(r.top_year)}:{r.top_year_pnl:7.0f}"
        )


def print_detail(df: pd.DataFrame, selected: list[str], title: str) -> None:
    print(f"\n=== {title} ===")
    for variant in selected:
        g = df[df["variant"] == variant]
        st = stats(g)
        print(f"\n{variant} n={st['n']} pnl={st['pnl']:.0f} pf={st['pf']:.2f} exp={st['exp']:.2f}")
        print("-- by instrument/direction --")
        for keys, x in g.groupby(["inst", "direction"]):
            xs = stats(x)
            print(f"  {keys[0]:<4} {keys[1]:<5} n={xs['n']:3d} pnl={xs['pnl']:8.0f} exp={xs['exp']:7.2f}")
        print("-- by year --")
        for y, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(y)} n={xs['n']:3d} pnl={xs['pnl']:8.0f} exp={xs['exp']:7.2f}")


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
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ"])
    ap.add_argument("--select", nargs="+", default=None,
                    help="Manually selected IS variants to run through 2025/2026.")
    ap.add_argument("--out-prefix", default="scratch/calm_gap_refine")
    args = ap.parse_args()

    is_df = run_window(args, data_dir=args.data_dir, start="2018-01-01", end="2024-12-31",
                       hmm_fit_end=args.hmm_fit_end_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_top(is_df, "2018-2024 top IS variants")

    selected = args.select if args.select else robust_candidates(is_df)
    print("\n=== IS SELECTION ===")
    if not selected:
        print("selected_before_oos=NONE")
        print("verdict=keep digging")
        return 0
    print("selected_before_oos=" + ",".join(selected))
    print_detail(is_df, selected, "2018-2024 selected detail")

    oos25 = run_window(args, data_dir=args.data_dir_2025, start="2025-01-01", end="2025-12-31",
                       hmm_fit_end=args.hmm_fit_end_oos, selected=set(selected))
    p25 = f"{args.out_prefix}_2025.csv"
    oos25.to_csv(p25, index=False)
    print(f"wrote {p25} rows={len(oos25)}")
    print_detail(oos25, selected, "2025 OOS selected")

    chk26 = run_window(args, data_dir=args.data_dir_2026, start="2026-01-01", end="2026-08-19",
                       hmm_fit_end=args.hmm_fit_end_oos, selected=set(selected))
    p26 = f"{args.out_prefix}_2026.csv"
    chk26.to_csv(p26, index=False)
    print(f"wrote {p26} rows={len(chk26)}")
    print_detail(chk26, selected, "2026 sanity selected")

    survivors = []
    for variant in selected:
        s25 = stats(oos25[oos25.variant == variant])
        s26 = stats(chk26[chk26.variant == variant])
        if s25["pnl"] > 0 and s26["pnl"] >= 0 and s25["pf"] >= 1.05:
            survivors.append(variant)
    print("\n=== VERDICT ===")
    if survivors:
        print("deploy_level_candidate=" + ",".join(survivors))
    else:
        print("deploy_level_candidate=NONE")
        print("verdict=keep digging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
