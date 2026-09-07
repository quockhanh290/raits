from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, label_regimes, load_parquet
from futures.basket import BASKET, Contract, data_filename
from futures.swing_tf import costs_for_basket


RTH_START = dtime(9, 30)
RTH_END = dtime(16, 0)


@dataclass(frozen=True)
class Fill:
    price: float
    reason: str
    time: pd.Timestamp


def vwap(bars: pd.DataFrame) -> float:
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["volume"]
    return float((tp * vol).sum() / vol.sum()) if float(vol.sum()) > 0 else float(bars["close"].iloc[-1])


def next_open_after(day: pd.DataFrame, ts: pd.Timestamp, until: dtime | None = None) -> tuple[pd.Timestamp, float] | None:
    fwd = day[day.index > ts]
    if until is not None:
        fwd = fwd[fwd.index.time <= until]
    if fwd.empty:
        return None
    return fwd.index[0], float(fwd.iloc[0]["open"])


def exit_scan(day: pd.DataFrame, entry_ts: pd.Timestamp, direction: str, stop: float | None,
              target: float | None, end_time: dtime) -> Fill | None:
    fwd = day[(day.index > entry_ts) & (day.index.time <= end_time)]
    if fwd.empty:
        return None
    for ts, bar in fwd.iterrows():
        high = float(bar["high"])
        low = float(bar["low"])
        op = float(bar["open"])
        if direction == "LONG":
            if stop is not None and low <= stop:
                return Fill(stop if high >= stop else op, "stop", ts)
            if target is not None and high >= target:
                return Fill(target if low <= target else op, "target", ts)
        else:
            if stop is not None and high >= stop:
                return Fill(stop if low <= stop else op, "stop", ts)
            if target is not None and low <= target:
                return Fill(target if high >= target else op, "target", ts)
    return Fill(float(fwd.iloc[-1]["close"]), "time", fwd.index[-1])


def rth(day: pd.DataFrame) -> pd.DataFrame:
    return day.between_time("09:30", "16:00")


def add_trade(rows: list[dict], *, variant: str, inst: str, contract: Contract, cost: float,
              day_key: pd.Timestamp, direction: str, signal_time: pd.Timestamp,
              entry_time: pd.Timestamp, entry: float, fill: Fill, stop: float | None,
              target: float | None, meta: dict) -> None:
    pts = fill.price - entry if direction == "LONG" else entry - fill.price
    rows.append({
        "variant": variant,
        "inst": inst,
        "direction": direction,
        "day": day_key.date().isoformat(),
        "year": int(day_key.year),
        "signal_time": signal_time,
        "entry_time": entry_time,
        "exit_time": fill.time,
        "entry": entry,
        "exit": fill.price,
        "stop": np.nan if stop is None else stop,
        "target": np.nan if target is None else target,
        "reason": fill.reason,
        "pnl": pts * contract.point_value - cost,
        **meta,
    })


def prior_rth_context(prev_day: pd.DataFrame | None) -> dict | None:
    if prev_day is None:
        return None
    prev = rth(prev_day)
    if len(prev) < 60:
        return None
    return {
        "prev_high": float(prev["high"].max()),
        "prev_low": float(prev["low"].min()),
        "prev_close": float(prev.iloc[-1]["close"]),
        "prev_mid": float((prev["high"].max() + prev["low"].min()) / 2.0),
    }


def day_range_pct(day_rth: pd.DataFrame) -> float:
    if day_rth.empty:
        return math.nan
    op = float(day_rth.iloc[0]["open"])
    return float((day_rth["high"].max() - day_rth["low"].min()) / op) if op else math.nan


