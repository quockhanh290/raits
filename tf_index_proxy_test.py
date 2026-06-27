"""
tf_index_proxy_test.py
======================================================================
HYPOTHESIS TEST (Meaning 2) — does RAITS's TREND_FOLLOW *pattern* have an
edge on an INDEX proxy (SPY / QQQ), as a stand-in for MES / MNQ?

WHY THIS IS SAFE
----------------
This script imports the EXISTING TrendFollowStrategy and HMMEngine classes
read-only and wraps them in a thin standalone replay harness. It does NOT
import, modify, or run backtest/engine.py. Nothing in the `raits` package is
changed. It mirrors how engine.py drives TREND_FOLLOW so the result is faithful:

  - ATR(14): TR = max(h-l, |h-prev_close|, |l-prev_close|), mean of last 14,
             fallback 1.5% of close   (identical to engine._compute_atr)
  - Window:  14:00 -> 15:55 ET, scanner runs once at 14:00       (TREND_START/EOD)
  - Entry:   resume-bar close (from strategy.generate_signal)
  - Exit:    Chandelier trailing stop, else hard EOD at 15:55
  - Regime:  HMMEngine trained on SPY daily up to the test window, then
             predicted forward per day (no look-ahead)

DELIBERATE SIMPLIFICATIONS (documented so you can audit):
  1. Single instrument => the "scanner" runs on one candidate (the index itself),
     which still applies the near-HOD/LOD direction intent + volume filter.
  2. One concurrent position per instrument (re-entry allowed after an exit).
  3. P&L reported in PERCENT (unit-free) — the question is pattern EDGE, not $.
     On real MES/MNQ, $ = pct * entry * point_value * contracts.
  4. ema_period uses the current production value; this is a screen, not a WFO.

If this screen shows positive expectancy / PF > 1 on SPY and especially QQQ,
the pattern plausibly survives on the index and the full pivot is worth the cost.
If it is flat/negative, that is a cheap NO before any continuous-contract work.

RUN (from project root, per your convention):
    & ".venv\\Scripts\\python.exe" "scratch\\tf_index_proxy_test.py"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from raits.strategies.trend_follow import TrendFollowStrategy
from raits.hmm.engine import HMMEngine

logging.getLogger("RAITS").setLevel(logging.WARNING)  # quiet strategy debug logs

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
PROXIES        = ["QQQ"]                   # MES≈SPY, MNQ≈QQQ
HMM_TRAIN_FROM = "2010-01-01"              # SPY daily training start
TEST_FROM      = "2017-01-01"              # OOS test window (avoid vault if desired)
TEST_TO        = "2022-12-29"             # keep strictly before the vault boundary
EMA_PERIOD     = 30                        # production value; not re-WFO'd here
POINT_VALUE    = {"SPY": 5.0, "QQQ": 2.0}  # MES $5/pt, MNQ $2/pt (for reference only)

TREND_START = dtime(14, 0)
EOD_EXIT    = dtime(15, 55)

CACHE_DIR = "./raits/data/cache"   # match the package default; change if your cache lives elsewhere
OUT_PATH  = Path("scratch") / "tf_index_proxy_results.json"
# Pre-fetched SPY daily parquet (2007-2024) — avoids DataPipeline's partial-fetch issue
SPY_DAILY_PARQUET = Path(CACHE_DIR) / "daily" / "SPY_daily_2007_2024.parquet"


# ──────────────────────────────────────────────────────────────────────────────
# API key + pipeline (refuses to run on mock data)
# ──────────────────────────────────────────────────────────────────────────────
def _load_api_key() -> Optional[str]:
    import importlib.util as _ilu
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for p in [os.path.join(here, "..", "config_private.py"),
              os.path.join(here, "..", "..", "config_private.py"),
              os.path.join(here, "..", "..", "..", "config_private.py"),
              "config_private.py"]:
        if os.path.exists(p):
            spec = _ilu.spec_from_file_location("config_private", p)
            mod = _ilu.module_from_spec(spec); spec.loader.exec_module(mod)
            return getattr(mod, "POLYGON_API_KEY", None)
    return None


def _make_pipeline():
    from raits.data.raits_data_pipeline import DataPipeline
    key = _load_api_key()
    if not key:
        raise SystemExit("FATAL: config_private.py / POLYGON_API_KEY not found — "
                         "refusing to run on mock data.")
    return DataPipeline(api_key=key, cache_dir=CACHE_DIR)


# ──────────────────────────────────────────────────────────────────────────────
# Faithful indicator helper (mirrors engine._compute_atr exactly)
# ──────────────────────────────────────────────────────────────────────────────
def compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


# ──────────────────────────────────────────────────────────────────────────────
# CORE — pure, testable replay of one trading day (no I/O, no engine)
# ──────────────────────────────────────────────────────────────────────────────
def replay_day(day_bars: pd.DataFrame,
               regime: str,
               strategy: TrendFollowStrategy,
               ema_period: int) -> List[dict]:
    """
    Replay 14:00->15:55 on one day's 5-min bars. Returns a list of trade dicts.
    Mirrors engine.py's TREND_FOLLOW drive: scanner@14:00, signal per bar,
    entry at resume close, Chandelier trail, hard EOD exit.
    """
    trades: List[dict] = []
    if day_bars.empty:
        return trades

    # Window bars (need the full day for HOD/LOD + indicators, gate entries to window)
    in_win = day_bars[(day_bars.index.time >= TREND_START) &
                      (day_bars.index.time <  EOD_EXIT)]
    if len(in_win) < 3:
        return trades

    # ── Scanner @ 14:00 (single index candidate) ──────────────────────────────
    first_ts   = in_win.index[0]
    upto_first = day_bars.loc[:first_ts]
    intent = None
    candidate = {
        "ticker":              "IDX",
        "current_price":       float(upto_first["close"].iloc[-1]),
        "hod":                 float(upto_first["high"].max()),
        "lod":                 float(upto_first["low"].min()),
        "atr":                 compute_atr(upto_first),
        "avg_intraday_volume": float(upto_first["volume"].tail(10).mean()),
        "current_volume":      float(upto_first["volume"].iloc[-1]),
        "sector_strength":     0.0,
    }
    strategy.reset()
    accepted = strategy.run_scanner([candidate])
    if not accepted:
        return trades                       # index not trending into PM → no trades
    intent = strategy.watchlist_directions.get("IDX")

    # ── Bar loop: state machine searching <-> in_position ─────────────────────
    state        = "searching"
    entry_price  = entry_ts = atr_entry = direction = None

    win_ts = list(in_win.index)
    for i, ts in enumerate(win_ts):
        bars_so_far = day_bars.loc[:ts]
        if len(bars_so_far) < 2:
            continue

        if state == "searching":
            ema = strategy.calculate_ema(bars_so_far, period=ema_period)
            atr = compute_atr(bars_so_far)
            pullback = bars_so_far.iloc[-2]
            resume   = bars_so_far.iloc[-1]
            avg_v10  = float(bars_so_far["volume"].tail(10).mean())
            sig = strategy.generate_signal(pullback, resume, ema, atr, regime, avg_v10)
            if sig is None:
                continue
            if intent is not None and sig["direction"] != intent:
                continue                    # engine rejects signals vs intraday trend
            entry_price = sig["entry_price"]
            direction   = sig["direction"]
            atr_entry   = sig["atr"]
            entry_ts    = ts
            state       = "in_position"
            continue

        # state == in_position → trail + check exit on THIS bar
        bar = day_bars.loc[ts]
        since = day_bars.loc[entry_ts:ts]
        stop = strategy.calculate_chandelier_stop(since, atr_entry, direction)

        exit_px = exit_reason = None
        if direction == "LONG" and float(bar["low"]) <= stop:
            exit_px, exit_reason = stop, "STOP"
        elif direction == "SHORT" and float(bar["high"]) >= stop:
            exit_px, exit_reason = stop, "STOP"
        elif i == len(win_ts) - 1:          # last bar of window → EOD
            exit_px, exit_reason = float(bar["close"]), "EOD"

        if exit_px is not None:
            pnl_pct = ((exit_px - entry_price) / entry_price) if direction == "LONG" \
                      else ((entry_price - exit_px) / entry_price)
            trades.append({
                "entry_ts": str(entry_ts), "exit_ts": str(ts),
                "direction": direction, "entry": round(entry_price, 4),
                "exit": round(exit_px, 4), "pnl_pct": pnl_pct,
                "reason": exit_reason, "regime": regime,
            })
            state = "searching"
            entry_price = entry_ts = atr_entry = direction = None

    return trades


# ──────────────────────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────────────────────
def summarize(trades: List[dict]) -> dict:
    if not trades:
        return {"n": 0}
    pnls = np.array([t["pnl_pct"] for t in trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    gross_win  = wins.sum()
    gross_loss = -losses.sum()
    by_regime: Dict[str, int] = {}
    for t in trades:
        by_regime[t["regime"]] = by_regime.get(t["regime"], 0) + 1
    return {
        "n":            len(trades),
        "win_rate":     round(len(wins) / len(trades), 4),
        "avg_win_pct":  round(float(wins.mean()) if len(wins) else 0.0, 5),
        "avg_loss_pct": round(float(losses.mean()) if len(losses) else 0.0, 5),
        "profit_factor": round(float(gross_win / gross_loss), 3) if gross_loss > 0 else float("inf"),
        "expectancy_pct": round(float(pnls.mean()), 5),
        "total_pct":    round(float(pnls.sum()), 4),
        "by_regime":    by_regime,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Data loading (uses YOUR pipeline; isolated so the core above stays testable)
# ──────────────────────────────────────────────────────────────────────────────
def load_index_days(ticker: str, dates: List[datetime]) -> Dict[datetime, pd.DataFrame]:
    """Load 5-min bars per day via the existing DataPipeline (Polygon + Parquet cache)."""
    pipe = _make_pipeline()
    out: Dict[datetime, pd.DataFrame] = {}
    for d in dates:
        try:
            hd = pipe.get_intraday_data(ticker, d, interval_minutes=5)
            df = hd.to_dataframe()
            if df.empty:
                continue
            df = df.sort_index()
            out[d] = df[["open", "high", "low", "close", "volume"]].astype(float)
        except Exception as e:
            logging.warning(f"{ticker} {d:%Y-%m-%d}: load failed ({e})")
    return out


def build_regimes(spy_daily_close: pd.Series, test_dates: List[pd.Timestamp]) -> Dict[pd.Timestamp, str]:
    """Fit HMMEngine on SPY daily up to the test window, predict forward per day."""
    engine = HMMEngine()
    train = spy_daily_close[spy_daily_close.index < test_dates[0]]
    engine.fit(train)
    regimes: Dict[pd.Timestamp, str] = {}
    for d in test_dates:
        trail = spy_daily_close[spy_daily_close.index <= d].tail(60)
        try:
            regimes[d] = engine.state_name(engine.predict_current(trail))
        except Exception:
            regimes[d] = "Normal"
    return regimes


def main():
    test_dates = pd.bdate_range(TEST_FROM, TEST_TO)
    # SPY daily close drives the regime (market-level, same as production)
    if SPY_DAILY_PARQUET.exists():
        spy_close = pd.read_parquet(SPY_DAILY_PARQUET)["close"].astype(float).sort_index().loc[HMM_TRAIN_FROM:TEST_TO]
    else:
        pipe = _make_pipeline()
        spy_daily = pipe.get_daily_data("SPY", pd.Timestamp(HMM_TRAIN_FROM), pd.Timestamp(TEST_TO))
        spy_close = spy_daily.to_dataframe()["close"].astype(float)
    regimes = build_regimes(spy_close, list(test_dates))

    report = {}
    for ticker in PROXIES:
        strat = TrendFollowStrategy(config={"ema_period": EMA_PERIOD})
        day_data = load_index_days(ticker, list(test_dates))
        all_trades: List[dict] = []
        for d, bars in day_data.items():
            reg = regimes.get(pd.Timestamp(d.date()), "Normal")
            all_trades += replay_day(bars, reg, strat, EMA_PERIOD)
        report[ticker] = summarize(all_trades)
        report[ticker]["_trades"] = all_trades
        print(f"\n=== {ticker} (proxy for {'MES' if ticker=='SPY' else 'MNQ'}) ===")
        print(json.dumps({k: v for k, v in report[ticker].items() if k != "_trades"}, indent=2))

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nFull results → {OUT_PATH}")


if __name__ == "__main__":
    main()
