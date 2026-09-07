from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from scratch.stress_ex2026_gate_20260821 import event_wfo, remap_clusters


OUT = Path("scratch/stress_targeted_ex2026_20260821_report.md")


def make_rules() -> list[base.Rule]:
    setups = ("10:00", "10:30")
    base.SETUPS = setups
    rules: list[base.Rule] = []
    for setup in setups:
        start = base.add_minutes(setup, 5)
        end = "12:30"
        for inst_name, insts in {"mnq": ("MNQ",), "mnqmes": ("MNQ", "MES")}.items():
            for breadth in (3, 4):
                for gap_min in (1, 2, 3):
                    for rr in (1.5, 2.0, 2.5):
                        for exit_time in ("14:00", "15:55"):
                            rules.append(base.Rule(
                                name=(
                                    f"target_gapcont_{setup}_b{breadth}_g{gap_min}_"
                                    f"{inst_name}_rr{str(rr).replace('.', '')}_x{exit_time.replace(':', '')}"
                                ),
                                family="cont_short",
                                direction="SHORT",
                                instruments=insts,
                                setup_time=setup,
                                entry_start=start,
                                entry_end=end,
                                exit_time=exit_time,
                                rr=rr,
                                breadth_min=breadth,
                                gapdown_min=gap_min,
                                wide_min=0,
                                avg_ret_max=None,
                                avg_gap_max=-0.001,
                            ))
    return rules


def score(row: dict, oos25: dict | None) -> float:
    if row["trades"] < 20 or row["net_raw"] <= 0 or row["pf_raw"] < 1.15 or row["sig"] or row["same"]:
        return -1e9
    s = row["net_raw"] + 800.0 * (row["pf_raw"] - 1.0) - 0.25 * row["maxdd_raw"]
    if row["slip3_raw"] <= 0:
        s -= 3000
    if row["boot_p5_raw"] < 0:
        s += row["boot_p5_raw"] * 0.5
    if row["best_share_raw"] > 0.5:
        s -= 1500.0 * min(row["best_share_raw"], 3.0)
    if not oos25 or oos25["trades"] == 0:
        s -= 1500
    elif oos25["net_raw"] < 0:
        s += 2.0 * oos25["net_raw"] - 1500
    else:
        s += min(oos25["net_raw"], 2500)
    return s


def fmt_best_share(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def main() -> int:
    rules = make_rules()
    floor_rows, floor_cands_raw, floor_sessions = base.measure_window("floor", rules)
    floor_cands = remap_clusters(floor_cands_raw)

    prelim = sorted(
        [
            r for r in floor_rows
            if r["trades"] >= 15 and r["net_raw"] > 0 and r["pf_raw"] >= 1.10 and not r["sig"] and not r["same"]
        ],
        key=lambda r: r["net_raw"] + 500.0 * (r["pf_raw"] - 1.0) - 0.25 * r["maxdd_raw"],
        reverse=True,
    )[:30]
    shortlist = {r["name"] for r in prelim}
    rows25, _, _ = base.measure_window("vault2025", [r for r in rules if r.name in shortlist])
    rows26, _, _ = base.measure_window("vault2026", [r for r in rules if r.name in shortlist])
    by25 = {r["name"]: r for r in rows25}
    by26 = {r["name"]: r for r in rows26}

    for r in floor_rows:
        r["score"] = score(r, by25.get(r["name"]))
        r["oos25"] = by25.get(r["name"], {}).get("net", "")
        r["oos25_trades"] = by25.get(r["name"], {}).get("trades", "")
        r["sanity2026"] = by26.get(r["name"], {}).get("net", "")
        r["sanity2026_trades"] = by26.get(r["name"], {}).get("trades", "")

    ranked = [r for r in sorted(floor_rows, key=lambda x: x["score"], reverse=True) if r["score"] > -1e8]
    top = ranked[:25]
    top_cands = {r["name"]: floor_cands[r["name"]] for r in top}
    wf, gate = event_wfo(top_cands)

    rows = []
    for r in top:
        df = floor_cands[r["name"]]
        s = base.summarize(df, floor_sessions)
        s3 = base.summarize(df, floor_sessions, 3.0)
        b = base.bootstrap_events(df)
        rows.append({
            "name": r["name"],
            "inst": r["inst"],
            "trades": s["trades"],
            "clusters": s["clusters"],
            "net": base.fmt_money(s["net"]),
            "pf": base.fmt_pf(s["pf"]),
            "calmar": f"{s['calmar']:.2f}",
            "maxdd": base.fmt_money(s["maxdd"]),
            "slip3": base.fmt_money(s3["net"]),
            "boot_p5": base.fmt_money(b["p5"]),
            "best_share": fmt_best_share(b["best_share"]),
            "2025": r["oos25"],
            "2025_trades": r["oos25_trades"],
            "2026_sanity": r["sanity2026"],
            "2026_trades": r["sanity2026_trades"],
        })

    lines = [
        "# Stress Targeted Ex-2026 Search - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Purpose: after removing 2026 from the gate, deepen the morning broad-weakness continuation family without using regime labels.",
        "",
        "Search space:",
        "",
        "- setup `10:00` and `10:30`, known five minutes later;",
        "- SHORT only, low-break continuation;",
        "- instruments: `MNQ` and `MNQ/MES`;",
        "- breadth: 3/4 or 4/4 below open/VWAP;",
        "- gap-down count: 1/4, 2/4, or 3/4;",
        "- RR: 1.5, 2.0, 2.5;",
        "- exit: 14:00 or 15:55;",
        "- 2026 is reported only as sanity, not used for ranking or rejection.",
        "",
        f"Rules searched: {len(rules)}",
        "",
        "## Ranked Candidates",
        "",
        base.table(rows, ["name", "inst", "trades", "clusters", "net", "pf", "calmar", "maxdd", "slip3", "boot_p5", "best_share", "2025", "2025_trades", "2026_sanity", "2026_trades"]),
        "",
        "## Event WFO Across Top Candidate Set",
        "",
        base.table([{
            "total": base.fmt_money(gate["total"]),
            "best": base.fmt_money(gate["best"]),
            "without_best": base.fmt_money(gate["without_best"]),
            "final4": base.fmt_money(gate["final4"]),
            "positive": gate["positive"],
            "folds": gate["folds"],
            "pass": gate["pass"],
        }], ["total", "best", "without_best", "final4", "positive", "folds", "pass"]),
    ]
    if not wf.empty:
        lines += ["", "WFO selected counts:", ""]
        lines.append(wf.groupby("selected").agg(folds=("net", "size"), net=("net", "sum")).sort_values("net", ascending=False).to_string())
    if top:
        best = top[0]["name"]
        df = floor_cands[best]
        lines += ["", f"## Best Candidate Autopsy: `{best}`", ""]
        lines.append(df.assign(year=pd.to_datetime(df["day"]).dt.year).groupby("year").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "By instrument:", ""]
        lines.append(df.groupby("instrument").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "By exit reason:", ""]
        lines.append(df.groupby("exit_reason").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
    lines += ["", "## Verdict", ""]
    lines.append("- This is still a research pass, not a deploy pass.")
    lines.append("- Promote only if a fixed candidate, not just dynamic WFO selection, clears concentration and 2025 holdout.")
    lines.append("- 2026 remains a visible warning column outside the gate.")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
