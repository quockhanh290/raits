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


def causal_labels(regime_csv: str, train_end: str, fit_end: str) -> dict[pd.Timestamp, str]:
    close = benchmark_daily(regime_csv).sort_index()
    lag0 = label_regimes(close, train_end, 3, fit_end)
    days = pd.DatetimeIndex(sorted(lag0.keys()))
    out = {}
    for d in close.index:
        d = pd.Timestamp(d).normalize()
        pos = days.searchsorted(d, side="left") - 1
        if pos >= 0:
            out[d] = lag0[pd.Timestamp(days[pos]).normalize()]
    return out


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
    ret = close.pct_change()
    out = pd.DataFrame({"day": close.index})
    out["spy_above50_d1"] = (close.shift(1) > close.rolling(50).mean().shift(1)).to_numpy()
    out["spy_rv20_d1"] = (ret.rolling(20).std() * math.sqrt(252)).shift(1).to_numpy()
    return out


def build_daily(data_dir: str, inst: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
    s = (start - pd.Timedelta(days=70)).tz_localize(df.index.tz)
    e = (end + pd.Timedelta(days=1)).tz_localize(df.index.tz)
    df = df[(df.index >= s) & (df.index <= e)].copy()
    work = df.copy()
    work["day"] = trading_day_index(work.index)
    rows = []
    for day, g in work.groupby("day", sort=True):
        day = pd.Timestamp(day).normalize()
        if day < start - pd.Timedelta(days=70) or day > end:
            continue
        rth = g.between_time("09:30", "15:59")
        pre = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("09:30").time())]
        if len(rth) < 160 or len(pre) < 30:
            continue
        bars = {
            "0930": at_or_after(rth, "09:30"),
            "1000": at_or_after(rth, "10:00"),
            "1555": at_or_after(rth, "15:55"),
        }
        if not all(bars.values()):
            continue
        rows.append(
            {
                "day": day,
                "inst": inst,
                "rth_open": float(rth["open"].iloc[0]),
                "rth_high": float(rth["high"].max()),
                "rth_low": float(rth["low"].min()),
                "rth_close": float(rth["close"].iloc[-1]),
                "overnight_ret": float(pre.iloc[-1]["close"] / pre.iloc[0]["open"] - 1.0),
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
    prev = out[["rth_open", "rth_high", "rth_low", "rth_close", "close_loc", "rth_ret"]].shift(1)
    for col in prev.columns:
        out[f"prev_{col}"] = prev[col]
    prev_range = (out["prev_rth_high"] - out["prev_rth_low"]).replace(0, np.nan)
    out["open_loc"] = (out["p0930"] - out["prev_rth_low"]) / prev_range
    out["close_ret"] = out["rth_close"].pct_change()
    out["prev_2down"] = (out["close_ret"].shift(1) < 0) & (out["close_ret"].shift(2) < 0)
    denom3 = (out["rth_high"].shift(1).rolling(3).max() - out["rth_low"].shift(1).rolling(3).min()).replace(0, np.nan)
    out["prev_close_loc_3d"] = (out["rth_close"].shift(1) - out["rth_low"].shift(1).rolling(3).min()) / denom3
    return out[out["day"] >= start].copy()


def build_rows(
    data_dir: str,
    start: str,
    end: str,
    labels: dict[pd.Timestamp, str],
    spy: pd.DataFrame,
    instruments: set[str],
    slippage_ticks: float,
    selected: set[str] | None = None,
) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    filters = {
        "openloc_lower": lambda r: r["open_loc"] <= 1 / 3,
        "openloc_lower_spyabove": lambda r: r["open_loc"] <= 1 / 3 and bool(r["spy_above50_d1"]),
        "pcloc_bottom": lambda r: r["prev_close_loc"] <= 1 / 3,
        "pcloc_bottom_down": lambda r: r["prev_close_loc"] <= 1 / 3 and r["prev_rth_ret"] <= 0,
        "negon_m001_m010": lambda r: -0.010 < r["overnight_ret"] <= -0.001,
        "negon_m002_m010": lambda r: -0.010 < r["overnight_ret"] <= -0.002,
        "negon_raw": lambda r: r["overnight_ret"] <= 0,
        "mdpb_2down_low3": lambda r: bool(r["prev_2down"]) and r["prev_close_loc_3d"] <= 0.25,
    }
    rows = []
    for inst in sorted(instruments):
        daily = build_daily(data_dir, inst, pd.Timestamp(start), pd.Timestamp(end)).merge(spy, on="day", how="left")
        pv = BASKET[inst].point_value
        cost = costs[inst]
        for _, r in daily.iterrows():
            day = pd.Timestamp(r["day"]).normalize()
            if labels.get(day) != "Calm":
                continue
            if pd.isna(r["open_loc"]) or pd.isna(r["prev_close_loc"]) or pd.isna(r["spy_above50_d1"]):
                continue
            for filt, fn in filters.items():
                if not fn(r):
                    continue
                for direction in ("LONG", "SHORT"):
                    variant = f"lag1calm_{filt}_{direction.lower()}_e1000_x1555"
                    if selected is not None and variant not in selected:
                        continue
                    entry = float(r["p1000"])
                    exit_px = float(r["p1555"])
                    pnl_pts = exit_px - entry if direction == "LONG" else entry - exit_px
                    signal_ts = r["t0930"]
                    rows.append(
                        {
                            "variant": variant,
                            "inst": inst,
                            "direction": direction,
                            "day": day.date().isoformat(),
                            "year": int(day.year),
                            "signal_time": signal_ts,
                            "entry_time": r["t1000"],
                            "exit_time": r["t1555"],
                            "entry": entry,
                            "exit": exit_px,
                            "pnl": pnl_pts * pv - cost,
                            "outside_exit_bar": 0 if price_inside(exit_px, r["low1555"], r["high1555"]) else 1,
                            "outside_entry_bar": 0 if price_inside(entry, r["low1000"], r["high1000"]) else 1,
                            "signal_after_entry": 1 if signal_ts > r["t1000"] else 0,
                            "overnight_ret": float(r["overnight_ret"]),
                            "open_loc": float(r["open_loc"]),
                            "prev_close_loc": float(r["prev_close_loc"]),
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


def print_summary(title: str, summary: pd.DataFrame, selected: list[str] | None = None) -> None:
    print(f"\n=== {title} ===")
    if summary.empty:
        print("no rows")
        return
    tbl = summary if selected is None else summary[summary["variant"].isin(selected)]
    for _, r in tbl.head(30).iterrows():
        print(
            f"{r['variant']:<52} n={int(r['n']):>5} days={int(r['days']):>4} "
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
        print("-- by year --")
        for year, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(year)} n={xs['n']:4d} net=${xs['net']:8.0f}")
        print("-- by instrument --")
        for inst, x in g.groupby("inst"):
            xs = stats(x)
            print(f"  {inst:<4} n={xs['n']:4d} net=${xs['net']:8.0f} pf={xs['pf']:5.2f}")


def run_window(args, window: str, data_dir: str, start: str, end: str, fit_end: str,
               selected: set[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    labels = causal_labels(args.regime_csv, args.hmm_train_end, fit_end)
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
    ap.add_argument("--instruments", nargs="+", default=["MES", "MNQ", "MYM"])
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--select-limit", type=int, default=2)
    ap.add_argument("--select", nargs="+", default=None)
    ap.add_argument("--out-prefix", default="scratch/calm_causal_lag1_excavation")
    args = ap.parse_args()

    is_df, is_summary = run_window(args, "is", args.data_dir, "2018-01-01", "2024-12-31", args.hmm_fit_end_is)
    is_df.to_csv(f"{args.out_prefix}_is.csv", index=False)
    is_summary.to_csv(f"{args.out_prefix}_is_summary.csv", index=False)
    print(f"wrote {args.out_prefix}_is.csv rows={len(is_df)}")
    print_summary("2018-2024 IS causal lag-1 Calm excavation", is_summary)

    selected = args.select if args.select else select_candidates(is_summary, args.select_limit)
    print("\n=== IS SELECTION ===")
    if not selected:
        print("selected_before_oos=NONE")
        print("verdict=reject / causal Calm still has no deploy candidate")
        return 0
    print("selected_before_oos=" + ",".join(selected))
    detail("2018-2024 selected", is_df, selected)

    o25, s25 = run_window(args, "2025", args.data_dir_2025, "2025-01-01", "2025-12-31", args.hmm_fit_end_oos, set(selected))
    o25.to_csv(f"{args.out_prefix}_2025.csv", index=False)
    s25.to_csv(f"{args.out_prefix}_2025_summary.csv", index=False)
    detail("2025 OOS selected", o25, selected)

    c26, s26 = run_window(args, "2026", args.data_dir_2026, "2026-01-01", "2026-08-19", args.hmm_fit_end_oos, set(selected))
    c26.to_csv(f"{args.out_prefix}_2026.csv", index=False)
    s26.to_csv(f"{args.out_prefix}_2026_summary.csv", index=False)
    detail("2026 sanity selected", c26, selected)
    pooled = pd.concat([o25, c26], ignore_index=True)
    print_summary("2025+2026 pooled selected", summarize(pooled, "oos_pooled"), selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
