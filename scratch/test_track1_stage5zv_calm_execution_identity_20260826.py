"""Stage 5ZV — shadow and paper must be the same trade, or shadow evidence is worth nothing.

Stage 5ZU made Calm judgeable by letting the gate see the 10:00 OPEN from a closed one-minute
bar at 10:01. That is enough for SHADOW and not enough for PAPER: an order sent at 10:01
cannot fill at an open that happened a minute earlier, so a shadow row claiming the 10:00 open
would be claiming a fill paper could never achieve.

The measurement that settles it: the rule reads the prior RTH session and today's 09:30 OPEN,
and 407 of 421 frozen setups reproduce from a frame TRUNCATED at 09:30. So the decision is
computable from closed bars at 09:31:00 and the entry is at 10:00 — **twenty-nine minutes of
slack**. The original contract is tradable; the entry does not have to move.

Moving it was measured too, over 416 comparable rows on one consistent read:

    10:00 (the record)  $14,776   mean $35.5   win 61.5%
    10:01               $13,606   -$1,170 (-7.9%)   18 trades flip sign
    10:05               $14,726   -$51   (-0.3%)    29 trades flip sign, stdev nearly double

The 10:05 total barely moves while its per-trade spread nearly doubles — the aggregate hides
the change rather than showing there is none.
"""
from __future__ import annotations

import ast
import csv
from pathlib import Path

import pandas as pd
import pytest

from global_index import track1_calm_a as ca
from global_index import track1_intraday as ti

REPO = Path(r"d:\raits")
ARTIFACT = REPO / "scratch/calm_pcloc_not_deep_gap_trade_list.csv"


# ══════════════════════════════════════════════════════════════════════════════
# A. the contract is self-consistent, and it does not move the entry
# ══════════════════════════════════════════════════════════════════════════════

def test_1_the_contract_passes_its_own_structural_rules():
    assert ca.CalmExecutionContract().self_check() == []


def test_2_the_entry_price_definition_is_the_strategy_identity():
    c, p = ca.CalmExecutionContract(), ca.CalmAParams()
    assert c.entry_reference_time == p.entry_time == "10:00"
    assert c.exit_reference_time == p.exit_time == "15:55"


def test_3_an_order_sent_at_a_different_instant_from_its_reference_is_refused():
    """The whole stage in one assertion: this is the shape that lets shadow claim a fill
    paper cannot achieve."""
    bad = ca.CalmExecutionContract(order_sent_at="10:01")
    errs = bad.self_check()
    assert errs, "sending at 10:01 while pricing at the 10:00 open was accepted"
    assert any("nobody can achieve" in e for e in errs), errs


def test_4_the_reference_cannot_be_readable_before_its_own_bar():
    bad = ca.CalmExecutionContract(entry_reference_readable_from="10:00")
    assert any("closed bar at or before" in e for e in bad.self_check())


def test_5_the_intent_must_be_journalled_before_the_order_is_sent():
    """The fixture trips the ordering rule and NOTHING ELSE, and the message is asserted.

    Rewritten after the mutation sweep. The first version used `order_sent_at="09:59"`, which
    also breaks the send-equals-reference rule — so `self_check()` stayed non-empty with the
    ordering check disabled entirely and the test passed for a rule it was not testing. A bare
    "is non-empty" over a validator with five rules cannot say which one fired.
    """
    bad = ca.CalmExecutionContract(intent_journalled_by="10:01")   # after the send instant
    errs = bad.self_check()
    assert errs, "an intent journalled after the order is sent was accepted"
    assert any("before the order is sent" in e for e in errs), errs
    assert len(errs) == 1, ("the fixture trips more than the ordering rule, so this test "
                            f"cannot attribute the failure: {errs}")


@pytest.mark.parametrize("field,value", [("entry_reference_time", "10:05"),
                                         ("exit_reference_time", "15:50")])
def test_6_moving_a_reference_off_the_strategy_is_refused(field, value):
    bad = ca.CalmExecutionContract(**{field: value})
    assert any("disagree" in e for e in bad.self_check()), bad.self_check()


# ══════════════════════════════════════════════════════════════════════════════
# B. the measurement the decision rests on
# ══════════════════════════════════════════════════════════════════════════════

def test_7_the_rule_reads_only_the_prior_session_and_the_0930_open():
    """By signature and by AST: `entry_conditions` takes two things, and the causal detector
    hands it exactly the prior session row and the 09:30 open."""
    import inspect

    params = list(inspect.signature(ca.entry_conditions).parameters)
    assert params[:2] == ["prev_row", "cur_rth_open"], params

    # Stage 5ZX: the rule moved into the pre-entry half that the detector is built on. Counted
    # across both halves it is still evaluated exactly once — which is the property. Counting
    # inside one half would now report zero and pass nothing useful.
    src = (REPO / "global_index/track1_calm_a.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    CAUSAL = ("detect_entry_for_day", "detect_setup_before_entry")
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name in CAUSAL]
    assert len(fns) == len(CAUSAL), f"the causal path lost a half: {[f.name for f in fns]}"
    calls = [n for f in fns for n in ast.walk(f) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "entry_conditions"]
    assert len(calls) == 1, "the causal path evaluates the rule somewhere else too"
    # and the full detector delegates rather than restating it
    full = next(f for f in fns if f.name == "detect_entry_for_day")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "detect_setup_before_entry" for n in ast.walk(full)), \
        "the detector no longer delegates — two copies of one rule will drift"


