from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from futures.basket import BASKET


OUT = Path("scratch/stress_payoff_sizing_20260821_report.md")
ACCOUNT = 50_000.0
HARD_DD = 0.15 * ACCOUNT
TARGET_DD = 0.10 * ACCOUNT
MARGIN_BUDGET = 0.40 * ACCOUNT

RULE_NAMES = {
    "target_gapcont_10:30_b4_g2_mnqmes_rr15_x1555",
    "target_gapcont_10:30_b4_g2_mnq_rr15_x1555",
    "target_gapcont_10:30_b4_g3_mnq_rr15_x1555",
}


def make_rules() -> list[base.Rule]:
    base.SETUPS = ("10:30",)
    rules = []
    for inst_name, insts in {"mnq": ("MNQ",), "mnqmes": ("MNQ", "MES")}.items():
        for gap_min in (2, 3):
            rules.append(base.Rule(
                name=f"target_gapcont_10:30_b4_g{gap_min}_{inst_name}_rr15_x1555",
                family="cont_short",
                direction="SHORT",
                instruments=insts,
                setup_time="10:30",
                entry_start="10:35",
                entry_end="12:30",
                exit_time="15:55",
                rr=1.5,
                breadth_min=4,
                gapdown_min=gap_min,
                wide_min=0,
                avg_ret_max=None,
                avg_gap_max=-0.001,
            ))
    return [r for r in rules if r.name in RULE_NAMES]


def maxdd(daily: pd.Series) -> float:
    eq = daily.cumsum()
    return float((eq.cummax() - eq).max()) if len(eq) else 0.0


def dense_daily(trades: pd.DataFrame, sessions: pd.DatetimeIndex, scale: int) -> pd.Series:
    s = pd.Series(0.0, index=sessions)
    if trades.empty:
        return s
    d = trades.groupby("day")["pnl"].sum() * scale
    d.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in d.index])
    return s.add(d, fill_value=0.0)


def margin_for(instruments: list[str], scale: int) -> float:
    return sum(BASKET[i].est_margin for i in sorted(set(instruments))) * scale


def summarize_scaled(df: pd.DataFrame, sessions: pd.DatetimeIndex, scale: int) -> dict:
    daily = dense_daily(df, sessions, scale)
    net = float(daily.sum())
    dd = maxdd(daily)
    return {
        "scale": scale,
        "net": net,
        "maxdd": dd,
        "dd_pct": dd / ACCOUNT,
        "margin": margin_for(list(df["instrument"].unique()) if not df.empty else [], scale),
        "margin_pct": margin_for(list(df["instrument"].unique()) if not df.empty else [], scale) / ACCOUNT,
        "hard_ok": dd <= HARD_DD,
        "target_ok": dd <= TARGET_DD,
    }


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run_window(which: str, rules: list[base.Rule]):
    dfs, costs, sessions = base.load_window(which)
    frames, ctx = base.build_day_cache(dfs)
    return {r.name: base.build_rule(frames, ctx, costs, r) for r in rules}, sessions


def main() -> int:
    rules = make_rules()
    floor, floor_sessions = run_window("floor", rules)
    oos25, oos25_sessions = run_window("vault2025", rules)
    sanity26, sanity26_sessions = run_window("vault2026", rules)

    lines = [
        "# Stress Payoff / Sizing Probe - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Purpose: test whether the best ex-2026 Stress candidates are thin because the signal is weak, or because 1-micro payoff is too small.",
        "",
        "Assumptions:",
        "",
        "- Synthetic scaling multiplies the same micro fills/PnL by N contracts.",
        "- This is not a liquidity model and not a production sizing rule.",
        "- $50k account, target DD 10% ($5k), hard DD 15% ($7.5k), margin budget 40% ($20k).",
        "- 2026 remains sanity-only per the current Stress gate.",
        "",
    ]
    for rule in rules:
        df = floor[rule.name]
        rows = []
        for scale in range(1, 11):
            f = summarize_scaled(df, floor_sessions, scale)
            y25 = summarize_scaled(oos25[rule.name], oos25_sessions, scale)
            y26 = summarize_scaled(sanity26[rule.name], sanity26_sessions, scale)
            rows.append({
                "scale": f"{scale}x",
                "floor_net": fmt_money(f["net"]),
                "floor_maxdd": fmt_money(f["maxdd"]),
                "dd_pct": f"{f['dd_pct']:.1%}",
                "margin": fmt_money(f["margin"]),
                "margin_pct": f"{f['margin_pct']:.0%}",
                "target_ok": f["target_ok"],
                "hard_ok": f["hard_ok"],
                "2025": fmt_money(y25["net"]),
                "2026_sanity": fmt_money(y26["net"]),
            })
        stops = df[df["exit_reason"] == "stop"]["pnl"] if not df.empty else pd.Series(dtype=float)
        losses = df[df["pnl"] < 0]["pnl"] if not df.empty else pd.Series(dtype=float)
        lines += [
            f"## {rule.name}",
            "",
            f"1x instruments: {', '.join(rule.instruments)}",
            f"1x trades: {len(df)}, net {fmt_money(float(df['pnl'].sum()) if not df.empty else 0.0)}, max single loss {fmt_money(float(losses.min()) if len(losses) else 0.0)}, median stop {fmt_money(float(stops.median()) if len(stops) else 0.0)}",
            "",
            table(rows, ["scale", "floor_net", "floor_maxdd", "dd_pct", "margin", "margin_pct", "target_ok", "hard_ok", "2025", "2026_sanity"]),
            "",
        ]
    lines += [
        "## Read",
        "",
        "- If using only the account hard-DD rule, the MNQ/MES candidate can scale to about 4x before floor MaxDD breaches 15%.",
        "- MNQ-only can scale higher because floor MaxDD is lower, but 2025 has only 3 trades and the same signal-sample caveat remains.",
        "- Scaling makes PnL thick enough on paper, but it also scales same-symbol conflict and 2026 sanity loss linearly.",
        "- Therefore payoff/sizing helps the thin-PnL problem only if overlap and insurance-value tests pass.",
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
