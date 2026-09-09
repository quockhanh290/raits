"""global_index/track1_session_note.py — what kind of day is this, that a reader should know?

Read-only. No gate here, no decision reversed. It answers one question and writes it where a
person will read it.

The problem it exists for
-------------------------
On 2026-09-18 this route trades a quarterly expiry Friday for the first time with complete
data. The measured window it was parameterised on contains NONE of them: every quarterly
expiry from 2017-03-17 to 2024-09-20 is missing its entire RTH from the files the backtest
and the live route both read — 31 sessions, all four US instruments, bars stopping at 09:29
because the continuous series follows the expiring contract to its last tick and does not
pick up the new front month until the next session. From 2024-12-20 the files are complete.

The decision was "run normally and record it". Recording is the half that does not happen by
itself. Nothing in the audit names a session type, so a reader coming back to 2026-09-18
would see an ordinary day and have to already know it was not one.

Derived, not written down
-------------------------
The third Friday of March, June, September and December, and the early closes, and the days
CME is shut — all asked of the calendar and the clock, never a list of dates. A list of dates
is a description, and descriptions in this repository have drifted from what they describe
five times.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

#: The four months whose third Friday is a quarterly expiry for the equity index contracts.
QUARTERLY_MONTHS = (3, 6, 9, 12)

QUARTERLY_EXPIRY = "quarterly_expiry"
EARLY_CLOSE = "early_close"
EXCHANGE_SHUT = "exchange_shut"
EQUITY_HOLIDAY = "equity_holiday"

#: What each note means for somebody reading the record afterwards. One checkable sentence,
#: not a category name repeated in longer words.
MEANING: dict = {
    QUARTERLY_EXPIRY:
        "the expiring quarterly contract settles at 09:30 and volume migrates to the next "
        "one; the window this route was parameterised on holds no session like it, because "
        "every quarterly expiry before 2024-12-20 is missing its RTH from the stored series",
    EARLY_CLOSE:
        "the equity market closes at 13:00 and the futures session ends about 13:15, so a "
        "range or a close measured across this day is not comparable with a full one",
    EXCHANGE_SHUT:
        "CME holds no session, so no sleeve on this route can look at anything and every "
        "refusal recorded on this day is a market fact rather than a fault",
    EQUITY_HOLIDAY:
        "the US equity market is shut while CME trades a shortened session, so sleeves whose "
        "window sits before 13:00 run and sleeves after it cannot",
}


def third_friday(year: int, month: int) -> _dt.date:
    """The third Friday of a month, counted rather than looked up."""
    d = _dt.date(year, month, 1)
    fridays = 0
    while True:
        if d.weekday() == 4:
            fridays += 1
            if fridays == 3:
                return d
        d += _dt.timedelta(days=1)


def is_quarterly_expiry(day: _dt.date) -> bool:
    if isinstance(day, _dt.datetime):
        day = day.date()
    return day.month in QUARTERLY_MONTHS and day == third_friday(day.year, day.month)


def notes_for(day) -> list:
    """Every note that applies to `day`, most consequential first.

    An empty list means an ordinary session, and that is a real answer rather than a gap:
    a reader who finds nothing here has been told there was nothing to know.

    Fails SILENT rather than closed, deliberately — this decides nothing, and a calendar that
    cannot answer must not turn an ordinary day into an alarming one. The reason each note is
    absent is not distinguishable from the day being ordinary, which is the one thing this
    module cannot tell you and says so here rather than pretending otherwise.
    """
    if isinstance(day, _dt.datetime):
        day = day.date()
    elif not isinstance(day, _dt.date):
        day = _dt.date.fromisoformat(str(day)[:10])

    out: list = []
    if is_quarterly_expiry(day):
        out.append(QUARTERLY_EXPIRY)
    try:
        from raits.live.trading_calendar import (is_early_close, is_futures_session,
                                                 is_trading_day)
    except Exception:                                        # noqa: BLE001
        return out
    try:
        if is_futures_session(day) is False:
            out.append(EXCHANGE_SHUT)
        elif not is_trading_day(day):
            out.append(EQUITY_HOLIDAY)
        elif is_early_close(day):
            out.append(EARLY_CLOSE)
    except Exception:                                        # noqa: BLE001
        pass
    return out


def line_for(day) -> str:
    """One sentence for the panel, or the empty string on an ordinary day."""
    notes = notes_for(day)
    if not notes:
        return ""
    return " · ".join(f"{n.replace('_', ' ')} — {MEANING[n]}" for n in notes)


def next_quarterly_expiry(after) -> Optional[_dt.date]:
    """The next quarterly expiry strictly after `after`, so the record can say one is coming
    rather than only that one has passed."""
    if isinstance(after, _dt.datetime):
        after = after.date()
    elif not isinstance(after, _dt.date):
        after = _dt.date.fromisoformat(str(after)[:10])
    for k in range(0, 16):
        y = after.year + (after.month - 1 + k) // 12
        m = (after.month - 1 + k) % 12 + 1
        if m not in QUARTERLY_MONTHS:
            continue
        d = third_friday(y, m)
        if d > after:
            return d
    return None
