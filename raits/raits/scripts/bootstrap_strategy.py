"""
scripts/bootstrap_strategy.py
------------------------------
TRUST AUDIT — per-strategy bootstrap p-values.

Re-measures the bootstrap p-values recorded in SCRATCHPAD.md (results_20260624_135619.pkl):
  CONFIRMED: TF p=0.008, PE_SHORT p=0.007, ORB p=0.019, STRESS_ORB p=0.019
  BORDERLINE: STRESS_MID p=0.112, GF_SHORT p=0.128
  NO EDGE:   FADE p=0.754, GAP_FILL p=0.687, VWAP_MR p=0.613

Approach:
  For each strategy: one-sided bootstrap H0: mean(net_pnl) <= 0
  p-value = fraction of N_BOOT resamples where resample_mean <= 0
  Lower p = more evidence of positive edge.

Usage:
    python scripts/bootstrap_strategy.py
    python scripts/bootstrap_strategy.py path/to/snapshot.pkl --n-boot 10000 --seed 42

Output: prints table to stdout, saves configs/bootstrap_strategy_report.txt
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Ensure project root (d:\raits) is on sys.path so `import raits` works when
# running the script directly: python raits/raits/scripts/bootstrap_strategy.py
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np


N_BOOT_DEFAULT = 10_000
SEED_DEFAULT = 42


def _load_snapshot(path: str | Path) -> list:
    with open(path, "rb") as f:
        return pickle.load(f)


def _collect_by_strategy(windows: list) -> Dict[str, List[float]]:
    by_strat: Dict[str, List[float]] = {}
    for w in windows:
        for t in w["trades"]:
            s = t.strategy
            if s not in by_strat:
                by_strat[s] = []
            by_strat[s].append(float(t.net_pnl))
    return by_strat


def bootstrap_pvalue(pnls: List[float], n_boot: int, rng: np.random.Generator) -> float:
    arr = np.array(pnls, dtype=float)
    if len(arr) == 0 or arr.mean() == 0:
        return 1.0
    boot_means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return float((boot_means <= 0).mean())


def _verdict(p: float) -> str:
    if p < 0.05:
        return "CONFIRMED"
    if p < 0.15:
        return "BORDERLINE"
    return "NO EDGE"


def _find_snapshot() -> Path | None:
    candidates = [
        Path("raits/data/cache/snapshots"),
        Path("data/cache/snapshots"),
    ]
    for base in candidates:
        if base.is_dir():
            pkls = sorted(base.glob("results_*.pkl"))
            if pkls:
                return pkls[-1]
    return None


def run(snapshot_path: Path, n_boot: int, seed: int) -> str:
    windows = _load_snapshot(snapshot_path)
    by_strat = _collect_by_strategy(windows)
    rng = np.random.default_rng(seed)

    rows: List[Tuple[str, int, float, float, float, str]] = []
    for strat in sorted(by_strat.keys()):
        pnls = by_strat[strat]
        n = len(pnls)
        wr = sum(1 for x in pnls if x > 0) / n if n else 0.0
        avg = float(np.mean(pnls)) if n else 0.0
        p = bootstrap_pvalue(pnls, n_boot, rng)
        rows.append((strat, n, wr, avg, p, _verdict(p)))

    header = f"{'Strategy':<14} {'N':>5} {'WR%':>6} {'Avg$':>8} {'p-value':>9} {'Verdict'}"
    sep = "-" * len(header)
    lines = [
        f"Bootstrap per-strategy — {snapshot_path.name}",
        f"N_BOOT={n_boot}  seed={seed}",
        sep,
        header,
        sep,
    ]
    for strat, n, wr, avg, p, v in rows:
        lines.append(f"{strat:<14} {n:>5} {wr*100:>5.1f}% {avg:>8.2f} {p:>9.3f}  {v}")
    lines.append(sep)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Bootstrap p-values per strategy from snapshot")
    ap.add_argument("snapshot", nargs="?", help="Path to results pkl (auto-detected if omitted)")
    ap.add_argument("--n-boot", type=int, default=N_BOOT_DEFAULT)
    ap.add_argument("--seed", type=int, default=SEED_DEFAULT)
    args = ap.parse_args()

    if args.snapshot:
        path = Path(args.snapshot)
    else:
        path = _find_snapshot()
        if path is None:
            print("ERROR: no snapshot found. Pass path explicitly.", file=sys.stderr)
            sys.exit(1)
        print(f"Auto-detected snapshot: {path}", file=sys.stderr)

    report = run(path, args.n_boot, args.seed)
    print(report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "bootstrap_strategy_report.txt"
    out.write_text(report)
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
