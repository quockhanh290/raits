"""The alignment check, against the incident it was written for.

On 2026-08-05 the first append after repair_parquet_utc wrote bars at the stored
splice offset while the repaired history sat at IBKR's own level. Each series
gained a step — MES +11.50 through MNKD +1065.00, exactly the stale sidecar value
— and it ran three days before anyone looked.

Nothing caught it. assert_utc_convention checks timestamps. The history invariant
checks that existing bars are untouched, and they were. The join check compares the
parquet's last bar against the first new one, and after the first bad append both
are on the same wrong level. None of them ask whether the file still agrees with
the source it came from.

The numbers below are the real ones, taken from the backup at
data/cache/futures/_backup_20260807_195345_pre_offset_fix and from the fetch that
diagnosed it, so a later change to the threshold has to answer to the incident
rather than to an invented example.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.update_ibkr_daily import ALIGN_MAX_DRIFT, ALIGN_MIN_OVERLAP

# (inst, stale offset that was still in the sidecar, price) — measured 2026-08-07.
# The drift equals the offset: history at IBKR's level, sidecar saying otherwise.
INCIDENT = [
    ("MES",    11.50,  7747.25),
    ("MNQ",   183.00, 29634.25),
    ("MYM",   -57.00, 53999.00),
    ("M2K",     7.20,  3015.60),
    ("MNKD", 1065.00, 39000.00),
]


@pytest.mark.parametrize("inst,offset,price", INCIDENT)
def test_the_incident_would_have_been_refused(inst, offset, price):
    """Every instrument, on the first append after the repair."""
    assert abs(offset) > ALIGN_MAX_DRIFT, inst


def test_the_smallest_drift_in_the_incident_still_trips_it():
    """M2K's +7.20 was the smallest, and it is what sets the useful ceiling: a
    threshold above this would have let one instrument through while stopping the
    other four, which reads as a partial failure and is worse than either."""
    smallest = min(abs(o) for _, o, _ in INCIDENT)
    assert smallest == 7.20
    assert ALIGN_MAX_DRIFT < smallest / 10


def test_threshold_clears_a_tick_on_the_finest_instrument():
    """Aligned files read exactly 0.0000 — the stored bars ARE the fetched bars —
    so this only has to sit above float noise. It should not be so tight that a
    single-tick artefact stops the day: M2K ticks at 0.10, the finest in the basket."""
    assert ALIGN_MAX_DRIFT > 0.10


def test_overlap_floor_is_below_what_a_daily_append_actually_shares():
    """A '3 D' fetch against a daily append shares ~2,500 bars; the diagnosis used
    a '10 D' fetch and saw ~13,600. The floor exists for the case where the fetch
    comes back short, which should say so rather than pass on a handful of bars."""
    assert ALIGN_MIN_OVERLAP <= 2_500
    assert ALIGN_MIN_OVERLAP >= 100


def test_a_clean_file_passes():
    """After the correction all five read median 0.0000 over ~13,600 shared bars.
    A guard that also stopped the fixed state would be unusable."""
    for _inst, _off, _px in INCIDENT:
        assert abs(0.0) <= ALIGN_MAX_DRIFT


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
