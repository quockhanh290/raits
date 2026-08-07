"""
global_index/test_stp.py — STP (stop order) placement + B3 STP-exit detection tests

Tests:
  STP1: place_stop() called after multi-day OPEN fill — orderId stored in OpenPos
  STP2: stop_price + stop_order_id serialised to / from JSON (cold-start round-trip)
  STP3: place_stop() NOT called for same-day entries (STRESS_MID)
  STP4: place_stop() NOT called when OPEN fill is CANCELLED
  STP5: B3 STP EXIT — IBKR shows 0 but stop_order_id is FILLED → auto-clear, no halt
  STP6: B3 MISMATCH with stop_order_id NOT_FOUND → CRITICAL + halt (with STP hint)
  STP7: B3 MISMATCH without stop_order_id → original CRITICAL behavior unchanged
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.broker import BrokerPosition, Fill, MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard  # noqa: F401
from global_index.runner import FuturesRunner, _openpos_from_dict, _openpos_to_dict
from futures.circuit_breaker import CircuitBreaker

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
DAY1 = pd.Timestamp("2024-03-11")
DAY2 = pd.Timestamp("2024-03-12")


# ── helpers ───────────────────────────────────────────────────────────────────

class _RecordingMockBroker(MockBroker):
    """MockBroker that records place_stop / cancel_order / get_order_status calls."""

    def __init__(self, bars, account, stp_status="PENDING"):
        super().__init__(bars, account)
        self.stp_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self._stp_status = stp_status  # returned by get_order_status()

    def place_stop(self, inst, direction, contracts, stop_price, cluster):
        order_id = f"stp-{inst}-{len(self.stp_calls)}"
        self.stp_calls.append(dict(
            inst=inst, direction=direction, contracts=contracts,
            stop_price=stop_price, cluster=cluster, order_id=order_id,
        ))
        return order_id

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        return True

    def get_order_status(self, order_id):
        return self._stp_status


class _CancelledOpenBroker(MockBroker):
    """Returns CANCELLED for OPEN orders — simulates entry timeout."""

    def send_order(self, o):
        if o.action == "OPEN":
            return Fill(o.inst, o.action, o.direction, o.contracts, o.cluster,
                        status="CANCELLED", error_msg="entry timeout")
        return super().send_order(o)

    def place_stop(self, inst, _d, _c, _sp, _cl):
        raise AssertionError("place_stop must NOT be called after CANCELLED OPEN")

    def cancel_order(self, _oid): return True
    def get_order_status(self, _oid): return "PENDING"


def _make_guard():
    return MultiClusterGuard(clusters={
        "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05, max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
        "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
    }, account=ACCOUNT)


def _multi_day_signal(day, bars, held):
    """DAY1: open a multi-day swing position (exit_day = DAY2)."""
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=5000.0, stop=4950.0,
                     exit=DAY2, pnl_sized=150.0)], []
    # DAY2: close the position
    return [], ([held[0]] if held else [])


def _sameday_signal(day, bars, held):
    """Open and close on the same day (STRESS_MID style)."""
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=5000.0, stop=4950.0,
                     exit=DAY1, pnl_sized=100.0)], []
    return [], []


# ── STP1: place_stop called after multi-day OPEN ─────────────────────────────

def test_stp1_place_stop_called_after_multiday_open(tmp_path):
    broker = _RecordingMockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )
    runner.run_day(DAY1)

    assert len(broker.stp_calls) == 1, f"Expected 1 place_stop call, got {broker.stp_calls}"
    c = broker.stp_calls[0]
    assert c["inst"] == "MES"
    assert c["direction"] == "LONG"
    assert c["stop_price"] == 4950.0
    assert c["cluster"] == CLUSTER

    # stop_price + stop_order_id stored in OpenPos
    pos = runner.state.open_positions[0]
    assert pos.stop_price == 4950.0
    assert pos.stop_order_id == "stp-MES-0"


# ── STP2: round-trip JSON serialisation ──────────────────────────────────────

def test_stp2_json_roundtrip():
    p = OpenPos(
        inst="MES", direction="LONG", contracts=1, risk_dollars=500.0,
        cluster=CLUSTER, entry_day=pd.Timestamp("2024-03-11"),
        stop_price=4950.0, stop_order_id="ibkr-123",
    )
    d = _openpos_to_dict(p)
    assert d["stop_price"] == 4950.0
    assert d["stop_order_id"] == "ibkr-123"

    restored = _openpos_from_dict(d)
    assert restored.stop_price == 4950.0
    assert restored.stop_order_id == "ibkr-123"


def test_stp2b_json_roundtrip_no_stp():
    """Legacy positions without stop fields load with None defaults."""
    raw = dict(
        inst="MNQ", direction="SHORT", contracts=1, risk_dollars=400.0,
        cluster="swing_tf_MNQ_SHORT", entry_day="2024-03-11",
    )
    p = _openpos_from_dict(raw)
    assert p.stop_price is None
    assert p.stop_order_id is None


# ── STP3: no place_stop for same-day entries ─────────────────────────────────

def test_stp3_no_stp_for_sameday_entry():
    broker = _RecordingMockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_sameday_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
    )
    runner.run_day(DAY1)
    assert broker.stp_calls == [], "place_stop must NOT be called for same-day entries"


# ── STP4: no place_stop when OPEN fill is CANCELLED ──────────────────────────

def test_stp4_no_stp_when_open_cancelled():
    broker = _CancelledOpenBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
    )
    # Must not raise (asserting inside _CancelledOpenBroker.place_stop)
    runner.run_day(DAY1)


# ── STP5: B3 STP EXIT auto-clear ─────────────────────────────────────────────

def test_stp5_b3_stp_exit_auto_clear(tmp_path):
    pos_file = tmp_path / "pos.json"

    # Write a persisted position with stop_order_id
    state = {
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": 4950.0, "stop_order_id": "ibkr-456",
        }],
        "breaker": {},
    }
    pos_file.write_text(json.dumps(state))

    # Broker reports 0 positions (STP filled overnight) and status=FILLED
    broker = _RecordingMockBroker({}, ACCOUNT, stp_status="FILLED")
    # get_positions returns [] — IBKR has no open position
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )

    # B3 STP EXIT: auto-cleared, no halt
    assert not runner._b3_halt_entries, "STP EXIT: halt must NOT fire"
    assert runner.state.open_positions == [], "STP EXIT: position must be cleared from state"


# ── STP6: B3 MISMATCH with stop_order_id NOT_FOUND → CRITICAL + halt ─────────

def test_stp6_b3_mismatch_stp_not_found_halts(tmp_path):
    pos_file = tmp_path / "pos.json"
    state = {
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": 4950.0, "stop_order_id": "ibkr-789",
        }],
        "breaker": {},
    }
    pos_file.write_text(json.dumps(state))

    broker = _RecordingMockBroker({}, ACCOUNT, stp_status="NOT_FOUND")
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )

    assert runner._b3_halt_entries, "STP NOT_FOUND mismatch must still halt entries"
    assert len(runner.state.open_positions) == 1, "Position remains in state pending resolution"


# ── STP7: B3 MISMATCH without stop_order_id → original behavior ──────────────

def test_stp7_b3_mismatch_no_stp_still_halts(tmp_path):
    pos_file = tmp_path / "pos.json"
    state = {
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
        }],
        "breaker": {},
    }
    pos_file.write_text(json.dumps(state))

    # IBKR has 0 MES (no stop_order_id, so it's a genuine orphan)
    broker = MockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )

    assert runner._b3_halt_entries, "Orphan (no STP) mismatch must halt entries"


# ── STP8: cancel_order called on successful CLOSE for position with stop_order_id ──

def test_stp8_cancel_called_on_close(tmp_path):
    """When runner sends CLOSE for a multi-day position that has a GTC stop,
    cancel_order(stop_order_id) must be called so the orphan stop cannot
    create an unintended position after the LONG/SHORT is gone."""
    broker = _RecordingMockBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )

    # DAY1: entry → STP placed, stop_order_id stored
    runner.run_day(DAY1)
    assert len(broker.stp_calls) == 1, "STP must be placed on DAY1"
    placed_id = broker.stp_calls[0]["order_id"]
    assert runner.state.open_positions[0].stop_order_id == placed_id

    # DAY2: exit → cancel_order must be called with the stop_order_id
    runner.run_day(DAY2)
    assert runner.state.open_positions == [], "Position must be closed on DAY2"
    assert placed_id in broker.cancel_calls, (
        f"cancel_order({placed_id!r}) not called on CLOSE; "
        f"cancel_calls={broker.cancel_calls}"
    )


# ── STP9: cancel_order returning False must raise an orphan alert ────────────

class _CancelFailsBroker(_RecordingMockBroker):
    """cancel_order reports failure the way IBKRBroker does — by returning False,
    not by raising. Seen live 2026-08-05: two GTC stops stayed working at IBKR for
    days while the runner logged 'cancelled' for both."""

    def cancel_order(self, order_id):
        self.cancel_calls.append(order_id)
        return False


def test_stp9_orphan_alert_when_cancel_fails(tmp_path):
    """A stop that could not be cancelled is still live at the broker and will fire
    against a position that no longer exists. The runner must say so."""
    broker = _CancelFailsBroker({}, ACCOUNT)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )

    runner.run_day(DAY1)
    placed_id = broker.stp_calls[0]["order_id"]

    runner.run_day(DAY2)
    assert placed_id in broker.cancel_calls, "cancel_order must still be attempted"

    orphan = [e for e in runner._events
              if e["level"] == "CRITICAL" and e["category"] == "ORDER"]
    assert orphan, (
        "cancel_order returned False but no CRITICAL/ORDER event was emitted — "
        f"the orphan stop {placed_id!r} is invisible. events={runner._events}"
    )
    assert placed_id in orphan[0]["message"], (
        f"orphan alert must name the order id; got {orphan[0]['message']!r}"
    )


# ── B4: naked-position check (open at broker, no stop order) ─────────────────

def _naked_broker(stop_working=False, working_raises=None):
    """MockBroker holding one MES LONG at the broker, for B4 tests."""
    b = _RecordingMockBroker({}, ACCOUNT)
    b._positions = [BrokerPosition("MES", "LONG", 1, CLUSTER, DAY1, None, 0.0)]
    if working_raises is not None:
        b.has_working_stop = lambda _inst: (_ for _ in ()).throw(working_raises)
    else:
        b.has_working_stop = lambda _inst: stop_working
    return b


def _naked_file(tmp_path, stop_price=None, stop_order_id=None):
    pos_file = tmp_path / "pos.json"
    pos_file.write_text(json.dumps({
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": stop_price, "stop_order_id": stop_order_id,
        }],
        "breaker": {},
    }))
    return pos_file


def _make_runner(broker, pos_file):
    return FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )


def test_b4_1_replaces_stop_when_level_known_and_none_working(tmp_path):
    """stop_price known + no working stop at broker → re-place, record orderId."""
    broker = _naked_broker(stop_working=False)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert len(broker.stp_calls) == 1, "B4 must re-place the missing stop"
    assert broker.stp_calls[0]["stop_price"] == 4950.0
    assert runner.state.open_positions[0].stop_order_id == broker.stp_calls[0]["order_id"]
    assert not runner._b3_halt_entries, "B4 must not halt entries"


def test_b4_2_no_duplicate_when_stop_already_working(tmp_path):
    """A stop is already live at the broker → must NOT stack a second one."""
    broker = _naked_broker(stop_working=True)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert broker.stp_calls == [], "duplicate STP would double-close and flip the position"
    assert runner._b4_naked_stops == [("MES", CLUSTER)]


def test_b4_3_alerts_when_stop_price_unknown(tmp_path):
    """The live 2026-08-03 case: OPEN misread as Cancelled → both fields None.
    Level is unknown, so B4 can only alert — never guess a stop level."""
    broker = _naked_broker(stop_working=False)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=None))

    assert broker.stp_calls == [], "no level known → must not place"
    assert runner._b4_naked_stops == [("MES", CLUSTER)]
    assert not runner._b3_halt_entries, "naked position is not a state mismatch"
    assert len(runner.state.open_positions) == 1, "position must stay in state"


def test_b4_4_no_place_when_broker_cannot_report_working_stops(tmp_path):
    """Broker can't answer has_working_stop → alert, don't place blind."""
    broker = _naked_broker(working_raises=NotImplementedError())
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0))

    assert broker.stp_calls == [], "unverifiable → duplicate-stop risk → must not place"
    assert runner._b4_naked_stops == [("MES", CLUSTER)]


def test_b4_5_noharm_position_with_stop_is_not_naked(tmp_path):
    """Position already carrying a stop_order_id → B4 stays silent."""
    broker = _naked_broker(stop_working=False)
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0,
                                              stop_order_id="ibkr-111"))

    assert broker.stp_calls == [], "already protected — nothing to do"
    assert runner._b4_naked_stops == []
    assert not runner._b3_halt_entries


# ── B4.6/B4.7: a recorded stop_order_id is not evidence of a working stop ────
#
# Live 2026-08-05: place_stop returned client-side ids 62/66/70, which were persisted
# to live_positions.json. B4's trigger was `stop_order_id is None`, so three naked
# positions read as protected and B4 — the guard written for exactly this — stayed
# silent. Detection must key off broker truth, not off the field the broken path wrote.


def _reporting_broker(working: dict):
    """MockBroker that CAN report working stops (unlike plain MockBroker → None)."""
    b = _naked_broker(stop_working=bool(working))
    b.get_working_stops = lambda: dict(working)
    return b


def test_b4_6_fabricated_stop_id_with_no_working_stop_is_naked(tmp_path):
    """stop_order_id recorded, but the broker holds no stop for that instrument."""
    broker = _reporting_broker({})          # broker answers: nothing is working
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0,
                                              stop_order_id="62"))

    assert runner._b4_naked_stops == [("MES", CLUSTER)], (
        "a recorded stop_order_id must not suppress B4 when the broker reports "
        "no working stop — this is the 2026-08-05 failure"
    )
    assert len(broker.stp_calls) == 1, "level is known and nothing is working → re-place"


def test_b4_7_working_stop_at_broker_is_not_naked(tmp_path):
    """Broker confirms a stop is working → B4 silent, no duplicate placed."""
    broker = _reporting_broker({"MES": "62"})
    runner = _make_runner(broker, _naked_file(tmp_path, stop_price=4950.0,
                                              stop_order_id="62"))

    assert runner._b4_naked_stops == []
    assert broker.stp_calls == [], "must not stack a second STP on a protected position"


# ── STP10: end-of-session sweep — a naked position must not wait for tomorrow ─
#
# B4 runs at startup, so a stop that fails to reach IBKR is only noticed on the NEXT
# slot — or, if the scheduler has finished for the day, not until tomorrow. On
# 2026-08-05 the entries ran at 14:40 ET and the gap was found that evening by hand.
# The runner already knows the answer before it disconnects; it just never asked.


def test_stp10_session_end_flags_position_with_no_working_stop(tmp_path):
    """After entries, before disconnect: every open position must have a live stop."""
    broker = _RecordingMockBroker({}, ACCOUNT)
    broker.get_working_stops = lambda: {}     # broker: nothing is working
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )

    runner.run_day(DAY1)

    assert runner.state.open_positions, "position must be open for this test to mean anything"
    unprotected = [e for e in runner._events
                   if e["level"] == "CRITICAL" and e["category"] == "ORDER"
                   and "UNPROTECTED" in e["message"]]
    assert unprotected, (
        "position is open and the broker reports no working stop, but the session "
        f"ended without saying so. events={runner._events}"
    )
    assert "MES" in unprotected[0]["message"]


def test_stp11_session_end_silent_when_stop_is_working(tmp_path):
    """Broker confirms the stop → no alert. Guards against crying wolf every slot."""
    broker = _RecordingMockBroker({}, ACCOUNT)
    broker.get_working_stops = lambda: {"MES": "stp-MES-0"}
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )

    runner.run_day(DAY1)

    unprotected = [e for e in runner._events
                   if e["level"] == "CRITICAL" and "UNPROTECTED" in e["message"]]
    assert unprotected == [], f"stop is working — must stay quiet. got {unprotected}"


def test_stp12_session_end_quiet_when_broker_cannot_report(tmp_path):
    """MockBroker answers None → no claim either way, no alert (reconcile unchanged)."""
    broker = _RecordingMockBroker({}, ACCOUNT)   # inherits get_working_stops → None
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=_multi_day_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )

    runner.run_day(DAY1)

    unprotected = [e for e in runner._events
                   if e["level"] == "CRITICAL" and "UNPROTECTED" in e["message"]]
    assert unprotected == [], "a broker that cannot testify must not trigger alarms"


# ── STP13: a stop-triggered exit must leave a trade record ───────────────────
#
# When a stop fires, the runner sends no order — so nothing on the send_order path
# writes a trade record, and the exit price of the trade is never captured. Chandelier
# stops are 79.5% of exits, so this is most of them.
#
# B3's STP-VERIFY branch is the one place that both notices the exit and holds the fill:
# it asks IBKR, gets price/size/time/permId back, and used to keep only "yes it filled".
# Measured 2026-08-07: reqExecutions served that fill on the day and had forgotten it by
# the next, so this is the only moment it can be recorded.


class _StopFilledBroker(_RecordingMockBroker):
    """IBKR holds no position; the recorded stop shows as gone but did execute."""

    def __init__(self, bars, account, fill):
        super().__init__(bars, account, stp_status="NOT_FOUND")
        self._fill = fill

    def find_execution(self, order_id):
        return dict(self._fill) if str(order_id) == "ibkr-456" else None


def test_stp13_stop_exit_is_written_to_the_trade_log(tmp_path):
    pos_file = tmp_path / "pos.json"
    pos_file.write_text(json.dumps({
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": 4950.0, "stop_order_id": "ibkr-456",
        }],
        "breaker": {},
    }))
    log_path = tmp_path / "trade_log.jsonl"
    broker = _StopFilledBroker({}, ACCOUNT, fill={
        "order_id": 456, "perm_id": 375088794,
        "price": 4948.75, "shares": 1, "time": "2024-03-12 14:31:02",
    })

    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
        trade_log_path=log_path,
    )

    assert runner.state.open_positions == [], "position must be cleared"
    assert log_path.exists(), (
        "the stop fill was confirmed and then not recorded anywhere — nothing else "
        "writes a trade record for a stop-triggered exit"
    )
    recs = [json.loads(l) for l in log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    closes = [r for r in recs if r.get("type") == "CLOSE"]
    assert len(closes) == 1, f"expected one CLOSE record, got {recs}"
    c = closes[0]
    assert c["fill_price"] == pytest.approx(4948.75), "the exit price is the point"
    assert c["perm_id"] == 375088794, "permId is the stable key across clients"
    # Joined with what only the runner knows — IBKR cannot supply any of these.
    assert (c["inst"], c["cluster"], c["direction"]) == ("MES", CLUSTER, "LONG")
    assert c["entry_day"] == "2024-03-11"
    assert c["exit_reason"] == "STP", "must be distinguishable from a signal exit"


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
