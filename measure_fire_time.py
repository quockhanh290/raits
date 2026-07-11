"""
measure_fire_time.py
---------------------
Đo: backtest signal fire LÚC NÀO trong window 14:00-15:55 ET,
và delta P&L nếu live fill tại 15:55 vs actual fire time.

Usage:
    cd d:\\raits
    python measure_fire_time.py
    python measure_fire_time.py --data-dir data\\cache\\futures\\frozen_sim --nkd-parquet global_index/data/NKD_frozen_2024.parquet
"""
import sys, argparse, collections, numpy as np, pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from futures.basket import BASKET, REGIME, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures._validated_core import load_parquet, benchmark_daily, label_regimes

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir",    default="data/cache/futures")
ap.add_argument("--regime-csv",  default="spy_daily_live.csv")
ap.add_argument("--nkd-parquet", default=None,
                help="Optional NKD parquet (unused — swing basket only)")
a = ap.parse_args()

HMM_FIT_END = REGIME["hmm_fit_end"]
DATA_DIR    = Path(a.data_dir)

print("=" * 72)
print("measure_fire_time — entry_time distribution + B-live 15:55 delta")
print(f"  data-dir:   {DATA_DIR}")
print(f"  regime-csv: {a.regime_csv}")
print("=" * 72)

# ─── load + backtest ──────────────────────────────────────────────────────────
print("\n[1] Load parquet + backtest...")
dfs    = {n: load_parquet(str(DATA_DIR / data_filename(c))) for n, c in BASKET.items()}
bench  = benchmark_daily(a.regime_csv)
labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
costs  = costs_for_basket(slippage_ticks=2.0)
swing_bt = SwingTFEngine().backtest_basket(dfs, labels, costs)

all_trades = [(inst, t) for inst, lst in swing_bt.items() for t in lst]
print(f"  Total swing trades: {len(all_trades)}")

# ─── resample 5-min ──────────────────────────────────────────────────────────
dfs5 = {}
for inst, df in dfs.items():
    dfs5[inst] = df.resample("5min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"
    }).dropna(subset=["close"])

# ─── extract fire times ──────────────────────────────────────────────────────
print("\n[2] Fire time distribution...")
fire_hhmm   = []   # "14:05" etc
fire_offsets = []  # minutes after 14:00
rows = []
missing_15h55 = 0

for inst, t in all_trades:
    fire_ts = t.get("entry_time")
    if fire_ts is None:
        continue

    fire_ts  = pd.Timestamp(fire_ts)
    fire_hm  = fire_ts.strftime("%H:%M")
    fire_min = (fire_ts.hour - 14) * 60 + fire_ts.minute   # minutes after 14:00

    fire_hhmm.append(fire_hm)
    fire_offsets.append(fire_min)

    # get 15:55 bar on same day
    day_bars  = dfs5[inst][dfs5[inst].index.normalize() == fire_ts.normalize()]
    bars_1555 = day_bars.between_time("15:55", "15:59")

    if bars_1555.empty:
        missing_15h55 += 1
        continue

    price_fire  = float(t["entry"])              # backtest entry = fire bar close
    price_15h55 = float(bars_1555.iloc[0]["close"])
    pv          = BASKET[inst].point_value
    dir_sign    = 1.0 if t["direction"] == "LONG" else -1.0

    # P&L delta: live fill at 15:55 vs backtest fill at fire_time
    # pnl_live = pnl_bt + (price_fire - price_15h55) * dir_sign * pv
    pnl_delta = (price_fire - price_15h55) * dir_sign * pv  # >0 = 15:55 better

    rows.append({
        "inst":        inst,
        "entry_day":   fire_ts.date(),
        "direction":   t["direction"],
        "fire_hm":     fire_hm,
        "fire_offset": fire_min,     # minutes after 14:00
        "price_fire":  price_fire,
        "price_15h55": price_15h55,
        "price_diff":  price_15h55 - price_fire,  # >0 = 15:55 price higher
        "pnl_bt":      float(t["pnl"]),
        "pnl_delta":   pnl_delta,
    })

df = pd.DataFrame(rows)
n = len(df)
total_bt_pnl  = df["pnl_bt"].sum()
total_delta   = df["pnl_delta"].sum()

# ─── fire time distribution ──────────────────────────────────────────────────
print(f"\n  Fire time distribution ({len(fire_hhmm)} trades with entry_time):")
cnt = collections.Counter(fire_hhmm)

