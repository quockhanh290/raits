"""Calm-NKD widened-stop excavation with live stop semantics. SCRATCH-ONLY.

This is a new hypothesis after the tight-stop audit:

  - Do not use the old midnight/session-boundary stop check.
  - Arm the stop immediately after entry and scan every 1-minute bar.
  - Test wider stops between the old tiny 5-minute chandelier and the daily-ATR
    stop that already failed.

The script deliberately stops at standalone metrics. Portfolio integration is only
worth doing if a standalone row passes floor + 2025 + slippage sanity.
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

from futures._validated_core import (
    _swing_cache,
    benchmark_daily,
    daily_atr_series,
    label_regimes,
)
from global_index._core import FuturesCost, load_parquet
from global_index.regime import RegimeLabels
from global_index.specs import SPECS
from model_sameday_stop import build_sig_cache, run_loop
from raits.strategies.trend_follow import TrendFollowStrategy


OUT_JSON = Path("scratch/calm_nkd_widened_live_stop_20260822.json")
OUT_REPORT = Path("scratch/calm_nkd_widened_live_stop_20260822_report.md")

DATA_PATH = "global_index/data/NKD_continuous_1m_8y.parquet"
SPY_CSV = "spy_daily_live.csv"
TRAIN_END = "2018-01-01"
FIT_IS = "2022-12-31"
FIT_OOS = "2024-12-31"
ACCOUNT = 50_000.0

WINDOWS = [
    ("floor", "2018-01-01", "2024-12-31", FIT_IS),
    ("vault2025", "2025-01-01", "2025-12-31", FIT_OOS),
    ("vault2026", "2026-01-01", "2026-08-19", FIT_OOS),
]

EMAS = [5, 10, 15, 20]
WIDTH_MULTS = [1.5, 2.0, 3.0, 4.0, 6.0, 8.0]
DAILY_ATR_FRACS = [0.25, 0.35, 0.50, 0.75, 1.00]
STOP_SLIP_TICKS = [0, 1, 2, 3]


class D1CalmAsNormal:
    def __init__(self, spy: pd.Series):
        self.base = RegimeLabels(spy, lag_days=1)

    def get(self, day, default=None):
        return "Normal" if self.base.get(day, default=None) == "Calm" else default


def spy_regime(fit_end: str) -> pd.Series:
    s = pd.Series(label_regimes(benchmark_daily(SPY_CSV), TRAIN_END, 3, fit_end))
    idx = pd.DatetimeIndex(s.index)
    s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return s.sort_index()


def make_strat(ema: int, mult: float = 2.5) -> TrendFollowStrategy:
    cfg = dict(TrendFollowStrategy().config)
    cfg["ema_period"] = ema
    cfg["chandelier_atr_mult"] = mult
    cfg["allowed_regimes"] = ["Normal"]
    return TrendFollowStrategy(cfg)


def patch_daily_atr_stop(strat: TrendFollowStrategy, datr: pd.Series, frac: float):
    base = strat.generate_signal

    def generate_signal(pullback_bar, resume_bar, ema_20, atr, hmm_state, avg_volume_10):
        sig = base(pullback_bar, resume_bar, ema_20, atr, hmm_state, avg_volume_10)
        if not sig:
            return sig
        day = pd.Timestamp(resume_bar.name)
        day = (day.tz_localize(None) if day.tzinfo is not None else day).normalize()
        da = datr.asof(day)
        if da is None or pd.isna(da) or float(da) <= 0:
            return None
        ep = float(sig["entry_price"])
        sig = dict(sig)
        sig["initial_stop"] = ep - frac * float(da) if sig["direction"] == "LONG" else ep + frac * float(da)
        return sig

    strat.generate_signal = generate_signal


def metrics(trades: list[dict], account: float = ACCOUNT) -> dict:
    if not trades:
        return dict(n=0, net=0.0, pf=0.0, sharpe=0.0, calmar=0.0, maxdd=0.0, win_rate=0.0)
    d = pd.DataFrame(trades)
    pnl = d["pnl"].astype(float)
    gp = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    exit_day = pd.to_datetime(d["exit_day"]).dt.tz_localize(None).dt.normalize()
    daily = d.assign(_d=exit_day).groupby("_d")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1) if len(daily) else 0.1
    return dict(
        n=int(len(d)),
        net=float(pnl.sum()),
        ret_pct=float(pnl.sum() / account),
        pf=float(gp / gl) if gl > 1e-9 else math.inf,
        sharpe=float(daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 1e-9 else 0.0,
        calmar=float((pnl.sum() / span) / dd) if dd > 1e-9 else math.inf,
        maxdd=dd,
        win_rate=float((pnl > 0).mean()),
        stop_rate=float(d["reason"].isin(["STP_D0", "GAP_D0", "CHANDELIER", "GAP"]).mean()),
    )


def yearly(trades: list[dict]) -> dict:
    if not trades:
        return {}
    d = pd.DataFrame(trades)
    y = pd.to_datetime(d["day"]).dt.tz_localize(None).dt.year
    return {int(k): round(float(v), 2) for k, v in d.assign(y=y).groupby("y")["pnl"].sum().items()}


def concentration(trades: list[dict]) -> dict:
    if not trades:
        return {}
    p = pd.Series([float(t["pnl"]) for t in trades]).sort_values(ascending=False)
    net = float(p.sum())
    return {
        "top1": float(p.iloc[:1].sum()),
        "top3": float(p.iloc[:3].sum()),
        "top5": float(p.iloc[:5].sum()),
        "top5_pct_net": float(p.iloc[:5].sum() / net) if abs(net) > 1e-9 else math.nan,
    }


def risk_stats(trades: list[dict], sig_cache: dict, c) -> dict:
    risks = []
    for t in trades:
        et = pd.Timestamp(t.get("entry_time"))
        # sig_cache is keyed by day and only valid for first entries. Re-entries are rare
        # in the live-stop loop, so derive risk from entry/exit only for stop exits where
        # the exit reason itself is the stop.
        if t["reason"] in ("STP_D0", "GAP_D0", "CHANDELIER", "GAP"):
            risks.append(abs(float(t["entry"]) - float(t["exit"])) * c.point_value)
    if not risks:
        return {}
    s = pd.Series(risks)
    return {
        "median_usd": float(s.median()),
        "p90_usd": float(s.quantile(0.90)),
        "max_usd": float(s.max()),
    }


def prepare_candidate(labels, cache, *, ema: int, kind: str, value: float):
    strat = make_strat(ema)
    datr = cache["datr"]
    stop_width_mult = 1.0
    if kind == "daily_atr":
        patch_daily_atr_stop(strat, datr, value)
    elif kind == "width_mult":
        stop_width_mult = value
    else:
        raise ValueError(kind)
    sig_cache = build_sig_cache(cache, labels, strat, ema, set(strat.config["allowed_regimes"]))
    return strat, stop_width_mult, sig_cache


def run_candidate(df, labels, cost, cache, *, ema: int, strat, stop_width_mult: float, sig_cache: dict, stop_slip_ticks: float):
    trades, n_d0 = run_loop(
        df,
        labels,
        cost,
        strat=strat,
        ema_period=ema,
        mult=2.5,
        max_hold_days=5,
        cache=cache,
        same_day_stop=True,
        stop_slip_ticks=stop_slip_ticks,
        gap_fill=True,
        activate_after_h=0.0,
        ratchet=True,
        sig_cache=sig_cache,
        stop_width_mult=stop_width_mult,
    )
    return trades, n_d0, sig_cache


def fmt_money(x):
    return f"${x:,.0f}"


def main() -> int:
    c = SPECS["MNKD"]
    raw = load_parquet(DATA_PATH).tz_convert(c.session_tz)
    cost = FuturesCost(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt, slippage_ticks_per_side=2.0)
    out = {"config": {"data": DATA_PATH, "instrument": "MNKD", "point_value": c.point_value, "tick": c.tick}, "windows": {}}

    for wname, start, end, fit_end in WINDOWS:
        print(f"[window] {wname}", flush=True)
        df = raw[(raw.index >= pd.Timestamp(start).tz_localize(c.session_tz)) & (raw.index <= pd.Timestamp(end).tz_localize(c.session_tz) + pd.Timedelta(days=1))]
        datr = daily_atr_series(df)
        cache = _swing_cache(df, datr)
        labels = D1CalmAsNormal(spy_regime(fit_end))
        wout = {"rows": []}

        specs = [("width_mult", v) for v in WIDTH_MULTS] + [("daily_atr", v) for v in DAILY_ATR_FRACS]
        for kind, value in specs:
            for ema in EMAS:
                strat, stop_width_mult, sig_cache = prepare_candidate(labels, cache, ema=ema, kind=kind, value=value)
                base_trades = None
                row = {"kind": kind, "value": value, "ema": ema, "slippage": {}}
                # First pass: baseline only. Extra stop-slippage is applied after
                # cross-window survivors are known, so dead rows do not consume hours.
                for slip in [0]:
                    trades, n_d0, _sig_cache = run_candidate(
                        df,
                        labels,
                        cost,
                        cache,
                        ema=ema,
                        strat=strat,
                        stop_width_mult=stop_width_mult,
                        sig_cache=sig_cache,
                        stop_slip_ticks=slip,
                    )
                    m = metrics(trades)
                    row["slippage"][str(slip)] = m
                    if slip == 0:
                        base_trades = trades
                        row["n_sameday_stop"] = int(n_d0)
                        row["yearly"] = yearly(trades)
                        row["concentration"] = concentration(trades)
                        row["risk"] = risk_stats(trades, sig_cache, c)
                wout["rows"].append(row)
                m0 = row["slippage"]["0"]
                print(f"  {kind:<10} {value:<4} ema={ema:<2} n={m0['n']:>4} net={fmt_money(m0['net']):>9} pf={m0['pf']:.2f} cal={m0['calmar']:.2f} dd={fmt_money(m0['maxdd']):>8}", flush=True)
        out["windows"][wname] = wout

    # Pick rows that are even worth looking at: positive floor and 2025 at zero extra stop slippage.
    candidates = []
    floor_rows = out["windows"]["floor"]["rows"]
    oos_rows = out["windows"]["vault2025"]["rows"]
    by_key_2025 = {(r["kind"], r["value"], r["ema"]): r for r in oos_rows}
    for r in floor_rows:
        key = (r["kind"], r["value"], r["ema"])
        r25 = by_key_2025.get(key)
        if not r25:
            continue
        f0 = r["slippage"]["0"]
        o0 = r25["slippage"]["0"]
        if f0["net"] > 0 and o0["net"] > 0:
            candidates.append({
                "kind": key[0],
                "value": key[1],
                "ema": key[2],
                "floor_net": f0["net"],
                "floor_pf": f0["pf"],
                "floor_calmar": f0["calmar"],
                "oos2025_net": o0["net"],
                "oos2025_pf": o0["pf"],
                "oos2025_calmar": o0["calmar"],
            })
    candidates.sort(key=lambda x: (x["oos2025_net"] > 0, x["floor_net"], x["oos2025_net"]), reverse=True)
    out["positive_floor_and_2025"] = candidates

    # Only survivors get slippage stress.
    if candidates:
        for cand in candidates:
            for wname, start, end, fit_end in WINDOWS:
                df = raw[(raw.index >= pd.Timestamp(start).tz_localize(c.session_tz)) & (raw.index <= pd.Timestamp(end).tz_localize(c.session_tz) + pd.Timedelta(days=1))]
                datr = daily_atr_series(df)
                cache = _swing_cache(df, datr)
                labels = D1CalmAsNormal(spy_regime(fit_end))
                strat, stop_width_mult, sig_cache = prepare_candidate(
                    labels,
                    cache,
                    ema=cand["ema"],
                    kind=cand["kind"],
                    value=cand["value"],
                )
                slip_rows = {}
                for slip in STOP_SLIP_TICKS:
                    trades, _n_d0, _sig_cache = run_candidate(
                        df,
                        labels,
                        cost,
                        cache,
                        ema=cand["ema"],
                        strat=strat,
                        stop_width_mult=stop_width_mult,
                        sig_cache=sig_cache,
                        stop_slip_ticks=slip,
                    )
                    slip_rows[str(slip)] = metrics(trades)
                cand.setdefault("slippage_by_window", {})[wname] = slip_rows

    OUT_JSON.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    write_report(out)
    print(OUT_JSON)
    print(OUT_REPORT)
    return 0


def write_report(out: dict) -> None:
    lines = [
        "# Calm-NKD Widened Live-Stop Excavation - 2026-08-22",
        "",
        "Scratch-only. Production code was not modified.",
        "",
        "Hypothesis: maybe the tight Calm-NKD stop failed because it was too narrow, while the 2x daily ATR stop was too wide. This tests the middle with live-stop semantics: stop armed immediately after entry and checked on 1-minute bars.",
        "",
        "Rows use baseline 2 ticks/side cost. Slippage columns add extra ticks only to stop exits.",
        "",
    ]
    for wname, wout in out["windows"].items():
        lines += [f"## {wname}", "", "| kind | value | ema | trades | net | PF | Calmar | MaxDD | stop rate |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        rows = sorted(wout["rows"], key=lambda r: r["slippage"]["0"]["net"], reverse=True)
        for r in rows[:20]:
            m0 = r["slippage"]["0"]
            lines.append(
                f"| {r['kind']} | {r['value']} | {r['ema']} | {m0['n']} | {fmt_money(m0['net'])} | {m0['pf']:.2f} | {m0['calmar']:.2f} | {fmt_money(m0['maxdd'])} | {100*m0['stop_rate']:.1f}% |"
            )
        lines.append("")
    lines += ["## Cross-Window Survivors", ""]
    surv = out.get("positive_floor_and_2025", [])
    if not surv:
        lines.append("No row is positive on both floor and 2025 at baseline live-stop fills.")
    else:
        lines += ["| kind | value | ema | floor net | floor PF | floor Calmar | 2025 net | 2025 PF | 2025 Calmar |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for r in surv[:20]:
            lines.append(
                f"| {r['kind']} | {r['value']} | {r['ema']} | {fmt_money(r['floor_net'])} | {r['floor_pf']:.2f} | {r['floor_calmar']:.2f} | {fmt_money(r['oos2025_net'])} | {r['oos2025_pf']:.2f} | {r['oos2025_calmar']:.2f} |"
            )
    lines += [
        "",
        "## Verdict",
        "",
        "Do not promote from this table unless a row is positive on floor and 2025, survives at least +1 stop tick, and has non-fragile PF/Calmar. If no row survives, Calm-NKD remains rejected and Track 1 stays the candidate.",
        "",
    ]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
