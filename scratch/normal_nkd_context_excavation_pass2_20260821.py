"""
Normal-NKD context excavation pass 2 - scratch/research only.

Starts from the pass-1 clue that NKD needs liquidity confirmation. This pass
tests a slightly richer but still small family:
  - entry same-slot relative volume thresholds/bands
  - prior-day NKD range caps
  - gap/open quality
  - direction and SPY close-only context

Selection is floor-only. OOS is read after selection. No production code is
changed.
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

from scratch.normal_nkd_context_excavation_20260821 import (
    centered_boot,
    load_nkd_book,
    month_drop,
    stats,
)
from scratch.normal_sleeve_gap_spy_context_probe_20260821 import load_spy


OUT = Path("scratch/normal_nkd_context_excavation_pass2_20260821.txt")
JSON_OUT = Path("scratch/normal_nkd_context_excavation_pass2_20260821.json")


def finite(x) -> float:
    try:
        y = float(x)
        return y if np.isfinite(y) else float("nan")
    except Exception:
        return float("nan")


def qvals(floor: list[dict]) -> dict:
    out = {}
    for key in ("rvol_slot20", "rvol_prev10", "prev_range_pct", "gap", "gap_abs", "open_loc", "spy_rv20", "spy_ret1"):
        vals = [finite(t.get(key)) for t in floor]
        vals = [x for x in vals if np.isfinite(x)]
        for p in (0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9):
            out[f"{key}_p{int(p*100)}"] = float(np.quantile(vals, p)) if vals else float("nan")
    return out


def rule_grid(th: dict) -> list[dict]:
    rules = [dict(name="none", parts=[])]

    atomic = []
    for x in (0.8, 1.0, 1.2, 1.5, 2.0):
        atomic.append((f"rvol_ge_{x:g}", lambda t, x=x: finite(t.get("rvol_slot20")) >= x))
    for x in (2.0, 3.0, 4.0, 5.0):
        atomic.append((f"rvol_le_{x:g}", lambda t, x=x: finite(t.get("rvol_slot20")) <= x))
    for lo, hi in ((0.8, 4.0), (1.0, 4.0), (1.0, 5.0), (1.2, 4.0), (1.2, 5.0)):
        atomic.append((f"rvol_{lo:g}_{hi:g}", lambda t, lo=lo, hi=hi: lo <= finite(t.get("rvol_slot20")) <= hi))

    for p in (70, 80, 90):
        cap = th[f"prev_range_pct_p{p}"]
        atomic.append((f"prev_range_le_p{p}", lambda t, cap=cap: finite(t.get("prev_range_pct")) <= cap))
    for p in (70, 80, 90):
        cap = th[f"gap_abs_p{p}"]
        atomic.append((f"gap_abs_le_p{p}", lambda t, cap=cap: finite(t.get("gap_abs")) <= cap))

    atomic.extend([
        ("gap_not_deep", lambda t: finite(t.get("gap")) >= -0.006),
        ("gap_flat", lambda t: -0.006 <= finite(t.get("gap")) <= 0.006),
        ("open_inside", lambda t: 0.0 <= finite(t.get("open_loc")) <= 1.0),
        ("open_not_deep", lambda t: finite(t.get("open_loc")) >= -0.05),
        ("long", lambda t: str(t.get("direction")) == "LONG"),
        ("short", lambda t: str(t.get("direction")) == "SHORT"),
        ("spy_not_crash", lambda t: finite(t.get("spy_ret1")) >= th["spy_ret1_p10"]),
        ("spy_ret3_down", lambda t: finite(t.get("spy_ret3")) <= 0.0),
        ("spy_rv80", lambda t: finite(t.get("spy_rv20")) <= th["spy_rv20_p80"]),
        ("spy_above50", lambda t: bool(t.get("spy_above50"))),
    ])

    amap = {name: fn for name, fn in atomic}
    for name in amap:
        rules.append(dict(name=name, parts=[name]))

    # Controlled combos: liquidity first, one or two context constraints.
    liquidity = ["rvol_ge_1", "rvol_ge_1.2", "rvol_1_4", "rvol_1.2_4", "rvol_1_5"]
    contexts = [
        "prev_range_le_p80", "prev_range_le_p90",
        "gap_abs_le_p80", "gap_flat", "open_inside", "open_not_deep",
        "spy_not_crash", "spy_rv80", "spy_ret3_down",
        "long", "short",
    ]
    for liq in liquidity:
        for ctx in contexts:
            rules.append(dict(name=f"{liq}__{ctx}", parts=[liq, ctx]))
    for liq in liquidity:
        for ctx1, ctx2 in (
            ("prev_range_le_p90", "spy_not_crash"),
            ("prev_range_le_p90", "gap_abs_le_p80"),
            ("prev_range_le_p90", "open_inside"),
            ("prev_range_le_p80", "spy_not_crash"),
            ("gap_abs_le_p80", "spy_not_crash"),
            ("long", "prev_range_le_p90"),
            ("long", "spy_not_crash"),
            ("short", "prev_range_le_p90"),
            ("short", "spy_not_crash"),
        ):
            rules.append(dict(name=f"{liq}__{ctx1}__{ctx2}", parts=[liq, ctx1, ctx2]))

    # Stash callables on each rule in a JSON-safe way via names only.
    for r in rules:
        r["_funcs"] = [amap[p] for p in r["parts"]]
    return rules


def apply_rule(book: list[dict], rule: dict) -> list[dict]:
    return [t for t in book if all(fn(t) for fn in rule["_funcs"])]


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def row_for(book: list[dict], rule: dict) -> dict:
    kept = apply_rule(book, rule)
    st = stats(kept)
    st3 = stats(kept, extra_ticks_per_side=1.0)
    st4 = stats(kept, extra_ticks_per_side=2.0)
    be = 2.0 + (st["net"] / (5.0 * len(kept)) if kept else 0.0)
    return {
        "rule": rule["name"],
        "n": st["n"],
        "days": st["days"],
        "net": st["net"],
        "pf": st["pf"],
        "sharpe": st["sharpe"],
        "calmar": st["calmar"],
        "maxdd": st["maxdd"],
        "avg": st["avg"],
        "net_3t": st3["net"],
        "net_4t": st4["net"],
        "breakeven_ticks_side": be,
    }


def main() -> int:
    report = []

    def emit(s: str = ""):
        print(s, flush=True)
        report.append(s)

    spy = load_spy()
    books = {w: load_nkd_book(w, spy) for w in ("floor", "vault2025", "vault2026")}
    th = qvals(books["floor"])
    rules = rule_grid(th)

    rows = {w: [dict(which=w, **row_for(book, rule)) for rule in rules] for w, book in books.items()}

    floor_rows = rows["floor"]
    selectable = [
        r for r in floor_rows
        if r["n"] >= 50
        and r["net"] > 0
        and r["pf"] >= 1.25
        and r["net_4t"] > 0
        and r["breakeven_ticks_side"] >= 5.0
    ]
    selectable.sort(key=lambda r: (r["calmar"], r["net"]), reverse=True)
    selected = [r["rule"] for r in selectable[:15]]

    emit("=" * 120)
    emit("NORMAL-NKD CONTEXT EXCAVATION PASS 2 (scratch only)")
    emit("=" * 120)
    emit("Selection uses floor only. Display gate: n>=50, net>0, PF>=1.25, positive at 4t/side, breakeven>=5t/side.")
    emit("")
    emit("FLOOR TOP")
    emit("  {:<42} {:>4} {:>10} {:>5} {:>7} {:>7} {:>10} {:>10} {:>6}".format(
        "rule", "n", "net$", "PF", "Sharpe", "Calmar", "net@3t", "net@4t", "be/t"))
    for r in selectable[:30]:
        emit("  {:<42} {:>4} {:>10,.0f} {:>5} {:>7.2f} {:>7.2f} {:>10,.0f} {:>10,.0f} {:>6.2f}".format(
            r["rule"], r["n"], r["net"], fmt_pf(r["pf"]), r["sharpe"], r["calmar"],
            r["net_3t"], r["net_4t"], r["breakeven_ticks_side"]))
    emit("")
    emit("selected_before_oos=" + (",".join(selected) if selected else "NONE"))
    emit("")

    by = {w: {r["rule"]: r for r in rr} for w, rr in rows.items()}
    emit("CROSS-WINDOW SELECTED")
    emit("  {:<42} {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7}".format(
        "rule", "floor$", "PF", "Calmar", "2025$", "PF", "Calmar", "2026$", "PF", "Calmar"))
    for rule in selected:
        f, y25, y26 = by["floor"][rule], by["vault2025"][rule], by["vault2026"][rule]
        emit("  {:<42} {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f}".format(
            rule, f["net"], fmt_pf(f["pf"]), f["calmar"],
            y25["net"], fmt_pf(y25["pf"]), y25["calmar"],
            y26["net"], fmt_pf(y26["pf"]), y26["calmar"]))
    emit("")

    rng = np.random.default_rng(20260822)
    diagnostics = {}
    emit("SELECTED DIAGNOSTICS")
    for rule in selected[:10]:
        rule_obj = next(r for r in rules if r["name"] == rule)
        diagnostics[rule] = {}
        emit(f"\n[{rule}]")
        for which, book in books.items():
            kept = apply_rule(book, rule_obj)
            bs = centered_boot(kept, rng)
            md = month_drop(kept)
            diagnostics[rule][which] = {"bootstrap": bs, "month_drop": md}
            st = by[which][rule]
            emit("  {:<9} n={:>3} net=${:>8,.0f} pf={} calmar={:.2f} be={:.2f}t day_p={:.3f} week_p={:.3f} month_p={:.3f} drop1=${:,.0f} drop2=${:,.0f}".format(
                which, st["n"], st["net"], fmt_pf(st["pf"]), st["calmar"], st["breakeven_ticks_side"],
                bs["day_p_centred"], bs["week_p_centred"], bs["month_p_centred"],
                md["drop1_net"], md["drop2_net"]))

    json_rows = {w: rr for w, rr in rows.items()}
    JSON_OUT.write_text(json.dumps({"thresholds": th, "selected": selected, "rows": json_rows, "diagnostics": diagnostics}, indent=2), encoding="utf-8")
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
