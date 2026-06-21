"""
calm_afternoon_diagnostic.py
----------------------------
Phân tích price behavior của SPY và individual stocks trong Calm regime
14:00-15:55 để xác định strategy phù hợp.

Câu hỏi cần trả lời:
  1. Bao nhiêu Calm days mỗi năm? (khung vũ trụ cơ bản)
  2. SPY move từ 14:00 → 15:55: trung bình, phân phối, directional bias
  3. VWAP deviation của SPY lúc 14:00 → gợi ý MR hay trend
  4. Intraday structure: 14:00-14:30 move có predict 14:30-15:55 move không?
  5. Individual stocks: VWAP deviation lúc 14:00 → behavior afterwards
  6. EOD (15:30-15:55): volume spike + reversal hay continuation?
  → Kết luận: MR, low-vol trend, hay EOD fade?

Usage:
    cd d:\\raits\\raits
    python raits/scripts/calm_afternoon_diagnostic.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading pkl files...")
with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# Build trade DataFrame
rows = []
for w in results:
    yr = w.get("label", "?")
    for t in w.get("trades", []):
        d = vars(t).copy()
        d["year"] = yr
        rows.append(d)
df_all = pd.DataFrame(rows)
df_all["entry_time"] = pd.to_datetime(df_all["entry_time"])
df_all["date"] = df_all["entry_time"].dt.normalize()

# ── Extract Calm days ─────────────────────────────────────────────────────────
calm_mask = (df_all["strategy"] == "FADE") & (df_all["hmm_state"] == "Calm")
calm_days = sorted(df_all[calm_mask]["date"].unique())
calm_by_yr = {}
for d in calm_days:
    calm_by_yr.setdefault(str(d.year), []).append(d)

# ── Build SPY with VWAP ───────────────────────────────────────────────────────
spy = data_5min["SPY"].sort_index().copy()
spy["date"]    = spy.index.normalize()
spy["tp"]      = (spy["high"] + spy["low"] + spy["close"]) / 3
spy["tpv"]     = spy["tp"] * spy["volume"]
spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
spy["vwap"]    = spy["cum_tpv"] / spy["cum_vol"]

available_stocks = [tk for tk in data_5min
                    if tk not in ("SPY", "QQQ", "IWM")
                    and not tk.startswith("XL")
                    and tk != "GLD"]

YEAR_LABELS = ["2020", "2021", "2022"]

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Calm day count
# ═══════════════════════════════════════════════════════════════════════════════
div("1. CALM DAY COUNT")
print(f"\n  Total Calm days (all years): {len(calm_days)}")
for yr in YEAR_LABELS:
    n = len(calm_by_yr.get(yr, []))
    print(f"  {yr}: {n} Calm days")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. SPY 14:00-15:55 behavior
# ═══════════════════════════════════════════════════════════════════════════════
div("2. SPY MOVE  14:00 → 15:55  on Calm Days")

spy_calm_rows = []
for day in calm_days:
    day_spy = spy[spy["date"] == day].sort_index()
    if day_spy.empty:
        continue

    pre_1400 = day_spy[day_spy.index.time <= dtime(14, 0)]
    if pre_1400.empty:
        continue
    bar_1400  = pre_1400.iloc[-1]
    px_1400   = float(bar_1400["close"])
    vwap_1400 = float(bar_1400["vwap"])
    vwap_dev  = (px_1400 - vwap_1400) / vwap_1400

    pre_1555 = day_spy[day_spy.index.time <= dtime(15, 55)]
    if pre_1555.empty:
        continue
    px_1555  = float(pre_1555.iloc[-1]["close"])
    move_pct = (px_1555 - px_1400) / px_1400

    pm_bars = day_spy[(day_spy.index.time >= dtime(14, 0)) &
                      (day_spy.index.time <= dtime(15, 55))]
    if len(pm_bars) < 2:
        continue
    pm_range_pct = (pm_bars["high"].max() - pm_bars["low"].min()) / px_1400

    bars_1430 = day_spy[(day_spy.index.time >= dtime(14, 0)) &
                        (day_spy.index.time <= dtime(14, 30))]
    move_1430 = float((bars_1430.iloc[-1]["close"] - px_1400) / px_1400) \
                if len(bars_1430) >= 2 else np.nan

    eod_bars = day_spy[day_spy.index.time >= dtime(15, 30)]
    pm_vol   = pm_bars["volume"].sum()
    eod_vol  = eod_bars["volume"].sum()
    eod_vol_pct = eod_vol / pm_vol if pm_vol > 0 else np.nan

    if len(eod_bars) >= 2:
        px_1530  = float(eod_bars.iloc[0]["close"])
        eod_move = (float(eod_bars.iloc[-1]["close"]) - px_1530) / px_1530
    else:
        eod_move = np.nan

    spy_calm_rows.append(dict(
        date=day, year=str(day.year),
        px_1400=px_1400, vwap_1400=vwap_1400,
        vwap_dev=vwap_dev,
        move_pct=move_pct,
        pm_range_pct=pm_range_pct,
        move_1430=move_1430,
        eod_vol_pct=eod_vol_pct,
        eod_move=eod_move,
        direction="UP" if move_pct > 0 else "DOWN",
        above_vwap=(vwap_dev > 0),
    ))

spy_calm = pd.DataFrame(spy_calm_rows)
n_total  = len(spy_calm)

print(f"\n  Days with valid SPY data: {n_total}")

n_up   = (spy_calm["direction"] == "UP").sum()
n_down = (spy_calm["direction"] == "DOWN").sum()
print(f"\n  Directional bias (14:00 → 15:55):")
print(f"    UP  : {n_up:>3}d ({n_up/n_total*100:.0f}%)")
print(f"    DOWN: {n_down:>3}d ({n_down/n_total*100:.0f}%)")

print(f"\n  Move distribution:")
print(f"    Mean  : {spy_calm['move_pct'].mean()*100:+.3f}%")
print(f"    Median: {spy_calm['move_pct'].median()*100:+.3f}%")
print(f"    Std   : {spy_calm['move_pct'].std()*100:.3f}%")
print(f"    P25   : {spy_calm['move_pct'].quantile(0.25)*100:+.3f}%")
print(f"    P75   : {spy_calm['move_pct'].quantile(0.75)*100:+.3f}%")
print(f"    Min/Max: {spy_calm['move_pct'].min()*100:+.3f}% / {spy_calm['move_pct'].max()*100:+.3f}%")

print(f"\n  PM range (high-low 14:00-15:55 as % of price):")
print(f"    Mean  : {spy_calm['pm_range_pct'].mean()*100:.3f}%")
print(f"    Median: {spy_calm['pm_range_pct'].median()*100:.3f}%")
print(f"    P75   : {spy_calm['pm_range_pct'].quantile(0.75)*100:.3f}%")
print(f"    P90   : {spy_calm['pm_range_pct'].quantile(0.90)*100:.3f}%")

print(f"\n  Per year:")
for yr in YEAR_LABELS:
    s = spy_calm[spy_calm["year"] == yr]
    if len(s) == 0: continue
    n_up_y = (s["direction"] == "UP").sum()
    print(f"    {yr}: {len(s):>3}d  mean={s['move_pct'].mean()*100:+.3f}%  "
          f"UP={n_up_y/len(s)*100:.0f}%  range={s['pm_range_pct'].mean()*100:.3f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. VWAP deviation at 14:00
# ═══════════════════════════════════════════════════════════════════════════════
div("3. VWAP DEVIATION AT 14:00 → Afternoon direction?")

above = spy_calm[spy_calm["above_vwap"]]
below = spy_calm[~spy_calm["above_vwap"]]
print(f"\n  ABOVE VWAP at 14:00 ({len(above)}d):  "
      f"mean={above['move_pct'].mean()*100:+.3f}%  "
      f"UP={(above['direction']=='UP').mean()*100:.0f}%")
print(f"  BELOW VWAP at 14:00 ({len(below)}d):  "
      f"mean={below['move_pct'].mean()*100:+.3f}%  "
      f"UP={(below['direction']=='UP').mean()*100:.0f}%")

print(f"\n  VWAP dev buckets:")
print(f"  {'Category':<38} {'n':>4}  {'mean move':>10}  {'UP%':>5}  {'mean dev':>9}")
bins = [(-1,    -0.003, "strongly below <-0.3%"),
        (-0.003,-0.001, "below -0.3% to -0.1%"),
        (-0.001, 0.001, "near VWAP ±0.1%"),
        ( 0.001, 0.003, "above +0.1% to +0.3%"),
        ( 0.003, 1,     "strongly above >+0.3%")]
for lo, hi, lbl in bins:
    s = spy_calm[(spy_calm["vwap_dev"] >= lo) & (spy_calm["vwap_dev"] < hi)]
    if len(s) == 0: continue
    print(f"  {lbl:<38} {len(s):>4}  "
          f"{s['move_pct'].mean()*100:>+9.3f}%  "
          f"{(s['direction']=='UP').mean()*100:>4.0f}%  "
          f"{s['vwap_dev'].mean()*100:>+8.3f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Intraday structure: early move predicts later?
# ═══════════════════════════════════════════════════════════════════════════════
div("4. INTRADAY STRUCTURE: early (14:00-14:30) → late (14:30-15:55)?")

valid = spy_calm.dropna(subset=["move_1430"]).copy()
valid["move_late"] = valid["move_pct"] - valid["move_1430"]
corr = valid["move_1430"].corr(valid["move_late"])
print(f"\n  Correlation(early 14:00-14:30, late 14:30-15:55): {corr:+.3f}")
if   corr >  0.3: print("  → TRENDING: early move predicts continuation")
elif corr < -0.3: print("  → MEAN REVERTING: early move followed by reversal")
else:             print("  → NOISY: no reliable structure (|corr| < 0.3)")

early_up   = valid[valid["move_1430"] >  0.001]
early_down = valid[valid["move_1430"] < -0.001]
early_flat = valid[(valid["move_1430"] >= -0.001) & (valid["move_1430"] <= 0.001)]
print(f"\n  Early UP   (>+0.1%)  {len(early_up):>3}d → late: {early_up['move_late'].mean()*100:+.3f}%  "
      f"UP={(early_up['move_late']>0).mean()*100:.0f}%")
print(f"  Early FLAT (±0.1%)   {len(early_flat):>3}d → late: {early_flat['move_late'].mean()*100:+.3f}%  "
      f"UP={(early_flat['move_late']>0).mean()*100:.0f}%")
print(f"  Early DOWN (<-0.1%)  {len(early_down):>3}d → late: {early_down['move_late'].mean()*100:+.3f}%  "
      f"UP={(early_down['move_late']>0).mean()*100:.0f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. EOD behavior (15:30-15:55)
# ═══════════════════════════════════════════════════════════════════════════════
div("5. EOD BEHAVIOR (15:30-15:55)")

eod_valid = spy_calm.dropna(subset=["eod_move", "eod_vol_pct"]).copy()
print(f"\n  EOD volume (15:30-15:55) as % of PM (14:00-15:55):")
print(f"    Mean: {eod_valid['eod_vol_pct'].mean()*100:.1f}%  "
      f"Median: {eod_valid['eod_vol_pct'].median()*100:.1f}%")

print(f"\n  EOD price move (15:30 → 15:55):")
eod_up = (eod_valid["eod_move"] > 0).sum()
print(f"    Mean={eod_valid['eod_move'].mean()*100:+.3f}%  "
      f"Std={eod_valid['eod_move'].std()*100:.3f}%  "
      f"UP={eod_up}/{len(eod_valid)}={eod_up/len(eod_valid)*100:.0f}%")

eod_valid["pm_before_eod"] = eod_valid["move_pct"] - eod_valid["eod_move"]
pm_up_eod   = eod_valid[eod_valid["pm_before_eod"] >  0.001]
pm_down_eod = eod_valid[eod_valid["pm_before_eod"] < -0.001]
pm_eod_corr = eod_valid["pm_before_eod"].corr(eod_valid["eod_move"])
print(f"\n  PM (14:00-15:30) UP   ({len(pm_up_eod)}d) → EOD: "
      f"{pm_up_eod['eod_move'].mean()*100:+.3f}%  "
      f"UP={(pm_up_eod['eod_move']>0).mean()*100:.0f}%")
print(f"  PM (14:00-15:30) DOWN ({len(pm_down_eod)}d) → EOD: "
      f"{pm_down_eod['eod_move'].mean()*100:+.3f}%  "
      f"UP={(pm_down_eod['eod_move']>0).mean()*100:.0f}%")
print(f"  Correlation PM→EOD: {pm_eod_corr:+.3f}")
if   pm_eod_corr >  0.2: print("  → CONTINUATION: PM trend persists into close")
elif pm_eod_corr < -0.2: print("  → FADE: PM winners get faded into close")
else:                     print("  → NOISY: no reliable PM→EOD relationship")

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Individual stock VWAP MR on Calm afternoons
# ═══════════════════════════════════════════════════════════════════════════════
div("6. INDIVIDUAL STOCKS: VWAP deviation at 14:00 → MR by 15:55?")

print("\n  Computing per-ticker VWAP on Calm days...")
stock_rows = []

for ticker in available_stocks:
    if ticker not in data_5min:
        continue
    bars = data_5min[ticker].sort_index().copy()
    bars["date"]    = bars.index.normalize()
    bars["tp"]      = (bars["high"] + bars["low"] + bars["close"]) / 3
    bars["tpv"]     = bars["tp"] * bars["volume"]
    bars["cum_tpv"] = bars.groupby("date")["tpv"].cumsum()
    bars["cum_vol"] = bars.groupby("date")["volume"].cumsum()
    bars["vwap"]    = bars["cum_tpv"] / bars["cum_vol"]

    for day in calm_days:
        day_bars = bars[bars["date"] == day].sort_index()
        if len(day_bars) < 8:
            continue

        pre_1400 = day_bars[day_bars.index.time <= dtime(14, 0)]
        if pre_1400.empty:
            continue
        bar_1400  = pre_1400.iloc[-1]
        px_1400   = float(bar_1400["close"])
        vwap_1400 = float(bar_1400["vwap"])
        if vwap_1400 <= 0 or px_1400 <= 0:
            continue
        vwap_dev = (px_1400 - vwap_1400) / vwap_1400

        post_1400 = day_bars[day_bars.index.time > dtime(14, 0)]
        if post_1400.empty:
            continue
        pre_1555 = post_1400[post_1400.index.time <= dtime(15, 55)]
        if pre_1555.empty:
            continue
        px_1555  = float(pre_1555.iloc[-1]["close"])
        move_pct = (px_1555 - px_1400) / px_1400

        dist_before = abs(px_1400 - vwap_1400)
        dist_after  = abs(px_1555 - vwap_1400)
        mr_success  = dist_after < dist_before

        stock_rows.append(dict(
            ticker=ticker, date=day, year=str(day.year),
            vwap_dev=vwap_dev,
            move_pct=move_pct,
            mr_success=mr_success,
        ))

stock_df = pd.DataFrame(stock_rows)
print(f"  {len(stock_df)} stock-day obs across {stock_df['ticker'].nunique()} tickers")

mr_rate = stock_df["mr_success"].mean() * 100
print(f"\n  Overall MR rate (move toward VWAP by 15:55): {mr_rate:.1f}%")

print(f"\n  By VWAP deviation bucket:")
print(f"  {'Category':<40} {'n':>5}  {'MR rate':>8}  {'mean move':>10}  {'UP%':>5}")
bins_stk = [
    (-1,    -0.015, "strongly below VWAP  < -1.5%"),
    (-0.015,-0.005, "below VWAP  -1.5% to -0.5%"),
    (-0.005, 0.005, "near VWAP  ±0.5%"),
    ( 0.005, 0.015, "above VWAP  +0.5% to +1.5%"),
    ( 0.015, 1,     "strongly above VWAP  > +1.5%"),
]
for lo, hi, lbl in bins_stk:
    s = stock_df[(stock_df["vwap_dev"] >= lo) & (stock_df["vwap_dev"] < hi)]
    if len(s) < 5: continue
    print(f"  {lbl:<40} {len(s):>5}  "
          f"{s['mr_success'].mean()*100:>7.1f}%  "
          f"{s['move_pct'].mean()*100:>+9.3f}%  "
          f"{(s['move_pct']>0).mean()*100:>4.0f}%")

far_above = stock_df[stock_df["vwap_dev"] >  0.01]
far_below = stock_df[stock_df["vwap_dev"] < -0.01]
print(f"\n  Far ABOVE VWAP (>+1%): {len(far_above):>4}d  "
      f"MR={far_above['mr_success'].mean()*100:.0f}%  "
      f"mean move={far_above['move_pct'].mean()*100:+.3f}%")
print(f"  Far BELOW VWAP (<-1%): {len(far_below):>4}d  "
      f"MR={far_below['mr_success'].mean()*100:.0f}%  "
      f"mean move={far_below['move_pct'].mean()*100:+.3f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Summary
# ═══════════════════════════════════════════════════════════════════════════════
div("7. SUMMARY")
print(f"""
  Quick numbers:
    Calm days total          : {len(calm_days)}
    SPY PM UP rate           : {(spy_calm['direction']=='UP').mean()*100:.0f}%
    SPY mean PM move         : {spy_calm['move_pct'].mean()*100:+.3f}%
    SPY mean PM range        : {spy_calm['pm_range_pct'].mean()*100:.3f}%
    Early→Late corr (trend?) : {corr:+.3f}
    PM→EOD corr (fade?)      : {pm_eod_corr:+.3f}
    Stock MR rate at 14:00   : {mr_rate:.1f}%

  Interpretation:
    Early→Late corr >+0.3   → trending afternoon → low-vol trend follow
    Early→Late corr <-0.3   → mean reverting     → VWAP MR extension
    PM→EOD corr     <-0.2   → EOD fade edge       → fade 15:30 positions
    Stock MR rate   >60%    → stock-level MR edge → stock VWAP MR
    SPY UP rate     >60%    → directional bias     → LONG-only afternoon trend
""")
