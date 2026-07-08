"""
scripts/bootstrap_continuous.py
--------------------------------
Bootstrap p-values for the CONTINUOUS IS design (2017-2022, single run,
Kelly=0.75, PDT on, MAX_TREND=3).

The ORIGINAL bootstrap (bootstrap_strategy.py) ran on the YEAR-BY-YEAR
design from window_debug.py:  capital reset yearly, PDT off, Kelly=0.5.
The deployed system is CONTINUOUS. This script re-runs the same bootstrap
test on the 605-trade continuous-IS baseline to check whether the
accept/reject verdicts hold under the deployed design.

Input: baselines/is_baseline_cb_fixed_2026-07-08.csv
  (committed baseline; survives cache wipe)

Same hypothesis as bootstrap_strategy.py:
  H0 per strategy: mean(net_pnl) <= 0
  p-value = fraction of N_BOOT resamples where resample_mean <= 0
  Verdict: CONFIRMED (p<0.05) | BORDERLINE (p<0.15) | NO EDGE (p>=0.15)

Usage (from d:\\raits\\raits):
    python raits/scripts/bootstrap_continuous.py
    python raits/scripts/bootstrap_continuous.py --n-boot 10000 --seed 42

Output:
  - prints side-by-side comparison with year-by-year verdicts
  - saves configs/bootstrap_continuous_report.txt
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np

N_BOOT_DEFAULT = 10_000
SEED_DEFAULT   = 42

# Committed baseline (survives cache wipe)
_BASELINE_CSV = _ROOT / "baselines" / "is_baseline_cb_fixed_2026-07-08.csv"

# Year-by-year verdicts for comparison (from SCRATCHPAD.md / bootstrap_strategy.py header)
_YBY_VERDICTS: Dict[str, Tuple[float, str]] = {
    "TREND_FOLLOW":  (0.008,  "CONFIRMED"),
    "PE_SHORT":      (0.007,  "CONFIRMED"),
    "ORB":           (0.019,  "CONFIRMED"),
    "STRESS_ORB":    (0.019,  "CONFIRMED"),
    "STRESS_MID":    (0.112,  "BORDERLINE"),
    "GF_SHORT":      (0.128,  "BORDERLINE"),
    "FADE":          (0.754,  "NO EDGE"),
    "GAP_FILL":      (0.687,  "NO EDGE"),
    "VWAP_MR":       (0.613,  "NO EDGE"),
}


def load_csv(path: Path) -> Dict[str, List[float]]:
    by_strat: Dict[str, List[float]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s   = row.get("strategy", "").strip()
            pnl = row.get("net_pnl", "").strip()
            if not s or not pnl:
                continue
            try:
                by_strat.setdefault(s, []).append(float(pnl))
            except ValueError:
                pass
    return by_strat


def bootstrap_pvalue(pnls: List[float], n_boot: int, rng: np.random.Generator) -> float:
    arr = np.array(pnls, dtype=float)
    if len(arr) == 0 or arr.mean() == 0:
        return 1.0
    boot_means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return float((boot_means <= 0).mean())


def verdict(p: float) -> str:
    if p < 0.05:
        return "CONFIRMED"
    if p < 0.15:
        return "BORDERLINE"
    return "NO EDGE"


def run(csv_path: Path, n_boot: int, seed: int) -> str:
    by_strat = load_csv(csv_path)
    rng      = np.random.default_rng(seed)

    rows: List[Tuple] = []
    for strat in sorted(by_strat.keys()):
        pnls = by_strat[strat]
        n    = len(pnls)
        wr   = sum(1 for x in pnls if x > 0) / n if n else 0.0
        avg  = float(np.mean(pnls)) if n else 0.0
        p    = bootstrap_pvalue(pnls, n_boot, rng)
        v    = verdict(p)
        yby  = _YBY_VERDICTS.get(strat, (None, "—"))
        rows.append((strat, n, wr, avg, p, v, yby))

    total_n   = sum(r[1] for r in rows)
    total_pnl = sum(r[3] * r[1] for r in rows)

    h1 = f"{'Strategy':<14} {'N':>5} {'WR%':>6} {'Avg$':>8} {'p-val':>7}  {'Continuous':>10}  {'Year-by-year p':>15}  {'YbY verdict':>12}  FLIP?"
    sep = "-" * len(h1)

    lines = [
        "Bootstrap — CONTINUOUS IS design vs YEAR-BY-YEAR (deployed comparison)",
        f"Baseline : {csv_path.name}  ({total_n} trades)",
        f"Design   : continuous 2017-2022, Kelly=0.75, PDT on, MAX_TREND=3",
        f"N_BOOT={n_boot}  seed={seed}",
        sep,
        h1,
        sep,
    ]

    flips = []
    for strat, n, wr, avg, p, v, (yby_p, yby_v) in rows:
        flip = ""
        if yby_v != "—":
            # Flip = CONFIRMED↔NO_EDGE, or either side crossing BORDERLINE in meaningful direction
            # (CONFIRMED→BORDERLINE or BORDERLINE→CONFIRMED count as partial flip, mark *)
            if (yby_v == "CONFIRMED") != (v == "CONFIRMED") or (yby_v == "NO EDGE") != (v == "NO EDGE"):
                if (yby_v in ("CONFIRMED", "NO EDGE")) and (v in ("CONFIRMED", "NO EDGE")) and yby_v != v:
                    flip = "*** FLIP"
                    flips.append((strat, yby_v, v))
                else:
                    flip = "* partial"
        yby_str = f"{yby_p:.3f} {yby_v}" if yby_p is not None else "—"
        lines.append(
            f"{strat:<14} {n:>5} {wr*100:>5.1f}% {avg:>8.2f} {p:>7.3f}  {v:>10}  {yby_str:>15}  {yby_v:>12}  {flip}"
        )

    lines.append(sep)
    lines.append(f"Total: {total_n} trades | total P&L ${total_pnl:+,.2f}")
    lines.append("")

    if flips:
        lines.append(f"*** {len(flips)} VERDICT FLIP(S) — strategy inclusion decisions may need revisiting:")
        for strat, from_v, to_v in flips:
            lines.append(f"   {strat}: {from_v} → {to_v}")
    else:
        lines.append("No verdict flips — strategy inclusion decisions hold under continuous design.")

    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv",    default=str(_BASELINE_CSV), help="Path to committed CSV baseline")
    ap.add_argument("--n-boot", type=int, default=N_BOOT_DEFAULT)
    ap.add_argument("--seed",   type=int, default=SEED_DEFAULT)
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: baseline CSV not found: {csv_path}", file=sys.stderr)
        print("Run verify_cb_fix.py first and commit the CSV, or pass --csv <path>", file=sys.stderr)
        sys.exit(1)

    report = run(csv_path, args.n_boot, args.seed)
    print(report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "bootstrap_continuous_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
