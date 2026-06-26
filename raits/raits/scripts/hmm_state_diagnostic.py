#!/usr/bin/env python3
"""
hmm_state_diagnostic.py -- IS only (2017-2022)

PURPOSE
-------
Diagnose what the HMM *actually* does at the day level. Resolves:
  (a) N_COMPONENTS = 4 in engine.py vs only 9 Calm trades in the IS trade log.
  (b) Whether "9 Calm trades" means Calm is rare by day, or just rarely traded.
  (c) Whether Crisis (state 3) can ever come from the HMM predict path.

READ-ONLY. No retraining. No engine/backtest imports. No 2023+ data.

MODEL SOURCING
--------------
Loads the FIRST non-retrain pkl from raits/models/hmm/ -- the initial IS model
trained before the IS period started (2007 - pre-2017 data). The IS WFO also
retrained weekly (~46k retrain pkls exist), but the initial model gives the
cleanest baseline for understanding state structure.

If a --model-pkl path is passed, that model is used instead.

Usage:
  python hmm_state_diagnostic.py [--spy-daily PATH] [--trade-log PATH]
                                  [--model-pkl PATH]
"""

import argparse
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# HMM module imports -- read-only, no engine/backtest code
warnings.filterwarnings("ignore")
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT   = _SCRIPT_DIR.parents[2]   # d:\raits
# Add repo root so that "import raits.hmm.*" resolves to d:\raits\raits\hmm\
sys.path.insert(0, str(_REPO_ROOT))

from raits.hmm.state_sorting import HMM_STATES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IS_START = "2017-01-01"
IS_END   = "2022-12-31"

VOL_OVERRIDE_THRESHOLD = 0.50   # 5-day rvol >= 50% -> Crisis (engine line 685)
SMA_FAST   = 50
SMA_SLOW   = 200
SMA_BULL_THRESHOLD = 0.02       # SMA50 > SMA200 by >2%

# Engine's N_COMPONENTS constant (what engine.py says it should be)
ENGINE_N_COMPONENTS = 4

# Default paths
DEFAULT_SPY_DAILY  = _REPO_ROOT / "raits" / "data" / "cache" / "daily" / "SPY_daily_2007_2024.parquet"
DEFAULT_TRADE_LOG  = _REPO_ROOT / "raits" / "configs" / "wfo_trade_log.csv"
DEFAULT_MODEL_DIR  = _REPO_ROOT / "raits" / "models" / "hmm"


# ===========================================================================
# Pure functions -- unit-testable, no I/O
# ===========================================================================

def count_state_days(states: pd.Series) -> dict:
    """
    Count occurrences of each integer state in a Series.

    Parameters
    ----------
    states : pd.Series of int
        One integer per day.

    Returns
    -------
    dict mapping state_idx (int) -> count (int), sorted by state_idx.
    """
    counts = {}
    for s in states.dropna():
        k = int(s)
        counts[k] = counts.get(k, 0) + 1
    return dict(sorted(counts.items()))


def is_bull_day(
    sma_fast: pd.Series,
    sma_slow: pd.Series,
    threshold: float = SMA_BULL_THRESHOLD,
) -> pd.Series:
    """
    Classify each day as bull-trending (True) or not (False).

    Bull condition: SMA_fast > SMA_slow by more than `threshold` (fraction).
    I.e. (SMA50 - SMA200) / SMA200 > threshold.

    Parameters
    ----------
    sma_fast : pd.Series   SMA50 values, aligned to sma_slow.
    sma_slow : pd.Series   SMA200 values.
    threshold : float      Default 0.02 (2%).

    Returns
    -------
    pd.Series of bool, same index as inputs. NaN where sma_slow is NaN.
    """
    gap = (sma_fast - sma_slow) / sma_slow
    return gap > threshold


