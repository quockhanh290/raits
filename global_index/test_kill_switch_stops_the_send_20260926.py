# -*- coding: utf-8 -*-
"""The kill switch stops the send, proved by running the slot — not by reading its source.

Why this exists beside the ordering check in test_riskwire_batch1_20260925.py. That one takes
the slot's source text and asserts three lines appear in the right order: the summary is built,
then a conditional, then the send. It does catch the mutation it was written for, because
deleting the conditional makes the index lookup raise. It cannot catch a semantic bypass — a
conditional that is present, in the right place, and no longer governs the send.

So this file runs the real slot twice, with a spy standing in for the send, and watches whether
the send is reached at all.

The control is the load-bearing half. Without it, "the send was not reached" is satisfied by a
harness that never reaches the send under any conditions, which is how a green test ends up
measuring nothing. Measured 2026-09-26: control reaches the send with one decision, gated run
reaches it zero times.
"""
import sys

import pandas as pd

import global_index.run_live_day_track1 as rl
import global_index.track1_signal_layer as sl
from global_index import test_riskwire_batch1_20260925 as B


def _run_slot_with_a_spy(tmp_path, monkeypatch, *, stop_file: bool):
    """Run one real slot. Returns (calls the send received, the durable row)."""
    from global_index import track1_freshness as fresh
    from global_index import track1_intraday as intra
    from global_index import track1_live_source as live_source
    import global_index.window_ledger as wl

    calls: list[dict] = []

    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(ledger))
    monkeypatch.setenv("RAITS_ROUTE", sl.ROUTE)
    monkeypatch.setattr(wl, "_disabled", False, raising=False)
    monkeypatch.setattr(live_source, "sleeve_frames",
                        lambda **kw: {kw["sleeves"][0]: {"MES": B._Joined()}})
    monkeypatch.setattr(rl, "_resample", lambda frame, sleeve, requirement=None: frame)
    monkeypatch.setattr(intra, "validate",
                        lambda sleeve, bars, **kw: intra.Verdict(sleeve, True, (), ()))
    monkeypatch.setattr(fresh, "evaluate", lambda **kw: B._FreshVerdict())
    monkeypatch.setattr(rl, "emit_explanations",
                        lambda decisions, **kw: {"records": len(decisions)})

    def _spy(decisions, **kw):
        calls.append({"n_decisions": len(decisions)})
        return rl._ps.SendSummary(status="DRY", reason="spy stood in for the send")
    monkeypatch.setattr(rl._ps, "maybe_send_orders", _spy)

    B._write_json(tmp_path / rl.POSITIONS_PATH,
                  B._book_payload(equity=0.0, peak_equity=0.0, day_start_equity=0.0))
    if stop_file:
        (tmp_path / rl.STOP_FILE).write_text("operator stop", encoding="utf-8")

    rl.observe_live_slot(
        sl.SWING, "TRACK1_SWING_1405",
        now_et=pd.Timestamp("2026-09-25 14:05", tz="America/New_York"),
        provider=object(), live_source=B._OneCandidateSource(),
        root=str(tmp_path), out_dir=rl.OPERATIONAL_SHADOW_DIR)

    rows = [r for r in B._coverage_rows(tmp_path)
            if r.get("event") == "slot_observed" and r.get("slot_id") == "TRACK1_SWING_1405"]
    assert len(rows) == 1, (
        "no durable slot row was written, so this harness is not exercising the path it claims "
        "to and every assertion built on it is void")
    return calls, rows[0]


def test_the_control_reaches_the_send_so_the_gated_case_means_something(tmp_path, monkeypatch):
    calls, row = _run_slot_with_a_spy(tmp_path, monkeypatch, stop_file=False)

    assert calls, (
        "with no stop file present the send was still never reached. The gated test below would "
        "then pass for the wrong reason, so this one fails first and on purpose")
    assert calls[0]["n_decisions"] >= 1, calls
    assert row.get("send_status") is None, (
        "no stop file was present, so the row must carry no gate-closed status: %r" % (row,))


def test_a_present_stop_file_means_the_send_is_never_reached(tmp_path, monkeypatch):
    calls, row = _run_slot_with_a_spy(tmp_path, monkeypatch, stop_file=True)

    assert calls == [], (
        "the stop file was present and the send was reached anyway: %r. The switch does not "
        "stop orders, whatever the source ordering says" % (calls,))
    assert row.get("send_status") == rl._ps.GATE_CLOSED, row
    assert rl.STOP_FILE in str(row.get("send_reason")), row
    assert "observation kept" in str(row.get("send_reason")), (
        "the refusal must say the observation was kept, or an operator reading this row cannot "
        "tell a gated slot from a slot that failed: %r" % (row,))


def test_the_gated_slot_still_records_what_it_saw(tmp_path, monkeypatch):
    """Refusing to send is not refusing to observe. The evidence must survive the gate."""
    calls, row = _run_slot_with_a_spy(tmp_path, monkeypatch, stop_file=True)

    assert calls == []
    assert row.get("decided") is True, row
    assert row.get("candidates") == 1, row
    assert row.get("breaker_armed") is False, row
    assert "out-of-band equity=0.0" in str(row.get("breaker_unarmed_reason")), row
