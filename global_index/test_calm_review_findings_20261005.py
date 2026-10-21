# -*- coding: utf-8 -*-
"""Five defects an independent reviewer found in the Calm 10:00 entry / clock exit wiring, 2026-10-05.

Each was checked against the code before it was fixed; each test below goes red when its fix is
removed, and each has a control that proves the harness reaches the thing it asserts about.

  late start    the EXECUTE slot allowed a 180 s grace, so it could send a "10:00" market order at
                10:02:30 and nothing in the route would call it late
  safety net    Track 1 orders could be requested in the mode that has no Track 1 safety net, so a
                Calm entry would open with no exit job registered
  stop owner    the no-stop-id fallback matched a working stop by instrument/side/size only and
                could cancel a DIFFERENT position's protection
  lost update   the exit rewrites the whole positions file; started at 15:55 it could race the
                15:55 swing slot's append and drop a new swing position from the book
  blind exit    the exit trusted the book alone, so an order the book never learned about was
                "nothing to do" and stayed open overnight
"""
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import global_index.run_live_day_track1 as rl
import global_index.run_maxhold_exit as cli
import global_index.track1_calm_a as CA
import global_index.track1_intraday as intra
import global_index.track1_live_source as live_source
import global_index.track1_signal_layer as sl
import global_index.track1_slots as t1
import global_index.window_ledger as wl
from global_index import test_calm_execute_sends_without_the_1000_bar as E
from global_index import test_calm_time_exit_1555 as X
from global_index import test_riskwire_batch1_20260925 as B

CALM, SWING, TODAY = X.CALM, X.SWING, X.TODAY


# ── late start ───────────────────────────────────────────────────────────────

def _slot_at(tmp_path, monkeypatch, at):
    from global_index import track1_freshness as fresh

    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(ledger))
    monkeypatch.setenv("RAITS_ROUTE", sl.ROUTE)
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    monkeypatch.setattr(wl, "_disabled", False, raising=False)
    monkeypatch.setattr(fresh, "evaluate", lambda **kw: B._FreshVerdict())
    monkeypatch.setattr(rl, "emit_explanations", lambda decisions, **kw: {"records": len(decisions)})
    src = E._source(monkeypatch, {"MES": E._frame("MES"), "MNQ": E._frame("MNQ")})
    B._write_json(tmp_path / rl.POSITIONS_PATH, B._book_payload())
    broker = E._SpyBroker()
    rl.observe_live_slot(
        "roska4_calm", E.EXECUTE_ID, now_et=pd.Timestamp(f"{TODAY.date()} {at}", tz=E.ET),
        provider=object(), live_source=src, root=str(tmp_path), out_dir=rl.OPERATIONAL_SHADOW_DIR,
        phase="EXECUTE", order_gate=rl.OrderGate(True, blockers={}), broker=broker)
    rows = [r for r in B._coverage_rows(tmp_path) if r.get("slot_id") == E.EXECUTE_ID]
    assert rows, "no durable slot row: the harness is not exercising the slot"
    return broker, rows[-1]


def test_control_a_slot_a_few_seconds_late_still_sends(tmp_path, monkeypatch):
    broker, row = _slot_at(tmp_path, monkeypatch, "10:00:20")
    assert len(broker.sent) == 2, (broker.sent, row)


def test_a_slot_that_starts_two_and_a_half_minutes_late_sends_nothing(tmp_path, monkeypatch):
    broker, row = _slot_at(tmp_path, monkeypatch, "10:02:30")
    assert broker.sent == [], "a market order went out 150 s after the 10:00 it was dated"
    assert row.get("reason") == "gate_refused", row
    assert intra.TOO_LATE in str(row.get("detail")), row


# ── safety net ───────────────────────────────────────────────────────────────

