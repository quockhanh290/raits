"""
tier2/structure_test.py — Gate 1: is there structure to exploit? (asset-agnostic)
=================================================================================
THE cheap falsification gate (gold lesson). Before building any trend/MR strategy
on a new asset, measure whether the price series even HAS trend or mean-reversion
structure. If it's a random walk (VR≈1, Hurst≈0.5), NO strategy of that kind can
work — stop here, save the months a full backtest would cost.

Variance Ratio (Lo-MacKinlay, heteroskedasticity-robust):
  VR(q) = Var(q-day returns) / (q · Var(1-day returns))
  VR > 1  → positive autocorrelation → TRENDING (trend-following-able)
  VR < 1  → negative autocorrelation → MEAN-REVERTING (MR-able)
  VR ≈ 1  → random walk → NO exploitable structure of this kind
  z-stat |z| > 2 → the deviation from 1 is statistically significant.

Hurst exponent (rescaled-range) as a cross-check: >0.55 trend, <0.45 MR, ~0.5 RW.

Works on any daily OHLC (or resamples 1-min → daily close). Point it at whatever
tier-2 asset you fetch.

    python -m tier2.structure_test --parquet tier2/data/ZN_daily.parquet --name ZN
    python -m tier2.structure_test --parquet data/cache/futures/ZN_1m.parquet --name ZN --resample
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_daily_close(parquet, resample):
    df = pd.read_parquet(parquet)
    # normalize column names
    df.columns = [c.lower() for c in df.columns]
    if not isinstance(df.index, pd.DatetimeIndex):
        for cand in ("ts_event", "timestamp", "date", "time"):
            if cand in df.columns:
                df = df.set_index(pd.to_datetime(df[cand])); break
    if resample:
        # daily RTH-agnostic: last close per calendar day
        close = df.groupby(df.index.normalize())["close"].last()
    else:
        close = df["close"]
    close.index = pd.DatetimeIndex(close.index)
    return close.sort_index().dropna()


def variance_ratio(logret, q):
    """Lo-MacKinlay VR(q) with heteroskedasticity-robust z-stat."""
    r = logret.dropna().values
    n = len(r)
    if n < q * 3:
        return np.nan, np.nan
    mu = r.mean()
    var1 = np.sum((r - mu) ** 2) / (n - 1)
    # q-period overlapping returns variance
    rq = np.array([r[i:i + q].sum() for i in range(n - q + 1)])
    m = q * (n - q + 1) * (1 - q / n)
    varq = np.sum((rq - q * mu) ** 2) / m
    if var1 <= 0:
        return np.nan, np.nan
    vr = varq / var1  # m already contains the q factor → do NOT divide by q again
    # heteroskedasticity-robust variance of VR (Lo-MacKinlay M2)
    theta = 0.0
    denom = (np.sum((r - mu) ** 2)) ** 2
    for j in range(1, q):
        dj = np.sum((r[j:] - mu) ** 2 * (r[:-j] - mu) ** 2)
        delta = (dj / denom) if denom > 0 else 0.0
        theta += ((2 * (q - j) / q) ** 2) * delta
    z = (vr - 1) / np.sqrt(theta) if theta > 0 else np.nan
    return vr, z


def hurst_rs(logret, max_lag=40):
    """Rescaled-range Hurst exponent estimate."""
    r = logret.dropna().values
    if len(r) < max_lag * 4:
        max_lag = max(8, len(r) // 4)
    lags = range(4, max_lag)
    rs = []
    for lag in lags:
        chunks = len(r) // lag
        if chunks < 1:
            continue
        vals = []
        for i in range(chunks):
            seg = r[i * lag:(i + 1) * lag]
            z = np.cumsum(seg - seg.mean())
            R = z.max() - z.min(); S = seg.std()
            if S > 0:
                vals.append(R / S)
        if vals:
            rs.append((np.log(lag), np.log(np.mean(vals))))
    if len(rs) < 3:
        return np.nan
    xs, ys = zip(*rs)
    return float(np.polyfit(xs, ys, 1)[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--name", default="asset")
    ap.add_argument("--resample", action="store_true", help="resample 1-min → daily close")
    ap.add_argument("--horizons", default="2,5,10,20", help="VR horizons in days")
    a = ap.parse_args()

    close = load_daily_close(a.parquet, a.resample)
    logret = np.log(close).diff().dropna()
    yrs = (close.index[-1] - close.index[0]).days / 365.25

    print(f"\n{'='*64}\nSTRUCTURE TEST (Gate 1) | {a.name} | {len(close)} days "
          f"({close.index[0].date()}→{close.index[-1].date()}, {yrs:.1f}y)\n{'='*64}")
    print(f"{'horizon q':>10}{'VR(q)':>9}{'z-stat':>9}   interpretation")
    print("-"*64)
    verdicts = []
    for q in [int(x) for x in a.horizons.split(",")]:
        vr, z = variance_ratio(logret, q)
        if np.isnan(vr):
            print(f"{q:>10}{'n/a':>9}{'n/a':>9}   (insufficient data)"); continue
        if abs(z) < 2:
            interp = "random walk (no edge)"; v = "RW"
        elif vr > 1:
            interp = "TRENDING → trend-following-able"; v = "TREND"
        else:
            interp = "MEAN-REVERTING → MR-able"; v = "MR"
        verdicts.append(v)
        star = "*" if abs(z) >= 2 else " "
        print(f"{q:>10}{vr:>9.3f}{z:>9.2f}{star}  {interp}")

    h = hurst_rs(logret)
    print("-"*64)
    if not np.isnan(h):
        hi = ("trending" if h > 0.55 else "mean-reverting" if h < 0.45 else "random walk")
        print(f"Hurst exponent: {h:.3f}  ({hi})")
    print("-"*64)
    # overall verdict
    sig = [v for v in verdicts if v != "RW"]
    if not sig:
        print(f"VERDICT: {a.name} ≈ RANDOM WALK at all horizons → NO exploitable trend/MR")
        print("  structure. Trend-following AND mean-reversion both NO-GO. Do NOT backtest —")
        print("  pick a different asset (this is the gold outcome, caught cheaply).")
    elif all(v == "TREND" for v in sig):
        print(f"VERDICT: {a.name} shows TRENDING structure → trend-following worth a Gate-2")
        print("  edge test. (Structure ≠ profit after cost — Gate 2 still decides.)")
    elif all(v == "MR" for v in sig):
        print(f"VERDICT: {a.name} shows MEAN-REVERTING structure → MR strategy worth Gate 2.")
    else:
        print(f"VERDICT: {a.name} mixed by horizon — structure exists but scale-dependent;")
        print("  match strategy horizon to the significant VR horizon.")
    print()


if __name__ == "__main__":
    main()
