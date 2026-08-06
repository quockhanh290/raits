"""global_index/test_stp_accept.py — place_stop must confirm IBKR accepted the order

Root cause (confirmed live 2026-08-05, and from ib_insync 0.9.86 source):
`IB.placeOrder` allocates the order id on the CLIENT — `ib.py:654`:

    orderId = order.orderId or self.client.getReqId()

and assigns it at ib.py:671 before the call returns, with an initial local status of
PendingSubmit. So `trade.order.orderId` is always non-zero the instant placeOrder
returns, and says nothing about whether IBKR received anything.

place_stop's guard was `for _n in range(10): if trade.order.orderId != 0: break`
(commit 42e1fc6). That condition cannot be false — it exits on the first iteration
every time and its `else:` warning branch is dead code. It returned a locally minted
id and logged "placed".

On 2026-08-05 three stops were logged as placed with ids 62/66/70 at prices matching
live_positions.json exactly. An independent client (clientId 88, reqAllOpenOrders +
reqCompletedOrders) found none of them — not open, not completed. They never entered
IBKR's book, and three positions were carried overnight unprotected.

Tests here cover IBKRBroker._await_stop_accepted(), which waits for a real status.

  SA1: PreSubmitted                    → accepted
  SA2: stuck at PendingSubmit          → NOT accepted (the 2026-08-05 case)
  SA3: Cancelled                       → NOT accepted
  SA4: status arrives late             → accepted once it settles
  SA5: Submitted                       → accepted
  SA6: Inactive (IBKR rejection)       → NOT accepted
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.ibkr_broker import IBKRBroker


# ── fakes ─────────────────────────────────────────────────────────────────────

class _Status:
    def __init__(self, status):
        self.status = status


class _LogEntry:
    def __init__(self, message):
        self.message = message


class _Order:
    orderId = 62


class _Trade:
    """Trade whose status advances after `settle_after` polls."""

    def __init__(self, status, settle_after=None, settle_to=None, log=()):
        self.orderStatus = _Status(status)
        self.order = _Order()
        self.log = list(log)
        self._polls = 0
        self._settle_after, self._settle_to = settle_after, settle_to

    def poll(self):
        self._polls += 1
        if (self._settle_after is not None
                and self._polls >= self._settle_after
                and self._settle_to is not None):
            self.orderStatus = _Status(self._settle_to)


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
    return broker._await_stop_accepted(_IB(trade), trade)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_sa1_presubmitted_is_accepted():
    """A GTC stop resting at the exchange reports PreSubmitted."""
    accepted, status, _ = _run(_Trade("PreSubmitted"))
    assert accepted is True
    assert status == "PreSubmitted"


def test_sa2_stuck_pendingsubmit_is_not_accepted():
    """The 2026-08-05 case: ib_insync's initial local status, never confirmed by IBKR.

    The old guard read trade.order.orderId here and called it a success.
    """
    accepted, status, _ = _run(_Trade("PendingSubmit"))
    assert accepted is False, (
        "PendingSubmit is ib_insync's own initial status (ib.py:673) — it is not "
        "confirmation that IBKR has the order"
    )
    assert status == "PendingSubmit"


def test_sa3_cancelled_is_not_accepted():
    accepted, status, _ = _run(_Trade("Cancelled"))
    assert accepted is False
    assert status == "Cancelled"


def test_sa4_late_confirmation_is_accepted():
    """Slow acknowledgement must not be read as failure."""
    trade = _Trade("PendingSubmit", settle_after=3, settle_to="PreSubmitted")
    accepted, status, _ = _run(trade)
    assert accepted is True
    assert status == "PreSubmitted"


def test_sa5_submitted_is_accepted():
    accepted, status, _ = _run(_Trade("Submitted"))
    assert accepted is True


def test_sa6_inactive_reports_the_reason():
    """IBKR rejections surface as Inactive; the reason lives in trade.log."""
    trade = _Trade("Inactive", log=[_LogEntry("stop price too close to market")])
    accepted, status, reason = _run(trade)
    assert accepted is False
    assert status == "Inactive"
    assert "too close" in reason, (
        f"the rejection reason must be surfaced for the log, got {reason!r}"
    )


# ── cancel_order must see orders placed by an earlier session ────────────────
#
# The runner reconnects fresh every 5-minute slot (clientId=1, run-and-exit
# subprocess), so ib.trades() — session-local — never contains a stop placed on an
# earlier day. cancel_order scanned exactly that and reported "not found in open
# trades" for orders that were sitting live at IBKR the whole time.
#
# has_working_stop() in the same file already issues reqAllOpenOrders() for this
# reason. cancel_order was left behind — the fix was applied to half the file.


class _CancelTrade:
    def __init__(self, order_id, done=False):
        self.order = type("O", (), {"orderId": order_id})()
        self._done = done

    def isDone(self):
        return self._done


class _CancelIB:
    """trades() is session-local and empty; the order only appears in openTrades()
    once reqAllOpenOrders() has been issued — mirroring IBKR's actual behaviour."""

    def __init__(self, cross_session_trades):
        self._cross = cross_session_trades
        self.req_all_called = 0
        self.cancelled: list = []

    def trades(self):
        return []

    def reqAllOpenOrders(self):
        self.req_all_called += 1

    def openTrades(self):
        return list(self._cross) if self.req_all_called else []

    def cancelOrder(self, order):
        self.cancelled.append(order.orderId)

    def sleep(self, _secs):
        pass