# group into 15-min buckets for readability
buckets = collections.OrderedDict()
for hm, c in sorted(cnt.items()):
    h, m = int(hm[:2]), int(hm[3:])
    bucket_start = 14 * 60 + (m // 15) * 15 if h == 14 else h * 60 + (m // 15) * 15
    b_h, b_m = divmod(bucket_start, 60)
    label = f"{b_h:02d}:{b_m:02d}-{b_h:02d}:{b_m+14:02d}"
    buckets[label] = buckets.get(label, 0) + c

total_with_time = len(fire_hhmm)
for label, c in sorted(buckets.items()):
    bar = "█" * (c * 40 // max(buckets.values()))
    print(f"    {label}: {c:4d}  ({c/total_with_time*100:5.1f}%)  {bar}")

offsets = np.array(fire_offsets)
print(f"\n  Fire offset stats (minutes after 14:00):")
print(f"    median: {np.median(offsets):.0f} min  ({14 + int(np.median(offsets))//60}:{int(np.median(offsets))%60:02d} ET)")
print(f"    mean:   {offsets.mean():.0f} min")
print(f"    p25:    {np.percentile(offsets, 25):.0f} min")
print(f"    p75:    {np.percentile(offsets, 75):.0f} min")
print(f"    p90:    {np.percentile(offsets, 90):.0f} min")
pct_early = (offsets <= 15).sum() / len(offsets) * 100  # ≤14:15
print(f"\n    Fire trong 14:00-14:15 (first 3 bars): {(offsets <= 15).sum()} ({pct_early:.0f}%)")
print(f"    Fire sau 15:00:                         {(offsets >= 60).sum()} ({(offsets >= 60).sum()/len(offsets)*100:.0f}%)")

# ─── P&L delta: 15:55 vs fire-time ──────────────────────────────────────────
print(f"\n[3] P&L delta: live@15:55 vs backtest@fire-time")
print(f"  Trades analyzed: {n}  (missing 15:55 bar: {missing_15h55})")
print(f"  Backtest total P&L: ${total_bt_pnl:,.0f}")
print(f"\n  Entry price diff (15:55 − fire_time):")
print(f"    median:  {df['price_diff'].median():+.3f} pts")
print(f"    mean:    {df['price_diff'].mean():+.3f} pts")
print(f"    std:     {df['price_diff'].std():.3f} pts")

print(f"\n  P&L delta (live@15:55 vs backtest@fire):")
print(f"    Total:       ${total_delta:+,.0f}")
print(f"    Per trade:   ${total_delta/n:+,.0f}")
print(f"    As % of BT:  {total_delta/total_bt_pnl*100:+.1f}%")

# ─── by fire-time bucket ─────────────────────────────────────────────────────
print(f"\n  By fire-time bucket (offset from 14:00, delta = live@15:55 vs fire):")
df["bucket"] = pd.cut(df["fire_offset"],
                       bins=[-1, 15, 30, 60, 95, 115],
                       labels=["14:00-14:15", "14:15-14:30", "14:30-15:00",
                               "15:00-15:35", "15:35-15:55"])
for bkt, grp in df.groupby("bucket", observed=True):
    avg_offset = grp["fire_offset"].mean()
    print(f"    {bkt} (~{avg_offset:.0f}min after 14:00): "
          f"{len(grp):3d} trades | "
          f"price_diff={grp['price_diff'].median():+.3f}pts(med) | "
          f"pnl_delta=${grp['pnl_delta'].sum():+,.0f}")

# ─── Calmar approximation ────────────────────────────────────────────────────
print(f"\n[4] Approximate Calmar comparison (trade-level, rough):")
df_sorted = df.sort_values("entry_day")
cum_bt   = df_sorted["pnl_bt"].cumsum()
cum_live = (df_sorted["pnl_bt"] + df_sorted["pnl_delta"]).cumsum()

def calmar_approx(cum, account=50_000):
    if len(cum) == 0: return float("nan")
    r  = cum.iloc[-1] / account
    dd = (cum - cum.cummax())
    mdd = abs(dd.min())
    return r / (mdd / account) if mdd > 0 else float("inf")

calmar_bt   = calmar_approx(cum_bt)
calmar_live = calmar_approx(cum_live)

print(f"  Backtest (fire-time entry):  {calmar_bt:.2f}")
print(f"  B-live   (15:55 entry):      {calmar_live:.2f}  (delta: {calmar_live-calmar_bt:+.2f})")
print(f"  Floor reference:             2.04")

print(f"\n{'='*72}")
pct = abs(total_delta / total_bt_pnl * 100)
if pct < 3.0:
    verdict = "B-LIVE (15:55) ĐỦ — delta <3%, không cần continuous runner"
elif pct < 7.0:
    verdict = "B-LIVE CÓ THỂ — delta 3-7%, cân nhắc C nếu muốn tight hơn"
else:
    verdict = "CÂN NHẮC C (continuous 14:05) — delta >7%, 15:55 lệch nhiều"
print(f"VERDICT: {verdict}")
print("=" * 72)
