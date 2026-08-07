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
    def __init__(self, order_id, done=False, status="PreSubmitted"):
        self.order = type("O", (), {"orderId": order_id})()
        self.orderStatus = _Status(status)
        self._done = done

    def isDone(self):
        return self._done


class _CancelIB:
    """Models the two views ib_insync gives of open orders, which disagree.

    reqAllOpenOrders() returns what IBKR reports as open right now. openTrades()
    reads wrapper.trades — an accumulating cache. IBKR pushes status updates only to
    the client that OWNS an order, so a cross-client order that fills is never
    updated there and lingers forever. Live 2026-08-06: a filled M2K stop still read
    PreSubmitted in the dashboard backend 16 minutes later.

    `stale` holds entries that only the cache still believes in.
    """

    def __init__(self, cross_session_trades, stale=()):
        self._cross = cross_session_trades
        self._stale = list(stale)
        self.req_all_called = 0
        self.cancelled: list = []

    def trades(self):
        return []

    def reqAllOpenOrders(self):
        self.req_all_called += 1
        return list(self._cross)          # authoritative, per call

    def openTrades(self):
        return list(self._cross) + self._stale   # cache — never evicts

    def cancelOrder(self, order):
        # A broker that honours the cancel — the normal case. Tests that model a
        # refusal override this.
        self.cancelled.append(order.orderId)
        for t in self._cross:
            if t.order.orderId == order.orderId:
                t._done = True
                t.orderStatus = _Status("Cancelled")

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


def test_ca4_cancel_that_does_not_take_effect_returns_false():
    """cancelOrder is a request, not a result.

    Live 2026-08-06: MYM's wrong-side stop #10 was "cancelled" twice, reported True
    both times, and stayed PreSubmitted at the broker throughout — plausibly because
    it belongs to another clientId. Returning True there tells the caller a live,
    dangerous order is gone.
    """
    fake = _CancelIB([_CancelTrade(10)])
    fake.cancelOrder = lambda order: None      # accepted, but nothing changes
    assert _cancel_broker(fake).cancel_order("10") is False, (
        "the order is still open after the cancel request — that is not success"
    )


def test_ca6_failed_cancel_names_the_owning_client(caplog):
    """IBKR only lets the originating clientId cancel an order.

    Confirmed live 2026-08-06: MYM #10 refused every cancel from clientIds 1, 77 and 82,
    then cancelled first try from 93, the id that placed it. The operator's next move is
    to reconnect as that client, so the failure has to say which one it was.
    """
    trade = _CancelTrade(10)
    trade.order.clientId = 93
    fake = _CancelIB([trade])
    fake.cancelOrder = lambda order: None      # refused

    with caplog.at_level("ERROR"):
        assert _cancel_broker(fake).cancel_order("10") is False
    assert "93" in caplog.text, (
        f"failure must name the clientId that owns the order; got {caplog.text!r}"
    )


def test_ca5_cancel_that_takes_effect_returns_true():
    trade = _CancelTrade(10)
    fake = _CancelIB([trade])

    def _cancel(order):
        trade._done = True                     # broker acknowledges: order is done
    fake.cancelOrder = _cancel
    assert _cancel_broker(fake).cancel_order("10") is True


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
    pass


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


def test_ws5_pendingsubmit_is_not_a_working_stop():
    """An order IBKR refused can sit at PendingSubmit forever.

    Excluding only the dead statuses lets it count as protection, which is how B4 and
    the end-of-session audit would both report a naked position as covered — live
    2026-08-06, after IBKR rejected two stops with code 110.
    """
    fake = _StopsIB([_StopTrade("M2K", 14, status="PendingSubmit")])
    assert _cancel_broker(fake).get_working_stops() == {}, (
        "PendingSubmit is not confirmation that IBKR holds the order"
    )


