"""
scripts/fade_deep_analysis.py
------------------------------
Deep-dive analysis of FADE trades stored in window_debug_results.pkl.
Examines: direction, exit reason, regime, OR range, entry depth, timing, ticker.

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_deep_analysis.py
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import pickle
import numpy as np
import pandas as pd

PICKLE_RESULTS = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_results.pkl")

def load_fade_trades():
    with open(PICKLE_RESULTS, "rb") as f:
        results = pickle.load(f)

    # results is a list of window dicts: [{label, trades, ...}, ...]
    all_trades = []
    for window in results:
        label = window.get("label", "?")
        trades = window.get("trades", [])
        for t in trades:
            row = t.__dict__.copy() if hasattr(t, "__dict__") else dict(t)
            row["year"] = label
            all_trades.append(row)

    df = pd.DataFrame(all_trades)
    print(f"  Columns available: {list(df.columns)}")
    print(f"  Strategy types: {df.get('strategy', df.get('strategy_type', pd.Series())).value_counts().to_dict()}")

    strat_col = "strategy" if "strategy" in df.columns else "strategy_type"
    fade = df[df[strat_col].isin(["FADE"])].copy()
    if strat_col == "strategy":
        fade["strategy_type"] = fade["strategy"]
    return fade, df


def bucket(val, edges, labels):
    for i, e in enumerate(edges):
        if val <= e:
            return labels[i]
    return labels[-1]


def div(label, width=64):
    print(f"\n{'─'*width}")
    print(f"  {label}")
    print('─'*width)


def pct(n, total):
    return f"{100*n/total:.1f}%" if total else "n/a"


def summary_table(df, group_col, label=""):
    div(label or group_col)
    grp = df.groupby(group_col)["net_pnl"].agg(
        Trades="count",
        Winners=lambda x: (x > 0).sum(),
        Avg=lambda x: x.mean(),
        Total="sum",
    ).reset_index()
    grp["Win%"] = (grp["Winners"] / grp["Trades"] * 100).round(1)
    grp["Avg"] = grp["Avg"].round(2)
    grp["Total"] = grp["Total"].round(0).astype(int)
    grp = grp.sort_values("Total", ascending=False)
    print(grp[[group_col, "Trades", "Win%", "Avg", "Total"]].to_string(index=False))


def main():
    fade, all_df = load_fade_trades()

    if fade.empty:
        print("No FADE trades found in pickle. Run window_debug.py first (without --use-results-cache).")
        return

    print(f"\n{'='*64}")
    print(f"  FADE DEEP ANALYSIS  —  {len(fade)} trades across {fade['year'].nunique()} years")
    print(f"{'='*64}")
    print(f"  Total P&L: ${fade['net_pnl'].sum():+,.0f}  |  Win rate: {pct((fade['net_pnl']>0).sum(), len(fade))}")
    print(f"  Avg P&L: ${fade['net_pnl'].mean():+.2f}  |  Median: ${fade['net_pnl'].median():+.2f}")

    # ── 1. Year breakdown ────────────────────────────────────────────────────
    summary_table(fade, "year", "BY YEAR")

    # ── 2. Direction ─────────────────────────────────────────────────────────
    if "direction" in fade.columns:
        summary_table(fade, "direction", "BY DIRECTION (LONG = fade short breakdown, SHORT = fade long breakout)")

    # ── 3. Exit reason ────────────────────────────────────────────────────────
    if "exit_reason" in fade.columns:
        summary_table(fade, "exit_reason", "BY EXIT REASON")
    else:
        # Infer from pnl vs risk
        if "stop_loss" in fade.columns and "entry_price" in fade.columns and "target" in fade.columns:
            def infer_exit(row):
                risk = abs(row["entry_price"] - row["stop_loss"])
                reward = abs(row["target"] - row["entry_price"])
                if row["net_pnl"] > 0 and abs(row["net_pnl"]) > 0.5 * reward * 1:  # rough target hit
                    return "target"
                elif row["net_pnl"] < 0 and abs(row["net_pnl"]) > 0.5 * risk:
                    return "stop"
                else:
                    return "time/partial"
            fade["exit_inferred"] = fade.apply(infer_exit, axis=1)
            summary_table(fade, "exit_inferred", "BY EXIT (INFERRED)")

    # ── 4. Regime ─────────────────────────────────────────────────────────────
    regime_col = next((c for c in ["regime", "hmm_state", "hmm_regime"] if c in fade.columns), None)
    if regime_col:
        summary_table(fade, regime_col, f"BY REGIME ({regime_col})")

    # ── 5. Entry depth (risk per share) ───────────────────────────────────────
    if "stop_loss" in fade.columns and "entry_price" in fade.columns:
        fade["risk_per_share"] = (fade["entry_price"] - fade["stop_loss"]).abs()
        edges = [fade["risk_per_share"].quantile(0.33), fade["risk_per_share"].quantile(0.67)]
        labels = [f"Tight (risk<=${edges[0]:.2f})", f"Medium", f"Deep (risk>${edges[1]:.2f})"]
        fade["depth_bucket"] = fade["risk_per_share"].apply(lambda v: bucket(v, edges, labels))
        summary_table(fade, "depth_bucket", "BY ENTRY DEPTH (risk per share terciles)")

        div("ENTRY DEPTH — percentiles")
        for p in [10, 25, 33, 50, 67, 75, 90]:
            print(f"  p{p:2d}: ${fade['risk_per_share'].quantile(p/100):.3f}")

    # ── 6. OR range size ─────────────────────────────────────────────────────
    if "or_high" in fade.columns and "or_low" in fade.columns:
        fade["or_range"] = fade["or_high"] - fade["or_low"]
        edges = [fade["or_range"].quantile(0.33), fade["or_range"].quantile(0.67)]
        labels = [f"Narrow (<=${edges[0]:.2f})", "Medium", f"Wide (>${edges[1]:.2f})"]
        fade["or_bucket"] = fade["or_range"].apply(lambda v: bucket(v, edges, labels))
        summary_table(fade, "or_bucket", "BY OR RANGE SIZE")

        div("OR RANGE — percentiles")
        for p in [10, 25, 50, 75, 90]:
            print(f"  p{p:2d}: ${fade['or_range'].quantile(p/100):.3f}")

    # ── 7. OR midpoint relationship ───────────────────────────────────────────
    # For FADE SHORT (failed long breakout): entry is below or_high
    # depth into OR = (or_high - entry) / or_range
    if "or_high" in fade.columns and "or_low" in fade.columns and "entry_price" in fade.columns and "direction" in fade.columns:
        def depth_pct(row):
            or_range = row["or_high"] - row["or_low"]
            if or_range <= 0:
                return np.nan
            if row["direction"] == "SHORT":
                # fading failed long breakout: entry below or_high
                return (row["or_high"] - row["entry_price"]) / or_range
            else:
                # fading failed short breakdown: entry above or_low
                return (row["entry_price"] - row["or_low"]) / or_range

        fade["depth_pct_or"] = fade.apply(depth_pct, axis=1)

        div("DEPTH INTO OR (entry as % of OR range from boundary)")
        print("  0% = just inside OR boundary (bad)")
        print("  50% = at OR midpoint")
        print("  100% = entry at opposite OR boundary (too deep to happen)")
        for p in [10, 25, 33, 50, 67, 75, 90]:
            print(f"  p{p:2d}: {100*fade['depth_pct_or'].quantile(p/100):.1f}%")

        div("P&L by depth into OR (deciles)")
        fade["depth_decile"] = pd.qcut(fade["depth_pct_or"].fillna(0), q=5, labels=False, duplicates="drop")
        depth_grp = fade.groupby("depth_decile")["net_pnl"].agg(
            Trades="count",
            Win=lambda x: (x>0).sum(),
            Avg="mean",
            Total="sum",
            depth_min=lambda x: fade.loc[x.index, "depth_pct_or"].min(),
            depth_max=lambda x: fade.loc[x.index, "depth_pct_or"].max(),
        )
        depth_grp["Win%"] = (depth_grp["Win"] / depth_grp["Trades"] * 100).round(1)
        depth_grp["Depth range"] = depth_grp.apply(
            lambda r: f"{100*r['depth_min']:.0f}%-{100*r['depth_max']:.0f}%", axis=1
        )
        depth_grp["Avg"] = depth_grp["Avg"].round(2)
        depth_grp["Total"] = depth_grp["Total"].round(0).astype(int)
        print(depth_grp[["Depth range", "Trades", "Win%", "Avg", "Total"]].to_string())

    # ── 8. Ticker breakdown ───────────────────────────────────────────────────
    if "ticker" in fade.columns:
        div("BY TICKER (sorted by Total P&L)")
        tk = fade.groupby("ticker")["net_pnl"].agg(
            Trades="count",
            Win=lambda x: (x>0).sum(),
            Avg="mean",
            Total="sum",
        ).reset_index()
        tk["Win%"] = (tk["Win"] / tk["Trades"] * 100).round(1)
        tk["Avg"] = tk["Avg"].round(2)
        tk["Total"] = tk["Total"].round(0).astype(int)
        tk = tk.sort_values("Total", ascending=False)
        print(tk[["ticker", "Trades", "Win%", "Avg", "Total"]].to_string(index=False))

    # ── 9. Day of week ────────────────────────────────────────────────────────
    date_col = next((c for c in ["date", "entry_date", "trade_date"] if c in fade.columns), None)
    if date_col:
        fade["dow"] = pd.to_datetime(fade[date_col]).dt.day_name()
        summary_table(fade, "dow", "BY DAY OF WEEK")

    # ── 10. Entry time ────────────────────────────────────────────────────────
    time_col = next((c for c in ["entry_time", "time", "bar_time"] if c in fade.columns), None)
    if time_col:
        div("BY ENTRY HOUR")
        fade["hour"] = pd.to_datetime(fade[time_col], errors="coerce").dt.hour
        summary_table(fade, "hour", "ENTRY HOUR")

    # ── 11. Print all FADE columns for inspection ─────────────────────────────
    div("AVAILABLE COLUMNS IN TRADE RECORDS")
    print(list(fade.columns))

    div("SAMPLE WINNING FADE TRADES (top 5 by P&L)")
    winners = fade.nlargest(5, "net_pnl")
    print(winners.to_string())

    div("SAMPLE LOSING FADE TRADES (bottom 5 by P&L)")
    losers = fade.nsmallest(5, "net_pnl")
    print(losers.to_string())


if __name__ == "__main__":
    main()
