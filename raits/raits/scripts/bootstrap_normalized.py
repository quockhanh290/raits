"""
scripts/bootstrap_normalized.py
---------------------------------
Bootstrap on R-multiples (normalized edge) vs dollar net_pnl (scale-contaminated).

METHODOLOGY
  The continuous IS design uses Kelly=0.75 + compounding: position size scales with
  account equity at each trade's time. This means dollar P&L is non-homogeneous across
  trades — a trade at $60k equity produces larger dollar swings than the same trade at
  $50k equity. Bootstrapping raw dollar P&L mixes trades at different scales AND breaks
  path dependency (the order of trades determines equity at entry).

  The correct test for STRATEGY EDGE is scale-independent:
    R-multiple = net_pnl / initial_risk
    initial_risk = shares * |entry_price - stop|
  This measures: "for each dollar of risk taken, what is the average return?"
  R-multiple is independent of account equity, Kelly fraction, and compounding.

  These are two DIFFERENT questions:
    "Does strategy X have edge?"          -> R-multiple bootstrap (this script)
    "How much does the system earn?"      -> equity-curve metrics (Calmar/Sharpe)
  Dollar per-trade bootstrap conflates both and is biased.

Input: baselines/is_baseline_cb_fixed_2026-07-08.csv (605 trades, full columns)
Same H0: mean(R) <= 0  (one-sided, N_BOOT=10,000, seed=42)
Verdict thresholds: CONFIRMED p<0.05 | BORDERLINE p<0.15 | NO EDGE p>=0.15

Usage (from d:\\raits\\raits):
    python raits/scripts/bootstrap_normalized.py
    python raits/scripts/bootstrap_normalized.py --n-boot 10000 --seed 42

Output: configs/bootstrap_normalized_report.txt
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np

N_BOOT_DEFAULT = 10_000
SEED_DEFAULT   = 42
_BASELINE_CSV  = _ROOT / "baselines" / "is_baseline_cb_fixed_2026-07-08.csv"

# Dollar-based p-values from bootstrap_continuous.py (for comparison)
_DOLLAR_P: Dict[str, float] = {
    "TREND_FOLLOW": 0.116,
    "ORB":          0.329,
    "STRESS_ORB":   0.215,
    "PE_SHORT":     0.011,
    "GF_SHORT":     0.010,
    "STRESS_MID":   0.401,
    "FADE":         0.997,
    "GAP_FILL":     0.100,
    "VWAP_MR":      0.889,
}


def verdict(p: float) -> str:
    if p < 0.05:
        return "CONFIRMED"
    if p < 0.15:
        return "BORDERLINE"
    return "NO EDGE"


def bootstrap_p(values: np.ndarray, n_boot: int, rng: np.random.Generator) -> float:
    if len(values) == 0 or values.mean() == 0:
        return 1.0
    boot_means = rng.choice(values, size=(n_boot, len(values)), replace=True).mean(axis=1)
    return float((boot_means <= 0).mean())


def compute_r(ep: float, sh: int, stop: float, pnl: float) -> float | None:
    """R-multiple = net_pnl / initial_risk. Returns None if risk is degenerate."""
    risk = sh * abs(ep - stop)
    if risk < 0.01:
        return None
    return pnl / risk


def load_csv(path: Path) -> Dict[str, Dict[str, List]]:
    """Returns {strategy: {'dollar': [...], 'R': [...], 'risk': [...]}}."""
    by_strat: Dict[str, Dict[str, List]] = {}
    skipped = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = row.get("strategy", "").strip()
            if not s:
                continue
            try:
                ep   = float(row["entry_price"])
                sh   = int(row["shares"])
                stop = float(row["stop"])
                pnl  = float(row["net_pnl"])
            except (ValueError, KeyError):
                skipped += 1
                continue
            R = compute_r(ep, sh, stop, pnl)
            if R is None:
                skipped += 1
                continue
            risk = sh * abs(ep - stop)
            d = by_strat.setdefault(s, {"dollar": [], "R": [], "risk": []})
            d["dollar"].append(pnl)
            d["R"].append(R)
            d["risk"].append(risk)
    if skipped:
        print(f"  [warning] skipped {skipped} rows (missing columns or zero risk)",
              file=sys.stderr)
    return by_strat


def cohen_d(values: np.ndarray) -> float:
    if len(values) < 2:
        return float("nan")
    return float(values.mean() / values.std(ddof=1))


def run(csv_path: Path, n_boot: int, seed: int) -> str:
    by_strat = load_csv(csv_path)
    rng      = np.random.default_rng(seed)

    SEP  = "=" * 95
    SEP2 = "-" * 95

    lines = [
        "Bootstrap — NORMALIZED (R-multiple) vs DOLLAR per-trade P&L",
        f"Baseline : {csv_path.name}  (605 trades, continuous IS 2017-2022)",
        f"N_BOOT={n_boot}  seed={seed}",
        f"R-multiple = net_pnl / (shares * |entry_price - stop|)",
        f"H0: mean(R) <= 0  |  same threshold as dollar bootstrap",
        "",
        "STEP 1 — METHODOLOGY DIAGNOSIS",
        "-" * 60,
        "Dollar bootstrap problem: Kelly=0.75 + compounding -> position size scales with",
        "equity at each trade. Dollar P&L from different equity levels is NOT homogeneous.",
        "A trade at $60k equity has ~20% larger positions than the same trade at $50k.",
        "Bootstrapping raw dollar P&L treats these as comparable — they are not.",
        "",
        "R-multiple fix: initial_risk = shares * |entry_price - stop| is set at entry",
        "and reflects the actual dollar at risk regardless of equity level.",
        "R = net_pnl / initial_risk is scale-independent — the same entry/exit logic",
        "produces the same R regardless of position size or account equity.",
        "",
    ]

    # ── Per-strategy stats ────────────────────────────────────────────────────
    lines.append("STEP 2 — R-MULTIPLE STATISTICS BY STRATEGY")
    lines.append(SEP2)
    hdr = (f"{'Strategy':<14} {'N':>4} {'Mean$':>8} {'MeanR':>7} {'StdR':>7} "
           f"{'d_R':>6} {'avg_risk':>9}")
    lines.append(hdr)
    lines.append(SEP2)

    strat_stats = {}
    for strat in sorted(by_strat.keys()):
        d   = by_strat[strat]
        arr_dollar = np.array(d["dollar"])
        arr_R      = np.array(d["R"])
        arr_risk   = np.array(d["risk"])
        n          = len(arr_R)
        mean_d = arr_dollar.mean() if n else 0.0
        mean_R = arr_R.mean()      if n else 0.0
        std_R  = arr_R.std(ddof=1) if n > 1 else 0.0
        cd_R   = cohen_d(arr_R)
        avg_risk = arr_risk.mean() if n else 0.0
        strat_stats[strat] = (arr_dollar, arr_R, n, mean_d, mean_R, std_R, cd_R, avg_risk)
        lines.append(
            f"{strat:<14} {n:>4} {mean_d:>+8.2f} {mean_R:>+7.4f} {std_R:>7.4f} "
            f"{cd_R:>+6.3f} {avg_risk:>9.2f}"
        )
    lines.append(SEP2)
    lines.append("")

    # ── Bootstrap comparison ─────────────────────────────────────────────────
    lines.append("STEP 3 — BOOTSTRAP COMPARISON: DOLLAR vs R-MULTIPLE")
    lines.append(SEP)
    hdr2 = (f"{'Strategy':<14} {'N':>4}  "
            f"{'Dollar p':>8} {'Dollar v':>10}  "
            f"{'R p':>8} {'R verdict':>10}  "
            f"{'Delta':>8}  Verdict change?")
    lines.append(hdr2)
    lines.append(SEP)

    verdicts = []
    for strat in sorted(by_strat.keys()):
        arr_dollar, arr_R, n, mean_d, mean_R, std_R, cd_R, avg_risk = strat_stats[strat]

        p_dollar = _DOLLAR_P.get(strat, float("nan"))
        p_R      = bootstrap_p(arr_R, n_boot, rng)

        v_dollar = verdict(p_dollar) if not (p_dollar != p_dollar) else "—"
        v_R      = verdict(p_R)
        delta    = p_R - p_dollar if not (p_dollar != p_dollar) else float("nan")

        # Classify change
        change = ""
        if v_dollar != "—" and v_dollar != v_R:
            if (v_dollar in ("CONFIRMED", "NO EDGE")) and (v_R in ("CONFIRMED", "NO EDGE")) and v_dollar != v_R:
                change = "*** FLIP"
            else:
                change = "* partial"

        delta_str = f"{delta:+.3f}" if delta == delta else "—"
        lines.append(
            f"{strat:<14} {n:>4}  "
            f"{p_dollar:>8.3f} {v_dollar:>10}  "
            f"{p_R:>8.3f} {v_R:>10}  "
            f"{delta_str:>8}  {change}"
        )
        verdicts.append((strat, n, p_dollar, v_dollar, p_R, v_R, change, cd_R))

    lines.append(SEP)
    lines.append("")

    # ── STEP 4 framing ───────────────────────────────────────────────────────
    lines.append("STEP 4 — WHAT EACH TEST ANSWERS")
    lines.append("-" * 60)
    lines.append("  R-multiple bootstrap (this script):")
    lines.append("    H0: mean(R) <= 0  -> 'Does the strategy generate positive expected")
    lines.append("    value per unit of risk, independent of position size and compounding?'")
    lines.append("    This is the correct test for EDGE — scale-independent, path-independent.")
    lines.append("")
    lines.append("  Dollar bootstrap (bootstrap_continuous.py):")
    lines.append("    H0: mean(dollar_pnl) <= 0  -> conflates edge with compounding scale.")
    lines.append("    Trades at higher equity (larger positions) have disproportionate weight.")
    lines.append("    Underestimates edge if strategy performs better early (low-equity phase);")
    lines.append("    overestimates if strategy performs better late (high-equity phase).")
    lines.append("    NOT the right test for 'does the strategy have edge.'")
    lines.append("")
    lines.append("  Equity-curve metrics (Calmar, Sharpe):")
    lines.append("    DO correctly account for compounding and path dependency.")
    lines.append("    Right for 'how much does the compounded system earn?' — not per-trade.")
    lines.append("")

    # ── Verdict summary ──────────────────────────────────────────────────────
    lines.append("VERDICT SUMMARY (R-multiple bootstrap = correct edge test)")
    lines.append("-" * 60)
    for strat, n, p_d, v_d, p_R, v_R, change, cd_R in verdicts:
        note = ""
        delta = p_R - p_d if p_d == p_d else float("nan")
        if delta == delta:
            if abs(delta) < 0.02:
                note = "(dollar and R-multiple agree — scale artifact minimal)"
            elif delta < 0:
                note = "(R-multiple STRONGER than dollar — dollar underestimated edge)"
            else:
                note = "(R-multiple WEAKER than dollar — dollar compounding inflated edge)"
        lines.append(
            f"  {strat:<14} N={n:<3} d={cd_R:+.3f}  R-p={p_R:.3f} -> {v_R:<10} {note}"
        )

    lines.append("")
    lines.append("ANSWER TO METHODOLOGY QUESTION")
    lines.append("-" * 60)

    # Specific analysis of TF
    tf = next((x for x in verdicts if x[0] == "TREND_FOLLOW"), None)
    if tf:
        _, n_tf, p_d_tf, v_d_tf, p_R_tf, v_R_tf, _, cd_tf = tf
        if p_R_tf < p_d_tf - 0.02:
            tf_finding = (f"  TF: R-p={p_R_tf:.3f} vs dollar-p={p_d_tf:.3f} -> "
                          f"dollar UNDERSTATED TF edge (TF performed better early when equity was low).\n"
                          f"  The 'weakness on continuous' was partly a compounding-scale artifact.")
        elif p_R_tf > p_d_tf + 0.02:
            tf_finding = (f"  TF: R-p={p_R_tf:.3f} vs dollar-p={p_d_tf:.3f} -> "
                          f"dollar OVERSTATED TF edge (TF performed better later, amplified by compounding).\n"
                          f"  The 'weakness on continuous' understates the actual edge decline.")
        else:
            tf_finding = (f"  TF: R-p={p_R_tf:.3f} vs dollar-p={p_d_tf:.3f} -> "
                          f"scale artifact is MINIMAL for TF.\n"
                          f"  The borderline verdict p={p_R_tf:.3f} is genuine, not a compounding artifact.")
        lines.append(tf_finding)
    lines.append("")

    orb = next((x for x in verdicts if x[0] == "ORB"), None)
    sorb = next((x for x in verdicts if x[0] == "STRESS_ORB"), None)
    if orb and sorb:
        orb_hold = v_R_tf is not None  # will be set
        orb_v = orb[5]; sorb_v = sorb[5]
        lines.append(
            f"  ORB: R-verdict={orb_v} (dollar: {orb[3]}). "
            + ("No-edge verdict confirmed on R-multiple." if orb_v == "NO EDGE"
               else "Dollar no-edge verdict REVERSED on R-multiple — edge may be real.")
        )
        lines.append(
            f"  STRESS_ORB: R-verdict={sorb_v} (dollar: {sorb[3]}). "
            + ("No-edge verdict confirmed on R-multiple." if sorb_v == "NO EDGE"
               else "Dollar no-edge verdict REVERSED on R-multiple.")
        )

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv",    default=str(_BASELINE_CSV))
    ap.add_argument("--n-boot", type=int, default=N_BOOT_DEFAULT)
    ap.add_argument("--seed",   type=int, default=SEED_DEFAULT)
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        sys.exit(1)

    report = run(csv_path, args.n_boot, args.seed)
    print(report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "bootstrap_normalized_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()