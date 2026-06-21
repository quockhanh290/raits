"""
VMR (VWAP Mean Reversion) trade analysis — tìm profitable setup filters.

Usage:
    cd d:\raits\raits
    python raits/scripts/vmr_diagnostic.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
PKL = os.path.join(SNAP_DIR, "results_scenario_g.pkl")

# ── Load trades ───────────────────────────────────────────────────────────────
with open(PKL, "rb") as f:
    results = pickle.load(f)

rows = []
for window in results:
    yr = window.get("label", "?")
    for t in window.get("trades", []):
        d = t.__dict__.copy() if hasattr(t, "__dict__") else {}
        d["year"] = yr
        rows.append(d)

all_df = pd.DataFrame(rows)
vmr = all_df[all_df["strategy"] == "VWAP_MR"].copy()
vmr["entry_time"] = pd.to_datetime(vmr["entry_time"])
vmr["exit_time"]  = pd.to_datetime(vmr["exit_time"])
vmr["hour"]       = vmr["entry_time"].dt.hour
vmr["minute"]     = vmr["entry_time"].dt.minute
vmr["hour_label"] = vmr["entry_time"].dt.strftime("%H:%M")
vmr["win"]        = vmr["net_pnl"] > 0
vmr["hold_min"]   = (vmr["exit_time"] - vmr["entry_time"]).dt.total_seconds() / 60

# R:R estimate: reward = entry→target, risk = entry→stop
if "entry_price" in vmr.columns and "stop_loss" in vmr.columns and "target" in vmr.columns:
    vmr["risk"]   = (vmr["entry_price"] - vmr["stop_loss"]).abs()
    vmr["reward"] = (vmr["entry_price"] - vmr["target"]).abs()
    vmr["rr"]     = vmr["reward"] / vmr["risk"].replace(0, np.nan)

W = 9

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

def summary(df, label=""):
    n = len(df)
    if n == 0:
        return f"  {label:<40} {'0':>{W}} {'—':>{W}} {'—':>{W}}"
    pnl = df["net_pnl"].sum()
    wr  = df["win"].mean() * 100
    avg = df["net_pnl"].mean()
    return f"  {label:<40} {n:>{W}} {pnl:>+{W},.0f} {wr:>{W-1}.0f}%  avg {avg:>+6.1f}"

print(f"\n{'='*72}")
print(f"  VMR DIAGNOSTIC  —  {len(vmr)} trades, ${vmr['net_pnl'].sum():+,.0f} total")
print(f"{'='*72}")
print(f"\n  {'':40} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")

# ── 1. Year × Direction ───────────────────────────────────────────────────────
div("1. YEAR × DIRECTION")
for yr in ["2020", "2021", "2022", "ALL"]:
    sub = vmr if yr == "ALL" else vmr[vmr["year"] == yr]
    for d in ["LONG", "SHORT", "ALL"]:
        s = sub if d == "ALL" else sub[sub["direction"] == d]
        lbl = f"[{yr}] {d}"
        if len(s): print(summary(s, lbl))

# ── 2. Hour bucket breakdown ──────────────────────────────────────────────────
div("2. ENTRY HOUR (ALL years)")
print(f"\n  {'Hour':40} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")

# Buckets: 10:15-11:00, 11:00-12:00, 12:00-13:00, 13:00-14:00
def hour_bucket(row):
    h, m = row["hour"], row["minute"]
    if h == 10: return "10:15–11:00"
    if h == 11: return "11:00–12:00"
    if h == 12: return "12:00–13:00"
    if h == 13: return "13:00–14:00"
    return f"{h:02d}:xx"

vmr["bucket"] = vmr.apply(hour_bucket, axis=1)
for bucket in ["10:15–11:00", "11:00–12:00", "12:00–13:00", "13:00–14:00"]:
    s = vmr[vmr["bucket"] == bucket]
    if len(s): print(summary(s, bucket))

# Direction × Hour
div("3. DIRECTION × HOUR BUCKET")
print(f"\n  {'Bucket':40} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")
for bucket in ["10:15–11:00", "11:00–12:00", "12:00–13:00", "13:00–14:00"]:
    for d in ["LONG", "SHORT"]:
        s = vmr[(vmr["bucket"] == bucket) & (vmr["direction"] == d)]
        if len(s): print(summary(s, f"  {bucket} {d}"))

# ── 4. Exit reason breakdown ──────────────────────────────────────────────────
div("4. EXIT REASON × DIRECTION")
if "exit_reason" in vmr.columns:
    print(f"\n  {'Exit reason':40} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")
    for reason in vmr["exit_reason"].dropna().unique():
        for d in ["LONG", "SHORT"]:
            s = vmr[(vmr["exit_reason"] == reason) & (vmr["direction"] == d)]
            if len(s): print(summary(s, f"{reason} {d}"))
else:
    print("  (exit_reason field not available in trade log)")

# ── 5. Hold time distribution ─────────────────────────────────────────────────
div("5. HOLD TIME vs P&L")
if "hold_min" in vmr.columns and vmr["hold_min"].notna().any():
    bins = [(0, 15), (15, 30), (30, 60), (60, 120), (120, 999)]
    print(f"\n  {'Hold (min)':40} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")
    for lo, hi in bins:
        s = vmr[(vmr["hold_min"] >= lo) & (vmr["hold_min"] < hi)]
        if len(s): print(summary(s, f"{lo}–{hi} min"))

# ── 6. R:R distribution ───────────────────────────────────────────────────────
div("6. R:R AT ENTRY (planned reward / planned risk)")
if "rr" in vmr.columns and vmr["rr"].notna().any():
    rr_valid = vmr[vmr["rr"].notna()]
    print(f"\n  median R:R = {rr_valid['rr'].median():.2f}")
    print(f"  mean R:R   = {rr_valid['rr'].mean():.2f}")
    print(f"  < 1.5 R:R  = {(rr_valid['rr'] < 1.5).sum()} trades")
    print(f"  1.5-2.0    = {((rr_valid['rr']>=1.5)&(rr_valid['rr']<2.0)).sum()} trades")
    print(f"  2.0-3.0    = {((rr_valid['rr']>=2.0)&(rr_valid['rr']<3.0)).sum()} trades")
    print(f"  > 3.0 R:R  = {(rr_valid['rr']>=3.0).sum()} trades")

    print(f"\n  {'R:R bucket':40} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")
    for lo, hi, lbl in [(1.5, 2.0, "1.5–2.0x R:R"), (2.0, 3.0, "2.0–3.0x R:R"),
                        (3.0, 99, ">3.0x R:R")]:
        s = rr_valid[(rr_valid["rr"] >= lo) & (rr_valid["rr"] < hi)]
        if len(s): print(summary(s, lbl))

# ── 7. Ticker analysis ────────────────────────────────────────────────────────
div("7. TICKER — top losers and top winners")
if "ticker" in vmr.columns:
    tk = vmr.groupby("ticker")["net_pnl"].agg(n="count", total="sum").reset_index()
    tk["avg"] = tk["total"] / tk["n"]
    tk["total"] = tk["total"].round(1)
    print("\n  Top 10 LOSERS:")
    print(f"  {'Ticker':8} {'n':>5} {'Total':>9} {'Avg/trade':>10}")
    for _, r in tk.nsmallest(10, "total").iterrows():
        print(f"  {r['ticker']:<8} {int(r['n']):>5} {r['total']:>+9.0f} {r['avg']:>+10.1f}")
    print("\n  Top 10 WINNERS:")
    for _, r in tk.nlargest(10, "total").iterrows():
        print(f"  {r['ticker']:<8} {int(r['n']):>5} {r['total']:>+9.0f} {r['avg']:>+10.1f}")

# ── 8. SPY direction context ──────────────────────────────────────────────────
div("8. SPY DIRECTION context (from entry day)")
# Try to infer SPY trend from trade metadata if available
if "spy_trend" in vmr.columns:
    for trend in vmr["spy_trend"].dropna().unique():
        s = vmr[vmr["spy_trend"] == trend]
        print(summary(s, f"SPY trend = {trend}"))
else:
    # Check if there's any market context field
    meta_cols = [c for c in vmr.columns
                 if any(x in c.lower() for x in ["spy","regime","market","trend"])]
    print(f"  Available context fields: {meta_cols or 'none'}")

# ── 9. Summary hypothesis ─────────────────────────────────────────────────────
div("9. SUMMARY — key splits")
print(f"\n  Total VMR trades : {len(vmr)}")
print(f"  Total P&L        : ${vmr['net_pnl'].sum():+,.0f}")
print(f"  Win rate         : {vmr['win'].mean()*100:.1f}%")
print(f"  Avg P&L/trade    : ${vmr['net_pnl'].mean():+.1f}")
print()
for d in ["LONG", "SHORT"]:
    s = vmr[vmr["direction"] == d]
    if len(s):
        print(f"  {d:<6}: {len(s):>3}t  ${s['net_pnl'].sum():>+7,.0f}  "
              f"WR={s['win'].mean()*100:.0f}%  avg ${s['net_pnl'].mean():>+5.1f}")
