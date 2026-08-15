"""
global_index/test_event_playback.py — Event backend end-to-end playback verification
=====================================================================================
Script-style (no pytest) — run from repo root:

    python global_index/test_event_playback.py

Verifies the full pipeline: runner.dump_state → live_state_data.js → dashboard-readable.
Uses synthetic MockBroker data — no Polygon.io required.

Coverage:
  Part 1 — Historical playback: 30 synthetic days, live_state_data.js written each day
  Part 2 — Inject scenarios:
    a) Breaker HALT      → GUARD CRITICAL + ops.breaker.level="HALT"
    b) G1 hard-stale     → GUARD CRITICAL + regime_freshness="HARD_BLOCK"
    c) G1 soft-stale     → GUARD WARN + regime_freshness="SOFT_WARN"
    d) G1 recovered      → GUARD INFO + regime_freshness="OK"
    e) C1 signal throw   → SIGNAL ALERT
    f) Restart mid-play  → STATE "Runner started" + positions count intact
    g) Persist fail      → STATE ALERT
    h) events[] bounded  → max 500 after 600+ events injected
  Part 3 — Dashboard compatibility: all 7 ops-status keys + events format + sort
  Part 4 — Baseline: dump_state no-op on P&L (reference run == live run)
"""
from __future__ import annotations
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from futures.circuit_breaker import CircuitBreaker
from global_index.broker import MockBroker
from global_index.live_decision import OpenPos
from global_index.net_exposure_multi import MultiClusterGuard, ClusterBudget
from global_index.runner import FuturesRunner, LIVE_SNAPSHOT_LIMIT

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  {tag}  {name}" + (f"  [{detail}]" if detail else ""))
    _results.append((name, cond, detail))


def _enforce_checks_under_pytest() -> None:
    """Make check() failures reach pytest.

    check() only prints and appends; the sys.exit(1) lives under
    `if __name__ == "__main__"`. So under pytest every test in this file passed
    no matter how many checks were red. This file's own pytest run reported
    "11 passed in 2152s" while the same code as a script reported six failures,
    one of them the breaker HALT scenario -- half an hour of runtime that could
    not go red. The sibling file measured the same way: script 122 passed /
    2 failed, pytest "31 passed".

    Wrapping each test rather than one summary test at the bottom: a summary
    test passes vacuously when selected alone (empty _results) and silently
    depends on file ordering, which holds only while no shuffling plugin is
    installed. Wrapping needs neither, and names the test that actually broke.
    """
    import functools
    import sys as _sys

    mod = _sys.modules[__name__]
    for _name in [n for n in dir(mod) if n.startswith("test_")]:
        _fn = getattr(mod, _name)
        if not callable(_fn) or getattr(_fn, "_checks_enforced", False):
            continue

        @functools.wraps(_fn)
        def _wrapped(*args, __fn=_fn, **kwargs):
            start = len(_results)
            out = __fn(*args, **kwargs)
            mine = _results[start:]
            assert mine, "this test recorded no checks at all"
            failed = [(n, d) for n, ok, d in mine if not ok]
            assert not failed, f"{len(failed)}/{len(mine)} check(s) failed: {failed}"
            return out

        _wrapped._checks_enforced = True
        setattr(mod, _name, _wrapped)


# ── Shared helpers ──────────────────────────────────────────────────────────

def _make_guard():
    clusters = {
        "roska4_swing":  ClusterBudget("roska4_swing",  max_gross_pct=0.05,  max_net_pct=0.044),
        "roska4_stress": ClusterBudget("roska4_stress", max_gross_pct=0.025, max_net_pct=None),
        "global_nkd":    ClusterBudget("global_nkd",    max_gross_pct=0.02,  max_net_pct=0.02),
    }
    return MultiClusterGuard(clusters=clusters, account=50_000)


def _empty_broker(account=50_000.0):
    return MockBroker({}, account=account)


def _make_runner(broker, signal_fn, positions_path=None, live_state_path=None,
                 hmm_stale_guard=None, breaker=None):
    guard = _make_guard()
    if breaker is None:
        breaker = CircuitBreaker(account=50_000)
    return FuturesRunner(
        broker=broker, guard=guard, contracts_by_inst={"MES": 1},
        signal_fn=signal_fn, breaker=breaker,
        positions_path=positions_path, live_state_path=live_state_path,
        hmm_stale_guard=hmm_stale_guard,
    )


def _noop_signal(day, bars, held):
    return [], []


def _one_entry_signal(day, bars, held):
    if held:
        return [], []
    return [{"inst": "MES", "direction": "LONG", "cluster": "roska4_swing",
             "risk_sized": 250.0, "entry": 5000.0, "stop": 4980.0}], []


