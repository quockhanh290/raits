"""
Execution-value CEILING estimate — free pre-check before buying orderflow data.
(EXPERIMENTAL harness, orb_stocks/imbalance_research/)  — RESEARCH ONLY.

WHY
───────────────────────────────────────────────────────────────────────────
Footprint / DOM orderflow (meanings 2 and 3) operates on a seconds-to-minutes
horizon. Measured holding periods in this system:

    STRESS_MID   152 min      STRESS_ORB   158 min     GF_SHORT   180 min
    ORB          350 min      PE_SHORT    1825 min     TREND_FOLLOW 6925 min

Nothing here trades at a scalper's horizon, so orderflow-as-SIGNAL is a
horizon mismatch. The one use that IS horizon-compatible is EXECUTION:
"send the order now or wait 30 seconds" is genuinely a seconds-scale decision.

Before spending anything on tick data, bound how much money is even on the
table. If the ceiling is a few hundred dollars over 5 years, close the branch.

WHAT THIS MEASURES (and what it does NOT)
───────────────────────────────────────────────────────────────────────────
Uses only data already on disk: the trade log + window_debug_5min.pkl.

Three benchmarks per fill, at entry and at exit:

  ACTUAL    the backtest's modelled fill (`entry_price` / `exit_price`)
  VWAP      that bar's volume-weighted average price — a REALISTIC target;
            working an order across the bar is roughly a VWAP outcome
  EXTREME   the bar's best possible price for that side — perfect hindsight,
            NOT achievable, reported strictly as an upper bound

The honest reading:
  - the VWAP column is the plausible prize
  - the EXTREME column is the theoretical maximum and will always look large;
    treating it as attainable is exactly the error this script exists to avoid

LIMITATIONS, stated up front
  1. Bars are 5-MINUTE. A 5-min range overstates what finer timing can capture
     within it, which makes EXTREME an even looser bound. VWAP is unaffected
     by this in direction, but a 5-min VWAP is a coarser target than a 1-min one.
  2. These are MODELLED fills, not real ones. This measures the gap between the
     model's fill and other prices in the same bar — i.e. the OPPORTUNITY SIZE,
     not a realised loss. No claim is made that the model's fill is wrong.
  3. `total_costs` already includes the engine's commission + slippage model.
     Reported alongside so the prize can be compared to costs already charged.

Run:
    cd d:\\raits
    python orb_stocks\\imbalance_research\\execution_ceiling.py
"""

from __future__ import annotations

import os
import pickle
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
# The snapshot pickles Trade objects from the raits package — the module must be
# importable or pickle.load raises ModuleNotFoundError.
sys.path.insert(0, REPO)
SNAPSHOT = os.path.join(REPO, "raits", "data", "cache", "snapshots",
                        "results_20260707_110323.pkl")
BARS = os.path.join(REPO, "raits", "data", "cache", "window_debug_5min.pkl")
OUT = os.path.join(HERE, "execution_ceiling.parquet")


def load_trades() -> pd.DataFrame:
    with open(SNAPSHOT, "rb") as f:
        windows = pickle.load(f)
    rows = []
    for w in windows:
        for t in w["trades"]:
            rows.append(dict(
                strategy=getattr(t, "strategy", None),
                ticker=t.ticker,
                direction=getattr(t, "direction", None),
                entry_time=pd.Timestamp(t.entry_time),
                exit_time=pd.Timestamp(t.exit_time) if getattr(t, "exit_time", None) is not None else pd.NaT,
                entry_price=float(t.entry_price),
                exit_price=float(t.exit_price) if getattr(t, "exit_price", None) is not None else np.nan,
                shares=float(getattr(t, "shares", 0) or 0),
                net_pnl=float(getattr(t, "net_pnl", 0) or 0),
                total_costs=float(getattr(t, "total_costs", 0) or 0),
                exit_reason=getattr(t, "exit_reason", None),
            ))
    return pd.DataFrame(rows)


def attach_bar(df: pd.DataFrame, bars: dict, tcol: str, pre: str) -> pd.DataFrame:
    """Attach the OHLCV+vwap of the bar containing the given timestamp."""
    for c in ("open", "high", "low", "close", "vwap"):
        df[f"{pre}_{c}"] = np.nan
    for tk, g in df.groupby("ticker"):
        if tk not in bars:
            continue
        b = bars[tk]
        idx = pd.to_datetime(b.index)
        ts = pd.to_datetime(g[tcol])
        ok = ts.notna()
        common = ts[ok]
        hit = common[common.isin(idx)]
        if len(hit) == 0:
            continue
        sub = b.loc[hit.values]
        for c in ("open", "high", "low", "close", "vwap"):
            if c in sub.columns:
                df.loc[hit.index, f"{pre}_{c}"] = sub[c].values
    return df


