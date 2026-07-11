"""
measure_entry_timing.py
------------------------
Đo impact của entry timing mismatch:
  backtest:  entry tại ~14:05 ET bar close (lúc pattern fire)
  live:      MARKET order fill tại ~16:05 ET (sau khi parquet update + runner chạy)

Lệch 2 giờ cuối phiên — đo tổng P&L delta và approximate Calmar impact.

Usage:
    cd d:\\raits
    python measure_entry_timing.py [--live-entry-time 16:05]
"""
import sys, argparse, numpy as np, pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from futures.basket import BASKET, REGIME, RISK, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures._validated_core import load_parquet, benchmark_daily, label_regimes

# ─── args ────────────────────────────────────────────────────────────────────
ap = argparse.ArgumentParser()
ap.add_argument("--live-entry-time", default="16:05",
                help="Time of live MARKET fill (HH:MM ET, default: 16:05)")
ap.add_argument("--data-dir", default="data/cache/futures")
ap.add_argument("--regime-csv", default="spy_daily_live.csv")
a = ap.parse_args()

HMM_FIT_END = REGIME["hmm_fit_end"]   # "2024-12-31"
DATA_DIR = Path(a.data_dir)
LIVE_TIME = a.live_entry_time          # e.g. "16:05"

print("=" * 72)
print(f"measure_entry_timing — backtest(14:05 bar) vs live({LIVE_TIME} MARKET)")
print(f"  data-dir:    {DATA_DIR}")
print(f"  regime-csv:  {a.regime_csv}")
print(f"  hmm_fit_end: {HMM_FIT_END}")
print("=" * 72)

# ─── load data ───────────────────────────────────────────────────────────────
print("\n[1] Loading parquet...")
dfs = {n: load_parquet(str(DATA_DIR / data_filename(c))) for n, c in BASKET.items()}
for n, df in dfs.items():
    print(f"    {n}: {len(df):,} bars  {df.index[0].date()} → {df.index[-1].date()}")

# ─── labels + costs ──────────────────────────────────────────────────────────
print("\n[2] HMM labels...")
bench = benchmark_daily(a.regime_csv)
labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
costs  = costs_for_basket(slippage_ticks=2.0)

# ─── backtest ────────────────────────────────────────────────────────────────
print("\n[3] Backtest (IS, 2-tick slippage)...")
engine   = SwingTFEngine()
swing_bt = engine.backtest_basket(dfs, labels, costs)
all_trades = [(inst, t) for inst, lst in swing_bt.items() for t in lst]
print(f"    Total swing trades: {len(all_trades)}")

# ─── resample to 5-min per instrument ────────────────────────────────────────
print("\n[4] Resample 1m → 5m for live entry lookup...")
dfs5 = {}
for inst, df in dfs.items():
    df5 = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["close"])
    dfs5[inst] = df5

# ─── measure delta ───────────────────────────────────────────────────────────
print(f"\n[5] Measuring entry price delta (backtest_bar vs {LIVE_TIME} bar)...")

LIVE_H, LIVE_M = int(LIVE_TIME.split(":")[0]), int(LIVE_TIME.split(":")[1])

rows = []
missing = 0
for inst, t in all_trades:
    df5     = dfs5[inst]
    pv      = BASKET[inst].point_value
    ent_day = pd.Timestamp(t["day"]).normalize()
    dir_    = t["direction"]   # "LONG" or "SHORT"
    entry_bt = float(t["entry"])   # backtest entry (14:05 bar close)
    entry_time_bt = t.get("entry_time")  # actual signal bar timestamp

    # get LIVE_TIME bar on entry_day
    day_bars = df5[df5.index.normalize() == ent_day]
    live_candidates = day_bars[
        (day_bars.index.hour == LIVE_H) & (day_bars.index.minute >= LIVE_M)
    ]
    if len(live_candidates) == 0:
        # fallback: last bar of the day
        end_bars = day_bars[day_bars.index.hour >= 15]
        if len(end_bars) == 0:
            missing += 1
            continue
        entry_live = float(end_bars.iloc[-1]["close"])
    else:
        entry_live = float(live_candidates.iloc[0]["close"])

    # P&L delta from entry shift (same exit assumed)
    dir_sign = 1.0 if dir_ == "LONG" else -1.0
    # live P&L = backtest P&L + (entry_bt - entry_live) * dir_sign * pv
    pnl_delta = (entry_bt - entry_live) * dir_sign * pv

    rows.append({
        "inst":          inst,
        "entry_day":     ent_day.date(),
        "direction":     dir_,
        "entry_bt":      entry_bt,
        "entry_bt_time": str(entry_time_bt) if entry_time_bt else "",
        "entry_live":    entry_live,
        "entry_diff_pts": entry_live - entry_bt,  # >0 means live entered higher
        "pnl_bt":        float(t["pnl"]),
        "pnl_delta":     pnl_delta,               # >0 = live better, <0 = live worse
    })

