"""Quick system summary from results pkl."""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

PKL = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
with open(PKL, "rb") as f: results = pickle.load(f)

rows = []
for w in results:
    yr = w.get("label","?")
    for t in w.get("trades",[]):
        d = vars(t).copy(); d["year"] = yr; rows.append(d)
df = pd.DataFrame(rows)
df["entry_time"] = pd.to_datetime(df["entry_time"])
df["win"] = df["net_pnl"] > 0

total = df["net_pnl"].sum()

print(f"\n{'='*68}")
print(f"  CURRENT SYSTEM — results_scenario_g.pkl")
print(f"{'='*68}")
print(f"\n  Total P&L : ${total:>+,.0f}")
print(f"  Total trades: {len(df)}")
print(f"  Win rate  : {df['win'].mean()*100:.1f}%")

print(f"\n  {'Strategy':<20} {'Trades':>7} {'P&L':>10} {'WR':>6} {'avg/t':>8} {'Regime'}")
print(f"  {'─'*62}")
for strat in df["strategy"].unique():
    s = df[df["strategy"]==strat]
    regimes = s["hmm_state"].value_counts().index.tolist()
    regime_str = "/".join(regimes[:2])
    print(f"  {strat:<20} {len(s):>7} {s['net_pnl'].sum():>+10,.0f} "
          f"{s['win'].mean()*100:>5.0f}% {s['net_pnl'].mean():>+8.1f}  {regime_str}")

print(f"\n  {'─'*62}")
print(f"  {'TOTAL':<20} {len(df):>7} {total:>+10,.0f} {df['win'].mean()*100:>5.0f}%")

print(f"\n  BY YEAR:")
print(f"  {'Strategy':<20} {'2020':>10} {'2021':>10} {'2022':>10}")
print(f"  {'─'*52}")
for strat in df["strategy"].unique():
    s = df[df["strategy"]==strat]
    row = f"  {strat:<20}"
    for yr in ["2020","2021","2022"]:
        sy = s[s["year"]==yr]
        row += f" {sy['net_pnl'].sum():>+10,.0f}" if len(sy) else f" {'—':>10}"
    print(row)
row = f"  {'TOTAL':<20}"
for yr in ["2020","2021","2022"]:
    sy = df[df["year"]==yr]
    row += f" {sy['net_pnl'].sum():>+10,.0f}"
print(f"  {'─'*52}")
print(row)

print(f"\n  BY REGIME:")
print(f"  {'Strategy':<20} {'Calm':>10} {'Normal':>10} {'Stress':>10}")
print(f"  {'─'*52}")
for strat in df["strategy"].unique():
    s = df[df["strategy"]==strat]
    row = f"  {strat:<20}"
    for regime in ["Calm","Normal","Stress"]:
        sr = s[s["hmm_state"]==regime]
        row += f" {sr['net_pnl'].sum():>+10,.0f}" if len(sr) else f" {'—':>10}"
    print(row)
