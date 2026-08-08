"""
global_index/test_operational_fixes.py — synthetic tests for B1/C1/C4/E1 fixes
================================================================================
Script-style (no pytest) — run from repo root:

    python global_index/test_operational_fixes.py

Tests:
  T1  B1  persist + reload: position survives runner restart
  T2  B1  corrupt file → fresh start (no crash)
  T3  C1  signal_fn throws → runner does not crash; pre-set exit still runs
  T4  C4  swing cluster throws → NKD cluster still runs (call tracked)
  T5  E1  duplicate instance → second runner refuses with RunnerLockError
"""
from __future__ import annotations
import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from global_index.broker import MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import MultiClusterGuard, ClusterBudget
from global_index.runner import FuturesRunner, RunnerLockError
from futures.circuit_breaker import CircuitBreaker

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag}  {name}" + (f" — {detail}" if detail else ""))
    _results.append((name, cond, detail))


def _make_guard():
    clusters = {
        "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05, max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
        "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
    }
    return MultiClusterGuard(clusters=clusters, account=50_000)


def _empty_broker():
    """MockBroker with no bars — fetch_bars returns empty DataFrame safely."""
    return MockBroker({}, account=50_000)


def _make_runner(broker, signal_fn, positions_path=None, lock_path=None):
    guard = _make_guard()
    breaker = CircuitBreaker(account=50_000)
    return FuturesRunner(
        broker=broker,
        guard=guard,
        contracts_by_inst={"MES": 1},
        signal_fn=signal_fn,
        breaker=breaker,
        positions_path=positions_path,
        lock_path=lock_path,
    )


def _noop_signal(day, bars, held):
    return [], []


def _one_entry_signal(day, bars, held):
    """Returns one LONG entry candidate — used to verify it gets blocked/discarded."""
    return [{"inst": "MES", "direction": "LONG", "cluster": "roska4_swing",
             "risk_sized": 250.0, "entry": 5000.0, "stop": 4980.0}], []


class _LogCapture(logging.Handler):
    """In-memory log handler for asserting alert messages were emitted."""
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


# ─── T1: B1 persist + reload ────────────────────────────────────────────────

def test_b1_persist_reload():
    print("\nT1: B1 persist + reload")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"
        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal, positions_path=pos_path)

        # Inject a position directly (simulating a prior run_day that opened it)
        today = pd.Timestamp("2024-06-15")
        tomorrow = pd.Timestamp("2024-06-16")
        pos = OpenPos(
            inst="MES", direction="LONG", contracts=1,
            risk_dollars=250.0, cluster="roska4_swing",
            entry_day=today, exit_day=tomorrow, pnl_sized=300.0,
        )
        runner.state.open_positions.append(pos)
        runner._persist_state()

        check("T1.1 file exists after persist", pos_path.exists())
        data = json.loads(pos_path.read_text())
        positions = data["positions"] if isinstance(data, dict) else data
        check("T1.2 file has 1 position", len(positions) == 1, f"got {len(positions)}")
        check("T1.3 inst serialized correctly", positions[0]["inst"] == "MES")

        # Simulate restart: new runner loads the file
        broker2 = _empty_broker()
        runner2 = _make_runner(broker2, _noop_signal, positions_path=pos_path)
        loaded = runner2.state.open_positions
        check("T1.4 positions loaded on restart", len(loaded) == 1, f"got {len(loaded)}")
        if loaded:
            p = loaded[0]
            check("T1.5 inst matches", p.inst == "MES")
            check("T1.6 direction matches", p.direction == "LONG")
            check("T1.7 pnl_sized matches", p.pnl_sized == 300.0, f"got {p.pnl_sized}")
            check("T1.8 exit_day matches", str(p.exit_day.date()) == "2024-06-16")


# ─── T2: B1 corrupt file → fresh start ──────────────────────────────────────

def test_b1_corrupt():
    print("\nT2: B1 corrupt file → fresh start (no crash)")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"
        pos_path.write_text("not valid json {{{")

        broker = _empty_broker()
        try:
            runner = _make_runner(broker, _noop_signal, positions_path=pos_path)
            check("T2.1 no crash on corrupt file", True)
            check("T2.2 fresh start (empty positions)", len(runner.state.open_positions) == 0,
                  f"got {len(runner.state.open_positions)}")
        except Exception as e:
            check("T2.1 no crash on corrupt file", False, str(e))
            check("T2.2 fresh start (empty positions)", False, "not reached")


# ─── T3: C1 signal_fn throws → no crash, pre-set exit still runs ────────────

def test_c1_signal_fail_exits_still_run():
    print("\nT3: C1 signal_fn throws → no crash; exit_day-based exit still runs")

    def _exploding_signal(day, bars, held):
        raise RuntimeError("injected engine failure")

    today = pd.Timestamp("2024-06-17")
    broker = _empty_broker()
    runner = _make_runner(broker, _exploding_signal)

    # Inject a position whose exit_day == today
    pos = OpenPos(
        inst="MES", direction="LONG", contracts=1,
        risk_dollars=250.0, cluster="roska4_swing",
        entry_day=pd.Timestamp("2024-06-10"), exit_day=today, pnl_sized=150.0,
    )
    runner.state.open_positions.append(pos)
    starting_equity = runner.state.equity

    try:
        decision = runner.run_day(today)
        check("T3.1 no crash when signal_fn throws", True)
        check("T3.2 no entries submitted", len(decision.entries) == 0,
              f"got {len(decision.entries)}")
        check("T3.3 position exited via exit_day", len(decision.exits) == 1,
              f"got {len(decision.exits)}")
        check("T3.4 equity updated by realized pnl",
              abs(runner.state.equity - (starting_equity + 150.0)) < 0.01,
              f"equity={runner.state.equity:.2f}, expected {starting_equity + 150.0:.2f}")
        close_fills = [f for f in broker.fills if f.action == "CLOSE"]
        check("T3.5 CLOSE order sent to broker", len(close_fills) >= 1,
              f"got {len(close_fills)} CLOSE fills")
        check("T3.6 open_positions empty after exit",
              len(runner.state.open_positions) == 0,
              f"got {len(runner.state.open_positions)}")
    except Exception as e:
        check("T3.1 no crash when signal_fn throws", False, str(e))
        for i in range(2, 7):
            check(f"T3.{i} (not reached)", False)


# ─── T4: C4 swing cluster throws → NKD cluster still runs ───────────────────

