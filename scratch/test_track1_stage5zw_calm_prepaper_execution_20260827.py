"""Stage 5ZW — the one invariant the Calm pre-paper plan must not be implemented without.

This stage is a PLAN, not an order-send implementation. But its central constraint is
testable today, and a constraint that is only written down is one the implementation discovers
after the fact: **shadow intent must never be written into the order journal.**

Measured: FOUR readers treat the existence of `global_index/track1_runtime/orders/` as meaning
the route has acted.

    b1_book_repair.route_has_never_traded   refuses the book repair if it exists
    track1_paper_callsite                   guards the production root against it
    track1_report                           reports NOT_PRODUCED while it is absent
    the shadow-window runbook               "an order journal was written - stop and investigate"

Writing a shadow intent there would make all four say the route has traded, on a day it sent
nothing. So the plan puts shadow intent in its own stream, and these tests hold that line
before anyone implements it.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from global_index import track1_calm_a as ca
from global_index import track1_order_journal as journal

REPO = Path(r"d:\raits")

#: Where Stage 5ZW proposes shadow intent goes. Deliberately NOT the order journal, and
#: deliberately not `shadow/` either — that already holds per-slot explanations and a reader
#: counting rows there would start counting intents.
SHADOW_INTENT_DIR = "global_index/track1_runtime/shadow_intent"


def test_1_the_proposed_stream_is_not_the_order_journal():
    assert SHADOW_INTENT_DIR != journal.ORDERS_DIR
    assert not SHADOW_INTENT_DIR.startswith(journal.ORDERS_DIR)
    assert not journal.ORDERS_DIR.startswith(SHADOW_INTENT_DIR)


def test_2_the_proposed_stream_is_not_an_existing_one():
    """A new fact needs a new place. Folding it into a stream a reader already counts is how
    'the route explained something' becomes 'the route ordered something'."""
    existing = {"audits", "data_observation", "shadow", "signals", "slot_timing",
                "window_coverage", "orders"}
    assert Path(SHADOW_INTENT_DIR).name not in existing


@pytest.mark.parametrize("module,why", [
    ("global_index/b1_book_repair.py",
     "refuses the book repair when the order journal exists"),
    ("global_index/track1_paper_callsite.py",
     "guards the production root against it"),
    ("global_index/track1_report.py",
     "reports NOT_PRODUCED while it is absent"),
])
def test_3_the_readers_that_depend_on_the_order_journals_absence_still_do(module, why):
    """If any of these stops naming the orders directory, the argument for a separate stream
    has lost one of its legs and this test should say so rather than the plan drifting.

    Two forms count, and the difference is worth recording: `track1_paper_callsite` references
    the shared constant `journal.ORDERS_DIR`, while `b1_book_repair` and `track1_report` each
    define their OWN copy of the same literal. Three definitions of one path is a drift waiting
    to happen — the first version of this test accepted only the literal and went red on the
    module doing it the better way.
    """
    src = (REPO / module).read_text(encoding="utf-8")
    by_literal = journal.ORDERS_DIR in src
    by_constant = "ORDERS_DIR" in {n.attr for n in ast.walk(ast.parse(src))
                                   if isinstance(n, ast.Attribute)}
    assert by_literal or by_constant, (
        f"{module} no longer names the order journal, by literal or by constant ({why})")


def test_3b_the_orders_path_is_defined_in_three_places_and_they_agree():
    """A finding this stage records rather than fixes: the path has three definitions. They
    agree today. This fails the day they stop, which is the only way anyone would find out."""
    copies = {}
    for module in ("global_index/track1_order_journal.py", "global_index/b1_book_repair.py",
                   "global_index/track1_report.py"):
        tree = ast.parse((REPO / module).read_text(encoding="utf-8"))
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "ORDERS_DIR"
                            for t in node.targets)
                    and isinstance(node.value, ast.Constant)):
                copies[module] = node.value.value
    assert len(copies) >= 2, f"expected several independent definitions, found {copies}"
    assert len(set(copies.values())) == 1, copies
    assert set(copies.values()) == {journal.ORDERS_DIR}, copies


def test_4_the_runbook_still_treats_an_order_journal_as_something_to_stop_for():
    rb = (REPO / "docs/futures/TRACK1_SHADOW_WINDOW_RUNBOOK.md").read_text(encoding="utf-8")
    assert "track1_runtime/orders/" in rb
    assert "stop and investigate" in rb


def test_5_no_order_journal_exists_today():
    """The state the whole argument rests on. If this ever fails, something wrote one."""
    assert not (REPO / journal.ORDERS_DIR).exists(), (
        "an order journal exists — the route has acted, or something wrote where it must not")


# ══════════════════════════════════════════════════════════════════════════════
# the contract the plan implements, and the phase times it needs
# ══════════════════════════════════════════════════════════════════════════════

def test_6_the_three_phases_have_the_times_the_plan_names():
    c = ca.CalmExecutionContract()
    assert c.setup_known_from == "09:31"      # DECIDE may run any time after this
    assert c.order_sent_at == "10:00"          # SEND, paper only, not built
    assert c.entry_reference_readable_from == "10:01"   # OBSERVE may run after this
    assert c.self_check() == []


def test_7_the_decide_phase_has_room_before_the_send():
    """A DECIDE job at 09:32 sits inside the slack and before the send instant."""
    c = ca.CalmExecutionContract()
    assert c.setup_known_from < "09:32" < c.intent_journalled_by < c.order_sent_at


def test_8_the_observe_phase_cannot_run_before_its_bar_closes():
    c = ca.CalmExecutionContract()
    assert c.entry_reference_readable_from > c.entry_reference_time


def test_9_the_stop_level_is_the_only_thing_that_waits_for_the_entry():
    """The 5ZV correction, held as a property rather than a list.

    The stop DISTANCE is a multiple of ATR and does not move with the entry; the dollar risk
    is that distance times contract value and cancels the entry out; the size is a sleeve
    constant. Only the LEVEL waits.
    """
    p = ca.CalmAParams()
    atr = 12.0
    a, b = 5000.0, 5123.75
    da = a - ca.disaster_stop(a, atr, p)
    db = b - ca.disaster_stop(b, atr, p)
    assert da == db == p.disaster_stop_atr_mult * atr
    assert ca.disaster_stop(a, atr, p) != ca.disaster_stop(b, atr, p), (
        "the stop LEVEL must move with the entry, or it is not entry-anchored at all")

    before = set(ca.SHADOW_MAY_RECORD["before_entry"])
    after = set(ca.SHADOW_MAY_RECORD["after_reference_bar_closes"])
    assert {"stop_rule", "risk_inputs"} <= before
    assert "planned_stop" in after and "planned_stop" not in before


# ══════════════════════════════════════════════════════════════════════════════
# nothing here armed anything
# ══════════════════════════════════════════════════════════════════════════════

def test_10_the_send_phase_is_still_unbuilt():
    """The plan describes it; the code must not have grown it."""
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    assert "NoOrderBroker" in names
    assert "IBKRBroker" not in names


def test_11_orders_are_still_impossible():
    from global_index import track1_gates as g

    assert g.may_enable_orders()[0] is False
    # Stage 5ZZZ-E. The confirmation file leaves this list, for the reason Stage 5ZZS restated
    # it in four suites and 5ZZW and 5ZZZ-A in several more: the operator signed it deliberately
    # on 2026-08-27, and asserting its absence asserts that nobody decided anything. What still
    # holds is that a decision on disk must be a SIGNED one - an unsigned file appearing here
    # would be something a run had dropped.
    _conf = REPO / g.CONFIRMATION_PATH
    if _conf.exists():
        import json as _json
        assert (_json.loads(_conf.read_text(encoding="utf-8")).get("confirmed_by") or "").strip()


def test_12_the_blockers_are_whatever_the_registry_says_not_a_frozen_list():
    """Written as a property because the roster moved twice in two days — REGIME_LABEL_
    VERIFICATION passed for the first time on 2026-08-26. Pinning the list is how a dozen
    unrelated suites went red; pinning the PROPERTY is what this is for."""
    from global_index import track1_gates as g

    # Stage 5ZZZ-E. B1 is no longer named. It CLOSED in Stage 5ZZK, and since then it opens and
    # shuts with the age of the account baseline record - it was blocking again for ninety
    # minutes on the morning of 2026-08-28 for exactly that reason. Naming it here pins a state
    # that changes on a timer, which is the very thing this test's own docstring warns against
    # one line above.
    #
    # The property it is for survives: whatever is blocking comes from the registry, and orders
    # are possible only when nothing is.
    blocking = {b.id for b in g.blocking()}
    assert blocking, "nothing is blocking at all; that is a decision, not a test result"
    assert blocking <= set(g.BLOCKERS)
    assert g.may_enable_orders()[0] is (blocking == set())
