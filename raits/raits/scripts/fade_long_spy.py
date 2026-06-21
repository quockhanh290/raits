"""
Check LONG FADE trades vs SPY status.
Hypothesis: LONG FADE khi SPY=DOWN = same problem as SHORT FADE khi SPY=UP.
If confirmed: keep LONG FADE but filter out SPY=DOWN instead of removing all LONG FADE.

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_long_spy.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

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
print(f"Loaded {len(fade)} FADE trades ({(fade['direction']=='SHORT').sum()} SHORT, {(fade['direction']=='LONG').sum()} LONG)")

print("Computing SPY status...")
fade["spy_status"] = [spy_status_at(spy, row["entry_time"]) for _, row in fade.iterrows()]

# ── SHORT FADE by SPY (confirm earlier finding) ───────────────────────────────
div("SHORT FADE by SPY status (baseline, both directions)")
table(fade[fade["direction"] == "SHORT"], "spy_status")

# ── LONG FADE by SPY ──────────────────────────────────────────────────────────
div("LONG FADE by SPY status")
table(fade[fade["direction"] == "LONG"], "spy_status")

div("LONG FADE by SPY status × year")
long_fade = fade[fade["direction"] == "LONG"].copy()
long_fade["spy_year"] = long_fade["spy_status"] + " " + long_fade["year"].astype(str)
table(long_fade, "spy_year")

# ── Optimal filter per direction ──────────────────────────────────────────────
div("SIMULATION — Symmetric SPY filter (principled)")
print("  Rule: skip SHORT FADE when SPY=UP, skip LONG FADE when SPY=DOWN")
print("  (Don't fade against market trend — in either direction)")

skip_mask = (
    ((fade["direction"] == "SHORT") & (fade["spy_status"] == "UP")) |
    ((fade["direction"] == "LONG")  & (fade["spy_status"] == "DOWN"))
)
kept    = fade[~skip_mask]
skipped = fade[skip_mask]

print(f"\n  Kept:    {len(kept)} trades, P&L: ${kept['net_pnl'].sum():+,.0f}")
print(f"  Skipped: {len(skipped)} trades, P&L if taken: ${skipped['net_pnl'].sum():+,.0f}")
print(f"  Net improvement: ${-skipped['net_pnl'].sum():+,.0f}")
print()
for yr in ["2020", "2021", "2022"]:
    k = kept[kept["year"] == yr]
    s = skipped[skipped["year"] == yr]
    print(f"  {yr}: kept {len(k)}T ${k['net_pnl'].sum():+,.0f}  |  skipped {len(s)}T ${s['net_pnl'].sum():+,.0f}")

div("LONG FADE kept (SPY != DOWN) — detail by year")
long_kept = kept[kept["direction"] == "LONG"]
for yr in ["2020", "2021", "2022"]:
    ly = long_kept[long_kept["year"] == yr]
    if len(ly):
        w = (ly["net_pnl"] > 0).sum()
        print(f"  {yr}: {len(ly)} trades, {w/len(ly)*100:.1f}% win, ${ly['net_pnl'].sum():+,.0f}")

# ── Full system comparison ─────────────────────────────────────────────────────
div("FULL SYSTEM COMPARISON (retroactive)")
non_fade_pnl = all_trades[all_trades["strategy_type"] != "FADE"]["net_pnl"].sum()

print(f"\n  {'Scenario':<35} {'FADE':>8} {'System':>8} {'Trades':>7}")
print(f"  {'-'*60}")

scenarios = [
    ("A — Baseline (all FADE)",
     fade),
    ("B — No LONG FADE",
     fade[fade["direction"] == "SHORT"]),
    ("C — No LONG + skip SHORT SPY=UP",
     fade[(fade["direction"] == "SHORT") & (fade["spy_status"] != "UP")]),
    ("D — Symmetric SPY filter (both dir)",
     fade[~skip_mask]),
]
for name, f in scenarios:
    fp = f["net_pnl"].sum()
    sp = fp + non_fade_pnl
    print(f"  {name:<35} {fp:>+8.0f} {sp:>+8.0f} {len(f):>7}")
