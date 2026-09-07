"""scratch/stocks_stage0_sensitivity_20260826.py — cost, slippage and sizing sensitivity.
READ-ONLY.

Re-books the CACHED candidate stream. Nothing is re-scanned, so exactly one input moves per
row and the difference between two rows is attributable to that input and to nothing else.
Re-running the whole backtest per variant would also change the trade set, and then a P&L
difference would be evidence about two backtests rather than about one parameter.

The stream is the same object Track 1's Stage 5Q-9 used for the same purpose: the committed
candidate stream, run through the real book twice, changing nothing but the one field.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scratch import stocks_stage0_engine_20260826 as E               # noqa: E402
from scratch.stocks_stage0_run_20260826 import metrics, breakdowns   # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "_stocks_stage0_sensitivity.json"


def rebook(cands, sizing, cost):
    rows, _ = E.build_book(cands, sizing, cost)
    return rows, metrics(rows, sizing.initial_capital)


def main() -> int:
    stream = HERE / "_stocks_stage0_candidates_B_causal_lag1_ema50.pkl"
    if not stream.exists():
        print("no cached candidate stream at", stream)
        print("run: python scratch\\stocks_stage0_run_20260826.py --configs B")
        return 2
    cands = pd.read_pickle(stream)
    base_sizing, base_cost = E.SizingModel(), E.StockCostModel()
    rep: dict = {"stream": str(stream), "n_candidates": len(cands)}

    rows0, m0 = rebook(cands, base_sizing, base_cost)
    rep["baseline"] = m0
    print("baseline: {} candidates, {} taken, net ${:,.2f}, PF {}".format(
        len(cands), m0.get("trades"), m0.get("net", 0), m0.get("profit_factor")))

    # ---- slippage ---------------------------------------------------------------------
    rep["slippage_bps_per_side"] = {}
    print("\n--- slippage sensitivity (bps per side; stop exits pay +5 on top) ---")
    print("  {:>6s}  {:>10s}  {:>10s}  {:>7s}  {:>7s}  {:>8s}".format(
        "bps", "net", "costs", "PF", "win%", "trades"))
    for bps in (0.0, 1.0, 3.0, 5.0, 10.0, 20.0):
        _, m = rebook(cands, base_sizing, replace(base_cost, slippage_bps_per_side=bps))
        rep["slippage_bps_per_side"][bps] = m
        print("  {:6.1f}  {:>10,.0f}  {:>10,.0f}  {:>7}  {:>7}  {:>8}".format(
            bps, m.get("net", 0), m.get("costs", 0), str(m.get("profit_factor")),
            str(m.get("win_rate")), m.get("trades")))

    # ---- commission -------------------------------------------------------------------
    rep["commission_per_share"] = {}
    print("\n--- commission sensitivity ($/share) ---")
    for c in (0.0, 0.0035, 0.005, 0.01):
        _, m = rebook(cands, base_sizing, replace(base_cost, commission_per_share=c))
        rep["commission_per_share"][c] = m
        print("  ${:.4f}/sh  net {:>10,.0f}  costs {:>10,.0f}  PF {}".format(
            c, m.get("net", 0), m.get("costs", 0), str(m.get("profit_factor"))))

    # ---- borrow -----------------------------------------------------------------------
    rep["borrow_bps_per_year"] = {}
    print("\n--- short borrow sensitivity (bps/yr) ---")
    for b in (0.0, 50.0, 200.0, 1000.0):
        _, m = rebook(cands, base_sizing, replace(base_cost, borrow_bps_per_year=b))
        rep["borrow_bps_per_year"][b] = m
        print("  {:6.0f}bp  net {:>10,.0f}  PF {}".format(b, m.get("net", 0),
                                                          str(m.get("profit_factor"))))

    # ---- risk fraction ----------------------------------------------------------------
    rep["risk_pct"] = {}
    print("\n--- risk-per-trade sensitivity ---")
    for r in (0.0025, 0.005, 0.01, 0.02):
        _, m = rebook(cands, replace(base_sizing, risk_pct=r), base_cost)
        rep["risk_pct"][r] = m
        print("  {:.2%}  net {:>10,.0f}  maxDD {:>9,.0f}  Calmar {}  trades {}".format(
            r, m.get("net", 0), m.get("max_dd", 0), str(m.get("calmar")), m.get("trades")))

    # ---- concurrency ------------------------------------------------------------------
    rep["max_concurrent_positions"] = {}
    print("\n--- concurrency cap sensitivity ---")
    for n in (2, 4, 8, 16, 100):
        _, m = rebook(cands, replace(base_sizing, max_concurrent_positions=n), base_cost)
        rep["max_concurrent_positions"][n] = m
        print("  {:3d}  net {:>10,.0f}  trades {:>5}  maxDD {:>9,.0f}".format(
            n, m.get("net", 0), m.get("trades"), m.get("max_dd", 0)))

    # ---- liquidity participation ------------------------------------------------------
    rep["max_pct_of_adv_shares"] = {}
    print("\n--- ADV participation cap sensitivity ---")
    for p in (0.001, 0.005, 0.01, 0.05):
        _, m = rebook(cands, replace(base_sizing, max_pct_of_adv_shares=p), base_cost)
        rep["max_pct_of_adv_shares"][p] = m
        print("  {:.2%} of ADV  net {:>10,.0f}  trades {:>5}".format(p, m.get("net", 0),
                                                                     m.get("trades")))

    # ---- ETF vs single name -----------------------------------------------------------
    from scratch import stocks_stage0_data_20260826 as D
    for name, keep in (("single_names_only", lambda s: s not in D.ETFS),
                       ("etfs_only", lambda s: s in D.ETFS)):
        sub = [c for c in cands if keep(c["symbol"])]
        if sub:
            _, m = rebook(sub, base_sizing, base_cost)
            rep[name] = m
            print("\n{}: {} candidates, {} taken, net ${:,.2f}, PF {}".format(
                name, len(sub), m.get("trades"), m.get("net", 0),
                str(m.get("profit_factor"))))

    # ---- the break-even slippage ------------------------------------------------------
    lo, hi = 0.0, 200.0
    for _ in range(40):
        mid = (lo + hi) / 2
        _, m = rebook(cands, base_sizing, replace(base_cost, slippage_bps_per_side=mid))
        if m.get("net", 0) > 0:
            lo = mid
        else:
            hi = mid
    rep["breakeven_slippage_bps_per_side"] = round(lo, 2)
    print("\nbreak-even slippage: {:.2f} bps per side "
          "(net P&L crosses zero there)".format(lo))

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
