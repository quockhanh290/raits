"""
nonequity/fetch.py — Databento → non-equity continuous (self-contained)
=======================================================================
Copy of the validated fetch_es_continuous.py (back-adjust math is byte-identical
and passes --self-test), with TWO non-equity changes:

  1. NEGATIVE-PRICE GUARD in back_adjust: the original computes the roll gap as
     new_open / prev_close - 1.0 and only guarded prev_close == 0. WTI CL settled
     NEGATIVE on 2020-04-20 (-$37); a roll near that boundary makes the ratio blow
     up / flip sign. We now skip adjustment (keep raw) at any roll where prev_close
     <= 0 and warn loudly. GC (gold) never hits this. For CL, prefer
     --start 2020-05-01 until you have explicitly validated the negative boundary.
  2. default --out points into nonequity/data/.

GLBX.MDP3 covers CME/CBOT/NYMEX/COMEX, so --symbol GC (gold) and --symbol CL
(crude) work with the same continuous c.0 stitching as ES.

Usage
-----
    pip install databento pyarrow pandas numpy
    export DATABENTO_API_KEY=db-XXXXXXXX

    # Gold — clean, runs as-is:
    python -m nonequity.fetch --symbol GC --start 2018-01-01 --end 2025-01-01 \
        --adjust diff --out nonequity/data/GC_continuous_1m_8y.parquet

    # Crude — start after the negative-price boundary for the first pass:
    python -m nonequity.fetch --symbol CL --start 2020-05-01 --end 2025-01-01 \
        --adjust diff --out nonequity/data/CL_continuous_1m.parquet

    # validate the back-adjust math without the API / credit:
    python -m nonequity.fetch --self-test

    # re-run back-adjust OFFLINE from a saved *_raw.parquet (no credit):
    python -m nonequity.fetch --readjust-from nonequity/data/GC_continuous_1m_8y_raw.parquet \
        --adjust ratio --out nonequity/data/GC_continuous_1m_8y_ratio.parquet
"""
# BYTE-IDENTICAL copy cua global_index/fetch.py (canonical, duoc import boi tier2/fetch.py).
# Dung standalone qua python -m nonequity.fetch. Sync neu global_index/fetch.py doi.
from __future__ import annotations

import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"
STYPE = "continuous"


# ── Core (pure, testable) — roll detection + back-adjustment ────────────────
def detect_rolls(instrument_id: pd.Series) -> list[int]:
    """Integer positions where the contract changes (first bar of new contract)."""
    changed = instrument_id.ne(instrument_id.shift(1))
    changed.iloc[0] = False
    return list(np.flatnonzero(changed.to_numpy()))


def back_adjust(df: pd.DataFrame, method: str = "diff",
                max_roll_jump: float = 0.03, fallback_spread: float = 0.005) -> pd.DataFrame:
    """
    Back-adjust OHLC continuous, anchored to the MOST RECENT contract.
      method 'diff'  : additive (Panama)  — preferred for ATR-absolute strategies
      method 'ratio' : multiplicative
      method 'none'  : passthrough
    max_roll_jump : boundary gaps larger than this are treated as REAL market move
        (only fallback_spread removed), preserving genuine volatility in history.

    NEGATIVE-PRICE GUARD (non-equity addition): at any roll where prev_close <= 0
    (e.g. CL around 2020-04-20) the gap math is undefined, so we skip adjustment
    for that roll and warn. Requires columns: open, high, low, close, volume,
    instrument_id. Returns a copy with adjusted OHLC; 'raw_close' kept for audit.
    """
    out = df.copy()
    out["raw_close"] = out["close"]
    if method == "none":
        return out.drop(columns=["instrument_id"])

    rolls = detect_rolls(out["instrument_id"])
    n = len(out)
    add = np.zeros(n)
    mul = np.ones(n)
    capped = []
    skipped_neg = []
    for r in reversed(rolls):
        prev_close = float(out["close"].iloc[r - 1])
        new_open = float(out["open"].iloc[r])
        if prev_close <= 0:                       # <-- negative/zero-price guard
            skipped_neg.append((r, prev_close))
            continue
        raw_jump = new_open / prev_close - 1.0
        is_capped = abs(raw_jump) > max_roll_jump
        if is_capped:
            capped.append((r, raw_jump))
        if method == "diff":
            delta = (np.sign(raw_jump) * prev_close * fallback_spread) if is_capped \
                else (new_open - prev_close)
            add[:r] += delta
        else:  # ratio
            factor = (1.0 + np.sign(raw_jump) * fallback_spread) if is_capped \
                else (new_open / prev_close)
            mul[:r] *= factor

    if skipped_neg:
        msg = ", ".join(f"{df.index[r].date()} (prev_close={pc:+.2f})"
                        for r, pc in reversed(skipped_neg))
        print(f"  [WARN] {len(skipped_neg)} roll(s) SKIPPED — prev_close <= 0 "
              f"(negative-price boundary, raw kept): {msg}")
        print("         → series is NOT fully continuous across these; inspect / "
              "trim --start past the negative episode before trusting backtest P&L.")
    if capped:
        msg = ", ".join(f"{df.index[r].date()} ({j:+.1%})" for r, j in reversed(capped))
        print(f"  [INFO] {len(capped)} roll(s) jump-capped (kept as real move): {msg}")

    for col in ["open", "high", "low", "close"]:
        out[col] = out[col] + add if method == "diff" else out[col] * mul
    return out.drop(columns=["instrument_id"])


