"""
vmr_filter_sim.py
-----------------
Test 3 filters cụ thể để cải thiện VWAP_MR (từ kết quả vmr_improve_sim.py):

  Filter 1: R:R CAP — bỏ trades với actual R:R > 2.5x
            Root cause: stocks xa VWAP quá thường là momentum moves, không revert
            Expected removal: 74 trades (-$71)

  Filter 2: NO SHORT khi SPY bullish + after 12:30
            Root cause: SPY afternoon trend overrides MR signal
            Expected removal: ~75 trades (-$88)

  Filter 3: NO LONG 12:00-13:00
            Phát hiện từ Section E: WR=28% trong window này
            Expected removal: 36 trades (-$49)

Mục tiêu: tìm combo đơn giản nhất mà:
  - All-3-years positive
  - ≥ 80 trades còn lại (đủ statistical significance)
  - VMR P&L từ -$128 → positive
  - System P&L > $9,048 (current)

Usage:
    cd d:\\raits\\raits
    python raits/scripts/vmr_filter_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

# ── Load ──────────────────────────────────────────────────────────────────────
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
vmr["win"]        = vmr["net_pnl"] > 0
vmr["hour"]       = vmr["entry_time"].dt.hour
vmr["minute"]     = vmr["entry_time"].dt.minute

vmr["stop_dist"]   = (vmr["entry_price"] - vmr["stop"]).abs()
vmr["reward_dist"] = (vmr["entry_price"] - vmr["target"]).abs()
vmr["actual_rr"]   = vmr["reward_dist"] / vmr["stop_dist"].replace(0, np.nan)

non_vmr_pnl = all_df[all_df["strategy"] != "VWAP_MR"]["net_pnl"].sum()

# ── SPY VWAP at entry ─────────────────────────────────────────────────────────
print("Computing SPY VWAP at entry time...")
spy = data_5min["SPY"].sort_index().copy()
spy["date"]    = spy.index.normalize()
spy["tp"]      = (spy["high"] + spy["low"] + spy["close"]) / 3
spy["tpv"]     = spy["tp"] * spy["volume"]
spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
spy["vwap"]    = spy["cum_tpv"] / spy["cum_vol"]
spy_series     = spy[["close", "vwap"]]

def get_spy_above(ts):
    idx = spy_series.index[spy_series.index <= ts]
    if len(idx) == 0:
        return None
    r = spy_series.loc[idx[-1]]
    return float(r["close"]) > float(r["vwap"])

spy_states = [get_spy_above(ts) for ts in vmr["entry_time"]]
vmr["spy_above_vwap"] = spy_states
# Time: minutes since market open (9:30)
vmr["mins_since_open"] = (vmr["hour"] - 9) * 60 + vmr["minute"] - 30

# ── Helpers ───────────────────────────────────────────────────────────────────
def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

def show(label, df, indent="  "):
    n = len(df)
    if n == 0:
        print(f"{indent}{label:<55} {'—':>5}")
        return
    pnl = df["net_pnl"].sum()
    wr  = df["win"].mean() * 100
    avg = df["net_pnl"].mean()
    sys = pnl + non_vmr_pnl
    yr_ok = all(
        df[df["year"] == yr]["net_pnl"].sum() >= 0
        for yr in ["2020", "2021", "2022"]
        if len(df[df["year"] == yr]) > 0
    )
    flag = " ✓ALL-YRS" if yr_ok and n >= 60 else (" ⚠2020-" if df[df["year"]=="2020"]["net_pnl"].sum() < 0 and n >= 60 else "")
    print(f"{indent}{label:<55} {n:>5}t  ${pnl:>+8,.0f}  WR={wr:>3.0f}%  sys=${sys:>+8,.0f}{flag}")

def yr_breakdown(df, indent="    "):
    for yr in ["2020", "2021", "2022"]:
        s = df[df["year"] == yr]
        if len(s) > 0:
            print(f"{indent}{yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+7,.0f}  WR={s['win'].mean()*100:.0f}%")
        else:
            print(f"{indent}{yr}:   0t")

print(f"\n{'='*72}")
print(f"  VMR FILTER SIM  —  baseline: {len(vmr)}t  ${vmr['net_pnl'].sum():+,.0f}  WR={vmr['win'].mean()*100:.0f}%")
print(f"  Non-VMR system baseline: ${non_vmr_pnl:+,.0f}")
print(f"{'='*72}")

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Three individual filters — what each removes
# ═══════════════════════════════════════════════════════════════════════════════
div("1. THREE FILTERS — what each removes and keeps")

# Filter 1: R:R cap 2.5x
mask_rr_ok  = vmr["actual_rr"].between(0, 2.5)   # keep ≤ 2.5x
mask_rr_bad = ~mask_rr_ok & vmr["actual_rr"].notna()

# Filter 2: NO SHORT when SPY above VWAP after 12:30
# (12:30 = 180 mins since open)
mask_short_spy_ok = ~(
    (vmr["direction"] == "SHORT") &
    (vmr["spy_above_vwap"] == True) &
    (vmr["mins_since_open"] >= 180)   # 12:30+
)

# Filter 3: NO LONG 12:00–13:00
mask_no_long_noon = ~(
    (vmr["direction"] == "LONG") &
    (vmr["hour"] == 12)
)

print(f"\n  REMOVED by each filter:")
removed_rr   = vmr[mask_rr_bad]
removed_short = vmr[~mask_short_spy_ok]
removed_long  = vmr[~mask_no_long_noon]

show("  Removed by Filter1 (R:R > 2.5x)", removed_rr)
show("  Removed by Filter2 (SHORT SPY↑ after 12:30)", removed_short)
show("  Removed by Filter3 (LONG 12:00-13:00)", removed_long)

# Overlap between filter 1 and 2
removed_12 = vmr[mask_rr_bad | ~mask_short_spy_ok]
removed_123 = vmr[mask_rr_bad | ~mask_short_spy_ok | ~mask_no_long_noon]
print(f"\n  Overlap — removed by F1 OR F2: {len(removed_12)}t")
print(f"  Overlap — removed by F1 OR F2 OR F3: {len(removed_123)}t")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. What each filter KEEPS
# ═══════════════════════════════════════════════════════════════════════════════
div("2. WHAT EACH FILTER KEEPS")
print(f"\n  {'Scenario':<55} {'n':>5}  {'VMR P&L':>9}  {'WR':>5}  {'sys':>9}")
print(f"  {'─'*85}")

show("Baseline (no filter)", vmr)
show("Filter 1 only: R:R ≤ 2.5x", vmr[mask_rr_ok])
show("Filter 2 only: no SHORT SPY↑ after 12:30", vmr[mask_short_spy_ok])
show("Filter 3 only: no LONG 12:00-13:00", vmr[mask_no_long_noon])

# ═══════════════════════════════════════════════════════════════════════════════
# 3. Combo scenarios
# ═══════════════════════════════════════════════════════════════════════════════
div("3. COMBO SCENARIOS")
print(f"\n  {'Scenario':<55} {'n':>5}  {'VMR P&L':>9}  {'WR':>5}  {'sys':>9}")
print(f"  {'─'*85}")

combos = {
    "F1+F2 (R:R≤2.5 + no SHORT SPY↑ 12:30+)":        mask_rr_ok & mask_short_spy_ok,
    "F1+F3 (R:R≤2.5 + no LONG noon)":                 mask_rr_ok & mask_no_long_noon,
    "F2+F3 (no SHORT SPY↑ 12:30+ + no LONG noon)":    mask_short_spy_ok & mask_no_long_noon,
    "F1+F2+F3 (all three)":                            mask_rr_ok & mask_short_spy_ok & mask_no_long_noon,
}
for name, mask in combos.items():
    show(name, vmr[mask])

# ═══════════════════════════════════════════════════════════════════════════════
# 4. Fine-tune Filter 2: try different SPY gate time thresholds
# ═══════════════════════════════════════════════════════════════════════════════
div("4. FINE-TUNE F2: what time to start blocking SHORT SPY↑?")
print(f"\n  {'Start blocking at':<40} {'n':>5}  {'VMR P&L':>9}  {'WR':>5}  {'removed':>8}")
for start_min_offset in [90, 120, 150, 180, 210, 240]:
    # start_min_offset: minutes since 9:30
    hh = 9 + (30 + start_min_offset) // 60
    mm = (30 + start_min_offset) % 60
    time_label = f"{hh:02d}:{mm:02d}"
    mask = ~(
        (vmr["direction"] == "SHORT") &
        (vmr["spy_above_vwap"] == True) &
        (vmr["mins_since_open"] >= start_min_offset)
    )
    kept     = vmr[mask]
    removed  = vmr[~mask]
    pnl      = kept["net_pnl"].sum()
    wr       = kept["win"].mean() * 100
    print(f"  Block after {time_label} ({start_min_offset}min)      {len(kept):>5}  {pnl:>+9,.0f}  {wr:>4.0f}%  {len(removed):>8}t")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. Fine-tune Filter 1: what R:R cap is optimal?
# ═══════════════════════════════════════════════════════════════════════════════
div("5. FINE-TUNE F1: R:R cap threshold")
print(f"\n  {'R:R cap':<15} {'n':>5}  {'VMR P&L':>9}  {'WR':>5}  {'removed':>8}")
for cap in [1.8, 2.0, 2.2, 2.5, 3.0, 3.5, 99]:
    mask  = vmr["actual_rr"].between(0, cap)
    kept  = vmr[mask]
    rem   = vmr[~mask & vmr["actual_rr"].notna()]
    pnl   = kept["net_pnl"].sum()
    wr    = kept["win"].mean() * 100
    lbl   = f"R:R ≤ {cap:.1f}" if cap < 99 else "no cap"
    print(f"  {lbl:<15} {len(kept):>5}  {pnl:>+9,.0f}  {wr:>4.0f}%  {len(rem):>8}t")

# ═══════════════════════════════════════════════════════════════════════════════
# 6. Year breakdown for best combos
# ═══════════════════════════════════════════════════════════════════════════════
div("6. YEAR BREAKDOWN for key scenarios")

key = {
    "Baseline":               vmr,
    "F2 only (no SHORT SPY↑ 12:30+)": vmr[mask_short_spy_ok],
    "F1+F2":                  vmr[mask_rr_ok & mask_short_spy_ok],
    "F2+F3":                  vmr[mask_short_spy_ok & mask_no_long_noon],
    "F1+F2+F3":               vmr[mask_rr_ok & mask_short_spy_ok & mask_no_long_noon],
}

for name, df in key.items():
    n   = len(df)
    pnl = df["net_pnl"].sum()
    wr  = df["win"].mean() * 100
    print(f"\n  {name} (n={n}, VMR=${pnl:+,.0f}, WR={wr:.0f}%, sys=${pnl+non_vmr_pnl:+,.0f}):")
    yr_breakdown(df)

# ═══════════════════════════════════════════════════════════════════════════════
# 7. Remaining STOP_HIT analysis after best filter
# ═══════════════════════════════════════════════════════════════════════════════
div("7. STOP_HIT analysis: what's left after F1+F2?")

kept_f12 = vmr[mask_rr_ok & mask_short_spy_ok]
if "exit_reason" in kept_f12.columns:
    print(f"\n  After F1+F2 filter ({len(kept_f12)} trades):")
    for reason in sorted(kept_f12["exit_reason"].dropna().unique()):
        s = kept_f12[kept_f12["exit_reason"] == reason]
        show(f"  {reason}", s)

    # What are the remaining STOP_HITs?
    stop_kept = kept_f12[kept_f12["exit_reason"] == "STOP_HIT"]
    print(f"\n  Remaining STOP_HIT ({len(stop_kept)}t):")
    for d in ["LONG", "SHORT"]:
        sd = stop_kept[stop_kept["direction"] == d]
        if len(sd):
            print(f"    {d}: {len(sd)}t  ${sd['net_pnl'].sum():+,.0f}")
            # Time distribution of remaining stops
            for h in [10, 11, 12, 13]:
                sh = sd[sd["hour"] == h]
                if len(sh):
                    spy_above = (sh["spy_above_vwap"] == True).sum()
                    print(f"      {h:02d}:xx  {len(sh)}t  SPY↑={spy_above}  ${sh['net_pnl'].sum():+,.0f}")

# ═══════════════════════════════════════════════════════════════════════════════
# 8. Implementation preview: if filter applied, what changes in engine?
# ═══════════════════════════════════════════════════════════════════════════════
div("8. IMPLEMENTATION PREVIEW")
best = vmr[mask_rr_ok & mask_short_spy_ok]
baseline_pnl = vmr["net_pnl"].sum()
best_pnl     = best["net_pnl"].sum()
improvement  = best_pnl - baseline_pnl

print(f"""
  Best two-filter combo: F1 (R:R≤2.5) + F2 (no SHORT SPY↑ after 12:30)
  Trades: {len(vmr)} → {len(best)} ({len(vmr)-len(best)} removed)
  VMR P&L: ${baseline_pnl:+,.0f} → ${best_pnl:+,.0f}  (Δ${improvement:+,.0f})
  System:  ${baseline_pnl+non_vmr_pnl:+,.0f} → ${best_pnl+non_vmr_pnl:+,.0f}

  Implementation in engine (2 changes):

  Change 1 — vwap_mr.py generate_signal():
    In DEFAULT_CONFIG: add 'max_rr_ratio': 2.5
    In Gate 3:
      if reward_dist / stop_distance > self.config.get('max_rr_ratio', 999):
          return None  # too far from VWAP — momentum, not MR

  Change 2 — engine.py section 8 (VWAP_MR entry loop):
    Before _attempt_entry:
      if sig['direction'] == 'SHORT' and bar_t >= dtime(12, 30):
          if spy_above_vwap:  # use existing _spy_above_vwap logic
              continue  # skip — SHORT against SPY trend in afternoon
""")