df_rows = pd.DataFrame(rows)
n = len(df_rows)
total_bt_pnl   = df_rows["pnl_bt"].sum()
total_delta    = df_rows["pnl_delta"].sum()
pct_impact     = total_delta / total_bt_pnl * 100 if total_bt_pnl != 0 else float("nan")

print(f"\n{'='*72}")
print(f"RESULTS — entry timing mismatch (backtest 14:05 → live {LIVE_TIME})")
print(f"{'='*72}")
print(f"  Trades analyzed:     {n}  (missing {LIVE_TIME} bar: {missing})")
print(f"  Backtest total P&L:  ${total_bt_pnl:,.0f}")
print(f"  Entry diff (median): {df_rows['entry_diff_pts'].median():.3f} pts  "
      f"(live − backtest; + = live entered higher)")
print(f"  Entry diff (std):    {df_rows['entry_diff_pts'].std():.3f} pts")
print(f"  P&L delta total:     ${total_delta:+,.0f}  (+ = live better, - = live worse)")
print(f"  P&L delta / trade:   ${total_delta/n:+,.0f}")
print(f"  Impact as % of BT:   {pct_impact:+.1f}%")
print()

print("By instrument:")
for inst, grp in df_rows.groupby("inst"):
    pv = BASKET[inst].point_value
    print(f"  {inst:6s}: {len(grp):3d} trades | "
          f"entry_diff={grp['entry_diff_pts'].median():+.3f}pts (med) | "
          f"pnl_delta=${grp['pnl_delta'].sum():+,.0f} | "
          f"${grp['pnl_delta'].mean():+,.0f}/trade")

print()
print("By direction:")
for dir_, grp in df_rows.groupby("direction"):
    print(f"  {dir_:5s}: {len(grp):3d} trades | "
          f"entry_diff={grp['entry_diff_pts'].median():+.3f}pts (med) | "
          f"pnl_delta=${grp['pnl_delta'].sum():+,.0f}")

print()
# Approximate Calmar: rebuild equity curve with adjusted P&L
# (simple approach: add delta per trade sorted by entry_day)
df_sorted = df_rows.sort_values("entry_day").copy()
df_sorted["pnl_live"] = df_sorted["pnl_bt"] + df_sorted["pnl_delta"]

cum_bt   = df_sorted["pnl_bt"].cumsum()
cum_live = df_sorted["pnl_live"].cumsum()

def calmar_approx(cum_series, account=50_000):
    """Rough Calmar from cumulative P&L series (no exact peak-to-trough)."""
    total_return = cum_series.iloc[-1] / account
    peak = cum_series.cummax()
    dd   = (cum_series - peak)
    max_dd = abs(dd.min())
    if max_dd == 0:
        return float("inf")
    # annualize: assume 252 trading days, series spans all trades (not daily)
    return total_return / (max_dd / account)

calmar_bt   = calmar_approx(cum_bt)
calmar_live = calmar_approx(cum_live)

print(f"Approximate Calmar (trade-level, not daily, rough estimate):")
print(f"  Backtest (14:05 entry): {calmar_bt:.2f}")
print(f"  Live ({LIVE_TIME} entry):   {calmar_live:.2f}")
print(f"  Delta:                  {calmar_live - calmar_bt:+.2f}")
print()

threshold_pct = 5.0
print(f"DECISION GUIDE (threshold: {threshold_pct}% impact):")
if abs(pct_impact) < threshold_pct:
    print(f"  → |{pct_impact:.1f}%| < {threshold_pct}% — OPTION A VIABLE")
    print(f"    Entry timing lệch {LIVE_TIME} không đáng kể.")
    print(f"    Chạy runner sau 16:00 ET (sau khi parquet update).")
else:
    print(f"  → |{pct_impact:.1f}%| >= {threshold_pct}% — CÂN NHẮC OPTION C")
    print(f"    Entry timing lệch {LIVE_TIME} ảnh hưởng rõ ràng.")
    print(f"    Cân nhắc chạy runner trong cửa sổ 14:00-15:55 ET với intraday bars.")

print()
print(f"  (Để so sánh: vault Calmar floor = 2.04. Nếu live Calmar vẫn > 2.04 → GO)")
print("=" * 72)
