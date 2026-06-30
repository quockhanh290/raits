"""
nonequity/mr_explore.py — intraday mean-reversion characterization (pre-strategy)
=================================================================================
Falsifies the PREREQUISITE for a VWAP-MR strategy BEFORE any strategy is written.
Mirrors the equity-index logic that killed MR there (Variance Ratio ≈ 1 → random
walk → nothing to fade). If gold intraday is also VR≈1, MR is hopeless and we
stop here — cheaply.

Three diagnostics, on 5-min bars, intraday only (overnight/break returns masked):

  1. VARIANCE RATIO at several horizons.  VR<1 mean-revert · VR≈1 random walk ·
     VR>1 trend. This is the same test used to reject equity-index MR.
  2. VWAP DEVIATION persistence for each candidate session anchor (Globex 18:00 ET
     and COMEX floor 08:20 ET). Lag-k autocorr of the deviation: LOWER = deviation
     decays faster = price returns to VWAP sooner (MR-friendly); HIGHER = deviation
     persists = drift. Read RELATIVE (which anchor is lower, vs #1/#3), not by sign
     — VWAP is a slow cumulative mean so the autocorr is positive even under MR.
  3. BOLLINGER TOUCH → REVERT rate: of the bars that poke a band and close back
     inside (the VWAP-MR entry trigger), what fraction actually revert toward
     VWAP within `lookahead` bars vs. keep going (breakout). ~50% = coin flip.

Self-contained: reads only nonequity._core. NO strategy logic, NO equity-RTH
window, NO trading — characterization only.

Usage
-----
    python -m nonequity.mr_explore --parquet nonequity/data/GC_continuous_1m_8y.parquet
"""
from __future__ import annotations
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from nonequity._core import load_parquet
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nonequity._core import load_parquet


GAP_MIN = 10.0   # a 5-min series gap larger than this = session/overnight break


def resample_5m_full(df: pd.DataFrame) -> pd.DataFrame:
    o = df["open"].resample("5min").first()
    h = df["high"].resample("5min").max()
    l = df["low"].resample("5min").min()
    c = df["close"].resample("5min").last()
    v = df["volume"].resample("5min").sum()
    out = pd.concat([o, h, l, c, v], axis=1)
    out.columns = ["open", "high", "low", "close", "volume"]
    return out.dropna()


def masked_log_returns(bars: pd.DataFrame) -> pd.Series:
    """5-min log returns with returns that span a >GAP_MIN time break set to NaN
    (so overnight/session gaps never enter the variance estimates)."""
    r = np.log(bars["close"]).diff()
    dt = bars.index.to_series().diff().dt.total_seconds() / 60.0
    r[dt > GAP_MIN] = np.nan
    return r


def variance_ratio(r1: pd.Series, ks=(1, 3, 6, 12)) -> dict:
    """VR(k) = Var(k-bar return) / (k * Var(1-bar return)). k-bar returns built
    by rolling-sum of 1-bar returns; any window containing a masked (NaN) gap is
    dropped (min_periods=k). Returns {k: (VR, n_eff)}."""
    r1 = r1.copy()
    var1 = np.nanvar(r1.to_numpy())
    out = {}
    for k in ks:
        if k == 1:
            out[k] = (1.0, int(np.isfinite(r1).sum()))
            continue
        rk = r1.rolling(k, min_periods=k).sum()        # NaN propagates over gaps
        rk = rk.iloc[::k]                               # non-overlapping windows
        vk = np.nanvar(rk.to_numpy())
        n = int(np.isfinite(rk).sum())
        out[k] = (float(vk / (k * var1)) if var1 > 0 else float("nan"), n)
    return out


def session_id(idx: pd.DatetimeIndex, anchor_hour: int, anchor_min: int) -> np.ndarray:
    """Assign each bar to a session that starts at anchor time (ET). A bar belongs
    to the session whose anchor is the most recent anchor at/before it."""
    et = idx  # already ET from load_parquet
    mins = et.hour * 60 + et.minute
    anchor = anchor_hour * 60 + anchor_min
    # day boundary shifts when before the anchor → belongs to previous session day
    day = et.normalize()
    before = mins < anchor
    sess = day - pd.to_timedelta(before.astype(int), unit="D")
    return sess.values


