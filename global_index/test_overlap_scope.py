"""global_index/test_overlap_scope.py — the overlap check compares the population it is owed.

Measured 2026-09-23, same instrument, same minutes, current offset applied, stored bars against
a fresh IBKR fetch:

    written AFTER the last anchor    1376 of 1376 identical   std 0.000
    written BEFORE it                median -1.75 (-2.3 bp)   std 1.08   worst -17.25

The second population cannot pass a 1e-6 tolerance, and not because anything is wrong with it:
the store is difference-adjusted to a 2024 contract and IBKR's continuous series is ratio-
adjusted to the current one, so one additive offset lines the two up at a single price level
and nowhere else. That is written in `update_ibkr_daily`'s own header.

So the check had been firing on a population it can never clear. It cost 49 slots on
2026-09-14 with the anchor already correct and the contract names already matching, and it gets
MORE certain the further back the fetch window reaches -- which is exactly what happens after an
outage leaves the store stale.

Three things are pinned here, and the third is the one that matters: narrowing must remove a
false alarm without removing the ability to detect anything.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.track1_live_source import (LiveSourceRefused, _overlap_population,
                                             _refuse_overlap_disagreement)

ANCHOR = pd.Timestamp("2026-09-17 12:00:00")


def _frames(n_before: int, n_after: int, *, drift: float, fault_at: int | None = None,
            fault_size: float = 5.0):
    """History and feed either side of the anchor.

    `drift` is applied only BEFORE the anchor — the structural adjustment residual.
    `fault_at` injects a real difference AFTER the anchor, which must always be caught.
    """
    before = pd.date_range(end=ANCHOR - pd.Timedelta(minutes=1), periods=n_before, freq="1min")
    after = pd.date_range(start=ANCHOR, periods=n_after, freq="1min")
    idx = before.append(after)
    hist = pd.Series(7000.0, index=idx)
    feed = hist.copy()
    feed.loc[before] += drift
    if fault_at is not None:
        feed.iloc[len(before) + fault_at] += fault_size
    mk = lambda ser: pd.DataFrame({"open": ser, "high": ser, "low": ser, "close": ser})
    return mk(hist), mk(feed)



def _check(inst, feed, hist, since):
    """Drive the two halves exactly as `live_frame` does: scope, then compare.

    Called through the pair rather than through one function, because the split IS the design:
    the comparison stays literally untouched — a source-level test in stage 5Q-4 pins that it
    keeps one raise and no new threshold — and only the population it runs on changes.
    """
    scoped = _overlap_population(inst, feed, hist, since)
    return _refuse_overlap_disagreement(inst, scoped, hist)


def test_os1_the_structural_residual_stops_failing_the_run():
    """GATE 2. The 2026-09-14 shape: every disagreeing bar is older than the anchor."""
    hist, feed = _frames(600, 400, drift=-1.75)

    with pytest.raises(LiveSourceRefused):
        _check("MES", feed, hist, None)                          # unnarrowed: still refuses

    checked = _check("MES", feed, hist, ANCHOR)
    assert checked == 400, (
        f"narrowed to {checked} bars, expected the 400 written under the current anchor")


def test_os2_a_real_fault_after_the_anchor_is_still_refused():
    """GATE 3, and the only one that matters: this must REMOVE a false alarm, not detection."""
    hist, feed = _frames(600, 400, drift=-1.75, fault_at=250, fault_size=5.0)
    with pytest.raises(LiveSourceRefused) as exc:
        _check("MES", feed, hist, ANCHOR)
    assert "disagree" in str(exc.value)


@pytest.mark.parametrize("fault_size", [5.0, 0.25, 1e-3])
def test_os3_even_a_small_fault_after_the_anchor_is_refused(fault_size):
    """No tolerance was widened. A quarter point, and a thousandth of one, still refuse."""
    hist, feed = _frames(600, 400, drift=-1.75, fault_at=10, fault_size=fault_size)
    with pytest.raises(LiveSourceRefused):
        _check("MES", feed, hist, ANCHOR)


def test_os4_narrowing_to_nothing_is_a_refusal_not_a_pass():
    """GATE 1, and the hole this closes had already fired in production.

    On 2026-09-23 the 02:55 NKD slot spliced across a 76-hour hole with zero shared minutes and
    recorded `overlap ok`. Zero compared is not agreement. If narrowing can empty the set, it
    must say so rather than inherit that silence.
    """
    hist, feed = _frames(600, 0, drift=-1.75)
    with pytest.raises(LiveSourceRefused) as exc:
        _check("MES", feed, hist, ANCHOR)
    assert exc.value.code == "overlap_before_anchor_only"


def test_os5_no_anchor_means_do_not_narrow():
    """A missing field must not quietly shrink what is checked. None keeps the wider, stricter
    comparison — the behaviour in force before any of this existed."""
    hist, feed = _frames(600, 400, drift=-1.75)
    with pytest.raises(LiveSourceRefused):
        _check("MES", feed, hist, None)


def test_os6_a_clean_join_still_reports_how_much_it_compared():
    hist, feed = _frames(600, 400, drift=0.0)
    assert _check("MES", feed, hist, ANCHOR) == 400
    assert _check("MES", feed, hist, None) == 1000
