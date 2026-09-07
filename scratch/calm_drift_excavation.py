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


def first_at_or_after(g: pd.DataFrame, hhmm: str, col: str = "open") -> tuple[pd.Timestamp, float] | None:
    sub = g.between_time(hhmm, "23:59") if hhmm >= "16:00" else g[g.index.time >= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[0], float(sub.iloc[0][col])


def last_at_or_before(g: pd.DataFrame, hhmm: str, col: str = "close") -> tuple[pd.Timestamp, float] | None:
    sub = g[g.index.time <= pd.Timestamp(hhmm).time()]
    if sub.empty:
        return None
    return sub.index[-1], float(sub.iloc[-1][col])


def trading_day_index(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    local = idx.normalize()
    evening = np.array([t >= pd.Timestamp("18:00").time() for t in idx.time])
    out = np.where(evening, local + pd.Timedelta(days=1), local)
    return pd.DatetimeIndex(out).tz_localize(None).normalize()


def build_daily(data_dir: str, start: str, end: str, instruments: set[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for inst, contract in BASKET.items():
        if inst not in instruments:
            continue
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        s = pd.Timestamp(start).tz_localize(df.index.tz)
        e = pd.Timestamp(end).tz_localize(df.index.tz) + pd.Timedelta(days=1)
        df = df[(df.index >= s - pd.Timedelta(days=2)) & (df.index <= e)]
        work = df.copy()
        work["tday"] = trading_day_index(work.index)
        rows = []
        for day, g in work.groupby("tday"):
            if day < pd.Timestamp(start) or day > pd.Timestamp(end):
                continue
            rth = g.between_time("09:30", "15:59")
            asia = g[(g.index.time >= pd.Timestamp("18:00").time()) | (g.index.time < pd.Timestamp("02:00").time())]
            europe = g.between_time("02:00", "07:59")
            pre = g.between_time("08:00", "09:29")
            if len(rth) < 60:
                continue
            rth_open_ts, rth_open = rth.index[0], float(rth.iloc[0]["open"])
            rth_close_ts, rth_close = rth.index[-1], float(rth.iloc[-1]["close"])
            noon = first_at_or_after(rth, "12:00", "open")
            ten = first_at_or_after(rth, "10:00", "open")
            rec = {
                "day": day,
                "rth_open_ts": rth_open_ts,
                "rth_open": rth_open,
                "rth_close_ts": rth_close_ts,
                "rth_close": rth_close,
                "rth_high": float(rth["high"].max()),
                "rth_low": float(rth["low"].min()),
                "noon_ts": noon[0] if noon else pd.NaT,
                "noon_open": noon[1] if noon else np.nan,
                "ten_ts": ten[0] if ten else pd.NaT,
                "ten_open": ten[1] if ten else np.nan,
                "asia_ret": np.nan,
                "europe_ret": np.nan,
                "pre_ret": np.nan,
                "overnight_ret": np.nan,
            }
            for name, sub in (("asia", asia), ("europe", europe), ("pre", pre)):
                if len(sub) >= 2:
                    rec[f"{name}_ret"] = float(sub.iloc[-1]["close"] / sub.iloc[0]["open"] - 1.0)
            if len(asia) + len(europe) + len(pre) >= 30:
                overnight = pd.concat([asia, europe, pre]).sort_index()
                if len(overnight) >= 2:
                    rec["overnight_ret"] = float(overnight.iloc[-1]["close"] / overnight.iloc[0]["open"] - 1.0)
            rows.append(rec)
        d = pd.DataFrame(rows).set_index("day").sort_index()
        d["next_rth_open"] = d["rth_open"].shift(-1)
        d["next_rth_open_ts"] = d["rth_open_ts"].shift(-1)
        d["prev_rth_ret"] = (d["rth_close"] / d["rth_open"] - 1.0).shift(1)
        d["rth_ret"] = d["rth_close"] / d["rth_open"] - 1.0
        d["close_pos"] = (d["rth_close"] - d["rth_low"]) / (d["rth_high"] - d["rth_low"]).replace(0, np.nan)
        out[inst] = d
    return out


def spy_frame(regime_csv: str) -> pd.DataFrame:
    close = benchmark_daily(regime_csv).sort_index()
    ret = close.pct_change()
    out = pd.DataFrame({"spy_close": close})
    out["spy_sma50_d1"] = close.rolling(50).mean().shift(1)
    out["spy_close_d1"] = close.shift(1)
    out["spy_rv20_d1"] = (ret.rolling(20).std() * math.sqrt(252)).shift(1)
    out["spy_above_sma50_d1"] = out["spy_close_d1"] > out["spy_sma50_d1"]
    return out


def add(rows: list[dict], *, variant: str, inst: str, direction: str, day: pd.Timestamp,
        signal_ts, entry_ts, exit_ts, entry: float, exit_px: float, point_value: float,
        cost: float, meta: dict) -> None:
    if pd.isna(entry) or pd.isna(exit_px):
        return
    pts = exit_px - entry if direction == "LONG" else entry - exit_px
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
        "pnl": pts * point_value - cost,
        "outside_exit_bar": 0,
        **meta,
    })


def run_variants(daily: dict[str, pd.DataFrame], labels: dict, spy: pd.DataFrame,
                 slippage_ticks: float, selected: set[str] | None = None) -> pd.DataFrame:
    costs = {k: c.round_turn_cost() for k, c in costs_for_basket(slippage_ticks=slippage_ticks).items()}
    rows: list[dict] = []
    for inst, d in daily.items():
        pv = BASKET[inst].point_value
        for day, r in d.iterrows():
            day = pd.Timestamp(day).normalize()
            if labels.get(day) != "Calm":
                continue
            sp = spy.loc[day] if day in spy.index else None
            spy_above = bool(sp["spy_above_sma50_d1"]) if sp is not None and not pd.isna(sp["spy_above_sma50_d1"]) else False
            spy_rv = float(sp["spy_rv20_d1"]) if sp is not None and not pd.isna(sp["spy_rv20_d1"]) else np.nan

            variants = []
            # Close-to-next-open risk-on carry. Signal uses only D RTH information.
            if not pd.isna(r.get("next_rth_open")):
                variants += [
                    ("on_long_all", "LONG", r["rth_close_ts"], r["rth_close_ts"], r["next_rth_open_ts"],
                     r["rth_close"], r["next_rth_open"], True),
                    ("on_long_spy_above", "LONG", r["rth_close_ts"], r["rth_close_ts"], r["next_rth_open_ts"],
                     r["rth_close"], r["next_rth_open"], spy_above),
                    ("on_long_close_top40", "LONG", r["rth_close_ts"], r["rth_close_ts"], r["next_rth_open_ts"],
                     r["rth_close"], r["next_rth_open"], r["close_pos"] >= 0.60),
                    ("on_long_rth_up", "LONG", r["rth_close_ts"], r["rth_close_ts"], r["next_rth_open_ts"],
                     r["rth_close"], r["next_rth_open"], r["rth_ret"] > 0),
                    ("on_short_close_bottom40", "SHORT", r["rth_close_ts"], r["rth_close_ts"], r["next_rth_open_ts"],
                     r["rth_close"], r["next_rth_open"], r["close_pos"] <= 0.40),
                ]

            # Overnight -> RTH open-to-noon/10:00 continuation/reversal. Signal is known at RTH open.
            if not pd.isna(r["overnight_ret"]) and not pd.isna(r["noon_open"]):
                if r["overnight_ret"] > 0:
                    variants += [
                        ("on_pos_continue_to_noon", "LONG", r["rth_open_ts"], r["rth_open_ts"], r["noon_ts"],
                         r["rth_open"], r["noon_open"], True),
                        ("on_pos_fade_to_noon", "SHORT", r["rth_open_ts"], r["rth_open_ts"], r["noon_ts"],
                         r["rth_open"], r["noon_open"], True),
                    ]
                elif r["overnight_ret"] < 0:
                    variants += [
                        ("on_neg_continue_to_noon", "SHORT", r["rth_open_ts"], r["rth_open_ts"], r["noon_ts"],
                         r["rth_open"], r["noon_open"], True),
                        ("on_neg_fade_to_noon", "LONG", r["rth_open_ts"], r["rth_open_ts"], r["noon_ts"],
                         r["rth_open"], r["noon_open"], True),
                    ]
                    if -0.008 < r["overnight_ret"] <= -0.001:
                        variants.append(("on_neg_fade_to_noon_mod001_008", "LONG",
                                         r["rth_open_ts"], r["rth_open_ts"], r["noon_ts"],
                                         r["rth_open"], r["noon_open"], True))
                    if -0.008 < r["overnight_ret"] <= -0.002:
                        variants.append(("on_neg_fade_to_noon_mod002_008", "LONG",
                                         r["rth_open_ts"], r["rth_open_ts"], r["noon_ts"],
                                         r["rth_open"], r["noon_open"], True))
            if not pd.isna(r["overnight_ret"]) and not pd.isna(r["ten_open"]):
                if r["overnight_ret"] > 0:
                    variants.append(("on_pos_continue_to_1000", "LONG", r["rth_open_ts"], r["rth_open_ts"], r["ten_ts"],
                                     r["rth_open"], r["ten_open"], True))
                elif r["overnight_ret"] < 0:
                    variants.append(("on_neg_fade_to_1000", "LONG", r["rth_open_ts"], r["rth_open_ts"], r["ten_ts"],
                                     r["rth_open"], r["ten_open"], True))

            # Sub-session continuation inside Globex, using only known prior subwindow.
            if not pd.isna(r["asia_ret"]) and not pd.isna(r["europe_ret"]):
                direction = "LONG" if r["asia_ret"] > 0 else "SHORT"
                variants.append(("asia_to_europe_momo", direction, day + pd.Timedelta(hours=2),
                                 day + pd.Timedelta(hours=2), day + pd.Timedelta(hours=8),
                                 1.0, 1.0 + abs(r["europe_ret"]), False))
            if not pd.isna(r["europe_ret"]) and not pd.isna(r["pre_ret"]):
                direction = "LONG" if r["europe_ret"] > 0 else "SHORT"
                variants.append(("europe_to_premarket_momo", direction, day + pd.Timedelta(hours=8),
                                 day + pd.Timedelta(hours=8), r["rth_open_ts"],
                                 1.0, 1.0 + abs(r["pre_ret"]), False))

            for name, direction, sig_ts, ent_ts, ex_ts, entry, exit_px, price_based in variants:
                if selected is not None and name not in selected:
                    continue
                if not price_based:
                    # Synthetic return-only sub-session rows are diagnostic; skip PnL because
                    # there is no single executable price pair in this compact aggregate.
                    continue
                if name.endswith("spy_above") and not spy_above:
                    continue
                if name.endswith("rv16") and not (spy_rv <= 0.16):
                    continue
                ok = True
                if isinstance(direction, str) and direction in {"LONG", "SHORT"}:
                    ok = True
                if ok:
                    add(rows, variant=name, inst=inst, direction=direction, day=day,
                        signal_ts=sig_ts, entry_ts=ent_ts, exit_ts=ex_ts, entry=float(entry),
                        exit_px=float(exit_px), point_value=pv, cost=costs[inst],
                        meta={
                            "spy_above_sma50_d1": spy_above,
                            "spy_rv20_d1": spy_rv,
                            "rth_ret": r.get("rth_ret"),
                            "overnight_ret": r.get("overnight_ret"),
                            "close_pos": r.get("close_pos"),
                        })
    return pd.DataFrame(rows)


def robust_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        pos_years = int((by_year > 0).sum())
        top_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 else 1.0
        pos_inst = int((by_inst > 0).sum())
        if st["n"] >= 250 and st["pnl"] >= 5000 and st["pf"] >= 1.10 and pos_years >= 5 and top_share <= 0.70:
            # Allow one-instrument candidates only if the instrument is MNQ and the PnL hurdle is higher.
            if pos_inst >= 2 or (set(g["inst"]) == {"MNQ"} and st["pnl"] >= 7000):
                keep.append((variant, st["pnl"], st["pf"], st["exp"]))
    keep.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)
    return [x[0] for x in keep[:limit]]


def print_summary(df: pd.DataFrame, title: str) -> None:
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
            "top_year": int(by_year.idxmax()) if len(by_year) else 0,
            "top_year_pnl": float(by_year.max()) if len(by_year) else 0.0,
            "pos_inst": int((by_inst > 0).sum()),
        })
    rank = pd.DataFrame(rows).sort_values(["pnl", "pf"], ascending=False)
    for _, r in rank.iterrows():
        print(
            f"{r.variant:<30} n={int(r.n):5d} pnl={r.pnl:9.0f} pf={r.pf:5.2f} "
            f"exp={r.exp:7.2f} posY={int(r.pos_years)} posI={int(r.pos_inst)} "
            f"top={int(r.top_year)}:{r.top_year_pnl:8.0f}"
        )


