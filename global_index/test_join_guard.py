"""The join check in update_ibkr_daily, on the numbers it was set from.

IBKR ContFuture is ratio back-adjusted to whichever contract is current, and we only
ever append, so the first append after a roll carries the next contract's price level
while everything before it carries the previous one's. The splice offset is computed
once and never revisited, so nothing absorbs the difference.

The threshold cannot be read off the size of the move: the largest one-minute move of
the past year is BIGGER than the roll spread on every instrument. It comes from how
ordinary the move is — p99.9 of one-minute changes against the spread — and from the
join being one specific minute a day rather than all 400k of them.

These cases are the measured numbers, so a later change to the threshold has to
confront them rather than just pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.update_ibkr_daily import JOIN_JUMP_MAX_PCT

# (inst, last close, p99.9 of |Δ| over ~400k 1-min bars, Sep→Dec spread) — 2026-08-07
MEASURED = [
    ("MES",  7747.25,  11.75,  66.75),
    ("MNQ", 29634.25,  62.50, 298.25),
    ("MYM", 53999.00,  83.00, 400.00),
    ("M2K",  3015.60,   7.00,  23.50),
]


def _pct(move: float, price: float) -> float:
    return abs(move) / price * 100


@pytest.mark.parametrize("inst,price,p999,spread", MEASURED)
def test_roll_spread_is_refused(inst, price, p999, spread):
    """Every roll must trip it, or the guard has no purpose."""
    assert _pct(spread, price) > JOIN_JUMP_MAX_PCT, inst


@pytest.mark.parametrize("inst,price,p999,spread", MEASURED)
def test_ordinary_moves_pass(inst, price, p999, spread):
    """A one-in-a-thousand minute must not stop the day's trading."""
    assert _pct(p999, price) < JOIN_JUMP_MAX_PCT, inst


@pytest.mark.parametrize("inst,price,p999,spread", MEASURED)
def test_margins_hold_on_both_sides(inst, price, p999, spread):
    """Set between the two, not against one of them: 1.5x clear of the noise and
    2.0x clear of the signal. Narrowing either margin should fail here."""
    assert JOIN_JUMP_MAX_PCT / _pct(p999, price) >= 1.5, f"{inst}: too close to noise"
    assert _pct(spread, price) / JOIN_JUMP_MAX_PCT >= 2.0, f"{inst}: too close to roll"


def test_the_window_is_narrow():
    """Both constraints together admit only 0.348-0.370%. Worth pinning: the worst
    ordinary minute (M2K, 0.232%) and the smallest roll (MYM, 0.741%) are 3.2x
    apart, so this guard has little room on either side and a casual adjustment
    will break one end. The first attempt used 0.40% and failed the roll margin."""
    lo = max(_pct(p999, px) * 1.5 for _, px, p999, _ in MEASURED)
    hi = min(_pct(sp, px) / 2.0 for _, px, _, sp in MEASURED)
    assert lo <= JOIN_JUMP_MAX_PCT <= hi
    assert hi / lo < 1.1


def test_threshold_is_a_fraction_not_points():
    """MYM trades near 54,000 and M2K near 3,000 — a shared point threshold would
    be nonsense on one of them. Pinned because a percentage that happens to look
    like a point count is easy to 'simplify' later."""
    assert 0 < JOIN_JUMP_MAX_PCT < 5


def test_the_largest_real_move_exceeds_the_roll_spread():
    """The reason a magnitude threshold cannot work, kept as a case rather than a
    comment: MES moved 118.50 in one minute last year and the Sep→Dec spread is
    66.75. Anything tuned to 'a roll is big' would fire on real market moves."""
    largest_1min, spread = 118.50, 66.75
    assert largest_1min > spread
    assert _pct(largest_1min, 7747.25) > JOIN_JUMP_MAX_PCT   # would trip the guard


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
