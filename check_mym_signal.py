"""
check_mym_signal.py — diagnose MYM direction discrepancy
=========================================================
Câu hỏi: tại sao --print-signals cho MYM SHORT Jul27
         nhưng reconcile route (60D IBKR) cho MYM LONG Jul23 BLOCKED?

Hai hypothesis:
  H1: 60D history không đủ để replicate đúng backtest state (LONG Jul23 bị
      stop-out intraday, SHORT Jul27 re-entry — 60D IBKR không thấy stop-out)
  H2: splice offset -57pt làm EMA/Chandelier levels khác nhau → flip direction

Test plan:
  1. Load MYM parquet (full 8yr) → run backtest_swing_tf(return_open=True)
     → confirm open position = SHORT Jul27 (matches --print-signals)
  2. Load MYM parquet limited to last 60 calendar days → same call
     → nếu LONG Jul23: H1 confirmed (history)
     → nếu SHORT Jul27: H2 (offset) hoặc vấn đề khác
  3. Print daily close + EMA30 + Chandelier stop cho Jul 21-27
     → xác nhận LONG Jul23 bị stop-out lúc nào
  4. Print EMA30 trên full parquet vs 60D parquet để so sánh

Chạy từ d:\\raits:
    python check_mym_signal.py
"""
import sys, datetime
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from futures.basket import BASKET, SWING_TF_PARAM, REGIME, data_filename
from futures.swing_tf_harness import backtest_swing_tf
from futures._validated_core import benchmark_daily, label_regimes
from futures.swing_tf import costs_for_basket

PARQUET = "data/cache/futures/YM_continuous_1m_8y.parquet"
REGIME_CSV = "spy_daily_live.csv"
HMM_FIT_END = REGIME["hmm_fit_end"]

EMA  = SWING_TF_PARAM["ema_period"]         # 30
MULT = SWING_TF_PARAM["chandelier_atr_mult"] # 2.5
HOLD = SWING_TF_PARAM["max_hold_days"]       # 5

MYM_OFFSET = -57.0   # from _ibkr_splice_offsets.json

def load_labels():
    bench = benchmark_daily(REGIME_CSV)
    return label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)

def load_parquet(cutoff_days=None):
    df = pd.read_parquet(PARQUET)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    if cutoff_days is not None:
        cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=cutoff_days)
        df = df[df.index >= cutoff]
    return df

def run_and_show(label, df, labels, cost):
    _, pos = backtest_swing_tf(df, labels, cost,
                               ema_period=EMA, chandelier_atr_mult=MULT,
                               max_hold_days=HOLD, return_open=True)
    if pos is None:
        print(f"  {label}: open_pos = None")
    else:
        ed = pos.get("entry_day") or pos.get("entry_date") or "?"
        print(f"  {label}: dir={pos['dir']}  entry={pos['entry']:.2f}"
              f"  stop={pos['stop']:.2f}  entry_day={ed}")
    return pos

