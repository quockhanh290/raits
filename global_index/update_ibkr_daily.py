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

# Alignment check: how far the stored history may sit from a fresh IBKR fetch over
# the bars they share, before an append is refused.
#
# In normal operation this is not "small", it is exactly zero — the stored bars ARE
# the fetched bars from earlier runs, plus a constant offset that is applied to both
# sides of the comparison. Measured across all five instruments after the 2026-08-07
# correction: median 0.0000, IQR 0.0000 over ~13,600 shared bars each.
#
# So the threshold only has to sit above floating-point noise and below the smallest
# offset error worth stopping the day for. 0.5 point clears one tick on every
# instrument except NKD (5.0), and is 0.017% of price on the cheapest (M2K near
# 3,000). The error it was written for was +7.20 on M2K and +1065.00 on MNKD.
#
# A drift of exactly the stored offset means the parquet was rebuilt without
# updating the sidecar. A wide IQR alongside it means the two sources disagree bar
# by bar, which is a data problem rather than an offset one.
ALIGN_MAX_DRIFT: float = 0.5

# Below this many shared bars the median is not worth trusting, and the run says so
# rather than passing quietly. A "3 D" fetch against a daily append shares ~2,500.
ALIGN_MIN_OVERLAP: int = 500

# Re-anchoring on a roll: the conditions under which the new offset is applied
# instead of the day being refused.
#
# Stopping was the right call while a roll was inferred from the size of a price
# jump, and while the offset was measured from a single pair of bars. Neither is
# true now — qualifyContracts names the contract outright, and the shift is the
# median over thousands of shared bars. What actually makes this safe is the
# alignment check above: if a re-anchor is wrong, tomorrow's append refuses. A
# mistake lives one day rather than sitting in the file for months, which is what
# the 2026-08-05 offset step did.
#
# Every condition has to hold, or the day is refused exactly as before:
#   - the contract changed (certainty about the cause)
#   - enough shared bars for the median to mean anything
#   - the difference is a clean level shift, not noise
#   - its size is what carry between two expiries looks like
#
# Measured 2026-08-07: Sep/Dec spreads ran 0.74-1.01% of price across the basket.
# The band is set wider than that in both directions — the spread moves with rates,
# dividends and time to expiry, and a December roll is not an August one.
REANCHOR_MAX_IQR_FRAC: float = 0.20   # IQR as a fraction of |median|
REANCHOR_MIN_PCT: float = 0.20        # of price
REANCHOR_MAX_PCT: float = 2.00

# ── Instruments: (runner_name, ibkr_symbol, parquet_path) ────────────────────
# ══════════════════════════════════════════════════════════════════════════════
# Stage 5Q-5 — the boundary bar, and why it was frozen partial for ever (B-5R-F)
#
# The append keeps `new_bars[new_bars.index > last_existing]` — STRICTLY newer. So the bar the
# previous fetch stopped on is never re-fetched, never compared and never rewritten. If that
# fetch caught the minute while it was still open, the file keeps a snapshot of a partial
# minute permanently, and the dedupe below never sees a duplicate to prefer because the
# filter already removed it.
#
# Measured 2026-08-24: MNQ `2026-08-21 13:45 ET` holds `low = 29400.25` while twelve
# independent live fetches all report `29395.75`. The feed's low is LOWER, which is the only
# direction a partial bar's low can be wrong in — the minute had not finished falling.
#
# The replacement rule, and why it needs no threshold to tune
# ------------------------------------------------------------
# A partial bar can only be COMPLETED, never contradicted. Over the rest of its minute:
#
#     open    cannot change     — it is fixed by the first tick
#     low     can only fall     — more trades can only extend the range downward
#     high    can only rise
#     volume  can only grow
#     close   may move anywhere — it is simply the last tick so far
#
# So "is this a completion of the same bar, or a disagreement about which bar it is?" is
# decidable from the two rows alone, with no tolerance to pick. Anything that violates the
# monotonicity is REFUSED: two sources describing the same minute differently is a contract,
# clock or feed question, and this function has no business guessing which.
#
# The percentage bound on top is a second, cruder net for the case where every monotonic rule
# happens to hold but the bar is from a different instrument entirely.
# ══════════════════════════════════════════════════════════════════════════════

