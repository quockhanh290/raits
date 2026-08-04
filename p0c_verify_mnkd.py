"""p0c_verify_mnkd.py — P0c: desired_position() offline+live-bars vs --print-signals.

Mirrors run_live_day EXACTLY:
  1. Load NKD frozen parquet → tz_convert(Asia/Tokyo)
  2. Connect IBKR → fetch_bars(MNKD, through=today+23:59) → ET-naive
  3. _concat_nkd_live: strip_tz(frozen) + live → same concat as signal_fn
  4. nkd_engine.desired_position(concat, nkd_labels, nkd_cost)

Compare with --print-signals output (4 fields: direction/entry/stop/entry_day).

Usage:
    cd d:\\raits
    python p0c_verify_mnkd.py [--port 4002] [--client-id 91]
"""
import sys
sys.path.insert(0, ".")

import argparse
import logging
import time
import pandas as pd

from futures.basket import REGIME, SWING_TF_PARAM
from futures.swing_tf import SwingTFEngine
from futures._validated_core import benchmark_daily, label_regimes
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.ibkr_broker import IBKRBroker

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s — %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("p0c_verify_mnkd")

# ── Constants (mirrors run_live_day.py exactly) ───────────────────────────────
NKD_INST       = "MNKD"
NKD_EMA        = 10
NKD_MULT_PARAM = SWING_TF_PARAM.get("chandelier_atr_mult", 2.5)
SLIPPAGE       = 2.0
HMM_FIT_END    = REGIME["hmm_fit_end"]
NKD_PARQUET    = "global_index/data/NKD_continuous_1m_8y.parquet"

# ── --print-signals output to verify against ─────────────────────────────────
LIVE_SIGNAL = {"direction": "LONG", "entry": 62720.00, "stop": 62601.43}


def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror run_live_day._strip_tz."""
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _concat_nkd_live(frozen_nkd_df, live_nkd_et):
    """Mirror run_live_day._concat_nkd_live exactly."""
    if live_nkd_et is None or live_nkd_et.empty:
        return _strip_tz(frozen_nkd_df)
    merged = pd.concat([_strip_tz(frozen_nkd_df), live_nkd_et])
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",      type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=91,
                    help="IBKR client ID (default 91 — avoids conflict with runner=1)")
    a = ap.parse_args()

    print("=== P0c MNKD: desired_position() + live bars vs --print-signals ===")
    print(f"  Live signal to verify: {LIVE_SIGNAL}")
    print()

    # ── 1. Load frozen NKD parquet (mirror run_live_day L156-157) ─────────────
    c_nkd = gi_specs.SPECS[NKD_INST]
    log.info("Loading NKD parquet: %s", NKD_PARQUET)
    ndf = gi_load(NKD_PARQUET)
    ndf.index = ndf.index.tz_convert(c_nkd.session_tz)   # → Asia/Tokyo tz-aware
    log.info("  Frozen: %d bars  [%s → %s]", len(ndf), ndf.index[0], ndf.index[-1])

    # ── 2. SPY labels (mirror run_live_day L162-167) ──────────────────────────
    bench        = benchmark_daily("spy_daily_live.csv")
    swing_labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
    spy_s        = pd.Series(swing_labels)
    idx          = pd.DatetimeIndex(spy_s.index)
    spy_s.index  = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nkd_labels   = RegimeLabels(spy_s.sort_index(), lag_days=1)
    log.info("  SPY labels: %d days  (lag_days=1)", len(swing_labels))

    # ── 3. Cost (mirror run_live_day L186-187) ────────────────────────────────
    nkd_cost = GIFC(
        point_value=c_nkd.point_value,
        tick=c_nkd.tick,
        commission_rt=c_nkd.commission_rt,
        slippage_ticks_per_side=SLIPPAGE,
    )

    # ── 4. Engine (mirror run_live_day L189-191) ──────────────────────────────
    nkd_engine = SwingTFEngine(
        ema_period=NKD_EMA,
        chandelier_atr_mult=NKD_MULT_PARAM,
        max_hold_days=5,
    )

    # ── 5. Connect IBKR + fetch live NKD bars (mirror --print-signals L267-278) ──
    log.info("Connecting IBKR port=%d client_id=%d ...", a.port, a.client_id)
    broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
    broker.connect()
    log.info("  Waiting 15s for IB Gateway farm connections to stabilize...")
    time.sleep(15)

    today = pd.Timestamp.now().normalize()
    through = today + pd.Timedelta(hours=23, minutes=59)
    log.info("  fetch_bars(%s, through=%s) ...", NKD_INST, through)
    live_bars = broker.fetch_bars(NKD_INST, through=through)
    if live_bars is not None and not live_bars.empty:
        log.info("  Live bars: %d  [%s → %s]", len(live_bars),
                 live_bars.index[0], live_bars.index[-1])
    else:
        log.warning("  fetch_bars returned empty — using frozen parquet only")

    # ── 6. Concat (mirror run_live_day _concat_nkd_live) ─────────────────────
    concat_nkd = _concat_nkd_live(ndf, live_bars)
    log.info("  Concat: %d bars  [%s → %s]",
             len(concat_nkd), concat_nkd.index[0], concat_nkd.index[-1])

    # ── 7. desired_position() on concat ──────────────────────────────────────
    log.info("Calling nkd_engine.desired_position(concat)...")
    sig = nkd_engine.desired_position(concat_nkd, nkd_labels, nkd_cost)

    # ── 8. Compare ────────────────────────────────────────────────────────────
    print()
    if sig is None:
        print("desired_position() returned: None")
        print()
        print("RESULT: MISMATCH — offline=None  live=LONG")
    else:
        print("desired_position() returned:")
        for k, v in sig.items():
            print(f"  {k:12s} = {v}")

        direction_ok = sig.get("direction") == LIVE_SIGNAL["direction"]
        entry_ok     = abs(float(sig.get("entry", 0)) - LIVE_SIGNAL["entry"]) < 1.0
        stop_ok      = abs(float(sig.get("stop",  0)) - LIVE_SIGNAL["stop"])  < 1.0

        print()
        print("=== Field comparison ===")
        print(f"  direction : {'OK  ' if direction_ok else 'MISMATCH'}  "
              f"offline={sig.get('direction')}  live={LIVE_SIGNAL['direction']}")
        print(f"  entry     : {'OK  ' if entry_ok     else 'MISMATCH'}  "
              f"offline={sig.get('entry'):.2f}  live={LIVE_SIGNAL['entry']:.2f}")
        print(f"  stop      : {'OK  ' if stop_ok      else 'MISMATCH'}  "
              f"offline={sig.get('stop'):.2f}  live={LIVE_SIGNAL['stop']:.2f}")
        entry_day = sig.get("entry_day")
        if entry_day:
            print(f"  entry_day : {entry_day}")

        all_ok = direction_ok and entry_ok and stop_ok
        print()
        print(f"P0c MNKD: {'*** PASS ***' if all_ok else '*** FAIL — investigate ***'}")


if __name__ == "__main__":
    main()
