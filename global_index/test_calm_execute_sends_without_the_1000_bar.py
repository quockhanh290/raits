# -*- coding: utf-8 -*-
"""Calm EXECUTE sends its market order at 10:00:00 WITHOUT the 10:00 bar. 2026-10-05.

The slot refused `entry_quote_absent` on 2 of 2 recorded runs (2026-10-02, 2026-10-05): the gate
asked for a one-minute bar stamped 10:00, which closes at 10:01:00, at the instant the order is
meant to go. These tests pin the three things that had to change together, and — because a test
that never reaches the send measures nothing — they run the REAL slot (real gate, real source,
real executor) against a spy broker, with a control that must reach the send first.

  gate     EXECUTE needs the CLOSED 09:59 bar, for EVERY instrument; the unphased contract and
           OBSERVE still need the 10:00 OPEN
  source   the entry is planned against the 09:59 CLOSE, dated at the order instant
  slot     armed + both bars present -> one market OPEN per instrument; one instrument missing
           its bar -> nothing is sent, not even for the instrument that has it
"""
import types

import numpy as np
import pandas as pd
import pytest

import global_index.run_live_day_track1 as rl
import global_index.track1_calm_a as CA
import global_index.track1_intraday as intra
import global_index.track1_live_source as live_source
import global_index.track1_signal_layer as sl
import global_index.window_ledger as wl
from global_index import test_riskwire_batch1_20260925 as B

ET = "America/New_York"
PRIOR = pd.Timestamp("2026-10-02")          # a Friday
TODAY = pd.Timestamp("2026-10-05")          # the Monday after
EXECUTE_ID = "TRACK1_CALM_EXECUTE_1000"
CLOSE_0959 = {"MES": 90.75, "MNQ": 40.5}    # the reference the entry is planned against
OPEN_1000 = {"MES": 91.25, "MNQ": 41.0}     # what the 10:00 bar would have opened at
STOP_ATR = 8.0


def _minutes(day, start, end):
    return pd.date_range(f"{day.date()} {start}", f"{day.date()} {end}", freq="1min", tz=ET)


def _frame(inst, *, last="09:59", drop=None):
    """Prior session set up for Calm A (close in the bottom third, down day), then today's bars.

    Prior RTH: open 100, high 110, low 90, close 91 -> close location 0.05, return -9%.
    Today opens 90.5 -> gap -0.55%, inside the -1% floor. `inst` only scales the prices so the
    two instruments are not accidentally identical.
    """
    k = CLOSE_0959[inst] / CLOSE_0959["MES"]
    pidx = _minutes(PRIOR, "09:30", "15:59")
    p = np.full(len(pidx), 100.0)
    p[pidx.get_loc(pd.Timestamp(f"{PRIOR.date()} 12:00", tz=ET))] = 105.0
    p[-1] = 91.0
    prior = pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "volume": 10.0}, index=pidx)
    # The gate wants the prior session through its 16:00 bar; the RULE reads only 09:30-15:59, so
    # the after-hours bars sit at the final RTH close and cannot move any threshold.
    after = pd.DataFrame(91.0, index=_minutes(PRIOR, "16:00", "16:10"),
                         columns=["open", "high", "low", "close", "volume"])
    prior = pd.concat([prior, after])
    prior.loc[prior.index[0], ["open", "high", "low", "close"]] = 100.0
    prior.loc[pd.Timestamp(f"{PRIOR.date()} 12:00", tz=ET), "high"] = 110.0
    prior.loc[pd.Timestamp(f"{PRIOR.date()} 14:00", tz=ET), "low"] = 90.0

    tidx = _minutes(TODAY, "09:30", last)
    t = np.full(len(tidx), 90.5)
    today = pd.DataFrame({"open": t, "high": t, "low": t, "close": t, "volume": 10.0}, index=tidx)
    today.loc[pd.Timestamp(f"{TODAY.date()} 09:59", tz=ET), "close"] = 90.75
    if last >= "10:00":
        today.loc[pd.Timestamp(f"{TODAY.date()} 10:00", tz=ET), "open"] = OPEN_1000["MES"]
    out = pd.concat([prior, today])
    out = out[["open", "high", "low", "close", "volume"]] * 1.0
    out = out.copy()
    out[["open", "high", "low", "close"]] *= k
    if drop is not None:
        out = out.drop(pd.Timestamp(f"{TODAY.date()} {drop}", tz=ET))
    return out