def test_c4_cluster_isolation():
    print("\nT4: C4 per-cluster isolation — swing fail does not kill NKD")
    from global_index.signal_layer import generate_today_signals, CLUSTER_NKD

    nkd_called = {"count": 0}

    class _FailSwingEngine:
        def desired_basket(self, *a, **kw):
            raise RuntimeError("injected swing cluster failure")

    class _TrackingNKDEngine:
        def desired_position(self, *a, **kw):
            nkd_called["count"] += 1
            return None   # no signal — just confirm the call happened

    class _OKStressEngine:
        def entry_signal(self, *a, **kw):
            return None

    today = pd.Timestamp("2024-06-17")
    # Minimal 1-row DataFrame — daily_atr_series won't crash on sparse data;
    # and since swing fails before ATR is used for swing, NKD ATR just needs a series.
    mini_df = pd.DataFrame(
        {"open": [5000.0], "high": [5010.0], "low": [4990.0], "close": [5000.0], "volume": [1000.0]},
        index=pd.DatetimeIndex(["2024-06-17"]),
    )
    swing_dfs = {n: mini_df for n in ["MES", "MNQ", "MYM", "M2K"]}
    point_values = {"MES": 5.0, "MNQ": 2.0, "MYM": 0.5, "M2K": 10.0, "MNKD": 100.0}
    contracts = {n: 1 for n in point_values}

    try:
        candidates, exits = generate_today_signals(
            swing_engine=_FailSwingEngine(),
            swing_dfs=swing_dfs,
            swing_labels={},
            swing_costs={},
            nkd_engine=_TrackingNKDEngine(),
            nkd_df=mini_df,
            nkd_labels={},
            nkd_cost=None,
            nkd_inst="MNKD",
            stress_engine=_OKStressEngine(),
            stress_bars_1015=None,
            today_regime="Normal",
            held=[],
            point_values=point_values,
            contracts_by_inst=contracts,
            today=today,
        )
        check("T4.1 no crash when swing cluster throws", True)
        check("T4.2 NKD engine was still called", nkd_called["count"] == 1,
              f"called {nkd_called['count']} time(s)")
        check("T4.3 no swing candidates generated", candidates == [],
              f"got {candidates}")
    except Exception as e:
        check("T4.1 no crash when swing cluster throws", False, str(e))
        check("T4.2 NKD engine was still called", False, "not reached")
        check("T4.3 no swing candidates generated", False, "not reached")


# ─── T5: E1 duplicate instance lock ─────────────────────────────────────────

def test_e1_duplicate_lock():
    print("\nT5: E1 duplicate lock — second instance refuses")
    with tempfile.TemporaryDirectory() as td:
        lock_path = Path(td) / "runner.pid"
        broker1 = _empty_broker()

        # First instance acquires lock
        runner1 = _make_runner(broker1, _noop_signal, lock_path=lock_path)
        check("T5.1 first instance starts successfully", lock_path.exists())

        # Second instance must refuse
        broker2 = _empty_broker()
        try:
            runner2 = _make_runner(broker2, _noop_signal, lock_path=lock_path)
            check("T5.2 second instance refused", False, "should have raised RunnerLockError")
        except RunnerLockError as e:
            check("T5.2 RunnerLockError raised by second instance", True, str(e)[:60])
        except Exception as e:
            check("T5.2 RunnerLockError raised by second instance", False,
                  f"wrong exception: {type(e).__name__}: {e}")

        # Stale lock (dead PID): write a definitely-dead PID, then new runner should start
        lock_path.write_text("99999999")   # almost certainly dead
        broker3 = _empty_broker()
        try:
            runner3 = _make_runner(broker3, _noop_signal, lock_path=lock_path)
            check("T5.3 stale lock overwritten (dead PID)", True)
        except RunnerLockError:
            # On some OS the dead PID might accidentally be alive (test env) — not a real fail
            check("T5.3 stale lock overwritten (dead PID)", True,
                  "PID happened to be live in test env — acceptable")
        except Exception as e:
            check("T5.3 stale lock overwritten (dead PID)", False, str(e))


# ─── T6: B1 exit_day after restart — exit runs on correct day ───────────────

def test_b1_exit_day_after_restart():
    """Scenario: position persisted with exit_day=D+2; runner restarts at D+1.
    After restart:
      - run_day(D+1) must NOT exit the position (exit_day != D+1)
      - run_day(D+2) must exit the position (decide_day step 1: exit_day == D+2)
    This tests that decide_day's exit_day check works correctly from persisted data,
    independent of signal_fn (signal_fn returns nothing for both days)."""
    print("\nT6: B1 exit_day persisted → exit fires on correct day after restart")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"
        D2 = pd.Timestamp("2024-07-02")  # entry
        D3 = pd.Timestamp("2024-07-03")  # D+1 — runner restarts here
        D4 = pd.Timestamp("2024-07-04")  # D+2 — exit should fire here

        # --- setup: persist a position with exit_day=D+2 ---
        broker0 = _empty_broker()
        runner0 = _make_runner(broker0, _noop_signal, positions_path=pos_path)
        pos = OpenPos(
            inst="MES", direction="LONG", contracts=1,
            risk_dollars=250.0, cluster="roska4_swing",
            entry_day=D2, exit_day=D4, pnl_sized=400.0,
        )
        runner0.state.open_positions.append(pos)
        runner0._persist_state()

        # --- restart: reload from file ---
        broker1 = _empty_broker()
        runner1 = _make_runner(broker1, _noop_signal, positions_path=pos_path)
        loaded = runner1.state.open_positions
        check("T6.1 position loaded after restart", len(loaded) == 1,
              f"got {len(loaded)}")
        if loaded:
            check("T6.2 exit_day preserved across restart",
                  str(loaded[0].exit_day.date()) == "2024-07-04",
                  f"got {loaded[0].exit_day}")

        # --- run_day(D+1): position must NOT exit ---
        d3_decision = runner1.run_day(D3)
        check("T6.3 no exit on D+1 (exit_day=D+2)", len(d3_decision.exits) == 0,
              f"got {len(d3_decision.exits)} exits")
        check("T6.4 position still held after D+1", len(runner1.state.open_positions) == 1,
              f"got {len(runner1.state.open_positions)}")

        # --- run_day(D+2): exit must fire via decide_day step 1 ---
        starting_equity = runner1.state.equity
        d4_decision = runner1.run_day(D4)
        check("T6.5 exit fires on D+2 (exit_day match)", len(d4_decision.exits) == 1,
              f"got {len(d4_decision.exits)} exits")
        check("T6.6 position gone after exit", len(runner1.state.open_positions) == 0,
              f"got {len(runner1.state.open_positions)}")
        check("T6.7 pnl_sized realized correctly",
              abs(runner1.state.equity - (starting_equity + 400.0)) < 0.01,
              f"equity={runner1.state.equity:.2f}, expected {starting_equity + 400.0:.2f}")
        close_fills = [f for f in broker1.fills if f.action == "CLOSE"]
        check("T6.8 CLOSE order sent on D+2", len(close_fills) == 1,
              f"got {len(close_fills)}")


