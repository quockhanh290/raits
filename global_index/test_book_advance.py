"""global_index/test_book_advance.py — a confirmed fill must reach the route's book.

Measured 2026-09-24, the first day this route was armed. Two orders were sent from slot
TRACK1_SWING_1555, both FILLED at the broker — MYM at 51,732.00 and M2K at 2,857.00 — and
`live_positions.track1.json` came out of the session with `positions: []`.

The contract was written and only half built. `track1_paper_executor` says so in its own words:

    "**It never touches the book.** There is no writer for live_positions.track1.json here at
     all — not a guarded one, none. The executor returns the Fill and the caller advances the
     book, and only on a confirmed fill."

The caller is `maybe_send_orders`, and what it did with the Fill was count it: `filled += 1`.
Nobody advanced anything. Same family as every other defect found that day — a component
correct in itself whose counterpart was never wired.

What it cost, all of it downstream of the empty book:
  * the safety net watches the book, so 11 jobs had nothing to protect
  * the stop-arming path reads the book, so the 14h arming had no position to arm
  * the B3 reconciler compared book 0 against broker 2 and halted new entries — correctly,
    and it was the only thing that noticed

So the four properties below are not style. Each one is a way the day could have gone worse.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index import track1_paper_send as ps


class _Fill:
    def __init__(self, status="filled", qty=1, price=51732.0, order_id="28"):
        self.status = status
        self.filled_qty = qty
        self.qty = qty
        self.avg_price = price
        self.order_id = order_id


class _Cand:
    trade_id = "normal_r4::MYM::2026-09-24"
    instrument = "MYM"
    direction = "LONG"
    contracts = 1
    entry_price = 51732.0
    stop_price = 50880.0
    risk_dollars = 852.0
    entry_time = "2026-09-24 15:55:00"


class _Decision:
    def __init__(self):
        self.candidate = _Cand()
        self.sleeve = "roska4_swing"


def _book(tmp_path, positions=()):
    p = tmp_path / "live_positions.track1.json"
    p.write_text(json.dumps({
        "schema_version": 2, "route": "track1_candidate", "window": "live",
        "positions": list(positions),
    }), encoding="utf-8")
    return p


def test_bk1_a_confirmed_fill_lands_in_the_book(tmp_path):
    """The whole defect, in one assertion."""
    p = _book(tmp_path)
    ps.advance_book(_Fill(), _Decision(), book_path=p)
    rows = json.loads(p.read_text(encoding="utf-8"))["positions"]
    assert len(rows) == 1, f"the fill did not reach the book: {rows}"
    r = rows[0]
    # The three keys `track1_paper_executor.read_book` REFUSES a row without.
    assert r["instrument"] == "MYM" and r["direction"] == "LONG" and int(r["qty"]) == 1


def test_bk1b_a_confirmed_fill_writes_both_book_dialects(tmp_path):
    """The live protection readers still consume the legacy spelling.

    A row with only `instrument/sleeve/qty/entry_time` reaches the book but cannot be
    classified by `check_open_orders`: `inst` is None, the stop-deferral rule has no
    `entry_day`, and a deliberately deferred same-day swing position turns into an
    unclassifiable protection gap.  The writer must therefore write both dialects at
    the source.
    """
    p = _book(tmp_path)
    ps.advance_book(_Fill(), _Decision(), book_path=p)
    r = json.loads(p.read_text(encoding="utf-8"))["positions"][0]
    assert r["instrument"] == r["inst"] == "MYM"
    assert r["sleeve"] == r["cluster"] == "roska4_swing"
    assert r["qty"] == r["contracts"] == 1
    assert r["entry_day"] == "2026-09-24"
    assert r["exit_day"] is None
    assert r["exit_pending"] is False
    assert r["stop_order_id"] is None


def test_bk2_an_UNKNOWN_fill_must_not_be_written(tmp_path):
    """"No" and "I could not hear you" are different facts — the executor's own words.

    A position written from an unconfirmed send is a position nobody can trust, and the
    reconciler would then see a book row with no broker behind it: the same mismatch as
    today's, pointing the opposite way and much harder to reason about.
    """
    p = _book(tmp_path)
    for status in ("unknown", "", "rejected"):
        ps.advance_book(_Fill(status=status), _Decision(), book_path=p)
    assert json.loads(p.read_text(encoding="utf-8"))["positions"] == []


def test_bk3_the_same_fill_twice_does_not_double_the_position(tmp_path):
    """The signal persisted across three slots on 2026-09-24 and the journal is keyed for it.

    A book that grows a row per slot would report three contracts where the broker holds one,
    and the reconciler would halt on a mismatch the book itself invented.
    """
    p = _book(tmp_path)
    ps.advance_book(_Fill(), _Decision(), book_path=p)
    ps.advance_book(_Fill(), _Decision(), book_path=p)
    rows = json.loads(p.read_text(encoding="utf-8"))["positions"]
    assert len(rows) == 1, f"the same trade was booked twice: {rows}"


def test_bk4_an_unreadable_book_refuses_rather_than_replacing_it(tmp_path):
    """Fail closed, and never by starting a fresh book over the top of one it could not read.

    Overwriting would silently drop positions the route really holds, which is the one outcome
    worse than not recording the new one.
    """
    p = tmp_path / "live_positions.track1.json"
    p.write_text("{ this is not json", encoding="utf-8")
    before = p.read_text(encoding="utf-8")
    # A bare `pytest.raises(Exception)` passed here while `advance_book` did not exist at all —
    # AttributeError is an Exception. Named so the test cannot be satisfied by the function
    # being missing, which is the very state it was written to end.
    with pytest.raises(json.JSONDecodeError):
        ps.advance_book(_Fill(), _Decision(), book_path=p)
    assert p.read_text(encoding="utf-8") == before, "the unreadable book was overwritten"


def test_bk5_a_book_stamped_another_route_is_refused(tmp_path):
    """`live_positions.json` and `live_positions.track1.json` are the same shape, so a wrong
    path would otherwise have this route writing into legacy's book."""
    p = tmp_path / "live_positions.track1.json"
    p.write_text(json.dumps({"schema_version": 2, "route": "legacy", "positions": []}),
                 encoding="utf-8")
    with pytest.raises(ps.SendRefused, match="route"):
        ps.advance_book(_Fill(), _Decision(), book_path=p)


