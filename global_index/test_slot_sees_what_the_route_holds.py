"""A slot must decide against the positions the route actually holds, not against an empty book.

2026-09-25. Every live slot built `Track1Book(...)` with an empty `open_book` and never read
`live_positions.track1.json`. Three rules read that list, and all three were blind:

    holders_of    SUPPRESS_SAME_SLEEVE could not see a position an earlier slot opened
    guard.admits  the cluster cap read 0% while global_nkd held 3.52% of a 6% cap
    settle_due    a position opened by an earlier slot could never be settled by a later one

What it cost, measured that night: the 01:25 ET NKD slot filled MNKD, and every slot after it
re-proposed the same trade. The order journal refused each one because FILLED is terminal, and the
slot exited 3 -- sixteen executions dying on the rule written to prevent exactly that, unable to
see the position.

And the journal's protection does not reach tomorrow. Its idempotency key carries the ref day:

    track1_candidate:2026-09-25:global_nkd:MNKD:OPEN:global_nkd::MNKD::2026-09-25

The next date is a different key, so the same signal would have been sent on top of the position
already held. Measured against the real book:

    book seeded   ->  suppress_same_sleeve   "global_nkd already holds MNKD"
    book empty    ->  take

That is the scaling question answered with a number rather than an opinion: the failure is not one
noisy night, it is a route that re-enters a position it already has as soon as the calendar turns.
"""
from __future__ import annotations

import json

import pytest

from global_index import track1_signal_layer as sl


def row(inst="MNKD", sleeve="global_nkd", qty=1, risk=1761.61, direction="LONG", **over):
    r = {"trade_id": f"{sleeve}::{inst}::2026-09-25", "sleeve": sleeve, "instrument": inst,
         "direction": direction, "qty": qty, "risk_dollars": risk,
         "entry_time": "2026-09-25 01:25:00", "exit_time": None, "entry_price": 66145.0,
         "stop_price": 63321.4}
    r.update(over)
    return r


def book_file(tmp_path, rows, route=None, **over):
    p = tmp_path / "live_positions.track1.json"
    body = {"schema_version": 2, "route": route if route is not None else "track1_candidate",
            "positions": list(rows)}
    body.update(over)
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def cand(inst="MNKD", sleeve="global_nkd", day="2026-09-26", qty=1, risk=1761.61):
    return sl.Candidate(trade_id=f"{sleeve}::{inst}::{day}", sleeve=sleeve, instrument=inst,
                        direction="LONG", qty=qty, risk_dollars=risk,
                        entry_time=f"{day} 01:10:00")


def fresh_book():
    return sl.Track1Book(guard=sl.make_guard(), enforce_windows=False)


# ── the defect, and the number that makes it a scaling problem ────────────────────────────────

def test_1_a_seeded_book_suppresses_the_same_instrument_on_a_later_day():
    """The assertion this file exists for. A new ref day means a new journal key, so the journal
    would NOT have refused this one -- the book is the only thing that can."""
    b = fresh_book()
    assert sl.seed_open_positions(b, [row()]) == 1
    d = b.evaluate(cand(), allow=True)
    assert d.verdict == sl.SUPPRESS_SAME_SLEEVE, (
        "a second MNKD on a later day was admitted as %r" % d.verdict)
    assert "already holds MNKD" in d.detail


def test_2_an_empty_book_takes_it_which_is_the_behaviour_being_fixed():
    """The falsifiability half. If this ever returns anything but `take`, test_1 has stopped
    discriminating and would pass for the wrong reason."""
    d = fresh_book().evaluate(cand(), allow=True)
    assert d.verdict == sl.TAKE, (
        "the empty-book case no longer takes the duplicate, so test_1 proves nothing: %r"
        % d.verdict)


def test_3_the_cluster_cap_can_see_positions_from_earlier_slots():
    """The second blind rule, and the one that matters at 2x size. `global_nkd` is capped at 6%
    gross of a 50,000 account = 3,000. One position already holds 1,761.61."""
    b = fresh_book()
    sl.seed_open_positions(b, [row()])
    d = b.evaluate(cand(inst="MNKD2", risk=1500.0), allow=True)
    assert d.verdict == sl.REJECT_CAP, (
        "1,761.61 + 1,500.00 = 3,261.61 is over the 3,000 cluster budget and was admitted as %r"
        % d.verdict)
    # and the same candidate against an empty book is admitted, which is today's behaviour
    assert fresh_book().evaluate(cand(inst="MNKD2", risk=1500.0), allow=True).verdict == sl.TAKE


