"""
global_index/update_ibkr_daily.py
====================================
Daily IBKR bar append — extends parquet files by one trading session.

Run ONCE each morning (before run_live_day.py) to keep parquet data current.
Uses IBKR ContFuture (continuous, ratio back-adjusted) for bar fetch.

Back-adjustment note:
    Existing parquet (Databento): diff (Panama) back-adjusted to Dec 2024 contract.
    IBKR ContFuture: ratio back-adjusted to current contract.
    At the initial splice (first run after Databento fill), a one-time offset is
    applied to align price levels. Stored in _splice_offsets.json sidecar.
    Subsequent runs: no offset — IBKR bars are internally consistent.
    For EMA30/ATR14: absolute offset is absorbed within ~30 trading days.

Usage:
    cd d:\\raits
    IB Gateway must be running on port 4002 (paper).

    python -m global_index.update_ibkr_daily [--port 4002] [--dry-run]

    # Single instrument (debug):
    python -m global_index.update_ibkr_daily --symbols MES

Run order each morning:
    1. python -m global_index.update_ibkr_daily   # append yesterday's bars
    2. python -m global_index.update_spy_csv       # update HMM regime labels
    3. python -m global_index.run_live_day ...      # signal + orders

Timing: futures close 17:00 ET; run after 17:30 ET (IBKR data fully settled).
        Morning-before-open also works — yesterday is finalized by then.
"""
from __future__ import annotations
import argparse, json, logging, sys
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
from global_index import specs as gi_specs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("update_ibkr_daily")

# ── Instruments: (runner_name, ibkr_symbol, parquet_path) ────────────────────
def _build_jobs(data_dir: Path, nkd_path: Path) -> list[dict]:
    jobs = []
    for name, cfg in BASKET.items():
        jobs.append(dict(
            name=name,
            ibkr_symbol=name,          # MES/MNQ/MYM/M2K — IBKR ContFuture symbol
            parquet=data_dir / data_filename(cfg),
            exchange="CME",
        ))
    # NKD (MNKD uses same IBKR symbol "NKD" as the full contract — same price)
    jobs.append(dict(
        name="MNKD",
        ibkr_symbol="NKD",
        parquet=nkd_path,
        exchange="CME",
    ))
    return jobs


def _fetch_contfuture(ib, ibkr_symbol: str, exchange: str,
                      duration: str = "3 D") -> pd.DataFrame:
    """Fetch 1m bars from IBKR ContFuture (ratio back-adjusted continuous)."""
    import ib_insync as ibi  # type: ignore
    contract = ibi.ContFuture(ibkr_symbol, exchange=exchange)
    ib.qualifyContracts(contract)
    bars = ib.reqHistoricalData(
        contract,
        endDateTime="",             # "" = now
        durationStr=duration,
        barSizeSetting="1 min",
        whatToShow="TRADES",
        useRTH=False,
        formatDate=1,
    )
    if not bars:
        return pd.DataFrame()
    df = ibi.util.df(bars)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    # P2: ib_insync formatDate=1 returns tz-aware US/Central for CME.
    # Convert to ET naive for consistency with existing parquet.
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].sort_index()


def _load_parquet(path: Path) -> pd.DataFrame:
    """Load parquet; normalize index to ET naive."""
    df = pd.read_parquet(path)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    return df


def _apply_splice_offset(new_bars: pd.DataFrame, old_last_close: float) -> pd.DataFrame:
    """
    Shift new_bars OHLC so that new_bars.open[0] aligns with old_last_close.
    This is the one-time correction at the Databento→IBKR splice boundary.
    The offset = (old_last_close - new_bars.open[0]) is stored and reused
    so subsequent daily appends don't re-apply it.
    """
    offset = old_last_close - float(new_bars["open"].iloc[0])
    if abs(offset) < 1e-6:
        return new_bars, 0.0
    out = new_bars.copy()
    for col in ["open", "high", "low", "close"]:
        if col in out.columns:
            out[col] = out[col] + offset
    return out, offset