# ── JS file parser (replicates dashboard's startLive logic) ─────────────────

def _parse_live_js(path: Path) -> dict | None:
    """Extract and parse window.LIVE_DATA from JS file, or return None."""
    try:
        content = path.read_text(encoding="utf-8")
        # Match multiline JSON after window.LIVE_DATA =
        m = re.search(r'window\.LIVE_DATA\s*=\s*(\{[\s\S]*?\});\s*$', content)
        if not m:
            # Try without trailing semicolon guard
            m = re.search(r'window\.LIVE_DATA\s*=\s*(\{[\s\S]*\})', content)
        if m:
            return json.loads(m.group(1))
        return None
    except Exception:
        return None


# Dashboard sort logic (replicated from renderLog)
LOG_LEVEL_ORD = {"CRITICAL": 0, "ALERT": 1, "WARN": 2, "INFO": 3}


def _dashboard_sort(events: list) -> list:
    """Replicate dashboard sort: CRITICAL/ALERT float to top, then newest first."""
    return sorted(events, key=lambda e: (
        LOG_LEVEL_ORD.get(e.get("level", "INFO"), 99),
        -len(e.get("ts", "")),  # newest first (lexicographic descending)
    ))


# ── Part 1: Historical playback ──────────────────────────────────────────────

def test_part1_historical_playback():
    print("\n" + "=" * 64)
    print("PART 1 — Historical playback (30 synthetic days)")
    print("=" * 64)

    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        pos_path = Path(td) / "live_positions.json"

        # Generate 30 synthetic trading days (Mon–Fri 2024-03-04 → 2024-04-19)
        bdays = pd.bdate_range("2024-03-04", periods=30).tolist()

        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal,
                              positions_path=pos_path, live_state_path=ls_path)

        files_written = 0
        for day in bdays:
            runner.run_day(day)
            if ls_path.exists():
                files_written += 1

        check("P1.1 live_state_data.js written after 30 days",
              ls_path.exists(),
              f"file {'exists' if ls_path.exists() else 'missing'}")

        check("P1.2 file written every run_day (30 files = last overwrite)",
              files_written == 30,
              f"files_written={files_written}")

        # Parse the final file
        live = _parse_live_js(ls_path)
        check("P1.3 final file is valid JSON", live is not None,
              "parse error" if live is None else "ok")

        if live is None:
            for i in range(4, 16):
                check(f"P1.{i} (skipped — parse failed)", False)
            return

        check("P1.4 top-level keys: runner_health + meta + snapshots",
              {"runner_health", "meta", "snapshots"}.issubset(live.keys()),
              f"keys={list(live.keys())}")

        meta = live.get("meta", {})
        check("P1.5 meta.account=50000", meta.get("account") == 50_000.0,
              f"got {meta.get('account')}")
        check("P1.6 meta.operational_status has 7 keys",
              len(meta.get("operational_status", {}).keys()) == 7,
              f"keys={list(meta.get('operational_status', {}).keys())}")
        check("P1.7 meta.events is a list",
              isinstance(meta.get("events"), list))
        # Chronological, oldest first. This check used to read
        # `snapshots[0] == bdays[-1]`, i.e. it asserted the array was REVERSED, and had
        # been red ever since -- against the real contract, not a real defect. The
        # contract is fixed by two independent witnesses: production live_state_data.js
        # runs 2026-08-10 → 2026-08-14 ascending, and dashboard startLive takes the LAST
        # element as current (test_dashboard_live_snapshot.py ls1/ls3). Asserting both
        # ends so a reversal is caught rather than half-tolerated.
        _snaps = live.get("snapshots") or []
        check("P1.8 snapshots run oldest→newest, one per trading day",
              len(_snaps) == len(bdays)
              and _snaps[0].get("date") == str(bdays[0].date())
              and _snaps[-1].get("date") == str(bdays[-1].date()),
              f"n={len(_snaps)} first={_snaps[0].get('date') if _snaps else None} "
              f"last={_snaps[-1].get('date') if _snaps else None} "
              f"expected n={len(bdays)} first={bdays[0].date()} last={bdays[-1].date()}")

        ops = meta.get("operational_status", {})
        check("P1.9 ops.runner.alive=True", ops.get("runner", {}).get("alive") is True)
        check("P1.10 ops.breaker.level='OK' (no DD on noop run)",
              ops.get("breaker", {}).get("level") == "OK",
              f"got {ops.get('breaker', {}).get('level')}")

        # Verify each event has required fields
        evs = meta.get("events", [])
        bad_events = [e for e in evs
                      if not all(k in e for k in ("ts", "level", "category", "message"))]
        check("P1.11 all events have ts/level/category/message",
              len(bad_events) == 0,
              f"{len(bad_events)} malformed event(s)")
        check("P1.12 events list non-empty (STATE day-start events expected)",
              len(evs) > 0,
              f"got {len(evs)} events")

        # Runner health
        rh = live.get("runner_health", {})
        check("P1.13 runner_health.last_heartbeat present",
              rh.get("last_heartbeat") is not None,
              f"got {rh.get('last_heartbeat')}")
        check("P1.14 runner_health.ibkr_connected=None (not wired yet)",
              rh.get("ibkr_connected") is None)

        # STATE events for each day-start
        state_day_events = [e for e in evs
                            if e.get("category") == "STATE" and "Day started" in e.get("message", "")]
        check("P1.15 30 STATE 'Day started' events emitted (one per day)",
              len(state_day_events) == 30,
              f"got {len(state_day_events)}")