def test_4_a_position_in_another_cluster_does_not_block_this_one():
    """The cap is per cluster, deliberately. A fix that made every sleeve see every position as
    competing budget would be a different and wrong change wearing this one's clothes."""
    b = fresh_book()
    sl.seed_open_positions(b, [row(inst="MYM", sleeve="roska4_swing", risk=677.95)])
    assert b.evaluate(cand(), allow=True).verdict == sl.TAKE


def test_5_a_seeded_row_is_never_settled_by_the_slot():
    """`exit_time` stays None on purpose. This function says what is HELD; the safety sweeps own
    exits and write the CLOSE rows. A slot that settled a seeded row would book a close nobody
    observed."""
    import pandas as pd

    b = fresh_book()
    sl.seed_open_positions(b, [row()])
    closed = b.settle_due(pd.Timestamp("2026-12-31 23:59:00"))
    assert closed == [], "the slot settled a position it only inherited: %r" % closed
    assert len(b.open_book) == 1


def test_6_a_seeded_row_says_where_it_came_from():
    b = fresh_book()
    sl.seed_open_positions(b, [row()])
    assert b.open_book[0].candidate.source == sl.SEEDED_SOURCE


# ── reading the book: three states, and a partial read is not the empty one ────────────────────

def test_7_a_missing_book_is_an_empty_book(tmp_path):
    assert sl.read_route_positions(tmp_path / "nope.json") == []


def test_8_an_unparseable_book_refuses_rather_than_reading_as_empty(tmp_path):
    p = tmp_path / "live_positions.track1.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(sl.BootstrapRefused):
        sl.read_route_positions(p)


def test_9_a_book_stamped_with_another_route_refuses(tmp_path):
    """`live_positions.json` and `live_positions.track1.json` are the same shape, so a mistaken
    path would otherwise read as a valid answer to a different question."""
    with pytest.raises(sl.BootstrapRefused):
        sl.read_route_positions(book_file(tmp_path, [row()], route="legacy"))


def test_10_a_closed_row_is_not_seeded(tmp_path):
    rows = sl.read_route_positions(
        book_file(tmp_path, [row(), row(inst="MES", exit_time="2026-09-25 03:00:00")]))
    assert [r["instrument"] for r in rows] == ["MNKD"]


def test_11_a_row_that_cannot_be_read_refuses_instead_of_being_skipped():
    """A partially seeded book understates what the route holds while looking complete, which is
    the same failure one layer up. So it raises rather than dropping the row."""
    b = fresh_book()
    with pytest.raises(sl.BootstrapRefused):
        sl.seed_open_positions(b, [row(), {"instrument": "MES"}])


def test_12_a_zero_qty_row_refuses(tmp_path):
    """The 2026-09-25 qty defect wrote exactly this row. A position of size zero is one the caps
    cannot weigh, and weighing it as zero is how a real position stops counting."""
    b = fresh_book()
    with pytest.raises(sl.BootstrapRefused):
        sl.seed_open_positions(b, [row(qty=0)])


# ── the call site: the rule may not live only in the function ──────────────────────────────────

def test_13_the_live_slot_path_actually_seeds(tmp_path):
    """A mechanism with code, tests and a runbook can still be wired into no entry point. This
    asserts the call, by source, in the function the scheduler drives."""
    import ast
    import inspect

    from global_index import run_live_day_track1 as rl

    src = inspect.getsource(rl.observe_live_slot)
    tree = ast.parse("if True:\n" + "\n".join("    " + ln for ln in src.splitlines()))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("seed_open_positions", "read_route_positions")]
    named = sorted({n.func.attr for n in calls})
    assert named == ["read_route_positions", "seed_open_positions"], (
        "the slot the scheduler drives does not both read and seed the route's book: %r" % named)


def test_14_the_slot_reports_how_many_it_held():
    """Anything added has to show up somewhere. A slot that seeds three and one that seeds none
    decide differently from the same signal, so the count is in the record."""
    import inspect

    from global_index import run_live_day_track1 as rl

    assert '"held_at_decision"' in inspect.getsource(rl.observe_live_slot)
