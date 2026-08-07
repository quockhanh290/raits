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

# Largest price change, as a percentage, allowed between the parquet's last bar and
# the first bar appended after it. Above this the append is refused — see the join
# check in main() for why stopping beats re-anchoring.
#
# Measured on the last ~400k one-minute bars of each instrument (2026-08-07),
# against the Sep/Dec calendar spread quoted by IBKR the same day, both as a
# percentage of the instrument's price:
#
#   inst   p99.9 of |Δ| 1-min   roll spread
#   MES    0.152%   (11.75)     0.862%   ( 66.75)
#   MNQ    0.211%   (62.50)     1.006%   (298.25)
#   MYM    0.154%   (83.00)     0.741%   (400.00)
#   M2K    0.232%   ( 7.00)     0.779%   ( 23.50)
#
# 0.35% is the only value that clears every p99.9 by 1.5x AND sits 2.0x below every
# roll spread; the window is 0.348-0.370%. That it is this narrow is the finding:
# the worst ordinary minute (0.232%) and the smallest roll (0.741%) are only 3.2x
# apart, so there is not much room on either side. Re-measure before moving it.
#
# It has to be a fraction rather than a number of points — MYM trades near 54,000
# and M2K near 3,000 — and it cannot be set from magnitude alone: the largest
# one-minute move of the year is BIGGER than the roll spread on all four instruments
# (MES 118.50 against 66.75). What separates a roll from a violent minute is not size
# but rarity, and the join is one specific minute a day rather than all 400k of them.
JOIN_JUMP_MAX_PCT: float = 0.35

# ── Instruments: (runner_name, ibkr_symbol, parquet_path) ────────────────────
def _build_jobs(data_dir: Path, nkd_path: Path) -> list[dict]:
    jobs = []
    _EXCHANGE = {"MYM": "CBOT"}  # MYM (Micro Dow) is on CBOT, not CME
    for name, cfg in BASKET.items():
        jobs.append(dict(
            name=name,
            ibkr_symbol=name,          # MES/MNQ/MYM/M2K — IBKR ContFuture symbol
            parquet=data_dir / data_filename(cfg),
            exchange=_EXCHANGE.get(name, "CME"),
        ))
    # NKD (MNKD uses same IBKR symbol "NKD" as the full contract — same price)
    jobs.append(dict(
        name="MNKD",
        ibkr_symbol="NKD",
        parquet=nkd_path,
        exchange="CME",
    ))
    return jobs


def _split_entry(entry) -> "tuple[float, str]":
    """(offset, contract) from a splice-offsets sidecar entry.

    Entries used to be a bare float. A legacy one yields an empty contract, which
    reads as "unknown" rather than "unchanged": the first append after upgrading
    records what it used without claiming to know what came before it.
    """
    if entry is None:
        return 0.0, ""          # instrument not in the sidecar yet
    if isinstance(entry, dict):
        return float(entry.get("offset", 0.0)), str(entry.get("contract", ""))
    return float(entry), ""


def _fetch_contfuture(ib, ibkr_symbol: str, exchange: str,
                      duration: str = "3 D") -> "tuple[pd.DataFrame, str]":
    """Fetch 1m bars from IBKR ContFuture, with the contract they came from.

    qualifyContracts resolves a ContFuture to the expiry it currently tracks and
    fills in localSymbol — 'MESU6' today, 'MESZ6' after the September roll. That is
    the roll, stated outright, and comparing it against what the previous append
    used identifies one exactly. Inferring it from the size of a price jump does
    not: the largest one-minute move of the past year is bigger than the roll
    spread on every instrument in the basket.
    """
    import ib_insync as ibi  # type: ignore
    contract = ibi.ContFuture(ibkr_symbol, exchange=exchange)
    ib.qualifyContracts(contract)
    resolved = contract.localSymbol or contract.lastTradeDateOrContractMonth or ""
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
        return pd.DataFrame(), resolved
    df = ibi.util.df(bars)
    if df is None or df.empty:
        return pd.DataFrame(), resolved
    df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    # P2: ib_insync formatDate=1 returns tz-aware US/Central for CME.
    #
    # Store UTC-naive, NOT ET. The parquet's 8 years of Databento history are
    # UTC-naive and _validated_core.load_parquet reads the file with
    # pd.to_datetime(idx, utc=True) — it treats every value as UTC. Writing ET here
    # put two conventions in one file: from the first IBKR append (2026-07-06) every
    # bar was read four hours early, so between_time("14:00","15:55") selected the
    # 18:00-19:55 ET Globex evening instead of the US afternoon.
    #
    # It also corrupted the splice itself. The anchor compares the parquet's last bar
    # against the first new bar; with the old bar's UTC value read as ET, those two
    # were four hours apart, and that four hours of price movement was frozen into a
    # permanent offset — the +11.50 on MES, +183.00 on MNQ, -57.00 on MYM. Their
    # mixed signs give them away: real back-adjustment across a rollover moves
    # correlated index futures the same way.
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].sort_index(), resolved


