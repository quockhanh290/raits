"""
tier2/fetch.py — Databento → tier-2 continuous DAILY (rates/FX/commodity)
=========================================================================
Reuses the VALIDATED back-adjust (detect_rolls + back_adjust) from the existing
fetch module — byte-identical roll math, already self-tested. The only change:
downloads DAILY bars (schema ohlcv-1d) instead of 1-min.

Why daily: trend-following on rates is a DAILY edge (multi-day trend, not intraday
microstructure). Structure test (Gate 1) and a daily trend backtest (Gate 2) both
need only daily closes. Fetching 1-min × 7y for rates would burn Databento credit
for data we won't use. If a later gate needs intraday, fetch 1-min then.

Roll note: rates roll quarterly (Mar/Jun/Sep/Dec). For Gate 1 (VR on daily
returns) a small quarterly roll artifact barely moves VR, so volume-roll (v) is
fine. Gate 2+ (edge, where roll spread hits P&L) needs the full roll diagnostic
like NKD/crude — do that only if Gate 1 clears.

Usage
-----
    export DATABENTO_API_KEY=db-XXXXXXXX
    # ZN (10Y note), volume-roll, additive back-adjust, daily:
    python -m tier2.fetch --symbol ZN --start 2018-01-01 --end 2025-01-01 \\
        --out tier2/data/ZN_daily_diff.parquet
    # ZB (30Y bond) similarly. --self-test validates the shared back-adjust math.
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# reuse the validated roll + back-adjust (do NOT re-implement)
from global_index.fetch import detect_rolls, back_adjust, self_test

DATASET = "GLBX.MDP3"          # covers CME/CBOT/NYMEX/COMEX → ZN/ZB (CBOT) OK
SCHEMA = "ohlcv-1d"            # DAILY (the tier-2 change)
STYPE = "continuous"


def fetch_daily(symbol: str, start: str, end: str, api_key: str, roll: str = "v") -> pd.DataFrame:
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
        raise RuntimeError(f"Databento df missing {missing}; got {list(df.columns)}")
    df = df[keep].copy()
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df.sort_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--symbol", default="ZN")
    ap.add_argument("--roll", choices=["v", "c", "n"], default="v")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--adjust", choices=["diff", "ratio", "none"], default="diff")
    ap.add_argument("--max-roll-jump", type=float, default=0.03)
    ap.add_argument("--fallback-spread", type=float, default=0.005)
    ap.add_argument("--out", default="tier2/data/ZN_daily_diff.parquet")
    ap.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY"))
    a = ap.parse_args()

    if a.self_test:
        self_test(); return
    if not (a.start and a.end and a.api_key):
        raise SystemExit("need --start --end and DATABENTO_API_KEY (or --api-key)")

    print(f"Fetching {a.symbol}.{a.roll}.0 {SCHEMA} {a.start}→{a.end} from {DATASET} ...")
    raw = fetch_daily(a.symbol, a.start, a.end, a.api_key, a.roll)
    print(f"  {len(raw)} daily bars, {raw['instrument_id'].nunique()} contracts, "
          f"{len(detect_rolls(raw['instrument_id']))} rolls")
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    # save raw (for offline re-adjust / audit)
    raw_path = out.with_name(out.stem + "_raw.parquet")
    raw.to_parquet(raw_path)
    adj = back_adjust(raw, method=a.adjust, max_roll_jump=a.max_roll_jump,
                      fallback_spread=a.fallback_spread)
    adj.to_parquet(out)
    print(f"  saved raw → {raw_path}")
    print(f"  saved back-adjusted ({a.adjust}) → {out}")
    print(f"  → next: python -m tier2.structure_test --parquet {out} --name {a.symbol}")


if __name__ == "__main__":
    main()
