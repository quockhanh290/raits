"""
scripts/pf_analysis.py
-----------------------
Standalone, read-only profit-factor analysis for RAITS WFO OOS trade log.

Blueprint Section 8.1 re-evaluation: answers two questions before Vault test:
  Q1. Is PF 1.37 uniform across strategies, or dragged by weak outliers?
  Q2. Does PF survive realistic cost stress (1x / 1.5x / 2x / 3x costs)?

Usage:
    python scripts/pf_analysis.py                       # auto-detect CSV
    python scripts/pf_analysis.py path/to/trades.csv    # explicit path

Expected CSV schema (column names, order does not matter):
    ticker, strategy, direction, entry_time, entry_price, shares,
    exit_time, exit_price, exit_reason, stop, target, hmm_state,
    gross_pnl, total_costs, net_pnl

Outputs:
    Prints tables + verdict to stdout.
    Saves configs/pf_analysis_report.txt and configs/pf_analysis_cost_stress.csv
    next to the input CSV's parent configs/ dir (or cwd/configs/).

No engine imports. Requires: pandas, numpy (stdlib only otherwise).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Tuple

import pandas as pd


# ── Profit-factor primitives ──────────────────────────────────────────────────

def profit_factor(net_pnls: pd.Series) -> float:
    """
    PF = gross_wins / abs(gross_losses).
    A trade is a win if net_pnl > 0 (strict).
    Returns inf if there are zero losing trades.
    Returns 0.0 if there are zero winning trades.
    """
    wins   = net_pnls[net_pnls > 0].sum()
    losses = net_pnls[net_pnls <= 0].sum()   # <= 0, so sum is non-positive
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / abs(losses))


def stressed_pf(gross_pnl: pd.Series, total_costs: pd.Series, mult: float) -> float:
    """Recompute PF after scaling total_costs by `mult`."""
    stressed_net = gross_pnl - total_costs * mult
    return profit_factor(stressed_net)


# ── CSV auto-detection ────────────────────────────────────────────────────────

def _find_default_csv() -> Optional[str]:
    """
    Search common locations for the most recent WFO trade log CSV.
    Priority: newest wfo_trade_log.csv > newest per_strategy_trades.csv.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    candidates: List[str] = []
    # Walk up to find configs/ directories relative to script location
    for base in [
        script_dir,
        os.path.join(script_dir, "..", ".."),          # raits/raits/
        os.path.join(script_dir, "..", "..", ".."),    # raits/
    ]:
        cfgdir = os.path.abspath(os.path.join(base, "configs"))
        if os.path.isdir(cfgdir):
            for name in ("wfo_trade_log.csv", "per_strategy_trades.csv"):
                p = os.path.join(cfgdir, name)
                if os.path.isfile(p):
                    candidates.append(p)

    if not candidates:
        return None
    # Return the most recently modified file
    return max(candidates, key=os.path.getmtime)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _flag(pf_val: float) -> str:
    if pf_val == float("inf"):
        return "[INF]"
    if pf_val < 1.0:
        return "[LOSING]"
    if pf_val < 1.2:
        return "[DRAG]"
    return ""


def _hline(widths: List[int], char: str = "-") -> str:
    return "-+-".join(char * w for w in widths)


def _fmt(val, fmt: str) -> str:
    try:
        return format(val, fmt)
    except (TypeError, ValueError):
        return str(val)


# ── Output 1: per-strategy PF table ──────────────────────────────────────────

