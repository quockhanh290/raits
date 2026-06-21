"""
Check: nếu dùng ATR rank filter (exclude top N highest-ATR tickers mỗi ngày),
ngoài TSLA thì còn trade LONG FADE nào khác bị filter?

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_atr_filter.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

SNAP_DIR     = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
BASELINE     = os.path.join(SNAP_DIR, "results_baseline_no_filter.pkl")
PICKLE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")

ATR_PERIOD = 14


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


def compute_atr_pct(daily_df, period=14):
    """14-day ATR% = ATR / prior close. Normalized by price."""
    df = daily_df.copy()
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr / prev_close  # normalize


def div(label, w=70):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading trades...")
all_trades = load_trades(BASELINE)
long_fade  = all_trades[(all_trades["strategy_type"] == "FADE") &
                         (all_trades["direction"] == "LONG")].copy()
long_fade["date"] = pd.to_datetime(long_fade["entry_time"]).dt.date

print("Loading daily data...")
with open(PICKLE_DAILY, "rb") as f:
    daily = pickle.load(f)

# ── Compute ATR for every ticker on every date ────────────────────────────────
print("Computing ATR for all tickers...")
atr_by_date = {}  # {date: {ticker: atr_value}}

# Get all unique dates in LONG FADE trades
trade_dates = sorted(long_fade["date"].unique())

# Build ATR series for each ticker
ticker_atr_series = {}
for ticker, df in daily.items():
    if ticker == "SPY":
        continue
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.DatetimeIndex(df.index)
    df = df.sort_index()
    if len(df) < ATR_PERIOD + 1:
        continue
    atr_s = compute_atr_pct(df, ATR_PERIOD)
    ticker_atr_series[ticker] = atr_s

# For each trade date, get ATR rank snapshot (use ATR as of prior close)
for date in trade_dates:
    ts = pd.Timestamp(date)
    day_atrs = {}
    for ticker, atr_s in ticker_atr_series.items():
        # ATR available at open = ATR computed with data up to prior day
        prior = atr_s[atr_s.index < ts]
        if prior.empty:
            continue
        day_atrs[ticker] = float(prior.iloc[-1])
    atr_by_date[date] = day_atrs

# ── Assign ATR rank to each LONG FADE trade ───────────────────────────────────
ranks_top1 = []   # rank of this ticker (1=highest ATR in universe)
ranks_top2 = []
atr_values = []
universe_sizes = []

for _, row in long_fade.iterrows():
    date   = row["date"]
    ticker = row["ticker"]
    atrs   = atr_by_date.get(date, {})
    if not atrs or ticker not in atrs:
        ranks_top1.append(None)
        ranks_top2.append(None)
        atr_values.append(None)
        universe_sizes.append(len(atrs))
        continue
    sorted_atrs = sorted(atrs.items(), key=lambda x: x[1], reverse=True)
    rank = next((i+1 for i, (t, _) in enumerate(sorted_atrs) if t == ticker), None)
    ranks_top1.append(rank == 1)
    ranks_top2.append(rank is not None and rank <= 2)
    atr_values.append(atrs[ticker])
    universe_sizes.append(len(atrs))

long_fade = long_fade.copy()
long_fade["atr_value"] = atr_values
long_fade["is_top1_atr"]  = ranks_top1
long_fade["is_top2_atr"]  = ranks_top2

# ── Results ───────────────────────────────────────────────────────────────────
div("ATR RANK distribution of LONG FADE trades")
top1 = long_fade[long_fade["is_top1_atr"] == True]
top2 = long_fade[long_fade["is_top2_atr"] == True]
rest = long_fade[long_fade["is_top2_atr"] == False]

print(f"  Top-1 ATR trades:  {len(top1):>3}  P&L: ${top1['net_pnl'].sum():>+8.0f}")
print(f"  Top-2 ATR trades:  {len(top2):>3}  P&L: ${top2['net_pnl'].sum():>+8.0f}")
print(f"  Rest (not top-2):  {len(rest):>3}  P&L: ${rest['net_pnl'].sum():>+8.0f}")

div("TOP-2 ATR FILTERED trades — which tickers?")
if not top2.empty:
    tk = top2.groupby("ticker")["net_pnl"].agg(
        Trades="count", Win=lambda x: (x>0).sum(), Avg="mean", Total="sum"
    ).reset_index()
    tk["Win%"] = (tk["Win"] / tk["Trades"] * 100).round(1)
    tk["Avg"]  = tk["Avg"].round(2)
    tk["Total"]= tk["Total"].round(0).astype(int)
    print(tk.sort_values("Total").to_string(index=False))

div("TOP-2 ATR FILTERED — full trade list")
cols = ["year","entry_time","ticker","atr_value","exit_reason","net_pnl"]
avail = [c for c in cols if c in top2.columns]
pd.set_option("display.float_format", "{:.2f}".format)
print(top2[avail].sort_values("net_pnl").to_string(index=False))

div("REST (not top-2 ATR) — breakdown")
print(f"  Total: {len(rest)} trades, ${rest['net_pnl'].sum():+,.0f}, win={( rest['net_pnl']>0).mean()*100:.1f}%")
print()
by_yr = rest.groupby("year")["net_pnl"].agg(n="count", win=lambda x:(x>0).sum(), total="sum").reset_index()
by_yr["win%"] = (by_yr["win"]/by_yr["n"]*100).round(1)
print(by_yr.to_string(index=False))

div("IMPACT: top-1 vs top-2 filter")
for n, mask in [("Top-1", long_fade["is_top1_atr"]==True),
                ("Top-2", long_fade["is_top2_atr"]==True)]:
    filtered_out = long_fade[mask]
    kept         = long_fade[~mask]
    print(f"\n  Filter: exclude {n} ATR")
    print(f"    Filtered: {len(filtered_out)} trades  P&L avoided: ${filtered_out['net_pnl'].sum():>+.0f}")
    print(f"    Kept:     {len(kept)} trades  P&L kept:   ${kept['net_pnl'].sum():>+.0f}")

div("REMAINING LOSERS after top-2 ATR filter (by ticker)")
if not rest.empty:
    tk2 = rest.groupby("ticker")["net_pnl"].agg(
        Trades="count", Win=lambda x:(x>0).sum(), Avg="mean", Total="sum"
    ).reset_index()
    tk2["Win%"] = (tk2["Win"]/tk2["Trades"]*100).round(1)
    tk2["Avg"]  = tk2["Avg"].round(2)
    tk2["Total"]= tk2["Total"].round(0).astype(int)
    print("  Losers:")
    print(tk2.nsmallest(8,"Total")[["ticker","Trades","Win%","Avg","Total"]].to_string(index=False))
    print("\n  Winners:")
    print(tk2.nlargest(8,"Total")[["ticker","Trades","Win%","Avg","Total"]].to_string(index=False))
