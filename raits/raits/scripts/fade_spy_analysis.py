"""
Phân tích FADE trades theo SPY OR direction tại thời điểm entry.
Hypothesis: cluster losses xảy ra khi SPY đang trending (broke OR).
FADE SHORT nên bị skip khi SPY đang above its OR (bullish day).

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_spy_analysis.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np
from datetime import time as dtime

PICKLE_RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_results.pkl")
PICKLE_5MIN    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")


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


def compute_spy_or(spy_df, date):
    """9:30-9:45 OR for SPY on a given date (ET naive)."""
    day = spy_df[spy_df.index.normalize() == pd.Timestamp(date).normalize()]
    or_bars = day.between_time("09:30", "09:44")
    if or_bars.empty:
        return None, None
    return float(or_bars["high"].max()), float(or_bars["low"].min())


def spy_status_at(spy_df, date, entry_time):
    """
    Returns 'UP' if SPY close > OR high, 'DOWN' if < OR low, 'RANGE' otherwise.
    Uses the SPY bar at entry_time.
    """
    or_high, or_low = compute_spy_or(spy_df, date)
    if or_high is None:
        return "UNKNOWN"
    ts = pd.Timestamp(entry_time)
    # Get most recent SPY bar at or before entry_time
    day_bars = spy_df[spy_df.index.normalize() == ts.normalize()]
    bars_before = day_bars[day_bars.index <= ts]
    if bars_before.empty:
        return "UNKNOWN"
    spy_close = float(bars_before.iloc[-1]["close"])
    if spy_close > or_high:
        return "UP"
    elif spy_close < or_low:
        return "DOWN"
    else:
        return "RANGE"


def div(label, w=70):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


def summary_table(df, group_col):
    grp = df.groupby(group_col)["net_pnl"].agg(
        Trades="count",
        Win=lambda x: (x > 0).sum(),
        Avg="mean",
        Total="sum",
    ).reset_index()
    grp["Win%"] = (grp["Win"] / grp["Trades"] * 100).round(1)
    grp["Avg"]   = grp["Avg"].round(2)
    grp["Total"] = grp["Total"].round(0).astype(int)
    grp = grp.sort_values("Total", ascending=False)
    print(grp[[group_col, "Trades", "Win%", "Avg", "Total"]].to_string(index=False))


# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading trades...")
all_trades = load_trades(PICKLE_RESULTS)
fade = all_trades[all_trades["strategy_type"] == "FADE"].copy()

print("Loading SPY 5-min data...")
with open(PICKLE_5MIN, "rb") as f:
    market = pickle.load(f)
spy = market.get("SPY")
if spy is None:
    print("ERROR: SPY data not found in pickle")
    sys.exit(1)

spy.index = pd.DatetimeIndex(spy.index)
spy.columns = [c.lower() for c in spy.columns]

# ── Compute SPY status for each FADE trade ───────────────────────────────────
print(f"Analyzing {len(fade)} FADE trades...")
spy_statuses = []
spy_or_highs = []
spy_or_lows  = []
spy_closes   = []

for _, row in fade.iterrows():
    entry_ts = pd.Timestamp(row["entry_time"])
    date = entry_ts.date()
    status = spy_status_at(spy, date, entry_ts)
    or_high, or_low = compute_spy_or(spy, date)
    day_bars = spy[spy.index.normalize() == entry_ts.normalize()]
    bars_before = day_bars[day_bars.index <= entry_ts]
    spy_close = float(bars_before.iloc[-1]["close"]) if not bars_before.empty else np.nan
    spy_statuses.append(status)
    spy_or_highs.append(or_high)
    spy_or_lows.append(or_low)
    spy_closes.append(spy_close)

fade["spy_status"]   = spy_statuses
fade["spy_or_high"]  = spy_or_highs
fade["spy_or_low"]   = spy_or_lows
fade["spy_close_at_entry"] = spy_closes
fade["spy_or_range"] = fade["spy_or_high"] - fade["spy_or_low"]
fade["spy_vs_or_pct"] = (fade["spy_close_at_entry"] - fade["spy_or_low"]) / fade["spy_or_range"]

# ── Results ───────────────────────────────────────────────────────────────────
div("FADE P&L BY SPY STATUS AT ENTRY")
print("  UP   = SPY above OR high at entry time (bullish, market trending up)")
print("  DOWN = SPY below OR low at entry time (bearish, market trending down)")
print("  RANGE= SPY inside OR (ranging, no clear direction)")
summary_table(fade, "spy_status")

div("FADE P&L BY DIRECTION × SPY STATUS")
fade["dir_spy"] = fade["direction"] + " | SPY=" + fade["spy_status"]
summary_table(fade, "dir_spy")

div("FADE SHORT: breakdown by SPY status (year)")
fade_short = fade[fade["direction"] == "SHORT"].copy()
print("\n  SHORT FADE by SPY status:")
summary_table(fade_short, "spy_status")
print("\n  SHORT FADE by SPY status × year:")
fade_short["spy_year"] = fade_short["spy_status"] + " " + fade_short["year"].astype(str)
summary_table(fade_short, "spy_year")

div("SIMULATION: Skip FADE SHORT when SPY is UP (trending bullish)")
skip_mask = (fade["direction"] == "SHORT") & (fade["spy_status"] == "UP")
kept = fade[~skip_mask]
skipped = fade[skip_mask]
print(f"  Trades kept:    {len(kept)}  P&L: ${kept['net_pnl'].sum():+,.0f}")
print(f"  Trades skipped: {len(skipped)}  P&L if taken: ${skipped['net_pnl'].sum():+,.0f}")
print(f"  Net improvement from filter: ${-skipped['net_pnl'].sum():+,.0f}")
print()
for yr in sorted(kept["year"].unique()):
    k = kept[kept["year"]==yr]
    s = skipped[skipped["year"]==yr]
    print(f"  {yr}: kept {len(k)}T ${k['net_pnl'].sum():+,.0f}  |  skipped {len(s)}T ${s['net_pnl'].sum():+,.0f}")

div("SIMULATION: Skip FADE when SPY trending in same direction as original breakout")
# SHORT FADE (fading failed up-breakout): skip if SPY UP (same direction as breakout)
# LONG FADE (fading failed down-breakdown): skip if SPY DOWN
def should_skip(row):
    if row["direction"] == "SHORT" and row["spy_status"] == "UP":
        return True
    if row["direction"] == "LONG" and row["spy_status"] == "DOWN":
        return True
    return False

fade["skip_spy_aligned"] = fade.apply(should_skip, axis=1)
kept2 = fade[~fade["skip_spy_aligned"]]
skip2 = fade[fade["skip_spy_aligned"]]
print(f"  Trades kept:    {len(kept2)}  P&L: ${kept2['net_pnl'].sum():+,.0f}")
print(f"  Trades skipped: {len(skip2)}  P&L if taken: ${skip2['net_pnl'].sum():+,.0f}")
print(f"  Net improvement: ${-skip2['net_pnl'].sum():+,.0f}")

div("CLUSTER LOSS DAYS — worst FADE days and SPY status")
fade["date"] = pd.to_datetime(fade["entry_time"]).dt.date
day_pnl = fade.groupby("date").agg(
    n_trades=("net_pnl","count"),
    total_pnl=("net_pnl","sum"),
    spy_status=("spy_status","first"),
    directions=("direction", lambda x: ",".join(sorted(set(x)))),
).reset_index()
worst = day_pnl.nsmallest(15, "total_pnl")
print(worst[["date","n_trades","spy_status","directions","total_pnl"]].to_string(index=False))

div("SPY STATUS distribution on cluster loss days (≥3 FADE trades, total <-$100)")
cluster_days = day_pnl[(day_pnl["n_trades"] >= 3) & (day_pnl["total_pnl"] < -100)]
print(cluster_days[["date","n_trades","spy_status","directions","total_pnl"]].to_string(index=False))
print(f"\n  SPY status on cluster loss days:")
print(cluster_days["spy_status"].value_counts().to_string())