def per_strategy_table(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    """
    Returns (summary_df, table_string).
    summary_df has columns: strategy, n_trades, win_rate, gross_pnl_total,
    net_pnl_total, avg_win, avg_loss, profit_factor, pct_net_profit, flag.
    """
    rows = []
    total_net = df["net_pnl"].sum()

    for strat, grp in df.groupby("strategy"):
        wins   = grp[grp["net_pnl"] > 0]
        losses = grp[grp["net_pnl"] <= 0]
        pf_val = profit_factor(grp["net_pnl"])
        net    = grp["net_pnl"].sum()
        rows.append({
            "strategy":       strat,
            "n_trades":       len(grp),
            "win_rate":       len(wins) / len(grp) if len(grp) else 0.0,
            "gross_pnl_total": grp["gross_pnl"].sum(),
            "net_pnl_total":  net,
            "avg_win":        wins["net_pnl"].mean() if len(wins) else 0.0,
            "avg_loss":       losses["net_pnl"].mean() if len(losses) else 0.0,
            "profit_factor":  pf_val,
            "pct_net_profit": net / total_net * 100 if total_net != 0 else 0.0,
            "flag":           _flag(pf_val),
        })

    # Overall row
    wins_all   = df[df["net_pnl"] > 0]
    losses_all = df[df["net_pnl"] <= 0]
    pf_overall = profit_factor(df["net_pnl"])
    rows.append({
        "strategy":        "OVERALL",
        "n_trades":        len(df),
        "win_rate":        len(wins_all) / len(df) if len(df) else 0.0,
        "gross_pnl_total": df["gross_pnl"].sum(),
        "net_pnl_total":   total_net,
        "avg_win":         wins_all["net_pnl"].mean() if len(wins_all) else 0.0,
        "avg_loss":        losses_all["net_pnl"].mean() if len(losses_all) else 0.0,
        "profit_factor":   pf_overall,
        "pct_net_profit":  100.0,
        "flag":            _flag(pf_overall),
    })

    summary = pd.DataFrame(rows)
    strategy_rows = summary[summary["strategy"] != "OVERALL"].sort_values(
        "net_pnl_total", ascending=False
    )
    overall_row = summary[summary["strategy"] == "OVERALL"]
    summary = pd.concat([strategy_rows, overall_row], ignore_index=True)

    # Build string table
    header = (
        f"{'Strategy':<14} {'N':>6} {'WinRate':>8} {'GrossPnL':>10} "
        f"{'NetPnL':>10} {'AvgWin':>8} {'AvgLoss':>9} {'PF':>6} {'%Net':>6}  Flag"
    )
    sep = "-" * len(header)
    lines = [sep, header, sep]
    for _, r in summary.iterrows():
        marker = "=" if r["strategy"] == "OVERALL" else " "
        lines.append(
            f"{marker}{r['strategy']:<13} {r['n_trades']:>6d} {r['win_rate']:>7.1%} "
            f"${r['gross_pnl_total']:>9,.0f} ${r['net_pnl_total']:>9,.0f} "
            f"${r['avg_win']:>7,.0f} ${r['avg_loss']:>8,.0f} "
            f"{r['profit_factor']:>6.2f} {r['pct_net_profit']:>5.1f}%  {r['flag']}"
        )
    lines.append(sep)

    # One-line read
    strat_pfs = summary[summary["strategy"] != "OVERALL"]["profit_factor"]
    pf_min = strat_pfs.min()
    pf_max = strat_pfs.max()
    pf_range = pf_max - pf_min
    drag_strats = summary[
        (summary["strategy"] != "OVERALL") & (summary["profit_factor"] < 1.2)
    ]["strategy"].tolist()
    losing_strats = summary[
        (summary["strategy"] != "OVERALL") & (summary["profit_factor"] < 1.0)
    ]["strategy"].tolist()

    if pf_range < 0.30 and pf_min >= 1.2:
        read = (
            f"READ: PF is UNIFORM -- all strategies in [{pf_min:.2f}, {pf_max:.2f}], "
            f"spread={pf_range:.2f}. No structural drag detected."
        )
    else:
        parts = []
        if drag_strats:
            parts.append(f"DRAG ({', '.join(drag_strats)}, PF<1.2)")
        if losing_strats:
            parts.append(f"LOSING ({', '.join(losing_strats)}, PF<1.0)")
        read = (
            f"READ: PF shows DISPERSION -- range [{pf_min:.2f}, {pf_max:.2f}], "
            f"spread={pf_range:.2f}."
        )
        if parts:
            read += " Flagged: " + "; ".join(parts) + "."

    lines += ["", read]
    return summary, "\n".join(lines)


# ── Output 2: cost stress test ────────────────────────────────────────────────

COST_MULTIPLIERS = [1.0, 1.5, 2.0, 3.0]


def cost_stress_table(df: pd.DataFrame, summary: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    """
    Returns (stress_df, table_string).
    stress_df has: multiplier, overall_pf, overall_net_pnl, strategies_below_1_0.
    """
    strategies = summary[summary["strategy"] != "OVERALL"]["strategy"].tolist()

    avg_cost_per_trade = df["total_costs"].mean()
    # avg cost as % of gross win among winning trades
    gross_wins = df[df["net_pnl"] > 0]["gross_pnl"]
    avg_cost_pct_gross_win = (df["total_costs"].mean() / gross_wins.mean() * 100) if len(gross_wins) else 0.0

    rows = []
    for mult in COST_MULTIPLIERS:
        overall = stressed_pf(df["gross_pnl"], df["total_costs"], mult)
        net_total = (df["gross_pnl"] - df["total_costs"] * mult).sum()
        below = []
        for strat in strategies:
            g = df[df["strategy"] == strat]
            if len(g) == 0:
                continue
            spf = stressed_pf(g["gross_pnl"], g["total_costs"], mult)
            if spf < 1.0:
                below.append(strat)
        rows.append({
            "multiplier":         mult,
            "overall_pf":         overall,
            "overall_net_pnl":    net_total,
            "strategies_below_1": "; ".join(below) if below else "(none)",
        })

    stress_df = pd.DataFrame(rows)

    # String table
    header = (
        f"{'Mult':>6} {'Overall_PF':>11} {'Net_PnL':>10}  "
        f"Strategies with PF < 1.0 at this cost level"
    )
    sep = "-" * max(len(header), 80)
    lines = [
        f"Avg cost/trade:       ${avg_cost_per_trade:.2f}",
        f"Avg cost as % gross win: {avg_cost_pct_gross_win:.1f}%",
        "",
        sep, header, sep,
    ]
    for _, r in stress_df.iterrows():
        marker = ">>>" if r["multiplier"] == 2.0 else "   "
        lines.append(
            f"{marker} {r['multiplier']:>4.1f}x  {r['overall_pf']:>10.4f} "
            f"${r['overall_net_pnl']:>9,.0f}  {r['strategies_below_1']}"
        )
    lines.append(sep)

    # One-line read
    pf_2x = stress_df.loc[stress_df["multiplier"] == 2.0, "overall_pf"].iloc[0]
    below_2x = stress_df.loc[stress_df["multiplier"] == 2.0, "strategies_below_1"].iloc[0]
    if pf_2x >= 1.0:
        read = (
            f"READ: System stays PROFITABLE at 2x costs (PF={pf_2x:.2f}). "
            f"Edge is not cost-fragile at realistic real-world slippage."
        )
        if below_2x != "(none)":
            read += f" Individual strategies below PF 1.0 at 2x: {below_2x}."
    else:
        read = (
            f"READ: System turns UNPROFITABLE at 2x costs (PF={pf_2x:.2f}). "
            f"Edge may be cost-fragile -- real slippage on high-beta names could erase it."
        )

    lines += ["", read]
    return stress_df, "\n".join(lines)


# ── Output 3: verdict ─────────────────────────────────────────────────────────

def verdict(
    df: pd.DataFrame,
    summary: pd.DataFrame,
    stress_df: pd.DataFrame,
    overall_pf: float,
) -> str:
    strategies = summary[summary["strategy"] != "OVERALL"]
    drag_strats = strategies[strategies["profit_factor"] < 1.2]["strategy"].tolist()
    losing_strats = strategies[strategies["profit_factor"] < 1.0]["strategy"].tolist()

    pf_min = strategies["profit_factor"].min()
    pf_max = strategies["profit_factor"].max()
    pf_range = pf_max - pf_min
    uniform = pf_range < 0.30 and pf_min >= 1.2

    pf_2x = stress_df.loc[stress_df["multiplier"] == 2.0, "overall_pf"].iloc[0]
    survives_2x = pf_2x >= 1.0

    lines = ["=" * 70, "VERDICT (blueprint Section 8.1 re-evaluation)", "=" * 70, ""]

    lines.append(f"Stitched PF: {overall_pf:.4f}  |  Aspirational target: 1.75 (Section 8.1)")
    lines.append(f"Revised Tier-1 threshold: 1.35  |  Tier-2 threshold: 1.20")
    tier = "TIER-1" if overall_pf > 1.35 else ("TIER-2" if overall_pf > 1.20 else "BELOW-TIER-2")
    lines.append(f"Current standing: {tier}")
    lines.append("")

    no_drag = not drag_strats  # all strategies above PF 1.2

    if survives_2x and no_drag:
        # Safe path: all strategies above PF 1.2 AND edge survives 2x costs.
        # Dispersion, if any, is driven by outperformers, not by weak strategies dragging.
        if not uniform:
            top = strategies.nlargest(1, "profit_factor").iloc[0]
            dispersion_note = (
                f"Spread driven by {top['strategy']} outperforming "
                f"(PF={top['profit_factor']:.2f}), not by weak strategies dragging. "
                f"No strategy below PF 1.2."
            )
        else:
            dispersion_note = "All strategies tightly clustered."

        tier_str = "TIER-1" if overall_pf > 1.35 else ("TIER-2" if overall_pf > 1.20 else "BELOW-TIER-2")
        lines.append(
            f"PF={overall_pf:.4f} is structurally BENIGN for a high-frequency\n"
            f"trailing-stop system. Below 1.75 aspirational is expected for this design\n"
            f"(Chandelier trailing stop, ~50% WR, mixed intraday/swing).\n\n"
            f"Dispersion note: {dispersion_note}\n\n"
            f"Cost robustness: PF={pf_2x:.4f} at 2x costs -- edge is NOT cost-fragile.\n\n"
            f"RECOMMENDATION: Safe to proceed to Vault.\n"
            f"Current standing: {tier_str} (Tier-1 PF>1.35, Tier-2 PF>1.20).\n"
            f"Vault will give the final tier verdict."
        )
    else:
        if drag_strats:
            df_no_drag = df[~df["strategy"].isin(drag_strats)]
            pf_no_drag = profit_factor(df_no_drag["net_pnl"])
            lines.append(
                f"DISPERSION WITH DRAG. Strategies below PF 1.2:\n"
                f"  {', '.join(drag_strats)}\n"
            )
            if losing_strats:
                lines.append(f"  LOSING strategies (PF < 1.0): {', '.join(losing_strats)}\n")
            lines.append(
                f"  PF without DRAG strategies: {pf_no_drag:.4f}\n\n"
                f"RECOMMENDATION: Re-examine logic of {', '.join(drag_strats)} BEFORE Vault.\n"
                f"A structural reason is required -- do NOT drop them purely for the number.\n"
                f"If no structural fix exists, document the drag and proceed with awareness."
            )

        if not survives_2x:
            lines.append(
                f"\nCOST FRAGILITY WARNING: System turns unprofitable at 2x costs "
                f"(PF={pf_2x:.4f}).\n"
                f"Real slippage on high-beta single names could erase the edge.\n"
                f"Consider: tighter entry criteria, limit orders, or reducing universe\n"
                f"to lower-beta names before Vault."
            )

    lines += ["", "=" * 70]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def _find_configs_dir(csv_path: str) -> str:
    """Return the configs/ directory to save output files into."""
    parent = os.path.dirname(os.path.abspath(csv_path))
    # If CSV lives in configs/, use that; else create configs/ next to it
    if os.path.basename(parent).lower() == "configs":
        return parent
    candidate = os.path.join(parent, "configs")
    os.makedirs(candidate, exist_ok=True)
    return candidate


def run(csv_path: str) -> None:
    print(f"\nReading trade log: {csv_path}")
    df = pd.read_csv(csv_path, parse_dates=["entry_time", "exit_time"])

    required = {"ticker", "strategy", "gross_pnl", "total_costs", "net_pnl"}
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"ERROR: CSV missing required columns: {missing}")

    n = len(df)
    overall_pf = profit_factor(df["net_pnl"])
    print(f"Loaded {n} trades  |  Overall PF = {overall_pf:.4f}\n")

    divider = "\n" + "=" * 70 + "\n"

    # ── Output 1 ─────────────────────────────────────────────────────────────
    print(divider.strip())
    print("OUTPUT 1 -- PROFIT FACTOR PER STRATEGY")
    print("=" * 70)
    summary, table1 = per_strategy_table(df)
    print(table1)

    # ── Output 2 ─────────────────────────────────────────────────────────────
    print(divider.strip())
    print("OUTPUT 2 -- COST STRESS TEST")
    print("=" * 70)
    stress_df, table2 = cost_stress_table(df, summary)
    print(table2)

    # ── Output 3 ─────────────────────────────────────────────────────────────
    print(divider.strip())
    v = verdict(df, summary, stress_df, overall_pf)
    print(v)

    # ── Save outputs ──────────────────────────────────────────────────────────
    configs_dir = _find_configs_dir(csv_path)

    report_path = os.path.join(configs_dir, "pf_analysis_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"Trade log: {csv_path}\n")
        f.write(f"Trades: {n}  |  Overall PF: {overall_pf:.4f}\n\n")
        f.write("OUTPUT 1 -- PF PER STRATEGY\n")
        f.write(table1 + "\n\n")
        f.write("OUTPUT 2 -- COST STRESS TEST\n")
        f.write(table2 + "\n\n")
        f.write(v + "\n")
    print(f"\n[Saved] {report_path}")

    stress_csv = os.path.join(configs_dir, "pf_analysis_cost_stress.csv")
    stress_df.to_csv(stress_csv, index=False)
    print(f"[Saved] {stress_csv}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAITS standalone PF analysis -- Section 8.1 re-evaluation"
    )
    parser.add_argument(
        "csv_path",
        nargs="?",
        help="Path to trade-log CSV. Auto-detected if omitted.",
    )
    args = parser.parse_args()

    csv_path = args.csv_path
    if csv_path is None:
        csv_path = _find_default_csv()
        if csv_path is None:
            sys.exit(
                "ERROR: No trade-log CSV found. Pass the path explicitly:\n"
                "  python scripts/pf_analysis.py path/to/trades.csv\n"
                "Or run export_trade_log.py first to generate wfo_trade_log.csv."
            )
        print(f"[Auto-detected] {csv_path}")

    if not os.path.isfile(csv_path):
        sys.exit(f"ERROR: File not found: {csv_path}")

    run(csv_path)


if __name__ == "__main__":
    main()
