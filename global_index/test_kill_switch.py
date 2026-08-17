"""D5 kill switch (STOP_TRADING) — wired, and actually stopping entries?

RUNNER_AUDIT.md §4.5/H2: `stop_path` appeared 0 times in every entry point while
`STATUS.md:76` counted D5 as 1 of 16 "grep-verified" safety mechanisms and
`OPERATIONS.md:89` documented the runbook. The runner implemented it end to end
(`__init__` takes stop_path, run_day checks it, the entry block skips on it) and no
caller ever passed the argument, so `self._stop_path` was always None and the
condition was always False. An operator following the runbook would create the file,
see it on disk, and keep trading.

That is the §4.6 shape: nothing tested the gap between "the runner can do X" and "the
runner is wired to do X", because every test built its own minimal runner rather than
the one the entry points build.

Two different questions here, deliberately separate:
  * test_entry_point_wires_the_kill_switch — is the argument passed at the call site?
  * test_kill_switch_blocks_entries_but_not_exits — does the runner honour it?
Only the first was red before this file existed; the second is regression cover for a
safety mechanism that had none.
"""
import ast
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.broker import MockBroker                  # noqa: E402
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard  # noqa: E402
from global_index.runner import FuturesRunner               # noqa: E402
from futures.circuit_breaker import CircuitBreaker          # noqa: E402

# Every entry point that constructs a runner able to send orders. run_maxhold_exit and
# run_stop_repair do not generate entries today, but the operator's model is "the file
# is on disk, so nothing opens" — a path that silently ignores the switch is exactly
# the defect this file exists to prevent, and the cost of passing it is one keyword.
ENTRY_POINTS = ["run_live_day.py", "run_maxhold_exit.py", "run_stop_repair.py"]

ACCOUNT = 50_000.0
CLUSTER = "roska4_swing"
DAY1 = pd.Timestamp("2024-03-11")
DAY2 = pd.Timestamp("2024-03-12")


