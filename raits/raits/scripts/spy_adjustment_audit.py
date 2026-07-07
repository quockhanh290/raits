"""
spy_adjustment_audit.py
=======================
AUDIT ONLY -- no code changes, no model saves.

Measures the SPY adjustment inconsistency between:
  A) 5-min-derived daily close  (split-only) -- what HMM actually trains on
  B) daily-parquet close        (split+div adj.) -- what scanner uses

LABEL-SWITCHING FIX:
  Comparing two independently-fit HMMs by raw state index is invalid --
  hmmlearn assigns arbitrary indices. Fix: sort both models by the production
  criterion (variance*1.0 + mean_return*0.1, ascending) before comparing.

  We report BOTH:
    raw   = GaussianHMM fitted directly, indices compared as-is (WRONG method)
    sorted = HMMEngine.fit() which already applies sort_hmm_states (CORRECT)
  The gap between raw and sorted shows the label-switching artifact.

  HMMEngine.fit() already calls sort_hmm_states internally (hmm/engine.py:142),
  so the sorted comparison is exactly what the production engine does.

STEP 1 FINDING (from code trace, hardcoded):
  SPY_daily_2007_2024.parquet NOT present -> fallback used
  Initial fit:    to_daily_close(spy_data) = 5-min resample = SPLIT-ONLY
  Weekly retrain: same spy_data source              = SPLIT-ONLY
  Both use identical basis -- no init-vs-retrain inconsistency.

Run from d:\\raits\\raits:
    python raits/scripts/spy_adjustment_audit.py *> spy_audit_output.txt
"""
from __future__ import annotations
import glob
import os
import sys
import warnings
warnings.filterwarnings("ignore")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

from raits.hmm.engine import HMMEngine, N_COMPONENTS, N_ITER, N_INIT, RANDOM_SEED
from raits.hmm.features import build_feature_matrix
from raits.hmm.state_sorting import HMM_STATES, validate_state_order

# ── Paths ──────────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CACHE_BASE   = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", "data", "cache"))
CACHE_5MIN   = os.path.join(CACHE_BASE, "data")
CACHE_DAILY  = os.path.join(CACHE_BASE, "daily")

INTERVAL     = 5
EXDIV_THRESH = 0.0008     # 0.08% -- above rounding noise, below normal daily moves


# ── Data loaders ───────────────────────────────────────────────────────────────

def load_5min_derived_daily(ticker: str = "SPY") -> pd.Series:
    """Last 5-min bar close of each market day -> split-only (production basis)."""
    pattern = os.path.join(CACHE_5MIN, f"{ticker}_{INTERVAL}min_*.parquet")
    files   = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No 5-min parquets for {ticker} in {CACHE_5MIN}\n"
            "Run wfo_real_run.py first."
        )
    df = pd.concat([pd.read_parquet(f) for f in files])
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index().pipe(lambda x: x[~x.index.duplicated(keep="first")])
    df = df.between_time("09:30", "16:00")
    return df["close"].resample("B").last().dropna()


def load_daily_parquet(ticker: str = "SPY") -> pd.Series:
    """Daily parquet close -- split+dividend adjusted."""
    pattern = os.path.join(CACHE_DAILY, f"{ticker}_daily_*.parquet")
    files   = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No daily parquets for {ticker} in {CACHE_DAILY}\n"
            "Run fetch_daily_data.py first."
        )
    df = pd.concat([pd.read_parquet(f) for f in files])
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index().pipe(lambda x: x[~x.index.duplicated(keep="first")])
    return df["close"]


# ── HMM helpers ────────────────────────────────────────────────────────────────