def assert_utc_convention(df: "pd.DataFrame", label: str, sample_days: int = 5) -> None:
    """Fail loudly if the index is not on the UTC clock.

    CME index futures halt 17:00-18:00 ET daily, which is hour 21 in UTC (22 under
    EST). If the most recent sessions show their gap at hour 17 instead, the bars are
    ET-labelled and the file has two conventions in it.

    This exists because that is exactly what happened and nothing noticed for a
    month: from 2026-07-06 the appends were ET while the history was UTC, and every
    downstream reader silently shifted the new data four hours. The frozen backtests
    kept passing the whole time — they read a different file. One check on the halt
    position would have caught it the first day.
    """
    if df is None or df.empty:
        return
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        raise ValueError(f"{label}: index is tz-aware; expected UTC-naive")
    days = sorted({t.date() for t in idx})[-sample_days:]
    verdicts = []
    for d in days:
        hrs = {t.hour for t in idx if t.date() == d}
        if len(hrs) < 20:
            continue                      # half day, holiday or partial — no signal
        if 21 not in hrs or 22 not in hrs:
            verdicts.append(("UTC", d))
        elif 17 not in hrs:
            verdicts.append(("ET", d))
    et = [d for conv, d in verdicts if conv == "ET"]
    if et:
        raise ValueError(
            f"{label}: bars appear ET-labelled, not UTC — the daily halt shows at "
            f"hour 17 on {et}. Expected the gap at hour 21 (17:00 ET in UTC). "
            f"Mixing conventions in one file shifts every downstream read by 4h; "
            f"see the 2026-07-06 incident in SCRATCHPAD.md."
        )


def _load_parquet(path: Path) -> pd.DataFrame:
    """Load parquet as UTC-naive — the file's canonical convention.

    The docstring used to promise "normalize index to ET naive" and the guard below
    only fires for a tz-AWARE index. The stored index is naive, so the branch never
    ran and UTC values were handed back to be treated as ET. The promise and the
    behaviour disagreed, and nothing checked.

    A tz-aware index (should not occur) is converted to UTC rather than dropped, so
    the return type is one convention either way.
    """
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    return df