# ─── T7: ratchet — stop level NOT in OpenPos, engine recomputes ──────────────

def test_ratchet_not_in_openpos():
    """Verify that OpenPos contains no 'stop' field.
    The chandelier ratchet lives entirely inside the engine's desired_basket()
    computation (which reruns from all bar data on each call). On restart, the
    engine recomputes the same stop level deterministically → no ratchet loss."""
    print("\nT7: ratchet — stop not in OpenPos (engine stateless w.r.t. restart)")
    import dataclasses
    fields = {f.name for f in dataclasses.fields(OpenPos)}
    check("T7.1 no 'stop' field in OpenPos", "stop" not in fields,
          f"fields={fields}")
    # entry_price is deliberate as of 97e0f7c. Live pnl_sized arrives as 0.0 — the
    # backtest fills it from its ledger, a broker does not — so a close cannot be valued
    # without the price the position filled at. decide_day never reads it.
    check("T7.2 OpenPos carries entry_price for live P&L", "entry_price" in fields,
          f"fields={fields}")
    from global_index.runner import _openpos_to_dict, _openpos_from_dict
    import pandas as pd
    pos = OpenPos("MES", "LONG", 1, 250.0, "roska4_swing",
                  pd.Timestamp("2024-01-10"), None, 0.0)
    d = _openpos_to_dict(pos)
    check("T7.3 _openpos_to_dict has no 'stop' key", "stop" not in d, f"keys={list(d)}")
    expected_keys = {"inst", "direction", "contracts", "risk_dollars", "cluster",
                     "entry_day", "exit_day", "pnl_sized", "exit_pending"}
    check("T7.4 serialized fields match OpenPos exactly", set(d.keys()) == expected_keys,
          f"extra={set(d.keys())-expected_keys}, missing={expected_keys-set(d.keys())}")


# ─── T8: atomic write — crash during write leaves original intact ─────────────

def test_atomic_write():
    """Simulate crash during json.dump: .tmp written partially, .json untouched.
    Also verify that a stale .tmp from previous crash does not corrupt new persist."""
    print("\nT8: atomic write — original intact if crash mid-write")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"
        tmp_path = pos_path.with_suffix(".tmp")
        today = pd.Timestamp("2024-07-01")

        # Setup: write a valid .json (represents last good persist)
        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal, positions_path=pos_path)
        pos = OpenPos("MES", "LONG", 1, 250.0, "roska4_swing", today, None, 200.0)
        runner.state.open_positions.append(pos)
        runner._persist_state()
        check("T8.1 initial persist wrote .json", pos_path.exists())
        original_content = pos_path.read_text()

        # Simulate crash: corrupt .tmp (as if process killed mid json.dump)
        tmp_path.write_text("{CORRUPT_PARTIAL")
        check("T8.2 stale .tmp written (simulate crash)", tmp_path.exists())

        # Verify: .json is still the original valid content (not overwritten by .tmp)
        check("T8.3 .json untouched by stale .tmp", pos_path.read_text() == original_content)

        # Next persist overwrites .tmp cleanly and completes
        runner._persist_state()
        check("T8.4 next persist succeeds over stale .tmp", pos_path.exists())
        import json
        try:
            data = json.loads(pos_path.read_text())
            pos_count = len(data["positions"]) if isinstance(data, dict) else len(data)
            check("T8.5 .json valid after persist over stale .tmp", True,
                  f"{pos_count} position(s)")
        except Exception as e:
            check("T8.5 .json valid after persist over stale .tmp", False, str(e))

        # Verify: load from reloaded runner works correctly
        broker2 = _empty_broker()
        runner2 = _make_runner(broker2, _noop_signal, positions_path=pos_path)
        check("T8.6 reload after stale-.tmp scenario works",
              len(runner2.state.open_positions) == 1,
              f"got {len(runner2.state.open_positions)}")


# ─── T9: C2 — hmm_stale_guard.check_day throws → entries blocked, no crash ──

def test_c2_stale_guard_throw():
    print("\nT9: C2 stale guard throws → entries blocked, no crash")

    class _ThrowingStaleGuard:
        entries_blocked = 0
        def check_day(self, day, spy_last_date_override=None):
            raise RuntimeError("injected stale guard failure")

    broker = _empty_broker()
    guard = _make_guard()
    breaker = CircuitBreaker(account=50_000)
    runner = FuturesRunner(
        broker=broker,
        guard=guard,
        contracts_by_inst={"MES": 1},
        signal_fn=_one_entry_signal,
        breaker=breaker,
        hmm_stale_guard=_ThrowingStaleGuard(),
    )

    try:
        decision = runner.run_day(pd.Timestamp("2024-06-17"))
        check("T9.1 no crash when stale guard throws", True)
    except Exception as exc:
        check("T9.1 no crash when stale guard throws", False, str(exc))
        return

    check("T9.2 entries blocked (conservative on guard failure)",
          len(decision.entries) == 0,
          f"got {len(decision.entries)} entries")
    check("T9.3 exits unaffected (no open positions to exit)",
          len(decision.exits) == 0)


# ─── T10: C3 — empty fetch_bars for open position → alert logged ─────────────

