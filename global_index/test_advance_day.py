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


# ── the checkpoint must notice the ENGINE changing, not only the data ─────────

import numpy as np                                                  # noqa: E402
from global_index.replay_checkpoint import make_entry, usable       # noqa: E402

SWING_KW = {"ema_period": 30, "chandelier_atr_mult": 2.5, "max_hold_days": 5}


def _price_history(n=600):
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="America/New_York")
    px = 100 + np.cumsum(np.random.RandomState(7).normal(0, 0.4, n))
    return pd.DataFrame({"open": px, "high": px + 0.5, "low": px - 0.5, "close": px},
                        index=idx)


def _open_position():
    return {"dir": "LONG", "entry": 101.0, "stop": 99.0, "extreme": 103.0,
            "entry_day": pd.Timestamp("2024-01-14"), "regime": "Normal"}


CKPT_DAY = pd.Timestamp("2024-01-15")


def test_a_checkpoint_is_refused_when_the_engine_parameters_change():
    """The fingerprint hashes the price history. Nothing hashed what turned that
    history into a position.

    A checkpoint records the open position at the end of a day. Which position that is
    depends on ema_period, the chandelier multiple and the hold limit as much as on the
    bars. Change any of them and the stored position is one the current engine would
    never have produced — and the live path resumes from it without a word, because the
    bars still hash the same.

    Measured before this: an entry carried exactly last_day, fingerprint and pos, and
    usable() took only the frame — there was nothing to compare parameters against and
    nowhere they were written down.

    That matters because the parameters are not declared once. The live shadow derives
    them from the engine object; the bootstrap that writes the checkpoint declares
    literals; ema_period=10 for the Nikkei leg appears in six files. The two ends of the
    checkpoint read from different sources, which is the drift this has to catch.

    The module promises "a stale checkpoint makes the run slow, never wrong". Without
    this it makes the run fast and wrong.
    """
    df = _price_history()
    entry = make_entry(df, CKPT_DAY, _open_position(), SWING_KW)

    assert usable(entry, df, SWING_KW) is not None, (
        "same data, same parameters — this must still resume, or the optimisation is "
        "simply switched off")

    changed = {**SWING_KW, "ema_period": 10}
    assert usable(entry, df, changed) is None, (
        "the bars are identical but the engine is not: the stored position belongs to "
        "ema_period=30 and would be resumed into a run using 10")

    for field, value in (("chandelier_atr_mult", 3.0), ("max_hold_days", 4)):
        assert usable(entry, df, {**SWING_KW, field: value}) is None, (
            f"{field} changes which position is open and must invalidate the entry")


def test_an_entry_written_before_parameters_were_recorded_is_refused():
    """Fail closed on the upgrade, not open.

    Every entry on disk predates this field. Accepting them once "to avoid a rebuild"
    keeps trusting a checkpoint whose parameters were never checked for exactly the
    window where nobody is looking for the problem. Refusing costs one bootstrap run,
    which is the documented recovery and is printed in the log line that reports it.
    """
    df = _price_history()
    legacy = make_entry(df, CKPT_DAY, _open_position(), SWING_KW)
    legacy.pop("params", None)                       # an entry from the old format

    assert usable(legacy, df, SWING_KW) is None, (
        "an entry with no recorded parameters cannot be shown to match the engine "
        "about to resume from it; unknown is not the same as equal")


def test_the_data_check_still_works_alongside_the_parameter_check():
    """Control. Adding parameters must not quietly replace the history check — a
    fingerprint that only compared parameters would accept a rewritten parquet."""
    df = _price_history()
    entry = make_entry(df, CKPT_DAY, _open_position(), SWING_KW)

    edited = df.copy()
    edited.iloc[100, edited.columns.get_loc("close")] += 0.01
    assert usable(entry, edited, SWING_KW) is None, (
        "a bar was rewritten in the middle of the history and the entry survived")


def test_a_divergent_shadow_does_not_advance_the_checkpoint():
    """Detecting the disagreement and then committing the state that produced it.

    One slot a day replays the spliced frame in full and compares it with the resumed
    answer. It is the only check that closes the loop on live data — everything else
    runs on parquet, and the frames that decide live trades carry IBKR bars that are
    never persisted.

    When it disagreed, the code logged an ERROR and then advanced the checkpoint
    anyway. The new position is computed with resume_pos=pos — the same resumed path
    that just failed the comparison — so the divergence was written forward and the next
    day resumed from it. Found by walking the ancestors of the advance_day call: no
    condition anywhere in the chain, and no variable holding the verify result.

    Not advancing is the whole fix. The entry stays where it is, so tomorrow re-runs the
    same comparison from the same anchor: a persistent divergence is re-reported instead
    of being buried under a moved anchor, and a transient one costs nothing. Dropping
    the entry outright would be stronger but stops the shadow entirely — the live path
    skips an unusable checkpoint rather than replaying it — and that is a heavy response
    to something that has never fired (56 agreements, 0 divergences over seven days).

    Checked on the source, because a runtime test here would need the whole live day.
    """
    import ast
    src = (Path(__file__).resolve().parent / "run_live_day.py").read_text(encoding="utf-8")
    fn = next((n for n in ast.walk(ast.parse(src))
               if isinstance(n, ast.FunctionDef) and n.name == "_shadow"), None)
    assert fn is not None, "_shadow is gone or renamed — the locator is broken"

    parents = {c: p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}
    advance = next((n for n in ast.walk(fn) if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", None) == "advance_day"), None)
    entry = next((n for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and getattr(n.func, "attr", None) == "make_entry"), None)
    assert advance is not None and entry is not None, (
        "no advance_day/make_entry call found in _shadow — the locator is broken")

    def _conditions(node):
        out, cur = [], node
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, ast.If):
                out.append(ast.unparse(cur.test))
        return out

    guards = _conditions(advance) + _conditions(entry)
    assert any("verif" in g.lower() or "agree" in g.lower() or "match" in g.lower()
               for g in guards), (
        f"the checkpoint is advanced without consulting the comparison, so a detected "
        f"divergence is written forward and resumed from tomorrow. Conditions found: "
        f"{guards}")
