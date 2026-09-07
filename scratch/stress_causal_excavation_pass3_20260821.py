from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index.deploy_sim import metrics
from scratch.stress_audit_response_20260821 import (
    ACCOUNT,
    calendar_daily,
    fmt_money,
    lag1,
    load_window,
    md_table,
    row,
)
from scratch.stress_sleeve_validation import (
    Variant,
    build_variant,
    chronological_event_wfo,
    daily_from_trades,
    split_table,
)


def pf(tr: pd.DataFrame) -> float:
    if tr.empty:
        return math.inf
    wins = float(tr.loc[tr["pnl"] > 0, "pnl"].sum())
    losses = float(-tr.loc[tr["pnl"] < 0, "pnl"].sum())
    return wins / losses if losses else math.inf


def base_specs() -> list[Variant]:
    return [
        Variant("breadth3_mnq_mes"),
        Variant("wide3_mnq_mes", breadth="wide_range3"),
        Variant("mnq_only", instruments=("MNQ",)),
        Variant("mes_only", instruments=("MES",)),
        Variant("rr15", rr=1.5),
        Variant("rr25", rr=2.5),
        Variant("exit1200", end_time="12:00"),
        Variant("exit1555", end_time="15:55"),
        Variant("delay1025", entry_time="10:25"),
        Variant("late_cont_break", family="late_cont_break", rr=1.5),
        Variant("partial1r_run25", partial_r=1.0, runner_rr=2.5, rr=2.5),
    ]


def named_filter(name: str):
    if name == "crash_only":
        return lambda tr: tr["event_subtype"].eq("crash-gap/liquidation")
    if name == "no_bear":
        return lambda tr: tr["event_subtype"].ne("bear-trend continuation")
    if name == "below4":
        return lambda tr: tr["below_count"].ge(4)
    if name == "wide4":
        return lambda tr: tr["wide_count"].ge(4)
    if name == "range_ge_100bp":
        return lambda tr: tr["avg_range_pct"].ge(0.010)
    if name == "range_ge_125bp":
        return lambda tr: tr["avg_range_pct"].ge(0.0125)
    if name == "stop_le_75bp":
        return lambda tr: tr["stop_dist_pct"].le(0.0075)
    if name == "stop_le_100bp":
        return lambda tr: tr["stop_dist_pct"].le(0.0100)
    if name == "stop_le_125bp":
        return lambda tr: tr["stop_dist_pct"].le(0.0125)
    raise ValueError(name)