def test_bk6_maybe_send_orders_actually_calls_it(monkeypatch, tmp_path):
    """The wiring test, and the one this whole file exists because nobody wrote.

    `advance_book` being correct changes nothing if `maybe_send_orders` still just counts the
    Fill. That is exactly the shape of the original defect.
    """
    import inspect
    src = inspect.getsource(ps.maybe_send_orders)
    assert "advance_book" in src, (
        "maybe_send_orders does not advance the book, so a correct writer is wired to nothing "
        "— which is the defect this file was written about, restored")


def test_bk7_a_send_under_a_tmp_root_never_touches_the_repo_book(tmp_path, monkeypatch):
    """The contamination this file's own author caused, one hour after writing the rest.

    Running the three order-layer suites on 2026-09-24 put two rows into the REAL
    `live_positions.track1.json` — trade_id `calm_a::MES::2026-08-27`, order_id "OID-1",
    entry 5000.0, qty 0 — because `advance_book` defaulted to the module's production path and
    `maybe_send_orders` passed no path at all. The live book that the safety net and the B3
    reconciler both read held two fabricated positions.

    The project had already paid for this shape twice: "a test that merely called it left
    artefacts in the repo", and a shared explanations path that erased one sleeve's rows with
    another's. `root` exists precisely so a caller can be given somewhere else to write.
    """
    import inspect
    src = inspect.getsource(ps.maybe_send_orders)
    assert "Path(root)" in src, (
        "maybe_send_orders still lets advance_book default to the production book path, so any "
        "test that reaches a fill writes into the live book")

    repo_book = Path(__file__).resolve().parent.parent / "live_positions.track1.json"
    before = repo_book.read_text(encoding="utf-8") if repo_book.exists() else None

    book = _book(tmp_path)
    ps.advance_book(_Fill(), _Decision(), book_path=book)
    assert json.loads(book.read_text(encoding="utf-8"))["positions"], "the tmp book got nothing"

    after = repo_book.read_text(encoding="utf-8") if repo_book.exists() else None
    assert after == before, "the repo's live book changed while a test was running"
