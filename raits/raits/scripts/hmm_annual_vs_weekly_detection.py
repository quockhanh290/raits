"""
scripts/hmm_annual_vs_weekly_detection.py
------------------------------------------
HEAD-TO-HEAD: Annual re-freeze vs weekly-expanding stress detection.

Answers whether annual or weekly retrain detects stress better on the SAME
objective ground truth used in hmm_stability_measure.py Part C (SPY 5-day
realized vol > 20% annualized). Judgment is by detection metrics only — no P&L.

Pre-committed decision criteria (stated here, before measurement):
  - Annual recall within ~5-10pp of weekly on BOTH windows: keep weekly.
    Switching cost (full re-validation + burns 2025) outweighs small parity gain.
  - Annual exceeds weekly by >10pp on recall AND false-alarm rate is not worse:
    flag as a structural reason to reconsider — magnitude reported, must still
    be weighed against switching cost.
  - Weekly beats annual (or roughly equal): weekly confirmed on detection merits
    independently of cost arguments.

Annual scheme: YE2018 model labels COVID-2020 and 2019-false-alarm.
              YE2021 model labels 2022 bear.
Rationale: user-specified annual re-freeze schedule.

COMPARISON NOTE:
  Annual labels here use INCREMENTAL Viterbi — for each window date d, the
  frozen annual model decodes all data 2007→d (model parameters frozen at YE).
  Weekly labels use Monday carry-forward (same method as hmm_stability_measure.py).
  For dates that are not Mondays, the annual model has MORE data than weekly
  (annual sees through d; weekly sees only through the last Monday M <= d).
  This is a slight advantage for annual — noted in report.

Production settings: diag, n_init=10, n_iter=200, anchored from 2007.
Run time: ~15-25 min (production), ~6-10 min (--fast, n_init=3).

Usage:
    python scripts/hmm_annual_vs_weekly_detection.py
    python scripts/hmm_annual_vs_weekly_detection.py --fast
    python scripts/hmm_annual_vs_weekly_detection.py --out path/to/report.txt
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

# Annual model assignment (per user spec)
ANNUAL_YEARS = {
    "false_alarm": 2018,   # 2019 calm reference → YE2018
    "covid":       2018,   # COVID Feb-Mar 2020 → YE2018
    "bear_2022":   2021,   # 2022 bear → YE2021
}

# Detection windows
WINDOWS = {
    "false_alarm": ("2019-01-01", "2019-12-31"),
    "covid":       ("2020-02-20", "2020-03-23"),
    "bear_2022":   ("2022-01-01", "2022-12-31"),
}

VOL_PRIMARY = 0.20
VOL_ALT     = [0.15, 0.25]

N_COMPONENTS  = 4
COV_TYPE      = "diag"
N_ITER        = 200
MIN_COVAR     = 1e-2
N_INIT_PROD   = 10
N_INIT_FAST   = 3

STRESS_STATES = {STRESS, N_COMPONENTS - 1}   # Stress=2, Crisis=3

# Pre-committed thresholds for verdict
MATERIAL_DIFF_PP = 10.0    # >10pp recall difference = material
ROUGH_EQUAL_PP   = 5.0     # <=5pp = roughly equal → keep weekly


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


# ── Annual labels ─────────────────────────────────────────────────────────────

def build_annual_labels(
    spy_close: pd.Series,
    n_init: int,
) -> Dict[str, Dict[pd.Timestamp, int]]:
    """
    Fit annual models and compute per-window labels using INCREMENTAL Viterbi.

    For each window date d, the frozen annual model decodes 2007→d.
    The label for d = last element of that Viterbi path.
    This is the 'live' annual label: model parameters frozen at YE, but
    each new day's observation updates the Viterbi path.

    Annual has a slight information advantage vs weekly on non-Monday dates
    (annual sees through d; weekly carry-forward sees through last Monday).
    Noted in report as conservative-for-weekly comparison.
    """
    # Fit unique annual models
    unique_yes = sorted(set(ANNUAL_YEARS.values()))
    annual_models: Dict[int, Optional[GaussianHMM]] = {}
    for ye in unique_yes:
        print(f"  Annual YE{ye}: fitting on 2007-{ye}-12-31 ...", file=sys.stderr)
        close_ye = spy_close[spy_close.index <= f"{ye}-12-31"]
        X_ye, _ = _feature_dates(close_ye)
        m = _fit_one(X_ye, n_init)
        if m is None:
            print(f"  WARNING: YE{ye} model fit failed!", file=sys.stderr)
        annual_models[ye] = m
        print(f"  Annual YE{ye}: done.", file=sys.stderr)

    # Compute incremental labels for each window
    result: Dict[str, Dict[pd.Timestamp, int]] = {}
    for win_key, (w_start, w_end) in WINDOWS.items():
        ye = ANNUAL_YEARS[win_key]
        m = annual_models[ye]
        if m is None:
            result[win_key] = {}
            continue

        w_dates = [d for d in pd.bdate_range(w_start, w_end) if d in spy_close.index]
        labels: Dict[pd.Timestamp, int] = {}

        for i, d in enumerate(w_dates):
            close_through_d = spy_close[spy_close.index <= d]
            X, feat_dates = _feature_dates(close_through_d)
            if len(X) == 0 or d not in feat_dates:
                continue
            states = m.predict(X)
            # label for d = last element (d is the last date in feat_dates)
            labels[d] = int(states[-1])

        result[win_key] = labels
        print(
            f"  Annual YE{ye} labels for {win_key}: {len(labels)} dates.",
            file=sys.stderr,
        )

    return result


# ── Weekly labels ─────────────────────────────────────────────────────────────

def _mondays_for_ranges(ranges: List[Tuple[str, str]]) -> List[pd.Timestamp]:
    """All bdate Mondays across multiple date ranges."""
    mondays = set()
    for start, end in ranges:
        for d in pd.bdate_range(start, end):
            if d.weekday() == 0:
                mondays.add(d)
    return sorted(mondays)


def build_weekly_labels(
    spy_close: pd.Series,
    n_init: int,
) -> Dict[str, Dict[pd.Timestamp, int]]:
    """
    Fit Monday-expanding models for the windows that need weekly labels.
    Carry-forward Monday labels to non-Monday dates.

    Ranges fitted (only what is needed):
      - 2018-12-17 to 2020-03-23  → covers 2019 false-alarm + COVID window
      - 2021-12-20 to 2022-12-31  → covers 2022 bear window

    The first Monday in each range serves as the carry-forward seed for the
    first non-Monday business days in that window.
    """
    fit_ranges = [
        ("2018-12-17", "2020-03-23"),   # 2019 false_alarm + COVID
        ("2021-12-20", "2022-12-31"),   # bear_2022
    ]
    mondays = _mondays_for_ranges(fit_ranges)
    total = len(mondays)
    print(f"  Weekly: {total} Monday fits across 2 date ranges.", file=sys.stderr)

    monday_labels: Dict[pd.Timestamp, int] = {}  # Monday date -> regime label

    for i, monday in enumerate(mondays):
        if (i + 1) % 20 == 0 or i == 0:
            print(
                f"  Weekly Monday {i+1}/{total} ({monday.date()}) ...",
                file=sys.stderr,
            )
        close_slice = spy_close[spy_close.index <= monday]
        if len(close_slice) < 40:
            continue
        X, valid_dates = _feature_dates(close_slice)
        model = _fit_one(X, n_init)
        if model is None:
            continue
        states = model.predict(X)
        date_to_state = {d: int(s) for d, s in zip(valid_dates, states)}
        if monday in date_to_state:
            monday_labels[monday] = date_to_state[monday]

    # Build carry-forward for all relevant business dates
    all_bdates = sorted(
        d for start, end in fit_ranges
        for d in pd.bdate_range(start, end)
    )
    # deduplicate (ranges don't overlap, but just in case)
    all_bdates = sorted(set(all_bdates))

    live_labels: Dict[pd.Timestamp, int] = {}
    last_lbl: Optional[int] = None
    for d in all_bdates:
        if d in monday_labels:
            last_lbl = monday_labels[d]
        if last_lbl is not None:
            live_labels[d] = last_lbl

    # Subset per window
    result: Dict[str, Dict[pd.Timestamp, int]] = {}
    for win_key, (w_start, w_end) in WINDOWS.items():
        w_dates = pd.bdate_range(w_start, w_end)
        result[win_key] = {d: live_labels[d] for d in w_dates if d in live_labels}
        print(
            f"  Weekly labels for {win_key}: {len(result[win_key])} dates.",
            file=sys.stderr,
        )
    return result


# ── Ground truth ──────────────────────────────────────────────────────────────

def vol_ground_truth(spy_close: pd.Series, threshold: float) -> pd.Series:
    """True stress = SPY 5-day realized vol (annualized) > threshold."""
    lr = np.log(spy_close / spy_close.shift(1))
    return lr.rolling(5).std() * np.sqrt(252) > threshold


# ── Metrics ───────────────────────────────────────────────────────────────────

def compute_detection(
    labels: Dict[pd.Timestamp, int],
    gt: pd.Series,
) -> dict:
    """
    For a stress window: recall = overlap / n_true_stress.
    For a calm window: false_alarm_rate = n_hmm_stress / n_non_stress.
    Always computes both so caller can pick.
    """
    n_true = n_hmm = n_overlap = n_non_stress = n_fa = 0
    for d, lbl in labels.items():
        if d not in gt.index:
            continue
        is_gt = bool(gt.loc[d])
        is_hmm = lbl in STRESS_STATES
        if is_gt:
            n_true += 1
        else:
            n_non_stress += 1
        if is_hmm:
            n_hmm += 1
        if is_gt and is_hmm:
            n_overlap += 1
        if not is_gt and is_hmm:
            n_fa += 1

    return {
        "n_days":      len(labels),
        "n_true":      n_true,
        "n_non_stress": n_non_stress,
        "n_hmm":       n_hmm,
        "n_overlap":   n_overlap,
        "n_fa":        n_fa,
        "recall":      100.0 * n_overlap / n_true if n_true > 0 else float("nan"),
        "fa_rate":     100.0 * n_fa / n_non_stress if n_non_stress > 0 else float("nan"),
        "precision":   100.0 * n_overlap / n_hmm if n_hmm > 0 else float("nan"),
    }


# ── Report ─────────────────────────────────────────────────────────────────────

def _nan_str(v: float, fmt: str = ".1f") -> str:
    return "N/A" if (v is None or np.isnan(v)) else f"{v:{fmt}}%"


def _verdict(
    covid_weekly: float, covid_annual: float,
    bear_weekly: float,  bear_annual: float,
    fa_weekly: float,    fa_annual: float,
) -> Tuple[str, str]:
    """
    Apply pre-committed criteria. Returns (case_label, explanation).
    """
    d_covid = covid_annual - covid_weekly
    d_bear  = bear_annual  - bear_weekly
    d_fa    = fa_annual    - fa_weekly      # positive = annual has MORE false alarms

    # Annual materially better on both windows AND false-alarm not worse
    if (d_covid > MATERIAL_DIFF_PP and d_bear > MATERIAL_DIFF_PP
            and not np.isnan(d_fa) and d_fa <= 5.0):
        case = "ANNUAL MATERIALLY BETTER — FLAG FOR RECONSIDERATION"
        explanation = (
            f"Annual exceeds weekly by {d_covid:.1f}pp (COVID) and {d_bear:.1f}pp (2022 bear) "
            f"with false-alarm diff {d_fa:+.1f}pp. "
            f"This is a structural reason to reconsider. "
            f"Must still weigh: full re-validation cost + 2025 data burn."
        )
    # Roughly equal on both windows
    elif abs(d_covid) <= ROUGH_EQUAL_PP and abs(d_bear) <= ROUGH_EQUAL_PP:
        case = "ROUGHLY EQUAL — KEEP WEEKLY"
        explanation = (
            f"Detection gap: COVID={d_covid:+.1f}pp, 2022={d_bear:+.1f}pp "
            f"(both within {ROUGH_EQUAL_PP:.0f}pp). "
            f"Switching cost exceeds any benefit. Weekly confirmed on detection merits."
        )
    # Weekly better or roughly equal with some windows
    elif d_covid <= 0 and d_bear <= 0:
        case = "WEEKLY BETTER OR EQUAL — KEEP WEEKLY"
        explanation = (
            f"Weekly detection at least as good as annual on both windows "
            f"(COVID gap {d_covid:+.1f}pp, 2022 gap {d_bear:+.1f}pp). "
            f"Weekly confirmed on detection merits."
        )
    # Mixed: one window favors annual, other doesn't — within-range differences
    elif max(d_covid, d_bear) < MATERIAL_DIFF_PP:
        case = "MIXED BUT BELOW MATERIAL — KEEP WEEKLY"
        explanation = (
            f"COVID gap {d_covid:+.1f}pp, 2022 gap {d_bear:+.1f}pp. "
            f"Largest difference ({max(d_covid, d_bear):.1f}pp) is below the {MATERIAL_DIFF_PP:.0f}pp "
            f"material threshold. Keep weekly."
        )
    else:
        # Annual better on one window by >10pp
        case = "ANNUAL BETTER ON ONE WINDOW — ASSESS"
        explanation = (
            f"COVID gap {d_covid:+.1f}pp, 2022 gap {d_bear:+.1f}pp. "
            f"Annual exceeds weekly by >{MATERIAL_DIFF_PP:.0f}pp on one window. "
            f"Check false-alarm rate before concluding — recall gain may come at FA cost."
        )
    return case, explanation


def format_report(
    ann_labels: Dict[str, Dict[pd.Timestamp, int]],
    wkl_labels: Dict[str, Dict[pd.Timestamp, int]],
    spy_close: pd.Series,
    n_init: int,
) -> str:
    lines = [
        "=" * 72,
        "HMM Annual vs Weekly Detection — Head-to-Head Comparison",
        f"Production settings: {COV_TYPE} covariance, n_init={n_init}, n_iter={N_ITER}",
        f"Annual scheme: YE2018 model for 2019-2020 | YE2021 model for 2021-2022",
        f"Annual labels: incremental Viterbi (2007→d per date; slight annual advantage",
        f"               on non-Monday dates — conservative comparison vs weekly)",
        f"Weekly labels: Monday carry-forward (same method as hmm_stability_measure.py)",
        f"Ground truth: SPY 5-day realized vol > {VOL_PRIMARY*100:.0f}% annualized (primary)",
        "=" * 72,
    ]

    # ── Per-window detail ─────────────────────────────────────────────────────
    metrics_by_thresh: Dict[str, Dict[str, Dict[float, dict]]] = {}
    for win_key, (w_start, w_end) in WINDOWS.items():
        metrics_by_thresh[win_key] = {"annual": {}, "weekly": {}}
        for thresh in [VOL_PRIMARY] + VOL_ALT:
            gt = vol_ground_truth(spy_close, thresh)
            metrics_by_thresh[win_key]["annual"][thresh] = compute_detection(ann_labels.get(win_key, {}), gt)
            metrics_by_thresh[win_key]["weekly"][thresh] = compute_detection(wkl_labels.get(win_key, {}), gt)

    # ── FALSE-ALARM window (2019) ─────────────────────────────────────────────
    lines += ["", "─" * 72, "FALSE-ALARM WINDOW: 2019-01-01 to 2019-12-31 (calm reference)", "─" * 72]
    lines.append(f"{'':30} {'Annual':>10} {'Weekly':>10}")
    lines.append(f"{'Days with labels':30} "
                 f"{metrics_by_thresh['false_alarm']['annual'][VOL_PRIMARY]['n_days']:>10} "
                 f"{metrics_by_thresh['false_alarm']['weekly'][VOL_PRIMARY]['n_days']:>10}")
    for thresh in [VOL_PRIMARY] + VOL_ALT:
        a = metrics_by_thresh["false_alarm"]["annual"][thresh]
        w = metrics_by_thresh["false_alarm"]["weekly"][thresh]
        primary = " ← PRIMARY" if thresh == VOL_PRIMARY else ""
        lines.append(
            f"  FA rate vol>{thresh*100:.0f}%:{' ':15} "
            f"{_nan_str(a['fa_rate']):>10} {_nan_str(w['fa_rate']):>10}"
            + primary
        )
        lines.append(
            f"    (non-stress days: {a['n_non_stress']:3d}a / {w['n_non_stress']:3d}w  "
            f"false-alarms: {a['n_fa']:3d}a / {w['n_fa']:3d}w)"
        )

    # ── COVID window ─────────────────────────────────────────────────────────
    lines += ["", "─" * 72, "STRESS WINDOW: COVID 2020-02-20 to 2020-03-23", "─" * 72]
    lines.append(f"{'':30} {'Annual':>10} {'Weekly':>10}")
    lines.append(f"{'Days with labels':30} "
                 f"{metrics_by_thresh['covid']['annual'][VOL_PRIMARY]['n_days']:>10} "
                 f"{metrics_by_thresh['covid']['weekly'][VOL_PRIMARY]['n_days']:>10}")
    for thresh in [VOL_PRIMARY] + VOL_ALT:
        a = metrics_by_thresh["covid"]["annual"][thresh]
        w = metrics_by_thresh["covid"]["weekly"][thresh]
        primary = " ← PRIMARY" if thresh == VOL_PRIMARY else ""
        lines.append(
            f"  Recall    vol>{thresh*100:.0f}%:{' ':15} "
            f"{_nan_str(a['recall']):>10} {_nan_str(w['recall']):>10}"
            + primary
        )
        diff = a['recall'] - w['recall'] if not np.isnan(a['recall']) and not np.isnan(w['recall']) else float("nan")
        lines.append(
            f"    (true_stress: {a['n_true']:3d}  hmm: {a['n_hmm']:3d}a/{w['n_hmm']:3d}w  "
            f"overlap: {a['n_overlap']:3d}a/{w['n_overlap']:3d}w  diff: {diff:+.1f}pp)"
        )

    # ── 2022 bear window ──────────────────────────────────────────────────────
    lines += ["", "─" * 72, "STRESS WINDOW: 2022 bear 2022-01-01 to 2022-12-31", "─" * 72]
    lines.append(f"{'':30} {'Annual':>10} {'Weekly':>10}")
    lines.append(f"{'Days with labels':30} "
                 f"{metrics_by_thresh['bear_2022']['annual'][VOL_PRIMARY]['n_days']:>10} "
                 f"{metrics_by_thresh['bear_2022']['weekly'][VOL_PRIMARY]['n_days']:>10}")
    for thresh in [VOL_PRIMARY] + VOL_ALT:
        a = metrics_by_thresh["bear_2022"]["annual"][thresh]
        w = metrics_by_thresh["bear_2022"]["weekly"][thresh]
        primary = " ← PRIMARY" if thresh == VOL_PRIMARY else ""
        lines.append(
            f"  Recall    vol>{thresh*100:.0f}%:{' ':15} "
            f"{_nan_str(a['recall']):>10} {_nan_str(w['recall']):>10}"
            + primary
        )
        diff = a['recall'] - w['recall'] if not np.isnan(a['recall']) and not np.isnan(w['recall']) else float("nan")
        lines.append(
            f"    (true_stress: {a['n_true']:3d}  hmm: {a['n_hmm']:3d}a/{w['n_hmm']:3d}w  "
            f"overlap: {a['n_overlap']:3d}a/{w['n_overlap']:3d}w  diff: {diff:+.1f}pp)"
        )

    # ── Head-to-head table ────────────────────────────────────────────────────
    lines += ["", "─" * 72, "HEAD-TO-HEAD TABLE (primary vol>20% threshold)", "─" * 72]
    header = f"{'Window':<30} {'Weekly':>9} {'Annual':>9} {'Diff':>8} {'Weekly FA':>10} {'Annual FA':>10}"
    lines.append(header)
    lines.append("-" * len(header))

    for win_key, label in [
        ("false_alarm", "2019 (false-alarm)"),
        ("covid",       "COVID Feb-Mar 2020"),
        ("bear_2022",   "2022 bear"),
    ]:
        a = metrics_by_thresh[win_key]["annual"][VOL_PRIMARY]
        w = metrics_by_thresh[win_key]["weekly"][VOL_PRIMARY]
        if win_key == "false_alarm":
            w_metric = _nan_str(w["fa_rate"])
            a_metric = _nan_str(a["fa_rate"])
            diff_val = (a["fa_rate"] - w["fa_rate"]) if not np.isnan(a["fa_rate"]) and not np.isnan(w["fa_rate"]) else float("nan")
            diff_str = f"{diff_val:+.1f}pp" if not np.isnan(diff_val) else "N/A"
            lines.append(f"{'FA rate: ' + label:<30} {w_metric:>9} {a_metric:>9} {diff_str:>8} {'—':>10} {'—':>10}")
        else:
            w_recall = _nan_str(w["recall"])
            a_recall = _nan_str(a["recall"])
            diff_val = (a["recall"] - w["recall"]) if not np.isnan(a["recall"]) and not np.isnan(w["recall"]) else float("nan")
            diff_str = f"{diff_val:+.1f}pp" if not np.isnan(diff_val) else "N/A"
            w_fa = _nan_str(metrics_by_thresh["false_alarm"]["weekly"][VOL_PRIMARY]["fa_rate"])
            a_fa = _nan_str(metrics_by_thresh["false_alarm"]["annual"][VOL_PRIMARY]["fa_rate"])
            lines.append(f"{'Recall: ' + label:<30} {w_recall:>9} {a_recall:>9} {diff_str:>8} {w_fa:>10} {a_fa:>10}")

    # ── Verdict ────────────────────────────────────────────────────────────────
    lines += ["", "─" * 72, "VERDICT (applying pre-committed criteria)", "─" * 72]

    a_covid  = metrics_by_thresh["covid"]["annual"][VOL_PRIMARY]["recall"]
    w_covid  = metrics_by_thresh["covid"]["weekly"][VOL_PRIMARY]["recall"]
    a_bear   = metrics_by_thresh["bear_2022"]["annual"][VOL_PRIMARY]["recall"]
    w_bear   = metrics_by_thresh["bear_2022"]["weekly"][VOL_PRIMARY]["recall"]
    a_fa_19  = metrics_by_thresh["false_alarm"]["annual"][VOL_PRIMARY]["fa_rate"]
    w_fa_19  = metrics_by_thresh["false_alarm"]["weekly"][VOL_PRIMARY]["fa_rate"]

    case, explanation = _verdict(w_covid, a_covid, w_bear, a_bear, w_fa_19, a_fa_19)

    lines.append(f"Pre-committed thresholds: material={MATERIAL_DIFF_PP:.0f}pp, roughly-equal={ROUGH_EQUAL_PP:.0f}pp")
    lines.append("")
    lines.append(f"CASE: {case}")
    lines.append("")
    lines.append(explanation)
    lines.append("")

    # Comparison note
    lines += [
        "─" * 72,
        "COMPARISON NOTE",
        "─" * 72,
        "Annual labels use incremental Viterbi (model parameters frozen at YE; Viterbi",
        "path extends one bar per day). On non-Monday dates, annual has seen more recent",
        "data than weekly (annual through date d; weekly through last Monday M<=d).",
        "Max advantage: 4 days (Fri label sees Mon-Thu data, weekly sees only Mon).",
        "This slightly favors annual recall on early-window dates. The comparison is",
        "conservative vs weekly — if weekly is still competitive, the advantage is robust.",
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
    print(f"Annual vs Weekly Detection — {mode} (n_init={n_init})", file=sys.stderr)

    if not _SPY_PATH.exists():
        print(f"ERROR: {_SPY_PATH} not found. Run from d:\\raits.", file=sys.stderr)
        sys.exit(1)

    spy_close = pd.read_parquet(_SPY_PATH)["close"]
    spy_close.index = pd.DatetimeIndex(spy_close.index).normalize()

    print("Building annual labels...", file=sys.stderr)
    ann_labels = build_annual_labels(spy_close, n_init)

    print("Building weekly labels...", file=sys.stderr)
    wkl_labels = build_weekly_labels(spy_close, n_init)

    report = format_report(ann_labels, wkl_labels, spy_close, n_init)
    print(report)

    if args.out:
        out = Path(args.out)
    else:
        out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "hmm_annual_vs_weekly_detection.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
