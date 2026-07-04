"""
raits/live/trading_calendar.py

Proactive NYSE trading calendar for the live path.

Public API
----------
  is_trading_day(d)    -> bool        — True if NYSE is open on date d
  is_early_close(d)    -> bool        — True if d closes at 13:00 ET (half-day)
  market_close_time(d) -> time        — 16:00 normally, 13:00 on early-close days
  et_now_time()        -> time        — current wall-clock time in US/Eastern

Lookup order
------------
  1. exchange_calendars  (XNYS) — most accurate, lazy-imported
  2. pandas_market_calendars (NYSE) — fallback, lazy-imported
  3. Hardcoded algorithmic rules — last resort; correct for NYSE since ~2015
     (covers all standard holidays + Black Friday, Christmas Eve, July 3 rules)

All date arguments accept datetime.date or datetime.datetime.
"""
from __future__ import annotations

import datetime
import functools
import logging
from typing import Callable, Optional, Tuple

logger = logging.getLogger("RAITS.live.trading_calendar")

_NORMAL_CLOSE = datetime.time(16, 0)
_EARLY_CLOSE  = datetime.time(13, 0)


# ── ET wall-clock helper ──────────────────────────────────────────────────────

def et_now_time() -> datetime.time:
    """Return the current wall-clock time in US/Eastern (naive, no tzinfo)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None).time()
    except Exception:
        pass
    try:
        import pytz
        return datetime.datetime.now(pytz.timezone("US/Eastern")).replace(tzinfo=None).time()
    except Exception:
        pass
    # Fallback: UTC - 4h (EDT; off by 1h in winter, acceptable for live guard)
    logger.warning(
        "et_now_time: ZoneInfo and pytz both unavailable — using UTC-4 static fallback. "
        "This is 1h WRONG in EST (November–March). Fix: pip install tzdata"
    )
    return (datetime.datetime.utcnow() - datetime.timedelta(hours=4)).time()


# ── Library-backed implementations ───────────────────────────────────────────

def _try_exchange_calendars() -> Optional[Tuple[Callable, Callable]]:
    try:
        import exchange_calendars as xcals
        import pandas as pd

        cal = xcals.get_calendar("XNYS")

        def _is_session(d: datetime.date) -> bool:
            try:
                return bool(cal.is_session(pd.Timestamp(d)))
            except Exception:
                return d.weekday() < 5

        def _close_time(d: datetime.date) -> datetime.time:
            try:
                ts = pd.Timestamp(d)
                if not cal.is_session(ts):
                    return _NORMAL_CLOSE
                close = cal.closes[ts]
                return close.tz_convert("America/New_York").replace(tzinfo=None).time()
            except Exception:
                return _NORMAL_CLOSE

        # Smoke-test the API with a known trading day
        _is_session(datetime.date(2026, 1, 2))
        _close_time(datetime.date(2026, 1, 2))
        return _is_session, _close_time
    except Exception:
        return None


def _try_pandas_market_calendars() -> Optional[Tuple[Callable, Callable]]:
    try:
        import pandas_market_calendars as mcal

        nyse = mcal.get_calendar("NYSE")

        def _is_session(d: datetime.date) -> bool:
            try:
                sched = nyse.schedule(
                    start_date=str(d), end_date=str(d),
                    tz="America/New_York",
                )
                return not sched.empty
            except Exception:
                return d.weekday() < 5

        def _close_time(d: datetime.date) -> datetime.time:
            try:
                sched = nyse.schedule(
                    start_date=str(d), end_date=str(d),
                    tz="America/New_York",
                )
                if sched.empty:
                    return _NORMAL_CLOSE
                close_ts = sched.iloc[0]["market_close"]
                return close_ts.time()
            except Exception:
                return _NORMAL_CLOSE

        _is_session(datetime.date(2026, 1, 2))
        return _is_session, _close_time
    except Exception:
        return None


# Resolve implementation at import time
_lib = _try_exchange_calendars()
_lib_name = "exchange_calendars"
if _lib is None:
    _lib = _try_pandas_market_calendars()
    _lib_name = "pandas_market_calendars"
if _lib is None:
    _lib_name = "hardcoded-fallback"

_LIB_IS_SESSION: Optional[Callable] = _lib[0] if _lib else None
_LIB_CLOSE_TIME: Optional[Callable] = _lib[1] if _lib else None

if _lib is not None:
    logger.debug("trading_calendar: using %s", _lib_name)
else:
    logger.warning(
        "trading_calendar: no calendar library found — using hardcoded rules. "
        "pip install exchange_calendars for full accuracy."
    )


# ── Hardcoded algorithmic fallback ────────────────────────────────────────────

def _compute_easter(year: int) -> datetime.date:
    """Easter Sunday via the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return datetime.date(year, month, day + 1)


