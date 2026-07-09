"""
global_index/update_futures_data.py
=====================================
Fill the futures parquet gap using Databento (GLBX.MDP3, ohlcv-1m, diff back-adjust).

Default: append-only — reads existing parquet end date, fetches only the missing
period (with 30-day overlap for back-adjustment splice alignment). Does NOT re-fetch
data you already have.

Usage:
    cd d:\\raits
    set DATABENTO_API_KEY=db-xxxxxxxxxxxx

    # Append-only (default) — fill gap from existing end date → yesterday:
    python -m global_index.update_futures_data [--dry-run]

    # Specific range (e.g. test a single instrument):
    python -m global_index.update_futures_data --symbols ES --start 2025-06-01

    # Full re-fetch from scratch (rare — only if parquet is corrupt or missing):
    python -m global_index.update_futures_data --full-refetch

Back-adjustment (splice):
    Existing parquet: diff-adjusted to the Dec 2024 contract (last bar 2024-12-31).
    New Databento fetch: diff-adjusted to today's contract (Sep 2026).
    These two series have the same raw prices but different cumulative offsets.

    Alignment: fetch with OVERLAP_DAYS=30 overlap so both series cover the same
    period. Compute per-bar mean offset over the overlap window; shift OLD data by
    this offset. Result: a seamless, fully diff-adjusted continuous series.

    This is equivalent to a full re-fetch but ~30× faster and costs only the gap.
"""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path

_CWD = Path.cwd()
if not ((_CWD / "global_index").is_dir() and (_CWD / "futures").is_dir()):
    sys.stderr.write(f"CWD guard FAIL: run from d:\\raits\n"); sys.exit(1)
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
from futures.basket import BASKET, data_filename
from global_index.fetch import fetch, back_adjust, roll_sanity, detect_rolls
from global_index import specs as gi_specs

# Number of overlap days fetched before parquet_end to compute splice offset.
OVERLAP_DAYS = 30

FULL_STARTS = {
    "ES":  "2017-01-01",
    "NQ":  "2017-01-01",
    "YM":  "2017-01-01",
    "RTY": "2017-07-01",   # RTY/M2K listed 2019-07-09; earlier data from macro proxy
    "NKD": "2018-01-01",
}


def _build_jobs(data_dir: Path, nkd_path: Path) -> list[dict]:
    jobs = []
    for name, cfg in BASKET.items():
        jobs.append(dict(name=name, symbol=cfg.data_symbol,
                         out=data_dir / data_filename(cfg)))
    jobs.append(dict(name="MNKD", symbol="NKD", out=nkd_path))
    return jobs


def _parquet_last_date(path: Path) -> "pd.Timestamp | None":
    if not path.exists():
        return None
    df = pd.read_parquet(path, columns=["close"])
    if df.empty:
        return None
    ts = df.index[-1]
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return pd.Timestamp(ts)


def _compute_splice_offset(old: pd.DataFrame, new_adj: pd.DataFrame) -> float:
    """
    Compute the additive offset to apply to OLD data so it aligns with NEW_ADJ.
    Both cover the same overlap window. Returns mean(new_adj.close - old.close)
    over bars present in both, rounded to nearest tick (0.25 for ES).
    """
    # Align indices — both are UTC or tz-naive; normalize to UTC naive
    def _to_utc_naive(df):
        idx = df.index
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        df = df.copy(); df.index = idx
        return df

    old_n   = _to_utc_naive(old)
    new_n   = _to_utc_naive(new_adj)
    common  = old_n.index.intersection(new_n.index)
    if len(common) == 0:
        return 0.0
    diff    = new_n.loc[common, "close"] - old_n.loc[common, "close"]
    offset  = float(diff.mean())
    return offset


