"""
scripts/diagnose_bootstrap_soundness.py
-----------------------------------------
Answers three questions about the continuous-design bootstrap results:

  STEP 1 — Method soundness
    - Is the continuous bootstrap the same method as the original (YbY)?
    - IID vs block: trades are not independent — what does that mean for p-values?

  STEP 2 — N-control for TF (the key flip concern)
    - TF dropped from ~650 YbY trades to 353 continuous.
    - Is p=0.116 explained by lower N (less power), or is per-trade edge genuinely weaker?
    - Approach: fix the per-trade distribution (mean, std) and simulate bootstrap
      at various N sizes to find the "breakeven N" where p would cross 0.05.
    - Also compare per-trade quality (Cohen's d = mean/std) between YbY and continuous
      if YbY trades are loadable.

  STEP 3 — PE_SHORT IS fragility check
    - Only 29 trades over 6 years (~5/year). High avg ($246/trade).
    - Bootstrap p=0.011 but N=29 is thin. How stable is this?
    - Jackknife sensitivity: what p do we get if we drop the top-1 or top-3 trades?

  STEP 4 — System P&L on continuous design with/without flipped strategies
    - Full system: 605 trades, $15,019.79
    - Without ORB + STRESS_ORB: P&L, Sharpe estimate
    - Honest verdict on marginal edge

Usage (from d:\\raits\\raits):
    python raits/scripts/diagnose_bootstrap_soundness.py

Saves: configs/bootstrap_soundness_report.txt
"""

from __future__ import annotations

import csv
import pickle
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np

N_BOOT  = 10_000
SEED    = 42
_CSV    = _ROOT / "baselines" / "is_baseline_cb_fixed_2026-07-08.csv"
_YBY_PKL = _ROOT / "raits" / "data" / "cache" / "window_debug_results.pkl"
_INITIAL_EQUITY = 50_000.0
_YEARS = 6  # 2017-2022

# Continuous bootstrap results for cross-reference
_CONT_P = {
    "TREND_FOLLOW": 0.116,
    "ORB":          0.329,
    "STRESS_ORB":   0.215,
    "PE_SHORT":     0.011,
    "GF_SHORT":     0.010,
    "STRESS_MID":   0.401,
}
_YBY_P = {
    "TREND_FOLLOW": 0.008,
    "ORB":          0.019,
    "STRESS_ORB":   0.019,
    "PE_SHORT":     0.007,
    "GF_SHORT":     0.128,
    "STRESS_MID":   0.112,
}


