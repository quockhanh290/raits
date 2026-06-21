"""
LONG FADE analysis excluding TSLA.
Question: nếu bỏ TSLA thì LONG FADE có viable không?

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_long_no_tsla.py
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
    if df.empty:
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
long_fade["spy_status"] = [spy_status_at(spy, row["entry_time"]) for _, row in long_fade.iterrows()]
long_fade["hour"] = pd.to_datetime(long_fade["entry_time"]).dt.hour

tsla    = long_fade[long_fade["ticker"] == "TSLA"]
no_tsla = long_fade[long_fade["ticker"] != "TSLA"]

# ── Overview ──────────────────────────────────────────────────────────────────
div("LONG FADE: TSLA vs non-TSLA")
print(f"  ALL:       {len(long_fade):>3} trades  ${long_fade['net_pnl'].sum():>+8.0f}  win={( long_fade['net_pnl']>0).mean()*100:.1f}%")
print(f"  TSLA only: {len(tsla):>3} trades  ${tsla['net_pnl'].sum():>+8.0f}  win={(tsla['net_pnl']>0).mean()*100:.1f}%")
print(f"  No TSLA:   {len(no_tsla):>3} trades  ${no_tsla['net_pnl'].sum():>+8.0f}  win={(no_tsla['net_pnl']>0).mean()*100:.1f}%")

# ── Non-TSLA breakdowns ───────────────────────────────────────────────────────
div("NO TSLA — BY YEAR")
table(no_tsla, "year")

div("NO TSLA — BY SPY STATUS")
table(no_tsla, "spy_status")

div("NO TSLA — BY ENTRY HOUR")
table(no_tsla, "hour")

div("NO TSLA — BY EXIT REASON")
table(no_tsla, "exit_reason")

div("NO TSLA — BY REGIME")
table(no_tsla, "hmm_state")

div("NO TSLA — SPY × HOUR")
no_tsla["spy_hour"] = no_tsla["spy_status"] + " | hour=" + no_tsla["hour"].astype(str)
table(no_tsla, "spy_hour")

div("NO TSLA — BY TICKER (remaining losers?)")
table(no_tsla, "ticker")

div("NO TSLA — ENTRY DEPTH")
if "stop" in no_tsla.columns:
    no_tsla = no_tsla.copy()
    no_tsla["risk"] = (no_tsla["entry_price"] - no_tsla["stop"]).abs()
    edges  = [no_tsla["risk"].quantile(0.33), no_tsla["risk"].quantile(0.67)]
    no_tsla["depth"] = pd.cut(no_tsla["risk"],
                               bins=[-np.inf, edges[0], edges[1], np.inf],
                               labels=[f"Tight(<={edges[0]:.2f})", "Medium", f"Deep(>{edges[1]:.2f})"])
    table(no_tsla, "depth")

# ── Compare all scenarios ─────────────────────────────────────────────────────
non_fade_pnl = all_trades[all_trades["strategy_type"] != "FADE"]["net_pnl"].sum()
short_fade   = fade[fade["direction"] == "SHORT"].copy()
short_fade["spy_status"] = [spy_status_at(spy, row["entry_time"]) for _, row in short_fade.iterrows()]

div("FULL SCENARIO COMPARISON (retroactive)")
print(f"\n  {'Scenario':<45} {'FADE':>8} {'System':>8} {'Trades':>7}")
print(f"  {'-'*70}")

# Baseline
f_base = fade["net_pnl"].sum()
print(f"  {'A — Baseline (all)':<45} {f_base:>+8.0f} {f_base+non_fade_pnl:>+8.0f} {len(fade):>7}")

# No LONG FADE
f_b = short_fade["net_pnl"].sum()
print(f"  {'B — No LONG FADE':<45} {f_b:>+8.0f} {f_b+non_fade_pnl:>+8.0f} {len(short_fade):>7}")

# No LONG + skip SHORT SPY=UP
short_no_up = short_fade[short_fade["spy_status"] != "UP"]
f_c = short_no_up["net_pnl"].sum()
print(f"  {'C — No LONG + skip SHORT SPY=UP':<45} {f_c:>+8.0f} {f_c+non_fade_pnl:>+8.0f} {len(short_no_up):>7}")

# No TSLA from LONG + keep LONG otherwise + skip SHORT SPY=UP
long_no_tsla_all = long_fade[long_fade["ticker"] != "TSLA"]
f_d_fade = short_no_up["net_pnl"].sum() + long_no_tsla_all["net_pnl"].sum()
n_d = len(short_no_up) + len(long_no_tsla_all)
print(f"  {'D — C + keep LONG (excl TSLA)':<45} {f_d_fade:>+8.0f} {f_d_fade+non_fade_pnl:>+8.0f} {n_d:>7}")

# Symmetric SPY + no TSLA from LONG
long_spy_filtered = long_no_tsla_all[long_no_tsla_all["spy_status"] != "DOWN"]
f_e_fade = short_no_up["net_pnl"].sum() + long_spy_filtered["net_pnl"].sum()
n_e = len(short_no_up) + len(long_spy_filtered)
print(f"  {'E — C + LONG excl TSLA + skip LONG SPY=DOWN':<45} {f_e_fade:>+8.0f} {f_e_fade+non_fade_pnl:>+8.0f} {n_e:>7}")

# Best case: C + LONG no TSLA only hour=10
long_h10_no_tsla = long_no_tsla_all[long_no_tsla_all["hour"] == 10]
f_f_fade = short_no_up["net_pnl"].sum() + long_h10_no_tsla["net_pnl"].sum()
n_f = len(short_no_up) + len(long_h10_no_tsla)
print(f"  {'F — C + LONG excl TSLA hour=10 only':<45} {f_f_fade:>+8.0f} {f_f_fade+non_fade_pnl:>+8.0f} {n_f:>7}")
