"""
global_index/test_equity_base.py — risk thresholds must measure SYSTEM equity

Bug (measured 2026-08-04): the runner initialised state.equity from
broker.get_equity() and H4 then assigned the broker balance outright, so the
circuit breaker ran against whatever the account happened to be funded with —
$995,344 on the paper account — while this system is designed, backtested and
sized for RISK["account"] = $50,000 at one micro contract.

Simulated in scratchpad/sim_breaker_base.py, same dollar P&L, two denominators:

    loss        designed ($50k)   live ($995k)
    $2,789      HALT_DAY  5.6%    OK  0.3%      <- backtest MaxDD
    $7,500      HALT     15.0%    OK  0.8%      <- the hard stop
    $50,000     HALT    100.0%    HALT_DAY 5.0% <- entire design capital gone

First loss that trips a brake: designed HALT_DAY $2,000 / HALT $7,500 versus live
$40,000 / $149,500. Twenty times too far away — the hard stop could not fire.

deploy_sim is the reference (equity = account, then += pnl_sized). The live path
now matches it, and reads the broker only for its DELTA so H4 still books the
same-session P&L that HALT_DAY depends on.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import MockBroker
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
from global_index.runner import FuturesRunner

ACCOUNT = 50_000.0
PAPER = 995_344.0          # what IBKR funded the paper account with
CLUSTER = "roska4_swing"
DAY = pd.Timestamp("2026-08-04")


class _RichBroker(MockBroker):
    """Broker whose balance is nothing like the system's design capital."""

    def __init__(self, equity=PAPER):
        super().__init__({}, equity)

    def set_equity(self, v):
        self._equity = float(v)


def _guard():
    return MultiClusterGuard(account=ACCOUNT, clusters={
        CLUSTER: ClusterBudget(CLUSTER, max_gross_pct=0.05, max_net_pct=0.044)})


def _runner(broker, tmp_path, breaker=None):
    return FuturesRunner(
        broker=broker, guard=_guard(), contracts_by_inst={"MES": 1},
        signal_fn=lambda d, b, h: ([], []),
        breaker=breaker if breaker is not None else CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
    )


# ── base ──────────────────────────────────────────────────────────────────────

def test_eq1_system_equity_not_broker_balance(tmp_path):
    r = _runner(_RichBroker(), tmp_path)
    assert r.state.equity == ACCOUNT, (
        f"risk base must be the $50,000 design capital, got {r.state.equity:,.0f} "
        f"(that is the broker's funding level)")


def test_eq2_hard_stop_fires_at_design_capital(tmp_path):
    """The whole point: a $7,500 loss must HALT, not read as 0.8% of a paper balance."""
    r = _runner(_RichBroker(), tmp_path)
    r.state.breaker.update(r.state.equity)
    st = r.state.breaker.status(ACCOUNT - 7_500)
    assert st["level"] == "HALT", f"$7,500 loss on $50k must HALT, got {st}"
    assert st["drawdown_pct"] == pytest.approx(0.15)


def test_eq3_losing_all_design_capital_is_not_a_five_percent_dip(tmp_path):
    r = _runner(_RichBroker(), tmp_path)
    r.state.breaker.update(r.state.equity)
    assert r.state.breaker.status(0.0)["drawdown_pct"] == pytest.approx(1.0)


# ── H4 delta ──────────────────────────────────────────────────────────────────

def test_eq4_h4_books_broker_delta_not_balance(tmp_path):
    """H4 must still capture real P&L — just as a delta."""
    b = _RichBroker()
    r = _runner(b, tmp_path)
    b.set_equity(PAPER - 1_200)              # a $1,200 realised loss at the broker
    r.run_day(DAY)
    assert r.state.equity == pytest.approx(ACCOUNT - 1_200), (
        f"system equity must move by the broker delta, got {r.state.equity:,.2f}")


def test_eq5_h4_does_not_rebook_the_same_pnl(tmp_path):
    """Slots run every 5 min; a stale mark would re-apply the same loss each time."""
    b = _RichBroker()
    r = _runner(b, tmp_path)
    b.set_equity(PAPER - 1_000)
    r.run_day(DAY)
    first = r.state.equity
    r.run_day(DAY + pd.Timedelta(days=1))    # broker unchanged
    assert r.state.equity == pytest.approx(first), "P&L booked twice"


def test_eq6_halt_day_still_reachable(tmp_path):
    """HALT_DAY at -4% of $50k = $2,000 — the reason H4 reads the broker at all."""
    b = _RichBroker()
    r = _runner(b, tmp_path)
    r.state.breaker.start_day(ACCOUNT)
    b.set_equity(PAPER - 2_500)
    r.run_day(DAY)
    assert r.state.breaker.status(r.state.equity)["level"] == "HALT_DAY"


# ── persistence across the run-and-exit boundary ──────────────────────────────

def test_eq7_ledger_survives_process_restart(tmp_path):
    b = _RichBroker()
    r = _runner(b, tmp_path)
    b.set_equity(PAPER - 900)
    r.run_day(DAY)
    saved = r.state.equity

    r2 = _runner(_RichBroker(PAPER - 900), tmp_path)   # fresh process, same files
    assert r2.state.equity == pytest.approx(saved), "ledger reset on restart"
    assert r2._last_broker_equity == pytest.approx(PAPER - 900)


def test_eq8_legacy_broker_scale_peak_is_discarded(tmp_path):
    """Files written before the fix hold peak_equity from the broker balance.
    Restoring it would keep the breaker on the wrong scale for good."""
    pos = tmp_path / "pos.json"
    pos.write_text(json.dumps({
        "schema_version": 1, "positions": [],
        "breaker": {"peak_equity": 995_582.23, "day_start_equity": 995_461.18,
                    "cur_day": "2026-08-03"},          # no system_equity → legacy
    }))
    r = _runner(_RichBroker(), tmp_path)
    assert r.state.breaker.peak_equity <= ACCOUNT, (
        f"legacy broker-scale peak must be dropped, got "
        f"{r.state.breaker.peak_equity:,.2f}")


def test_eq9_valid_system_scale_peak_is_kept(tmp_path):
    """A real drawdown recorded on the system scale must NOT be thrown away."""
    pos = tmp_path / "pos.json"
    pos.write_text(json.dumps({
        "schema_version": 1, "positions": [],
        "breaker": {"peak_equity": 54_000.0, "system_equity": 48_000.0,
                    "last_broker_equity": PAPER, "cur_day": "2026-08-03"},
    }))
    r = _runner(_RichBroker(), tmp_path)
    assert r.state.breaker.peak_equity == pytest.approx(54_000.0)
    assert r.state.equity == pytest.approx(48_000.0)
    assert r.state.breaker.status(48_000.0)["drawdown_pct"] == pytest.approx(6_000/54_000)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
