"""Stage 5V — the fail-closed order journal.

READ-ONLY of production data. No broker, no connection, no order, no confirmation file.
Every journal these tests write lives under `tmp_path`, and a test at the end proves the real
runtime tree gained nothing.

What is being held open
-----------------------
The window ledger swallows write failures **by design** — its contract is to never block a
trading path. This journal's contract is the exact opposite: a write that did not land must
stop the order, because the only correct response to "I could not record that I am about to
trade" is not to trade.

So every test here is really one question asked eight ways: *can this thing ever fail open?*
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO = Path(r"d:\raits")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_order_journal as j    # noqa: E402
from global_index import track1_order_state as st     # noqa: E402
from global_index import window_ledger as wl          # noqa: E402

DAY = "2026-08-25"
KEY = "track1_candidate:2026-08-25:global_nkd:MNKD:OPEN:c1"


def rec(state, key=KEY, **kw):
    base = dict(idempotency_key=key, state=state, ref_day=DAY, sleeve="global_nkd",
                instrument="MNKD", tradable_symbol="MNK", action="OPEN",
                candidate_id="c1", created_at="2026-08-25T06:10:00Z",
                slot_id="TRACK1_NKD_0110")
    base.update(kw)
    return j.JournalRecord(**base)


# ══════════════════════════════════════════════════════════════════════════════
# it writes, and it is readable
# ══════════════════════════════════════════════════════════════════════════════

def test_an_intended_record_is_written_and_reads_back(tmp_path):
    p = j.append(rec(st.INTENDED), root=tmp_path)
    assert p.exists() and p.name == "track1_orders_20260825.jsonl"
    assert p.parent == (tmp_path / j.ORDERS_DIR).resolve()
    got, invalid = j.read(root=tmp_path, day=DAY)
    assert invalid == [] and len(got) == 1
    assert got[0].state == st.INTENDED
    assert got[0].route == "track1_candidate"
    assert got[0].schema_version == j.SCHEMA_VERSION


def test_the_journal_lives_under_the_durable_runtime_root_not_scratch():
    assert j.ORDERS_DIR == "global_index/track1_runtime/orders"
    assert "scratch" not in j.ORDERS_DIR


def test_every_declared_field_survives_a_round_trip(tmp_path):
    """Flat and scalar, because it is read back after a crash."""
    j.append(rec(st.INTENDED), root=tmp_path)
    j.append(rec(st.SUBMITTED, order_id="ib-7"), root=tmp_path)
    j.append(rec(st.PARTIAL, order_id="ib-7", fill_status="PARTIAL", filled_qty=3,
                 avg_price=41999.5, commission=1.4, error=""), root=tmp_path)
    got, invalid = j.read(root=tmp_path, day=DAY)
    assert invalid == []
    last = got[-1]
    for name, want in (("order_id", "ib-7"), ("fill_status", "PARTIAL"), ("filled_qty", 3),
                       ("avg_price", 41999.5), ("commission", 1.4), ("sleeve", "global_nkd"),
                       ("slot_id", "TRACK1_NKD_0110"), ("tradable_symbol", "MNK"),
                       ("candidate_id", "c1"), ("ref_day", DAY), ("action", "OPEN")):
        assert getattr(last, name) == want, name
    raw = json.loads(Path(j.journal_path(DAY, tmp_path)).read_text(
        encoding="utf-8").splitlines()[-1])
    # Stage 5ZN widened this to admit None. The planned-stop fields default to None, and that
    # is load-bearing: "no plan travelled with this row" must be distinguishable from a stop at
    # a price, and 0.0 would collide with a real one. None round-trips through JSON unchanged,
    # so the property this line guards — flat and scalar, readable after a crash — still holds.
    assert all(v is None or isinstance(v, (str, int, float)) for v in raw.values()), raw


def test_multiple_appends_preserve_order(tmp_path):
    for s in (st.INTENDED, st.SUBMITTED, st.FILLED):
        j.append(rec(s), root=tmp_path)
    got, _ = j.read(root=tmp_path, day=DAY)
    assert [r.state for r in got] == [st.INTENDED, st.SUBMITTED, st.FILLED]


def test_an_idempotency_key_is_deterministic_and_carries_no_timestamp():
    """A retry of the same intent must produce the same key, or it cannot identify an attempt."""
    kw = dict(sleeve="global_nkd", instrument="MNKD", ref_day=DAY, action="OPEN",
              candidate_id="c1")
    a, b = j.idempotency_key(**kw), j.idempotency_key(**kw)
    assert a == b
    assert a.startswith("track1_candidate:")
    assert j.idempotency_key(**{**kw, "action": "CLOSE"}) != a
    with pytest.raises(j.OrderJournalRefused):
        j.idempotency_key(**{**kw, "candidate_id": ""})


# ══════════════════════════════════════════════════════════════════════════════
# it fails CLOSED
# ══════════════════════════════════════════════════════════════════════════════

def test_a_write_failure_raises_and_does_not_pretend_success(tmp_path, monkeypatch):
    """The whole reason this module exists. Nothing is caught."""
    real_open = open

    def boom(path, *a, **kw):
        if str(path).endswith(".jsonl"):
            raise OSError(28, "No space left on device")
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", boom)
    with pytest.raises(OSError):
        j.append(rec(st.INTENDED), root=tmp_path)


def test_an_fsync_failure_also_raises(tmp_path, monkeypatch):
    """A record that reached an OS buffer and not the device is not durable, and `append`
    promises durability."""
    monkeypatch.setattr(j.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(OSError):
        j.append(rec(st.INTENDED), root=tmp_path)


def test_the_module_catches_nothing_around_its_write(tmp_path):
    """Parsed, not grepped: `append` must contain no exception handler at all."""
    tree = ast.parse(Path(j.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "append")
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.Try)], \
        "append swallows something; a journal that fails open is not a journal"


def test_the_write_is_flushed_and_fsynced(tmp_path):
    tree = ast.parse(Path(j.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "append")
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert {"flush", "fsync"} <= called


# ══════════════════════════════════════════════════════════════════════════════
# transitions
# ══════════════════════════════════════════════════════════════════════════════

def test_the_first_record_for_a_key_must_be_intended(tmp_path):
    for s in (st.SUBMITTED, st.FILLED, st.PARTIAL, st.REJECTED, st.UNKNOWN):
        with pytest.raises(j.OrderJournalRefused) as e:
            j.append(rec(s, key=f"k-{s}"), root=tmp_path)
        assert e.value.code == j.BAD_TRANSITION


def test_intended_to_filled_is_refused(tmp_path):
    j.append(rec(st.INTENDED), root=tmp_path)
    with pytest.raises(j.OrderJournalRefused) as e:
        j.append(rec(st.FILLED), root=tmp_path)
    assert e.value.code == j.BAD_TRANSITION
    got, _ = j.read(root=tmp_path, day=DAY)
    assert [r.state for r in got] == [st.INTENDED], "the refused line was written anyway"


@pytest.mark.parametrize("path", [
    (st.INTENDED, st.SUBMITTED, st.FILLED),
    (st.INTENDED, st.SUBMITTED, st.UNKNOWN),
    (st.INTENDED, st.SUBMITTED, st.UNKNOWN, st.FILLED),
    (st.INTENDED, st.SUBMITTED, st.UNKNOWN, st.PARTIAL),
    (st.INTENDED, st.SUBMITTED, st.UNKNOWN, st.REJECTED),
    (st.INTENDED, st.SUBMITTED, st.PARTIAL, st.FILLED),
    (st.INTENDED, st.SUBMITTED, st.PARTIAL, st.REJECTED),
    (st.INTENDED, st.REJECTED),
    (st.INTENDED, st.UNKNOWN, st.FILLED),
])
def test_legal_histories_are_accepted(tmp_path, path):
    for s in path:
        j.append(rec(s), root=tmp_path)
    got, _ = j.read(root=tmp_path, day=DAY)
    assert [r.state for r in got] == list(path)


@pytest.mark.parametrize("terminal", [st.FILLED, st.REJECTED])
def test_a_terminal_state_cannot_transition(tmp_path, terminal):
    j.append(rec(st.INTENDED), root=tmp_path)
    j.append(rec(st.SUBMITTED), root=tmp_path)
    j.append(rec(terminal), root=tmp_path)
    for nxt in st.ORDER_STATES:
        with pytest.raises(j.OrderJournalRefused) as e:
            j.append(rec(nxt), root=tmp_path)
        assert e.value.code == j.BAD_TRANSITION


def test_two_keys_do_not_interfere(tmp_path):
    j.append(rec(st.INTENDED, key="a"), root=tmp_path)
    j.append(rec(st.INTENDED, key="b"), root=tmp_path)
    j.append(rec(st.SUBMITTED, key="a"), root=tmp_path)
    out = j.resolve(root=tmp_path, day=DAY)
    assert out["final"] == {"a": st.SUBMITTED, "b": st.INTENDED}
    # only "a" is unresolved. INTENDED is NOT: SUBMITTED is written BEFORE send_order is
    # called, so a journal ending at INTENDED means the broker was never reached. The first
    # version of this test expected both and was wrong — and being wrong about it surfaced
    # that the Stage 5U wording ("handed to the broker") had left the ordering ambiguous.
    assert out["unresolved"] == ["a"]


def test_submitted_means_written_before_the_broker_call(tmp_path):
    """The ordering rule that makes INTENDED safe to treat as 'nothing was attempted'.

    It is the same rule `track1_switch` already follows — "Every stage emits BEFORE it acts" —
    and without it a process that died inside `send_order` would leave a journal saying
    INTENDED while a live order existed.
    """
    assert st.INTENDED not in st.UNRESOLVED
    assert st.SUBMITTED in st.UNRESOLVED
    # asserted where the rule is actually written down, not where it sounded likely
    assert "before send_order is called" in st.CRASH_RECOVERY[st.INTENDED]
    assert "ATTEMPTED" in st.CRASH_RECOVERY[st.INTENDED].upper()
    assert "outcome is unknown" in st.CRASH_RECOVERY[st.SUBMITTED]
    j.append(rec(st.INTENDED, key="x"), root=tmp_path)
    assert j.resolve(root=tmp_path, day=DAY)["unresolved"] == []


# ══════════════════════════════════════════════════════════════════════════════
# corruption is reported, never skipped
# ══════════════════════════════════════════════════════════════════════════════

def test_a_corrupt_line_is_reported_by_the_reader(tmp_path):
    j.append(rec(st.INTENDED), root=tmp_path)
    p = j.journal_path(DAY, tmp_path)
    p.write_text(p.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    got, invalid = j.read(root=tmp_path, day=DAY)
    assert len(got) == 1 and len(invalid) == 1
    assert "track1_orders_20260825.jsonl:2" in invalid[0]


def test_a_corrupt_journal_refuses_to_authorise_another_order(tmp_path):
    """A journal that cannot be read whole cannot authorise an order."""
    j.append(rec(st.INTENDED), root=tmp_path)
    p = j.journal_path(DAY, tmp_path)
    p.write_text(p.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    with pytest.raises(j.OrderJournalRefused) as e:
        j.append(rec(st.SUBMITTED), root=tmp_path)
    assert e.value.code == j.UNREADABLE
    with pytest.raises(j.OrderJournalRefused):
        j.resolve(root=tmp_path, day=DAY)


def test_an_impossible_history_already_on_disk_is_refused_not_repaired(tmp_path):
    """Hand-written straight into the file, bypassing `append`."""
    p = j.journal_path(DAY, tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [rec(st.INTENDED).as_row(), rec(st.FILLED).as_row()]
    p.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(j.OrderJournalRefused) as e:
        j.resolve(root=tmp_path, day=DAY)
    assert e.value.code == j.BAD_TRANSITION


# ══════════════════════════════════════════════════════════════════════════════
# the record itself
# ══════════════════════════════════════════════════════════════════════════════

def test_an_unknown_state_is_refused_at_construction():
    with pytest.raises(j.OrderJournalRefused) as e:
        rec("probably_filled")
    assert e.value.code == j.BAD_RECORD


def test_a_missing_required_field_is_refused_at_construction():
    for blank in ("sleeve", "instrument", "tradable_symbol", "action", "candidate_id",
                  "ref_day", "created_at", "idempotency_key"):
        with pytest.raises(j.OrderJournalRefused) as e:
            rec(st.INTENDED, **{blank: ""})
        assert e.value.code == j.BAD_RECORD, blank


def test_a_record_without_the_route_stamp_is_refused():
    with pytest.raises(j.OrderJournalRefused) as e:
        rec(st.INTENDED, route="legacy")
    assert e.value.code == j.BAD_ROUTE


def test_the_reconcile_view_is_a_conversion_not_a_second_schema(tmp_path):
    r = rec(st.SUBMITTED, order_id="ib-3")
    o = r.as_order_record()
    assert isinstance(o, st.OrderRecord)
    assert o.state == st.SUBMITTED and o.idempotency_key == KEY and o.broker_order_id == "ib-3"


# ══════════════════════════════════════════════════════════════════════════════
# path safety
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("day", ["../../etc/passwd", "/abs", "2026-8-5", "20260825x",
                                 "..", "", "2026082", "202608255"])
def test_a_day_that_could_escape_the_journal_directory_is_refused(tmp_path, day):
    with pytest.raises(j.OrderJournalRefused) as e:
        j.journal_path(day, tmp_path)
    assert e.value.code == j.PATH_ESCAPE


def test_the_writer_creates_its_own_directory_but_only_inside_the_root(tmp_path):
    assert not (tmp_path / j.ORDERS_DIR).exists()
    p = j.append(rec(st.INTENDED), root=tmp_path)
    assert (tmp_path / j.ORDERS_DIR).is_dir()
    assert tmp_path.resolve() in p.resolve().parents


# ══════════════════════════════════════════════════════════════════════════════
# nothing else moved
# ══════════════════════════════════════════════════════════════════════════════

def test_the_window_ledger_is_still_best_effort_and_unchanged():
    """This module exists BECAUSE the ledger swallows. If it stopped, re-read the design."""
    tree = ast.parse(Path(wl.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_write")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers
    for h in handlers:
        assert not any(isinstance(n, ast.Raise) for n in ast.walk(h))


def test_classify_slot_row_is_still_independent_of_order_words():
    from global_index import track1_shadow_acceptance as acc
    tree = ast.parse(Path(acc.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "classify_slot_row")
    read = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for w in ("filled", "submitted", "order_state", "fill", "intended"):
        assert w not in read, w
    assert "decided" in read


def test_this_module_cannot_reach_a_broker():
    tree = ast.parse(Path(j.__file__).read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
    assert "ib_insync" not in imported
    assert not any("ibkr" in m.lower() for m in imported), imported
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for forbidden in ("send_order", "placeOrder", "connect", "IBKRBroker", "get_positions"):
        assert forbidden not in called, forbidden


def test_no_production_call_site_sends_an_order():
    from global_index import run_live_day_track1 as R
    text = Path(R.__file__).read_text(encoding="utf-8")
    for token in ("placeOrder", "MarketOrder", "LimitOrder"):
        assert token not in text, token
    tree = ast.parse(text)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "IBKRBroker"]


def _importers(name: str) -> list:
    """Which files in global_index/ IMPORT `name`, by AST.

    Not a substring scan. A substring scan counts the module's own docstring saying it is
    imported by nothing, and it counts a mention in a comment - the mistake Stage 5T made
    with "ib_insync" and Stage 5W repeated with a half-checked import node.
    """
    import ast as _ast
    out = []
    for p in (REPO / "global_index").rglob("*.py"):
        if p.name == name + ".py":
            continue
        try:
            tree = _ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in _ast.walk(tree):
            if not isinstance(n, (_ast.Import, _ast.ImportFrom)):
                continue
            mod = getattr(n, "module", "") or ""
            if name in mod or any(name in a.name for a in n.names):
                out.append(p.name)
                break
    return sorted(set(out))


def test_the_journal_is_wired_into_nothing_that_runs():
    """Stage 5W's executor imports the journal, and nothing imports the executor.

    By AST rather than substring: this file's own name appears in prose in several modules,
    and a text scan cannot tell a mention from an import.
    """
    assert _importers("track1_order_journal") == ["track1_paper_callsite.py",
                                                  "track1_paper_executor.py"]
    assert _importers("track1_paper_callsite") == [], (
        "the journal is now reachable from production through the dry-run module")
    assert _importers("track1_paper_executor") == ["track1_paper_callsite.py"]


def test_no_real_runtime_journal_was_created_by_this_suite():
    assert not (REPO / j.ORDERS_DIR).exists(), (
        "this suite wrote into the REAL runtime tree; every journal must live under tmp_path")


def test_nothing_in_this_suite_armed_anything():
    import os as _os
    from global_index import track1_gates as gates
    assert not Path(gates.CONFIRMATION_PATH).exists()
    assert _os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "")
    assert gates.may_enable_orders()[0] is False