def test_ws6_has_working_stop_ignores_pendingsubmit_too():
    fake = _StopsIB([_StopTrade("M2K", 14, status="PendingSubmit")])
    assert _cancel_broker(fake).has_working_stop("M2K") is False


# ── stop prices must land on the contract's tick grid ────────────────────────
#
# IBKR rejects an off-tick price with code 110, "The price does not conform to the
# minimum price variation for this contract". This is what actually killed the stops on
# 2026-08-05: the chandelier levels 7758.86 (MES, tick 0.25), 54708.68 (MYM, tick 1.0)
# and 3038.44 (M2K, tick 0.1) are all off-grid, so IBKR refused all three — and
# place_stop reported success because it never looked.
#
# Rounding is away from the market, never toward it: a LONG stop sits below market and
# rounds down, a SHORT stop sits above and rounds up. Rounding the other way would
# tighten a stop the sizing never agreed to, and could push it through the market.


def _rt(inst, direction, price):
    broker = IBKRBroker(_raw_fetcher=lambda i, t: None)
    return broker._round_stop_to_tick(inst, direction, price)


def test_tk1_mym_short_rounds_up_to_whole_point():
    """MYM tick is 1.0; 54708.68 is off-grid and was refused live."""
    assert _rt("MYM", "SHORT", 54708.68) == pytest.approx(54709.0)


def test_tk2_m2k_short_rounds_up_to_tenth():
    assert _rt("M2K", "SHORT", 3038.44) == pytest.approx(3038.5)


def test_tk3_mes_long_rounds_down_to_quarter():
    """LONG stops sit below market — round down, so the stop never tightens."""
    assert _rt("MES", "LONG", 7758.86) == pytest.approx(7758.75)


def test_tk4_short_long_round_opposite_ways():
    """Same off-grid price, opposite directions, opposite rounding."""
    assert _rt("MES", "LONG", 5000.10) == pytest.approx(5000.00)
    assert _rt("MES", "SHORT", 5000.10) == pytest.approx(5000.25)


def test_tk5_on_grid_price_is_unchanged():
    assert _rt("MES", "LONG", 5000.25) == pytest.approx(5000.25)
    assert _rt("MYM", "SHORT", 54709.0) == pytest.approx(54709.0)


def test_tk6_unknown_instrument_passes_through():
    """No tick on record → send what we were given rather than invent a grid."""
    assert _rt("ZZZ", "LONG", 123.456) == pytest.approx(123.456)


# ── the cache is not the broker: stale entries must not read as working ──────
#
# ib_insync keeps every trade it has ever seen in wrapper.trades, and openTrades()
# filters that cache by status. IBKR only pushes status updates to the client that
# owns an order, so a cross-client order that fills is never marked done and stays in
# openTrades() forever. reqAllOpenOrders() RETURNS the authoritative list — its own
# docstring warns that other clients' orders "will not be kept in sync".
#
# Live 2026-08-06: M2K stop #14 filled at 08:11 and the dashboard backend still showed
# it PreSubmitted at 08:27. A naked position would have rendered as protected.


def test_ws7_stale_cached_stop_is_not_working():
    live = _StopTrade("MES", 9)
    stale = _StopTrade("M2K", 14)        # filled at IBKR; only the cache still has it
    working = _cancel_broker(_StopsIB([live], stale=[stale])).get_working_stops()

    assert working == {"MES": "9"}, (
        f"openTrades() keeps filled cross-client orders forever — the authoritative "
        f"list is what reqAllOpenOrders returns. got {working}"
    )


def test_ws8_has_working_stop_ignores_the_stale_cache():
    live = _StopTrade("MES", 9)
    stale = _StopTrade("M2K", 14)
    broker = _cancel_broker(_StopsIB([live], stale=[stale]))
    assert broker.has_working_stop("M2K") is False
    assert broker.has_working_stop("MES") is True


