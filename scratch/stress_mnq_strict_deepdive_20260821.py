from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from scratch.stress_ex2026_gate_20260821 import event_wfo, remap_clusters
from scratch.stress_payoff_sizing_20260821 import ACCOUNT, HARD_DD, TARGET_DD
from futures.basket import BASKET


OUT = Path("scratch/stress_mnq_strict_deepdive_20260821_report.md")


def make_rules() -> list[base.Rule]:
    base.SETUPS = ("10:00", "10:30", "11:00")
    rules: list[base.Rule] = []
    for setup in base.SETUPS:
        start = base.add_minutes(setup, 5)
        end = "12:30" if setup in {"10:00", "10:30"} else "13:30"
        for gap_min in (2, 3, 4):
            for rr in (1.0, 1.25, 1.5, 1.75, 2.0):
                for exit_time in ("14:00", "15:55"):
                    rules.append(base.Rule(
                        name=(
                            f"mnq_strict_{setup}_b4_g{gap_min}_"
                            f"rr{str(rr).replace('.', '')}_x{exit_time.replace(':', '')}"
                        ),
                        family="cont_short",
                        direction="SHORT",
                        instruments=("MNQ",),
                        setup_time=setup,
                        entry_start=start,
                        entry_end=end,
                        exit_time=exit_time,
                        rr=rr,
                        breadth_min=4,
                        gapdown_min=gap_min,
                        wide_min=0,
                        avg_ret_max=None,
                        avg_gap_max=-0.001,
                    ))
    return rules


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def maxdd(daily: pd.Series) -> float:
    eq = daily.cumsum()
    return float((eq.cummax() - eq).max()) if len(eq) else 0.0


def dense_daily(df: pd.DataFrame, sessions: pd.DatetimeIndex, scale: int = 1) -> pd.Series:
    out = pd.Series(0.0, index=sessions)
    if df.empty:
        return out
    d = df.groupby("day")["pnl"].sum() * scale
    d.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in d.index])
    return out.add(d, fill_value=0.0)


def scaled_row(df: pd.DataFrame, sessions: pd.DatetimeIndex, scale: int, df25: pd.DataFrame, sess25, df26: pd.DataFrame, sess26) -> dict:
    f = dense_daily(df, sessions, scale)
    y25 = dense_daily(df25, sess25, scale)
    y26 = dense_daily(df26, sess26, scale)
    dd = maxdd(f)
    margin = BASKET["MNQ"].est_margin * scale
    return {
        "scale": f"{scale}x",
        "floor": fmt_money(float(f.sum())),
        "maxdd": fmt_money(dd),
        "dd_pct": f"{dd / ACCOUNT:.1%}",
        "margin": fmt_money(margin),
        "margin_pct": f"{margin / ACCOUNT:.0%}",
        "target_ok": dd <= TARGET_DD,
        "hard_ok": dd <= HARD_DD,
        "2025": fmt_money(float(y25.sum())),
        "2026_sanity": fmt_money(float(y26.sum())),
    }


def measure_all(which: str, rules: list[base.Rule]):
    rows, cands_raw, sessions = base.measure_window(which, rules)
    return rows, remap_clusters(cands_raw), sessions


def score(row: dict, y25: dict | None) -> float:
    if row["trades"] < 20 or row["net_raw"] <= 0 or row["pf_raw"] < 1.20 or row["sig"] or row["same"]:
        return -1e9
    s = row["net_raw"] + 900.0 * (row["pf_raw"] - 1.0) - 0.30 * row["maxdd_raw"]
    if row["slip3_raw"] <= 0:
        s -= 3000
    if row["boot_p5_raw"] < 0:
        s += row["boot_p5_raw"] * 0.6
    if row["best_share_raw"] > 0.5:
        s -= 2000.0 * min(row["best_share_raw"], 3.0)
    if not y25 or y25["trades"] == 0:
        s -= 2000
    elif y25["net_raw"] < 0:
        s += 2.0 * y25["net_raw"] - 2000
    else:
        s += min(y25["net_raw"], 2000)
    return s


