"""The stop, when a position rolls to the next contract.

_handle_rollover closes the front month and opens the next, and until now said
"position continues unchanged" — which was true of the position and false of its
protection. The old contract's STP stayed working while the new contract carried
nothing, and B4/B5 both matched stops on the instrument symbol, so the orphan made
the new position read as protected.

An orphaned stop is worse than no stop. A SELL STP with no long behind it does not
sit idle; it fills into a short nobody asked for, on a contract about to expire.

Next roll: 2026-09-11, the first this append pipeline will ever see.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import Fill
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner
from global_index.test_rollover import MockBroker

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
ROLL_DAY = pd.Timestamp("2026-09-11")


def _guard():
    return MultiClusterGuard(clusters={
        CLUSTER: ClusterBudget(CLUSTER, max_gross_pct=0.05, max_net_pct=0.044),
    }, account=ACCOUNT)


class _RollBroker(MockBroker):
    """Rolls once, records what happened to the stop around it."""

    def __init__(self, *a, close_ok=True, open_ok=True, stop_accepted=True,
                 cancel_ok=True, **kw):
        super().__init__(*a, **kw)
        self.cancelled: list = []
        self.placed: list = []
        self._close_ok, self._open_ok = close_ok, open_ok
        self._stop_accepted, self._cancel_ok = stop_accepted, cancel_ok

    def _handle_rollover(self, inst, day, direction, contracts, cluster):
        if str(pd.Timestamp(day).date()) != str(ROLL_DAY.date()):
            return None
        return (
            Fill(inst=inst, action="CLOSE", direction=direction, contracts=contracts,
                 cluster=cluster, avg_price=7747.25,
                 status="FILLED" if self._close_ok else "FAILED"),
            Fill(inst=inst, action="OPEN", direction=direction, contracts=contracts,
                 cluster=cluster, avg_price=7814.00,
                 status="FILLED" if self._open_ok else "FAILED"),
        )

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return self._cancel_ok

    def place_stop(self, inst, direction, contracts, stop_price, cluster):
        self.placed.append((inst, direction, contracts, round(stop_price, 4), cluster))
        return "stp-new" if self._stop_accepted else ""


def _runner(broker, pos=None):
    r = FuturesRunner(broker=broker, guard=_guard(), contracts_by_inst={},
                      signal_fn=lambda d, b, h: ([], []),
                      breaker=CircuitBreaker(account=ACCOUNT))
    if pos is not None:
        r.state.open_positions.append(pos)
    return r


def _pos(stop_price=7700.0, stop_order_id="stp-old"):
    return OpenPos(inst="MES", direction="LONG", contracts=1, risk_dollars=500.0,
                   cluster=CLUSTER, entry_day=pd.Timestamp("2026-09-08"),
                   stop_price=stop_price, stop_order_id=stop_order_id)


def test_old_stop_is_cancelled():
    """The orphan is the dangerous half — it can fill into a new position."""
    b = _RollBroker({}, ACCOUNT)
    _runner(b, _pos())._handle_rollover_if_needed(ROLL_DAY)
    assert b.cancelled == ["stp-old"]


def test_new_stop_is_placed_shifted_by_the_realised_spread():
    """close@7747.25 → open@7814.00 is +66.75 of contract difference, not a market
    move. The stop has to travel with it or it sits 66.75 further from price than
    the chandelier intended."""
    b = _RollBroker({}, ACCOUNT)
    p = _pos(stop_price=7700.0)
    _runner(b, p)._handle_rollover_if_needed(ROLL_DAY)
    assert b.placed == [("MES", "LONG", 1, 7766.75, CLUSTER)]
    assert p.stop_price == pytest.approx(7766.75)
    assert p.stop_order_id == "stp-new"


def test_nothing_happens_when_it_is_not_a_roll_day():
    b = _RollBroker({}, ACCOUNT)
    p = _pos()
    _runner(b, p)._handle_rollover_if_needed(pd.Timestamp("2026-09-10"))
    assert (b.cancelled, b.placed) == ([], [])
    assert p.stop_order_id == "stp-old"


def test_close_failure_leaves_the_stop_alone():
    """CLOSE did not execute, so the position is still on the old contract and its
    stop is still the right stop. Cancelling here would strip a live position."""
    b = _RollBroker({}, ACCOUNT, close_ok=False)
    p = _pos()
    _runner(b, p)._handle_rollover_if_needed(ROLL_DAY)
    assert (b.cancelled, b.placed) == ([], [])
    assert p.stop_order_id == "stp-old"


def test_open_failure_leaves_the_stop_alone():
    """CLOSE succeeded, OPEN did not: flat at IBKR, position removed from state.
    There is nothing to protect, and placing a stop would open one."""
    b = _RollBroker({}, ACCOUNT, open_ok=False)
    r = _runner(b, _pos())
    r._handle_rollover_if_needed(ROLL_DAY)
    assert b.placed == []
    assert r.state.open_positions == []


def test_rejected_replacement_is_critical(caplog):
    """Not accepted means unprotected. It has to be loud — this is the state that
    ran overnight on 2026-08-04."""
    b = _RollBroker({}, ACCOUNT, stop_accepted=False)
    p = _pos()
    with caplog.at_level("CRITICAL"):
        _runner(b, p)._handle_rollover_if_needed(ROLL_DAY)
    assert any("UNPROTECTED" in r.getMessage() for r in caplog.records)
    assert p.stop_order_id is None      # never claim protection that does not exist


def test_failed_cancel_is_critical(caplog):
    """A stop that would not cancel is still working on the expiring contract."""
    b = _RollBroker({}, ACCOUNT, cancel_ok=False)
    with caplog.at_level("CRITICAL"):
        _runner(b, _pos())._handle_rollover_if_needed(ROLL_DAY)
    assert any("could NOT cancel" in r.getMessage() for r in caplog.records)


def test_no_recorded_level_is_critical(caplog):
    """Nothing to shift and nothing to place — say so rather than roll on quietly."""
    b = _RollBroker({}, ACCOUNT)
    with caplog.at_level("CRITICAL"):
        _runner(b, _pos(stop_price=None, stop_order_id=None))._handle_rollover_if_needed(ROLL_DAY)
    assert any("no recorded stop level" in r.getMessage() for r in caplog.records)
    assert b.placed == []


def test_short_stop_shifts_the_same_way():
    """The shift is a property of the contracts, not of the side."""
    b = _RollBroker({}, ACCOUNT)
    p = OpenPos(inst="MES", direction="SHORT", contracts=1, risk_dollars=500.0,
                cluster=CLUSTER, entry_day=pd.Timestamp("2026-09-08"),
                stop_price=7800.0, stop_order_id="stp-old")
    _runner(b, p)._handle_rollover_if_needed(ROLL_DAY)
    assert p.stop_price == pytest.approx(7866.75)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
