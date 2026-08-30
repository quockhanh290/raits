"""Stage 5Y — the broker write path now returns an order id, and legacy did not move.

Fake brokers only. Nothing connects, nothing orders, every journal lives under tmp_path.

Half of this suite is about the change and half is about everything that must NOT have
changed: `Fill` gained a field, `send_order` gained a keyword, and both were done in the one
shape that leaves every caller written before today untouched.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest

from global_index import track1_broker_read as BR
from global_index import track1_order_journal as J
from global_index import track1_order_state as S
from global_index import track1_paper_executor as X
from global_index import track1_signal_layer as T
from global_index.broker import (Broker, Fill, MockBroker, Order, OrderReceipt,
                                 OrderReceiptRefused)

REPO = Path(__file__).resolve().parents[1]
DAY = "20260825"


# ── fakes ────────────────────────────────────────────────────────────────────

class ArmedGate:
    allow_orders = True


class RecordingBroker:
    """Accepts the receipt keyword and behaves exactly as instructed."""

    def __init__(self, *, order_id="55", fill_status="FILLED", filled_qty=2,
                 fill_order_id=..., raise_after_receipt=None, raise_before_receipt=None):
        self.order_id = order_id
        self.fill_status, self.filled_qty = fill_status, filled_qty
        self._fill_order_id = fill_order_id
        self._after, self._before = raise_after_receipt, raise_before_receipt
        self.receipts: list = []

    def send_order(self, order, *, on_submit=None):
        if self._before is not None:
            raise self._before
        if on_submit is not None and self.order_id is not None:
            r = OrderReceipt(order_id=self.order_id, inst=order.inst, action=order.action,
                             contracts=order.contracts)
            self.receipts.append(r)
            on_submit(r)
        if self._after is not None:
            raise self._after
        oid = self.order_id if self._fill_order_id is ... else self._fill_order_id
        return Fill(order.inst, order.action, order.direction, order.contracts,
                    order.cluster, status=self.fill_status, filled_qty=self.filled_qty,
                    avg_price=20100.25, order_id=oid)

    def get_positions(self): return []
    def get_order_status(self, order_id): return "PENDING"
    def cancel_order(self, order_id): return True
    def place_stop(self, *a, **k): return ""


class OldBroker:
    """A broker written before Stage 5Y: `send_order(order)` and nothing else."""

    def send_order(self, order):
        return Fill(order.inst, order.action, order.direction, order.contracts,
                    order.cluster, status="FILLED", filled_qty=order.contracts)

    def get_positions(self): return []
    def get_order_status(self, order_id): return "PENDING"
    def cancel_order(self, order_id): return True
    def place_stop(self, *a, **k): return ""


def cand(inst="MNQ", sleeve="roska4_stress", qty=2, tid="t1"):
    return T.Candidate(trade_id=tid, sleeve=sleeve, instrument=inst, direction="long",
                       qty=qty, risk_dollars=250.0, entry_time="2026-08-25 10:35:00", meta={})


def took(c=None):
    return T.Decision(candidate=c or cand(), verdict=T.TAKE)


def ex(tmp_path, broker):
    import datetime as dt
    return X.Track1OrderExecutor(broker=broker, gate=ArmedGate(), journal_root=tmp_path,
                                 now_fn=lambda: dt.datetime(2026, 8, 25, 14, 35))


def rows(tmp_path, day=DAY):
    recs, invalid = J.read(root=tmp_path, day=day)
    assert not invalid, invalid
    return recs


# ══════════════════════════════════════════════════════════════════════════════
# 1. the shape of the change — additive, and provably so
# ══════════════════════════════════════════════════════════════════════════════

def test_1_order_id_is_the_LAST_field_and_defaults_to_None():
    fields = dataclasses.fields(Fill)
    assert fields[-1].name == "order_id"
    assert fields[-1].default is None, (
        "an empty string would read as an id; None means the order never reached a broker "
        "or the broker cannot say")


def test_2_every_legacy_construction_shape_still_works():
    """Positional, keyword, and the mixed form the runner uses."""
    a = Fill("MNQ", "OPEN", "long", 1, "roska4_stress")
    b = Fill("MNQ", "OPEN", "long", 1, "roska4_stress", 0.0, "FILLED", 1, 20100.0)
    c = Fill(inst="MNQ", action="CLOSE", direction="long", contracts=1,
             cluster="roska4_stress", pnl_sized=12.5, status="FILLED")
    assert (a.order_id, b.order_id, c.order_id) == (None, None, None)


def test_3_the_contract_month_normaliser_still_runs():
    """__post_init__ predates this change and must not have been disturbed."""
    assert Fill("MNQ", "OPEN", "long", 1, "c", contract_month="20260911").contract_month \
        == "202609"


def test_4_on_submit_is_keyword_only_with_a_default_everywhere():
    from global_index.ibkr_broker import IBKRBroker
    for owner in (Broker, MockBroker, IBKRBroker):
        p = inspect.signature(owner.send_order).parameters["on_submit"]
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, owner.__name__
        assert p.default is None, owner.__name__


def test_5_a_pre_5Y_caller_shape_still_satisfies_every_implementation():
    """`broker.send_order(order)` — the form used at 6 sites in runner.py and 2 in
    track1_switch.py — must still bind."""
    from global_index.ibkr_broker import IBKRBroker
    order = Order(inst="MNQ", action="OPEN", direction="long", contracts=1,
                  cluster="roska4_stress", ref_day="2026-08-25")
    for owner in (MockBroker, IBKRBroker):
        inspect.signature(owner.send_order).bind(object(), order)


def test_6_MockBroker_still_returns_a_Fill_and_now_names_it():
    m = MockBroker({}, 100000.0)
    f = m.send_order(Order(inst="MNQ", action="OPEN", direction="long", contracts=1,
                           cluster="roska4_stress", ref_day="2026-08-25"))
    assert f.status == "FILLED" and f.order_id == "mock-1"
    assert m.fills == [f], "MockBroker's fills list is what the verify path reads"


def test_7_MockBroker_ids_are_visibly_synthetic():
    """So one can never be mistaken for something IBKR issued if it reaches a log."""
    m = MockBroker({}, 100000.0)
    o = Order(inst="MNQ", action="OPEN", direction="long", contracts=1,
              cluster="roska4_stress", ref_day="2026-08-25")
    assert [m.send_order(o).order_id for _ in range(3)] == ["mock-1", "mock-2", "mock-3"]


def test_8_MockBroker_fires_the_receipt_when_asked_and_not_otherwise():
    seen = []
    m = MockBroker({}, 100000.0)
    o = Order(inst="MNQ", action="OPEN", direction="long", contracts=1,
              cluster="roska4_stress", ref_day="2026-08-25")
    m.send_order(o)
    assert seen == []
    m.send_order(o, on_submit=seen.append)
    assert len(seen) == 1 and seen[0].order_id == "mock-2"


# ══════════════════════════════════════════════════════════════════════════════
# 2. IBKRBroker.send_order, read from the file
# ══════════════════════════════════════════════════════════════════════════════

def _send_order_ast():
    src = (REPO / "global_index/ibkr_broker.py").read_text(encoding="utf-8")
    cls = next(n for n in ast.parse(src).body
               if isinstance(n, ast.ClassDef) and n.name == "IBKRBroker")
    return next(n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == "send_order")


def test_9_every_post_placement_Fill_carries_the_order_id():
    """Seven of eight. The eighth is test mode, which places nothing."""
    fn = _send_order_ast()
    fills = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "Fill"]
    assert len(fills) == 8, len(fills)
    without = [f.lineno for f in fills
               if not any(k.arg == "order_id" for k in f.keywords)]
    assert len(without) == 1, f"post-placement Fills missing an id: {without}"


def test_10_test_mode_invents_no_id_and_fires_no_receipt():
    """A fabricated identifier in a journal is worse than none: a reconcile trusts it."""
    fn = _send_order_ast()
    guard = next(n for n in fn.body if isinstance(n, ast.If))
    assert "_raw_fetcher" in ast.dump(guard.test)
    calls = [n for n in ast.walk(guard) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "OrderReceipt"]
    assert calls == []
    fill = next(n for n in ast.walk(guard) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "Fill")
    assert not any(k.arg == "order_id" for k in fill.keywords)


def test_11_the_receipt_fires_BEFORE_the_fill_poll():
    """The 30-second poll is the window this exists to close. After it would be useless."""
    fn = _send_order_ast()
    receipt = min(n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Name) and n.func.id == "OrderReceipt")
    poll = min(n.lineno for n in ast.walk(fn) if isinstance(n, ast.While))
    place = min(n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == "placeOrder")
    assert place < receipt < poll, (place, receipt, poll)


def test_12_a_refused_receipt_is_re_raised_not_turned_into_a_cancelled_fill():
    """The worst available answer would be to report a LIVE order as cancelled."""
    fn = _send_order_ast()
    reraise = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)
               and any(isinstance(b, ast.Raise) and b.exc is None for b in h.body)]
    assert reraise, "no bare re-raise handler survives in send_order"
    names = set()
    for h in reraise:
        t = h.type
        for part in (t.elts if isinstance(t, ast.Tuple) else [t]):
            if isinstance(part, ast.Name):
                names.add(part.id)
    assert "OrderReceiptRefused" in names, sorted(names)
    assert "IBKRConnectionError" in names, sorted(names)


def test_13_the_except_path_separates_placed_from_never_placed():
    """The one change that adds information rather than a field: an exception after
    placement leaves live exposure, and before it does not."""
    src = (REPO / "global_index/ibkr_broker.py").read_text(encoding="utf-8")
    assert "trade = None      # bound only once placeOrder returns" in src
    assert "placed = trade is not None" in src


def test_14_OrderReceiptRefused_is_not_an_IBKR_specific_type():
    """It lives in broker.py so any broker implementation can honour the same contract."""
    import global_index.broker as b
    assert getattr(b, "OrderReceiptRefused", None) is OrderReceiptRefused
    assert issubclass(OrderReceiptRefused, RuntimeError)


# ══════════════════════════════════════════════════════════════════════════════
# 3. the journal: the amendment
# ══════════════════════════════════════════════════════════════════════════════

def test_15_a_fill_journals_intended_submitted_amended_then_filled(tmp_path):
    ex(tmp_path, RecordingBroker()).open_position(took(), ref_day="2026-08-25")
    r = rows(tmp_path)
    assert [x.state for x in r] == [S.INTENDED, S.SUBMITTED, S.SUBMITTED, S.FILLED]
    assert [x.order_id for x in r] == ["", "", "55", "55"]


def test_16_the_first_SUBMITTED_row_still_has_no_id_because_it_precedes_the_call(tmp_path):
    """Not a gap. The ordering the journal commits to makes it impossible for it to."""
    ex(tmp_path, RecordingBroker()).open_position(took(), ref_day="2026-08-25")
    assert rows(tmp_path)[1].order_id == ""


def test_17_the_amendment_is_written_while_send_order_is_still_in_flight(tmp_path):
    """Proved from inside the call, like the SUBMITTED ordering in Stage 5W."""
    seen = {}

    class Watcher(RecordingBroker):
        def send_order(self, order, *, on_submit=None):
            out = super().send_order(order, on_submit=on_submit)
            seen["states"] = [x.state for x in rows(tmp_path)]
            seen["ids"] = [x.order_id for x in rows(tmp_path)]
            return out

    ex(tmp_path, Watcher()).open_position(took(), ref_day="2026-08-25")
    assert seen["states"] == [S.INTENDED, S.SUBMITTED, S.SUBMITTED]
    assert seen["ids"][-1] == "55", "the id was not durable before the call returned"


def test_18_an_amendment_that_adds_no_id_is_refused(tmp_path):
    """Otherwise a genuine duplicate send would look like a legal history."""
    r = J.JournalRecord(idempotency_key="k", state=S.INTENDED, ref_day="2026-08-25",
                        sleeve="s", instrument="MNQ", tradable_symbol="MNQ", action="OPEN",
                        candidate_id="t", created_at="x")
    J.append(r, root=tmp_path, day=DAY)
    J.append(dataclasses.replace(r, state=S.SUBMITTED), root=tmp_path, day=DAY)
    with pytest.raises(J.OrderJournalRefused) as e:
        J.append(dataclasses.replace(r, state=S.SUBMITTED), root=tmp_path, day=DAY)
    assert e.value.code == J.BAD_AMENDMENT


def test_19_an_id_may_never_be_replaced(tmp_path):
    """Two ids under one key are two orders."""
    r = J.JournalRecord(idempotency_key="k", state=S.INTENDED, ref_day="2026-08-25",
                        sleeve="s", instrument="MNQ", tradable_symbol="MNQ", action="OPEN",
                        candidate_id="t", created_at="x")
    J.append(r, root=tmp_path, day=DAY)
    J.append(dataclasses.replace(r, state=S.SUBMITTED), root=tmp_path, day=DAY)
    J.append(dataclasses.replace(r, state=S.SUBMITTED, order_id="55"), root=tmp_path, day=DAY)
    with pytest.raises(J.OrderJournalRefused) as e:
        J.append(dataclasses.replace(r, state=S.SUBMITTED, order_id="66"),
                 root=tmp_path, day=DAY)
    assert e.value.code == J.BAD_AMENDMENT
    assert "two orders" in e.value.detail


def test_20_an_amendment_may_not_move_anything_else(tmp_path):
    r = J.JournalRecord(idempotency_key="k", state=S.INTENDED, ref_day="2026-08-25",
                        sleeve="s", instrument="MNQ", tradable_symbol="MNQ", action="OPEN",
                        candidate_id="t", created_at="x")
    J.append(r, root=tmp_path, day=DAY)
    J.append(dataclasses.replace(r, state=S.SUBMITTED), root=tmp_path, day=DAY)
    with pytest.raises(J.OrderJournalRefused) as e:
        J.append(dataclasses.replace(r, state=S.SUBMITTED, order_id="55",
                                     instrument="MES"), root=tmp_path, day=DAY)
    assert e.value.code == J.BAD_AMENDMENT
    assert "instrument" in e.value.detail


def test_21_the_state_machine_still_forbids_submitted_to_submitted():
    """The amendment is a journal-level exception, deliberately NOT a new transition."""
    assert not S.transition_allowed(S.SUBMITTED, S.SUBMITTED)


@pytest.mark.parametrize("bad", [S.INTENDED, S.FILLED])
def test_22_no_other_self_transition_was_opened(tmp_path, bad):
    r = J.JournalRecord(idempotency_key="k", state=S.INTENDED, ref_day="2026-08-25",
                        sleeve="s", instrument="MNQ", tradable_symbol="MNQ", action="OPEN",
                        candidate_id="t", created_at="x")
    J.append(r, root=tmp_path, day=DAY)
    if bad is S.FILLED:
        J.append(dataclasses.replace(r, state=S.SUBMITTED), root=tmp_path, day=DAY)
        J.append(dataclasses.replace(r, state=S.FILLED), root=tmp_path, day=DAY)
    with pytest.raises(J.OrderJournalRefused) as e:
        J.append(dataclasses.replace(r, state=bad, order_id="55"), root=tmp_path, day=DAY)
    assert e.value.code == J.BAD_TRANSITION


# ══════════════════════════════════════════════════════════════════════════════
# 4. every outcome
# ══════════════════════════════════════════════════════════════════════════════

def test_23_a_partial_fill_carries_the_id(tmp_path):
    ex(tmp_path, RecordingBroker(fill_status="PARTIAL", filled_qty=1)).open_position(
        took(), ref_day="2026-08-25")
    last = rows(tmp_path)[-1]
    assert last.state == S.PARTIAL and last.order_id == "55"


def test_24_a_rejection_carries_the_id(tmp_path):
    ex(tmp_path, RecordingBroker(fill_status="CANCELLED")).open_position(
        took(), ref_day="2026-08-25")
    last = rows(tmp_path)[-1]
    assert last.state == S.REJECTED and last.order_id == "55"


def test_25_an_unclassifiable_status_is_UNKNOWN_and_still_carries_the_id(tmp_path):
    ex(tmp_path, RecordingBroker(fill_status="PendingSubmit")).open_position(
        took(), ref_day="2026-08-25")
    last = rows(tmp_path)[-1]
    assert last.state == S.UNKNOWN and last.order_id == "55"


def test_26_an_exception_AFTER_the_receipt_records_UNKNOWN_WITH_the_id(tmp_path):
    """The case the whole stage is for: the order is live and we can name it."""
    e = ex(tmp_path, RecordingBroker(raise_after_receipt=TimeoutError("no reply")))
    with pytest.raises(TimeoutError):
        e.open_position(took(), ref_day="2026-08-25")
    r = rows(tmp_path)
    assert [x.state for x in r] == [S.INTENDED, S.SUBMITTED, S.SUBMITTED, S.UNKNOWN]
    assert r[-1].order_id == "55"


def test_27_an_exception_BEFORE_the_receipt_records_UNKNOWN_with_NO_id(tmp_path):
    """Still UNKNOWN. Never REJECTED, and never a fabricated id."""
    e = ex(tmp_path, RecordingBroker(raise_before_receipt=ConnectionResetError("gone")))
    with pytest.raises(ConnectionResetError):
        e.open_position(took(), ref_day="2026-08-25")
    r = rows(tmp_path)
    assert [x.state for x in r] == [S.INTENDED, S.SUBMITTED, S.UNKNOWN]
    assert r[-1].order_id == ""


def test_28_a_broker_that_names_nothing_still_works_and_says_nothing(tmp_path):
    """Task 4: UNKNOWN remains UNKNOWN if the broker id cannot be obtained."""
    ex(tmp_path, RecordingBroker(order_id=None, fill_order_id=None)).open_position(
        took(), ref_day="2026-08-25")
    r = rows(tmp_path)
    assert [x.state for x in r] == [S.INTENDED, S.SUBMITTED, S.FILLED]
    assert all(x.order_id == "" for x in r)


def test_29_a_pre_5Y_broker_is_driven_without_the_keyword(tmp_path):
    """`accepts_receipt` is measured from the signature, not assumed."""
    b = OldBroker()
    assert X.accepts_receipt(b) is False
    ex(tmp_path, b).open_position(took(), ref_day="2026-08-25")
    r = rows(tmp_path)
    assert [x.state for x in r] == [S.INTENDED, S.SUBMITTED, S.FILLED]
    assert all(x.order_id == "" for x in r)


def test_30_the_receipt_id_survives_a_Fill_that_forgot_it(tmp_path):
    """A broker may report early and then hand back a Fill with no id. The earlier,
    durable answer is the one that stands."""
    ex(tmp_path, RecordingBroker(fill_order_id=None)).open_position(
        took(), ref_day="2026-08-25")
    assert rows(tmp_path)[-1].order_id == "55"


def test_31_an_empty_receipt_id_writes_no_amendment(tmp_path):
    """An amendment that adds nothing would be refused by the journal, so it is not
    attempted. The executor must not manufacture a row it knows is unlawful."""
    ex(tmp_path, RecordingBroker(order_id="", fill_order_id="")).open_position(
        took(), ref_day="2026-08-25")
    assert [x.state for x in rows(tmp_path)] == [S.INTENDED, S.SUBMITTED, S.FILLED]


# ══════════════════════════════════════════════════════════════════════════════
# 5. the read side prefers the id
# ══════════════════════════════════════════════════════════════════════════════

def rec(order_id="", instrument="MNQ", action="OPEN", qty=2):
    return J.JournalRecord(
        idempotency_key="k1", state=S.SUBMITTED, ref_day="2026-08-25",
        sleeve="roska4_stress", instrument=instrument, tradable_symbol="MNQ",
        action=action, candidate_id="t1", created_at="x", order_id=order_id,
        filled_qty=qty)


class ReadBroker:
    CAN_TESTIFY = True

    def __init__(self, open_orders=(), status="PENDING", execution=None):
        self._oo, self._st, self._ex = open_orders, status, execution

    def get_positions(self): return []
    def get_open_orders(self): return self._oo
    def get_order_status(self, order_id): return self._st
    def find_execution(self, order_id, inst=None): return self._ex


def test_32_a_working_order_is_matched_by_id_when_both_sides_have_one():
    v = BR.resolve_submitted(rec(order_id="55"), BR.Track1BrokerReader(
        ReadBroker(open_orders=[{"order_id": "55", "instrument": "MNQ", "action": "OPEN"}])))
    assert v.resolution == BR.STILL_WORKING
    assert v.evidence["matched_by"] == BR.BY_ORDER_ID


def test_33_a_DIFFERENT_id_is_not_ours_and_the_weaker_match_is_not_consulted():
    """The failure the id was added to remove: another order on the same contract,
    same action, different id. Instrument-and-action would have claimed it."""
    v = BR.resolve_submitted(rec(order_id="55"), BR.Track1BrokerReader(
        ReadBroker(open_orders=[{"order_id": "99", "instrument": "MNQ", "action": "OPEN"}],
                   status=BR.STATUS_NOT_FOUND)))
    assert v.resolution != BR.STILL_WORKING
    assert v.evidence["matched_by"] == BR.NOT_MATCHED


def test_34_without_an_id_the_stage_5X_fallback_still_applies():
    v = BR.resolve_submitted(rec(order_id=""), BR.Track1BrokerReader(
        ReadBroker(open_orders=[{"instrument": "MNQ", "action": "OPEN"}])))
    assert v.resolution == BR.STILL_WORKING
    assert v.evidence["matched_by"] == BR.BY_INSTRUMENT_ACTION


def test_35_the_fallback_still_refuses_a_stop_on_the_same_contract():
    v = BR.resolve_submitted(rec(order_id=""), BR.Track1BrokerReader(
        ReadBroker(open_orders=[{"instrument": "MNQ", "action": "CLOSE"}],
                   status=BR.STATUS_NOT_FOUND)))
    assert v.resolution != BR.STILL_WORKING


def test_36_the_evidence_says_which_route_was_taken():
    with_id = BR.resolve_submitted(rec(order_id="55"),
                                   BR.Track1BrokerReader(ReadBroker(open_orders=[])))
    without = BR.resolve_submitted(rec(order_id=""),
                                   BR.Track1BrokerReader(ReadBroker(open_orders=[])))
    assert with_id.evidence["identified_by"] == BR.BY_ORDER_ID
    assert without.evidence["identified_by"] == BR.BY_INSTRUMENT_ACTION


def test_37_no_id_means_the_status_lookup_is_UNKNOWN_and_says_why():
    v = BR.resolve_submitted(rec(order_id=""),
                             BR.Track1BrokerReader(ReadBroker(open_orders=[])))
    assert v.resolution == BR.RESOLVED_UNKNOWN
    assert "weaker on purpose" in v.evidence["order_status"]


def test_38_an_id_makes_a_filled_order_resolvable_end_to_end():
    v = BR.resolve_submitted(rec(order_id="55", qty=2), BR.Track1BrokerReader(
        ReadBroker(open_orders=[], status="FILLED",
                   execution={"shares": 2, "price": 20100.0})))
    assert v.resolution == BR.RESOLVED_FILLED and not v.blocks_entries


def test_39_positions_are_still_last_and_never_decisive():
    v = BR.resolve_submitted(rec(order_id="55"), BR.Track1BrokerReader(
        ReadBroker(open_orders=[], status=BR.STATUS_NOT_FOUND)))
    assert v.resolution == BR.RESOLVED_UNKNOWN
    assert "positions" in v.evidence


# ── exits, unchanged ─────────────────────────────────────────────────────────

def test_40_a_reducing_exit_is_still_allowed_under_UNKNOWN():
    ok, _ = BR.exit_allowed(verdict_or_resolution=BR.RESOLVED_UNKNOWN,
                            reduces_exposure=True)
    assert ok


def test_41_an_oversized_close_is_still_blocked():
    ok, why = BR.exit_allowed(verdict_or_resolution=BR.RESOLVED_UNKNOWN,
                              reduces_exposure=False)
    assert not ok and "opens the opposite side" in why


def test_42_the_same_holds_under_MISMATCH():
    assert BR.exit_allowed(verdict_or_resolution=S.MISMATCH, reduces_exposure=True)[0]
    assert not BR.exit_allowed(verdict_or_resolution=S.MISMATCH,
                               reduces_exposure=False)[0]


# ══════════════════════════════════════════════════════════════════════════════
# 6. legacy callers did not move
# ══════════════════════════════════════════════════════════════════════════════

def test_43_no_legacy_caller_passes_the_new_keyword():
    """`runner.py`, `track1_switch.py` and the connect scripts call `send_order(order)`.
    If one of them started passing `on_submit`, that is a behaviour change to review."""
    callers = []
    for d in ("global_index", "futures", "monitor"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.name in ("broker.py", "ibkr_broker.py", "track1_paper_executor.py"):
                continue
            # A file that will not parse is NOT a file with no callers. Mutation M17
            # produced exactly that: an unparseable runner.py was skipped and this test
            # passed while a legacy call site had changed. Same shape as answering "I
            # could not read it" with "there is nothing there".
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError as exc:
                callers.append(f"{p.name}: UNPARSEABLE ({exc})")
                continue
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "send_order"
                        and any(k.arg == "on_submit" for k in n.keywords)):
                    callers.append(f"{p.name}:{n.lineno}")
    assert callers == [], callers


def test_44_the_legacy_runner_still_calls_send_order_with_one_argument():
    src = (REPO / "global_index/runner.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "send_order"]
    assert len(calls) >= 6, len(calls)
    assert all(len(c.args) == 1 and not c.keywords for c in calls)


def test_45_track1_switch_was_not_changed_by_this_stage():
    src = (REPO / "global_index/track1_switch.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "send_order"]
    assert len(calls) == 2 and all(not c.keywords for c in calls)


def test_46_nothing_outside_the_broker_files_constructs_an_OrderReceipt():
    hits = []
    for d in ("global_index", "futures", "monitor"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.name in ("broker.py", "ibkr_broker.py"):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            hits += [p.name for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id == "OrderReceipt"]
    assert hits == [], hits


# ══════════════════════════════════════════════════════════════════════════════
# 7. orders are still impossible
# ══════════════════════════════════════════════════════════════════════════════

def test_47_the_executor_is_still_imported_by_nothing():
    hits = []
    for d in ("global_index", "monitor", "futures"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.stem in ("track1_paper_executor", "track1_broker_read",
                          "track1_paper_callsite"):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if not isinstance(n, (ast.Import, ast.ImportFrom)):
                    continue
                mod = getattr(n, "module", "") or ""
                names = [a.name for a in n.names]
                for target in ("track1_paper_executor", "track1_broker_read"):
                    if target in mod or any(target in nm for nm in names):
                        hits.append(f"{p.name} -> {target}")
    assert hits == [], hits
    # and the one module that imports them all is imported by nothing
    head = []
    for p in (REPO / "global_index").rglob("*.py"):
        if p.stem == "track1_paper_callsite":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            head.append(f"{p.name}: UNPARSEABLE")
            continue
        for n in ast.walk(tree):
            if not isinstance(n, (ast.Import, ast.ImportFrom)):
                continue
            mod = getattr(n, "module", "") or ""
            if "track1_paper_callsite" in mod or any(
                    "track1_paper_callsite" in a.name for a in n.names):
                head.append(p.name)
    assert head == [], head



def test_48_run_shadow_still_builds_a_NoOrderBroker():
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "run_shadow")
    built = [n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id.endswith("Broker")]
    assert built == ["NoOrderBroker"], built


def test_49_orders_are_still_impossible():
    import os
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    assert "B1_broker_account_or_legacy_retirement" in ids
    assert "PAPER_SHADOW_EVIDENCE" in ids
    assert not (REPO / G.CONFIRMATION_PATH).exists()
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")


def test_50_no_caller_passes_allow_orders():
    for rel in ("global_index/run_scheduler.py", "monitor/ops.py"):
        p = REPO / rel
        if not p.exists():
            continue
        lits = [n for n in ast.walk(ast.parse(p.read_text(encoding="utf-8",
                                                          errors="replace")))
                if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
        assert lits == [], rel


def test_51_this_suite_created_no_runtime_orders_directory():
    assert not (REPO / J.ORDERS_DIR).exists()


# ══════════════════════════════════════════════════════════════════════════════
# 8. the amendment must survive READ-BACK, not just the write
# ══════════════════════════════════════════════════════════════════════════════
#
# These exist because the first version of this stage shipped without them and was broken:
# `append` accepted the amendment and `resolve` then called the resulting journal an
# impossible history, so every order that successfully got an id made that day's journal
# unreadable. Fifty-two tests passed. All of them checked the write; none re-read.

def test_52_a_journal_containing_an_amendment_still_resolves(tmp_path):
    ex(tmp_path, RecordingBroker()).open_position(took(), ref_day="2026-08-25")
    res = J.resolve(root=tmp_path, day=DAY)
    assert res["final"] == {list(res["final"])[0]: S.FILLED}
    assert res["unresolved"] == []


def test_53_an_amended_but_unfinished_order_is_still_unresolved(tmp_path):
    e = ex(tmp_path, RecordingBroker(raise_after_receipt=TimeoutError("no reply")))
    with pytest.raises(TimeoutError):
        e.open_position(took(), ref_day="2026-08-25")
    assert len(J.resolve(root=tmp_path, day=DAY)["unresolved"]) == 1


def test_54_the_id_reaches_the_reconcile_view(tmp_path):
    """`as_order_record` maps order_id onto broker_order_id, which is what a restart reads."""
    ex(tmp_path, RecordingBroker()).open_position(took(), ref_day="2026-08-25")
    recs = [r.as_order_record() for r in rows(tmp_path)]
    assert S.resolve_journal(recs)["impossible"] == []
    assert S.resolve_journal(recs)["records"][recs[0].idempotency_key].broker_order_id == "55"


def test_55_the_amendment_rule_has_ONE_definition_used_by_writer_and_reader():
    """The bug was two rules. The writer knew about amendments and the reader did not."""
    assert callable(S.is_amendment)
    src = (REPO / "global_index/track1_order_state.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "resolve_journal")
    assert [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "is_amendment"], (
        "resolve_journal no longer consults the shared rule; a written amendment would be "
        "called an impossible history on read-back")

    jsrc = (REPO / "global_index/track1_order_journal.py").read_text(encoding="utf-8")
    jfn = next(n for n in ast.walk(ast.parse(jsrc))
               if isinstance(n, ast.FunctionDef) and n.name == "_check_amendment")
    assert [n for n in ast.walk(jfn) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "is_amendment"]


def test_56_is_amendment_refuses_everything_that_is_not_one():
    def r(state, oid=""):
        return S.OrderRecord(trade_id="t", sleeve="s", instrument="MNQ",
                             tradable_symbol="MNQ", direction="long", qty=1, state=state,
                             ref_day="2026-08-25", idempotency_key="k",
                             broker_order_id=oid)
    assert S.is_amendment(r(S.SUBMITTED), r(S.SUBMITTED, "55")) is True
    assert S.is_amendment(None, r(S.SUBMITTED, "55")) is False
    assert S.is_amendment(r(S.SUBMITTED), r(S.SUBMITTED)) is False          # adds nothing
    assert S.is_amendment(r(S.SUBMITTED, "55"), r(S.SUBMITTED, "66")) is False  # replaces
    assert S.is_amendment(r(S.INTENDED), r(S.INTENDED, "55")) is False      # wrong state
    assert S.is_amendment(r(S.FILLED, "55"), r(S.FILLED, "66")) is False


def test_57_a_hand_written_double_submitted_with_no_id_is_still_impossible():
    """resolve_journal must not have been loosened into accepting any repeat."""
    def r(oid=""):
        return S.OrderRecord(trade_id="t", sleeve="s", instrument="MNQ",
                             tradable_symbol="MNQ", direction="long", qty=1,
                             state=S.SUBMITTED, ref_day="2026-08-25",
                             idempotency_key="k", broker_order_id=oid)
    assert S.resolve_journal([r(), r()])["impossible"] == ["k: submitted -> submitted"]
    assert S.resolve_journal([r("55"), r("66")])["impossible"] == ["k: submitted -> submitted"]