def main() -> int:
    rules = make_rules()
    floor_rows, floor_cands, floor_sessions = measure_all("floor", rules)
    prelim = sorted(
        [r for r in floor_rows if r["trades"] >= 15 and r["net_raw"] > 0 and r["pf_raw"] >= 1.10],
        key=lambda r: r["net_raw"] + 700.0 * (r["pf_raw"] - 1.0) - 0.25 * r["maxdd_raw"],
        reverse=True,
    )[:24]
    shortlist = {r["name"] for r in prelim}
    srules = [r for r in rules if r.name in shortlist]
    rows25, cands25, sess25 = measure_all("vault2025", srules)
    rows26, cands26, sess26 = measure_all("vault2026", srules)
    by25 = {r["name"]: r for r in rows25}
    by26 = {r["name"]: r for r in rows26}

    for r in floor_rows:
        r["score"] = score(r, by25.get(r["name"]))
        r["2025"] = by25.get(r["name"], {}).get("net", "")
        r["2025_trades"] = by25.get(r["name"], {}).get("trades", "")
        r["2026_sanity"] = by26.get(r["name"], {}).get("net", "")
        r["2026_trades"] = by26.get(r["name"], {}).get("trades", "")
    ranked = [r for r in sorted(floor_rows, key=lambda x: x["score"], reverse=True) if r["score"] > -1e8]
    top = ranked[:20]
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
            "trades": s["trades"],
            "clusters": s["clusters"],
            "net": fmt_money(s["net"]),
            "pf": base.fmt_pf(s["pf"]),
            "calmar": f"{s['calmar']:.2f}",
            "maxdd": fmt_money(s["maxdd"]),
            "slip3": fmt_money(s3["net"]),
            "boot_p5": fmt_money(b["p5"]),
            "best_share": "inf" if math.isinf(b["best_share"]) else f"{b['best_share']:.2f}",
            "2025": r["2025"],
            "2025_trades": r["2025_trades"],
            "2026_sanity": r["2026_sanity"],
            "2026_trades": r["2026_trades"],
        })

    best = top[0]["name"] if top else ""
    lines = [
        "# Stress MNQ-Only Strict Deep Dive - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Purpose: investigate the cleaner MNQ-only strict Stress direction under the ex-2026 gate.",
        "",
        "Search space:",
        "",
        "- no daily Stress regime label;",
        "- setup `10:00`, `10:30`, `11:00`, known five minutes later;",
        "- 4/4 basket below open/VWAP;",
        "- gap-down count 2/4, 3/4, or 4/4;",
        "- MNQ only;",
        "- SHORT low-break continuation;",
        "- RR 1.0, 1.25, 1.5, 1.75, 2.0;",
        "- exit 14:00 or 15:55;",
        "- 2026 is sanity-only.",
        "",
        f"Rules searched: {len(rules)}",
        "",
        "## Ranked Fixed Candidates",
        "",
        table(rows, ["name", "trades", "clusters", "net", "pf", "calmar", "maxdd", "slip3", "boot_p5", "best_share", "2025", "2025_trades", "2026_sanity", "2026_trades"]),
        "",
        "## Dynamic WFO Across Top MNQ-Strict Set",
        "",
        table([{
            "total": fmt_money(gate["total"]),
            "best": fmt_money(gate["best"]),
            "without_best": fmt_money(gate["without_best"]),
            "final4": fmt_money(gate["final4"]),
            "positive": gate["positive"],
            "folds": gate["folds"],
            "pass": gate["pass"],
        }], ["total", "best", "without_best", "final4", "positive", "folds", "pass"]),
    ]
    if not wf.empty:
        lines += ["", "WFO selected counts:", ""]
        lines.append(wf.groupby("selected").agg(folds=("net", "size"), net=("net", "sum")).sort_values("net", ascending=False).to_string())
    if best:
        df = floor_cands[best]
        lines += ["", f"## Best Fixed Candidate Autopsy: `{best}`", ""]
        lines.append(df.assign(year=pd.to_datetime(df["day"]).dt.year).groupby("year").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "By exit reason:", ""]
        lines.append(df.groupby("exit_reason").agg(trades=("pnl", "size"), net=("pnl", "sum"), avg=("pnl", "mean")).to_string())
        lines += ["", "Sizing sketch:", ""]
        y25 = cands25.get(best, pd.DataFrame())
        y26 = cands26.get(best, pd.DataFrame())
        scale_rows = [scaled_row(df, floor_sessions, n, y25, sess25, y26, sess26) for n in range(1, 11)]
        lines.append(table(scale_rows, ["scale", "floor", "maxdd", "dd_pct", "margin", "margin_pct", "target_ok", "hard_ok", "2025", "2026_sanity"]))
    lines += ["", "## Verdict", ""]
    lines.append("- This pass is a research deep dive, not a deploy approval.")
    lines.append("- The winner must beat the previous `b4 g3 MNQ rr15` shape without relying on a parameter-only improvement.")
    lines.append("- 2026 remains visible but non-gating under the current Stress protocol.")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
