"""Stage 5ZX — Calm's two shadow phases, the intent stream, and what may be concluded from it.

Fifteen cases plus five mutations. The mutations are the point: each one performs a collapse
that would leave the system looking healthy, and asserts the corresponding test goes red. A
test that stays green under its own mutation is checking nothing, and this programme has shipped
three of those.

Nothing here connects, sends, or writes outside a temp root.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from global_index import track1_calm_a as CA
from global_index import track1_intraday as intra
from global_index import track1_paper_readiness as pr
from global_index import track1_shadow_intent as si
from global_index import track1_slots as ts

DAY = "2026-08-21"


def _code_of(fn) -> str:
    """A function's source with docstrings and comments removed.

    Substring assertions over raw source read prose as if it were code. `detect_setup_before_
    entry` says in its own docstring that it calls `_bar_open_at` once — and a test counting
    occurrences in the raw text counts that sentence, then reports the function reads two bars.
    """
    import ast
    import inspect
    import io
    import tokenize

    src = inspect.getsource(fn)
    tree = ast.parse(textwrap.dedent(src))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    out = ast.unparse(tree)
    # comments are already gone (ast drops them); this keeps the reader honest if that changes
    kept = []
    for tok in tokenize.generate_tokens(io.StringIO(out).readline):
        if tok.type != tokenize.COMMENT:
            kept.append(tok.string)
    return " ".join(kept)


def _be(**over):
    """A complete before-entry block. Every field the schema declares, so a test that trips
    ONE rule trips only that one — a fixture breaking two rules passes for the wrong reason."""
    d = {"setup": "calm_a", "instrument": "MES", "direction": "LONG", "qty": 1,
         "stop_rule": "entry - 1.5 x daily_atr",
         "risk_inputs": {"daily_atr_causal": 68.55, "point_value": 5.0,
                         "stop_atr_mult": 1.5, "stop_distance": 102.825,
                         "risk_dollars": 514.125},
         "entry_reference_time": "10:00", "intent": "would_send_at_entry_reference_time"}
    d.update(over)
    return d


def _decide(**kw):
    kw.setdefault("status", si.RECORDED)
    kw.setdefault("reason_code", si.OK)
    kw.setdefault("before_entry", _be())
    return si.decide_row("TRACK1_CALM_DECIDE_0932", DAY, **kw)


def _observe(ref=7680.75, **kw):
    kw.setdefault("status", si.RECORDED)
    kw.setdefault("reason_code", si.OK)
    kw.setdefault("before_entry", _be())
    kw.setdefault("after_reference",
                  {"entry_reference_price": ref,
                   "planned_stop": si.planned_stop_from(ref, 68.55, 1.5)})
    return si.observe_row("TRACK1_CALM_OBSERVE_1002", DAY, **kw)


# ═══════════════════════════════════════════════════════════════════════════════
# 1-5  the schema: what each phase may and may not carry
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_decide_row_carries_no_price_of_any_kind():
    """The rule the module exists for. Not 'no entry price' — no price at all."""
    row = _decide().as_dict()
    assert row["after_reference"] == {}
    blob = json.dumps(row["before_entry"])
    for forbidden in ("entry_reference_price", "planned_stop", "fill_price"):
        assert forbidden not in blob
    # and the stop is present as a RULE, which is the whole distinction
    assert row["before_entry"]["stop_rule"].startswith("entry - 1.5")


def test_2_decide_row_carrying_planned_stop_is_refused():
    """Named collapse: planned_stop written in DECIDE.

    Two defences, and the test names both because they fail differently. `decide_row` cannot
    even be ASKED for an after-reference field — the argument does not exist — so a caller
    would have to reach past it to `IntentRow`, which is where the refusal lives. Testing only
    the constructor would leave the second door unproven; testing only the builder would prove
    a TypeError and call it a safety guarantee.
    """
    with pytest.raises(TypeError):
        si.decide_row("X", DAY, status=si.RECORDED, reason_code=si.OK,
                      before_entry=_be(), after_reference={"planned_stop": 7577.9})
    with pytest.raises(si.ShadowIntentRefused) as e:
        si.IntentRow(phase=si.DECIDE, slot_id="X", session_date=DAY, status=si.RECORDED,
                     reason_code=si.OK, before_entry=_be(),
                     after_reference={"planned_stop": 7577.9})
    assert "planned_stop" in str(e.value)


def test_3_fill_fields_are_explicit_nulls_on_every_row():
    """Absent means 'no such field'; null means 'this run produced none'. Only one is true."""
    for row in (_decide().as_dict(), _observe().as_dict()):
        for k in si.NEVER_IN_SHADOW:
            assert k in row, f"{k} is absent, not null — a reader cannot tell the difference"
            assert row[k] is None


def test_4_observe_recorded_must_carry_both_fields_it_exists_to_add():
    with pytest.raises(si.ShadowIntentRefused) as e:
        si.observe_row("X", DAY, status=si.RECORDED, reason_code=si.OK,
                       after_reference={"entry_reference_price": 7680.75})
    assert "planned_stop" in str(e.value)


def test_5_status_and_reason_may_not_contradict_each_other():
    with pytest.raises(si.ShadowIntentRefused):
        si.decide_row("X", DAY, status=si.RECORDED, reason_code=si.NO_CANDIDATE,
                      before_entry=_be())
    with pytest.raises(si.ShadowIntentRefused):
        si.decide_row("X", DAY, status=si.NO_SETUP, reason_code=si.OK)


# ═══════════════════════════════════════════════════════════════════════════════
# 6-8  the slot shape and the gate that governs each phase
# ═══════════════════════════════════════════════════════════════════════════════

def test_6_calm_is_two_phase_slots_and_neither_sits_on_the_entry_instant():
    calm = [s for s in ts.TRACK1_SLOTS if s.sleeve == "roska4_calm"]
    assert len(calm) == 2, calm
    by_phase = {s.phase: s for s in calm}
    assert set(by_phase) == {"DECIDE", "OBSERVE"}
    d, o = by_phase["DECIDE"], by_phase["OBSERVE"]
    assert (d.hour, d.minute) == (9, 32) and d.id == "TRACK1_CALM_DECIDE_0932"
    assert (o.hour, o.minute) == (10, 2) and o.id == "TRACK1_CALM_OBSERVE_1002"
    # The old slot fired AT the entry and needed a bar that closes five minutes later.
    assert not any((s.hour, s.minute) == (10, 0) for s in calm)
    # decide strictly before the entry; observe strictly after
    assert (d.hour, d.minute) < (10, 0) < (o.hour, o.minute)


def test_7_every_phased_slot_has_a_requirement_and_a_typo_gets_none():
    phased = [s for s in ts.TRACK1_SLOTS if s.phase]
    assert phased, "no phased slot at all — this test would pass on an empty list"
    for s in phased:
        assert intra.requirement_for(s.sleeve, s.phase) is not None, s.id
    # A typo must NOT fall back to the sleeve's own requirement.
    assert intra.requirement_for("roska4_calm", "decide") is None
    assert intra.requirement_for("roska4_calm", "SEND") is None
    # and an unphased call still gets exactly what it always got
    assert intra.requirement_for("roska4_calm") is intra.REQUIREMENTS["roska4_calm"]


def test_8_decide_requires_no_entry_quote_and_closes_before_the_entry():
    d = intra.requirement_for("roska4_calm", "DECIDE")
    o = intra.requirement_for("roska4_calm", "OBSERVE")
    # The defining property. A decide phase that needed the entry quote is the old slot again.
    assert d.required_entry_quote_time is None
    assert o.required_entry_quote_time == "10:00"
    # An intent first written at or after the entry instant is not an intent.
    assert d.decide_to < "10:00" and d.decision_grace_seconds == 0
    assert o.decide_from > "10:00"
    # Both read the MINUTE frame: the 09:30 and 10:00 opens close at 09:31 and 10:01, and a
    # five-minute frame cannot offer either in time.
    assert d.bar_minutes == 1 and o.bar_minutes == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 9-11  what the stream is allowed to conclude
# ═══════════════════════════════════════════════════════════════════════════════

def test_9_observe_alone_is_not_a_judgeable_day():
    """Named collapse: OBSERVE counted without DECIDE."""
    v = si.classify_day([_observe().as_dict()])
    assert v["label"] == si.INCOMPLETE
    assert v["label"] != si.DECISION_JUDGEABLE


def test_10_decide_alone_is_not_a_judgeable_day():
    """Named collapse: missing OBSERVE treated as PASS."""
    v = si.classify_day([_decide().as_dict()])
    assert v["label"] == si.INCOMPLETE


def test_11_both_phases_make_a_decision_judgeable_day_and_nothing_more():
    """Named collapse: DECIDE counted as execution proof."""
    v = si.classify_day([_decide().as_dict(), _observe().as_dict()])
    assert v["label"] == si.DECISION_JUDGEABLE
    assert v["label"] != si.EXECUTION_PROVEN
    # the words themselves must disclaim it, because a label is what a later reader copies
    why = v["why"].lower()
    assert "fill" in why or "accept" in why
    # an empty day is not a quiet day
    assert si.classify_day([])["label"] == si.PRE_SCHEMA


# ═══════════════════════════════════════════════════════════════════════════════
# 12-13  what the readiness gate may credit
# ═══════════════════════════════════════════════════════════════════════════════

def test_12_the_gate_counts_judgeable_and_no_setup_but_never_an_absent_day(tmp_path):
    root = tmp_path
    si.append(_decide(), root=root, day=DAY)
    si.append(_observe(), root=root, day=DAY)
    si.append(si.decide_row("S", "2026-08-20", status=si.NO_SETUP,
                            reason_code=si.NO_CANDIDATE), root=root, day="2026-08-20")
    got = pr.calm_decision_evidence(root, [DAY, "2026-08-20", "2026-08-19"])
    assert got[DAY] == si.DECISION_JUDGEABLE
    assert got["2026-08-20"] == si.NO_SETUP_DAY
    # a day with no rows must appear, and must not count
    assert got["2026-08-19"] == si.PRE_SCHEMA
    assert si.DECISION_JUDGEABLE in pr._CALM_COUNTS and si.NO_SETUP_DAY in pr._CALM_COUNTS
    assert si.PRE_SCHEMA not in pr._CALM_COUNTS
    assert si.INCOMPLETE not in pr._CALM_COUNTS


def test_13_the_gate_can_never_report_an_execution_label():
    assert si.EXECUTION_PROVEN not in pr._CALM_COUNTS
    src = Path(pr.__file__).read_text(encoding="utf-8")
    # the guard exists AND it raises rather than logging
    assert "EXECUTION_PROVEN" in src
    assert "raise AssertionError" in src


# ═══════════════════════════════════════════════════════════════════════════════
# 14  isolation — the stream must not be, or touch, the order journal
# ═══════════════════════════════════════════════════════════════════════════════

def test_14_the_stream_is_not_the_order_journal_and_writes_nowhere_else(tmp_path):
    """Named collapse: shadow intent written to orders dir."""
    from global_index import track1_order_journal as oj

    assert si.SHADOW_INTENT_DIR != oj.ORDERS_DIR
    assert "orders" not in Path(si.SHADOW_INTENT_DIR).name

    si.append(_decide(), root=tmp_path, day=DAY)
    si.append(_observe(), root=tmp_path, day=DAY)
    written = sorted(str(p.relative_to(tmp_path)).replace("\\", "/")
                     for p in tmp_path.rglob("*") if p.is_file())
    assert written, "nothing was written — this test would pass on a no-op"
    assert written == [f"{si.SHADOW_INTENT_DIR}/shadow_intent_{DAY.replace('-','')}.jsonl"]
    for forbidden in (oj.ORDERS_DIR, "trade_log.track1.jsonl",
                      "live_positions.track1.json", "replay_checkpoint.track1.json"):
        assert not (tmp_path / forbidden).exists()


# ═══════════════════════════════════════════════════════════════════════════════
# 15  the strategy did not move
# ═══════════════════════════════════════════════════════════════════════════════

def test_15_calm_entry_and_stop_are_unchanged_and_the_two_detectors_agree():
    p = CA.CalmAParams()
    assert p.entry_time == "10:00", "Calm's entry moved — this stage may not do that"
    assert p.rth_start == "09:30" and p.disaster_stop_atr_mult == 1.5

    # The pre-entry detector is not a second copy of the rule: the full one is built on it.
    body = _code_of(CA.detect_entry_for_day)
    assert "detect_setup_before_entry" in body, \
        "the full detector no longer delegates — two copies of one rule will drift"
    # and it reads the entry bar exactly once, after the shared half
    assert body.count("_bar_open_at") == 1, body

    pre = _code_of(CA.detect_setup_before_entry)
    assert pre.count("_bar_open_at") == 1, \
        "the pre-entry half reads a second bar — the one it exists not to read"
    # It must not name the entry time at all. Counting the raw source would count the
    # docstring, which is prose describing the rule rather than the rule — the same trap that
    # broke a substring assertion two stages ago when a new comment quoted an old label.
    assert p.entry_time not in pre, "the pre-entry half names the entry time"
    assert "rth_start" in pre, "the pre-entry half no longer reads the 09:30 open"

    # The intent stream's own strategy digest must MOVE when the rule moves. A digest that
    # cannot change is a field that says nothing, which is exactly what the signals channel's
    # version has been since it was written.
    import dataclasses
    base = si.calm_params_identity()
    assert len(base) == 16 and base == si.calm_params_identity(), "the digest is not stable"

    class _Moved(CA.CalmAParams):
        pass
    moved = dataclasses.replace(p, disaster_stop_atr_mult=2.0)
    import global_index.track1_shadow_intent as _si
    real = CA.CalmAParams
    try:
        CA.CalmAParams = lambda: moved
        assert si.calm_params_identity() != base,             "the stop multiple changed and the digest did not — the field proves nothing"
    finally:
        CA.CalmAParams = real
    assert si.calm_params_identity() == base, "the digest did not come back"


# ═══════════════════════════════════════════════════════════════════════════════
# 16  the wire itself — does the SCHEDULER actually launch the phase?
# ═══════════════════════════════════════════════════════════════════════════════

def test_16_the_scheduler_really_launches_each_slot_with_its_own_phase(monkeypatch):
    """Stage 5ZY-PRE. Fires the real registered jobs with the launcher replaced, and reads the
    argv they build.

    This exists because a mutation found the gap: deleting the phase branch from the scheduler
    left every test in the corpus green. The slot table knew about phases, the gate knew about
    phases, and nothing asserted that the thing which starts processes passes one — the fifth
    time in this programme a mechanism was built and its wiring left unproven.

    Nothing is started: `_run` is replaced before any job body executes, so the bodies build
    their argv and hand it here instead of to a subprocess.
    """
    import logging

    from global_index import run_scheduler as rs

    logging.disable(logging.CRITICAL)
    seen: dict = {}

    def _capture(cmd, *, label=None, dry_run=None, route=None, **kw):
        seen[label] = list(cmd)

    monkeypatch.setattr(rs, "_run", _capture)
    sched = rs.make_scheduler(port=7497, dry_run=True, track1_only=True)
    jobs = {j.id: j for j in sched.get_jobs()}

    wanted = {s.id: s for s in ts.TRACK1_SLOTS}
    assert wanted, "no Track 1 slot at all — this test would pass on an empty table"
    for slot in wanted.values():
        job = jobs.get(slot.id.lower())
        assert job is not None, f"{slot.id} is in the table and not in the schedule"
        job.func()

    assert set(seen) == set(wanted), {
        "launched but not declared": sorted(set(seen) - set(wanted)),
        "declared but not launched": sorted(set(wanted) - set(seen))}

    for sid, cmd in seen.items():
        slot = wanted[sid]
        if slot.phase:
            assert "--phase" in cmd, f"{sid} has phase {slot.phase!r} and its argv omits it"
            assert cmd[cmd.index("--phase") + 1] == slot.phase, cmd
        else:
            assert "--phase" not in cmd, (
                f"{sid} has no phase and its argv carries one — the three unsplit sleeves' "
                f"command lines must stay exactly what production has been launching")
        # the standing property, re-checked on every slot rather than once
        assert "--allow-orders" not in cmd, f"{sid} argv can request orders"
        assert "--source" in cmd and cmd[cmd.index("--source") + 1] == "live-shadow"

    phased = [i for i, s in wanted.items() if s.phase]
    assert sorted(phased) == ["TRACK1_CALM_DECIDE_0932", "TRACK1_CALM_OBSERVE_1002"], phased


# ═══════════════════════════════════════════════════════════════════════════════
# mutations — each one performs a named collapse and demands its test go red
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except (AssertionError, si.ShadowIntentRefused, Failed):
        return True
    return False


try:                                            # pytest.fail raises this
    from _pytest.outcomes import Failed
except ImportError:                             # pragma: no cover
    Failed = AssertionError


def test_M1_planned_stop_in_decide_mutation(monkeypatch):
    """Collapse: the schema stops refusing a price in DECIDE."""
    monkeypatch.setattr(si.IntentRow, "__post_init__", lambda self: None)
    assert _must_fail(test_2_decide_row_carrying_planned_stop_is_refused), \
        "test_2 stayed green while a DECIDE row was allowed to carry a price"


def test_M2_observe_without_decide_mutation(monkeypatch):
    """Collapse: an observe-only day counted as judgeable."""
    monkeypatch.setattr(si, "classify_day",
                        lambda rows: {"label": si.DECISION_JUDGEABLE, "why": "mutated"})
    assert _must_fail(test_9_observe_alone_is_not_a_judgeable_day), \
        "test_9 stayed green while observe-only was declared judgeable"


def test_M3_decide_as_execution_proof_mutation(monkeypatch):
    """Collapse: the judgeable label silently becomes an execution claim."""
    monkeypatch.setattr(si, "classify_day",
                        lambda rows: {"label": si.EXECUTION_PROVEN, "why": "mutated"})
    assert _must_fail(test_11_both_phases_make_a_decision_judgeable_day_and_nothing_more), \
        "test_11 stayed green while the label claimed an execution"


def test_M4_missing_observe_treated_as_pass_mutation(monkeypatch):
    """Collapse: a decide-only day counted."""
    monkeypatch.setattr(si, "classify_day",
                        lambda rows: {"label": si.DECISION_JUDGEABLE, "why": "mutated"})
    assert _must_fail(test_10_decide_alone_is_not_a_judgeable_day), \
        "test_10 stayed green while a decide-only day was declared judgeable"


def test_M5_stream_pointed_at_the_orders_dir_mutation(monkeypatch, tmp_path):
    """Collapse: the intent stream writes into the order journal's directory."""
    from global_index import track1_order_journal as oj

    monkeypatch.setattr(si, "SHADOW_INTENT_DIR", oj.ORDERS_DIR)
    assert _must_fail(test_14_the_stream_is_not_the_order_journal_and_writes_nowhere_else,
                      tmp_path), \
        "test_14 stayed green while the stream wrote into the orders directory"