#: How far a completed bar may sit from its partial version, as a share of the stored close.
#: A net, not a threshold: a real completion of one minute moves a fraction of a percent, and a
#: wrong contract moves whole percents. Nothing legitimate sits near this line.
BOUNDARY_REPLACE_MAX_PCT = 0.5

BOUNDARY_COLS = ("open", "high", "low", "close", "volume")


def boundary_replacement(existing, fetched, *, last_existing):
    """`(row_or_None, reason)` — the completed version of the final stored bar, or why not.

    Pure: two frames in, one row out. No IO, no broker, no clock — so the rule can be
    exercised without a Gateway, which is the only way a rule that runs once a day at 13:45
    ever gets tested.

    `reason` is always a name, never None, so a run can say why it did nothing.
    """
    if last_existing not in fetched.index:
        return None, "not_offered: the fetch does not cover the final stored bar"
    old = existing.loc[last_existing]
    new = fetched.loc[last_existing]
    cols = [c for c in BOUNDARY_COLS if c in existing.columns and c in fetched.columns]
    if len(cols) < len(BOUNDARY_COLS):
        return None, f"schema: only {cols} are common to both halves"

    diffs = {c: (float(old[c]), float(new[c])) for c in cols
             if abs(float(old[c]) - float(new[c])) > 1e-6}
    if not diffs:
        return None, "identical: the stored bar already matches the feed"

    # A completion, or a disagreement? The monotonic rules decide it.
    if abs(float(new["open"]) - float(old["open"])) > 1e-6:
        return None, (f"open_changed: {float(old['open'])} -> {float(new['open'])}. The open "
                      f"is fixed by the first tick, so this is not the same bar")
    if float(new["low"]) > float(old["low"]) + 1e-6:
        return None, (f"low_rose: {float(old['low'])} -> {float(new['low'])}. A minute's low "
                      f"can only fall as it completes")
    if float(new["high"]) < float(old["high"]) - 1e-6:
        return None, (f"high_fell: {float(old['high'])} -> {float(new['high'])}. A minute's "
                      f"high can only rise as it completes")
    if float(new["volume"]) < float(old["volume"]) - 1e-6:
        return None, (f"volume_shrank: {float(old['volume'])} -> {float(new['volume'])}. A "
                      f"minute's volume can only grow")

    base = abs(float(old["close"])) or 1.0
    worst = max(abs(float(new[c]) - float(old[c])) for c in ("open", "high", "low", "close"))
    if 100.0 * worst / base > BOUNDARY_REPLACE_MAX_PCT:
        return None, (f"moved_too_far: {100.0 * worst / base:.3f}% > "
                      f"{BOUNDARY_REPLACE_MAX_PCT}% of {base:.4f}. A completion of one minute "
                      f"does not move this much; a different contract does")

    return fetched.loc[[last_existing]], f"completed: {sorted(diffs)}"


import datetime as _dt
import pathlib  # noqa: E402  (Stage 5Q-5 snapshot stamp)


#: One bar. A minute stamped T covers [T, T+1min), so it is finished only once T+BAR_SECONDS
#: has passed. Named rather than written as 60 in three places.
BAR_SECONDS = 60

TAIL_KEPT = "kept: final bar had closed before the fetch"
TAIL_NO_BARS = "nothing fetched"


