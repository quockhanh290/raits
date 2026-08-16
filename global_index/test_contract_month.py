"""OpenPos.contract_month — the book records WHICH contract it is holding.

RUNNER_AUDIT.md C1. `_handle_rollover`'s docstring promises this field three times
("Return (close_fill, open_fill) so runner can update position contract_month", "only
contract_month updates", "contract_month field (TBD in OpenPos)") and it was never
added. `grep contract_month global_index/*.py` matched those three docstring lines and
nothing else.

The consequence is not cosmetic. With no field for it, the book cannot represent which
month it holds — for every instrument, not just Nikkei. A successful Rổ 4 roll leaves the
book byte-identical to before it. So no file-versus-file check can detect a position and
its orders drifting into different months; the only witness is
`unprotected_positions`, which reads the expiry off the live IBKR contract objects. C1
sat undetected in exactly that blind spot.

The field is OBSERVATIONAL ONLY, the same contract `entry_price` and `exit_reason`
already carry in OpenPos: decide_day must never read it, so it cannot change a decision.
test_cm3 enforces that on the source rather than on memory.
"""
import ast
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.broker import Fill, MockBroker                     # noqa: E402
from global_index.live_decision import OpenPos                       # noqa: E402
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard  # noqa: E402
from global_index.runner import (FuturesRunner, _openpos_from_dict,  # noqa: E402
                                 _openpos_to_dict)
from futures.circuit_breaker import CircuitBreaker                   # noqa: E402

ACCOUNT = 50_000.0
CLUSTER = "global_nkd"
DAY1 = pd.Timestamp("2026-09-03")
ROLL_DAY = pd.Timestamp("2026-09-04")


def _guard():
    return MultiClusterGuard(clusters={
        "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05, max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
        "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
    }, account=ACCOUNT)


# ── A. serialisation ─────────────────────────────────────────────────────────

def test_cm1_contract_month_survives_the_round_trip():
    """Written on one slot, read by the next — every slot is a fresh process, so a field
    that does not persist does not exist."""
    p = OpenPos(inst="MNKD", direction="LONG", contracts=1, risk_dollars=500.0,
                cluster=CLUSTER, entry_day=DAY1, contract_month="202609")
    d = _openpos_to_dict(p)
    assert d["contract_month"] == "202609", f"not written: {d}"
    assert _openpos_from_dict(d).contract_month == "202609"


def test_cm2_a_file_written_before_this_field_still_loads():
    """Backward-compat. live_positions.json on disk right now has no such key, and the
    loader's own comment requires d.get(): a KeyError here means the next slot starts
    from a fresh book and forgets the open position."""
    legacy = dict(inst="MNKD", direction="LONG", contracts=1, risk_dollars=500.0,
                  cluster=CLUSTER, entry_day="2026-09-03", stop_price=68200.0,
                  stop_order_id="301", entry_price=68575.0)
    p = _openpos_from_dict(legacy)
    assert p.contract_month is None, "an absent month must read as unknown, not crash"
    assert p.entry_price == 68575.0, "the rest of the row must survive untouched"


# ── B. the engine boundary ───────────────────────────────────────────────────

def test_cm3_no_decision_code_reads_the_field():
    """The whole safety argument for adding this field.

    OpenPos is the engine's own type. entry_price and exit_reason live there under an
    explicit promise that decide_day never reads them; this field joins them under the
    same promise, and the promise is checked rather than remembered.

    Enforced on the source: any read outside the dataclass declaration means a
    persisted, broker-derived value can now change a trading decision, and the verify
    path (MockBroker leaves it None) would diverge from live.
    """
    src = (Path(__file__).resolve().parent / "live_decision.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    declarations, reads = [], []
    for node in ast.walk(tree):
        # `contract_month: str | None = None` inside the dataclass — the one allowed use.
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) \
                and node.target.id == "contract_month":
            declarations.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "contract_month":
            reads.append(node.lineno)

    assert declarations, (
        "contract_month is not declared in live_decision.py — the locator is looking in "
        "the wrong place, so a green result here would prove nothing")
    assert not reads, (
        f"decide_day must not read contract_month; found attribute access at lines "
        f"{reads}. Observational only — see entry_price and exit_reason.")


# ── C. it gets filled in, from the contract that was actually sent ───────────

class _MonthBroker(MockBroker):
    """Reports the month of the contract it traded, the way IBKRBroker does."""

    def __init__(self, bars, account, month="202609"):
        super().__init__(bars, account)
        self.month = month
        self.sent: list = []

    def send_order(self, o):
        self.sent.append((o.action, o.inst))
        f = super().send_order(o)
        return Fill(f.inst, f.action, f.direction, f.contracts, f.cluster,
                    pnl_sized=f.pnl_sized, status="FILLED", avg_price=68575.0,
                    contract_month=self.month)

    def place_stop(self, *_a, **_k):
        return "stp-1"

    def cancel_order(self, _oid):
        return True

    def get_order_status(self, _oid):
        return "PENDING"


