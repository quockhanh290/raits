"""global_index/test_fetch_window.py — the live fetch window is sized from the history, not fixed.

Two measurements put this here, and they pull in opposite directions.

SPEED. A swing slot fetches four instruments one after another, each call capped at 120s, so
one slot's structural worst case is 480s against a slot cadence — and an audit ceiling — of
300s. On 2026-09-18 the 14:50 slot ran 305.7s, the 14:55 slot was refused the mutex, and the
whole day was marked FAIL; 2026-09-08 breached the same way. Measured across 20 days and 452
slots: the median slot takes 156s and every fetch asks for `2 D` of one-minute bars, while the
overlap records show history typically ends only a few hours back. Most of every fetch is data
the parquet already holds.

SIGHT. The same fetch does a second job nobody sized it for. Where the live half and history
share a timestamp the prices must match, and that check is what caught the 2026-09-10 roll:
1,143 of 1,185 shared minutes disagreed by up to 17.25 points. A window that does not reach
back to the last stored bar has NO shared minutes, and `_refuse_overlap_disagreement` then
returns 0 — which the caller records as `overlap_result: ok`. Not "compared and agreed":
"could not compare anything".

That blind splice is not hypothetical. It happens whenever the machine misses the daily append
and history goes stale under a fixed 2-day window: 26 MNQ slots on 2026-09-17 ran across a
28.3h hole, and the 02:55 NKD slot on 2026-09-23 across a 76.2h one. Both recorded `ok`.

So the window may not simply shrink. It has to be COMPUTED — far enough back to overlap the
last stored bar with room to spare, and no further. On an ordinary day that is much less than
two days; after an outage it is more, which is exactly the case the fixed window got wrong.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.track1_live_source import (OVERLAP_MARGIN_HOURS, lookback_to_hours,
                                             required_lookback)

_NOW = pd.Timestamp("2026-09-18 14:50:00")
_TWO_DAYS = lookback_to_hours("2 D")


def _frozen_ending(hours_back: float, *, tz: str | None = None):
    """A history frame whose last bar is `hours_back` before _NOW.

    `tz` because the real frozen half is always zone-aware — `on_frozen_clock` refuses a naive
    one — while the sizing rule itself must cope with either, so the two kinds of test ask for
    what they actually need instead of sharing one shape that suits neither.
    """
    end = _NOW - dt.timedelta(hours=hours_back)
    idx = pd.date_range(end=end, periods=400, freq="1min")
    if tz is not None:
        idx = idx.tz_localize(tz)
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx)


def test_fw1_an_ordinary_day_asks_for_much_less_than_two_days():
    """The whole point: stop paying for ~43h of bars the parquet already holds."""
    got = required_lookback(_frozen_ending(5), _NOW)
    hours = lookback_to_hours(got)
    assert hours < _TWO_DAYS, (
        f"{got!r} is not smaller than the fixed '2 D' — the fetch is no faster and the "
        f"14:50/14:55 collision stays")
    assert hours >= 5 + OVERLAP_MARGIN_HOURS, (
        f"{got!r} does not even cover the 5h gap plus the overlap margin")


def test_fw2_a_stale_history_makes_the_window_GROW():
    """The blind-splice fix, and the case the fixed window got wrong.

    2026-09-23: history 76.2h old, `2 D` could not reach it, zero shared minutes, `ok`.
    """
    got = required_lookback(_frozen_ending(76.2), _NOW)
    hours = lookback_to_hours(got)
    assert hours > _TWO_DAYS, (
        f"{got!r} still does not outreach '2 D', so a 76h-stale history would splice with "
        f"nothing to compare and the record would say ok")
    assert hours >= 76.2 + OVERLAP_MARGIN_HOURS


@pytest.mark.parametrize("gap_h", [0.0, 0.5, 5.0, 20.0, 26.0, 47.0, 65.4, 76.2, 200.0])
def test_fw3_the_window_always_reaches_past_the_last_stored_bar(gap_h):
    """The invariant that makes the overlap check possible AT ALL, at every gap seen live.

    The gaps parametrised here are the ones the baseline actually recorded, 65.4h and 76.2h
    included — both of which the fixed window failed to reach.
    """
    hours = lookback_to_hours(required_lookback(_frozen_ending(gap_h), _NOW))
    assert hours >= gap_h + OVERLAP_MARGIN_HOURS, (
        f"gap {gap_h}h: a window of {hours}h stops short of the last stored bar, so there "
        f"are no shared minutes and the overlap check is blind")


def test_fw4_no_history_falls_back_rather_than_inventing_a_window():
    """An empty frozen half is not a zero gap — nobody knows how far back to ask."""
    assert required_lookback(pd.DataFrame(), _NOW) is None
    assert required_lookback(None, _NOW) is None


def test_fw5_live_frame_actually_uses_it():
    """Drives the real join. A sizing rule nothing calls is the defect family this repo keeps
    paying for — see the autostart script that could not start anything."""
    from global_index import track1_live_source as ls

    frozen = _frozen_ending(30, tz="America/New_York")
    seen: dict = {}

    class _Provider:
        name = "probe"
        last_error = ""

        def fetch_session_bars(self, inst, *, through, lookback=None):
            seen["lookback"] = lookback
            idx = pd.date_range(end=_NOW, periods=60, freq="1min")
            return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx)

    ls.live_frame("MES", frozen=frozen, provider=_Provider(), through=_NOW)

    assert "lookback" in seen, (
        "live_frame never offered a lookback, so the provider kept the fixed 2 D and nothing "
        "about the fetch changed")
    assert seen["lookback"] is not None
    assert lookback_to_hours(seen["lookback"]) >= 30 + OVERLAP_MARGIN_HOURS


def test_fw6_the_2026_09_10_roll_is_still_caught_on_the_smaller_overlap():
    """GATE 2. The window may only shrink if it still sees what the wide one saw.

    Reconstructed from the record the live route wrote on 2026-09-14:

        MES: the live half and history disagree on 1143 of 1185 shared timestamps in 'open';
        first at 2026-09-10 18:00:00-04:00, history says 7667.5000 and the feed says
        7666.7500, largest gap 17.2500

    IBKR rolled the continuous series at 2026-09-10 18:00 ET. History is not rewritten — by
    design — so every bar from that instant on carries the old scale in the parquet and the new
    one in the feed. The slot ran on 2026-09-14, four days later, which is the point: the whole
    of a 13.4h window sits AFTER the roll, so every shared minute in it disagrees. The wide
    window saw 1,185 shared minutes and 1,143 of them were wrong; a narrow one sees fewer
    minutes and the same proportion wrong.

    The check must still refuse. If it passes, the new window is blind to a real 17-point
    splice error and must be reverted.
    """
    from global_index.track1_live_source import _refuse_overlap_disagreement

    # The overlap the NEW window yields: the margin, nothing more.
    shared = pd.date_range(end=pd.Timestamp("2026-09-14 04:30:00"),
                           periods=int(OVERLAP_MARGIN_HOURS * 60), freq="1min")
    history = pd.DataFrame({"open": 7667.50, "high": 7668.0, "low": 7667.0, "close": 7667.25},
                           index=shared)
    feed = pd.DataFrame({"open": 7666.75, "high": 7667.25, "low": 7666.25, "close": 7666.50},
                        index=shared)

    with pytest.raises(Exception) as exc:
        _refuse_overlap_disagreement("MES", feed, history)
    assert "overlap_disagreement" in str(getattr(exc.value, "code", "")) or \
           "disagree" in str(exc.value), f"refused for the wrong reason: {exc.value}"


def test_fw7_a_margin_that_saw_nothing_would_be_caught_by_its_own_gate():
    """The gate above must be able to go red, or it proves nothing.

    With a zero-length overlap the same check returns 0 and raises nothing — which is exactly
    the blind splice this work exists to close, and exactly what test_fw6 would look like if
    the margin were ever set to zero.
    """
    from global_index.track1_live_source import _refuse_overlap_disagreement

    empty = pd.DataFrame({"open": [], "high": [], "low": [], "close": []},
                         index=pd.DatetimeIndex([]))
    history = pd.DataFrame({"open": [7667.5]}, index=pd.DatetimeIndex(["2026-09-14 04:30"]))
    assert _refuse_overlap_disagreement("MES", empty, history) == 0, (
        "if this ever raises, fw6 is not proving what it claims")
    assert OVERLAP_MARGIN_HOURS > 0, "a zero margin restores the blind splice"


def test_fw8_a_tokyo_history_is_not_compared_against_an_ET_instant():
    """The sleeve whose history is NOT on the route's clock.

    `frozen_frame` returns each instrument on its own session clock: America/New_York for the
    index futures, **Asia/Tokyo** for the Nikkei sleeve. `through` is the fetch instant on the
    provider clock, naive ET. Subtracting one wall clock from the other is meaningless, and it
    fails in the dangerous direction: Tokyo is 13-14 hours AHEAD, so the gap comes out negative,
    clamps to zero, and the window shrinks to the bare margin exactly when the history is stale
    and the fetch most needs to reach back.

    Caught by measuring, not by reading: a standalone check printed a gap of -15.0h for MNKD
    while every index future printed a small positive one, and a negative gap cannot be real.

    Same family as the two parquet loaders that return ET and UTC for the same file — compare
    in the frame's own clock or do not compare at all.
    """
    from global_index.track1_live_source import required_lookback

    # 45h of real staleness. The size is chosen, not arbitrary: the clock error understates
    # the gap by ~13h, and rounding the window UP to whole days can absorb that at some
    # staleness values and not others. At 40h the wrong answer rounds up to 2 D and passes
    # for the wrong reason; at 45h it does not. A test that only goes red at some inputs is
    # a test that reports the bug as fixed on the others.
    et_now = pd.Timestamp("2026-09-23 08:00:00")                      # naive ET, as `through`
    tokyo_last = (et_now.tz_localize("America/New_York")
                  .tz_convert("Asia/Tokyo") - dt.timedelta(hours=45))
    idx = pd.date_range(end=tokyo_last, periods=400, freq="1min")
    frozen = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=idx)

    hours = lookback_to_hours(required_lookback(frozen, et_now))
    assert hours >= 45 + OVERLAP_MARGIN_HOURS, (
        f"a 45h-stale Tokyo history asked for only {hours}h — the clocks were subtracted "
        f"raw, so the window shrank to the margin and the overlap check goes blind on the "
        f"one sleeve whose history is not on the route's clock")
