"""
vmr_root_cause.py
-----------------
Tìm root cause của STOP:TARGET = 2:1 trong VWAP_MR.
Ba hypothesis:
  H1. Signal quality  — BB touch không đủ selective
  H2. Stop too wide   — 1.5×ATR quá rộng, bị hit trước khi target
  H3. Universe wrong  — một số tickers hệ thống hóa là losers

Với mỗi trade, load 5-min bars trong suốt thời gian giữ để tính:
  MAE = Max Adverse Excursion (giá đi ngược tối đa trước khi exit)
  MFE = Max Favorable Excursion (giá đi thuận tối đa trước khi exit)

Usage:
    cd d:\\raits\\raits
    python raits/scripts/vmr_root_cause.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

print("Loading pkl files...")
with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for window in results:
    yr = window.get("label", "?")
    for t in window.get("trades", []):
        d = vars(t).copy() if hasattr(t, "__dict__") else {}
        d["year"] = yr
        rows.append(d)

all_df = pd.DataFrame(rows)
vmr = all_df[all_df["strategy"] == "VWAP_MR"].copy()
vmr["entry_time"] = pd.to_datetime(vmr["entry_time"])
vmr["exit_time"]  = pd.to_datetime(vmr["exit_time"])
vmr["win"]        = vmr["net_pnl"] > 0
vmr["stop_dist"]  = (vmr["entry_price"] - vmr["stop"]).abs()
vmr["atr"]        = vmr["stop_dist"] / 1.5

non_vmr_pnl = all_df[all_df["strategy"] != "VWAP_MR"]["net_pnl"].sum()

# ── MAE / MFE computation ────────────────────────────────────────────────────
print("Computing MAE/MFE for each trade (loading intraday bars)...")

FIVE_MIN = pd.Timedelta("5min")

mae_rows = []
for _, tr in vmr.iterrows():
    ticker    = tr["ticker"]
    entry_ts  = tr["entry_time"]
    exit_ts   = tr["exit_time"]
    direction = tr["direction"]
    entry_px  = tr["entry_price"]
    atr       = tr["atr"]
    stop_dist = tr["stop_dist"]

    if ticker not in data_5min or atr <= 0:
        mae_rows.append({})
        continue

    bars = data_5min[ticker].sort_index()
    # bars during the trade (entry bar open → exit bar close)
    trade_bars = bars[(bars.index >= entry_ts) & (bars.index <= exit_ts)]
    if len(trade_bars) == 0:
        mae_rows.append({})
        continue

    if direction == "LONG":
        # Adverse = price going DOWN from entry
        mae_abs = entry_px - trade_bars["low"].min()    # positive = how far down
        mfe_abs = trade_bars["high"].max() - entry_px   # positive = how far up
    else:  # SHORT
        # Adverse = price going UP from entry
        mae_abs = trade_bars["high"].max() - entry_px   # positive = how far up
        mfe_abs = entry_px - trade_bars["low"].min()    # positive = how far down

    mae_atr = mae_abs / atr
    mfe_atr = mfe_abs / atr

    # Touch bar features (bar just before entry)
    touch_ts = entry_ts - FIVE_MIN
    cands    = bars.index[bars.index <= touch_ts]
    touch_bar_found = len(cands) > 0

    if touch_bar_found:
        tb = bars.loc[cands[-1]]
        bar_range = tb["high"] - tb["low"]
        if direction == "SHORT":
            wick_outside = max(0.0, tb["high"] - entry_px)
            close_back   = max(0.0, entry_px - tb["close"])
        else:
            wick_outside = max(0.0, entry_px - tb["low"])
            close_back   = max(0.0, tb["close"] - entry_px)
        rejection   = close_back / bar_range if bar_range > 0 else 0
        wick_ratio  = wick_outside / atr     if atr     > 0 else 0

        day_bars = bars[bars.index.normalize() == touch_ts.normalize()]
        day_avg_vol  = day_bars["volume"].mean()
        vol_ratio    = tb["volume"] / day_avg_vol if day_avg_vol > 0 else 1.0
    else:
        rejection = wick_ratio = vol_ratio = np.nan

    # Entry position: how far inside the band at entry (in ATR units)
    # Positive = entry is inside band (good for MR)
    reward_dist = (entry_px - tr["target"])
    if direction == "SHORT":
        entry_to_vwap_atr = reward_dist / atr   # entry above VWAP = positive
    else:
        entry_to_vwap_atr = -reward_dist / atr  # entry below VWAP, target above

    mae_rows.append({
        "mae_abs":          round(mae_abs, 4),
        "mfe_abs":          round(mfe_abs, 4),
        "mae_atr":          round(mae_atr, 3),
        "mfe_atr":          round(mfe_atr, 3),
        "rejection":        round(rejection, 3) if not np.isnan(rejection) else np.nan,
        "wick_ratio":       round(wick_ratio, 3) if not np.isnan(wick_ratio) else np.nan,
        "vol_ratio":        round(vol_ratio, 3)  if not np.isnan(vol_ratio)  else np.nan,
        "entry_to_vwap_atr": round(entry_to_vwap_atr, 3),
    })

feat = pd.DataFrame(mae_rows)
vmr  = pd.concat([vmr.reset_index(drop=True), feat], axis=1)
vmr_f = vmr[feat["mae_atr"].notna()].copy()

print(f"  {len(vmr_f)} / {len(vmr)} trades with full MAE data\n")

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

def show(label, df, indent="  "):
    n = len(df)
    if n == 0: return
    pnl = df["net_pnl"].sum()
    wr  = df["win"].mean() * 100
    avg = df["net_pnl"].mean()
    print(f"{indent}{label:<45} {n:>4}t  ${pnl:>+8,.0f}  WR={wr:>3.0f}%  avg=${avg:>+5.1f}")

print(f"{'='*72}")
print(f"  VMR ROOT CAUSE  —  {len(vmr_f)} trades")
print(f"{'='*72}")

# ═══════════════════════════════════════════════════════════════════════════════
# H2. STOP WIDTH — MAE analysis
# (chạy H2 trước vì đây là diagnostic purity nhất)
# ═══════════════════════════════════════════════════════════════════════════════
div("H2. STOP WIDTH — Max Adverse Excursion by exit reason")

print(f"\n  MAE = how far price moved against the trade (in ATR units, stop = 1.5×ATR)")
print(f"\n  {'Exit reason':<20}  {'n':>4}  {'MAE mean':>10}  {'MAE p50':>9}  {'MAE p90':>9}  {'MFE mean':>10}")
for reason in ["STOP_HIT", "TARGET_HIT", "TIME_STOP"]:
    if "exit_reason" not in vmr_f.columns:
        break
    s = vmr_f[vmr_f["exit_reason"] == reason]
    if len(s) == 0: continue
    print(f"  {reason:<20}  {len(s):>4}  "
          f"{s['mae_atr'].mean():>9.2f}×  "
          f"{s['mae_atr'].median():>8.2f}×  "
          f"{s['mae_atr'].quantile(0.9):>8.2f}×  "
          f"{s['mfe_atr'].mean():>9.2f}×")

print(f"\n  ── What % of TARGET_HIT & TIME_STOP trades saw MAE > 1.0×ATR? ──")
winners_ts = vmr_f[vmr_f["exit_reason"].isin(["TARGET_HIT", "TIME_STOP"])]
if len(winners_ts):
    pct_large_mae = (winners_ts["mae_atr"] > 1.0).mean() * 100
    pct_very_large = (winners_ts["mae_atr"] > 1.5).mean() * 100
    print(f"  MAE > 1.0×ATR: {pct_large_mae:.0f}% of TARGET_HIT+TIME_STOP trades")
    print(f"  MAE > 1.5×ATR: {pct_very_large:.0f}% of TARGET_HIT+TIME_STOP trades")
    print(f"  → If stop were 1.0×ATR, would kill {pct_large_mae:.0f}% of eventual winners")
    print(f"  → If stop were 1.5×ATR (current), kills {pct_very_large:.0f}% of winners")

print(f"\n  ── Stop width simulation (retroactive) ──")
print(f"  {'Stop width':<18}  {'STOP_HIT avoided':>18}  {'Winners killed':>16}  {'Net change':>12}")
for stop_mult in [0.8, 1.0, 1.2, 1.5, 2.0, 2.5]:
    # How many current STOP_HITs would have been avoided with this stop?
    current_stops = vmr_f[vmr_f["exit_reason"] == "STOP_HIT"]
    # A tighter stop: STOP_HIT avoided = those where MAE < current stop_dist (wouldn't hit tighter stop)
    # Actually: with mult M, stop = M×ATR
    # A current STOP_HIT would be avoided if MAE < M×ATR (price never hit M×ATR stop)
    if stop_mult < 1.5:
        # Tighter: some current winners (TARGET_HIT, TIME_STOP) get stopped → kills winners
        avoided   = (current_stops["mae_atr"] > stop_mult).sum()   # these WON'T be stopped (tighter but price went further)
        # Actually let me rethink:
        # With stop at M×ATR:
        # - Current STOP_HIT trades: if their MAE ≤ M×ATR → they were NOT stopped under new stop...
        # Wait, STOP_HIT means price hit 1.5×ATR. If M > 1.5, no STOP_HIT avoidance. If M < 1.5:
        # trades where MAE exactly hit at ~1.5×ATR — with tighter stop M, they'd still be hit
        # Current STOP_HIT: MAE ≥ 1.5×ATR (that's why they hit the stop)
        # With stop M×ATR (M<1.5): they'd ALSO be hit (MAE ≥ 1.5 > M), just earlier
        # So tighter stop = hits same number of STOP_HITs but faster, AND kills some winners
        stopped_early = (winners_ts["mae_atr"] >= stop_mult).sum()
        net_lbl = f"-{stopped_early} winners"
        stopped_str = "same STOP_HITs"
    else:
        # Wider stop: some current STOP_HITs survive and reach target/time_stop
        # A trade that hit 1.5×ATR MAE: would wider stop let it recover?
        # Need MFE: if the trade's MFE (after hitting 1.5×ATR) eventually > 0, then with wider stop it might recover
        # Approximation: look at net_pnl of STOP_HIT trades — if they were TIME_STOPs instead, would they be wins?
        # This is hard to know without re-simulating. Use a rough proxy:
        # "stop_hit trades that eventually reversed" — we don't have this without resim.
        # Skip this for now and just show tighter stop kills.
        stopped_early = 0
        stopped_str = "wider stop"
        net_lbl = "?"

    if stop_mult <= 1.5:
        print(f"  {stop_mult:.1f}×ATR             "
              f"  (stops same {len(current_stops)} losers)     "
              f"  kills {stopped_early:>3} winners     "
              f"  {net_lbl}")

# Simpler version: just show MAE distribution for TARGET_HIT and TIME_STOP
print(f"\n  ── MAE distribution for TARGET_HIT trades (what they survive) ──")
target_hits = vmr_f[vmr_f["exit_reason"] == "TARGET_HIT"]
if len(target_hits):
    for lo, hi, lbl in [(0, 0.3, "< 0.3×ATR"),
                        (0.3, 0.6, "0.3–0.6×ATR"),
                        (0.6, 1.0, "0.6–1.0×ATR"),
                        (1.0, 1.5, "1.0–1.5×ATR"),
                        (1.5, 99,  "> 1.5×ATR (impossible with 1.5x stop)")]:
        s = target_hits[(target_hits["mae_atr"] >= lo) & (target_hits["mae_atr"] < hi)]
        if len(s):
            print(f"    MAE {lbl:<25}  {len(s):>3}t = {len(s)/len(target_hits)*100:.0f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# H1. SIGNAL QUALITY — wick, rejection, volume
# ═══════════════════════════════════════════════════════════════════════════════
div("H1. SIGNAL QUALITY — touch bar features")

print(f"\n  WINNERS vs LOSERS — mean feature comparison:")
print(f"  {'Feature':<20}  {'winners':>10}  {'losers':>10}  {'delta':>10}  note")
winners = vmr_f[vmr_f["win"] == True]
losers  = vmr_f[vmr_f["win"] == False]
for feat, note in [
    ("wick_ratio",  "higher = wick went further past band"),
    ("rejection",   "higher = close strongly back inside"),
    ("vol_ratio",   "lower = settling (good); higher = momentum (bad)"),
    ("mae_atr",     "lower MAE for winners = entered in better spot"),
    ("mfe_atr",     "higher MFE for winners = trade worked faster"),
    ("entry_to_vwap_atr", "how far entry is from VWAP in ATR")
]:
    if feat not in vmr_f.columns:
        continue
    wv = winners[feat].mean()
    lv = losers[feat].mean()
    print(f"  {feat:<20}  {wv:>10.3f}  {lv:>10.3f}  {wv-lv:>+10.3f}  {note}")

div("H1a. WICK RATIO (how far price poked past band / ATR)")
print(f"\n  {'Bucket':<30}  {'n':>4}  {'WR':>5}  {'P&L':>9}  {'avg MAE':>9}")
for lo, hi, lbl in [(0, 0.1, "tiny  <0.1×ATR"),
                    (0.1, 0.3, "small 0.1–0.3×ATR"),
                    (0.3, 0.6, "med   0.3–0.6×ATR"),
                    (0.6, 99,  "large >0.6×ATR")]:
    s = vmr_f[(vmr_f["wick_ratio"] >= lo) & (vmr_f["wick_ratio"] < hi)]
    if len(s) == 0: continue
    print(f"  {lbl:<30}  {len(s):>4}  {s['win'].mean()*100:>4.0f}%  "
          f"{s['net_pnl'].sum():>+9,.0f}  {s['mae_atr'].mean():>8.2f}×")

div("H1b. REJECTION RATIO (how far close snapped back inside band)")
print(f"\n  {'Bucket':<30}  {'n':>4}  {'WR':>5}  {'P&L':>9}  {'avg MAE':>9}")
for lo, hi, lbl in [(0, 0.3,  "weak   <30%"),
                    (0.3, 0.6, "med  30–60%"),
                    (0.6, 0.8, "good 60–80%"),
                    (0.8, 1.0, "strong >80%")]:
    s = vmr_f[(vmr_f["rejection"] >= lo) & (vmr_f["rejection"] < hi)]
    if len(s) == 0: continue
    print(f"  {lbl:<30}  {len(s):>4}  {s['win'].mean()*100:>4.0f}%  "
          f"{s['net_pnl'].sum():>+9,.0f}  {s['mae_atr'].mean():>8.2f}×")

div("H1c. VOLUME AT TOUCH BAR")
print(f"\n  {'Bucket':<30}  {'n':>4}  {'WR':>5}  {'P&L':>9}  {'avg MAE':>9}")
for lo, hi, lbl in [(0, 0.5,  "very low  <0.5×"),
                    (0.5, 1.0, "below avg 0.5–1.0×"),
                    (1.0, 2.0, "above avg 1.0–2.0×"),
                    (2.0, 99,  "spike     >2.0×")]:
    s = vmr_f[(vmr_f["vol_ratio"] >= lo) & (vmr_f["vol_ratio"] < hi)]
    if len(s) == 0: continue
    print(f"  {lbl:<30}  {len(s):>4}  {s['win'].mean()*100:>4.0f}%  "
          f"{s['net_pnl'].sum():>+9,.0f}  {s['mae_atr'].mean():>8.2f}×")

div("H1d. ENTRY DISTANCE FROM VWAP (reward / ATR)")
print(f"\n  How far entry is from target (VWAP) in ATR units at time of entry.")
print(f"  Larger = more room to VWAP = better potential reward.\n")
print(f"  {'Bucket':<30}  {'n':>4}  {'WR':>5}  {'P&L':>9}  {'avg MAE':>9}")
for lo, hi, lbl in [(0, 1.0,  "close to VWAP  <1×ATR"),
                    (1.0, 1.5, "1.0–1.5×ATR"),
                    (1.5, 2.0, "1.5–2.0×ATR"),
                    (2.0, 3.0, "2.0–3.0×ATR"),
                    (3.0, 99,  "far from VWAP >3×ATR")]:
    s = vmr_f[(vmr_f["entry_to_vwap_atr"] >= lo) & (vmr_f["entry_to_vwap_atr"] < hi)]
    if len(s) == 0: continue
    print(f"  {lbl:<30}  {len(s):>4}  {s['win'].mean()*100:>4.0f}%  "
          f"{s['net_pnl'].sum():>+9,.0f}  {s['mae_atr'].mean():>8.2f}×")

div("H1e. COMBINED SIGNAL: wick × rejection × volume")
print(f"\n  {'Filter':<50}  {'n':>4}  {'WR':>5}  {'P&L':>9}")
combos = {
    "Baseline (all)":                            vmr_f,
    "wick ≥ 0.3×ATR":                           vmr_f[vmr_f["wick_ratio"] >= 0.3],
    "rejection ≥ 60%":                          vmr_f[vmr_f["rejection"] >= 0.6],
    "vol < 1.0×avg":                            vmr_f[vmr_f["vol_ratio"] < 1.0],
    "wick≥0.3 AND rejection≥60%":               vmr_f[(vmr_f["wick_ratio"] >= 0.3) & (vmr_f["rejection"] >= 0.6)],
    "wick≥0.3 AND vol<1.0":                     vmr_f[(vmr_f["wick_ratio"] >= 0.3) & (vmr_f["vol_ratio"] < 1.0)],
    "rejection≥60% AND vol<1.0":                vmr_f[(vmr_f["rejection"] >= 0.6) & (vmr_f["vol_ratio"] < 1.0)],
    "wick≥0.3 AND rejection≥60% AND vol<1.0":   vmr_f[(vmr_f["wick_ratio"] >= 0.3) & (vmr_f["rejection"] >= 0.6) & (vmr_f["vol_ratio"] < 1.0)],
}
for name, s in combos.items():
    if len(s) == 0: continue
    sys_pnl = s["net_pnl"].sum() + non_vmr_pnl
    print(f"  {name:<50}  {len(s):>4}  {s['win'].mean()*100:>4.0f}%  "
          f"{s['net_pnl'].sum():>+9,.0f}  sys=${sys_pnl:>+8,.0f}")

# ═══════════════════════════════════════════════════════════════════════════════
# H3. UNIVERSE — ticker-level analysis
# ═══════════════════════════════════════════════════════════════════════════════
div("H3. UNIVERSE — ticker performance breakdown")

tk_stats = vmr_f.groupby("ticker").apply(lambda g: pd.Series({
    "n":       len(g),
    "pnl":     g["net_pnl"].sum(),
    "wr":      g["win"].mean() * 100,
    "avg":     g["net_pnl"].mean(),
    "mae_avg": g["mae_atr"].mean(),
    "mfe_avg": g["mfe_atr"].mean(),
    "stop_pct": (g.get("exit_reason", pd.Series()) == "STOP_HIT").mean() * 100 if "exit_reason" in g.columns else np.nan,
})).sort_values("pnl")

print(f"\n  {'Ticker':<8} {'n':>4}  {'P&L':>8}  {'WR':>5}  {'avg':>6}  {'MAE':>6}  {'MFE':>6}  {'stop%':>7}")
for ticker, r in tk_stats.iterrows():
    print(f"  {ticker:<8} {int(r['n']):>4}  {r['pnl']:>+8,.0f}  "
          f"{r['wr']:>4.0f}%  {r['avg']:>+6.1f}  "
          f"{r['mae_avg']:>5.2f}×  {r['mfe_avg']:>5.2f}×  "
          f"{r['stop_pct']:>6.0f}%")

print(f"\n  ── Systematic losers (P&L < -$20, n ≥ 10): ──")
losers_tk = tk_stats[(tk_stats["pnl"] < -20) & (tk_stats["n"] >= 10)]
for ticker, r in losers_tk.iterrows():
    print(f"    {ticker}: {int(r['n'])}t  ${r['pnl']:+,.0f}  WR={r['wr']:.0f}%  "
          f"stop%={r['stop_pct']:.0f}%  MAE={r['mae_avg']:.2f}×ATR")

print(f"\n  ── Consistent winners (P&L > $20, n ≥ 5): ──")
winners_tk = tk_stats[(tk_stats["pnl"] > 20) & (tk_stats["n"] >= 5)]
for ticker, r in winners_tk.sort_values("pnl", ascending=False).iterrows():
    print(f"    {ticker}: {int(r['n'])}t  ${r['pnl']:+,.0f}  WR={r['wr']:.0f}%  "
          f"stop%={r['stop_pct']:.0f}%  MAE={r['mae_avg']:.2f}×ATR")

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
div("SUMMARY — which hypothesis is most supported?")
print(f"""
  Đọc kết quả theo nguyên tắc:

  H2 (stop too wide):
    → Nếu TARGET_HIT trades có MAE < 0.5×ATR thường xuyên
      → Stop có thể tighter → ít noise hit
    → Nếu TARGET_HIT trades thường xuyên có MAE > 1.0×ATR
      → Stop 1.5×ATR là cần thiết, không phải vấn đề

  H1 (signal quality):
    → Nếu winner/loser có difference rõ ở wick_ratio hay rejection
      → Có thể filter signal bằng các features này
    → Nếu winner/loser features gần giống nhau
      → Signal quality không phải vấn đề, là execution hay universe

  H3 (universe):
    → Nếu 2-3 tickers chiếm phần lớn losses với stop_pct cao
      → Loại tickers đó khỏi VWAP_MR universe
    → Nếu losses phân tán đều qua nhiều tickers
      → Universe không phải vấn đề
""")