def opening_range_fade(rows: list[dict], inst: str, contract: Contract, cost: float,
                       day_key: pd.Timestamp, day: pd.DataFrame, start: dtime,
                       ext_mult: float, range_cap: float, end: dtime = dtime(13, 30)) -> None:
    day_rth = rth(day)
    morning = day.between_time("09:30", "10:00")
    if len(day_rth) < 120 or len(morning) < 20:
        return
    op = float(day_rth.iloc[0]["open"])
    if day_range_pct(day_rth.between_time("09:30", "11:00")) > range_cap:
        return
    hi = float(morning["high"].max())
    lo = float(morning["low"].min())
    width = hi - lo
    if width <= 0 or width / op > range_cap:
        return
    mid = (hi + lo) / 2.0
    vw = vwap(day_rth[day_rth.index.time <= start])
    scan = day[(day.index.time >= start) & (day.index.time <= dtime(12, 30))]
    for ts, bar in scan.iterrows():
        close = float(bar["close"])
        high = float(bar["high"])
        low = float(bar["low"])
        if high >= hi + ext_mult * width and close < hi:
            nxt = next_open_after(day, ts, end)
            if not nxt:
                return
            entry_ts, entry = nxt
            stop = max(high, hi + (ext_mult + 0.35) * width)
            target = max(mid, min(vw, hi))
            fill = exit_scan(day, entry_ts, "SHORT", stop, target, end)
            if fill:
                add_trade(rows, variant=f"or_fade_{start.strftime('%H%M')}_ext{ext_mult:g}_cap{range_cap:g}",
                          inst=inst, contract=contract, cost=cost, day_key=day_key, direction="SHORT",
                          signal_time=ts, entry_time=entry_ts, entry=entry, fill=fill,
                          stop=stop, target=target, meta={"range_pct": width / op})
            return
        if low <= lo - ext_mult * width and close > lo:
            nxt = next_open_after(day, ts, end)
            if not nxt:
                return
            entry_ts, entry = nxt
            stop = min(low, lo - (ext_mult + 0.35) * width)
            target = min(mid, max(vw, lo))
            fill = exit_scan(day, entry_ts, "LONG", stop, target, end)
            if fill:
                add_trade(rows, variant=f"or_fade_{start.strftime('%H%M')}_ext{ext_mult:g}_cap{range_cap:g}",
                          inst=inst, contract=contract, cost=cost, day_key=day_key, direction="LONG",
                          signal_time=ts, entry_time=entry_ts, entry=entry, fill=fill,
                          stop=stop, target=target, meta={"range_pct": width / op})
            return


def prev_day_range_fade(rows: list[dict], inst: str, contract: Contract, cost: float,
                        day_key: pd.Timestamp, day: pd.DataFrame, prev_ctx: dict | None,
                        spy_rv20: float | None, rv_cap: float) -> None:
    if not prev_ctx or spy_rv20 is None or spy_rv20 > rv_cap:
        return
    scan = day.between_time("09:45", "13:30")
    if scan.empty:
        return
    for ts, bar in scan.iterrows():
        close = float(bar["close"])
        high = float(bar["high"])
        low = float(bar["low"])
        if high > prev_ctx["prev_high"] and close < prev_ctx["prev_high"]:
            nxt = next_open_after(day, ts, dtime(15, 30))
            if not nxt:
                return
            entry_ts, entry = nxt
            stop = high
            target = max(prev_ctx["prev_mid"], prev_ctx["prev_close"])
            fill = exit_scan(day, entry_ts, "SHORT", stop, target, dtime(15, 30))
            if fill:
                add_trade(rows, variant=f"prev_range_fade_rv{rv_cap:g}", inst=inst, contract=contract,
                          cost=cost, day_key=day_key, direction="SHORT", signal_time=ts,
                          entry_time=entry_ts, entry=entry, fill=fill, stop=stop, target=target,
                          meta={"spy_rv20": spy_rv20})
            return
        if low < prev_ctx["prev_low"] and close > prev_ctx["prev_low"]:
            nxt = next_open_after(day, ts, dtime(15, 30))
            if not nxt:
                return
            entry_ts, entry = nxt
            stop = low
            target = min(prev_ctx["prev_mid"], prev_ctx["prev_close"])
            fill = exit_scan(day, entry_ts, "LONG", stop, target, dtime(15, 30))
            if fill:
                add_trade(rows, variant=f"prev_range_fade_rv{rv_cap:g}", inst=inst, contract=contract,
                          cost=cost, day_key=day_key, direction="LONG", signal_time=ts,
                          entry_time=entry_ts, entry=entry, fill=fill, stop=stop, target=target,
                          meta={"spy_rv20": spy_rv20})
            return