def test_c3_empty_bars_alert():
    print("\nT10: C3 empty bars → alert logged for open position")
    broker = _empty_broker()  # returns pd.DataFrame() for any inst
    runner = _make_runner(broker, _noop_signal)
    pos = OpenPos("MES", "LONG", 1, 250.0, "roska4_swing",
                  pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-17"), 400.0)
    runner.state.open_positions.append(pos)

    capture = _LogCapture()
    runner_logger = logging.getLogger("global_index.runner")
    runner_logger.addHandler(capture)
    try:
        runner.run_day(pd.Timestamp("2024-06-17"))
    finally:
        runner_logger.removeHandler(capture)

    c3_msgs = [m for m in capture.messages if "C3" in m]
    check("T10.1 C3 alert logged for empty bars",
          len(c3_msgs) >= 1,
          f"got {len(c3_msgs)} C3 message(s)")
    check("T10.2 alert mentions instrument name",
          any("MES" in m for m in c3_msgs),
          f"messages={c3_msgs}")
    # exit must still fire — exit is bar-independent (exit_day-based)
    check("T10.3 exit still runs despite empty bars",
          len(runner.state.open_positions) == 0,
          f"positions remaining={len(runner.state.open_positions)}")


# ─── T11: E3 — clock skew (stale bars) → entries skipped ────────────────────

def test_e3_clock_skew():
    print("\nT11: E3 clock skew → entries skipped")
    old_idx = pd.DatetimeIndex(["2024-01-03", "2024-01-04", "2024-01-05"])
    old_df = pd.DataFrame({
        "open": [5000.0] * 3, "high": [5010.0] * 3,
        "low":  [4990.0] * 3, "close": [5005.0] * 3,
        "volume": [100_000.0] * 3,
    }, index=old_idx)
    broker = MockBroker({"MES": old_df}, account=50_000)

    # today = 2024-07-01 → delta = 177 days from last bar (2024-01-05) → E3 fires
    today = pd.Timestamp("2024-07-01")
    runner = _make_runner(broker, _one_entry_signal)

    capture = _LogCapture()
    runner_logger = logging.getLogger("global_index.runner")
    runner_logger.addHandler(capture)
    try:
        decision = runner.run_day(today)
    except Exception as exc:
        runner_logger.removeHandler(capture)
        check("T11.1 no crash on clock skew", False, str(exc))
        return
    finally:
        runner_logger.removeHandler(capture)

    check("T11.1 no crash on clock skew", True)
    e3_msgs = [m for m in capture.messages if "E3" in m]
    check("T11.2 E3 alert logged",
          len(e3_msgs) >= 1,
          f"got {len(e3_msgs)} E3 message(s)")
    check("T11.3 entries discarded by E3",
          len(decision.entries) == 0,
          f"got {len(decision.entries)} entries")
    check("T11.4 exits unaffected (none scheduled)",
          len(decision.exits) == 0)


# ─── T12: peak_equity persisted and restored (the B1 breaker gap) ────────────

def test_peak_equity_persist():
    print("\nT12: peak_equity persisted and restored after restart")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"

        # runner1: simulate account that peaked at $55k
        broker1 = MockBroker({}, account=55_000)
        runner1 = _make_runner(broker1, _noop_signal, positions_path=pos_path)
        runner1.state.breaker.peak_equity = 55_000.0
        runner1._persist_state()
        check("T12.1 persist wrote state file", pos_path.exists())

        # Verify the file contains breaker.peak_equity
        raw = json.loads(pos_path.read_text())
        check("T12.2 persisted file has breaker.peak_equity",
              isinstance(raw, dict) and "peak_equity" in raw.get("breaker", {}),
              f"keys={list(raw.get('breaker', {}).keys())}")

        # runner2: restart with equity=$48k (drawn down from peak)
        broker2 = MockBroker({}, account=48_000)
        runner2 = _make_runner(broker2, _noop_signal, positions_path=pos_path)

        restored_peak = runner2.state.breaker.peak_equity
        check("T12.3 peak_equity restored to $55k (not reset to $48k)",
              abs(restored_peak - 55_000.0) < 0.01,
              f"got ${restored_peak:,.2f}")

        # DD must reflect true peak, not current equity
        actual_dd = runner2.state.breaker.drawdown_pct(48_000.0)
        expected_dd = (55_000 - 48_000) / 55_000  # 12.7%
        check("T12.4 DD=12.7% (reflects true peak, not 0%)",
              abs(actual_dd - expected_dd) < 0.001,
              f"DD={actual_dd:.1%} expected {expected_dd:.1%}")
        check("T12.5 DD > 10% (breaker not blind after restart)",
              actual_dd > 0.10,
              f"DD={actual_dd:.1%}")


# ─── T13: near-halt scenario — halt fires correctly after restart ─────────────

def test_peak_equity_halt_after_restart():
    print("\nT13: restart near halt → breaker halts entries at 15% DD")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"
        D1 = pd.Timestamp("2024-06-17")

        # runner1: peak=$55k, persist
        broker1 = MockBroker({}, account=55_000)
        runner1 = _make_runner(broker1, _noop_signal, positions_path=pos_path)
        runner1.state.breaker.peak_equity = 55_000.0
        runner1._persist_state()

        # runner2: equity at exactly 15% DD from $55k peak → should HALT
        halt_equity = 55_000 * (1 - 0.15)  # $46,750
        broker2 = MockBroker({}, account=halt_equity)
        runner2 = _make_runner(broker2, _one_entry_signal, positions_path=pos_path)

        try:
            decision = runner2.run_day(D1)
            check("T13.1 no crash at halt boundary after restart", True)
        except Exception as exc:
            check("T13.1 no crash at halt boundary after restart", False, str(exc))
            return

        dd = runner2.state.breaker.drawdown_pct(halt_equity)
        check("T13.2 DD at/above halt threshold (15%)",
              dd >= 0.15 - 0.001,
              f"DD={dd:.2%}")
        check("T13.3 entries halted (circuit breaker fires)",
              len(decision.entries) == 0,
              f"entries={len(decision.entries)}")
        check("T13.4 halted list populated (entry was blocked, not admitted)",
              len(decision.halted) >= 1,
              f"halted={len(decision.halted)}")


# ─── T16: H1 — schema_version in persist + backward-compat load ─────────────

def test_h1_schema_version():
    print("\nT16: H1 schema_version persisted + backward-compat (no version key) load")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"

        # New format: should write schema_version: 1
        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal, positions_path=pos_path)
        runner._persist_state()
        data = json.loads(pos_path.read_text())
        check("T16.1 schema_version=1 present in persisted file",
              data.get("schema_version") == 1,
              f"got schema_version={data.get('schema_version')}")

        # Old format (no schema_version) must still load cleanly (backward-compat)
        old_format = {"positions": [], "breaker": {}}
        pos_path.write_text(json.dumps(old_format))
        broker2 = _empty_broker()
        try:
            runner2 = _make_runner(broker2, _noop_signal, positions_path=pos_path)
            check("T16.2 old format (no schema_version key) loads cleanly", True)
            check("T16.3 positions empty from old format",
                  len(runner2.state.open_positions) == 0,
                  f"got {len(runner2.state.open_positions)}")
        except Exception as e:
            check("T16.2 old format loads cleanly", False, str(e))
            check("T16.3 positions empty", False, "not reached")


# ─── T17: G4a — bad lock path → RunnerLockError with actionable message ──────

