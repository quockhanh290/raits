"""global_index/track1_live_frame.py — splice today's partial session onto history, safely.

Stage 4B. **No network, no broker, no fetch.** This module takes two frames and returns one.
Where the live half comes from is the caller's problem; what this file guarantees is that
joining them cannot corrupt the history it is joined to.

The failure this exists for
---------------------------
It has already happened here, and it was not subtle. Live NKD bars arrived on the ET wall
clock and were concatenated onto a frozen frame carried on the Tokyo wall clock. JST is ET+13
in summer, so a bar labelled 03:00 meant 14:00 ET the previous day on one side and 03:00 ET on
the other. **1,050 of 1,590 live bars collided with frozen labels and silently overwrote
them** — `concat` keeps the last — with price errors of roughly 900 to 1,000 points, right
across the recent window every signal is computed from.

Nothing raised. The frame was the correct length, the index was monotonic, and every check
that existed passed.

So the rules here are not defensive decoration. Each one is the shape of a real way this join
has gone wrong or could:

    tz mismatch        REFUSED, never converted. A caller handing over a frame on a different
                       clock has made a mistake; converting it silently is how the NKD
                       corruption produced a plausible-looking frame.
    overlap            the live half is TRIMMED to bars strictly after the frozen end. History
                       is never overwritten, so a mislabelled live bar cannot rewrite a
                       settled one — it can only be refused or dropped.
    duplicates         REFUSED. A duplicated timestamp survives sorting and the last one wins
                       on a reindex, which is exactly how the overwrite went unseen.
    out of order       REFUSED. `fetch_bars` sorts, but a frame that arrives unsorted is a
                       frame whose provenance is unknown.
    column mismatch    REFUSED. Two frames with different columns concatenate into one with
                       NaN holes.
    stale live half    REPORTED, and the caller decides. Staleness is a policy question that
                       `track1_intraday` already owns per sleeve; duplicating a threshold here
                       would give the route two answers.

What "safe" does NOT mean
-------------------------
It does not mean the prices are right. This module cannot tell a correctly-labelled bar from
a wrongly-priced one. It guarantees that the frozen half comes out byte-for-byte unchanged and
that anything appended is strictly newer, in order, unique, and on the same clock.

The property worth proving, and the test that proves it
--------------------------------------------------------
If you cut a historical frame at some instant and hand the tail back as "live", splicing must
reproduce the original frame exactly — and every sleeve run on the spliced frame must produce
the same candidates as on the original. That is testable offline with no broker at all, and it
is the check that would have caught the NKD incident: the tail carried a different clock, so
the reconstruction would not have matched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

OK = "ok"
NOT_A_FRAME = "not_a_frame"
EMPTY_FROZEN = "empty_frozen"
TZ_MISMATCH = "tz_mismatch"
DUPLICATE_TIMESTAMPS = "duplicate_timestamps"
OUT_OF_ORDER = "out_of_order"
COLUMN_MISMATCH = "column_mismatch"
OVERLAP_TRIMMED = "overlap_trimmed"
NOTHING_NEW = "nothing_new"
HISTORY_MUTATED = "history_mutated"

REFUSALS = (NOT_A_FRAME, EMPTY_FROZEN, TZ_MISMATCH, DUPLICATE_TIMESTAMPS, OUT_OF_ORDER,
            COLUMN_MISMATCH, HISTORY_MUTATED)

#: Notes that are reported but do not refuse. A live half entirely inside history is normal on
#: the first slot of a session; trimming an overlap is the designed behaviour, not a fault.
NOTICES = (OVERLAP_TRIMMED, NOTHING_NEW)


class SpliceRefused(RuntimeError):
    """The join was refused. Raised rather than returned as a frame, because every caller of
    this function goes on to compute a signal from what it gets back, and a caller that has to
    remember to check a flag is a caller that will one day forget."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class SpliceReport:
    code: str
    frozen_rows: int
    live_rows_offered: int
    live_rows_appended: int
    frozen_last: Any = None
    live_first_kept: Any = None
    notices: tuple = ()
    detail: str = ""

    def as_dict(self) -> dict:
        return {"code": self.code, "frozen_rows": self.frozen_rows,
                "live_rows_offered": self.live_rows_offered,
                "live_rows_appended": self.live_rows_appended,
                "frozen_last": str(self.frozen_last),
                "live_first_kept": str(self.live_first_kept),
                "notices": list(self.notices), "detail": self.detail}


def _tz_of(idx: pd.DatetimeIndex):
    return str(idx.tz) if idx.tz is not None else None