def test_8_the_setup_needs_nothing_after_0930():
    """Behavioural. Two identical inputs must give an identical answer, so the claim is that
    the ONLY thing after 09:30 the rule could want is the 09:30 open itself — which exists at
    09:30:00 and is carried by a closed one-minute bar at 09:31:00."""
    prev = pd.Series({"open": 100.0, "high": 105.0, "low": 95.0, "close": 97.0})
    p = ca.CalmAParams()
    a = ca.entry_conditions(prev, 99.0, p)
    b = ca.entry_conditions(prev, 99.0, p)
    assert a == b
    assert a is not None, "the fixture must set up, or this test proves nothing"
    c = ca.CalmExecutionContract()
    assert c.setup_known_from < c.order_sent_at
    # twenty-nine minutes of slack, stated as a number rather than a feeling
    lo = pd.Timestamp(f"2026-01-01 {c.setup_known_from}")
    hi = pd.Timestamp(f"2026-01-01 {c.order_sent_at}")
    assert (hi - lo) == pd.Timedelta(minutes=29)


def test_9_the_artifact_still_says_the_entry_is_the_1000_open():
    rows = list(csv.DictReader(ARTIFACT.open(encoding="utf-8")))
    assert len(rows) == 421
    assert {pd.Timestamp(r["entry_time"]).strftime("%H:%M") for r in rows} == {"10:00"}
    assert {pd.Timestamp(r["signal_time"]).strftime("%H:%M") for r in rows} == {"09:30"}


# ══════════════════════════════════════════════════════════════════════════════
# C. what shadow may and may not claim
# ══════════════════════════════════════════════════════════════════════════════

def test_10_shadow_may_not_record_a_fill():
    never = set(ca.SHADOW_MAY_RECORD["never_in_shadow"])
    assert {"fill_price", "fill_time", "realised_pnl", "slippage"} <= never


def test_11_the_reference_price_is_recorded_only_after_its_bar_closes():
    before = set(ca.SHADOW_MAY_RECORD["before_entry"])
    after = set(ca.SHADOW_MAY_RECORD["after_reference_bar_closes"])
    assert "entry_reference_price" in after
    assert "entry_reference_price" not in before, (
        "shadow would record a price before the bar carrying it exists")
    assert before & after == set(), "a field on both sides of the entry says nothing"


def test_11b_the_planned_stop_price_is_not_a_before_entry_fact():
    """Calm's stop is `entry - 1.5 x ATR`, so a concrete stop price cannot be known before
    the 10:00 reference exists. Before-entry evidence may name the stop rule and risk inputs;
    the price belongs after the reference bar is observable."""
    before = set(ca.SHADOW_MAY_RECORD["before_entry"])
    after = set(ca.SHADOW_MAY_RECORD["after_reference_bar_closes"])
    assert "planned_stop" not in before
    assert {"stop_rule", "risk_inputs"} <= before
    assert "planned_stop" in after


def test_11c_calm_stop_price_depends_on_the_entry_reference():
    p = ca.CalmAParams()
    atr = 12.5
    a = ca.disaster_stop(5000.0, atr, p)
    b = ca.disaster_stop(5001.0, atr, p)
    assert b - a == 1.0


def test_12_the_three_groups_do_not_overlap():
    groups = [set(v) for v in ca.SHADOW_MAY_RECORD.values()]
    assert groups, "the mapping is empty"
    for i, a in enumerate(groups):
        for b in groups[i + 1:]:
            assert a & b == set(), a & b


def test_13_paper_only_evidence_names_the_things_shadow_cannot_stand_in_for():
    joined = " ".join(ca.PAPER_ONLY_EVIDENCE).lower()
    for must in ("fill", "slippage", "stop"):
        assert must in joined, must


# ══════════════════════════════════════════════════════════════════════════════
# D. the machinery this contract needs already exists, and orders stay impossible
# ══════════════════════════════════════════════════════════════════════════════

def test_14_the_journal_already_distinguishes_intended_from_submitted():
    """Option A needs a durable record that an order is INTENDED before it is sent. Stage 5V
    built exactly that; this stage does not need to invent it."""
    from global_index import track1_order_state as st

    assert st.INTENDED in st.ORDER_STATES
    assert st.SUBMITTED in st.ORDER_STATES
    assert st.INTENDED != st.SUBMITTED


def test_15_nothing_here_wired_an_order_send():
    """The contract is a declaration. It must not have grown a broker."""
    src = (REPO / "global_index/track1_calm_a.py").read_text(encoding="utf-8")
    names = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    for forbidden in ("IBKRBroker", "send_order", "place_order", "submit"):
        assert forbidden not in (names | attrs), forbidden


def test_16_orders_are_still_impossible():
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


def test_17_the_splice_guard_is_untouched():
    from global_index import track1_gates as g

    released, detail = g.live_frame_wiring()
    assert released is True, detail


def test_18_the_5zu_gate_contract_is_unchanged_by_this_stage():
    """This stage decides WHICH contract to trade. It does not re-open the gate work."""
    r = ti.REQUIREMENTS["roska4_calm"]
    assert r.decision_bar is None
    assert r.required_context_through == "09:55"
    assert r.required_entry_quote_time == "10:00"
    assert r.decision_grace_seconds == 180


def test_19_the_gate_span_is_at_least_as_wide_as_the_rule_needs():
    """5ZU chose 09:55 conservatively; the rule measurably needs only the 09:30 open. The
    declared span must never be NARROWER than what the rule reads, in either direction of a
    future edit."""
    r = ti.REQUIREMENTS["roska4_calm"]
    c = ca.CalmExecutionContract()
    assert r.today_from <= "09:30"
    assert r.required_context_through >= "09:30"
    assert r.required_context_through < c.entry_reference_time
