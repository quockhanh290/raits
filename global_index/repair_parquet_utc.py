"""
global_index/repair_parquet_utc.py — rebuild the ET-labelled tail as UTC

Since the first IBKR append (2026-07-06) update_ibkr_daily wrote ET-naive bars into
files whose 8 years of Databento history are UTC-naive. _validated_core.load_parquet
reads everything with pd.to_datetime(idx, utc=True), so that tail was read four hours
early — between_time("14:00","15:55") selected the 18:00-19:55 ET Globex evening
instead of the US afternoon, for a month.

The same bug corrupted the splice. _apply_splice_offset anchors the parquet's last
close to the first new bar's open; with the old bar's UTC value read as ET the two
were four hours apart, and that movement was frozen into a permanent offset — +11.50
MES, +183.00 MNQ, -57.00 MYM, +7.20 M2K, +1065.00 MNKD. Mixed signs give them away:
genuine back-adjustment across a rollover moves correlated index futures the same way.
Measured against the live contract, the offset was 0.00 the day before the splice and
exactly 11.50 (std 0.00) after.

And it left a hole. The parquet's last Databento bar is 2026-07-06 23:59 UTC = 19:59
ET; the first appended bar is 2026-07-07 00:00 ET. Four hours and one minute of
market data was never written.

Three faults, one cause. This drops the tail and refetches it from IBKR on the UTC
clock, which repairs all three at once.

Safe by construction: dry-run unless --apply, writes a new file and only swaps after
the checks pass, and never touches the Databento history.

    python -m global_index.repair_parquet_utc                 # dry-run
    python -m global_index.repair_parquet_utc --apply
"""
from __future__ import annotations
import argparse
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.update_ibkr_daily import assert_utc_convention

# Last bar written by Databento. Everything after it is the ET-labelled tail.
SPLICE_UTC = pd.Timestamp("2026-07-06 23:59:00")

INSTRUMENTS = {
    "MES":  ("data/cache/futures/ES_continuous_1m_8y.parquet",  "MES",  "CME"),
    "MNQ":  ("data/cache/futures/NQ_continuous_1m_8y.parquet",  "MNQ",  "CME"),
    "MYM":  ("data/cache/futures/YM_continuous_1m_8y.parquet",  "MYM",  "CBOT"),
    "M2K":  ("data/cache/futures/RTY_continuous_1m_8y.parquet", "M2K",  "CME"),
    "MNKD": ("global_index/data/NKD_continuous_1m_8y.parquet",  "NKD",  "CME"),
}

REQUEST_GAP_S = 11.0     # IBKR allows ~60 historical requests per 10 minutes
JOIN_TOLERANCE = 0.02    # 2% — a real gap at the join is possible, a scale error is not


def _front_month(ib, symbol: str, exchange: str):
    import ib_insync as ibi
    from global_index.ibkr_broker import _current_front_month
    # ROLL_SCHEDULE is keyed by the IBKR symbol — "NKD", not the raits name "MNKD".
    # Passing the raits name returned None, the contract went out with no month, and
    # IBKR rejected it as ambiguous across fifteen listed expiries.
    month = _current_front_month(symbol)
    if not month:
        raise ValueError(f"{symbol}: no front month in ROLL_SCHEDULE — refusing to "
                         f"send an unqualified contract")
    c = ibi.Future(symbol, lastTradeDateOrContractMonth=month,
                   exchange=exchange, currency="USD")
    ib.qualifyContracts(c)
    if not getattr(c, "localSymbol", ""):
        raise ValueError(f"{symbol} {month}: qualifyContracts returned no localSymbol")
    return c


def _fetch_window(ib, contract, end_utc: pd.Timestamp, duration: str = "1 W"):
    """One week ending at end_utc, returned UTC-naive.

    Weekly, not daily. A "1 D" request whose endDateTime lands mid-session returns a
    truncated window — 409 bars against the session's 1380 — and stepping day by day
    that way loses most of the data. A week-long window covers whole sessions, and
    overlapping requests are deduplicated by the caller.

    endDateTime uses the yyyymmdd-hh:mm:ss form, which IBKR reads as UTC. The
    'yyyymmdd hh:mm:ss US/Eastern' form is rejected by this Gateway (error 10314).

    Verified to return the full 1380-bar session with its gap at hour 21 UTC — the
    17:00-18:00 ET CME halt — matching the Databento history's convention exactly.
    """
    import ib_insync as ibi
    bars = ib.reqHistoricalData(
        contract, endDateTime=end_utc.strftime("%Y%m%d-%H:%M:%S"),
        durationStr=duration, barSizeSetting="1 min", whatToShow="TRADES",
        useRTH=False, formatDate=1, timeout=180)
    if not bars:
        return pd.DataFrame()
    d = ibi.util.df(bars).set_index("date")
    idx = pd.to_datetime(d.index)
    # ib_insync returns tz-aware US/Central for CME; anything naive is already UTC.
    idx = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    d.index = idx
    d.columns = [c.lower() for c in d.columns]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in d.columns]
    return d[keep].sort_index()