def apply_crisis_override(
    hmm_states: pd.Series,
    spy_close: pd.Series,
    vol_window: int = 5,
    threshold: float = VOL_OVERRIDE_THRESHOLD,
) -> pd.Series:
    """
    Replicate the engine's vol-override logic: if 5-day realized vol >= threshold,
    effective state becomes 3 (Crisis) regardless of HMM output.

    Parameters
    ----------
    hmm_states : pd.Series of int, indexed by date.
    spy_close  : pd.Series of float, daily closes (indexed by date, full history).
    vol_window : int   default 5 (matches engine).
    threshold  : float default 0.50 (50% annualised vol, matches engine line 685).

    Returns
    -------
    pd.Series of int, same index as hmm_states, with Crisis (3) overrides applied.
    """
    log_ret = np.log(spy_close / spy_close.shift(1))
    rvol    = log_ret.rolling(vol_window).std() * np.sqrt(252)
    # Align rvol to hmm_states dates
    rvol_aligned = rvol.reindex(hmm_states.index)

    effective = hmm_states.copy()
    crisis_mask = rvol_aligned >= threshold
    effective[crisis_mask] = 3
    return effective


def compute_20d_returns(spy_close: pd.Series) -> pd.Series:
    """20-day forward-looking SPY log-return (strictly backward: log(P_t / P_{t-20}))."""
    return np.log(spy_close / spy_close.shift(20))


def compute_sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


# ===========================================================================
# Model loading
# ===========================================================================

def _find_initial_model_pkl(model_dir: Path) -> Path:
    """Return the first (earliest mtime) non-retrain pkl in model_dir."""
    pkls = sorted(model_dir.glob("hmm_*.pkl"), key=lambda p: p.stat().st_mtime)
    if not pkls:
        raise FileNotFoundError(f"No hmm_*.pkl found in {model_dir}")
    # Prefer the first file that is NOT a retrain (no '_retrain' in name)
    initial = [p for p in pkls if "_retrain" not in p.name]
    return initial[0] if initial else pkls[0]


def load_model_from_pkl(pkl_path: Path) -> tuple:
    """
    Load GaussianHMM and metadata from a pkl checkpoint.

    Returns
    -------
    (model, checkpoint_dict)
      model: hmmlearn GaussianHMM
      checkpoint_dict: full dict from pickle
    """
    with open(pkl_path, "rb") as f:
        ck = pickle.load(f)
    return ck["model"], ck


# ===========================================================================
# Day-level state sequence
# ===========================================================================

def build_day_states(spy_close: pd.Series, model) -> pd.Series:
    """
    Run the HMM's Viterbi decoder on the full `spy_close` series.

    Parameters
    ----------
    spy_close : pd.Series   Daily SPY closes (full history for warmup).
    model     : GaussianHMM (hmmlearn) -- already fitted and sorted.

    Returns
    -------
    pd.Series of int, indexed by date, for every day where features are valid.
    """
    log_ret = np.log(spy_close / spy_close.shift(1))
    rvol    = log_ret.rolling(5).std() * np.sqrt(252)

    features_df = pd.DataFrame({
        "log_return":   log_ret,
        "realised_vol": rvol,
    }, index=spy_close.index).dropna()

    X      = features_df.values.astype(np.float64)
    states = model.predict(X)

    return pd.Series(states, index=features_df.index, name="hmm_state")


# ===========================================================================
# Reporting helpers
# ===========================================================================

STATE_NAME = {
    0: "Calm",
    1: "Normal",
    2: "Stress",
    3: "Crisis*",   # * = vol override, not HMM
}


def _bar(n, total, width=20):
    filled = int(round(n / total * width)) if total > 0 else 0
    return "#" * filled + "." * (width - filled)


def _pct(n, total):
    return f"{n/total*100:.1f}%" if total > 0 else "N/A"


