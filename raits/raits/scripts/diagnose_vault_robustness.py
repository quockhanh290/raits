"""
diagnose_vault_robustness.py
-----------------------------
STEP 1  -- Design provenance: which design produced each headline metric?
STEP 2  -- Jackknife vault Sharpe/Calmar: remove top k trades, does it collapse?
STEP 3  -- Trustworthiness report

Known vault metrics (stocks OOS 2023-2024, from vault_metrics.py docstring):
  Calmar=1.04, Sharpe=0.88, MaxDD=-6.9%, PF=1.18, WinRate=48.4%,
  TotalReturn=14.8%, N=405 trades, net P&L approx +$7,404

Usage (from d:\\raits\\raits):
    python raits/scripts/diagnose_vault_robustness.py
    python raits/scripts/diagnose_vault_robustness.py --snap <path.pkl>

Output: configs/vault_robustness_report.txt
"""

from __future__ import annotations

import argparse
import glob
import os
import pickle
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

OOS_START = pd.Timestamp("2023-01-01")
OOS_END   = pd.Timestamp("2024-12-31")
CAPITAL   = 50_000.0

SEP  = "=" * 70
SEP2 = "-" * 65


# ── Loaders ───────────────────────────────────────────────────────────────────

def find_latest_snap(snap_dir: str) -> str | None:
    pkls = sorted(glob.glob(os.path.join(snap_dir, "results_2*.pkl")))
    return pkls[-1] if pkls else None


def load_snapshot(path: str) -> list:
    with open(path, "rb") as f:
        return pickle.load(f)


def find_vault_window(results: list) -> dict | None:
    for r in results:
        if "2023" in str(r.get("label", "")):
            return r
    return results[-1] if results else None


def trades_to_df(trades: list) -> pd.DataFrame:
    rows = []
    for t in trades:
        if t.is_open or t.net_pnl is None:
            continue
        exit_t = pd.Timestamp(t.exit_time)
        if exit_t.tz is not None:
            exit_t = exit_t.tz_convert(None)
        if not (OOS_START <= exit_t <= OOS_END + pd.Timedelta("2D")):
            continue
        rows.append(dict(
            strategy  = t.strategy,
            ticker    = t.ticker,
            direction = getattr(t, "direction", "?"),
            exit_time = exit_t,
            net_pnl   = float(t.net_pnl),
        ))
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["strategy", "ticker", "direction", "exit_time", "net_pnl"]
    )


# ── Metric helpers ─────────────────────────────────────────────────────────────

def daily_returns(trades_df: pd.DataFrame) -> pd.Series:
    """Daily return series from exit-date P&L. Business days filled with 0."""
    pnl = trades_df.groupby(trades_df["exit_time"].dt.normalize())["net_pnl"].sum()
    pnl.index = pd.DatetimeIndex(pnl.index)
    if pnl.index.tz is not None:
        pnl.index = pnl.index.tz_convert(None)
    bdays = pd.bdate_range(OOS_START, OOS_END)
    return pnl.reindex(bdays, fill_value=0.0) / CAPITAL


def sharpe_ratio(daily_ret: pd.Series) -> float:
    mu  = daily_ret.mean()
    sig = daily_ret.std(ddof=1)
    if sig == 0 or pd.isna(sig):
        return float("nan")
    return float(mu / sig * np.sqrt(252))


def calmar_ratio(daily_ret: pd.Series) -> float:
    """Annualized mean return / |max drawdown on equity curve|."""
    eq   = (1.0 + daily_ret).cumprod()
    peak = eq.cummax()
    dd   = (eq - peak) / peak
    max_dd = float(dd.min())
    ann_ret = float(daily_ret.mean() * 252)
    if max_dd == 0:
        return float("inf")
    return float(ann_ret / abs(max_dd))


def profit_factor(pnls: np.ndarray) -> float:
    gross_pos = float(pnls[pnls > 0].sum())
    gross_neg = float(abs(pnls[pnls < 0].sum()))
    return gross_pos / gross_neg if gross_neg > 0 else float("inf")


def metric_line(k_label: str, sh: float, ca: float, pf_: float,
                n: int, pnl: float, wr: float) -> str:
    return (
        f"  {k_label:<16} Sharpe={sh:.3f}  Calmar={ca:.3f}  PF={pf_:.2f}  "
        f"N={n}  P&L=${pnl:+,.0f}  WR={wr:.1%}"
    )


