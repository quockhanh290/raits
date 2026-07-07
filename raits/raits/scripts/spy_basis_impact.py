"""
spy_basis_impact.py
===================
INVESTIGATION ONLY — no code changes, no model saves.

QUESTION: Does the 8.17% label difference between split-only (production)
and div-adjusted (alternative) HMM bases actually flip any strategy decision,
or is it downstream-harmless?

METHOD:
  1. Load existing WFO snapshot (trades already executed under rolling split-only HMM)
  2. Fit a static HMM-B (div-adjusted) over the full IS period
  3. For each trade date: compare split-only regime (actual, from trade.hmm_state)
     to what div-adjusted HMM would have assigned
  4. On "flipped" days: check if trade's strategy is allowed under the alternative regime
  5. Bootstrap p-values on (all trades) vs (trades surviving under div-adj regime)
     to detect verdict flips

CAVEATS (stated honestly):
  - Production engine uses ROLLING weekly retrains; this script uses a STATIC
    HMM-B fit over all IS data. The flip dates may differ slightly.
  - "Blocked under div-adj" = upper-bound estimate; actual engine may route
    differently depending on surrounding context.
  - STEP 3 (full re-run with div-adj labels) would require hours; this script
    provides a trade-removal approximation instead.

STEP 1 — BASIS FRAMING:
  split-only: actual traded prices (what strategies execute on); ex-div drops
    appear as real intraday volatility → HMM correctly identifies elevated risk
  div-adjusted: total return basis; ex-div drops smoothed out → cleaner trend
    signal but detached from prices strategies actually trade
  For an intraday regime gate, strategies trade split-adjusted prices.
  Ex-div drops in 5-min data look like real volatility to ORB/TREND strategies.
  Split-only is arguably correct: HMM sees what strategies see.
  Div-adjusted would suppress that signal, potentially keeping regime "Normal"
  on days that look stressful to intraday positions.
  NEITHER is obviously "the bug" — the question is which matters more for
  downstream decisions, which is what this script measures.

Run from d:\\raits\\raits:
    python raits/scripts/spy_basis_impact.py *> basis_impact_output.txt
"""
from __future__ import annotations
import glob
import os
import pickle
import sys
import warnings
warnings.filterwarnings("ignore")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd

from raits.hmm.engine import HMMEngine
from raits.hmm.state_sorting import HMM_STATES, validate_state_order

# ── Paths ──────────────────────────────────────────────────────────────────────
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CACHE_BASE   = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", "data", "cache"))
CACHE_5MIN   = os.path.join(CACHE_BASE, "data")
CACHE_DAILY  = os.path.join(CACHE_BASE, "daily")
SNAPSHOT_DIR = os.path.join(CACHE_BASE, "snapshots")

INTERVAL     = 5
N_BOOT       = 10_000
SEED         = 42

# Production regime-to-strategy gate (from backtest/engine.py)
_REGIME_STRATEGIES = {
    "Calm":   ["PE_SHORT"],
    "Normal": ["ORB", "TREND_FOLLOW", "GF_SHORT", "PE_SHORT"],
    "Stress": ["TREND_FOLLOW", "STRESS_ORB", "STRESS_MID", "PE_SHORT"],
    "Crisis": ["PE_SHORT"],
}


# ── Data loaders ───────────────────────────────────────────────────────────────

def load_5min_derived_daily(ticker: str = "SPY") -> pd.Series:
    pattern = os.path.join(CACHE_5MIN, f"{ticker}_{INTERVAL}min_*.parquet")
    files   = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No 5-min parquets for {ticker} in {CACHE_5MIN}")
    df = pd.concat([pd.read_parquet(f) for f in files])
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index().pipe(lambda x: x[~x.index.duplicated(keep="first")])
    df = df.between_time("09:30", "16:00")
    return df["close"].resample("B").last().dropna()


def load_daily_parquet(ticker: str = "SPY") -> pd.Series:
    pattern = os.path.join(CACHE_DAILY, f"{ticker}_daily_*.parquet")
    files   = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No daily parquets for {ticker} in {CACHE_DAILY}")
    df = pd.concat([pd.read_parquet(f) for f in files])
    df.index = pd.DatetimeIndex(df.index)
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index().pipe(lambda x: x[~x.index.duplicated(keep="first")])
    return df["close"]


def load_latest_snapshot() -> tuple[str, list]:
    pkls = sorted(glob.glob(os.path.join(SNAPSHOT_DIR, "results_*.pkl")))
    if not pkls:
        raise FileNotFoundError(f"No snapshot pkls in {SNAPSHOT_DIR}")
    path = pkls[-1]
    with open(path, "rb") as f:
        windows = pickle.load(f)
    return path, windows


# ── HMM helpers ────────────────────────────────────────────────────────────────

