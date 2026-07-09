"""
scripts/bootstrap_block_r.py
------------------------------
Block bootstrap on R-multiples — the fully correct edge test:
  - Scale-independent: R = net_pnl / initial_risk (fixes compounding-scale artifact)
  - Path-aware: circular block bootstrap preserves temporal autocorrelation

Also:
  - Sanity-checks R computation (GF_SHORT MeanR=8.59 deep dive)
  - Jackknife on R for PE_SHORT and GF_SHORT (concentration check)
  - Final verdict table across all four filters:
      IID-dollar | IID-R | block-R(B20) | jackknife-R(k=2)

Prior results hardcoded for comparison:
  IID-dollar p: from bootstrap_continuous.py (seed=42, N_BOOT=10000)
  IID-R p:      from bootstrap_normalized.py  (seed=42, N_BOOT=10000)

Usage (from d:\\raits\\raits):
    python raits/scripts/bootstrap_block_r.py
    python raits/scripts/bootstrap_block_r.py --n-boot 10000 --seed 42

Output: configs/bootstrap_block_r_report.txt
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
BLOCK_SIZES    = [20, 40]
_BASELINE_CSV  = _ROOT / "baselines" / "is_baseline_cb_fixed_2026-07-08.csv"

_DOLLAR_P: Dict[str, float] = {
    "TREND_FOLLOW": 0.116, "ORB": 0.329, "STRESS_ORB": 0.215,
    "PE_SHORT": 0.011, "GF_SHORT": 0.010, "STRESS_MID": 0.401,
}
_IID_R_P: Dict[str, float] = {
    "TREND_FOLLOW": 0.009, "ORB": 0.241, "STRESS_ORB": 0.366,
    "PE_SHORT": 0.010, "GF_SHORT": 0.000, "STRESS_MID": 0.380,
}

SEP  = "=" * 85
SEP2 = "-" * 85


def verdict(p: float) -> str:
    if p < 0.05:
        return "CONFIRMED"
    if p < 0.15:
        return "BORDERLINE"
    return "NO EDGE"


def iid_p(arr: np.ndarray, n_boot: int, rng: np.random.Generator) -> float:
    if len(arr) == 0 or arr.mean() == 0:
        return 1.0
    boot = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return float((boot <= 0).mean())


def block_p(r_sorted: np.ndarray, block_size: int, n_boot: int,
            rng: np.random.Generator) -> Tuple[float, bool]:
    """Circular block bootstrap on time-sorted R values.
    Returns (p, is_degenerate). Degenerate when n_blocks <= 1."""
    n = len(r_sorted)
    if n < 2:
        return 1.0, False
    n_blocks = int(np.ceil(n / block_size))
    if n_blocks <= 1:
        return float("nan"), True
    extended = np.concatenate([r_sorted, r_sorted[:block_size]])
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        sample = np.concatenate([extended[s:s + block_size] for s in starts])[:n]
        boot_means[i] = sample.mean()
    return float((boot_means <= 0).mean()), False


def compute_R(ep: float, sh: int, stop: float, pnl: float):
    risk = sh * abs(ep - stop)
    return (pnl / risk, risk) if risk >= 0.01 else (None, None)


def load_csv(path: Path) -> Dict[str, Dict]:
    raw: Dict[str, List] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = row.get("strategy", "").strip()
            if not s:
                continue
            try:
                ep    = float(row["entry_price"])
                sh    = int(row["shares"])
                stop  = float(row["stop"])
                pnl   = float(row["net_pnl"])
                exit_t = row["exit_time"]
            except (ValueError, KeyError):
                continue
            R, risk = compute_R(ep, sh, stop, pnl)
            if R is None:
                continue
            raw.setdefault(s, []).append(
                (exit_t, R, pnl, risk,
                 row["ticker"], row["direction"], ep, sh, stop)
            )

    result = {}
    for strat, entries in raw.items():
        entries.sort(key=lambda x: x[0])
        result[strat] = {
            "R":        np.array([e[1] for e in entries]),
            "dollar":   np.array([e[2] for e in entries]),
            "risk":     np.array([e[3] for e in entries]),
            "ticker":   [e[4] for e in entries],
            "dir":      [e[5] for e in entries],
            "entry":    [e[6] for e in entries],
            "shares":   [e[7] for e in entries],
            "stop":     [e[8] for e in entries],
            "time":     [e[0] for e in entries],
        }
    return result


def fmt_p(p: float) -> str:
    return f"{p:.3f}" if p == p else "N/A"


def run(csv_path: Path, n_boot: int, seed: int) -> str:
    by_strat = load_csv(csv_path)
    rng = np.random.default_rng(seed)
    out: List[str] = []

    # ── STEP 2: GF_SHORT sanity check ────────────────────────────────────────
    out += [
        SEP,
        "STEP 2 -- GF_SHORT R-MULTIPLE SANITY CHECK  (MeanR=8.59 vs others ~0.04-0.35)",
        SEP,
        "",
        "  Q: Is MeanR=8.59 a tiny-denominator artifact, or legitimately tight stops?",
        "",
    ]
    if "GF_SHORT" in by_strat:
        d = by_strat["GF_SHORT"]
        n_gf = len(d["R"])
        out.append(
            f"  {'#':<3} {'Exit date':<12} {'Ticker':<8} {'Dir':<5}"
            f" {'Entry':>8} {'Stop':>8} {'Shares':>6} {'Risk$':>8} {'P&L$':>9} {'R':>8}"
        )
        out.append(f"  {'-'*80}")
        for i in range(n_gf):
            out.append(
                f"  {i+1:<3} {d['time'][i][:10]:<12} {d['ticker'][i]:<8} {d['dir'][i]:<5}"
                f" {d['entry'][i]:>8.4f} {d['stop'][i]:>8.4f} {int(d['shares'][i]):>6}"
                f" ${d['risk'][i]:>7.2f} ${d['dollar'][i]:>8.2f} {d['R'][i]:>+8.3f}"
            )
        out.append(f"  {'-'*80}")
        arr = d["R"]
        n_big = int((arr > 5.0).sum())
        out += [
            f"  Mean R={arr.mean():+.3f}  Std={arr.std(ddof=1):.3f}"
            f"  Min={arr.min():+.3f}  Max={arr.max():+.3f}",
            f"  Trades with R > 5.0: {n_big}/{n_gf}",
            f"  Avg initial_risk=${d['risk'].mean():.2f}",
            "",
            "  GF_SHORT jackknife on R (remove top k by R value):",
            f"  {'k':<3} {'Mean R':>8} {'IID-R p':>9} {'Verdict':>10}  Notes",
            f"  {'-'*55}",
        ]
        top_idx = np.argsort(arr)[::-1]
        jk_gf = {}
        for k in [0, 1, 2, 3]:
            rem = np.delete(arr, top_idx[:k]) if k > 0 else arr
            p_k = iid_p(rem, n_boot, rng) if len(rem) > 0 else 1.0
            jk_gf[k] = p_k
            note = ""
            if k > 0:
                removed = [arr[top_idx[j]] for j in range(k)]
                note = "  removed: " + ", ".join(f"R={v:+.2f}" for v in sorted(removed, reverse=True))
            out.append(
                f"  {k:<3} {rem.mean() if len(rem)>0 else 0:>+8.3f}"
                f" {p_k:>9.3f} {verdict(p_k):>10}{note}"
            )
        out.append("")
    else:
        out.append("  GF_SHORT not in baseline.")
        jk_gf = {}
        out.append("")

    # ── STEP 3: PE_SHORT jackknife on R ──────────────────────────────────────
    out += [
        SEP,
        "STEP 3 -- PE_SHORT JACKKNIFE ON R-MULTIPLE  (concentration check)",
        SEP,
        "",
        "  Dollar jackknife showed fragility at k=2 (p=0.055 BORDERLINE).",
        "  Does the same concentration appear in R-space (scale-independent)?",
        "",
    ]
    jk_pe: Dict[int, float] = {}
    if "PE_SHORT" in by_strat:
        d_pe  = by_strat["PE_SHORT"]
        arr_pe = d_pe["R"]
        top_pe = np.argsort(arr_pe)[::-1]
        total_R_pe = arr_pe.sum()

        # Top-5 trades by R
        out += [
            "  Top 5 PE_SHORT trades by R-multiple:",
            f"  {'#':<3} {'Exit date':<12} {'Ticker':<8} {'Risk$':>8} {'P&L$':>9} {'R':>8} {'CumR%':>7}",
            f"  {'-'*60}",
        ]
        cum = 0.0
        for rank, i in enumerate(top_pe[:5]):
            cum += arr_pe[i]
            out.append(
                f"  {rank+1:<3} {d_pe['time'][i][:10]:<12} {d_pe['ticker'][i]:<8}"
                f" ${d_pe['risk'][i]:>7.2f} ${d_pe['dollar'][i]:>8.2f}"
                f" {arr_pe[i]:>+8.3f} {cum/total_R_pe*100:>6.1f}%"
            )
        out.append("")

        out += [
            "  PE_SHORT jackknife on R (remove top k by R value):",
            f"  {'k':<3} {'N':>4} {'Mean R':>8} {'IID-R p':>9} {'Verdict':>10}  Notes",
            f"  {'-'*65}",
        ]
        for k in [0, 1, 2, 3, 5]:
            if k >= len(arr_pe):
                break
            rem = np.delete(arr_pe, top_pe[:k]) if k > 0 else arr_pe
            p_k = iid_p(rem, n_boot, rng) if len(rem) > 0 else 1.0
            jk_pe[k] = p_k
            note = ""
            if k > 0:
                removed = sorted([arr_pe[top_pe[j]] for j in range(k)], reverse=True)
                note = "  [" + ", ".join(f"R={v:+.2f}" for v in removed[:3]) + "]"
            out.append(
                f"  {k:<3} {len(rem):>4} {rem.mean() if len(rem)>0 else 0:>+8.3f}"
                f" {p_k:>9.3f} {verdict(p_k):>10}{note}"
            )
        out.append("")
    else:
        out.append("  PE_SHORT not in baseline.")
        out.append("")

    # ── STEP 1: Block bootstrap on R ─────────────────────────────────────────
    out += [
        SEP,
        "STEP 1 -- BLOCK BOOTSTRAP ON R-MULTIPLE  (scale-independent + path-aware)",
        SEP,
        "",
        f"  Circular block bootstrap, trades sorted by exit_time.",
        f"  Degenerate when ceil(N/block_size) <= 1.",
        f"  N_BOOT={n_boot}  seed={seed}",
        "",
        f"  {'Strategy':<14} {'N':>4}  {'IID-R':>7}  {'B20 p':>7} {'B20 v':>10}  {'B40 p':>7} {'B40 v':>10}",
        f"  {'-'*72}",
    ]

    block_r: Dict[str, Dict] = {}
    for strat in sorted(by_strat.keys()):
        arr = by_strat[strat]["R"]
        n = len(arr)
        iid_r = _IID_R_P.get(strat, float("nan"))
        bp: Dict[int, float] = {}
        for bs in BLOCK_SIZES:
            pv, degen = block_p(arr, bs, n_boot, rng)
            bp[bs] = pv
        block_r[strat] = {"n": n, "block": bp}

        b20 = bp.get(20, float("nan"))
        b40 = bp.get(40, float("nan"))
        v20 = verdict(b20) if b20 == b20 else "degen"
        v40 = verdict(b40) if b40 == b40 else "degen"
        out.append(
            f"  {strat:<14} {n:>4}  {fmt_p(iid_r):>7}  "
            f"{fmt_p(b20):>7} {v20:>10}  {fmt_p(b40):>7} {v40:>10}"
        )

    out.append(f"  {'-'*72}")
    out.append("")

    # TF narrative
    tf_b20 = block_r.get("TREND_FOLLOW", {}).get("block", {}).get(20, float("nan"))
    tf_b40 = block_r.get("TREND_FOLLOW", {}).get("block", {}).get(40, float("nan"))
    if tf_b20 == tf_b20:
        vt = verdict(tf_b20)
        if vt == "CONFIRMED":
            msg = "TF is CONFIRMED on the fully correct test (scale-independent + path-aware)."
        elif vt == "BORDERLINE":
            msg = "TF is BORDERLINE on block-R — IID-R=0.009 was optimistic; autocorrelation present."
        else:
            msg = "TF is NO EDGE on block-R — IID-R=0.009 was over-optimistic."
        out.append(f"  TF  B20={fmt_p(tf_b20)} -> {vt}. {msg}")
    if tf_b40 == tf_b40:
        out.append(f"  TF  B40={fmt_p(tf_b40)} -> {verdict(tf_b40)} (larger block).")
    out.append("")

    # ── STEP 4: Final verdict table ───────────────────────────────────────────
    out += [
        SEP,
        "STEP 4 -- FINAL EDGE PICTURE  (all four filters)",
        SEP,
        "",
        "  Rigor increases left to right. Deployable edge = block-R CONFIRMED + JK not fragile.",
        "",
        f"  {'Strategy':<14} {'N':>4}  "
        f"{'[1]$':>5} {'v':>10}  "
        f"{'[2]Rp':>6} {'v':>10}  "
        f"{'[3]B20':>6} {'v':>10}  "
        f"{'[4]JK2':>6} {'v':>10}  FINAL VERDICT",
        f"  {'-'*105}",
    ]

    # Compute JK-R at k=2 for all strategies
    jk2_all: Dict[str, float] = {}
    for strat in sorted(by_strat.keys()):
        arr = by_strat[strat]["R"]
        top2 = np.argsort(arr)[::-1][:2]
        rem  = np.delete(arr, top2) if len(arr) > 2 else arr
        jk2_all[strat] = iid_p(rem, n_boot, rng) if len(rem) > 0 else 1.0

    for strat in sorted(by_strat.keys()):
        n    = block_r[strat]["n"]
        p_d  = _DOLLAR_P.get(strat, float("nan"))
        p_ir = _IID_R_P.get(strat, float("nan"))
        p_b  = block_r[strat]["block"].get(20, float("nan"))
        p_j2 = jk2_all.get(strat, float("nan"))

        v_d  = verdict(p_d)  if p_d  == p_d  else "—"
        v_ir = verdict(p_ir) if p_ir == p_ir else "—"
        v_b  = verdict(p_b)  if p_b  == p_b  else "degen"
        v_j2 = verdict(p_j2) if p_j2 == p_j2 else "—"

        primary = verdict(p_b) if p_b == p_b else verdict(p_ir)
        conc    = v_j2

        if primary == "CONFIRMED" and conc == "CONFIRMED":
            final = "CONFIRMED"
        elif primary == "CONFIRMED" and conc == "BORDERLINE":
            final = "CONFIRMED (conc.)"
        elif primary == "CONFIRMED" and conc == "NO EDGE":
            final = "FRAGILE"
        elif primary == "BORDERLINE":
            final = "BORDERLINE"
        else:
            final = "NO EDGE"

        out.append(
            f"  {strat:<14} {n:>4}  "
            f"{fmt_p(p_d):>5} {v_d:>10}  "
            f"{fmt_p(p_ir):>6} {v_ir:>10}  "
            f"{fmt_p(p_b):>6} {v_b:>10}  "
            f"{fmt_p(p_j2):>6} {v_j2:>10}  {final}"
        )

    out.append(f"  {'-'*105}")
    out += [
        "",
        "  NARRATIVE:",
        "  ----------",
    ]
    for strat in sorted(by_strat.keys()):
        p_b  = block_r[strat]["block"].get(20, float("nan"))
        p_j2 = jk2_all.get(strat, float("nan"))
        p_ir = _IID_R_P.get(strat, float("nan"))
        primary = verdict(p_b) if p_b == p_b else verdict(p_ir)
        conc    = verdict(p_j2) if p_j2 == p_j2 else "—"

        if primary == "CONFIRMED" and conc == "CONFIRMED":
            note = "edge is real, scale-independent, path-robust, not concentration-driven."
        elif primary == "CONFIRMED" and conc in ("BORDERLINE", "NO EDGE"):
            note = f"edge confirmed on block-R but jackknife-fragile at k=2 (p={fmt_p(p_j2)}) — concentrated."
        elif primary == "BORDERLINE":
            note = f"borderline on block-R — not deployable without more data."
        else:
            note = "no edge on block-R — confirmed no-edge by all tests."

        out.append(f"  {strat:<14}: {primary:<10} {note}")

    out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv",    default=str(_BASELINE_CSV))
    ap.add_argument("--n-boot", type=int, default=N_BOOT_DEFAULT)
    ap.add_argument("--seed",   type=int, default=SEED_DEFAULT)
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"ERROR: {csv_path}", file=sys.stderr)
        sys.exit(1)

    report = run(csv_path, args.n_boot, args.seed)
    print(report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "bootstrap_block_r_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()