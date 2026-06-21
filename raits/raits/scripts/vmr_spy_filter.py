"""
VMR SPY direction filter analysis.
Hypothesis: SHORT VMR khi SPY bullish → mean reversion fail → stop hit.
             LONG VMR khi SPY bearish → same.

Retroactively apply SPY VWAP filter to VMR trades from pkl.

Usage:
    cd d:\raits\raits
    python raits/scripts/vmr_spy_filter.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

# ── Load trades ───────────────────────────────────────────────────────────────
with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)

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
vmr["win"] = vmr["net_pnl"] > 0

# R:R (now using correct field name 'stop')
vmr["risk"]   = (vmr["entry_price"] - vmr["stop"]).abs()
vmr["reward"] = (vmr["entry_price"] - vmr["target"]).abs()
vmr["rr"]     = vmr["reward"] / vmr["risk"].replace(0, np.nan)

# ── Load SPY 5-min ────────────────────────────────────────────────────────────
print("Loading SPY 5-min data...")
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)

spy_5min = data_5min.get("SPY", pd.DataFrame())
spy_5min.index = pd.to_datetime(spy_5min.index)
spy_5min = spy_5min.sort_index()

# ── Compute SPY VWAP per day, per bar ────────────────────────────────────────
def compute_spy_vwap_series(df):
    """For each bar, cumulative VWAP from 9:30 of that day."""
    df = df.copy()
    df["date"] = df.index.normalize()
    df["tp"]   = (df["high"] + df["low"] + df["close"]) / 3
    df["tpv"]  = df["tp"] * df["volume"]
    df["cum_tpv"] = df.groupby("date")["tpv"].cumsum()
    df["cum_vol"] = df.groupby("date")["volume"].cumsum()
    df["vwap"]    = df["cum_tpv"] / df["cum_vol"]
    return df[["close", "vwap"]]

print("Computing SPY VWAP...")
spy_vwap = compute_spy_vwap_series(spy_5min)

# ── Tag each VMR trade with SPY context at entry ──────────────────────────────
def get_spy_context(entry_ts):
    """SPY close and VWAP at the bar that contains entry_ts."""
    bar_ts = spy_vwap.index[spy_vwap.index <= entry_ts]
    if len(bar_ts) == 0:
        return None, None
    latest = bar_ts[-1]
    row = spy_vwap.loc[latest]
    return float(row["close"]), float(row["vwap"])

print("Tagging trades with SPY context...")
spy_closes, spy_vwaps = [], []
for ts in vmr["entry_time"]:
    c, v = get_spy_context(ts)
    spy_closes.append(c)
    spy_vwaps.append(v)

vmr["spy_close"] = spy_closes
vmr["spy_vwap"]  = spy_vwaps
vmr["spy_above_vwap"] = vmr["spy_close"] > vmr["spy_vwap"]  # True = SPY bullish at entry

W = 9
def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

def row(df, label):
    n = len(df)
    if n == 0: return
    pnl = df["net_pnl"].sum()
    wr  = df["win"].mean() * 100
    avg = df["net_pnl"].mean()
    print(f"  {label:<45} {n:>{W}} {pnl:>+{W},.0f} {wr:>{W-1}.0f}%  avg {avg:>+6.1f}")

print(f"\n{'='*72}")
print(f"  VMR SPY FILTER ANALYSIS  —  {len(vmr)} trades")
print(f"{'='*72}")
print(f"\n  {'':45} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")

# ── 1. SPY above/below VWAP × Direction ──────────────────────────────────────
div("1. SPY VWAP at entry × DIRECTION")
for spy_state, lbl in [(True, "SPY > VWAP (bullish)"), (False, "SPY < VWAP (bearish)")]:
    sub = vmr[vmr["spy_above_vwap"] == spy_state]
    for d in ["LONG", "SHORT", "ALL"]:
        s = sub if d == "ALL" else sub[sub["direction"] == d]
        row(s, f"  {lbl} {d}")

# ── 2. The key filter: skip trades going AGAINST SPY ─────────────────────────
div("2. TRADES WITH vs AGAINST SPY DRIFT")

# With SPY: LONG when SPY>VWAP, SHORT when SPY<VWAP (momentum aligned)
with_spy = vmr[
    ((vmr["direction"] == "LONG")  & (vmr["spy_above_vwap"] == True)) |
    ((vmr["direction"] == "SHORT") & (vmr["spy_above_vwap"] == False))
]
# Against SPY: LONG when SPY<VWAP, SHORT when SPY>VWAP (mean reversion bet)
against_spy = vmr[
    ((vmr["direction"] == "LONG")  & (vmr["spy_above_vwap"] == False)) |
    ((vmr["direction"] == "SHORT") & (vmr["spy_above_vwap"] == True))
]

row(with_spy,    "Aligned with SPY drift")
row(against_spy, "Against SPY drift")
print()
row(vmr[vmr["direction"]=="SHORT"], "ALL SHORT")
row(vmr[vmr["direction"]=="LONG"],  "ALL LONG")

# ── 3. Simulated: skip VMR when direction is against SPY VWAP ─────────────────
div("3. SIMULATION: skip if direction AGAINST SPY VWAP")

non_vmr_pnl = all_df[all_df["strategy"] != "VWAP_MR"]["net_pnl"].sum()

print(f"\n  {'Scenario':<50} {'VMR P&L':>9} {'System P&L':>12} {'VMR trades':>11}")
print(f"  {'-'*82}")

scenarios = {
    "A. Current (no filter)":
        vmr,
    "B. Skip SHORT when SPY > VWAP":
        vmr[~((vmr["direction"] == "SHORT") & (vmr["spy_above_vwap"] == True))],
    "C. Skip LONG when SPY < VWAP":
        vmr[~((vmr["direction"] == "LONG")  & (vmr["spy_above_vwap"] == False))],
    "D. Both B + C (skip when against SPY)":
        vmr[
            ~(((vmr["direction"] == "SHORT") & (vmr["spy_above_vwap"] == True)) |
              ((vmr["direction"] == "LONG")  & (vmr["spy_above_vwap"] == False)))
        ],
}

for name, df in scenarios.items():
    vp  = df["net_pnl"].sum()
    sp  = vp + non_vmr_pnl
    n   = len(df)
    print(f"  {name:<50} {vp:>+9,.0f} {sp:>+12,.0f} {n:>11}")

# ── 4. Year breakdown for best scenario ───────────────────────────────────────
div("4. SCENARIO D — year breakdown")
scen_d = scenarios["D. Both B + C (skip when against SPY)"]
print(f"\n  {'Year':6} {'n':>6} {'P&L':>9} {'WR':>7}")
for yr in ["2020", "2021", "2022"]:
    s = scen_d[scen_d["year"] == yr]
    if len(s):
        wr = s["win"].mean() * 100
        print(f"  {yr}   {len(s):>6} {s['net_pnl'].sum():>+9,.0f} {wr:>6.0f}%")

# ── 5. R:R distribution (fixed field name) ────────────────────────────────────
div("5. R:R DISTRIBUTION (entry_price → stop → target)")
rr_valid = vmr[vmr["rr"].notna() & np.isfinite(vmr["rr"])]
print(f"\n  median R:R = {rr_valid['rr'].median():.2f}")
print(f"  mean R:R   = {rr_valid['rr'].mean():.2f}")
print(f"  min R:R    = {rr_valid['rr'].min():.2f}")
print(f"  max R:R    = {rr_valid['rr'].max():.2f}")
print(f"\n  {'R:R bucket':40} {'n':>{W}} {'P&L':>{W}} {'WR':>{W}}")
for lo, hi, lbl in [(1.0, 1.5, "1.0–1.5x"), (1.5, 2.0, "1.5–2.0x"),
                    (2.0, 3.0, "2.0–3.0x"), (3.0, 99, ">3.0x")]:
    s = rr_valid[(rr_valid["rr"] >= lo) & (rr_valid["rr"] < hi)]
    if len(s):
        wr  = s["win"].mean() * 100
        avg = s["net_pnl"].mean()
        print(f"  {lbl:<40} {len(s):>{W}} {s['net_pnl'].sum():>+{W},.0f} "
              f"{wr:>{W-1}.0f}%  avg {avg:>+6.1f}")

# ── 6. HIGH R:R filter (only take trades with strong R:R) ────────────────────
div("6. SIMULATION: high R:R filter (>= 2.0) COMBINED with SPY filter")
high_rr_spy = scen_d[scen_d["rr"] >= 2.0]
vp  = high_rr_spy["net_pnl"].sum()
sp  = vp + non_vmr_pnl
wr  = high_rr_spy["win"].mean() * 100 if len(high_rr_spy) else 0
print(f"\n  SPY filter + R:R>=2.0: {len(high_rr_spy)} trades, "
      f"VMR ${vp:+,.0f}, System ${sp:+,.0f}, WR={wr:.0f}%")
for yr in ["2020", "2021", "2022"]:
    s = high_rr_spy[high_rr_spy["year"] == yr]
    if len(s):
        print(f"    {yr}: {len(s)}t, ${s['net_pnl'].sum():+,.0f}, WR={s['win'].mean()*100:.0f}%")
