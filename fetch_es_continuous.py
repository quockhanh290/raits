"""
fetch_es_continuous.py — RAITS Gate 1 data spike (Databento → ES continuous)
============================================================================
Pulls ES 1-minute OHLCV from Databento using CONTINUOUS front-month symbology,
back-adjusts across quarterly rolls so there is no artificial price jump, runs
roll-boundary sanity checks, and writes a parquet that `gate2_edge_harness.py`
reads directly (columns: open, high, low, close, volume; UTC tz-aware index).

This is a SPIKE-quality data layer (throwaway), not the production data module.
It is fully standalone and writes only to the --out path you give it.

Databento facts used (verified June 2026)
-----------------------------------------
    dataset   : GLBX.MDP3              (CME Globex: CME/CBOT/NYMEX/COMEX)
    schema    : ohlcv-1m              (1-minute OHLCV aggregates)
    stype_in  : continuous           (front-month stitching)
    symbol    : ES.c.0               (continuous, front by volume)
    timestamps: ts_event, UTC nanoseconds → to_df() gives a UTC DatetimeIndex
    pricing   : historical = pay-as-you-go; $125 free credit covers this spike

Back-adjustment note (honest limitation)
----------------------------------------
Continuous `ES.c.0` gives ONE contract at a time; at a roll the underlying
`instrument_id` changes and the raw price jumps by the calendar spread. We
detect rolls by instrument_id change and back-adjust history to the MOST RECENT
contract. Because c.0 alone shows only one contract per bar, the per-roll gap is
estimated from adjacent bars across the roll (seconds apart in market time, so
the gap ≈ the contract spread). For higher fidelity, pull c.0 AND c.1 and
compute the spread from both legs at the roll instant — left as a known upgrade.

Usage
-----
    pip install databento pyarrow pandas numpy
    export DATABENTO_API_KEY=db-XXXXXXXX
    python fetch_es_continuous.py --start 2021-01-01 --end 2023-01-01 \\
        --out data/cache/futures/ES_continuous_1m.parquet

    # validate the back-adjust math without touching the API:
    python fetch_es_continuous.py --self-test
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"
STYPE = "continuous"


# ══════════════════════════════════════════════════════════════════════════════
# Core (pure, testable) — roll detection + back-adjustment
# ══════════════════════════════════════════════════════════════════════════════
def detect_rolls(instrument_id: pd.Series) -> list[int]:
    """Return integer positions where the contract changes (first bar of new contract)."""
    changed = instrument_id.ne(instrument_id.shift(1))
    changed.iloc[0] = False                       # first bar is not a roll
    return list(np.flatnonzero(changed.to_numpy()))


def back_adjust(df: pd.DataFrame, method: str = "diff",
                max_roll_jump: float = 0.03, fallback_spread: float = 0.005) -> pd.DataFrame:
    """
    Back-adjust OHLC so the series is continuous, anchored to the MOST RECENT
    contract. History before each roll is shifted by the gap at that roll.

    method = 'diff'  : additive (Panama). adj_price = price + cumulative_delta
    method = 'ratio' : multiplicative.    adj_price = price * cumulative_factor
    method = 'none'  : passthrough (raw c.0, jumps intact)

    max_roll_jump : if the raw boundary gap exceeds this (e.g. a roll that lands
        on a huge weekend move like the 2020-03-22 COVID -10% gap), the excess is
        treated as GENUINE market movement, not contract spread. We then remove
        only `fallback_spread` (typical ES calendar spread) instead of the whole
        gap — so real volatility is preserved in history rather than erased.
    fallback_spread : spread fraction removed when a roll is jump-capped.

    Requires columns: open, high, low, close, volume, instrument_id (in order).
    Returns a copy with adjusted OHLC; 'raw_close' preserved for audit.
    """
    out = df.copy()
    out["raw_close"] = out["close"]
    if method == "none":
        return out.drop(columns=["instrument_id"])

    rolls = detect_rolls(out["instrument_id"])
    n = len(out)

    # cumulative adjustment applied to each bar. Bars from the LAST roll onward
    # get zero adjustment (they are the anchor contract). Walk rolls newest→oldest.
    add = np.zeros(n)          # additive deltas
    mul = np.ones(n)           # multiplicative factors
    capped = []                # rolls where the jump was treated as real move
    for r in reversed(rolls):
        prev_close = float(out["close"].iloc[r - 1])   # last bar of older contract
        new_open = float(out["open"].iloc[r])          # first bar of newer contract
        if prev_close == 0:
            continue
        raw_jump = new_open / prev_close - 1.0
        is_capped = abs(raw_jump) > max_roll_jump
        if is_capped:
            capped.append((r, raw_jump))
        if method == "diff":
            if is_capped:
                # remove only a typical spread, keep the rest as real market move
                delta = np.sign(raw_jump) * prev_close * fallback_spread
            else:
                delta = new_open - prev_close
            add[:r] += delta
        else:  # ratio
            if is_capped:
                factor = 1.0 + np.sign(raw_jump) * fallback_spread
            else:
                factor = new_open / prev_close
            mul[:r] *= factor

    if capped:
        msg = ", ".join(f"{df.index[r].date()} ({j:+.1%})" for r, j in reversed(capped))
        print(f"  [INFO] {len(capped)} roll(s) jump-capped (kept as real market move): {msg}")

    for col in ["open", "high", "low", "close"]:
        if method == "diff":
            out[col] = out[col] + add
        else:
            out[col] = out[col] * mul

    return out.drop(columns=["instrument_id"])


def roll_sanity(df_adj: pd.DataFrame, df_raw: pd.DataFrame, rolls: list[int]) -> dict:
    """Compare 1-bar return magnitude at roll boundaries before vs after adjust."""
    def boundary_ret(frame, positions):
        c = frame["close"].to_numpy()
        return [abs(c[p] / c[p - 1] - 1.0) for p in positions if p > 0]
    raw = boundary_ret(df_raw, rolls)
    adj = boundary_ret(df_adj.assign(close=df_adj["close"]), rolls)
    return {
        "n_rolls": len(rolls),
        "raw_max_boundary_ret": max(raw) if raw else 0.0,
        "adj_max_boundary_ret": max(adj) if adj else 0.0,
        "raw_mean_boundary_ret": float(np.mean(raw)) if raw else 0.0,
        "adj_mean_boundary_ret": float(np.mean(adj)) if adj else 0.0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Databento fetch
# ══════════════════════════════════════════════════════════════════════════════
def fetch(symbol: str, start: str, end: str, api_key: str) -> pd.DataFrame:
    import databento as db

    client = db.Historical(api_key)
    data = client.timeseries.get_range(
        dataset=DATASET,
        schema=SCHEMA,
        symbols=[f"{symbol}.c.0"],
        stype_in=STYPE,
        start=start,
        end=end,
    )
    df = data.to_df()                       # UTC DatetimeIndex (ts_event)
    df.columns = [c.lower() for c in df.columns]
    keep = ["open", "high", "low", "close", "volume", "instrument_id"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise RuntimeError(f"Databento df missing columns {missing}; got {list(df.columns)}")
    df = df[keep].copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.sort_index()


# ══════════════════════════════════════════════════════════════════════════════
# Self-test (no API) — proves the back-adjust math
# ══════════════════════════════════════════════════════════════════════════════
def self_test() -> None:
    print("Self-test: back-adjust across two synthetic rolls (diff + ratio)\n")
    # Build 3 contracts. True continuous move is +1 per bar. Inject contract
    # spreads of +20 and +15 at the two rolls (raw jumps that must vanish).
    idx = pd.date_range("2022-01-01", periods=12, freq="1min", tz="UTC")
    # raw closes: contract A then +20 jump to B then +15 jump to C
    a = [100, 101, 102, 103]
    b = [123, 124, 125, 126]          # = (103+1) + 19 spread → +20 raw jump
    c = [141, 142, 143, 144]          # = (126+1) + 14 spread → +15 raw jump
    closes = a + b + c
    opens = [closes[0]] + closes[:-1]  # open = prior close (simplification)
    opens[4] = 123; opens[8] = 141     # first bar of each new contract opens at its level
    df = pd.DataFrame({
        "open": opens, "high": [x + 0.5 for x in closes],
        "low": [x - 0.5 for x in closes], "close": closes,
        "volume": [1000] * 12,
        "instrument_id": [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3],
    }, index=idx)

    rolls = detect_rolls(df["instrument_id"])
    assert rolls == [4, 8], f"roll detection wrong: {rolls}"
    print(f"  rolls detected at positions {rolls}  (expected [4, 8])  OK")

    adj = back_adjust(df, "diff", max_roll_jump=1.0)
    # KNOWN LIMITATION: from c.0 alone the per-roll gap = spread + the genuine
    # 1-bar move; removing it zeroes that single roll bar's return. The correct
    # outcome is therefore: boundary jump REMOVED (~0, was +20/+15), the series
    # is continuous/monotonic, and the anchor (newest) contract is unchanged.
    d1 = adj["close"].iloc[4] - adj["close"].iloc[3]
    d2 = adj["close"].iloc[8] - adj["close"].iloc[7]
    print(f"  diff: Δclose at roll1={d1:+.2f}, roll2={d2:+.2f} (expect ~0 — jump removed)")
    assert abs(d1) < 1e-6 and abs(d2) < 1e-6, "diff adjust did not remove the roll jump"

    diffs = adj["close"].diff().dropna()
    assert (diffs >= -1e-9).all(), f"series not monotonic after adjust: min step {diffs.min()}"
    print(f"  diff: adjusted series monotonic, no negative jumps (min step {diffs.min():+.2f})  OK")

    # most-recent contract bars must be UNCHANGED (anchor)
    assert (adj["close"].iloc[8:] == df["close"].iloc[8:]).all(), "anchor contract altered"
    print("  diff: anchor (newest) contract prices unchanged  OK")

    san = roll_sanity(adj, df, rolls)
    print(f"  sanity: raw_max_boundary_ret={san['raw_max_boundary_ret']:.3f} → "
          f"adj_max_boundary_ret={san['adj_max_boundary_ret']:.5f}")
    assert san["adj_max_boundary_ret"] < 1e-6 < san["raw_max_boundary_ret"], "adjust did not remove jumps"

    adj_r = back_adjust(df, "ratio", max_roll_jump=1.0)
    r1 = adj_r["close"].iloc[4] / adj_r["close"].iloc[3] - 1
    print(f"  ratio: ret at roll1={r1:+.5f} (small, jump removed)")
    assert abs(r1) < 0.02, "ratio adjust failed"
    print("\nALL SELF-TESTS PASSED — back-adjust math is correct.\n")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    ap = argparse.ArgumentParser(description="Gate 1: Databento ES continuous fetcher.")
    ap.add_argument("--self-test", action="store_true", help="validate back-adjust math (no API)")
    ap.add_argument("--symbol", default="ES")
    ap.add_argument("--start", help="YYYY-MM-DD")
    ap.add_argument("--end", help="YYYY-MM-DD")
    ap.add_argument("--adjust", choices=["diff", "ratio", "none"], default="diff")
    ap.add_argument("--max-roll-jump", type=float, default=0.03,
                    help="rolls jumping more than this are kept as real market move (default 3%%)")
    ap.add_argument("--fallback-spread", type=float, default=0.005,
                    help="spread removed at a jump-capped roll (default 0.5%%)")
    ap.add_argument("--out", default="data/cache/futures/ES_continuous_1m.parquet")
    ap.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY"))
    ap.add_argument("--readjust-from", metavar="RAW_PARQUET",
                    help="re-run back-adjust OFFLINE from a saved raw file (no API/credit)")
    a = ap.parse_args()

    if a.self_test:
        self_test(); return

    # ── Offline re-adjust path (no API call, no credit) ──────────────────────
    if a.readjust_from:
        print(f"Re-adjusting offline from {a.readjust_from} (no API call) ...")
        raw = pd.read_parquet(a.readjust_from)
        if "instrument_id" not in raw.columns:
            ap.error("raw file has no instrument_id column — re-fetch once with this "
                     "patched version to produce a *_raw.parquet sidecar.")
    else:
        if not (a.start and a.end):
            ap.error("--start and --end are required (or use --self-test / --readjust-from)")
        if not a.api_key:
            ap.error("set DATABENTO_API_KEY env var or pass --api-key")
        print(f"Fetching {a.symbol}.c.0 {SCHEMA} {a.start}→{a.end} from {DATASET} ...")
        raw = fetch(a.symbol, a.start, a.end, a.api_key)
        # save the RAW (with instrument_id) so future re-adjusts need no credit
        raw_path = Path(a.out).with_name(Path(a.out).stem + "_raw.parquet")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(raw_path)
        print(f"  pulled {len(raw):,} bars | {raw.index[0]} → {raw.index[-1]}")
        print(f"  saved raw sidecar (for credit-free re-adjust): {raw_path}")

    rolls = detect_rolls(raw["instrument_id"])
    adj = back_adjust(raw, a.adjust, max_roll_jump=a.max_roll_jump,
                      fallback_spread=a.fallback_spread)
    san = roll_sanity(adj, raw, rolls)
    print(f"  rolls: {san['n_rolls']} | boundary |ret| max raw={san['raw_max_boundary_ret']:.3%}"
          f" → adj={san['adj_max_boundary_ret']:.3%}")
    if san["adj_max_boundary_ret"] > 0.01:
        print("  [WARN] residual roll jump > 1% after adjust — inspect roll boundaries "
              "(lower --max-roll-jump, or use c.0+c.1 spread method).")

    out_path = Path(a.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["open", "high", "low", "close", "volume"]
    adj[cols].to_parquet(out_path)
    print(f"  wrote {out_path}  ({len(adj):,} bars, columns {cols})")
    print("  → feed this to: gate2_edge_harness.py --parquet "
          f"{out_path} --strategy trend_follow")


if __name__ == "__main__":
    main()
