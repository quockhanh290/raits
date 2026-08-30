"""global_index/track1_freshness.py — the Track 1 data-freshness gate. NEW FILE.

Stage 3. Pure: reads file metadata and a CSV's last date, nothing else. No IBKR call, no
network, no clock beyond the one the caller passes in.

The problem this exists for
---------------------------
The 13:45 ET pre-flight — `update_ibkr_daily` then `update_spy_csv` — is the system's one data
refresh, and its record is the system's one piece of evidence that the refresh happened. It is
SHARED infrastructure (Stage 5L), not a legacy strategy job, even though legacy was the first
route to depend on it: if either step fails, every legacy 14:05-15:55 slot is skipped that day.
That arrangement works for legacy because every legacy entry window opens AFTER 13:45.

Two of Track 1's windows do not. Calm A fires at 10:00 ET and Stress runs 10:35-12:30 ET,
both BEFORE the day's own pre-flight. The night NKD slots already live with this and solve it
by reading the PREVIOUS business day's flag, which is honest but leaves the freshness
contract unstated: what those slots actually trade on is a parquet last appended at 13:45 ET
the previous business day.

For Track 1 that has to be written down rather than inherited, because the Calm A entry is
one-shot and the Stress entry is a break of a level computed from this morning's bars.

The choice made, and what it costs
----------------------------------
Option 2 of the two Stage 2D offered: **encode the D-1 13:45 contract explicitly.** No
pre-10:00 update job is added — that would be a new IBKR-touching job, and this build does
not touch IBKR.

The contract, stated so it can be tested:

    Every historical input a Track 1 sleeve reads must be no older than the most recent
    completed 13:45 ET pre-flight, which on any instant before 13:45 ET is the PREVIOUS
    business day's. Anything older, missing, or unreadable is a REFUSAL.

What this does NOT claim
------------------------
It does not claim the intraday bars a live Calm A or Stress decision needs are covered. They
are not: those come from the broker at decision time and this gate cannot see them. So the
gate reports `intraday_source` as UNVERIFIED rather than PASS, and the route stays
shadow-only while that is true. Reporting it as a pass would be the "silent pass conflates
unverified with verified OK" failure the frozen-manifest check already guards against.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

OK = "ok"
STALE = "stale"
MISSING = "missing"
UNREADABLE = "unreadable"
UNVERIFIED = "unverified"

#: A refusal verdict. `UNVERIFIED` is deliberately not one: it is a statement that a check
#: did not run, and the route reports it without letting it masquerade as either outcome.
REFUSING = frozenset({STALE, MISSING, UNREADABLE})


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str = ""
    observed: Any = None
    required: Any = None

    @property
    def refuses(self) -> bool:
        return self.status in REFUSING


@dataclass(frozen=True)
class Verdict:
    checks: tuple
    allow: bool
    reasons: tuple = ()
    unverified: tuple = ()

    def as_dict(self) -> dict:
        return {
            "allow": self.allow,
            "reasons": list(self.reasons),
            "unverified": list(self.unverified),
            "checks": [
                {"name": c.name, "status": c.status, "detail": c.detail,
                 "observed": str(c.observed), "required": str(c.required)}
                for c in self.checks
            ],
        }


def prev_business_day(day) -> pd.Timestamp:
    d = pd.Timestamp(day).normalize()
    x = d - pd.Timedelta(days=1)
    while x.weekday() >= 5:
        x -= pd.Timedelta(days=1)
    return x


def required_data_through(now_et) -> pd.Timestamp:
    """The INTRADAY requirement. Kept under its old name because every existing caller means
    this one, and renaming it would have moved the meaning of live call sites silently.

    Stage 5Q-5 split the question: the daily series has its own availability and its own
    answer, `required_daily_close_through`. See the block above `evaluate` for why one
    requirement could not serve both.

    Before 13:45 ET the day's own pre-flight has not run, so the answer is the previous
    trading day. From 13:45 ET it is today — but only once the pre-flight has actually
    completed, which is why the caller passes the pre-flight record in rather than this
    function assuming it.
    """
    return required_intraday_through(now_et)


def _csv_last_date(path: Path) -> "pd.Timestamp | None":
    try:
        df = pd.read_csv(path, usecols=["date"])
        return pd.Timestamp(df["date"].max()).normalize()
    except Exception:
        return None


def _parquet_last_ts(path: Path) -> "pd.Timestamp | None":
    """Last index timestamp of a parquet, read WITHOUT loading the frame twice.

    Uses the same loader the route uses, so "fresh enough for the gate" and "fresh enough
    for the engine" are the same question asked once. A loader-specific timezone difference
    is exactly the kind of thing that makes a gate agree with nothing.
    """
    try:
        from futures._validated_core import load_parquet
        df = load_parquet(str(path))
        if df.empty:
            return None
        ts = pd.Timestamp(df.index[-1])
        return (ts.tz_localize(None) if ts.tz is not None else ts).normalize()
    except Exception:
        return None


def check_regime_csv(path, *, through: pd.Timestamp) -> Check:
    p = Path(path)
    if not p.exists():
        return Check("regime_csv", MISSING, f"{p} does not exist", None, str(through.date()))
    last = _csv_last_date(p)
    if last is None:
        return Check("regime_csv", UNREADABLE, f"{p} has no readable date column",
                     None, str(through.date()))
    if last < through:
        return Check("regime_csv", STALE,
                     f"last date {last.date()} is before the required {through.date()}",
                     str(last.date()), str(through.date()))
    return Check("regime_csv", OK, "", str(last.date()), str(through.date()))


def check_parquet(name: str, path, *, through: pd.Timestamp) -> Check:
    p = Path(path)
    if not p.exists():
        return Check(f"parquet:{name}", MISSING, f"{p} does not exist",
                     None, str(through.date()))
    last = _parquet_last_ts(p)
    if last is None:
        return Check(f"parquet:{name}", UNREADABLE, f"{p} could not be read",
                     None, str(through.date()))
    if last < through:
        return Check(f"parquet:{name}", STALE,
                     f"last bar {last.date()} is before the required {through.date()}",
                     str(last.date()), str(through.date()))
    return Check(f"parquet:{name}", OK, "", str(last.date()), str(through.date()))


def check_preflight_record(state_path, *, through: pd.Timestamp) -> Check:
    """The Track 1 reading of the SHARED pre-flight record.

    The 13:45 job is shared infrastructure, not a legacy strategy job — it refreshes the data
    both routes read (Stage 5L). Track 1 does not WRITE this file, and that is a deliberate
    split of duties rather than a hint that the file belongs to someone else: one writer, many
    readers. The record of whether the 13:45 update succeeded is the only evidence that exists
    about the parquet's freshness, and inventing a second record would be a second thing to
    keep in step.

    Consequence for retirement: removing the legacy entry slots must not remove this job. If it
    ever is removed, every check here turns MISSING and Track 1 fails closed — loudly, which is
    the right direction, but the schedule is the place to prevent it. See
    `global_index.track1_slots.route_classification`.

    A missing record is a REFUSAL, not a shrug — the same fail-closed direction legacy takes.
    """
    p = Path(state_path)
    key = str(through.date())
    if not p.exists():
        return Check("preflight_record", MISSING,
                     f"{p} does not exist; no evidence the {key} update ran", None, key)
    try:
        import json
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return Check("preflight_record", UNREADABLE, f"{p}: {exc}", None, key)
    val = rec.get(key)
    if val is True:
        return Check("preflight_record", OK, "", key, key)
    if val is False:
        return Check("preflight_record", STALE,
                     f"the {key} pre-flight ran and FAILED", "failed", key)
    return Check("preflight_record", MISSING,
                 f"no pre-flight record for {key} (restart, or the 13:45 job was missed)",
                 None, key)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5Q-5 — ONE requirement was being asked of TWO data sources with different
# availability, and that is the whole of B-5R-E.
#
# What was measured, 2026-08-24
# -----------------------------
#     preflight_state.json   2026-08-21 : true
#     spy_daily_live.csv     last date  2026-08-20
#     required_data_through(Mon 11:30)  2026-08-21   -> regime_csv STALE -> allow=False
#
# Two different faults were sitting on top of each other.
#
# **The requirement was wrong for the daily CSV from 13:45 onward.** `update_spy_csv` runs
# inside the 13:45 pre-flight and fetches through "today"; SPY's daily bar does not close until
# 16:00, so that fetch can never bring today's close. Asking the CSV for today from 13:45 is
# asking for a number that does not exist yet — and the route does not need it either. A
# session on day D trades the regime label of D-1: `RegimeLabels.get` returns
# `reg.asof(day - lag_days)` with `lag_days = 1`. So the causal requirement for the daily
# series, at every instant of session day D, is **the last trading day strictly before D**.
#
# The intraday parquets are a different question with a different answer. One-minute futures
# bars for today DO exist at 13:45, and the pre-flight fetches them; requiring today from
# 13:45 is right for them and always was. Hence two functions instead of one.
#
# **And the data genuinely is not there.** Even with the requirement corrected, Monday morning
# needs Friday's close and the CSV holds Thursday's — because the only refresh in the schedule
# runs at 13:45, before any close. That half is not a threshold and cannot be fixed here: it
# needs a refresh that runs after the close. It is named as its own blocker rather than
# papered over by widening the requirement, which would silently trade a session on a label
# the backtest never used.
# ══════════════════════════════════════════════════════════════════════════════


def _is_trading_day(day) -> bool:
    """Weekday AND not a US market holiday, where a calendar is available.

    Falls back to weekday-only if the calendar module cannot be imported, and the fallback is
    reported by `calendar_source()` rather than assumed: the day after a holiday is exactly
    when the difference bites — `prev_business_day` would name the holiday, the CSV can never
    contain a close for it, and the gate would refuse for ever on a route that was fine.
    """
    d = pd.Timestamp(day).normalize()
    if d.weekday() >= 5:
        return False
    try:
        from raits.live.trading_calendar import is_trading_day
    except Exception:                                      # noqa: BLE001
        return True
    try:
        return bool(is_trading_day(d.date()))
    except Exception:                                      # noqa: BLE001
        return True


def calendar_source() -> str:
    """Which calendar the requirement is being computed on. Reported in the record so a
    holiday-adjacent refusal can be read without guessing."""
    try:
        from raits.live import trading_calendar          # noqa: F401
        return "raits.live.trading_calendar"
    except Exception:                                      # noqa: BLE001
        return "weekday_only_fallback"


def prev_trading_day(day) -> pd.Timestamp:
    """The last US trading day strictly before `day`. Holidays skipped where known."""
    d = pd.Timestamp(day).normalize() - pd.Timedelta(days=1)
    for _ in range(14):
        if _is_trading_day(d):
            return d
        d -= pd.Timedelta(days=1)
    return d


def required_intraday_through(now_et) -> pd.Timestamp:
    """The last session the INTRADAY parquets must already cover.

    Unchanged from the rule this module has always had, and correct for minute bars: before
    13:45 ET the day's own pre-flight has not run, so the answer is the previous trading day;
    from 13:45 it is today, because today's minute bars exist by then and the pre-flight
    fetched them.
    """
    ts = pd.Timestamp(now_et)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/New_York").tz_localize(None)
    day = ts.normalize()
    if not _is_trading_day(day):
        return prev_trading_day(day)
    minutes = ts.hour * 60 + ts.minute
    if minutes < 13 * 60 + 45:
        return prev_trading_day(day)
    return day


def required_daily_close_through(now_et) -> pd.Timestamp:
    """The last session the DAILY series must already cover: the last trading day before today.

    Not "today from 13:45", and the difference is the bug. Today's daily close does not exist
    until 16:00, and a session on day D never needs it — the label D trades on is D-1's, by
    `RegimeLabels(lag_days=1)`. So this is the same answer all day, which is also what makes
    it checkable: a requirement that changes at 13:45 to something the data cannot hold is a
    requirement that can only be met by luck.

    On a non-trading day it is the last trading day before it, so a Saturday audit asks for
    Friday rather than for Saturday.
    """
    ts = pd.Timestamp(now_et)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("America/New_York").tz_localize(None)
    return prev_trading_day(ts.normalize())


def check_preflight_consistency(preflight: Check, data_checks) -> Check:
    """The pre-flight record against what the data actually shows.

    `preflight_state.json` says a day's 13:45 job succeeded. It does NOT say which dates
    landed, and on 2026-08-21 it said `true` while the SPY CSV still ended on 2026-08-20 — a
    true record and an unmet requirement, side by side, with nothing naming the contradiction.

    This is that name. It refuses, which changes no verdict on its own (the stale input
    already refuses) — the value is that a reader can tell "the job did not run" from "the job
    ran and reported success and the data still does not satisfy what we ask of it", which are
    different problems with different owners.
    """
    stale = [c.name for c in data_checks if c.status in REFUSING]
    if preflight.status != OK:
        return Check("preflight_consistency", OK,
                     "not applicable: the pre-flight record is not a success", None, None)
    if not stale:
        return Check("preflight_consistency", OK, "", None, None)
    return Check(
        "preflight_consistency", STALE,
        f"the pre-flight record for {preflight.required} says the 13:45 job SUCCEEDED, and "
        f"{stale} still do not satisfy what the gate asks of them. A successful refresh that "
        f"leaves an input short is not a failed job — it is a job that cannot supply what is "
        f"being asked for, which is a contract question, not a retry.",
        stale, preflight.required)


def evaluate(*, now_et, regime_csv, parquets: Mapping[str, Any],
             preflight_state="global_index/preflight_state.json",
             intraday_verified: bool = False) -> Verdict:
    """The whole gate. Fails closed: any refusing check means no entries.

    `intraday_verified` is False for every caller today and is reported as UNVERIFIED rather
    than as a pass or a failure. A Calm A or Stress decision needs this morning's bars, this
    gate cannot see them, and saying so is the only honest third state.
    """
    # Stage 5Q-5: two requirements, because the two data kinds become available at different
    # times. The pre-flight record is judged on the INTRADAY day, because that is the day its
    # 13:45 run is about.
    through = required_intraday_through(now_et)
    daily_through = required_daily_close_through(now_et)

    preflight = check_preflight_record(preflight_state, through=through)
    data_checks = [check_regime_csv(regime_csv, through=daily_through)]
    for name, path in dict(parquets).items():
        data_checks.append(check_parquet(name, path, through=through))

    checks = [preflight, *data_checks,
              check_preflight_consistency(preflight, data_checks),
              Check("requirement", OK,
                    f"intraday through {through.date()} on {calendar_source()}; daily close "
                    f"through {daily_through.date()}",
                    str(daily_through.date()), str(through.date()))]

    unverified = []
    if not intraday_verified:
        checks.append(Check("intraday_source", UNVERIFIED,
                            "the bars a same-session sleeve decides on come from the broker "
                            "at decision time; this gate cannot see them",
                            None, "a broker fetch inside the window"))
        unverified.append("intraday_source")

    refusing = [c for c in checks if c.refuses]
    return Verdict(tuple(checks), not refusing,
                   tuple(f"{c.name}: {c.detail}" for c in refusing), tuple(unverified))
