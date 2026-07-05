"""
scripts/hmm_retrain_artifact_check.py
--------------------------------------
Verifies whether annual's detection advantage (hmm_annual_vs_weekly_detection.py)
is a real structural finding or a measurement artifact from the different labeling
methods (annual used incremental Viterbi; weekly used Monday carry-forward — giving
annual up to 4 extra days of data on non-Monday dates).

Step 1 — Same-method comparison:
  Re-run with BOTH schemes using MONDAY CARRY-FORWARD:
    For each Monday M, BOTH the annual (frozen YE parameters) and weekly (expanding
    parameters) decode 2007→M and assign M's label, then carry forward Mon-Fri.
    Only variable: model parameters. Eliminates incremental Viterbi advantage entirely.
  Re-measures 2019 false-alarm rate and 2022 recall.

Step 2 — Quarterly mechanism check:
  Tracks weekly vs annual recall per quarter (Q1-Q4) through 2022.
  If weekly recall degrades Q1→Q4 while annual stays ~100%, it confirms
  the adaptation hypothesis: expanding weekly model incorporates 2022 bear data
  and shifts its regime boundaries, starting to call sustained high-vol "Normal".
  Also checks vol profile of missed vs caught days (distinguishes adaptation from
  genuinely lower-vol borderline cases).

Step 3 — Verdict:
  Applies the same pre-committed criteria as the prior script.
  Reports whether annual advantage is real (structural) or artifact.

Production settings: diag, n_init=10, n_iter=200, anchored from 2007.
Runtime: ~15-20 min (production), ~5-8 min (--fast, n_init=3).

Usage:
    python scripts/hmm_retrain_artifact_check.py
    python scripts/hmm_retrain_artifact_check.py --fast
    python scripts/hmm_retrain_artifact_check.py --out path/to/report.txt
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

warnings.filterwarnings("ignore", category=RuntimeWarning)

from hmmlearn.hmm import GaussianHMM
from raits.hmm.state_sorting import (
    CALM, STRESS, HMM_STATES, sort_hmm_states, validate_state_order,
)

_SPY_PATH = Path("raits/data/cache/daily/SPY_daily_2007_2024.parquet")

# Windows and annual model assignment (identical to prior scripts)
WINDOWS = {
    "false_alarm": ("2019-01-01", "2019-12-31"),
    "covid":       ("2020-02-20", "2020-03-23"),
    "bear_2022":   ("2022-01-01", "2022-12-31"),
}
ANNUAL_YEARS = {
    "false_alarm": 2018,
    "covid":       2018,
    "bear_2022":   2021,
}

# Monday fit ranges (same as previous script)
# Range 1 covers false_alarm + COVID; range 2 covers bear_2022.
_RANGE1_END    = pd.Timestamp("2020-03-23")
FIT_RANGES     = [
    ("2018-12-17", "2020-03-23"),
    ("2021-12-20", "2022-12-31"),
]

VOL_PRIMARY    = 0.20
VOL_ALT        = [0.15, 0.25]
N_COMPONENTS   = 4
COV_TYPE       = "diag"
N_ITER         = 200
MIN_COVAR      = 1e-2
N_INIT_PROD    = 10
N_INIT_FAST    = 3
STRESS_STATES  = {STRESS, N_COMPONENTS - 1}   # Stress=2, Crisis=3

# Pre-committed thresholds (same as prior script)
MATERIAL_PP    = 10.0
ROUGH_EQUAL_PP = 5.0


# ── HMM helpers ──────────────────────────────────────────────────────────────

def _feature_dates(close: pd.Series) -> Tuple[np.ndarray, pd.DatetimeIndex]:
    lr = np.log(close / close.shift(1))
    rv = lr.rolling(5).std() * np.sqrt(252)
    df = pd.DataFrame({"lr": lr, "rv": rv}, index=close.index).dropna()
    return df.values.astype(np.float64), pd.DatetimeIndex(df.index)


def _fit_one(X: np.ndarray, n_init: int) -> Optional[GaussianHMM]:
    best_ll, best_m = -1e18, None
    for seed in range(n_init):
        try:
            m = GaussianHMM(
                n_components=N_COMPONENTS, covariance_type=COV_TYPE,
                n_iter=N_ITER, min_covar=MIN_COVAR, random_state=seed,
            )
            m.fit(X)
            ll = m.score(X)
            if ll > best_ll:
                best_ll, best_m = ll, m
        except Exception:
            pass
    if best_m is None:
        return None
    sm = sort_hmm_states(best_m)
    return sm if validate_state_order(sm) else None


def vol_gt(spy_close: pd.Series, threshold: float) -> pd.Series:
    """True stress = SPY 5-day realized vol (annualized) > threshold."""
    lr = np.log(spy_close / spy_close.shift(1))
    return lr.rolling(5).std() * np.sqrt(252) > threshold


def _all_mondays(ranges: List[Tuple[str, str]]) -> List[pd.Timestamp]:
    s = set()
    for start, end in ranges:
        for d in pd.bdate_range(start, end):
            if d.weekday() == 0:
                s.add(d)
    return sorted(s)


def _carry_forward(
    monday_labels: Dict[pd.Timestamp, int],
    ranges: List[Tuple[str, str]],
) -> Dict[pd.Timestamp, int]:
    all_dates = sorted(set(d for s, e in ranges for d in pd.bdate_range(s, e)))
    live: Dict[pd.Timestamp, int] = {}
    last: Optional[int] = None
    for d in all_dates:
        if d in monday_labels:
            last = monday_labels[d]
        if last is not None:
            live[d] = last
    return live


# ── Step 1: same-method labels ────────────────────────────────────────────────

def build_same_method_labels(
    spy_close: pd.Series,
    n_init: int,
) -> Tuple[Dict[str, Dict[pd.Timestamp, int]], Dict[str, Dict[pd.Timestamp, int]]]:
    """
    Both annual and weekly use Monday carry-forward (identical labeling method).

    For each Monday M:
      Annual : frozen YE model  → annual_model.predict(X_M)[-1]
      Weekly : expanding fit    → weekly_model.predict(X_M)[-1]

    X_M = feature_matrix(spy_close[2007:M+1]) — identical for both.
    Only variable: model parameters.
    """
    # Fit annual models ONCE
    annual_models: Dict[int, Optional[GaussianHMM]] = {}
    for ye in sorted(set(ANNUAL_YEARS.values())):
        print(f"  Annual YE{ye}: fitting on 2007-{ye}-12-31 ...", file=sys.stderr)
        close_ye = spy_close[spy_close.index <= f"{ye}-12-31"]
        X_ye, _ = _feature_dates(close_ye)
        annual_models[ye] = _fit_one(X_ye, n_init)
        print(f"  Annual YE{ye}: done.", file=sys.stderr)

    mondays = _all_mondays(FIT_RANGES)
    total = len(mondays)
    print(f"  Same-method: {total} Monday fits.", file=sys.stderr)

    weekly_monday: Dict[pd.Timestamp, int] = {}
    annual_monday: Dict[pd.Timestamp, int] = {}

    for i, monday in enumerate(mondays):
        if (i + 1) % 20 == 0 or i == 0:
            print(f"  Monday {i+1}/{total} ({monday.date()}) ...", file=sys.stderr)

        close_M = spy_close[spy_close.index <= monday]
        if len(close_M) < 40:
            continue
        X, valid_dates = _feature_dates(close_M)
        if monday not in valid_dates:
            continue   # non-trading day (holiday falls on Monday)

        ye = 2018 if monday <= _RANGE1_END else 2021

        # Annual frozen predict on same X as weekly
        m_ann = annual_models.get(ye)
        if m_ann is not None:
            annual_monday[monday] = int(m_ann.predict(X)[-1])

        # Weekly expanding fit + predict on same X
        m_wkl = _fit_one(X, n_init)
        if m_wkl is not None:
            weekly_monday[monday] = int(m_wkl.predict(X)[-1])

    # Carry-forward to daily
    ann_live = _carry_forward(annual_monday, FIT_RANGES)
    wkl_live = _carry_forward(weekly_monday, FIT_RANGES)

    # Subset to each window (trading days only)
    ann_by_win: Dict[str, Dict[pd.Timestamp, int]] = {}
    wkl_by_win: Dict[str, Dict[pd.Timestamp, int]] = {}
    for win_key, (ws, we) in WINDOWS.items():
        w_days = [d for d in pd.bdate_range(ws, we) if d in spy_close.index]
        ann_by_win[win_key] = {d: ann_live[d] for d in w_days if d in ann_live}
        wkl_by_win[win_key] = {d: wkl_live[d] for d in w_days if d in wkl_live}
        print(
            f"  {win_key}: {len(ann_by_win[win_key])} annual / {len(wkl_by_win[win_key])} weekly labels.",
            file=sys.stderr,
        )

    return ann_by_win, wkl_by_win


# ── Step 2: quarterly mechanism ────────────────────────────────────────────────

def quarterly_mechanism(
    wkl_labels: Dict[pd.Timestamp, int],
    ann_labels: Dict[pd.Timestamp, int],
    spy_close: pd.Series,
    year: int = 2022,
) -> List[dict]:
    """
    Per-quarter recall tracking + vol profile of weekly-missed vs weekly-caught
    true-stress days. Confirms or refutes the 'adaptation' hypothesis.

    Adaptation confirmed if:
    1. Weekly recall drops Q1 → Q4
    2. vol of missed days is NOT systematically lower than caught days
       (if missed days are high-vol, the miss is a genuine regime misclassification)
    """
    lr_spy = np.log(spy_close / spy_close.shift(1))
    rolling_vol = lr_spy.rolling(5).std() * np.sqrt(252)
    gt = vol_gt(spy_close, VOL_PRIMARY)

    quarters = [
        ("Q1 Jan-Mar", f"{year}-01-01", f"{year}-03-31"),
        ("Q2 Apr-Jun", f"{year}-04-01", f"{year}-06-30"),
        ("Q3 Jul-Sep", f"{year}-07-01", f"{year}-09-30"),
        ("Q4 Oct-Dec", f"{year}-10-01", f"{year}-12-31"),
    ]

    rows = []
    for qlabel, qstart, qend in quarters:
        q_dates = [d for d in pd.bdate_range(qstart, qend) if d in spy_close.index]
        n_true = n_w_tp = n_a_tp = 0
        missed_vols: List[float] = []
        caught_vols: List[float] = []

        for d in q_dates:
            if d not in gt.index:
                continue
            is_gt = bool(gt.loc[d])
            if not is_gt:
                continue

            vol_d = float(rolling_vol.loc[d]) if d in rolling_vol.index else float("nan")
            w_lbl = wkl_labels.get(d)
            a_lbl = ann_labels.get(d)
            is_w  = (w_lbl in STRESS_STATES) if w_lbl is not None else False
            is_a  = (a_lbl in STRESS_STATES) if a_lbl is not None else False

            n_true += 1
            if is_w:
                n_w_tp += 1
                if not np.isnan(vol_d):
                    caught_vols.append(vol_d)
            else:
                if not np.isnan(vol_d):
                    missed_vols.append(vol_d)
            if is_a:
                n_a_tp += 1

        rows.append({
            "quarter":        qlabel,
            "n_true":         n_true,
            "w_recall":       100.0 * n_w_tp / n_true if n_true > 0 else float("nan"),
            "a_recall":       100.0 * n_a_tp / n_true if n_true > 0 else float("nan"),
            "w_missed_n":     len(missed_vols),
            "missed_avg_vol": float(np.mean(missed_vols)) * 100 if missed_vols else float("nan"),
            "caught_avg_vol": float(np.mean(caught_vols)) * 100 if caught_vols else float("nan"),
        })

    return rows


# ── Metrics helper ─────────────────────────────────────────────────────────────

def compute_detection(labels: Dict[pd.Timestamp, int], gt: pd.Series) -> dict:
    n_true = n_non = n_hmm = n_tp = n_fp = 0
    for d, lbl in labels.items():
        if d not in gt.index:
            continue
        is_gt = bool(gt.loc[d])
        is_h  = lbl in STRESS_STATES
        if is_gt:
            n_true += 1
        else:
            n_non += 1
        if is_h:
            n_hmm += 1
        if is_gt and is_h:
            n_tp += 1
        if not is_gt and is_h:
            n_fp += 1
    return {
        "n_days": len(labels), "n_true": n_true, "n_non": n_non,
        "n_hmm": n_hmm, "n_tp": n_tp, "n_fp": n_fp,
        "recall":    100.0 * n_tp / n_true if n_true > 0 else float("nan"),
        "fa_rate":   100.0 * n_fp / n_non if n_non > 0 else float("nan"),
        "precision": 100.0 * n_tp / n_hmm if n_hmm > 0 else float("nan"),
    }


def _nan_str(v: float, fmt: str = ".1f") -> str:
    return "N/A" if (v is None or np.isnan(v)) else f"{v:{fmt}}%"


# ── Report ─────────────────────────────────────────────────────────────────────

def format_report(
    ann_by_win: Dict[str, Dict],
    wkl_by_win: Dict[str, Dict],
    qrows: List[dict],
    spy_close: pd.Series,
    n_init: int,
) -> str:
    lines = [
        "=" * 72,
        "HMM Retrain Artifact Check — Same-Method + Mechanism",
        f"Settings: {COV_TYPE}, n_init={n_init}, n_iter={N_ITER}",
        "BOTH schemes use Monday carry-forward (identical labeling method).",
        "Annual: frozen YE parameters | Weekly: expanding parameters.",
        "Data seen at each Monday M: identical (2007→M) for both.",
        "Ground truth: SPY 5-day realized vol > 20% annualized (primary).",
        "=" * 72,
    ]

    # Compute all metrics at primary threshold
    all_metrics: Dict[str, Dict[str, Dict[float, dict]]] = {}
    for win_key in WINDOWS:
        all_metrics[win_key] = {"a": {}, "w": {}}
        for thresh in [VOL_PRIMARY] + VOL_ALT:
            gt = vol_gt(spy_close, thresh)
            all_metrics[win_key]["a"][thresh] = compute_detection(ann_by_win.get(win_key, {}), gt)
            all_metrics[win_key]["w"][thresh] = compute_detection(wkl_by_win.get(win_key, {}), gt)

    # ── Step 1 results ────────────────────────────────────────────────────────
    lines += [
        "",
        "─" * 72,
        "STEP 1 — SAME-METHOD COMPARISON",
        "Both Monday carry-forward. Only model parameters differ.",
        "─" * 72,
    ]

    for win_key, title in [
        ("false_alarm", "FALSE-ALARM WINDOW: 2019-01-01 to 2019-12-31 (calm)"),
        ("covid",       "STRESS WINDOW: COVID 2020-02-20 to 2020-03-23"),
        ("bear_2022",   "STRESS WINDOW: 2022 bear 2022-01-01 to 2022-12-31"),
    ]:
        is_fa = (win_key == "false_alarm")
        lines += ["", title]
        lines.append(f"{'':30} {'Annual':>10} {'Weekly':>10}")
        a_p = all_metrics[win_key]["a"][VOL_PRIMARY]
        w_p = all_metrics[win_key]["w"][VOL_PRIMARY]
        lines.append(f"{'Days with labels':30} {a_p['n_days']:>10} {w_p['n_days']:>10}")
        for thresh in [VOL_PRIMARY] + VOL_ALT:
            a = all_metrics[win_key]["a"][thresh]
            w = all_metrics[win_key]["w"][thresh]
            primary = " ← PRIMARY" if thresh == VOL_PRIMARY else ""
            if is_fa:
                diff = a["fa_rate"] - w["fa_rate"] if not (np.isnan(a["fa_rate"]) or np.isnan(w["fa_rate"])) else float("nan")
                diff_str = f"(diff {diff:+.1f}pp)" if not np.isnan(diff) else ""
                lines.append(
                    f"  FA rate vol>{thresh*100:.0f}%:{' ':15} "
                    f"{_nan_str(a['fa_rate']):>10} {_nan_str(w['fa_rate']):>10} {diff_str}"
                    + primary
                )
                lines.append(
                    f"    (non-stress: {a['n_non']:3d}  FAs: {a['n_fp']:3d}a / {w['n_fp']:3d}w)"
                )
            else:
                diff = a["recall"] - w["recall"] if not (np.isnan(a["recall"]) or np.isnan(w["recall"])) else float("nan")
                diff_str = f"(diff {diff:+.1f}pp)" if not np.isnan(diff) else ""
                lines.append(
                    f"  Recall    vol>{thresh*100:.0f}%:{' ':15} "
                    f"{_nan_str(a['recall']):>10} {_nan_str(w['recall']):>10} {diff_str}"
                    + primary
                )
                lines.append(
                    f"    (true_stress: {a['n_true']:3d}  hmm: {a['n_hmm']:3d}a/{w['n_hmm']:3d}w  "
                    f"overlap: {a['n_tp']:3d}a/{w['n_tp']:3d}w)"
                )

    # Head-to-head summary table
    lines += ["", "HEAD-TO-HEAD (primary vol>20%, same-method):"]
    header = f"{'Window':<32} {'Weekly':>9} {'Annual':>9} {'Diff':>8}"
    lines += [header, "-" * len(header)]
    for win_key, label in [
        ("false_alarm", "2019 FA rate"),
        ("covid",       "COVID recall"),
        ("bear_2022",   "2022 bear recall"),
    ]:
        a = all_metrics[win_key]["a"][VOL_PRIMARY]
        w = all_metrics[win_key]["w"][VOL_PRIMARY]
        if win_key == "false_alarm":
            wv, av = w["fa_rate"], a["fa_rate"]
        else:
            wv, av = w["recall"], a["recall"]
        diff = av - wv if not (np.isnan(av) or np.isnan(wv)) else float("nan")
        diff_str = f"{diff:+.1f}pp" if not np.isnan(diff) else "N/A"
        lines.append(f"{label:<32} {_nan_str(wv):>9} {_nan_str(av):>9} {diff_str:>8}")

    # ── Step 2: quarterly mechanism ────────────────────────────────────────────
    lines += [
        "",
        "─" * 72,
        "STEP 2 — QUARTERLY MECHANISM CHECK (2022 bear, same-method labels)",
        "Tracking whether weekly recall degrades Q1→Q4 as model adapts.",
        "─" * 72,
    ]

    q_header = (
        f"{'Quarter':<14} {'True stress':>11} "
        f"{'W recall':>10} {'A recall':>10} "
        f"{'W missed':>10} {'Missed avg vol':>15} {'Caught avg vol':>15}"
    )
    lines += ["", q_header, "-" * len(q_header)]
    for r in qrows:
        lines.append(
            f"{r['quarter']:<14} {r['n_true']:>11} "
            f"{_nan_str(r['w_recall']):>10} {_nan_str(r['a_recall']):>10} "
            f"{r['w_missed_n']:>10} "
            f"{_nan_str(r['missed_avg_vol']):>15} {_nan_str(r['caught_avg_vol']):>15}"
        )

    # Pattern detection
    recalls = [r["w_recall"] for r in qrows if not np.isnan(r["w_recall"])]
    if len(recalls) >= 2:
        trend = recalls[-1] - recalls[0]
        lines.append(
            f"\nWeekly recall trend Q1→Q4: {trend:+.1f}pp "
            + ("(DECLINING — consistent with adaptation)" if trend < -5 else
               "(STABLE — no strong adaptation pattern)" if abs(trend) <= 5 else
               "(RISING — opposite of adaptation)")
        )

    missed_vols_all  = [r["missed_avg_vol"] for r in qrows if not np.isnan(r["missed_avg_vol"])]
    caught_vols_all  = [r["caught_avg_vol"] for r in qrows if not np.isnan(r["caught_avg_vol"])]
    if missed_vols_all and caught_vols_all:
        avg_missed = np.mean(missed_vols_all)
        avg_caught = np.mean(caught_vols_all)
        vol_gap = avg_missed - avg_caught
        lines.append(
            f"Avg vol of weekly-missed days: {avg_missed:.1f}%  |  Avg vol of caught days: {avg_caught:.1f}%"
        )
        lines.append(
            f"Vol gap (missed - caught): {vol_gap:+.1f}pp "
            + ("(missed days have LOWER vol — borderline misses, partially expected)" if vol_gap < -3 else
               "(missed days have SIMILAR vol to caught — genuine regime misclassification)" if abs(vol_gap) <= 3 else
               "(missed days have HIGHER vol — severe adaptation failure: high-vol days relabeled Normal)")
        )

    # ── Step 3: verdict ────────────────────────────────────────────────────────
    lines += [
        "",
        "─" * 72,
        "STEP 3 — VERDICT",
        "─" * 72,
    ]

    a_2022 = all_metrics["bear_2022"]["a"][VOL_PRIMARY]["recall"]
    w_2022 = all_metrics["bear_2022"]["w"][VOL_PRIMARY]["recall"]
    a_fa   = all_metrics["false_alarm"]["a"][VOL_PRIMARY]["fa_rate"]
    w_fa   = all_metrics["false_alarm"]["w"][VOL_PRIMARY]["fa_rate"]
    diff_2022 = a_2022 - w_2022 if not (np.isnan(a_2022) or np.isnan(w_2022)) else float("nan")
    diff_fa   = a_fa - w_fa if not (np.isnan(a_fa) or np.isnan(w_fa)) else float("nan")

    is_material   = (not np.isnan(diff_2022)) and diff_2022 > MATERIAL_PP
    fa_not_worse  = (not np.isnan(diff_fa)) and diff_fa <= 5.0   # annual FA not more than 5pp worse

    # Adaptation pattern
    adapt_confirmed = len(recalls) >= 2 and (recalls[-1] - recalls[0]) < -5

    # Vol profile: are missed days high-vol?
    genuine_miss = False
    if missed_vols_all and caught_vols_all:
        vol_gap = np.mean(missed_vols_all) - np.mean(caught_vols_all)
        genuine_miss = vol_gap >= -3.0   # missed vol ≈ or > caught vol

    lines += [
        f"Same-method 2022 recall:  annual={_nan_str(a_2022)}  weekly={_nan_str(w_2022)}  diff={diff_2022:+.1f}pp",
        f"Same-method 2019 FA rate: annual={_nan_str(a_fa)}   weekly={_nan_str(w_fa)}   diff={diff_fa:+.1f}pp",
        "",
    ]

    if is_material and fa_not_worse:
        if adapt_confirmed and genuine_miss:
            verdict = "STRUCTURAL FINDING CONFIRMED"
            explanation = (
                f"Annual advantage is REAL, not method artifact:\n"
                f"  1. Same-method comparison shows annual still better by {diff_2022:.1f}pp on 2022 recall.\n"
                f"  2. Weekly recall trend Q1→Q4 is {recalls[-1]-recalls[0]:+.1f}pp (declining = adaptation confirmed).\n"
                f"  3. Weekly-missed days have similar vol to caught days (genuine regime misclassification,\n"
                f"     not borderline low-vol cases).\n"
                f"  Mechanism: weekly-expanding model incorporates 2022 bear data and shifts its\n"
                f"  vol-to-regime mapping, relabeling sustained high-vol periods as Normal.\n"
                f"  Annual frozen model maintains YE2021 calibration, which correctly identifies\n"
                f"  the 2022 vol range as Stress.\n\n"
                f"  IMPLICATION: weekly retrain has a structural weakness for slow-grind bear markets.\n"
                f"  Per pre-committed criteria, this is a genuine reason to reconsider annual for equity.\n"
                f"  COST TO WEIGH: full re-validation of paper harness + 2025 data burn (one-use OOS).\n"
                f"  NOT a rollback trigger — present the tradeoff, do not auto-decide."
            )
        elif adapt_confirmed and not genuine_miss:
            verdict = "PARTIALLY STRUCTURAL"
            explanation = (
                f"Annual advantage is {diff_2022:.1f}pp on same-method comparison (material).\n"
                f"Adaptation pattern confirmed (weekly recall drops Q1→Q4).\n"
                f"BUT weekly-missed days have lower vol than caught — some misses are borderline cases.\n"
                f"Adaptation is real but partially affects lower-vol stress days; severe high-vol days\n"
                f"are less affected. Still a structural weakness, but less severe than if all missed days\n"
                f"were high-vol. Weigh carefully against switching cost."
            )
        else:
            verdict = "MATERIAL BUT MECHANISM UNCLEAR"
            explanation = (
                f"Annual {diff_2022:.1f}pp better on same-method comparison (material threshold met).\n"
                f"Adaptation pattern is not clearly confirmed by quarterly analysis.\n"
                f"The advantage exists but the mechanism is uncertain — could be parameter calibration\n"
                f"rather than adaptation drift. Still weigh against switching cost."
            )
    elif not is_material and not np.isnan(diff_2022):
        verdict = "ARTIFACT RULED OUT — ADVANTAGE REDUCED"
        explanation = (
            f"Same-method comparison shows {diff_2022:+.1f}pp annual advantage on 2022 recall.\n"
            f"This is below the {MATERIAL_PP:.0f}pp material threshold.\n"
            f"The prior {11.4:.1f}pp advantage in hmm_annual_vs_weekly_detection.py was PARTLY an artifact\n"
            f"of the different labeling methods (incremental Viterbi vs Monday carry-forward).\n"
            f"Removing the method difference reduces the advantage to sub-material levels.\n"
            f"Keep weekly: switching cost is not justified by this margin."
        )
    else:
        verdict = "INCONCLUSIVE"
        explanation = "Insufficient data to apply pre-committed criteria."

    lines += [f"VERDICT: {verdict}", "", explanation, ""]

    lines += [
        "─" * 72,
        "REFERENCE: prior script result (incremental Viterbi for annual)",
        "  2022 recall: annual 100.0% vs weekly 88.6% (+11.4pp)",
        "  2019 FA rate: annual 4.5% vs weekly 10.9% (-6.4pp for annual)",
        f"  Same-method 2022 diff: {diff_2022:+.1f}pp (reported above)",
        f"  Same-method FA diff:   {diff_fa:+.1f}pp (reported above)",
        "=" * 72,
    ]

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help=f"Use n_init={N_INIT_FAST}")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    n_init = N_INIT_FAST if args.fast else N_INIT_PROD
    mode = "FAST" if args.fast else "PRODUCTION"
    print(f"HMM Artifact Check — {mode} (n_init={n_init})", file=sys.stderr)

    if not _SPY_PATH.exists():
        print(f"ERROR: {_SPY_PATH} not found. Run from d:\\raits.", file=sys.stderr)
        sys.exit(1)

    spy_close = pd.read_parquet(_SPY_PATH)["close"]
    spy_close.index = pd.DatetimeIndex(spy_close.index).normalize()

    print("Step 1: building same-method labels ...", file=sys.stderr)
    ann_by_win, wkl_by_win = build_same_method_labels(spy_close, n_init)

    print("Step 2: quarterly mechanism analysis ...", file=sys.stderr)
    qrows = quarterly_mechanism(wkl_by_win["bear_2022"], ann_by_win["bear_2022"], spy_close)

    report = format_report(ann_by_win, wkl_by_win, qrows, spy_close, n_init)
    print(report)

    if args.out:
        out = Path(args.out)
    else:
        out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "hmm_retrain_artifact_check.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
