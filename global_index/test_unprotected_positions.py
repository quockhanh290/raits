"""unprotected_positions: matching a position to a stop on ITS OWN contract.

get_working_stops and has_working_stop both match on the instrument symbol, which
answers "is there a stop for MES" rather than "is this position protected". The two
differ the moment a position and a stop sit on different expiries — after a roll,
where _handle_rollover moves the position to the next contract and the old
contract's STP is left working. The symbol-level check then reports the new
position as protected while the only live stop belongs to a contract nobody holds.

Verified against the live paper account on 2026-08-07: with one MYM 20260918 short
and its stop on the same contract it returns [], placing an unrelated MES stop does
not make it return anything, and the stop cancels cleanly. What could not be tried
there is the case it exists for — a position whose stop is on another expiry —
because producing it means deliberately unprotecting a real position. That branch
is pinned here instead.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.ibkr_broker import IBKRBroker


class _C:
    def __init__(self, symbol, expiry):
        self.symbol = symbol
        self.lastTradeDateOrContractMonth = expiry


class _Pos:
    def __init__(self, symbol, expiry, qty):
        self.contract = _C(symbol, expiry)
        self.position = qty


class _Status:
    def __init__(self, status):
        self.status = status


class _Order:
    def __init__(self, order_type):
        self.orderType = order_type
        self.orderId = 1


class _Trade:
    def __init__(self, symbol, expiry, order_type="STP", status="PreSubmitted"):
        self.contract = _C(symbol, expiry)
        self.order = _Order(order_type)
        self.orderStatus = _Status(status)


class _IB:
    def __init__(self, positions, trades):
        self._p, self._t = positions, trades

    def positions(self):
        return self._p

    def reqAllOpenOrders(self):
        return self._t


def _broker(positions, trades):
    b = IBKRBroker.__new__(IBKRBroker)
    b._raw_fetcher = None
    b._require_connection = lambda: _IB(positions, trades)
    return b


SEP, DEC = "20260918", "20261218"


def test_stop_on_the_same_contract_is_protected():
    """The live shape on 2026-08-07: one short, one stop, same expiry."""
    b = _broker([_Pos("MYM", SEP, -1)], [_Trade("MYM", SEP)])
    assert b.unprotected_positions() == []


def test_stop_on_the_previous_contract_is_not_protection():
    """The case after a roll. B4 would call this protected because a MYM stop
    exists; the position it belongs to was closed when the roll moved to December."""
    b = _broker([_Pos("MYM", DEC, -1)], [_Trade("MYM", SEP)])
    out = b.unprotected_positions()
    assert len(out) == 1
    assert out[0]["inst"] == "MYM"
    assert out[0]["expiry"] == DEC
    assert out[0]["stop_expiries"] == [SEP]      # says where the stop actually is


def test_no_stop_at_all_is_reported():
    b = _broker([_Pos("MES", SEP, 1)], [])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MES"]


def test_a_closed_position_is_not_reported():
    """IBKR keeps reporting an instrument at qty 0 after it is closed."""
    b = _broker([_Pos("MES", SEP, 0)], [])
    assert b.unprotected_positions() == []


def test_a_stop_without_a_position_is_ignored():
    """Tried live: an unrelated MES stop with no MES position returns nothing.
    An orphan is dangerous, but it is not an unprotected position."""
    b = _broker([], [_Trade("MES", SEP)])
    assert b.unprotected_positions() == []


def test_a_dead_order_does_not_count_as_protection():
    b = _broker([_Pos("MES", SEP, 1)], [_Trade("MES", SEP, status="Cancelled")])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MES"]


def test_a_non_stop_order_does_not_count_as_protection():
    """A working limit order on the same contract protects nothing."""
    b = _broker([_Pos("MES", SEP, 1)], [_Trade("MES", SEP, order_type="LMT")])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MES"]


def test_nkd_is_reported_under_its_runner_name():
    """IBKR says NKD, the runner says MNKD. Reporting the IBKR name would make the
    line unmatchable against live_positions.json."""
    b = _broker([_Pos("NKD", SEP, 1)], [])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MNKD"]


def test_offline_says_it_cannot_tell():
    """None is not 'everything is fine' — MockBroker keeps no order book, and a
    verify run must not raise a false all-clear."""
    b = IBKRBroker.__new__(IBKRBroker)
    b._raw_fetcher = object()
    assert b.unprotected_positions() is None


def test_one_unprotected_among_several_is_found():
    b = _broker(
        [_Pos("MES", SEP, 1), _Pos("MYM", DEC, -1), _Pos("M2K", SEP, 1)],
        [_Trade("MES", SEP), _Trade("MYM", SEP), _Trade("M2K", SEP)],
    )
    assert [u["inst"] for u in b.unprotected_positions()] == ["MYM"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