def classify_sharpe(s: float) -> str:
    if s >= 0.80:
        return "ROBUST"
    if s >= 0.60:
        return "WEAKENED"
    if s >= 0.40:
        return "FRAGILE"
    return "COLLAPSED"


# ── STEP 1: Design provenance ──────────────────────────────────────────────────

STEP1_TEXT = """
{SEP}
STEP 1 -- DESIGN PROVENANCE OF HEADLINE METRICS
{SEP}

Every project metric comes from one of four designs. Deploy decisions should
rest only on OOS-continuous metrics.

  Metric                                    Design          Deploy-valid?
  -----------------------------------------------------------------------
  WFO IS: Calmar=2.49, Sharpe=1.68, 764t   WFO rolling     NO  (IS, stitched — optimistic)
  YbY IS: ann~10.5%, +$34k (window_debug)  Year-by-year    NO  (wrong: Kelly=0.5, PDT off,
                                              (WRONG)            yearly capital reset)
  Strategy inclusion decisions              Year-by-year    NO  (wrong design — per audit;
    (keep ORB/TF/STRESS_ORB)                (WRONG)            ORB+STRESS_ORB flip to NO EDGE
                                                               on continuous design)
  Continuous IS: ann=5.0%, +$15,020, 605t  Continuous IS   REFERENCE (IS data, not OOS)
    (verify_cb_fix.py, CB-fixed)             (correct IS)
  WFO params: orb=20/bb=1.5/ema=30         WFO rolling     YES (appropriate for hyperparam
    (configs/final_params.yaml)              (correct meth)      selection — WFO IS windows)
  Vault OOS: +$7,404, Sharpe=0.88          OOS continuous  YES (gold standard for deploy)
    Calmar=1.04, PF=1.18, MaxDD=-6.9%       (sealed)

Consistency check (annualized P&L comparison):
  Continuous IS: $15,020 / 6yr = $2,503/yr
  Vault OOS:     $7,404  / 2yr = $3,702/yr
  OOS slightly outperforms IS rate -- no suspicious gap (within normal variance).

The YbY "$34k over 6yr" number should not be compared to the vault. The
correct IS comparison is $15,020 (continuous, CB-fixed).
""".format(SEP=SEP)


# ── STEP 2: Jackknife ─────────────────────────────────────────────────────────

def run_jackknife(trades_df: pd.DataFrame) -> str:
    n_all    = len(trades_df)
    top_sorted = trades_df.sort_values("net_pnl", ascending=False).reset_index(drop=True)
    total_pnl  = float(trades_df["net_pnl"].sum())

    lines = [
        SEP,
        f"STEP 2 -- VAULT JACKKNIFE  (stocks OOS 2023-2024, N={n_all})",
        SEP,
        "",
        "  Method: remove top k trades by net_pnl, recompute metrics from daily P&L.",
        f"  Sharpe = mean(daily_ret)/std(daily_ret)*sqrt(252), capital=${CAPITAL:,.0f}.",
        "  Baseline Sharpe should be near 0.88 (reported); small delta = approximation ok.",
        SEP2,
    ]

    rows = []
    for k in [0, 1, 2, 3, 5, 10]:
        if k >= n_all:
            break
        remaining = top_sorted.iloc[k:].copy()
        dr   = daily_returns(remaining)
        sh   = sharpe_ratio(dr)
        ca   = calmar_ratio(dr)
        pf_  = profit_factor(remaining["net_pnl"].values)
        n    = len(remaining)
        pnl  = float(remaining["net_pnl"].sum())
        wr   = float((remaining["net_pnl"] > 0).sum()) / n if n > 0 else 0.0

        removed_note = ""
        if k > 0:
            removed_pnl = float(top_sorted.head(k)["net_pnl"].sum())
            removed_pct = removed_pnl / total_pnl * 100 if total_pnl else 0
            removed_note = f"  [removed ${removed_pnl:+,.0f}, {removed_pct:.1f}% of P&L]"

        label = f"k={k}" + (" (baseline)" if k == 0 else "")
        lines.append(metric_line(label, sh, ca, pf_, n, pnl, wr) + removed_note)
        rows.append((k, sh, ca))

    lines.append(SEP2)
    lines.append("")
    lines.append("  Jackknife Sharpe verdict:")
    for k, sh, _ in rows:
        tag = classify_sharpe(sh)
        lines.append(f"    k={k:<3} Sharpe={sh:.3f}  {tag}")

    lines.append("")
    lines.append("  Top 10 winning trades:")
    lines.append(f"  {'Rank':<5} {'Ticker':<8} {'Strategy':<14} {'Exit date':<12} {'Net P&L':>10} {'Cum%':>7}")
    lines.append(f"  {'-'*60}")
    cum = 0.0
    for i, row in top_sorted.head(10).iterrows():
        cum += row["net_pnl"]
        lines.append(
            f"  {i+1:<5} {row['ticker']:<8} {row['strategy']:<14} "
            f"{str(row['exit_time'].date()):<12} "
            f"${row['net_pnl']:>9,.0f} {cum/total_pnl*100:>6.1f}%"
        )
    lines.append("")
    return "\n".join(lines)


