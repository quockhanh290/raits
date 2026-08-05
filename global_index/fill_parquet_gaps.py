"""
global_index/fill_parquet_gaps.py — refetch sessions the weekly windows missed

repair_parquet_utc.py pulls the post-splice tail in 1-week windows. IBKR returns
5,639 bars for a "1 W" request where a full week holds 6,899, and the shortfall is
always the same shape: Tue-Fri arrive complete, the Monday day-session does not.
Each repaired instrument came out missing three Mondays, holding only their 120-bar
evening portion.

The endDateTime is what decides this. A "1 D" request ending at 21:00 UTC — the
17:00 ET CME close — returns the whole 1,380-bar session. Ending at midnight returns
120 bars, because by then the session has closed and only the evening reopen falls
inside the window. Aligning to the session boundary rather than the calendar day is
the whole trick.

Finds short sessions and refetches them individually, so it is also the general
repair for any future hole. Dry-run unless --apply.

    python -m global_index.fill_parquet_gaps                  # report
    python -m global_index.fill_parquet_gaps --apply
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
from global_index.repair_parquet_utc import INSTRUMENTS, SPLICE_UTC, _front_month

FULL_SESSION = 1380       # minutes in a 23-hour CME session
SHORT_IF_UNDER = 1000     # below this a weekday session is incomplete
SESSION_CLOSE_UTC = 21    # 17:00 ET
REQUEST_GAP_S = 11.0


def short_sessions(df: pd.DataFrame, skip_last_day: bool = True) -> list:
    """Weekday sessions after the splice holding far fewer bars than a full one.

    The final day is skipped by default — it is still being traded, so being short
    is expected rather than a hole.
    """
    r = df[df.index > SPLICE_UTC]
    if r.empty:
        return []
    last_day = r.index[-1].date()
    out = []
    for day, g in r.groupby(r.index.date):
        if pd.Timestamp(day).dayofweek >= 5:      # Sat/Sun: evening reopen only
            continue
        if skip_last_day and day == last_day:
            continue
        if len(g) < SHORT_IF_UNDER:
            out.append((day, len(g)))
    return out


def fetch_session(ib, contract, day) -> pd.DataFrame:
    """One full session, anchored on the 21:00 UTC close rather than midnight."""
    import ib_insync as ibi
    end = pd.Timestamp(day) + pd.Timedelta(hours=SESSION_CLOSE_UTC)
    bars = ib.reqHistoricalData(
        contract, endDateTime=end.strftime("%Y%m%d-%H:%M:%S"), durationStr="1 D",
        barSizeSetting="1 min", whatToShow="TRADES", useRTH=False,
        formatDate=1, timeout=120)
    if not bars:
        return pd.DataFrame()
    d = ibi.util.df(bars).set_index("date")
    idx = pd.to_datetime(d.index)
    d.index = idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx
    d.columns = [c.lower() for c in d.columns]
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in d.columns]
    return d[keep].sort_index()


def fill(name, path, symbol, exchange, ib, apply) -> bool:
    p = Path(path)
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)

    gaps = short_sessions(df)
    print(f"\n=== {name} ===")
    if not gaps:
        print("  no short sessions")
        return True
    for day, n in gaps:
        print(f"  short: {day} ({pd.Timestamp(day).day_name()[:3]})  {n} bars")

    contract = _front_month(ib, symbol, exchange)
    got = []
    for i, (day, _) in enumerate(gaps):
        try:
            b = fetch_session(ib, contract, day)
            same = int((b.index.date == day).sum()) if not b.empty else 0
            print(f"  fetched {day}: {len(b):>5} bars ({same} on the day)")
            if not b.empty:
                got.append(b)
        except Exception as exc:
            print(f"  fetched {day}: FAILED {exc}")
        if i < len(gaps) - 1:
            time.sleep(REQUEST_GAP_S)

    if not got:
        print("  nothing fetched — file untouched")
        return False

    add = pd.concat(got)
    add = add[~add.index.duplicated(keep="last")].sort_index()
    # Existing bars win: only genuinely absent minutes are added, so a refetch can
    # never silently rewrite data that is already there.
    merged = pd.concat([df, add[~add.index.isin(df.index)]]).sort_index()
    print(f"  added {len(merged) - len(df):,} bars  ({len(df):,} -> {len(merged):,})")

    still = short_sessions(merged)
    if still:
        print(f"  STILL SHORT: {[str(d) for d, _ in still]}")
    try:
        assert_utc_convention(merged, name)
    except Exception as exc:
        print(f"  convention check FAILED: {exc}")
        return False

    if not apply:
        print("  dry-run — not written")
        return True
    tmp = p.with_suffix(".filled.parquet")
    merged.to_parquet(tmp)
    shutil.move(str(tmp), str(p))
    print(f"  WRITTEN → {p}")
    return not still


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=66)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = {s.strip().upper() for s in a.only.split(",") if s.strip()}

    import ib_insync as ibi
    ib = ibi.IB(); ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=30)
    ib.sleep(3)
    print(f"{'APPLY' if a.apply else 'DRY-RUN'} — filling short sessions")
    ok = True
    try:
        for name, (path, sym, exch) in INSTRUMENTS.items():
            if only and name not in only:
                continue
            ok &= fill(name, path, sym, exch, ib, a.apply)
    finally:
        ib.disconnect()
    print("\n" + ("ALL OK" if ok else "SOME INCOMPLETE — see above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
