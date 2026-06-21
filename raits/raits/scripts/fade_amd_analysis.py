"""
AMD LONG FADE deep analysis.
Câu hỏi: tại sao AMD profitable khi ở top-2 ATR%?

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_amd_analysis.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

SNAP_DIR     = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
BASELINE     = os.path.join(SNAP_DIR, "results_baseline_no_filter.pkl")
PICKLE_5MIN  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")
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
    df = daily_df.copy()
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr / prev_close


def spy_status_at(spy_df, entry_time):
    ts = pd.Timestamp(entry_time)
    day = spy_df[spy_df.index.normalize() == ts.normalize()]
    or_bars = day.between_time("09:30", "09:44")
    if or_bars.empty:
        return "UNKNOWN"
    or_high = float(or_bars["high"].max())
    or_low  = float(or_bars["low"].min())
    bars_before = day[day.index <= ts]
    if bars_before.empty:
        return "UNKNOWN"
    spy_close = float(bars_before.iloc[-1]["close"])
    if spy_close > or_high:
        return "UP"
    elif spy_close < or_low:
        return "DOWN"
    return "RANGE"


def div(label, w=70):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


# ── Load ──────────────────────────────────────────────────────────────────────
all_trades = load_trades(BASELINE)
with open(PICKLE_5MIN, "rb") as f:
    market5 = pickle.load(f)
spy = market5["SPY"]
spy.index = pd.DatetimeIndex(spy.index)
spy.columns = [c.lower() for c in spy.columns]

with open(PICKLE_DAILY, "rb") as f:
    daily = pickle.load(f)

# Build ATR% series for all tickers
ticker_atr_pct = {}
for ticker, df in daily.items():
    if ticker == "SPY":
        continue
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.DatetimeIndex(df.index)
    df = df.sort_index()
    if len(df) < ATR_PERIOD + 1:
        continue
    ticker_atr_pct[ticker] = compute_atr_pct(df, ATR_PERIOD)

def get_atr_pct_rank(ticker, date):
    ts = pd.Timestamp(date)
    day_atrs = {}
    for t, atr_s in ticker_atr_pct.items():
        prior = atr_s[atr_s.index < ts]
        if prior.empty:
            continue
        day_atrs[t] = float(prior.iloc[-1])
    if not day_atrs or ticker not in day_atrs:
        return None, None, None
    sorted_atrs = sorted(day_atrs.items(), key=lambda x: x[1], reverse=True)
    rank = next((i+1 for i, (t, _) in enumerate(sorted_atrs) if t == ticker), None)
    atr_val = day_atrs[ticker]
    top2 = [t for t, _ in sorted_atrs[:2]]
    return rank, atr_val, top2

# ── Get all AMD LONG FADE trades ──────────────────────────────────────────────
fade  = all_trades[(all_trades["strategy_type"] == "FADE") & (all_trades["direction"] == "LONG")]
amd   = fade[fade["ticker"] == "AMD"].copy()
amd["date"]       = pd.to_datetime(amd["entry_time"]).dt.date
amd["hour"]       = pd.to_datetime(amd["entry_time"]).dt.hour
amd["spy_status"] = [spy_status_at(spy, r["entry_time"]) for _, r in amd.iterrows()]

# ATR% rank on each trade date
amd_ranks, amd_atrs, amd_top2 = [], [], []
for _, row in amd.iterrows():
    rank, atr_val, top2 = get_atr_pct_rank("AMD", row["date"])
    amd_ranks.append(rank)
    amd_atrs.append(atr_val)
    amd_top2.append(top2)

amd["atr_pct"]  = [f"{v:.3f}" if v else "?" for v in amd_atrs]
amd["atr_rank"] = amd_ranks
amd["top2"]     = [str(t) for t in amd_top2]
amd["in_top2"]  = [r is not None and r <= 2 for r in amd_ranks]

# R:R at entry
if "stop" in amd.columns and "target" in amd.columns:
    amd["risk"]    = (amd["entry_price"] - amd["stop"]).abs()
    amd["reward"]  = (amd["target"] - amd["entry_price"]).abs()
    amd["rr_ratio"]= (amd["reward"] / amd["risk"]).round(2)

div("ALL AMD LONG FADE TRADES — sorted by date")
show_cols = ["entry_time","hour","spy_status","hmm_state","atr_pct","atr_rank",
             "exit_reason","net_pnl","in_top2"]
if "rr_ratio" in amd.columns:
    show_cols.insert(-1, "rr_ratio")
avail = [c for c in show_cols if c in amd.columns]
pd.set_option("display.float_format", "{:.2f}".format)
pd.set_option("display.max_colwidth", 20)
print(amd[avail].sort_values("entry_time").to_string(index=False))

div("IN top-2 ATR% (4 trades, +$394) vs NOT in top-2 (7 trades, -$170)")
for grp_name, grp in [("IN top-2 ATR%", amd[amd["in_top2"]]),
                       ("NOT in top-2",  amd[~amd["in_top2"]])]:
    wins = (grp["net_pnl"] > 0).sum()
    print(f"\n  {grp_name}: {len(grp)} trades, {wins/len(grp)*100:.0f}% win, "
          f"${grp['net_pnl'].sum():+.0f}")
    sub_cols = ["entry_time","hour","spy_status","atr_pct","atr_rank","exit_reason","net_pnl"]
    avail2 = [c for c in sub_cols if c in grp.columns]
    print(grp[avail2].sort_values("net_pnl", ascending=False).to_string(index=False))

div("STRUCTURAL DIFFERENCES: top-2 vs rest")
for col in ["hour","spy_status","hmm_state","exit_reason"]:
    if col not in amd.columns:
        continue
    print(f"\n  By {col}:")
    for grp_name, grp in [("top-2", amd[amd["in_top2"]]),
                           ("rest",  amd[~amd["in_top2"]])]:
        summary = grp.groupby(col)["net_pnl"].agg(n="count", total="sum").reset_index()
        print(f"    [{grp_name}] {summary.to_string(index=False)}")

div("HYPOTHESIS CHECK: ATR% level when AMD is high-rank")
print("  When AMD is in top-2 ATR%, what's its ATR%?")
top2_atr = [float(v) for v in amd[amd["in_top2"]]["atr_pct"]]
rest_atr  = [float(v) for v in amd[~amd["in_top2"]]["atr_pct"]]
if top2_atr:
    print(f"  Top-2 ATR% values: {[f'{v:.3f}' for v in top2_atr]}")
    print(f"  Rest ATR% values:  {[f'{v:.3f}' for v in rest_atr]}")
    print(f"  Top-2 mean: {np.mean(top2_atr):.3f}  |  Rest mean: {np.mean(rest_atr):.3f}")

div("WHO ELSE WAS TOP-2 on days AMD was profitable?")
print("  (The stock AMD 'beat' to stay in the fade-allowed zone)")
for _, row in amd[~amd["in_top2"]].iterrows():
    _, _, top2_stocks = get_atr_pct_rank("AMD", row["date"])
    pnl = row["net_pnl"]
    print(f"  {row['entry_time']}  AMD rank={row['atr_rank']}  top-2={top2_stocks}  P&L={pnl:+.0f}")
