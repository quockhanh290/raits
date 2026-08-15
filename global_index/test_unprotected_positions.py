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
    def __init__(self, order_type, action="SELL", qty=1):
        self.orderType = order_type
        self.orderId = 1
        # action and totalQuantity are not decoration: a SELL stop under a SHORT doubles
        # the position, and a 1-lot stop under a 2-lot position leaves one contract
        # naked. Both used to be invisible here because the fixture did not carry them.
        self.action = action
        self.totalQuantity = qty


class _Trade:
    def __init__(self, symbol, expiry, order_type="STP", status="PreSubmitted",
                 action="SELL", qty=1):
        self.contract = _C(symbol, expiry)
        self.order = _Order(order_type, action, qty)
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
    b = _broker([_Pos("MYM", SEP, -1)], [_Trade("MYM", SEP, action="BUY")])
    assert b.unprotected_positions() == []


def test_stop_on_the_previous_contract_is_not_protection():
    """The case after a roll. B4 would call this protected because a MYM stop
    exists; the position it belongs to was closed when the roll moved to December."""
    b = _broker([_Pos("MYM", DEC, -1)], [_Trade("MYM", SEP, action="BUY")])
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
    b = _broker([_Pos("MES", SEP, 1)],
                [_Trade("MES", SEP, status="Cancelled")])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MES"]


def test_a_non_stop_order_does_not_count_as_protection():
    """A working limit order on the same contract protects nothing."""
    b = _broker([_Pos("MES", SEP, 1)], [_Trade("MES", SEP, order_type="LMT")])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MES"]


def test_nkd_is_reported_under_its_runner_name():
    """IBKR says MNK, the runner says MNKD. Reporting the IBKR name would make the
    line unmatchable against live_positions.json."""
    b = _broker([_Pos("MNK", SEP, 1)], [])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MNKD"]


def test_a_stray_full_size_nkd_still_surfaces_under_its_own_name():
    """NKD is no longer ours — orders route to the micro MNK since 2026-08-14.

    A leftover full-size position must still be reported when it has no stop, because
    it is the largest unhedged exposure the account can carry. What it must NOT do is
    come back as "MNKD": that name would hand it to B4, which sizes a stop from the
    micro's $0.50 point value against a contract worth ten times that.
    """
    b = _broker([_Pos("NKD", SEP, 1)], [])
    assert [u["inst"] for u in b.unprotected_positions()] == ["NKD"], (
        "a stray full-size position must neither be dropped nor adopted as the micro"
    )


def test_offline_says_it_cannot_tell():
    """None is not 'everything is fine' — MockBroker keeps no order book, and a
    verify run must not raise a false all-clear."""
    b = IBKRBroker.__new__(IBKRBroker)
    b._raw_fetcher = object()
    assert b.unprotected_positions() is None


def test_one_unprotected_among_several_is_found():
    b = _broker(
        [_Pos("MES", SEP, 1), _Pos("MYM", DEC, -1), _Pos("M2K", SEP, 1)],
        [_Trade("MES", SEP), _Trade("MYM", SEP, action="BUY"), _Trade("M2K", SEP)],
    )
    assert [u["inst"] for u in b.unprotected_positions()] == ["MYM"]


# ── bên và độ phủ: hai chiều mà phép kiểm cũ không có ────────────────────────

def test_a_wrong_side_stop_is_not_protection():
    """Một STP SELL nằm dưới vị thế SHORT không đóng vị thế — nó NHÂN ĐÔI. Bản cũ chỉ lọc
    theo loại lệnh và trạng thái nên nó được tính là bảo vệ, và cấu hình đó đã từng có
    thật trên tài khoản (2026-08-05, MYM)."""
    b = _broker([_Pos("MYM", SEP, -1)], [_Trade("MYM", SEP, action="SELL")])
    assert [u["inst"] for u in b.unprotected_positions()] == ["MYM"]


def test_a_stop_smaller_than_the_position_leaves_it_uncovered():
    """`if exp in have` cũ kiểm SỰ TỒN TẠI. Một STP 1 hợp đồng dưới vị thế 2 hợp đồng
    thoả mãn nó, và hợp đồng thứ hai chạy trần."""
    b = _broker([_Pos("MES", SEP, 2)], [_Trade("MES", SEP, qty=1)])
    out = b.unprotected_positions()
    assert len(out) == 1 and out[0]["covered"] == 1 and out[0]["qty"] == 2


def test_stops_on_the_same_side_add_up():
    """Hai STP nhỏ phủ đủ một vị thế lớn thì vị thế đó ĐÃ được bảo vệ — nếu không, B5 sẽ
    kêu mỗi ngày với một tài khoản hoàn toàn lành."""
    b = _broker([_Pos("MES", SEP, 2)],
                [_Trade("MES", SEP, qty=1), _Trade("MES", SEP, qty=1)])
    assert b.unprotected_positions() == []


def test_a_wrong_side_stop_does_not_top_up_coverage():
    """Cộng dồn phải theo TỪNG BÊN. Một SELL 1 + một BUY 1 dưới vị thế LONG 2 không phải
    là phủ đủ — cái BUY sẽ mở thêm chứ không đóng."""
    b = _broker([_Pos("MES", SEP, 2)],
                [_Trade("MES", SEP, qty=1), _Trade("MES", SEP, qty=1, action="BUY")])
    out = b.unprotected_positions()
    assert len(out) == 1 and out[0]["covered"] == 1


def test_a_short_is_covered_by_a_buy_stop():
    b = _broker([_Pos("MES", SEP, -2)], [_Trade("MES", SEP, qty=2, action="BUY")])
    assert b.unprotected_positions() == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
