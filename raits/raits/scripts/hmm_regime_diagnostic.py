"""
scripts/hmm_regime_diagnostic.py
---------------------------------
Compare HMM-predicted regimes vs current hardcoded vol thresholds.

Trains a 3-state HMM on SPY daily from yfinance (IS: 2007-2016),
then compares its OOS predictions (2017-2024) against the hardcoded
vol threshold currently used in backtest/engine.py.

Usage:
    cd d:\raits\raits
    pip install yfinance   # if not already installed
    python raits/scripts/hmm_regime_diagnostic.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

# ── 1. Fetch SPY daily from yfinance ──────────────────────────────────────────
print("Fetching SPY daily from yfinance (2007-2024)...")
try:
    import yfinance as yf
    spy_raw = yf.download("SPY", start="2007-01-01", end="2024-12-31",
                          auto_adjust=True, progress=False)
    # yfinance may return MultiIndex columns — squeeze to plain Series
    close = spy_raw["Close"]
    spy_daily = close.squeeze().dropna() if hasattr(close, "squeeze") else close.dropna()
    spy_daily = spy_daily.astype(float)
    spy_daily.index = pd.DatetimeIndex(spy_daily.index).tz_localize(None)
    print(f"  OK: {len(spy_daily)} days  "
          f"({spy_daily.index[0].date()} → {spy_daily.index[-1].date()})")
except ImportError:
    print("  yfinance not installed. Run: pip install yfinance")
    sys.exit(1)
except Exception as e:
    print(f"  fetch failed: {e}")
    sys.exit(1)

# ── 2. Vol threshold (exact logic from backtest/engine.py) ─────────────────────
def vol_threshold_regime(spy_close: pd.Series) -> pd.Series:
    log_ret = np.log(spy_close / spy_close.shift(1))
    rv = log_ret.rolling(5).std() * np.sqrt(252)
    def classify(v):
        if pd.isna(v):  return "Normal"
        if v < 0.12:    return "Calm"
        if v < 0.25:    return "Normal"
        if v < 0.50:    return "Stress"
        return "Crisis"
    return rv.map(classify)

print("Computing vol-threshold regimes...")
threshold_regimes = vol_threshold_regime(spy_daily)

# ── 3. Train 3-state HMM on IS 2007-2016 ──────────────────────────────────────
print("Training 3-state HMM on IS data (2007-2016)...")
from raits.hmm.engine import HMMEngine

IS_END   = "2016-12-31"
OOS_START = "2017-01-01"
spy_is = spy_daily[spy_daily.index <= IS_END]
print(f"  IS: {len(spy_is)} days  ({spy_is.index[0].date()} → {spy_is.index[-1].date()})")

hmm3 = HMMEngine(n_components=3)
try:
    hmm3.fit(spy_is, save=False)
    print("  Trained OK")
    for i in range(3):
        m = hmm3.model.means_[i]
        c = hmm3.model.covars_[i]
        var = float(np.sum(c)) if c.ndim == 1 else float(np.trace(c))
        print(f"    State {i} ({hmm3.state_name(i):6}): "
              f"mean_logret={m[0]:+.4f}  mean_vol={m[1]:.4f}  var={var:.6f}")
except Exception as e:
    print(f"  HMM fit failed: {e}")
    sys.exit(1)

# ── 4. Predict OOS 2017-2024 (rolling 252-day window, weekly retrain) ──────────
print("\nPredicting 2017-2024 with weekly retrain (takes ~30s)...")
LOOKBACK     = 252
hmm3_regimes = pd.Series("Normal", index=spy_daily.index, dtype=str)
oos_dates    = spy_daily.index[spy_daily.index >= OOS_START]
last_retrain = None
n            = len(oos_dates)

for k, date in enumerate(oos_dates):
    i = spy_daily.index.get_loc(date)
    if i < LOOKBACK:
        continue

    # Weekly retrain
    if last_retrain is None or (date - last_retrain).days >= 7:
        window_train = spy_daily.iloc[max(0, i - LOOKBACK): i]
        try:
            hmm3.retrain(window_train, save=False)
        except Exception:
            pass
        last_retrain = date

    window_pred = spy_daily.iloc[i - LOOKBACK: i + 1]
    try:
        idx = hmm3.predict_current(window_pred)
        hmm3_regimes[date] = hmm3.state_name(idx)
    except Exception:
        pass

    if (k + 1) % 200 == 0:
        print(f"  {k+1}/{n}...")

print(f"  Done ({n} days predicted)")

# ── 5. Comparison ──────────────────────────────────────────────────────────────
compare = pd.DataFrame({
    "threshold": threshold_regimes,
    "hmm3":      hmm3_regimes,
}).loc[OOS_START:]

print("\n" + "="*70)
print("REGIME COMPARISON  |  Vol Threshold (w/ Crisis) vs 3-state HMM")
print("="*70)

total = len(compare)
agree = (compare["threshold"] == compare["hmm3"]).sum()
print(f"\nPeriod : {OOS_START} → 2024-12-31  ({total} days)")
print(f"Agree  : {agree}/{total}  ({agree/total:.1%})")

print("\nVol threshold distribution:")
for state in ["Calm","Normal","Stress","Crisis"]:
    n = (compare["threshold"] == state).sum()
    if n: print(f"  {state:<8}: {n:4d} days ({n/total:.1%})")

print("\n3-state HMM distribution:")
for state in ["Calm","Normal","Stress"]:
    n = (compare["hmm3"] == state).sum()
    if n: print(f"  {state:<8}: {n:4d} days ({n/total:.1%})")

print("\nDisagreements by type (threshold → hmm):")
dis = compare[compare["threshold"] != compare["hmm3"]]
print(dis.groupby(["threshold","hmm3"]).size().rename("days").to_string())

# ── 6. Key period breakdown ─────────────────────────────────────────────────────
PERIODS = [
    ("2018 Q4 correction",  "2018-10-01", "2018-12-31"),
    ("2020 COVID crash",    "2020-02-01", "2020-06-30"),
    ("2020 COVID recovery", "2020-07-01", "2020-12-31"),
    ("2022 Bear market",    "2022-01-01", "2022-12-31"),
    ("2023 Recovery",       "2023-01-01", "2023-12-31"),
    ("2024",                "2024-01-01", "2024-12-31"),
]

log_ret = np.log(spy_daily / spy_daily.shift(1))
rv5 = (log_ret.rolling(5).std() * np.sqrt(252)).dropna()

print("\n" + "="*70)
print("KEY PERIOD BREAKDOWN")
print("="*70)

for label, start, end in PERIODS:
    mask = (compare.index >= start) & (compare.index <= end)
    sub  = compare[mask]
    if sub.empty:
        continue

    rv_sub = rv5[(rv5.index >= start) & (rv5.index <= end)]
    ag     = (sub["threshold"] == sub["hmm3"]).mean()

    thr_counts = sub["threshold"].value_counts()
    hmm_counts = sub["hmm3"].value_counts()

    print(f"\n{label}  ({start[:7]} → {end[:7]}, {len(sub)} days)")
    print(f"  Vol 5d  — mean={rv_sub.mean():.1%}  max={rv_sub.max():.1%}  "
          f"days>50%={(rv_sub>0.50).sum()}")
    print(f"  Agree   — {ag:.0%}")

    thr_str = "  ".join(f"{s}={v}" for s,v in thr_counts.items())
    hmm_str = "  ".join(f"{s}={v}" for s,v in hmm_counts.items())
    print(f"  Thresh  — {thr_str}")
    print(f"  HMM     — {hmm_str}")

    # Show first 5 disagreement days
    sub_dis = sub[sub["threshold"] != sub["hmm3"]]
    if not sub_dis.empty:
        print(f"  Disagree ({len(sub_dis)} days, first 5):")
        for date, row in sub_dis.head(5).iterrows():
            rv_val = rv5.get(date, float("nan"))
            print(f"    {date.date()}  thresh={row['threshold']:<8} "
                  f"hmm={row['hmm3']:<8} vol={rv_val:.1%}")

print("\n" + "="*70)
print("INTERPRETATION GUIDE")
print("="*70)
print("""
High agreement (>80%): HMM and vol threshold see the same regimes
  → Safe to wire HMM into backtest without major behavior change

COVID crash (2020-02 → 2020-06):
  - Vol threshold: should show Crisis for March/April (vol >50%)
  - 3-state HMM:  can only show Stress (no Crisis state)
  - Disagreement here is EXPECTED and is exactly the gap we want to fix

Stress vs Normal disagreements:
  - If HMM assigns Normal when threshold says Stress → HMM is smoother
  - If HMM assigns Stress when threshold says Normal → HMM is more sensitive

Next step: if results look comparable, implement 4-state HMM with 20d_return
feature to properly capture Crisis vs Stress distinction.
""")
