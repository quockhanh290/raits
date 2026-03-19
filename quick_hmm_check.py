"""
Step 2: Pipeline integration check
Confirms HMM engine and your Phase 1A mock data pipeline talk to each other.
Run: python quick_hmm_check.py
"""

import sys
import numpy as np
import pandas as pd

# ── Synthetic SPY daily closes (no API needed) ───────────────────────────────
# Simulates 400 trading days with three embedded regimes:
#   Days   0-199: Calm (low vol, slight upward drift)
#   Days 200-249: Stress (high vol, negative drift — crash-like)
#   Days 250-399: Normal (medium vol, recovery)

print("=" * 60)
print("STEP 2: HMM Pipeline Integration Check")
print("=" * 60)

rng = np.random.default_rng(42)

calm_rets   = rng.normal(0.0005, 0.005, 200)   # 0.5% daily vol
stress_rets = rng.normal(-0.001, 0.022, 50)    # 2.2% daily vol (crash)
normal_rets = rng.normal(0.0003, 0.010, 150)   # 1.0% daily vol

all_rets = np.concatenate([calm_rets, stress_rets, normal_rets])
prices   = 400.0 * np.exp(np.cumsum(all_rets))
dates    = pd.date_range("2022-01-03", periods=400, freq="B")
spy_daily = pd.Series(prices, index=dates, name="SPY_close")

print(f"\n  Synthetic SPY: {len(spy_daily)} trading days")
print(f"  Price range:   ${spy_daily.min():.2f} – ${spy_daily.max():.2f}")

# ── Fit HMM ──────────────────────────────────────────────────────────────────
print("\n  Fitting HMM (n_init=5, may take 10–20 seconds)...")

from raits.hmm import HMMEngine, HMM_STATES, CALM, NORMAL, STRESS

engine = HMMEngine(n_iter=200, n_init=5)
engine.fit(spy_daily, save=False)
print("  HMM fitted successfully")

# ── Predict sequence ──────────────────────────────────────────────────────────
states = engine.predict_sequence(spy_daily)
from raits.hmm.features import build_feature_matrix
X = build_feature_matrix(spy_daily)
state_series = pd.Series(states, index=spy_daily.index[len(spy_daily)-len(states):])

print("\n  Regime distribution (full series):")
for idx, label in HMM_STATES.items():
    pct = (state_series == idx).mean()
    bar = "█" * int(pct * 30)
    print(f"    {label:8s} (State {idx}): {pct:5.1%}  {bar}")

# ── Spot-check known injected regimes ────────────────────────────────────────
print("\n  Spot-checks against injected regimes:")

calm_period   = state_series["2022-01-03":"2022-10-14"]   # first ~200 days
stress_period = state_series["2022-10-17":"2022-12-16"]   # next ~50 days
normal_period = state_series["2022-12-19":"2023-12-29"]   # last ~150 days

def dominant(s):
    if len(s) == 0:
        return "no data"
    counts = {HMM_STATES[i]: (s==i).sum() for i in range(3)}
    return max(counts, key=counts.get)

print(f"    Injected CALM   period dominant state: {dominant(calm_period)}"
      f"  (Stress={( calm_period==STRESS).mean():.0%})")
print(f"    Injected STRESS period dominant state: {dominant(stress_period)}"
      f"  (Stress={(stress_period==STRESS).mean():.0%})")
print(f"    Injected NORMAL period dominant state: {dominant(normal_period)}"
      f"  (Calm  ={(normal_period==CALM  ).mean():.0%})")

# ── Current regime ────────────────────────────────────────────────────────────
current_state = engine.predict_current(spy_daily)
probs = engine.predict_proba(spy_daily)
print(f"\n  Current regime (last bar): {engine.state_name(current_state)}")
print(f"  Posteriors: Calm={probs[0]:.1%}  Normal={probs[1]:.1%}  Stress={probs[2]:.1%}")

# ── State sorting sanity check ────────────────────────────────────────────────
from raits.hmm.state_sorting import validate_state_order
ordered = validate_state_order(engine.model)
print(f"\n  State variance ordered (Calm < Normal < Stress): {'YES' if ordered else 'NO — BUG'}")

print("\n  Result:", "PASS" if ordered else "FAIL — state sorting issue")
print("=" * 60)