LABELS = {PRIOR: "Calm"}


def _resampled(frame):
    o = frame["open"].resample("5min").first()
    h = frame["high"].resample("5min").max()
    lo = frame["low"].resample("5min").min()
    c = frame["close"].resample("5min").last()
    v = frame["volume"].resample("5min").sum()
    return pd.concat([o, h, lo, c, v], axis=1, keys=["open", "high", "low", "close", "volume"]
                     ).dropna()


# ── unit: the rule is the same, only the price differs ───────────────────────

def test_the_paper_entry_is_planned_against_the_0959_close_and_dated_at_the_order_instant():
    f = _frame("MES")
    s = CA.detect_paper_entry_for_day(f, LABELS, "MES", TODAY)
    assert s is not None, "a day that sets up must produce a setup from a frame ending at 09:59"
    assert s.entry == pytest.approx(CLOSE_0959["MES"])
    assert s.entry_time == pd.Timestamp(f"{TODAY.date()} 10:00", tz=ET)
    assert np.isnan(s.exit)
    assert s.direction == "LONG"


def test_the_old_detector_cannot_answer_on_the_same_frame_which_is_the_defect():
    f = _frame("MES")
    assert CA.detect_entry_for_day(f, LABELS, "MES", TODAY) is None, (
        "the open-based detector needs the 10:00 bar; this frame ends at 09:59, as the live "
        "frame does at 10:00:00 — if this stops being None the control below proves nothing")


def test_same_rule_fields_as_the_open_based_detector_when_both_can_answer():
    full = _frame("MES", last="10:00")
    a = CA.detect_entry_for_day(full, LABELS, "MES", TODAY)
    b = CA.detect_paper_entry_for_day(full, LABELS, "MES", TODAY)
    assert a is not None and b is not None
    assert (a.prev_close_loc, a.prev_rth_ret, a.gap_from_prev_rth_close, a.prev_session_day) == \
           (b.prev_close_loc, b.prev_rth_ret, b.gap_from_prev_rth_close, b.prev_session_day)
    assert a.entry == pytest.approx(OPEN_1000["MES"]) and b.entry == pytest.approx(CLOSE_0959["MES"])


def test_a_missing_0959_bar_is_none_never_a_neighbouring_price():
    f = _frame("MES", drop="09:59")
    seen = []
    assert CA.detect_paper_entry_for_day(f, LABELS, "MES", TODAY, observer=seen.append) is None
    gate = [e for e in seen if e.get("gate") == "entry_time_valid"]
    assert gate and gate[-1]["passed"] is False, seen


def test_a_day_that_does_not_set_up_is_none():
    f = _frame("MES")
    assert CA.detect_paper_entry_for_day(f, {PRIOR: "Normal"}, "MES", TODAY) is None


# ── gate ─────────────────────────────────────────────────────────────────────

def _verdict(frame, req, now="10:00:03"):
    return intra.validate("roska4_calm", _resampled(frame), now_et=pd.Timestamp(
        f"{TODAY.date()} {now}", tz=ET), session_day=TODAY, requirement=req,
        entry_quote_index=frame.index)


def test_execute_gate_passes_with_the_0959_bar_and_no_1000_bar():
    v = _verdict(_frame("MES"), intra.requirement_for("roska4_calm", "EXECUTE"))
    assert v.allow, (v.codes, [(c.name, c.code, c.detail) for c in v.checks])


def test_the_unphased_contract_and_observe_still_need_the_1000_open():
    f = _frame("MES")
    for req in (intra.REQUIREMENTS["roska4_calm"], intra.requirement_for("roska4_calm", "OBSERVE")):
        assert req.required_entry_quote_time == "10:00"
    v = _verdict(f, intra.REQUIREMENTS["roska4_calm"])
    assert not v.allow and intra.ENTRY_QUOTE_ABSENT in v.codes, v.codes


def test_execute_gate_refuses_when_the_0959_bar_is_missing():
    v = _verdict(_frame("MES", drop="09:59"), intra.requirement_for("roska4_calm", "EXECUTE"))
    assert not v.allow and intra.ENTRY_QUOTE_ABSENT in v.codes, v.codes


