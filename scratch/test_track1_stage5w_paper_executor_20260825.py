"""Stage 5W — the paper executor skeleton, and the three walls that keep it out of production.

The module under test is the first Track 1 file that could, in principle, call `send_order`.
So roughly half of these tests are not about what it does but about what cannot reach it, and
they are written to fail if that ever stops being true.

No order is sent, no broker is connected, no runtime file is written. The journal lives in a
tmp_path in every test that writes one.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
from pathlib import Path

import pytest

from global_index import track1_order_journal as J
from global_index import track1_order_state as S
from global_index import track1_paper_executor as X
from global_index import track1_paper_order as PO
from global_index import track1_signal_layer as T
from global_index.broker import Fill

REPO = Path(__file__).resolve().parents[1]
DAY = "20260825"


# ── the smallest honest fakes ────────────────────────────────────────────────

class BrokerBoom(Exception):
    """Bespoke, because OrderJournalRefused subclasses RuntimeError and a broad
    `pytest.raises(RuntimeError)` would be satisfied by the journal refusing
    before the broker was ever reached - caught by mutation M9."""


class ArmedGate:
    """Only a test can produce this. The real gate is checked in test_36."""
    allow_orders = True


class ClosedGate:
    allow_orders = False


class FakeBroker:
    """Has every method the executor demands; only `send_order` does anything."""

    def __init__(self, result=None, raises=None, spy=None):
        self._result, self._raises, self._spy = result, raises, spy
        self.calls = []

    def send_order(self, order):
        if self._spy is not None:
            self._spy(order)          # runs INSIDE the call — used to prove ordering
        self.calls.append(order)
        if self._raises is not None:
            raise self._raises
        return self._result

    def get_positions(self): return []
    def get_order_status(self, *a, **k): return None
    def cancel_order(self, *a, **k): return None
    def place_stop(self, *a, **k): return None


def cand(inst="MNQ", sleeve="roska4_stress", qty=2, tid="t1"):
    return T.Candidate(trade_id=tid, sleeve=sleeve, instrument=inst, direction="long",
                       qty=qty, risk_dollars=250.0, entry_time="2026-08-25 10:35:00", meta={})


def took(c=None):
    return T.Decision(candidate=c or cand(), verdict=T.TAKE)


def fill(status="FILLED", qty=2, price=20100.25):
    return Fill(inst="MNQ", action="OPEN", direction="long", contracts=2,
                cluster="roska4_stress", status=status, filled_qty=qty, avg_price=price)


def ex(tmp_path, broker=None, gate=None):
    return X.Track1OrderExecutor(broker=broker or FakeBroker(result=fill()),
                                 gate=gate or ArmedGate(), journal_root=tmp_path,
                                 now_fn=lambda: dt.datetime(2026, 8, 25, 14, 35))


def states(tmp_path, day=DAY):
    recs, invalid = J.read(root=tmp_path, day=day)
    assert not invalid, invalid
    return [r.state for r in recs]


# ── 1. it cannot be built unarmed ────────────────────────────────────────────

def test_1_construction_refused_without_an_armed_gate(tmp_path):
    with pytest.raises(X.PaperExecutorRefused) as e:
        X.Track1OrderExecutor(broker=FakeBroker(), gate=ClosedGate(), journal_root=tmp_path)
    assert e.value.code == X.NOT_ARMED


def test_2_construction_refused_when_the_gate_has_no_opinion(tmp_path):
    """An object with no `allow_orders` is not 'armed by default'."""
    class Mute:
        pass
    with pytest.raises(X.PaperExecutorRefused) as e:
        X.Track1OrderExecutor(broker=FakeBroker(), gate=Mute(), journal_root=tmp_path)
    assert e.value.code == X.NOT_ARMED


def test_3_construction_refused_when_the_broker_cannot_place_or_query(tmp_path):
    class Half:
        def send_order(self, o): return None
    with pytest.raises(X.PaperExecutorRefused) as e:
        X.Track1OrderExecutor(broker=Half(), gate=ArmedGate(), journal_root=tmp_path)
    assert "get_positions" in e.value.detail


# ── 2. the write-ahead ordering ──────────────────────────────────────────────

def test_4_a_fill_journals_intended_submitted_then_filled_in_that_order(tmp_path):
    ex(tmp_path).open_position(took(), ref_day="2026-08-25", slot_id="s1")
    assert states(tmp_path) == [S.INTENDED, S.SUBMITTED, S.FILLED]


def test_5_submitted_is_on_disk_BEFORE_the_broker_is_called(tmp_path):
    """The single most important ordering claim in the module, proved from inside the call."""
    seen = {}

    def spy(_order):
        seen["states"] = states(tmp_path)

    ex(tmp_path, broker=FakeBroker(result=fill(), spy=spy)).open_position(
        took(), ref_day="2026-08-25")
    assert seen["states"] == [S.INTENDED, S.SUBMITTED], (
        "the broker was reached before the attempt was durable")


def test_6_a_journal_that_will_not_write_stops_the_order_reaching_the_broker(tmp_path,
                                                                            monkeypatch):
    broker = FakeBroker(result=fill())
    e = ex(tmp_path, broker=broker)

    def boom(*a, **k):
        raise J.OrderJournalRefused(J.WRITE_FAILED, "disk full")

    monkeypatch.setattr(J, "append", boom)
    with pytest.raises(J.OrderJournalRefused):
        e.open_position(took(), ref_day="2026-08-25")
    assert broker.calls == [], "an order was sent although its intent was never recorded"


def test_7_the_second_write_failing_also_stops_the_send(tmp_path, monkeypatch):
    """Not just the first. SUBMITTED is a gate too, not a courtesy."""
    broker = FakeBroker(result=fill())
    e = ex(tmp_path, broker=broker)
    real, calls = J.append, {"n": 0}

    def once_then_fail(rec, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise J.OrderJournalRefused(J.WRITE_FAILED, "disk full on the second line")
        return real(rec, **k)

    monkeypatch.setattr(J, "append", once_then_fail)
    with pytest.raises(J.OrderJournalRefused):
        e.open_position(took(), ref_day="2026-08-25")
    assert broker.calls == []
    assert states(tmp_path) == [S.INTENDED]


# ── 3. what a broker answer becomes ──────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    ("FILLED", S.FILLED),
    ("PARTIAL", S.PARTIAL),
    ("CANCELLED", S.REJECTED),
    ("FAILED", S.REJECTED),
    ("REJECTED", S.REJECTED),
])
def test_8_known_statuses_map_to_their_own_state(tmp_path, status, expected):
    ex(tmp_path, broker=FakeBroker(result=fill(status=status))).open_position(
        took(), ref_day="2026-08-25")
    assert states(tmp_path)[-1] == expected


@pytest.mark.parametrize("status", ["", "PendingSubmit", "ApiCancelled", "weird", None])
def test_9_anything_unrecognised_is_UNKNOWN_never_REJECTED(tmp_path, status):
    """'I could not classify that' must not be recorded as 'the broker said no'."""
    f = fill()
    f.status = status
    ex(tmp_path, broker=FakeBroker(result=f)).open_position(took(), ref_day="2026-08-25")
    assert states(tmp_path)[-1] == S.UNKNOWN


def test_10_a_broker_that_raises_leaves_UNKNOWN_and_the_exception_propagates(tmp_path):
    e = ex(tmp_path, broker=FakeBroker(raises=TimeoutError("no reply from TWS")))
    with pytest.raises(TimeoutError):
        e.open_position(took(), ref_day="2026-08-25")
    assert states(tmp_path) == [S.INTENDED, S.SUBMITTED, S.UNKNOWN]


def test_11_the_UNKNOWN_row_says_what_went_wrong(tmp_path):
    e = ex(tmp_path, broker=FakeBroker(raises=TimeoutError("no reply from TWS")))
    with pytest.raises(TimeoutError):
        e.open_position(took(), ref_day="2026-08-25")
    recs, _ = J.read(root=tmp_path, day=DAY)
    assert "TimeoutError" in recs[-1].error and "no reply" in recs[-1].error


def test_12_an_UNKNOWN_order_is_reported_unresolved_to_a_restart(tmp_path):
    e = ex(tmp_path, broker=FakeBroker(raises=TimeoutError("x")))
    with pytest.raises(TimeoutError):
        e.open_position(took(), ref_day="2026-08-25")
    assert len(e.unresolved(day=DAY)) == 1


def test_13_a_filled_order_is_NOT_unresolved(tmp_path):
    e = ex(tmp_path)
    e.open_position(took(), ref_day="2026-08-25")
    assert e.unresolved(day=DAY) == []


# ── 4. refusals happen before anything is written ────────────────────────────

def test_14_a_rejected_candidate_never_reaches_the_journal(tmp_path):
    broker = FakeBroker(result=fill())
    e = ex(tmp_path, broker=broker)
    with pytest.raises(PO.PaperOrderRefused) as err:
        e.open_position(T.Decision(candidate=cand(), verdict=T.REJECT_CAP), ref_day="2026-08-25")
    assert err.value.code == PO.NOT_ADMITTED
    assert broker.calls == []
    assert not (Path(tmp_path) / J.ORDERS_DIR).exists()


def test_15_a_zero_quantity_candidate_never_reaches_the_journal(tmp_path):
    e = ex(tmp_path)
    with pytest.raises(PO.PaperOrderRefused) as err:
        e.open_position(took(cand(qty=0)), ref_day="2026-08-25")
    assert err.value.code == PO.QTY_INVALID
    assert not (Path(tmp_path) / J.ORDERS_DIR).exists()


def test_16_a_missing_ref_day_never_reaches_the_journal(tmp_path):
    e = ex(tmp_path)
    with pytest.raises(PO.PaperOrderRefused) as err:
        e.open_position(took(), ref_day=None)
    assert err.value.code == PO.REF_DAY_MISSING
    assert not (Path(tmp_path) / J.ORDERS_DIR).exists()


def test_17_identity_drift_never_reaches_the_journal(tmp_path, monkeypatch):
    from global_index import ibkr_broker
    monkeypatch.setattr(ibkr_broker, "ibkr_symbol_and_exchange", lambda i: ("NQ", "CME"))
    e = ex(tmp_path)
    with pytest.raises(PO.PaperOrderRefused) as err:
        e.open_position(took(), ref_day="2026-08-25")
    assert err.value.code == PO.IDENTITY_DRIFT
    assert not (Path(tmp_path) / J.ORDERS_DIR).exists()


# ── 5. identity on the record ────────────────────────────────────────────────

def test_18_MNKD_journals_the_runner_name_and_the_ORDER_symbol_side_by_side(tmp_path):
    c = cand(inst="MNKD", sleeve="global_nkd", tid="nkd1")
    ex(tmp_path, broker=FakeBroker(result=fill())).open_position(took(c), ref_day="2026-08-25")
    recs, _ = J.read(root=tmp_path, day=DAY)
    assert {r.instrument for r in recs} == {"MNKD"}
    assert {r.tradable_symbol for r in recs} == {"MNK"}, (
        "the journal must say which contract it meant; NKD is the HISTORY symbol and must "
        "never appear on an order record")


def test_19_the_idempotency_key_is_the_same_on_all_four_rows(tmp_path):
    e = ex(tmp_path, broker=FakeBroker(raises=BrokerBoom("no route to host")))
    with pytest.raises(BrokerBoom):
        e.open_position(took(), ref_day="2026-08-25")
    recs, _ = J.read(root=tmp_path, day=DAY)
    assert len(recs) == 3
    assert len({r.idempotency_key for r in recs}) == 1


def test_20_every_row_is_stamped_with_the_track1_route(tmp_path):
    ex(tmp_path).open_position(took(), ref_day="2026-08-25")
    recs, _ = J.read(root=tmp_path, day=DAY)
    assert {r.route for r in recs} == {J.ROUTE}


def test_21_the_fill_numbers_land_on_the_terminal_row(tmp_path):
    ex(tmp_path, broker=FakeBroker(result=fill(status="PARTIAL", qty=1, price=20100.25))
       ).open_position(took(), ref_day="2026-08-25")
    recs, _ = J.read(root=tmp_path, day=DAY)
    last = recs[-1]
    assert (last.filled_qty, last.avg_price, last.fill_status) == (1, 20100.25, "PARTIAL")


# ── 6. it never touches the book ─────────────────────────────────────────────

def test_22_the_module_contains_no_write_to_the_track1_book(tmp_path):
    """Not a guarded write. None. Proved by AST, not by a substring search of the prose."""
    tree = ast.parse(Path(X.__file__).read_text(encoding="utf-8"))
    writers = {"write_text", "write_bytes", "dump", "replace", "rename", "unlink"}
    found = [n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in writers]
    assert found == [], f"a writer appears in the executor: {found}"
    opens = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open"]
    assert opens == [], "the executor opens a file handle of its own"


def test_23_a_fill_does_not_create_or_change_the_book_file(tmp_path):
    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps({"positions": []}), encoding="utf-8")
    before = book.read_bytes()
    ex(tmp_path).open_position(took(), ref_day="2026-08-25")
    assert book.read_bytes() == before, "the executor advanced the book itself"


# ── 7. reading the book fails closed ─────────────────────────────────────────

def test_24_a_missing_book_is_an_empty_book(tmp_path):
    pos, detail = X.read_book(Path(tmp_path) / X.BOOK_PATH)
    assert pos == [] and "does not exist" in detail


def test_25_an_unreadable_book_is_NOT_an_empty_book(tmp_path):
    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(X.PaperExecutorRefused) as e:
        X.read_book(book)
    assert e.value.code == X.BOOK_UNREADABLE


def test_26_a_book_missing_a_quantity_refuses_rather_than_dropping_the_row(tmp_path):
    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps([{"instrument": "MNQ", "direction": "long"}]), encoding="utf-8")
    with pytest.raises(X.PaperExecutorRefused):
        X.read_book(book)


def test_27_the_REAL_book_shape_is_what_it_reads(tmp_path):
    """Measured against `track1_bootstrap.snapshot_book`, not against a guess.

    The writer spells the quantity `qty`. A reader asking for `contracts` would have refused
    every genuine book while still looking fail-closed, which is the worst of both.
    """
    from global_index import track1_bootstrap as bs
    import inspect
    src = inspect.getsource(bs.snapshot_book)
    assert '"qty": int(h.position.contracts)' in src, (
        "the book writer changed its quantity key; read_book must follow it")

    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps({
        "schema_version": bs.BOOK_SCHEMA, "route": "track1_candidate", "window": None,
        "cut_instant": None, "equity": 100000.0, "cur_day": "2026-08-25",
        "positions": [{"trade_id": "t1", "sleeve": "roska4_stress", "instrument": "MNQ",
                       "direction": "long", "qty": 2, "risk_dollars": 250.0,
                       "entry_time": "2026-08-25 10:35:00", "exit_time": None,
                       "entry_price": 20100.0, "stop_price": 20000.0}],
        "booked_counter": {}, "counters": {}}), encoding="utf-8")
    pos, _ = X.read_book(book)
    assert pos == [S.Position(instrument="MNQ", direction="long", contracts=2)]


def test_27b_a_book_stamped_with_another_route_is_refused(tmp_path):
    """`live_positions.json` and the Track1 book are the same shape; only the stamp differs."""
    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps({"schema_version": 2, "route": "legacy", "positions": [
        {"instrument": "MNQ", "direction": "long", "qty": 2}]}), encoding="utf-8")
    with pytest.raises(X.PaperExecutorRefused) as e:
        X.read_book(book)
    assert "legacy" in e.value.detail


def test_27c_a_book_from_a_future_schema_is_refused(tmp_path):
    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps({"schema_version": 3, "route": "track1_candidate",
                                "positions": []}), encoding="utf-8")
    with pytest.raises(X.PaperExecutorRefused):
        X.read_book(book)


def test_28_reconcile_reads_the_track1_book_and_journal(tmp_path):
    e = ex(tmp_path)
    e.open_position(took(), ref_day="2026-08-25")
    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps({"positions": [
        {"instrument": "MNQ", "direction": "long", "qty": 2}]}), encoding="utf-8")
    r = e.reconcile_at_startup(
        broker_positions=[S.Position(instrument="MNQ", direction="long", contracts=2)],
        day=DAY)
    assert r.verdict == S.MATCH


def test_29_a_disagreement_still_blocks_entries(tmp_path):
    e = ex(tmp_path)
    book = Path(tmp_path) / X.BOOK_PATH
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(json.dumps({"positions": [
        {"instrument": "MNQ", "direction": "long", "qty": 2}]}), encoding="utf-8")
    r = e.reconcile_at_startup(
        broker_positions=[S.Position(instrument="MNQ", direction="long", contracts=1)],
        day=DAY)
    assert r.verdict == S.MISMATCH and r.blocks_entries and r.allows_exits


def test_30_a_corrupt_journal_line_refuses_the_whole_reconcile(tmp_path):
    e = ex(tmp_path)
    e.open_position(took(), ref_day="2026-08-25")
    p = J.journal_path(DAY, tmp_path)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("{not json}\n")
    with pytest.raises(J.OrderJournalRefused):
        e.reconcile_at_startup(broker_positions=[], day=DAY)


# ── 9. the broker capability gap, named ──────────────────────────────────────

def test_31_the_broker_capability_report_is_data_not_discovery(tmp_path):
    rep = X.broker_capability_report(FakeBroker())
    assert rep["required_absent"] == []
    assert rep["optional_absent"] == []          # corrected in Stage 5X - see test_32
    assert rep["fill_carries_order_id"] is True  # closed in Stage 5Y
    assert rep["interim_unknown_resolution"]
    assert "never resolve an order on their own" in rep["interim_unknown_resolution"]


def test_32_the_broker_capability_claim_tracks_what_is_actually_there(tmp_path):
    """This test has fired twice, and was right both times.

    Stage 5W claimed `get_open_orders` and `get_executions` were missing. The second name was
    never real - the capability exists as `find_execution` - and the first was added in Stage
    5X over a `reqAllOpenOrders()` call the file already made five times.

    What was left after that was the Fill carrying no order id, so neither id-keyed lookup
    could be used on an entry this route sent. **Stage 5Y closed that too**, by appending an
    optional field rather than by changing any existing one. What this test pins now is that
    the claim in the module is derived from the dataclass rather than asserted - which is the
    whole lesson from the two times it was wrong.
    """
    import dataclasses
    from global_index.ibkr_broker import IBKRBroker
    assert X.MISSING_BROKER_METHODS == ()
    for real in ("find_execution", "get_open_orders", "get_order_status", "get_positions"):
        assert callable(getattr(IBKRBroker, real, None)), real

    names = [f.name for f in dataclasses.fields(Fill)]
    assert "order_id" in names
    assert names[-1] == "order_id", (
        "order_id must stay LAST; it was appended so no positional caller moved")
    assert X.FILL_CARRIES_ORDER_ID is True
    assert dataclasses.fields(Fill)[-1].default is None, (
        "the default must be None - an order that never reached a broker has no id, and "
        "an empty string would read as one")


# ── 10. the three walls ──────────────────────────────────────────────────────

def test_33_nothing_in_production_imports_the_executor(tmp_path):
    hits = []
    for d in ("global_index", "monitor", "futures"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            # Stage 5Z: the dry-run module is an allowed consumer, and it is itself
            # imported by nothing - asserted below, so the chain stays unreachable.
            if p.stem in ("track1_paper_executor", "track1_paper_callsite") \
                    or "scratch" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if not isinstance(n, (ast.Import, ast.ImportFrom)):
                    continue
                # BOTH halves matter. `from global_index import track1_paper_executor` puts
                # the name in `.names` and only "global_index" in `.module`, so checking the
                # module alone lets the most natural import in this repo through - which is
                # exactly what mutation M11 did while the test stayed green.
                mod = getattr(n, "module", "") or ""
                names = [a.name for a in n.names]
                if "track1_paper_executor" in mod or any(
                        "track1_paper_executor" in nm for nm in names):
                    hits.append(str(p))
    # Stage 5ZZG. See ALLOWED_EXECUTOR_IMPORTERS below for why this is a set and not empty.
    named = sorted(Path(h).name for h in hits)
    assert named == sorted(ALLOWED_EXECUTOR_IMPORTERS), {
        "unexpected": sorted(set(named) - set(ALLOWED_EXECUTOR_IMPORTERS)),
        "missing": sorted(set(ALLOWED_EXECUTOR_IMPORTERS) - set(named))}
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



#: The modules allowed to name the executor, and what stands between each and a live order.
#: Stage 5ZZG added the second; before it there were none and the invariant was "nobody".
REASON_5ZZG = """
    Stage 5ZZG REPLACED the old form of this. It used to say "nothing in production imports
    the executor", which was true while the SEND wire did not exist and is now false by design.
    Weakening it to "anything may import it" would throw away the only thing that would notice a
    second path to a broker, so the invariant is restated rather than dropped:

        the executor may be named by exactly the modules listed here, and by nothing else.

    One of them is WALLED (a broker that refuses every call), one is GATED (the import sits
    past the gate check, so an unarmed run never loads the order layer at all). A third name
    appearing in this list is a new road to a live order, and this assertion is what says so.
