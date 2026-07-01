"""
regime_index_relevance.py
======================================================================
HYPOTHESIS TEST (Meaning 3) — does RAITS's HMM regime signal carry meaning
for an INDEX (SPY/QQQ → MES/MNQ)?

The regime is computed from SPY only and is market-level, so it *should*
transfer. This script verifies it empirically: if the regime states cleanly
partition the index's forward volatility and returns (Stress = high vol, etc.),
then the regime gate that TREND_FOLLOW relies on is still useful on futures.

SAFE: imports HMMEngine read-only. Does NOT touch backtest/engine.py or any
package code. Mirrors production: train on SPY daily, predict forward (no
look-ahead), label each test day, then group index outcomes by regime.

RUN (from project root):
    & ".venv\\Scripts\\python.exe" "scratch\\regime_index_relevance.py"
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from raits.hmm.engine import HMMEngine

logging.getLogger("RAITS").setLevel(logging.WARNING)

HMM_TRAIN_FROM = "2018-01-01"
TEST_FROM      = "2021-01-01"
TEST_TO        = "2022-12-29"   # before vault boundary
INDICES        = ["SPY", "QQQ"]
FWD_VOL_DAYS   = 5              # forward realized-vol horizon
CACHE_DIR      = "./raits/data/cache"   # match package default; change if yours differs
OUT_PATH       = Path("scratch") / "regime_index_relevance.json"


def _load_api_key():
    import importlib.util as _ilu, os
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


def daily_close(ticker: str, start, end) -> pd.Series:
    pipe = _make_pipeline()
    hd = pipe.get_daily_data(ticker, pd.Timestamp(start), pd.Timestamp(end))
    return hd.to_dataframe()["close"].astype(float).sort_index()


def label_regimes(spy_close: pd.Series, test_dates: List[pd.Timestamp]) -> Dict[pd.Timestamp, str]:
    engine = HMMEngine()
    engine.fit(spy_close[spy_close.index < test_dates[0]])
    out: Dict[pd.Timestamp, str] = {}
    for d in test_dates:
        trail = spy_close[spy_close.index <= d].tail(60)
        try:
            out[d] = engine.state_name(engine.predict_current(trail))
        except Exception:
            out[d] = "Normal"
    return out


def analyze(index_close: pd.Series, regimes: Dict[pd.Timestamp, str]) -> dict:
    """Group index forward vol + forward return by regime label."""
    logret = np.log(index_close / index_close.shift(1))
    fwd_vol = logret.rolling(FWD_VOL_DAYS).std().shift(-FWD_VOL_DAYS) * np.sqrt(252)
    fwd_ret = (index_close.shift(-1) / index_close - 1.0)   # next-day return

    rows = []
    for d, reg in regimes.items():
        ts = pd.Timestamp(d)
        if ts not in index_close.index:
            # align to nearest available index trading day
            near = index_close.index[index_close.index.get_indexer([ts], method="nearest")[0]]
            ts = near
        rows.append({"regime": reg,
                     "fwd_vol": float(fwd_vol.get(ts, np.nan)),
                     "fwd_ret": float(fwd_ret.get(ts, np.nan))})
    dfr = pd.DataFrame(rows).dropna()

    summary = {}
    for reg, g in dfr.groupby("regime"):
        summary[reg] = {
            "days":            int(len(g)),
            "avg_fwd_vol_ann": round(float(g["fwd_vol"].mean()), 4),
            "avg_fwd_ret":     round(float(g["fwd_ret"].mean()), 5),
            "pct_up_days":     round(float((g["fwd_ret"] > 0).mean()), 3),
        }
    return summary


def main():
    test_dates = list(pd.bdate_range(TEST_FROM, TEST_TO))
    spy_close = daily_close("SPY", HMM_TRAIN_FROM, TEST_TO)
    regimes = label_regimes(spy_close, test_dates)

    report = {}
    for tk in INDICES:
        ic = daily_close(tk, TEST_FROM, TEST_TO)
        report[tk] = analyze(ic, regimes)
        print(f"\n=== {tk} forward outcomes by regime ===")
        print(json.dumps(report[tk], indent=2))

    # Interpretation hint
    print("\nREAD: a useful regime gate shows Stress >> Normal > Calm in avg_fwd_vol_ann.")
    print("If vol ordering holds and TREND_FOLLOW's allowed regimes (Normal/Stress)")
    print("capture the higher-vol/trending days, the regime layer transfers to futures.")

    OUT_PATH.parent.mkdir(exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2))
    print(f"\nFull results → {OUT_PATH}")


if __name__ == "__main__":
    main()
