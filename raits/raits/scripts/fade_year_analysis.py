"""
Phân tích tại sao FADE lỗ trong 2020 và 2022 (Scenario G results).

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_year_analysis.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

SNAP_DIR   = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
SCENE_G    = os.path.join(SNAP_DIR, "results_scenario_g.pkl")
BASELINE   = os.path.join(SNAP_DIR, "results_baseline_no_filter.pkl")
PICKLE_5MIN = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")


def load_trades(path):
    with open(path, "rb") as f:
        results = pickle.load(f)
    rows = []
    for window in results:
        yr = window.get("label", "?")
        for t in window.get("trades", []):
            d = t.__dict__.copy() if hasattr(t, "__dict__") else dict(t)
            d["year"] = yr
            rows.append(d)
    df = pd.DataFrame(rows)
    if "strategy" in df.columns:
        df["strategy_type"] = df["strategy"]
    return df


def spy_status_at(spy_df, entry_time):
    ts = pd.Timestamp(entry_time)
    day = spy_df[spy_df.index.normalize() == ts.normalize()]
    or_bars = day[(day.index.time >= pd.Timestamp("09:30").time()) &
                  (day.index.time <= pd.Timestamp("09:44").time())]
    if or_bars.empty:
        return "UNKNOWN"
    or_high = float(or_bars["high"].max())
    or_low  = float(or_bars["low"].min())
    bars_before = day[day.index <= ts]
    if bars_before.empty:
        return "UNKNOWN"
    spy_close = float(bars_before.iloc[-1]["close"])
    if spy_close > or_high:   return "UP"
    if spy_close < or_low:    return "DOWN"
    return "RANGE"


def div(label, w=70):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


def table(df, col):
    if df.empty or col not in df.columns:
        print("  (no data)")
        return
    g = df.groupby(col)["net_pnl"].agg(
        Trades="count", Win=lambda x: (x > 0).sum(), Avg="mean", Total="sum"
    ).reset_index()
    g["Win%"]  = (g["Win"] / g["Trades"] * 100).round(1)
    g["Avg"]   = g["Avg"].round(2)
    g["Total"] = g["Total"].round(0).astype(int)
    print(g[[col, "Trades", "Win%", "Avg", "Total"]].sort_values("Total", ascending=False).to_string(index=False))


# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading Scenario G trades...")
sg = load_trades(SCENE_G)
with open(PICKLE_5MIN, "rb") as f:
    mkt = pickle.load(f)
spy = mkt["SPY"]
spy.index = pd.DatetimeIndex(spy.index)
spy.columns = [c.lower() for c in spy.columns]

fade = sg[sg["strategy_type"] == "FADE"].copy()
fade["hour"]       = pd.to_datetime(fade["entry_time"]).dt.hour
fade["spy_status"] = [spy_status_at(spy, r["entry_time"]) for _, r in fade.iterrows()]

div("FADE OVERVIEW by YEAR × DIRECTION")
fade["yr_dir"] = fade["year"] + " " + fade["direction"]
table(fade, "yr_dir")

# ── Per-year deep dive ────────────────────────────────────────────────────────
for yr in ["2020", "2022"]:
    fy = fade[fade["year"] == yr]
    div(f"YEAR {yr} — {len(fy)} trades, ${fy['net_pnl'].sum():+.0f}")

    print(f"\n  Direction:")
    table(fy, "direction")

    print(f"\n  Exit reason:")
    table(fy, "exit_reason")

    print(f"\n  SPY status:")
    table(fy, "spy_status")

    print(f"\n  Entry hour:")
    table(fy, "hour")

    print(f"\n  HMM regime:")
    table(fy, "hmm_state")

    print(f"\n  Ticker:")
    table(fy, "ticker")

    print(f"\n  SPY × Direction:")
    fy2 = fy.copy()
    fy2["spy_dir"] = fy2["spy_status"] + " | " + fy2["direction"]
    table(fy2, "spy_dir")

    print(f"\n  Hour × Direction:")
    fy2["hr_dir"] = "h" + fy2["hour"].astype(str) + " | " + fy2["direction"]
    table(fy2, "hr_dir")

    # Cluster days — multiple FADE trades same day
    fy2["date"] = pd.to_datetime(fy2["entry_time"]).dt.date
    day_counts = fy2.groupby("date")["net_pnl"].agg(n="count", total="sum")
    cluster_days = day_counts[day_counts["n"] >= 3]
    if not cluster_days.empty:
        print(f"\n  CLUSTER DAYS (≥3 FADE trades same day):")
        print(cluster_days.sort_values("total").to_string())

    print(f"\n  Worst 10 trades:")
    cols = ["entry_time", "ticker", "direction", "spy_status", "hour", "hmm_state", "exit_reason", "net_pnl"]
    avail = [c for c in cols if c in fy2.columns]
    print(fy2[avail].nsmallest(10, "net_pnl").to_string(index=False))

div("COMPARE: 2021 (profitable) vs 2020+2022 (losing)")
print("\n  SPY status distribution:")
for yr in ["2020", "2021", "2022"]:
    fy = fade[fade["year"] == yr]
    spy_counts = fy["spy_status"].value_counts()
    total_pnl  = fy["net_pnl"].sum()
    print(f"  {yr}: UP={spy_counts.get('UP',0)} DOWN={spy_counts.get('DOWN',0)} RANGE={spy_counts.get('RANGE',0)}  total=${total_pnl:+.0f}")

print("\n  Regime distribution:")
for yr in ["2020", "2021", "2022"]:
    fy = fade[fade["year"] == yr]
    rc = fy["hmm_state"].value_counts()
    print(f"  {yr}: Calm={rc.get('Calm',0)} Normal={rc.get('Normal',0)} Stress={rc.get('Stress',0)}")

print("\n  Direction split:")
for yr in ["2020", "2021", "2022"]:
    fy = fade[fade["year"] == yr]
    longs  = fy[fy["direction"] == "LONG"]
    shorts = fy[fy["direction"] == "SHORT"]
    print(f"  {yr}: LONG {len(longs)} trades ${longs['net_pnl'].sum():+.0f}  |  SHORT {len(shorts)} trades ${shorts['net_pnl'].sum():+.0f}")

print("\n  Win% by year:")
for yr in ["2020", "2021", "2022"]:
    fy  = fade[fade["year"] == yr]
    win = (fy["net_pnl"] > 0).mean() * 100
    avg = fy["net_pnl"].mean()
    print(f"  {yr}: {win:.1f}% win, avg ${avg:+.2f}/trade")

div("STOP_HIT analysis — stop out rates")
for yr in ["2020", "2021", "2022"]:
    fy = fade[fade["year"] == yr]
    stops = fy[fy["exit_reason"] == "STOP_HIT"]
    wins  = fy[fy["exit_reason"] == "TARGET_HIT"]
    print(f"  {yr}: STOP_HIT={len(stops)} ({len(stops)/len(fy)*100:.0f}%)  avg_loss=${stops['net_pnl'].mean():+.2f}"
          f"  |  TARGET={len(wins)} ({len(wins)/len(fy)*100:.0f}%)  avg_win=${wins['net_pnl'].mean():+.2f}"
          if not stops.empty and not wins.empty else f"  {yr}: insufficient data")