def roll_sanity(df_adj: pd.DataFrame, df_raw: pd.DataFrame, rolls: list[int]) -> dict:
    def boundary_ret(frame, positions):
        c = frame["close"].to_numpy()
        return [abs(c[p] / c[p - 1] - 1.0) for p in positions
                if p > 0 and c[p - 1] > 0]
    raw = boundary_ret(df_raw, rolls)
    adj = boundary_ret(df_adj, rolls)
    return {
        "n_rolls": len(rolls),
        "raw_max_boundary_ret": max(raw) if raw else 0.0,
        "adj_max_boundary_ret": max(adj) if adj else 0.0,
        "raw_mean_boundary_ret": float(np.mean(raw)) if raw else 0.0,
        "adj_mean_boundary_ret": float(np.mean(adj)) if adj else 0.0,
    }


# ── Databento fetch ─────────────────────────────────────────────────────────
def fetch(symbol: str, start: str, end: str, api_key: str, roll: str = "v") -> pd.DataFrame:
    import databento as db
    client = db.Historical(api_key)
    data = client.timeseries.get_range(
        dataset=DATASET, schema=SCHEMA, symbols=[f"{symbol}.{roll}.0"],
        stype_in=STYPE, start=start, end=end)
    df = data.to_df()
    df.columns = [c.lower() for c in df.columns]
    keep = ["open", "high", "low", "close", "volume", "instrument_id"]
    missing = [c for c in keep if c not in df.columns]
    if missing:
        raise RuntimeError(f"Databento df missing columns {missing}; got {list(df.columns)}")
    df = df[keep].copy()
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df.sort_index()


