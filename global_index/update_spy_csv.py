"""
global_index/update_spy_csv.py — Fetch latest SPY daily close → append to spy_daily.csv
========================================================================================
Keeps spy_daily.csv fresh so HMMStaleGuard.check_day() does not trigger G1 HARD-STALE.

HMMStaleGuard reads the last date in spy_daily.csv.  If it is >2 business days stale,
G1 SOFT-STALE fires (entries warned).  >5 business days → G1 HARD-STALE, all entries
blocked.  This script prevents that by appending any missing rows before each run_day.

Source: Polygon.io (polygon-api-client already installed in RAITS env).
        IBKR historical daily bars are an alternative once live — swap fetch_spy_close().
API key: set POLYGON_API_KEY env var, or pass --api-key.

Usage (run before each FuturesRunner.run_day, or as part of the launch script):

    python -m global_index.update_spy_csv --csv d:/raits/spy_daily.csv

    # or specify key directly:
    python -m global_index.update_spy_csv --csv spy_daily.csv --api-key db-XXXX

Typical schedule: once daily, 6:00 AM ET on US trading days (after prior day's close
is available from Polygon).  Can also run from the live-launch script just before
instantiating FuturesRunner.

CSV format (matches existing spy_daily.csv):
    date,close
    2017-01-03,193.97
    2017-01-04,195.12
    ...
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# ── Snapshot discipline ───────────────────────────────────────────────────────

SNAPSHOT_DIR = Path("spy_snapshots")  # relative to CWD (d:\raits)


def save_snapshot(csv_path: Path, snapshot_dir: Path = SNAPSHOT_DIR) -> Path | None:
    """Copy csv_path → snapshot_dir/<stem>_snapshot_<last_date>.csv before any update.
    Returns snapshot path, or None if CSV does not exist yet.
    Skips silently if an identical snapshot already exists (idempotent).
    """
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    last_date = pd.to_datetime(df["date"]).max().date().isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snap = snapshot_dir / f"{csv_path.stem}_snapshot_{last_date}.csv"
    if snap.exists():
        log.info("Snapshot already exists (no-op): %s", snap.name)
    else:
        shutil.copy2(str(csv_path), str(snap))
        log.info("Snapshot saved: %s", snap)
    return snap


def verify_regime_labels(snap_path: Path, new_csv: Path,
                          check_end: str = "2024-12-31") -> int:
    """Compare HMM regime labels for 2018-2024 between snapshot and updated CSV.
    Returns count of dates where label changed (should be 0).

    Why labels, not just prices:
        Labels = HMM.decode(prices). Prices bất biến + HMM code bất biến → labels bất biến.
        But HMM refit (code change / different seed / different fit_end) with SAME prices
        can give DIFFERENT labels. Price verify alone does NOT catch HMM drift.
        This function verifies labels DIRECTLY.

    Logs WARNING if any label changed, with date list (up to 10 examples).
    Runs label_regimes twice (old spy + new spy) with production HMM params.
    """
    try:
        from futures._validated_core import benchmark_daily, label_regimes
    except ImportError:
        log.warning("verify_regime_labels: cannot import futures._validated_core — skipping")
        return 0

    try:
        old_bench = benchmark_daily(str(snap_path))
        new_bench = benchmark_daily(str(new_csv))
    except Exception as exc:
        log.warning("verify_regime_labels: could not load CSVs — %s", exc)
        return 0

    hmm_train_end = "2018-01-01"
    n_components  = 3
    hmm_fit_end   = check_end  # production: 2024-12-31

    try:
        old_labels = label_regimes(old_bench, hmm_train_end, n_components, hmm_fit_end)
        new_labels = label_regimes(new_bench, hmm_train_end, n_components, hmm_fit_end)
    except Exception as exc:
        log.warning("verify_regime_labels: label_regimes failed — %s", exc)
        return 0

    import pandas as _pd
    cutoff = _pd.Timestamp(check_end)
    old_labels = _pd.Series(old_labels)
    new_labels = _pd.Series(new_labels)
    common = old_labels.index.intersection(new_labels.index)
    common = common[common <= cutoff]

    diff_idx = [d for d in common if old_labels.get(d) != new_labels.get(d)]
    n_diff = len(diff_idx)

    if n_diff:
        log.warning(
            "LABEL DRIFT: %d date(s) with changed regime label (2018→%s): %s%s",
            n_diff, check_end,
            [str(d.date()) for d in diff_idx[:10]],
            " ..." if n_diff > 10 else "",
        )
        log.warning(
            "  Possible causes: (1) Polygon revised SPY prices, "
            "(2) HMM code/params changed, (3) refit with different seed. "
            "Compare snapshot vs updated CSV and check HMM fit_end."
        )
    else:
        log.info("Regime labels unchanged (%d dates verified through %s) — HMM stable",
                 len(common), check_end)
    return n_diff


def verify_historical_prices(snap_path: Path, new_csv: Path, overlap_start: date) -> int:
    """Compare rows BEFORE overlap_start between snapshot and updated CSV.
    Returns count of rows whose close price changed (should be 0).
    Logs WARNING if any change detected — Polygon may have revised history.
    """
    old = pd.read_csv(snap_path)
    new = pd.read_csv(new_csv)
    for df in (old, new):
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"])

    cutoff = pd.Timestamp(overlap_start)
    old_h = old[old["date"] < cutoff].set_index("date")["close"]
    new_h = new[new["date"] < cutoff].set_index("date")["close"]
    common = old_h.index.intersection(new_h.index)
    changed = int(((old_h.loc[common] - new_h.loc[common]).abs() > 0.001).sum())
    if changed:
        log.warning(
            "PRICE REVISION: %d historical row(s) changed before %s — "
            "SPY labels may have shifted. Compare %s vs updated CSV.",
            changed, overlap_start, snap_path.name,
        )
    else:
        log.info("Historical prices unchanged (%d rows verified before %s) — labels stable",
                 len(common), overlap_start)
    return changed


# ── Data fetch (wire here when ready) ────────────────────────────────────────


def fetch_spy_close(api_key: str, from_date: date, to_date: date) -> pd.DataFrame:
    """
    Fetch SPY daily close bars from Polygon.io for [from_date, to_date] inclusive.
    Returns DataFrame with columns: date (str "YYYY-MM-DD"), close (float).

    MUST pass adjusted=True to Polygon.
    spy_daily.csv uses Polygon adjusted=True close (2017-01-03 = 225.24 as of 2026-07-06
    correction; prior frozen value was 193.97 from ~2017 fetch — 32 quarterly dividends
    caused ~16% drift over 8 years, corrected 2026-07-06).
    HMM features are log-returns: on ex-dividend days, adjusted vs unadjusted returns
    differ by ~0.3-0.4% (the dividend yield), which is enough to flip a Calm/Normal
    label at the boundary.  Always use adjusted=True.

    Source: Polygon.io (polygon-api-client already installed; key in config_private.py).
    Alternative: IBKRBroker.fetch_bars("SPY", through=to_date) reshaped to daily,
    but IBKR historical data is split-adjusted only — DO NOT use for this CSV.
    """
    from polygon import RESTClient
    client = RESTClient(api_key)
    bars = client.get_aggs(
        "SPY", 1, "day",
        from_=str(from_date), to=str(to_date),
        adjusted=True, limit=50000,
    )
    rows = []
    for b in bars:
        ts = pd.Timestamp(b.timestamp, unit="ms", tz="UTC").tz_convert("America/New_York")
        rows.append({"date": ts.date().isoformat(), "close": float(b.close)})
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


# ── Core update logic ─────────────────────────────────────────────────────────


OVERLAP_DAYS = 30   # re-fetch last N calendar days and replace them (see docstring)


def update_spy_csv(csv_path: Path, api_key: str,
                   snapshot_dir: Path = SNAPSHOT_DIR) -> int:
    """
    Extend spy_daily.csv with new rows.  Returns number of NEW rows added.
    Raises NotImplementedError until fetch_spy_close() is wired.

    Adjustment consistency strategy (IMPORTANT — do not change to pure-append):
    -------------------------------------------------------------------------
    spy_daily.csv uses Polygon adjusted=True (dividend-adjusted) close prices.
    Polygon retroactively re-adjusts ALL historical prices whenever a new dividend
    ex-date is processed.  For SPY quarterly dividends (~$1.50-1.90/share), the
    re-adjustment shifts prices ~0.3-0.4% at the ex-div boundary.

    A pure append (only fetch rows newer than last_date) would create a boundary
    discontinuity: old rows use the pre-dividend adjustment basis, new rows use
    the post-dividend basis.  The resulting log-return at the boundary is wrong
    by ~0.3-0.4%, which can flip a Calm/Normal regime label.

    Fix: always re-fetch the last OVERLAP_DAYS calendar days and REPLACE those
    rows.  This ensures the overlap window is on the same adjustment basis as the
    new data.  Rows older than the overlap window are never touched (they are
    already on a stable basis — no new dividends affect them).

    Strategy:
      1. Compute fetch_from = max(last_date - OVERLAP_DAYS, first_date).
      2. Fetch [fetch_from, today] with adjusted=True.
      3. Replace rows >= fetch_from in existing CSV with the fetched rows.
      4. Atomic write-back.
    """
    if csv_path.exists():
        existing = pd.read_csv(csv_path, parse_dates=["date"])
        last_date = existing["date"].max().date()
        first_date = existing["date"].min().date()
        n_before = len(existing)
    else:
        from datetime import timedelta
        last_date = date(2017, 1, 1)
        first_date = date(2017, 1, 1)
        existing = pd.DataFrame(columns=["date", "close"])
        n_before = 0
        log.info("spy_daily.csv not found at %s — will create fresh", csv_path)

    today = date.today()
    if last_date >= today:
        log.info("spy_daily.csv up-to-date (last=%s)", last_date)
        return 0

    # ── Snapshot BEFORE any mutation ──────────────────────────────────────────
    snap_path = save_snapshot(csv_path, snapshot_dir)

    from datetime import timedelta
    fetch_from = max(last_date - timedelta(days=OVERLAP_DAYS), first_date)
    log.info(
        "Fetching SPY close [%s, %s] (overlap %dd for adjustment consistency)",
        fetch_from, today, OVERLAP_DAYS,
    )

    fetched = fetch_spy_close(api_key, fetch_from, today)
    if fetched.empty:
        log.warning("fetch_spy_close returned empty — no update applied")
        return 0

    fetched["date"] = pd.to_datetime(fetched["date"])

    # Keep old rows that are BEFORE the fetch window (untouched, stable adjustment basis)
    existing["date"] = pd.to_datetime(existing["date"])
    keep = existing[existing["date"] < pd.Timestamp(fetch_from)]

    # Replace overlap window + new rows with freshly-fetched data
    combined = pd.concat([keep, fetched], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date"]).sort_values("date")
    combined["date"] = combined["date"].dt.strftime("%Y-%m-%d")

    tmp = csv_path.with_suffix(".tmp")
    combined[["date", "close"]].to_csv(tmp, index=False)
    os.replace(str(tmp), str(csv_path))

    if snap_path:
        verify_historical_prices(snap_path, csv_path, fetch_from)
        verify_regime_labels(snap_path, csv_path)   # verify labels directly (prices→labels insufficient)

    n_after = len(combined)
    n_new = max(0, n_after - n_before)
    log.info(
        "Updated %s: %d new row(s), %d total (last=%s)",
        csv_path, n_new, n_after, combined["date"].iloc[-1],
    )
    return n_new


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch SPY daily close and append to spy_daily.csv "
                    "(keeps HMMStaleGuard G1 fresh)."
    )
    parser.add_argument(
        "--csv", default="spy_daily.csv",
        help="Path to spy_daily.csv (default: spy_daily.csv in cwd)",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="Polygon.io API key (fallback: POLYGON_API_KEY env var)",
    )
    parser.add_argument(
        "--snapshot-dir", default=str(SNAPSHOT_DIR),
        help=f"Directory for pre-update snapshots (default: {SNAPSHOT_DIR})",
    )
    args = parser.parse_args(argv)

    api_key = args.api_key or os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        sys.exit(
            "ERROR: Polygon.io API key required. "
            "Pass --api-key KEY or set POLYGON_API_KEY env var.\n"
            "Key is in config_private.py as POLYGON_API_KEY."
        )

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        n = update_spy_csv(Path(args.csv), api_key, snapshot_dir=Path(args.snapshot_dir))
    except NotImplementedError as exc:
        sys.exit(f"fetch_spy_close not yet wired: {exc}")

    if n == 0:
        print("spy_daily.csv: already up-to-date")
    else:
        print(f"spy_daily.csv: appended {n} new row(s)")


if __name__ == "__main__":
    main()