def make_candidates(raw: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {k: v.copy() for k, v in raw.items()}

    filters = [
        "crash_only",
        "no_bear",
        "below4",
        "wide4",
        "range_ge_100bp",
        "range_ge_125bp",
        "stop_le_75bp",
        "stop_le_100bp",
        "stop_le_125bp",
    ]
    seed_names = [
        "breadth3_mnq_mes",
        "wide3_mnq_mes",
        "mnq_only",
        "rr15",
        "rr25",
        "delay1025",
        "exit1200",
        "exit1555",
    ]
    for seed in seed_names:
        tr = raw.get(seed)
        if tr is None or tr.empty:
            continue
        for fname in filters:
            mask = named_filter(fname)(tr)
            out[f"{seed}__{fname}"] = tr.loc[mask].copy().reset_index(drop=True)
    return out


def concentration_gate(folds: pd.DataFrame) -> dict:
    if folds.empty:
        return {
            "total": 0.0,
            "best": 0.0,
            "without_best": 0.0,
            "best_share": math.inf,
            "final4": 0.0,
            "positive": 0,
            "folds": 0,
            "pass": False,
        }
    nets = folds["net"].astype(float)
    total = float(nets.sum())
    best = float(nets.max())
    without = total - best
    best_share = best / total if total > 0 else math.inf
    final4 = float(nets.tail(4).sum())
    ok = total > 0 and without > 0 and best_share <= 0.50 and final4 >= 0
    return {
        "total": total,
        "best": best,
        "without_best": without,
        "best_share": best_share,
        "final4": final4,
        "positive": int((nets > 0).sum()),
        "folds": int(len(folds)),
        "pass": bool(ok),
    }


def summarize_candidates(candidates: dict[str, pd.DataFrame], sessions: pd.DatetimeIndex, top_n: int = 30) -> pd.DataFrame:
    rows = []
    for name, tr in candidates.items():
        r = row(name, tr, sessions)
        r["target_rate"] = float((tr["exit_reason"] == "target").mean()) if not tr.empty else 0.0
        r["stop_rate"] = float((tr["exit_reason"] == "stop").mean()) if not tr.empty else 0.0
        r["clusters"] = int(tr["event_cluster"].nunique()) if not tr.empty and "event_cluster" in tr else 0
        rows.append(r)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["score"] = df["net"] - 0.25 * df["maxdd"]
    return df.sort_values(["net", "pf", "trades"], ascending=[False, False, False]).head(top_n)


def bootstrap_by_event(tr: pd.DataFrame, n_iter: int = 5000, seed: int = 42) -> dict:
    if tr.empty or "event_cluster" not in tr:
        return {"p_pos": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0, "events": 0}
    vals = tr.groupby("event_cluster")["pnl"].sum().astype(float).to_numpy()
    if len(vals) == 0:
        return {"p_pos": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0, "events": 0}
    rng = np.random.default_rng(seed)
    draws = rng.choice(vals, size=(n_iter, len(vals)), replace=True).sum(axis=1)
    return {
        "p_pos": float((draws > 0).mean()),
        "p5": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
        "events": int(len(vals)),
    }


def fold_table_md(folds: pd.DataFrame) -> str:
    if folds.empty:
        return "_insufficient folds_"
    cols = ["test_cluster", "event_subtype", "selected", "trades", "net", "pf"]
    return md_table(folds[cols].to_dict("records"), cols)


def run_window(which: str, regime_csv: str, hmm_fit_oos: str) -> dict:
    dfs, atrs, labels0, labels1, costs, sessions = load_window(which, regime_csv, hmm_fit_oos)
    raw = {}
    audits = {}
    for spec in base_specs():
        tr, audit = build_variant(dfs, labels1, costs, atrs, spec)
        raw[spec.name] = tr
        audits[spec.name] = audit
    candidates = make_candidates(raw)
    top = summarize_candidates(candidates, sessions, top_n=40)

    candidate_names = sorted(candidates)
    folds = chronological_event_wfo(candidates, candidate_names, ACCOUNT)
    gate = concentration_gate(folds)

    # Also test a restricted family that avoids pure post-hoc filters on many variants.
    predeclared = [
        "breadth3_mnq_mes",
        "wide3_mnq_mes",
        "mnq_only",
        "breadth3_mnq_mes__crash_only",
        "wide3_mnq_mes__crash_only",
        "mnq_only__crash_only",
        "breadth3_mnq_mes__stop_le_100bp",
        "wide3_mnq_mes__stop_le_100bp",
        "delay1025",
        "late_cont_break",
    ]
    predeclared = [x for x in predeclared if x in candidates]
    folds_pre = chronological_event_wfo(candidates, predeclared, ACCOUNT)
    gate_pre = concentration_gate(folds_pre)

    return {
        "which": which,
        "sessions": sessions,
        "raw": raw,
        "candidates": candidates,
        "top": top,
        "folds": folds,
        "gate": gate,
        "folds_pre": folds_pre,
        "gate_pre": gate_pre,
        "audits": audits,
    }


def report_window(r: dict) -> list[str]:
    lines = [f"## {r['which']}", ""]
    top = r["top"].copy()
    show = top[["name", "trades", "days", "clusters", "net", "pf", "sharpe_calendar", "calmar_calendar", "maxdd", "target_rate", "stop_rate"]]
    lines += [
        "Top causal lag-1 candidates by standalone net:",
        "",
        md_table(show.to_dict("records"), list(show.columns)),
        "",
        "Full candidate-set chronological event WFO:",
        "",
        fold_table_md(r["folds"]),
        "",
        "Full candidate-set concentration gate:",
        "",
        md_table([r["gate"]], ["total", "best", "without_best", "best_share", "final4", "positive", "folds", "pass"]),
        "",
        "Restricted predeclared-family chronological event WFO:",
        "",
        fold_table_md(r["folds_pre"]),
        "",
        "Restricted-family concentration gate:",
        "",
        md_table([r["gate_pre"]], ["total", "best", "without_best", "best_share", "final4", "positive", "folds", "pass"]),
        "",
    ]
    for name in ["breadth3_mnq_mes", "wide3_mnq_mes", "mnq_only", "breadth3_mnq_mes__crash_only", "wide3_mnq_mes__crash_only"]:
        tr = r["candidates"].get(name)
        if tr is None:
            continue
        bs = bootstrap_by_event(tr)
        lines += [
            f"Bootstrap by event cluster for `{name}`:",
            "",
            md_table([{"candidate": name, **bs}], ["candidate", "events", "p_pos", "p5", "p50", "p95"]),
            "",
            f"By subtype for `{name}`:",
            "",
            split_table(tr, "event_subtype").reset_index().to_string(index=False) if not tr.empty else "_empty_",
            "",
        ]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--report", default="scratch/stress_causal_excavation_pass3_20260821_report.md")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-fit-end-oos", default="2024-12-31")
    args = ap.parse_args()

    report = [
        "# Stress Causal Excavation Pass 3 - 2026-08-21",
        "",
        "Scope: scratch-only. Production code was not modified.",
        "",
        "This pass intentionally does not tune on lag-0 Stress labels. All candidates",
        "use lag-1 regime labels and only features available at or before the tested entry.",
        "",
        "Acceptance gate, declared before reading this pass:",
        "",
        "- held-out event-WFO total must stay positive after removing the single best cluster;",
        "- no single cluster may contribute more than 50% of held-out net;",
        "- final four folds must not be negative after selection converges;",
        "- promoted primary must be selected by its own folds, not by another strategy family.",
        "",
    ]

    results = []
    for which in args.which:
        print(f"\n=== {which} ===", flush=True)
        r = run_window(which, args.regime_csv, args.hmm_fit_end_oos)
        results.append(r)
        top = r["top"].head(12)
        for _, x in top.iterrows():
            print(
                f"{x['name']:<38} n={int(x['trades']):>3} clusters={int(x['clusters']):>2} "
                f"net={fmt_money(float(x['net'])):>8} pf={float(x['pf']):>5.2f} "
                f"cal={float(x['calmar_calendar']):>5.2f} maxdd={fmt_money(float(x['maxdd'])):>8}"
            )
        g = r["gate_pre"]
        print(
            "restricted WFO "
            f"total={fmt_money(g['total'])} without_best={fmt_money(g['without_best'])} "
            f"best_share={g['best_share']:.2f} final4={fmt_money(g['final4'])} pass={g['pass']}"
        )
        report += report_window(r)

    floor = next((r for r in results if r["which"] == "floor"), results[0])
    report += [
        "## Consolidated Verdict",
        "",
    ]
    if floor["gate_pre"]["pass"]:
        report += [
            "The restricted causal family passes the predeclared floor event-WFO concentration gate.",
            "This would justify a follow-up holdout-only verification before any operational work.",
        ]
    else:
        report += [
            "No deploy-level Stress candidate was found. The restricted causal family fails the",
            "predeclared floor event-WFO concentration gate, so any attractive standalone row should",
            "be treated as event-cluster mining rather than a robust hedge candidate.",
        ]
    report += [
        "",
        "Stress remains research-only unless a future pass with a predeclared intraday Stress detector",
        "passes the event-WFO concentration gate and solves same-symbol position ownership.",
        "",
    ]

    Path(args.report).write_text("\n".join(report), encoding="utf-8")
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