def _signal_open(day, bars, held):
    if day == DAY1:
        return [dict(inst="MNKD", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=68575.0, stop=68200.0,
                     exit=None, pnl_sized=0.0)], []
    return [], []


def _runner(broker, tmp_path, today, signal_fn=_signal_open):
    return FuturesRunner(
        broker=broker, guard=_guard(), contracts_by_inst={"MNKD": 1},
        signal_fn=signal_fn, breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
        trade_log_path=tmp_path / "trade_log.jsonl",
        today=today,
        now=pd.Timestamp(today) + pd.Timedelta(hours=1, minutes=10),
    )


def test_cm4_entry_records_the_month_that_was_actually_traded(tmp_path):
    """Taken from the fill, not recomputed.

    Recomputing it here with _current_front_month would build a SECOND answer to
    "which month", derived from the wall clock rather than from the order that went
    out — that is M4, the two-clocks defect, rebuilt inside the fix for C1.

    The fill reports what IBKR reports: qualifyContracts replaces the contract's fields
    with the resolved ones, and the resolved expiry is a full DATE, "20260911", not the
    "202609" that was asked for. exercise_rollover_live compares it with .startswith()
    for exactly that reason, and backfill_nkd passes "20260910" outright.

    The book must not carry two spellings of one month: entry would write "20260911"
    while the roll path writes "202612" straight from ROLL_SCHEDULE, and any comparison
    between them silently fails. Normalised to YYYYMM at the broker boundary — the same
    "one vocabulary leaves IBKRBroker" rule test_symbol_boundary enforces for symbols.

    The first version of this test chose "202609" for the fake and so could never have
    caught it: the value under test was one I picked, not one IBKR produces.
    """
    broker = _MonthBroker({}, ACCOUNT, month="20260911")
    runner = _runner(broker, tmp_path, DAY1)
    runner.run_day(DAY1)

    assert runner.state.open_positions, (
        f"no position was opened — the test cannot say anything about its month. "
        f"sent={broker.sent}")
    assert runner.state.open_positions[0].contract_month == "202609"

    saved = json.loads((tmp_path / "pos.json").read_text(encoding="utf-8"))["positions"]
    assert saved[0]["contract_month"] == "202609", f"did not reach the file: {saved[0]}"


# ── D. the payoff: a roll is visible in the book ─────────────────────────────

class _RollBroker(_MonthBroker):
    """Rolls MNKD on ROLL_DAY, reporting both months the way IBKRBroker._handle_rollover
    does now that it resolves each contract through the shared builder."""

    def _handle_rollover(self, inst, today, direction, contracts, cluster):
        from global_index.ibkr_broker import get_roll_event
        roll = get_roll_event(inst, today)
        if roll is None:
            return None
        front, nxt = roll
        return (
            Fill(inst, "CLOSE", direction, contracts, cluster, status="FILLED",
                 avg_price=68500.0, contract_month=front),
            Fill(inst, "OPEN", direction, contracts, cluster, status="FILLED",
                 avg_price=68520.0, contract_month=nxt),
        )


def test_cm5_a_roll_moves_the_month_in_the_book(tmp_path):
    """Before this field the book was byte-identical before and after a roll, so nothing
    reading the file could tell a rolled position from an un-rolled one. That is the
    blind spot C1 lived in."""
    broker = _RollBroker({}, ACCOUNT, month="202609")
    _runner(broker, tmp_path, DAY1).run_day(DAY1)

    before = json.loads((tmp_path / "pos.json").read_text(encoding="utf-8"))["positions"]
    assert before[0]["contract_month"] == "202609"

    _runner(broker, tmp_path, ROLL_DAY, signal_fn=lambda d, b, h: ([], [])).run_day(ROLL_DAY)

    after = json.loads((tmp_path / "pos.json").read_text(encoding="utf-8"))["positions"]
    assert after, "the roll removed the position instead of moving it"
    assert after[0]["contract_month"] == "202612", (
        f"the book still claims the expiring month after a successful roll — a month "
        f"split is undetectable from the file, which is the C1 blind spot: {after[0]}")


def test_cm6_the_month_reaches_the_dashboard_projection(tmp_path):
    """runner_positions_reader projects a fixed key list, so a new key is dropped unless
    it is named. Recording the month in a file nobody can see is half a fix."""
    from monitor.backend.runner_positions_reader import _parse

    pos_file = tmp_path / "pos.json"
    pos_file.write_text(json.dumps({
        "schema_version": 1,
        "positions": [dict(inst="MNKD", direction="LONG", contracts=1,
                           cluster=CLUSTER, entry_day="2026-09-03",
                           entry_price=68575.0, stop_price=68200.0,
                           stop_order_id="301", contract_month="202609")],
    }), encoding="utf-8")

    out = _parse(pos_file)
    assert out["positions"][0].get("contract_month") == "202609", (
        f"the reader dropped the month: {out['positions'][0]}")