def main() -> None:
    ap = argparse.ArgumentParser(description="Append yesterday's IBKR bars to parquet")
    ap.add_argument("--port",          type=int, default=4002)
    ap.add_argument("--client-id",     type=int, default=2,
                    help="Use client_id=2 to avoid conflict with run_live_day (id=1)")
    ap.add_argument("--data-dir",      default="data/cache/futures")
    ap.add_argument("--nkd-parquet",   default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--splice-offsets",
                    default="global_index/data/_ibkr_splice_offsets.json",
                    help="JSON file storing per-instrument splice offsets (one-time)")
    ap.add_argument("--symbols",       nargs="*", default=None,
                    help="Subset to update, e.g. --symbols MES NKD")
    ap.add_argument("--duration",      default="3 D",
                    help="IBKR durationStr for ContFuture fetch (default: '3 D')")
    ap.add_argument("--dry-run",       action="store_true",
                    help="Connect + check coverage, no writes")
    a = ap.parse_args()

    data_dir = Path(a.data_dir)
    nkd_path = Path(a.nkd_parquet)
    offsets_path = Path(a.splice_offsets)
    jobs = _build_jobs(data_dir, nkd_path)
    if a.symbols:
        jobs = [j for j in jobs if j["name"] in a.symbols]

    # Load stored splice offsets
    splice_offsets: dict = {}
    if offsets_path.exists():
        with open(offsets_path) as f:
            splice_offsets = json.load(f)

    # Current coverage
    print("=" * 72)
    print(f"update_ibkr_daily — ContFuture append (port {a.port})")
    print(f"  dry-run: {a.dry_run}  |  duration: {a.duration}")
    print("=" * 72)
    print("\nCurrent parquet coverage:")
    for j in jobs:
        if j["parquet"].exists():
            df = pd.read_parquet(j["parquet"], columns=["close"])
            print(f"  {j['name']:<5} {j['parquet'].name}: last bar {df.index[-1]}")
        else:
            print(f"  {j['name']:<5} NOT FOUND: {j['parquet']}")

    if a.dry_run:
        print("\n[dry-run] No connection made. Remove --dry-run to append.")
        return

    # Connect IBKR
    log.info("Connecting IBKRBroker → 127.0.0.1:%d clientId=%d ...", a.port, a.client_id)
    try:
        import ib_insync as ibi  # type: ignore
    except ImportError:
        sys.exit("ib_insync not installed")

    ib = ibi.IB()
    ib.connect("127.0.0.1", a.port, clientId=a.client_id)

    # Suppress ib_insync noise
    import logging as _logging
    for _ln in ("ib_insync", "ib_insync.ib", "ib_insync.wrapper",
                "ib_insync.client", "ib_insync.util"):
        _l = _logging.getLogger(_ln)
        _l.setLevel(_logging.ERROR)
        _l.propagate = False

    log.info("Connected.")
    offsets_dirty = False
    failed = []

    try:
        for j in jobs:
            name = j["name"]
            parquet_path = j["parquet"]
            log.info("\n%s", "─" * 72)
            log.info("[%s] Fetching ContFuture bars (duration=%s) ...", name, a.duration)

            try:
                new_bars = _fetch_contfuture(ib, j["ibkr_symbol"], j["exchange"],
                                             duration=a.duration)
                ib.sleep(0.5)  # pacing: IBKR allows ~50 requests/10min

                if new_bars.empty:
                    log.warning("  %s: no bars returned — IBKR may be in maintenance", name)
                    failed.append(name)
                    continue

                log.info("  %s: fetched %d bars  %s → %s",
                         name, len(new_bars), new_bars.index[0], new_bars.index[-1])

                if not parquet_path.exists():
                    log.warning("  %s: parquet not found — run update_futures_data.py first", name)
                    failed.append(name)
                    continue

                existing = _load_parquet(parquet_path)
                last_existing = existing.index[-1]
                log.info("  %s: existing parquet last bar: %s", name, last_existing)

                # Apply one-time splice offset (Databento diff → IBKR ratio alignment)
                if name not in splice_offsets:
                    # First time: compute and store offset
                    old_last_close = float(existing["close"].iloc[-1])
                    new_bars_adj, offset = _apply_splice_offset(new_bars, old_last_close)
                    if abs(offset) > 0.01:
                        log.info("  %s: splice offset applied: %+.4f "
                                 "(Databento diff → IBKR ratio alignment, one-time)",
                                 name, offset)
                    splice_offsets[name] = offset
                    offsets_dirty = True
                else:
                    # Subsequent runs: apply stored offset to maintain consistency
                    stored_offset = splice_offsets[name]
                    new_bars_adj = new_bars.copy()
                    if abs(stored_offset) > 0.01:
                        for col in ["open", "high", "low", "close"]:
                            if col in new_bars_adj.columns:
                                new_bars_adj[col] = new_bars_adj[col] + stored_offset

                # Keep only NEW bars (after existing last bar)
                new_only = new_bars_adj[new_bars_adj.index > last_existing]
                if new_only.empty:
                    log.info("  %s: already up to date (no new bars after %s)",
                             name, last_existing)
                    continue

                log.info("  %s: appending %d new bars (%s → %s)",
                         name, len(new_only), new_only.index[0], new_only.index[-1])

                # Concat + sort + dedup
                keep_cols = [c for c in ["open", "high", "low", "close", "volume"]
                             if c in existing.columns]
                updated = pd.concat([existing[keep_cols], new_only[keep_cols]])
                updated = updated[~updated.index.duplicated(keep="last")].sort_index()

                # History invariant: existing bars must be UNCHANGED after append.
                # new_only contains only bars AFTER last_existing → no overlap.
                # This guard catches any future logic bug that modifies history.
                check_n   = min(200, len(existing))
                old_tail  = existing[keep_cols].tail(check_n)
                new_tail  = updated[keep_cols].reindex(old_tail.index)
                if not old_tail.equals(new_tail):
                    log.error("  %s: HISTORY INVARIANT VIOLATED — existing bars changed!", name)
                    log.error("       Rows with diff: %s",
                              old_tail.index[~old_tail.eq(new_tail).all(axis=1)].tolist()[:5])
                    log.error("  → NOT saving parquet. Investigate before proceeding.")
                    failed.append(name)
                    continue

                parquet_path.parent.mkdir(parents=True, exist_ok=True)
                updated.to_parquet(parquet_path)
                log.info("  %s: saved %s  (%d bars total, history-check OK)",
                         name, parquet_path.name, len(updated))

            except Exception as exc:
                log.exception("  %s: ERROR — %s", name, exc)
                failed.append(name)

    finally:
        ib.disconnect()
        log.info("Disconnected.")

    # Save splice offsets if updated
    if offsets_dirty:
        offsets_path.parent.mkdir(parents=True, exist_ok=True)
        with open(offsets_path, "w") as f:
            json.dump(splice_offsets, f, indent=2)
        log.info("Splice offsets saved: %s", offsets_path)

    print(f"\n{'='*72}")
    if failed:
        print(f"COMPLETED WITH ERRORS: {failed}")
    else:
        print(f"ALL {len(jobs)} INSTRUMENTS UPDATED")
        print("\nNext: python -m global_index.run_live_day ...")
    print("=" * 72)


if __name__ == "__main__":
    main()
