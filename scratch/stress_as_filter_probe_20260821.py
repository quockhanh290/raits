from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import load_parquet, resample_5m
from futures.basket import BASKET, data_filename
from global_index.deploy_sim import metrics
from scratch.harness import ARGV
from scratch.stress_new_hypothesis_pass_20260821 import parse_time, vwap


CALM_FILES = {
    "floor": Path("scratch/calm_open_location_drift_delay_sensitivity_is.csv"),
    "vault2025": Path("scratch/calm_open_location_drift_delay_sensitivity_2025.csv"),
    "vault2026": Path("scratch/calm_open_location_drift_delay_sensitivity_2026.csv"),
}
NORMAL_FILES = {
    "floor": Path("scratch/normal_sleeve_trades_floor_20260821.json"),
    "vault2025": Path("scratch/normal_sleeve_trades_vault2025_20260821.json"),
    "vault2026": Path("scratch/normal_sleeve_trades_vault2026_20260821.json"),
}
CALM_VARIANT = "openloc_lower_third_long_e1000_x1555"


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def clip(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start:
        df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    if end:
        df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
    return df


def load_dfs(which: str):
    argv = list(ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    dfs = {n: clip(load_parquet(str(Path(data_dir) / data_filename(c))), start, end) for n, c in BASKET.items()}
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    return dfs, sessions


def ctx_at(g: pd.DataFrame, setup_time: str, prev_close: float | None = None) -> dict | None:
    bars5 = resample_5m(g).between_time("09:30", "15:55")
    rth = g.between_time("09:30", "16:00")
    pre = bars5[bars5.index.time <= parse_time(setup_time)]
    sig = bars5[bars5.index.time == parse_time(setup_time)]
    if rth.empty or len(pre) < 8 or sig.empty:
        return None
    open_px = float(rth.iloc[0]["open"])
    sig_close = float(sig.iloc[-1]["close"])
    vw = vwap(pre)
    hi = float(pre["high"].max())
    lo = float(pre["low"].min())
    out = {
        "open": open_px,
        "signal_close": sig_close,
        "vwap": vw,
        "pre_high": hi,
        "pre_low": lo,
        "range_pct": (hi - lo) / open_px if open_px else 0.0,
        "below": sig_close < open_px and sig_close < vw,
        "ret": sig_close / open_px - 1.0 if open_px else 0.0,
    }
    if prev_close is not None:
        out["gap"] = open_px / prev_close - 1.0
    return out


def has_low_break(g: pd.DataFrame, level: float, start: str, end: str) -> bool:
    sub = g[(g.index.time >= parse_time(start)) & (g.index.time <= parse_time(end))]
    return bool((sub["low"] < level).any()) if not sub.empty else False


def detector_days(which: str) -> dict[str, set[pd.Timestamp]]:
    dfs, _ = load_dfs(which)
    by_day_inst = {}
    prev_close = {}
    for inst, df in dfs.items():
        last = None
        for day_ts, g in df.groupby(df.index.normalize()):
            day = pd.Timestamp(day_ts).tz_localize(None).normalize()
            by_day_inst[(day, inst)] = g
            prev_close[(day, inst)] = last
            rth = g.between_time("09:30", "16:00")
            if not rth.empty:
                last = float(rth.iloc[-1]["close"])

    late = set()
    gapfull = set()
    for day in sorted({d for d, _ in by_day_inst}):
        ctx1100 = {inst: ctx_at(by_day_inst[(day, inst)], "11:00") for inst in BASKET if (day, inst) in by_day_inst}
        ctx1100 = {k: v for k, v in ctx1100.items() if v is not None}
        if len(ctx1100) == 4:
            below = sum(1 for c in ctx1100.values() if c["below"])
            wide = sum(1 for c in ctx1100.values() if c["range_pct"] >= 0.008)
            if below >= 3 and wide >= 2:
                for inst in ("MNQ", "MES"):
                    c = ctx1100.get(inst)
                    g = by_day_inst.get((day, inst))
                    if c and c["below"] and g is not None and has_low_break(g, c["pre_low"], "11:05", "13:00"):
                        late.add(day)
                        break

        ctx1030 = {}
        for inst in BASKET:
            g = by_day_inst.get((day, inst))
            if g is None:
                continue
            ctx = ctx_at(g, "10:30", prev_close.get((day, inst)))
            if ctx is not None:
                ctx1030[inst] = ctx
        if len(ctx1030) == 4:
            below = sum(1 for c in ctx1030.values() if c["below"])
            gapdown = sum(1 for c in ctx1030.values() if c.get("gap", 0.0) <= -0.004)
            if below >= 4 and gapdown >= 3:
                for inst in ("MNQ", "MES"):
                    c = ctx1030.get(inst)
                    g = by_day_inst.get((day, inst))
                    if c and c["below"] and g is not None and has_low_break(g, c["pre_low"], "10:35", "12:30"):
                        gapfull.add(day)
                        break
    return {
        "late_break_1100_b3_days": late,
        "gapdown_full_breadth_1030_days": gapfull,
        "union_days": late | gapfull,
    }


def load_normal(which: str) -> pd.DataFrame:
    path = NORMAL_FILES[which]
    if not path.exists():
        return pd.DataFrame()
    data = json.loads(path.read_text())
    bucket = data.get("corrected") or data.get("booked") or {}
    rows = []
    for inst, trades in bucket.items():
        for t in trades:
            rows.append({
                "source": "normal_corrected",
                "variant": "normal_corrected",
                "instrument": inst,
                "day": pd.Timestamp(t["day"]).normalize(),
                "pnl": float(t["pnl"]),
            })
    return pd.DataFrame(rows)


def load_calm(which: str) -> pd.DataFrame:
    path = CALM_FILES[which]
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df = df[df["variant"] == CALM_VARIANT].copy()
    if df.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "source": "calm_openloc_e1000",
        "variant": CALM_VARIANT,
        "instrument": df["inst"],
        "day": pd.to_datetime(df["day"]).dt.normalize(),
        "pnl": df["pnl"].astype(float),
    })


