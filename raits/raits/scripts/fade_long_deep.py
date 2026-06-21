"""
Deep analysis of LONG FADE trades — same methodology as SHORT FADE analysis.
Goal: find if ANY condition makes LONG FADE viable, or confirm it's structurally broken.

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_long_deep.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

SNAP_DIR    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
BASELINE    = os.path.join(SNAP_DIR, "results_baseline_no_filter.pkl")
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


def compute_spy_or(spy_df, date):
    day = spy_df[spy_df.index.normalize() == pd.Timestamp(date).normalize()]
    or_bars = day.between_time("09:30", "09:44")
    if or_bars.empty:
        return None, None
    return float(or_bars["high"].max()), float(or_bars["low"].min())


def spy_status_at(spy_df, entry_time):
    ts = pd.Timestamp(entry_time)
    or_high, or_low = compute_spy_or(spy_df, ts.date())
    if or_high is None:
        return "UNKNOWN"
    day_bars = spy_df[spy_df.index.normalize() == ts.normalize()]
    bars_before = day_bars[day_bars.index <= ts]
    if bars_before.empty:
        return "UNKNOWN"
    spy_close = float(bars_before.iloc[-1]["close"])
    if spy_close > or_high:
        return "UP"
    elif spy_close < or_low:
        return "DOWN"
    return "RANGE"


def div(label, w=68):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


def table(df, group_col):
    if df.empty or group_col not in df.columns:
        print("  (no data)")
        return
    grp = df.groupby(group_col)["net_pnl"].agg(
        Trades="count", Win=lambda x: (x > 0).sum(), Avg="mean", Total="sum"
    ).reset_index()
    grp["Win%"] = (grp["Win"] / grp["Trades"] * 100).round(1)
    grp["Avg"]  = grp["Avg"].round(2)
    grp["Total"]= grp["Total"].round(0).astype(int)
    print(grp[[group_col, "Trades", "Win%", "Avg", "Total"]].sort_values("Total", ascending=False).to_string(index=False))


# ── Load ──────────────────────────────────────────────────────────────────────
all_trades = load_trades(BASELINE)
with open(PICKLE_5MIN, "rb") as f:
    market = pickle.load(f)
spy = market["SPY"]
spy.index = pd.DatetimeIndex(spy.index)
spy.columns = [c.lower() for c in spy.columns]

fade = all_trades[all_trades["strategy_type"] == "FADE"].copy()
long_fade = fade[fade["direction"] == "LONG"].copy()
print(f"LONG FADE: {len(long_fade)} trades across 3 years")
print(f"Total P&L: ${long_fade['net_pnl'].sum():+,.0f}  |  Win rate: {(long_fade['net_pnl']>0).mean()*100:.1f}%")

# Compute SPY status
print("Computing SPY status...")
long_fade["spy_status"] = [spy_status_at(spy, row["entry_time"]) for _, row in long_fade.iterrows()]
long_fade["hour"] = pd.to_datetime(long_fade["entry_time"]).dt.hour

# ── 1. By year ─────────────────────────────────────────────────────────────────
div("BY YEAR")
table(long_fade, "year")

# ── 2. Exit reason ─────────────────────────────────────────────────────────────
div("BY EXIT REASON")
table(long_fade, "exit_reason")

# ── 3. SPY status ──────────────────────────────────────────────────────────────
div("BY SPY STATUS")
print("  UP   = SPY above OR high (bullish) — for LONG FADE, this should be favorable")
print("  DOWN = SPY below OR low (bearish)  — for LONG FADE, this should be worst")
print("  RANGE= SPY inside OR (ranging)")
table(long_fade, "spy_status")

# ── 4. Regime ──────────────────────────────────────────────────────────────────
div("BY HMM REGIME")
table(long_fade, "hmm_state")

# ── 5. Entry hour ──────────────────────────────────────────────────────────────
div("BY ENTRY HOUR")
table(long_fade, "hour")

# ── 6. Ticker ──────────────────────────────────────────────────────────────────
div("BY TICKER")
table(long_fade, "ticker")

# ── 7. SPY × Regime ────────────────────────────────────────────────────────────
div("SPY STATUS × REGIME")
long_fade["spy_regime"] = long_fade["spy_status"] + " | " + long_fade["hmm_state"]
table(long_fade, "spy_regime")

# ── 8. SPY × Hour ──────────────────────────────────────────────────────────────
div("SPY STATUS × ENTRY HOUR")
long_fade["spy_hour"] = long_fade["spy_status"] + " | hour=" + long_fade["hour"].astype(str)
table(long_fade, "spy_hour")

# ── 9. Entry depth (risk per share) ───────────────────────────────────────────
if "stop" in long_fade.columns:
    long_fade["risk_per_share"] = (long_fade["entry_price"] - long_fade["stop"]).abs()
    edges = [long_fade["risk_per_share"].quantile(0.33), long_fade["risk_per_share"].quantile(0.67)]
    labels = [f"Tight(<={edges[0]:.2f})", "Medium", f"Deep(>{edges[1]:.2f})"]
    long_fade["depth"] = pd.cut(long_fade["risk_per_share"],
                                 bins=[-np.inf, edges[0], edges[1], np.inf],
                                 labels=labels)
    div("BY ENTRY DEPTH (risk per share terciles)")
    table(long_fade, "depth")

# ── 10. SPY × Ticker (top contributors) ───────────────────────────────────────
div("TOP 5 LOSING TICKERS for LONG FADE")
tk = long_fade.groupby("ticker")["net_pnl"].agg(
    Trades="count", Win=lambda x: (x > 0).sum(), Avg="mean", Total="sum"
).reset_index()
tk["Win%"] = (tk["Win"] / tk["Trades"] * 100).round(1)
tk["Avg"]  = tk["Avg"].round(2)
tk["Total"]= tk["Total"].round(0).astype(int)
print("Losers:")
print(tk.nsmallest(8, "Total")[["ticker","Trades","Win%","Avg","Total"]].to_string(index=False))
print("\nWinners:")
print(tk.nlargest(5, "Total")[["ticker","Trades","Win%","Avg","Total"]].to_string(index=False))

# ── 11. Compare LONG FADE winners vs losers directly ──────────────────────────
div("WINNERS vs LOSERS — full trade detail (sorted by net_pnl)")
cols = ["year","entry_time","ticker","spy_status","hmm_state","hour","exit_reason","net_pnl"]
avail = [c for c in cols if c in long_fade.columns]
print("\n  ALL LONG FADE trades (sorted worst → best):")
print(long_fade[avail].sort_values("net_pnl").to_string(index=False))

# ── 12. Check if there's ANY profitable subset ───────────────────────────────
div("BEST SUBSET SEARCH — is any slice of LONG FADE profitable?")
for spy_s in ["DOWN", "RANGE", "UP"]:
    for regime in long_fade["hmm_state"].dropna().unique():
        subset = long_fade[(long_fade["spy_status"] == spy_s) & (long_fade["hmm_state"] == regime)]
        if len(subset) >= 5:
            pnl = subset["net_pnl"].sum()
            win = (subset["net_pnl"] > 0).mean() * 100
            print(f"  SPY={spy_s:<6} Regime={regime:<8} n={len(subset):>3}  Win={win:.0f}%  Total=${pnl:>+.0f}")