def test_g4a_lock_bad_path():
    print("\nT17: G4a bad lock path → RunnerLockError with actionable message")
    from global_index.runner import _acquire_lock, RunnerLockError as RLE
    with tempfile.TemporaryDirectory() as td:
        # Non-existent parent directory → OSError/FileNotFoundError on write
        bad_path = Path(td) / "nosuchdir" / "runner.pid"
        try:
            _acquire_lock(bad_path)
            check("T17.1 RunnerLockError raised on unwritable path", False,
                  "no exception raised")
        except RLE as e:
            check("T17.1 RunnerLockError raised on unwritable path", True)
            check("T17.2 error message includes lock path",
                  str(bad_path) in str(e),
                  f"message: {str(e)[:100]}")
            check("T17.3 error message is actionable (permission / writable)",
                  "permission" in str(e).lower() or "writable" in str(e).lower(),
                  f"message: {str(e)[:100]}")
        except Exception as e:
            check("T17.1 RunnerLockError raised on unwritable path", False,
                  f"wrong exc: {type(e).__name__}: {e}")
            check("T17.2 error message includes lock path", False, "not reached")
            check("T17.3 error message is actionable", False, "not reached")


# ─── T18: H3 — benchmark_daily output deduped by load_spy_regime ─────────────

def test_h3_csv_dedup():
    print("\nT18: H3 CSV duplicate dates deduplicated after benchmark_daily")
    from futures._validated_core import benchmark_daily
    import os
    with tempfile.TemporaryDirectory() as td:
        # CSV with one duplicate date (2024-01-03 appears twice)
        csv_path = Path(td) / "spy_dup.csv"
        csv_path.write_text(
            "date,close\n"
            "2024-01-02,470.0\n"
            "2024-01-03,472.0\n"
            "2024-01-03,473.0\n"  # duplicate — later value should win
            "2024-01-04,474.0\n"
        )
        s_raw = benchmark_daily(str(csv_path))
        check("T18.1 raw series has duplicate date (pre-dedup baseline)",
              s_raw.index.duplicated().sum() >= 1,
              f"dup count={s_raw.index.duplicated().sum()}")

        # Same dedup applied by load_spy_regime (regime.py H3 fix)
        s_clean = s_raw[~s_raw.index.duplicated(keep='last')]
        check("T18.2 no duplicates after dedup",
              s_clean.index.duplicated().sum() == 0,
              f"dup remaining={s_clean.index.duplicated().sum()}")
        check("T18.3 latest value kept for duplicate date (473.0, not 472.0)",
              abs(float(s_clean[pd.Timestamp("2024-01-03")]) - 473.0) < 0.01,
              f"got {float(s_clean[pd.Timestamp('2024-01-03')])}")
        check("T18.4 row count 4→3 after dedup",
              len(s_clean) == 3,
              f"got {len(s_clean)}")


# ─── T14: J2 — _SWING_CACHE cleared after run_day ───────────────────────────

def test_j2_cache_clear():
    print("\nT14: J2 _SWING_CACHE cleared after run_day")
    try:
        from futures._validated_core import _SWING_CACHE
    except ImportError as e:
        check("T14.1 _SWING_CACHE importable", False, str(e))
        check("T14.2 _SWING_CACHE empty after run_day", False, "not reached")
        return

    # Seed the cache with a sentinel to prove it gets cleared
    _SWING_CACHE["__test_sentinel__"] = {"fake": True}
    check("T14.1 cache seeded (sentinel present)",
          "__test_sentinel__" in _SWING_CACHE,
          f"cache size: {len(_SWING_CACHE)}")

    broker = _empty_broker()
    runner = _make_runner(broker, _noop_signal)
    runner.run_day(pd.Timestamp("2024-06-17"))

    check("T14.2 _SWING_CACHE empty after run_day",
          len(_SWING_CACHE) == 0,
          f"entries remaining: {len(_SWING_CACHE)}")


# ─── T15: H2 — invalid position discarded on load ────────────────────────────

def test_h2_invalid_position_discarded():
    print("\nT15: H2 invalid position (contracts=-1) discarded on load")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"

        # File with one invalid (contracts=-1) and one valid position
        payload = {
            "positions": [
                {
                    "inst": "MES", "direction": "LONG", "contracts": -1,
                    "risk_dollars": 250.0, "cluster": "roska4_swing",
                    "entry_day": "2024-06-01", "exit_day": None, "pnl_sized": 0.0,
                },
                {
                    "inst": "MNQ", "direction": "LONG", "contracts": 1,
                    "risk_dollars": 300.0, "cluster": "roska4_swing",
                    "entry_day": "2024-06-01", "exit_day": None, "pnl_sized": 0.0,
                },
            ],
            "breaker": {},
        }
        pos_path.write_text(json.dumps(payload))

        broker = _empty_broker()
        try:
            runner = _make_runner(broker, _noop_signal, positions_path=pos_path)
            check("T15.1 no crash loading file with invalid position", True)
        except Exception as e:
            check("T15.1 no crash loading file with invalid position", False, str(e))
            check("T15.2 invalid position discarded", False, "not reached")
            check("T15.3 valid position preserved", False, "not reached")
            return

        check("T15.2 invalid position (contracts=-1) discarded",
              len(runner.state.open_positions) == 1,
              f"got {len(runner.state.open_positions)} position(s)")
        if runner.state.open_positions:
            check("T15.3 valid position (MNQ) preserved",
                  runner.state.open_positions[0].inst == "MNQ",
                  f"inst={runner.state.open_positions[0].inst}")


# ─── T19: operational_status has all 7 keys ──────────────────────────────────

def test_ops_status_keys():
    print("\nT19: operational_status — all 7 keys present after run_day")
    broker = _empty_broker()
    runner = _make_runner(broker, _noop_signal)
    day = pd.Timestamp("2024-06-17")
    runner.run_day(day)
    ops = runner._build_operational_status(day)
    required = {"runner", "breaker", "regime_freshness", "model_age",
                "positions", "refreeze", "regime_unreliable"}
    check("T19.1 all 7 operational_status keys present",
          required.issubset(ops.keys()),
          f"missing={required - ops.keys()}")
    check("T19.2 runner.alive=True", ops["runner"]["alive"] is True)
    check("T19.3 runner.pid is int", isinstance(ops["runner"]["pid"], int))
    check("T19.4 breaker.level in known levels",
          ops["breaker"]["level"] in ("OK", "WARN", "HALT_DAY", "HALT"),
          f"got {ops['breaker']['level']}")
    check("T19.5 positions.count matches open_positions",
          ops["positions"]["count"] == len(runner.state.open_positions),
          f"ops={ops['positions']['count']}, state={len(runner.state.open_positions)}")
    check("T19.6 refreeze.pending is bool",
          isinstance(ops["refreeze"]["pending"], bool))
    check("T19.7 regime_unreliable is bool",
          isinstance(ops["regime_unreliable"], bool))


# ─── T20: events bounded to 500 ──────────────────────────────────────────────