def repair(name: str, path: str, symbol: str, exchange: str, ib, apply: bool) -> bool:
    p = Path(path)
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)

    head = df[df.index <= SPLICE_UTC]
    tail = df[df.index > SPLICE_UTC]
    print(f"\n=== {name} ===")
    print(f"  history kept : {len(head):>9,} bars  through {head.index[-1]}")
    print(f"  tail dropped : {len(tail):>9,} bars  ({tail.index[0]} -> {tail.index[-1]})")
    if tail.empty:
        print("  nothing to repair")
        return True

    contract = _front_month(ib, symbol, exchange)
    start = head.index[-1]
    end = pd.Timestamp.utcnow().replace(tzinfo=None)
    # Weekly windows stepping forward, each overlapping the last so nothing falls
    # between them; duplicates are dropped after.
    marks = list(pd.date_range(start + pd.Timedelta(days=6), end + pd.Timedelta(days=7),
                               freq="7D"))
    print(f"  refetching   : {len(marks)} weekly windows from {contract.localSymbol}")

    got = []
    for i, mk in enumerate(marks):
        try:
            b = _fetch_window(ib, contract, min(mk, end))
            if not b.empty:
                got.append(b)
                print(f"    week to {min(mk, end).date()}: {len(b):>6,} bars")
            else:
                print(f"    week to {min(mk, end).date()}: empty")
        except Exception as exc:
            print(f"    week to {min(mk, end).date()}: FAILED {exc}")
        if i < len(marks) - 1:
            time.sleep(REQUEST_GAP_S)

    if not got:
        print("  no bars returned — ABORT, file untouched")
        return False

    new = pd.concat(got)
    new = new[~new.index.duplicated(keep="last")].sort_index()
    new = new[new.index > start]
    if new.empty:
        print("  refetch produced nothing past the history — ABORT")
        return False

    join_gap = abs(float(new["open"].iloc[0]) - float(head["close"].iloc[-1]))
    rel = join_gap / float(head["close"].iloc[-1])
    print(f"  refetched    : {len(new):>9,} bars  ({new.index[0]} -> {new.index[-1]})")
    print(f"  join gap     : {join_gap:,.2f} ({rel:.3%}) — no offset applied")
    if rel > JOIN_TOLERANCE:
        print(f"  join gap exceeds {JOIN_TOLERANCE:.0%} — ABORT, likely wrong contract")
        return False

    out = pd.concat([head, new]).sort_index()
    try:
        assert_utc_convention(out, name)
    except Exception as exc:
        print(f"  convention check FAILED: {exc}")
        return False
    print(f"  result       : {len(out):>9,} bars  (was {len(df):,})  convention OK")

    if not apply:
        print("  dry-run — not written")
        return True

    tmp = p.with_suffix(".repaired.parquet")
    out.to_parquet(tmp)
    shutil.move(str(tmp), str(p))
    print(f"  WRITTEN → {p}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=74)
    ap.add_argument("--only", default="", help="comma-separated instruments")
    a = ap.parse_args()
    only = {s.strip().upper() for s in a.only.split(",") if s.strip()}

    import ib_insync as ibi
    ib = ibi.IB()
    ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=30)
    ib.sleep(3)
    print(f"{'APPLY' if a.apply else 'DRY-RUN'} — splice boundary {SPLICE_UTC} UTC")

    ok = True
    try:
        for name, (path, sym, exch) in INSTRUMENTS.items():
            if only and name not in only:
                continue
            ok &= repair(name, path, sym, exch, ib, a.apply)
    finally:
        ib.disconnect()

    print("\n" + ("ALL OK" if ok else "SOME FAILED — see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