def vwap_deviation_autocorr(bars: pd.DataFrame, anchor_hour, anchor_min, lag=3) -> tuple:
    """Per-session VWAP; deviation = close - vwap (normalized by session std).
    Returns (mean lag-`lag` autocorr of deviation, n_sessions). Negative autocorr
    at short lag = mean-reverting deviation; ~0 = random."""
    sess = session_id(bars.index, anchor_hour, anchor_min)
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    pv = tp * bars["volume"]
    g = pd.DataFrame({"sess": sess, "pv": pv.values, "v": bars["volume"].values,
                      "close": bars["close"].values}, index=bars.index)
    accs = []
    for _, blk in g.groupby("sess"):
        if len(blk) < 20:
            continue
        vwap = blk["pv"].cumsum() / blk["v"].cumsum()
        dev = blk["close"].to_numpy() - vwap.to_numpy()
        sd = np.nanstd(dev)
        if sd == 0 or not np.isfinite(sd):
            continue
        dev = dev / sd
        if len(dev) > lag + 5:
            a = np.corrcoef(dev[:-lag], dev[lag:])[0, 1]
            if np.isfinite(a):
                accs.append(a)
    return (float(np.mean(accs)) if accs else float("nan"), len(accs))


def bollinger_revert_rate(bars: pd.DataFrame, anchor_hour, anchor_min,
                          window=20, m=2.0, lookahead=6) -> dict:
    """Per session: band = rolling mean ± m*rolling std on close. Count entry
    triggers (poke band, close back inside) and whether price reverts toward the
    mean within `lookahead` bars. Returns rate + counts."""
    sess = session_id(bars.index, anchor_hour, anchor_min)
    g = pd.DataFrame({"sess": sess, "high": bars["high"].values, "low": bars["low"].values,
                      "close": bars["close"].values}, index=bars.index)
    rev = brk = 0
    for _, blk in g.groupby("sess"):
        c = blk["close"].to_numpy(); hi = blk["high"].to_numpy(); lo = blk["low"].to_numpy()
        if len(c) < window + lookahead + 2:
            continue
        ma = pd.Series(c).rolling(window).mean().to_numpy()
        sd = pd.Series(c).rolling(window).std().to_numpy()
        up = ma + m * sd; dn = ma - m * sd
        for t in range(window, len(c) - lookahead):
            if not np.isfinite(up[t]):
                continue
            short_sig = hi[t] >= up[t] and c[t] < up[t]
            long_sig = lo[t] <= dn[t] and c[t] > dn[t]
            if not (short_sig or long_sig):
                continue
            fut = c[t + 1:t + 1 + lookahead]
            if short_sig:   # expect price to fall back toward ma
                rev += int((fut <= ma[t]).any()); brk += int(not (fut <= ma[t]).any())
            else:           # long: expect rise toward ma
                rev += int((fut >= ma[t]).any()); brk += int(not (fut >= ma[t]).any())
    tot = rev + brk
    return dict(rate=(rev / tot if tot else float("nan")), reverts=rev, breaks=brk, n=tot)


def main() -> None:
    ap = argparse.ArgumentParser(description="Intraday MR characterization (pre-strategy).")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--bb-window", type=int, default=20)
    ap.add_argument("--bb-mult", type=float, default=2.0)
    ap.add_argument("--lookahead", type=int, default=6)
    a = ap.parse_args()

    df = load_parquet(a.parquet)
    bars = resample_5m_full(df)
    print(f"5-min bars: {len(bars):,}  {bars.index[0].date()} → {bars.index[-1].date()}\n")

    print("1. VARIANCE RATIO (5-min base; <1 mean-revert, ≈1 random walk, >1 trend):")
    r1 = masked_log_returns(bars)
    vr = variance_ratio(r1, ks=(1, 3, 6, 12, 24))
    for k, (v, n) in vr.items():
        tag = "mean-revert" if v < 0.9 else ("trend" if v > 1.1 else "~random walk")
        print(f"   VR({k:>2}-bar / {k*5:>3}min) = {v:5.3f}   (n={n:>6})   {tag}")

    anchors = {"Globex 18:00 ET": (18, 0), "COMEX floor 08:20 ET": (8, 20)}
    print("\n2. VWAP DEVIATION persistence (lag-3 autocorr; LOWER = reverts to VWAP "
          "faster. Read relative, not by sign — slow cumulative VWAP keeps it positive):")
    for name, (h, mi) in anchors.items():
        ac, ns = vwap_deviation_autocorr(bars, h, mi, lag=3)
        print(f"   {name:<22} autocorr={ac:+.3f}  (sessions={ns})")

    print(f"\n3. BOLLINGER touch→revert rate (window={a.bb_window}, m={a.bb_mult}, "
          f"lookahead={a.lookahead} bars; ~50% = coin flip):")
    for name, (h, mi) in anchors.items():
        b = bollinger_revert_rate(bars, h, mi, window=a.bb_window, m=a.bb_mult,
                                  lookahead=a.lookahead)
        print(f"   {name:<22} revert={b['rate']*100:5.1f}%  "
              f"(reverts={b['reverts']}, breaks={b['breaks']}, n={b['n']})")

    print("\nPre-commit read: VR≥0.95 at all horizons AND revert≈50% → MR hopeless, "
          "close (as equity index). VR<0.9 somewhere AND revert>55% → worth a strategy.")


if __name__ == "__main__":
    main()