def _apply_splice_offset(new_bars: pd.DataFrame, old_last_close: float,
                         last_existing: "pd.Timestamp") -> tuple:
    """
    Shift new_bars OHLC so that the FIRST NEW BAR (after last_existing) aligns
    with old_last_close. Uses the splice-point bar, not the first fetched bar,
    to avoid embedding real market movement from the overlap window into the offset.

    Bug note: original code used new_bars.open[0] (first fetched bar, often hours
    before last_existing) instead of new_bars_after_last.open[0] (actual splice bar).
    If the market moved during the overlap, the wrong anchor embeds that move as a
    permanent step-change in the series.
    """
    new_after = new_bars[new_bars.index > last_existing]
    if new_after.empty:
        return new_bars, 0.0
    offset = old_last_close - float(new_after["open"].iloc[0])
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
                new_bars, fetched_contract = _fetch_contfuture(
                    ib, j["ibkr_symbol"], j["exchange"], duration=a.duration)
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
                stored_offset, stored_contract = _split_entry(splice_offsets.get(name))
                if name not in splice_offsets:
                    # First time: compute and store offset
                    old_last_close = float(existing["close"].iloc[-1])
                    new_bars_adj, offset = _apply_splice_offset(new_bars, old_last_close,
                                                               last_existing)
                    if abs(offset) > 0.01:
                        log.info("  %s: splice offset applied: %+.4f "
                                 "(Databento diff → IBKR ratio alignment, one-time)",
                                 name, offset)
                    splice_offsets[name] = {"offset": offset,
                                            "contract": fetched_contract}
                    offsets_dirty = True
                else:
                    # Subsequent runs: apply stored offset to maintain consistency
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

                # The join must be a market move, not a change of contract.
                #
                # IBKR ContFuture is ratio back-adjusted to whichever contract is
                # current, so its history is continuous but the bars we fetch are the
                # live contract's actual prices. We only ever append, so the first
                # append after a roll carries the next contract's price level while
                # everything before it carries the previous one's — and the splice
                # offset is computed once and never revisited. Measured 2026-08-07,
                # Sep vs Dec: +66.75 MES, +298.25 MNQ, +400.00 MYM, +23.50 M2K,
                # 0.74-1.01% of price and all the same sign.
                #
                # A jump like that is not a market event. It inflates the day's true
                # range, and daily ATR is Wilder-smoothed, so one fake bar widens the
                # chandelier band for ~56 sessions; an open position's recorded extreme
                # jumps with it and ratchets the stop to a level that never traded.
                #
                # The threshold is a fraction of price, not a number of points: the
                # four instruments differ by two orders of magnitude in absolute price.
                # It cannot be set from the size of the move alone — the largest
                # one-minute move of the past year EXCEEDS the roll spread on every
                # instrument (MES 118.50 vs 66.75, M2K 59.50 vs 23.50). What separates
                # them is how ordinary they are: p99.9 of one-minute moves is
                # 0.17-0.27% of price against 0.82-1.15% for a roll. 0.40% sits at
                # least 1.5x above every p99.9 and 2.0x below every roll spread, and
                # the join is one specific minute a day rather than all 400k of them.
                #
                # Stop rather than re-anchor. A jump can also mean bad data — the wrong
                # contract fetched, a corrupt bar — and adjusting automatically would
                # smooth a data error into a series that looks clean. Rolls happen four
                # times a year; losing one session is cheaper than corrupting the
                # history every backtest is measured against. exit(1) fails the
                # pre-flight, which skips the day's slots (fail-closed, already wired).
                _last_close = float(existing["close"].iloc[-1])
                _first_open = float(new_only["open"].iloc[0])
                _jump = _first_open - _last_close
                _jump_pct = abs(_jump) / _last_close * 100 if _last_close else 0.0
                log.info("  %s: join %.4f → %.4f  (%+.4f, %.3f%%)  contract %s",
                         name, _last_close, _first_open, _jump, _jump_pct,
                         fetched_contract or "(unknown)")

                # Did the CONTRACT change? That is the roll, and IBKR says it
                # outright — no inference from the size of the move, which cannot
                # work anyway (see JOIN_JUMP_MAX_PCT).
                if stored_contract and fetched_contract and stored_contract != fetched_contract:
                    log.error(
                        "  %s: CONTRACT ROLLED %s -> %s — refusing to append.",
                        name, stored_contract, fetched_contract)
                    log.error(
                        "       The stored offset (%+.4f) aligns the parquet to %s; bars "
                        "from %s sit on a different price level. Join was %+.4f (%.3f%%).",
                        stored_offset, stored_contract, fetched_contract, _jump, _jump_pct)
                    log.error(
                        "       Appending would put that step into the series: the day's "
                        "true range absorbs it, daily ATR is Wilder-smoothed so the "
                        "chandelier band stays wide for ~56 sessions, and an open "
                        "position's extreme ratchets its stop to a level that never traded.")
                    log.error(
                        "       OPERATOR: re-anchor %s in %s — offset %+.4f -> %+.4f "
                        "(old minus the join), contract -> %s — then re-run.",
                        name, a.splice_offsets, stored_offset,
                        stored_offset - _jump, fetched_contract)
                    failed.append(name)
                    continue

                # No roll, so a jump this size is not a change of contract: it is bad
                # data — the wrong contract fetched by hand, a corrupt bar, a feed
                # glitch. Loose on purpose, since identity already covers rolls and
                # this only has to sit above anything a real market does.
                if _jump_pct > JOIN_JUMP_MAX_PCT:
                    log.error(
                        "  %s: JOIN JUMP %.3f%% > %.2f%% with NO contract change (%s) "
                        "— refusing to append.\n"
                        "       parquet last close %.4f -> first new open %.4f (%+.4f)\n"
                        "       Not a roll, so this is a data problem: wrong contract,\n"
                        "       corrupt bar, or a feed glitch. Do not append.",
                        name, _jump_pct, JOIN_JUMP_MAX_PCT,
                        fetched_contract or "unknown",
                        _last_close, _first_open, _jump,
                    )
                    failed.append(name)
                    continue

                # Record what this append used, so the next one has something to
                # compare against. Legacy entries carry no contract; this fills it in
                # on the first run without pretending to know what came before.
                if fetched_contract and fetched_contract != stored_contract:
                    splice_offsets[name] = {"offset": stored_offset,
                                            "contract": fetched_contract}
                    offsets_dirty = True

                # Concat + sort + dedup
                keep_cols = [c for c in ["open", "high", "low", "close", "volume"]
                             if c in existing.columns]
                updated = pd.concat([existing[keep_cols], new_only[keep_cols]])
                updated = updated[~updated.index.duplicated(keep="last")].sort_index()

                # History invariant: existing bars must be UNCHANGED after append.
                # new_only contains only bars AFTER last_existing → no overlap.
                # This guard catches any future logic bug that modifies history.
                # Use float64 cast before equals(): parquet may store volume as int64
                # while IBKR returns float64; concat upcast causes dtype-only false positive
                # (equals() is dtype-strict; values are identical when Rows with diff=[]).
                check_n   = min(200, len(existing))
                old_tail  = existing[keep_cols].tail(check_n)
                new_tail  = updated[keep_cols].reindex(old_tail.index)
                old_f     = old_tail.astype("float64")
                new_f     = new_tail.astype("float64")
                if not old_f.equals(new_f):
                    diff_rows = old_f.index[~old_f.eq(new_f).all(axis=1)].tolist()[:5]
                    log.error("  %s: HISTORY INVARIANT VIOLATED — existing bars changed!", name)
                    log.error("       Rows with diff: %s", diff_rows)
                    log.error("  → NOT saving parquet. Investigate before proceeding.")
                    failed.append(name)
                    continue

                # Never write a file whose convention has drifted. Cheaper to fail
                # the update than to discover a month later that every downstream
                # read was four hours off.
                assert_utc_convention(updated, name)

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
        print("=" * 72)
        sys.exit(1)   # pre-flight detects failure via returncode != 0
    else:
        print(f"ALL {len(jobs)} INSTRUMENTS UPDATED")
        print("\nNext: python -m global_index.run_live_day ...")
    print("=" * 72)


if __name__ == "__main__":
    main()