def _apply_offset(df: pd.DataFrame, offset: float) -> pd.DataFrame:
    if abs(offset) < 1e-6:
        return df
    out = df.copy()
    for col in ["open", "high", "low", "close"]:
        if col in out.columns:
            out[col] = out[col] + offset
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Fill futures parquet gap from Databento (append-only by default)")
    ap.add_argument("--end",          default=None,
                    help="Last date to fetch (YYYY-MM-DD). Default: yesterday.")
    ap.add_argument("--start",        default=None,
                    help="Override fetch start (YYYY-MM-DD). Default: auto from parquet.")
    ap.add_argument("--data-dir",     default="data/cache/futures")
    ap.add_argument("--nkd-parquet",  default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--symbols",      nargs="*", default=None,
                    help="Subset, e.g. --symbols ES NKD")
    ap.add_argument("--full-refetch", action="store_true",
                    help="Re-fetch from original start dates (no append logic). "
                         "Use only if parquet is corrupt or missing.")
    ap.add_argument("--dry-run",      action="store_true",
                    help="Show what would be fetched; no API calls.")
    ap.add_argument("--api-key",      default=os.environ.get("DATABENTO_API_KEY"))
    a = ap.parse_args()

    end_date  = a.end or str((pd.Timestamp.now() - pd.Timedelta(days=1)).date())
    data_dir  = Path(a.data_dir)
    nkd_path  = Path(a.nkd_parquet)
    jobs      = _build_jobs(data_dir, nkd_path)
    if a.symbols:
        jobs = [j for j in jobs if j["symbol"] in a.symbols]

    print("=" * 72)
    print(f"update_futures_data — Databento GLBX.MDP3 ohlcv-1m")
    print(f"  mode:     {'FULL REFETCH' if a.full_refetch else 'append-only (gap fill)'}")
    print(f"  end:      {end_date}")
    print(f"  dry-run:  {a.dry_run}")
    print("=" * 72)

    # Show current coverage and planned fetch ranges
    print("\nCurrent coverage → fetch plan:")
    fetch_plans = []
    for j in jobs:
        last = _parquet_last_date(j["out"])
        if a.full_refetch or last is None:
            fetch_start = a.start or FULL_STARTS.get(j["symbol"], "2017-01-01")
            mode = "FULL"
        else:
            # Append: overlap back OVERLAP_DAYS calendar days for splice alignment
            overlap_start = last - pd.Timedelta(days=OVERLAP_DAYS)
            fetch_start = a.start or str(overlap_start.date())
            mode = f"GAP (overlap {OVERLAP_DAYS}d)"
        fetch_plans.append(dict(**j, last=last, fetch_start=fetch_start, mode=mode))
        last_str = str(last.date()) if last else "MISSING"
        print(f"  {j['symbol']:<5} {j['out'].name}: last={last_str} → "
              f"fetch {fetch_start}→{end_date}  [{mode}]")

    if a.dry_run:
        print("\n[dry-run] No API calls. Remove --dry-run to fetch.")
        return

    if not a.api_key:
        sys.exit("\nERROR: set DATABENTO_API_KEY or pass --api-key db-xxxx")

    failed = []
    for p in fetch_plans:
        sym, out = p["symbol"], p["out"]
        fetch_start, mode, last = p["fetch_start"], p["mode"], p["last"]
        print(f"\n{'─'*72}")
        print(f"[{sym}] Fetching {sym}.v.0  {fetch_start}→{end_date}  [{mode}] ...")

        try:
            raw = fetch(sym, fetch_start, end_date, a.api_key, roll="v")
            print(f"  pulled {len(raw):,} bars | {raw.index[0].date()} → {raw.index[-1].date()}")

            # Save raw sidecar (allows offline re-adjust; overwrites only the gap sidecar)
            raw_path = out.with_name(out.stem + "_raw.parquet")
            out.parent.mkdir(parents=True, exist_ok=True)
            raw.to_parquet(raw_path)

            # Back-adjust new chunk
            rolls = detect_rolls(raw["instrument_id"])
            new_adj = back_adjust(raw, "diff")
            san = roll_sanity(new_adj, raw, rolls)
            print(f"  rolls: {san['n_rolls']} | boundary |ret| "
                  f"raw={san['raw_max_boundary_ret']:.3%} → adj={san['adj_max_boundary_ret']:.3%}")

            cols = ["open", "high", "low", "close", "volume"]

            if a.full_refetch or last is None or not out.exists():
                # Write directly — no splice needed
                new_adj[cols].to_parquet(out)
                print(f"  wrote {out.name}  ({len(new_adj):,} bars)")
            else:
                # Append mode: compute splice offset over overlap window
                existing = pd.read_parquet(out)
                # Overlap = bars where both existing and new_adj cover same timestamps
                offset = _compute_splice_offset(existing, new_adj[cols])
                if abs(offset) > 0.01:
                    print(f"  splice offset: {offset:+.4f} "
                          f"(back-adjust anchor shift Dec 2024→Sep 2026)")
                    existing = _apply_offset(existing, offset)
                else:
                    print(f"  splice offset: ~0 (already aligned)")

                # Normalize indices to UTC-naive for concat
                def _normalize(df):
                    idx = df.index
                    if idx.tz is not None:
                        idx = idx.tz_convert("UTC").tz_localize(None)
                    df = df.copy(); df.index = idx
                    return df

                existing_n = _normalize(existing)
                new_n      = _normalize(new_adj[cols])

                # Keep existing up to overlap start; then new_adj from overlap start onward
                overlap_ts  = new_n.index[0]
                keep_old    = existing_n[existing_n.index < overlap_ts]
                combined    = pd.concat([keep_old, new_n])
                combined    = combined[~combined.index.duplicated(keep="last")].sort_index()

                combined.to_parquet(out)
                new_bar_count = len(combined) - len(existing_n)
                print(f"  appended ~{new_bar_count:,} new bars → "
                      f"{out.name}  ({len(combined):,} total)")
                print(f"  last bar: {combined.index[-1].date()}")

        except Exception as exc:
            print(f"  [ERROR] {sym}: {exc}")
            failed.append(sym)

    print(f"\n{'='*72}")
    if failed:
        print(f"COMPLETED WITH ERRORS: {failed}")
        print("Re-run with --symbols to retry.")
    else:
        print(f"ALL {len(jobs)} INSTRUMENTS UPDATED through {end_date}")
        print("\nNext:")
        print("  python -m global_index.update_ibkr_daily   # (daily from here)")
        print("  python -m global_index.run_live_day ...")
    print("=" * 72)


if __name__ == "__main__":
    main()
