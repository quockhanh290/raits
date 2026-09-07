from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.stress_open_search_20260821 import (
    bootstrap_events,
    build_day_cache,
    build_rule,
    fmt_money,
    fmt_pf,
    generate_rules,
    load_window,
    measure_window,
    summarize,
    table,
)


OUT = Path("scratch/stress_ex2026_gate_20260821_report.md")


def global_clusters(cands: dict[str, pd.DataFrame]) -> dict[pd.Timestamp, str]:
    days = sorted({
        pd.Timestamp(x).normalize()
        for df in cands.values()
        if not df.empty
        for x in df["day"].unique()
    })
    out = {}
    last = None
    cluster = 0
    for d in days:
        if last is None or (d - last).days > 3:
            cluster += 1
        out[d] = f"E{cluster:03d}"
        last = d
    return out


def remap_clusters(cands: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    clusters = global_clusters(cands)
    out = {}
    for name, df in cands.items():
        if df.empty:
            out[name] = df
            continue
        work = df.copy()
        work["event_cluster"] = [clusters[pd.Timestamp(x).normalize()] for x in work["day"]]
        out[name] = work
    return out


def event_wfo(cands: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    clusters = sorted(global_clusters(cands).values())
    rows = []
    for i, cluster in enumerate(clusters):
        if i < 8:
            continue
        train_clusters = set(clusters[:i])
        best_name = None
        best_score = -1e18
        for name, df in cands.items():
            train = df[df["event_cluster"].isin(train_clusters)] if not df.empty else df
            if len(train) < 20:
                continue
            gp = float(train.loc[train["pnl"] > 0, "pnl"].sum())
            gl = float(-train.loc[train["pnl"] < 0, "pnl"].sum())
            pf = gp / gl if gl else math.inf
            net = float(train["pnl"].sum())
            if net <= 0 or pf < 1.10:
                continue
            b = bootstrap_events(train, n=300, seed=17)
            score = net + 500.0 * (pf - 1.0) + min(b["p5"], 0.0) * 0.25
            if b["best_share"] > 0.5:
                score -= 1000.0 * min(b["best_share"], 3.0)
            if score > best_score:
                best_score = score
                best_name = name
        if best_name is None:
            continue
        test = cands[best_name][cands[best_name]["event_cluster"] == cluster]
        rows.append({
            "test_cluster": cluster,
            "selected": best_name,
            "trades": int(len(test)),
            "net": float(test["pnl"].sum()) if not test.empty else 0.0,
        })
    wf = pd.DataFrame(rows)
    if wf.empty:
        return wf, {"total": 0.0, "best": 0.0, "without_best": 0.0, "final4": 0.0, "positive": 0, "folds": 0, "pass": False}
    total = float(wf["net"].sum())
    best = float(wf["net"].max())
    final4 = float(wf.tail(4)["net"].sum())
    gate = {
        "total": total,
        "best": best,
        "without_best": total - best,
        "final4": final4,
        "positive": int((wf["net"] > 0).sum()),
        "folds": int(len(wf)),
        "pass": bool(total > 0 and total - best > 0 and best <= 0.5 * total and final4 >= 0),
    }
    return wf, gate


def ex2026_score(row: dict, oos25: dict | None) -> float:
    if row["trades"] < 20 or row["net_raw"] <= 0 or row["pf_raw"] < 1.15 or row["sig"] or row["same"]:
        return -1e9
    score = row["net_raw"] + 750.0 * (row["pf_raw"] - 1.0) - 0.25 * row["maxdd_raw"]
    if row["slip3_raw"] <= 0:
        score -= 3000
    if row["boot_p5_raw"] < 0:
        score += row["boot_p5_raw"] * 0.5
    if row["best_share_raw"] > 0.5:
        score -= 1500.0 * min(row["best_share_raw"], 3.0)
    if not oos25 or oos25["trades"] == 0:
        score -= 1500
    elif oos25["net_raw"] < 0:
        score += 2.0 * oos25["net_raw"] - 1500
    else:
        score += min(oos25["net_raw"], 2500)
    return score


def fmt_gate(g: dict) -> dict:
    return {
        "total": fmt_money(g["total"]),
        "best": fmt_money(g["best"]),
        "without_best": fmt_money(g["without_best"]),
        "final4": fmt_money(g["final4"]),
        "positive": g["positive"],
        "folds": g["folds"],
        "pass": g["pass"],
    }


def main() -> int:
    rules = generate_rules()
    floor_rows, floor_cands_raw, floor_sessions = measure_window("floor", rules)
    floor_cands = remap_clusters(floor_cands_raw)

    prelim = sorted(
        [
            r for r in floor_rows
            if r["trades"] >= 15 and r["net_raw"] > 0 and r["pf_raw"] >= 1.10 and not r["sig"] and not r["same"]
        ],
        key=lambda r: (
            r["net_raw"]
            + 500.0 * (r["pf_raw"] - 1.0)
            - 0.25 * r["maxdd_raw"]
            + min(r["boot_p5_raw"], 0.0) * 0.25
        ),
        reverse=True,
    )[:30]
    shortlist_names = {r["name"] for r in prelim}
    shortlist_rules = [r for r in rules if r.name in shortlist_names]
    rows25, _, _ = measure_window("vault2025", shortlist_rules)
    rows26, _, _ = measure_window("vault2026", shortlist_rules)
    by25 = {r["name"]: r for r in rows25}
    by26 = {r["name"]: r for r in rows26}

    for r in floor_rows:
        r["score_ex2026"] = ex2026_score(r, by25.get(r["name"]))
        r["oos25"] = by25.get(r["name"], {}).get("net", "")
        r["oos25_trades"] = by25.get(r["name"], {}).get("trades", "")
        r["sanity2026"] = by26.get(r["name"], {}).get("net", "")
        r["sanity2026_trades"] = by26.get(r["name"], {}).get("trades", "")

    ranked = [r for r in sorted(floor_rows, key=lambda x: x["score_ex2026"], reverse=True) if r["score_ex2026"] > -1e8]
    top = ranked[:20]
    top_names = {r["name"] for r in top}
    top_cands = {name: df for name, df in floor_cands.items() if name in top_names}
    wf, wf_gate = event_wfo(top_cands)

    rows = []
    for r in top:
        df = floor_cands[r["name"]]
        s = summarize(df, floor_sessions)
        s3 = summarize(df, floor_sessions, 3.0)
        b = bootstrap_events(df)
        rows.append({
            "name": r["name"],
            "dir": r["dir"],
            "inst": r["inst"],
            "trades": s["trades"],
            "clusters": s["clusters"],
            "net": fmt_money(s["net"]),
            "pf": fmt_pf(s["pf"]),
            "maxdd": fmt_money(s["maxdd"]),
            "slip3": fmt_money(s3["net"]),
            "boot_p5": fmt_money(b["p5"]),
            "best_share": "inf" if math.isinf(b["best_share"]) else f"{b['best_share']:.2f}",
            "2025": r["oos25"],
            "2025_trades": r["oos25_trades"],
            "2026_sanity": r["sanity2026"],
            "2026_trades": r["sanity2026_trades"],
        })

    best = top[0]["name"] if top else None
    lines = [
        "# Stress Ex-2026 Gate - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Gate change requested by user: 2026 is removed from selection/rejection gate.",
        "2026 is reported only as a forward sanity/monitoring column.",
        "",
        "Gate inputs now:",
        "",
        "- 2018-2024 floor quality;",
        "- event-cluster WFO on floor;",
        "- 2025 OOS;",
        "- fill/timing audit;",
        "- 2x/3x slippage sensitivity;",
        "- 2026 is not used for ranking or rejection.",
        "",
        "## Ranked Candidates",
        "",
        table(rows, ["name", "dir", "inst", "trades", "clusters", "net", "pf", "maxdd", "slip3", "boot_p5", "best_share", "2025", "2025_trades", "2026_sanity", "2026_trades"]),
        "",
        "## Event WFO On Top Candidate Set",
        "",
        table([fmt_gate(wf_gate)], ["total", "best", "without_best", "final4", "positive", "folds", "pass"]),
    ]
    if not wf.empty:
        lines += ["", "WFO selected counts:", ""]
        lines.append(wf.groupby("selected").agg(folds=("net", "size"), net=("net", "sum")).sort_values("net", ascending=False).to_string())
    if best:
        df = floor_cands[best]
        lines += ["", f"## Best Candidate: `{best}`", ""]
        lines.append(df.assign(year=pd.to_datetime(df["day"]).dt.year).groupby("year").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "By instrument:", ""]
        lines.append(df.groupby("instrument").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "By exit reason:", ""]
        lines.append(df.groupby("exit_reason").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
    lines += [
        "",
        "## Verdict",
        "",
        "- Removing 2026 from the gate can produce a research candidate, but not a production candidate by itself.",
        "- A candidate still must pass floor event-WFO and 2025 OOS without relying on one cluster.",
        "- 2026 remains a non-gating warning column for live monitoring.",
    ]

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