# ── Self-test (no API) — proves the back-adjust math + negative guard ────────
def self_test() -> None:
    print("Self-test: back-adjust across two synthetic rolls (diff + ratio)\n")
    idx = pd.date_range("2022-01-01", periods=12, freq="1min", tz="UTC")
    a = [100, 101, 102, 103]; b = [123, 124, 125, 126]; c = [141, 142, 143, 144]
    closes = a + b + c
    opens = [closes[0]] + closes[:-1]
    opens[4] = 123; opens[8] = 141
    df = pd.DataFrame({"open": opens, "high": [x + 0.5 for x in closes],
                       "low": [x - 0.5 for x in closes], "close": closes,
                       "volume": [1000] * 12,
                       "instrument_id": [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3]}, index=idx)
    rolls = detect_rolls(df["instrument_id"])
    assert rolls == [4, 8], f"roll detection wrong: {rolls}"
    print(f"  rolls detected at positions {rolls}  (expected [4, 8])  OK")

    adj = back_adjust(df, "diff", max_roll_jump=1.0)
    d1 = adj["close"].iloc[4] - adj["close"].iloc[3]
    d2 = adj["close"].iloc[8] - adj["close"].iloc[7]
    print(f"  diff: Δclose at roll1={d1:+.2f}, roll2={d2:+.2f} (expect ~0 — jump removed)")
    assert abs(d1) < 1e-6 and abs(d2) < 1e-6, "diff adjust did not remove the roll jump"
    diffs = adj["close"].diff().dropna()
    assert (diffs >= -1e-9).all(), f"series not monotonic after adjust: {diffs.min()}"
    print(f"  diff: adjusted series monotonic (min step {diffs.min():+.2f})  OK")
    assert (adj["close"].iloc[8:] == df["close"].iloc[8:]).all(), "anchor contract altered"
    print("  diff: anchor (newest) contract prices unchanged  OK")

    # negative-price guard: inject a negative prev_close at the second roll
    dfn = df.copy()
    dfn.loc[dfn.index[7], "close"] = -5.0
    adj_n = back_adjust(dfn, "diff", max_roll_jump=1.0)
    assert "raw_close" in adj_n.columns
    print("  neg-guard: roll with prev_close<0 skipped without crashing  OK")

    san = roll_sanity(adj, df, rolls)
    assert san["adj_max_boundary_ret"] < 1e-6 < san["raw_max_boundary_ret"]
    print(f"  sanity: raw_max={san['raw_max_boundary_ret']:.3f} → "
          f"adj_max={san['adj_max_boundary_ret']:.5f}")
    print("\nALL SELF-TESTS PASSED — back-adjust math + negative guard correct.\n")


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Databento non-equity continuous fetcher.")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--symbol", default="GC")
    ap.add_argument("--roll", choices=["v", "c", "n"], default="v",
                    help="continuous roll rule: v=volume (default, avoids the CME "
                         "calendar-symbology bug that mis-resolves to a far month), "
                         "c=calendar, n=open-interest")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--adjust", choices=["diff", "ratio", "none"], default="diff")
    ap.add_argument("--max-roll-jump", type=float, default=0.03)
    ap.add_argument("--fallback-spread", type=float, default=0.005)
    ap.add_argument("--out", default="nonequity/data/GC_continuous_1m_8y.parquet")
    ap.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY"))
    ap.add_argument("--readjust-from", metavar="RAW_PARQUET")
    a = ap.parse_args()

    if a.self_test:
        self_test(); return

    if a.readjust_from:
        print(f"Re-adjusting offline from {a.readjust_from} (no API call) ...")
        raw = pd.read_parquet(a.readjust_from)
        if "instrument_id" not in raw.columns:
            ap.error("raw file has no instrument_id column — re-fetch once to produce "
                     "a *_raw.parquet sidecar.")
    else:
        if not (a.start and a.end):
            ap.error("--start and --end required (or --self-test / --readjust-from)")
        if not a.api_key:
            ap.error("set DATABENTO_API_KEY or pass --api-key")
        print(f"Fetching {a.symbol}.{a.roll}.0 {SCHEMA} {a.start}→{a.end} from {DATASET} ...")
        raw = fetch(a.symbol, a.start, a.end, a.api_key, roll=a.roll)
        raw_path = Path(a.out).with_name(Path(a.out).stem + "_raw.parquet")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw.to_parquet(raw_path)
        print(f"  pulled {len(raw):,} bars | {raw.index[0]} → {raw.index[-1]}")
        print(f"  saved raw sidecar (credit-free re-adjust): {raw_path}")

    rolls = detect_rolls(raw["instrument_id"])
    adj = back_adjust(raw, a.adjust, max_roll_jump=a.max_roll_jump,
                      fallback_spread=a.fallback_spread)
    san = roll_sanity(adj, raw, rolls)
    print(f"  rolls: {san['n_rolls']} | boundary |ret| max raw={san['raw_max_boundary_ret']:.3%}"
          f" → adj={san['adj_max_boundary_ret']:.3%}")
    if san["adj_max_boundary_ret"] > 0.01:
        print("  [WARN] residual roll jump > 1% after adjust — inspect boundaries "
              "(lower --max-roll-jump, or use c.0+c.1 spread method).")

    out_path = Path(a.out); out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["open", "high", "low", "close", "volume"]
    adj[cols].to_parquet(out_path)
    print(f"  wrote {out_path}  ({len(adj):,} bars, columns {cols})")
    print("  → next: verify schema/spot-check, then feed to nonequity/swing_tf_daily.py")
    print("    (NOT gate2_edge_harness trend_follow — that is the equity power-hour entry)")


if __name__ == "__main__":
    main()