def _cancel_broker(fake_ib):
    broker = IBKRBroker(_raw_fetcher=lambda inst, through: None)
    broker._raw_fetcher = None            # leave offline short-circuit, keep the fake ib
    broker._require_connection = lambda: fake_ib
    return broker


def test_ca1_cancels_order_from_earlier_session():
    """The 2026-08-05 case: stops 9 and 10 were live at IBKR but invisible to ib.trades()."""
    fake = _CancelIB([_CancelTrade(9)])
    ok = _cancel_broker(fake).cancel_order("9")

    assert fake.req_all_called >= 1, (
        "cancel_order must issue reqAllOpenOrders() — without it, an order placed in "
        "an earlier session is never found and the stop is orphaned"
    )
    assert ok is True
    assert 9 in fake.cancelled


def test_ca2_genuinely_absent_order_returns_false():
    """Not-found must stay False — the caller alerts on it."""
    fake = _CancelIB([])
    assert _cancel_broker(fake).cancel_order("9") is False
    assert fake.cancelled == []


def test_ca3_already_done_order_is_not_cancelled():
    """A filled stop is gone; cancelling it is not success."""
    fake = _CancelIB([_CancelTrade(9, done=True)])
    assert _cancel_broker(fake).cancel_order("9") is False
    assert fake.cancelled == []


# ── get_order_status has the same session-local blind spot ───────────────────
#
# It scans ib.trades() → ib.fills() → ib.openTrades(), but never issues
# reqAllOpenOrders(). The first two are session-local, and openTrades() only carries
# other clients' orders after that request. B3 reads this to tell "the STP fired" from
# "orphan position", and a wrong NOT_FOUND there escalates to CRITICAL + halt entries.


class _StatusTrade:
    def __init__(self, order_id, status):
        self.order = type("O", (), {"orderId": order_id})()
        self.orderStatus = _Status(status)


class _StatusIB(_CancelIB):
    """Same cross-session behaviour as _CancelIB, plus an empty fills() ledger."""

    def fills(self):
        return []


def test_gs1_finds_live_stop_from_earlier_session():
    """A GTC stop placed yesterday is PENDING, not NOT_FOUND."""
    fake = _StatusIB([_StatusTrade(9, "PreSubmitted")])
    status = _cancel_broker(fake).get_order_status("9")

    assert fake.req_all_called >= 1, (
        "get_order_status must issue reqAllOpenOrders() before scanning openTrades(), "
        "or a stop from an earlier session reads as NOT_FOUND and B3 halts entries"
    )
    assert status == "PENDING", f"live GTC stop must read PENDING, got {status!r}"


def test_gs2_absent_order_still_not_found():
    """Genuinely gone must stay NOT_FOUND — B3 depends on that distinction."""
    assert _cancel_broker(_StatusIB([])).get_order_status("9") == "NOT_FOUND"


# ── working-stop lookups must speak the runner's instrument names ────────────
#
# The runner calls everything by its internal name; IBKR knows MNKD as NKD
# (_RAITS_TO_IBKR). A lookup keyed on the IBKR symbol never matches "MNKD", so an
# NKD position would read as unprotected on every slot — B4 re-placing a stop that
# is already working is exactly the duplicate-STP case that closes a position twice.


class _StopTrade:
    def __init__(self, symbol, order_id, order_type="STP", status="PreSubmitted"):
        self.contract = type("C", (), {"symbol": symbol})()
        self.order = type("O", (), {"orderId": order_id, "orderType": order_type})()
        self.orderStatus = _Status(status)


class _StopsIB(_CancelIB):
    def openTrades(self):
        return list(self._cross)          # reqAllOpenOrders already asserted elsewhere


def test_ws1_nkd_stop_is_keyed_by_runner_name():
    """IBKR reports NKD; the runner asks about MNKD."""
    fake = _StopsIB([_StopTrade("NKD", 71)])
    working = _cancel_broker(fake).get_working_stops()

    assert working == {"MNKD": "71"}, (
        f"stop must be keyed by the runner's instrument name, got {working}"
    )


def test_ws2_plain_symbols_pass_through():
    fake = _StopsIB([_StopTrade("MES", 62), _StopTrade("M2K", 70)])
    assert _cancel_broker(fake).get_working_stops() == {"MES": "62", "M2K": "70"}


def test_ws3_non_stop_and_dead_orders_excluded():
    fake = _StopsIB([
        _StopTrade("MES", 1, order_type="MKT"),
        _StopTrade("MYM", 2, status="Cancelled"),
        _StopTrade("M2K", 3),
    ])
    assert _cancel_broker(fake).get_working_stops() == {"M2K": "3"}


def test_ws4_has_working_stop_also_speaks_runner_names():
    fake = _StopsIB([_StopTrade("NKD", 71)])
    assert _cancel_broker(fake).has_working_stop("MNKD") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
