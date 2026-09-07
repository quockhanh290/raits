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
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from scratch.harness import ARGV
from scratch.stress_sleeve_validation import (
    Variant,
    build_variant,
    daily_from_trades,
    split_table,
)


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


def pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return math.inf
    wins = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
    losses = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses else math.inf


def summary(name: str, tr: pd.DataFrame, account: float) -> dict:
    daily = daily_from_trades(tr)
    m = metrics(daily)
    return {
        "name": name,
        "trades": int(len(tr)),
        "net": float(tr["pnl"].sum()) if not tr.empty else 0.0,
        "pf": pf(tr),
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd_pct": float(m["maxdd"] / account * 100.0) if account else 0.0,
        "stop_rate": float((tr["exit_reason"] == "stop").mean()) if not tr.empty else 0.0,
        "target_rate": float((tr["exit_reason"] == "target").mean()) if not tr.empty else 0.0,
    }


def apply_daily_cap(
    tr: pd.DataFrame,
    account: float,
    cap: float,
    *,
    risk_mode: str,
    max_positions: int | None = None,
) -> tuple[pd.DataFrame, int]:
    if tr.empty:
        return tr, 0
    kept = []
    rejected = 0
    for _, g in tr.groupby("day"):
        work = g.copy()
        if risk_mode == "stop":
            work["risk_dollars"] = work["stop_dist"] * work["inst"].map(lambda x: BASKET[x].point_value)
        elif risk_mode == "deploy_atr":
            work["risk_dollars"] = work["daily_atr"] * 2.5 * work["inst"].map(lambda x: BASKET[x].point_value)
        else:
            raise ValueError(risk_mode)
        work = work.sort_values(["risk_dollars", "inst"], ascending=[False, True])
        used = 0.0
        taken = 0
        for _, row in work.iterrows():
            if max_positions is not None and taken >= max_positions:
                rejected += 1
                continue
            if used + float(row["risk_dollars"]) > account * cap:
                rejected += 1
                continue
            kept.append(row.drop(labels=["risk_dollars"]))
            used += float(row["risk_dollars"])
            taken += 1
    if not kept:
        return tr.iloc[0:0].copy(), rejected
    return pd.DataFrame(kept).reset_index(drop=True), rejected


def policy_trades(name: str, trades: dict[str, pd.DataFrame]) -> pd.DataFrame:
    base = trades["breadth3_mnq_mes"]
    if base.empty and name not in {"wide3", "late_cont"}:
        return base
    if name == "base":
        return base
    if name == "crash_liq_only":
        return base[base["event_subtype"] == "crash-gap/liquidation"]
    if name == "no_false_chop":
        return base[base["event_subtype"] != "false stress / chop"]
    if name == "no_bear_cont":
        return base[base["event_subtype"] != "bear-trend continuation"]
    if name == "stop_pct_le_010":
        return base[base["stop_dist_pct"] <= 0.010]
    if name == "stop_pct_le_012":
        return base[base["stop_dist_pct"] <= 0.012]
    if name == "wide3":
        return trades["wide3_mnq_mes"]
    if name == "late_cont":
        return trades["late_cont_break"]
    if name == "hybrid_crash_wide_else_late":
        wide = trades["wide3_mnq_mes"]
        late = trades["late_cont_break"]
        if wide.empty and late.empty:
            return base
        return pd.concat([
            wide[wide["event_subtype"] == "crash-gap/liquidation"],
            late[late["event_subtype"] != "crash-gap/liquidation"],
        ]).sort_values(["day", "inst"]).reset_index(drop=True)
    if name == "hybrid_crash_base_else_late":
        late = trades["late_cont_break"]
        if base.empty and late.empty:
            return base
        return pd.concat([
            base[base["event_subtype"] == "crash-gap/liquidation"],
            late[late["event_subtype"] != "crash-gap/liquidation"],
        ]).sort_values(["day", "inst"]).reset_index(drop=True)
    raise ValueError(name)


def stress_overlap_proxy(stress_tr: pd.DataFrame) -> dict:
    if stress_tr.empty:
        return {"same_day_pairs": 0, "two_inst_days": 0, "mnq_mes_opposite_risk": 0}
    day_inst = stress_tr.groupby("day")["inst"].nunique()
    return {
        "same_day_pairs": int((day_inst - 1).clip(lower=0).sum()),
        "two_inst_days": int((day_inst >= 2).sum()),
        "mnq_mes_opposite_risk": int((day_inst >= 2).sum()),
    }


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def print_summary(title: str, rows: list[dict]) -> None:
    print(f"\n=== {title} ===")
    for r in rows:
        print(
            f"{r['name']:<28} n={r['trades']:>3} net={fmt_money(r['net']):>8} "
            f"pf={r['pf']:>5.2f} sh={r['sharpe']:>5.2f} cal={r['calmar']:>5.2f} "
            f"dd={r['maxdd_pct']:>4.1f}% target={r['target_rate']:>4.1%} stop={r['stop_rate']:>4.1%}"
        )


