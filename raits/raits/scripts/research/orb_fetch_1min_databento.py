"""
Fetch the ORB_RETEST_SCALP execution data: 1-minute bars, top-5 lit venues,
sliced to 09:30-10:45 ET.
(RESEARCH ONLY — raits/raits/scripts/research/. Touches no production code.)

EVERY CHOICE HERE WAS MEASURED, NOT ASSUMED
-------------------------------------------
Venue set — top 5 lit venues, merged high=max / low=min.
    Measured on a random sample of the real selected universe against an
    unadjusted Polygon reference: top-5 reproduces consolidated RTH extremes
    with a MEDIAN residual of 0.0000%, and adding the other 9 venues changes
    neither the median nor the p95 on the high side. XNAS.ITCH alone was
    0.0219% with 90% coverage — cheaper, but one venue is not enough on a
    mid/small-cap universe.

Time slice — 09:30-10:45 ET.
    ORB forms its range 09:30-09:45 and signals to 10:15; 10:45 leaves room
    for the retest window and time stop. Measured cost: this slice is 16.6% of
    a full session's billable bytes (not 7.8%, which is its share of the CLOCK
    — the open is the densest part of the day). That is the difference between
    a ~$230 pull and a ~$38 one.

Universe — the union of the two pre-committed variants (314 symbols).
    C+O (common + foreign ordinary) is the primary study universe; C+O+A adds
    ADRs as a robustness check. Their scanner selections differ by more than
    the ADRs themselves, because adding names to the pool re-ranks everything,
    so both lists are bought once and analysed separately.

    ETFs/ETNs, preferreds, warrants, units, MLPs, CEFs and royalty trusts are
    excluded — 55% of the nominally tradeable pool, nearly half of it ETFs.
    ORBUniverseScanner ranks on gap FREQUENCY, and leveraged ETFs gap by
    construction, so it hunted them down systematically. That is a bias in the
    selection rule, not noise in the data.

Session boundary — the slice is applied after converting to America/New_York,
    never by a fixed UTC offset. An earlier version of this comparison used
    Databento's full-session daily bars against Polygon's RTH-only ones and
    produced a confident, wrong answer; the tell was that merging MORE venues
    made the residual worse, which max() cannot do.

Requires:
    set DATABENTO_API_KEY=db-XXXXXXXX

Run:
    cd d:\\raits
    python raits\\raits\\scripts\\research\\orb_fetch_1min_databento.py
    python raits\\raits\\scripts\\research\\orb_fetch_1min_databento.py --approve-cost
    python raits\\raits\\scripts\\research\\orb_fetch_1min_databento.py --consolidate
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parents[4]

RESEARCH = _ROOT / "raits" / "data" / "cache" / "research_daily"
DAILY_PARQUET = RESEARCH / "databento_ohlcv1d.parquet"
BUY_LIST = RESEARCH / "universe_BUY.txt"
RAW_DIR = _ROOT / "raits" / "data" / "cache" / "orb_1min"
OUT_PARQUET = RAW_DIR / "_consolidated_1m.parquet"

VENUES = ["XNAS.ITCH", "XNYS.PILLAR", "ARCX.PILLAR", "BATS.PITCH", "EDGX.PITCH"]
SCHEMA = "ohlcv-1m"
WIN_OPEN, WIN_CLOSE = "09:30", "10:45"
QUOTE_SAMPLE_DAYS = 12


def _client():
    key = os.environ.get("DATABENTO_API_KEY", "")
    if not key:
        print("NO API KEY — nothing fetched, no cost incurred.")
        print("  PowerShell:  $env:DATABENTO_API_KEY = 'db-XXXXXXXX'")
        return None
    import databento as db
    return db.Historical(key)


def _symbols() -> list:
    if not BUY_LIST.exists():
        print(f"  Missing {BUY_LIST}")
        return []
    return [x.strip() for x in BUY_LIST.read_text(encoding="utf-8").splitlines() if x.strip()]


def _trading_days() -> list:
    if not DAILY_PARQUET.exists():
        return []
    d = pd.read_parquet(DAILY_PARQUET).reset_index()
    tc = next((c for c in ("ts_event", "index", "date") if c in d.columns), None)
    dates = pd.to_datetime(d[tc]).dt.tz_localize(None).dt.normalize().unique()
    return sorted(pd.Timestamp(x) for x in dates)


def _bounds(day: pd.Timestamp):
    """UTC bounds of the ORB window on `day`, via America/New_York so DST is
    handled per-day. A fixed offset would be an hour wrong for half the year."""
    s = pd.Timestamp(f"{day.date()} {WIN_OPEN}", tz="America/New_York")
    e = pd.Timestamp(f"{day.date()} {WIN_CLOSE}", tz="America/New_York")
    return s.tz_convert("UTC"), e.tz_convert("UTC")


def _path(venue: str, day: pd.Timestamp) -> Path:
    return RAW_DIR / venue / f"{day.date()}.parquet"


def quote(client, syms: list, days: list) -> float:
    """Price a spread sample of days and extrapolate. Quoting all 4,190
    (venue, day) pairs would take longer than the fetch itself."""
    step = max(1, len(days) // QUOTE_SAMPLE_DAYS)
    sample = days[::step][:QUOTE_SAMPLE_DAYS]
    print(f"  quoting {len(sample)} sample days x {len(VENUES)} venues "
          f"(metadata only, $0)")
    per_day = 0.0
    for day in sample:
        s, e = _bounds(day)
        for v in VENUES:
            try:
                per_day += float(client.metadata.get_cost(
                    dataset=v, symbols=syms, schema=SCHEMA,
                    start=s.isoformat(), end=e.isoformat(), stype_in="raw_symbol"))
            except Exception as ex:
                print(f"    {day.date()} {v}: {type(ex).__name__}: {str(ex)[:80]}")
    avg = per_day / max(len(sample), 1)
    total = avg * len(days)
    print(f"\n  average per trading day : ${avg:.4f}")
    print(f"  trading days            : {len(days):,}")
    print(f"  ESTIMATED TOTAL         : ${total:,.2f}")
    return total


_TL = threading.local()
_LOCK = threading.Lock()


def _thread_client():
    """One client per thread. The SDK's thread-safety is not documented, and a
    shared connection is the obvious thing to get subtly wrong under
    concurrency, so each worker gets its own."""
    c = getattr(_TL, "client", None)
    if c is None:
        import databento as db
        c = db.Historical(os.environ["DATABENTO_API_KEY"])
        _TL.client = c
    return c


def _one(v: str, day: pd.Timestamp, syms: list, retries: int = 4):
    """Fetch a single (venue, day). Returns 'ok' | 'empty' | 'err:<msg>'.

    Backs off on rate limiting rather than failing: at 8 workers the API is
    the shared resource, and a 429 means slow down, not stop.
    """
    s, e = _bounds(day)
    for attempt in range(retries):
        try:
            data = _thread_client().timeseries.get_range(
                dataset=v, schema=SCHEMA, symbols=syms,
                start=s.isoformat(), end=e.isoformat(), stype_in="raw_symbol")
            try:
                df = data.to_df(map_symbols=True)
            except TypeError:
                df = data.to_df()
            tmp = _path(v, day).with_suffix(".tmp")
            if len(df) == 0:
                # Empty marker so a resume does not retry holidays forever.
                pd.DataFrame(columns=["symbol", "open", "high", "low",
                                      "close", "volume"]).to_parquet(tmp)
                os.replace(tmp, _path(v, day))
                return "empty"
            df.reset_index().to_parquet(tmp)
            # Atomic rename: a half-written parquet would be treated as done
            # by the next resume and silently leave a hole in the data.
            os.replace(tmp, _path(v, day))
            return "ok"
        except Exception as ex:
            msg = str(ex)
            transient = ("429" in msg or "rate" in msg.lower()
                         or "timeout" in msg.lower() or "connection" in msg.lower())
            if transient and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            return f"err:{type(ex).__name__}: {msg[:80]}"


def fetch(client, syms: list, days: list, workers: int = 1) -> None:
    todo = [(v, d) for d in days for v in VENUES if not _path(v, d).exists()]
    done = len(days) * len(VENUES) - len(todo)
    print(f"\n  requests: {len(todo):,} to do, {done:,} already on disk")
    print(f"  workers : {workers}")
    if not todo:
        print("  Nothing to fetch.")
        return
    for v in VENUES:
        (RAW_DIR / v).mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    counts = {"ok": 0, "empty": 0, "err": 0}
    shown = []

    def _tick(res, i):
        with _LOCK:
            if res.startswith("err"):
                counts["err"] += 1
                if len(shown) < 10:
                    shown.append(res)
                    print(f"    {res}")
            else:
                counts[res] += 1
            n = counts["ok"] + counts["empty"] + counts["err"]
            if n % 100 == 0 or n == len(todo):
                el = time.time() - t0
                rate = n / max(el, 1e-9)
                eta = (len(todo) - n) / max(rate, 1e-9)
                print(f"  {n:,}/{len(todo):,}  ok={counts['ok']:,} "
                      f"empty={counts['empty']:,} err={counts['err']:,}  "
                      f"{rate:.2f} req/s  elapsed {el / 60:.1f}m  "
                      f"ETA {eta / 60:.0f}m", flush=True)

    if workers <= 1:
        for i, (v, day) in enumerate(todo, 1):
            _tick(_one(v, day, syms), i)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, v, d, syms): (v, d) for v, d in todo}
            for i, f in enumerate(as_completed(futs), 1):
                _tick(f.result(), i)

    el = time.time() - t0
    print(f"\n  done in {el / 60:.1f}m: ok={counts['ok']:,} "
          f"empty={counts['empty']:,} err={counts['err']:,}")
    if counts["err"]:
        print("  Re-run to retry the failures — existing files are skipped.")


def consolidate() -> None:
    print("=" * 78)
    print("CONSOLIDATE — merge venues, verify, write one frame")
    print("=" * 78)
    frames = []
    for v in VENUES:
        files = sorted((RAW_DIR / v).glob("*.parquet"))
        if not files:
            print(f"  {v:<14} no files")
            continue
        parts = []
        for f in files:
            try:
                x = pd.read_parquet(f)
            except Exception:
                continue
            if len(x):
                parts.append(x)
        if not parts:
            print(f"  {v:<14} {len(files):,} files, all empty")
            continue
        d = pd.concat(parts, ignore_index=True)
        d["venue"] = v
        frames.append(d)
        print(f"  {v:<14} {len(files):,} files -> {len(d):,} bars")
    if not frames:
        print("  Nothing to consolidate.")
        return
    allv = pd.concat(frames, ignore_index=True)

    tc = next((c for c in ("ts_event", "index") if c in allv.columns), None)
    ts = pd.to_datetime(allv[tc], utc=True).dt.tz_convert("America/New_York")
    allv["ts"] = ts.dt.tz_localize(None)
    allv["date"] = allv["ts"].dt.normalize()

    # ── self-checks ─────────────────────────────────────────────────────────
    print("\n  SELF-CHECKS")
    t = allv["ts"].dt.time
    lo, hi = pd.Timestamp(WIN_OPEN).time(), pd.Timestamp(WIN_CLOSE).time()
    outside = int(((t < lo) | (t > hi)).sum())
    print(f"    1. bars outside {WIN_OPEN}-{WIN_CLOSE} ET : {outside:,} "
          f"{'OK' if outside == 0 else 'FAIL — the slice is wrong'}")

    per_day = allv.groupby(["symbol", "date"]).size()
    print(f"    2. bars per symbol-day: median {per_day.median():.0f}, "
          f"max {per_day.max():.0f}  (76 minutes x {len(VENUES)} venues = "
          f"{76 * len(VENUES)} ceiling)")
    print(f"       {'OK' if per_day.max() <= 76 * len(VENUES) else 'FAIL — over ceiling'}")

    bad = int((allv["high"] < allv["low"]).sum())
    print(f"    3. bars with high < low: {bad:,} {'OK' if bad == 0 else 'FAIL'}")

    print(f"\n  symbols {allv['symbol'].nunique():,} | "
          f"days {allv['date'].nunique():,} | bars {len(allv):,}")

    merged = allv.groupby(["symbol", "ts"]).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum")).reset_index()
    merged.to_parquet(OUT_PARQUET)
    print(f"\n  merged (high=max, low=min across venues): {len(merged):,} bars")
    print(f"  written: {OUT_PARQUET}")
    print("\n  NOTE: `open` and `close` are taken from an arbitrary venue's bar")
    print("  within the minute — the true consolidated open/close needs trade")
    print("  timestamps, which OHLCV does not carry. high/low are exact, and")
    print("  those are what the retest rule tests.")
    print("=" * 78)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--approve-cost", action="store_true",
                    help="required to actually download (this spends money)")
    ap.add_argument("--workers", type=int, default=8,
                    help="concurrent requests. The bottleneck is round-trip latency, not bandwidth or CPU, so threads help. Start at 8; drop it if errors climb.")
    ap.add_argument("--venues", default="",
                    help="comma-separated subset to fetch, e.g. XNAS.ITCH. "
                         "Lets you run one process per venue in parallel — the "
                         "output layout is already per-venue so they cannot "
                         "collide. STOP any other running fetch first: the "
                         "skip-if-exists check happens when the work list is "
                         "built, so two processes covering the same venue will "
                         "both fetch and you pay twice.")
    ap.add_argument("--consolidate", action="store_true",
                    help="merge what is on disk; fetches nothing")
    a = ap.parse_args()

    if a.consolidate:
        consolidate()
        return

    print("=" * 78)
    print("ORB 1-MINUTE FETCH — top-5 lit venues, 09:30-10:45 ET")
    print("=" * 78)
    global VENUES
    if a.venues:
        want = [v.strip() for v in a.venues.split(",") if v.strip()]
        bad = [v for v in want if v not in VENUES]
        if bad:
            print(f"  unknown venue(s): {bad}")
            print(f"  valid: {', '.join(VENUES)}")
            return
        VENUES = want

    syms, days = _symbols(), _trading_days()
    if not syms or not days:
        print("  Missing universe_BUY.txt or the daily parquet.")
        return
    print(f"  symbols : {len(syms):,}")
    print(f"  days    : {len(days):,}  ({days[0].date()} .. {days[-1].date()})")
    print(f"  venues  : {', '.join(VENUES)}")
    print(f"  window  : {WIN_OPEN}-{WIN_CLOSE} ET (16.6% of a full session)")
    print(f"  output  : {RAW_DIR}")

    client = _client()
    if client is None:
        return
    total = quote(client, syms, days)

    if not a.approve_cost:
        print("\n  Nothing downloaded. Re-run with --approve-cost to fetch.")
        print("  The fetch is resumable — interrupt it freely, existing files")
        print("  are skipped on the next run.")
        print("=" * 78)
        return
    fetch(client, syms, days, a.workers)
    print("\n  Next:  --consolidate")
    print("=" * 78)


if __name__ == "__main__":
    main()
