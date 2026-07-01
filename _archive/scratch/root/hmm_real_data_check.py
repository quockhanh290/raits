"""
Step 3: Real SPY data validation
Downloads 7 years of SPY and checks regime detection against known market events.
Run: python hmm_real_data_check.py
"""

import sys
import pandas as pd
import numpy as np

print("=" * 60)
print("STEP 3: HMM Real Data Validation")
print("=" * 60)

# ── Download SPY ──────────────────────────────────────────────────────────────
print("\n[1/4] Downloading SPY daily closes (2018–2025)...")

try:
    import yfinance as yf
except ImportError:
    print("  ERROR: yfinance not installed.")
    print("  Run:   pip install yfinance")
    sys.exit(1)

spy_raw = yf.download('SPY', start='2018-01-01', end='2025-01-01',
                      auto_adjust=True, progress=False)

if spy_raw.empty:
    print("  ERROR: No data returned. Check your internet connection.")
    sys.exit(1)

spy_close = spy_raw['Close'].dropna().squeeze()
print(f"  Downloaded {len(spy_close)} trading days")
print(f"  Date range: {spy_close.index[0].date()} → {spy_close.index[-1].date()}")

# ── Fit HMM ──────────────────────────────────────────────────────────────────
print("\n[2/4] Fitting HMM (n_init=10, ~30–60 seconds)...")

from raits.hmm import HMMEngine, HMM_STATES, CALM, NORMAL, STRESS

engine = HMMEngine(n_iter=200, n_init=10)
engine.fit(spy_close, version_tag='spy_real_v1', save=True)
print("  HMM fitted and saved to models/hmm/")

# ── Predict full sequence ─────────────────────────────────────────────────────
print("\n[3/4] Predicting regime sequence...")

states = engine.predict_sequence(spy_close)
state_series = pd.Series(
    states,
    index=spy_close.index[len(spy_close) - len(states):],
    name="regime"
)

print("\n  Regime distribution (7 years):")
for idx, label in HMM_STATES.items():
    pct = (state_series == idx).mean()
    bar = "█" * int(pct * 40)
    print(f"    {label:8s}: {pct:5.1%}  {bar}")

# Expected healthy ranges:
#   Calm   28–38%
#   Normal 40–50%
#   Stress 15–25%

calm_pct   = (state_series == CALM).mean()
normal_pct = (state_series == NORMAL).mean()
stress_pct = (state_series == STRESS).mean()

dist_ok = (
    0.20 <= calm_pct   <= 0.45 and
    0.30 <= normal_pct <= 0.60 and
    0.10 <= stress_pct <= 0.35
)
print(f"\n  Distribution looks {'REASONABLE' if dist_ok else 'UNUSUAL — may need tuning'}")

# ── Spot-check known market events ────────────────────────────────────────────
print("\n[4/4] Spot-checking known market events...")
print()

checks = {
    "COVID crash  (Feb–Mar 2020)": {
        "range":    ("2020-02-24", "2020-03-23"),
        "expect":   "Stress dominant",
        "stress_min": 0.60,
        "calm_max":   0.10,
    },
    "Volmageddon (Feb 5–9 2018)": {
        "range":    ("2018-02-05", "2018-02-09"),
        "expect":   "Stress dominant",
        "stress_min": 0.50,
        "calm_max":   0.10,
    },
    "2019 calm bull run": {
        "range":    ("2019-01-01", "2019-12-31"),
        "expect":   "Calm/Normal dominant",
        "stress_min": 0.00,
        "calm_max":   1.00,   # no upper bound check for calm here
        "stress_max": 0.20,
    },
    "2021 post-COVID bull": {
        "range":    ("2021-01-01", "2021-12-31"),
        "expect":   "Calm/Normal dominant",
        "stress_max": 0.20,
    },
    "2022 bear market": {
        "range":    ("2022-01-01", "2022-12-31"),
        "expect":   "Stress elevated",
        "stress_min": 0.25,
    },
}

all_pass = True
for name, spec in checks.items():
    start, end = spec["range"]
    period = state_series[start:end]

    if len(period) == 0:
        print(f"  {name}")
        print(f"    SKIP — no data in range")
        print()
        continue

    s_pct = (period == STRESS).mean()
    n_pct = (period == NORMAL).mean()
    c_pct = (period == CALM).mean()

    # Evaluate pass/fail
    passed = True
    if "stress_min" in spec and s_pct < spec["stress_min"]:
        passed = False
    if "calm_max"   in spec and c_pct > spec["calm_max"] and "stress_min" in spec:
        passed = False
    if "stress_max" in spec and s_pct > spec["stress_max"]:
        passed = False

    status = "PASS" if passed else "FAIL"
    if not passed:
        all_pass = False

    dominant_label = HMM_STATES[int(period.mode()[0])]

    print(f"  {name}")
    print(f"    Expected : {spec['expect']}")
    print(f"    Actual   : Calm={c_pct:.0%}  Normal={n_pct:.0%}  Stress={s_pct:.0%}"
          f"  (dominant: {dominant_label})")
    print(f"    Result   : {status}")
    print()

# ── State sorting sanity ──────────────────────────────────────────────────────
from raits.hmm.state_sorting import validate_state_order
ordered = validate_state_order(engine.model)

print("─" * 60)
print("SUMMARY")
print("─" * 60)
print(f"  Distribution reasonable : {'YES' if dist_ok else 'NO'}")
print(f"  State variance ordered  : {'YES' if ordered else 'NO — BUG'}")
print(f"  Spot-checks             : {'ALL PASS' if all_pass else 'SOME FAILED — see above'}")
print()

if dist_ok and ordered and all_pass:
    print("  OVERALL: HMM READY — proceed to Weeks 6-8 (Transaction Cost Model)")
else:
    print("  OVERALL: ISSUES FOUND — review failures above, then come back")

print("=" * 60)
