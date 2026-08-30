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
from dataclasses import dataclass
from typing import Any
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
                         check_end: str = "2024-12-31"):
    """Compare HMM regime labels between snapshot and updated CSV. Returns a `VerifyResult`.

    Stage 5ZL. This used to return a COUNT, and returned 0 from four places that had verified
    nothing — no engine, unreadable inputs, a raising labeller, and no overlapping dates. Zero
    is also what a clean run returns, so "I could not check" and "I checked and it was fine"
    were the same number. The logic now lives in `regime_verify`, which answers PASS, DRIFT or
    UNKNOWN and carries a code saying which of the seven conditions it met.

    The return type changed deliberately rather than by adding a second function. A caller
    that keeps treating the answer as a count now fails loudly instead of silently reading
    `UNKNOWN` as zero drift, which is the exact mistake this stage exists to remove.
    """
    from global_index import regime_verify as rv

    result = rv.verify_labels(snap_path, new_csv, check_end=check_end)
    if result.status == rv.PASS:
        log.info("Regime labels verified: %s", result.detail)
    elif result.status == rv.DRIFT:
        log.error("LABEL DRIFT: %s", result.detail)
        log.error("  The engine's view of history moved. Compare the snapshot against the "
                  "updated CSV and check the HMM fit end before anything trades on it.")
    else:
        # ERROR, not WARNING. The scheduler keeps only CRITICAL and ERROR from a child that
        # exited 0, so a WARNING here never reaches the job journal — which is how a
        # verification that could not run stayed invisible for as long as it did.
        log.error("REGIME VERIFICATION UNKNOWN (%s): %s", result.code, result.detail)
        log.error("  This is NOT 'no drift'. Nothing was proved about the labels.")
    return result


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
    Về IBKR làm nguồn thay thế — chính xác hơn bản trước của chú thích này:
    IBKR KHÔNG chỉ điều chỉnh chia tách. `whatToShow="TRADES"` thì đúng là chỉ điều chỉnh
    chia tách, và đó là giá trị `ibkr_broker.fetch_bars` đang cố định — nhưng `whatToShow=
    "ADJUSTED_LAST"` trả dữ liệu điều chỉnh cả cổ tức. Nên đây là lựa chọn tham số, không
    phải giới hạn năng lực; bản cũ viết "split-adjusted only — DO NOT use" dễ khiến người
    đọc kết luận nhầm là không làm được.

    Điều KHÔNG đổi: không được nối nguồn mới vào giữa chuỗi này. File là một chuỗi liên tục
    từ 2017 và nó quyết định nhãn chế độ, tức quyết định sleeve nào được vào lệnh. Cổng phải
    qua trước khi đổi nguồn không phải "so giá" mà là: gán lại nhãn chế độ trên cả hai chuỗi
    ở cửa sổ chồng lấn và đếm số ngày BỊ LẬT NHÃN. Lệch 0,3-0,4% sát ranh giới là đủ lật một
    nhãn — cùng lý do `adjusted=True` là bắt buộc. Lật ngày nào thì đổi nguồn = đổi luật vào
    lệnh mà không ai khai.

    Dùng IBKR làm ĐỐI CHỨNG song song thì có giá trị ngay và không có rủi ro đó: kêu khi hai
    nguồn lệch quá ngưỡng. Cách đó sẽ bắt được lỗi 16% nói trên ngay ngày đầu thay vì sau 8
    năm. `fetch_bars` hiện dựng hợp đồng tương lai, nên vẫn cần thêm nhánh Stock trước.
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


@dataclass(frozen=True)
class UpdateOutcome:
    """What one update did, and what it could say about the labels afterwards.

    Stage 5ZL. This used to be a bare row count, so the verification result had nowhere to go
    and was dropped on the floor at the call site. `rows_added` keeps the old meaning; callers
    that only want the count read that field.
    """
    rows_added: int
    verify: Any = None

    def __int__(self) -> int:
        return int(self.rows_added)

    def __eq__(self, other) -> bool:
        # So `outcome == 0` still reads the way every existing caller and test expects.
        if isinstance(other, int):
            return self.rows_added == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.rows_added, id(self.verify)))


