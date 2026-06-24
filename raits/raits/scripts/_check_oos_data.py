import sys, json, pickle
sys.path.insert(0, r'd:\raits\raits')
import pandas as pd

print("=== 5-min PKL ===")
with open(r'd:\raits\raits\data\cache\window_debug_5min.pkl', 'rb') as f:
    d = pickle.load(f)
for yr in [2023, 2024]:
    covered = []
    missing = []
    for tk in sorted(d.keys()):
        idx = pd.DatetimeIndex(d[tk].index)
        n = int((idx.year == yr).sum())
        (covered if n >= 100 else missing).append(tk)
    miss_str = str(missing) if missing else "none"
    print(f"  {yr}: {len(covered)}/{len(d)} tickers OK  missing={miss_str}")

print()
print("=== Earnings calendar ===")
with open(r'd:\raits\raits\data\cache\earnings_dates_expanded.json') as f:
    ec = json.load(f)
for yr in ["2022", "2023", "2024"]:
    n   = sum(1 for tk in ec for dt in ec[tk] if dt.startswith(yr))
    tks = sum(1 for tk in ec if any(dt.startswith(yr) for dt in ec[tk]))
    print(f"  {yr}: {n} events across {tks} tickers")

print()
print("=== VIX ===")
vix = pd.read_parquet(r'd:\raits\raits\data\cache\daily\vix_daily.parquet')
vix.index = pd.DatetimeIndex(vix.index)
print(f"  Range: {vix.index[0].date()} -> {vix.index[-1].date()}")
for yr in [2023, 2024]:
    n = int((vix.index.year == yr).sum())
    print(f"  {yr}: {n} rows")

print()
print("=== Daily PKL ===")
with open(r'd:\raits\raits\data\cache\window_debug_daily.pkl', 'rb') as f:
    dd = pickle.load(f)
spy_d = dd.get("SPY", pd.DataFrame())
spy_d.index = pd.DatetimeIndex(spy_d.index)
for yr in [2023, 2024]:
    n = int((spy_d.index.year == yr).sum())
    print(f"  SPY {yr}: {n} rows")

print()
print("=== WINDOWS in window_debug.py ===")
import re
with open(r'd:\raits\raits\raits\scripts\window_debug.py') as f:
    src = f.read()
matches = re.findall(r'\("(\d{4}-\d{2}-\d{2})", "(\d{4}-\d{2}-\d{2})", "(\d{4})"\)', src)
for m in matches:
    print(f"  {m[2]}: {m[0]} -> {m[1]}")
