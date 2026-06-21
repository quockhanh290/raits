"""
Compare FADE trades between two snapshots to understand what changed.
Usage:
    cd d:\raits\raits
    python raits/scripts/fade_compare.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

SNAP_DIR  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
BASELINE  = os.path.join(SNAP_DIR, "results_baseline_no_filter.pkl")
CURRENT   = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_results.pkl")


def load_trades(path, label):
    with open(path, "rb") as f:
        results = pickle.load(f)
    rows = []
    for window in results:
        yr = window.get("label", "?")
        for t in window.get("trades", []):
            d = t.__dict__.copy() if hasattr(t, "__dict__") else dict(t)
            d["year"] = yr
            d["source"] = label
            rows.append(d)
    return pd.DataFrame(rows)


def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


base = load_trades(BASELINE, "baseline")
curr = load_trades(CURRENT,  "short_only")

for df in [base, curr]:
    if "strategy" in df.columns:
        df["strategy_type"] = df["strategy"]

fade_base = base[base["strategy_type"] == "FADE"].copy()
fade_curr = curr[curr["strategy_type"] == "FADE"].copy()

# ── 1. Overview ───────────────────────────────────────────────────────────────
div("OVERVIEW")
for label, df in [("BASELINE (both directions)", fade_base), ("SHORT ONLY", fade_curr)]:
    total = df["net_pnl"].sum()
    wins  = (df["net_pnl"] > 0).sum()
    n     = len(df)
    print(f"  {label}: {n} trades, {wins/n*100:.1f}% win, ${total:+,.0f}")

# ── 2. All FADE trades from both, side by side by date ───────────────────────
div("ALL FADE TRADES — BASELINE (chronological)")
cols = ["year", "entry_time", "ticker", "direction", "entry_price", "shares",
        "stop", "target", "exit_reason", "exit_price", "net_pnl"]
avail = [c for c in cols if c in fade_base.columns]
fade_base_sorted = fade_base[avail].sort_values("entry_time")
pd.set_option("display.max_rows", 300)
pd.set_option("display.width", 180)
pd.set_option("display.float_format", "{:.2f}".format)
print(fade_base_sorted.to_string(index=False))

div("ALL FADE TRADES — SHORT ONLY (chronological)")
avail2 = [c for c in cols if c in fade_curr.columns]
fade_curr_sorted = fade_curr[avail2].sort_values("entry_time")
print(fade_curr_sorted.to_string(index=False))

# ── 3. Trades that disappeared (in baseline but not current) ─────────────────
div("REMOVED TRADES (baseline had, short_only doesn't)")
base_ids = set(fade_base["trade_id"])
curr_ids = set(fade_curr["trade_id"])
removed  = fade_base[fade_base["trade_id"].isin(base_ids - curr_ids)][avail].sort_values("entry_time")
print(f"  {len(removed)} trades removed")
print(removed.to_string(index=False))

# ── 4. Trades that appeared (in current but not baseline) ────────────────────
div("NEW TRADES (short_only has, baseline didn't)")
new_trades = fade_curr[fade_curr["trade_id"].isin(curr_ids - base_ids)][avail2].sort_values("entry_time")
print(f"  {len(new_trades)} new trades")
print(new_trades.to_string(index=False))

# ── 5. P&L impact breakdown ───────────────────────────────────────────────────
div("P&L IMPACT")
removed_pnl = removed["net_pnl"].sum() if not removed.empty else 0
new_pnl     = new_trades["net_pnl"].sum() if not new_trades.empty else 0
print(f"  Removed trades P&L: ${removed_pnl:+,.2f}")
print(f"  New trades P&L:     ${new_pnl:+,.2f}")
print(f"  Net change:         ${new_pnl - removed_pnl:+,.2f}")

# ── 6. Removed LONG trades that were winners (the cost of the fix) ─────────
if "direction" in removed.columns:
    removed_long_win = removed[(removed["direction"] == "LONG") & (removed["net_pnl"] > 0)]
    removed_long_loss= removed[(removed["direction"] == "LONG") & (removed["net_pnl"] <= 0)]
    div("REMOVED LONG FADE: winners vs losers")
    print(f"  Winners removed: {len(removed_long_win)} trades, ${removed_long_win['net_pnl'].sum():+,.2f}")
    print(f"  Losers  removed: {len(removed_long_loss)} trades, ${removed_long_loss['net_pnl'].sum():+,.2f}")

# ── 7. By year and direction breakdown of new vs removed ─────────────────────
div("REMOVED TRADES by year + direction")
if not removed.empty and "direction" in removed.columns:
    grp = removed.groupby(["year","direction"])["net_pnl"].agg(n="count", total="sum").reset_index()
    print(grp.to_string(index=False))

div("NEW TRADES by year + direction")
if not new_trades.empty and "direction" in new_trades.columns:
    grp2 = new_trades.groupby(["year","direction"])["net_pnl"].agg(n="count", total="sum").reset_index()
    print(grp2.to_string(index=False))