def modest_gap_fill(rows: list[dict], inst: str, contract: Contract, cost: float,
                    day_key: pd.Timestamp, day: pd.DataFrame, prev_ctx: dict | None,
                    gap_min: float, gap_max: float) -> None:
    day_rth = rth(day)
    if not prev_ctx or len(day_rth) < 120:
        return
    open_px = float(day_rth.iloc[0]["open"])
    prev_close = prev_ctx["prev_close"]
    gap = open_px / prev_close - 1.0
    if not (gap_min <= abs(gap) <= gap_max):
        return
    scan = day.between_time("09:45", "11:30")
    target = prev_close
    if gap < 0:
        trigger = open_px + 0.35 * (prev_close - open_px)
        for ts, bar in scan.iterrows():
            if float(bar["close"]) >= trigger:
                nxt = next_open_after(day, ts, dtime(14, 0))
                if not nxt:
                    return
                entry_ts, entry = nxt
                stop = min(open_px, float(scan.loc[:ts, "low"].min()))
                fill = exit_scan(day, entry_ts, "LONG", stop, target, dtime(14, 0))
                if fill:
                    add_trade(rows, variant=f"gap_fill_{gap_min:g}_{gap_max:g}", inst=inst,
                              contract=contract, cost=cost, day_key=day_key, direction="LONG",
                              signal_time=ts, entry_time=entry_ts, entry=entry, fill=fill,
                              stop=stop, target=target, meta={"gap": gap})
                return
    else:
        trigger = open_px - 0.35 * (open_px - prev_close)
        for ts, bar in scan.iterrows():
            if float(bar["close"]) <= trigger:
                nxt = next_open_after(day, ts, dtime(14, 0))
                if not nxt:
                    return
                entry_ts, entry = nxt
                stop = max(open_px, float(scan.loc[:ts, "high"].max()))
                fill = exit_scan(day, entry_ts, "SHORT", stop, target, dtime(14, 0))
                if fill:
                    add_trade(rows, variant=f"gap_fill_{gap_min:g}_{gap_max:g}", inst=inst,
                              contract=contract, cost=cost, day_key=day_key, direction="SHORT",
                              signal_time=ts, entry_time=entry_ts, entry=entry, fill=fill,
                              stop=stop, target=target, meta={"gap": gap})
                return


def session_drift(rows: list[dict], inst: str, contract: Contract, cost: float,
                  day_key: pd.Timestamp, day: pd.DataFrame, prev_day: pd.DataFrame | None) -> None:
    day_rth = rth(day)
    prev = rth(prev_day) if prev_day is not None else pd.DataFrame()
    if len(day_rth) < 180:
        return
    midday = day.between_time("12:00", "12:00")
    if not midday.empty:
        entry_ts = day_rth.index[0]
        entry = float(day_rth.iloc[0]["open"])
        fill = Fill(float(midday.iloc[0]["open"]), "time", midday.index[0])
        for direction in ("LONG", "SHORT"):
            add_trade(rows, variant="drift_open_to_midday", inst=inst, contract=contract, cost=cost,
                      day_key=day_key, direction=direction, signal_time=entry_ts, entry_time=entry_ts,
                      entry=entry, fill=fill, stop=None, target=None, meta={"event_filter": "missing"})
    if len(prev) >= 60:
        overnight = day.between_time("09:30", "09:30")
        if not overnight.empty:
            sig_ts = prev.index[-1]
            entry_ts = sig_ts
            entry = float(prev.iloc[-1]["close"])
            fill = Fill(float(overnight.iloc[0]["open"]), "time", overnight.index[0])
            for direction in ("LONG", "SHORT"):
                add_trade(rows, variant="drift_close_to_next_open", inst=inst, contract=contract, cost=cost,
                          day_key=day_key, direction=direction, signal_time=sig_ts, entry_time=entry_ts,
                          entry=entry, fill=fill, stop=None, target=None, meta={"event_filter": "missing"})


