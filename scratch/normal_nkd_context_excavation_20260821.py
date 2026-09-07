"""
Normal-NKD context excavation - scratch/research only.

Question: can NKD be rescued by a small, economically motivated context/liquidity
filter family?

Uses corrected NKD trades and tests filters selected on floor only. For selected
rows it reports OOS, slippage stress, centered cluster bootstrap, and drop-best-
month concentration. No production code is changed.
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

from scratch.normal_promotion_nkd_sleeve_audit_20260821 import (
    bootstrap,
    cluster_sums,
    drop_best_months,
)
from scratch.normal_sleeve_gap_spy_context_probe_20260821 import (
    instrument_contexts,
    load_spy,
)
from scratch.normal_sleeve_risk_policy_probe_20260821 import load_trade_json, metrics
from scratch.normal_sleeve_volume_filter_probe_20260821 import load_frames, volume_contexts


OUT = Path("scratch/normal_nkd_context_excavation_20260821.txt")
JSON_OUT = Path("scratch/normal_nkd_context_excavation_20260821.json")


def finite(x) -> float:
    try:
        y = float(x)
        return y if np.isfinite(y) else float("nan")
    except Exception:
        return float("nan")


def load_nkd_book(which: str, spy: pd.DataFrame) -> list[dict]:
    raw = load_trade_json(which)
    nkd = raw["nkd_instrument"]
    frames = load_frames(raw)
    ictx = instrument_contexts({nkd: frames[nkd]})
    vctx = volume_contexts({nkd: frames[nkd]})[nkd]

    rows = []
    for t in raw["corrected"][nkd]:
        day = pd.Timestamp(t["day"]).normalize()
        item = dict(t)
        item["inst"] = nkd
        item["entry_day"] = day
        item["exit_day_ts"] = pd.Timestamp(t.get("exit_day") or t["day"]).normalize()
        item["pnl_sized"] = float(t["pnl"])
        item["pnl"] = float(t["pnl"])
        item.update(ictx.get((nkd, day), {}))

        ets = pd.Timestamp(t.get("entry_time"))
        b = vctx
        if b.index.tz is not None and ets.tzinfo is None:
            ets = ets.tz_localize(b.index.tz)
        elif b.index.tz is not None:
            ets = ets.tz_convert(b.index.tz)
        elif ets.tzinfo is not None:
            ets = ets.tz_localize(None)
        if ets in b.index:
            vr = b.loc[ets]
        else:
            pos = b.index.get_indexer([ets], method="nearest")[0]
            vr = b.iloc[pos] if pos >= 0 else None
        item["rvol_slot20"] = finite(vr["rvol_slot20"]) if vr is not None else np.nan
        item["rvol_prev10"] = finite(vr["rvol_prev10"]) if vr is not None else np.nan
        rows.append(item)

    sdf = pd.DataFrame([{"ix": i, "entry_day": t["entry_day"]} for i, t in enumerate(rows)])
    sdf = pd.merge_asof(
        sdf.sort_values("entry_day"),
        spy.sort_values("spy_feature_date"),
        left_on="entry_day",
        right_on="spy_feature_date",
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("ix")
    for rec in sdf.to_dict("records"):
        item = rows[int(rec["ix"])]
        for k in ("spy_ret1", "spy_ret3", "spy_above50", "spy_rv20"):
            item[k] = rec.get(k)
    return rows


def daily_metrics(book: list[dict]) -> dict:
    daily = {}
    for t in book:
        d = pd.Timestamp(t.get("exit_day_ts", t["entry_day"])).normalize()
        daily[d] = daily.get(d, 0.0) + float(t["pnl"])
    return metrics(pd.Series(daily).sort_index())


def stats(book: list[dict], *, extra_ticks_per_side: float = 0.0) -> dict:
    adj = []
    for t in book:
        x = dict(t)
        x["pnl"] = float(t["pnl"]) - 5.0 * extra_ticks_per_side
        adj.append(x)
    m = daily_metrics(adj)
    return {
        "n": len(book),
        "days": len({pd.Timestamp(t["entry_day"]).normalize() for t in book}),
        "net": m["pnl"],
        "pf": m["pf"],
        "sharpe": m["sharpe"],
        "calmar": m["calmar"],
        "maxdd": m["maxdd"],
        "avg": m["pnl"] / len(book) if book else 0.0,
    }


def thresholds(floor: list[dict]) -> dict:
    def q(key, p):
        vals = [finite(t.get(key)) for t in floor]
        vals = [x for x in vals if np.isfinite(x)]
        return float(np.quantile(vals, p)) if vals else float("nan")
    return {
        "prev_range_p80": q("prev_range_pct", 0.80),
        "prev_range_p90": q("prev_range_pct", 0.90),
        "rvol_p20": q("rvol_slot20", 0.20),
        "rvol_p80": q("rvol_slot20", 0.80),
        "spy_rv80": q("spy_rv20", 0.80),
        "spy_ret1_p10": q("spy_ret1", 0.10),
    }


def pass_rule(t: dict, rule: str, th: dict) -> bool:
    if rule == "none":
        return True
    direction = str(t.get("direction"))
    gap = finite(t.get("gap"))
    open_loc = finite(t.get("open_loc"))
    prev_range = finite(t.get("prev_range_pct"))
    rvol = finite(t.get("rvol_slot20"))
    spy_ret1 = finite(t.get("spy_ret1"))
    spy_ret3 = finite(t.get("spy_ret3"))
    spy_rv = finite(t.get("spy_rv20"))
    checks = {
        "long": lambda: direction == "LONG",
        "short": lambda: direction == "SHORT",
        "gap_not_deep": lambda: np.isfinite(gap) and gap >= -0.006,
        "gap_flat": lambda: np.isfinite(gap) and -0.006 <= gap <= 0.006,
        "open_inside": lambda: np.isfinite(open_loc) and 0.0 <= open_loc <= 1.0,
        "open_not_deep": lambda: np.isfinite(open_loc) and open_loc >= -0.05,
        "prev_range_le_p80": lambda: np.isfinite(prev_range) and prev_range <= th["prev_range_p80"],
        "prev_range_le_p90": lambda: np.isfinite(prev_range) and prev_range <= th["prev_range_p90"],
        "rvol_06_2": lambda: np.isfinite(rvol) and 0.6 <= rvol <= 2.0,
        "rvol_le_2": lambda: np.isfinite(rvol) and rvol <= 2.0,
        "rvol_ge_1": lambda: np.isfinite(rvol) and rvol >= 1.0,
        "rvol_mid_floor": lambda: np.isfinite(rvol) and th["rvol_p20"] <= rvol <= th["rvol_p80"],
        "spy_not_crash": lambda: np.isfinite(spy_ret1) and spy_ret1 >= th["spy_ret1_p10"],
        "spy_ret3_down": lambda: np.isfinite(spy_ret3) and spy_ret3 <= 0.0,
        "spy_rv80": lambda: np.isfinite(spy_rv) and spy_rv <= th["spy_rv80"],
    }
    if rule in checks:
        return checks[rule]()
    parts = rule.split("__")
    if len(parts) > 1:
        return all(pass_rule(t, p, th) for p in parts)
    raise ValueError(rule)


def rule_grid() -> list[str]:
    base = [
        "none",
        "long",
        "short",
        "gap_not_deep",
        "gap_flat",
        "open_inside",
        "open_not_deep",
        "prev_range_le_p80",
        "prev_range_le_p90",
        "rvol_06_2",
        "rvol_le_2",
        "rvol_ge_1",
        "rvol_mid_floor",
        "spy_not_crash",
        "spy_ret3_down",
        "spy_rv80",
    ]
    combos = []
    for a in ("long", "short"):
        for b in ("rvol_06_2", "rvol_le_2", "rvol_ge_1", "gap_flat", "open_inside", "prev_range_le_p90", "spy_not_crash"):
            combos.append(f"{a}__{b}")
    for a in ("rvol_06_2", "rvol_le_2", "rvol_ge_1"):
        for b in ("gap_flat", "open_inside", "prev_range_le_p90", "spy_not_crash"):
            combos.append(f"{a}__{b}")
    return base + combos


def apply_rule(book: list[dict], rule: str, th: dict) -> list[dict]:
    return [t for t in book if pass_rule(t, rule, th)]


def month_drop(book: list[dict]) -> dict:
    out = {}
    for k in (1, 2):
        kept, dropped = drop_best_months(book, k)
        out[f"drop{k}_net"] = sum(float(t["pnl"]) for t in kept)
        out[f"drop{k}_months"] = dropped
    return out


def centered_boot(book: list[dict], rng: np.random.Generator) -> dict:
    tmp = []
    for t in book:
        x = dict(t)
        x["day"] = str(pd.Timestamp(t["entry_day"]).date())
        tmp.append(x)
    out = {}
    for how in ("day", "week", "month"):
        b = bootstrap(cluster_sums(tmp, how), rng)
        out[f"{how}_n"] = b.get("n", 0)
        out[f"{how}_p_centred"] = b.get("p_centred", np.nan)
        out[f"{how}_p5"] = b.get("p5", np.nan)
        out[f"{how}_p50"] = b.get("p50", np.nan)
        out[f"{how}_p95"] = b.get("p95", np.nan)
    return out


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def main() -> int:
    report = []

    def emit(s: str = ""):
        print(s, flush=True)
        report.append(s)

    spy = load_spy()
    books = {w: load_nkd_book(w, spy) for w in ("floor", "vault2025", "vault2026")}
    th = thresholds(books["floor"])
    rules = rule_grid()
    rows = {}
    for which, book in books.items():
        out = []
        for rule in rules:
            kept = apply_rule(book, rule, th)
            st = stats(kept)
            st3 = stats(kept, extra_ticks_per_side=1.0)
            st4 = stats(kept, extra_ticks_per_side=2.0)
            breakeven = 2.0 + (st["net"] / (5.0 * len(kept)) if kept else 0.0)
            out.append({
                "which": which,
                "rule": rule,
                **st,
                "net_3t": st3["net"],
                "net_4t": st4["net"],
                "breakeven_ticks_side": breakeven,
            })
        rows[which] = out

    floor = rows["floor"]
    selectable = [
        r for r in floor
        if r["n"] >= 60 and r["net"] > 0 and r["pf"] >= 1.20
        and r["net_4t"] > 0 and r["breakeven_ticks_side"] >= 4.5
    ]
    selectable.sort(key=lambda r: (r["calmar"], r["net"]), reverse=True)
    selected = [r["rule"] for r in selectable[:12]]

    emit("=" * 118)
    emit("NORMAL-NKD CONTEXT EXCAVATION (scratch only)")
    emit("=" * 118)
    emit("Selection uses floor only. Gate for display: n>=60, net>0, PF>=1.20, still positive at 4 ticks/side, breakeven>=4.5 ticks/side.")
    emit("thresholds=" + ", ".join(f"{k}={v:.6f}" for k, v in th.items()))
    emit("")
    emit("FLOOR TOP")
    emit("  {:<28} {:>5} {:>10} {:>5} {:>7} {:>7} {:>10} {:>10} {:>6}".format(
        "rule", "n", "net$", "PF", "Sharpe", "Calmar", "net@3t", "net@4t", "be/t"))
    for r in selectable[:24]:
        emit("  {:<28} {:>5} {:>10,.0f} {:>5} {:>7.2f} {:>7.2f} {:>10,.0f} {:>10,.0f} {:>6.2f}".format(
            r["rule"], r["n"], r["net"], fmt_pf(r["pf"]), r["sharpe"], r["calmar"], r["net_3t"], r["net_4t"], r["breakeven_ticks_side"]))
    emit("")
    emit("selected_before_oos=" + (",".join(selected) if selected else "NONE"))
    emit("")

    by = {w: {r["rule"]: r for r in rr} for w, rr in rows.items()}
    emit("CROSS-WINDOW SELECTED")
    emit("  {:<28} {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7}".format(
        "rule", "floor$", "PF", "Calmar", "2025$", "PF", "Calmar", "2026$", "PF", "Calmar"))
    for rule in selected:
        f, y25, y26 = by["floor"][rule], by["vault2025"][rule], by["vault2026"][rule]
        emit("  {:<28} {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f}".format(
            rule, f["net"], fmt_pf(f["pf"]), f["calmar"], y25["net"], fmt_pf(y25["pf"]), y25["calmar"], y26["net"], fmt_pf(y26["pf"]), y26["calmar"]))
    emit("")

    rng = np.random.default_rng(20260821)
    diagnostics = {}
    emit("SELECTED DIAGNOSTICS")
    for rule in selected[:8]:
        diagnostics[rule] = {}
        emit(f"\n[{rule}]")
        for which, book in books.items():
            kept = apply_rule(book, rule, th)
            bs = centered_boot(kept, rng)
            md = month_drop(kept)
            diagnostics[rule][which] = {"bootstrap": bs, "month_drop": md}
            st = by[which][rule]
            emit("  {:<9} n={:>3} net=${:>8,.0f} pf={} calmar={:.2f} be={:.2f}t day_p={:.3f} week_p={:.3f} month_p={:.3f} drop1=${:,.0f} drop2=${:,.0f}".format(
                which, st["n"], st["net"], fmt_pf(st["pf"]), st["calmar"], st["breakeven_ticks_side"],
                bs["day_p_centred"], bs["week_p_centred"], bs["month_p_centred"], md["drop1_net"], md["drop2_net"]))

    JSON_OUT.write_text(json.dumps({"thresholds": th, "selected": selected, "rows": rows, "diagnostics": diagnostics}, indent=2), encoding="utf-8")
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