def drop_open_final_bar(fetched, *, observed_utc) -> "tuple":
    """`(bars, dropped_timestamp_or_None, reason)` — never persist a minute still in progress.

    Stage 5R-0, closing B-5R-H. `--repair-boundary` (above) repairs the partial bar the
    PREVIOUS run left behind. It cannot help the one the CURRENT run is about to create: the
    fetch asks for "now", IBKR answers with the minute in progress, and the append stores that
    snapshot as if it were a finished bar. Measured 2026-08-24: one 13:45 pre-flight left
    partial bars in three of five instruments, and repairing them at 20:20 immediately left
    three more at 20:20 and 20:21. Repairing moves the defect; only refusing to store it
    removes it.

    The rule has no threshold to tune. A bar stamped T covers [T, T+1min), so it is complete
    exactly when the observation instant has reached T+1min. Nothing about prices is inspected
    — a partial bar is not detectably wrong from its own values, which is what let this survive
    every price check the route has.

    **`observed_utc` must be taken BEFORE the request goes out**, and that is not fussiness.
    The data snapshot IBKR answers with is at or after the moment we asked; taking the instant
    afterwards instead would let a bar that closed DURING the round trip look complete, and the
    row we hold for it would still be the partial one the snapshot contained. Using the earlier
    instant means every bar kept had already closed before we asked, so the value we have for
    it is final. The cost is at most one just-closed minute deferred to the next run, which
    appends it as an ordinary new bar.

    Only the FINAL bar is ever a candidate. An interior bar cannot be in progress, and a
    function that could drop one would be a filter rather than a tail guard.
    """
    if fetched is None or len(fetched) == 0:
        return fetched, None, TAIL_NO_BARS
    idx = pd.DatetimeIndex(fetched.index)
    obs = pd.Timestamp(observed_utc)
    if obs.tzinfo is not None:
        obs = obs.tz_convert("UTC").tz_localize(None)
    if idx.tz is not None:
        # The frame is on a zone; compare on the same one rather than stripping either side.
        obs = obs.tz_localize("UTC").tz_convert(idx.tz)
    last = idx[-1]
    if obs >= last + pd.Timedelta(seconds=BAR_SECONDS):
        return fetched, None, TAIL_KEPT
    return (fetched.iloc[:-1], last,
            f"dropped: {last} is still open at {obs} "
            f"(complete at {last + pd.Timedelta(seconds=BAR_SECONDS)})")


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


def history_ibkr_symbol(inst: str) -> str:
    """The IBKR symbol the STORED HISTORY for `inst` was fetched under.

    Stage 5Q-7. A live fetch that wants to be comparable with the parquet has to ask the
    broker for the same thing the parquet was built from, and this is the only function in
    the repo that knows what that is — because `_build_jobs` above is the code that fetched
    it. Anywhere else the answer would be a copy, and a copy is what the identity split
    keeps getting caught by.

    It is NOT `Contract.data_symbol`. That field is the file stem and the two disagree on
    four of five instruments:

        inst   data_symbol   fetched as   file
        MES    ES            MES          ES_continuous_1m_8y.parquet
        MNQ    NQ            MNQ          NQ_continuous_1m_8y.parquet
        MYM    YM            MYM          YM_continuous_1m_8y.parquet
        M2K    RTY           M2K          RTY_continuous_1m_8y.parquet
        MNKD   NKD           NKD          NKD_continuous_1m_8y.parquet

    Reaching for `data_symbol` would have sent the four basket instruments at the full-size
    E-mini contracts to fix the one that needed it.

    It is also NOT `Contract.ibkr` / `_RAITS_TO_IBKR`. That map answers a different question
    — what ticker goes on an ORDER — and for MNKD the two answers are deliberately different:
    orders go to the $0.50 micro MNK, bars come from the full-size NKD, because micro history
    starts in 2024 Q4 and the backtest runs from 2018. Measured 2026-08-24: fetching MNK and
    comparing it against this history disagreed on 1,155 of 1,186 shared minutes, median gap
    one tick, signed median zero — two order books on one index, not a clock error. Fetching
    NKD disagreed on 0 of 1,186.

    Unknown instruments answer with their own name, which is what every caller did before
    this function existed.
    """
    for job in _build_jobs(Path("."), Path(".")):
        if job["name"] == inst:
            return str(job["ibkr_symbol"])
    return inst


