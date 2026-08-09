"""Which day a checkpoint may advance to.

Written after the shadow spent all of 2026-08-07 rejecting its own checkpoint.
Every slot logged "khong co checkpoint dung duoc" for MES/MNQ/MYM/M2K, with the
stored row count 554 short of the computed one, and the session produced no
comparison for four of five instruments.

The cause was not the fingerprint. It was the choice of day. Advancing used the
spliced frame — parquet plus live IBKR bars — which holds yesterday complete, so
the checkpoint moved to yesterday. The fingerprint is taken on the parquet, and
the parquet does not hold yesterday complete: appends run once a day at 13:45 ET,
so its newest date stops mid-day and the following day's append adds 13:46-23:59 ET
to a date already checkpointed. History "up to last_day" grew,
the hash changed, and the checkpoint invalidated itself within a day. Forever.

So the rule has to be read off the parquet, and stop one day short of the
parquet's own final session. The tests below are shaped like the real files:
one-minute bars, an append boundary at 13:45 on the frame's own clock.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.replay_checkpoint import advance_day

APPEND_ET = "13:45"      # frames are ET tz-aware; MNKD is the exception, below


def _frame(start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="1min")
    return pd.DataFrame({"close": 1.0}, index=idx)


def _parquet(last_day: str) -> pd.DataFrame:
    """The parquet as it sits between appends: complete through the previous
    day, then last_day only as far as the 13:45 ET append reached."""
    return _frame("2026-08-01 00:00", f"{last_day} {APPEND_ET}")


def test_stops_short_of_the_parquets_partial_day():
    """08-06 is complete in the frame the live path replays and half-written on
    disk. Taking it is exactly the 2026-08-07 bug."""
    raw = _parquet("2026-08-06")
    assert advance_day(raw, "2026-08-07", pd.Timestamp("2026-08-04")) == \
        pd.Timestamp("2026-08-05")


def test_takes_the_day_once_the_append_has_completed_it():
    """Same day, after 13:45 ET: the append has filled 08-06 to 23:59, nothing
    will add to it again, and it is now safe to fingerprint."""
    raw = _parquet("2026-08-07")
    assert advance_day(raw, "2026-08-07", pd.Timestamp("2026-08-04")) == \
        pd.Timestamp("2026-08-06")


def test_the_chosen_day_survives_the_next_append():
    """The property that actually matters, stated directly: bars added by the
    following day's append must not touch history up to the chosen day."""
    raw = _parquet("2026-08-07")
    day = advance_day(raw, "2026-08-07", None)
    before = (raw.index <= pd.Timestamp(day) + pd.Timedelta(days=1)).sum()
    tomorrow = _parquet("2026-08-08")            # one more append
    after = (tomorrow.index <= pd.Timestamp(day) + pd.Timedelta(days=1)).sum()
    assert before == after                       # 554 apart before the fix


def test_the_run_day_itself_is_never_taken():
    """Today is still trading; a checkpoint there describes a partial day."""
    raw = _parquet("2026-08-07")
    assert advance_day(raw, "2026-08-07", None) < pd.Timestamp("2026-08-07")


def test_no_move_when_already_current():
    raw = _parquet("2026-08-07")
    assert advance_day(raw, "2026-08-07", pd.Timestamp("2026-08-06")) is None


def test_never_moves_backwards():
    """A checkpoint ahead of what the parquet can support is left alone rather
    than rewound — rewinding would silently replace a good position with one
    derived from less data."""
    raw = _parquet("2026-08-06")
    assert advance_day(raw, "2026-08-07", pd.Timestamp("2026-08-06")) is None


def test_a_night_slot_before_the_append_picks_the_earlier_day():
    """Slots run before 13:45 ET too. The parquet still ends at yesterday's
    append, so the answer moves back a day — and stays stable, which is the
    point. Returning a different day at 02:00 and at 15:00 is fine; returning
    one that tomorrow invalidates is not."""
    raw = _parquet("2026-08-06")
    assert advance_day(raw, "2026-08-07", None) == pd.Timestamp("2026-08-05")


def test_tz_aware_frames_are_handled():
    """NKD is carried on a Tokyo clock, Rổ 4 on ET. Comparing a tz-aware
    index against a naive run day raises rather than misbehaves, so it would have
    surfaced — but MNKD is the instrument least covered elsewhere, and it is the
    only one whose checkpoint was working before this fix."""
    raw = _parquet("2026-08-07").tz_localize("UTC").tz_convert("Asia/Tokyo")
    out = advance_day(raw, "2026-08-07", None)
    assert out is not None and out.tz is None


def test_a_tokyo_day_ends_before_the_append_boundary():
    """Why MNKD was the one instrument still working on 2026-08-07.

    Its index is Tokyo, so a day closes at 00:00 JST = 15:00 UTC — before the
    13:45 ET append rather than after it — and history up to last_day was already
    fixed. Rổ 4 on ET closes at 00:00 ET, after the append — the failure. Stated
    as a property rather than a constant so it keeps holding through DST: the
    cutoff the fingerprint uses must land at or before where the parquet stops.
    """
    raw = _parquet("2026-08-07").tz_localize("UTC").tz_convert("Asia/Tokyo")
    day = advance_day(raw, "2026-08-07", None)
    naive = raw.index.tz_localize(None)          # what fingerprint() hashes on
    cutoff = day + pd.Timedelta(days=1)
    assert cutoff <= naive[-1]                   # the day is closed on disk

    tomorrow = _parquet("2026-08-08").tz_localize("UTC").tz_convert("Asia/Tokyo")
    assert (naive < cutoff).sum() == \
        (tomorrow.index.tz_localize(None) < cutoff).sum()


def test_an_empty_parquet_yields_nothing():
    assert advance_day(_frame("2026-08-01", "2026-08-01").iloc[:0], "2026-08-07", None) is None


def test_a_frame_with_one_session_yields_nothing():
    """Nothing before the partial day means nothing safe to checkpoint."""
    raw = _frame("2026-08-07 00:00", f"2026-08-07 {APPEND_ET}")
    assert advance_day(raw, "2026-08-07", None) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