def _check_one(name: str, df) -> None:
    if df is None or not hasattr(df, "index"):
        raise SpliceRefused(NOT_A_FRAME, f"{name} is not a frame")
    idx = pd.DatetimeIndex(df.index)
    if idx.has_duplicates:
        dup = [str(x) for x in idx[idx.duplicated()][:3]]
        raise SpliceRefused(
            DUPLICATE_TIMESTAMPS,
            f"{name} carries {int(idx.duplicated().sum())} duplicated timestamp(s), first "
            f"{dup} — sorting does not remove these and a reindex silently keeps the last, "
            f"which is how 1,050 of 1,590 live NKD bars once overwrote frozen history")
    if not idx.is_monotonic_increasing:
        bad = next(i for i in range(1, len(idx)) if idx[i] < idx[i - 1])
        raise SpliceRefused(OUT_OF_ORDER,
                            f"{name} steps backwards at position {bad}: "
                            f"{idx[bad - 1]} then {idx[bad]}")


def splice(frozen: pd.DataFrame, live: pd.DataFrame | None) -> tuple:
    """`(frame, SpliceReport)` — history plus whatever of `live` is strictly newer.

    The frozen half is returned unmodified and unshifted. Track 1's sleeves read RAW parquet
    frames, so there is no back-adjustment seam here; the legacy path's price-scale offset
    belongs to a different frame convention and is deliberately not reproduced.
    """
    _check_one("frozen", frozen)
    if len(frozen.index) == 0:
        raise SpliceRefused(EMPTY_FROZEN, "the frozen half has no bars to anchor to")

    f_idx = pd.DatetimeIndex(frozen.index)
    notices: list = []

    # `None` means "there is nothing yet", which is the ordinary first-slot case. Anything
    # else that is not a frame is a MISTAKE, and it was being read as "no bars": `getattr(42,
    # "index", [])` is empty, so an integer sailed through as an empty live half and the join
    # reported success. Caught by the test that asked for a refusal and did not get one.
    if live is None:
        return frozen, SpliceReport(NOTHING_NEW, len(f_idx), 0, 0, f_idx[-1], None,
                                    (NOTHING_NEW,), "no live bars offered")

    _check_one("live", live)
    if len(pd.DatetimeIndex(live.index)) == 0:
        return frozen, SpliceReport(NOTHING_NEW, len(f_idx), 0, 0, f_idx[-1], None,
                                    (NOTHING_NEW,), "the live half is empty")
    l_idx = pd.DatetimeIndex(live.index)

    if _tz_of(f_idx) != _tz_of(l_idx):
        raise SpliceRefused(
            TZ_MISMATCH,
            f"frozen is on {_tz_of(f_idx)!r} and live is on {_tz_of(l_idx)!r}. This is "
            f"REFUSED, not converted: converting is what makes a wrongly-clocked frame look "
            f"plausible, and a 13-hour offset between an ET live feed and a Tokyo-clocked "
            f"history is exactly the shape of the NKD corruption")

    if list(frozen.columns) != list(live.columns):
        raise SpliceRefused(COLUMN_MISMATCH,
                            f"frozen columns {list(frozen.columns)} != live "
                            f"{list(live.columns)}; concatenating them yields NaN holes")

    after = live[l_idx > f_idx[-1]]
    if len(after) < len(live):
        notices.append(OVERLAP_TRIMMED)
    if len(after) == 0:
        return frozen, SpliceReport(NOTHING_NEW, len(f_idx), len(l_idx), 0, f_idx[-1], None,
                                    tuple(notices) or (NOTHING_NEW,),
                                    "every live bar is at or before the frozen end")

    out = pd.concat([frozen, after])
    o_idx = pd.DatetimeIndex(out.index)

    # The guarantee, checked rather than asserted in prose: the frozen half must come out
    # exactly as it went in. This is the line that would have failed on the NKD incident.
    head = out.iloc[:len(f_idx)]
    if not head.index.equals(f_idx) or not head.equals(frozen):
        raise SpliceRefused(HISTORY_MUTATED,
                            "the frozen half changed during the join — this must be "
                            "impossible and it is checked because it once was not")
    if o_idx.has_duplicates or not o_idx.is_monotonic_increasing:
        raise SpliceRefused(OUT_OF_ORDER, "the joined frame is not strictly increasing")

    return out, SpliceReport(OK, len(f_idx), len(l_idx), len(after), f_idx[-1],
                             after.index[0], tuple(notices))


def cut(df: pd.DataFrame, at) -> tuple:
    """Split a frame into `(frozen, live)` at an instant, for testing a splice offline.

    Exists so the round-trip property — cut, splice, get the original back — can be exercised
    without a broker. A test fixture that built its own two frames could only ever show that
    the two frames it built join cleanly.
    """
    idx = pd.DatetimeIndex(df.index)
    at = pd.Timestamp(at)
    if at.tzinfo is None and idx.tz is not None:
        at = at.tz_localize(idx.tz)
    return df[idx <= at], df[idx > at]