# ── Part 2a: Breaker HALT inject ─────────────────────────────────────────────

def test_part2a_breaker_halt():
    print("\nPART 2a — Inject: Breaker HALT")
    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        # HOW THIS SCENARIO TRIPS HALT -- read before changing any number here.
        #
        # The runner measures drawdown against SYSTEM equity (breaker.account plus
        # realised P&L), never the broker balance. runner.py:751-765 says so and says
        # why: the paper account is funded to ~$995k while the system is sized for
        # $50k, so feeding the broker balance to the breaker put every protective
        # threshold 20x too far away -- losing the entire design capital would have
        # registered as a 5% drawdown.
        #
        # This scenario used to set MockBroker(account=$42,500) and expect HALT. It
        # could never work: state.equity starts at breaker.account = $50,000, which
        # was also the peak, so drawdown was 0.00% and the breaker sat at OK. Every
        # check below was red, and T26 in test_operational_fixes.py had the same
        # defect -- between them they were the only tests guarding the HALT path, so
        # in practice nothing was guarding it.
        #
        # Drawdown is peak-relative, so put the peak where a real drawdown leaves it:
        # $50,000 of equity under a $60,000 high-water mark is 16.67% DD, past the 15%
        # hard limit. That is the restart-after-a-losing-streak case, and the shape the
        # runner genuinely restores from persisted state (runner.py:809).
        broker = MockBroker({}, account=50_000)
        breaker = CircuitBreaker(account=50_000)
        breaker.peak_equity = 60_000.0

        runner = _make_runner(broker, _one_entry_signal, live_state_path=ls_path,
                              breaker=breaker)
        runner.run_day(pd.Timestamp("2024-06-17"))

        live = _parse_live_js(ls_path)
        check("P2a.1 file written", live is not None)
        if live is None:
            return

        ops = live["meta"]["operational_status"]
        check("P2a.2 ops.breaker.level='HALT'",
              ops["breaker"]["level"] == "HALT",
              f"got {ops['breaker']['level']}")
        check("P2a.3 ops.breaker.dd_pct_display ≥ 15.0",
              ops["breaker"]["dd_pct_display"] >= 15.0,
              f"got {ops['breaker']['dd_pct_display']}")

        halt_evs = [e for e in runner._events
                    if e["category"] == "GUARD" and "HALT" in e["message"]
                    and e["level"] == "CRITICAL"]
        check("P2a.4 GUARD CRITICAL HALT event emitted",
              len(halt_evs) >= 1,
              f"events: {[e['message'] for e in runner._events if 'GUARD' in e.get('category','')]}")

        # Dashboard sort: CRITICAL should be first
        sorted_evs = _dashboard_sort(runner._events)
        check("P2a.5 CRITICAL floats to top after dashboard sort",
              sorted_evs[0]["level"] == "CRITICAL" if sorted_evs else False,
              f"first level: {sorted_evs[0]['level'] if sorted_evs else 'empty'}")

        # Snapshot breaker_level
        check("P2a.6 snapshot.breaker_level='HALT'",
              live["snapshots"][0]["breaker_level"] == "HALT",
              f"got {live['snapshots'][0]['breaker_level']}")

        # The point of HALT is that it stops new entries -- everything above only
        # checks that the state is REPORTED. Worth its own check because the failure
        # is silent and expensive: when HALT stopped firing, the breaker fell to WARN,
        # and WARN is in allow_new_entries, so the runner opened a position at 16.67%
        # drawdown while the dashboard showed an amber "approaching limit". This runs
        # _one_entry_signal, which returns an entry candidate every day it is asked.
        check("P2a.7 HALT actually blocked the entry, not just reported itself",
              len(runner.state.open_positions) == 0,
              f"opened {len(runner.state.open_positions)} position(s) under HALT: "
              f"{[(p.inst, p.direction) for p in runner.state.open_positions]}")


