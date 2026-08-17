"""
global_index/test_maxhold.py — MAX_HOLD exit logic tests (offline, MockBroker)

Cases:
  MH1: hold ≥ 5d → CLOSE + GTC STP cancel → position removed from state
  MH2: hold < 5d → no CLOSE, position stays
  MH3: CLOSE fails → exit_pending=True, position stays (retry at 14:05)
  MH4: cancel_order fails after CLOSE success → non-fatal, position still removed
  MH5: double-close guard — 09:31 close+persist; fresh 14:05 runner sees empty state
  MH6: _retry_pending_exits clears exit_pending on success (via run_day)
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.broker import Fill, MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner
from futures.circuit_breaker import CircuitBreaker

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
DAY0 = pd.Timestamp("2024-03-04")   # entry day (calendar T-7, bday T-5)
DAY5 = pd.Timestamp("2024-03-11")   # (DAY5 - DAY0).days = 7 → well above 5 → MAX_HOLD fires


def _make_guard():
    return MultiClusterGuard(clusters={
        "roska4_swing": ClusterBudget("roska4_swing", max_gross_pct=0.05, max_net_pct=0.044),
    }, account=ACCOUNT)


def _make_runner(broker, pos_path=None):
    return FuturesRunner(
        broker=broker, guard=_make_guard(),
        contracts_by_inst={},
        signal_fn=lambda d, b, h: ([], []),
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=pos_path,
    )


def _inject(runner, entry_day=DAY0, stop_order_id="stp-MES-0"):
    p = OpenPos(
        inst="MES", direction="LONG", contracts=1, risk_dollars=500.0,
        cluster=CLUSTER, entry_day=entry_day,
        stop_price=4950.0, stop_order_id=stop_order_id,
    )
    runner.state.open_positions.append(p)
    return p


# ── custom brokers ─────────────────────────────────────────────────────────────

class _FailCloseBroker(MockBroker):
    def send_order(self, o):
        if o.action == "CLOSE":
            return Fill(o.inst, o.action, o.direction, o.contracts, o.cluster,
                        status="FAILED", error_msg="mock CLOSE failure")
        return super().send_order(o)


class _FailCancelBroker(MockBroker):
    """CLOSE succeeds; cancel_order raises (simulates GTC cancel timeout)."""
    def cancel_order(self, _oid):
        raise RuntimeError("cancel_order timed out")

    def place_stop(self, inst, _d, _c, _sp, _cl, contract_month=None):
        return f"stp-{inst}"


# ── MH1 ───────────────────────────────────────────────────────────────────────

def test_mh1_hold5_close_cancel_stp_removed(tmp_path):
    """hold ≥ 5d → CLOSE sent, GTC STP cancelled, position removed from state."""
    broker = MockBroker({}, ACCOUNT)
    runner = _make_runner(broker, pos_path=tmp_path / "pos.json")
    _inject(runner, entry_day=DAY0, stop_order_id="stp-abc")

    closed = runner.run_maxhold_exit(DAY5, max_hold_days=5)

    assert ("MES", CLUSTER) in closed, f"Expected MES/{CLUSTER} in closed list"
    assert runner.state.open_positions == [], "Position must be removed from state after close"


# ── MH2 ───────────────────────────────────────────────────────────────────────

def test_mh2_hold4_keep():
    """hold < 5d → no CLOSE, position stays."""
    broker = MockBroker({}, ACCOUNT)
    runner = _make_runner(broker)
    _inject(runner, entry_day=pd.Timestamp("2024-03-08"))  # (DAY5 - mar8).days = 3

    closed = runner.run_maxhold_exit(DAY5, max_hold_days=5)

    assert closed == [], "No position should be closed (hold = 3 < 5)"
    assert len(runner.state.open_positions) == 1, "Position must remain in state"


# ── MH3 ───────────────────────────────────────────────────────────────────────

def test_mh3_close_fail_exit_pending(tmp_path):
    """CLOSE fails → exit_pending=True, position stays for _retry_pending_exits at 14:05."""
    broker = _FailCloseBroker({}, ACCOUNT)
    runner = _make_runner(broker, pos_path=tmp_path / "pos.json")
    _inject(runner, entry_day=DAY0)

    closed = runner.run_maxhold_exit(DAY5, max_hold_days=5)

    assert closed == [], "No position should be reported closed when CLOSE fails"
    assert len(runner.state.open_positions) == 1, "Position must remain in state"
    assert runner.state.open_positions[0].exit_pending is True, (
        "exit_pending must be set so _retry_pending_exits retries at 14:05"
    )


# ── MH4 ───────────────────────────────────────────────────────────────────────

def test_mh4_cancel_fail_nonfatal(tmp_path):
    """cancel_order fails → logged as ERROR, non-fatal. Position still removed (STP orphaned)."""
    broker = _FailCancelBroker({}, ACCOUNT)
    runner = _make_runner(broker, pos_path=tmp_path / "pos.json")
    _inject(runner, entry_day=DAY0, stop_order_id="stp-xyz")

    closed = runner.run_maxhold_exit(DAY5, max_hold_days=5)

    assert ("MES", CLUSTER) in closed, "Position must be closed despite cancel_order failure"
    assert runner.state.open_positions == [], (
        "Position must be removed from state even if STP cancel fails"
    )


# ── MH5 ───────────────────────────────────────────────────────────────────────

def test_mh5_double_close_guard(tmp_path):
    """09:31 run_maxhold_exit closes+persists; fresh 14:05 runner reads empty state.
    run_day must emit zero CLOSE orders (no double-close)."""
    pos_file = tmp_path / "pos.json"

    # Simulate 09:31 cron
    broker1 = MockBroker({}, ACCOUNT)
    runner1 = _make_runner(broker1, pos_path=pos_file)
    _inject(runner1, entry_day=DAY0)
    closed1 = runner1.run_maxhold_exit(DAY5, max_hold_days=5)
    assert len(closed1) == 1, "09:31 runner must close the position"

    # Simulate 14:05 cron — fresh process reads same file
    broker2 = MockBroker({}, ACCOUNT)
    runner2 = _make_runner(broker2, pos_path=pos_file)
    assert runner2.state.open_positions == [], (
        "14:05 runner must see empty state after 09:31 close+persist"
    )

    runner2.run_day(DAY5)
    close_fills = [f for f in broker2.fills if f.action == "CLOSE"]
    assert close_fills == [], "run_day must emit no CLOSE orders — position already gone"


# ── MH6 ───────────────────────────────────────────────────────────────────────

def test_mh6_retry_pending_clears(tmp_path):
    """exit_pending=True from prior failed CLOSE → _retry_pending_exits at 14:05 clears it."""
    pos_file = tmp_path / "pos.json"
    state_data = {
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-04", "exit_day": None,
            "pnl_sized": 0.0, "exit_pending": True,
        }],
        "breaker": {},
    }
    pos_file.write_text(json.dumps(state_data))

    broker = MockBroker({}, ACCOUNT)  # send_order CLOSE returns FILLED by default
    runner = _make_runner(broker, pos_path=pos_file)

    # _retry_pending_exits fires at the start of run_day
    runner.run_day(DAY5)

    assert runner.state.open_positions == [], (
        "_retry_pending_exits must clear exit_pending position when CLOSE succeeds"
    )


# ── MH7 ───────────────────────────────────────────────────────────────────────

class _FalseCancelBroker(MockBroker):
    """cancel_order returns False — how IBKRBroker actually reports failure.

    MH4 covers the raising case. This is the one that happened live on 2026-08-05:
    no exception, just False, and the runner logged 'cancelled' anyway.
    """
    def cancel_order(self, _oid):
        return False

    def place_stop(self, inst, _d, _c, _sp, _cl, contract_month=None):
        return f"stp-{inst}"


def test_mh7_orphan_alert_when_cancel_returns_false(tmp_path):
    """A stop left working after MAX_HOLD close must be reported, not assumed gone."""
    broker = _FalseCancelBroker({}, ACCOUNT)
    runner = _make_runner(broker, pos_path=tmp_path / "pos.json")
    _inject(runner, entry_day=DAY0, stop_order_id="stp-xyz")

    closed = runner.run_maxhold_exit(DAY5, max_hold_days=5)

    assert ("MES", CLUSTER) in closed, "Position must still be closed"
    orphan = [e for e in runner._events
              if e["level"] == "CRITICAL" and e["category"] == "ORDER"]
    assert orphan, (
        "cancel_order returned False but no CRITICAL/ORDER event was emitted — "
        f"orphan stop 'stp-xyz' is invisible. events={runner._events}"
    )
    assert "stp-xyz" in orphan[0]["message"], (
        f"orphan alert must name the order id; got {orphan[0]['message']!r}"
    )


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
