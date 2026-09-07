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
from futures.stress_mid import StressMidEngine
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from scratch.harness import ARGV


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


def lag1(labels: dict[pd.Timestamp, str]) -> dict[pd.Timestamp, str]:
    s = pd.Series(labels).sort_index()
    shifted = s.shift(1).dropna()
    return {pd.Timestamp(k).normalize(): str(v) for k, v in shifted.items()}


def load_window(which: str):
    argv = list(ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    costs = costs_for_basket(slippage_ticks=float(arg_from(argv, "--slippage-ticks", 2.0)))
    dfs = {n: clip(load_parquet(str(Path(data_dir) / data_filename(c))), start, end) for n, c in BASKET.items()}
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    labels0 = label_regimes(
        benchmark_daily(arg_from(argv, "--regime-csv", "spy_daily_live.csv")),
        arg_from(argv, "--hmm-train-end", "2018-01-01"),
        3,
        arg_from(argv, "--hmm-fit-end", None),
    )
    return dfs, costs, sessions, labels0, lag1(labels0)


def trades_for(dfs: dict, costs: dict, labels: dict[pd.Timestamp, str]) -> pd.DataFrame:
    eng = StressMidEngine()
    rows = []
    for inst, df in dfs.items():
        for t in eng.backtest(df, labels, costs[inst]):
            entry_time = pd.Timestamp(t["entry_time"])
            known_time = entry_time + pd.Timedelta(minutes=5)
            rows.append({
                "instrument": inst,
                "day": pd.Timestamp(t["day"]).normalize(),
                "entry_time": entry_time,
                "known_time": known_time,
                "exit_time": pd.Timestamp(t["exit_time"]),
                "pnl": float(t["pnl"]),
                "exit_reason": t.get("exit_reason"),
                "signal_after_entry": int(known_time > entry_time),
                "same_bar_exit": int(pd.Timestamp(t["exit_time"]) == entry_time),
            })
    return pd.DataFrame(rows)


def dense_daily(trades: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(0.0, index=sessions)
    if trades.empty:
        return s
    d = trades.groupby("day")["pnl"].sum()
    d.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in d.index])
    return s.add(d, fill_value=0.0)


def summarize(trades: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict:
    if trades.empty:
        return {"trades": 0, "days": 0, "net": 0.0, "pf": math.inf, "calmar": 0.0, "sharpe": 0.0, "maxdd": 0.0, "sig_after": 0, "same": 0}
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
        "sharpe": float(m["sharpe"]),
        "maxdd": float(m["maxdd"]),
        "sig_after": int(trades["signal_after_entry"].sum()),
        "same": int(trades["same_bar_exit"].sum()),
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
    dfs, costs, sessions, labels0, labels1 = load_window(which)
    rows = []
    frames = {}
    for name, labels in (("lag0_current_backtest", labels0), ("lag1_live_causal", labels1)):
        tr = trades_for(dfs, costs, labels)
        frames[name] = tr
        s = summarize(tr, sessions)
        rows.append({
            "label_basis": name,
            "trades": s["trades"],
            "days": s["days"],
            "net": fmt_money(s["net"]),
            "pf": fmt_pf(s["pf"]),
            "calmar": f"{s['calmar']:.2f}",
            "sharpe": f"{s['sharpe']:.2f}",
            "maxdd": fmt_money(s["maxdd"]),
            "signal_after_entry": s["sig_after"],
            "same_bar_exit": s["same"],
        })
    lines = [f"## {which}", "", table(rows, ["label_basis", "trades", "days", "net", "pf", "calmar", "sharpe", "maxdd", "signal_after_entry", "same_bar_exit"])]
    for name, tr in frames.items():
        if tr.empty:
            continue
        lines += ["", f"By year/instrument for `{name}`:", ""]
        lines.append(tr.assign(year=pd.to_datetime(tr["day"]).dt.year).groupby("year").agg(
            trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")
        ).to_string())
        lines.append("")
        lines.append(tr.groupby("instrument").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
    print(which, rows)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_mid_legacy_status_20260821_report.md")
    args = ap.parse_args()
    parts = [
        "# STRESS_MID Legacy Status - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Measures current legacy STRESS_MID under current lag-0 labels versus lag-1 live-causal labels.",
        "The timing column treats the 5-minute bar stamped 10:15 as known at 10:20.",
        "",
    ]
    for w in args.which:
        parts.append(run(w))
        parts.append("")
    Path(args.report).write_text("\n".join(parts), encoding="utf-8")
    print(args.report)


if __name__ == "__main__":
    main()