# ── Part 2b: G1 hard-stale inject ───────────────────────────────────────────

def test_part2b_g1_hard_stale():
    print("\nPART 2b — Inject: G1 hard-stale")

    class _HardStaleGuard:
        """Simulates a guard that transitions to hard-stale on first call."""
        def __init__(self):
            self.regime_unreliable = False
            self.entries_blocked = 0
            self._g1_soft_active = False
            self._g2_soft_notified = False
            self._g2_hard_notified = False
            self.fit_end = pd.Timestamp("2024-12-31")
            self.regime_csv = Path("/nonexistent/spy.csv")
            self._first_call = True

        def check_day(self, today, spy_last_date_override=None):
            if self._first_call:
                self.regime_unreliable = True
                self._g1_soft_active = True
                self._first_call = False
            return not self.regime_unreliable

    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        broker = _empty_broker()
        guard_obj = _HardStaleGuard()
        runner = _make_runner(broker, _one_entry_signal, live_state_path=ls_path,
                              hmm_stale_guard=guard_obj)
        runner.run_day(pd.Timestamp("2024-06-17"))

        live = _parse_live_js(ls_path)
        check("P2b.1 file written", live is not None)
        if live is None:
            return

        ops = live["meta"]["operational_status"]
        check("P2b.2 regime_freshness.status='HARD_BLOCK'",
              ops.get("regime_freshness", {}).get("status") == "HARD_BLOCK",
              f"got {ops.get('regime_freshness', {}).get('status')}")
        check("P2b.3 ops.regime_unreliable=True",
              ops.get("regime_unreliable") is True,
              f"got {ops.get('regime_unreliable')}")

        g1_hard_evs = [e for e in runner._events
                       if e["category"] == "GUARD" and "G1 HARD-STALE" in e["message"]]
        check("P2b.4 GUARD CRITICAL G1 HARD-STALE event emitted",
              len(g1_hard_evs) >= 1,
              f"guard events: {[e['message'] for e in runner._events if e['category']=='GUARD']}")
        if g1_hard_evs:
            check("P2b.5 level=CRITICAL", g1_hard_evs[0]["level"] == "CRITICAL")


# ── Part 2c: G1 soft-stale inject ───────────────────────────────────────────

def test_part2c_g1_soft_stale():
    print("\nPART 2c — Inject: G1 soft-stale")

    class _SoftStaleGuard:
        def __init__(self):
            self.regime_unreliable = False
            self.entries_blocked = 0
            self._g1_soft_active = False
            self._g2_soft_notified = False
            self._g2_hard_notified = False
            self.fit_end = pd.Timestamp("2024-12-31")
            self.regime_csv = Path("/nonexistent/spy.csv")
            self._first_call = True

        def check_day(self, today, spy_last_date_override=None):
            if self._first_call:
                self._g1_soft_active = True  # soft only, regime_unreliable stays False
                self._first_call = False
            return True  # entries allowed (soft only)

    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal, live_state_path=ls_path,
                              hmm_stale_guard=_SoftStaleGuard())
        runner.run_day(pd.Timestamp("2024-06-17"))

        live = _parse_live_js(ls_path)
        check("P2c.1 file written", live is not None)
        if live is None:
            return

        ops = live["meta"]["operational_status"]
        check("P2c.2 regime_freshness.status='SOFT_WARN'",
              ops.get("regime_freshness", {}).get("status") == "SOFT_WARN",
              f"got {ops.get('regime_freshness', {}).get('status')}")
        check("P2c.3 ops.regime_unreliable=False",
              ops.get("regime_unreliable") is False,
              f"got {ops.get('regime_unreliable')}")

        soft_evs = [e for e in runner._events
                    if e["category"] == "GUARD" and "G1 SOFT-STALE" in e["message"]]
        check("P2c.4 GUARD WARN G1 SOFT-STALE event emitted",
              len(soft_evs) >= 1,
              f"events: {[e['message'] for e in runner._events if e['category']=='GUARD']}")
        if soft_evs:
            check("P2c.5 level=WARN", soft_evs[0]["level"] == "WARN")


# ── Part 2d: G1 recovered inject ────────────────────────────────────────────