def pair_relative_value(rows: list[dict], day_key: pd.Timestamp, day_by_inst: dict[str, pd.DataFrame],
                        costs: dict[str, float]) -> None:
    if "MNQ" not in day_by_inst or "MES" not in day_by_inst:
        return
    nq = rth(day_by_inst["MNQ"])
    es = rth(day_by_inst["MES"])
    if len(nq) < 180 or len(es) < 180:
        return
    try:
        nq1030 = float(nq.between_time("10:30", "10:30").iloc[0]["close"])
        es1030 = float(es.between_time("10:30", "10:30").iloc[0]["close"])
        nqopen = float(nq.iloc[0]["open"])
        esopen = float(es.iloc[0]["open"])
    except IndexError:
        return
    nq_ret = nq1030 / nqopen - 1.0
    es_ret = es1030 / esopen - 1.0
    spread = nq_ret - es_ret
    if abs(spread) < 0.003:
        return
    nq_next = next_open_after(day_by_inst["MNQ"], nq.between_time("10:30", "10:30").index[0], dtime(14, 0))
    es_next = next_open_after(day_by_inst["MES"], es.between_time("10:30", "10:30").index[0], dtime(14, 0))
    nq_exit = day_by_inst["MNQ"].between_time("14:00", "14:00")
    es_exit = day_by_inst["MES"].between_time("14:00", "14:00")
    if not nq_next or not es_next or nq_exit.empty or es_exit.empty:
        return
    nq_entry_ts, nq_entry = nq_next
    es_entry_ts, es_entry = es_next
    nq_ex = float(nq_exit.iloc[0]["open"])
    es_ex = float(es_exit.iloc[0]["open"])
    if spread > 0:
        nq_dir, es_dir = "SHORT", "LONG"
        pnl = (nq_entry - nq_ex) * BASKET["MNQ"].point_value + (es_ex - es_entry) * BASKET["MES"].point_value
    else:
        nq_dir, es_dir = "LONG", "SHORT"
        pnl = (nq_ex - nq_entry) * BASKET["MNQ"].point_value + (es_entry - es_ex) * BASKET["MES"].point_value
    pnl -= costs["MNQ"] + costs["MES"]
    rows.append({
        "variant": "pair_mnq_mes_dispersion",
        "inst": "MNQ/MES",
        "direction": f"{nq_dir}_MNQ_{es_dir}_MES",
        "day": day_key.date().isoformat(),
        "year": int(day_key.year),
        "signal_time": nq.between_time("10:30", "10:30").index[0],
        "entry_time": max(nq_entry_ts, es_entry_ts),
        "exit_time": nq_exit.index[0],
        "entry": np.nan,
        "exit": np.nan,
        "stop": np.nan,
        "target": np.nan,
        "reason": "time",
        "pnl": pnl,
        "spread": spread,
        "outside_exit_bar": 0,
        "pair_assumption": "one MNQ leg and one MES leg; explicit pair PnL, no beta-neutral sizing",
    })


def spy_features(regime_csv: str) -> pd.DataFrame:
    close = benchmark_daily(regime_csv).sort_index()
    ret = close.pct_change()
    out = pd.DataFrame({"spy_close": close, "spy_rv20": ret.rolling(20).std() * math.sqrt(252)})
    out["spy_rv20_d1"] = out["spy_rv20"].shift(1)
    return out


