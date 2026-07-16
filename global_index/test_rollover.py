"""
global_index/test_rollover.py — C2 rollover logic tests (offline, MockBroker)

Tests _handle_rollover_if_needed() (runner.py) via injected broker with _handle_rollover.
_handle_rollover in IBKRBroker uses live Gateway; these tests verify the runner
logic for all 3 Fill-outcome branches without a connection.

Cases:
  RO1: SUCCESS (FILLED, FILLED) → position unchanged in state, slippage logged
  RO2: CLOSE fail (FAILED, *) → position UNCHANGED in state (IBKR still holds it)
  RO3: OPEN fail AFTER CLOSE (FILLED, FAILED) → position REMOVED from state (FLAT in IBKR)
  RO4: not a roll day (None) → position unchanged (no-op)
  RO5: ROLL_SCHEDULE 2026 dates correct — get_roll_event returns right months
  RO6: interaction — MAX_HOLD closes 09:31; rollover at 14:05 finds nothing to roll
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.broker import Fill, MockBroker
from global_index.ibkr_broker import get_roll_event
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner
from futures.circuit_breaker import CircuitBreaker

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
ENTRY_DAY = pd.Timestamp("2026-06-10")
ROLL_DAY  = pd.Timestamp("2026-06-12")   # MES/MNQ/MYM/M2K roll 202606→202609


def _make_guard():
    return MultiClusterGuard(clusters={
        "roska4_swing": ClusterBudget("roska4_swing", max_gross_pct=0.05, max_net_pct=0.044),
    }, account=ACCOUNT)


def _inject(runner, inst="MES", direction="LONG"):
    p = OpenPos(
        inst=inst, direction=direction, contracts=1, risk_dollars=500.0,
        cluster=CLUSTER, entry_day=ENTRY_DAY,
        stop_price=None, stop_order_id=None,
    )
    runner.state.open_positions.append(p)
    return p


# ── custom broker with _handle_rollover ───────────────────────────────────────

class _RollBroker(MockBroker):
    """MockBroker that implements _handle_rollover for C2 rollover logic tests."""

    def __init__(self, bars, account, *, close_status="FILLED", open_status="FILLED",
                 is_roll_day=True):
        super().__init__(bars, account)
        self._close_status = close_status
        self._open_status  = open_status
        self._is_roll_day  = is_roll_day
        self.roll_calls: list = []

    def _handle_rollover(self, inst, today, direction, contracts, cluster):
        self.roll_calls.append({"inst": inst, "today": today, "direction": direction})
        if not self._is_roll_day:
            return None  # not a roll date
        close_fill = Fill(inst, "CLOSE", direction, contracts, cluster,
                          status=self._close_status,
                          avg_price=21000.0 if self._close_status == "FILLED" else 0.0)
        open_fill  = Fill(inst, "OPEN",  direction, contracts, cluster,
                          status=self._open_status,
                          avg_price=21010.0 if self._open_status == "FILLED" else 0.0,
                          error_msg=None if self._open_status == "FILLED"
                                    else "roll-open timeout — position flat")
        return close_fill, open_fill


def _make_roll_runner(broker):
    return FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
    )


# ── RO1 ───────────────────────────────────────────────────────────────────────

def test_ro1_success_position_unchanged():
    """Roll SUCCESS (FILLED, FILLED) → position stays in open_positions."""
    broker = _RollBroker({}, ACCOUNT, close_status="FILLED", open_status="FILLED")
    runner = _make_roll_runner(broker)
    _inject(runner)

    runner._handle_rollover_if_needed(ROLL_DAY)

    assert len(runner.state.open_positions) == 1, (
        "SUCCESS roll: position must remain in open_positions (still open, now in new contract)"
    )
    assert len(broker.roll_calls) == 1
    assert broker.roll_calls[0]["inst"] == "MES"


# ── RO2 ───────────────────────────────────────────────────────────────────────

def test_ro2_close_fail_position_unchanged():
    """CLOSE fail → roll ABORTED, position UNCHANGED in state (IBKR still holds front-month)."""
    broker = _RollBroker({}, ACCOUNT, close_status="FAILED", open_status="FAILED")
    runner = _make_roll_runner(broker)
    _inject(runner)

    runner._handle_rollover_if_needed(ROLL_DAY)

    assert len(runner.state.open_positions) == 1, (
        "CLOSE-fail branch: position must remain unchanged — IBKR still holds it in old contract"
    )


# ── RO3 ───────────────────────────────────────────────────────────────────────

def test_ro3_open_fail_after_close_flat():
    """CLOSE OK but OPEN fails → position FLAT in IBKR. Runner must remove from state
    and emit CRITICAL so operator can intervene. This is the most dangerous branch."""
    broker = _RollBroker({}, ACCOUNT, close_status="FILLED", open_status="FAILED")
    runner = _make_roll_runner(broker)
    _inject(runner)

    runner._handle_rollover_if_needed(ROLL_DAY)

    assert len(runner.state.open_positions) == 0, (
        "OPEN-fail-FLAT branch: position must be REMOVED from runner state "
        "(IBKR is flat; keeping it in state would cause phantom close on next run_day)"
    )


# ── RO3b ──────────────────────────────────────────────────────────────────────

def test_ro3b_open_fail_persists_immediately(tmp_path):
    """I5.13: OPEN-fail branch must persist JSON immediately (not just at end of run_day).
    Crash-window: runner removes position from memory, then crash before end-of-run_day.
    Without I5.13 fix: JSON still shows position → restart sees mismatch, operator confused.
    With fix: JSON already flat before crash-window."""
    pos_file = tmp_path / "pos.json"

    broker = _RollBroker({}, ACCOUNT, close_status="FILLED", open_status="FAILED")
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={}, signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )
    _inject(runner)

    # Before: pos_file may not exist (no prior persist)
    runner._handle_rollover_if_needed(ROLL_DAY)

    # After: position removed from memory
    assert len(runner.state.open_positions) == 0, "Position must be removed from memory"

    # After: JSON must be written immediately (I5.13) — not deferred to end of run_day
    assert pos_file.exists(), "JSON must be written by _persist_state() in OPEN-fail branch"
    import json
    data = json.loads(pos_file.read_text())
    assert data["positions"] == [], (
        "JSON positions must be empty after OPEN-fail persist — "
        "crash now would show flat truth, not stale 'has position'"
    )


# ── RO4 ───────────────────────────────────────────────────────────────────────

def test_ro4_not_roll_day_no_op():
    """Non-roll day → _handle_rollover returns None → runner no-op, position unchanged."""
    broker = _RollBroker({}, ACCOUNT, is_roll_day=False)
    runner = _make_roll_runner(broker)
    _inject(runner)

    non_roll_day = pd.Timestamp("2026-06-11")  # day before roll
    runner._handle_rollover_if_needed(non_roll_day)

    assert len(runner.state.open_positions) == 1, "Non-roll day: position must be unchanged"
    assert len(broker.roll_calls) == 1, "_handle_rollover was still called (it returns None)"


# ── RO5 ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("inst,roll_date,expected_front,expected_next", [
    ("MES", "2026-03-13", "202603", "202606"),
    ("MES", "2026-06-12", "202606", "202609"),
    ("MES", "2026-09-11", "202609", "202612"),
    ("MES", "2026-12-11", "202612", "202703"),
    ("MNQ", "2026-06-12", "202606", "202609"),
    ("MYM", "2026-09-11", "202609", "202612"),
    ("M2K", "2026-12-11", "202612", "202703"),
    ("NKD", "2026-03-06", "202603", "202606"),
    ("NKD", "2026-06-05", "202606", "202609"),
    ("NKD", "2026-09-04", "202609", "202612"),
    ("NKD", "2026-12-04", "202612", "202703"),
])
def test_ro5_roll_schedule_2026(inst, roll_date, expected_front, expected_next):
    """ROLL_SCHEDULE 2026 dates: correct (front_month, next_month) on roll day."""
    result = get_roll_event(inst, roll_date)
    assert result is not None, f"{inst} roll on {roll_date} should return (front, next)"
    front, nxt = result
    assert front == expected_front, f"{inst} {roll_date}: expected front={expected_front}, got {front}"
    assert nxt   == expected_next,  f"{inst} {roll_date}: expected next={expected_next}, got {nxt}"


def test_ro5b_non_roll_day_returns_none():
    """Non-roll date returns None for all instruments."""
    assert get_roll_event("MES", "2026-06-11") is None
    assert get_roll_event("NKD", "2026-09-05") is None
    assert get_roll_event("XXX", "2026-06-12") is None  # unknown inst


# ── RO6 ───────────────────────────────────────────────────────────────────────

def test_ro6_maxhold_then_rollover_no_conflict(tmp_path):
    """MAX_HOLD closes at 09:31, persists. Fresh 14:05 runner finds nothing to roll."""
    pos_file = tmp_path / "pos.json"

    # 09:31 cron: close position
    broker1 = MockBroker({}, ACCOUNT)
    runner1 = FuturesRunner(
        broker=broker1, guard=_make_guard(),
        contracts_by_inst={}, signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )
    _inject(runner1)
    runner1.run_maxhold_exit(ROLL_DAY, max_hold_days=5)

    # 14:05 cron: fresh runner with rollover broker
    broker2 = _RollBroker({}, ACCOUNT)
    runner2 = FuturesRunner(
        broker=broker2, guard=_make_guard(),
        contracts_by_inst={}, signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_file,
    )

    assert runner2.state.open_positions == [], "14:05 runner sees empty state (09:31 already closed)"
    runner2._handle_rollover_if_needed(ROLL_DAY)
    assert broker2.roll_calls == [], "No rollover attempt — nothing in open_positions"


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