def test_part2d_g1_recovered():
    print("\nPART 2d — Inject: G1 hard → recovered")

    class _RecoverGuard:
        def __init__(self):
            self.regime_unreliable = True   # start halted
            self.entries_blocked = 0
            self._g1_soft_active = True
            self._g2_soft_notified = False
            self._g2_hard_notified = False
            self.fit_end = pd.Timestamp("2024-12-31")
            self.regime_csv = Path("/nonexistent/spy.csv")

        def check_day(self, today, spy_last_date_override=None):
            # Simulate recovery: clear hard-stale on this day
            self.regime_unreliable = False
            self._g1_soft_active = False
            return True

    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal, live_state_path=ls_path,
                              hmm_stale_guard=_RecoverGuard())
        runner.run_day(pd.Timestamp("2024-06-17"))

        live = _parse_live_js(ls_path)
        check("P2d.1 file written", live is not None)
        if live is None:
            return

        ops = live["meta"]["operational_status"]
        check("P2d.2 regime_freshness.status='OK' after recovery",
              ops.get("regime_freshness", {}).get("status") == "OK",
              f"got {ops.get('regime_freshness', {}).get('status')}")
        check("P2d.3 ops.regime_unreliable=False after recovery",
              ops.get("regime_unreliable") is False)

        rec_evs = [e for e in runner._events
                   if e["category"] == "GUARD" and "RECOVERED" in e["message"]]
        check("P2d.4 GUARD INFO G1 RECOVERED event emitted",
              len(rec_evs) >= 1,
              f"guard events: {[e['message'] for e in runner._events if e['category']=='GUARD']}")
        if rec_evs:
            check("P2d.5 level=INFO", rec_evs[0]["level"] == "INFO")


# ── Part 2e: C1 signal throw inject ─────────────────────────────────────────

def test_part2e_c1_signal_throw():
    print("\nPART 2e — Inject: C1 signal_fn throws")

    def _boom(day, bars, held):
        raise RuntimeError("injected engine failure")

    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        broker = _empty_broker()
        runner = _make_runner(broker, _boom, live_state_path=ls_path)
        runner.run_day(pd.Timestamp("2024-06-17"))

        live = _parse_live_js(ls_path)
        check("P2e.1 file written even after signal failure", live is not None)
        if live is None:
            return

        c1_evs = [e for e in runner._events
                  if e["category"] == "SIGNAL" and "C1" in e["message"]]
        check("P2e.2 SIGNAL ALERT C1 event emitted",
              len(c1_evs) >= 1,
              f"events: {[e['message'] for e in runner._events if e['category']=='SIGNAL']}")
        if c1_evs:
            check("P2e.3 level=ALERT", c1_evs[0]["level"] == "ALERT")
            check("P2e.4 context.error present",
                  "error" in c1_evs[0].get("context", {}))

        # events[] in the JS file should contain the C1 event
        js_c1_evs = [e for e in live["meta"].get("events", [])
                     if e.get("category") == "SIGNAL" and "C1" in e.get("message", "")]
        check("P2e.5 C1 event present in live_state_data.js events[]",
              len(js_c1_evs) >= 1)


# ── Part 2f: Restart mid-playback ───────────────────────────────────────────

def test_part2f_restart():
    print("\nPART 2f — Inject: Restart mid-playback")
    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        pos_path = Path(td) / "live_positions.json"

        # Phase 1: run day 1, inject a position
        broker1 = _empty_broker()
        runner1 = _make_runner(broker1, _noop_signal,
                               positions_path=pos_path, live_state_path=ls_path)
        today = pd.Timestamp("2024-06-17")
        runner1.run_day(today)

        # Inject position, persist manually
        pos = OpenPos("MES", "LONG", 1, 250.0, "roska4_swing",
                      today, pd.Timestamp("2024-06-20"), 300.0)
        runner1.state.open_positions.append(pos)
        runner1._persist_state()

        # Phase 2: restart (new runner, new broker), run day 2
        broker2 = _empty_broker()
        runner2 = _make_runner(broker2, _noop_signal,
                               positions_path=pos_path, live_state_path=ls_path)

        restart_evs = [e for e in runner2._events if "Runner started" in e.get("message", "")]
        check("P2f.1 STATE 'Runner started' event on restart",
              len(restart_evs) >= 1,
              f"events: {[e['message'] for e in runner2._events[:3]]}")

        check("P2f.2 restarted runner has 1 persisted position",
              len(runner2.state.open_positions) == 1,
              f"got {len(runner2.state.open_positions)}")

        runner2.run_day(pd.Timestamp("2024-06-18"))

        live = _parse_live_js(ls_path)
        check("P2f.3 file written after restart run", live is not None)
        if live is None:
            return

        ops = live["meta"]["operational_status"]
        check("P2f.4 ops.positions.count matches open_positions",
              ops["positions"]["count"] == len(runner2.state.open_positions),
              f"ops={ops['positions']['count']}, state={len(runner2.state.open_positions)}")

        # STATE events in JS file should include the restart event
        js_state_evs = [e for e in live["meta"].get("events", [])
                        if e.get("category") == "STATE" and "Runner started" in e.get("message", "")]
        check("P2f.5 restart STATE event present in live_state_data.js",
              len(js_state_evs) >= 1)


