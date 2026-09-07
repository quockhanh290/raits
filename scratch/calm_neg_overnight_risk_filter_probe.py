from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes, load_parquet
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


def price_inside_bar(price: float, bar: pd.Series) -> bool:
    px = float(price)
    lo = float(bar["low"])
    hi = float(bar["high"])
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def calm_labels(calm_days_csv: str | None, regime_csv: str, train_end: str, fit_end: str) -> dict:
    if calm_days_csv and Path(calm_days_csv).exists():
        days = pd.read_csv(calm_days_csv, usecols=["day"])["day"].dropna().unique()
        return {pd.Timestamp(x).normalize(): "Calm" for x in days}
    return label_regimes(benchmark_daily(regime_csv), train_end, 3, fit_end)


def spy_features(regime_csv: str) -> pd.DataFrame:
    close = benchmark_daily(regime_csv).sort_index()
    ret = close.pct_change()
    out = pd.DataFrame(index=close.index)
    out["rv20_d1"] = (ret.rolling(20).std() * math.sqrt(252)).shift(1)
    out["close_d1"] = close.shift(1)
    out["sma50_d1"] = close.rolling(50).mean().shift(1)
    out["above_sma50_d1"] = out["close_d1"] > out["sma50_d1"]
    return out


def feasible_stop_or_time(
    rth: pd.DataFrame,
    entry_ts: pd.Timestamp,
    entry_px: float,
    stop_px: float | None,
    time_exit: str,
) -> tuple[pd.Timestamp, float, str, int] | None:
    later = rth[rth.index > entry_ts]
    if later.empty:
        return None
    scheduled = at_or_after(later, time_exit, "open")
    if not scheduled:
        return None
    time_ts, time_px = scheduled
    path = later[later.index <= time_ts]
    if stop_px is not None:
        for ts, bar in path.iterrows():
            low = float(bar["low"])
            high = float(bar["high"])
            op = float(bar["open"])
            if low <= stop_px:
                fill = stop_px if low <= stop_px <= high else op
                outside = 0 if price_inside_bar(fill, bar) else 1
                return ts, fill, "stop", outside
    time_bar = path.loc[time_ts]
    outside = 0 if price_inside_bar(time_px, time_bar) else 1
    return time_ts, time_px, "time", outside


def add_row(rows: list[dict], *, variant: str, inst: str, day: pd.Timestamp,
            entry_ts: pd.Timestamp, exit_ts: pd.Timestamp, entry_px: float, exit_px: float,
            point_value: float, cost: float, reason: str, outside: int,
            outside_entry: int, signal_after_entry: int, meta: dict) -> None:
    rows.append({
        "variant": variant,
        "inst": inst,
        "direction": "LONG",
        "day": day.date().isoformat(),
        "year": int(day.year),
        "signal_time": entry_ts,
        "entry_time": entry_ts,
        "exit_time": exit_ts,
        "entry": entry_px,
        "exit": exit_px,
        "pnl": (exit_px - entry_px) * point_value - cost,
        "outside_exit_bar": outside,
        "outside_entry_bar": outside_entry,
        "signal_after_entry": signal_after_entry,
        "exit_reason": reason,
        **meta,
    })


