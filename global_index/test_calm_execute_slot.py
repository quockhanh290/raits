"""The Calm evidence phases must have a real 10:00 execution pass."""

from global_index import track1_intraday as intra
from global_index import track1_slots as slots
from global_index import track1_signals as signals


def test_calm_has_decide_execute_and_observe_in_contract_order():
    calm = [s for s in slots.TRACK1_SLOTS if s.sleeve == "roska4_calm"]
    assert [(s.id, s.phase, s.hour, s.minute) for s in calm] == [
        ("TRACK1_CALM_DECIDE_0932", "DECIDE", 9, 32),
        ("TRACK1_CALM_EXECUTE_1000", "EXECUTE", 10, 0),
        ("TRACK1_CALM_OBSERVE_1002", "OBSERVE", 10, 2),
    ]


def test_calm_execute_needs_the_closed_0959_bar_not_the_1000_open():
    """EXECUTE sends a market order at 10:00:00; a one-minute bar stamped 10:00 closes at 10:01:00.

    It used to require that bar and refused `entry_quote_absent` on 2 of 2 recorded runs
    (2026-10-02, 2026-10-05). Everything else about the requirement is the unphased Calm
    contract's, and the halves that run AFTER 10:00 still read the 10:00 OPEN.
    """
    req = intra.requirement_for("roska4_calm", "EXECUTE")
    base = intra.REQUIREMENTS["roska4_calm"]
    assert req.required_entry_quote_time == "09:59"
    assert req.required_context_through == base.required_context_through == "09:55"
    assert req.decide_from == req.decide_to == "10:00"
    assert (req.bar_minutes, req.needs_prior_rth) == (base.bar_minutes, base.needs_prior_rth)
    # The one other difference: this slot SENDS, so it may start a few seconds late and not minutes.
    assert req.decision_grace_seconds == 30 < base.decision_grace_seconds == 180
    assert base.required_entry_quote_time == "10:00"
    assert intra.requirement_for("roska4_calm", "OBSERVE").required_entry_quote_time == "10:00"


def test_calm_refusal_exposes_the_concrete_gate_cause():
    row = {
        "status": signals.SLOT_REFUSED,
        "reason": "gate_refused",
        "detail": "entry_quote_absent",
    }
    assert signals.one_line(row) == (
        "Signal: REFUSED · gate_refused · "
        "Entry quote unavailable (10:00 OPEN not present)"
    )
    assert signals.label("entry_quote_absent") == (
        "Entry quote unavailable (10:00 OPEN not present)"
    )