def dense_daily(trades: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(0.0, index=sessions)
    if trades.empty:
        return s
    d = trades.groupby("day")["pnl"].sum()
    d.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in d.index])
    return s.add(d, fill_value=0.0)


def summarize(trades: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict:
    if trades.empty:
        return {"trades": 0, "days": 0, "net": 0.0, "pf": math.inf, "calmar": 0.0, "maxdd": 0.0}
    daily = dense_daily(trades, sessions)
    m = metrics(daily)
    gp = float(trades.loc[trades["pnl"] > 0, "pnl"].sum())
    gl = float(-trades.loc[trades["pnl"] < 0, "pnl"].sum())
    return {
        "trades": int(len(trades)),
        "days": int(trades["day"].nunique()),
        "net": float(trades["pnl"].sum()),
        "pf": gp / gl if gl else math.inf,
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
    }


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run(which: str) -> str:
    _, sessions = load_dfs(which)
    dets = detector_days(which)
    books = [load_normal(which), load_calm(which)]
    base = pd.concat([b for b in books if not b.empty], ignore_index=True) if any(not b.empty for b in books) else pd.DataFrame()
    rows = []
    for source in sorted(base["source"].unique()) if not base.empty else []:
        src = base[base["source"] == source].copy()
        for det_name, days in dets.items():
            kept = src[~src["day"].isin(days)].copy()
            skipped = src[src["day"].isin(days)].copy()
            b = summarize(src, sessions)
            k = summarize(kept, sessions)
            rows.append({
                "source": source,
                "filter": det_name,
                "filter_days": len(days),
                "base_trades": b["trades"],
                "skipped_trades": len(skipped),
                "skipped_pnl": fmt_money(float(skipped["pnl"].sum()) if not skipped.empty else 0.0),
                "base_net": fmt_money(b["net"]),
                "kept_net": fmt_money(k["net"]),
                "delta": fmt_money(k["net"] - b["net"]),
                "base_pf": fmt_pf(b["pf"]),
                "kept_pf": fmt_pf(k["pf"]),
                "base_maxdd": fmt_money(b["maxdd"]),
                "kept_maxdd": fmt_money(k["maxdd"]),
            })
    print(which, {k: len(v) for k, v in dets.items()}, rows[:3])
    return "\n".join([f"## {which}", "", table(rows, ["source", "filter", "filter_days", "base_trades", "skipped_trades", "skipped_pnl", "base_net", "kept_net", "delta", "base_pf", "kept_pf", "base_maxdd", "kept_maxdd"])])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_as_filter_probe_20260821_report.md")
    args = ap.parse_args()
    parts = [
        "# Stress As Filter Probe - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Tests Stress detectors as risk-off skip filters for existing Normal corrected trades and the clean Calm open-location 10:00 candidate.",
        "",
    ]
    for w in args.which:
        parts.append(run(w))
        parts.append("")
    Path(args.report).write_text("\n".join(parts), encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