# ── source ───────────────────────────────────────────────────────────────────

class _Joined:
    def __init__(self, frame):
        self.frame = frame


def _source(monkeypatch, frames):
    monkeypatch.setattr(live_source, "sleeve_frames",
                        lambda **kw: {kw["sleeves"][0]: {k: _Joined(v) for k, v in frames.items()}})
    monkeypatch.setattr(live_source, "causal_daily_atr", lambda frame, day, period=14: STOP_ATR)
    return live_source.LiveTrack1Source(bar_provider=object(), labels=LABELS,
                                        costs=live_source.default_costs())


def test_source_plans_execute_candidates_from_the_0959_close(monkeypatch):
    frames = {"MES": _frame("MES"), "MNQ": _frame("MNQ")}
    src = _source(monkeypatch, frames)
    got = src.candidates(pd.Timestamp(f"{TODAY.date()} 10:00:03", tz=ET), phase="EXECUTE")
    assert sorted(c.instrument for c in got) == ["MES", "MNQ"], got
    for c in got:
        assert c.entry_price == pytest.approx(CLOSE_0959[c.instrument])
        assert c.stop_price == pytest.approx(CLOSE_0959[c.instrument] - 1.5 * STOP_ATR)
        assert c.entry_time == pd.Timestamp(f"{TODAY.date()} 10:00", tz=ET)
        assert c.meta["entry_reference"] == "prior_bar_close_09:59"


def test_source_default_phase_is_unchanged_and_still_needs_the_1000_bar(monkeypatch):
    src = _source(monkeypatch, {"MES": _frame("MES"), "MNQ": _frame("MNQ")})
    assert src.candidates(pd.Timestamp(f"{TODAY.date()} 10:00", tz=ET)) == []


# ── the real slot, with a spy for a broker ───────────────────────────────────

class _SpyBroker:
    """Has every method the executor requires; records what `send_order` was asked."""

    def __init__(self):
        self.sent = []

    def send_order(self, order, on_submit=None):
        self.sent.append(order)
        px = CLOSE_0959[order.inst]
        if on_submit:
            on_submit(types.SimpleNamespace(order_id=f"OID-{len(self.sent)}"))
        return types.SimpleNamespace(status="FILLED", filled_qty=0, avg_price=px,
                                     commission=0.6, order_id=f"OID-{len(self.sent)}",
                                     error_msg="")

    def get_positions(self, *a, **k): return []
    def get_order_status(self, *a, **k): return None
    def cancel_order(self, *a, **k): return True
    def place_stop(self, *a, **k): return None


def _run_slot(tmp_path, monkeypatch, frames, *, armed=True):
    from global_index import track1_freshness as fresh

    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(ledger))
    monkeypatch.setenv("RAITS_ROUTE", sl.ROUTE)
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    monkeypatch.setattr(wl, "_disabled", False, raising=False)
    monkeypatch.setattr(fresh, "evaluate", lambda **kw: B._FreshVerdict())
    monkeypatch.setattr(rl, "emit_explanations", lambda decisions, **kw: {"records": len(decisions)})
    src = _source(monkeypatch, frames)
    B._write_json(tmp_path / rl.POSITIONS_PATH, B._book_payload())
    broker = _SpyBroker()
    gate = rl.OrderGate(True, blockers={}) if armed else rl.OrderGate(False)
    out = rl.observe_live_slot(
        "roska4_calm", EXECUTE_ID, now_et=pd.Timestamp(f"{TODAY.date()} 10:00:03", tz=ET),
        provider=object(), live_source=src, root=str(tmp_path), out_dir=rl.OPERATIONAL_SHADOW_DIR,
        phase="EXECUTE", order_gate=gate, broker=broker)
    rows = [r for r in B._coverage_rows(tmp_path) if r.get("slot_id") == EXECUTE_ID]
    assert rows, "no durable slot row: this harness is not exercising the slot it claims to"
    return broker, rows[-1], out


def test_control_a_closed_gate_sends_nothing_so_the_armed_case_means_something(tmp_path, monkeypatch):
    broker, row, _ = _run_slot(tmp_path, monkeypatch,
                               {"MES": _frame("MES"), "MNQ": _frame("MNQ")}, armed=False)
    assert broker.sent == []
    assert row.get("decided") is True, row