def _observed(d: datetime.date) -> datetime.date:
    """NYSE holiday observance: Saturday → Friday, Sunday → Monday."""
    if d.weekday() == 5:
        return d - datetime.timedelta(days=1)
    if d.weekday() == 6:
        return d + datetime.timedelta(days=1)
    return d


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> Optional[datetime.date]:
    """Return the nth occurrence (1-based) of weekday (Mon=0) in year/month."""
    count = 0
    for day in range(1, 32):
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            break
        if d.weekday() == weekday:
            count += 1
            if count == n:
                return d
    return None


def _last_weekday_in_month(year: int, month: int, weekday: int) -> Optional[datetime.date]:
    """Return the last occurrence of weekday (Mon=0) in year/month."""
    result: Optional[datetime.date] = None
    for day in range(1, 32):
        try:
            d = datetime.date(year, month, day)
        except ValueError:
            break
        if d.weekday() == weekday:
            result = d
    return result


@functools.lru_cache(maxsize=16)
def _us_market_holidays(year: int) -> frozenset:
    """NYSE full-day closed dates for `year` (algorithmic, not hardcoded list)."""
    dates: set = set()

    # New Year's Day (Jan 1, observed)
    dates.add(_observed(datetime.date(year, 1, 1)))

    # MLK Day — 3rd Monday in January
    d = _nth_weekday(year, 1, 0, 3)
    if d:
        dates.add(d)

    # Presidents' Day — 3rd Monday in February
    d = _nth_weekday(year, 2, 0, 3)
    if d:
        dates.add(d)

    # Good Friday (2 days before Easter Sunday)
    dates.add(_compute_easter(year) - datetime.timedelta(days=2))

    # Memorial Day — last Monday in May
    d = _last_weekday_in_month(year, 5, 0)
    if d:
        dates.add(d)

    # Juneteenth — June 19 (observed; NYSE added 2022)
    if year >= 2022:
        dates.add(_observed(datetime.date(year, 6, 19)))

    # Independence Day — July 4 (observed)
    dates.add(_observed(datetime.date(year, 7, 4)))

    # Labor Day — 1st Monday in September
    d = _nth_weekday(year, 9, 0, 1)
    if d:
        dates.add(d)

    # Thanksgiving — 4th Thursday in November
    d = _nth_weekday(year, 11, 3, 4)
    if d:
        dates.add(d)

    # Christmas — Dec 25 (observed)
    dates.add(_observed(datetime.date(year, 12, 25)))

    return frozenset(dates)


@functools.lru_cache(maxsize=16)
def _early_close_dates(year: int) -> frozenset:
    """NYSE 13:00 ET early-close dates for `year`."""
    dates: set = set()

    # Black Friday — day after 4th-Thursday-in-November Thanksgiving
    thx = _nth_weekday(year, 11, 3, 4)
    if thx:
        bf = thx + datetime.timedelta(days=1)
        if bf.weekday() < 5:
            dates.add(bf)

    # Christmas Eve — Dec 24 if it falls Mon-Fri AND Dec 25 is also Mon-Fri
    dec24 = datetime.date(year, 12, 24)
    dec25 = datetime.date(year, 12, 25)
    if dec24.weekday() < 5 and dec25.weekday() < 5:
        dates.add(dec24)

    # Day before Independence Day:
    # If July 4 falls Tue-Sat (weekday 1-5), July 3 (Mon-Fri) is early close.
    jul4 = datetime.date(year, 7, 4)
    if 1 <= jul4.weekday() <= 5:
        jul3 = datetime.date(year, 7, 3)
        if jul3.weekday() < 5:
            dates.add(jul3)

    return frozenset(dates)


# ── Public API ────────────────────────────────────────────────────────────────

def is_trading_day(d: datetime.date) -> bool:
    """Return True if NYSE is open on date d."""
    if isinstance(d, datetime.datetime):
        d = d.date()
    if _LIB_IS_SESSION is not None:
        try:
            return _LIB_IS_SESSION(d)
        except Exception:
            pass
    # Hardcoded fallback
    if d.weekday() >= 5:
        return False
    return d not in _us_market_holidays(d.year)


def market_close_time(d: datetime.date) -> datetime.time:
    """Return NYSE close time (ET, naive) for date d: 16:00 normally, 13:00 on half-days."""
    if isinstance(d, datetime.datetime):
        d = d.date()
    if _LIB_CLOSE_TIME is not None:
        try:
            return _LIB_CLOSE_TIME(d)
        except Exception:
            pass
    # Hardcoded fallback
    if d in _early_close_dates(d.year):
        return _EARLY_CLOSE
    return _NORMAL_CLOSE


def is_early_close(d: datetime.date) -> bool:
    """Return True if NYSE closes at 13:00 ET on date d (half-day)."""
    if isinstance(d, datetime.datetime):
        d = d.date()
    return is_trading_day(d) and market_close_time(d) < _NORMAL_CLOSE
