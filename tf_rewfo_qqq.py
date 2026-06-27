"""
tf_rewfo_qqq.py
======================================================================
EXPLORATORY re-WFO (Meaning 2, second pass) — does a QQQ-specific parameter
set produce a *consistent* edge, or was the 2021-22 result curve-fit / 2022-luck?

This is the honest follow-up to the long-horizon run that came back breakeven
(PF 1.05 over 2017-2022, all profit from 2022). We now re-derive ema_period and
chandelier_atr_mult on an IN-SAMPLE window and validate OUT-OF-SAMPLE.

SAFE: reuses replay_day / summarize / build_regimes from tf_index_proxy_test.py
(import, not copy). Does NOT touch backtest/engine.py or any package code.

DESIGN — built to AVOID fooling ourselves:
  - In-sample:  IS_FROM -> IS_TO   (tune here)
  - Out-of-sample: OOS_FROM -> OOS_TO  (never used for selection)
  - We print THREE things, not just the winner:
      1. The full param grid (in-sample PF) -> plateau vs isolated spike.
         A real edge shows a broad region of PF>1; overfit shows one lucky cell.
      2. Per-year P&L of the top combos -> consistency, not one-year rescue.
      3. OOS performance of the in-sample-best combo.

  HOW TO READ (decide BEFORE looking, so you don't rationalize):
    GO-ish  : in-sample best sits in a PLATEAU (neighbors also PF>1.2),
              is positive in MOST in-sample years (not 1), AND OOS PF > ~1.3.
    NO-GO   : best is an isolated spike, or in-sample is carried by one year,
              or OOS collapses. Any one of these = stop.

RUN (from project root, with this file + tf_index_proxy_test.py in scratch\):
    & ".venv\\Scripts\\python.exe" "scratch\\tf_rewfo_qqq.py"
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

# Reuse the verified harness (same folder)
from tf_index_proxy_test import (
    replay_day, summarize, build_regimes, load_index_days, _make_pipeline,
)
from raits.strategies.trend_follow import TrendFollowStrategy

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
PROXY        = "QQQ"
HMM_TRAIN    = "2010-01-01"
IS_FROM      = "2017-01-01"
IS_TO        = "2021-12-31"
OOS_FROM     = "2022-01-01"
OOS_TO       = "2022-12-29"          # before vault boundary

EMA_GRID     = [15, 20, 30, 50]
CHAND_GRID   = [2.0, 2.5, 3.0, 3.5]
MIN_TRADES   = 40                     # ignore combos too sparse to trust in-sample

OUT_PATH     = Path("scratch") / "tf_rewfo_qqq_results.json"


def run_window(day_bars: Dict, regimes: Dict, ema: int, chand: float) -> List[dict]:
    strat = TrendFollowStrategy(config={"ema_period": ema, "chandelier_atr_mult": chand})
    trades: List[dict] = []
    for d, bars in day_bars.items():
        reg = regimes.get(pd.Timestamp(pd.Timestamp(d).date()), "Normal")
        trades += replay_day(bars, reg, strat, ema)
    return trades


def per_year(trades: List[dict]) -> Dict[str, dict]:
    yg = defaultdict(list)
    for t in trades:
        yg[t["entry_ts"][:4]].append(t["pnl_pct"])
    out = {}
    for y, p in sorted(yg.items()):
        arr = np.array(p)
        out[y] = {"n": len(arr), "total_pct": round(float(arr.sum()) * 100, 2)}
    return out


def main():
    # SPY daily -> regimes (computed once; params don't affect regime)
    from tf_index_proxy_test import SPY_DAILY_PARQUET
    if SPY_DAILY_PARQUET.exists():
        spy_close = pd.read_parquet(SPY_DAILY_PARQUET)["close"].astype(float).sort_index().loc[HMM_TRAIN:OOS_TO]
    else:
        pipe = _make_pipeline()
        spy = pipe.get_daily_data("SPY", pd.Timestamp(HMM_TRAIN), pd.Timestamp(OOS_TO))
        spy_close = spy.to_dataframe()["close"].astype(float).sort_index()

    is_dates  = list(pd.bdate_range(IS_FROM, IS_TO))
    oos_dates = list(pd.bdate_range(OOS_FROM, OOS_TO))
    regimes = build_regimes(spy_close, is_dates + oos_dates)

    print(f"Loading {PROXY} 5-min bars (in-sample + OOS)…")
    is_bars  = load_index_days(PROXY, is_dates)
    oos_bars = load_index_days(PROXY, oos_dates)

    # ── Grid search on IN-SAMPLE ──────────────────────────────────────────────
    grid = {}
    for ema in EMA_GRID:
        for ch in CHAND_GRID:
            tr = run_window(is_bars, regimes, ema, ch)
            s = summarize(tr)
            grid[(ema, ch)] = {"summary": s, "by_year": per_year(tr), "trades": tr}

    print(f"\n=== IN-SAMPLE grid ({IS_FROM[:4]}–{IS_TO[:4]}) — profit factor ===")
    print("ema\\chand   " + "  ".join(f"{c:>5}" for c in CHAND_GRID))
    for ema in EMA_GRID:
        row = []
        for ch in CHAND_GRID:
            s = grid[(ema, ch)]["summary"]
            pf = s.get("profit_factor", 0)
            row.append(f"{pf:>5.2f}" if s.get("n", 0) >= MIN_TRADES else "  -- ")
        print(f"{ema:>4}        " + "  ".join(row))

    # ── Pick in-sample best (PF, with min-trade floor) ────────────────────────
    eligible = {k: v for k, v in grid.items() if v["summary"].get("n", 0) >= MIN_TRADES}
    if not eligible:
        print("\nNo combo cleared the min-trade floor in-sample. NO-GO.")
        return
    ranked = sorted(eligible.items(),
                    key=lambda kv: kv[1]["summary"]["profit_factor"], reverse=True)

    print("\n=== Top 3 in-sample combos — consistency check (per-year total %) ===")
    for (ema, ch), v in ranked[:3]:
        s = v["summary"]
        yrs = v["by_year"]
        pos = sum(1 for y in yrs.values() if y["total_pct"] > 0)
        print(f"  ema={ema:>2} chand={ch}: PF={s['profit_factor']:.2f} "
              f"exp={s['expectancy_pct']*100:.3f}% n={s['n']} | "
              f"positive years={pos}/{len(yrs)}")
        print("      " + "  ".join(f"{y}:{d['total_pct']:+.1f}%" for y, d in yrs.items()))

    # ── OOS validation of the in-sample winner ────────────────────────────────
    (bema, bch), _ = ranked[0]
    oos_tr = run_window(oos_bars, regimes, bema, bch)
    oos_s  = summarize(oos_tr)
    print(f"\n=== OUT-OF-SAMPLE {OOS_FROM[:4]} — winner (ema={bema}, chand={bch}) ===")
    print(json.dumps({k: v for k, v in oos_s.items() if k != "by_regime"}, indent=2))

    # ── Plateau diagnostic ────────────────────────────────────────────────────
    good = sum(1 for v in eligible.values() if v["summary"]["profit_factor"] >= 1.2)
    print(f"\nPlateau check: {good}/{len(eligible)} eligible combos have in-sample PF ≥ 1.2")
    print("  (broad = robust edge; 0–1 = isolated spike = overfit)")

    OUT_PATH.parent.mkdir(exist_ok=True)
    dump = {f"{e}_{c}": {"summary": {k: v for k, v in g["summary"].items() if k != "by_regime"},
                          "by_year": g["by_year"]}
            for (e, c), g in grid.items()}
    dump["_oos_winner"] = {"ema": bema, "chand": bch,
                            "oos": {k: v for k, v in oos_s.items() if k != "by_regime"}}
    OUT_PATH.write_text(json.dumps(dump, indent=2))
    print(f"\nFull results → {OUT_PATH}")


if __name__ == "__main__":
    main()