def run_window(args, data_dir: str, start: str, end: str, fit_end: str, calm_days_csv: str,
               selected: set[str] | None = None) -> pd.DataFrame:
    labels = calm_labels(calm_days_csv, args.regime_csv, args.hmm_train_end, fit_end)
    spy = spy_features(args.regime_csv)
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=args.slippage_ticks).items()}
    rows = []
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    bands = [("mod001_010", -0.010, -0.001)]
    if not args.focused:
        bands += [("raw", -9.0, 0.0), ("mod002_010", -0.010, -0.002)]
    filters = [("all", lambda x: True)]
    filters += [
        ("rv20le20", lambda x: pd.notna(x["rv20_d1"]) and float(x["rv20_d1"]) <= 0.20),
        ("spyabove50", lambda x: bool(x["above_sma50_d1"]) if pd.notna(x["above_sma50_d1"]) else False),
        ("spybelow50", lambda x: not bool(x["above_sma50_d1"]) if pd.notna(x["above_sma50_d1"]) else False),
    ]
    if not args.focused:
        filters += [("rv20le16", lambda x: pd.notna(x["rv20_d1"]) and float(x["rv20_d1"]) <= 0.16)]
    for inst, contract in BASKET.items():
        if inst not in set(args.instruments):
            continue
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        atr = daily_atr_series(df)
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
            entry = at_or_after(rth, "09:30", "open")
            noon = at_or_after(rth, "12:00", "open")
            eod = at_or_after(rth, "15:55", "open")
            if not entry or not noon or not eod:
                continue
            sp = spy.loc[day] if day in spy.index else pd.Series({"rv20_d1": np.nan, "above_sma50_d1": np.nan})
            on = float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0)
            entry_ts, entry_px = entry
            entry_outside = 0 if price_inside_bar(entry_px, rth.loc[entry_ts]) else 1
            signal_after_entry = 1 if pre.index.max() >= entry_ts else 0
            av = atr.asof(day)
            if av is None or pd.isna(av):
                av = float(atr.median())
            for band_name, lo, hi in bands:
                if not (lo < on <= hi):
                    continue
                for filter_name, filter_fn in filters:
                    if not filter_fn(sp):
                        continue
                    meta = {
                        "overnight_ret": on,
                        "spy_rv20_d1": float(sp["rv20_d1"]) if pd.notna(sp["rv20_d1"]) else np.nan,
                        "spy_above_sma50_d1": bool(sp["above_sma50_d1"]) if pd.notna(sp["above_sma50_d1"]) else False,
                        "atr": float(av),
                        "event_filter": "missing",
                    }

                    # Baseline and disaster-stop variants: one full micro exits at 15:55 unless stopped.
                    stop_specs = [("nostop", None), ("stop075atr", 0.75), ("stop10atr", 1.0)]
                    if not args.focused:
                        stop_specs.insert(1, ("stop05atr", 0.5))
                    for stop_name, stop_mult in stop_specs:
                        stop_px = None if stop_mult is None else entry_px - float(stop_mult) * float(av)
                        ex = feasible_stop_or_time(rth, entry_ts, entry_px, stop_px, "15:55")
                        if not ex:
                            continue
                        exit_ts, exit_px, reason, outside = ex
                        variant = f"negON_{band_name}_{filter_name}_{stop_name}_x1555"
                        if selected is not None and variant not in selected:
                            continue
                        add_row(rows, variant=variant, inst=inst, day=day, entry_ts=entry_ts,
                                exit_ts=exit_ts, entry_px=float(entry_px), exit_px=float(exit_px),
                                point_value=pv, cost=cost, reason=reason, outside=outside,
                                outside_entry=entry_outside, signal_after_entry=signal_after_entry,
                                meta={**meta, "stop_mult": np.nan if stop_mult is None else stop_mult,
                                      "split": "none"})

                    # Normalized 50/50 split: one-micro equivalent PnL with half at noon and half at 15:55.
                    # This is a deploy-sizing concept; one literal micro cannot be halved.
                    noon_ts, noon_px = noon
                    eod_ts, eod_px = eod
                    variant = f"negON_{band_name}_{filter_name}_split50_noon1555"
                    if selected is None or variant in selected:
                        split_exit_px = 0.5 * float(noon_px) + 0.5 * float(eod_px)
                        split_outside = 0 if price_inside_bar(noon_px, rth.loc[noon_ts]) and price_inside_bar(eod_px, rth.loc[eod_ts]) else 1
                        add_row(rows, variant=variant, inst=inst, day=day, entry_ts=entry_ts,
                                exit_ts=eod_ts, entry_px=float(entry_px), exit_px=split_exit_px,
                                point_value=pv, cost=cost, reason="split_time", outside=split_outside,
                                outside_entry=entry_outside, signal_after_entry=signal_after_entry,
                                meta={**meta, "stop_mult": np.nan, "split": "50_noon_50_1555"})
    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, title: str, limit: int = 50) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("no trades")
        return
    print(
        f"fill_audit outside_exit_bar={int(df['outside_exit_bar'].sum())} "
        f"outside_entry_bar={int(df['outside_entry_bar'].sum())} "
        f"signal_after_entry={int(df['signal_after_entry'].sum())}"
    )
    rows = []
    for v, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        rows.append({
            "variant": v,
            **st,
            "pos_years": int((by_year > 0).sum()),
            "pos_inst": int((by_inst > 0).sum()),
            "top_year": int(by_year.idxmax()),
            "top_pnl": float(by_year.max()),
            "top_share": float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0,
        })
    rank = pd.DataFrame(rows).sort_values(["pnl", "pf"], ascending=False).head(limit)
    for _, r in rank.iterrows():
        print(f"{r.variant:<48} n={int(r.n):5d} pnl={r.pnl:9.0f} pf={r.pf:5.2f} "
              f"exp={r.exp:7.2f} posY={int(r.pos_years)} posI={int(r.pos_inst)} "
              f"top={int(r.top_year)}:{r.top_pnl:8.0f} share={r.top_share:4.2f}")


def select_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for v, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        top_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0
        audit_ok = (
            int(g["outside_exit_bar"].sum()) == 0
            and int(g["outside_entry_bar"].sum()) == 0
            and int(g["signal_after_entry"].sum()) == 0
        )
        if (st["n"] >= 300 and st["pnl"] >= 5000 and st["pf"] >= 1.12
                and (by_year > 0).sum() >= 5 and top_share <= 0.70
                and (by_inst > 0).sum() >= 2 and audit_ok):
            keep.append((v, st["pnl"], st["pf"]))
    keep.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return [x[0] for x in keep[:limit]]


def detail(df: pd.DataFrame, selected: list[str], title: str) -> None:
    print(f"\n=== {title} ===")
    for v in selected:
        g = df[df.variant == v]
        st = stats(g)
        print(
            f"\n{v} n={st['n']} pnl={st['pnl']:.0f} pf={st['pf']:.2f} exp={st['exp']:.2f} "
            f"outside_exit_bar={int(g['outside_exit_bar'].sum())} "
            f"outside_entry_bar={int(g['outside_entry_bar'].sum())} "
            f"signal_after_entry={int(g['signal_after_entry'].sum())}"
        )
        print("-- by instrument --")
        for inst, x in g.groupby("inst"):
            xs = stats(x)
            print(f"  {inst:<4} n={xs['n']:4d} pnl={xs['pnl']:8.0f} pf={xs['pf']:5.2f}")
        print("-- by year --")
        for year, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(year)} n={xs['n']:4d} pnl={xs['pnl']:8.0f}")
        print("-- exit reason --")
        for reason, x in g.groupby("exit_reason"):
            xs = stats(x)
            print(f"  {reason:<10} n={xs['n']:4d} pnl={xs['pnl']:8.0f}")


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
    ap.add_argument("--focused", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--out-prefix", default="scratch/calm_neg_overnight_risk_filter_probe")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--calm-days-2025", default="scratch/calm_drift_basket_big_2025.csv")
    ap.add_argument("--calm-days-2026", default="scratch/calm_drift_basket_big_2026.csv")
    args = ap.parse_args()

    is_df = run_window(args, args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is, args.calm_days_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS negative overnight risk/filter probe")

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
