"""
gap_fill_sizing_sim.py — GAP_FILL position sizing analysis.

Current engine: Kelly + max_position_pct=20% → actual risk ~$10-100/trade
Sim baseline:   $500/stop_dist shares (uncapped) → WR=78%, +$2,838

This script loads the 27 engine GAP_FILL trades and re-prices them under
three sizing scenarios to show the potential uplift from unlocking sizing.

Scenarios:
  A) Current (baseline) — engine Kelly + 20% cap
  B) Vol-sizing only, 20% cap — $500/stop_dist, cap at $10k position
  C) Vol-sizing only, 50% cap — $500/stop_dist, cap at $25k position
  D) Uncapped vol-sizing     — $500/stop_dist, no position cap

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\gap_fill_sizing_sim.py
"""
import sys, os, pickle
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
COMMISSION  = 0.01
TARGET_RISK = 500.0

print("Loading results PKL...")
with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)

gf_trades = []
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "strategy", "") == "GAP_FILL":
            gf_trades.append(t)

print(f"GAP_FILL trades found: {len(gf_trades)}")
if not gf_trades:
    print("No GAP_FILL trades — check PKL path")
    sys.exit(1)

# ── Compute sizing scenarios ──────────────────────────────────────────────────
rows = []
for t in gf_trades:
    entry   = float(t.entry_price)
    stop    = float(t.stop)
    exit_px = float(t.exit_price)
    reason  = t.exit_reason
    year    = str(pd.Timestamp(t.entry_time).year)

    stop_dist = abs(entry - stop)

    # Baseline (actual engine shares)
    sh_a  = int(t.shares)
    pnl_a = float(t.net_pnl)
    risk_a = sh_a * stop_dist

    # Vol-sizing: target $500 risk per trade
    def vol_shares(cap_pct: float) -> int:
        if stop_dist <= 0:
            return 0
        vol = int(TARGET_RISK / stop_dist)
        pos = int(entry * cap_pct / entry) if cap_pct else vol   # simplified
        cap_sh = int(50_000 * cap_pct / entry) if cap_pct else vol
        return max(1, min(vol, cap_sh))

    sh_b = vol_shares(0.20)   # 20% cap ($10k)
    sh_c = vol_shares(0.50)   # 50% cap ($25k)
    sh_d = int(TARGET_RISK / stop_dist) if stop_dist > 0 else 0  # uncapped

    def reprice(n: int) -> float:
        gross = (exit_px - entry) * n
        return gross - n * COMMISSION * 2

    pnl_b = reprice(sh_b)
    pnl_c = reprice(sh_c)
    pnl_d = reprice(sh_d)

    rows.append(dict(
        ticker=t.ticker, year=year,
        entry=entry, stop=stop, stop_dist=stop_dist,
        exit_px=exit_px, reason=reason,
        win=(exit_px > entry),
        sh_a=sh_a, pnl_a=pnl_a, risk_a=risk_a,
        sh_b=sh_b, pnl_b=pnl_b, risk_b=sh_b * stop_dist,
        sh_c=sh_c, pnl_c=pnl_c, risk_c=sh_c * stop_dist,
        sh_d=sh_d, pnl_d=pnl_d, risk_d=sh_d * stop_dist,
        limit_factor=getattr(t, "limiting_factor", "?"),
    ))

df = pd.DataFrame(rows)

# ── Report ────────────────────────────────────────────────────────────────────
HDR = "=" * 65
print(f"\n{HDR}")
print(f"  GAP_FILL SIZING ANALYSIS  —  27 engine trades, 2020-2022")
print(f"  Sim baseline (uncapped $500 risk): WR=78%, +$2,838")
print(f"{HDR}")

print(f"\n  stop_dist: min={df.stop_dist.min():.3f}  "
      f"mean={df.stop_dist.mean():.3f}  max={df.stop_dist.max():.3f}")
print(f"  Current limiting factors: {dict(df.limit_factor.value_counts())}")
print(f"\n  {'Scenario':<35} {'Trades':>6} {'Total P&L':>10} {'WR':>5} "
      f"{'avg P&L':>8} {'avg risk':>9}")
print(f"  {'-'*63}")

for label, col_sh, col_pnl, col_risk in [
    ("A  Current (Kelly + 20% cap)", "sh_a", "pnl_a", "risk_a"),
    ("B  Vol-sizing, 20% cap (~$10k)", "sh_b", "pnl_b", "risk_b"),
    ("C  Vol-sizing, 50% cap (~$25k)", "sh_c", "pnl_c", "risk_c"),
    ("D  Uncapped vol-sizing", "sh_d", "pnl_d", "risk_d"),
]:
    tot  = df[col_pnl].sum()
    wr   = df["win"].mean() * 100
    avg  = df[col_pnl].mean()
    risk = df[col_risk].mean()
    print(f"  {label:<35} {len(df):>6} {tot:>+10,.0f} {wr:>4.0f}%"
          f" {avg:>+8.1f} {risk:>+8.1f}")

print(f"\n  Year breakdown:")
for yr in ["2020", "2021", "2022"]:
    y = df[df.year == yr]
    if len(y) == 0:
        continue
    a = y["pnl_a"].sum(); b = y["pnl_b"].sum()
    c = y["pnl_c"].sum(); d = y["pnl_d"].sum()
    print(f"    {yr}: {len(y):2}t  "
          f"A={a:>+7,.0f}  B={b:>+7,.0f}  C={c:>+7,.0f}  D={d:>+7,.0f}")

print(f"\n  Exit reason breakdown (current):")
for r_, grp in df.groupby("reason"):
    print(f"    {r_:<14}: {len(grp)}t  "
          f"A={grp['pnl_a'].sum():>+7,.0f}  "
          f"C={grp['pnl_c'].sum():>+7,.0f}  "
          f"D={grp['pnl_d'].sum():>+7,.0f}")

print(f"\n  Per-trade detail (stop_dist vs scenarios):")
print(f"  {'Ticker':<6} {'Year'} {'stop_dist':>10} {'sh_A':>5} {'sh_B':>5} "
      f"{'sh_C':>5} {'sh_D':>5} {'reason':<12} {'pnl_A':>7} {'pnl_C':>7} {'pnl_D':>7}")
for _, r in df.sort_values("stop_dist").iterrows():
    print(f"  {r.ticker:<6} {r.year} {r.stop_dist:>10.3f} {int(r.sh_a):>5} "
          f"{int(r.sh_b):>5} {int(r.sh_c):>5} {int(r.sh_d):>5} "
          f"{r.reason:<12} {r.pnl_a:>+7.0f} {r.pnl_c:>+7.0f} {r.pnl_d:>+7.0f}")

print(f"{HDR}\n")