def print_detail(df: pd.DataFrame, selected: list[str], title: str) -> None:
    print(f"\n=== {title} ===")
    for variant in selected:
        g = df[df.variant == variant]
        st = stats(g)
        print(f"\n{variant} n={st['n']} pnl={st['pnl']:.0f} pf={st['pf']:.2f} exp={st['exp']:.2f}")
        print("-- by instrument --")
        for inst, x in g.groupby("inst"):
            xs = stats(x)
            print(f"  {inst:<4} n={xs['n']:4d} pnl={xs['pnl']:8.0f} pf={xs['pf']:5.2f} exp={xs['exp']:7.2f}")
        print("-- by year --")
        for year, x in g.groupby("year"):
            xs = stats(x)
            print(f"  {int(year)} n={xs['n']:4d} pnl={xs['pnl']:8.0f} exp={xs['exp']:7.2f}")


def run_window(args, *, data_dir: str, start: str, end: str, hmm_fit_end: str,
               selected: set[str] | None = None) -> pd.DataFrame:
    labels = label_regimes(benchmark_daily(args.regime_csv), args.hmm_train_end, 3, hmm_fit_end)
    daily = build_daily(data_dir, start, end, set(args.instruments))
    spy = spy_frame(args.regime_csv)
    return run_variants(daily, labels, spy, args.slippage_ticks, selected)


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
    ap.add_argument("--instruments", nargs="+", default=["MNQ"])
    ap.add_argument("--select", nargs="+", default=None,
                    help="Manually selected IS variants to run through 2025/2026.")
    ap.add_argument("--out-prefix", default="scratch/calm_drift_excavation")
    args = ap.parse_args()

    is_df = run_window(args, data_dir=args.data_dir, start="2018-01-01", end="2024-12-31",
                       hmm_fit_end=args.hmm_fit_end_is)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS drift/continuation")

    selected = args.select if args.select else robust_candidates(is_df)
    print("\n=== IS SELECTION ===")
    if not selected:
        print("selected_before_oos=NONE")
        print("verdict=keep digging")
        return 0
    print("selected_before_oos=" + ",".join(selected))
    print_detail(is_df, selected, "2018-2024 selected")

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
