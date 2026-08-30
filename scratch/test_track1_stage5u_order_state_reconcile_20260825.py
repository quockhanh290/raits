"""Stage 5U — order state and startup reconcile, as testable contracts.

READ-ONLY of production data. No broker, no connection, no order, no confirmation file,
no `--allow-orders`. Every function under test is pure: it takes data and returns a verdict.

The two things being pinned
---------------------------
**A.** `intended` is never `filled`, and `decided` never comes to depend on a fill. If it did,
a broker outage would read as the strategy having stopped deciding, and the shadow evidence and
the paper evidence would stop being comparable — which is the premise the readiness gate rests
on.

**B.** Reconcile has THREE answers. `get_positions()` warns and returns its last read when the
subscription never settles, so a caller cannot tell truth from guess. UNKNOWN blocks entries
exactly as MISMATCH does — the `scheduler_processes() -> []` mistake cost six entry slots and
this is the same shape.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(r"d:\raits")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_order_state as os_  # noqa: E402
from global_index import window_ledger as wl        # noqa: E402

P = os_.Position


def rec(key, state, inst="MNQ", qty=1, direction="LONG", sleeve="roska4_swing"):
    return os_.OrderRecord(trade_id=key, sleeve=sleeve, instrument=inst,
                           tradable_symbol=inst, direction=direction, qty=qty,
                           state=state, ref_day="2026-08-25", idempotency_key=key)


# ══════════════════════════════════════════════════════════════════════════════
# A. the state machine
# ══════════════════════════════════════════════════════════════════════════════

def test_the_six_states_are_distinct_and_rejected_is_not_unknown():
    """"No" and "I could not hear you" are different facts. Treating the second as the first
    is how a filled order becomes a position nobody believes in."""
    assert len(set(os_.ORDER_STATES)) == 6
    assert os_.REJECTED != os_.UNKNOWN
    assert os_.UNKNOWN in os_.UNRESOLVED and os_.SUBMITTED in os_.UNRESOLVED
    assert os_.REJECTED not in os_.UNRESOLVED
    assert os_.TERMINAL == {os_.FILLED, os_.PARTIAL, os_.REJECTED}


def test_an_intended_order_can_never_become_filled_without_being_submitted():
    """The whole of question A in one assertion."""
    assert not os_.transition_allowed(os_.INTENDED, os_.FILLED)
    assert not os_.transition_allowed(os_.INTENDED, os_.PARTIAL)
    assert os_.transition_allowed(os_.INTENDED, os_.SUBMITTED)
    assert os_.transition_allowed(os_.SUBMITTED, os_.FILLED)


def test_terminal_states_are_terminal():
    for s in os_.TERMINAL - {os_.PARTIAL}:
        assert os_.ALLOWED_TRANSITIONS[s] == frozenset(), s
    # a PARTIAL still has a remainder that must resolve one way or the other
    assert os_.ALLOWED_TRANSITIONS[os_.PARTIAL] == frozenset({os_.FILLED, os_.REJECTED})


def test_unknown_is_resolvable_only_by_asking():
    assert os_.ALLOWED_TRANSITIONS[os_.UNKNOWN] == frozenset(
        {os_.FILLED, os_.PARTIAL, os_.REJECTED})
    assert os_.SUBMITTED not in os_.ALLOWED_TRANSITIONS[os_.UNKNOWN]


def test_an_unknown_state_string_is_refused_at_construction():
    with pytest.raises(ValueError):
        rec("k", "probably_filled")


def test_the_journal_reports_an_impossible_history_rather_than_smoothing_it():
    """A reader that quietly repairs the journal is a reader that can be lied to."""
    out = os_.resolve_journal([rec("a", os_.INTENDED), rec("a", os_.FILLED)])
    assert out["impossible"] == ["a: intended -> filled"]
    assert out["final"]["a"] == os_.INTENDED       # the impossible step is NOT applied


def test_unresolved_orders_are_exactly_the_ones_that_leave_us_unable_to_say():
    j = [rec("a", os_.INTENDED), rec("a", os_.SUBMITTED),
         rec("b", os_.INTENDED), rec("b", os_.SUBMITTED), rec("b", os_.FILLED),
         rec("c", os_.INTENDED), rec("c", os_.REJECTED),
         rec("d", os_.INTENDED), rec("d", os_.UNKNOWN)]
    assert os_.unresolved_orders(j) == ["a", "d"]


def test_every_state_has_a_written_crash_recovery():
    assert set(os_.CRASH_RECOVERY) == set(os_.ORDER_STATES)
    for state, text in os_.CRASH_RECOVERY.items():
        assert len(text) > 40, state
    assert "flat" in os_.SWITCH_FLAT_RECOVERY


# ══════════════════════════════════════════════════════════════════════════════
# A. why the ledger cannot own it
# ══════════════════════════════════════════════════════════════════════════════

def test_the_window_ledger_swallows_write_failures_by_design():
    """This is WHY order state needs its own journal. The ledger's contract is to never block
    a trading path; a write-ahead log's contract is the opposite. Parsed, not grepped."""
    tree = ast.parse(Path(wl.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_write")
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers, "_write no longer swallows — re-read whether the journal is still needed"
    # it catches broad Exception and does not re-raise
    assert any(h.type is None or getattr(h.type, "id", "") == "Exception" for h in handlers)
    for h in handlers:
        assert not any(isinstance(n, ast.Raise) for n in ast.walk(h))


def test_the_ledgers_decided_field_does_not_mention_orders():
    """`decided` must keep meaning 'the route reached a decision'. If a paper implementation
    ever makes it depend on a fill, shadow and paper evidence stop being comparable."""
    from global_index import track1_shadow_acceptance as acc
    tree = ast.parse(Path(acc.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "classify_slot_row")
    read = {n.value for n in ast.walk(fn)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    for order_word in ("filled", "order_state", "submitted", "fill"):
        assert order_word not in read, order_word
    assert "decided" in read


# ══════════════════════════════════════════════════════════════════════════════
# B. startup reconcile
# ══════════════════════════════════════════════════════════════════════════════

def test_a_clean_book_matches_and_allows_entries():
    r = os_.reconcile([P("MNQ", "LONG", 1)], [P("MNQ", "LONG", 1)], shared_account=False)
    assert r.verdict == os_.MATCH
    assert r.blocks_entries is False and r.allows_exits is True


def test_an_unsettled_broker_read_is_UNKNOWN_not_a_match():
    """`get_positions` warns and returns its last read when it never settles. The caller must
    not read that as truth — the third time a status reader in this project has had no way to
    say 'I do not know', and the first cost six entry slots."""
    r = os_.reconcile([], [], broker_settled=False)
    assert r.verdict == os_.RECONCILE_UNKNOWN
    assert r.blocks_entries is True and r.allows_exits is True
    assert "broker_positions_unsettled" in r.reasons


def test_a_missing_broker_list_is_UNKNOWN_not_flat():
    r = os_.reconcile([P("MNQ", "LONG", 1)], None)
    assert r.verdict == os_.RECONCILE_UNKNOWN and r.blocks_entries is True


def test_book_says_held_broker_says_flat_is_a_mismatch():
    """The close-filled/open-failed case after `persist_flat` raised."""
    r = os_.reconcile([P("MNQ", "LONG", 1)], [], shared_account=False)
    assert r.verdict == os_.MISMATCH and r.blocks_entries is True
    assert r.detail["disagreements"]["MNQ"] == {"book_expects": 1, "broker_reports": 0}


def test_broker_holds_something_the_route_does_not_trade():
    """A leftover full-size NKD position. `_to_runner` deliberately no longer maps NKD back to
    MNKD, so it arrives under a name the book does not use — and must block rather than be
    quietly adopted as MNKD, which is how the ten-times-size incident would be re-inherited."""
    r = os_.reconcile([], [P("NKD", "LONG", 1)], shared_account=False)
    assert r.verdict == os_.MISMATCH
    assert r.detail["unrecognised"] == ["NKD"]
    assert "broker_holds_an_instrument_the_route_does_not" in r.reasons


def test_an_unresolved_order_is_UNKNOWN_even_when_positions_agree():
    j = [rec("a", os_.INTENDED), rec("a", os_.SUBMITTED)]
    r = os_.reconcile([P("MNQ", "LONG", 1)], [P("MNQ", "LONG", 1)],
                      journal=j, shared_account=False)
    assert r.verdict == os_.RECONCILE_UNKNOWN
    assert r.blocks_entries is True
    assert r.detail["unresolved_orders"] == ["a"]


def test_an_impossible_journal_history_is_a_mismatch_not_an_unknown():
    j = [rec("a", os_.INTENDED), rec("a", os_.FILLED)]
    r = os_.reconcile([], [], journal=j, shared_account=False)
    assert r.verdict == os_.MISMATCH
    assert r.detail["impossible_history"] == ["a: intended -> filled"]


def test_entries_are_blocked_and_exits_allowed_in_every_bad_case():
    """Refusing to REDUCE exposure while the book is confused is the wrong failure direction."""
    cases = [
        os_.reconcile([], [], broker_settled=False),
        os_.reconcile([P("MNQ", "LONG", 1)], [], shared_account=False),
        os_.reconcile([], [P("NKD", "LONG", 1)], shared_account=False),
        os_.reconcile([], [], journal=[rec("a", os_.INTENDED), rec("a", os_.SUBMITTED)],
                      shared_account=False),
    ]
    for r in cases:
        assert r.blocks_entries is True, r.verdict
        assert r.allows_exits is True, r.verdict


def test_long_and_short_net_the_way_the_broker_reports_them():
    """`ib.positions()` returns a signed net per contract. Both sides must use one convention
    or a LONG 1 against a SHORT 1 reads as agreement."""
    r = os_.reconcile([P("MNQ", "LONG", 1)], [P("MNQ", "SHORT", 1)], shared_account=False)
    assert r.verdict == os_.MISMATCH
    assert r.detail["disagreements"]["MNQ"] == {"book_expects": 1, "broker_reports": -1}


# ── the B1 constraint, which decides what reconcile can prove at all ─────────────────────

def test_on_a_shared_account_reconcile_can_only_check_the_combined_net():
    """B1. One IB Gateway login is one position book: `get_positions()` returns the NET per
    contract for BOTH routes, so the strongest available statement is
    broker == track1 + legacy. It detects disagreement; it cannot ATTRIBUTE it."""
    r = os_.reconcile([P("MNQ", "LONG", 1)], [P("MNQ", "LONG", 2)],
                      legacy_book=[P("MNQ", "LONG", 1)], shared_account=True)
    assert r.verdict == os_.MATCH, r.detail
    # and the same broker truth is a MISMATCH once the account is Track 1's alone
    r2 = os_.reconcile([P("MNQ", "LONG", 1)], [P("MNQ", "LONG", 2)], shared_account=False)
    assert r2.verdict == os_.MISMATCH


def test_on_a_shared_account_equal_and_opposite_errors_CANCEL_and_are_invisible():
    """The uncomfortable half, and the strongest argument for closing B1 before paper.

    reality:  Track 1 holds LONG 1, legacy holds LONG 1, so the broker nets LONG 2.
    belief:   Track 1's book claims LONG 2, legacy's book claims LONG 0.

    The combined expectation is 2 and the broker reports 2, so reconcile says MATCH and
    ALLOWS ENTRIES — while Track 1's book is wrong by a whole contract. Nothing in this
    design can see that, because `get_positions()` reports one net per contract for both
    routes and there is no field to attribute it with.

    The first version of this test asserted the opposite and passed, because the case it
    built (legacy claiming a SHORT it does not hold) is one that IS caught. Getting this
    right matters: it is the difference between "reconcile has a limitation" and "reconcile
    covers it".
    """
    r = os_.reconcile([P("MNQ", "LONG", 2)],                 # Track 1 believes 2 (truth: 1)
                      [P("MNQ", "LONG", 2)],                 # broker nets 2 (1 + 1)
                      legacy_book=[P("MNQ", "LONG", 0)],     # legacy believes 0 (truth: 1)
                      shared_account=True)
    assert r.verdict == os_.MATCH
    assert r.blocks_entries is False        # <- the hole, asserted rather than described

    # With a dedicated account the same broker truth is caught immediately.
    exact = os_.reconcile([P("MNQ", "LONG", 2)], [P("MNQ", "LONG", 1)], shared_account=False)
    assert exact.verdict == os_.MISMATCH
    assert exact.blocks_entries is True


# ══════════════════════════════════════════════════════════════════════════════
# nothing here can trade
# ══════════════════════════════════════════════════════════════════════════════

def test_this_module_cannot_reach_a_broker():
    tree = ast.parse(Path(os_.__file__).read_text(encoding="utf-8"))
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module.split(".")[0])
    assert "ib_insync" not in imported
    assert not (imported & {"global_index"}), "pure: it takes data, not modules that connect"
    called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    for forbidden in ("send_order", "placeOrder", "connect", "get_positions", "IBKRBroker"):
        assert forbidden not in called, forbidden


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


def test_it_is_wired_into_nothing_that_runs():
    """These modules form a chain that ends outside production, and that is the guarantee.

    Stage 5W added `track1_paper_executor`, which imports all three - so "imported by
    nothing" is no longer the right assertion for the pieces. What must stay true is that the
    one module at the head of the chain is itself imported by nothing, which keeps the whole
    chain unreachable. Stage 5W owns that assertion; it is repeated here so this suite fails
    too if the head is ever wired in.
    """
    assert _importers("track1_order_state") == ["track1_broker_read.py",
                                                "track1_order_journal.py",
                                                "track1_paper_callsite.py",
                                                "track1_paper_executor.py"]
    assert _importers("track1_order_journal") == ["track1_paper_callsite.py",
                                                  "track1_paper_executor.py"]
    assert _importers("track1_paper_order") == ["track1_paper_callsite.py",
                                                "track1_paper_executor.py"]
    # Stage 5Z put a single head back on the chain: the dry run imports the executor and the
    # read side, and nothing imports the dry run. That is a STRONGER guarantee than the two
    # heads 5X left - there is one door to watch instead of two.
    assert _importers("track1_paper_executor") == ["track1_paper_callsite.py"]
    assert _importers("track1_broker_read") == ["track1_paper_callsite.py"]
    assert _importers("track1_paper_callsite") == [], (
        "the head of the chain is now imported by production; every module below it just "
        "became reachable")


def test_nothing_in_this_suite_armed_anything():
    import os as _os
    from global_index import track1_gates as gates
    assert not Path(gates.CONFIRMATION_PATH).exists()
    assert _os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "")
    assert gates.may_enable_orders()[0] is False
