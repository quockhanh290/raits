"""
Estimate impact của hai hướng:
A) Fix VMR (Calm 10:15-14:00): max upside từ existing VMR trades
B) Midday Normal strategy (10:15-14:00): proxy từ TF data + SPY intraday

Usage:
    cd d:\raits\raits
    python raits/scripts/midday_gap_estimate.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)

for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

rows = []
for w in results:
    yr = w.get("label", "?")
    for t in w.get("trades", []):
        d = vars(t).copy()
        d["year"] = yr
        rows.append(d)
df = pd.DataFrame(rows)
df["entry_time"] = pd.to_datetime(df["entry_time"])
df["exit_time"]  = pd.to_datetime(df["exit_time"])
df["win"] = df["net_pnl"] > 0

vmr = df[df["strategy"] == "VWAP_MR"].copy()
tf  = df[df["strategy"] == "TREND_FOLLOW"].copy()

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

# ═══════════════════════════════════════════════════════════════════════
# DIRECTION A: Fix VMR — max upside estimate từ exit reasons
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*72}")
print(f"  DIRECTION A: FIX VMR (Calm 10:15-14:00)")
print(f"{'='*72}")

div("A1. Current VMR exit breakdown")
for reason in ["STOP_HIT", "TARGET_HIT", "TIME_STOP", "CIRCUIT_BREAKER"]:
    s = vmr[vmr["exit_reason"] == reason]
    if len(s):
        print(f"  {reason:<20} {len(s):>4}t  {s['net_pnl'].sum():>+8,.0f}  "
              f"WR={s['win'].mean()*100:>3.0f}%  avg={s['net_pnl'].mean():>+6.1f}")

div("A2. Ceiling: if ALL stop hits converted to time stops")
stop_pnl    = vmr[vmr["exit_reason"] == "STOP_HIT"]["net_pnl"].sum()
target_pnl  = vmr[vmr["exit_reason"] == "TARGET_HIT"]["net_pnl"].sum()
time_pnl    = vmr[vmr["exit_reason"] == "TIME_STOP"]["net_pnl"].sum()
cb_pnl      = vmr[vmr["exit_reason"] == "CIRCUIT_BREAKER"]["net_pnl"].sum()
n_stops     = len(vmr[vmr["exit_reason"] == "STOP_HIT"])
avg_time    = vmr[vmr["exit_reason"] == "TIME_STOP"]["net_pnl"].mean()

# If all stops became time stops instead
recovered   = n_stops * (avg_time - vmr[vmr["exit_reason"]=="STOP_HIT"]["net_pnl"].mean())
theoretical_max = target_pnl + n_stops * avg_time + time_pnl + cb_pnl

print(f"\n  Current VMR P&L              : {vmr['net_pnl'].sum():>+8,.0f}")
print(f"  Stop hits removed (→ zero)   : {-stop_pnl:>+8,.0f}  (best case: avoid all stops)")
print(f"  Stops → avg time stop profit : {n_stops * avg_time:>+8,.0f}")
print(f"  ─────────────────────────────────────────")
print(f"  Theoretical MAX VMR P&L      : {theoretical_max:>+8,.0f}  (3 years)")
print(f"  Realistic (50% improvement)  : {vmr['net_pnl'].sum() + recovered * 0.5:>+8,.0f}  (3 years)")
print(f"\n  Per year:  max={theoretical_max/3:>+.0f}  realistic={vmr['net_pnl'].sum()/3 + recovered*0.5/3:>+.0f}")

div("A3. VMR Calm days available (upper bound on opportunity)")
calm_days_by_yr = {}
for yr in ["2020", "2021", "2022"]:
    v = vmr[vmr["year"] == yr]
    days = v["entry_time"].dt.normalize().nunique()
    calm_days_by_yr[yr] = days
    print(f"  {yr}: ~{days} Calm trading days with VMR activity, "
          f"{len(v)} trades ({len(v)/days:.1f} trades/day)")

# ═══════════════════════════════════════════════════════════════════════
# DIRECTION B: Normal regime midday — proxy từ SPY intraday moves
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*72}")
print(f"  DIRECTION B: NORMAL REGIME MIDDAY (10:15-14:00)")
print(f"{'='*72}")

spy = data_5min.get("SPY", pd.DataFrame()).sort_index()

div("B1. TF benchmark (current Normal regime strategy 14:00-15:55)")
for yr in ["2020", "2021", "2022"]:
    t = tf[tf["year"] == yr]
    if len(t):
        normal_t = t[t["hmm_state"] == "Normal"]
        print(f"  [{yr}] TF total: {len(t)}t ${t['net_pnl'].sum():>+,.0f}  "
              f"Normal: {len(normal_t)}t ${normal_t['net_pnl'].sum():>+,.0f}  "
              f"avg=${normal_t['net_pnl'].mean():>+.1f}/trade")

div("B2. SPY directional move 10:15→14:00 on Normal regime days")
# Use TF Normal trades to identify Normal days
tf_normal = tf[tf["hmm_state"] == "Normal"].copy()
tf_normal["date"] = tf_normal["entry_time"].dt.normalize()
normal_days = tf_normal["date"].unique()

results_b = []
for day in sorted(normal_days):
    day_spy = spy[spy.index.normalize() == day]
    if day_spy.empty:
        continue

    # Get SPY at 10:15 and 14:00
    bar_1015 = day_spy[day_spy.index.time <= pd.Timestamp("10:15").time()]
    bar_1400 = day_spy[day_spy.index.time <= pd.Timestamp("14:00").time()]
    if bar_1015.empty or bar_1400.empty:
        continue

    px_1015 = float(bar_1015.iloc[-1]["close"])
    px_1400 = float(bar_1400.iloc[-1]["close"])
    move_pct = (px_1400 - px_1015) / px_1015 * 100

    # TF trades on this day
    day_tf = tf_normal[tf_normal["date"] == day]
    tf_direction = day_tf["direction"].mode()[0] if len(day_tf) else None
    tf_pnl = day_tf["net_pnl"].sum()

    # Would midday trend (10:15→14:00) align with TF direction?
    spy_up = move_pct > 0
    midday_aligned = (spy_up and tf_direction == "LONG") or \
                     (not spy_up and tf_direction == "SHORT")

    results_b.append({
        "date": day,
        "year": str(day.year),
        "spy_move_pct": move_pct,
        "tf_direction": tf_direction,
        "tf_pnl": tf_pnl,
        "midday_aligned": midday_aligned,
        "spy_up": spy_up,
    })

rb = pd.DataFrame(results_b)
print(f"\n  Normal trading days analyzed: {len(rb)}")
print(f"  SPY up 10:15→14:00   : {rb['spy_up'].sum()} days  ({rb['spy_up'].mean()*100:.0f}%)")
print(f"  SPY down 10:15→14:00 : {(~rb['spy_up']).sum()} days ({(~rb['spy_up']).mean()*100:.0f}%)")
print(f"  Aligned with TF direction: {rb['midday_aligned'].sum()} days ({rb['midday_aligned'].mean()*100:.0f}%)")

div("B3. SPY move magnitude 10:15→14:00 (how much directional move exists)")
print(f"\n  avg |move| : {rb['spy_move_pct'].abs().mean():.3f}%")
print(f"  median     : {rb['spy_move_pct'].abs().median():.3f}%")
print(f"  >0.3% days : {(rb['spy_move_pct'].abs() > 0.3).sum()} ({(rb['spy_move_pct'].abs()>0.3).mean()*100:.0f}%)")
print(f"  >0.5% days : {(rb['spy_move_pct'].abs() > 0.5).sum()} ({(rb['spy_move_pct'].abs()>0.5).mean()*100:.0f}%)")

div("B4. When SPY moves >0.3% midday, TF performance that day")
strong = rb[rb["spy_move_pct"].abs() > 0.3]
weak   = rb[rb["spy_move_pct"].abs() <= 0.3]
print(f"\n  Strong midday move (>0.3%): {len(strong)} days  TF P&L={strong['tf_pnl'].sum():>+,.0f}  avg={strong['tf_pnl'].mean():>+.1f}")
print(f"  Weak midday move  (≤0.3%): {len(weak)} days  TF P&L={weak['tf_pnl'].sum():>+,.0f}  avg={weak['tf_pnl'].mean():>+.1f}")

div("B5. Hypothetical midday strategy estimate")
# Assumption: midday strategy captures 40% of SPY's 10:15→14:00 move
# on a $50k portfolio, 1-2 positions similar size to TF
tf_avg_pnl   = tf_normal["net_pnl"].mean()  # avg P&L per TF trade
tf_avg_size  = (tf_normal["entry_price"] * tf_normal["shares"]).mean() if "shares" in tf_normal.columns else 5000

# Conservative: midday captures 50% of what TF captures (weaker signal)
# Estimate trades: ~0.5 trades/Normal day (TF gets ~0.5 too)
n_normal_days_total = len(rb)
est_trades_per_day  = 0.5
est_trades          = n_normal_days_total * est_trades_per_day
est_pnl_conservative = tf_avg_pnl * 0.5 * est_trades   # 50% of TF edge
est_pnl_optimistic   = tf_avg_pnl * 0.75 * est_trades  # 75% of TF edge

print(f"\n  Normal days in dataset       : {n_normal_days_total}")
print(f"  TF avg P&L/trade (Normal)    : ${tf_avg_pnl:>+.1f}")
print(f"  Est midday trades (0.5/day)  : {est_trades:.0f}")
print(f"\n  Estimate (conservative 50%): ${est_pnl_conservative:>+,.0f} over 3yr  = ${est_pnl_conservative/3:>+,.0f}/yr")
print(f"  Estimate (optimistic  75%): ${est_pnl_optimistic:>+,.0f} over 3yr  = ${est_pnl_optimistic/3:>+,.0f}/yr")

# ═══════════════════════════════════════════════════════════════════════
# SUMMARY COMPARISON
# ═══════════════════════════════════════════════════════════════════════
print(f"\n{'='*72}")
print(f"  SUMMARY: Direction A vs B")
print(f"{'='*72}")
current_system = df["net_pnl"].sum()
print(f"""
  Current system (3yr)    : ${current_system:>+,.0f}

  Direction A — Fix VMR (Calm 10:15-14:00):
    Theoretical max        : ${theoretical_max:>+,.0f}  (+${theoretical_max - vmr['net_pnl'].sum():,.0f} vs current VMR)
    Realistic estimate     : ${vmr['net_pnl'].sum() + recovered*0.5:>+,.0f}
    Per year (realistic)   : ${(vmr['net_pnl'].sum() + recovered*0.5)/3:>+,.0f}/yr
    Regime                 : Calm only

  Direction B — Normal midday strategy (10:15-14:00):
    Conservative estimate  : ${est_pnl_conservative:>+,.0f}  (${est_pnl_conservative/3:>+,.0f}/yr)
    Optimistic estimate    : ${est_pnl_optimistic:>+,.0f}  (${est_pnl_optimistic/3:>+,.0f}/yr)
    Regime                 : Normal (more frequent than Calm)
    Risk                   : new strategy, needs design + validation
""")
