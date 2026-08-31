"""Stage 5ZZZ-AZ, re-pointed in 5ZZZ-BD. The gate that holds the route until the last slot of
a Normal session has been OBSERVED -- reading a ledger of its own, not the display store.

Each sleeve family's last slot fires at :55, which is the moment the window's final bar opens.
The detector reads a bar seconds old, its volume gate refuses it, and no later slot exists to
read it complete -- while the backtest reads the same bar whole. Measured: 13 of 1,223 orders
are signalled on that bar and withholding it costs 12.02% of P&L.

The first version of this gate read the display-side diagnostics store and filtered
reconstructions out. That broke a line three files hold BY CONSTRUCTION, and the test enforcing
it stops at the first offender -- so the readiness check and the acceptance judge stopped being
checked at all. Measured at the time: 1 mention in the gates file, 0 in the other two, and the
loop never reached them. The evidence now has its own ledger.
"""
from __future__ import annotations

import json

import pytest

from global_index import track1_final_bar_observation as fbo
from global_index import track1_gates as g

MEASURE = "final_bar_divergence_observed"
BLOCKER = "FINAL_BAR_DIVERGENCE_OBSERVED"
GUARDED_FILES = ("track1_gates.py", "track1_paper_readiness.py",
                 "track1_shadow_acceptance.py")


@pytest.fixture()
def root(tmp_path):
    return tmp_path


def _write(root, **over):
    kw = dict(root=root, session_date="2026-09-01", sleeve="roska4_swing",
              slot_id="LIVE_DAY_1555", regime="Normal", last_bar_complete=False,
              bars_evaluated=22, surge_reached=12, surge_passed=0)
    kw.update(over)
    return fbo.record(**kw)


# -- the safety line this stage exists to put back ----------------------------------------
def test_no_gate_readiness_or_acceptance_file_reads_the_display_store():
    """The line, checked here too rather than only in its original home.

    It is enforced by a plain substring check, which is crude and is the point: it caught a
    DOCSTRING that merely named the module. A guarantee that survives being mentioned is not
    the guarantee this line is after.
    """
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]
    offenders = [n for n in GUARDED_FILES
                 if "track1_strategy_diagnostics"
                 in (repo / "global_index" / n).read_text(encoding="utf-8")]
    assert offenders == [], offenders


def test_the_ledger_itself_cannot_reach_the_display_store():
    """If the ledger imported it, the gate would reach it one hop away and the line would be
    decoration."""
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]
    src = (repo / "global_index" / "track1_final_bar_observation.py").read_text(
        encoding="utf-8")
    assert "track1_strategy_diagnostics" not in src


# -- it can say YES -----------------------------------------------------------------------
def test_a_recorded_normal_final_slot_opens_the_gate(root):
    """Without this the gate could be hardcoded to refuse and every other test would pass."""
    assert _write(root) is not None
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is True, detail
    assert "closed=False" in detail
    assert "roska4_swing" in detail and "2026-09-01" in detail


def test_the_night_family_last_slot_counts_too(root):
    _write(root, sleeve="global_nkd", slot_id="NKD_NIGHT_0255")
    ok, _ = g.MEASUREMENTS[MEASURE](root)
    assert ok is True


def test_a_closed_final_bar_also_counts_as_an_observation(root):
    """The gate asks whether the behaviour was WATCHED, not what the answer turned out to be."""
    _write(root, last_bar_complete=True)
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is True and "closed=True" in detail


# -- and it says NO for each distinct reason ----------------------------------------------
def test_nothing_recorded_is_unknown_not_a_pass(root):
    """Asserted on the STATUS, not on the word.

    The first version of this test looked for "UNKNOWN" in the gate's detail string -- and the
    detail sentence for this case contains that word in its prose, so collapsing the status
    into NOT_OBSERVED left the test green. Found by mutation, not by reading it.
    """
    assert fbo.latest(root).status == fbo.UNKNOWN
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert detail.startswith(fbo.UNKNOWN + ":"), detail


def test_a_calm_session_does_not_count(root):
    """The whole question is what the detector does when the regime lets it look at bars."""
    _write(root, regime="Calm")
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert "NOT_OBSERVED" in detail and "no Normal session" in detail


def test_a_slot_that_did_not_measure_is_refused_and_says_so(root):
    """None means nobody looked. Counting it would let the gate open on silence."""
    _write(root, last_bar_complete=None)
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False
    assert "none of which answered" in detail, detail
    assert "UNKNOWN" not in detail, "a slot that ran is a different answer from no slot at all"


def test_a_non_final_slot_is_never_written_at_all(root):
    """A 15:30 slot sees its newest bar again five minutes later; the final slot never does."""
    assert _write(root, slot_id="LIVE_DAY_1530") is None
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False and "UNKNOWN" in detail


def test_an_unreadable_ledger_fails_closed(root, monkeypatch):
    """A check that cannot run is not a check that passed."""
    _write(root)

    def boom(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(fbo, "_read_dir", boom)
    ok, detail = g.MEASUREMENTS[MEASURE](root)
    assert ok is False and "failing closed" in detail


def test_a_corrupt_line_does_not_take_the_whole_ledger_down(root):
    p = _write(root)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    ok, _ = g.MEASUREMENTS[MEASURE](root)
    assert ok is True, "one bad line hid a good observation"


# -- the writer records what was measured and nothing else --------------------------------
def test_the_row_carries_the_surge_counts_the_operator_needs(root):
    p = _write(root)
    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["surge_reached"] == 12 and row["surge_passed"] == 0
    assert row["last_bar_complete"] is False
    assert row["status"] == fbo.OBSERVED


def test_the_slot_path_writes_the_ledger_beside_the_diagnostics_block():
    """Checked at the CALL SITE: a ledger nothing writes to is a gate that never opens."""
    import inspect
    from global_index import run_live_day_track1 as rl
    src = inspect.getsource(rl)
    assert "_record_final_bar_observation(_b" in src


# -- and it is wired into the thing that stops orders -------------------------------------
def test_the_blocker_is_registered_and_blocks_orders():
    b = g.BLOCKERS[BLOCKER]
    assert b.blocks_orders is True
    assert b.status == g.MEASURED_GATE
    assert b.released_by_measurement == MEASURE
    assert b.released_by == (), "no signature may open this -- it is an observation, not a call"


def test_the_gate_is_in_the_blocking_list_right_now():
    """It has to be holding the route today; a gate that is already open guards nothing."""
    assert BLOCKER in [str(getattr(x, "id", x)) for x in g.blocking()]