def test_orders_are_dropped_unless_the_track1_safety_net_will_exist(monkeypatch):
    from global_index import run_scheduler as rs
    from global_index import track1_gates

    os.environ.setdefault("PYTEST_CURRENT_TEST", "calm_review")
    monkeypatch.setattr(track1_gates, "may_enable_orders", lambda *a, **k: (True, []))

    def argv_of_calm_execute(**kw):
        seen = {}
        orig = rs._run
        lvl = logging.getLogger().manager.disable
        logging.disable(logging.CRITICAL)
        try:
            rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
                seen.setdefault(label, list(args)) and True)
            sched = rs.make_scheduler(port=4002, dry_run=True, allow_orders=True, **kw)
            sched.get_job("track1_calm_execute_1000").func()
        finally:
            rs._run = orig
            logging.disable(lvl)
        return seen["TRACK1_CALM_EXECUTE_1000"]

    full = argv_of_calm_execute(track1_only=True)
    assert "--allow-orders" in full, "control: the full mode must still arm, or the next line proves nothing"
    transitional = argv_of_calm_execute(track1_shadow=True)
    assert "--allow-orders" not in transitional, (
        "orders requested where no clock exit, 09:31 limit or stop repair is registered")


# ── stop owner ───────────────────────────────────────────────────────────────

class _OpenOrders(X._Spy):
    """Reports a fixed set of working orders, as the real broker does."""

    def __init__(self, orders, *a, **k):
        super().__init__(*a, **k)
        self._orders = orders

    def get_open_orders(self):
        return list(self._orders)


def _stp(oid, inst="MES", qty=1):
    return {"order_id": oid, "order_type": "STP", "instrument": inst, "action": "SELL",
            "quantity": qty}


def test_control_a_lone_unrecorded_stop_is_still_found_and_cancelled(tmp_path):
    b = _OpenOrders([_stp("stp-calm")], {}, X.ACCOUNT)
    r = X._runner(b, tmp_path)
    X._add(r, "MES", CALM, stop_order_id=None)
    assert r.run_time_exit(TODAY, CALM) == [("MES", CALM)]
    assert b.cancelled == ["stp-calm"], "without this the ownership test below proves nothing"


def test_a_stop_that_may_belong_to_another_position_is_never_cancelled(tmp_path, caplog):
    b = _OpenOrders([_stp("stp-swing")], {}, X.ACCOUNT)
    r = X._runner(b, tmp_path)
    X._add(r, "MES", CALM, stop_order_id=None)                               # lost its id
    X._add(r, "MES", SWING, entry_day=TODAY, stop_order_id="stp-swing")      # same inst/side/size
    with caplog.at_level("ERROR"):
        closed = r.run_time_exit(TODAY, CALM)
    assert closed == [("MES", CALM)]
    assert b.cancelled == [], "the swing position's stop was cancelled to tidy up Calm's"
    assert any("Not guessing" in x.message for x in caplog.records), [x.message for x in caplog.records]


def test_a_time_exit_that_cannot_find_its_stop_says_so_at_error_level(tmp_path, caplog):
    r = X._runner(_OpenOrders([], {}, X.ACCOUNT), tmp_path)
    X._add(r, "MES", CALM, stop_order_id=None)
    with caplog.at_level("ERROR"):
        r.run_time_exit(TODAY, CALM)
    assert any("orphan" in x.message and x.levelname == "ERROR" for x in caplog.records)


def test_maxhold_without_a_rival_is_unchanged(tmp_path):
    b = _OpenOrders([_stp("stp-1")], {}, X.ACCOUNT)
    r = X._runner(b, tmp_path)
    X._add(r, "MES", SWING, entry_day=pd.Timestamp("2026-09-25"), stop_order_id=None)
    assert r.run_maxhold_exit(TODAY, max_hold_days=5) == [("MES", SWING)]
    assert b.cancelled == ["stp-1"]


# ── lost update ──────────────────────────────────────────────────────────────

def test_the_exit_starts_before_the_last_swing_slot_so_its_book_rewrite_cannot_race_it():
    job = t1.calm_time_exit_job()
    swing_slots = [s for s in t1.TRACK1_SLOTS if s.sleeve == "roska4_swing"]
    last = max((s.hour, s.minute) for s in swing_slots)
    prior = max((s.hour, s.minute) for s in swing_slots if (s.hour, s.minute) < last)
    assert (job.hour, job.minute) > prior, "it would overlap the second-to-last swing slot"
    assert (job.hour, job.minute) < last, (
        "it starts with the last swing slot, which appends a row after its fetch; the exit "
        "rewrites the whole file from what it loaded and could drop that row")


