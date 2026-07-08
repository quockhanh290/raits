"""
pnl_impact_corrected.py — P&L impact of CSV cumulative adjustment correction
============================================================================
Applies all 32 ex-div corrections → 80 label changes → 21 vault.
Estimates P&L delta from snapshot trades (no full backtest re-run needed).
DOES NOT MODIFY production files.
"""
import sys, warnings, json, re, os
sys.path.insert(0, "d:/raits")
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from futures._validated_core import benchmark_daily, label_regimes
from collections import Counter

DIVS = [
    ("2017-03-17", 1.0331), ("2017-06-16", 1.1831), ("2017-09-15", 1.2346),
    ("2017-12-15", 1.3513), ("2018-03-16", 1.0968), ("2018-06-15", 1.2456),
    ("2018-09-21", 1.3226), ("2018-12-21", 1.4354), ("2019-03-15", 1.2331),
    ("2019-06-21", 1.4316), ("2019-09-20", 1.3836), ("2019-12-20", 1.5700),
    ("2020-03-20", 1.4056), ("2020-06-19", 1.3662), ("2020-09-18", 1.3392),
    ("2020-12-18", 1.5800), ("2021-03-19", 1.2778), ("2021-06-18", 1.3759),
    ("2021-09-17", 1.4281), ("2021-12-17", 1.6364), ("2022-03-18", 1.3660),
    ("2022-06-17", 1.5769), ("2022-09-16", 1.5964), ("2022-12-16", 1.7814),
    ("2023-03-17", 1.5062), ("2023-06-16", 1.6384), ("2023-09-15", 1.5832),
    ("2023-12-15", 1.9061), ("2024-03-15", 1.5949), ("2024-06-21", 1.7590),
    ("2024-09-20", 1.7455), ("2024-12-20", 1.9655),
]