def _print_sep(title="", width=72):
    if title:
        pad = max(0, (width - len(title) - 2) // 2)
        print("=" * pad + " " + title + " " + "=" * pad)
    else:
        print("=" * width)


# ===========================================================================
# Main analysis
# ===========================================================================

def analyze(
    spy_daily_path: Path,
    trade_log_path: Path,
    model_pkl_path: Path,
) -> None:

    print()
    _print_sep("HMM STATE DIAGNOSTIC -- IN-SAMPLE 2017-2022")
    print()
    print("CAVEATS:")
    print("  * IN-SAMPLE ONLY (2017-2022). 2023+ data never loaded.")
    print("  * Results use the initial IS model (see model info below).")
    print("    WFO weekly retrains (~46k pkls) are NOT walked -- this diagnostic")
    print("    applies the single initial model over the full IS period to get a")
    print("    clean baseline view of state structure.")
    print()

    # -----------------------------------------------------------------------
    # Load model
    # -----------------------------------------------------------------------
    model, ck = load_model_from_pkl(model_pkl_path)

    n_model = model.n_components
    trained_at = ck.get("trained_at", "unknown")
    ck_n = ck.get("n_components", n_model)

    print("MODEL INFO:")
    print(f"  File        : {model_pkl_path.name}")
    print(f"  Trained at  : {trained_at}")
    print(f"  n_components: {n_model}  (checkpoint stores: {ck_n})")
    print(f"  engine.py N_COMPONENTS constant: {ENGINE_N_COMPONENTS}")
    if n_model != ENGINE_N_COMPONENTS:
        print(f"  *** MISMATCH: model has {n_model} states; engine constant says {ENGINE_N_COMPONENTS} ***")
        print(f"  *** This means N_COMPONENTS=4 was set AFTER this model was trained. ***")
    print()

    print("  Per-state means (from trained model):")
    for i in range(n_model):
        label  = HMM_STATES.get(i, f"State{i}")
        means  = model.means_[i]
        covars = model.covars_[i]
        var_proxy = float(np.sum(covars)) if covars.ndim == 1 else float(np.trace(covars))
        print(f"    State {i} ({label}): log_ret={means[0]:+.5f}  rvol={means[1]:.4f} ({means[1]*100:.1f}%)  var={var_proxy:.6f}")
    print()

    # -----------------------------------------------------------------------
    # Load SPY daily (full history for Viterbi warmup)
    # -----------------------------------------------------------------------
    spy = pd.read_parquet(spy_daily_path)
    spy.index = pd.to_datetime(spy.index)
    spy_to_is  = spy[spy.index <= IS_END]["close"]          # 2007-2022 for Viterbi
    spy_is     = spy_to_is[spy_to_is.index >= IS_START]     # 2017-2022 for analysis

    print(f"SPY data: {len(spy_to_is)} days (2007-{IS_END}) loaded for Viterbi warmup")
    print(f"IS window: {len(spy_is)} days ({IS_START} - {IS_END})")
    print()

    # -----------------------------------------------------------------------
    # Run HMM predict on full history, filter to IS
    # -----------------------------------------------------------------------
    print("Running HMM Viterbi decode on full 2007-2022 history...", end="", flush=True)
    all_states = build_day_states(spy_to_is, model)
    print(" done.")

    hmm_states_is = all_states.loc[IS_START:IS_END]  # raw HMM states (0/1/2)
    n_is_days = len(hmm_states_is)
    print(f"  IS days with valid HMM predictions: {n_is_days}")
    print()

    # Check: which states does predict actually emit?
    unique_emitted = sorted(hmm_states_is.unique())
    print(f"  States emitted by HMM predict: {unique_emitted}")
    if 3 in unique_emitted:
        print("  NOTE: HMM emits state 3 (Crisis) directly -- model has n_components=4")
    else:
        print(f"  NOTE: HMM NEVER emits state 3 (Crisis) -- model has only {n_model} states")
    print()

    # -----------------------------------------------------------------------
    # Apply vol override -> effective states
    # -----------------------------------------------------------------------
    effective_states_is = apply_crisis_override(hmm_states_is, spy_to_is)
    n_override = (effective_states_is == 3).sum()
    n_raw_crisis = (hmm_states_is == 3).sum()
    print(f"  Vol override (rvol >= {VOL_OVERRIDE_THRESHOLD:.0%}): {n_override} days forced to Crisis")
    print(f"  Raw HMM Crisis (state 3) before override: {n_raw_crisis} days")
    print()

    # -----------------------------------------------------------------------
    # Compute supplementary series
    # -----------------------------------------------------------------------
    log_ret_is = np.log(spy_is / spy_is.shift(1))
    rvol_is    = log_ret_is.rolling(5).std() * np.sqrt(252)
    ret_20d    = compute_20d_returns(spy_to_is).loc[IS_START:IS_END]
    sma50      = compute_sma(spy_to_is, SMA_FAST).loc[IS_START:IS_END]
    sma200     = compute_sma(spy_to_is, SMA_SLOW).loc[IS_START:IS_END]
    bull_mask  = is_bull_day(sma50, sma200)

    # Align everything to hmm_states_is index
    idx = hmm_states_is.index
    log_ret_a  = log_ret_is.reindex(idx)
    rvol_a     = rvol_is.reindex(idx)
    ret_20d_a  = ret_20d.reindex(idx)
    bull_a     = bull_mask.reindex(idx)

    # -----------------------------------------------------------------------
    # Load trade log
    # -----------------------------------------------------------------------
    trades = pd.read_csv(trade_log_path, parse_dates=["entry_time"])
    trades = trades[(trades["entry_time"] >= IS_START) & (trades["entry_time"] <= IS_END)]
    n_total_trades = len(trades)

    # -----------------------------------------------------------------------
    # OUTPUT 1: State Distribution
    # -----------------------------------------------------------------------
    _print_sep("OUTPUT 1: STATE DISTRIBUTION BY DAY")
    print()
    print("  Raw HMM (no vol override):")
    raw_counts = count_state_days(hmm_states_is)
    print(f"  {'State':<8} {'Label':<10} {'n_days':>7} {'% of IS':>8}  bar")
    print("  " + "-" * 52)
    for s, n in raw_counts.items():
        label = HMM_STATES.get(s, f"State{s}")
        print(f"  {s:<8} {label:<10} {n:>7,d} {_pct(n, n_is_days):>8}  {_bar(n, n_is_days)}")
    print()
    print("  Effective (with vol override -- matches engine logic):")
    eff_counts = count_state_days(effective_states_is)
    all_eff_states = [0, 1, 2, 3]
    print(f"  {'State':<8} {'Label':<12} {'n_days':>7} {'% of IS':>8}  bar")
    print("  " + "-" * 56)
    for s in all_eff_states:
        n = eff_counts.get(s, 0)
        label = STATE_NAME.get(s, f"State{s}")
        print(f"  {s:<8} {label:<12} {n:>7,d} {_pct(n, n_is_days):>8}  {_bar(n, n_is_days)}")
    print()

    # -----------------------------------------------------------------------
    # OUTPUT 2: Crisis State Analysis
    # -----------------------------------------------------------------------
    _print_sep("OUTPUT 2: CRISIS STATE -- ALIVE OR DEAD?")
    print()
    print(f"  Model n_components       : {n_model}")
    print(f"  Engine N_COMPONENTS const: {ENGINE_N_COMPONENTS}")
    print(f"  States model can predict : 0 to {n_model - 1}  ({', '.join(HMM_STATES[i] for i in range(n_model))})")
    print()
    print(f"  HMM predict emits state 3 (Crisis): {'YES' if n_raw_crisis > 0 else 'NO -- model has only 3 states'}")
    print(f"  Crisis days via vol override:        {n_override} day(s) where 5-day rvol >= {VOL_OVERRIDE_THRESHOLD:.0%}")
    print()
    print("  ENGINE PATH for Crisis:")
    print("    Line 678: _state_idx = _hmm.predict_current(spy_daily)  # emits 0/1/2 only")
    print("    Line 679: self._hmm_state = _hmm.state_name(_state_idx) # 'Calm'/'Normal'/'Stress'")
    print("    Line 685: if _cur_vol >= 0.50: self._hmm_state = 'Crisis'  # vol override")
    print("  => Crisis can ONLY come from vol override, NEVER from model.predict()")
    print()
    if n_override > 0:
        crisis_dates = effective_states_is[effective_states_is == 3].index
        print(f"  Crisis days ({n_override} total):")
        for d in crisis_dates:
            rv = rvol_a.get(d, np.nan)
            print(f"    {d.date()}  rvol={rv:.1%}")
    print()

    # -----------------------------------------------------------------------
    # OUTPUT 3: Per-State Characterization
    # -----------------------------------------------------------------------
    _print_sep("OUTPUT 3: PER-STATE CHARACTERIZATION")
    print()
    # Use effective states for characterization
    print(f"  (Based on {n_is_days:,d} IS days, using effective states incl. vol-override Crisis)")
    print()
    hdr = (f"  {'State':<10} {'n_days':>7} {'mean_ret':>9} {'std_ret':>9} "
           f"{'mean_rvol':>10} {'mean_20d_ret':>13} {'bull_%':>7}")
    print(hdr)
    print("  " + "-" * 72)

    for s in [0, 1, 2, 3]:
        mask  = (effective_states_is == s)
        n     = mask.sum()
        label = STATE_NAME.get(s, f"State{s}")
        if n == 0:
            print(f"  {label:<10} {n:>7,d}  (no days)")
            continue
        mn_ret  = float(log_ret_a[mask].mean())
        std_ret = float(log_ret_a[mask].std())
        mn_vol  = float(rvol_a[mask].mean())
        mn_20d  = float(ret_20d_a[mask].mean())
        bull_pct= float(bull_a[mask].mean()) * 100
        print(f"  {label:<10} {n:>7,d}  {mn_ret:>+9.5f}  {std_ret:>9.5f}  "
              f"{mn_vol:>10.2%}  {mn_20d:>+13.4f}  {bull_pct:>6.1f}%")
    print()
    print("  Columns:")
    print("    mean_ret    = mean daily SPY log-return while in state")
    print("    std_ret     = std of daily log-returns (realized dispersion)")
    print("    mean_rvol   = mean 5-day realized vol (annualised)")
    print("    mean_20d_ret= mean 20-day backward log-return (trend context)")
    print("    bull_%      = % of days where SMA50 > SMA200 by >2%")
    print()

    # -----------------------------------------------------------------------
    # OUTPUT 4: Days vs Trades Reconciliation
    # -----------------------------------------------------------------------
    _print_sep("OUTPUT 4: DAYS vs TRADES RECONCILIATION")
    print()

    trade_counts = {}
    if "hmm_state" in trades.columns:
        tc = trades["hmm_state"].value_counts().to_dict()
        for label, cnt in tc.items():
            # Map string label to int
            for k, v in HMM_STATES.items():
                if v == label:
                    trade_counts[k] = cnt
                    break
            else:
                # Crisis
                if label == "Crisis":
                    trade_counts[3] = cnt
    else:
        print("  WARNING: hmm_state column not found in trade log")

    print(f"  Total IS trades: {n_total_trades:,d}  |  Total IS trading days: {n_is_days:,d}")
    print()
    print(f"  {'State':<10} {'Label':<12} {'eff_days':>9} {'eff_day%':>9} {'n_trades':>9} {'trade%':>8} {'trades/day':>11}")
    print("  " + "-" * 72)

    for s in [0, 1, 2, 3]:
        eff_n    = eff_counts.get(s, 0)
        tr_n     = trade_counts.get(s, 0)
        label    = STATE_NAME.get(s, f"State{s}")
        tpd      = tr_n / eff_n if eff_n > 0 else 0
        print(f"  {s:<10} {label:<12} {eff_n:>9,d} {_pct(eff_n, n_is_days):>9} "
              f"{tr_n:>9,d} {_pct(tr_n, n_total_trades):>8} {tpd:>11.3f}")
    print()

    # Explanation for Calm
    calm_eff = eff_counts.get(0, 0)
    calm_tr  = trade_counts.get(0, 0)
    if calm_eff > 0:
        tr_per_day = calm_tr / calm_eff
        all_tr_per_day = n_total_trades / n_is_days
        print(f"  CALM INSIGHT: {calm_eff} Calm days -> {calm_tr} Calm trades = {tr_per_day:.3f} trades/day")
        print(f"  vs. overall average: {all_tr_per_day:.3f} trades/day")
        if tr_per_day < all_tr_per_day * 0.5:
            print(f"  => RAITS trades MUCH LESS on Calm days (below 50% of average rate)")
        elif tr_per_day < all_tr_per_day:
            print(f"  => RAITS trades somewhat less on Calm days")
        else:
            print(f"  => RAITS trades at a normal rate on Calm days")
        print()
        days_label = "common" if calm_eff > 100 else ("moderate" if calm_eff > 30 else "RARE")
        print(f"  RESOLUTION: Calm is {days_label} by day ({calm_eff} days = {_pct(calm_eff, n_is_days)} of IS).")
        if calm_eff <= 30:
            print(f"  => Cause of 9 Calm trades: RARE DAYS -- HMM barely assigns Calm.")
        elif calm_eff > 100 and calm_tr < 30:
            print(f"  => Cause of 9 Calm trades: RAITS INACTIVE on Calm days (many days, few trades).")
        else:
            print(f"  => Both effects contribute: Calm days are limited AND RAITS trades infrequently on them.")
    print()

    # -----------------------------------------------------------------------
    # OUTPUT 5: Bull Days per State
    # -----------------------------------------------------------------------
    _print_sep("OUTPUT 5: BULL-TRENDING DAYS PER STATE")
    print()
    print(f"  Bull criterion: SMA{SMA_FAST} > SMA{SMA_SLOW} by >{SMA_BULL_THRESHOLD:.0%}")
    print()

    total_bull = int(bull_a.sum())
    n_nan_bull = int(bull_a.isna().sum())
    print(f"  Total IS days with valid SMA200: {n_is_days - n_nan_bull:,d}")
    print(f"  Bull-trending days (SMA50>SMA200 >2%): {total_bull:,d}  ({_pct(total_bull, n_is_days - n_nan_bull)} of valid days)")
    print()

    print(f"  {'State':<10} {'Label':<12} {'state_days':>10} {'bull_in_state':>14} {'%_bull':>8} {'%_of_all_bull':>14}")
    print("  " + "-" * 72)
    for s in [0, 1, 2, 3]:
        mask_state = (effective_states_is == s)
        n_state    = mask_state.sum()
        n_bull_in  = int(bull_a[mask_state].sum())
        pct_bull   = _pct(n_bull_in, n_state) if n_state > 0 else "N/A"
        pct_of_all = _pct(n_bull_in, total_bull) if total_bull > 0 else "N/A"
        label = STATE_NAME.get(s, f"State{s}")
        print(f"  {s:<10} {label:<12} {n_state:>10,d} {n_bull_in:>14,d} {pct_bull:>8} {pct_of_all:>14}")
    print()

    # The key question: do bull periods have their own state?
    print("  BULL PERIOD QUESTION: Do bull-trending days cluster in a specific state?")
    dominant_bull_state = None
    dominant_bull_pct   = 0.0
    for s in [0, 1, 2, 3]:
        mask_state = (effective_states_is == s)
        n_bull_in  = int(bull_a[mask_state].sum())
        pct_of_all = n_bull_in / total_bull * 100 if total_bull > 0 else 0
        if pct_of_all > dominant_bull_pct:
            dominant_bull_pct   = pct_of_all
            dominant_bull_state = s

    if dominant_bull_pct > 60:
        label = STATE_NAME.get(dominant_bull_state, f"State{dominant_bull_state}")
        print(f"  => {dominant_bull_pct:.1f}% of bull days land in {label} -- bull has a dominant state.")
    else:
        print("  => Bull days spread across multiple states -- no single 'bull state'.")
    print()

    # -----------------------------------------------------------------------
    # OUTPUT 6: Verdicts
    # -----------------------------------------------------------------------
    _print_sep("OUTPUT 6: VERDICTS")
    print()

    # Verdict 1: Is the HMM using 4 states?
    print("  [1] IS THE HMM USING 4 STATES (Calm/Normal/Stress/Crisis)?")
    if n_model == 3:
        print(f"  NO. The loaded model has n_components={n_model} (3 states: Calm/Normal/Stress).")
        print(f"  The engine.py constant N_COMPONENTS={ENGINE_N_COMPONENTS} was set to 4 but the actual")
        print(f"  IS models were trained with 3 states. Crisis (state 3) cannot come from")
        print(f"  model.predict() -- it is ONLY emitted via the vol override at rvol>=50%.")
    elif n_model == 4:
        print(f"  YES. Model has n_components=4. Check state usage above.")
    print()

    # Verdict 2: Is Calm rare by day or just rarely traded?
    calm_eff_n = eff_counts.get(0, 0)
    calm_tr_n  = trade_counts.get(0, 0)
    print("  [2] IS CALM RARE BY DAY OR JUST RARELY TRADED?")
    if calm_eff_n < 30:
        print(f"  CALM IS RARE BY DAY: only {calm_eff_n} IS days assigned Calm ({_pct(calm_eff_n, n_is_days)}).")
        print(f"  The 9 Calm trades are explained by: HMM almost never fires Calm.")
    elif calm_tr_n < 0.1 * (calm_eff_n * n_total_trades / n_is_days):
        print(f"  CALM IS RARELY TRADED: {calm_eff_n} Calm days but only {calm_tr_n} trades.")
        print(f"  RAITS is inactive on Calm days (likely Calm strategies are excluded or gated).")
    else:
        print(f"  BOTH: {calm_eff_n} Calm days ({_pct(calm_eff_n, n_is_days)}), {calm_tr_n} trades.")
    print()

    # Verdict 3: Do bull periods get their own state?
    print("  [3] DO BULL-TRENDING PERIODS GET THEIR OWN HMM STATE?")
    for s in [0, 1, 2, 3]:
        mask_state = (effective_states_is == s)
        n_bull_in  = int(bull_a[mask_state].sum())
        pct_of_all = n_bull_in / total_bull * 100 if total_bull > 0 else 0
        if pct_of_all > 0:
            label = STATE_NAME.get(s, f"State{s}")
            pct_of_state = n_bull_in / mask_state.sum() * 100 if mask_state.sum() > 0 else 0
            print(f"    {label}: {n_bull_in} bull days ({pct_of_all:.1f}% of all bull days, "
                  f"{pct_of_state:.1f}% of {label} days are bull)")
    print()
    if dominant_bull_pct > 60:
        print(f"  => Bull days cluster in one state ({_pct(int(dominant_bull_pct * total_bull / 100), total_bull)} there).")
        print(f"     The HMM does capture some bull structure.")
    else:
        print("  => Bull days are scattered across states -- the HMM does NOT distinguish")
        print("     bull-trending from other states by SMA criterion.")
        print("     This supports the trend-blindness hypothesis from the previous diagnostic.")
    print()


# ===========================================================================
# Entry point
# ===========================================================================

def _parse_args():
    p = argparse.ArgumentParser(
        description="RAITS HMM State Diagnostic (IS 2017-2022, read-only)"
    )
    p.add_argument("--spy-daily", type=Path, default=DEFAULT_SPY_DAILY,
                   help=f"SPY daily parquet (default: SPY_daily_2007_2024.parquet)")
    p.add_argument("--trade-log", type=Path, default=DEFAULT_TRADE_LOG,
                   help=f"IS trade log CSV (default: wfo_trade_log.csv)")
    p.add_argument("--model-pkl", type=Path, default=None,
                   help="Path to specific pkl to use. If omitted, uses first non-retrain pkl in model_dir.")
    p.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR,
                   help=f"Model directory (default: raits/models/hmm/)")
    return p.parse_args()


def main():
    args = _parse_args()

    for p, name in [(args.spy_daily, "--spy-daily"), (args.trade_log, "--trade-log")]:
        if not p.exists():
            print(f"ERROR: {name} not found: {p}", file=sys.stderr)
            sys.exit(1)

    if args.model_pkl:
        model_pkl = args.model_pkl
        if not model_pkl.exists():
            print(f"ERROR: --model-pkl not found: {model_pkl}", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.model_dir.exists():
            print(f"ERROR: --model-dir not found: {args.model_dir}", file=sys.stderr)
            sys.exit(1)
        model_pkl = _find_initial_model_pkl(args.model_dir)
        print(f"Auto-selected model: {model_pkl.name}")

    analyze(args.spy_daily, args.trade_log, model_pkl)


if __name__ == "__main__":
    main()
