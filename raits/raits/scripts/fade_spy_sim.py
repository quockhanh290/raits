"""
Retroactive simulation: apply SPY OR filter to FADE trades from baseline pkl.
Filters applied (cumulative):
  A) Baseline: both LONG + SHORT FADE
  B) No LONG FADE
  C) No LONG FADE + skip SHORT FADE when SPY=UP

Loads baseline pkl + SPY 5-min data. No engine re-run needed.
Caveat: circuit breaker interactions not modeled — treat as approximation.

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_spy_sim.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pandas as pd
import numpy as np

SNAP_DIR    = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "snapshots")
BASELINE    = os.path.join(SNAP_DIR, "results_baseline_no_filter.pkl")
PICKLE_5MIN = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")


def load_all_trades(path, label):
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
    df = pd.DataFrame(rows)
    if "strategy" in df.columns:
        df["strategy_type"] = df["strategy"]
    return df, results


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


def div(label, w=70):
    print(f"\n{'='*w}\n  {label}\n{'='*w}")


def show_by_strat(df, label):
    print(f"\n  {label}")
    print(f"  {'Strategy':<14} {'2020':>8} {'2021':>8} {'2022':>8} {'Total':>8} {'Trades':>7}")
    print(f"  {'-'*55}")
    for strat in ["ORB", "ORB_FADE", "FADE", "TREND_FOLLOW", "VWAP_MR"]:
        s = df[df["strategy_type"] == strat]
        if s.empty:
            continue
        totals = {yr: s[s["year"]==yr]["net_pnl"].sum() for yr in ["2020","2021","2022"]}
        row = f"  {strat:<14}"
        for yr in ["2020","2021","2022"]:
            row += f" {totals.get(yr,0):>+8.0f}"
        row += f" {s['net_pnl'].sum():>+8.0f} {len(s):>7}"
        print(row)
    total = df["net_pnl"].sum()
    n = len(df)
    print(f"  {'─'*55}")
    print(f"  {'TOTAL':<14} {df[df['year']=='2020']['net_pnl'].sum():>+8.0f}"
          f" {df[df['year']=='2021']['net_pnl'].sum():>+8.0f}"
          f" {df[df['year']=='2022']['net_pnl'].sum():>+8.0f}"
          f" {total:>+8.0f} {n:>7}")


# ── Load ──────────────────────────────────────────────────────────────────────
print("Loading baseline trades...")
all_trades, _ = load_all_trades(BASELINE, "baseline")

print("Loading SPY 5-min data...")
with open(PICKLE_5MIN, "rb") as f:
    market = pickle.load(f)
spy = market.get("SPY")
spy.index = pd.DatetimeIndex(spy.index)
spy.columns = [c.lower() for c in spy.columns]

# ── Compute SPY status for every FADE trade ───────────────────────────────────
fade_mask = all_trades["strategy_type"] == "FADE"
fade_idx  = all_trades[fade_mask].index

print(f"Computing SPY status for {fade_mask.sum()} FADE trades...")
spy_statuses = {}
for idx, row in all_trades[fade_mask].iterrows():
    spy_statuses[idx] = spy_status_at(spy, row["entry_time"])

all_trades["spy_status"] = all_trades.index.map(lambda i: spy_statuses.get(i, "N/A"))

# ── Define filters ────────────────────────────────────────────────────────────
def apply_filters(df, no_long_fade=False, no_spy_up=False):
    """Return subset of trades after applying FADE filters.
    Non-FADE trades are always kept unchanged."""
    non_fade = df[df["strategy_type"] != "FADE"].copy()
    fade     = df[df["strategy_type"] == "FADE"].copy()

    if no_long_fade:
        fade = fade[fade["direction"] == "SHORT"]
    if no_spy_up:
        fade = fade[~((fade["direction"] == "SHORT") & (fade["spy_status"] == "UP"))]

    return pd.concat([non_fade, fade], ignore_index=True)


# ── Run three scenarios ───────────────────────────────────────────────────────
scenario_A = apply_filters(all_trades)                              # baseline
scenario_B = apply_filters(all_trades, no_long_fade=True)          # no LONG FADE
scenario_C = apply_filters(all_trades, no_long_fade=True,
                            no_spy_up=True)                         # + skip SPY=UP

div("SCENARIO A — BASELINE (both LONG + SHORT FADE)")
show_by_strat(scenario_A, "")

div("SCENARIO B — NO LONG FADE only")
show_by_strat(scenario_B, "")

div("SCENARIO C — NO LONG FADE + skip SHORT FADE when SPY=UP")
show_by_strat(scenario_C, "")

# ── Delta summary ─────────────────────────────────────────────────────────────
div("DELTA SUMMARY (vs baseline A)")
fade_a = scenario_A[scenario_A["strategy_type"]=="FADE"]["net_pnl"].sum()
fade_b = scenario_B[scenario_B["strategy_type"]=="FADE"]["net_pnl"].sum()
fade_c = scenario_C[scenario_C["strategy_type"]=="FADE"]["net_pnl"].sum()
sys_a  = scenario_A["net_pnl"].sum()
sys_b  = scenario_B["net_pnl"].sum()
sys_c  = scenario_C["net_pnl"].sum()

print(f"\n  {'Scenario':<12} {'FADE P&L':>10} {'FADE Δ':>8} {'System P&L':>12} {'System Δ':>10} {'FADE Trades':>12}")
print(f"  {'-'*66}")
for name, sc, f in [("A (base)",  scenario_A, fade_a),
                    ("B (no LONG)", scenario_B, fade_b),
                    ("C (+ SPY)",   scenario_C, fade_c)]:
    n_fade = len(sc[sc["strategy_type"]=="FADE"])
    sys_p  = sc["net_pnl"].sum()
    print(f"  {name:<12} {f:>+10.0f} {f-fade_a:>+8.0f} {sys_p:>+12.0f} {sys_p-sys_a:>+10.0f} {n_fade:>12}")

# ── Scenario C FADE detail by year ────────────────────────────────────────────
div("SCENARIO C — FADE detail by year")
fade_c_df = scenario_C[scenario_C["strategy_type"]=="FADE"]
for yr in ["2020","2021","2022"]:
    fy = fade_c_df[fade_c_df["year"]==yr]
    wins = (fy["net_pnl"]>0).sum()
    n = len(fy)
    print(f"  {yr}: {n} trades, {wins/n*100:.1f}% win, ${fy['net_pnl'].sum():+,.0f}")

# ── SPY status breakdown for skipped trades ───────────────────────────────────
div("TRADES SKIPPED BY SPY=UP FILTER (SHORT FADE, SPY=UP)")
skipped = all_trades[
    (all_trades["strategy_type"] == "FADE") &
    (all_trades["direction"] == "SHORT") &
    (all_trades["spy_status"] == "UP")
]
print(f"  Total skipped: {len(skipped)} trades, P&L if taken: ${skipped['net_pnl'].sum():+,.0f}")
for yr in ["2020","2021","2022"]:
    s = skipped[skipped["year"]==yr]
    if len(s):
        print(f"  {yr}: {len(s)} trades skipped, P&L avoided: ${s['net_pnl'].sum():+,.0f}")

print(f"\n  Exit reason breakdown of skipped trades:")
print(skipped.groupby("exit_reason")["net_pnl"].agg(n="count", total="sum").to_string())

print("\n  NOTE: retroactive sim — CB interaction not modeled.")
print("  Actual engine results will differ slightly.")
