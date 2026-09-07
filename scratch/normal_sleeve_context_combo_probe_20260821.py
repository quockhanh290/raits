"""
Normal sleeve context combo probe - scratch/research only.

Combines the two best Normal context clues found so far:
  - R4 prior-day futures range cap (p90 derived on floor).
  - R4 time-slot relative-volume filters.

Replays both current cap and strict 2.5% cap. No production code is changed.
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

from scratch.normal_sleeve_gap_spy_context_probe_20260821 import load_book_with_context, load_spy
from scratch.normal_sleeve_position_sizing_policy_20260821 import replay
from scratch.normal_sleeve_volume_filter_probe_20260821 import attach_book, load_frames, volume_contexts
from scratch.normal_sleeve_risk_policy_probe_20260821 import R4, build_meta, load_trade_json


OUT = Path("scratch/normal_sleeve_context_combo_probe_20260821.txt")
JSON_OUT = Path("scratch/normal_sleeve_context_combo_probe_20260821.json")


def finite(x) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def book_with_all_context(which: str, spy: pd.DataFrame) -> list[dict]:
    # Start from the gap/SPY context book, then attach volume features by matching
    # instrument + entry day + direction + PnL. This avoids touching production paths.
    base = load_book_with_context(which, spy)
    raw = load_trade_json(which)
    vol_book = attach_book(raw, build_meta(raw), volume_contexts(load_frames(raw)))
    buckets = {}
    for t in vol_book:
        key = (
            t["inst"],
            pd.Timestamp(t["entry"]).normalize(),
            t["direction"],
            round(float(t["pnl_sized"]), 8),
        )
        buckets.setdefault(key, []).append(t)
    for t in base:
        key = (
            t["inst"],
            pd.Timestamp(t["entry"]).normalize(),
            t["direction"],
            round(float(t["pnl_sized"]), 8),
        )
        srcs = buckets.get(key) or []
        src = srcs.pop(0) if srcs else {}
        t["rvol_slot20"] = src.get("rvol_slot20", np.nan)
        t["rvol_prev10"] = src.get("rvol_prev10", np.nan)
    return base


def derive_thresholds(floor_book: list[dict]) -> dict:
    vals = [finite(t.get("prev_range_pct")) for t in floor_book if t["cluster"] == "roska4_swing"]
    vals = [x for x in vals if np.isfinite(x)]
    return {
        "r4_prev_range_p90": float(np.quantile(vals, 0.90)),
        "r4_prev_range_p80": float(np.quantile(vals, 0.80)),
    }


def is_r4(t: dict) -> bool:
    return t["cluster"] == "roska4_swing"


def pass_rule(t: dict, rule: str, th: dict) -> bool:
    if rule == "none":
        return True
    if not is_r4(t):
        return True
    prev_range = finite(t.get("prev_range_pct"))
    rvol = finite(t.get("rvol_slot20"))
    checks = {
        "range_p90": lambda: np.isfinite(prev_range) and prev_range <= th["r4_prev_range_p90"],
        "range_p80": lambda: np.isfinite(prev_range) and prev_range <= th["r4_prev_range_p80"],
        "vol_06_2": lambda: np.isfinite(rvol) and 0.6 <= rvol <= 2.0,
        "vol_le_2": lambda: np.isfinite(rvol) and rvol <= 2.0,
    }
    if rule in checks:
        return checks[rule]()
    if rule == "range_p90__vol_06_2":
        return checks["range_p90"]() and checks["vol_06_2"]()
    if rule == "range_p90__vol_le_2":
        return checks["range_p90"]() and checks["vol_le_2"]()
    if rule == "range_p80__vol_06_2":
        return checks["range_p80"]() and checks["vol_06_2"]()
    if rule == "range_p80__vol_le_2":
        return checks["range_p80"]() and checks["vol_le_2"]()
    raise ValueError(rule)


def run_policy(book: list[dict], *, rule: str, th: dict, cap: str) -> dict:
    kept = [t for t in book if pass_rule(t, rule, th)]
    skipped = [t for t in book if not pass_rule(t, rule, th)]
    if cap == "current":
        r = replay(kept, swing_gross=0.050, swing_net=0.044, nkd_cap=0.060, breaker=0.15, release="latch")
    elif cap == "strict025":
        r = replay(kept, swing_gross=0.025, swing_net=0.025, nkd_cap=0.060, breaker=0.15, release="latch")
    else:
        raise ValueError(cap)
    return {
        "rule": rule,
        "cap": cap,
        "kept": len(kept),
        "skipped": len(skipped),
        "skipped_pnl": float(sum(t["pnl_sized"] for t in skipped)),
        "net": r["net"],
        "pf": r["pf"],
        "sharpe": r["sharpe"],
        "calmar": r["calmar"],
        "maxdd_pct": r["maxdd_pct"],
        "halted": r["halted_days"],
        "blocked": r["blocked_trades"],
        "safety_margin_15": r["safety_margin_15"],
        "taken": r["taken"],
        "rejected": r["rejected"],
    }


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def main() -> int:
    report = []

    def emit(s: str = ""):
        print(s, flush=True)
        report.append(s)

    spy = load_spy()
    books = {w: book_with_all_context(w, spy) for w in ("floor", "vault2025", "vault2026")}
    th = derive_thresholds(books["floor"])
    rules = [
        "none",
        "range_p90",
        "range_p80",
        "vol_06_2",
        "vol_le_2",
        "range_p90__vol_06_2",
        "range_p90__vol_le_2",
        "range_p80__vol_06_2",
        "range_p80__vol_le_2",
    ]
    results = {}
    for which, book in books.items():
        rows = []
        for rule in rules:
            for cap in ("current", "strict025"):
                rows.append(dict(which=which, **run_policy(book, rule=rule, th=th, cap=cap)))
        results[which] = rows
        emit("#" * 118)
        emit(f"WINDOW: {which}")
        emit("#" * 118)
        emit("  {:<24} {:<9} {:>5} {:>6} {:>10} {:>5} {:>7} {:>7} {:>8} {:>7} {:>6}".format(
            "rule", "cap", "kept", "skip", "net$", "PF", "Sharpe", "Calmar", "MaxDD%", "block", "rej"))
        for r in sorted(rows, key=lambda x: (x["cap"], x["calmar"], x["net"]), reverse=True):
            emit("  {:<24} {:<9} {:>5} {:>6} {:>10,.0f} {:>5} {:>7.2f} {:>7.2f} {:>8.1%} {:>7} {:>6}".format(
                r["rule"], r["cap"], r["kept"], r["skipped"], r["net"], fmt_pf(r["pf"]),
                r["sharpe"], r["calmar"], r["maxdd_pct"], r["blocked"], r["rejected"]))
        emit("")

    emit("=" * 118)
    emit("CROSS-WINDOW SUMMARY")
    emit("=" * 118)
    by = {(w, r["rule"], r["cap"]): r for w, rows in results.items() for r in rows}
    emit("  {:<24} {:<9} {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7}".format(
        "rule", "cap", "floor$", "PF", "Calmar", "2025$", "PF", "Calmar", "2026$", "PF", "Calmar"))
    for rule in rules:
        for cap in ("current", "strict025"):
            f = by[("floor", rule, cap)]
            y25 = by[("vault2025", rule, cap)]
            y26 = by[("vault2026", rule, cap)]
            emit("  {:<24} {:<9} {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f}".format(
                rule, cap, f["net"], fmt_pf(f["pf"]), f["calmar"],
                y25["net"], fmt_pf(y25["pf"]), y25["calmar"],
                y26["net"], fmt_pf(y26["pf"]), y26["calmar"]))

    JSON_OUT.write_text(json.dumps({"thresholds": th, "results": results}, indent=2), encoding="utf-8")
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
