"""
Normal sleeve R4/NKD split probe - scratch/research only.

Separates the current best Normal context candidate into:
  - R4 filtered only
  - NKD only
  - R4 filtered + NKD

The R4 filter is range_p90__vol_le_2:
  - prior-day futures RTH range <= floor-derived R4 p90
  - entry bar relative volume <= 2.0x same time-slot median20

No production code is changed.
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

from scratch.normal_sleeve_context_combo_probe_20260821 import (
    book_with_all_context,
    derive_thresholds,
    pass_rule,
)
from scratch.normal_sleeve_gap_spy_context_probe_20260821 import load_spy
from scratch.normal_sleeve_position_sizing_policy_20260821 import replay


OUT = Path("scratch/normal_sleeve_r4_nkd_split_probe_20260821.txt")
JSON_OUT = Path("scratch/normal_sleeve_r4_nkd_split_probe_20260821.json")
RULE = "range_p90__vol_le_2"


def is_r4(t: dict) -> bool:
    return t["cluster"] == "roska4_swing"


def is_nkd(t: dict) -> bool:
    return t["cluster"] == "global_nkd"


def filtered_r4(book: list[dict], th: dict) -> list[dict]:
    return [t for t in book if is_r4(t) and pass_rule(t, RULE, th)]


def nkd_only(book: list[dict]) -> list[dict]:
    return [t for t in book if is_nkd(t)]


def run(book: list[dict], cap: str) -> dict:
    if cap == "current":
        return replay(book, swing_gross=0.050, swing_net=0.044, nkd_cap=0.060, breaker=0.15, release="latch")
    if cap == "strict025":
        return replay(book, swing_gross=0.025, swing_net=0.025, nkd_cap=0.060, breaker=0.15, release="latch")
    raise ValueError(cap)


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def yearly(book: list[dict]) -> dict[int, float]:
    out = {}
    for t in book:
        y = int(pd.Timestamp(t["exit"]).year)
        out[y] = out.get(y, 0.0) + float(t["pnl_sized"])
    return out


def main() -> int:
    report = []

    def emit(s: str = ""):
        print(s, flush=True)
        report.append(s)

    spy = load_spy()
    books = {w: book_with_all_context(w, spy) for w in ("floor", "vault2025", "vault2026")}
    th = derive_thresholds(books["floor"])
    results = {}

    for which, book in books.items():
        r4f = filtered_r4(book, th)
        nkd = nkd_only(book)
        variants = {
            "R4 filtered only": r4f,
            "NKD only": nkd,
            "R4 filtered + NKD": r4f + nkd,
            "R4 raw only": [t for t in book if is_r4(t)],
            "R4 raw + NKD": book,
        }
        rows = []
        for name, vbook in variants.items():
            for cap in ("current", "strict025"):
                if name == "NKD only" and cap == "strict025":
                    continue
                r = run(vbook, cap)
                rows.append(dict(
                    which=which,
                    variant=name,
                    cap=cap,
                    trades=len(vbook),
                    net=r["net"],
                    pf=r["pf"],
                    sharpe=r["sharpe"],
                    calmar=r["calmar"],
                    maxdd_pct=r["maxdd_pct"],
                    halted=r["halted_days"],
                    blocked=r["blocked_trades"],
                    taken=r["taken"],
                    rejected=r["rejected"],
                    yearly=yearly(vbook),
                ))
        results[which] = rows
        emit("#" * 118)
        emit(f"WINDOW: {which}")
        emit("#" * 118)
        emit("  {:<20} {:<9} {:>6} {:>10} {:>5} {:>7} {:>7} {:>8} {:>7} {:>6}".format(
            "variant", "cap", "trades", "net$", "PF", "Sharpe", "Calmar", "MaxDD%", "block", "rej"))
        for r in rows:
            emit("  {:<20} {:<9} {:>6} {:>10,.0f} {:>5} {:>7.2f} {:>7.2f} {:>8.1%} {:>7} {:>6}".format(
                r["variant"], r["cap"], r["trades"], r["net"], fmt_pf(r["pf"]), r["sharpe"],
                r["calmar"], r["maxdd_pct"], r["blocked"], r["rejected"]))
        emit("")

    emit("=" * 118)
    emit("CROSS-WINDOW SUMMARY")
    emit("=" * 118)
    keys = [
        ("R4 filtered only", "current"),
        ("NKD only", "current"),
        ("R4 filtered + NKD", "current"),
        ("R4 filtered only", "strict025"),
        ("R4 filtered + NKD", "strict025"),
        ("R4 raw + NKD", "current"),
    ]
    emit("  {:<20} {:<9} {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7}".format(
        "variant", "cap", "floor$", "PF", "Calmar", "2025$", "PF", "Calmar", "2026$", "PF", "Calmar"))
    for variant, cap in keys:
        rowmap = {}
        for which, rows in results.items():
            rowmap[which] = next(r for r in rows if r["variant"] == variant and r["cap"] == cap)
        f, y25, y26 = rowmap["floor"], rowmap["vault2025"], rowmap["vault2026"]
        emit("  {:<20} {:<9} {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f}".format(
            variant, cap,
            f["net"], fmt_pf(f["pf"]), f["calmar"],
            y25["net"], fmt_pf(y25["pf"]), y25["calmar"],
            y26["net"], fmt_pf(y26["pf"]), y26["calmar"]))

    JSON_OUT.write_text(json.dumps({"thresholds": th, "rule": RULE, "results": results}, indent=2), encoding="utf-8")
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
