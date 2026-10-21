"""The paper baseline's PASS sentence must describe what B1 said, not assert flatness.

Stage 2026-09-24. The gate reads statuses, so this is not a gate defect — it is worse in one
specific way: the sentence goes into a DURABLE record that a person reads weeks later to answer
"what did the account look like when this route started sending orders?". A record claiming "no
positions, no working orders" on an evening when two were open is evidence that lies.

The trigger was real and immediate. The baseline expired at 20:01 ET tonight (24 hours after it
was taken), B1 now answers `track1_holding_own_positions` rather than `legacy_and_broker_flat`,
and the very next `--record` would have written the flat sentence over a book holding MYM and
M2K.

The gate on the change, asserted below: the VERDICT and CODE must be identical in both cases.
Only the prose moves. A fix that also shifted a verdict would be a different change wearing this
one's clothes.
"""
from __future__ import annotations

import datetime as dt

from global_index import track1_account_baseline as AB
from global_index import track1_b1 as B1

NOW = dt.datetime(2026, 9, 24, 20, 30, tzinfo=dt.timezone.utc)


def account(equity: float = 251_386.16) -> AB.AccountEvidence:
    return AB.AccountEvidence(
        source="ibkr_direct", connected=True, observed_at=NOW.isoformat(),
        account_id="DUR125337", currency="USD", equity=equity,
        equity_by_currency={"USD": equity}, error="")


class _B1:
    def __init__(self, status, code, detail):
        self.status, self.code, self.detail = status, code, detail


FLAT = _B1(B1.PASS, "legacy_and_broker_flat",
           "the legacy book holds nothing, the Track 1 book holds nothing, and the broker "
           "reports 0 position(s) and 0 working order(s)")
HOLDING = _B1(B1.PASS, "track1_holding_own_positions",
              "the Track 1 book holds 2 position(s) and the order journal says this route "
              "filled every one of them; the broker holds the same instruments")


def test_1_a_flat_account_still_passes_and_still_says_so():
    r = AB.measure(account(), FLAT, now=NOW)
    assert (r.status, r.code) == (AB.PASS, AB.OK)
    assert "legacy_and_broker_flat" in r.detail


def test_2_an_accounted_for_account_passes_with_the_same_code():
    """The gate on this change. Both are PASS/OK; the difference is what the sentence says."""
    flat = AB.measure(account(), FLAT, now=NOW)
    held = AB.measure(account(), HOLDING, now=NOW)
    assert (held.status, held.code) == (flat.status, flat.code) == (AB.PASS, AB.OK)
    assert held.detail != flat.detail, (
        "the two cases produce the same sentence; whichever one it describes, it is wrong "
        "about the other")


def test_3_the_sentence_never_claims_flat_while_positions_are_held():
    """The defect, stated as the thing that must not appear."""
    held = AB.measure(account(), HOLDING, now=NOW)
    low = held.detail.lower()
    for lie in ("no positions", "no working orders", "books flat", "book flat"):
        assert lie not in low, (
            "the PASS sentence says %r while B1 reports the route holds 2 positions: %s"
            % (lie, held.detail))
    assert "track1_holding_own_positions" in held.detail


def test_4_the_equity_and_the_currency_are_still_in_the_sentence():
    """What the old sentence got right and a rewrite could quietly drop. The currency is the
    whole reason this module exists — a bare 250000 could have been Canadian dollars."""
    held = AB.measure(account(), HOLDING, now=NOW)
    assert "USD" in held.detail
    assert "251,386.16" in held.detail


def test_5_a_b1_record_with_no_code_does_not_produce_an_empty_claim():
    """Three states again. If B1 recorded nothing, the sentence must say so rather than read as
    though the account had been vouched for by something."""
    blank = AB.measure(account(), _B1(B1.PASS, None, ""), now=NOW)
    assert (blank.status, blank.code) == (AB.PASS, AB.OK)
    assert "no code recorded" in blank.detail


def test_6_the_inputs_still_carry_b1_verbatim_for_a_later_reader():
    """The sentence is a summary. The record has to keep the original, or the summary becomes
    the only account of what happened."""
    held = AB.measure(account(), HOLDING, now=NOW)
    b1_in = held.inputs["b1"]
    assert b1_in["code"] == "track1_holding_own_positions"
    assert b1_in["detail"] == HOLDING.detail
    assert b1_in["status"] == B1.PASS


