"""
Normal sleeve volume filter probe - scratch/research only.

Reads the corrected Normal trade tables, attaches causal volume features at each
entry bar, then replays simple volume gates without touching production code.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.normal_sleeve_position_sizing_policy_20260821 import replay
from scratch.normal_sleeve_risk_policy_probe_20260821 import (
    ACCOUNT,
    R4,
    build_meta,
    load_trade_json,
    metrics,
)


OUT = Path("scratch/normal_sleeve_volume_filter_probe_20260821.txt")
JSON_OUT = Path("scratch/normal_sleeve_volume_filter_probe_20260821.json")


def _argv_value(argv: list[str], key: str, default=None):
    return argv[argv.index(key) + 1] if key in argv else default


def _clip(df: pd.DataFrame, argv: list[str]) -> pd.DataFrame:
    start = _argv_value(argv, "--start")
    end = _argv_value(argv, "--end")
    if start:
        ts = pd.Timestamp(start)
        if df.index.tz is not None and ts.tzinfo is None:
            ts = ts.tz_localize(df.index.tz)
        df = df[df.index >= ts]
    if end:
        ts = pd.Timestamp(end)
        if df.index.tz is not None and ts.tzinfo is None:
            ts = ts.tz_localize(df.index.tz)
        df = df[df.index <= ts]
    return df


def load_frames(raw: dict) -> dict[str, pd.DataFrame]:
    from futures._validated_core import load_parquet
    from futures.basket import BASKET, data_filename
    from global_index import specs as gi_specs
    from global_index._core import load_parquet as gi_load

    argv = raw["argv"]
    data_dir = Path(_argv_value(argv, "--data-dir"))
    frames = {}
    for inst in R4:
        df = load_parquet(str(data_dir / data_filename(BASKET[inst])))
        frames[inst] = _clip(df, argv)
    nkd_inst = raw["nkd_instrument"]
    c = gi_specs.SPECS[nkd_inst]
    ndf = gi_load(_argv_value(argv, "--nkd-parquet"))
    ndf.index = ndf.index.tz_convert(c.session_tz)
    frames[nkd_inst] = _clip(ndf, argv)
    return frames


def bars_5m(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"].resample("5min").first()
    h = df["high"].resample("5min").max()
    l = df["low"].resample("5min").min()
    c = df["close"].resample("5min").last()
    v = df["volume"].resample("5min").sum()
    out = pd.concat([o, h, l, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna()


def volume_contexts(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {}
    for inst, df in frames.items():
        b = bars_5m(df).copy()
        b["_day"] = b.index.normalize()
        b["_time"] = b.index.time
        b["vol_prev10"] = b.groupby("_day")["volume"].shift(1).rolling(10, min_periods=5).mean()
        b["rvol_prev10"] = b["volume"] / b["vol_prev10"]

        parts = []
        for _, g in b.groupby("_time", sort=False):
            med = g["volume"].shift(1).rolling(20, min_periods=5).median()
            parts.append(med)
        slot_med20 = pd.concat(parts).sort_index()
        b["slot_med20"] = slot_med20
        b["rvol_slot20"] = b["volume"] / b["slot_med20"]
        out[inst] = b
    return out


def _entry_ts(t: dict, fallback_day: str) -> pd.Timestamp:
    val = t.get("entry_time") or fallback_day
    return pd.Timestamp(val)


def attach_book(raw: dict, meta: dict, volctx: dict[str, pd.DataFrame]) -> list[dict]:
    out = []
    nkd = raw["nkd_instrument"]
    trades_by_inst = {k: raw["corrected"][k] for k in R4}
    trades_by_inst[nkd] = raw["corrected"][nkd]
    for inst, trades in trades_by_inst.items():
        m = meta[inst]
        b = volctx[inst]
        for t in trades:
            ed = pd.Timestamp(t["day"])
            xd = pd.Timestamp(t.get("exit_day") or t["day"])
            if ed.tz is not None:
                ed = ed.tz_localize(None)
            if xd.tz is not None:
                xd = xd.tz_localize(None)
            ets = _entry_ts(t, t["day"])
            if b.index.tz is not None and ets.tzinfo is None:
                ets = ets.tz_localize(b.index.tz)
            elif b.index.tz is not None:
                ets = ets.tz_convert(b.index.tz)
            elif ets.tzinfo is not None:
                ets = ets.tz_localize(None)
            if ets not in b.index:
                pos = b.index.get_indexer([ets], method="nearest")[0]
                row = b.iloc[pos] if pos >= 0 else None
            else:
                row = b.loc[ets]
            rslot = float(row["rvol_slot20"]) if row is not None and pd.notna(row["rvol_slot20"]) else np.nan
            rprev = float(row["rvol_prev10"]) if row is not None and pd.notna(row["rvol_prev10"]) else np.nan
            from scratch.normal_sleeve_risk_policy_probe_20260821 import real_risk

            n = 1
            out.append(dict(
                inst=inst,
                cluster=m["cluster"],
                entry=ed,
                exit=xd,
                entry_time=str(ets),
                direction=t["direction"],
                pnl1=float(t["pnl"]),
                pnl_sized=float(t["pnl"]) * n,
                risk_sized=real_risk(m["atr"], m["mult"], m["pv"], ed, n),
                rvol_slot20=rslot,
                rvol_prev10=rprev,
            ))
    return out


def passes(t: dict, rule: dict) -> bool:
    if rule["feature"] == "none":
        return True
    x = t.get(rule["feature"], np.nan)
    if not np.isfinite(x):
        return False
    lo = rule.get("lo")
    hi = rule.get("hi")
    if lo is not None and x < lo:
        return False
    if hi is not None and x > hi:
        return False
    return True


def simple_trade_metrics(book: list[dict]) -> dict:
    daily = {}
    for t in book:
        daily[t["exit"]] = daily.get(t["exit"], 0.0) + t["pnl_sized"]
    m = metrics(pd.Series(daily).sort_index())
    return {k: m[k] for k in ("pnl", "pf", "sharpe", "calmar", "maxdd")}


def rules() -> list[dict]:
    out = [{"name": "none", "feature": "none"}]
    for feat in ("rvol_slot20", "rvol_prev10"):
        for lo in (0.6, 0.8, 1.0, 1.2, 1.5):
            out.append({"name": f"{feat}_ge_{lo:g}", "feature": feat, "lo": lo})
        for hi in (0.8, 1.0, 1.2, 1.5, 2.0):
            out.append({"name": f"{feat}_le_{hi:g}", "feature": feat, "hi": hi})
        for lo, hi in ((0.6, 1.5), (0.8, 1.5), (0.8, 2.0), (1.0, 2.0)):
            out.append({"name": f"{feat}_{lo:g}_{hi:g}", "feature": feat, "lo": lo, "hi": hi})
    return out


def run_window(which: str) -> list[dict]:
    raw = load_trade_json(which)
    meta = build_meta(raw)
    book = attach_book(raw, meta, volume_contexts(load_frames(raw)))
    rows = []
    for rule in rules():
        kept = [t for t in book if passes(t, rule)]
        skipped = [t for t in book if not passes(t, rule)]
        r_current = replay(kept, swing_gross=0.050, swing_net=0.044, nkd_cap=0.060,
                           breaker=0.15, release="latch")
        r_strict = replay(kept, swing_gross=0.025, swing_net=0.025, nkd_cap=0.060,
                          breaker=0.15, release="latch")
        sm = simple_trade_metrics(kept)
        rows.append(dict(
            which=which,
            rule=rule["name"],
            kept=len(kept),
            skipped=len(skipped),
            skipped_pnl=sum(t["pnl_sized"] for t in skipped),
            raw_net=sm["pnl"],
            raw_pf=sm["pf"],
            current_net=r_current["net"],
            current_pf=r_current["pf"],
            current_sharpe=r_current["sharpe"],
            current_calmar=r_current["calmar"],
            current_maxdd_pct=r_current["maxdd_pct"],
            current_halted=r_current["halted_days"],
            current_blocked=r_current["blocked_trades"],
            strict025_net=r_strict["net"],
            strict025_pf=r_strict["pf"],
            strict025_sharpe=r_strict["sharpe"],
            strict025_calmar=r_strict["calmar"],
            strict025_maxdd_pct=r_strict["maxdd_pct"],
            strict025_halted=r_strict["halted_days"],
            strict025_blocked=r_strict["blocked_trades"],
        ))
    return rows


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def main() -> int:
    report = []

    def emit(s: str = ""):
        print(s, flush=True)
        report.append(s)

    all_rows = {}
    for which in ("floor", "vault2025", "vault2026"):
        rows = run_window(which)
        all_rows[which] = rows
        base = next(r for r in rows if r["rule"] == "none")
        rows_sorted = sorted(rows, key=lambda r: (r["current_calmar"], r["current_net"]), reverse=True)
        emit("#" * 110)
        emit(f"WINDOW: {which}")
        emit("#" * 110)
        emit(
            "base current cap: net ${:,.0f} PF {} Sharpe {:.2f} Calmar {:.2f} MaxDD {:.1%} kept {}".format(
                base["current_net"], fmt_pf(base["current_pf"]), base["current_sharpe"],
                base["current_calmar"], base["current_maxdd_pct"], base["kept"]
            )
        )
        emit("top current-cap volume rules")
        emit("  {:<24} {:>5} {:>6} {:>10} {:>5} {:>7} {:>7} {:>8} {:>7}".format(
            "rule", "kept", "skip", "net$", "PF", "Sharpe", "Calmar", "MaxDD%", "blocked"))
        for r in rows_sorted[:18]:
            emit("  {:<24} {:>5} {:>6} {:>10,.0f} {:>5} {:>7.2f} {:>7.2f} {:>8.1%} {:>7}".format(
                r["rule"], r["kept"], r["skipped"], r["current_net"], fmt_pf(r["current_pf"]),
                r["current_sharpe"], r["current_calmar"], r["current_maxdd_pct"], r["current_blocked"]))
        emit("")

    emit("=" * 110)
    emit("CROSS-WINDOW READ")
    emit("=" * 110)
    floor_top = sorted(all_rows["floor"], key=lambda r: (r["current_calmar"], r["current_net"]), reverse=True)[:12]
    emit("  {:<24} {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7}".format(
        "rule", "floor$", "PF", "Calmar", "2025$", "PF", "Calmar", "2026$", "PF", "Calmar"))
    by = {w: {r["rule"]: r for r in rows} for w, rows in all_rows.items()}
    for fr in floor_top:
        r25 = by["vault2025"][fr["rule"]]
        r26 = by["vault2026"][fr["rule"]]
        emit("  {:<24} {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f}".format(
            fr["rule"], fr["current_net"], fmt_pf(fr["current_pf"]), fr["current_calmar"],
            r25["current_net"], fmt_pf(r25["current_pf"]), r25["current_calmar"],
            r26["current_net"], fmt_pf(r26["current_pf"]), r26["current_calmar"]))

    JSON_OUT.write_text(json.dumps(all_rows, indent=2), encoding="utf-8")
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
