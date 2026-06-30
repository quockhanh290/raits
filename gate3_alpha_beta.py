"""
gate3_alpha_beta.py — RAITS Gate 3: is the edge timing-ALPHA or index-BETA?
==========================================================================
STANDALONE, READ-ONLY. Reads a trade log CSV (from gate2_edge_harness
--dump-csv) plus the ES parquet, and answers the decisive Gate-3 question:

    "Does this strategy make money by TIMING (alpha), or just by being on the
     right side of a one-directional market (beta in disguise)?"

Because ES *is* the index, the Phase-1 'correlation vs SPY' test is reframed:
  1. DAILY REGRESSION  — regress the strategy's daily return on ES buy-&-hold
     daily return. Want LOW beta and LOW R²: money comes from intraday timing,
     not from holding the index.
  2. UP/DOWN-MONTH SPLIT — edge should appear in BOTH rising and falling months.
     If P&L only shows up when ES moves one way → directional beta, not alpha.
  3. DIRECTION × MARKET cross — if all the profit is SHORT trades in down-months
     (or LONG in up-months), that is just riding the trend = beta.

Engine-safety: imports gate2_edge_harness only for its read-only data helpers
(load_parquet, daily_close_series). Touches no engine, no model files.

Usage
-----
    # 1) produce the trade log:
    python gate2_edge_harness.py --parquet ES_7y.parquet --strategy trend_follow \\
        --hmm-train-end 2022-01-01 --dump-csv tf_trades.csv

    # 2) analyse it:
    python gate3_alpha_beta.py --trades-csv tf_trades.csv --parquet ES_7y.parquet \\
        --point-value 5.0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd()))

# Pre-registered Gate-3 thresholds (lock before running; override via CLI)
BETA_THR = 0.30          # |beta| above this → too directional
R2_THR = 0.20            # R² above this → returns largely explained by the index


def ols(x: np.ndarray, y: np.ndarray) -> dict:
    """Simple OLS y = a + b·x. Returns alpha, beta, R², corr, n."""
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return {"n": len(x), "alpha": np.nan, "beta": np.nan, "r2": np.nan, "corr": np.nan}
    b, a = np.polyfit(x, y, 1)
    yhat = a + b * x
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    corr = float(np.corrcoef(x, y)[0, 1]) if len(x) > 1 else np.nan
    return {"n": len(x), "alpha": float(a), "beta": float(b), "r2": float(r2), "corr": corr}


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate 3: alpha vs beta (read-only).")
    ap.add_argument("--trades-csv", required=True, help="trade log (gate2 --dump-csv, or dump_stock_trades.py)")
    ap.add_argument("--parquet", help="intraday continuous parquet (MES/ES) — benchmark source")
    ap.add_argument("--benchmark-daily-csv", help="daily benchmark CSV with columns date,close (e.g. SPY) "
                                                  "— use instead of --parquet for stock RAITS")
    ap.add_argument("--point-value", type=float, default=5.0,
                    help="MES=5, ES=50; for stock use 1 (pnl already in $, notional ~ benchmark px)")
    ap.add_argument("--beta-thr", type=float, default=BETA_THR)
    ap.add_argument("--r2-thr", type=float, default=R2_THR)
    ap.add_argument("--notional", type=float, default=None,
                    help="flat notional/account-equity to normalize daily P&L into a return "
                         "(stock: pass account equity e.g. 25000; futures: leave blank → point_value×price)")
    a = ap.parse_args()
    if not a.parquet and not a.benchmark_daily_csv:
        ap.error("provide --parquet (intraday) OR --benchmark-daily-csv (daily benchmark)")

    # ── load trades ──────────────────────────────────────────────────────────
    tr = pd.read_csv(a.trades_csv, parse_dates=["day"])
    tr["day"] = pd.to_datetime(tr["day"]).dt.normalize()
    if tr.empty:
        print("No trades in CSV — nothing to analyse."); return

    # ── benchmark daily close → daily return + month direction ───────────────
    if a.benchmark_daily_csv:
        b = pd.read_csv(a.benchmark_daily_csv)
        b.columns = [c.lower() for c in b.columns]
        dcol = "date" if "date" in b.columns else b.columns[0]
        ccol = "close" if "close" in b.columns else b.columns[-1]
        daily_close = pd.Series(b[ccol].values,
                                index=pd.to_datetime(b[dcol]).dt.normalize()).sort_index()
    else:
        import gate2_edge_harness as G
        df = G.load_parquet(a.parquet)
        daily_close = G.daily_close_series(df)
        daily_close.index = pd.to_datetime(daily_close.index).normalize()
    es_ret = daily_close.pct_change()

    # ── strategy daily P&L over the TEST window (0 on flat days) ──────────────
    t0, t1 = tr["day"].min(), tr["day"].max()
    window = daily_close.loc[(daily_close.index >= t0) & (daily_close.index <= t1)].index
    strat_pnl = tr.groupby("day")["pnl"].sum().reindex(window, fill_value=0.0)
    es_r = es_ret.reindex(window)
    # convert P&L to a return so beta is dimensionless.
    # stock: --notional = account equity; futures: point_value × price.
    if a.notional:
        notional = pd.Series(a.notional, index=window)
    else:
        notional = a.point_value * daily_close.reindex(window)
    strat_ret = (strat_pnl / notional).replace([np.inf, -np.inf], np.nan)

    print("\n" + "=" * 66)
    print(f"GATE 3  alpha vs beta  |  {Path(a.trades_csv).name}")
    print("=" * 66)
    print(f"Test window: {t0.date()} → {t1.date()} | {len(window)} trading days | "
          f"{len(tr)} trades | net P&L ${tr['pnl'].sum():,.0f}")

    # ── 1. daily regression ──────────────────────────────────────────────────
    reg = ols(es_r.to_numpy(), strat_ret.to_numpy())
    print("\n[1] DAILY REGRESSION  strat_ret ~ ES_ret")
    print(f"    beta = {reg['beta']:+.3f}   R² = {reg['r2']:.3f}   "
          f"corr = {reg['corr']:+.3f}   (n={reg['n']} days)")
    print(f"    annualized alpha ≈ {reg['alpha']*252:+.2%}")
    beta_ok = abs(reg["beta"]) <= a.beta_thr
    r2_ok = reg["r2"] <= a.r2_thr
    print(f"    |beta| ≤ {a.beta_thr}? {'YES' if beta_ok else 'NO'}   "
          f"R² ≤ {a.r2_thr}? {'YES' if r2_ok else 'NO'}")

    # ── 2. up/down-month split ───────────────────────────────────────────────
    m = pd.DataFrame({"pnl": strat_pnl, "es_ret": es_r}).dropna(subset=["es_ret"])
    m["month"] = m.index.to_period("M")
    by_month = m.groupby("month").agg(strat_pnl=("pnl", "sum"), es_ret=("es_ret", "sum"))
    up = by_month[by_month["es_ret"] > 0]
    dn = by_month[by_month["es_ret"] <= 0]
    print("\n[2] P&L BY MARKET DIRECTION (calendar months)")
    print(f"    UP-months   ({len(up):>2}): strat P&L ${up['strat_pnl'].sum():>10,.0f}   "
          f"mean ${up['strat_pnl'].mean() if len(up) else 0:>8,.0f}")
    print(f"    DOWN-months ({len(dn):>2}): strat P&L ${dn['strat_pnl'].sum():>10,.0f}   "
          f"mean ${dn['strat_pnl'].mean() if len(dn) else 0:>8,.0f}")
    up_pos = up["strat_pnl"].sum() > 0
    dn_pos = dn["strat_pnl"].sum() > 0
    both = up_pos and dn_pos
    print(f"    positive in BOTH directions? {'YES (alpha-like)' if both else 'NO (one-sided → beta-like)'}")

    # ── 3. direction × market cross ──────────────────────────────────────────
    if "direction" in tr.columns:
        tr2 = tr.merge(by_month["es_ret"].rename("m_es_ret"),
                       left_on=tr["day"].dt.to_period("M"), right_index=True, how="left")
        tr2["mkt"] = np.where(tr2["m_es_ret"] > 0, "up", "down")
        cross = tr2.pivot_table(index="direction", columns="mkt", values="pnl",
                                aggfunc="sum", fill_value=0.0)
        print("\n[3] P&L  (trade direction × market month)  $")
        print(cross.round(0).to_string())
        long_net = tr2.loc[tr2["direction"] == "LONG", "pnl"].sum()
        short_net = tr2.loc[tr2["direction"] == "SHORT", "pnl"].sum()
        print(f"    LONG net ${long_net:,.0f}   SHORT net ${short_net:,.0f}")

    # ── verdict ──────────────────────────────────────────────────────────────
    print("\n" + "-" * 66)
    if beta_ok and r2_ok and both:
        print("VERDICT: [ALPHA] low beta/R², profitable in both up & down months.")
        print("         Edge looks like intraday timing, not index exposure.")
    else:
        fails = []
        if not beta_ok: fails.append(f"beta {reg['beta']:+.2f}")
        if not r2_ok: fails.append(f"R² {reg['r2']:.2f}")
        if not both: fails.append("one-sided P&L (up xor down)")
        print(f"VERDICT: [BETA-SUSPECT] failed: {', '.join(fails)}.")
        print("         Some/all of the 'edge' may be directional index exposure —")
        print("         the Phase-1 failure mode. Inspect before trusting the WFO.")
    print("-" * 66 + "\n")


if __name__ == "__main__":
    main()