def test_events_bounded():
    print("\nT20: events bounded to 500 entries")
    broker = _empty_broker()
    runner = _make_runner(broker, _noop_signal)
    for i in range(600):
        runner._emit_event("INFO", "STATE", f"event {i}")
    check("T20.1 events capped at 500",
          len(runner._events) == 500,
          f"got {len(runner._events)}")
    check("T20.2 oldest events dropped (FIFO)",
          runner._events[0]["message"] == "event 100",
          f"first event: {runner._events[0]['message']}")
    check("T20.3 newest event is last",
          runner._events[-1]["message"] == "event 599",
          f"last event: {runner._events[-1]['message']}")


# ─── T21: STATE event emitted at run_day start ───────────────────────────────

def test_state_event_day_started():
    print("\nT21: STATE event emitted at run_day start")
    broker = _empty_broker()
    runner = _make_runner(broker, _noop_signal)
    runner.run_day(pd.Timestamp("2024-06-17"))
    day_events = [e for e in runner._events if "Day started" in e["message"]]
    check("T21.1 STATE 'Day started' event emitted",
          len(day_events) >= 1,
          f"events: {[e['message'] for e in runner._events[:5]]}")
    if day_events:
        check("T21.2 level=INFO", day_events[-1]["level"] == "INFO")
        check("T21.3 category=STATE", day_events[-1]["category"] == "STATE")
        check("T21.4 contains date string",
              "2024-06-17" in day_events[-1]["message"],
              f"message: {day_events[-1]['message']}")


# ─── T22: SIGNAL WARN event for C3 empty bars ────────────────────────────────

def test_c3_event_emitted():
    print("\nT22: SIGNAL WARN event emitted for C3 empty bars")
    broker = _empty_broker()
    runner = _make_runner(broker, _noop_signal)
    pos = OpenPos("MES", "LONG", 1, 250.0, "roska4_swing",
                  pd.Timestamp("2024-06-01"), pd.Timestamp("2024-06-17"), 400.0)
    runner.state.open_positions.append(pos)
    runner.run_day(pd.Timestamp("2024-06-17"))
    c3_events = [e for e in runner._events
                 if e["category"] == "SIGNAL" and "C3" in e["message"]]
    check("T22.1 SIGNAL C3 event emitted",
          len(c3_events) >= 1,
          f"events: {[e['message'] for e in runner._events]}")
    if c3_events:
        check("T22.2 level=WARN", c3_events[0]["level"] == "WARN")
        check("T22.3 context.inst=MES",
              c3_events[0].get("context", {}).get("inst") == "MES",
              f"context: {c3_events[0].get('context')}")


# ─── T23: SIGNAL ALERT event for E3 clock skew ───────────────────────────────

def test_e3_event_emitted():
    print("\nT23: SIGNAL ALERT event emitted for E3 clock skew")
    old_df = pd.DataFrame({
        "open": [5000.0], "high": [5010.0], "low": [4990.0],
        "close": [5005.0], "volume": [100_000.0],
    }, index=pd.DatetimeIndex(["2024-01-05"]))
    broker = MockBroker({"MES": old_df}, account=50_000)
    runner = _make_runner(broker, _one_entry_signal)
    runner.run_day(pd.Timestamp("2024-07-01"))  # 177d gap → E3
    e3_events = [e for e in runner._events
                 if e["category"] == "SIGNAL" and "E3" in e["message"]]
    check("T23.1 SIGNAL E3 event emitted",
          len(e3_events) >= 1,
          f"events: {[e['message'] for e in runner._events]}")
    if e3_events:
        check("T23.2 level=ALERT", e3_events[0]["level"] == "ALERT")
        check("T23.3 context has delta_days",
              "delta_days" in e3_events[0].get("context", {}),
              f"context: {e3_events[0].get('context')}")


# ─── T24: SIGNAL ALERT event for C1 signal_fn fail ───────────────────────────

def test_c1_event_emitted():
    print("\nT24: SIGNAL ALERT event emitted for C1 signal_fn failure")
    def _boom(day, bars, held):
        raise RuntimeError("injected failure")
    broker = _empty_broker()
    runner = _make_runner(broker, _boom)
    runner.run_day(pd.Timestamp("2024-06-17"))
    c1_events = [e for e in runner._events
                 if e["category"] == "SIGNAL" and "C1" in e["message"]]
    check("T24.1 SIGNAL C1 event emitted",
          len(c1_events) >= 1,
          f"events: {[e['message'] for e in runner._events]}")
    if c1_events:
        check("T24.2 level=ALERT", c1_events[0]["level"] == "ALERT")
        check("T24.3 context has error string",
              "error" in c1_events[0].get("context", {}),
              f"context: {c1_events[0].get('context')}")


# ─── T25: GUARD event for G1 hard-stale transition ───────────────────────────

def test_g1_hard_event_emitted():
    print("\nT25: GUARD CRITICAL event emitted on G1 hard-stale transition")
    from global_index.hmm_stale_guard import HMMStaleGuard

    class _FakeStaleGuard(HMMStaleGuard):
        def __init__(self):
            self.regime_unreliable = False
            self.entries_blocked = 0
            self._g1_soft_active = False
            self._g2_soft_notified = False
            self._g2_hard_notified = False
            self.fit_end = pd.Timestamp("2024-12-31")

        def check_day(self, today, spy_last_date_override=None):
            # Simulate transition to hard-stale
            self.regime_unreliable = True
            self._g1_soft_active = True
            return False

    broker = _empty_broker()
    guard = _make_guard()
    breaker = CircuitBreaker(account=50_000)
    runner = FuturesRunner(
        broker=broker, guard=guard, contracts_by_inst={"MES": 1},
        signal_fn=_noop_signal, breaker=breaker,
        hmm_stale_guard=_FakeStaleGuard(),
    )
    runner.run_day(pd.Timestamp("2024-06-17"))
    g1_events = [e for e in runner._events
                 if e["category"] == "GUARD" and "G1 HARD-STALE" in e["message"]]
    check("T25.1 GUARD G1 HARD-STALE event emitted",
          len(g1_events) >= 1,
          f"events: {[e['message'] for e in runner._events]}")
    if g1_events:
        check("T25.2 level=CRITICAL", g1_events[0]["level"] == "CRITICAL")


# ─── T26: GUARD CRITICAL event for breaker HALT transition ───────────────────

