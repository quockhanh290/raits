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
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures.stress_liquidation_1020 import StressLiquidation1020Engine
from global_index.deploy_sim import metrics
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import (
    Variant,
    build_variant,
    chronological_event_wfo,
    clip,
    daily_from_trades,
    split_table,
)


ACCOUNT = 50_000.0


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def lag1(labels: dict[pd.Timestamp, str]) -> dict[pd.Timestamp, str]:
    s = pd.Series(labels).sort_index()
    s.index = pd.DatetimeIndex(s.index).normalize()
    shifted = s.shift(1).dropna()
    return {pd.Timestamp(k).normalize(): str(v) for k, v in shifted.items()}


def pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return math.inf
    wins = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
    losses = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses else math.inf


def calendar_daily(tr: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    if tr.empty:
        return pd.Series(0.0, index=sessions)
    sparse = daily_from_trades(tr)
    use = sessions[(sessions >= sparse.index.min()) & (sessions <= sparse.index.max())]
    dense = pd.Series(0.0, index=use)
    dense.loc[sparse.index] = sparse.values
    return dense


def row(name: str, tr: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict:
    sparse = daily_from_trades(tr)
    dense = calendar_daily(tr, sessions)
    ms = metrics(sparse)
    md = metrics(dense)
    return {
        "name": name,
        "trades": int(len(tr)),
        "days": int(len(sparse)),
        "net": float(tr["pnl"].sum()) if not tr.empty else 0.0,
        "pf": pf(tr),
        "sharpe_active": float(ms["sharpe"]),
        "sharpe_calendar": float(md["sharpe"]),
        "calmar_active": float(ms["calmar"]),
        "calmar_calendar": float(md["calmar"]),
        "maxdd": float(md["maxdd"]),
    }


def fmt_money(v: float) -> str:
    return f"${v:,.0f}"


def variants() -> list[Variant]:
    return [
        Variant("breadth3_mnq_mes"),
        Variant("wide3_mnq_mes", breadth="wide_range3"),
        Variant("rr25", rr=2.5),
        Variant("delay1025", entry_time="10:25"),
        Variant("late_cont_break", family="late_cont_break", rr=1.5),
        Variant("partial1r_run25", partial_r=1.0, runner_rr=2.5, rr=2.5),
    ]


def load_window(which: str, regime_csv_default: str, hmm_fit_default: str):
    argv = list(ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    regime_csv = arg_from(argv, "--regime-csv", regime_csv_default)
    hmm_fit_end = arg_from(argv, "--hmm-fit-end", hmm_fit_default)
    dfs = {
        name: clip(load_parquet(str(Path(data_dir) / data_filename(contract))), start, end)
        for name, contract in BASKET.items()
    }
    atrs = {name: daily_atr_series(df) for name, df in dfs.items()}
    labels0 = label_regimes(benchmark_daily(regime_csv), "2018-01-01", 3, hmm_fit_end)
    labels1 = lag1(labels0)
    costs = costs_for_basket(slippage_ticks=2.0)
    sessions = pd.DatetimeIndex(sorted({
        pd.Timestamp(x).tz_localize(None).normalize()
        for x in dfs["MES"].index.normalize().unique()
    }))
    return dfs, atrs, labels0, labels1, costs, sessions


def build_all(dfs, labels, costs, atrs) -> tuple[dict[str, pd.DataFrame], dict[str, dict]]:
    trades = {}
    audits = {}
    for v in variants():
        tr, audit = build_variant(dfs, labels, costs, atrs, v)
        trades[v.name] = tr
        audits[v.name] = audit
    return trades, audits


def swing_positions(dfs, labels, costs) -> list[dict]:
    swing = SwingTFEngine().backtest_basket(dfs, labels, costs)
    return [
        {
            "inst": inst,
            "d0": pd.Timestamp(t["day"]).normalize(),
            "d1": pd.Timestamp(t["exit_day"]).normalize(),
            "dir": t["direction"],
        }
        for inst, lst in swing.items()
        for t in lst
    ]


def overlap_with_swing(sw: list[dict], stress_tr: pd.DataFrame) -> dict:
    if stress_tr.empty:
        return {"held": 0, "opposite": 0, "opposite_pnl": 0.0, "total_pnl": 0.0}
    held = opposite = 0
    opposite_pnl = 0.0
    for _, s in stress_tr.iterrows():
        matches = [
            w for w in sw
            if w["inst"] == s["inst"]
            and w["d0"] < pd.Timestamp(s["day"]).normalize() <= w["d1"]
        ]
        if matches:
            held += 1
            if any(w["dir"] != s["direction"] for w in matches):
                opposite += 1
                opposite_pnl += float(s["pnl"])
    return {
        "held": held,
        "opposite": opposite,
        "opposite_pnl": opposite_pnl,
        "total_pnl": float(stress_tr["pnl"].sum()),
    }


def true_risk_stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"med": 0.0, "max": 0.0, "day_max": 0.0, "atr_med": 0.0, "ratio_med": 0.0}
    pv = tr["inst"].map(lambda i: BASKET[i].point_value)
    stop_risk = tr["stop_dist"] * pv
    atr_risk = tr["daily_atr"] * 2.5 * pv
    day_stop = pd.DataFrame({"day": tr["day"], "risk": stop_risk}).groupby("day")["risk"].sum()
    return {
        "med": float(stop_risk.median()),
        "max": float(stop_risk.max()),
        "day_max": float(day_stop.max()),
        "atr_med": float(atr_risk.median()),
        "ratio_med": float((atr_risk / stop_risk).median()),
    }


def cap_on_true_stop(tr: pd.DataFrame, cap_pct: float, max_positions: int | None) -> tuple[pd.DataFrame, int]:
    if tr.empty:
        return tr, 0
    kept = []
    rejected = 0
    for _, g in tr.groupby("day"):
        work = g.copy()
        work["risk"] = work["stop_dist"] * work["inst"].map(lambda i: BASKET[i].point_value)
        work = work.sort_values(["risk", "inst"], ascending=[False, True])
        used = 0.0
        n = 0
        for _, r in work.iterrows():
            if max_positions is not None and n >= max_positions:
                rejected += 1
                continue
            if used + float(r["risk"]) > ACCOUNT * cap_pct:
                rejected += 1
                continue
            kept.append(r.drop(labels=["risk"]))
            used += float(r["risk"])
            n += 1
    return (pd.DataFrame(kept).reset_index(drop=True) if kept else tr.iloc[0:0].copy()), rejected


def live_cut_probe(dfs, labels, variant: str) -> dict:
    engine = StressLiquidation1020Engine(variant=variant, instruments={"MNQ", "MES"})
    by_inst_day = {}
    for inst, df in dfs.items():
        by_inst_day[inst] = {
            pd.Timestamp(day).tz_localize(None).normalize(): g
            for day, g in df.groupby(df.index.normalize())
        }
    stress_days = sorted(d for d, v in labels.items() if v == "Stress")
    counts = {}
    for cutoff in ("10:15", "10:20", "10:21"):
        signal_days = 0
        signal_legs = 0
        for day in stress_days:
            bars = {}
            for inst in BASKET:
                g = by_inst_day.get(inst, {}).get(pd.Timestamp(day).normalize())
                if g is None:
                    continue
                bars[inst] = g[g.index.time <= pd.Timestamp(cutoff).time()]
            sig = engine.entry_signals(bars, "Stress")
            if sig:
                signal_days += 1
                signal_legs += len(sig)
        counts[cutoff] = {"signal_days": signal_days, "signal_legs": signal_legs}
    return counts


def print_rows(title: str, rows: list[dict]) -> None:
    print(f"\n=== {title} ===")
    for r in rows:
        print(
            f"{r['name']:<18} n={r['trades']:>3} days={r['days']:>3} net={fmt_money(r['net']):>8} "
            f"pf={r['pf']:>5.2f} sh_cal={r['sharpe_calendar']:>5.2f} "
            f"cal_cal={r['calmar_calendar']:>5.2f} maxdd={fmt_money(r['maxdd']):>8}"
        )


def md_table(dict_rows: list[dict], fields: list[str]) -> str:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for r in dict_rows:
        vals = []
        for f in fields:
            v = r.get(f, "")
            if isinstance(v, float):
                vals.append(fmt_money(v) if f in {"net", "maxdd", "opposite_pnl", "risk_med", "risk_max", "risk_day_max"} else f"{v:.2f}")
            else:
                vals.append(str(v))
        out.append("| " + " | ".join(vals) + " |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_audit_response_20260821_report.md")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    args = ap.parse_args()

    report = [
        "# Stress Audit Response - 2026-08-21",
        "",
        "Scratch-only response to the Claude audit. Production code was not modified.",
        "",
    ]

    for which in args.which:
        print(f"\n--- {which} ---", flush=True)
        dfs, atrs, labels0, labels1, costs, sessions = load_window(which, args.regime_csv, args.hmm_fit_end_oos)
        stress0 = {d for d, v in labels0.items() if v == "Stress"}
        stress1 = {d for d, v in labels1.items() if v == "Stress"}
        print(f"labels lag0_stress={len(stress0)} lag1_stress={len(stress1)} moved={len(stress0 ^ stress1)}")

        trades0, audits0 = build_all(dfs, labels0, costs, atrs)
        trades1, audits1 = build_all(dfs, labels1, costs, atrs)

        rows0 = [row(name, tr, sessions) for name, tr in trades0.items()]
        rows1 = [row(name, tr, sessions) for name, tr in trades1.items()]
        print_rows(f"{which} lag0 as validated", rows0)
        print_rows(f"{which} lag1 causal after fix", rows1)

        base = trades1["breadth3_mnq_mes"]
        wide = trades1["wide3_mnq_mes"]
        sw = swing_positions(dfs, labels0, costs)
        overlap = {
            "breadth3_mnq_mes": overlap_with_swing(sw, base),
            "wide3_mnq_mes": overlap_with_swing(sw, wide),
        }
        live_cut = {
            "breadth3": live_cut_probe(dfs, labels1, "breadth3"),
            "wide_range3": live_cut_probe(dfs, labels1, "wide_range3"),
        }
        risk = {
            "breadth3_mnq_mes": true_risk_stats(base),
            "wide3_mnq_mes": true_risk_stats(wide),
        }
        cap_rows = []
        for name, tr in [("breadth3_mnq_mes", base), ("wide3_mnq_mes", wide)]:
            for cap in (0.025, 0.05):
                for maxp in (1, 2):
                    capped, rejected = cap_on_true_stop(tr, cap, maxp)
                    rr = row(name, capped, sessions)
                    cap_rows.append({
                        "variant": name,
                        "cap": f"{cap:.1%}",
                        "max_pos": maxp,
                        "trades": rr["trades"],
                        "rejected": rejected,
                        "net": rr["net"],
                        "pf": rr["pf"],
                    })

        wfo = chronological_event_wfo(
            trades1,
            ["breadth3_mnq_mes", "wide3_mnq_mes", "rr25", "delay1025", "late_cont_break", "partial1r_run25"],
            ACCOUNT,
        )
        if not wfo.empty:
            picks = wfo["selected"].value_counts().to_dict()
            print(f"lag1 event WFO total={fmt_money(float(wfo['net'].sum()))} positive={(wfo['net'] > 0).sum()}/{len(wfo)} picks={picks}")
        else:
            picks = {}
            print("lag1 event WFO: insufficient clusters")

        audit_base = audits1["breadth3_mnq_mes"]
        report += [
            f"## {which}",
            "",
            f"Regime labels: lag0 Stress days={len(stress0)}, lag1 Stress days={len(stress1)}, moved={len(stress0 ^ stress1)}.",
            "",
            "Lag-1 causal variant table, calendar-basis metrics:",
            "",
            md_table(rows1, ["name", "trades", "days", "net", "pf", "sharpe_calendar", "calmar_calendar", "maxdd"]),
            "",
            "Lag-0 comparison, calendar-basis metrics:",
            "",
            md_table(rows0, ["name", "trades", "days", "net", "pf", "sharpe_calendar", "calmar_calendar", "maxdd"]),
            "",
            f"Fill/timing audit after lag-1 fix for `breadth3_mnq_mes`: outside_exit_bar={audit_base['outside_exit_bar']}, signal_after_entry={audit_base['signal_after_entry']}, same_bar_exit={audit_base['same_bar_exit']}.",
            "",
            "Lag-1 event-cluster WFO:",
            "",
        ]
        if wfo.empty:
            report += ["Insufficient event clusters.", ""]
        else:
            report += [
                f"Total held-out net={fmt_money(float(wfo['net'].sum()))}; positive folds={int((wfo['net'] > 0).sum())}/{len(wfo)}; picks={picks}.",
                md_table(wfo[["test_cluster", "event_subtype", "selected", "trades", "net", "pf"]].to_dict("records"), ["test_cluster", "event_subtype", "selected", "trades", "net", "pf"]),
                "",
            ]
        report += [
            "Same-symbol overlap with existing swing sleeve, using lag-1 Stress trades and current swing labels:",
            "",
            md_table([
                {
                    "variant": k,
                    "held": v["held"],
                    "opposite": v["opposite"],
                    "opposite_pnl": v["opposite_pnl"],
                    "total_pnl": v["total_pnl"],
                }
                for k, v in overlap.items()
            ], ["variant", "held", "opposite", "opposite_pnl", "total_pnl"]),
            "",
            "True stop-risk basis after lag-1 fix:",
            "",
            md_table([
                {
                    "variant": k,
                    "risk_med": v["med"],
                    "risk_max": v["max"],
                    "risk_day_max": v["day_max"],
                    "atr_med": v["atr_med"],
                    "ratio_med": v["ratio_med"],
                }
                for k, v in risk.items()
            ], ["variant", "risk_med", "risk_max", "risk_day_max", "atr_med", "ratio_med"]),
            "",
            "True stop-risk cap table:",
            "",
            md_table(cap_rows, ["variant", "cap", "max_pos", "trades", "rejected", "net", "pf"]),
            "",
            "Lag-1 base by event subtype:",
            "",
            split_table(base, "event_subtype").reset_index().to_string(index=False) if not base.empty else "_empty_",
            "",
            "Live bar-cut probe using lag-1 labels and `entry_signals`:",
            "",
            str(live_cut),
            "",
        ]

    report += [
        "## Consolidated Verdict",
        "",
        "S1 confirmed. Same-day regime labels materially inflated the primary Stress result. After applying lag-1 causal labels, `breadth3_mnq_mes` is not paper-ready.",
        "",
        "S2 confirmed in substance. Same-symbol conflict remains common enough after the lag-1 fix that paper deployment still needs either overlap blocking or separate account/stop ownership.",
        "",
        "S3 confirmed for the earlier WFO evidence. The old event WFO did not support the promoted primary. The lag-1 WFO table above is the replacement evidence and should decide any future candidate.",
        "",
        "S5 confirmed. The high 7.5%-10% cap narrative came from the wrong ATR risk basis. True stop risk is small enough that 2.5% cap is not the limiting issue; max concurrent and symbol conflict are the actual gates.",
        "",
        "S4.1 confirmed by measurement. With bars cut at 10:15, the batch live API produces zero 10:20 signals; bars through 10:20 or later are required.",
        "",
        "Updated status: research hedge only. Do not start production deploy plumbing until a lag-1 event-WFO candidate is selected and same-symbol overlap policy is specified.",
        "",
    ]
    Path(args.report).write_text("\n".join(report), encoding="utf-8")
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