def update_spy_csv(csv_path: Path, api_key: str,
                   snapshot_dir: Path = SNAPSHOT_DIR,
                   verify_root: str | None = None) -> "UpdateOutcome":
    """
    Extend spy_daily.csv with new rows.  Returns an `UpdateOutcome`.
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
        # Stage 5ZL: no fetch, no snapshot, no comparison. Returning a bare 0 here used to be
        # indistinguishable from a run that verified cleanly.
        from global_index import regime_verify as _rv
        return UpdateOutcome(rows_added=0, verify=_rv.VerifyResult(
            status=_rv.UNKNOWN, code=_rv.NO_SNAPSHOT,
            detail=f"the series already ends at {last_date}, so nothing was fetched and no "
                   f"snapshot comparison was made",
            checked_at=_rv._now(), inputs={"updated": str(csv_path)}))

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
        from global_index import regime_verify as _rv
        return UpdateOutcome(rows_added=0, verify=_rv.VerifyResult(
            status=_rv.UNKNOWN, code=_rv.UNREADABLE,
            detail="the fetch returned no rows, so the updated series was never written and "
                   "no comparison was made",
            checked_at=_rv._now(), inputs={"updated": str(csv_path)}))

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

    # Stage 5ZL. The result is KEPT, recorded and returned. It used to be discarded on this
    # very line, so a drift logged a warning nobody reads and the process exited 0.
    from global_index import regime_verify as _rv
    if snap_path:
        verify_historical_prices(snap_path, csv_path, fetch_from)
        verify_result = verify_regime_labels(snap_path, csv_path)
    else:
        verify_result = _rv.VerifyResult(
            status=_rv.UNKNOWN, code=_rv.NO_SNAPSHOT,
            detail="snapshots are disabled for this run, so no comparison was possible",
            checked_at=_rv._now(), inputs={"updated": str(csv_path)})
    try:
        _rv.record(verify_result, root=verify_root or ".", source="update_spy_csv")
    except OSError as _exc:
        # Recording is evidence, not control flow: a series that was fetched correctly must
        # not be thrown away because a status file could not be written. But say so loudly —
        # an unrecorded verification reads as no verification to everything downstream.
        log.error("could not record the regime verification (%s) — readiness will read this "
                  "as UNKNOWN, which is the safe direction but not the true one", _exc)

    n_after = len(combined)
    n_new = max(0, n_after - n_before)
    log.info(
        "Updated %s: %d new row(s), %d total (last=%s)",
        csv_path, n_new, n_after, combined["date"].iloc[-1],
    )
    return UpdateOutcome(rows_added=n_new, verify=verify_result)


# ── CLI ───────────────────────────────────────────────────────────────────────


#: What the daily series can say about a day somebody needs. Stage 5ZZB.
#:
#: Four states, because the caller has to tell them apart and three of them used to look the
#: same from outside. `--verify-strict` checks the regime LABELS and reports, in its own words,
#: "1761 label(s) compared through 2024-12-31" — it is a drift check over settled history and
#: says nothing whatever about whether last night's close arrived. So a run could append zero
#: rows, verify perfectly, exit 0, and leave the series a day short of what the next morning
#: asks for. That is precisely what happened on 2026-08-26.
COVERAGE_OK = "covers_required_day"
COVERAGE_SHORT = "provider_did_not_return_required_day"
COVERAGE_UNREADABLE = "coverage_unknown"
COVERAGE_NOT_ASKED = "coverage_not_requested"

#: Exit code for "the run was clean and the series is still short". Deliberately NOT 1: 1 means
#: the labels moved or could not be verified, which is a different problem with a different
#: owner, and collapsing them would leave an operator unable to tell a data-supply gap from a
#: history that changed under them.
EXIT_COVERAGE_SHORT = 2


def coverage_status(csv_path, required_through) -> dict:
    """Does the series reach `required_through`? Read-only, and never guesses.

    An unreadable file is its own answer. "I could not tell" and "it is short" lead to
    different actions — one is a retry, the other is a question for whoever owns the feed —
    and a check that returns the same thing for both is how a gap gets retried forever.
    """
    import datetime as _dt

    want = (required_through if isinstance(required_through, _dt.date)
            else _dt.date.fromisoformat(str(required_through)[:10]))
    try:
        df = pd.read_csv(csv_path)
        last = pd.to_datetime(df["date"]).max().date()
    except Exception as exc:                                          # noqa: BLE001
        return {"state": COVERAGE_UNREADABLE, "last": None, "required": want.isoformat(),
                "detail": f"the series could not be read ({type(exc).__name__}: {exc})"}
    if last >= want:
        return {"state": COVERAGE_OK, "last": last.isoformat(), "required": want.isoformat(),
                "detail": f"the series covers {want}"}
    return {"state": COVERAGE_SHORT, "last": last.isoformat(), "required": want.isoformat(),
            "detail": (f"the series ends on {last} and {want} was asked for. The run itself "
                       f"was clean; the provider did not have that day when it was asked")}


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
    # Stage 5ZL. Off by default, and the default is the DOCUMENTED reason rather than an
    # oversight: the 13:45 pre-flight gates the whole trading day, and making a verification
    # result skip every slot is a far larger decision than this stage is allowed to take —
    # the brief is explicit that UNKNOWN must not block shadow execution. The 16:20 post-close
    # refresh gates nothing, so it runs strict and its failure is visible on its own.
    parser.add_argument(
        "--verify-strict", action="store_true",
        help="exit non-zero when the regime verification is DRIFT or UNKNOWN. Off by "
             "default: the pre-flight caller must not skip a trading day over it.",
    )
    parser.add_argument(
        "--verify-root", default=None,
        help="where to record the verification status (default: the working directory)",
    )
    # Stage 5ZZB. Coverage is a SEPARATE question from drift and now has its own answer and
    # its own exit code. The caller says which day it needs; this says whether it is there.
    # Stage 5ZZC. What makes a RETRY possible at all.
    #
    # Measured before building the ladder: a retry that finds nothing to do — the SUCCESSFUL
    # case, the one that happens on every good day — exits 1. The series already ends at
    # today, so the update returns early with `UNKNOWN (no_snapshot)`: nothing was fetched, so
    # nothing could be compared, which is an honest verification result and not a PASS. Strict
    # mode then fails on it.
    #
    # Two retries a day, each reporting FAILED on every day that went well, is an alarm that
    # fires when nothing is wrong — and this project's own record says what happens to those:
    # people learn to ignore them, and then the one real firing goes unread too.
    #
    # So a retry asks first and works second. If the day it was sent for is already there, it
    # says so and stops: no fetch, no API call, no verification, exit 0. There is nothing to
    # verify about a file nobody is going to touch.
    parser.add_argument(
        "--skip-if-covered", action="store_true",
        help="exit 0 immediately when --require-through is already satisfied, before any "
             "fetch. For retries: a retry with nothing to do is a success, not a failure.",
    )
    parser.add_argument(
        "--require-through", default=None, metavar="YYYY-MM-DD",
        help="the last daily close the caller needs. When the series is still short of it "
             f"after the update, exit {EXIT_COVERAGE_SHORT} — distinct from the drift "
             "failure, because a data-supply gap and a moved history are different problems.",
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

    # Before anything else, and before the API key is used. A retry that is not needed must
    # cost nothing and must not be able to fail.
    if args.skip_if_covered and args.require_through:
        pre = coverage_status(Path(args.csv), args.require_through)
        if pre["state"] == COVERAGE_OK:
            print(f"coverage: {pre['state']} — {pre['detail']}")
            print("nothing to do: the day this run was sent for is already in the series.")
            return 0

    try:
        outcome = update_spy_csv(Path(args.csv), api_key,
                                 snapshot_dir=Path(args.snapshot_dir),
                                 verify_root=args.verify_root)
    except NotImplementedError as exc:
        sys.exit(f"fetch_spy_close not yet wired: {exc}")

    n = int(outcome)
    if n == 0:
        print("spy_daily.csv: already up-to-date")
    else:
        print(f"spy_daily.csv: appended {n} new row(s)")

    from global_index import regime_verify as rv
    v = getattr(outcome, "verify", None)
    if v is not None:
        print(f"regime verification: {v.one_line()}")
        if args.verify_strict and v.status != rv.PASS:
            # The two are separated on purpose. A drift is a finding about the data; an unknown
            # is the absence of a finding. Collapsing them into one exit code would be the same
            # mistake this stage removed from the return value.
            if v.status == rv.DRIFT:
                print("FAILING: the regime labels moved. Nothing should trade on them until "
                      "the cause is separated from the other two.")
            else:
                print("FAILING: the regime labels could not be verified. This is not "
                      "'no drift' — nothing was proved.")
            return 1

    # Coverage last, and separately. It is reported on EVERY run, asked for or not, so a reader
    # of the output never has to work out from the row count whether the day they need arrived.
    cov = (coverage_status(Path(args.csv), args.require_through)
           if args.require_through else
           {"state": COVERAGE_NOT_ASKED, "last": None, "required": None,
            "detail": "no --require-through was given, so no day was checked for"})
    print(f"coverage: {cov['state']} — {cov['detail']}")
    if cov["state"] == COVERAGE_SHORT:
        print("FAILING: the run was clean and the series is still short. This is not a retry "
              "for the same minute — the day being asked for did not exist when it was asked "
              "for, and it may exist later.")
        return EXIT_COVERAGE_SHORT
    if cov["state"] == COVERAGE_UNREADABLE:
        print("FAILING: the series could not be read, so coverage is unknown. Unknown is not "
              "covered.")
        return EXIT_COVERAGE_SHORT
    return 0


if __name__ == "__main__":
    # sys.exit(main()), not a bare main(): a bare call throws the return value away and the
    # process exits 0, which is precisely how a failed verification used to read as success.
    sys.exit(main() or 0)
