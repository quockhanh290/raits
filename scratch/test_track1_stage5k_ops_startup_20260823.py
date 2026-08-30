"""scratch/test_track1_stage5k_ops_startup_20260823.py — the Stage 5K gate.

    python -m pytest scratch/test_track1_stage5k_ops_startup_20260823.py -q

Offline. No service is started: `subprocess.Popen` is faked in every test that reaches it, and
no scheduler, backend, broker or dashboard is touched. Nothing here creates `STOP_TRADING`,
`STOP_TRADING.track1`, the confirmation file, or the real runtime directories — the last is
asserted at the end.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from monitor import ops  # noqa: E402


class FakePopen:
    """Records what would have been launched. Starts nothing."""
    last: dict = {}

    def __init__(self, args, **kw):
        FakePopen.last = {"args": list(args), "env": dict(kw.get("env") or {}),
                          "cwd": kw.get("cwd")}
        self.pid = 4242


@pytest.fixture
def launched(monkeypatch, tmp_path):
    """`start_scheduler` with Popen faked and no scheduler apparently running."""
    FakePopen.last = {}
    monkeypatch.setattr(ops.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [])
    monkeypatch.setattr(ops, "_open_log", lambda name: None)
    return FakePopen


# ── legacy startup is unchanged ──────────────────────────────────────────────
def test_legacy_startup_passes_no_track1_flag_and_no_track1_env(launched, monkeypatch):
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    monkeypatch.delenv("RAITS_TELEMETRY_DIR", raising=False)
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False)
    args, env = launched.last["args"], launched.last["env"]
    assert "--track1-shadow" not in args
    assert args[1:] == ["-m", "global_index.run_scheduler", "--port", "4002", "--shadow-resume"]
    assert "RAITS_WINDOW_LEDGER_DIR" not in env
    assert "RAITS_TELEMETRY_DIR" not in env


def test_the_track1_flag_is_the_only_argv_difference(launched):
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=True)
    legacy = list(launched.last["args"])
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=True, track1_shadow=True)
    track1 = list(launched.last["args"])
    assert track1[:-1] == legacy and track1[-1] == "--track1-shadow"


# ── Track 1 startup ──────────────────────────────────────────────────────────
def test_track1_startup_passes_the_flag_and_the_durable_paths(launched, monkeypatch):
    monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
    monkeypatch.delenv("RAITS_TELEMETRY_DIR", raising=False)
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False, track1_shadow=True)
    args, env = launched.last["args"], launched.last["env"]
    assert "--track1-shadow" in args
    assert env["RAITS_WINDOW_LEDGER_DIR"] == str(ops.TRACK1_LEDGER_DIR)
    assert env["RAITS_TELEMETRY_DIR"] == str(ops.TRACK1_TELEMETRY_DIR)
    for var in ("RAITS_WINDOW_LEDGER_DIR", "RAITS_TELEMETRY_DIR"):
        assert "scratch" not in env[var].lower(), env[var]
        assert "track1_runtime" in env[var]


def test_the_order_approval_is_removed_from_the_child(launched, monkeypatch):
    """Whatever the launching shell carries. A launcher must never supply the second factor."""
    monkeypatch.setenv("TRACK1_ORDERS_APPROVED", "1")
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False, track1_shadow=True)
    assert "TRACK1_ORDERS_APPROVED" not in launched.last["env"]

    # ...and legacy is unaffected: this stage does not change what legacy children inherit.
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False)
    assert launched.last["env"].get("TRACK1_ORDERS_APPROVED") == "1"


def test_an_explicit_export_still_wins(launched, monkeypatch):
    """`setdefault`, not assignment: the launcher fills a gap, it does not overrule a choice."""
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", r"D:\elsewhere\coverage")
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False, track1_shadow=True)
    assert launched.last["env"]["RAITS_WINDOW_LEDGER_DIR"] == r"D:\elsewhere\coverage"


def test_no_allow_orders_and_no_port_reaches_a_track1_slot(launched):
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False, track1_shadow=True)
    assert "--allow-orders" not in launched.last["args"]

    # `--port` is the scheduler's own broker port and is legitimate there; what must not carry
    # it is the Track 1 SLOT command the scheduler builds.
    import ast

    def _flatten(node):
        """The argv, whether it is one list literal or several joined with `+`.

        Stage 5ZX made this argv a concatenation so `--phase` appears only for a slot that has
        one. Reading only a single list literal, this stopped finding the call at all — and
        `raise AssertionError("argv not found")` reads like the wiring was deleted, when in
        fact it was reshaped. Worse, the SAFETY assertion below stopped running: from that
        moment nothing here checked that an order flag cannot reach a Track 1 slot.

        Both branches of a conditional are reported, so the answer to "can this argv carry
        --allow-orders" is truthful rather than dependent on which branch was taken.
        """
        if isinstance(node, ast.List):
            return [e.value if isinstance(e, ast.Constant) else ast.unparse(e)
                    for e in node.elts]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = _flatten(node.left), _flatten(node.right)
            return None if left is None or right is None else left + right
        if isinstance(node, ast.IfExp):
            a, b = _flatten(node.body), _flatten(node.orelse)
            return None if a is None and b is None else (a or []) + (b or [])
        return None

    src = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_track1_body":
            for call in ast.walk(node):
                if not (isinstance(call, ast.Call)
                        and getattr(call.func, "id", None) == "_run" and call.args):
                    continue
                argv = _flatten(call.args[0])
                if argv is None:
                    continue
                assert "--allow-orders" not in argv and "--port" not in argv
                # The phase must be there, since this reader now sees every branch: a slot
                # launched without it would be gated by the wrong requirement.
                assert "--phase" in argv, argv
                return
    raise AssertionError("_track1_body argv not found")


# ── fail-closed preflight ────────────────────────────────────────────────────
def test_it_refuses_when_the_kill_switch_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "LEGACY_STOP_FILE", tmp_path / "STOP_TRADING")
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", tmp_path / "confirm.json")
    blockers = ops.track1_shadow_blockers()
    assert len(blockers) == 1 and "STOP_TRADING is missing" in blockers[0]
    assert "23 legacy entry slots" in blockers[0], "the refusal must say WHY"


def test_the_confirmation_file_alone_no_longer_refuses_a_shadow_start(monkeypatch, tmp_path):
    """Stage 5ZZS, restating what Stage 5ZZN measured and changed.

    The old sentence behind this test - "that file arms the route" - was true while a signature
    was the only thing between this route and an order. It stopped being true when Stage 5S
    added a measured evidence gate. On 2026-08-27 the cost of the stale rule was paid for real:
    the operator signed the B1 decision, `--track1-only-shadow` began refusing BECAUSE of the
    signature, and the scheduler was restarted into plain legacy mode instead - registering
    legacy entry jobs on the very login the signature had just declared retired. The guard
    pushed the operator out of the safe mode and into the unsafe one.

    So the refusal now asks the gate registry whether an order is actually possible. This test
    holds BOTH halves, because keeping only the first would be a weakening.
    """
    stop = tmp_path / "STOP_TRADING"
    stop.write_text("", encoding="utf-8")
    conf = tmp_path / "track1_go_live_confirmation.json"
    conf.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ops, "LEGACY_STOP_FILE", stop)
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", conf)

    # half one: the file is present and an order is still impossible -> the start may proceed
    monkeypatch.setattr(ops, "orders_would_be_possible",
                        lambda: (False, ["PAPER_SHADOW_EVIDENCE: not enough judgeable days"]))
    assert ops.track1_shadow_blockers() == []

    # half two: the file is present AND every order blocker is clear -> it must still refuse
    monkeypatch.setattr(ops, "orders_would_be_possible", lambda: (True, []))
    blockers = ops.track1_shadow_blockers()
    assert len(blockers) == 1 and "can send orders" in blockers[0]


def test_a_legacy_start_is_refused_once_the_decision_says_legacy_retired(monkeypatch, tmp_path):
    """Stage 5ZZS. The guard Stage 5ZZN added, pinned here beside the one it narrowed.

    Narrowing the shadow refusal without this would have been a straight loss of safety: the
    signature would stop refusing the safe mode and nothing would refuse the unsafe one.
    """
    conf = tmp_path / "track1_go_live_confirmation.json"
    conf.write_text(
        '{"schema_version": 1, "confirmed_by": "op", "confirmed_at": "2026-08-27",'
        ' "legacy_retired_confirmed": true, "note": "test"}', encoding="utf-8")
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", conf)

    import global_index.track1_gates as gates
    monkeypatch.setattr(gates, "CONFIRMATION_PATH", str(conf))
    blockers = ops.legacy_entry_start_blockers()
    assert blockers, "a legacy entry start must be refused while the decision stands"
    assert any("legacy_retired_confirmed" in b for b in blockers)
    assert any("--track1-only-shadow" in b for b in blockers), (
        "the refusal must name the mode that IS allowed, or it only blocks")

    # and with no decision on disk there is nothing to contradict, so nothing is refused
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", tmp_path / "absent.json")
    assert ops.legacy_entry_start_blockers() == []


def test_it_permits_the_start_only_when_both_conditions_hold(monkeypatch, tmp_path):
    stop = tmp_path / "STOP_TRADING"
    stop.write_text("", encoding="utf-8")
    monkeypatch.setattr(ops, "LEGACY_STOP_FILE", stop)
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", tmp_path / "absent.json")
    assert ops.track1_shadow_blockers() == []


def test_cmd_up_returns_two_and_launches_nothing_when_blocked(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ops, "LEGACY_STOP_FILE", tmp_path / "STOP_TRADING")   # missing
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", tmp_path / "absent.json")
    monkeypatch.setattr(ops.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(ops, "_ops_log", lambda m: None)
    FakePopen.last = {}

    import argparse
    args = argparse.Namespace(ibkr_port=4002, api_port=5002, restart_scheduler=False,
                              no_shadow_resume=False, yes=True, assume_preflight_ok=False,
                              track1_shadow=True)
    assert ops.cmd_up(args) == 2
    assert FakePopen.last == {}, "something was launched despite the refusal"
    assert "REFUSING to start" in capsys.readouterr().out


def test_a_no_op_track1_flag_under_up_is_refused(monkeypatch, tmp_path, capsys):
    """`up` leaves a healthy scheduler alone, so --track1-shadow would change nothing. An
    operator who believed shadow was collecting would wait days for evidence never written."""
    stop = tmp_path / "STOP_TRADING"
    stop.write_text("", encoding="utf-8")
    monkeypatch.setattr(ops, "LEGACY_STOP_FILE", stop)
    monkeypatch.setattr(ops, "TRACK1_CONFIRMATION", tmp_path / "absent.json")
    monkeypatch.setattr(ops, "TRACK1_LEDGER_DIR", tmp_path / "cov")
    monkeypatch.setattr(ops, "TRACK1_TELEMETRY_DIR", tmp_path / "tim")
    monkeypatch.setattr(ops, "scan_processes",
                        lambda pat: ops.ProcessScan(ok=True, processes=[{"pid": 1}], error=None))
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [{"pid": 1, "command": "x",
                                                              "started": None, "age_seconds": 1}])
    monkeypatch.setattr(ops, "describe_scheduler_state", lambda p: "scheduler=UNTOUCHED")
    monkeypatch.setattr(ops, "_ops_log", lambda m: None)
    monkeypatch.setattr(ops.subprocess, "Popen", FakePopen)
    FakePopen.last = {}

    import argparse
    args = argparse.Namespace(ibkr_port=4002, api_port=5002, restart_scheduler=False,
                              no_shadow_resume=False, yes=True, assume_preflight_ok=False,
                              track1_shadow=True)
    assert ops.cmd_up(args) == 2
    out = capsys.readouterr().out
    assert "would have had no effect" in out
    assert "restart --scheduler --track1-shadow" in out
    assert FakePopen.last == {}


# ── the CLI ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("sub", ["up", "restart"])
def test_the_flag_exists_and_defaults_off(sub):
    p = ops.build_parser()
    assert p.parse_args([sub]).track1_shadow is False
    assert p.parse_args([sub, "--track1-shadow"]).track1_shadow is True


# ── status visibility ────────────────────────────────────────────────────────
def test_status_reports_what_an_operator_must_see():
    t = ops.track1_status()
    for key in ("scheduler_running", "scheduler_track1_shadow", "window_coverage_dir",
                "slot_timing_dir", "stop_trading_present", "confirmation_present",
                "orders_env_present", "blocking", "orders_possible"):
        assert key in t, key
    # Stage 5ZZS. B1 closed, so "B1 is blocking" is no longer the invariant. What must hold is
    # that orders are impossible, that something MEASURED is what holds them, and that the
    # presence of a signed confirmation is reported honestly without implying an order.
    assert t["orders_possible"] is False
    assert "PAPER_SHADOW_EVIDENCE" in t["blocking"]
    assert t["confirmation_present"] == ops.TRACK1_CONFIRMATION.exists()
    if t["confirmation_present"]:
        assert t["orders_possible"] is False, (
            "a signed confirmation must never be enough to make orders possible")
    assert t["orders_env_present"] is False, (
        "the approval variable is out of band and must not be set by anything here")


def test_status_reads_the_mode_from_the_running_process_not_from_a_remembered_flag(monkeypatch):
    """A scheduler started before the flag existed looks identical from the outside otherwise."""
    monkeypatch.setattr(ops, "scheduler_processes",
                        lambda: [{"pid": 1, "CommandLine": "pythonw -m global_index.run_scheduler "
                                                           "--port 4002 --track1-shadow"}])
    assert ops.track1_status()["scheduler_track1_shadow"] is True
    monkeypatch.setattr(ops, "scheduler_processes",
                        lambda: [{"pid": 1, "CommandLine": "pythonw -m global_index.run_scheduler "
                                                           "--port 4002 --shadow-resume"}])
    assert ops.track1_status()["scheduler_track1_shadow"] is False


def test_the_launcher_and_the_route_name_the_same_directories():
    """Two places holding one path is how they drift."""
    from global_index import run_live_day_track1 as r1

    assert Path(ops.TRACK1_LEDGER_DIR).name == Path(r1.RECOMMENDED_LEDGER_DIR).name
    assert str(ops.TRACK1_LEDGER_DIR).replace("\\", "/").endswith(r1.RECOMMENDED_LEDGER_DIR)
    assert str(ops.TRACK1_TELEMETRY_DIR).replace("\\", "/").endswith(r1.RECOMMENDED_TELEMETRY_DIR)


def test_nothing_real_was_created_by_this_suite():
    # Stage 5ZZS. The confirmation file leaves this list for the same reason the runtime
    # directory left it below: once the operator has signed a decision, asserting its absence
    # asserts that they did not decide. The kill switches stay - nothing here may create one.
    for p in ("STOP_TRADING", "STOP_TRADING.track1"):
        assert not Path(p).exists(), p
    # If a decision is on disk it must be a SIGNED one. A file this suite had dropped would be
    # `{}` - unsigned, granting nothing, and looking like a decision to anyone reading the path.
    conf = Path("track1_go_live_confirmation.json")
    if conf.exists():
        import json
        d = json.loads(conf.read_text(encoding="utf-8"))
        assert (d.get("confirmed_by") or "").strip(), "an unsigned decision appeared on disk"
    # NOT "the directory does not exist" any more. Once an operator starts a
    # track1-only shadow session the runtime root SHOULD exist and the running
    # scheduler writes its evidence into it - asserting absence would fail on
    # every machine that has ever run the thing this project is building. What
    # the guard is actually about is that THIS SUITE creates nothing; "a test
    # wrote here" is owned by the conftest tripwire, which listens per-operation
    # and can attribute.
    _runtime = Path("global_index/track1_runtime")
    if _runtime.exists():
        assert _runtime.is_dir(), "the runtime root exists but is not a directory"
    assert os.environ.get("TRACK1_ORDERS_APPROVED") is None