#: Where the splice sidecar lives. Named once: it was only a CLI default, so a reader
#: elsewhere had to retype the path and a retyped path is a path that drifts.
SPLICE_OFFSETS_PATH = "global_index/data/_ibkr_splice_offsets.json"


def stored_anchor(inst: str, path: "str | None" = None) -> "tuple[float, str]":
    """(offset, contract) the stored history for `inst` is anchored on. Raises if unreadable.

    Stage 5ZZZ-CC. The offset is "how much to ADD to a raw IBKR fetch to reach the stored
    frame" -- that is exactly how the appender applies it, `new_bars + stored_offset`, and any
    reader that gets the sign backwards puts a stop order a roll-spread from where it belongs.

    RAISES rather than returning zero when the file is missing, unparseable, or has no entry
    for `inst`. Zero is not a safe default here: it means "no conversion needed", which is
    indistinguishable from "the conversion could not be looked up" and would silently restore
    today's behaviour on the one day the conversion starts to matter. A measuring function has
    three answers -- a value, a known zero, and "could not tell" -- and folding the third into
    the second is how a guard fails open.
    """
    p = Path(path or SPLICE_OFFSETS_PATH)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpliceAnchorUnavailable(
            f"splice offsets not found at {p}; the stored frame for {inst!r} cannot be "
            f"converted and a fetch must not be compared against it") from exc
    except (ValueError, OSError) as exc:
        raise SpliceAnchorUnavailable(f"splice offsets at {p} are unreadable: {exc}") from exc
    if inst not in raw:
        raise SpliceAnchorUnavailable(
            f"no splice anchor recorded for {inst!r} in {p}; the appender writes one on its "
            f"first run for an instrument, and until it has there is nothing to convert with")
    return _split_entry(raw[inst])