def test_armed_and_both_bars_present_sends_one_market_open_per_instrument(tmp_path, monkeypatch):
    broker, row, _ = _run_slot(tmp_path, monkeypatch,
                               {"MES": _frame("MES"), "MNQ": _frame("MNQ")})
    assert row.get("reason") != "gate_refused", row
    assert sorted((o.inst, o.action, o.direction) for o in broker.sent) == [
        ("MES", "OPEN", "LONG"), ("MNQ", "OPEN", "LONG")], broker.sent
    assert all(o.contracts >= 1 for o in broker.sent)


def test_one_instrument_missing_its_bar_stops_the_whole_slot(tmp_path, monkeypatch):
    broker, row, _ = _run_slot(tmp_path, monkeypatch,
                               {"MES": _frame("MES"), "MNQ": _frame("MNQ", drop="09:59")})
    assert broker.sent == [], "MNQ could not answer the gate; nothing may be sent for MES either"
    assert row.get("reason") == "gate_refused", row


def test_the_refusal_does_not_depend_on_which_instrument_sorts_first(tmp_path, monkeypatch):
    broker, row, _ = _run_slot(tmp_path, monkeypatch,
                               {"MES": _frame("MES", drop="09:59"), "MNQ": _frame("MNQ")})
    assert broker.sent == [] and row.get("reason") == "gate_refused", row


# ── a session that ends before the exit cannot take the trade ────────────────

def _calendar(monkeypatch, *, early=None, boom=False):
    import raits.live.trading_calendar as cal

    def is_early_close(d):
        if boom:
            raise RuntimeError("calendar unavailable")
        return bool(early)

    monkeypatch.setattr(cal, "is_early_close", is_early_close)


def test_control_a_full_session_still_takes_the_entry(monkeypatch):
    _calendar(monkeypatch, early=False)
    src = _source(monkeypatch, {"MES": _frame("MES"), "MNQ": _frame("MNQ")})
    got = src.candidates(pd.Timestamp(f"{TODAY.date()} 10:00:03", tz=ET), phase="EXECUTE")
    assert len(got) == 2, "without this the refusals below could be a source that never answers"


def test_an_early_close_session_is_refused_because_it_has_no_1555_to_exit_at(monkeypatch):
    _calendar(monkeypatch, early=True)
    src = _source(monkeypatch, {"MES": _frame("MES"), "MNQ": _frame("MNQ")})
    with pytest.raises(live_source.LiveSourceRefused) as e:
        src.candidates(pd.Timestamp(f"{TODAY.date()} 10:00:03", tz=ET), phase="EXECUTE")
    assert e.value.code == live_source.SESSION_ENDS_BEFORE_EXIT


def test_a_calendar_that_cannot_answer_refuses_it_does_not_assume_a_full_day(monkeypatch):
    _calendar(monkeypatch, boom=True)
    src = _source(monkeypatch, {"MES": _frame("MES"), "MNQ": _frame("MNQ")})
    with pytest.raises(live_source.LiveSourceRefused) as e:
        src.candidates(pd.Timestamp(f"{TODAY.date()} 10:00:03", tz=ET), phase="EXECUTE")
    assert e.value.code == live_source.SESSION_ENDS_BEFORE_EXIT


def test_only_the_slot_that_sends_cares_about_the_calendar(monkeypatch):
    _calendar(monkeypatch, early=True)
    src = _source(monkeypatch, {"MES": _frame("MES", last="10:00"), "MNQ": _frame("MNQ", last="10:00")})
    got = src.candidates(pd.Timestamp(f"{TODAY.date()} 10:00:03", tz=ET))      # the old, default path
    assert len(got) == 2, "the read-only path must not start refusing"


def test_the_slot_records_the_refusal_and_sends_nothing_on_an_early_close(tmp_path, monkeypatch):
    _calendar(monkeypatch, early=True)
    broker, row, _ = _run_slot(tmp_path, monkeypatch,
                               {"MES": _frame("MES"), "MNQ": _frame("MNQ")})
    assert broker.sent == []
    assert row.get("reason") == live_source.SESSION_ENDS_BEFORE_EXIT, row