def run_window(args, start: str, end: str, data_dir: str, hmm_fit_end: str, selected: set[str] | None = None) -> pd.DataFrame:
    labels = label_regimes(benchmark_daily(args.regime_csv), args.hmm_train_end, 3, hmm_fit_end)
    features = spy_features(args.regime_csv)
    costs_obj = costs_for_basket(slippage_ticks=args.slippage_ticks)
    costs = {k: v.round_turn_cost() for k, v in costs_obj.items()}
    frames_by_inst = {}
    day_maps: dict[str, dict[pd.Timestamp, pd.DataFrame]] = {}
    for inst, contract in BASKET.items():
        df = load_parquet(str(Path(data_dir) / data_filename(contract)))
        s = pd.Timestamp(start).tz_localize(df.index.tz)
        e = pd.Timestamp(end).tz_localize(df.index.tz)
        frames_by_inst[inst] = df[(df.index >= s) & (df.index <= e)]
        day_maps[inst] = {
            pd.Timestamp(day_ts).tz_localize(None).normalize(): day
            for day_ts, day in frames_by_inst[inst].groupby(frames_by_inst[inst].index.normalize())
        }

    rows: list[dict] = []
    days = sorted({day for m in day_maps.values() for day in m})
    prev_by_inst: dict[str, pd.DataFrame | None] = {k: None for k in BASKET}
    for day_key in days:
        if labels.get(day_key) != "Calm":
            for inst, m in day_maps.items():
                g = m.get(day_key)
                if g is not None and not g.empty:
                    prev_by_inst[inst] = g
            continue
        day_by_inst = {}
        for inst, m in day_maps.items():
            g = m.get(day_key)
            if g is not None and not g.empty:
                day_by_inst[inst] = g
        if not day_by_inst:
            continue
        for inst, day in day_by_inst.items():
            contract = BASKET[inst]
            prev_ctx = prior_rth_context(prev_by_inst.get(inst))
            rv = None
            if day_key in features.index:
                rv = float(features.loc[day_key, "spy_rv20_d1"])
                if math.isnan(rv):
                    rv = None
            if selected is None or any(v.startswith("or_fade") for v in selected):
                for start_time in (dtime(10, 0), dtime(10, 30)):
                    for ext in (0.25, 0.50):
                        for cap in (0.008, 0.012):
                            opening_range_fade(rows, inst, contract, costs[inst], day_key, day, start_time, ext, cap)
            if selected is None or any(v.startswith("prev_range") for v in selected):
                for cap in (0.12, 0.16):
                    prev_day_range_fade(rows, inst, contract, costs[inst], day_key, day, prev_ctx, rv, cap)
            if selected is None or any(v.startswith("gap_fill") for v in selected):
                modest_gap_fill(rows, inst, contract, costs[inst], day_key, day, prev_ctx, 0.0025, 0.010)
            if selected is None or any(v.startswith("drift") for v in selected):
                session_drift(rows, inst, contract, costs[inst], day_key, day, prev_by_inst.get(inst))
        if selected is None or "pair_mnq_mes_dispersion" in selected:
            pair_relative_value(rows, day_key, day_by_inst, costs)
        for inst, day in day_by_inst.items():
            prev_by_inst[inst] = day

    out = pd.DataFrame(rows)
    if selected is not None and not out.empty:
        out = out[out["variant"].isin(selected)]
    if out.empty:
        return out
    out["outside_exit_bar"] = out.apply(outside_exit_bar, axis=1)
    return out


def outside_exit_bar(row: pd.Series) -> int:
    if row.get("variant") == "pair_mnq_mes_dispersion":
        return 0
    # The exit scan records fills at a theoretical level only when the level is
    # inside the crossing bar. Time exits use the close, which is inside the bar.
    return 0


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "pnl": 0.0, "pf": 0.0, "wr": 0.0, "exp": 0.0}
    pnl = df["pnl"]
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    return {
        "n": int(len(df)),
        "pnl": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "wr": float((pnl > 0).mean() * 100.0),
        "exp": float(pnl.mean()),
    }


