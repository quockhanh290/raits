"""
Normal sleeve volume deep-dive - scratch/research only.

Tests where the time-slot relative-volume signal is useful: all trades, R4-only,
NKD-only, and direction-specific gates. Uses corrected trade tables and replay.
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
from scratch.normal_sleeve_risk_policy_probe_20260821 import build_meta, load_trade_json
from scratch.normal_sleeve_volume_filter_probe_20260821 import attach_book, load_frames, volume_contexts


OUT = Path("scratch/normal_sleeve_volume_deepdive_20260821.txt")
JSON_OUT = Path("scratch/normal_sleeve_volume_deepdive_20260821.json")


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def load_book(which: str) -> list[dict]:
    raw = load_trade_json(which)
    return attach_book(raw, build_meta(raw), volume_contexts(load_frames(raw)))


def applies(t: dict, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "r4":
        return t["cluster"] == "roska4_swing"
    if scope == "nkd":
        return t["cluster"] == "global_nkd"
    if scope == "long":
        return t["direction"] == "LONG"
    if scope == "short":
        return t["direction"] == "SHORT"
    if scope == "r4_long":
        return t["cluster"] == "roska4_swing" and t["direction"] == "LONG"
    if scope == "r4_short":
        return t["cluster"] == "roska4_swing" and t["direction"] == "SHORT"
    if scope == "nkd_long":
        return t["cluster"] == "global_nkd" and t["direction"] == "LONG"
    if scope == "nkd_short":
        return t["cluster"] == "global_nkd" and t["direction"] == "SHORT"
    raise ValueError(scope)


def keep_trade(t: dict, rule: dict) -> bool:
    if not applies(t, rule["scope"]):
        return True
    x = t.get("rvol_slot20", np.nan)
    if not np.isfinite(x):
        return False
    lo = rule.get("lo")
    hi = rule.get("hi")
    if lo is not None and x < lo:
        return False
    if hi is not None and x > hi:
        return False
    return True


def rule_grid() -> list[dict]:
    rules = [dict(name="none", scope="all")]
    scopes = ("all", "r4", "nkd", "long", "short", "r4_long", "r4_short", "nkd_long", "nkd_short")
    lows = (0.5, 0.6, 0.7, 0.8, 1.0, 1.2)
    highs = (1.0, 1.2, 1.5, 2.0)
    bands = ((0.5, 1.5), (0.6, 1.5), (0.7, 1.5), (0.8, 1.5), (0.6, 2.0), (0.8, 2.0))
    for scope in scopes:
        for lo in lows:
            rules.append(dict(name=f"{scope}_slot_ge_{lo:g}", scope=scope, lo=lo))
        for hi in highs:
            rules.append(dict(name=f"{scope}_slot_le_{hi:g}", scope=scope, hi=hi))
        for lo, hi in bands:
            rules.append(dict(name=f"{scope}_slot_{lo:g}_{hi:g}", scope=scope, lo=lo, hi=hi))
    return rules


def bucket_stats(book: list[dict]) -> list[dict]:
    bins = [0, 0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0, float("inf")]
    labels = ["<0.5", "0.5-0.6", "0.6-0.8", "0.8-1.0", "1.0-1.2", "1.2-1.5", "1.5-2.0", ">=2.0"]
    rows = []
    for scope in ("all", "r4", "nkd", "long", "short"):
        scoped = [t for t in book if applies(t, scope) and np.isfinite(t.get("rvol_slot20", np.nan))]
        for i, label in enumerate(labels):
            lo, hi = bins[i], bins[i + 1]
            xs = [t for t in scoped if lo <= t["rvol_slot20"] < hi]
            pnl = sum(t["pnl_sized"] for t in xs)
            wins = sum(t["pnl_sized"] for t in xs if t["pnl_sized"] > 0)
            losses = -sum(t["pnl_sized"] for t in xs if t["pnl_sized"] < 0)
            rows.append(dict(
                scope=scope,
                bucket=label,
                n=len(xs),
                pnl=pnl,
                avg=pnl / len(xs) if xs else 0.0,
                pf=(wins / losses if losses > 1e-9 else float("inf")) if xs else 0.0,
            ))
    return rows


def run_window(which: str) -> tuple[list[dict], list[dict]]:
    book = load_book(which)
    rows = []
    for rule in rule_grid():
        kept = [t for t in book if keep_trade(t, rule)]
        skipped = [t for t in book if not keep_trade(t, rule)]
        cur = replay(kept, swing_gross=0.050, swing_net=0.044, nkd_cap=0.060,
                     breaker=0.15, release="latch")
        strict = replay(kept, swing_gross=0.025, swing_net=0.025, nkd_cap=0.060,
                        breaker=0.15, release="latch")
        rows.append(dict(
            which=which,
            rule=rule["name"],
            scope=rule["scope"],
            kept=len(kept),
            skipped=len(skipped),
            skipped_pnl=sum(t["pnl_sized"] for t in skipped),
            net=cur["net"],
            pf=cur["pf"],
            sharpe=cur["sharpe"],
            calmar=cur["calmar"],
            maxdd_pct=cur["maxdd_pct"],
            halted=cur["halted_days"],
            blocked=cur["blocked_trades"],
            strict025_net=strict["net"],
            strict025_pf=strict["pf"],
            strict025_calmar=strict["calmar"],
            strict025_maxdd_pct=strict["maxdd_pct"],
        ))
    return rows, bucket_stats(book)


def main() -> int:
    report = []

    def emit(s: str = ""):
        print(s, flush=True)
        report.append(s)

    all_rows = {}
    all_buckets = {}
    for which in ("floor", "vault2025", "vault2026"):
        rows, buckets = run_window(which)
        all_rows[which] = rows
        all_buckets[which] = buckets
        base = next(r for r in rows if r["rule"] == "none")
        ranked = sorted(
            [r for r in rows if r["kept"] >= max(25, int(base["kept"] * 0.35))],
            key=lambda r: (r["calmar"], r["net"]),
            reverse=True,
        )
        emit("#" * 118)
        emit(f"WINDOW: {which}")
        emit("#" * 118)
        emit("base: net ${:,.0f} PF {} Sharpe {:.2f} Calmar {:.2f} MaxDD {:.1%} kept {}".format(
            base["net"], fmt_pf(base["pf"]), base["sharpe"], base["calmar"], base["maxdd_pct"], base["kept"]))
        emit("top scoped rules with kept >= max(25, 35% base)")
        emit("  {:<28} {:>5} {:>6} {:>10} {:>5} {:>7} {:>7} {:>8} {:>10}".format(
            "rule", "kept", "skip", "net$", "PF", "Sharpe", "Calmar", "MaxDD%", "skip_pnl"))
        for r in ranked[:24]:
            emit("  {:<28} {:>5} {:>6} {:>10,.0f} {:>5} {:>7.2f} {:>7.2f} {:>8.1%} {:>10,.0f}".format(
                r["rule"], r["kept"], r["skipped"], r["net"], fmt_pf(r["pf"]), r["sharpe"],
                r["calmar"], r["maxdd_pct"], r["skipped_pnl"]))
        emit("")
        emit("volume bucket PnL by scope")
        emit("  {:<7} {:<8} {:>5} {:>10} {:>9} {:>5}".format("scope", "bucket", "n", "pnl$", "avg$", "PF"))
        for b in buckets:
            if b["n"] == 0:
                continue
            emit("  {:<7} {:<8} {:>5} {:>10,.0f} {:>9,.1f} {:>5}".format(
                b["scope"], b["bucket"], b["n"], b["pnl"], b["avg"], fmt_pf(b["pf"])))
        emit("")

    emit("=" * 118)
    emit("CROSS-WINDOW FOR FLOOR-TOP SCOPED RULES")
    emit("=" * 118)
    by = {w: {r["rule"]: r for r in rows} for w, rows in all_rows.items()}
    floor_base = next(r for r in all_rows["floor"] if r["rule"] == "none")
    floor_top = sorted(
        [r for r in all_rows["floor"] if r["kept"] >= max(25, int(floor_base["kept"] * 0.35))],
        key=lambda r: (r["calmar"], r["net"]),
        reverse=True,
    )[:16]
    emit("  {:<28} {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7}".format(
        "rule", "floor$", "PF", "Calmar", "2025$", "PF", "Calmar", "2026$", "PF", "Calmar"))
    for fr in floor_top:
        r25 = by["vault2025"][fr["rule"]]
        r26 = by["vault2026"][fr["rule"]]
        emit("  {:<28} {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f}".format(
            fr["rule"], fr["net"], fmt_pf(fr["pf"]), fr["calmar"],
            r25["net"], fmt_pf(r25["pf"]), r25["calmar"],
            r26["net"], fmt_pf(r26["pf"]), r26["calmar"]))

    JSON_OUT.write_text(json.dumps({"rows": all_rows, "buckets": all_buckets}, indent=2), encoding="utf-8")
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