def _runner_call_kwargs(src_path: Path) -> "set[str] | None":
    """Keyword names on the FuturesRunner(...) call in this source file.

    None when there is no such call — the caller must treat that as a broken test
    rather than as a pass, or renaming the class turns this whole file green.
    """
    tree = ast.parse(src_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "FuturesRunner":
            return {kw.arg for kw in node.keywords}
    return None


@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_entry_point_wires_the_kill_switch(name):
    """The call site must NAME stop_path. Reading the source is the point: the defect
    was a missing argument, and no runtime assertion on a hand-built runner can see
    what the entry point forgot to pass."""
    path = Path(__file__).resolve().parent / name
    kwargs = _runner_call_kwargs(path)

    # Self-check before the real assertion: a test that cannot find the call site
    # would pass vacuously for the wrong reason.
    assert kwargs is not None, (
        f"{name}: no FuturesRunner(...) call found. The test is blind, not satisfied — "
        f"fix the locator before trusting a green result here."
    )
    assert "stop_path" in kwargs, (
        f"{name} builds a FuturesRunner without stop_path, so self._stop_path is None "
        f"and STOP_TRADING does nothing. OPERATIONS.md:89 tells the operator this file "
        f"stops entries. Passed kwargs: {sorted(kwargs)}"
    )


@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_entry_point_wires_the_trade_log(name):
    """Every path that can book money must have somewhere to write the row.

    H4 found close paths that moved the sleeve ledger and wrote nothing to
    trade_log.jsonl, and was closed at 0/6 — correctly, for runner.py: all six booking
    sites call _append_trade. But _append_trade_raw opens with

        if self._trade_log_path is None: return

    and two of the three entry points never passed one, so the write was a silent no-op
    at the call site while the mechanism above it looked complete.

    Measured live 2026-08-17: the 09:31 max-hold exit closed M2K, moved system equity
    50228.75 -> 50408.25, emptied the position file, and left trade_log.jsonl untouched
    since 08-11. Reproduced offline both ways — no path: 0 rows; with a path: one CLOSE
    carrying exit_reason=MAX_HOLD and its pnl. $179.50 the ledger knows and the trade
    log does not, so Today's Decision, the performance stats, the equity curve and the
    exit-path gate all read a day with no exit in it.

    Same shape as the stop_path check above, and the same lesson from the other side:
    the previous pass verified the six booking sites and never asked whether the entry
    point handed them anywhere to write.
    """
    path = Path(__file__).resolve().parent / name
    kwargs = _runner_call_kwargs(path)

    assert kwargs is not None, (
        f"{name}: no FuturesRunner(...) call found. The test is blind, not satisfied.")
    assert "trade_log_path" in kwargs, (
        f"{name} builds a FuturesRunner without trade_log_path, so every _append_trade "
        f"on this path returns without writing. The money still moves; nothing records "
        f"it. Passed kwargs: {sorted(kwargs)}"
    )


# ── the other half: does the runner honour the switch once it is wired? ──────────

def _guard():
    return MultiClusterGuard(clusters={
        "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05, max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
        "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
    }, account=ACCOUNT)


class _RecordingBroker(MockBroker):
    """Records orders but DELEGATES to MockBroker, which keeps its own position book.

    Returning a hand-built Fill here instead left `_positions` empty, so on day 2 B3
    saw file=1 / broker=0, called MISMATCH and halted entries — and the blocking test
    passed for that reason rather than because of the switch. The control test below
    is what exposed it. Overriding send_order without delegating is the same defect
    the audit calls "a sim that does not replicate the engine's own filters".
    """

    def __init__(self, bars, account):
        super().__init__(bars, account)
        self.sent: list[tuple] = []

    def send_order(self, o):
        self.sent.append((o.action, o.inst, o.direction, o.contracts))
        return super().send_order(o)

    def place_stop(self, inst, _d, _c, _sp, _cl, contract_month=None):
        return f"stp-{inst}"

    def cancel_order(self, _oid):
        return True

    def get_order_status(self, _oid):
        return "PENDING"


def _signal(day, bars, held):
    """DAY1 opens a swing position; DAY2 wants a NEW entry and closes the held one."""
    if day == DAY1:
        return [dict(inst="MES", direction="LONG", cluster=CLUSTER,
                     risk_sized=500.0, entry=5000.0, stop=4950.0,
                     exit=DAY2, pnl_sized=150.0)], []
    return ([dict(inst="MNQ", direction="LONG", cluster=CLUSTER,
                  risk_sized=500.0, entry=20000.0, stop=19800.0,
                  exit=None, pnl_sized=0.0)],
            list(held))


def _runner(broker, tmp_path, today, stop_path=None):
    return FuturesRunner(
        broker=broker, guard=_guard(),
        contracts_by_inst={"MES": 1, "MNQ": 1},
        signal_fn=_signal,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=tmp_path / "pos.json",
        trade_log_path=tmp_path / "trade_log.jsonl",
        stop_path=stop_path,
        today=today,
        now=pd.Timestamp(today) + pd.Timedelta(hours=14, minutes=5),
    )


def test_kill_switch_blocks_entries_but_not_exits(tmp_path):
    """STOP_TRADING present → no OPEN leaves, every CLOSE still does.

    "Exits keep running" is half the contract and the easier half to break: a switch
    that also froze exits would strand open positions with no way out, which is worse
    than the thing it protects against.
    """
    switch = tmp_path / "STOP_TRADING"
    broker = _RecordingBroker({}, ACCOUNT)

    _runner(broker, tmp_path, DAY1).run_day(DAY1)
    assert ("OPEN", "MES", "LONG", 1) in broker.sent, (
        "day 1 must open a position with the switch absent, otherwise day 2 proves "
        f"nothing about exits. sent={broker.sent}")

    switch.write_text("halt", encoding="utf-8")
    broker.sent.clear()
    _runner(broker, tmp_path, DAY2, stop_path=switch).run_day(DAY2)

    actions = [o[0] for o in broker.sent]
    assert "OPEN" not in actions, (
        f"STOP_TRADING exists but an entry still went to the broker: {broker.sent}")
    assert "CLOSE" in actions, (
        f"the switch must not freeze exits — an open position needs a way out. "
        f"sent={broker.sent}")


def test_absent_switch_leaves_entries_alone(tmp_path):
    """Control. Without this, the test above passes just as well against a runner that
    never enters at all, and the measurement would not distinguish the two."""
    missing = tmp_path / "STOP_TRADING"
    assert not missing.exists()

    broker = _RecordingBroker({}, ACCOUNT)
    _runner(broker, tmp_path, DAY1).run_day(DAY1)
    broker.sent.clear()
    _runner(broker, tmp_path, DAY2, stop_path=missing).run_day(DAY2)

    assert "OPEN" in [o[0] for o in broker.sent], (
        f"with no switch file the entry must go out; otherwise the blocking test above "
        f"cannot tell the switch from an inert runner. sent={broker.sent}")