def test_7_a_failing_b1_still_refuses_and_the_prose_change_did_not_reach_it():
    """The refusal paths are untouched: this was a change to one PASS sentence, and a FAIL that
    started passing would be the worst possible outcome of it."""
    bad = AB.measure(account(), _B1(B1.FAIL, "legacy_book_not_flat", "legacy holds 1"), now=NOW)
    assert bad.status == AB.FAIL
    assert bad.code == AB.B1_NOT_PASSING

    wrong_ccy = AB.AccountEvidence(
        source="ibkr_direct", connected=True, observed_at=NOW.isoformat(),
        account_id="DUR125337", currency="CAD", equity=251_386.16,
        equity_by_currency={"CAD": 251_386.16}, error="")
    assert AB.measure(wrong_ccy, HOLDING, now=NOW).code == AB.CURRENCY_WRONG


def test_8_the_sentence_that_was_there_this_morning_fails_test_3():
    """The falsifiability check, and it is not optional here.

    Tests 1-7 are green against the fixed module, which on its own is also what a test that
    checks nothing looks like. So the OLD sentence is rebuilt — by executing the real module
    source with that one f-string put back — and test_3's assertion is run against it. If the
    old form passes, test_3 is decoration and this file has proved the wrong thing.

    The module is exec'd from source in memory. Nothing on disk is patched: the scheduler is up,
    and a slot spawned during a mutation window would import the mutated file.
    """
    from pathlib import Path

    src = Path(AB.__file__).read_text(encoding="utf-8")
    fixed = 'f"{account.currency} {account.equity:,.2f}, and B1 reports {b1_code}"'
    assert src.count(fixed) == 1, "the PASS sentence moved; this mutation no longer applies"
    old = (src.replace(
        fixed
        + '\n        + (f": {b1_said}" if b1_said else "")\n'
          '        + f" — read {stale} minute(s) ago",',
        'f"{account.currency} {account.equity:,.2f}, no positions, no working orders, both '
        'books "\n        f"flat and route-stamped, read {stale} minute(s) ago",'))
    assert old != src, "the mutation did not apply; a green result here would mean nothing"

    # `@dataclass` resolves string annotations through `sys.modules[cls.__module__]`, so the
    # namespace has to be a registered module for the duration of the exec or the decorator
    # dies on a None lookup. Registered under its own name and removed afterwards, so nothing
    # else in the process can import it by accident.
    import sys
    import types

    name = "track1_account_baseline_premutation"
    mod = types.ModuleType(name)
    mod.__file__ = AB.__file__
    sys.modules[name] = mod
    try:
        exec(compile(old, AB.__file__, "exec"), mod.__dict__)               # noqa: S102
        ns = mod.__dict__
    finally:
        sys.modules.pop(name, None)

    before = ns["measure"](account(), HOLDING, now=NOW)
    assert (before.status, before.code) == (AB.PASS, AB.OK), (
        "the mutation changed the verdict as well as the prose; it is not the right mutation")
    assert "no positions" in before.detail.lower(), (
        "the pre-fix sentence did not contain the claim this file exists to remove")


# ── the same defect, second instance: the line that reaches the dashboard ────────────────────

def test_9_the_operator_line_does_not_say_flat_while_positions_are_held():
    """`operator_line` had the identical unconditional PASS prose — "broker reconcile flat" —
    and this is the copy a person actually reads, on the dashboard and in `ops status`. B1's own
    operator line needed exactly this correction earlier the same afternoon, for exactly this
    reason: a blanket PASS branch describing the words of one code."""
    held = AB.operator_line(AB.measure(account(), HOLDING, now=NOW))
    assert "flat" not in held.lower(), (
        "the operator line says flat while B1 reports the route holds positions: %s" % held)
    assert "track1_holding_own_positions" in held
    assert "USD 251,386" in held


def test_10_a_genuinely_flat_account_still_reads_the_way_it_always_did():
    """The other half. Narrowing a sentence must not cost the case it was written for."""
    flat = AB.operator_line(AB.measure(account(), FLAT, now=NOW))
    assert flat == "Paper account baseline: USD 251,386 — broker reconcile flat"


def test_11_the_other_statuses_are_untouched_by_both_edits():
    from global_index import track1_b1 as _B1mod

    bad = AB.measure(account(), _B1("FAIL", "legacy_book_not_flat", "legacy holds 1"), now=NOW)
    assert AB.operator_line(bad).startswith("Paper account NOT a safe baseline:")

    unknown = AB.measure(
        AB.account_unavailable("no broker was queried"), HOLDING, now=NOW)
    assert unknown.status == AB.UNKNOWN
    assert AB.operator_line(unknown).startswith("Paper account baseline UNKNOWN:")
    assert _B1mod.PASS == "PASS"


def test_12_an_operator_line_with_no_b1_block_still_produces_a_line():
    """The crash-avoidance property the docstring already claims, re-asserted because both edits
    now read out of `inputs` — a reporting function that can raise turns a mild problem into no
    report at all."""
    stub = AB.BaselineResult(AB.PASS, AB.OK, "detail", NOW.isoformat(), {}, {})
    assert "unrecorded amount" in AB.operator_line(stub)