def test_gs3_stale_cached_order_reads_not_found():
    """B3 asks this to tell 'stop still live' from 'stop gone'. A cached ghost would
    answer PENDING and stall the reconcile it exists to resolve."""
    live = _StatusTrade(9, "PreSubmitted")
    stale = _StatusTrade(14, "PreSubmitted")
    broker = _cancel_broker(_StatusIB([live], stale=[stale]))
    assert broker.get_order_status("14") == "NOT_FOUND"
    assert broker.get_order_status("9") == "PENDING"


def test_ca7_cannot_cancel_an_order_that_only_the_cache_believes_in():
    stale = _CancelTrade(14)
    fake = _CancelIB([], stale=[stale])
    assert _cancel_broker(fake).cancel_order("14") is False
    assert fake.cancelled == [], "must not send a cancel for an order IBKR no longer has"


# ── a correct stop does not cancel out a dangerous one ───────────────────────
#
# Live 2026-08-06: MYM ended up holding BUY #12 (correct) and SELL #10 (left over from
# an earlier LONG, never successfully cancelled). classify reported OK because a
# protective stop existed, and the tool printed "PASS — every position protected"
# while a stop that would double the short sat live at the broker.


def test_cl1_wrong_side_stop_is_reported_even_when_protected():
    from global_index.check_open_orders import classify

    positions = [{"inst": "MYM", "direction": "SHORT", "stop_price": 54709.0}]
    stops = {"MYM": [("BUY", 12, 54709.0), ("SELL", 10, 53290.0)]}

    verdicts = {r[0] for r in classify(positions, stops)}
    assert "HAZARD" in verdicts, (
        "a live SELL stop under a SHORT position would add to it — that must be "
        f"reported even though a correct BUY stop also exists. got {verdicts}"
    )


def test_cl2_clean_position_is_just_ok():
    from global_index.check_open_orders import classify

    positions = [{"inst": "MYM", "direction": "SHORT", "stop_price": 54709.0}]
    stops = {"MYM": [("BUY", 12, 54709.0)]}
    assert [r[0] for r in classify(positions, stops)] == ["OK"]


# ── a skipped position still needs its recorded order id corrected ───────────
#
# repair_stops left stop_order_id alone whenever a position was already protected.
# On 2026-08-05 MES carried the fabricated id 62 and a real working stop #9; the
# repair skipped it, so 62 stayed on file. When MES closed on 2026-08-06 the runner
# dutifully tried to cancel 62, failed, raised STP ORPHAN naming 62 — and #9 was left
# working with no position behind it, which is the order that would have opened a
# short if MES had fallen far enough.


def test_id1_records_the_stop_that_is_actually_working():
    from global_index.repair_stops import id_corrections

    positions = [{"inst": "MES", "direction": "LONG", "stop_order_id": "62"}]
    stops = {"MES": [("SELL", 9, 7627.25)]}
    assert id_corrections(positions, stops) == {"MES": "9"}


def test_id2_silent_when_the_recorded_id_is_already_right():
    from global_index.repair_stops import id_corrections

    positions = [{"inst": "MYM", "direction": "SHORT", "stop_order_id": "12"}]
    stops = {"MYM": [("BUY", 12, 54709.0)]}
    assert id_corrections(positions, stops) == {}


def test_id3_never_records_a_wrong_side_stop_as_protection():
    """Recording it would make the runner treat a position-doubling order as its stop."""
    from global_index.repair_stops import id_corrections

    positions = [{"inst": "MYM", "direction": "SHORT", "stop_order_id": None}]
    stops = {"MYM": [("SELL", 10, 53290.0)]}
    assert id_corrections(positions, stops) == {}


def test_id4_fills_in_a_missing_id():
    from global_index.repair_stops import id_corrections

    positions = [{"inst": "M2K", "direction": "SHORT", "stop_order_id": None}]
    stops = {"M2K": [("BUY", 100, 3020.10)]}
    assert id_corrections(positions, stops) == {"M2K": "100"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