def fit_sorted_engine(spy_close: pd.Series) -> HMMEngine:
    engine = HMMEngine()
    engine.fit(spy_close, save=False)
    return engine


def get_regime_series(engine: HMMEngine, spy_close: pd.Series) -> pd.Series:
    """Return named regime label for every date in spy_close."""
    raw = engine.predict_sequence(spy_close)
    idx = spy_close.index[-len(raw):]
    return pd.Series([HMM_STATES[s] for s in raw], index=idx)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def bootstrap_pvalue(pnls: list[float], n_boot: int, rng: np.random.Generator) -> float:
    arr = np.array(pnls, dtype=float)
    if len(arr) == 0 or arr.mean() == 0:
        return 1.0
    boot_means = rng.choice(arr, size=(n_boot, len(arr)), replace=True).mean(axis=1)
    return float((boot_means <= 0).mean())


def verdict(p: float) -> str:
    if p < 0.05:   return "CONFIRMED"
    if p < 0.15:   return "BORDERLINE"
    return "NO EDGE"


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    SEP = "=" * 65

    # ── STEP 1: Basis framing ─────────────────────────────────────────────────
    print(SEP)
    print("STEP 1 -- BASIS FRAMING (not a bug, a design choice)")
    print(SEP)
    print("""
  split-only:
    - Actual traded prices; ex-div drops appear as real volatility
    - HMM sees the same signal strategies execute on
    - Correct for an intraday gate: if SPY gaps -1% on ex-div,
      that IS elevated risk for intraday ORB trades that morning
    - Already used for both initial fit and weekly retrain (this env)

  div-adjusted:
    - Total return series; ex-div drops smoothed away
    - Better for multi-year trend analysis; may suppress mechanical noise
    - Detached from actual intraday prices; strategies don't trade the
      div-adjusted series

  For an INTRADAY regime gate, split-only is arguably more correct:
  what matters is how the market LOOKS to traders that day, not the
  total-return accounting. But neither basis is provably wrong --
  the test is downstream impact, which STEP 2 measures.
""")

    # ── Load data ─────────────────────────────────────────────────────────────
    print(SEP)
    print("Loading data...")
    print(SEP)

    print("  Loading 5-min derived daily (split-only)...")
    close_5min = load_5min_derived_daily()
    print(f"    {len(close_5min)} days  "
          f"{close_5min.index[0].date()} to {close_5min.index[-1].date()}")

    print("  Loading daily parquet (div-adjusted)...")
    close_daily = load_daily_parquet()
    print(f"    {len(close_daily)} days  "
          f"{close_daily.index[0].date()} to {close_daily.index[-1].date()}")

    common = close_5min.index.intersection(close_daily.index)
    a = close_5min.loc[common]
    b = close_daily.loc[common]

    print(f"\n  Common period: {len(common)} days")

    print("\n  Loading latest snapshot...")
    snap_path, windows = load_latest_snapshot()
    print(f"    {snap_path}")
    all_trades = [t for w in windows for t in w["trades"]]
    print(f"    {len(all_trades)} total trades across {len(windows)} WFO windows")

    # ── Fit both HMMs ─────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("Fitting HMM-A (split-only) and HMM-B (div-adjusted)...")
    print(SEP)

    print("  HMM-A (split-only)...")
    eng_a = fit_sorted_engine(a)
    ok_a  = validate_state_order(eng_a.model)
    labels_a = get_regime_series(eng_a, a)
    print(f"    validate_state_order: {ok_a}")

    print("  HMM-B (div-adjusted)...")
    eng_b = fit_sorted_engine(b)
    ok_b  = validate_state_order(eng_b.model)
    labels_b = get_regime_series(eng_b, b)
    print(f"    validate_state_order: {ok_b}")

    # Compute overall label diff for reference
    ci = labels_a.index.intersection(labels_b.index)
    la = labels_a.loc[ci]
    lb = labels_b.loc[ci]
    n_diff  = (la != lb).sum()
    pct     = n_diff / len(la) * 100
    print(f"\n  Label diffs (sorted): {n_diff}/{len(la)} = {pct:.2f}%")

    # ── STEP 2: Trade-level impact ────────────────────────────────────────────
    print(f"\n{SEP}")
    print("STEP 2 -- TRADE-LEVEL IMPACT")
    print(SEP)
    print("""
  Caveat: production uses ROLLING weekly retrains; HMM-A and HMM-B here
  are fitted STATICALLY over all IS data. Flip dates may differ slightly.
  This is a proxy / upper-bound, not an exact re-run.
""")

    # Build date -> regime dict for both bases
    regime_a = {d.date(): r for d, r in labels_a.items()}
    regime_b = {d.date(): r for d, r in labels_b.items()}

    results = []  # (trade, actual_regime, alt_regime, still_allowed)
    unmatched = 0

    for t in all_trades:
        if t.entry_time is None:
            continue
        d = t.entry_time.date()
        act = t.hmm_state          # regime from rolling engine (split-only basis)
        alt = regime_b.get(d)      # what div-adj static HMM says for that date

        if alt is None:
            unmatched += 1
            continue

        # Would the trade still be allowed under alt regime?
        still_allowed = t.strategy in _REGIME_STRATEGIES.get(alt, [])
        results.append({
            "trade":         t,
            "date":          d,
            "strategy":      t.strategy,
            "actual_regime": act,
            "alt_regime":    alt,
            "flipped":       act != alt,
            "still_allowed": still_allowed,
            "net_pnl":       float(t.net_pnl) if t.net_pnl is not None else 0.0,
        })

    df = pd.DataFrame(results)
    print(f"  Trades analyzed: {len(df)} / {len(all_trades)} "
          f"({unmatched} unmatched dates)")

    flipped = df[df["flipped"]]
    blocked = df[df["flipped"] & ~df["still_allowed"]]
    survived = df[~df["flipped"] | df["still_allowed"]]

    print(f"\n  Regime label flips (A vs B on trade entry dates): "
          f"{len(flipped)} / {len(df)} = {len(flipped)/len(df)*100:.1f}%")
    print(f"  Of those: blocked under div-adj regime: {len(blocked)}")
    print(f"  Trades surviving under div-adj basis:   {len(survived)}")

    # Flip breakdown by strategy
    print(f"\n  Flip breakdown by strategy:")
    print(f"  {'Strategy':<14} {'Total':>6} {'Flipped':>8} {'Blocked':>8} {'PnL blocked':>12}")
    print(f"  {'-'*54}")
    for strat in sorted(df["strategy"].unique()):
        st_all      = df[df["strategy"] == strat]
        st_flipped  = flipped[flipped["strategy"] == strat]
        st_blocked  = blocked[blocked["strategy"] == strat]
        pnl_blocked = st_blocked["net_pnl"].sum()
        print(f"  {strat:<14} {len(st_all):>6} {len(st_flipped):>8} "
              f"{len(st_blocked):>8} {pnl_blocked:>+12.2f}")

    # Regime flip patterns
    print(f"\n  Regime flip patterns (A=actual, B=alt) on trade dates:")
    flip_counts = (flipped.groupby(["actual_regime", "alt_regime"])
                   .size()
                   .reset_index(name="count"))
    for _, row in flip_counts.iterrows():
        danger = " *** DANGEROUS" if {row["actual_regime"], row["alt_regime"]} == {"Calm", "Stress"} else ""
        print(f"    {row['actual_regime']} -> {row['alt_regime']}: {row['count']} trades{danger}")

    calm_stress = blocked[
        (blocked["actual_regime"].isin(["Calm", "Stress"])) &
        (blocked["alt_regime"].isin(["Calm", "Stress"])) &
        (blocked["actual_regime"] != blocked["alt_regime"])
    ]
    print(f"\n  Calm<->Stress direct flips on trade entry dates: {len(calm_stress)}")

    # P&L of blocked trades
    total_pnl      = df["net_pnl"].sum()
    blocked_pnl    = blocked["net_pnl"].sum()
    pct_blocked_pnl = blocked_pnl / total_pnl * 100 if total_pnl != 0 else 0.0
    print(f"\n  Total P&L (all trades):         ${total_pnl:>+,.2f}")
    print(f"  P&L of blocked trades:          ${blocked_pnl:>+,.2f}  ({pct_blocked_pnl:+.1f}% of total)")
    print(f"  P&L without blocked trades:     ${total_pnl - blocked_pnl:>+,.2f}")

    # ── STEP 2b: Bootstrap p-values under each basis ──────────────────────────
    print(f"\n{SEP}")
    print("STEP 2b -- BOOTSTRAP P-VALUES: split-only vs div-adjusted basis")
    print(SEP)
    print(f"  N_BOOT={N_BOOT}  seed={SEED}")
    print("""
  "div-adj basis" p-values = bootstrap on trades that would survive
  under div-adjusted regime gate (blocked trades removed).
  This approximates what the bootstrap would show if the engine had
  run on div-adj labels.
""")

    # Group by strategy
    rng = np.random.default_rng(SEED)

    all_by_strat = {}
    surv_by_strat = {}
    for _, row in df.iterrows():
        s = row["strategy"]
        all_by_strat.setdefault(s, []).append(row["net_pnl"])
        if row["still_allowed"] or not row["flipped"]:
            surv_by_strat.setdefault(s, []).append(row["net_pnl"])

    header = (f"  {'Strategy':<14} {'N(A)':>5} {'p(A)':>8} {'V(A)':<12} "
              f"{'N(B)':>5} {'p(B)':>8} {'V(B)':<12} {'FLIP?'}")
    print(header)
    print(f"  {'-'*85}")

    any_verdict_flip = False
    for strat in sorted(set(list(all_by_strat.keys()) + list(surv_by_strat.keys()))):
        pnls_a = all_by_strat.get(strat, [])
        pnls_b = surv_by_strat.get(strat, pnls_a)

        p_a = bootstrap_pvalue(pnls_a, N_BOOT, rng)
        p_b = bootstrap_pvalue(pnls_b, N_BOOT, rng)
        v_a = verdict(p_a)
        v_b = verdict(p_b)

        flip = "*FLIP*" if v_a != v_b else "ok"
        if v_a != v_b:
            any_verdict_flip = True
        print(f"  {strat:<14} {len(pnls_a):>5} {p_a:>8.3f} {v_a:<12} "
              f"{len(pnls_b):>5} {p_b:>8.3f} {v_b:<12} {flip}")

    # ── STEP 3: Baseline materiality ──────────────────────────────────────────
    print(f"\n{SEP}")
    print("STEP 3 -- BASELINE MATERIALITY (approximation)")
    print(SEP)
    print("""
  Full re-run with div-adj HMM would take 2-3h. Approximated here
  by removing blocked trades and recomputing summary metrics.
""")

    n_orig    = len(df)
    n_surv    = len(survived)
    pnl_orig  = total_pnl
    pnl_surv  = survived["net_pnl"].sum()
    pct_trade = (n_orig - n_surv) / n_orig * 100
    pct_pnl   = (pnl_orig - pnl_surv) / abs(pnl_orig) * 100 if pnl_orig != 0 else 0.0

    print(f"\n  Trade count:   {n_orig} (split-only)  ->  {n_surv} (div-adj)  "
          f"[{n_orig - n_surv:+d}, {pct_trade:.1f}% reduction]")
    print(f"  Approx P&L:   ${pnl_orig:>+,.2f}  ->  ${pnl_surv:>+,.2f}  "
          f"[{pct_pnl:+.1f}% impact]")

    if n_orig > 0 and survived["net_pnl"].count() > 0:
        wr_orig = (df["net_pnl"] > 0).mean()
        wr_surv = (survived["net_pnl"] > 0).mean()
        print(f"  Win rate:      {wr_orig:.1%}  ->  {wr_surv:.1%}")

    # ── STEP 4: Verdict ───────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("STEP 4 -- VERDICT")
    print(SEP)

    print(f"\n  Label diff (static HMM, full IS):    {pct:.2f}%")
    print(f"  Trades on flipped-regime days:       {len(flipped)} ({len(flipped)/len(df)*100:.1f}%)")
    print(f"  Trades blocked under div-adj:        {len(blocked)} ({len(blocked)/len(df)*100:.1f}%)")
    print(f"  P&L impact of blocked trades:        ${blocked_pnl:>+,.2f}  ({pct_blocked_pnl:+.1f}%)")
    print(f"  Calm<->Stress flips on trade dates:  {len(calm_stress)}")
    print(f"  Strategy verdict flips:              {'YES — see table above' if any_verdict_flip else 'NONE'}")
    print()

    if not any_verdict_flip and abs(pct_pnl) < 5.0 and len(calm_stress) == 0:
        print("  VERDICT: BENIGN")
        print("    No strategy verdicts flip. Baseline P&L changes <5%.")
        print("    No Calm<->Stress flips on trade entry dates.")
        print("    8.17% label diff is downstream-harmless.")
        print("    split-only basis is correct for this intraday gate.")
        print("    Proceed with split-only; no data-basis fix required.")
    elif any_verdict_flip:
        print("  VERDICT: CONTAMINATION DETECTED")
        print("    One or more strategy verdicts flip across the 0.05 threshold.")
        print("    The basis choice materially changes which strategies are trusted.")
        print("    Action: decide which basis is correct (STEP 1), then re-validate.")
    elif abs(pct_pnl) >= 5.0:
        print("  VERDICT: MATERIAL BASELINE IMPACT")
        print(f"    P&L shifts {pct_pnl:+.1f}% -- material but no verdict flips.")
        print("    split-only and div-adjusted give different strategy mixes.")
        print("    Review which basis better reflects live execution conditions.")
    else:
        print("  VERDICT: MODERATE / MONITOR")
        print("    Some trade-level impact but no clean verdict flips.")
        print(f"    P&L impact {pct_pnl:+.1f}%, no dangerous regime flips.")
        print("    Proceed with split-only; revisit if Calm<->Stress flips emerge.")


if __name__ == "__main__":
    main()