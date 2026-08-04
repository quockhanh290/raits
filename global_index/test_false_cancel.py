"""
global_index/test_false_cancel.py — ib_insync false-cancel verification

Root cause (confirmed live 2026-08-03, and from ib_insync 0.9.86 source):
`Wrapper.error()` (wrapper.py:1097) classifies a message as a warning only if its
code is in a hardcoded set {110, 165, 202, 399, 404, 434, 492, 10167} or in
2100..2199. Anything else — including pure warnings such as 10349 "Order TIF was
set to DAY based on order preset" — takes the error branch and runs:

    if not trade.isDone():
        status = trade.orderStatus.status = OrderStatus.Cancelled

That mutation is client-side. IBKR never cancelled the order; it fills normally.
Three OPEN orders were reported CANCELLED on 2026-08-03 and all three filled,
leaving positions with no stop order (runner's STP block is gated on fill status).

Tests here cover IBKRBroker._verified_status(), which refuses a bare Cancelled.

  FC1: Cancelled + execution reports        → Filled, qty/avg from executions
  FC2: Cancelled + orderStatus catches up   → Filled, qty/avg from orderStatus
  FC3: Cancelled + genuinely nothing filled → stays Cancelled
  FC4: Filled                               → passthrough, no re-poll
  FC5: partial fill under a false cancel    → qty preserved for PARTIAL handling
  FC6: weighted average across split fills
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.ibkr_broker import IBKRBroker


# ── fakes ─────────────────────────────────────────────────────────────────────

class _Status:
    def __init__(self, status, filled=0.0, avg=0.0):
        self.status, self.filled, self.avgFillPrice = status, filled, avg


class _Exec:
    def __init__(self, shares, price):
        self.shares, self.price = shares, price


class _FillRec:
    def __init__(self, shares, price):
        self.execution = _Exec(shares, price)


class _Order:
    orderId = 42


class _Trade:
    """Trade whose state advances after `flip_after` polls, mimicking IBKR
    delivering the execution report a moment after ib_insync flipped the status."""

    def __init__(self, status, fills=(), flip_after=None, flip_to=None):
        self.orderStatus = status
        self.fills = list(fills)
        self.order = _Order()
        self._polls = 0
        self._flip_after, self._flip_to = flip_after, flip_to

    def poll(self):
        self._polls += 1
        if self._flip_after is not None and self._polls >= self._flip_after:
            if self._flip_to is not None:
                self.orderStatus = self._flip_to


class _IB:
    """Minimal ib stub — sleep() drives the trade's clock."""

    def __init__(self, trade):
        self._trade = trade
        self.sleeps = 0

    def sleep(self, _secs):
        self.sleeps += 1
        self._trade.poll()


def _run(trade):
    broker = IBKRBroker(_raw_fetcher=lambda inst, through: None)
    return broker._verified_status(_IB(trade), trade)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_fc1_cancelled_with_executions_is_filled():
    """The live 2026-08-03 case: status flipped to Cancelled, order actually traded."""
    trade = _Trade(_Status("Cancelled"), fills=[_FillRec(1, 2993.20)])
    status, filled, avg = _run(trade)
    assert status == "Filled", "execution report outranks a client-side Cancelled"
    assert filled == 1
    assert avg == pytest.approx(2993.20)


def test_fc2_cancelled_then_orderstatus_catches_up():
    """No execution objects, but orderStatus resolves to Filled during the re-poll."""
    trade = _Trade(_Status("Cancelled"), flip_after=2,
                   flip_to=_Status("Filled", filled=1.0, avg=7634.75))
    status, filled, avg = _run(trade)
    assert (status, filled) == ("Filled", 1)
    assert avg == pytest.approx(7634.75)


def test_fc3_real_cancel_stays_cancelled():
    """A genuine rejection must NOT be laundered into a fill."""
    trade = _Trade(_Status("Cancelled"))
    status, filled, avg = _run(trade)
    assert status == "Cancelled"
    assert (filled, avg) == (0, 0.0)


def test_fc4_filled_passes_through_without_repoll():
    ib_trade = _Trade(_Status("Filled", filled=1.0, avg=100.0))
    broker = IBKRBroker(_raw_fetcher=lambda inst, through: None)
    ib = _IB(ib_trade)
    status, filled, avg = broker._verified_status(ib, ib_trade)
    assert (status, filled, avg) == ("Filled", 1, 100.0)
    assert ib.sleeps == 0, "a healthy fill must not pay the verification delay"


def test_fc5_partial_fill_under_false_cancel_keeps_qty():
    """2 of 3 filled → qty must survive so send_order can report PARTIAL."""
    trade = _Trade(_Status("Cancelled"), fills=[_FillRec(2, 50.0)])
    status, filled, _ = _run(trade)
    assert (status, filled) == ("Filled", 2)


def test_fc6_weighted_average_across_split_fills():
    trade = _Trade(_Status("Cancelled"),
                   fills=[_FillRec(1, 100.0), _FillRec(3, 200.0)])
    _, filled, avg = _run(trade)
    assert filled == 4
    assert avg == pytest.approx((100.0 + 3 * 200.0) / 4)


def test_fc7_inactive_treated_like_cancelled():
    trade = _Trade(_Status("Inactive"), fills=[_FillRec(1, 10.0)])
    status, filled, _ = _run(trade)
    assert (status, filled) == ("Filled", 1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
