"""p0c_verify_swing.py — P0c: swing desired_basket() + live bars vs --print-signals.

Mirrors run_live_day signal_fn EXACTLY for Rổ 4 (MES/MNQ/MYM/M2K):
  1. Load frozen swing parquets
  2. Connect IBKR → fetch_bars for all 4 instruments → ET-naive
  3. _concat_live(frozen, live) per instrument
  4. swing_engine.desired_basket(concat_dfs, swing_labels, costs_2t)
  5. Apply entry_day guard (cur=None path, same as signal_layer.py L173-175)

Expected output: direction/entry/stop/entry_day per instrument, filtered to entry_day=today.
Compare manually with --print-signals ENTRY lines.

Usage:
    cd d:\\raits
    python p0c_verify_swing.py [--port 4002] [--client-id 92]
"""
import sys
sys.path.insert(0, ".")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import argparse
import logging
import time
from pathlib import Path

import pandas as pd

from futures.basket import BASKET, REGIME, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures._validated_core import load_parquet, benchmark_daily, label_regimes
from global_index.ibkr_broker import IBKRBroker

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s — %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("p0c_verify_swing")

# ── Constants (mirrors run_live_day.py exactly) ───────────────────────────────
HMM_FIT_END = REGIME["hmm_fit_end"]
SLIPPAGE    = 2.0
DATA_DIR    = "data/cache/futures"


def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror run_live_day._strip_tz."""
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def _concat_live(frozen_df, live_df):
    """Mirror run_live_day._concat_live exactly."""
    if live_df is None or live_df.empty:
        return _strip_tz(frozen_df)
    merged = pd.concat([_strip_tz(frozen_df), live_df])
    return merged[~merged.index.duplicated(keep="last")].sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",      type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=92,
                    help="IBKR client ID (default 92 — avoids conflict with runner=1, p0c_mnkd=91)")
    ap.add_argument("--data-dir",  default=DATA_DIR)
    a = ap.parse_args()

    today_norm = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    print(f"=== P0c Swing (Rổ 4): desired_basket() + live bars vs --print-signals ===")
    print(f"  Today (ET): {today_norm.date()}")
    print(f"  Entry_day guard: only show signals where entry_day == today")
    print()

    # ── 0. Staleness check: spy_daily_live.csv (updated by pre-flight update_spy_csv) ─
    import os
    spy_csv = "spy_daily_live.csv"
    if not os.path.exists(spy_csv):
        sys.exit(f"ERROR: {spy_csv} not found — run pre-flight first:\n"
                 f"  python -m global_index.update_spy_csv --csv {spy_csv}")
    mtime = pd.Timestamp(os.path.getmtime(spy_csv), unit="s", tz="UTC").tz_convert("America/New_York")
    age_hours = (pd.Timestamp.now(tz="America/New_York") - mtime).total_seconds() / 3600
    if age_hours > 48:
        log.warning("spy_daily_live.csv is %.0fh old — regime labels may be stale. "
                    "Run update_spy_csv first.", age_hours)
    else:
        log.info("spy_daily_live.csv age: %.1fh — OK", age_hours)

    # ── 1. Load frozen swing parquets (mirrors run_live_day L153-154) ────────
    log.info("Loading frozen swing parquets from %s ...", a.data_dir)
    frozen_dfs = {
        n: load_parquet(str(Path(a.data_dir) / data_filename(c)))
        for n, c in BASKET.items()
    }
    for n, df in frozen_dfs.items():
        log.info("  %s: %d bars  last=%s", n, len(df), df.index[-1])

    # ── 2. SPY labels (mirrors run_live_day L162-163) ────────────────────────
    bench        = benchmark_daily("spy_daily_live.csv")
    swing_labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
    log.info("SPY labels: %d days", len(swing_labels))

    # ── 3. Costs (mirrors run_live_day L185: costs_for_basket(slippage=SLIPPAGE)) ─
    costs_2t = costs_for_basket(slippage_ticks=SLIPPAGE)

    # ── 4. Engine ─────────────────────────────────────────────────────────────
    swing_engine = SwingTFEngine()   # uses SWING_TF_PARAM defaults (ema_period=30 etc.)

    # ── 5. Connect IBKR + fetch live bars for all swing instruments ───────────
    log.info("Connecting IBKR port=%d client_id=%d ...", a.port, a.client_id)
    broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
    broker.connect()
    log.info("  Waiting 15s for IB Gateway farm connections to stabilize...")
    time.sleep(15)

    through = today_norm + pd.Timedelta(hours=23, minutes=59)
    log.info("  fetch_bars for all swing instruments (through=%s) ...", through)
    live_bars = {}
    for inst in BASKET:
        bars = broker.fetch_bars(inst, through=through)
        live_bars[inst] = bars
        if bars is not None and not bars.empty:
            log.info("  %s live: %d bars  [%s → %s]",
                     inst, len(bars), bars.index[0], bars.index[-1])
        else:
            log.warning("  %s live: EMPTY — using frozen only", inst)

    # ── 6. Concat frozen + live per instrument (mirrors signal_fn L239-242) ──
    concat_dfs = {
        inst: _concat_live(frozen_dfs[inst], live_bars.get(inst))
        for inst in frozen_dfs
    }
    for inst, df in concat_dfs.items():
        log.info("  %s concat: %d bars  last=%s", inst, len(df), df.index[-1])

    # ── 7. desired_basket() (mirrors signal_layer.py L159) ───────────────────
    log.info("Calling swing_engine.desired_basket(concat_dfs) ...")
    raw_basket = swing_engine.desired_basket(concat_dfs, swing_labels, costs_2t)

    # ── 8. Apply entry_day guard (mirrors signal_layer.py L173-175, held=[]) ─
    # For held=[] (no existing positions), cur=None for all → guard applies:
    #   desired[key] = sig if entry_day == today else None
    print()
    print("=== Raw desired_basket() → after entry_day guard (held=[]) ===")
    print()
    any_today = False
    for inst, sig in raw_basket.items():
        if sig is None:
            print(f"  {inst:6s}: None")
            continue
        new_ed = pd.Timestamp(sig["entry_day"]).normalize()
        passes_guard = (new_ed == today_norm)
        flag = "← ENTRY TODAY" if passes_guard else f"← BLOCKED (entry_day={new_ed.date()} ≠ today)"
        print(f"  {inst:6s}: dir={sig['direction']:5s}  entry={sig['entry']:.2f}"
              f"  stop={sig['stop']:.2f}  entry_day={new_ed.date()}  {flag}")
        if passes_guard:
            any_today = True

    print()
    if not any_today:
        print("No swing entry with entry_day=today.")
        print("→ --print-signals should show 0 swing entries.")
    else:
        print("Instruments above marked '← ENTRY TODAY' should appear in --print-signals.")
        print("Compare direction/entry/stop with --print-signals ENTRY lines.")

    print()
    print("NOTE: stop in desired_basket() = INITIAL intraday chandelier stop.")
    print("      If position already held, stop = RATCHETED EOD value (different).")


if __name__ == "__main__":
    main()