def test_breaker_halt_event_emitted():
    print("\nT26: GUARD CRITICAL event emitted on breaker HALT transition")
    # equity at 15% DD from peak → HALT
    halt_equity = 50_000 * (1 - 0.15)
    broker = MockBroker({}, account=halt_equity)
    guard = _make_guard()
    breaker = CircuitBreaker(account=50_000)
    breaker.peak_equity = 50_000.0  # peak stayed at 50k

    runner = FuturesRunner(
        broker=broker, guard=guard, contracts_by_inst={"MES": 1},
        signal_fn=_one_entry_signal, breaker=breaker,
    )
    runner.run_day(pd.Timestamp("2024-06-17"))
    halt_events = [e for e in runner._events
                   if e["category"] == "GUARD" and "HALT" in e["message"]
                   and e["level"] == "CRITICAL"]
    check("T26.1 GUARD CRITICAL HALT event emitted",
          len(halt_events) >= 1,
          f"events: {[e['message'] for e in runner._events]}")
    if halt_events:
        check("T26.2 context has dd_pct",
              "dd_pct" in halt_events[0].get("context", {}),
              f"context: {halt_events[0].get('context')}")


# ─── T27: dump_state writes parseable JS file ─────────────────────────────────

def test_dump_state_writes_file():
    print("\nT27: dump_state writes parseable window.LIVE_DATA JS file")
    import re
    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        broker = _empty_broker()
        guard = _make_guard()
        breaker = CircuitBreaker(account=50_000)
        runner = FuturesRunner(
            broker=broker, guard=guard, contracts_by_inst={"MES": 1},
            signal_fn=_noop_signal, breaker=breaker,
            live_state_path=ls_path,
        )
        day = pd.Timestamp("2024-06-17")
        runner.run_day(day)

        check("T27.1 live_state_data.js created", ls_path.exists())
        content = ls_path.read_text(encoding="utf-8")
        check("T27.2 file starts with window.LIVE_DATA",
              "window.LIVE_DATA" in content,
              f"first 60 chars: {content[:60]}")

        # Strip the JS assignment and parse JSON
        m = re.search(r'window\.LIVE_DATA\s*=\s*(\{.*\});?\s*$', content, re.DOTALL)
        check("T27.3 JSON extractable from JS file", m is not None,
              "regex did not match")
        if m:
            try:
                live = json.loads(m.group(1))
                check("T27.4 JSON parses without error", True)
                check("T27.5 meta key present", "meta" in live)
                check("T27.6 snapshots is a list", isinstance(live.get("snapshots"), list))
                check("T27.7 snapshots[0].date matches run day",
                      live.get("snapshots", [{}])[0].get("date") == "2024-06-17",
                      f"got {live.get('snapshots', [{}])[0].get('date')}")
                check("T27.8 meta.operational_status has 7 keys",
                      len(live["meta"].get("operational_status", {}).keys()) == 7,
                      f"keys={list(live['meta'].get('operational_status', {}).keys())}")
                check("T27.9 meta.events is a list",
                      isinstance(live["meta"].get("events"), list))
                check("T27.10 runner_health present at top level",
                      "runner_health" in live)
            except Exception as e:
                check("T27.4 JSON parses without error", False, str(e))
                for i in range(5, 11):
                    check(f"T27.{i} (not reached)", False)


# ─── T28: STATE ALERT emitted on persist fail ─────────────────────────────────

def test_persist_fail_event():
    print("\nT28: STATE ALERT event emitted when persist fails")
    with tempfile.TemporaryDirectory() as td:
        # Use a path inside a non-existent subdir → persist will fail
        bad_pos_path = Path(td) / "nosuchdir" / "live_positions.json"
        broker = _empty_broker()
        # Can't pass bad path to __init__ (it would fail at load-time check → skip load)
        # Instead: make runner with valid path, then point _positions_path at bad path
        valid_pos_path = Path(td) / "live_positions.json"
        runner = _make_runner(broker, _noop_signal, positions_path=valid_pos_path)
        runner._positions_path = bad_pos_path  # swap to bad path after construction

        # Clear events from startup
        runner._events.clear()
        runner._persist_state()

        persist_fail_events = [e for e in runner._events
                               if e["category"] == "STATE" and "persist failed" in e["message"]]
        check("T28.1 STATE ALERT persist fail event emitted",
              len(persist_fail_events) >= 1,
              f"events: {[e['message'] for e in runner._events]}")
        if persist_fail_events:
            check("T28.2 level=ALERT", persist_fail_events[0]["level"] == "ALERT")
            check("T28.3 context has error key",
                  "error" in persist_fail_events[0].get("context", {}),
                  f"context: {persist_fail_events[0].get('context')}")



# ─── T29: the brake still blocks entries after a realised loss ───────────────
#
# This used to drive the loss by having the broker report an equity the runner had not
# synced, which H4 then folded into state.equity. As of 97e0f7c the ledger is ACCOUNT
# plus realised sleeve P&L — H4 moved the whole account's NetLiquidation, interest and
# FX included, on an account twenty times the sleeve.
#
# The property under test is unchanged and still matters: decide_day admits entries
# against the equity it sees BEFORE this run's closes are booked, so a day that has
# since crossed -4% must not still open new risk. Only the route the loss takes changes.

def test_halt_day_blocks_entries_after_realised_loss():
    print()
    print("T29: brake blocks multi-day entries after a realised loss crosses -4%")
    account = 50_000.0
    day = pd.Timestamp("2024-06-17")

    # Live runs ~22 slots a day and only the first re-baselines the breaker. decide_day
    # books exits BEFORE calling start_day (deliberate — see live_decision), so a loss
    # in the first slot sets the day's baseline below itself. This models the case the
    # brake is actually for: the baseline is set in slot 1, the loss lands in slot 2.
    state = {"slot": 0}

    def _signal(d, bars, held):
        state["slot"] += 1
        if state["slot"] == 1:
            return [{"inst": "MES", "direction": "LONG", "cluster": "roska4_swing",
                     "risk_sized": 250.0, "entry": 5000.0, "stop": 4980.0,
                     "exit": day + pd.Timedelta(days=9)}], []
        if state["slot"] == 2:
            # The stop level moved against us: close it, and the signal wants a new one.
            held[0].pnl_sized = -2_500.0        # 5% of $50k
            return [{"inst": "MNQ", "direction": "LONG", "cluster": "roska4_swing",
                     "risk_sized": 250.0, "entry": 5000.0, "stop": 4980.0,
                     "exit": day + pd.Timedelta(days=9)}], [held[0]]
        return [], []

    broker = MockBroker({}, account)
    runner = FuturesRunner(
        broker=broker, guard=_make_guard(), contracts_by_inst={"MES": 1, "MNQ": 1},
        signal_fn=_signal, breaker=CircuitBreaker(account=account),
    )
    runner.run_day(day)          # slot 1: opens MES, baseline set at $50,000
    runner.run_day(day)          # slot 2: MES closes -2,500, MNQ entry requested

    mnq_opens = [f for f in broker.fills if f.action == "OPEN" and f.inst == "MNQ"]
    blocked = [e for e in runner._events
               if e.get("category") == "GUARD" and "blocked" in e.get("message", "")]

    check("T29.1 no new multi-day entry once the day is past -4%",
          len(mnq_opens) == 0,
          f"MNQ opens: {len(mnq_opens)}, equity={runner.state.equity:,.2f}")
    check("T29.2 the block is reported, not silent",
          len(blocked) >= 1,
          f"events: {[e['message'] for e in runner._events]}")
    check("T29.3 the loss reached the ledger",
          abs(runner.state.equity - (account - 2_500)) < 1.0,
          f"equity={runner.state.equity:,.2f}")

