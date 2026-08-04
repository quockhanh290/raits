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


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
