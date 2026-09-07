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


AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def calm_labels(calm_days_csv: str | None, regime_csv: str, train_end: str, fit_end: str) -> dict:
    if calm_days_csv and Path(calm_days_csv).exists():
        days = pd.read_csv(calm_days_csv, usecols=["day"])["day"].dropna().unique()
        return {pd.Timestamp(x).normalize(): "Calm" for x in days}
    return label_regimes(benchmark_daily(regime_csv), train_end, 3, fit_end)


def price_inside(price: float, low: float, high: float) -> bool:
    px = float(price)
    lo = float(low)
    hi = float(high)
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def at_or_after(g: pd.DataFrame, hhmm: str) -> tuple[pd.Timestamp, pd.Series] | None:
    sub = g[g.index.time >= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[0], sub.iloc[0]


def spy_context(path: str) -> pd.DataFrame:
    close = benchmark_daily(path).sort_index()
    idx = pd.DatetimeIndex(close.index)
    close.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    out = pd.DataFrame({"day": close.index})
    ret = close.pct_change()
    out["spy_above50_d1"] = (close.shift(1) > close.rolling(50).mean().shift(1)).to_numpy()
    out["spy_rv20_d1"] = (ret.rolling(20).std() * math.sqrt(252)).shift(1).to_numpy()
    return out


def build_daily(data_dir: str, inst: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
    s = (start - pd.Timedelta(days=40)).tz_localize(df.index.tz)
    e = (end + pd.Timedelta(days=1)).tz_localize(df.index.tz)
    df = df[(df.index >= s) & (df.index <= e)].copy()
    rth = df.between_time("09:30", "15:59").copy()
    rth["day"] = trading_day_index(rth.index)
    rows = []
    for day, g in rth.groupby("day", sort=True):
        day = pd.Timestamp(day).normalize()
        if day < start - pd.Timedelta(days=40) or day > end or len(g) < 160:
            continue
        bars = {
            "0930": at_or_after(g, "09:30"),
            "1000": at_or_after(g, "10:00"),
            "1555": at_or_after(g, "15:55"),
        }
        if not all(bars.values()):
            continue
        rows.append(
            {
                "day": day,
                "inst": inst,
                "rth_open": float(g["open"].iloc[0]),
                "rth_high": float(g["high"].max()),
                "rth_low": float(g["low"].min()),
                "rth_close": float(g["close"].iloc[-1]),
                "t0930": bars["0930"][0],
                "p0930": float(bars["0930"][1]["open"]),
                "low0930": float(bars["0930"][1]["low"]),
                "high0930": float(bars["0930"][1]["high"]),
                "t1000": bars["1000"][0],
                "p1000": float(bars["1000"][1]["open"]),
                "low1000": float(bars["1000"][1]["low"]),
                "high1000": float(bars["1000"][1]["high"]),
                "t1555": bars["1555"][0],
                "p1555": float(bars["1555"][1]["open"]),
                "low1555": float(bars["1555"][1]["low"]),
                "high1555": float(bars["1555"][1]["high"]),
            }
        )
    out = pd.DataFrame(rows).sort_values("day").reset_index(drop=True)
    denom = (out["rth_high"] - out["rth_low"]).replace(0, np.nan)
    out["close_loc"] = (out["rth_close"] - out["rth_low"]) / denom
    out["rth_ret"] = out["rth_close"] / out["rth_open"] - 1.0
    out["range_pct"] = (out["rth_high"] - out["rth_low"]) / out["rth_close"]
    out["range_med20"] = out["range_pct"].rolling(20, min_periods=10).median()
    prev_cols = ["close_loc", "rth_ret", "range_pct", "range_med20"]
    for col in prev_cols:
        out[f"prev_{col}"] = out[col].shift(1)
    return out[out["day"] >= start].copy()


def build_rows(
    data_dir: str,
    start: str,
    end: str,
    labels: dict,
    spy: pd.DataFrame,
    instruments: set[str],
    slippage_ticks: float,
    selected: set[str] | None = None,
) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    filters = {
        "prev_top_third": lambda r: r["prev_close_loc"] >= 2.0 / 3.0,
        "prev_bottom_third": lambda r: r["prev_close_loc"] <= 1.0 / 3.0,
        "prev_top_up": lambda r: (r["prev_close_loc"] >= 2.0 / 3.0) and (r["prev_rth_ret"] > 0),
        "prev_bottom_down": lambda r: (r["prev_close_loc"] <= 1.0 / 3.0) and (r["prev_rth_ret"] <= 0),
        "prev_top_compress": lambda r: (r["prev_close_loc"] >= 2.0 / 3.0) and (r["prev_range_pct"] <= r["prev_range_med20"]),
        "prev_bottom_compress": lambda r: (r["prev_close_loc"] <= 1.0 / 3.0) and (r["prev_range_pct"] <= r["prev_range_med20"]),
        "prev_top_spy_above": lambda r: (r["prev_close_loc"] >= 2.0 / 3.0) and bool(r["spy_above50_d1"]),
        "prev_bottom_spy_below": lambda r: (r["prev_close_loc"] <= 1.0 / 3.0) and (not bool(r["spy_above50_d1"])),
    }
    rows = []
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    for inst in sorted(instruments):
        daily = build_daily(data_dir, inst, start_ts, end_ts).merge(spy, on="day", how="left")
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for _, r in daily.iterrows():
            day = pd.Timestamp(r["day"]).normalize()
            if labels.get(day) != "Calm":
                continue
            if pd.isna(r["prev_close_loc"]) or pd.isna(r["prev_rth_ret"]) or pd.isna(r["spy_above50_d1"]):
                continue
            for filt, fn in filters.items():
                if not fn(r):
                    continue
                for direction in ("LONG", "SHORT"):
                    for entry_key in ("0930", "1000"):
                        variant = f"pcloc_{filt}_{direction.lower()}_e{entry_key}_x1555"
                        if selected is not None and variant not in selected:
                            continue
                        entry = float(r[f"p{entry_key}"])
                        exit_px = float(r["p1555"])
                        pnl_pts = exit_px - entry if direction == "LONG" else entry - exit_px
                        signal_ts = pd.Timestamp(r["day"]).tz_localize(r[f"t{entry_key}"].tz) - pd.Timedelta(minutes=1)
                        entry_ts = r[f"t{entry_key}"]
                        rows.append(
                            {
                                "variant": variant,
                                "inst": inst,
                                "direction": direction,
                                "day": day.date().isoformat(),
                                "year": int(day.year),
                                "signal_time": signal_ts,
                                "entry_time": entry_ts,
                                "exit_time": r["t1555"],
                                "entry": entry,
                                "exit": exit_px,
                                "pnl": pnl_pts * pv - cost,
                                "outside_exit_bar": 0 if price_inside(exit_px, r["low1555"], r["high1555"]) else 1,
                                "outside_entry_bar": 0
                                if price_inside(entry, r[f"low{entry_key}"], r[f"high{entry_key}"])
                                else 1,
                                "signal_after_entry": 1 if signal_ts > entry_ts else 0,
                                "prev_close_loc": float(r["prev_close_loc"]),
                                "prev_rth_ret": float(r["prev_rth_ret"]),
                                "prev_range_pct": float(r["prev_range_pct"]),
                                "spy_above50_d1": bool(r["spy_above50_d1"]),
                            }
                        )
    return pd.DataFrame(rows)


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


def summarize(df: pd.DataFrame, window: str) -> pd.DataFrame:
    rows = []
    if df.empty:
        return pd.DataFrame()
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
                "top_year_share": float(by_year.max() / st["net"]) if st["net"] > 0 else 1.0,
                "mes_net": float(by_inst.get("MES", 0.0)),
                "mnq_net": float(by_inst.get("MNQ", 0.0)),
                "mym_net": float(by_inst.get("MYM", 0.0)),
                "outside_exit_bar": int(g["outside_exit_bar"].sum()),
                "outside_entry_bar": int(g["outside_entry_bar"].sum()),
                "signal_after_entry": int(g["signal_after_entry"].sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(["net", "pf"], ascending=False)


def select_candidates(summary: pd.DataFrame, limit: int) -> list[str]:
    keep = summary[
        (summary["n"] >= 250)
        & (summary["net"] >= 5_000)
        & (summary["pf"] >= 1.12)
        & (summary["pos_years"] >= 5)
        & (summary["pos_inst"] >= 2)
        & (summary["top_year_share"] <= 0.70)
        & (summary["outside_exit_bar"] == 0)
        & (summary["outside_entry_bar"] == 0)
        & (summary["signal_after_entry"] == 0)
    ]
    return keep.sort_values(["net", "pf"], ascending=False)["variant"].head(limit).tolist()


def print_summary(title: str, summary: pd.DataFrame, selected: list[str] | None = None, limit: int = 30) -> None:
    print(f"\n=== {title} ===")
    if summary.empty:
        print("no rows")
        return
    tbl = summary if selected is None else summary[summary["variant"].isin(selected)]
    for _, r in tbl.head(limit).iterrows():
        print(
            f"{r['variant']:<56} n={int(r['n']):>5} days={int(r['days']):>4} "
            f"net=${r['net']:>9,.0f} pf={r['pf']:>5.2f} avg=${r['avg']:>7.2f} "
            f"dd=${r['maxdd']:>7,.0f} posY={int(r['pos_years'])}/{int(r['years'])} "
            f"posI={int(r['pos_inst'])} audit={int(r['outside_exit_bar'])}/"
            f"{int(r['outside_entry_bar'])}/{int(r['signal_after_entry'])}"
        )


def detail(title: str, df: pd.DataFrame, selected: list[str]) -> None:
    print(f"\n=== {title} ===")
    for v in selected:
        g = df[df["variant"] == v]
        st = stats(g)
        print(f"\n{v} n={st['n']} days={st['days']} net=${st['net']:.0f} pf={st['pf']:.2f} avg=${st['avg']:.2f}")
        print("-- by instrument --")
        for inst, x in g.groupby("inst"):
            xs = stats(x)
            print(f"  {inst:<4} n={xs['n']:4d} net=${xs['net']:8.0f} pf={xs['pf']:5.2f}")
        print("-- by year --")
        for year, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(year)} n={xs['n']:4d} net=${xs['net']:8.0f}")


def run_window(args: argparse.Namespace, window: str, data_dir: str, start: str, end: str, fit_end: str,
               calm_days_csv: str, selected: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = calm_labels(calm_days_csv, args.regime_csv, args.hmm_train_end, fit_end)
    spy = spy_context(args.regime_csv)
    trades = build_rows(data_dir, start, end, labels, spy, set(args.instruments), args.slippage_ticks, selected)
    return trades, summarize(trades, window)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures/frozen_sim")
    ap.add_argument("--data-dir-2025", default="data/cache/futures/frozen_2025_sim")
    ap.add_argument("--data-dir-2026", default="data/cache/futures")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end-is", default="2022-12-31")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    ap.add_argument("--calm-days-is", default="scratch/calm_drift_basket_big_is.csv")
    ap.add_argument("--calm-days-2025", default="scratch/calm_drift_basket_big_2025.csv")
    ap.add_argument("--calm-days-2026", default="scratch/calm_drift_basket_big_2026.csv")
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--select-limit", type=int, default=2)
    ap.add_argument("--select", nargs="+", default=None)
    ap.add_argument("--out-prefix", default="scratch/calm_prior_close_location_probe")
    args = ap.parse_args()

    is_df, is_summary = run_window(
        args, "is", args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is, args.calm_days_is
    )
    is_df.to_csv(f"{args.out_prefix}_is.csv", index=False)
    is_summary.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print(f"wrote {args.out_prefix}_is.csv rows={len(is_df)}")
    print_summary("2018-2024 IS prior-close-location", is_summary)

    selected = args.select if args.select else select_candidates(is_summary, args.select_limit)
    print("\n=== IS SELECTION ===")
    if not selected:
        print("selected_before_oos=NONE")
        print("verdict=reject / keep digging")
        return 0
    print("selected_before_oos=" + ",".join(selected))
    detail("2018-2024 selected", is_df, selected)

    o25, s25 = run_window(
        args, "2025", args.data_dir_2025, "2025-01-01", "2025-12-31", args.hmm_fit_end_oos,
        args.calm_days_2025, set(selected)
    )
    o25.to_csv(f"{args.out_prefix}_2025.csv", index=False)
    s25.to_csv(f"{args.out_prefix}_2025_summary.csv", index=False)
    detail("2025 OOS selected", o25, selected)

    c26, s26 = run_window(
        args, "2026", args.data_dir_2026, "2026-01-01", "2026-08-19", args.hmm_fit_end_oos,
        args.calm_days_2026, set(selected)
    )
    c26.to_csv(f"{args.out_prefix}_2026.csv", index=False)
    s26.to_csv(f"{args.out_prefix}_2026_summary.csv", index=False)
    detail("2026 sanity selected", c26, selected)

    pooled = pd.concat([o25, c26], ignore_index=True)
    pooled_summary = summarize(pooled, "oos_pooled")
    pooled_summary.to_csv(f"{args.out_prefix}_oos_pooled_summary.csv", index=False)
    print_summary("2025+2026 pooled selected", pooled_summary, selected)
    print("\n=== VERDICT ===")
    survivors = []
    for v in selected:
        a = stats(o25[o25["variant"] == v])
        b = stats(c26[c26["variant"] == v])
        p = stats(pooled[pooled["variant"] == v])
        if a["net"] > 0 and b["net"] > 0 and p["pf"] >= 1.10:
            survivors.append(v)
    print("paper_candidate=" + (",".join(survivors) if survivors else "NONE"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