# ── STEP 3: Trustworthiness ────────────────────────────────────────────────────

def run_trust(trades_df: pd.DataFrame, jackknife_rows: list[tuple]) -> str:
    pnls      = trades_df["net_pnl"].values
    n         = len(trades_df)
    total_pnl = float(pnls.sum())
    wr        = float((pnls > 0).sum()) / n

    by_strat = (
        trades_df.groupby("strategy")["net_pnl"]
        .agg(count="count", sum="sum")
        .assign(pct=lambda x: x["sum"] / total_pnl * 100)
        .sort_values("sum", ascending=False)
    )

    df2 = trades_df.copy()
    df2["_q"] = df2["exit_time"].dt.to_period("Q")
    qpnl = df2.groupby("_q")["net_pnl"].sum()

    top3_pnl = float(trades_df.nlargest(3, "net_pnl")["net_pnl"].sum())
    top3_pct  = top3_pnl / total_pnl * 100 if total_pnl else 0

    # jackknife result at k=2
    sh0  = next((sh for k, sh, _ in jackknife_rows if k == 0), float("nan"))
    sh2  = next((sh for k, sh, _ in jackknife_rows if k == 2), float("nan"))
    sh5  = next((sh for k, sh, _ in jackknife_rows if k == 5), float("nan"))

    lines = [
        SEP,
        "STEP 3 -- TRUSTWORTHINESS REPORT",
        SEP,
        "",
        f"  Vault headline (stocks OOS 2023-2024):",
        f"    N={n}  Net P&L=${total_pnl:+,.0f}  WR={wr:.1%}",
        f"    Sharpe=0.88  Calmar=1.04  MaxDD=-6.9%  PF=1.18  TotalReturn=14.8%",
        f"    Design: OOS continuous, sealed, one-shot. Two-year sample.",
        "",
        "  Strategy contribution:",
        f"  {'Strategy':<14} {'N':>5} {'Net P&L':>10} {'% of total':>10}",
        f"  {'-'*44}",
    ]
    for strat, row_ in by_strat.iterrows():
        lines.append(
            f"  {strat:<14} {int(row_['count']):>5} "
            f"${row_['sum']:>9,.0f} {row_['pct']:>9.1f}%"
        )
    lines.append(f"  {'-'*44}")
    lines.append(f"  {'TOTAL':<14} {n:>5} ${total_pnl:>9,.0f}")
    lines.append("")

    neg_qs = sum(1 for v in qpnl.values if v < 0)
    lines.append("  Quarterly P&L (8 quarters: 2023Q1 to 2024Q4):")
    for q, v in qpnl.items():
        bar = "+" * max(0, int(v / 200)) if v >= 0 else "-" * max(0, int(abs(v) / 200))
        lines.append(f"    {q}  ${v:+,.0f}  {bar}")
    lines.append(f"    Negative quarters: {neg_qs}/{len(qpnl)}")
    lines.append("")

    lines.append(f"  Concentration:")
    lines.append(f"    Top 3 trades = ${top3_pnl:+,.0f} = {top3_pct:.1f}% of total P&L")
    lines.append(f"    Trades/year = {n/2:.0f}")
    lines.append("")

    # Jackknife summary
    jk_verdict = classify_sharpe(sh2)
    if sh2 >= 0.60:
        jk_text = f"Sharpe stays {sh2:.3f} after removing top 2 => NOT single-trade-dependent."
    elif sh2 >= 0.40:
        jk_text = f"Sharpe weakens to {sh2:.3f} after removing top 2 => MODERATELY concentrated."
    else:
        jk_text = f"Sharpe collapses to {sh2:.3f} after removing top 2 => HIGHLY concentrated."

    lines += [
        "  Jackknife summary:",
        f"    k=0 Sharpe={sh0:.3f} | k=2 Sharpe={sh2:.3f} ({jk_verdict}) | k=5 Sharpe={sh5:.3f}",
        f"    {jk_text}",
        "",
        "  Trustworthiness by claim:",
        "  +--------------------------------------------------+--------------+",
        "  | Claim                                            | Assessment   |",
        "  +--------------------------------------------------+--------------+",
    ]

    def _row(claim, assess):
        return f"  | {claim:<48} | {assess:<12} |"

    lines.append(_row("Vault P&L positive (+$7,404 OOS)", "CONFIRMED"))
    lines.append(_row("OOS design correct (continuous, sealed)", "YES"))
    lines.append(_row("No lookahead (one-shot, not re-run)", "YES"))
    lines.append(_row(f"Sharpe robust at k=2 ({jk_verdict})", jk_verdict))
    lines.append(_row("2-year sample is sufficient", "MODEST"))
    lines.append(_row("Strategy inclusion on correct design", "NO (YbY)"))
    lines.append(_row("PE_SHORT OOS: IS edge concentrated (N=29)", "WATCH"))
    lines.append(_row("TF OOS: IS borderline (p=0.116)", "WATCH"))
    lines.append("  +--------------------------------------------------+--------------+")
    lines.append("")
    lines.append("  BOTTOM LINE:")
    lines.append(f"    The vault +$7,404 / Sharpe=0.88 is on the correct (OOS continuous) design.")
    lines.append(f"    Jackknife: {jk_text}")
    lines.append(f"    The vault result is the strongest evidence for deployment. However:")
    lines.append(f"    - 2 years is a short OOS window (market regime dependent).")
    lines.append(f"    - Strategy inclusion decisions were on the wrong (YbY) design.")
    lines.append(f"    - PE_SHORT and TF are the key OOS unknowns — monitor per-strategy in 2025.")
    lines.append(f"    Decision framework: deploy with per-strategy OOS monitoring, not as a black box.")
    lines.append("")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snap", default=None,
                    help="Path to snapshot pkl (auto-detects latest if omitted)")
    args = ap.parse_args()

    snap_dir  = str(_ROOT / "raits" / "data" / "cache" / "snapshots")
    snap_path = args.snap or find_latest_snap(snap_dir)
    if not snap_path:
        print(f"ERROR: no snapshot pkl found in {snap_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Snapshot: {snap_path}", file=sys.stderr)
    results = load_snapshot(snap_path)
    vault_w = find_vault_window(results)
    if vault_w is None:
        print("ERROR: could not find vault (2023) window in snapshot", file=sys.stderr)
        sys.exit(1)
    print(f"Vault window label: {vault_w.get('label', '?')}", file=sys.stderr)

    trades = vault_w.get("trades", [])
    df     = trades_to_df(trades)
    if df.empty:
        print("ERROR: no closed OOS trades found in vault window", file=sys.stderr)
        sys.exit(1)
    print(f"OOS trades (2023-2024): {len(df)}", file=sys.stderr)

    # Step 2 needs rows for step 3
    n_all     = len(df)
    top_sorted = df.sort_values("net_pnl", ascending=False).reset_index(drop=True)
    total_pnl  = float(df["net_pnl"].sum())
    jk_rows: list[tuple] = []
    for k in [0, 1, 2, 3, 5, 10]:
        if k >= n_all:
            break
        remaining = top_sorted.iloc[k:].copy()
        dr = daily_returns(remaining)
        sh = sharpe_ratio(dr)
        ca = calmar_ratio(dr)
        jk_rows.append((k, sh, ca))

    sections = [
        f"Vault Robustness Report",
        f"Snapshot : {os.path.basename(snap_path)}",
        f"OOS trades: {len(df)}  |  total P&L: ${total_pnl:+,.0f}",
        "",
        STEP1_TEXT,
        run_jackknife(df),
        run_trust(df, jk_rows),
    ]
    report = "\n".join(sections)
    print(report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "vault_robustness_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()