CSV = "d:/raits/spy_daily.csv"
df = pd.read_csv(CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
bench_base = benchmark_daily(CSV)
labels_base = label_regimes(bench_base, "2018-01-01", 3, "2024-12-31")

# Build cumulative corrected series (apply all dividend adjustments)
df_cum = df.copy()
for ex_date_str, amount in DIVS:
    ex_ts = pd.Timestamp(ex_date_str)
    mask = df_cum["date"] < ex_ts
    before = df_cum[mask]
    if len(before) == 0:
        continue
    p_prev = float(before.iloc[-1]["close"])
    factor = (p_prev - amount) / p_prev
    df_cum.loc[mask, "close"] *= factor

TMP = "d:/raits/_archive/scratch/_cum_corrected.csv"
df_cum["date"] = df_cum["date"].dt.strftime("%Y-%m-%d")
df_cum.to_csv(TMP, index=False)

bench_c = benchmark_daily(TMP)
labels_c = label_regimes(bench_c, "2018-01-01", 3, "2024-12-31")
os.remove(TMP)

changes = {d: (labels_base[d], labels_c[d])
           for d in labels_base if labels_base[d] != labels_c.get(d, labels_base[d])}

vault_start = pd.Timestamp("2023-01-01")
vault_changes = {d: v for d, v in changes.items() if d >= vault_start}
is_changes = {d: v for d, v in changes.items() if d < vault_start}

print(f"Cumulative label changes: {len(changes)} total")
print(f"  IS (2018-2022): {len(is_changes)}  | Types: {dict(Counter(v for v in is_changes.values()))}")
print(f"  Vault (2023+):  {len(vault_changes)} | Types: {dict(Counter(v for v in vault_changes.values()))}")
print()

# Load snapshot
with open("d:/raits/global_index/replay_snapshots_data.js", encoding="utf-8") as f:
    raw = f.read()
m = re.search(r"window\.REPLAY_DATA\s*=\s*(\{.*\})", raw, re.DOTALL)
data = json.loads(m.group(1))
snap = {s["date"]: s for s in data["snapshots"] if s.get("date")}

# P&L impact analysis for vault period
print("=== VAULT P&L IMPACT ===")
print()
hdr = f"{'Date':<14}{'Change':<22}{'Snap':<10}{'N':>4}{'Snap_PnL':>11}{'Delta_est':>12}  Note"
print(hdr)
print("-" * 100)

rows = []
for d in sorted(vault_changes):
    orig, corr = vault_changes[d]
    d_str = str(d.date())
    s = snap.get(d_str, {})
    dec = s.get("decision", {})
    entries = dec.get("entries", [])
    snap_regime = s.get("regime", "?")
    pnl_all = sum(e.get("pnl_sized", 0) for e in entries)
    n = len(entries)

    # Strategy breakdown
    by_strat = {}
    for e in entries:
        st = e.get("strategy", "?").upper()
        by_strat[st] = by_strat.get(st, 0) + e.get("pnl_sized", 0)

    # Impact interpretation
    if orig == "Calm" and corr == "Normal":
        # Snapshot used Calm (no ORB/TREND); corrected data says Normal → missed ORB/TREND
        # Can't quantify missed entries from snapshot directly
        note = "MISSED Normal entries (snapshot=Calm, correct=Normal)"
        delta = None  # unmeasurable from snapshot
    elif orig == "Normal" and corr == "Calm":
        if snap_regime == "Normal":
            note = f"EXTRA Normal ran; should Calm"
            delta = -pnl_all  # remove those trades
        else:
            note = f"snap={snap_regime}, already Calm in snapshot"
            delta = 0.0
    elif orig == "Normal" and corr == "Stress":
        if snap_regime == "Normal":
            # Only TREND should run in Stress; ORB/FADE/VWAP_MR are extra
            extra_strats = {"ORB", "FADE", "VWAP_MR", "VWAP"}
            extra_pnl = sum(pnl for st, pnl in by_strat.items()
                            if any(x in st for x in extra_strats))
            note = f"EXTRA ORB/FADE in Stress → -{extra_pnl:+.2f} extra strats"
            delta = -extra_pnl
        else:
            note = f"snap={snap_regime}"
            delta = 0.0
    else:
        note = f"other: {orig}→{corr}"
        delta = None

    delta_str = f"{delta:+.2f}" if delta is not None else "N/A"
    print(f"{d_str:<14}{orig}→{corr:<18}{snap_regime:<10}{n:>4}{pnl_all:>11.2f}{delta_str:>12}  {note}")
    rows.append({"date": d_str, "orig": orig, "corr": corr, "snap": snap_regime,
                 "n": n, "pnl": pnl_all, "delta": delta})

# Vault P&L summary
computable = [r for r in rows if r["delta"] is not None]
missed_rows = [r for r in rows if r["delta"] is None]
net_delta = sum(r["delta"] for r in computable)

print()
print("=== VAULT SUMMARY ===")
print(f"Vault OOS current baseline: $7,404")
print()
print(f"Computable delta ({len(computable)} days):")
for r in computable:
    print(f"  {r['date']}: {r['orig']}→{r['corr']} snap={r['snap']} | "
          f"pnl={r['pnl']:+.2f} | delta={r['delta']:+.2f}")
print(f"  Net computable delta: {net_delta:+.2f}")
print()
print(f"Non-quantifiable ({len(missed_rows)} Calm→Normal days, missed entries):")
for r in missed_rows:
    print(f"  {r['date']}: snapshot had {r['n']} Calm entries, pnl={r['pnl']:+.2f} "
          f"(correct=Normal → extra ORB/TREND entries unknown)")
print()
lo = 7404 + net_delta
print(f"Vault range: ${lo:.0f} (without Calm→Normal gains) to higher (if Calm→Normal adds P&L)")
print(f"Direction: correction could go EITHER way depending on Calm→Normal missed trades")
print()

# IS label changes by year
print("=== IS LABEL CHANGES BY YEAR ===")
by_year = {}
for d in changes:
    yr = d.year
    by_year[yr] = by_year.get(yr, 0) + 1
for yr in sorted(by_year):
    print(f"  {yr}: {by_year[yr]} label changes")
print()

# Live-vs-backtest basis
print("=== LIVE-VS-BACKTEST BASIS ===")
print("If live uses Polygon adjusted=True (correct) but backtest used old CSV:")
print("Systematic mismatch = 80 labels across 6 years = ~13 days/year")
print("Vault 2023-2024: 21/504 trading days = 4.2% of live days will differ")
print()
print("Nature of live mismatch:")
live_types = Counter(vault_changes.values())
for t, cnt in sorted(live_types.items(), key=lambda x: -x[1]):
    print(f"  {t[0]}→{t[1]}: {cnt} days")
print()

# IS all-in P&L impact via IS snapshot
print("=== IS SNAPSHOT P&L ESTIMATE ===")
is_trade_days = []
for d in sorted(is_changes):
    d_str = str(d.date())
    s = snap.get(d_str, {})
    entries = s.get("decision", {}).get("entries", [])
    if entries:
        pnl = sum(e.get("pnl_sized", 0) for e in entries)
        is_trade_days.append({"date": d_str, "change": is_changes[d], "pnl": pnl, "n": len(entries)})

is_type_pnl = {}
for r in is_trade_days:
    k = r["change"]
    is_type_pnl[k] = is_type_pnl.get(k, 0) + r["pnl"]

print(f"IS days with trades affected: {len(is_trade_days)} / {len(is_changes)}")
print("P&L by change type (snapshot-based — same caveat: Calm→Normal = missed entries):")
for k, v in sorted(is_type_pnl.items(), key=lambda x: -abs(x[1])):
    n_days = sum(1 for r in is_trade_days if r["change"] == k)
    print(f"  {k[0]}→{k[1]}: {n_days} days, snapshot P&L = {v:+.2f}")
print()
print("IS baseline: $52,962 — full re-run on corrected CSV needed for exact IS P&L")
print("(Cumulative correction changes log-returns, which changes HMM fit geometry,")
print(" which can cascade beyond just the 59 IS label changes)")