# ── Part 2g: Persist fail inject ────────────────────────────────────────────

def test_part2g_persist_fail():
    print("\nPART 2g — Inject: Persist fail")
    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        valid_pos_path = Path(td) / "live_positions.json"

        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal,
                              positions_path=valid_pos_path, live_state_path=ls_path)
        runner.run_day(pd.Timestamp("2024-06-17"))
        runner._events.clear()

        # Swap to bad path → persist will fail
        runner._positions_path = Path(td) / "nosuchdir" / "positions.json"
        runner._persist_state()

        fail_evs = [e for e in runner._events
                    if e["category"] == "STATE" and "persist failed" in e["message"]]
        check("P2g.1 STATE ALERT persist-fail event emitted",
              len(fail_evs) >= 1,
              f"events: {[e['message'] for e in runner._events]}")
        if fail_evs:
            check("P2g.2 level=ALERT", fail_evs[0]["level"] == "ALERT")
            check("P2g.3 context.error present",
                  "error" in fail_evs[0].get("context", {}))


# ── Part 2h: events[] bounded ───────────────────────────────────────────────

def test_part2h_events_bounded():
    print("\nPART 2h — events[] bounded at 500 after long run")
    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        broker = _empty_broker()
        runner = _make_runner(broker, _noop_signal, live_state_path=ls_path)

        # Run 1381 days (same as full backtest history) — each day emits ≥1 event
        bdays = pd.bdate_range("2018-01-01", periods=1381).tolist()
        for day in bdays:
            runner.run_day(day)

        check("P2h.1 events[] bounded at 500 after 1381-day playback",
              len(runner._events) == 500,
              f"got {len(runner._events)}")

        # The JS file's events[] should also be bounded
        live = _parse_live_js(ls_path)
        if live:
            js_events = live["meta"].get("events", [])
            check("P2h.2 live_state_data.js events[] bounded at 500",
                  len(js_events) == 500,
                  f"got {len(js_events)}")
        else:
            check("P2h.2 live_state_data.js parseable after 1381 days", False)


# ── Part 2i: the FILE is bounded, not just events[] ─────────────────────────

def test_part2i_snapshots_bounded():
    """PART 2h bounds meta.events. Measured at day 982 of that same run, events were
    65 KB of a 426 KB file and snapshots were 360 KB across 982 entries, growing one
    per trading day with no limit. So the test named "bounded" was true and the
    artifact it protects was not.

    That costs twice. live_state_data.js is refetched by the dashboard on every poll,
    and dump_state rebuilds and reserialises the whole list inside the trading process
    on every scheduler slot -- which is why replaying 1381 days is quadratic and takes
    ~12 minutes. The runner's own history files stay complete; only the dashboard
    payload is trimmed.
    """
    print("\nPART 2i — live_state_data.js bounded, not only events[]")
    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"
        hist_days = {str(d.date()): 50_000.0 + i
                     for i, d in enumerate(pd.bdate_range("2018-01-01", periods=2000))}
        (Path(td) / "paper_history.json").write_text(
            json.dumps({"epoch": "2018-01-01", "account": 50_000.0, "days": hist_days}),
            encoding="utf-8")

        runner = _make_runner(_empty_broker(), _noop_signal, live_state_path=ls_path)
        run_day = pd.Timestamp(max(hist_days))
        runner.run_day(run_day)

        live = _parse_live_js(ls_path)
        check("P2i.1 file written", live is not None)
        if live is None:
            return
        snaps = live.get("snapshots") or []
        check("P2i.2 snapshots bounded", len(snaps) <= LIVE_SNAPSHOT_LIMIT,
              f"got {len(snaps)} from {len(hist_days)} days of history, "
              f"limit {LIVE_SNAPSHOT_LIMIT}")
        # Trim the old end, never the new one: the dashboard opens on the latest day.
        check("P2i.3 newest day survives the trim",
              bool(snaps) and snaps[-1].get("date") == str(run_day.date()),
              f"last={snaps[-1].get('date') if snaps else None}, ran {run_day.date()}")
        _dates = [s.get("date") for s in snaps]
        check("P2i.4 still oldest→newest after trimming",
              _dates == sorted(_dates),
              f"{_dates[0]} → {_dates[-1]}" if _dates else "empty")


# ── Part 3: Dashboard compatibility ─────────────────────────────────────────