class SpliceAnchorUnavailable(RuntimeError):
    """The stored frame's anchor could not be read. Never downgraded to a zero offset."""


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
                      duration: str = "3 D") -> "tuple[pd.DataFrame, str, object]":
    """`(bars, contract, requested_at)` — 1m bars from IBKR ContFuture, UTC-naive.

    `requested_at` is the UTC-naive instant the request went out, and it travels with the
    bars because only the caller can decide what to do with a still-open final minute — but
    only this function knows when the data was asked for. See `drop_open_final_bar`.

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
    # Stage 5R-0. Stamped BEFORE the request, not after. The snapshot IBKR answers with is at
    # or after this instant, so a bar that had already closed by now is one whose values are
    # final. Stamping afterwards would let a minute that closed during the round trip look
    # complete while the row we hold for it is still the partial one. See drop_open_final_bar.
    requested_at = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
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
        return pd.DataFrame(), resolved, requested_at
    df = ibi.util.df(bars)
    if df is None or df.empty:
        return pd.DataFrame(), resolved, requested_at
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
    return df[keep].sort_index(), resolved, requested_at


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
    ap.add_argument("--repair-boundary", action="store_true",
                    help="re-fetch and REPLACE the final stored bar when the feed shows it "
                         "was captured mid-minute. OFF by default: it is the only path here "
                         "that rewrites a bar the file already has, and the 13:45 job runs "
                         "unattended. See boundary_replacement() for the rule.")
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
    #: Stage 5R-0. Final minutes deliberately NOT stored because they were still open when the
    #: fetch went out. Reported at the end so an operator sees the skip was a decision rather
    #: than a gap — a silently shorter file is exactly how a missing bar becomes a mystery.
    dropped_tails: dict = {}

    try:
        for j in jobs:
            name = j["name"]
            parquet_path = j["parquet"]
            log.info("\n%s", "─" * 72)
            log.info("[%s] Fetching ContFuture bars (duration=%s) ...", name, a.duration)

            try:
                new_bars, fetched_contract, requested_at = _fetch_contfuture(
                    ib, j["ibkr_symbol"], j["exchange"], duration=a.duration)
                ib.sleep(0.5)  # pacing: IBKR allows ~50 requests/10min

                # Stage 5R-0 — B-5R-H. Before anything else looks at these bars: the last one
                # may be the minute still in progress, and storing it is what has been
                # freezing a partial bar into history on every intraday run.
                new_bars, dropped_tail, tail_why = drop_open_final_bar(
                    new_bars, observed_utc=requested_at)
                log.info("  %s: final-bar check — %s", name, tail_why)
                if dropped_tail is not None:
                    dropped_tails[name] = str(dropped_tail)

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

                # Does the offset we are about to apply still align this file with
                # IBKR? The fetch covers more days than the parquet is missing, so a
                # couple of thousand bars have a counterpart on both sides. Comparing
                # the ADJUSTED fetch against what is already stored asks the only
                # question that matters — not "are the new bars right", which is
                # circular since they came from this same fetch, but "is the offset
                # still the right one to write them with".
                #
                # This is the check that was missing on 2026-08-05. repair_parquet_utc
                # had rebuilt the tails at IBKR's own level the day before while the
                # sidecar kept its pre-repair values, so the stored history aligned at
                # 0 while the offset said +11.50 (MES) through +1065.00 (MNKD). Every
                # append after that wrote the difference into the series, and it went
                # three days unnoticed: assert_utc_convention checks timestamps, the
                # history invariant checks that old bars are untouched, and the join
                # check compares two bars that are both on the new level. None of them
                # look at whether the file still agrees with the source.
                #
                # The median is over thousands of bars, so one bad print cannot move
                # it, and the IQR says whether it is a clean level difference or noise.
                _ov = existing.index.intersection(new_bars_adj.index)
                if len(_ov) >= ALIGN_MIN_OVERLAP:
                    _d = existing.loc[_ov, "close"] - new_bars_adj.loc[_ov, "close"]
                    _med = float(_d.median())
                    _iqr = float(_d.quantile(0.75) - _d.quantile(0.25))
                    log.info("  %s: alignment over %d shared bars — median %+.4f, "
                             "IQR %.4f", name, len(_ov), _med, _iqr)
                    _rolled = bool(stored_contract and fetched_contract
                                   and stored_contract != fetched_contract)
                    if abs(_med) > ALIGN_MAX_DRIFT or _rolled:
                        # A roll makes both of these fire, so it has to be named
                        # first: the alignment message would otherwise blame a
                        # rebuild, which is the wrong diagnosis at exactly the moment
                        # the right one matters. The suggested offset is the same
                        # either way — the median over thousands of shared bars.
                        # A roll is the one cause we can be certain of, so it is the
                        # one case worth continuing through — but only when the
                        # measurement corroborates it. Anything short of that falls
                        # back to refusing, which is what every other path does.
                        _px = float(existing["close"].iloc[-1]) or 1.0
                        _shift_pct = abs(_med) / abs(_px) * 100
                        _iqr_frac = (_iqr / abs(_med)) if _med else float("inf")
                        _why = []
                        if len(_ov) < ALIGN_MIN_OVERLAP:
                            _why.append(f"only {len(_ov)} shared bars")
                        if _iqr_frac > REANCHOR_MAX_IQR_FRAC:
                            _why.append(f"IQR is {_iqr_frac:.0%} of the shift — not a "
                                        f"clean level difference")
                        if not (REANCHOR_MIN_PCT <= _shift_pct <= REANCHOR_MAX_PCT):
                            _why.append(f"shift is {_shift_pct:.3f}% of price, outside "
                                        f"{REANCHOR_MIN_PCT}-{REANCHOR_MAX_PCT}%")

                        if _rolled and not _why:
                            _new_off = stored_offset + _med
                            for _c in ("open", "high", "low", "close"):
                                if _c in new_bars_adj.columns:
                                    new_bars_adj[_c] = new_bars_adj[_c] + _med
                            splice_offsets[name] = {"offset": _new_off,
                                                    "contract": fetched_contract}
                            offsets_dirty = True
                            log.warning(
                                "  %s: CONTRACT ROLLED %s -> %s — re-anchored and "
                                "continuing.", name, stored_contract, fetched_contract)
                            log.warning(
                                "       Shift %+.4f (%.3f%% of price) measured over %d "
                                "shared bars, IQR %.4f (%.0f%% of the shift). Offset "
                                "%+.4f -> %+.4f.",
                                _med, _shift_pct, len(_ov), _iqr, _iqr_frac * 100,
                                stored_offset, _new_off)
                            log.warning(
                                "       Tomorrow's alignment check verifies this. If the "
                                "anchor was wrong it will refuse then — do not ignore an "
                                "ALIGNMENT DRIFT the day after a roll.")
                            # Fall through and append with the new offset applied.
                        elif _rolled:
                            log.error(
                                "  %s: CONTRACT ROLLED %s -> %s — refusing to append "
                                "(%s).", name, stored_contract, fetched_contract,
                                "; ".join(_why))
                            log.error(
                                "       Bars from %s sit on a different price level than "
                                "the history, which was built against %s. Measured over "
                                "%d shared bars: %+.4f (IQR %.4f).",
                                fetched_contract, stored_contract, len(_ov), _med, _iqr)
                            log.error(
                                "       Appending would put that step into the series: "
                                "the day's true range absorbs it and daily ATR is a "
                                "14-period mean, so the chandelier band stays wrong for "
                                "14 sessions, and an open position's extreme ratchets "
                                "its stop to a level that never traded.")
                            log.error(
                                "       OPERATOR: in %s set %s offset %+.4f -> %+.4f and "
                                "contract -> %s, then re-run. Confirm first that every "
                                "instrument moved the same way — correlated index "
                                "futures roll together.",
                                a.splice_offsets, name, stored_offset,
                                stored_offset + _med, fetched_contract)
                        else:
                            log.error(
                                "  %s: ALIGNMENT DRIFT %+.4f — refusing to append.",
                                name, _med)
                            log.error(
                                "       %d shared bars, IQR %.4f, contract unchanged "
                                "(%s). Stored offset %+.4f is no longer the one that "
                                "lines this file up with IBKR; writing new bars with it "
                                "would put a step of %+.4f into the series.",
                                len(_ov), _iqr, fetched_contract or "unknown",
                                stored_offset, -_med)
                            log.error(
                                "       A tight IQR means a clean level difference — "
                                "usually the parquet was rebuilt without updating %s. "
                                "The offset that would align it is %+.4f. A wide IQR "
                                "means the two sources disagree bar by bar, which is a "
                                "data problem, not an offset.",
                                a.splice_offsets, stored_offset + _med)

                        # Re-anchored runs carry on with the corrected offset; every
                        # other path here has already said why it is stopping.
                        if not (_rolled and not _why):
                            failed.append(name)
                            continue
                else:
                    log.warning("  %s: only %d shared bars — alignment unchecked",
                                name, len(_ov))

                # Keep only NEW bars (after existing last bar)
                new_only = new_bars_adj[new_bars_adj.index > last_existing]

                # Stage 5Q-5. The one bar the filter above always drops: the minute the LAST
                # fetch stopped on. Off unless --repair-boundary, because it is the only path
                # in this file that rewrites a bar the parquet already has, and this job runs
                # unattended at 13:45.
                boundary, boundary_why = (None, "off: --repair-boundary not given")
                if a.repair_boundary:
                    boundary, boundary_why = boundary_replacement(
                        existing, new_bars_adj, last_existing=last_existing)
                log.info("  %s: boundary bar %s — %s", name, last_existing, boundary_why)

                if new_only.empty and boundary is None:
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

                # The contract check above already ruled out a roll, so a jump this
                # size is bad
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
                #
                # Reads the entry back rather than reusing stored_offset, which was
                # captured before the roll branch ran. Writing the stale value here
                # silently undid a re-anchor: the bars went in shifted, the sidecar
                # kept the old offset, and the next append would have rebuilt the step
                # the re-anchor had just removed — the same shape as the 2026-08-05
                # incident. The run reported success either way; only the state file
                # showed it.
                _cur_off, _cur_con = _split_entry(splice_offsets.get(name))
                if fetched_contract and fetched_contract != _cur_con:
                    splice_offsets[name] = {"offset": _cur_off,
                                            "contract": fetched_contract}
                    offsets_dirty = True

                # Concat + sort + dedup
                keep_cols = [c for c in ["open", "high", "low", "close", "volume"]
                             if c in existing.columns]
                # The replacement sits BETWEEN history and the new bars, so `keep="last"`
                # prefers it over the stored copy of the same timestamp — which is exactly the
                # mechanism the strictly-newer filter had been preventing from ever engaging.
                _parts = [existing[keep_cols]]
                if boundary is not None:
                    _parts.append(boundary[keep_cols])
                _parts.append(new_only[keep_cols])
                updated = pd.concat(_parts)
                updated = updated[~updated.index.duplicated(keep="last")].sort_index()

                # History invariant: existing bars must be UNCHANGED after append.
                # new_only contains only bars AFTER last_existing → no overlap.
                # This guard catches any future logic bug that modifies history.
                # Use float64 cast before equals(): parquet may store volume as int64
                # while IBKR returns float64; concat upcast causes dtype-only false positive
                # (equals() is dtype-strict; values are identical when Rows with diff=[]).
                check_n   = min(200, len(existing))
                old_tail  = existing[keep_cols].tail(check_n)
                # Stage 5Q-5: the boundary bar is the ONE timestamp allowed to change, and it
                # is excluded here by name rather than by widening the comparison. Every other
                # bar in the tail is still required to come out untouched, and a replacement
                # that moved anything else is caught below.
                if boundary is not None:
                    old_tail = old_tail.drop(index=[last_existing], errors="ignore")
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

                # A replacement rewrites a bar the file already had, so it gets the two
                # things an append does not need: a snapshot to go back to, and a re-read to
                # prove the write landed. The repo has already lost a baseline to an in-place
                # parquet write with neither.
                _backup = None
                if boundary is not None:
                    _stamp = _dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                    _backup = parquet_path.with_suffix(
                        parquet_path.suffix + f".pre5q5-{_stamp}.bak")
                    if _backup.exists():
                        log.error("  %s: snapshot %s already exists — NOT writing.",
                                  name, _backup)
                        failed.append(name)
                        continue
                    _backup.write_bytes(parquet_path.read_bytes())
                    log.info("  %s: snapshot -> %s", name, _backup.name)

                parquet_path.parent.mkdir(parents=True, exist_ok=True)
                updated.to_parquet(parquet_path)

                if boundary is not None:
                    _after = pd.read_parquet(parquet_path)
                    _want = boundary[keep_cols].iloc[0].astype("float64")
                    _got = _after.loc[last_existing, keep_cols].astype("float64")
                    if not _got.equals(_want) or len(_after) != len(updated):
                        log.error("  %s: BOUNDARY REPAIR DID NOT LAND — restore %s",
                                  name, _backup)
                        failed.append(name)
                        continue
                    log.info("  %s: boundary bar %s replaced and verified by re-read",
                             name, last_existing)

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
    # Stage 5R-0. The per-instrument log line already names each skip; this repeats them
    # together on stdout, where the pre-flight captures them, so an operator reading only the
    # summary still sees that a shorter file was a decision rather than a gap.
    if dropped_tails:
        print("IN-PROGRESS FINAL MINUTES NOT STORED (Stage 5R-0, intentional):")
        for _n, _ts in sorted(dropped_tails.items()):
            print(f"  {_n:<5} {_ts}  — still open at fetch; it arrives on the next run")
        print("-" * 72)
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
