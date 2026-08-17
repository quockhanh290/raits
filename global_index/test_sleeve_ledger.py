"""global_index/test_sleeve_ledger.py — the sleeve ledger must track the sleeve

H4 moved system equity by the delta of the whole account's NetLiquidation:

    self.state.equity += broker.get_equity() - self._last_broker_equity

Measured 2026-08-07 on the live account — broker 997,756.40 − 997,395.69 = +360.71 and
the ledger 52,212.33 − 51,851.62 = +360.71, identical 1:1. The account is CAD-based and
around $997k, twenty times the $50k sleeve, so anything happening in it lands in the
sleeve's P&L. The week's statement shows a monthly CAD interest credit of +1,374.32,
the same size as the entire realised trading P&L of +1,160.75. Noise and signal at the
same magnitude, on the curve that feeds Calmar, Sharpe, max drawdown and the circuit
breaker's threshold.

The convention is not a choice. deploy_sim.replay does `equity += t["pnl_sized"]` and
then `breaker.update(equity)` — realised only, no mark-to-market — and every number in
the IS baseline was produced under it. A live ledger on a different convention makes
paper-vs-backtest a comparison of two different quantities, and fires the breaker under
conditions it was never validated against.

So: equity = ACCOUNT + sum of realised P&L on sleeve trades.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import Fill, MockBroker
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
DAY1 = pd.Timestamp("2024-03-11")
DAY2 = pd.Timestamp("2024-03-12")

# MES: $5 a point. A long from 5000.00 to 4990.00 loses $50.
_ENTRY, _EXIT = 5000.00, 4990.00
_EXPECTED_PNL = (_EXIT - _ENTRY) * 5.0 * 1


def _guard():
    return MultiClusterGuard(clusters={
        "roska4_swing": ClusterBudget("roska4_swing", max_gross_pct=0.05, max_net_pct=0.044),
    }, account=ACCOUNT)


def _signal(day, bars, held):
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=_ENTRY, stop=4950.0, exit=DAY2)], []
    return [], ([held[0]] if held else [])


class _PricedBroker(MockBroker):
    """Fills carry a price, the way IBKRBroker's do, and the account earns interest.

    MockBroker leaves avg_price at 0.0 — only IBKRBroker sets it — which is what keeps
    the live P&L path from firing during reconcile.
    """

    def __init__(self, bars, account, interest=0.0):
        super().__init__(bars, account)
        self._interest = interest
        self.stp_calls: list = []

    def send_order(self, o):
        f = super().send_order(o)
        f.avg_price = _ENTRY if o.action == "OPEN" else _EXIT
        # Cash the account earns for reasons that have nothing to do with the sleeve:
        # a monthly interest credit was +1,374.32 in the week measured.
        self._equity += self._interest
        return f

    def get_equity(self):
        return self._equity

    def place_stop(self, inst, direction, contracts, stop_price, cluster, contract_month=None):
        self.stp_calls.append(stop_price)
        return f"stp-{inst}"

    def cancel_order(self, _oid):
        return True

    def get_order_status(self, _oid):
        return "PENDING"


def _runner(broker, tmp_path, **kw):
    return FuturesRunner(
        broker=broker, guard=_guard(), contracts_by_inst={"MES": 1},
        signal_fn=_signal, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json", **kw)


# ── the defining behaviour ────────────────────────────────────────────────────

def test_sl1_equity_moves_by_trade_pnl_not_by_account_interest(tmp_path):
    """A large interest credit lands in the account and must not reach the sleeve."""
    broker = _PricedBroker({}, ACCOUNT, interest=1374.32)
    runner = _runner(broker, tmp_path)

    runner.run_day(DAY1)
    runner.run_day(DAY2)

    assert runner.state.open_positions == [], "the position should have closed"
    assert runner.state.equity == pytest.approx(ACCOUNT + _EXPECTED_PNL), (
        f"equity {runner.state.equity:.2f} — expected {ACCOUNT + _EXPECTED_PNL:.2f}. "
        f"The broker earned {2 * 1374.32:.2f} of interest over these two days; none of "
        f"it belongs to the strategy's P&L."
    )


def test_sl2_entry_price_is_recorded_and_survives_a_restart(tmp_path):
    """P&L needs the entry fill, and every slot is a separate process."""
    broker = _PricedBroker({}, ACCOUNT)
    runner = _runner(broker, tmp_path)
    runner.run_day(DAY1)

    assert runner.state.open_positions[0].entry_price == pytest.approx(_ENTRY)
    saved = json.loads((tmp_path / "pos.json").read_text())["positions"][0]
    assert saved["entry_price"] == pytest.approx(_ENTRY), (
        "without this on disk the next slot cannot value the position it inherits"
    )


def test_sl3_a_position_with_no_entry_price_is_reported_not_valued_at_zero(tmp_path, caplog):
    """Positions opened before this change carry entry_price=None.

    Booking them at zero would silently understate the loss and leave the breaker
    reading an equity that never happened.
    """
    pos_file = tmp_path / "pos.json"
    pos_file.write_text(json.dumps({
        "schema_version": 1,
        "positions": [{
            "inst": "MES", "direction": "LONG", "contracts": 1,
            "risk_dollars": 500.0, "cluster": CLUSTER,
            "entry_day": "2024-03-11", "exit_day": "2024-03-12",
            "pnl_sized": 0.0, "exit_pending": False,
            "stop_price": 4950.0, "stop_order_id": None,
        }],
        "breaker": {},
    }))
    broker = _PricedBroker({}, ACCOUNT)
    broker._positions = [__import__("global_index.broker", fromlist=["BrokerPosition"])
                         .BrokerPosition("MES", "LONG", 1, CLUSTER, DAY1, None, 0.0)]
    runner = FuturesRunner(
        broker=broker, guard=_guard(), contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], [h[0]] if h else []),
        breaker=CircuitBreaker(account=ACCOUNT), positions_path=pos_file)

    with caplog.at_level("CRITICAL"):
        runner.run_day(DAY2)

    assert runner.state.equity == pytest.approx(ACCOUNT), (
        "an unpriceable close must leave equity alone rather than book a made-up zero"
    )
    assert "entry_price" in caplog.text.lower() or "unpriceable" in caplog.text.lower(), (
        f"the gap has to be reported; got {caplog.text!r}"
    )


def test_sl4_verify_mode_is_untouched(tmp_path):
    """Reconcile runs on MockBroker, which never sets avg_price.

    The live P&L path must not fire there, or the engine comparison breaks.
    """
    broker = MockBroker({}, ACCOUNT)          # plain: avg_price stays 0.0
    ledger_pnl = 250.0

    def _verify_signal(day, bars, held):
        if day == DAY1:
            return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                         risk_sized=500.0, entry=_ENTRY, stop=4950.0,
                         exit=DAY2, pnl_sized=ledger_pnl)], []
        return [], []

    runner = FuturesRunner(
        broker=broker, guard=_guard(), contracts_by_inst={"MES": 1},
        signal_fn=_verify_signal, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json")
    runner.run_day(DAY1)
    runner.run_day(DAY2)

    assert runner.state.equity == pytest.approx(ACCOUNT + ledger_pnl), (
        "verify mode books the ledger's own pnl_sized and nothing else"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