def test_part3_dashboard_compat():
    print("\nPART 3 — Dashboard compatibility verification")

    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"

        # Run with a breaker HALT scenario to generate varied events. Peak-relative,
        # same as PART 2a -- see the long note there for why the broker balance cannot
        # produce a drawdown. P3.11/P3.12 read snapshot.breaker_level and
        # snapshot.drawdown_pct, which come from br.status(state.equity) too.
        broker = MockBroker({}, account=50_000)
        breaker = CircuitBreaker(account=50_000)
        breaker.peak_equity = 60_000.0

        runner = _make_runner(broker, _noop_signal, live_state_path=ls_path,
                              breaker=breaker)
        # Inject some extra events of each level/category
        runner._emit_event("CRITICAL", "GUARD",   "test CRITICAL event")
        runner._emit_event("ALERT",    "SIGNAL",  "test ALERT event")
        runner._emit_event("WARN",     "STATE",   "test WARN event")
        runner._emit_event("INFO",     "PROCESS", "test INFO event")
        runner.run_day(pd.Timestamp("2024-06-17"))

        live = _parse_live_js(ls_path)
        check("P3.1 file parseable", live is not None)
        if live is None:
            return

        # 3.1 — 7-item ops-status bar
        ops = live["meta"]["operational_status"]
        required_ops = {"runner", "breaker", "regime_freshness", "model_age",
                        "positions", "refreeze", "regime_unreliable"}
        check("P3.2 all 7 ops-status keys present",
              required_ops.issubset(ops.keys()),
              f"missing={required_ops - ops.keys()}")

        # runner subkeys the dashboard reads
        check("P3.3 ops.runner has alive/pid/last_run_day",
              all(k in ops["runner"] for k in ("alive", "pid", "last_run_day")),
              f"keys={list(ops['runner'].keys())}")
        # breaker subkeys
        check("P3.4 ops.breaker has level/dd_pct_display",
              all(k in ops["breaker"] for k in ("level", "dd_pct_display")),
              f"keys={list(ops['breaker'].keys())}")

        # 3.2 — events[] in log panel
        evs = live["meta"]["events"]
        check("P3.5 events[] present and non-empty", isinstance(evs, list) and len(evs) > 0,
              f"len={len(evs)}")

        # All events have required fields
        bad = [e for e in evs if not all(k in e for k in ("ts", "level", "category", "message"))]
        check("P3.6 all events have ts/level/category/message",
              len(bad) == 0, f"{len(bad)} malformed")

        # Levels are valid
        valid_levels = {"CRITICAL", "ALERT", "WARN", "INFO"}
        invalid_levels = [e for e in evs if e.get("level") not in valid_levels]
        check("P3.7 all event levels are CRITICAL/ALERT/WARN/INFO",
              len(invalid_levels) == 0,
              f"{len(invalid_levels)} invalid: {[e['level'] for e in invalid_levels][:3]}")

        # Categories are valid (dashboard filter buttons)
        valid_cats = {"GUARD", "STATE", "SIGNAL", "FEED", "ORDER", "PROCESS"}
        invalid_cats = [e for e in evs if e.get("category") not in valid_cats]
        check("P3.8 all event categories are valid dashboard categories",
              len(invalid_cats) == 0,
              f"{len(invalid_cats)} invalid: {[e['category'] for e in invalid_cats][:3]}")

        # 3.3 — Dashboard sort: CRITICAL float to top
        sorted_evs = _dashboard_sort(evs)
        if sorted_evs:
            check("P3.9 CRITICAL events float to top after dashboard sort",
                  sorted_evs[0]["level"] == "CRITICAL",
                  f"first={sorted_evs[0]['level']}, msg={sorted_evs[0]['message'][:50]}")

        # Dot colors: verify level maps correctly
        LEVEL_TO_DOT = {
            "HALT": "halt", "HALT_DAY": "halt", "WARN": "warn", "OK": "ok",
        }
        breaker_dot = LEVEL_TO_DOT.get(ops["breaker"]["level"], "na")
        check("P3.10 breaker dot level maps correctly for dashboard",
              breaker_dot == "halt",  # we set up HALT scenario
              f"dot={breaker_dot}")

        # 3.4 — Snapshot breaker_level drives DD bar color in dashboard
        snap = live["snapshots"][0]
        check("P3.11 snapshot.breaker_level='HALT' (drives DD bar red)",
              snap.get("breaker_level") == "HALT",
              f"got {snap.get('breaker_level')}")
        check("P3.12 snapshot.drawdown_pct ≥ 0.15",
              snap.get("drawdown_pct", 0) >= 0.15,
              f"got {snap.get('drawdown_pct')}")

        # 3.5 — Live mode detection: window.LIVE_DATA present → startLive() called
        content = ls_path.read_text(encoding="utf-8")
        check("P3.13 window.LIVE_DATA assignment present in JS",
              "window.LIVE_DATA" in content)
        check("P3.14 no window.REPLAY_DATA (live file only sets LIVE_DATA)",
              "window.REPLAY_DATA" not in content)