def daily_ema_atr(df):
    """Resample to daily OHLC + compute EMA30 and ATR14 on close."""
    d = df.resample("1D").agg({"open": "first", "high": "max",
                               "low": "min", "close": "last"}).dropna()
    c = d["close"]
    # EMA30
    ema = c.ewm(span=EMA, adjust=False).mean()
    # ATR14 on daily
    tr = pd.concat([
        d["high"] - d["low"],
        (d["high"] - c.shift()).abs(),
        (d["low"]  - c.shift()).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    return d, ema, atr

def print_recent_levels(df, label, n_days=10):
    """Print daily close, EMA30, ATR14, chandelier levels for last n_days."""
    d, ema, atr = daily_ema_atr(df)
    recent = d[d.index >= d.index[-1] - pd.Timedelta(days=n_days)]
    print(f"\n  {'Date':<12} {'Close':>8} {'EMA30':>8} {'ATR14':>7}"
          f"  {'Chan-LONG':>10} {'Chan-SHORT':>11}  {'Above EMA':>9}")
    print(f"  {'-'*75}")
    for dt in recent.index:
        cl  = d["close"].get(dt, np.nan)
        em  = ema.get(dt, np.nan)
        at  = atr.get(dt, np.nan)
        hi  = d["high"].get(dt, np.nan)
        lo  = d["low"].get(dt, np.nan)
        # Chandelier: entry at day's close, stop = close - mult*ATR (LONG) or + (SHORT)
        chan_long  = cl - MULT * at if not np.isnan(at) else np.nan
        chan_short = cl + MULT * at if not np.isnan(at) else np.nan
        above = "LONG" if cl > em else "SHORT"
        print(f"  {str(dt.date()):<12} {cl:>8.1f} {em:>8.1f} {at:>7.1f}"
              f"  {chan_long:>10.1f} {chan_short:>11.1f}  {above:>9}")

def main():
    print("=" * 68)
    print("MYM SIGNAL DIAGNOSTIC")
    print(f"  EMA={EMA}  chandelier_mult={MULT}  max_hold={HOLD}d")
    print(f"  MYM splice offset = {MYM_OFFSET:+.1f} pts")
    print("=" * 68)

    labels = load_labels()
    cost   = costs_for_basket()["MYM"]

    # ── Test 1: full parquet ────────────────────────────────────────────────
    print("\n[T1] Full parquet (8yr):")
    df_full = load_parquet()
    print(f"     bars: {len(df_full)}  range: {df_full.index[0]} → {df_full.index[-1]}")
    pos_full = run_and_show("full", df_full, labels, cost)

    # ── Test 2: parquet limited to 60 calendar days ─────────────────────────
    print("\n[T2] Parquet limited to last 60 calendar days:")
    df_60 = load_parquet(cutoff_days=60)
    print(f"     bars: {len(df_60)}  range: {df_60.index[0]} → {df_60.index[-1]}")
    pos_60 = run_and_show("60D", df_60, labels, cost)

    # ── Test 3: parquet limited to 90 calendar days ─────────────────────────
    print("\n[T3] Parquet limited to last 90 calendar days:")
    df_90 = load_parquet(cutoff_days=90)
    print(f"     bars: {len(df_90)}  range: {df_90.index[0]} → {df_90.index[-1]}")
    pos_90 = run_and_show("90D", df_90, labels, cost)

    # ── Test 4: parquet limited to 120 calendar days ────────────────────────
    print("\n[T4] Parquet limited to last 120 calendar days:")
    df_120 = load_parquet(cutoff_days=120)
    print(f"     bars: {len(df_120)}  range: {df_120.index[0]} → {df_120.index[-1]}")
    pos_120 = run_and_show("120D", df_120, labels, cost)

    # ── Test 5: EMA30 comparison full vs 60D (last 15 trading days) ─────────
    print("\n[T5] Daily close + EMA30 + Chandelier (full parquet, last 15 days):")
    print_recent_levels(df_full, "full", n_days=15)

    print("\n[T5b] Same window but 60D parquet (EMA warm-up từ 60D only):")
    print_recent_levels(df_60, "60D", n_days=15)

    # ── Hypothesis verdict ──────────────────────────────────────────────────
    print("\n" + "=" * 68)
    print("VERDICT:")
    if pos_full is not None and pos_60 is not None:
        if pos_full["dir"] != pos_60["dir"]:
            print("  H1 CONFIRMED: 60D history gives different direction.")
            print("  → EMA warm-up từ 60D không đủ để match 8yr backtest state.")
        else:
            print("  H1 REJECTED: 60D parquet và full parquet cùng direction.")
            print("  → Discrepancy với reconcile route do splice offset -57pt.")
    elif pos_full is not None and pos_60 is None:
        print("  H1 CONFIRMED: 60D history → no open position; full → open position.")
    else:
        print("  Không đủ data để kết luận.")
    print("=" * 68)


if __name__ == "__main__":
    main()