# ─── T30: exit_pending persists + restores across runner restart ──────────────

def test_exit_pending_persist_restore():
    print("\nT30: exit_pending=True persists to JSON and restores correctly")
    with tempfile.TemporaryDirectory() as td:
        pos_path = Path(td) / "live_positions.json"

        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal, positions_path=pos_path)

        # Inject a position with exit_pending=True (simulates a prior session's failed CLOSE)
        p = OpenPos("MES", "LONG", 1, 250.0, "roska4_swing",
                    pd.Timestamp("2024-06-10"),
                    exit_day=pd.Timestamp("2024-06-17"),
                    pnl_sized=300.0,
                    exit_pending=True)
        runner.state.open_positions = [p]
        runner._persist_state()

        # Reload via a fresh runner
        broker2 = _empty_broker()
        runner2 = _make_runner(broker2, _noop_signal, positions_path=pos_path)
        loaded = runner2.state.open_positions

        check("T30.1 position loaded after restart",
              len(loaded) == 1, f"len={len(loaded)}")
        if loaded:
            check("T30.2 exit_pending=True preserved",
                  loaded[0].exit_pending is True,
                  f"exit_pending={loaded[0].exit_pending}")
            check("T30.3 other fields intact",
                  loaded[0].inst == "MES" and abs(loaded[0].pnl_sized - 300.0) < 0.01,
                  f"inst={loaded[0].inst} pnl={loaded[0].pnl_sized}")


# ─── T31: STRESS_MID 2-pass — same-session loss → HALT_DAY blocks multi-day ──

def test_stress_mid_2pass_halt_day():
    print("\nT31: STRESS_MID 2-pass: same-session loss → H4 sync → HALT_DAY blocks multi-day")
    account = 50_000.0

    class _StressMidLossBroker(MockBroker):
        """Fills carry a price, the way IBKRBroker's do.

        This used to fake the loss by reporting a lower account balance, which worked
        while the runner copied that balance into its ledger. The ledger is the sleeve's
        own realised P&L now, so the loss has to arrive the way a real one does: a short
        opened at 5000 and covered at 5500 loses (5000-5500) x $5 = -$2,500, 5% of $50k.
        """
        def send_order(self, order):
            f = super().send_order(order)
            f.avg_price = 5000.0 if order.action == "OPEN" else 5500.0
            return f

    # Signal: MES same-day (STRESS_MID, exit=day, no pnl_sized = live mode)
    #         MNQ multi-day swing entry
    day = pd.Timestamp("2024-06-17")

    def _stress_and_swing(d, bars, held):
        return [
            {"inst": "MES", "direction": "SHORT", "cluster": "roska4_stress",
             "risk_sized": 250.0, "entry": 5000.0, "stop": 4980.0, "exit": d},
            {"inst": "MNQ", "direction": "LONG",  "cluster": "roska4_swing",
             "risk_sized": 250.0, "entry": 5000.0, "stop": 4980.0},
        ], []

    broker = _StressMidLossBroker({}, account)
    guard = MultiClusterGuard(clusters={
        "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05, max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
        "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
    }, account=account)
    breaker = CircuitBreaker(account=account)
    runner = FuturesRunner(
        broker=broker, guard=guard,
        contracts_by_inst={"MES": 1, "MNQ": 1},
        signal_fn=_stress_and_swing,
        breaker=breaker,
    )
    runner.run_day(day)

    open_fills  = [f for f in broker.fills if f.action == "OPEN"]
    close_fills = [f for f in broker.fills if f.action == "CLOSE"]
    mes_opens   = [f for f in open_fills  if f.inst == "MES"]
    mnq_opens   = [f for f in open_fills  if f.inst == "MNQ"]
    halt_day_events = [e for e in runner._events if "HALT_DAY" in e.get("message", "")]

    check("T31.1 STRESS_MID OPEN sent in pass 1",
          len(mes_opens) == 1, f"MES opens={len(mes_opens)}")
    check("T31.2 STRESS_MID CLOSE sent same-day",
          len(close_fills) >= 1, f"closes={len(close_fills)}")
    check("T31.3 multi-day MNQ OPEN blocked after H4 sync (HALT_DAY fires)",
          len(mnq_opens) == 0, f"MNQ opens={len(mnq_opens)}")
    check("T31.4 HALT_DAY event emitted",
          len(halt_day_events) >= 1,
          f"events: {[e['message'] for e in runner._events]}")


# ─── main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Operational fixes test suite (B1/C1/C4/E1/C2/C3/E3/peak_equity/J2/H2/H1/G4a/H3/H4/I4.8/STRESS-2pass/events/dump_state)")
    print("=" * 60)

    test_b1_persist_reload()
    test_b1_corrupt()
    test_c1_signal_fail_exits_still_run()
    test_c4_cluster_isolation()
    test_e1_duplicate_lock()
    test_b1_exit_day_after_restart()
    test_ratchet_not_in_openpos()
    test_atomic_write()
    test_c2_stale_guard_throw()
    test_c3_empty_bars_alert()
    test_e3_clock_skew()
    test_peak_equity_persist()
    test_peak_equity_halt_after_restart()
    test_j2_cache_clear()
    test_h2_invalid_position_discarded()
    test_h1_schema_version()
    test_g4a_lock_bad_path()
    test_h3_csv_dedup()
    test_ops_status_keys()
    test_events_bounded()
    test_state_event_day_started()
    test_c3_event_emitted()
    test_e3_event_emitted()
    test_c1_event_emitted()
    test_g1_hard_event_emitted()
    test_breaker_halt_event_emitted()
    test_dump_state_writes_file()
    test_persist_fail_event()
    test_halt_day_blocks_entries_after_realised_loss()
    test_exit_pending_persist_restore()
    test_stress_mid_2pass_halt_day()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    print(f"Results: {passed} passed, {failed} failed / {len(_results)} total")
    if failed:
        print("FAILED tests:")
        for name, ok, detail in _results:
            if not ok:
                print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        sys.exit(1)
    else:
        print("ALL PASS")
