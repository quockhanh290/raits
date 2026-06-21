"""Current engine setup + performance summary."""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
from collections import defaultdict

SNAP_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
PKL = os.path.join(SNAP_DIR, "results_scenario_g.pkl")

with open(PKL, "rb") as f:
    results = pickle.load(f)

W = 10
STRATS = [("ORB","ORB"),("ORB_FADE","ORB_F"),("FADE","FADE"),
          ("TREND_FOLLOW","TF"),("VWAP_MR","VMR")]

def row(trades):
    n   = len(trades)
    pnl = sum(t.net_pnl or 0 for t in trades)
    wr  = sum(1 for t in trades if (t.net_pnl or 0) > 0) / n * 100 if n else 0
    return n, pnl, wr

print("\n" + "="*70)
print("  CURRENT ENGINE STATUS  —  Scenario G")
print("="*70)

print(f"\n  {'':22} {'2020':>{W}} {'2021':>{W}} {'2022':>{W}} {'TOTAL':>{W}}")
print(f"  {'-'*62}")

# Equity / Return
starts = {r["label"]: r.get("equity_start", 50_000) for r in results}
ends   = {r["label"]: r.get("equity_end",   50_000) for r in results}
trades_by_yr = {r["label"]: r.get("trades", []) for r in results}

# overall PnL
yr_pnl = {}
for r in results:
    pnl = sum((t.net_pnl or 0) for t in r.get("trades", []))
    yr_pnl[r["label"]] = pnl

total_pnl = sum(yr_pnl.values())
cols = "".join(f"{yr_pnl.get(yr,0):>+{W},.0f}" for _, _, yr in
               [("","","2020"),("","","2021"),("","","2022")])
print(f"  {'System P&L ($)':<22}{cols}{total_pnl:>+{W},.0f}")

ret_cols = "".join(f"{yr_pnl.get(yr,0)/50_000:>{W}.1%}" for _, _, yr in
                   [("","","2020"),("","","2021"),("","","2022")])
print(f"  {'Return':<22}{ret_cols}{total_pnl/50_000:>{W}.1%}")

# trades total
n_cols = "".join(f"{len(trades_by_yr.get(yr,[])):>{W}}" for yr in ["2020","2021","2022"])
print(f"  {'Total trades':<22}{n_cols}{sum(len(v) for v in trades_by_yr.values()):>{W}}")

print(f"\n  {'─'*62}")
print(f"  By strategy:")

for strat_key, strat_lbl in STRATS:
    ns, ps = [], []
    for yr in ["2020","2021","2022"]:
        st = [t for t in trades_by_yr.get(yr,[]) if getattr(t,"strategy","") == strat_key]
        n, p, wr = row(st)
        ns.append(f"{n:>4}t {p:>+6,.0f}")
        ps.append((n, p, wr))
    total_n = sum(x[0] for x in ps)
    total_p = sum(x[1] for x in ps)
    cols = "".join(f"{s:>{W}}" for s in ns)
    print(f"  {strat_lbl:<8} P&L           {'':>{W-1}}", end="")
    for n, p, wr in ps:
        print(f"  {n:>3}t {p:>+6,.0f}", end="")
    print(f"  {total_n:>3}t {total_p:>+6,.0f}")

print(f"\n  {'─'*62}")
print(f"  FADE detail:")
for yr in ["2020","2021","2022"]:
    fade = [t for t in trades_by_yr.get(yr,[]) if getattr(t,"strategy","") == "FADE"]
    if not fade: continue
    shorts = [t for t in fade if getattr(t,"direction","") == "SHORT"]
    longs  = [t for t in fade if getattr(t,"direction","") == "LONG"]
    _, sp, swr = row(shorts)
    _, lp, lwr = row(longs)
    _, fp, fwr = row(fade)
    print(f"  [{yr}] FADE {len(fade):>3}t  ${fp:>+7,.0f}  WR={fwr:.0f}%  "
          f"| SHORT {len(shorts):>2}t ${sp:>+6,.0f} WR={swr:.0f}%"
          f"  | LONG {len(longs):>2}t ${lp:>+6,.0f} WR={lwr:.0f}%")

print(f"\n{'='*70}")
print(f"  CURRENT SETUP — Scenario G")
print(f"{'='*70}")
print(f"""
  HMM Regime Detection:
    States     : Calm / Normal / Stress / Crisis
    Retraining : weekly (Monday)
    Crisis OVR : 5-day realized vol >= 50%

  FADE filters (Scenario G):
    Universe   : ORBFadeUniverseScanner top-10 (gap_freq × reversal_rate)
    SHORT FADE : skip when SPY close > SPY OR high (9:30–9:44)
    LONG FADE  : skip when ticker in top-2 ATR% universe
    Window     : 9:45–10:15 ET only

  WFO hyperparameters (locked):
    orb_range_minutes = 15
    vwap_bb_std       = 2.0
    ema_period        = 30

  Position limits:
    MAX_TOTAL = 8  |  MAX_FADE = 5  |  MAX_ORB = 2  |  MAX_TF = 2

  Circuit breakers:
    Daily drawdown >= -4%  OR  5 consecutive losses → SHUTDOWN
""")
