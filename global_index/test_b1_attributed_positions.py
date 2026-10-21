"""global_index/test_b1_attributed_positions.py — a position the route's own journal claims is
not an unexplained one.

B1 answers one question: on a shared IB Gateway login, can a position be attributed to a route?
Its own evidence says how it can answer at all — "Zero needs no attribution, which is why a
shared login can answer this at all." Everything it does follows from that.

Until 2026-09-24 the route had never placed an order, so zero was the only answer it ever had to
give, and "the Track 1 book holds a position" could only mean something had gone wrong. That
sentence is written into the refusal: "The route has placed no order, so a position here is
unexplained."

On 2026-09-24 the route placed two, they filled, and the order journal recorded both. From that
day the sentence is false, and B1 began refusing on the one condition it was built to permit —
which would block orders for as long as the route holds anything, i.e. permanently.

So the inverse of B1's own rule is what this adds: a book row whose trade_id the journal says
FILLED is ATTRIBUTED, and attributed is what B1 asks for. A row with no journal entry behind it
is still unexplained and still refuses — and that is not hypothetical either. Running the
order-layer suites the same afternoon wrote two fixtures into the live book (order_id "OID-1",
entry 5000.0, qty 0, no journal entry anywhere). Under this rule those refuse, loudly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index import track1_b1 as b1


def _journal(tmp_path, day="20260924", rows=()):
    d = tmp_path / "global_index" / "track1_runtime" / "orders"
    d.mkdir(parents=True, exist_ok=True)
    p = d / ("track1_orders_" + day + ".jsonl")
    p.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
                 encoding="utf-8")
    return p


def _filled(trade_id, inst):
    return {"candidate_id": trade_id, "instrument": inst, "state": "filled",
            "action": "OPEN", "qty": 1, "order_id": "28", "avg_price": 1.0}


def test_b1a1_a_row_the_journal_filled_is_attributed(tmp_path):
    """The condition B1 was built to permit, and had started refusing."""
    _journal(tmp_path, rows=[_filled("normal_r4::MYM::2026-09-24", "MYM")])
    ids, known = b1.journal_filled_trade_ids(root=tmp_path)
    assert known is True
    assert "normal_r4::MYM::2026-09-24" in ids


def test_b1a2_a_row_with_no_journal_entry_is_NOT_attributed(tmp_path):
    """The two fixtures a test suite wrote into the live book had no journal entry.

    That is the case this must keep catching, and the reason the rule is "the journal says so"
    rather than "the book says so" — a book can be written by anything.
    """
    _journal(tmp_path, rows=[_filled("normal_r4::MYM::2026-09-24", "MYM")])
    ids, known = b1.journal_filled_trade_ids(root=tmp_path)
    assert "calm_a::MES::2026-08-27" not in ids, (
        "a fabricated book row would read as attributed, which is how a contaminated book "
        "passes a gate whose whole job is attribution")


def test_b1a3_an_unreadable_journal_attributes_NOTHING(tmp_path):
    """Fail closed. 'I could not read the journal' must not become 'the journal agrees'."""
    d = tmp_path / "global_index" / "track1_runtime" / "orders"
    d.mkdir(parents=True, exist_ok=True)
    (d / "track1_orders_20260924.jsonl").write_text("{ not json", encoding="utf-8")
    ids, known = b1.journal_filled_trade_ids(root=tmp_path)
    assert known is False, "an unreadable journal reported itself as read"
    assert ids == set()


def test_b1a4_no_journal_at_all_attributes_nothing_and_says_so(tmp_path):
    """Before the first order there is no journal, and that is the ORIGINAL state B1 was
    written for — every book row unexplained. It must keep answering that way."""
    ids, known = b1.journal_filled_trade_ids(root=tmp_path)
    assert ids == set()
    # Absence is a knowable fact here, unlike a corrupt file: there were no orders.
    assert known is True


def test_b1a5_only_FILLED_counts(tmp_path):
    """An intent or a submission is not a position. The journal records all three states, and
    only the last one means the broker has something."""
    _journal(tmp_path, rows=[
        {"candidate_id": "x::MES::2026-09-24", "state": "intended"},
        {"candidate_id": "y::MNQ::2026-09-24", "state": "submitted"},
        _filled("z::MYM::2026-09-24", "MYM"),
    ])
    ids, _known = b1.journal_filled_trade_ids(root=tmp_path)
    assert ids == {"z::MYM::2026-09-24"}


def test_b1a6_the_operator_line_must_not_say_flat_while_holding():
    """A blanket `status == PASS` branch printed "Track 1 book flat" while the book held two
    positions the route had just opened. The operator line is the sentence read INSTEAD of the
    detail, so it is the one place a wrong word does the most damage."""
    r = b1.B1Result(status=b1.PASS, code=b1.TRACK1_BOOK_ATTRIBUTED, detail="", inputs={},
                    findings={}, checked_at="")
    line = b1.operator_line(r)
    assert "flat" not in line.lower(), f"the line still claims a flat book: {line!r}"
    assert "own positions" in line
