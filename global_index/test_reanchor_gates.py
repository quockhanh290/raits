"""When a roll is allowed to re-anchor itself, and when the day still stops.

Refusing was right while a roll was inferred from the size of a price jump and the
offset came from a single pair of bars. Neither holds now: qualifyContracts names
the contract outright and the shift is a median over thousands of shared bars. What
makes carrying on safe is the alignment check — a wrong anchor is refused by the
next day's append, so a mistake lives one day instead of sitting in the file, which
is what the 2026-08-05 offset step did for three.

Four conditions, all required. The numbers below are measured: Sep/Dec spreads from
IBKR on 2026-08-07, and the offset step found in the parquets the same day.

The last case is the one worth keeping. That step was +11.50 on MES — 0.148% of
price — and it was a stale sidecar value, not a roll. Even mislabelled as a contract
change it stays outside the band, because carry between two expiries does not look
like that.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.update_ibkr_daily import (ALIGN_MIN_OVERLAP, REANCHOR_MAX_IQR_FRAC,
                                            REANCHOR_MAX_PCT, REANCHOR_MIN_PCT)

# (inst, price, Sep->Dec spread) measured from IBKR on 2026-08-07
ROLLS = [
    ("MES",  7747.25,  66.75),
    ("MNQ", 29634.25, 298.25),
    ("MYM", 53999.00, 400.00),
    ("M2K",  3015.60,  23.50),
]

# The 2026-08-05 offset step, from the same day's parquets
STEP_BUG = [("MES", 7768.75, 11.50), ("M2K", 3027.00, 7.20)]


def _blocked(*, rolled: bool, shift: float, price: float, iqr: float, overlap: int):
    """The conditions as main() applies them; returns why it would refuse."""
    why = []
    if not rolled:
        why.append("contract unchanged")
    if overlap < ALIGN_MIN_OVERLAP:
        why.append("overlap")
    frac = (iqr / abs(shift)) if shift else float("inf")
    if frac > REANCHOR_MAX_IQR_FRAC:
        why.append("iqr")
    pct = abs(shift) / price * 100
    if not (REANCHOR_MIN_PCT <= pct <= REANCHOR_MAX_PCT):
        why.append("magnitude")
    return why


@pytest.mark.parametrize("inst,price,spread", ROLLS)
def test_a_real_roll_re_anchors(inst, price, spread):
    """Contract changed, thousands of shared bars, a clean shift the size of carry."""
    assert _blocked(rolled=True, shift=-spread, price=price,
                    iqr=spread * 0.03, overlap=3_900) == [], inst


@pytest.mark.parametrize("inst,price,spread", ROLLS)
def test_same_shift_without_a_contract_change_still_stops(inst, price, spread):
    """Size alone never authorises anything. Without the contract having changed
    this is drift, and drift is refused however roll-like it looks."""
    assert "contract unchanged" in _blocked(
        rolled=False, shift=-spread, price=price, iqr=spread * 0.03, overlap=3_900)


@pytest.mark.parametrize("inst,price,step", STEP_BUG)
def test_the_2026_08_05_step_is_not_roll_shaped(inst, price, step):
    """The step left by the repair was 0.148% on MES and 0.239% on M2K. Even if the
    sidecar had claimed a contract change, MES falls under the band — carry between
    two expiries is a much larger fraction of price. Kept because it is the one real
    non-roll level shift this system has produced."""
    why = _blocked(rolled=True, shift=step, price=price, iqr=0.0, overlap=3_946)
    if inst == "MES":
        assert "magnitude" in why
    else:
        # M2K's 0.239% does clear the floor, which is worth being explicit about:
        # the magnitude test alone would not have stopped it. The contract check is
        # what does, and it is the reason that check is required rather than advisory.
        assert why == []


def test_noise_is_not_a_level_shift():
    """A wide IQR means the two sources disagree bar by bar rather than by a
    constant — a data problem, and not something to bake into the offset."""
    assert "iqr" in _blocked(rolled=True, shift=-66.75, price=7747.25,
                             iqr=30.0, overlap=3_900)


def test_too_few_shared_bars_stops():
    """A short fetch makes the median meaningless; say so rather than anchor on it."""
    assert "overlap" in _blocked(rolled=True, shift=-66.75, price=7747.25,
                                 iqr=2.0, overlap=100)


def test_a_move_far_too_large_stops():
    """Above the band this is not carry. 10% of price is a broken fetch."""
    assert "magnitude" in _blocked(rolled=True, shift=-775.0, price=7747.25,
                                   iqr=10.0, overlap=3_900)


def test_the_band_contains_every_measured_spread():
    """If a real roll fell outside the band the guard would stop the day it was
    built to let through."""
    for inst, price, spread in ROLLS:
        pct = spread / price * 100
        assert REANCHOR_MIN_PCT <= pct <= REANCHOR_MAX_PCT, f"{inst} at {pct:.3f}%"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
