"""
vmr_improve_sim.py
------------------
Điều tra VWAP_MR (-$128, 267t, WR=42%) với 3 angle mới chưa test:

  A. Regime split — VWAP_MR có vol-gate nên có thể fire ở cả Calm VÀ Normal.
     Nếu Normal trades kém hơn, filter về Calm-only cải thiện WR?

  B. Exit reason surgery — TIME_STOP trade là win hay lose?
     Nếu TIME_STOP = losers thì có thể shrink window hay tighten entry condition.

  C. SPY VWAP + regime + time combined — tìm combo filter tốt nhất mà
     vẫn all-3-years positive và >= 80 trades còn lại.

  D. VWAP deviation at entry — R:R thực tế (entry→VWAP / entry→stop).
     Trades với R:R thực < 1.5 có đáng lẽ phải bị block?

Usage:
    cd d:\\raits\\raits
    python raits/scripts/vmr_improve_sim.py
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
vmr["exit_time"]  = pd.to_datetime(vmr["exit_time"])
vmr["win"]        = vmr["net_pnl"] > 0
vmr["hold_min"]   = (vmr["exit_time"] - vmr["entry_time"]).dt.total_seconds() / 60
vmr["hour"]       = vmr["entry_time"].dt.hour

# Actual R:R from trade log
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
spy_vwap_series = spy[["close", "vwap"]]

def get_spy_state(ts):
    idx = spy_vwap_series.index[spy_vwap_series.index <= ts]
    if len(idx) == 0:
        return None
    r = spy_vwap_series.loc[idx[-1]]
    return float(r["close"]) > float(r["vwap"])

spy_states = [get_spy_state(ts) for ts in vmr["entry_time"]]
vmr["spy_above_vwap"] = spy_states

# ── Hour bucket ───────────────────────────────────────────────────────────────
def hour_bucket(h):
    if h == 10: return "10:15-11:00"
    if h == 11: return "11:00-12:00"
    if h == 12: return "12:00-13:00"
    return "13:00-14:00"

vmr["time_bucket"] = vmr["hour"].map(hour_bucket)

# ── Helpers ───────────────────────────────────────────────────────────────────
W = 9
def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

def show(label, df, indent="  "):
    n = len(df)
    if n == 0:
        return
    pnl = df["net_pnl"].sum()
    wr  = df["win"].mean() * 100
    avg = df["net_pnl"].mean()
    sys_pnl = pnl + non_vmr_pnl
    print(f"{indent}{label:<48} {n:>5}t  ${pnl:>+8,.0f}  WR={wr:>3.0f}%  avg=${avg:>+5.1f}  sys=${sys_pnl:>+8,.0f}")

def yr_breakdown(df, indent="    "):
    for yr in ["2020", "2021", "2022"]:
        s = df[df["year"] == yr]
        if len(s):
            print(f"{indent}{yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+7,.0f}  WR={s['win'].mean()*100:.0f}%")

print(f"\n{'='*72}")
print(f"  VMR IMPROVE SIM  —  {len(vmr)} trades, ${vmr['net_pnl'].sum():+,.0f} total, WR={vmr['win'].mean()*100:.0f}%")
print(f"  Non-VMR baseline: ${non_vmr_pnl:+,.0f}")
print(f"{'='*72}")

# ═══════════════════════════════════════════════════════════════════════════════
# A. REGIME SPLIT
# ═══════════════════════════════════════════════════════════════════════════════
div("A. REGIME SPLIT — Calm vs Normal (vol-gate)")
print(f"\n  Note: VWAP_MR uses vol-gate (SPY 5d vol ≤ threshold), not just HMM=Calm.")
print(f"  → May fire on Normal-regime days with low realized vol.\n")

if "hmm_state" in vmr.columns:
    for state in sorted(vmr["hmm_state"].dropna().unique()):
        s = vmr[vmr["hmm_state"] == state]
        show(f"hmm_state = {state}", s)
    print()
    calm_only = vmr[vmr["hmm_state"] == "Calm"]
    non_calm  = vmr[vmr["hmm_state"] != "Calm"]
    show("Calm only", calm_only)
    show("Non-Calm (vol-gated Normal)", non_calm)

    print(f"\n  Calm-only year breakdown:")
    yr_breakdown(calm_only)
    if len(non_calm):
        print(f"\n  Non-Calm year breakdown:")
        yr_breakdown(non_calm)
else:
    print("  hmm_state column not in trade log — regime split unavailable")

# ═══════════════════════════════════════════════════════════════════════════════
# B. EXIT REASON SURGERY
# ═══════════════════════════════════════════════════════════════════════════════
div("B. EXIT REASON × DIRECTION × REGIME")

if "exit_reason" in vmr.columns:
    print(f"\n  All trades by exit reason:")
    for reason in sorted(vmr["exit_reason"].dropna().unique()):
        s = vmr[vmr["exit_reason"] == reason]
        show(f"{reason}", s)

    print(f"\n  EXIT REASON × DIRECTION:")
    for reason in sorted(vmr["exit_reason"].dropna().unique()):
        for d in ["LONG", "SHORT"]:
            s = vmr[(vmr["exit_reason"] == reason) & (vmr["direction"] == d)]
            if len(s):
                show(f"  {reason} {d}", s)

    if "hmm_state" in vmr.columns:
        print(f"\n  EXIT REASON × REGIME (Calm vs Normal):")
        for reason in sorted(vmr["exit_reason"].dropna().unique()):
            for state in ["Calm", "Normal"]:
                s = vmr[(vmr["exit_reason"] == reason) & (vmr["hmm_state"] == state)]
                if len(s):
                    show(f"  {reason} + {state}", s)

    print(f"\n  Hold time by exit reason:")
    for reason in sorted(vmr["exit_reason"].dropna().unique()):
        s = vmr[vmr["exit_reason"] == reason]
        if len(s):
            print(f"    {reason:<20} hold median={s['hold_min'].median():.0f}min  "
                  f"mean={s['hold_min'].mean():.0f}min")
else:
    print("  exit_reason not available")

# ═══════════════════════════════════════════════════════════════════════════════
# C. SPY FILTER × REGIME × TIME COMBINED
# ═══════════════════════════════════════════════════════════════════════════════
div("C. COMBINED FILTER SCENARIOS (target: all-3-yrs positive, ≥80 trades)")

print(f"\n  {'Scenario':<55} {'n':>5}  {'VMR P&L':>9}  {'WR':>5}  {'sys':>9}")
print(f"  {'─'*85}")

# Helper: with-SPY mask (LONG when SPY>VWAP, SHORT when SPY<VWAP)
# Against-SPY: LONG when SPY<VWAP, SHORT when SPY>VWAP
mask_with_spy = (
    ((vmr["direction"] == "LONG")  & (vmr["spy_above_vwap"] == True)) |
    ((vmr["direction"] == "SHORT") & (vmr["spy_above_vwap"] == False))
)
mask_against_spy = (
    ((vmr["direction"] == "LONG")  & (vmr["spy_above_vwap"] == False)) |
    ((vmr["direction"] == "SHORT") & (vmr["spy_above_vwap"] == True))
)
mask_calm = vmr["hmm_state"] == "Calm" if "hmm_state" in vmr.columns else pd.Series(True, index=vmr.index)
mask_early = vmr["hour"] < 13  # before 13:00

scenarios = {}
scenarios["0. Current (no filter)"]                       = vmr
scenarios["1. Calm-only"]                                 = vmr[mask_calm]
scenarios["2. SPY aligned"]                               = vmr[mask_with_spy]
scenarios["3. NOT against SPY"]                           = vmr[~mask_against_spy]
scenarios["4. Calm + SPY aligned"]                        = vmr[mask_calm & mask_with_spy]
scenarios["5. Calm + NOT against SPY"]                    = vmr[mask_calm & ~mask_against_spy]
scenarios["6. Before 13:00"]                              = vmr[mask_early]
scenarios["7. Calm + before 13:00"]                       = vmr[mask_calm & mask_early]
scenarios["8. Calm + SPY aligned + before 13:00"]         = vmr[mask_calm & mask_with_spy & mask_early]
scenarios["9. Calm + NOT against SPY + before 13:00"]     = vmr[mask_calm & ~mask_against_spy & mask_early]
scenarios["A. SPY aligned + before 13:00"]               = vmr[mask_with_spy & mask_early]

# R:R filter
mask_rr2 = vmr["actual_rr"] >= 2.0
mask_rr15 = vmr["actual_rr"] >= 1.5
scenarios["B. Actual R:R ≥ 2.0"]                         = vmr[mask_rr2]
scenarios["C. Actual R:R ≥ 2.0 + Calm"]                  = vmr[mask_rr2 & mask_calm]
scenarios["D. Actual R:R ≥ 2.0 + Calm + SPY aligned"]    = vmr[mask_rr2 & mask_calm & mask_with_spy]

for name, df in scenarios.items():
    n   = len(df)
    pnl = df["net_pnl"].sum()
    wr  = df["win"].mean() * 100 if n > 0 else 0
    sys = pnl + non_vmr_pnl
    flag = ""
    if n >= 80:
        # Check all 3 years positive
        yr_ok = all(
            df[df["year"] == yr]["net_pnl"].sum() >= 0
            for yr in ["2020", "2021", "2022"]
            if len(df[df["year"] == yr]) > 0
        )
        flag = " ✓" if yr_ok else ""
    print(f"  {name:<55} {n:>5}  {pnl:>+9,.0f}  {wr:>4.0f}%  {sys:>+9,.0f}{flag}")

# ═══════════════════════════════════════════════════════════════════════════════
# D. ACTUAL R:R DISTRIBUTION
# ═══════════════════════════════════════════════════════════════════════════════
div("D. ACTUAL R:R AT ENTRY (entry→VWAP / entry→stop)")

rr_valid = vmr[vmr["actual_rr"].notna() & np.isfinite(vmr["actual_rr"])]
print(f"\n  N with valid R:R: {len(rr_valid)}")
print(f"  Median R:R : {rr_valid['actual_rr'].median():.2f}")
print(f"  Mean R:R   : {rr_valid['actual_rr'].mean():.2f}")
print(f"  P25 R:R    : {rr_valid['actual_rr'].quantile(0.25):.2f}")
print(f"  P75 R:R    : {rr_valid['actual_rr'].quantile(0.75):.2f}")
print(f"  < 1.5 R:R  : {(rr_valid['actual_rr'] < 1.5).sum()} trades  "
      f"(should be 0 — engine blocks these)")

print(f"\n  {'R:R bucket':<20} {'n':>5}  {'P&L':>9}  {'WR':>5}  {'avg':>7}")
for lo, hi, lbl in [(1.0, 1.5, "1.0–1.5x"),
                    (1.5, 2.0, "1.5–2.0x"),
                    (2.0, 2.5, "2.0–2.5x"),
                    (2.5, 3.0, "2.5–3.0x"),
                    (3.0, 99,  ">3.0x")]:
    s = rr_valid[(rr_valid["actual_rr"] >= lo) & (rr_valid["actual_rr"] < hi)]
    if len(s):
        print(f"  {lbl:<20} {len(s):>5}  {s['net_pnl'].sum():>+9,.0f}  "
              f"{s['win'].mean()*100:>4.0f}%  {s['net_pnl'].mean():>+7.1f}")

# ═══════════════════════════════════════════════════════════════════════════════
# E. DIRECTION × TIME × SPY — granular breakdowns
# ═══════════════════════════════════════════════════════════════════════════════
div("E. DIRECTION × TIME BUCKET × SPY state")

print(f"\n  {'Label':<55} {'n':>5}  {'P&L':>9}  {'WR':>5}")
for d in ["LONG", "SHORT"]:
    for bucket in ["10:15-11:00", "11:00-12:00", "12:00-13:00", "13:00-14:00"]:
        for spy_state, spy_lbl in [(True, "SPY↑"), (False, "SPY↓"), (None, "all SPY")]:
            s = vmr[(vmr["direction"] == d) & (vmr["time_bucket"] == bucket)]
            if spy_state is not None:
                s = s[s["spy_above_vwap"] == spy_state]
            if len(s) < 5:
                continue
            label = f"{d} {bucket} {spy_lbl}"
            pnl   = s["net_pnl"].sum()
            wr    = s["win"].mean() * 100
            print(f"  {label:<55} {len(s):>5}  {pnl:>+9,.0f}  {wr:>4.0f}%")

# ═══════════════════════════════════════════════════════════════════════════════
# F. YEAR BREAKDOWN FOR BEST SCENARIOS (from section C)
# ═══════════════════════════════════════════════════════════════════════════════
div("F. YEAR BREAKDOWN for selected scenarios")

key_scenarios = {
    "0. Current":                 scenarios["0. Current (no filter)"],
    "1. Calm-only":               scenarios["1. Calm-only"],
    "5. Calm + NOT against SPY":  scenarios["5. Calm + NOT against SPY"],
    "9. Calm+¬SPY+<13:00":        scenarios["9. Calm + NOT against SPY + before 13:00"],
    "C. R:R≥2 + Calm":            scenarios["C. Actual R:R ≥ 2.0 + Calm"],
    "D. R:R≥2 + Calm + SPY":      scenarios["D. Actual R:R ≥ 2.0 + Calm + SPY aligned"],
}

for name, df in key_scenarios.items():
    print(f"\n  {name} (n={len(df)}, P&L=${df['net_pnl'].sum():+,.0f}, WR={df['win'].mean()*100:.0f}%):")
    for yr in ["2020", "2021", "2022"]:
        s = df[df["year"] == yr]
        if len(s):
            print(f"    {yr}: {len(s):>3}t  ${s['net_pnl'].sum():>+7,.0f}  WR={s['win'].mean()*100:.0f}%")
        else:
            print(f"    {yr}:   0t")

# ═══════════════════════════════════════════════════════════════════════════════
# G. SHORT-ONLY DEEP DIVE (hypothesis: SHORT is the problem)
# ═══════════════════════════════════════════════════════════════════════════════
div("G. LONG vs SHORT deep dive")

for d in ["LONG", "SHORT"]:
    s = vmr[vmr["direction"] == d]
    print(f"\n  {d}: {len(s)}t  ${s['net_pnl'].sum():+,.0f}  WR={s['win'].mean()*100:.0f}%  avg=${s['net_pnl'].mean():+.1f}")
    if "exit_reason" in s.columns:
        for reason in sorted(s["exit_reason"].dropna().unique()):
            sr = s[s["exit_reason"] == reason]
            print(f"    {reason:<20} {len(sr):>3}t  ${sr['net_pnl'].sum():>+8,.0f}  WR={sr['win'].mean()*100:.0f}%")
    print(f"    Year breakdown:")
    for yr in ["2020", "2021", "2022"]:
        sy = s[s["year"] == yr]
        if len(sy):
            print(f"      {yr}: {len(sy):>3}t  ${sy['net_pnl'].sum():>+7,.0f}  WR={sy['win'].mean()*100:.0f}%")
