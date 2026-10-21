"""global_index/test_order_block_override.py — a third state: measured, failing, and not blocking.

The operator's decision, 2026-09-23: open paper orders now, and keep the shadow-evidence gate
measuring exactly as it does. Those two are not in conflict — the gate does two jobs, and only
one of them was asked to stop. It judges the shadow record every day, and it holds the order
gate shut. Opening orders needs the second to stop; nothing about the first should change.

The cheap way to do that is `blocks_orders=False`, and it is the wrong way. `blocking()` would
return an empty list, `ops status` would print `orders_possible=True`, and nothing anywhere
would say that the evidence was still FAILING — 4 of the last 5 days, measured the same morning
this was written. Six weeks later that reads as a gate that passed.

So the override is a state of its own. It is recorded like every other operator decision, it
is reported wherever the gate is reported, and it says the two things that are both true:
orders may be sent, AND the evidence does not support them yet.

The test that matters is the last one: an override may never be reported as a pass.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index import track1_gates as g

FLAG = "paper_shadow_evidence_order_block_overridden"
EV = "PAPER_SHADOW_EVIDENCE"
B1 = "B1_broker_account_or_legacy_retirement"


def _conf(**flags):
    """Confirmations carrying exactly these flags."""
    base = dict(g.NO_CONFIRMATIONS) if isinstance(g.NO_CONFIRMATIONS, dict) else {}
    base.update(flags)
    return base


def _ids(blockers):
    return [b.id for b in blockers]


def test_ov1_without_the_flag_nothing_changes(monkeypatch):
    """The default must stay exactly what it was: evidence failing means orders blocked."""
    monkeypatch.setitem(g.MEASUREMENTS, "shadow_evidence",
                        lambda *a, **k: (False, "4 FAIL day(s) in the qualifying window"))
    assert EV in _ids(g.blocking(_conf()))


def test_ov2_the_flag_lifts_the_order_block(monkeypatch):
    monkeypatch.setitem(g.MEASUREMENTS, "shadow_evidence",
                        lambda *a, **k: (False, "4 FAIL day(s) in the qualifying window"))
    assert EV not in _ids(g.blocking(_conf(**{FLAG: True})))


def test_ov3_the_flag_releases_NOTHING_else(monkeypatch):
    """An override is for one gate. B1 is a different question and stays shut."""
    monkeypatch.setitem(g.MEASUREMENTS, "shadow_evidence",
                        lambda *a, **k: (False, "still failing"))
    assert B1 in _ids(g.blocking(_conf(**{FLAG: True})))


def test_ov4_an_override_is_REPORTED_not_silent(monkeypatch):
    """The whole point. Lifting the block must produce a statement, not an absence."""
    monkeypatch.setitem(g.MEASUREMENTS, "shadow_evidence",
                        lambda *a, **k: (False, "4 FAIL day(s) in the qualifying window"))
    over = g.overridden(_conf(**{FLAG: True}))
    assert [b.id for b, _ in over] == [EV]
    _blocker, detail = over[0]
    assert "4 FAIL" in detail, (
        f"the report does not carry WHY the gate is failing, so a reader sees an override "
        f"with no idea what it is overriding: {detail!r}")


def test_ov5_nothing_to_confess_when_the_evidence_actually_passes(monkeypatch):
    """An override on a gate that would open anyway is not an override. Reporting it would
    teach the reader to ignore the line on the days it means something."""
    monkeypatch.setitem(g.MEASUREMENTS, "shadow_evidence", lambda *a, **k: (True, ""))
    assert g.overridden(_conf(**{FLAG: True})) == []
    assert EV not in _ids(g.blocking(_conf(**{FLAG: True})))


def test_ov6_blocking_and_overridden_never_overlap(monkeypatch):
    monkeypatch.setitem(g.MEASUREMENTS, "shadow_evidence", lambda *a, **k: (False, "failing"))
    conf = _conf(**{FLAG: True})
    assert not (set(_ids(g.blocking(conf))) & {b.id for b, _ in g.overridden(conf)})


def test_ov7_an_override_is_never_a_pass(monkeypatch):
    """The assertion this file exists for.

    Whatever the reporting surface, an overridden gate must not be describable as released,
    satisfied or passed. If this ever goes green while `released()` says True, the third state
    has collapsed back into two and the record has started lying.
    """
    monkeypatch.setitem(g.MEASUREMENTS, "shadow_evidence", lambda *a, **k: (False, "failing"))
    conf = _conf(**{FLAG: True})
    ev = g.BLOCKERS[EV]
    assert ev.released(conf) is False, (
        "the override made the gate report itself RELEASED — that is the exact confusion "
        "this design exists to prevent: orders may proceed, the evidence has not passed, and "
        "both must stay visible")


def test_ov8_the_flag_survives_the_REAL_file_loader(tmp_path):
    """The gap the other seven tests left, and it bit within a minute of being written.

    Every test above builds a Confirmations dict directly, so none of them touched the schema —
    and the schema refuses unknown keys by design: "a misspelled flag that is silently dropped
    reads as a granted gate". The flag was implemented, the tests were green, and writing it
    into the real file INVALIDATED the file: both the new key and the provenance key I had
    added were refused, every confirmation was dropped, and B1 — which had just been cleared —
    slammed shut again. Fail-closed worked. The tests had simply never asked the question.
    """
    import json
    from global_index.track1_gates import load_confirmations

    p = tmp_path / "conf.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "confirmed_by": "kevindo290",
        "confirmed_at": "2026-09-23",
        "legacy_retired_confirmed": True,
        "paper_shadow_evidence_order_block_overridden": True,
        "note": "evidence failing 4 of 5 days; proceeding on paper to observe execution",
    }), encoding="utf-8")

    conf, errors = load_confirmations(p)
    assert not errors, f"the schema refuses the flag, so the file cannot carry it: {errors}"
    assert conf.get(FLAG) is True


def test_ov9_an_override_without_a_stated_reason_is_refused(tmp_path):
    """Same rule `b1_measurement_waived` carries, and for a stronger reason here.

    Six weeks later, `orders_possible=True` with an empty note is indistinguishable from a
    gate that opened on its own evidence. The note is the only thing that can tell those apart,
    so the file may not carry the flag without one.
    """
    import json
    from global_index.track1_gates import load_confirmations

    p = tmp_path / "conf.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "confirmed_by": "kevindo290",
        "confirmed_at": "2026-09-23",
        "legacy_retired_confirmed": True,
        "paper_shadow_evidence_order_block_overridden": True,
        "note": "   ",
    }), encoding="utf-8")

    _conf_, errors = load_confirmations(p)
    assert any("note" in e for e in errors), (
        f"an override with no stated reason was accepted: {errors}")