def main() -> None:
    print("=" * 78)
    print("EXECUTION-VALUE CEILING  (free pre-check — no data purchased)")
    print("RESEARCH ONLY. Opportunity size, NOT a realised loss.")
    print("=" * 78)

    tr = load_trades()
    with open(BARS, "rb") as f:
        bars = pickle.load(f)
    for tk in bars:
        bars[tk].index = pd.to_datetime(bars[tk].index)

    tr = attach_bar(tr, bars, "entry_time", "e")
    tr = attach_bar(tr, bars, "exit_time", "x")

    n0 = len(tr)
    tr = tr[tr["e_close"].notna()].copy()
    print(f"\n  trades: {n0} total, {len(tr)} with an entry bar matched "
          f"({n0 - len(tr)} unmatched, dropped)")

    is_long = tr["direction"].eq("LONG")

    # ── where in the bar does the modelled fill sit? ──────────────────────
    rng = (tr["e_high"] - tr["e_low"]).replace(0, np.nan)
    tr["e_pos_in_range"] = (tr["entry_price"] - tr["e_low"]) / rng
    print(f"\n  modelled ENTRY fill position within its bar "
          f"(0=low, 1=high): median={tr['e_pos_in_range'].median():.2f}")
    same_close = np.isclose(tr["entry_price"], tr["e_close"], rtol=0, atol=1e-6).mean()
    print(f"  entry_price == bar close: {same_close * 100:.0f}% of trades "
          f"(the engine fills at bar close)")

    # ── ENTRY: gain per share from a better fill ─────────────────────────
    # LONG wants a LOWER entry; SHORT wants a HIGHER entry.
    tr["e_gain_vwap"] = np.where(is_long,
                                 tr["entry_price"] - tr["e_vwap"],
                                 tr["e_vwap"] - tr["entry_price"])
    tr["e_gain_extreme"] = np.where(is_long,
                                    tr["entry_price"] - tr["e_low"],
                                    tr["e_high"] - tr["entry_price"])

    # ── EXIT: LONG wants a HIGHER exit; SHORT wants a LOWER exit ─────────
    has_x = tr["x_close"].notna()
    tr["x_gain_vwap"] = np.where(is_long,
                                 tr["x_vwap"] - tr["exit_price"],
                                 tr["exit_price"] - tr["x_vwap"])
    tr["x_gain_extreme"] = np.where(is_long,
                                    tr["x_high"] - tr["exit_price"],
                                    tr["exit_price"] - tr["x_low"])
    tr.loc[~has_x, ["x_gain_vwap", "x_gain_extreme"]] = np.nan

    for c in ("e_gain_vwap", "e_gain_extreme", "x_gain_vwap", "x_gain_extreme"):
        tr[c + "_usd"] = tr[c] * tr["shares"]

    tr.to_parquet(OUT, index=False)

    # ── report ───────────────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print("PRIZE BY STRATEGY  (USD over the whole 2017-2022 backtest)")
    print("=" * 78)
    print(f"  {'strategy':<14}{'n':>5}{'net P&L':>11}{'costs':>10}"
          f"{'VWAP e+x':>11}{'EXTREME e+x':>13}{'VWAP %P&L':>11}")
    tot = {}
    for s, g in tr.groupby("strategy"):
        pnl = g["net_pnl"].sum()
        cost = g["total_costs"].sum()
        vw = np.nansum(g["e_gain_vwap_usd"]) + np.nansum(g["x_gain_vwap_usd"])
        ex = np.nansum(g["e_gain_extreme_usd"]) + np.nansum(g["x_gain_extreme_usd"])
        pct = (vw / pnl * 100) if pnl else np.nan
        tot[s] = (len(g), pnl, cost, vw, ex)
        print(f"  {s:<14}{len(g):>5}{pnl:>11,.0f}{cost:>10,.0f}"
              f"{vw:>11,.0f}{ex:>13,.0f}{pct:>10.0f}%")
    P = sum(v[1] for v in tot.values())
    C = sum(v[2] for v in tot.values())
    V = sum(v[3] for v in tot.values())
    E = sum(v[4] for v in tot.values())
    print(f"  {'-' * 74}")
    print(f"  {'TOTAL':<14}{len(tr):>5}{P:>11,.0f}{C:>10,.0f}"
          f"{V:>11,.0f}{E:>13,.0f}{V / P * 100 if P else 0:>10.0f}%")

    # ── per-trade view + sign of the VWAP gap ────────────────────────────
    print(f"\n{'-' * 78}")
    print("PER-TRADE  (is the modelled fill better or worse than bar VWAP?)")
    print(f"{'-' * 78}")
    for s, g in tr.groupby("strategy"):
        ev = g["e_gain_vwap_usd"].dropna()
        better = (ev > 0).mean() * 100
        print(f"  {s:<14} entry vs VWAP: mean=${ev.mean():+7.2f}/trade  "
              f"median=${ev.median():+7.2f}  "
              f"modelled fill better than VWAP on {better:.0f}% of trades")

    print(f"\n{'=' * 78}")
    print("READ THIS BEFORE ACTING")
    print("=" * 78)
    print("  VWAP column = the plausible prize if every fill were worked to that")
    print("  bar's VWAP instead of taken at the close. EXTREME = perfect hindsight,")
    print("  unattainable, shown only to bound the problem from above.")
    print()
    print("  A POSITIVE VWAP number means the modelled fill is WORSE than VWAP, so")
    print("  there is something to win. A NEGATIVE number means the backtest is")
    print("  already assuming fills BETTER than VWAP — in which case better")
    print("  execution cannot add anything, and the modelled fill may be optimistic.")
    print()
    print("  Decision rule set BEFORE reading the numbers:")
    print("    prize < $1,000 over 5 years -> close the orderflow branch entirely")
    print("    $1,000-5,000                -> marginal; only worth it if")
    print("                                   concentrated in few strategies")
    print("    > $5,000                    -> justifies buying tick data to")
    print("                                   study execution timing")
    print(f"\n  written: {OUT}")
    print("=" * 78)


if __name__ == "__main__":
    main()