"""

#: What THIS scan may find. The dry-run callsite is skipped by the loop above — it has been an
#: allowed consumer since Stage 5Z, walled behind a RefusingBroker — so the only name that may
#: reach here is the gated send. Listing the callsite here as well would be a truer-sounding
#: sentence about a scan that never looks at it, and the 5ZZG suite asserts the full picture
#: over an unfiltered scan instead.
ALLOWED_EXECUTOR_IMPORTERS = {
    "track1_paper_send.py": "gated — the import sits past the gate check, so an unarmed run "
                            "never loads the order layer at all",
}


def test_34_the_slot_takes_an_order_gate_and_defaults_it_shut(tmp_path):
    """Stage 5ZZG. The old form asserted `observe_live_slot` had NO order argument at all,
    which was the whole safety story while the wire did not exist. The wire exists now, so the
    assertion moves from "there is no such argument" to the thing that actually matters:

        the argument exists, it DEFAULTS TO SHUT, and every existing caller — the scheduler
        above all — passes nothing and therefore cannot arm anything.

    Dropping the test would have left nobody watching the default.
    """
    import inspect as _i
    from global_index import run_live_day_track1 as R

    params = _i.signature(R.observe_live_slot).parameters
    assert "order_gate" in params, "the slot lost the gate it is supposed to carry"
    assert params["order_gate"].default is None, params["order_gate"].default
    assert "broker" in params and params["broker"].default is None

    # a slot built with the default gate is a slot that cannot send
    gate = R.OrderGate(False)
    assert gate.allow_orders is False

    # and the scheduler passes neither
    src = (REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8")
    code = "\n".join(ln.split("#")[0] for ln in src.splitlines())
    for forbidden in ("order_gate", "allow-orders", "allow_orders"):
        assert forbidden not in code, f"the scheduler names {forbidden}"


def test_35_the_pure_modules_still_do_not_import_ib_insync(tmp_path):
    for mod in (X, PO, J, S):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                assert not any("ib_insync" in a.name for a in n.names), mod.__name__
            if isinstance(n, ast.ImportFrom):
                assert "ib_insync" not in (n.module or ""), mod.__name__


def test_36_the_real_order_gate_still_refuses_to_arm(tmp_path):
    """The wall that matters most: the executor cannot be constructed against production."""
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    ids = [r.split(":")[0] for r in reasons]
    assert "B1_broker_account_or_legacy_retirement" in ids
    assert "PAPER_SHADOW_EVIDENCE" in ids
    gate = X.production_gate()
    assert gate.allow_orders is False
    with pytest.raises(X.PaperExecutorRefused) as e:
        X.Track1OrderExecutor(broker=FakeBroker(), gate=gate, journal_root=tmp_path)
    assert e.value.code == X.NOT_ARMED


def test_37_no_confirmation_file_and_no_approval_env(tmp_path):
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")
    from global_index import track1_gates as G
    assert not (REPO / G.CONFIRMATION_PATH).exists()


def test_38_no_caller_ever_passes_allow_orders(tmp_path):
    """By AST, not by substring.

    A plain `in` check on the source fails here and correctly so: run_scheduler.py both
    documents and comments that it passes no such flag, so a search for the string matches
    the prose forbidding the thing. Only a real string LITERAL counts.

    And the flag's own DEFINITION is not a caller. `run_live_day_track1` owns the argument;
    the claim under test is that nothing hands it over, so that file is checked separately
    for the shape it is allowed to have.
    """
    for rel in ("global_index/run_scheduler.py", "monitor/ops.py",
                "global_index/track1_slots.py"):
        p = REPO / rel
        if not p.exists():
            continue
        literals = [n for n in ast.walk(ast.parse(p.read_text(encoding="utf-8",
                                                              errors="replace")))
                    if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
        assert literals == [], f"{rel} builds an argv containing --allow-orders"


def test_39_the_flag_exists_only_as_its_own_argparse_definition(tmp_path):
    """The one place the literal is allowed, pinned to the shape that makes it harmless."""
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    sites = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and any(
                isinstance(a, ast.Constant) and a.value == "--allow-orders" for a in n.args)):
            continue
        sites.append(n.func.attr if isinstance(n.func, ast.Attribute) else "?")
    assert sites == ["add_argument"], (
        f"--allow-orders appears somewhere other than its own argparse definition: {sites}")
    literals = [n for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
    assert len(literals) == 1, "more than one --allow-orders literal in the runner"


# ── 11. arming changes the label and nothing that decides ────────────────────

def test_40_arming_changes_only_the_recorded_mode_not_whether_freshness_binds():
    """Both live modes are in the binding set, so arming cannot loosen the gate."""
    from global_index import run_live_day_track1 as R
    from global_index import track1_explain as tx
    assert R.decision_mode_for("live", ClosedGate()) == tx.SHADOW_LIVE
    assert R.decision_mode_for("live", ArmedGate()) == tx.ARMED
    assert {tx.SHADOW_LIVE, tx.ARMED} <= tx.FRESHNESS_BINDING_MODES, (
        "arming would change whether the freshness gate binds")


def test_41_the_mode_label_reaches_the_explanation_writer_and_nothing_else():
    """Structural, and therefore stronger than a two-arm run on one day.

    A run-and-compare proves the two modes agreed on the day it was run. This proves the
    label cannot reach a decision on ANY day: inside `run_shadow` the derived mode is used
    exactly once after it is assigned, and that use is the explanation writer's `mode=`.
    """
    import ast as _ast
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, _ast.FunctionDef) and n.name == "run_shadow")
    uses = [n for n in _ast.walk(fn)
            if isinstance(n, _ast.Name) and n.id == "mode"
            and isinstance(n.ctx, _ast.Load)]
    # one Load is the argument to resolve_decision_mode on the assignment line itself
    assign = min(n.lineno for n in _ast.walk(fn)
                 if isinstance(n, _ast.Name) and n.id == "mode"
                 and isinstance(n.ctx, _ast.Store))
    downstream = [n.lineno for n in uses if n.lineno != assign]
    assert len(downstream) == 1, f"mode is read at more than one place: {downstream}"

    consumer = [n for n in _ast.walk(fn)
                if isinstance(n, _ast.Call)
                and any(k.arg == "mode" and isinstance(k.value, _ast.Name)
                        and k.value.id == "mode" for k in n.keywords)]
    names = [c.func.id if isinstance(c.func, _ast.Name) else c.func.attr for c in consumer]
    assert names == ["emit_explanations"], names


def test_42_the_broker_is_still_NoOrderBroker_on_the_run_path():
    import ast as _ast
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in _ast.walk(_ast.parse(src))
              if isinstance(n, _ast.FunctionDef) and n.name == "run_shadow")
    built = [n.func.id for n in _ast.walk(fn)
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
             and n.func.id.endswith("Broker")]
    assert built == ["NoOrderBroker"], built
