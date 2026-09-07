from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.calm_a_combined_replay_20260822 as calm_a_base
import scratch.stress_with_nkd_probe_20260822 as nkd_base
from futures.basket import BASKET, data_filename
from futures._validated_core import load_parquet
from global_index.deploy_sim import metrics
from scratch.normal_sleeve_fill_audit import ACCOUNT


OUT = Path("scratch/calm_a_disaster_stop_probe_20260822_report.md")
JSON_OUT = Path("scratch/calm_a_disaster_stop_probe_20260822.json")
CALM_A_CSV = Path("scratch/calm_pcloc_not_deep_gap_trade_list.csv")

WINDOW_MAP = {
    "floor": "IS_2018_2024",
    "vault2025": "OOS_2025",
    "vault2026": "SANITY_2026",
}


@dataclass(frozen=True)
class StopSpec:
    name: str
    kind: str
    value: float | None = None


STOP_SPECS = [
    StopSpec("no_stop", "none"),
    StopSpec("atr05", "atr", 0.5),
    StopSpec("atr10", "atr", 1.0),
    StopSpec("atr15", "atr", 1.5),
    StopSpec("atr20", "atr", 2.0),
    StopSpec("or_low_1tick", "or_low", 1.0),
]


def arg_from(argv: list[str], flag: str, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def load_price_frames(which: str) -> dict[str, pd.DataFrame]:
    raw = json.loads(nkd_base.full.NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    argv = raw["argv"]
    data_dir = Path(arg_from(argv, "--data-dir"))
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    out = {}
    for inst in ("MES", "MNQ"):
        df = load_parquet(str(data_dir / data_filename(BASKET[inst])))
        if start:
            df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
        if end:
            df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
        out[inst] = df
    return out


def day_bars(df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    d = pd.Timestamp(day)
    if d.tz is None:
        d = d.tz_localize(df.index.tz)
    return df[df.index.normalize() == d.normalize()]


def atr_value(meta: dict, inst: str, day: pd.Timestamp) -> float:
    v = meta[inst]["atr"].asof(pd.Timestamp(day))
    if v is None or pd.isna(v):
        v = meta[inst]["atr"].median()
    return float(v)


def stop_for(row: pd.Series, spec: StopSpec, frames: dict[str, pd.DataFrame], meta: dict) -> float | None:
    if spec.kind == "none":
        return None
    inst = row["inst"]
    entry = float(row["entry"])
    if spec.kind == "atr":
        return entry - float(spec.value) * atr_value(meta, inst, pd.Timestamp(row["day"]))
    if spec.kind == "or_low":
        df = frames[inst]
        g = day_bars(df, pd.Timestamp(row["day"]))
        pre = g[(g.index >= pd.Timestamp(row["entry_time"]).replace(hour=9, minute=30))
                & (g.index < pd.Timestamp(row["entry_time"]))]
        if pre.empty:
            return None
        return float(pre["low"].min()) - float(spec.value) * BASKET[inst].tick
    raise ValueError(spec.kind)


def simulate_exit(row: pd.Series, stop: float | None, frames: dict[str, pd.DataFrame], slip_ticks: float = 2.0) -> dict:
    inst = row["inst"]
    entry_ts = pd.Timestamp(row["entry_time"])
    exit_ts0 = pd.Timestamp(row["exit_time"])
    entry = float(row["entry"])
    pv = BASKET[inst].point_value
    cost = calm_a_base.full.costs_for_basket(slippage_ticks=slip_ticks)[inst].round_turn_cost()
    if stop is None:
        exit_px = float(row["exit"])
        reason = "time"
        exit_ts = exit_ts0
    else:
        df = frames[inst]
        fwd = df[(df.index > entry_ts) & (df.index <= exit_ts0)]
        exit_px = float(row["exit"])
        reason = "time"
        exit_ts = exit_ts0
        for ts, bar in fwd.iterrows():
            if float(bar["low"]) <= stop:
                exit_px = float(bar["open"]) if float(bar["open"]) <= stop else float(stop)
                reason = "stop"
                exit_ts = ts
                break
    pnl = (exit_px - entry) * pv - cost
    risk = (entry - stop) * pv if stop is not None else float("nan")
    return {
        "exit": exit_px,
        "exit_time": exit_ts,
        "pnl_sized": pnl,
        "risk_sized": risk,
        "exit_reason": reason,
        "stop": stop,
    }


def build_calm_trades(which: str, spec: StopSpec, meta: dict, frames: dict[str, pd.DataFrame],
                      slip_ticks: float = 2.0) -> pd.DataFrame:
    src = pd.read_csv(CALM_A_CSV)
    src = src[src["window"] == WINDOW_MAP[which]].copy()
    rows = []
    for i, t in src.reset_index(drop=True).iterrows():
        stop = stop_for(t, spec, frames, meta)
        sim = simulate_exit(t, stop, frames, slip_ticks)
        inst = t["inst"]
        risk = sim["risk_sized"]
        if math.isnan(risk) or risk <= 0:
            risk = calm_a_base._real_risk(meta[inst]["atr"], meta[inst]["mult"], meta[inst]["pv"], pd.Timestamp(t["day"]), 1)
        rows.append({
            "trade_id": f"calm_a_{spec.name}_{which}_{inst}_{i}",
            "source": "calm_a_pcloc_not_deep",
            "cluster": "roska4_calm",
            "instrument": inst,
            "direction": t["direction"],
            "day": pd.Timestamp(t["day"]).normalize(),
            "entry_time": pd.Timestamp(t["entry_time"]),
            "exit_time": pd.Timestamp(sim["exit_time"]),
            "entry": float(t["entry"]),
            "exit": float(sim["exit"]),
            "pnl_sized": float(sim["pnl_sized"]),
            "risk_sized": float(risk),
            "exit_reason": sim["exit_reason"],
            "stop": sim["stop"],
            "outside_exit_bar": int(t.get("outside_exit_bar", 0)),
            "outside_entry_bar": int(t.get("outside_entry_bar", 0)),
            "signal_after_entry": int(t.get("signal_after_entry", 0)),
        })
    return pd.DataFrame(rows)


def daily_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return dict(n=0, net=0.0, pf=0.0, sharpe=0.0, calmar=0.0, maxdd=0.0, stop_rate=0.0)
    exit_days = pd.DatetimeIndex([
        (pd.Timestamp(x).tz_localize(None) if pd.Timestamp(x).tz is not None else pd.Timestamp(x)).normalize()
        for x in df["exit_time"]
    ])
    daily = df.assign(_exit_day=exit_days).groupby("_exit_day")["pnl_sized"].sum().sort_index()
    m = metrics(daily)
    pnl = df["pnl_sized"].astype(float)
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return dict(
        n=int(len(df)),
        net=float(pnl.sum()),
        pf=float(wins / losses) if losses > 1e-9 else math.inf,
        sharpe=float(m["sharpe"]),
        calmar=float(m["calmar"]),
        maxdd=float(m["maxdd"]),
        stop_rate=float((df["exit_reason"] == "stop").mean()),
        med_risk=float(df["risk_sized"].median()),
        max_risk=float(df["risk_sized"].max()),
    )


def combined_replay_with(calm_df: pd.DataFrame, which: str, cap: float = 0.05) -> tuple[pd.Series, dict]:
    old_loader = calm_a_base.load_calm_a
    old_policies = calm_a_base.POLICIES

    def loader(_which: str, _meta: dict, _slip_ticks: float):
        assert _which == which
        return calm_df.copy()

    calm_a_base.load_calm_a = loader
    calm_a_base.POLICIES = [calm_a_base.Policy("tmp", cap, "skip_same_symbol", 2.0)]
    try:
        return calm_a_base.replay(which, calm_a_base.POLICIES[0])
    finally:
        calm_a_base.load_calm_a = old_loader
        calm_a_base.POLICIES = old_policies


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    return f"{100*x:.1f}%"


def fmt_float(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run_window(which: str) -> tuple[str, list[dict]]:
    _r4, _nkd, _prices, extra = nkd_base.load_r4_and_nkd(which)
    meta = extra["meta"]
    frames = load_price_frames(which)
    rows = []
    raw = []
    for spec in STOP_SPECS:
        calm = build_calm_trades(which, spec, meta, frames)
        sm = daily_metrics(calm)
        daily, st = combined_replay_with(calm, which, cap=0.05)
        cm = metrics(daily)
        row = {
            "stop": spec.name,
            "standalone_n": sm["n"],
            "standalone_net": fmt_money(sm["net"]),
            "standalone_pf": fmt_float(sm["pf"]),
            "standalone_dd": fmt_money(sm["maxdd"]),
            "stop_rate": fmt_pct(sm["stop_rate"]),
            "med_risk": fmt_money(sm["med_risk"]),
            "max_risk": fmt_money(sm["max_risk"]),
            "Calm taken/rej": f"{st['taken']['roska4_calm']}/{st['rejected']['roska4_calm']}",
            "combined_net": fmt_money(cm["pnl"]),
            "combined_pf": fmt_float(cm["pf"]),
            "combined_sharpe": fmt_float(cm["sharpe"]),
            "combined_calmar": fmt_float(cm["calmar"]),
            "combined_maxdd": fmt_money(cm["maxdd"]),
            "halts": st["halted"],
        }
        rows.append(row)
        raw.append({"stop": spec.__dict__, "standalone": sm, "combined": cm, "state": st})
    section = "\n".join([f"## {which}", "", table(rows, [
        "stop", "standalone_n", "standalone_net", "standalone_pf", "standalone_dd",
        "stop_rate", "med_risk", "max_risk", "Calm taken/rej", "combined_net",
        "combined_pf", "combined_sharpe", "combined_calmar", "combined_maxdd", "halts",
    ]), ""])
    return section, raw


def main() -> int:
    parts = [
        "# Calm A Disaster Stop Probe - 2026-08-22",
        "",
        "Scratch-only. Tests explicit disaster stops for Calm A PCLoc bottom-down not-deep-gap. Combined rows use the current strongest base plus Calm A with skip-same-symbol and Calm cap 5%.",
        "",
        "Stop fill rule for LONG: if a forward bar trades through the stop, fill at stop unless the bar opens below the stop, in which case fill at the open.",
        "",
    ]
    out = {}
    for which in ("floor", "vault2025", "vault2026"):
        section, raw = run_window(which)
        parts.append(section)
        out[which] = raw
    OUT.write_text("\n".join(parts), encoding="utf-8")
    JSON_OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    print(JSON_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