def load_csv(path: Path) -> Dict[str, List[float]]:
    by_strat: Dict[str, List[float]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s   = row.get("strategy", "").strip()
            pnl = row.get("net_pnl", "").strip()
            if s and pnl:
                try:
                    by_strat.setdefault(s, []).append(float(pnl))
                except ValueError:
                    pass
    return by_strat


def bootstrap_p(pnls: np.ndarray, n_boot: int, rng: np.random.Generator) -> float:
    if len(pnls) == 0:
        return 1.0
    boot = rng.choice(pnls, size=(n_boot, len(pnls)), replace=True).mean(axis=1)
    return float((boot <= 0).mean())


def simulate_p_at_n(pnls: np.ndarray, target_n: int, n_boot: int,
                     rng: np.random.Generator, n_outer: int = 500) -> float:
    """
    What p-value would we get if we had `target_n` trades instead of len(pnls),
    assuming the same per-trade distribution?
    Draw n_outer replications of target_n trades (with replacement from actual),
    compute bootstrap p for each, return median p.
    """
    ps = []
    for _ in range(n_outer):
        sample = rng.choice(pnls, size=target_n, replace=True)
        p = bootstrap_p(sample, n_boot=max(1000, n_boot // 10), rng=rng)
        ps.append(p)
    return float(np.median(ps))


def jackknife_top_k(pnls: np.ndarray, k: int, n_boot: int,
                    rng: np.random.Generator) -> Tuple[float, List[float]]:
    """Remove the k largest winning trades. Return (new p, removed pnls)."""
    sorted_idx = np.argsort(pnls)[::-1]  # descending
    removed = pnls[sorted_idx[:k]].tolist()
    trimmed = np.delete(pnls, sorted_idx[:k])
    p = bootstrap_p(trimmed, n_boot, rng)
    return p, removed


def load_yby_by_strategy(pkl_path: Path) -> Optional[Dict[str, np.ndarray]]:
    """
    Load year-by-year window results pkl.
    Expected format: list of window dicts each with 'trades' key,
    where each trade has .strategy and .net_pnl attributes.
    Returns None if not loadable.
    """
    if not pkl_path.exists():
        return None
    try:
        with open(pkl_path, "rb") as f:
            data = pickle.load(f)
        by_strat: Dict[str, List[float]] = {}
        for w in data:
            trades = w.get("trades", []) if isinstance(w, dict) else []
            for t in trades:
                s   = getattr(t, "strategy", None)
                pnl = getattr(t, "net_pnl", None)
                if s and pnl is not None:
                    by_strat.setdefault(s, []).append(float(pnl))
        return {s: np.array(v) for s, v in by_strat.items()} if by_strat else None
    except Exception as e:
        return None


def _verdict(p: float) -> str:
    if p < 0.05:  return "CONFIRMED"
    if p < 0.15:  return "BORDERLINE"
    return "NO EDGE"


def run() -> str:
    rng = np.random.default_rng(SEED)
    cont = {s: np.array(v) for s, v in load_csv(_CSV).items()}
    yby  = load_yby_by_strategy(_YBY_PKL)

    lines: List[str] = []
    W = 90
    def h(title: str) -> None:
        lines.append("")
        lines.append("=" * W)
        lines.append(f"  {title}")
        lines.append("=" * W)

    # ────────────────────────────────────────────────────────────────────────
    h("STEP 1 — BOOTSTRAP METHOD SOUNDNESS")

    lines.append("""
Method: IID bootstrap — resample individual trades independently with replacement.
        H0: mean(net_pnl) <= 0 (one-sided), N_BOOT=10000, seed=42.
        IDENTICAL method between bootstrap_strategy.py (YbY) and bootstrap_continuous.py.
        The comparison of p-values is apples-to-apples on method.

IID ASSUMPTION VIOLATION:
        Trades are NOT independent. In the continuous 2017-2022 run, TF entries cluster
        during trend regimes. A bull regime creates correlated wins; a bear regime creates
        correlated losses. IID bootstrap treats them as independent draws — this UNDERSTATES
        the variance of the resample mean, producing p-values LOWER than a block bootstrap
        would give.

        Direction of bias: IID makes p-values look MORE significant (lower p) than reality.
        Implication for our results:
          - TF p=0.116 under IID may be an OPTIMISTIC estimate of significance.
            Block bootstrap would likely give p HIGHER than 0.116.
          - ORB p=0.329 and STRESS_ORB p=0.215 are already well above 0.05 even with
            the IID optimism — block bootstrap would push them higher, not reverse the verdict.
          - PE_SHORT p=0.011 could be more fragile than it appears (see Step 3).

        Conclusion: the continuous bootstrap is not block-bootstrapped, which is the
        correct method for time-series trades. The p-values are optimistic. Any strategy
        that is already near or above 0.05 with IID is almost certainly NOT significant
        under block bootstrap. This strengthens, not weakens, the concern about TF.
""")

    # ────────────────────────────────────────────────────────────────────────
    h("STEP 2 — N-CONTROL: TF p=0.116 — N effect or per-trade edge weakness?")

    tf = cont.get("TREND_FOLLOW", np.array([]))
    n_tf = len(tf)
    mu_tf = float(tf.mean()) if n_tf else 0.0
    sd_tf = float(tf.std())  if n_tf else 0.0
    t_tf  = (mu_tf / (sd_tf / np.sqrt(n_tf))) if (n_tf and sd_tf > 0) else 0.0
    cv_tf = sd_tf / abs(mu_tf) if mu_tf != 0 else float("inf")

    lines.append(f"  Continuous TF: N={n_tf}, mean=${mu_tf:.2f}, std=${sd_tf:.2f}")
    lines.append(f"  t-stat = {t_tf:.3f}  |  CoV (std/mean) = {cv_tf:.1f}x  |  Cohen's d = {1/cv_tf:.3f}")
    lines.append(f"  Verified p at N={n_tf}: {bootstrap_p(tf, N_BOOT, rng):.3f}")
    lines.append("")

    # YbY comparison if available
    if yby and "TREND_FOLLOW" in yby:
        tf_y = yby["TREND_FOLLOW"]
        n_y  = len(tf_y)
        mu_y = float(tf_y.mean())
        sd_y = float(tf_y.std())
        t_y  = (mu_y / (sd_y / np.sqrt(n_y))) if (n_y and sd_y > 0) else 0.0
        cv_y = sd_y / abs(mu_y) if mu_y != 0 else float("inf")
        lines.append(f"  YbY TF: N={n_y}, mean=${mu_y:.2f}, std=${sd_y:.2f}")
        lines.append(f"  t-stat = {t_y:.3f}  |  CoV = {cv_y:.1f}x  |  Cohen's d = {1/cv_y:.3f}")
        lines.append("")
        lines.append(f"  Per-trade quality (Cohen's d): YbY={1/cv_y:.3f} vs Continuous={1/cv_tf:.3f}")
        if abs(1/cv_y - 1/cv_tf) / max(1/cv_y, 1/cv_tf) > 0.2:
            lines.append("  ** Per-trade edge quality IS different — not purely a N effect **")
        else:
            lines.append("  Per-trade edge quality is similar — p increase is largely N effect.")
    else:
        lines.append(f"  YbY pkl not loadable or missing. N-control via simulation only.")
        lines.append(f"  (looked for: {_YBY_PKL})")
    lines.append("")

    # N-control simulation: what p would we get at larger N with same distribution?
    n_sizes = [353, 500, 650, 800, 1000, 1500]
    lines.append("  N-control simulation (same mean/std, varying N; 500 outer draws, 1000 inner boot):")
    lines.append(f"  {'N':>6}  {'median p':>10}  {'verdict':>12}  note")
    lines.append(f"  {'-'*55}")
    p_at_n = {}
    for n_sim in n_sizes:
        p_med = simulate_p_at_n(tf, n_sim, N_BOOT, rng)
        p_at_n[n_sim] = p_med
        note = "<-- actual" if n_sim == n_tf else ""
        if n_sim > n_tf:
            note = "(hypothetical)"
        lines.append(f"  {n_sim:>6}  {p_med:>10.3f}  {_verdict(p_med):>12}  {note}")

    # Breakeven N
    n_test = n_sizes[-1]
    while p_at_n.get(n_test, 1.0) > 0.05 and n_test < 5000:
        n_test += 500
        p_at_n[n_test] = simulate_p_at_n(tf, n_test, N_BOOT, rng)
    if p_at_n.get(n_test, 1.0) < 0.05:
        lines.append(f"")
        lines.append(f"  Breakeven N (p<0.05 with same distribution): ~{n_test}")
    else:
        lines.append(f"")
        lines.append(f"  N>5000 needed to confirm TF at p<0.05 — edge is genuinely weak per-trade.")

    lines.append(f"""
  INTERPRETATION:
    t-stat for TF at N=353 is {t_tf:.3f}. A t-stat below 1.0 indicates the mean is smaller
    than one standard error — the distribution of trade P&Ls is very noisy relative to the
    mean. Compare to PE_SHORT (see below) which has a much higher t-stat despite small N.

    If the breakeven N is > 650 (2x actual): the p flip is NOT just an N effect —
    the per-trade edge quality in continuous design is genuinely weaker than in YbY.
    Possible causes:
      (a) PDT on changes which TF entries fire (PDT rations day-trade capacity)
      (b) Kelly 0.75 changes position sizes, affecting which size-constrained exits trigger
      (c) MAX_TREND change (could be different from YbY) changes concurrent TF positions
      (d) Continuous capital compounding creates different entry timing than annual reset
""")

    # ────────────────────────────────────────────────────────────────────────
    h("STEP 3 — PE_SHORT IS FRAGILITY CHECK")

    pe = cont.get("PE_SHORT", np.array([]))
    n_pe  = len(pe)
    mu_pe = float(pe.mean()) if n_pe else 0.0
    sd_pe = float(pe.std())  if n_pe else 0.0
    t_pe  = (mu_pe / (sd_pe / np.sqrt(n_pe))) if (n_pe and sd_pe > 0) else 0.0
    lines.append(f"  PE_SHORT: N={n_pe}, mean=${mu_pe:.2f}, std=${sd_pe:.2f}")
    lines.append(f"  t-stat = {t_pe:.3f}  |  ~{n_pe/_YEARS:.1f} trades/year")
    lines.append(f"  p at N={n_pe}: {bootstrap_p(pe, N_BOOT, rng):.3f}")
    lines.append("")

    # Jackknife: remove top 1, 2, 3 winning trades
    lines.append(f"  Jackknife sensitivity (remove top winning trades):")
    lines.append(f"  {'k removed':>12}  {'new N':>7}  {'new p':>8}  {'verdict':>12}  trades removed ($)")
    lines.append(f"  {'-'*70}")
    for k in [1, 2, 3, 5]:
        if k >= n_pe:
            break
        p_jk, removed = jackknife_top_k(pe, k, N_BOOT, rng)
        removed_str = ", ".join(f"${v:.0f}" for v in sorted(removed, reverse=True))
        lines.append(f"  {k:>12}  {n_pe-k:>7}  {p_jk:>8.3f}  {_verdict(p_jk):>12}  [{removed_str}]")

    # Top-10 trades
    top_idx = np.argsort(pe)[::-1][:10]
    lines.append(f"\n  Top 10 PE_SHORT trades by P&L:")
    for i, idx in enumerate(top_idx):
        pct = pe[idx] / pe.sum() * 100 if pe.sum() != 0 else 0
        lines.append(f"    #{i+1}: ${pe[idx]:>9.2f}  ({pct:.1f}% of total PE_SHORT P&L)")
    total_pe_pnl = pe.sum()
    top3_pnl = pe[top_idx[:3]].sum()
    lines.append(f"\n  Top 3 trades = ${top3_pnl:.2f} ({top3_pnl/total_pe_pnl*100:.0f}% of total PE_SHORT P&L)")

    lines.append(f"""
  INTERPRETATION:
    PE_SHORT has N=29 over 6 years — ~5 trades/year. Despite confirmed p=0.011,
    the t-stat of {t_pe:.2f} reflects {n_pe} draws. The jackknife shows how many
    "lucky" trades are needed to sustain the verdict.

    Concentration risk: if the top 1-3 trades flip the verdict, PE_SHORT's edge
    is CONCENTRATED not CONSISTENT. A concentrated IS edge is more likely IS-specific.

    The user notes "short strategies were flagged as losing OOS earlier" — this likely
    refers to the vault OOS 2023-2024 context where short strategies in a strong bull
    market (2023: SPY +26%) would be expected to underperform. PE_SHORT's IS edge
    may not survive the 2025 OOS test.
""")

    # ────────────────────────────────────────────────────────────────────────
    h("STEP 4 — SYSTEM CHARACTERIZATION ON CONTINUOUS DESIGN")

    total_n   = sum(len(v) for v in cont.values())
    total_pnl = sum(v.sum() for v in cont.values())
    ann_pnl   = total_pnl / _YEARS
    ann_ret   = ann_pnl / _INITIAL_EQUITY

    lines.append(f"  Full system ({_YEARS}yr IS, 2017-2022):")
    lines.append(f"    Strategies: {', '.join(sorted(cont.keys()))}")
    lines.append(f"    N trades:   {total_n}")
    lines.append(f"    Total P&L:  ${total_pnl:,.2f}")
    lines.append(f"    Ann. P&L:   ${ann_pnl:,.2f}/yr")
    lines.append(f"    Ann. return: {ann_ret*100:.1f}% (on ${_INITIAL_EQUITY:,.0f} initial equity)")
    lines.append("")

    # Without ORB + STRESS_ORB
    keep = {s: v for s, v in cont.items() if s not in ("ORB", "STRESS_ORB")}
    pnl_keep = sum(v.sum() for v in keep.values())
    n_keep   = sum(len(v)   for v in keep.values())
    ann_keep = pnl_keep / _YEARS
    ret_keep = ann_keep / _INITIAL_EQUITY

    lines.append(f"  System WITHOUT ORB + STRESS_ORB (flipped strategies):")
    lines.append(f"    Strategies: {', '.join(sorted(keep.keys()))}")
    lines.append(f"    N trades:   {n_keep}")
    lines.append(f"    Total P&L:  ${pnl_keep:,.2f}  (removed: ${total_pnl - pnl_keep:,.2f})")
    lines.append(f"    Ann. P&L:   ${ann_keep:,.2f}/yr")
    lines.append(f"    Ann. return: {ret_keep*100:.1f}% (on ${_INITIAL_EQUITY:,.0f})")
    lines.append("")

    # TF + PE_SHORT only
    core = {s: v for s, v in cont.items() if s in ("TREND_FOLLOW", "PE_SHORT")}
    pnl_core = sum(v.sum() for v in core.values())
    n_core   = sum(len(v)   for v in core.values())
    ann_core = pnl_core / _YEARS
    ret_core = ann_core / _INITIAL_EQUITY

    lines.append(f"  TF + PE_SHORT only (confirmed/borderline-only core):")
    lines.append(f"    N trades:   {n_core}")
    lines.append(f"    Total P&L:  ${pnl_core:,.2f}  ({pnl_core/total_pnl*100:.0f}% of system)")
    lines.append(f"    Ann. P&L:   ${ann_core:,.2f}/yr")
    lines.append(f"    Ann. return: {ret_core*100:.1f}%")
    lines.append("")

    # Per-strategy contribution table
    lines.append(f"  Per-strategy breakdown:")
    hdr = f"  {'Strategy':<14} {'N':>5}  {'TotalP&L':>10}  {'Ann$':>8}  {'%sys':>6}  {'ContinP':>8}  {'YbYP':>8}  Verdict"
    lines.append(hdr)
    lines.append(f"  {'-'*len(hdr)}")
    for s in sorted(cont.keys()):
        arr = cont[s]
        spnl = arr.sum()
        ann_s = spnl / _YEARS
        pct   = spnl / total_pnl * 100 if total_pnl else 0
        cp    = _CONT_P.get(s, float("nan"))
        yp    = _YBY_P.get(s, float("nan"))
        v     = _verdict(cp)
        flip  = "FLIP" if _verdict(yp) != v and _verdict(yp) != "BORDERLINE" and v != "BORDERLINE" else ""
        lines.append(f"  {s:<14} {len(arr):>5}  ${spnl:>9,.0f}  ${ann_s:>7,.0f}  {pct:>5.0f}%  {cp:>8.3f}  {yp:>8.3f}  {v} {flip}")

    # ────────────────────────────────────────────────────────────────────────
    h("STEP 4 — HONEST VERDICT")

    lines.append(f"""
  THE QUESTION: Is this a "trim two strategies" situation, or "edge is marginal"?

  EVIDENCE FOR "TRIM TWO":
    - ORB ($1,215 / 6yr = $202/yr) and STRESS_ORB ($508 / 6yr = $85/yr) contribute little.
    - Their combined IS contribution is ${total_pnl - pnl_keep:,.0f} out of ${total_pnl:,.0f} ({(total_pnl-pnl_keep)/total_pnl*100:.0f}%).
    - Removing them leaves TF + PE_SHORT + GF_SHORT + STRESS_MID, still positive.
    - "Trim" framing: the system's IS edge is mostly PE_SHORT and TF. Remove noise.

  EVIDENCE FOR "EDGE IS MARGINAL":
    - TF is 58% of trades but p=0.116 BORDERLINE (possibly optimistic due to IID bias).
      Block bootstrap would likely push TF to p>0.15 = NO EDGE. The backbone is not confirmed.
    - PE_SHORT p=0.011 with N=29 — concentrated. One bad year removes the verdict.
    - IS annualized return: {ann_ret*100:.1f}% on ${_INITIAL_EQUITY:,.0f}. After Kelly and costs, this is thin.
    - The system was designed, tuned, and bootstrapped on YbY (wrong design).
      The continuous bootstrap is the FIRST valid test on the deployed design,
      and only PE_SHORT fully passes.
    - IID bootstrap is optimistic -> true p-values are higher -> even fewer strategies pass.

  THE HONEST FRAMING:
    The strategy inclusion decisions were made on a design (YbY, PDT off, Kelly=0.5) that
    does not match the deployed system (continuous, PDT on, Kelly=0.75). On the correct
    design, the system has ONE confirmed strategy (PE_SHORT, N=29, concentrated),
    ONE borderline backbone (TF, p=0.116, IID-optimistic), and two NO-EDGE strategies
    that are in the deployed system (ORB, STRESS_ORB).

    This is NOT a "trim two" situation — trimming ORB/STRESS_ORB post-hoc on continuous
    IS would be re-selecting strategies on the data used to evaluate them, which is
    overfitting. The correct read is:

    ** The IS evidence for a deployable multi-strategy edge is weak under the correct
       design. The 2025 OOS test is the real arbiter of whether the system works.
       The vault OOS 2023-2024 (+$7,404, Sharpe=0.88) is a 2-year sample and
       insufficient to override this conclusion. **

    WHAT THIS MEANS FOR ACTION:
    - Do NOT drop ORB/STRESS_ORB based on continuous IS alone (overfitting).
    - Do NOT re-run strategy selection on continuous IS (overfitting).
    - The system's IS inclusion decisions were made on YbY, which was the design at the
      time. Those decisions cannot be retroactively re-optimized on continuous IS.
    - The honest position: treat 2025 OOS as a live strategy validity test.
      If ORB/STRESS_ORB underperform OOS as well, that's the signal to remove them.
    - PE_SHORT's IS edge is concentrated — worth monitoring closely OOS.
      If it's 2-3 strong trades per year and the OOS year catches none, edge is gone.
    - TF is borderline on the correct design. The vault OOS validated the whole system,
      not TF specifically. TF OOS decomposition would be required to evaluate it alone.
""")

    h("SUMMARY TABLE")
    lines.append(f"  {'Strategy':<14}  {'Cont p':>8}  {'YbY p':>8}  {'Cont verdict':>14}  {'Action'}")
    lines.append(f"  {'-'*75}")
    verdicts = {
        "TREND_FOLLOW":  "Monitor — backbone, borderline",
        "ORB":           "Keep — don't re-cut on IS (OOS will tell)",
        "STRESS_ORB":    "Keep — don't re-cut on IS (OOS will tell)",
        "PE_SHORT":      "Monitor — confirmed but concentrated (N=29)",
        "GF_SHORT":      "Monitor — improved but N=12, fragile",
        "STRESS_MID":    "Keep — small contributor, low harm",
    }
    for s in sorted(cont.keys()):
        cp = _CONT_P.get(s, float("nan"))
        yp = _YBY_P.get(s, float("nan"))
        v  = _verdict(cp)
        lines.append(f"  {s:<14}  {cp:>8.3f}  {yp:>8.3f}  {v:>14}  {verdicts.get(s, '')}")

    lines.append(f"""
  BOTTOM LINE:
    - Continuous bootstrap IS methodologically consistent with YbY bootstrap.
    - IID assumption is a SHARED limitation — but biases toward lower p (optimistic).
      P-values reported are best-case estimates; true values may be higher.
    - TF N-control: see breakeven N above. If > 650, the flip is NOT just N —
      per-trade edge quality genuinely declined from YbY to continuous design.
    - PE_SHORT: check jackknife above. If removing top 1-3 trades flips verdict,
      the edge is concentrated and fragile despite p=0.011.
    - DO NOT re-cut strategies on continuous IS. The 2025 OOS is the real test.
""")

    return "\n".join(lines)


def main() -> None:
    report = run()
    print(report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "bootstrap_soundness_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