# ── Part 4: Baseline preservation ───────────────────────────────────────────

def test_part4_baseline():
    print("\nPART 4 — Baseline preservation: dump_state is no-op on P&L")

    # Build a signal that generates some trades to compare with / without live_state_path
    _trade_days = pd.bdate_range("2024-03-04", periods=20).tolist()
    _entry_day = _trade_days[2]
    _exit_day  = _trade_days[7]

    def _scripted_signal(day, bars, held):
        day_ts = pd.Timestamp(day).normalize()
        if day_ts == _entry_day.normalize() and not held:
            return [{"inst": "MES", "direction": "LONG", "cluster": "roska4_swing",
                     "risk_sized": 250.0, "entry": 5000.0, "stop": 4980.0,
                     "exit": _exit_day, "pnl_sized": 400.0}], []
        return [], []

    with tempfile.TemporaryDirectory() as td:
        ls_path = Path(td) / "live_state_data.js"

        # Reference run: no live_state_path
        broker_ref = _empty_broker()
        runner_ref = _make_runner(broker_ref, _scripted_signal)
        for day in _trade_days:
            runner_ref.run_day(day)
        ref_equity = broker_ref.get_equity()

        # Live run: with live_state_path
        broker_live = _empty_broker()
        runner_live = _make_runner(broker_live, _scripted_signal, live_state_path=ls_path)
        for day in _trade_days:
            runner_live.run_day(day)
        live_equity = broker_live.get_equity()

        check("P4.1 P&L identical with and without live_state_path",
              abs(ref_equity - live_equity) < 0.01,
              f"ref=${ref_equity:,.2f} live=${live_equity:,.2f} diff=${live_equity-ref_equity:+.2f}")

        # Verify baseline $52,936 equivalent: the scripted $400 trade reaches the expected account
        expected_equity = 50_000.0 + 400.0
        check("P4.2 scripted trade P&L realized correctly",
              abs(live_equity - expected_equity) < 0.01,
              f"got ${live_equity:,.2f} expected ${expected_equity:,.2f}")

        # The JS file's meta.net_pnl matches the actual P&L
        live_js = _parse_live_js(ls_path)
        if live_js:
            js_pnl = live_js["meta"].get("net_pnl", None)
            check("P4.3 meta.net_pnl in JS file matches actual P&L",
                  js_pnl is not None and abs(js_pnl - (live_equity - 50_000.0)) < 0.01,
                  f"js_pnl={js_pnl} actual={live_equity - 50_000.0}")
        else:
            check("P4.3 JS file parseable for net_pnl check", False)


# Applied here, after every test is defined -- the wrapper reads module globals.
# Only outside script mode: wrapping raises on the first red check, which is right
# for pytest but would stop the script before it printed the whole report, and
# collect-all is what the script exists for. An autouse fixture was the obvious
# alternative and was rejected -- asserting after `yield` is a TEARDOWN failure, so
# pytest prints "31 passed, 2 errors" and leaves a misleading passed-count standing
# right next to the errors.
if __name__ != "__main__":
    _enforce_checks_under_pytest()


# ── Summary ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 64)
    print("EVENT BACKEND END-TO-END PLAYBACK VERIFICATION")
    print("=" * 64)

    # Discovered, not hand-listed, in definition order. The hand-written list dropped
    # PART 2i the moment it was added: the function existed and pytest ran it, but the
    # script silently skipped it and still printed "69 passed, 0 failed / 69 total" --
    # a green total over a test it never called. Same family as everything else fixed
    # in this file: a count that cannot tell you what it failed to count.
    _suite = sorted(
        ((fn.__code__.co_firstlineno, name, fn)
         for name, fn in list(globals().items())
         if name.startswith("test_") and callable(fn)
         and getattr(fn, "__module__", None) == __name__),
    )
    assert _suite, "no test functions discovered"
    for _lineno, _name, _fn in _suite:
        _fn()

    print("\n" + "=" * 64)
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total  = len(_results)
    print(f"Results: {passed} passed, {failed} failed / {total} total")

    if failed:
        print("\nFAILED:")
        for name, ok, detail in _results:
            if not ok:
                print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        sys.exit(1)
    else:
        print("ALL PASS")