# ── blind exit ───────────────────────────────────────────────────────────────

def _journal_open(root, inst, states, sleeve=CALM):
    from global_index import track1_order_journal as oj

    for st in states:
        oj.append(oj.JournalRecord(
            idempotency_key=f"k-{inst}", state=st, ref_day="2026-10-05", sleeve=sleeve,
            instrument=inst, tradable_symbol=inst, action="OPEN", candidate_id=f"calm_a::{inst}",
            created_at="2026-10-05T14:00:10+00:00", qty=1), root=root)


def _flat_book_run(monkeypatch, tmp_path, *, close_row=None):
    book = X._book(tmp_path, [SWING])
    log = tmp_path / "t.jsonl"
    if close_row:
        log.write_text(json.dumps(close_row) + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_CWD", tmp_path)
    real_now = pd.Timestamp.now
    monkeypatch.setattr(pd.Timestamp, "now",
                        staticmethod(lambda tz=None: TODAY.tz_localize(tz) if tz else TODAY))
    try:
        return X._run_cli(monkeypatch, tmp_path, book, ["--time-exit-cluster", CALM])
    finally:
        monkeypatch.setattr(pd.Timestamp, "now", staticmethod(real_now))


def test_control_a_swing_only_flat_day_exits_quietly_and_does_not_connect(monkeypatch, tmp_path):
    assert _flat_book_run(monkeypatch, tmp_path) == 0 and X._NeverConnect.constructed == 0


def test_a_flat_book_with_a_filled_calm_open_in_the_journal_fails_loudly(monkeypatch, tmp_path):
    _journal_open(tmp_path, "MES", ["intended", "submitted", "filled"])
    assert _flat_book_run(monkeypatch, tmp_path) == 1


def test_the_same_day_is_quiet_once_the_trade_log_holds_the_close(monkeypatch, tmp_path):
    _journal_open(tmp_path, "MES", ["intended", "submitted", "filled"])
    close = {"type": "CLOSE", "cluster": CALM, "inst": "MES", "exit_day": "2026-10-05"}
    assert _flat_book_run(monkeypatch, tmp_path, close_row=close) == 0


def test_a_rejected_or_merely_intended_open_is_not_a_position(monkeypatch, tmp_path):
    _journal_open(tmp_path, "MES", ["intended", "submitted", "rejected"])
    _journal_open(tmp_path, "MNQ", ["intended"])
    assert _flat_book_run(monkeypatch, tmp_path) == 0


def test_an_unreadable_journal_is_a_failure_not_an_empty_day(monkeypatch, tmp_path):
    from global_index import track1_order_journal as oj

    p = oj.journal_path("20261005", tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json\n", encoding="utf-8")
    assert _flat_book_run(monkeypatch, tmp_path) == 1


# ── a non-trading day ────────────────────────────────────────────────────────

def test_a_non_trading_day_is_refused_like_an_early_close(monkeypatch):
    import raits.live.trading_calendar as cal

    monkeypatch.setattr(cal, "is_early_close", lambda d: False)
    monkeypatch.setattr(cal, "is_trading_day", lambda d: False)
    src = E._source(monkeypatch, {"MES": E._frame("MES"), "MNQ": E._frame("MNQ")})
    with pytest.raises(live_source.LiveSourceRefused) as e:
        src.candidates(pd.Timestamp(f"{TODAY.date()} 10:00:03", tz=E.ET), phase="EXECUTE")
    assert e.value.code == live_source.SESSION_ENDS_BEFORE_EXIT


# ── the dashboard must not offer the clock exit as "the next protection" ─────

def test_the_clock_exit_is_never_offered_as_the_next_protection_job():
    import datetime as dt

    from monitor.backend.track1_market_view import _next_protection_job

    exit_id = t1.calm_time_exit_job().id.upper()
    # 13:57 ET on a trading day: the exit (15:54) is the next safety job in the table by time.
    got = _next_protection_job(dt.datetime(2026, 9, 25, 17, 57, tzinfo=dt.timezone.utc))
    assert got["job_id"] != exit_id, got
    # control: the table does contain it, so the filter is what keeps it out
    assert exit_id.lower() in {j.id for j in t1.track1_safety_jobs()}
