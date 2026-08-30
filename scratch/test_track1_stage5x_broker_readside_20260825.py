"""Stage 5X — the broker read side made tri-state, and Track 1 reconcile against it.

Every broker here is a fake. Nothing connects, nothing orders, nothing writes outside
tmp_path. The point of most of these tests is a single distinction: **"nothing" and "I could
not ask" must not arrive as the same value.**
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from global_index import track1_broker_read as BR
from global_index import track1_order_journal as J
from global_index import track1_order_state as S
from global_index import track1_paper_executor as X

REPO = Path(__file__).resolve().parents[1]
DAY = "20260825"


# ── fakes ────────────────────────────────────────────────────────────────────

class Pos:
    """The shape IBKRBroker.get_positions returns (BrokerPosition-like)."""

    def __init__(self, inst, direction, contracts):
        self.inst, self.direction, self.contracts = inst, direction, contracts


_RAISE = object()


class FakeBroker:
    """Answers exactly what it is told to, including by raising or returning None."""

    CAN_TESTIFY = True

    def __init__(self, positions=(), open_orders=(), status=None, execution=None):
        self._pos, self._oo, self._st, self._ex = positions, open_orders, status, execution

    @staticmethod
    def _serve(v):
        if v is _RAISE:
            raise ConnectionResetError("socket closed by peer")
        return v

    def get_positions(self): return self._serve(self._pos)
    def get_open_orders(self): return self._serve(self._oo)
    def get_order_status(self, order_id): return self._serve(self._st)
    def find_execution(self, order_id, inst=None): return self._serve(self._ex)


class MuteBroker:
    """Every method present, every answer empty — but it cannot testify."""

    CAN_TESTIFY = False

    def get_positions(self): return []
    def get_open_orders(self): return []
    def get_order_status(self, order_id): return "NOT_FOUND"
    def find_execution(self, order_id, inst=None): return None


class BareBroker:
    """No read methods at all."""


def rec(instrument="MNQ", action="OPEN", qty=2, order_id="", state=S.SUBMITTED):
    return J.JournalRecord(
        idempotency_key="k1", state=state, ref_day="2026-08-25", sleeve="roska4_stress",
        instrument=instrument, tradable_symbol="MNQ", action=action, candidate_id="t1",
        created_at="2026-08-25T14:35:00", order_id=order_id, filled_qty=qty)


def reader(**kw):
    return BR.Track1BrokerReader(FakeBroker(**kw))


# ══════════════════════════════════════════════════════════════════════════════
# 1. the reads themselves: nothing vs cannot say
# ══════════════════════════════════════════════════════════════════════════════

def test_1_an_empty_position_list_from_a_real_broker_is_KNOWN_flat():
    a = reader(positions=[]).positions()
    assert a.known and a.value == []


def test_2_an_empty_position_list_from_a_broker_that_cannot_testify_is_UNKNOWN():
    """The whole point. `[]` from NoOrderBroker means 'never asked', not 'flat'."""
    a = BR.Track1BrokerReader(MuteBroker()).positions()
    assert not a.known and BR.CANNOT_TESTIFY in a.detail


def test_3_a_raising_read_is_UNKNOWN_not_empty():
    a = reader(positions=_RAISE).positions()
    assert not a.known and BR.READ_RAISED in a.detail
    assert "ConnectionResetError" in a.detail


def test_4_None_from_get_positions_is_UNKNOWN():
    a = reader(positions=None).positions()
    assert not a.known


def test_5_positions_come_back_as_the_state_modules_own_type():
    a = reader(positions=[Pos("MNQ", "LONG", 2)]).positions()
    assert a.known
    assert a.value == [S.Position(instrument="MNQ", direction="long", contracts=2)]


def test_6_a_short_position_keeps_its_size_positive_and_its_side():
    a = reader(positions=[Pos("MNQ", "SHORT", -3)]).positions()
    assert a.value == [S.Position(instrument="MNQ", direction="short", contracts=3)]


def test_7_one_unreadable_position_row_makes_the_whole_read_UNKNOWN():
    """A book that is partly readable is not a book."""
    class Broken:
        inst, direction = "MNQ", "LONG"

        @property
        def contracts(self): raise ValueError("no size on this row")

    a = reader(positions=[Pos("MNQ", "LONG", 2), Broken()]).positions()
    assert not a.known and BR.AMBIGUOUS in a.detail


def test_8_a_missing_method_is_UNKNOWN_not_an_exception():
    a = BR.Track1BrokerReader(BareBroker()).positions()
    assert not a.known and BR.NO_METHOD in a.detail


# ── open orders: the get_working_stops convention, kept ──────────────────────

def test_9_an_empty_open_order_list_is_KNOWN_nothing_working():
    a = reader(open_orders=[]).open_orders()
    assert a.known and a.value == []


def test_10_None_from_get_open_orders_is_UNKNOWN_offline():
    a = reader(open_orders=None).open_orders()
    assert not a.known and BR.CANNOT_TESTIFY in a.detail


# ── order status: NOT_FOUND is the important one ─────────────────────────────

@pytest.mark.parametrize("status", ["FILLED", "CANCELLED", "PENDING"])
def test_11_a_definite_status_is_KNOWN(status):
    a = reader(status=status).order_status("55")
    assert a.known and a.value == status


def test_12_NOT_FOUND_is_UNKNOWN_because_the_broker_also_says_it_on_error():
    """`get_order_status` returns NOT_FOUND from its own `except Exception` branch."""
    a = reader(status=BR.STATUS_NOT_FOUND).order_status("55")
    assert not a.known and BR.AMBIGUOUS in a.detail


def test_13_the_real_get_order_status_really_does_conflate_them():
    """Measured from the source, so this claim cannot rot into a story."""
    src = (REPO / "global_index/ibkr_broker.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "get_order_status")
    handlers = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
    returns = [c.value for h in handlers for c in ast.walk(h)
               if isinstance(c, ast.Return) and isinstance(c.value, ast.Constant)]
    assert BR.STATUS_NOT_FOUND in [r.value for r in returns], (
        "get_order_status no longer returns NOT_FOUND from its except branch; the "
        "re-labelling in track1_broker_read may no longer be needed")


def test_14_no_order_id_is_UNKNOWN_and_says_why():
    a = reader(status="FILLED").order_status("")
    assert not a.known and "idempotency key" in a.detail


# ── executions ───────────────────────────────────────────────────────────────

def test_15_a_found_execution_is_KNOWN():
    a = reader(execution={"shares": 2, "price": 20100.0}).execution("55", "MNQ")
    assert a.known and a.value["shares"] == 2


def test_16_None_from_find_execution_is_UNKNOWN_never_no_fill_happened():
    a = reader(execution=None).execution("55", "MNQ")
    assert not a.known and "no fill happened" in a.detail


def test_17_the_real_find_execution_returns_None_for_three_different_things():
    src = (REPO / "global_index/ibkr_broker.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "find_execution")
    nones = [n for n in ast.walk(fn)
             if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
             and n.value.value is None]
    assert len(nones) >= 3, (
        f"find_execution now returns None from {len(nones)} places; the ambiguity this "
        f"module compensates for may have changed")


# ══════════════════════════════════════════════════════════════════════════════
# 2. the six reconcile scenarios the stage asked for
# ══════════════════════════════════════════════════════════════════════════════

def test_18_SUBMITTED_plus_a_working_order_is_unresolved_and_blocks_entries():
    v = BR.resolve_submitted(
        rec(order_id="55"),
        reader(open_orders=[{"order_id": "55", "instrument": "MNQ", "action": "OPEN"}],
               status="PENDING"))
    assert v.resolution == BR.STILL_WORKING
    assert v.blocks_entries and not v.resolved
    assert "order_still_working" in v.reasons


def test_19_a_working_order_is_matched_without_an_id_by_instrument_AND_action():
    v = BR.resolve_submitted(
        rec(order_id=""),
        reader(open_orders=[{"instrument": "MNQ", "action": "OPEN"}]))
    assert v.resolution == BR.STILL_WORKING


def test_20_a_stop_working_on_the_same_contract_is_not_our_entry():
    """Instrument alone would claim it. The action is what separates them."""
    v = BR.resolve_submitted(
        rec(order_id=""),
        reader(open_orders=[{"instrument": "MNQ", "action": "CLOSE"}], status=None))
    assert v.resolution != BR.STILL_WORKING


def test_21_SUBMITTED_no_open_order_no_execution_positions_unchanged_is_UNKNOWN():
    """The scenario that must never come back REJECTED."""
    v = BR.resolve_submitted(
        rec(order_id="55"),
        reader(open_orders=[], status=BR.STATUS_NOT_FOUND, execution=None, positions=[]))
    assert v.resolution == BR.RESOLVED_UNKNOWN
    assert v.resolution != BR.RESOLVED_REJECTED
    assert v.blocks_entries
    assert "broker_could_not_resolve" in v.reasons
    assert "Not rejected — unproven" in v.detail


def test_22_a_filled_execution_resolves_the_row_and_unblocks_entries():
    v = BR.resolve_submitted(
        rec(order_id="55", qty=2),
        reader(open_orders=[], status="FILLED", execution={"shares": 2, "price": 20100.0}))
    assert v.resolution == BR.RESOLVED_FILLED
    assert v.resolved and not v.blocks_entries


def test_23_a_partial_fill_stays_PARTIAL_and_keeps_blocking():
    v = BR.resolve_submitted(
        rec(order_id="55", qty=4),
        reader(open_orders=[], status="FILLED", execution={"shares": 1, "price": 20100.0}))
    assert v.resolution == BR.RESOLVED_PARTIAL
    assert v.blocks_entries
    assert "partial_fill" in v.reasons


def test_24_FILLED_without_an_execution_record_is_UNKNOWN_not_FILLED():
    """The broker says filled and will not say how much. That cannot advance a book."""
    v = BR.resolve_submitted(
        rec(order_id="55"),
        reader(open_orders=[], status="FILLED", execution=None))
    assert v.resolution == BR.RESOLVED_UNKNOWN
    assert "filled_without_execution_record" in v.reasons


def test_25_a_broker_read_timeout_is_UNKNOWN_and_blocks_entries():
    v = BR.resolve_submitted(
        rec(order_id="55"),
        reader(open_orders=_RAISE, status=_RAISE, positions=_RAISE))
    assert v.resolution == BR.RESOLVED_UNKNOWN
    assert v.blocks_entries
    assert {"open_orders_unknown", "order_status_unknown",
            "positions_unknown"} <= set(v.reasons)


def test_26_only_a_broker_STATEMENT_reaches_REJECTED():
    v = BR.resolve_submitted(rec(order_id="55"), reader(open_orders=[], status="CANCELLED"))
    assert v.resolution == BR.RESOLVED_REJECTED
    assert not v.blocks_entries


def test_27_silence_is_never_rejection_across_every_silent_shape():
    for kw in ({"status": BR.STATUS_NOT_FOUND}, {"status": ""}, {"status": _RAISE},
               {"status": None}):
        v = BR.resolve_submitted(rec(order_id="55"), reader(open_orders=[], **kw))
        assert v.resolution != BR.RESOLVED_REJECTED, kw


def test_28_a_mute_broker_resolves_nothing_and_blocks_everything():
    v = BR.resolve_submitted(rec(order_id="55"), BR.Track1BrokerReader(MuteBroker()))
    assert v.resolution == BR.RESOLVED_UNKNOWN and v.blocks_entries


def test_29_positions_are_read_but_never_resolve_the_order_alone():
    """A matching position proves something filled, not that THIS order filled it."""
    v = BR.resolve_submitted(
        rec(order_id="55"),
        reader(open_orders=[], status=BR.STATUS_NOT_FOUND,
               positions=[Pos("MNQ", "LONG", 2)]))
    assert v.resolution == BR.RESOLVED_UNKNOWN
    assert v.evidence["positions"], "positions were not even consulted"


def test_30_entries_are_blocked_if_any_row_is_unresolved():
    good = BR.resolve_submitted(rec(order_id="1"),
                                reader(open_orders=[], status="CANCELLED"))
    bad = BR.resolve_submitted(rec(order_id="2"), BR.Track1BrokerReader(MuteBroker()))
    ok, reasons = BR.entries_allowed([good, bad])
    assert not ok and reasons
    ok2, _ = BR.entries_allowed([good])
    assert ok2


# ── exits ────────────────────────────────────────────────────────────────────

def test_31_an_exit_that_reduces_exposure_is_allowed_under_UNKNOWN():
    ok, why = BR.exit_allowed(verdict_or_resolution=BR.RESOLVED_UNKNOWN,
                              reduces_exposure=True)
    assert ok and "reduces exposure" in why


def test_32_an_exit_that_does_not_reduce_exposure_is_refused_under_UNKNOWN():
    """Stage 5U said 'exits always allowed'. An over-sized close opens the other side."""
    ok, why = BR.exit_allowed(verdict_or_resolution=BR.RESOLVED_UNKNOWN,
                              reduces_exposure=False)
    assert not ok and "opens the opposite side" in why


def test_33_exit_allowed_accepts_a_verdict_object_too():
    v = BR.resolve_submitted(rec(order_id="55"), BR.Track1BrokerReader(MuteBroker()))
    ok, _ = BR.exit_allowed(verdict_or_resolution=v, reduces_exposure=True)
    assert ok


def test_34_MISMATCH_from_stage_5U_also_permits_a_reducing_exit():
    ok, _ = BR.exit_allowed(verdict_or_resolution=S.MISMATCH, reduces_exposure=True)
    assert ok


# ══════════════════════════════════════════════════════════════════════════════
# 3. the book read-back
# ══════════════════════════════════════════════════════════════════════════════

def _book(tmp_path, payload):
    p = Path(tmp_path) / X.BOOK_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_35_the_reader_accepts_the_writers_schema_qty_not_contracts(tmp_path):
    import inspect
    from global_index import track1_bootstrap as bs
    assert '"qty": int(h.position.contracts)' in inspect.getsource(bs.snapshot_book)
    p = _book(tmp_path, {"schema_version": bs.BOOK_SCHEMA, "route": "track1_candidate",
                         "positions": [{"instrument": "MNQ", "direction": "long", "qty": 2}]})
    pos, _ = X.read_book(p)
    assert pos == [S.Position(instrument="MNQ", direction="long", contracts=2)]


def test_36_a_missing_book_is_an_empty_track1_book_not_an_error(tmp_path):
    pos, detail = X.read_book(Path(tmp_path) / X.BOOK_PATH)
    assert pos == [] and "does not exist" in detail


def test_37_the_live_book_exists_and_is_flat():
    """Rewritten by Stage 5ZN, and the reason is the point.

    As written this asserted the book was ABSENT — and it passed for the wrong reason:
    `X.BOOK_PATH` was `global_index/live_positions.track1.json`, a path the book has never
    occupied. Every other component uses the repository root, and that is where
    `track1_bootstrap.write` puts it. So the assertion was true of a file nobody writes.

    That constant made `read_book` — which correctly treats a missing file as an empty book —
    answer ALWAYS-empty, which would have made `reconcile_at_startup` conclude the route was
    flat whatever it held. It never fired because nothing imports the executor. 5ZN sources
    the constant from `track1_slots` so the two cannot drift again.

    The route's first complete window wrote the book on 2026-08-25; it exists and holds
    nothing, which is a different fact from not existing.
    """
    from global_index import track1_slots as _ts
    assert X.BOOK_PATH == _ts.TRACK1_POSITIONS_PATH
    p = REPO / X.BOOK_PATH
    if not p.exists():
        pytest.skip("no window has closed on this machine yet")
    positions, detail = X.read_book(p)
    assert positions == [], detail
    assert "0 position(s)" in detail


def test_38_a_corrupt_book_fails_closed(tmp_path):
    p = Path(tmp_path) / X.BOOK_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(X.PaperExecutorRefused) as e:
        X.read_book(p)
    assert e.value.code == X.BOOK_UNREADABLE


def test_39_a_corrupt_book_blocks_ENTRIES_through_the_reconcile(tmp_path):
    """Fail-closed has to mean something at the call site, not just at the reader."""
    class Armed:
        allow_orders = True

    class Cap:
        def send_order(self, o): return None
        def get_positions(self): return []
        def get_order_status(self, *a): return "PENDING"
        def cancel_order(self, *a): return None
        def place_stop(self, *a): return None

    ex = X.Track1OrderExecutor(broker=Cap(), gate=Armed(), journal_root=tmp_path)
    p = Path(tmp_path) / X.BOOK_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(X.PaperExecutorRefused):
        ex.reconcile_at_startup(broker_positions=[], day=DAY)


# ══════════════════════════════════════════════════════════════════════════════
# 4. the new broker method, and the walls
# ══════════════════════════════════════════════════════════════════════════════

def _ibkr_fn(name):
    """Parse one IBKRBroker method from the FILE.

    Not `inspect.getsource` - that reads the linecache, so a test built on it cannot be
    broken by a source-level mutation and silently proves nothing. Mutations M13 and M15
    both stayed green against the earlier version of these two tests.
    """
    src = (REPO / "global_index/ibkr_broker.py").read_text(encoding="utf-8")
    cls = next(n for n in ast.parse(src).body
               if isinstance(n, ast.ClassDef) and n.name == "IBKRBroker")
    return next(n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_40_get_open_orders_returns_None_offline_never_an_empty_list():
    from global_index.ibkr_broker import IBKRBroker
    assert callable(IBKRBroker.get_open_orders)
    fn = _ibkr_fn("get_open_orders")
    guard = next(n for n in fn.body if isinstance(n, ast.If))
    assert "_raw_fetcher" in ast.dump(guard.test)
    returns = [n.value for n in ast.walk(guard) if isinstance(n, ast.Return)]
    assert len(returns) == 1
    assert isinstance(returns[0], ast.Constant) and returns[0].value is None, (
        "offline mode must return None, never [], or 'nothing working' and 'cannot say' "
        "collapse again at the source")


#: Stage 5ZQ gave `get_open_orders` its first caller: the read-only B1 audit, which asks the
#: account whether it is flat. That is what the method was written for — its own docstring says
#: so — and this test was the reason it sat uncalled for several stages.
#:
#: The test's NAME and its ASSERTION had drifted apart: the name claims nothing in the LEGACY
#: ROUTE calls it, the assertion claimed nothing ANYWHERE does. The second is a stronger claim
#: than the intent behind it ("it is additive; legacy B3/B4 cannot have moved"), and it is the
#: stronger one that would have to be broken by any use at all.
#:
#: So the claim is now written as it was always meant: every caller must be named here, and the
#: legacy route must not be among them. A new caller anywhere still turns this red — it just
#: says which file, rather than forbidding the method from ever being used.
ALLOWED_GET_OPEN_ORDERS_CALLERS = {
    "b1_audit.py": "the read-only B1 audit — asks the account whether it is flat, places "
                   "nothing, and is not on the route or in the legacy safety path",
}

#: The legacy route's own files. None of these may appear as a caller, whatever else does.
LEGACY_ROUTE_FILES = {"runner.py", "run_live_day.py", "run_stop_repair.py",
                      "run_maxhold_exit.py", "broker.py"}


def test_41_get_open_orders_is_CALLED_by_nothing_in_the_legacy_route():
    """It is additive. Legacy B3/B4 behaviour cannot have moved.

    By AST. A substring scan fails here and it caught me a third time in this arc: the
    corrected comment in track1_paper_executor NAMES the method while calling nothing, so
    the text search matched the prose about the thing instead of the thing.
    """
    callers = {}
    for d in ("global_index", "futures", "monitor"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.name in ("ibkr_broker.py", "track1_broker_read.py"):
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "get_open_orders"):
                    callers.setdefault(p.name, []).append(n.lineno)

    trespassing = sorted(set(callers) & LEGACY_ROUTE_FILES)
    assert trespassing == [], f"the legacy route now calls get_open_orders: {trespassing}"

    unexpected = sorted(set(callers) - set(ALLOWED_GET_OPEN_ORDERS_CALLERS))
    assert unexpected == [], (
        f"a new caller appeared that this test does not know about: {unexpected}. "
        f"If it is legitimate, name it in ALLOWED_GET_OPEN_ORDERS_CALLERS and say why.")


def test_41b_the_allowed_caller_actually_calls_it():
    """The allow-list must describe reality in both directions. An entry naming a file that no
    longer calls the method would quietly widen the permission for the next file with that
    name — and would leave the B1 audit asking nobody while this suite stayed green."""
    p = REPO / "global_index" / "b1_audit.py"
    assert p.exists(), "the B1 audit tool is gone; the allow-list is describing nothing"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "get_open_orders"]
    assert calls, "b1_audit no longer calls get_open_orders — it is asking the broker nothing"


def test_42_the_three_legacy_readers_were_not_modified():
    """Their bodies are load-bearing for runner.py's B3/B4. Stage 5X sits above them.

    This is a guard against HELPING: the obvious "fix" is to make these three fail closed
    too, and that would change what the legacy runner does on every reconnect. Read from the
    file, so a source-level change is what turns it red.
    """
    status = _ibkr_fn("get_order_status")
    handler_returns = [c.value.value for h in ast.walk(status)
                       if isinstance(h, ast.ExceptHandler)
                       for c in ast.walk(h)
                       if isinstance(c, ast.Return) and isinstance(c.value, ast.Constant)]
    assert BR.STATUS_NOT_FOUND in handler_returns, (
        "get_order_status stopped answering NOT_FOUND on error; legacy B3 depends on it")

    positions = _ibkr_fn("get_positions")
    tail = positions.body[-1]
    assert isinstance(tail, ast.Return) and isinstance(tail.value, ast.Name), (
        "get_positions no longer returns its last unsettled read; legacy behaviour moved")

    execution = _ibkr_fn("find_execution")
    nones = [n for n in ast.walk(execution)
             if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
             and n.value.value is None]
    assert len(nones) >= 3, len(nones)


def test_43_NoOrderBroker_is_marked_as_unable_to_testify():
    from global_index.run_live_day_track1 import NoOrderBroker
    b = NoOrderBroker()
    assert b.CAN_TESTIFY is False
    assert b.get_positions() == [], "the empty list several suites depend on is unchanged"
    assert not BR.Track1BrokerReader(b).positions().known


def test_44_the_read_module_imports_no_broker_and_no_ib_insync():
    tree = ast.parse(Path(BR.__file__).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        mods = [(getattr(n, "module", "") or "")] if isinstance(n, ast.ImportFrom) else []
        mods += [a.name for a in getattr(n, "names", [])] if isinstance(
            n, (ast.Import, ast.ImportFrom)) else []
        for m in mods:
            assert "ib_insync" not in m, m
            assert "ibkr_broker" not in m, m


def test_45_nothing_in_production_imports_the_read_module_or_the_executor():
    hits = []
    for d in ("global_index", "monitor", "futures"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.stem in ("track1_broker_read", "track1_paper_executor",
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
                for target in ("track1_broker_read", "track1_paper_executor"):
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



def test_46_orders_are_still_impossible():
    import os
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    assert "B1_broker_account_or_legacy_retirement" in ids
    assert "PAPER_SHADOW_EVIDENCE" in ids
    assert not (REPO / G.CONFIRMATION_PATH).exists()
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")


def test_47_no_caller_passes_allow_orders():
    for rel in ("global_index/run_scheduler.py", "monitor/ops.py"):
        p = REPO / rel
        if not p.exists():
            continue
        lits = [n for n in ast.walk(ast.parse(p.read_text(encoding="utf-8", errors="replace")))
                if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
        assert lits == [], rel


def test_48_this_suite_created_no_runtime_orders_directory():
    assert not (REPO / J.ORDERS_DIR).exists()


def test_49_neither_new_module_reads_or_writes_the_LEGACY_book():
    """`live_positions.json` is the legacy route's book, and Stage 5X must not have borrowed
    any of the code that touches it. The Track 1 path is the only one either module knows.

    By AST string literals, so a mention in a docstring explaining the distinction does not
    count as a use - track1_paper_executor's read_book docstring names the legacy file
    precisely to say it must be refused.
    """
    for mod in (BR, X):
        lits = [n.value for n in ast.walk(ast.parse(
                    Path(mod.__file__).read_text(encoding="utf-8")))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value.endswith("live_positions.json")]
        assert lits == [], f"{Path(mod.__file__).name} carries a legacy book path: {lits}"


def test_50_the_legacy_route_compensates_at_the_call_site_and_still_does():
    """Recorded because it is the design difference, and because a future 'tidy-up' of
    runner.py's per-site guards would remove the only protection legacy has.

    Legacy does not fix the read; it patches around it where it is called - a banner when
    the file claims positions and the broker shows none, and a bare `except: pass` around
    get_order_status. Track 1 fixes it once, at the read. Both facts are asserted so neither
    can quietly change.
    """
    src = (REPO / "global_index/runner.py").read_text(encoding="utf-8")
    assert "if not broker_pos and loaded_positions:" in src, (
        "runner.py lost its unsettled-positions banner; that heuristic is legacy's only "
        "compensation for get_positions returning a last-read")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("get_positions", "get_order_status", "find_execution")]
    assert len(calls) >= 3, len(calls)