def fit_raw_hmm(spy_close: pd.Series) -> GaussianHMM:
    """Fit bare GaussianHMM WITHOUT state sorting (raw index comparison)."""
    X = build_feature_matrix(spy_close)
    rng = np.random.RandomState(RANDOM_SEED)
    best_model, best_ll = None, -np.inf
    for _ in range(N_INIT):
        seed = rng.randint(0, 2**31 - 1)
        m = GaussianHMM(n_components=N_COMPONENTS, covariance_type="diag",
                        n_iter=N_ITER, random_state=seed, verbose=False)
        try:
            m.fit(X)
            ll = m.score(X)
            if ll > best_ll:
                best_ll, best_model = ll, m
        except Exception:
            continue
    if best_model is None:
        raise RuntimeError("All raw HMM inits failed")
    return best_model


def predict_raw_indices(raw_model: GaussianHMM, spy_close: pd.Series) -> pd.Series:
    """Viterbi with raw (unsorted) model; return state indices as strings."""
    X = build_feature_matrix(spy_close)
    states = raw_model.predict(X)
    idx = spy_close.index[-len(states):]
    return pd.Series([str(s) for s in states], index=idx)


def fit_sorted_engine(spy_close: pd.Series) -> HMMEngine:
    """Fit HMMEngine -- sort_hmm_states already applied internally (engine.py:142)."""
    engine = HMMEngine()
    engine.fit(spy_close, save=False)
    return engine