def write_report(path: Path, results: dict, account: float) -> None:
    lines = [
        "# Stress Pass 2 - Event And Risk Gate",
        "",
        "Scratch-only follow-up. This pass tests whether Stress deserves more work after the first event validation.",
        "",
    ]
    for which, data in results.items():
        lines += [f"## {which}", ""]
        lines += ["Policy table:", ""]
        lines += ["| policy | trades | net | PF | Calmar | MaxDD% |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for r in data["rows"]:
            lines.append(f"| {r['name']} | {r['trades']} | {fmt_money(r['net'])} | {r['pf']:.2f} | {r['calmar']:.2f} | {r['maxdd_pct']:.1f}% |")
        lines += ["", "Cap table for base:", ""]
        lines += ["| risk_mode | cap | max_pos | trades | rejected | net | PF |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for r in data["caps"]:
            lines.append(f"| {r['risk_mode']} | {r['cap']:.1%} | {r['max_pos']} | {r['trades']} | {r['rejected']} | {fmt_money(r['net'])} | {r['pf']:.2f} |")
        lines += [
            "",
            "Base by event subtype:",
            "",
            table_from_df(split_table(data["base"], "event_subtype")),
            "",
            f"Same-day stress overlap proxy: {data['overlap']}",
            "",
        ]
    lines += [
        "## Verdict",
        "",
        "Stop digging broad Stress alpha. Keep exactly one hedge candidate on the board: `breadth3_mnq_mes` or the slightly more conservative `wide3_mnq_mes` if risk review prefers lower chop exposure.",
        "",
        "The follow-up did not create a stronger robust standalone Stress sleeve. Filtering to crash/liquidation improves the story but mostly restates where the edge already lives; `late_cont_break` is smoother in IS but too weak in 2025. The two-stage partial gives up too much payoff.",
        "",
        "Next action is not more parameter mining. Next action is a deploy feasibility gate: live 10:20 basket confirmation, explicit same-day Stress stop/exit ownership, same-symbol netting resolution, and final cap choice around 7.5%-10% if using deploy-style ATR risk.",
        "",
        f"Account assumption: {fmt_money(account)}.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def table_from_df(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    work = df.reset_index()
    cols = list(work.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for rec in work.to_dict("records"):
        vals = []
        for c in cols:
            v = rec[c]
            vals.append(f"{v:.2f}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--account", type=float, default=50_000.0)
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-train-end", default="2018-01-01")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--report", default="scratch/stress_event_risk_pass2_report.md")
    args = ap.parse_args()

    variants = [
        Variant("breadth3_mnq_mes"),
        Variant("wide3_mnq_mes", breadth="wide_range3"),
        Variant("late_cont_break", family="late_cont_break", rr=1.5),
    ]
    policies = [
        "base",
        "crash_liq_only",
        "no_false_chop",
        "no_bear_cont",
        "stop_pct_le_010",
        "stop_pct_le_012",
        "wide3",
        "late_cont",
        "hybrid_crash_wide_else_late",
        "hybrid_crash_base_else_late",
    ]
    all_results = {}

    for which in args.which:
        print(f"\n--- loading {which} ---", flush=True)
        argv = list(ARGV[which])
        data_dir = arg_from(argv, "--data-dir")
        start = arg_from(argv, "--start")
        end = arg_from(argv, "--end")
        regime_csv = arg_from(argv, "--regime-csv", args.regime_csv)
        hmm_fit_end = arg_from(argv, "--hmm-fit-end", args.hmm_fit_end_oos)
        dfs = {
            name: clip(load_parquet(str(Path(data_dir) / data_filename(contract))), start, end)
            for name, contract in BASKET.items()
        }
        atrs = {name: daily_atr_series(df) for name, df in dfs.items()}
        labels = label_regimes(benchmark_daily(regime_csv), args.hmm_train_end, 3, hmm_fit_end)
        costs = costs_for_basket(slippage_ticks=args.slippage_ticks)
        trades = {}
        audits = {}
        for v in variants:
            tr, audit = build_variant(dfs, labels, costs, atrs, v)
            trades[v.name] = tr
            audits[v.name] = audit
            print(f"  {v.name:<26} n={len(tr):>3} net={fmt_money(float(tr['pnl'].sum()) if not tr.empty else 0)}", flush=True)

        rows = [summary(p, policy_trades(p, trades), args.account) for p in policies]
        print_summary(which, rows)

        base = trades["breadth3_mnq_mes"]
        print(
            f"-- audit base -- outside_exit_bar={audits['breadth3_mnq_mes']['outside_exit_bar']} "
            f"signal_after_entry={audits['breadth3_mnq_mes']['signal_after_entry']} "
            f"same_bar_exit={audits['breadth3_mnq_mes']['same_bar_exit']}"
        )
        print("-- cap table base --")
        caps = []
        for risk_mode in ["stop", "deploy_atr"]:
            for cap in [0.025, 0.05, 0.075, 0.10]:
                for max_pos in [1, 2, None]:
                    capped, rejected = apply_daily_cap(base, args.account, cap, risk_mode=risk_mode, max_positions=max_pos)
                    row = summary("base", capped, args.account)
                    row.update({"risk_mode": risk_mode, "cap": cap, "max_pos": "all" if max_pos is None else max_pos, "rejected": rejected})
                    caps.append(row)
                    print(
                        f"  {risk_mode:<10} cap={cap:>5.1%} max_pos={row['max_pos']:<3} "
                        f"n={row['trades']:>3} rej={rejected:>3} net={fmt_money(row['net']):>8} pf={row['pf']:>5.2f}"
                    )
        overlap = stress_overlap_proxy(base)
        print(f"-- same-day Stress overlap proxy -- {overlap}")
        print("-- base by subtype --")
        print(split_table(base, "event_subtype"))
        all_results[which] = {"rows": rows, "caps": caps, "base": base, "overlap": overlap}

    report_path = Path(args.report)
    write_report(report_path, all_results, args.account)
    print(f"\nwrote report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
