"""A booked position must carry the size that was actually filled, never zero.

2026-09-25, 01:25 ET. The first NKD paper fill exposed a field-name bug in the two writers that
record a confirmed fill:

    order journal     qty 1          correct
    order journal     filled_qty 0   wrong
    position book     qty 0          wrong -- a position of size zero
    trade log         contracts 0    wrong

The broker had filled MNKD x1 at 66,145 and journalled it as order 40, FILLED. Both wrong values
came from reading `cand.contracts`. `track1_signal_layer.Candidate` -- the object every Track 1
slot passes in -- declares `qty` and has no `contracts` field at all, so that read returned 0
every single time.

What makes this worth a file of its own is where the rule was already written down. The comment
directly above the book writer said a book keyed on the fill's own count "would have written a
zero-size position -- the empty book by another route". The rule was correct, stated, and the line
underneath it did the thing the comment forbade. A comment cannot enforce anything; these tests
can.

Why zero is worse than a missing row: a missing row makes the broker's position an ORPHAN, and B3
reconciliation shouts about it. A zero row looks booked. It passes a presence check, sizes a stop
at zero, and reconciles as a MISMATCH only if something compares the numbers.
"""
from __future__ import annotations

import json

from global_index import track1_order_journal as J
from global_index import track1_paper_executor as X
from global_index import track1_paper_send as ps
from global_index import track1_signal_layer as T


def cand(qty=1, inst="MNKD"):
    return T.Candidate(trade_id="global_nkd::%s::2026-09-25" % inst, sleeve="global_nkd",
                       instrument=inst, direction="LONG", qty=qty, risk_dollars=250.0,
                       entry_time="2026-09-25 01:25:00", entry_price=66140.0,
                       stop_price=63321.4, meta={})


class Fill:
    """What the paper broker actually reported on all three fills so far: FILLED, and a
    filled_qty of 0. Nothing may be keyed on this field."""

    def __init__(self, filled_qty=0, order_id="40", avg_price=66145.0):
        self.status = "filled"
        self.filled_qty = filled_qty
        self.order_id = order_id
        self.avg_price = avg_price
        self.commission = 0.69


class Decision:
    verdict = "TAKE"
    sleeve = "global_nkd"
    regime = "Normal"

    def __init__(self, c):
        self.candidate = c


def _book(tmp_path, positions=()):
    p = tmp_path / "live_positions.track1.json"
    p.write_text(json.dumps({
        "schema_version": X.BOOK_SCHEMA, "route": J.ROUTE, "positions": list(positions),
    }), encoding="utf-8")
    return p


# ── the helper, which is where the rule now lives ────────────────────────────────────────────

def test_1_qty_is_read_before_contracts():
    """The order matters. A Candidate has qty; only broker.Order spells it contracts."""
    assert ps._candidate_qty(cand(qty=3), Fill()) == 3


def test_2_a_zero_fill_count_never_wins():
    """The fill reported 0 on every real fill. If it could win, the bug comes straight back."""
    assert ps._candidate_qty(cand(qty=2), Fill(filled_qty=0)) == 2


def test_3_an_order_shaped_object_still_works():
    class Order:
        contracts = 4

    assert ps._candidate_qty(Order(), None) == 4


def test_4_the_fill_is_the_last_resort_not_the_first():
    class Bare:
        pass

    assert ps._candidate_qty(Bare(), Fill(filled_qty=5)) == 5


def test_5_nothing_anywhere_reads_zero_rather_than_guessing():
    class Bare:
        pass

    assert ps._candidate_qty(Bare(), Fill(filled_qty=0)) == 0


def test_6_a_junk_value_does_not_crash_the_write_path():
    """This runs after a broker fill. An exception here would leave a position at the broker with
    nothing recorded anywhere, which is the worst of the three outcomes."""
    class Junk:
        qty = "not a number"
        contracts = None

    assert ps._candidate_qty(Junk(), Fill(filled_qty=7)) == 7


# ── the two writers, end to end ──────────────────────────────────────────────────────────────

def test_7_the_book_records_the_size_that_was_filled(tmp_path):
    """The defect, stated as the thing that must not happen again."""
    p = _book(tmp_path)
    c = cand(qty=1)
    assert ps.advance_book(Fill(), Decision(c), book_path=p) is True

    rows = json.loads(p.read_text(encoding="utf-8"))["positions"]
    assert len(rows) == 1
    assert rows[0]["qty"] == 1, (
        "the book recorded qty %r for a fill of 1 contract" % rows[0]["qty"])
    assert rows[0]["instrument"] == "MNKD"
    # and the fill's own count is kept beside it, unused, so the discrepancy stays visible
    assert rows[0]["fill_reported_qty"] == 0


def test_8_a_multi_contract_fill_is_not_rounded_to_one(tmp_path):
    """A hardcoded 1 would pass test_7 and be just as wrong."""
    p = _book(tmp_path)
    assert ps.advance_book(Fill(), Decision(cand(qty=3)), book_path=p) is True
    assert json.loads(p.read_text(encoding="utf-8"))["positions"][0]["qty"] == 3


def test_9_no_book_row_is_ever_written_with_size_zero(tmp_path):
    """The general form, and the one that would have caught this on 2026-09-25. Whatever the
    candidate looks like, a row that reaches the book must carry a size -- because a position
    that exists at the broker and reads as zero in the book looks booked and is not."""
    for qty in (1, 2, 5):
        d = tmp_path / str(qty)
        d.mkdir()
        p = _book(d)
        assert ps.advance_book(Fill(), Decision(cand(qty=qty)), book_path=p) is True
        for row in json.loads(p.read_text(encoding="utf-8"))["positions"]:
            assert int(row["qty"]) > 0, row
