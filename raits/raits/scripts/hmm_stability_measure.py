"""
scripts/hmm_stability_measure.py
---------------------------------
TRUST AUDIT — HMM_STABILITY_REPORT Parts A, B, C re-measurement.

Re-measures three sets of claims from the same report session that produced
the fabricated "3/6 convergence fail" claim. Since one number in that session
was wrong, all numbers are treated as unverified until measured here.

Part A — Weekly label churn (simulate every Monday retrain 2017-2022):
  Claimed: 10.5% of IS days ever flipped, 1.8% avg quarterly churn, 0 Calm<->Stress inversions.

Part B — Weekly vs annual agreement (YE2018 and YE2021 annual models):
  Claimed: 98.5% agreement on valid-label days 2019-2022.

Part C — Stress detection recall (objective vol-threshold ground truth):
  Claimed: 91.6% recall on COVID window (2020-02-20 to 2020-03-23),
           80.2% recall on 2022 bear (2022-01-01 to 2022-12-31).

Production settings throughout: diag covariance, n_init=10, n_iter=200,
anchored-expanding from 2007-01-03.

Ground truth for Part C: SPY 5-day realized vol (annualized) > VOL_THRESHOLD.
  This threshold is pre-committed and applied uniformly across all windows.
  Also reports sensitivity at 0.15 and 0.25 thresholds.

Expected runtime: ~20-30 minutes (one fit per Monday, 2017-2022 ~ 300 fits).
Add --fast (n_init=3, ~6 minutes) for quick validation; results should match.

Usage:
    python scripts/hmm_stability_measure.py
    python scripts/hmm_stability_measure.py --fast
    python scripts/hmm_stability_measure.py --out path/to/report.txt

Output: prints report to stdout, saves to configs/hmm_stability_report.txt
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import numpy as np
import pandas as pd

# Ensure project root is on sys.path when run directly
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Suppress hmmlearn "not converging" informational messages (not failures)
warnings.filterwarnings("ignore", category=RuntimeWarning)

from hmmlearn.hmm import GaussianHMM

from raits.hmm.features import build_feature_matrix
from raits.hmm.state_sorting import (
    HMM_STATES,
    CALM,
    STRESS,
    sort_hmm_states,
    validate_state_order,
)


# ── Production constants ──────────────────────────────────────────────────────

_SPY_PATH = Path("raits/data/cache/daily/SPY_daily_2007_2024.parquet")

ANCHOR         = "2007-01-03"
IS_START       = "2017-01-01"
IS_END         = "2022-12-31"
N_COMPONENTS   = 4
COV_TYPE       = "diag"
N_INIT_PROD    = 10      # production setting
N_INIT_FAST    = 3       # --fast flag
N_ITER         = 200
MIN_COVAR      = 1e-2

ANNUAL_YE      = [2018, 2021]        # Part B annual re-freeze year-ends

COVID_START    = "2020-02-20"
COVID_END      = "2020-03-23"
BEAR_START     = "2022-01-01"
BEAR_END       = "2022-12-31"

VOL_THRESHOLD  = 0.20   # primary: 5-day realized vol > 20% annualized
VOL_ALT        = [0.15, 0.25]       # sensitivity thresholds

# Claimed values (from HMM_STABILITY_REPORT.md)
CLAIMED = {
    "pct_ever_flipped":       10.5,
    "avg_quarterly_churn":     1.8,
    "calm_stress_inversions":  0,
    "weekly_annual_agreement": 98.5,
    "covid_recall":            91.6,
    "bear_2022_recall":        80.2,
}

MATERIAL_DIFF = 3.0  # percentage points; flag if measured differs by this much


# ── HMM fitting ───────────────────────────────────────────────────────────────

def _feature_dates(close: pd.Series) -> Tuple[np.ndarray, pd.DatetimeIndex]:
    """Build feature matrix and return (X, valid_dates)."""
    log_ret = np.log(close / close.shift(1))
    real_vol = log_ret.rolling(5).std() * np.sqrt(252)
    df = pd.DataFrame({"lr": log_ret, "rv": real_vol}, index=close.index)
    df = df.dropna()
    return df.values.astype(np.float64), pd.DatetimeIndex(df.index)


def _fit_one(X: np.ndarray, n_init: int) -> Optional[GaussianHMM]:
    """Fit best-of-n_init, sort states. Return None if all seeds degenerate."""
    best_ll = -1e18
    best_m: Optional[GaussianHMM] = None
    for seed in range(n_init):
        try:
            m = GaussianHMM(
                n_components=N_COMPONENTS,
                covariance_type=COV_TYPE,
                n_iter=N_ITER,
                min_covar=MIN_COVAR,
                random_state=seed,
            )
            m.fit(X)
            ll = m.score(X)
            if ll > best_ll:
                best_ll = ll
                best_m = m
        except Exception:
            pass
    if best_m is None:
        return None
    sorted_m = sort_hmm_states(best_m)
    return sorted_m if validate_state_order(sorted_m) else None


# ── Part A ─────────────────────────────────────────────────────────────────────

class ChuRnRow(NamedTuple):
    monday: pd.Timestamp
    quarter: str          # "2017Q1"
    n_common: int         # number of common dates compared
    n_changed: int        # number that changed label
    churn_rate: float     # n_changed / n_common


def _quarter_key(ts: pd.Timestamp) -> str:
    return f"{ts.year}Q{ts.quarter}"


def _mondays_in_range(bdate_index: pd.DatetimeIndex) -> List[pd.Timestamp]:
    return [d for d in bdate_index if d.weekday() == 0]


def run_part_a(
    spy_close: pd.Series,
    n_init: int,
) -> Tuple[Dict[pd.Timestamp, int], List[ChuRnRow], float, float, int]:
    """
    Simulate every-Monday retrain over IS period.

    Returns
    -------
    live_labels      : date -> int state  (for all IS dates)
    churn_rows       : list of ChuRnRow per Monday
    pct_ever_flipped : % of IS dates whose label changed at least once
    avg_q_churn      : average quarterly churn (%)
    calm_stress_inv  : count of Calm<->Stress transitions (across all Monday pairs × all dates)
    """
    is_bindex = pd.bdate_range(IS_START, IS_END)
    mondays = _mondays_in_range(is_bindex)

    # Map IS date -> index for tracking flips
    is_date_set = set(is_bindex)
    is_dates_sorted = sorted(is_bindex)
    date_to_isidx = {d: i for i, d in enumerate(is_dates_sorted)}
    n_is = len(is_dates_sorted)

    flip_count = np.zeros(n_is, dtype=np.int32)  # how many times each IS date flipped
    live_labels: Dict[pd.Timestamp, int] = {}    # IS date -> current label

    # For churn: track current and previous week's (date, label) arrays
    prev_labels_dict: Dict[pd.Timestamp, int] = {}  # date -> label from previous Monday
    churn_rows: List[ChuRnRow] = []
    calm_stress_inv = 0

    total_mondays = len(mondays)
    for mon_i, monday in enumerate(mondays):
        if (mon_i + 1) % 20 == 0 or mon_i == 0:
            print(
                f"  Part A: Monday {mon_i+1}/{total_mondays} ({monday.date()}) …",
                file=sys.stderr,
            )

        # Slice: anchor through this Monday
        close_slice = spy_close[spy_close.index <= monday]
        if len(close_slice) < 40:
            continue

        X, valid_dates = _feature_dates(close_slice)
        model = _fit_one(X, n_init)
        if model is None:
            print(f"  WARNING: fit failed at {monday.date()}, skipping", file=sys.stderr)
            continue

        states = model.predict(X)

        # Build current Monday's label dict (date -> state for all decoded dates)
        curr_labels_dict: Dict[pd.Timestamp, int] = {
            d: int(s) for d, s in zip(valid_dates, states)
        }

        # ── Churn vs previous Monday ──────────────────────────────────────────
        if prev_labels_dict:
            common = [d for d in prev_labels_dict if d in curr_labels_dict]
            n_common = len(common)
            if n_common > 0:
                n_changed = sum(
                    1 for d in common
                    if curr_labels_dict[d] != prev_labels_dict[d]
                )
                churn_rate = n_changed / n_common

                # Calm<->Stress inversions for this week
                for d in common:
                    old = prev_labels_dict[d]
                    new = curr_labels_dict[d]
                    if (old == CALM and new == STRESS) or (old == STRESS and new == CALM):
                        calm_stress_inv += 1

                # Track per-IS-date flips
                for d in common:
                    if d in date_to_isidx:
                        if curr_labels_dict[d] != prev_labels_dict[d]:
                            flip_count[date_to_isidx[d]] += 1

                churn_rows.append(ChuRnRow(
                    monday=monday,
                    quarter=_quarter_key(monday),
                    n_common=n_common,
                    n_changed=n_changed,
                    churn_rate=churn_rate,
                ))

        prev_labels_dict = curr_labels_dict

        # ── Live labels for this Monday ───────────────────────────────────────
        # Assign the current Monday's own label as the live label for this date.
        if monday in curr_labels_dict:
            live_labels[monday] = curr_labels_dict[monday]

    # Fill live labels for non-Monday IS dates (carry forward from last Monday)
    last_label: Optional[int] = None
    for d in is_dates_sorted:
        if d in live_labels:
            last_label = live_labels[d]
        elif last_label is not None:
            live_labels[d] = last_label

    # pct_ever_flipped: fraction of IS dates with any flip
    n_is_with_labels = sum(1 for d in is_dates_sorted if d in live_labels)
    pct_ever_flipped = (
        100.0 * np.sum(flip_count > 0) / n_is if n_is > 0 else 0.0
    )

    # avg quarterly churn
    if churn_rows:
        by_q: Dict[str, List[float]] = {}
        for row in churn_rows:
            by_q.setdefault(row.quarter, []).append(row.churn_rate)
        q_avgs = [np.mean(v) * 100 for v in by_q.values()]
        avg_q_churn = float(np.mean(q_avgs))
    else:
        avg_q_churn = 0.0

    return live_labels, churn_rows, pct_ever_flipped, avg_q_churn, calm_stress_inv


# ── Part B ─────────────────────────────────────────────────────────────────────

def run_part_b(
    spy_close: pd.Series,
    live_labels: Dict[pd.Timestamp, int],
    n_init: int,
) -> List[dict]:
    """
    Compare weekly live_labels vs annual model labels for 2019-2022.
    Fits YE2018 and YE2021 annual models. For each comparison window,
    measures agreement % and disagrement breakdown.
    """
    results = []
    compare_start = "2019-01-01"
    compare_end = "2022-12-31"
    compare_dates = pd.bdate_range(compare_start, compare_end)

    for ye in ANNUAL_YE:
        print(f"  Part B: fitting annual YE{ye} model …", file=sys.stderr)
        close_ye = spy_close[spy_close.index <= f"{ye}-12-31"]
        X_ye, dates_ye = _feature_dates(close_ye)
        model_ye = _fit_one(X_ye, n_init)
        if model_ye is None:
            print(f"  WARNING: annual YE{ye} fit failed, skipping", file=sys.stderr)
            continue

        # Decode through end of compare window with the frozen annual model
        close_full = spy_close[spy_close.index <= compare_end]
        X_full, dates_full = _feature_dates(close_full)
        annual_states = model_ye.predict(X_full)
        annual_label_dict: Dict[pd.Timestamp, int] = {
            d: int(s) for d, s in zip(dates_full, annual_states)
        }

        # Compare for 2019-2022 dates that have both weekly and annual labels
        n_agree = n_disagree = 0
        disagree_types: Dict[str, int] = {}
        for d in compare_dates:
            if d not in live_labels or d not in annual_label_dict:
                continue
            w_lbl = live_labels[d]
            a_lbl = annual_label_dict[d]
            if w_lbl == a_lbl:
                n_agree += 1
            else:
                n_disagree += 1
                key = f"{HMM_STATES[w_lbl]}->{HMM_STATES[a_lbl]}"
                disagree_types[key] = disagree_types.get(key, 0) + 1

        total = n_agree + n_disagree
        agreement_pct = 100.0 * n_agree / total if total > 0 else 0.0

        results.append({
            "ye": ye,
            "total": total,
            "n_agree": n_agree,
            "n_disagree": n_disagree,
            "agreement_pct": agreement_pct,
            "disagree_breakdown": dict(sorted(disagree_types.items(), key=lambda x: -x[1])),
        })

    return results


# ── Part C ─────────────────────────────────────────────────────────────────────

def _vol_ground_truth(spy_close: pd.Series, threshold: float) -> pd.Series:
    """True stress = 5-day realized SPY log-return vol (annualized) > threshold."""
    log_ret = np.log(spy_close / spy_close.shift(1))
    vol_5d = log_ret.rolling(5).std() * np.sqrt(252)
    return vol_5d > threshold


def run_part_c(
    spy_close: pd.Series,
    live_labels: Dict[pd.Timestamp, int],
) -> List[dict]:
    """
    Stress detection recall using objective vol-based ground truth.

    For each window and threshold:
      true_stress  = vol_5d > threshold
      hmm_stress   = weekly label in {Stress, Crisis}
      recall       = |true & hmm| / |true|
    """
    stress_states = {STRESS, N_COMPONENTS - 1}  # Stress=2, Crisis=3

    windows = [
        ("COVID 2020-02-20 to 2020-03-23", COVID_START, COVID_END),
        ("2022 bear 2022-01-01 to 2022-12-31", BEAR_START, BEAR_END),
    ]
    thresholds = [VOL_THRESHOLD] + VOL_ALT

    results = []
    for name, wstart, wend in windows:
        w_dates = pd.bdate_range(wstart, wend)
        row: dict = {"window": name, "n_dates": len(w_dates), "thresholds": []}

        for thresh in thresholds:
            gt = _vol_ground_truth(spy_close, thresh)

            n_true = n_hmm_stress = n_both = n_neither = 0
            for d in w_dates:
                d_ts = pd.Timestamp(d)
                if d_ts not in live_labels:
                    continue
                is_true = bool(gt.get(d_ts, False))
                is_hmm = live_labels[d_ts] in stress_states
                if is_true:
                    n_true += 1
                if is_hmm:
                    n_hmm_stress += 1
                if is_true and is_hmm:
                    n_both += 1
                if not is_true and not is_hmm:
                    n_neither += 1

            recall = 100.0 * n_both / n_true if n_true > 0 else float("nan")
            precision = 100.0 * n_both / n_hmm_stress if n_hmm_stress > 0 else float("nan")

            row["thresholds"].append({
                "threshold": thresh,
                "n_true_stress": n_true,
                "n_hmm_stress": n_hmm_stress,
                "n_overlap": n_both,
                "recall_pct": recall,
                "precision_pct": precision,
            })

        results.append(row)

    return results


# ── Reporting ─────────────────────────────────────────────────────────────────

def _flag(measured: float, claimed: float) -> str:
    diff = abs(measured - claimed)
    if diff > MATERIAL_DIFF:
        return f"  ← MATERIAL DIFF vs claimed {claimed:.1f}%"
    return f"  (claimed {claimed:.1f}%, diff={diff:.1f}pp)"


def _format_report(
    part_a: tuple,
    part_b: list,
    part_c: list,
    n_init: int,
) -> str:
    live_labels, churn_rows, pct_ever_flipped, avg_q_churn, calm_stress_inv = part_a
    lines = [
        "=" * 70,
        "HMM STABILITY MEASURE — Trust Audit Report",
        f"Production settings: {COV_TYPE} covariance, n_init={n_init}, n_iter={N_ITER}",
        f"Anchored-expanding from {ANCHOR}. IS period {IS_START} to {IS_END}.",
        f"Vol ground truth threshold: {VOL_THRESHOLD*100:.0f}% annualized (Part C primary).",
        "=" * 70,
        "",
        "─" * 70,
        "PART A — Weekly Label Churn",
        "─" * 70,
    ]
    n_mondays = len(churn_rows)
    lines.append(f"Monday retrains simulated: {n_mondays}")

    lines.append("")
    lines.append(f"% of IS days ever flipped: {pct_ever_flipped:.1f}%"
                 + _flag(pct_ever_flipped, CLAIMED["pct_ever_flipped"]))
    lines.append(f"Average quarterly churn:   {avg_q_churn:.1f}%"
                 + _flag(avg_q_churn, CLAIMED["avg_quarterly_churn"]))
    lines.append(f"Calm<->Stress inversions:  {calm_stress_inv}"
                 + (f"  ← MATERIAL DIFF vs claimed 0"
                    if calm_stress_inv > 0 else "  (claimed 0, matches)"))

    # Quarterly breakdown
    if churn_rows:
        lines.append("")
        lines.append("Quarterly churn breakdown:")
        by_q: Dict[str, List[float]] = {}
        for r in churn_rows:
            by_q.setdefault(r.quarter, []).append(r.churn_rate * 100)
        for q in sorted(by_q):
            vals = by_q[q]
            lines.append(f"  {q}: avg={np.mean(vals):.2f}%  "
                         f"min={np.min(vals):.2f}%  max={np.max(vals):.2f}%  n={len(vals)} Mondays")

    # Label distribution
    if live_labels:
        label_counts = {}
        for lbl in live_labels.values():
            label_counts[HMM_STATES[lbl]] = label_counts.get(HMM_STATES[lbl], 0) + 1
        total = sum(label_counts.values())
        lines.append("")
        lines.append("IS live-label distribution (weekly carry-forward):")
        for name in ["Calm", "Normal", "Stress", "Crisis"]:
            n = label_counts.get(name, 0)
            lines.append(f"  {name:<8}: {n:4d} days ({100*n/total:.1f}%)")

    lines += [
        "",
        "─" * 70,
        "PART B — Weekly vs Annual Scheme Agreement",
        "─" * 70,
    ]
    if not part_b:
        lines.append("  No annual models converged; Part B not computed.")
    for r in part_b:
        lines.append(f"Annual YE{r['ye']} model vs weekly labels (2019-2022):")
        lines.append(f"  Total days compared: {r['total']}")
        lines.append(f"  Agreement:           {r['agreement_pct']:.1f}%"
                     + _flag(r['agreement_pct'], CLAIMED["weekly_annual_agreement"]))
        lines.append(f"  Disagreements ({r['n_disagree']}):")
        breakdown = r["disagree_breakdown"]
        for pair, count in list(breakdown.items())[:10]:
            pct = 100.0 * count / r["total"]
            lines.append(f"    {pair:<25}: {count:4d} ({pct:.1f}%)")
        lines.append("")

    lines += [
        "─" * 70,
        "PART C — Stress Detection Recall",
        f"Ground truth: SPY 5-day realized vol (annualized) > threshold",
        "─" * 70,
    ]
    claimed_recalls = {
        "COVID 2020-02-20 to 2020-03-23": CLAIMED["covid_recall"],
        "2022 bear 2022-01-01 to 2022-12-31": CLAIMED["bear_2022_recall"],
    }
    for r in part_c:
        lines.append(f"Window: {r['window']}  ({r['n_dates']} trading days)")
        claimed = claimed_recalls.get(r["window"], float("nan"))
        for t in r["thresholds"]:
            marker = " ← PRIMARY" if t["threshold"] == VOL_THRESHOLD else ""
            recall = t["recall_pct"]
            recall_str = f"{recall:.1f}%" if not np.isnan(recall) else "N/A"
            lines.append(
                f"  vol>{t['threshold']*100:.0f}%:  "
                f"true_stress={t['n_true_stress']}d  "
                f"hmm_stress={t['n_hmm_stress']}d  "
                f"overlap={t['n_overlap']}d  "
                f"recall={recall_str}"
                + ((_flag(recall, claimed) if not np.isnan(recall) else "") if t["threshold"] == VOL_THRESHOLD else "")
                + marker
            )
        lines.append("")

    lines += [
        "─" * 70,
        "VERDICT",
        "─" * 70,
    ]
    # Churn verdict
    churn_ok = avg_q_churn < 5.0 and calm_stress_inv == 0
    lines.append(f"Keep-weekly retrain: {'SUPPORTED' if churn_ok else 'REVIEW NEEDED'}")
    lines.append(f"  Low quarterly churn ({avg_q_churn:.1f}%) and "
                 + (f"zero" if calm_stress_inv == 0 else f"{calm_stress_inv}")
                 + " Calm<->Stress inversions"
                 + (" → labels are stable between retrains." if churn_ok else " → INVESTIGATE."))

    # Agreement verdict
    for r in part_b:
        agr_ok = r["agreement_pct"] >= 95.0
        lines.append(f"Annual YE{r['ye']} agreement {r['agreement_pct']:.1f}%: "
                     + ("consistent with weekly scheme" if agr_ok else "MATERIAL DIVERGENCE — investigate"))

    # Recall verdict
    for r in part_c:
        for t in r["thresholds"]:
            if t["threshold"] == VOL_THRESHOLD:
                recall = t["recall_pct"]
                if not np.isnan(recall):
                    recall_ok = recall >= 70.0
                    lines.append(f"Stress detection ({r['window'][:10]}): recall={recall:.1f}% "
                                 + ("— adequate" if recall_ok else "— BELOW THRESHOLD, investigate"))

    lines.append("")
    lines.append("Claimed vs measured (primary threshold):")
    lines.append(f"  pct_ever_flipped:       claimed={CLAIMED['pct_ever_flipped']:.1f}%   measured={pct_ever_flipped:.1f}%")
    lines.append(f"  avg_quarterly_churn:    claimed={CLAIMED['avg_quarterly_churn']:.1f}%    measured={avg_q_churn:.1f}%")
    lines.append(f"  calm_stress_inversions: claimed={int(CLAIMED['calm_stress_inversions'])}       measured={calm_stress_inv}")
    for r in part_b:
        lines.append(f"  agreement_YE{r['ye']}:      claimed={CLAIMED['weekly_annual_agreement']:.1f}%  measured={r['agreement_pct']:.1f}%")
    for r in part_c:
        for t in r["thresholds"]:
            if t["threshold"] == VOL_THRESHOLD:
                recall = t["recall_pct"]
                ckey = "covid_recall" if "COVID" in r["window"] else "bear_2022_recall"
                recall_str = f"{recall:.1f}%" if not np.isnan(recall) else "N/A"
                lines.append(f"  {ckey}:  claimed={CLAIMED[ckey]:.1f}%  measured={recall_str}")

    lines.append("=" * 70)
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="HMM stability re-measurement (Parts A, B, C)")
    ap.add_argument("--fast", action="store_true",
                    help=f"Use n_init={N_INIT_FAST} instead of {N_INIT_PROD} for quick validation")
    ap.add_argument("--out", default=None, help="Output file path (default: configs/hmm_stability_report.txt)")
    args = ap.parse_args()

    n_init = N_INIT_FAST if args.fast else N_INIT_PROD
    mode = "FAST" if args.fast else "PRODUCTION"
    print(f"HMM Stability Measure — {mode} settings (n_init={n_init})", file=sys.stderr)

    if not _SPY_PATH.exists():
        print(f"ERROR: {_SPY_PATH} not found. Run from d:\\raits.", file=sys.stderr)
        sys.exit(1)

    spy_close = pd.read_parquet(_SPY_PATH)["close"]
    spy_close = spy_close[spy_close.index <= IS_END]
    spy_close.index = pd.DatetimeIndex(spy_close.index).normalize()

    print("Part A: weekly churn simulation …", file=sys.stderr)
    pa = run_part_a(spy_close, n_init)

    print("Part B: annual model agreement …", file=sys.stderr)
    pb = run_part_b(spy_close, pa[0], n_init)

    print("Part C: stress detection recall …", file=sys.stderr)
    pc = run_part_c(spy_close, pa[0])

    report = _format_report(pa, pb, pc, n_init)
    print(report)

    if args.out:
        out = Path(args.out)
    else:
        out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "hmm_stability_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