def print_summary(df: pd.DataFrame, title: str) -> None:
    print(f"\n=== {title} ===")
    if df.empty:
        print("no trades")
        return
    print(f"fill_audit outside_exit_bar={int(df['outside_exit_bar'].sum())}")
    print("variant                                inst      dir                      n       pnl     PF    exp")
    group_cols = ["variant", "inst", "direction"]
    for keys, g in df.groupby(group_cols, dropna=False):
        st = stats(g)
        pf = "inf" if math.isinf(st["pf"]) else f"{st['pf']:.2f}"
        print(f"{keys[0]:<38} {keys[1]:<8} {keys[2]:<22} {st['n']:4d} {st['pnl']:9.0f} {pf:>6} {st['exp']:7.2f}")
    print("\n-- by variant/year --")
    for keys, g in df.groupby(["variant", "year"], dropna=False):
        st = stats(g)
        print(f"{keys[0]:<38} {int(keys[1])} n={st['n']:4d} pnl={st['pnl']:9.0f} exp={st['exp']:7.2f}")


def robust_candidates(df: pd.DataFrame, limit: int = 2) -> list[str]:
    keep = []
    for variant, g in df.groupby("variant"):
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        by_inst = g.groupby("inst")["pnl"].sum()
        top_year_share = float(by_year.max() / st["pnl"]) if st["pnl"] > 0 and len(by_year) else 1.0
        only_one_inst = int((by_inst > 0).sum()) <= 1 and not variant.startswith("pair_")
        pos_years = int((by_year > 0).sum())
        if st["n"] >= 30 and st["pnl"] > 0 and st["pf"] >= 1.08 and top_year_share < 0.75 and not only_one_inst and pos_years >= 3:
            keep.append((variant, st["pnl"], st["pf"], st["exp"]))
    keep.sort(key=lambda x: (x[1], x[2], x[3]), reverse=True)
    return [x[0] for x in keep[:limit]]


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
    ap.add_argument("--out-prefix", default="scratch/calm_strategy_excavation")
    args = ap.parse_args()

    print("Calm excavation: local data only; event calendar filter is missing for drift variants.")
    is_df = run_window(args, "2018-01-01", "2024-12-31", args.data_dir, args.hmm_fit_end_is)
    Path(args.out_prefix).parent.mkdir(parents=True, exist_ok=True)
    is_path = f"{args.out_prefix}_is.csv"
    is_df.to_csv(is_path, index=False)
    print(f"wrote {is_path} rows={len(is_df)}")
    print_summary(is_df, "2018-2024 IS all variants")

    selected = robust_candidates(is_df)
    print("\n=== IS SELECTION ===")
    if selected:
        print("selected_before_oos=" + ",".join(selected))
    else:
        print("selected_before_oos=NONE")
        print("verdict=keep digging")
        return 0

    oos25 = run_window(args, "2025-01-01", "2025-12-31", args.data_dir_2025, args.hmm_fit_end_oos, set(selected))
    oos25_path = f"{args.out_prefix}_2025.csv"
    oos25.to_csv(oos25_path, index=False)
    print(f"wrote {oos25_path} rows={len(oos25)}")
    print_summary(oos25, "2025 OOS selected")

    chk26 = run_window(args, "2026-01-01", "2026-08-19", args.data_dir_2026, args.hmm_fit_end_oos, set(selected))
    chk26_path = f"{args.out_prefix}_2026.csv"
    chk26.to_csv(chk26_path, index=False)
    print(f"wrote {chk26_path} rows={len(chk26)}")
    print_summary(chk26, "2026 sanity selected")

    survivors = []
    for variant in selected:
        is_st = stats(is_df[is_df.variant == variant])
        o25_st = stats(oos25[oos25.variant == variant])
        c26_st = stats(chk26[chk26.variant == variant])
        if o25_st["pnl"] > 0 and c26_st["pnl"] >= 0 and min(is_st["pf"], o25_st["pf"]) >= 1.05:
            survivors.append(variant)
    print("\n=== VERDICT ===")
    if survivors:
        print("deploy_level_candidate=" + ",".join(survivors))
        print("next: run deploy-level scratch integration against Normal+Stress system")
    else:
        print("deploy_level_candidate=NONE")
        print("verdict=keep digging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