def predict_named(engine: HMMEngine, spy_close: pd.Series) -> pd.Series:
    """Viterbi decode using sorted model; return named labels."""
    raw = engine.predict_sequence(spy_close)
    idx = spy_close.index[-len(raw):]
    return pd.Series([HMM_STATES[s] for s in raw], index=idx)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    SEP = "=" * 65

    # ── STEP 1: Adjustment basis report ──────────────────────────────────────
    hist_path = os.path.normpath(os.path.join(CACHE_DAILY, "SPY_daily_2007_2024.parquet"))
    print(SEP)
    print("STEP 1 -- HMM Training Basis (code trace result)")
    print(SEP)
    if os.path.exists(hist_path):
        print("  SPY_daily_2007_2024.parquet: FOUND")
        print("  Initial fit basis : DAILY PARQUET (div-adjusted, 2007+)")
        print("  Weekly retrain    : 5-MIN RESAMPLE (split-only)")
        print("  *** DIFFERENT BASIS between initial fit and weekly retrain ***")
        initial_basis = "div-adjusted"
    else:
        print("  SPY_daily_2007_2024.parquet: NOT FOUND (fallback used)")
        print("  Initial fit basis : 5-MIN RESAMPLE (split-only)")
        print("  Weekly retrain    : 5-MIN RESAMPLE (split-only)")
        print("  Same basis -- no init-vs-retrain inconsistency.")
        initial_basis = "split-only"

    # ── Load data ──────────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("Loading data...")
    print(SEP)

    print("  Loading 5-min derived daily (split-only)...")
    try:
        close_5min = load_5min_derived_daily()
        print(f"    {len(close_5min)} days  "
              f"{close_5min.index[0].date()} to {close_5min.index[-1].date()}")
    except FileNotFoundError as e:
        print(f"  FAIL: {e}"); sys.exit(1)

    print("  Loading daily parquet (div-adjusted)...")
    try:
        close_daily = load_daily_parquet()
        print(f"    {len(close_daily)} days  "
              f"{close_daily.index[0].date()} to {close_daily.index[-1].date()}")
    except FileNotFoundError as e:
        print(f"  FAIL: {e}"); sys.exit(1)

    common = close_5min.index.intersection(close_daily.index)
    a = close_5min.loc[common].rename("split_only")
    b = close_daily.loc[common].rename("div_adjusted")
    print(f"\n  Common period: {len(common)} days  "
          f"{common[0].date()} to {common[-1].date()}")

    # ── DELIVERABLE 1: Ex-div date detection ──────────────────────────────────
    print(f"\n{SEP}")
    print("DELIVERABLE 1 -- Ex-div event detection")
    print(SEP)

    ret_a = np.log(a / a.shift(1)).dropna()
    ret_b = np.log(b / b.shift(1)).dropna()
    common_ret = ret_a.index.intersection(ret_b.index)
    gap = (ret_a.loc[common_ret] - ret_b.loc[common_ret])
    exdiv = gap[gap.abs() > EXDIV_THRESH].sort_index()

    print(f"  Return-gap threshold: {EXDIV_THRESH*100:.2f}%")
    print(f"  Divergence events:    {len(exdiv)}")
    if len(exdiv) == 0:
        print("  -> NO inconsistency at this threshold.")
    else:
        print(f"\n  {'Date':<14} {'Gap (5min-daily)':<22} {'Interpretation'}")
        print(f"  {'-'*56}")
        for dt, v in exdiv.items():
            sign = "ex-div (price drop)" if v < 0 else "positive gap"
            print(f"  {str(dt.date()):<14} {v*100:+.4f}%               {sign}")
        print(f"\n  Total gap magnitude: {exdiv.abs().sum()*100:.3f}% over {len(exdiv)} events")
        print(f"  Mean gap per event:  {exdiv.abs().mean()*100:.3f}%")

    # ── DELIVERABLE 2: HMM label impact (label-switching fix) ─────────────────
    print(f"\n{SEP}")
    print("DELIVERABLE 2 -- HMM label impact (label-switching fixed)")
    print(SEP)

    # Raw (unsorted) GaussianHMM -- shows label-switching artifact
    print("\n  Fitting raw HMM-A (split-only, NO sort)...")
    raw_a = fit_raw_hmm(a)
    print("  Fitting raw HMM-B (div-adjusted, NO sort)...")
    raw_b = fit_raw_hmm(b)

    labels_a_raw = predict_raw_indices(raw_a, a)
    labels_b_raw = predict_raw_indices(raw_b, b)
    ci_raw = labels_a_raw.index.intersection(labels_b_raw.index)
    la_raw = labels_a_raw.loc[ci_raw]
    lb_raw = labels_b_raw.loc[ci_raw]
    n_raw   = (la_raw != lb_raw).sum()
    pct_raw = n_raw / len(la_raw) * 100
    print(f"\n  Raw label diffs (unsorted): {n_raw}/{len(la_raw)} = {pct_raw:.2f}%")
    print("  (inflated by label-switching -- NOT the real number)")

    # Sorted via HMMEngine (production-consistent)
    print("\n  Fitting sorted HMM-A (split-only) via HMMEngine...")
    eng_a = fit_sorted_engine(a)
    print(f"    validate_state_order: {validate_state_order(eng_a.model)}")
    print("  Fitting sorted HMM-B (div-adjusted) via HMMEngine...")
    eng_b = fit_sorted_engine(b)
    print(f"    validate_state_order: {validate_state_order(eng_b.model)}")

    labels_a = predict_named(eng_a, a)
    labels_b = predict_named(eng_b, b)

    ci = labels_a.index.intersection(labels_b.index)
    la = labels_a.loc[ci]
    lb = labels_b.loc[ci]
    n_diff  = (la != lb).sum()
    n_total = len(la)
    pct     = n_diff / n_total * 100

    print(f"\n  Sorted label diffs (production-consistent): {n_diff}/{n_total} = {pct:.2f}%")
    print(f"  Label-switching artifact removed: {pct_raw - pct:+.2f}pp")

    # Distribution
    dist_a = la.value_counts().sort_index()
    dist_b = lb.value_counts().sort_index()
    all_states = sorted(set(dist_a.index) | set(dist_b.index))

    print(f"\n  {'State':<10} {'HMM-A (split)':<18} {'HMM-B (div-adj)':<18} {'D days'}")
    print(f"  {'-'*60}")
    for s in all_states:
        ca = dist_a.get(s, 0)
        cb = dist_b.get(s, 0)
        print(f"  {s:<10} {ca:<18} {cb:<18} {cb-ca:+d}")

    # Transition matrix
    print(f"\n  Transition matrix (row=A split-only, col=B div-adjusted):")
    states_ordered = ["Calm", "Normal", "Stress", "Crisis"]
    corner = "A/B"
    print(f"  {corner:<10}" + "".join(f"{s:<10}" for s in states_ordered))
    calm_stress_flips = 0
    for sa in states_ordered:
        if (la == sa).sum() == 0:
            continue
        row = f"  {sa:<10}"
        for sb in states_ordered:
            cnt = int(((la == sa) & (lb == sb)).sum())
            row += f"{cnt:<10}"
            if sa != sb and {sa, sb} == {"Calm", "Stress"}:
                calm_stress_flips += cnt
        print(row)

    print(f"\n  Off-diagonal (regime changes between bases):")
    any_offdiag = False
    for sa in states_ordered:
        for sb in states_ordered:
            if sa != sb:
                cnt = int(((la == sa) & (lb == sb)).sum())
                if cnt > 0:
                    danger = " *** DANGEROUS" if {sa, sb} == {"Calm", "Stress"} else ""
                    print(f"    {sa} -> {sb}: {cnt} days{danger}")
                    any_offdiag = True
    if not any_offdiag:
        print("    (none)")
    print(f"\n  Calm<->Stress direct flips: {calm_stress_flips}")

    # ── DELIVERABLE 3: Weekly-retrain churn ───────────────────────────────────
    print(f"\n{SEP}")
    print("DELIVERABLE 3 -- Weekly-retrain churn (A vs B)")
    print(SEP)
    print("  Simulating Monday retrains (sorted models)...")

    mondays = pd.date_range(common[0], common[-1], freq="W-MON")
    churn_a, churn_b = [], []
    prev_la = prev_lb = None

    for mon in mondays:
        wa = a[a.index <= mon]
        wb = b[b.index <= mon]
        if len(wa) < 35 or len(wb) < 35:
            continue
        try:
            ha = fit_sorted_engine(wa)
            hb = fit_sorted_engine(wb)
        except Exception:
            continue
        cur_la = predict_named(ha, wa)
        cur_lb = predict_named(hb, wb)
        if prev_la is not None:
            ov = prev_la.index.intersection(cur_la.index)
            if len(ov) > 0:
                churn_a.append((cur_la.loc[ov] != prev_la.loc[ov]).mean())
                churn_b.append((cur_lb.loc[ov] != prev_lb.loc[ov]).mean())
        prev_la, prev_lb = cur_la, cur_lb

    churn_delta = 0.0
    if churn_a:
        churn_delta = (np.mean(churn_b) - np.mean(churn_a)) * 100
        print(f"\n  Retrains simulated: {len(churn_a)}")
        print(f"  Avg churn A (split):    {np.mean(churn_a)*100:.2f}%  "
              f"max={max(churn_a)*100:.2f}%")
        print(f"  Avg churn B (div-adj):  {np.mean(churn_b)*100:.2f}%  "
              f"max={max(churn_b)*100:.2f}%")
        print(f"  D churn (B-A):         {churn_delta:+.3f}%")
    else:
        print("  Not enough data.")

    # ── DELIVERABLE 4: Quarterly churn ────────────────────────────────────────
    print(f"\n{SEP}")
    print("DELIVERABLE 4 -- Quarterly churn")
    print(SEP)

    quarters = pd.date_range(common[0], common[-1], freq="QS")
    q_churn_a, q_churn_b = [], []
    prev_qa = prev_qb = None

    for q in quarters:
        wa = a[a.index <= q]
        wb = b[b.index <= q]
        if len(wa) < 35 or len(wb) < 35:
            continue
        try:
            ha = fit_sorted_engine(wa)
            hb = fit_sorted_engine(wb)
        except Exception:
            continue
        cur_qa = predict_named(ha, wa)
        cur_qb = predict_named(hb, wb)
        if prev_qa is not None:
            ov = prev_qa.index.intersection(cur_qa.index)
            if len(ov) > 0:
                q_churn_a.append((cur_qa.loc[ov] != prev_qa.loc[ov]).mean())
                q_churn_b.append((cur_qb.loc[ov] != prev_qb.loc[ov]).mean())
        prev_qa, prev_qb = cur_qa, cur_qb

    q_delta = 0.0
    if q_churn_a:
        q_delta = (np.mean(q_churn_b) - np.mean(q_churn_a)) * 100
        print(f"\n  Quarterly retrains: {len(q_churn_a)}")
        print(f"  Avg churn A (split):    {np.mean(q_churn_a)*100:.2f}%")
        print(f"  Avg churn B (div-adj):  {np.mean(q_churn_b)*100:.2f}%")
        print(f"  D (B-A):               {q_delta:+.3f}%")
    else:
        print("  Not enough data.")

    # ── DELIVERABLE 5: Two-basis interaction ──────────────────────────────────
    print(f"\n{SEP}")
    print("DELIVERABLE 5 -- Two-basis interaction (ex-div windows)")
    print(SEP)
    if len(exdiv) > 0:
        affected = set()
        for d in exdiv.index:
            for offset in range(-2, 3):
                affected.add(d + pd.offsets.BusinessDay(offset))
        affected_idx = la.index[la.index.isin(affected)]
        if len(affected_idx) > 0:
            la_aff = la.loc[la.index.isin(affected_idx)]
            lb_aff = lb.loc[lb.index.isin(affected_idx)]
            n_aff  = (la_aff != lb_aff).sum()
            pct_aff = n_aff / len(la_aff) * 100
            print(f"\n  Days within +-2 bdays of ex-div: {len(affected_idx)}")
            print(f"  Label diffs on those days:        {n_aff} ({pct_aff:.1f}%)")
            if n_aff == 0:
                print("  -> No label conflict on ex-div windows. Two-basis risk = LOW.")
            else:
                print(f"  -> {n_aff} conflicting labels near ex-div dates.")
        else:
            print("  No common dates near ex-div events.")
    else:
        print("  No ex-div divergence detected -> two-basis interaction = N/A.")

    # ── SUMMARY + VERDICT ─────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)
    print(f"  Training basis (initial fit):    {initial_basis}")
    print(f"  Training basis (weekly retrain): split-only (5-min resample)")
    print()
    print(f"  Ex-div events detected:          {len(exdiv)}")
    print(f"  Label diffs (raw/unsorted):      {n_raw}/{len(la_raw)} = {pct_raw:.2f}%")
    print(f"  Label diffs (sorted, REAL):      {n_diff}/{n_total} = {pct:.2f}%")
    print(f"  Label-switching artifact:        {pct_raw - pct:+.2f}pp")
    print(f"  Calm<->Stress direct flips:      {calm_stress_flips}")
    if churn_a:
        print(f"  Weekly churn D (B-A):            {churn_delta:+.3f}%")
    if q_churn_a:
        print(f"  Quarterly churn D (B-A):         {q_delta:+.3f}%")
    print()

    if pct < 2.0 and calm_stress_flips == 0:
        print("  VERDICT: NEGLIGIBLE")
        print("    Sorted label diffs <2%, no Calm<->Stress flips.")
        print("    Adjustment inconsistency does not materially affect regime labels.")
        print("    No data-basis fix required.")
    elif calm_stress_flips > 0:
        print(f"  VERDICT: MATERIAL")
        print(f"    {calm_stress_flips} Calm<->Stress flips -- changes entire active strategy set.")
        print("    Requires data-basis fix + full IS re-validation.")
    else:
        print(f"  VERDICT: MODERATE")
        print(f"    {pct:.1f}% sorted label diffs, no direct Calm<->Stress flips.")
        print("    Normal<->Calm or Normal<->Stress flips affect strategy routing.")
        print("    Consider data-basis fix before OOS vault.")


if __name__ == "__main__":
    main()
