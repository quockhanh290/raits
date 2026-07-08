"""
audit_spy_exdiv.py — Audit ALL SPY ex-dividend dates 2017-2024
==============================================================
For each quarterly ex-div, compare spy_daily.csv close vs Polygon adjusted=True.
Then for each drifted date (>0.1% deviation), test whether it triggers HMM cliff.

DOES NOT MODIFY CSV.  Measure + report only.

Run:
    cd d:\raits
    python _archive/scratch/audit_spy_exdiv.py

Requires: config_private.py (POLYGON_API_KEY) in d:\raits, or POLYGON_API_KEY env var.
Runtime: ~2-3 min (32 Polygon calls + HMM perturbation per drifted date).
"""
from __future__ import annotations
import sys, os, warnings, time
warnings.filterwarnings("ignore")
sys.path.insert(0, "d:/raits")

import pandas as pd
import numpy as np
from pathlib import Path

# ── API key ──────────────────────────────────────────────────────────────────
try:
    from config_private import POLYGON_API_KEY
except ImportError:
    POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "")
if not POLYGON_API_KEY:
    sys.exit("ERROR: POLYGON_API_KEY not found in config_private.py or env")

# ── Load CSV ──────────────────────────────────────────────────────────────────
CSV = Path("d:/raits/spy_daily.csv")
csv_df = pd.read_csv(CSV, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
csv_series = csv_df.set_index("date")["close"]

print(f"spy_daily.csv: {len(csv_df)} rows | {csv_df['date'].min().date()} – {csv_df['date'].max().date()}")
print()

# ── Fetch SPY dividends from Polygon ─────────────────────────────────────────
print("Fetching SPY dividends 2017-2024 from Polygon...")
from polygon import RESTClient
client = RESTClient(POLYGON_API_KEY)

divs_raw = list(client.list_dividends(
    ticker="SPY",
    ex_dividend_date_gte="2017-01-01",
    ex_dividend_date_lte="2024-12-31",
    limit=100,
))
divs = sorted(
    [{"ex_date": d.ex_dividend_date, "amount": float(d.cash_amount)} for d in divs_raw],
    key=lambda x: x["ex_date"],
)
print(f"Found {len(divs)} dividends\n")
for d in divs:
    print(f"  {d['ex_date']}  ${d['amount']:.4f}")
print()

# ── For each ex-div: fetch Polygon adjusted close 3 trading days before ───────
# Using X-3 to avoid the ex-div date itself (return on ex-div day includes the
# price drop from the dividend; we want the "stored price" comparison, not the return).
# Comparison: does CSV[X-3] == Polygon_adjusted[X-3]?

def polygon_adjusted_close(date_str: str) -> float | None:
    """Fetch Polygon adjusted close for a single date. Returns None on error."""
    try:
        bars = client.get_aggs("SPY", 1, "day",
                               from_=date_str, to=date_str,
                               adjusted=True)
        if bars and len(bars) > 0:
            return float(bars[0].close)
        return None
    except Exception as e:
        print(f"  [WARN] Polygon error for {date_str}: {e}")
        return None

def business_days_before(target_str: str, n: int) -> str | None:
    """Return date N business days before target, within csv_df range."""
    target = pd.Timestamp(target_str)
    all_dates = csv_df["date"].values
    before = all_dates[all_dates < target.to_datetime64()]
    if len(before) < n:
        return None
    return pd.Timestamp(before[-n]).strftime("%Y-%m-%d")

print("Comparing CSV vs Polygon adjusted for each ex-div (fetching 3 bdays before each)...")
print(f"{'Ex-div date':<14} {'Div $':>7} {'Ref date':<14} {'CSV close':>11} {'Poly adj':>11} {'Ratio':>8} {'Drift%':>8} {'Flag'}")
print("-" * 90)

results = []
for i, d in enumerate(divs):
    ex_date = d["ex_date"]
    amount = d["amount"]

    ref_date = business_days_before(ex_date, 3)
    if ref_date is None:
        print(f"  {ex_date}: skip (not enough data before)")
        continue

    # CSV close for ref_date
    ref_ts = pd.Timestamp(ref_date)
    if ref_ts not in csv_series.index:
        # try nearest date
        close_dates = csv_series.index[csv_series.index <= ref_ts]
        if len(close_dates) == 0:
            continue
        ref_ts = close_dates[-1]
        ref_date = ref_ts.strftime("%Y-%m-%d")
    csv_close = float(csv_series[ref_ts])

    # Polygon adjusted close for same date
    time.sleep(0.12)  # ~8 req/sec, stay under 5/min = 0.2s minimum; Polygon allows more
    poly_close = polygon_adjusted_close(ref_date)

    if poly_close is None:
        print(f"  {ex_date}: WARN — Polygon returned no data for {ref_date}")
        continue

    ratio = csv_close / poly_close
    drift_pct = (ratio - 1.0) * 100
    flag = "** DRIFT **" if abs(drift_pct) > 0.10 else "ok"

    results.append({
        "ex_date": ex_date, "amount": amount, "ref_date": ref_date,
        "csv_close": csv_close, "poly_close": poly_close,
        "ratio": ratio, "drift_pct": drift_pct, "drifted": abs(drift_pct) > 0.10,
    })

    print(f"{ex_date:<14} {amount:>7.4f} {ref_date:<14} {csv_close:>11.4f} {poly_close:>11.4f} {ratio:>8.6f} {drift_pct:>7.3f}%  {flag}")

print()

# ── Summary ───────────────────────────────────────────────────────────────────
drifted = [r for r in results if r["drifted"]]
clean = [r for r in results if not r["drifted"]]
print(f"=== DRIFT MAP ===")
print(f"Total ex-divs checked: {len(results)}")
print(f"Correctly adjusted (within 0.1%): {len(clean)}")
print(f"DRIFTED (>0.1%):                  {len(drifted)}")
print()

if drifted:
    print("Drifted ex-divs:")
    for r in drifted:
        print(f"  {r['ex_date']}  div=${r['amount']:.4f}  drift={r['drift_pct']:+.3f}%  "
              f"csv={r['csv_close']:.4f}  poly={r['poly_close']:.4f}")
    print()

# Find break point: first drifted date (CSV starts diverging from Polygon)
if drifted:
    breakpoint_date = drifted[0]["ex_date"]
    print(f"BREAK POINT (first drifted ex-div): {breakpoint_date}")
    print(f"  → CSV was fetched/frozen before or around {breakpoint_date}")
    print(f"  → All {len(drifted)} ex-div adjustments AFTER this date missing from CSV")
    print()

# ── HMM cliff test for each drifted date ─────────────────────────────────────
if not drifted:
    print("No drifted ex-divs found — CSV is fully adjusted. No cliff test needed.")
    sys.exit(0)

print("=" * 70)
print("HMM CLIFF TEST — for each drifted ex-div")
print("Applying correction factor and measuring label changes...")
print()

from futures._validated_core import benchmark_daily, label_regimes

bench_base = benchmark_daily(str(CSV))
labels_base = label_regimes(bench_base, "2018-01-01", 3, "2024-12-31")

# We need a temp file path for CSV save/reload (float serialization consistency)
TMP = Path("d:/raits/_archive/scratch/_exdiv_audit_tmp.csv")

cliff_results = []

for r in drifted:
    ex_date = r["ex_date"]
    amount = r["amount"]

    # The correction factor: if CSV was NOT re-adjusted for this dividend,
    # all prices BEFORE ex_date in CSV are HIGHER than they should be.
    # Correction: multiply prices before ex_date by factor = (P_exdiv_prev - div) / P_exdiv_prev
    # We approximate P_exdiv_prev from CSV (the day before ex_date).
    ex_ts = pd.Timestamp(ex_date)
    before = csv_df[csv_df["date"] < ex_ts]
    if len(before) == 0:
        continue
    p_prev = float(before.iloc[-1]["close"])
    factor = (p_prev - amount) / p_prev
    actual_drift_pct = (1/factor - 1) * 100

    # Build corrected series (apply factor to all dates before ex_date)
    df_c = csv_df.copy()
    df_c.loc[df_c["date"] < ex_ts, "close"] = df_c.loc[df_c["date"] < ex_ts, "close"] * factor
    df_c["date"] = df_c["date"].dt.strftime("%Y-%m-%d")
    df_c.to_csv(TMP, index=False)

    bench_c = benchmark_daily(str(TMP))
    labels_c = label_regimes(bench_c, "2018-01-01", 3, "2024-12-31")

    changes = {d: (labels_base[d], labels_c[d])
               for d in labels_base if labels_base[d] != labels_c.get(d, labels_base[d])}

    vault_changes = {d: v for d, v in changes.items() if d >= pd.Timestamp("2023-01-01")}

    cliff_flag = "CLIFF" if len(changes) >= 20 else ("mild" if len(changes) > 3 else "stable")
    print(f"{ex_date}  div=${amount:.4f}  drift={actual_drift_pct:.3f}%  "
          f"→ {len(changes):3d} label changes  {cliff_flag}")
    if vault_changes:
        print(f"  VAULT affected: {len(vault_changes)} days: {[str(d.date()) for d in sorted(vault_changes)]}")

    cliff_results.append({
        "ex_date": ex_date, "amount": amount, "factor": factor,
        "actual_drift_pct": actual_drift_pct, "n_changes": len(changes),
        "vault_changes": len(vault_changes), "cliff": cliff_flag,
    })

if TMP.exists():
    TMP.unlink()

print()
print("=" * 70)
print("FINAL SUMMARY")
print()
print(f"{'Ex-div':<14} {'Div $':>7} {'Drift%':>8} {'Labels Δ':>10} {'Vault Δ':>9} {'Cliff?'}")
print("-" * 60)
for r in cliff_results:
    print(f"{r['ex_date']:<14} {r['amount']:>7.4f} {r['actual_drift_pct']:>7.3f}% "
          f"{r['n_changes']:>10d} {r['vault_changes']:>9d}  {r['cliff']}")

total_cliffs = sum(1 for r in cliff_results if r["cliff"] == "CLIFF")
total_label_changes = sum(r["n_changes"] for r in cliff_results)
total_vault_changes = sum(r["vault_changes"] for r in cliff_results)

print()
print(f"Ex-divs that triggered CLIFF (≥20 label changes): {total_cliffs} / {len(drifted)} drifted")
print(f"Total label changes summed across all drifted dates: {total_label_changes}")
print(f"  [Note: changes from earlier dates compound — do NOT add; run cumulative test for full impact]")
print(f"Vault-period labels affected: {total_vault_changes} instances across drifted ex-divs")
print()

if total_cliffs > 0:
    print("FINDING: Multiple ex-div dates triggered cliff in CSV (labels already wrong).")
    print("Backtest/vault IS/OOS results sit on a CSV with compounded adjustment drift.")
    print("The 46-change Dec 2024 finding was NOT the only cliff — earlier ex-divs also cliffed.")
else:
    print("FINDING: Only the last drifted date (Dec 2024) causes cliff-level label changes.")
    print("Earlier drifted dates (if any) have drift but don't reach cliff threshold.")

# ── Cumulative impact: apply ALL missing adjustments at once ──────────────────
if len(drifted) > 1:
    print()
    print("=" * 70)
    print("CUMULATIVE TEST: all drifted adjustments applied together")
    df_cum = csv_df.copy()
    for r in drifted:
        ex_ts = pd.Timestamp(r["ex_date"])
        before = df_cum[df_cum["date"] < ex_ts]
        if len(before) == 0:
            continue
        p_prev = float(before.iloc[-1]["close"])
        factor = (p_prev - r["amount"]) / p_prev
        df_cum.loc[df_cum["date"] < ex_ts, "close"] *= factor

    df_cum["date"] = df_cum["date"].dt.strftime("%Y-%m-%d")
    df_cum.to_csv(TMP, index=False)
    bench_cum = benchmark_daily(str(TMP))
    labels_cum = label_regimes(bench_cum, "2018-01-01", 3, "2024-12-31")
    if TMP.exists():
        TMP.unlink()

    cum_changes = {d: (labels_base[d], labels_cum[d])
                   for d in labels_base if labels_base[d] != labels_cum.get(d, labels_base[d])}
    cum_vault = {d: v for d, v in cum_changes.items() if d >= pd.Timestamp("2023-01-01")}
    print(f"Total label changes (all corrections together): {len(cum_changes)}")
    print(f"Vault-period changes: {len(cum_vault)}")
    if cum_vault:
        from collections import Counter
        types = Counter(v for v in cum_vault.values())
        print(f"Vault change types: {dict(types)}")
        print(f"Vault change dates: {[str(d.date()) for d in sorted(cum_vault)]}")
