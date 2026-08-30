"""Stage 5M-D — Track 1-only shadow mode, and the legacy-removability audit.

No scheduler started, no real IBKR, no orders, no switch files, no live state written. Every
ledger and checkpoint these tests produce goes under `tmp_path`.

The mode under test
-------------------
    (default)             legacy only — 60 jobs, unchanged and tested to be unchanged
    --track1-shadow       legacy PLUS Track 1 — transitional, 107 jobs, unchanged
    --track1-only-shadow  Track 1 plus shared infrastructure — legacy STRATEGY jobs are not
                          registered at all. 62 jobs. NEW.

Why the third exists: `STOP_TRADING` halts legacy ENTRIES inside `runner.run_day`, but by then
the legacy slot has spawned, connected on clientId 1 and fetched bars. Freezing legacy removes
the trading, not the load — so 5M-C had to keep the Normal-R4 provider staged. Removing the
jobs removes the collision structurally, which is why the swing provider defaults to `ibkr`
in this mode and only in this mode.

The removability audit
----------------------
"Legacy-removable" is tested by BLOCKING the legacy entrypoint at import time — not by a
static scan alone, because an import on a branch nobody took slips past a scan — and then
building the scheduler, firing every Track 1 slot closure, and building the dashboard mirror.
"""
from __future__ import annotations

import ast
import importlib
import logging
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_index import track1_slots as ts   # noqa: E402

SWING = "roska4_swing"
LEGACY_MODULES = ("global_index.run_live_day",)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SWING_PROVIDER", "RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY"):
        monkeypatch.delenv(k, raising=False)


def _sched(**kw):
    os.environ.setdefault("PYTEST_CURRENT_TEST", "5md")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from global_index import run_scheduler as rs
        return rs.make_scheduler(port=4002, dry_run=True, **kw)
    finally:
        logging.disable(lvl)


def _ids(**kw) -> set:
    return {j.id for j in _sched(**kw).get_jobs()}


def _buckets(ids) -> dict:
    out: dict = {}
    for i in ids:
        out.setdefault(ts._bucket_for(i), []).append(i)
    return {k: sorted(v) for k, v in out.items()}


# ══════════════════════════════════════════════════════════════════════════════
# 1. the three schedules
# ══════════════════════════════════════════════════════════════════════════════

def test_the_default_schedule_is_unchanged():
    b = _buckets(_ids())
    assert len(b.get("legacy_entry", [])) == 45
    assert len(b.get("safety", [])) == 12
    assert sorted(b.get("shared_infra", [])) == ["heartbeat", "preflight",
                                                 "session_report_fallback",
                                                 "spy_refresh_pm"]
    assert "track1" not in b
    assert sum(len(v) for v in b.values()) == 61  # Stage 5Q-5 added the 16:20 post-close SPY refresh (shared infra, all modes): 60->61, 129->130, 100->101


def test_the_transitional_shadow_schedule_is_unchanged():
    # Track 1's own count is derived — Stage 5N added the 22 NKD slots and the pinned 48
    # turned red for an intended change. What must not move is LEGACY: 45 entry jobs, all
    # still present in the transitional mode.
    b = _buckets(_ids(track1_shadow=True))
    assert len(b.get("legacy_entry", [])) == 45
    assert len(b.get("track1", [])) == len(ts.TRACK1_SLOTS)
    assert sum(len(v) for v in b.values()) == 60 + len(ts.TRACK1_SLOTS)


def test_track1_only_registers_no_legacy_strategy_job():
    """The stage's central claim, asserted as an absence AND a presence."""
    b = _buckets(_ids(track1_only=True))
    assert b.get("legacy_entry", []) == [], b.get("legacy_entry")
    # Stage 5Q added the read-only post-window audit jobs to this mode. Derived from their
    # own table, like the slots and the safety jobs, so the count moves with the table.
    t1_expected = (len(ts.TRACK1_SLOTS) + len(ts.track1_safety_jobs())
                   + len(ts.track1_audit_jobs()))
    assert len(b.get("track1", [])) == t1_expected
    assert sorted(b.get("shared_infra", [])) == ["heartbeat", "preflight",
                                                 "session_report_fallback",
                                                 "spy_refresh_pm"]
    assert sum(len(v) for v in b.values()) == 15 + t1_expected


def test_the_removed_set_is_exactly_the_retirement_candidates():
    """Not "some legacy jobs are gone" — exactly the set the Stage 5L classification calls
    removable, and nothing else. One table, three readers: the audit, the classification and
    this mode. Two definitions of "legacy's jobs" is how they drift."""
    on = _ids(track1_shadow=True)
    only = _ids(track1_only=True)
    assert on - only == ts.legacy_retirement_candidates(track1_shadow=True)


def test_the_safety_sweeps_survive_and_are_named_as_a_blocker_not_a_feature():
    """Stop repair and max-hold stay registered in Track 1-only mode. They are NOT
    route-safe — both are hard-wired to legacy's positions file — and removing them would
    leave any position still open in that book with no stop repair and no five-day exit.
    Keeping them is correct; calling the mode legacy-INDEPENDENT because of them would not be.
    That is Stage 5O."""
    b = _buckets(_ids(track1_only=True))
    assert "maxhold_exit" in b.get("safety", [])
    assert any(i.startswith("stop_repair") for i in b.get("safety", []))


# ══════════════════════════════════════════════════════════════════════════════
# 2. the argv in the new mode
# ══════════════════════════════════════════════════════════════════════════════

def _argv(**kw) -> list:
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args), "route": route}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, **kw)
        # STRATEGY slots only. Stage 5O added 11 track1_* SAFETY jobs whose argv is a
        # different contract — no --sleeve, and --port is legitimate there (run_stop_repair
        # dials the Gateway). This suite's subject is the strategy slots; the safety argv
        # has its own suite.
        strategy_ids = {s.id.lower() for s in ts.TRACK1_SLOTS}
        for j in sched.get_jobs():
            if j.id in strategy_ids:
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    assert seen, "no Track 1 slot fired — nothing was captured"
    return seen


def _providers(rows) -> dict:
    out: dict = {}
    for r in rows:
        a = r["args"]
        out.setdefault(a[a.index("--sleeve") + 1], set()).add(
            a[a.index("--bar-provider") + 1])
    return out


def test_in_track1_only_the_swing_slots_take_ibkr_by_default():
    """The reason 5M-C staged the provider was the legacy collision; this mode removes the
    collision, so the staging reason is gone WITH it — in this mode only. Stage 5N added
    global_nkd to the staged set for the same reason (legacy nkd_night occupies its band in
    the transitional mode), so it appears here too."""
    p = _providers(_argv(track1_only=True))
    assert p == {"roska4_calm": {"ibkr"}, "roska4_stress": {"ibkr"}, SWING: {"ibkr"},
                 "global_nkd": {"ibkr"}}, p


def test_in_transitional_shadow_the_swing_slots_still_default_to_none():
    """The 5M-C decision stands where its reason still holds: legacy children still occupy
    every 14:05-15:55 minute in this mode, and the collision is still unmeasured."""
    p = _providers(_argv(track1_shadow=True))
    assert p[SWING] == {"none"}, p


def test_the_env_var_still_overrides_in_both_directions(monkeypatch):
    monkeypatch.setenv(ts.SWING_PROVIDER_ENV, "none")
    assert _providers(_argv(track1_only=True))[SWING] == {"none"}
    monkeypatch.setenv(ts.SWING_PROVIDER_ENV, "ibkr")
    assert _providers(_argv(track1_shadow=True))[SWING] == {"ibkr"}


def test_a_typo_in_the_override_still_refuses_at_build_time(monkeypatch):
    monkeypatch.setenv(ts.SWING_PROVIDER_ENV, "IBKR")
    with pytest.raises(ValueError):
        _argv(track1_only=True)


@pytest.mark.parametrize("nope", ["--allow-orders", "--port", "--window"])
def test_no_order_or_replay_flag_in_the_new_mode(nope):
    for r in _argv(track1_only=True):
        assert nope not in r["args"], (r["label"], nope)


def test_every_child_is_stamped_with_the_route():
    assert {r["route"] for r in _argv(track1_only=True)} == {"track1_candidate"}


def test_b1_still_blocks_orders():
    from global_index import track1_gates as g
    assert g.as_ledger()["blocking_now"] == ["B1_broker_account_or_legacy_retirement"]


# ══════════════════════════════════════════════════════════════════════════════
# 3. dashboard parity, three modes
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kw", [{}, {"track1_shadow": True}, {"track1_only": True}])
def test_the_scheduler_and_the_mirror_agree(kw):
    r = ts.parity_report(**kw)
    assert r["in_parity"], r


def test_in_track1_only_the_mirror_shows_no_legacy_strategy_rows(monkeypatch):
    import datetime as dt
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    from monitor.backend import schedule_status as ss
    importlib.reload(ss)
    try:
        ids = [r["id"] for r in ss._scheduled_slots_for(dt.date(2026, 8, 24))]
        assert not [i for i in ids if i.startswith(("LIVE_DAY", "NKD_NIGHT"))], ids
        weekday_safety = [sj for sj in ts.track1_safety_jobs()
                          if sj.day_of_week != "sun"]
        assert len([i for i in ids if i.startswith("TRACK1_")]) == (
            len(ts.TRACK1_SLOTS) + len(weekday_safety) + len(ts.track1_audit_jobs()))
        assert "PREFLIGHT" in ids and "MAX_HOLD_EXIT" in ids
    finally:
        monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
        importlib.reload(ss)


def test_track1_only_implies_the_shadow_mirror(monkeypatch):
    """One env var must not be able to disagree with the other about whether Track 1 rows
    exist — RAITS_TRACK1_ONLY alone must light both."""
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    from monitor.backend import schedule_status as ss
    importlib.reload(ss)
    try:
        assert ss.track1_shadow_enabled() is True
        assert ss.track1_only_enabled() is True
    finally:
        monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
        importlib.reload(ss)


# ══════════════════════════════════════════════════════════════════════════════
# 4. ops
# ══════════════════════════════════════════════════════════════════════════════

def test_ops_refuses_both_shadow_flags_together(capsys, tmp_path, monkeypatch):
    import argparse
    from monitor import ops
    # The runtime dirs are redirected even though this call is EXPECTED to refuse before
    # reaching them. It did not stay expected: the Stage 5O mutation harness neuters the
    # refusal on purpose (D4), and the un-refused `cmd_up` ran its
    # `TRACK1_LEDGER_DIR.mkdir(parents=True)` against the real tree — creating
    # `global_index/track1_runtime/` on 2026-08-24 at 00:28. A test whose safety depends on
    # the code under test taking an early return is a test that leaks the day someone
    # deliberately removes that return.
    monkeypatch.setattr(ops, "TRACK1_LEDGER_DIR", tmp_path / "window_coverage")
    monkeypatch.setattr(ops, "TRACK1_TELEMETRY_DIR", tmp_path / "slot_timing")
    ns = argparse.Namespace(track1_shadow=True, track1_only_shadow=True, yes=True,
                            label="up", ibkr_port=4002, scheduler=False,
                            no_shadow_resume=False, assume_preflight_ok=False,
                            api_port=ops.DEFAULT_API_PORT)
    rc = ops.cmd_up(ns)
    assert rc == 2
    assert "different schedules" in capsys.readouterr().out


def test_ops_track1_only_does_not_require_stop_trading():
    """The mode registers no legacy entry jobs, so there is nothing for the switch to halt.
    Requiring it anyway would teach the operator the switch is what stops legacy."""
    from monitor import ops
    assert not ops.LEGACY_STOP_FILE.exists(), "precondition: no STOP_TRADING on disk"
    assert ops.track1_shadow_blockers(track1_only=True) == []
    blockers = ops.track1_shadow_blockers(track1_only=False)
    assert any("STOP_TRADING" in b for b in blockers), (
        "transitional mode no longer requires the switch — that is a behaviour change this "
        "stage did not intend")


def test_ops_env_carries_both_flags_to_the_child():
    from monitor import ops
    env = ops._env(track1_only=True)
    assert env.get("RAITS_TRACK1_ONLY") == "1"
    assert env.get("RAITS_TRACK1_SHADOW") == "1"
    assert ops.TRACK1_ORDERS_ENV not in env
    legacy_env = ops._env()
    assert "RAITS_TRACK1_ONLY" not in legacy_env


def test_ops_start_scheduler_builds_the_right_argv(monkeypatch):
    from monitor import ops
    seen = {}

    class _P:
        pid = 1234

    monkeypatch.setattr(ops, "scheduler_processes", lambda: [])
    monkeypatch.setattr(ops.subprocess, "Popen",
                        lambda args, **kw: seen.update({"args": args, "env": kw.get("env")}) or _P())
    monkeypatch.setattr(ops, "_open_log", lambda name: None)
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False,
                        track1_only=True)
    assert "--track1-only-shadow" in seen["args"]
    assert "--track1-shadow" not in seen["args"], "both flags on one argv"
    assert seen["env"].get("RAITS_TRACK1_ONLY") == "1"


def test_ops_help_works_as_a_script_not_only_as_an_import():
    """The Stage 5M-C defect, pinned: `track1_slot_count()` runs at parser build, and
    operators run `python monitor/ops.py`, which does not put the repo root on sys.path. The
    5M-C tests imported the module and never crossed that seam. This runs it the way the
    runbook says to."""
    import subprocess
    r = subprocess.run([sys.executable, "monitor/ops.py", "up", "--help"],
                       capture_output=True, text=True, cwd=r"d:\raits", timeout=120)
    assert r.returncode == 0, r.stderr[-500:]
    assert "track1-only-shadow" in r.stdout


# ══════════════════════════════════════════════════════════════════════════════
# 5. legacy-removability
# ══════════════════════════════════════════════════════════════════════════════

class _block_legacy:
    """Make the legacy entrypoint unimportable, by EVERY import route.

    A `builtins.__import__` wrapper — the first version of this — only intercepts `import X`
    statements. `importlib.import_module` walks `sys.meta_path` directly and sailed straight
    past it, which this suite's own self-check caught: the "prove the block blocks" test was
    the one that failed. A meta-path finder placed FIRST is consulted by both routes.
    """

    class _Finder:
        def find_spec(self, name, path=None, target=None):
            if name in LEGACY_MODULES or any(name.startswith(n + ".")
                                             for n in LEGACY_MODULES):
                raise ImportError(f"{name} is deleted in this simulation")
            return None

    def __enter__(self):
        self._finder = self._Finder()
        self._saved = {n: sys.modules.pop(n, None) for n in LEGACY_MODULES}
        sys.meta_path.insert(0, self._finder)
        return self

    def __exit__(self, *exc):
        sys.meta_path.remove(self._finder)
        for n, mod in self._saved.items():
            if mod is not None:
                sys.modules[n] = mod
        return False


def test_no_track1_module_imports_the_legacy_entrypoint():
    """Static half: no import statement anywhere in the Track 1 runtime."""
    offenders = []
    for p in sorted(Path(r"d:\raits\global_index").glob("track1_*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"), str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [f"{p.name}:{node.lineno}" for a in node.names
                              if a.name in LEGACY_MODULES]
            elif isinstance(node, ast.ImportFrom) and node.module in LEGACY_MODULES:
                offenders.append(f"{p.name}:{node.lineno}")
    assert offenders == [], offenders


def test_the_track1_only_schedule_builds_with_legacy_deleted():
    """Dynamic half: the entrypoint is unimportable, and everything still works."""
    with _block_legacy():
        b = _buckets(_ids(track1_only=True))
        assert b.get("legacy_entry", []) == []
        assert len(b.get("track1", [])) == (len(ts.TRACK1_SLOTS)
                                            + len(ts.track1_safety_jobs())
                                            + len(ts.track1_audit_jobs()))


def test_every_track1_slot_fires_with_legacy_deleted():
    with _block_legacy():
        rows = _argv(track1_only=True)
        assert len(rows) == len(ts.TRACK1_SLOTS)
        assert _providers(rows)[SWING] == {"ibkr"}
        assert _providers(rows)["global_nkd"] == {"ibkr"}


def test_the_dashboard_mirror_builds_with_legacy_deleted(monkeypatch):
    import datetime as dt
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    with _block_legacy():
        from monitor.backend import schedule_status as ss
        importlib.reload(ss)
        rows = ss._scheduled_slots_for(dt.date(2026, 8, 24))
        weekday_safety = [sj for sj in ts.track1_safety_jobs()
                          if sj.day_of_week != "sun"]
        assert len([r for r in rows if r["id"].startswith("TRACK1_")]) == (
            len(ts.TRACK1_SLOTS) + len(weekday_safety) + len(ts.track1_audit_jobs()))
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    from monitor.backend import schedule_status as ss2
    importlib.reload(ss2)


def test_the_import_block_itself_works():
    """The three tests above pass by nothing failing, which is the shape of a guard that has
    stopped guarding. Prove the block actually blocks."""
    with _block_legacy():
        with pytest.raises(ImportError):
            importlib.import_module("global_index.run_live_day")


def test_track1_names_legacy_state_only_to_refuse_writing_it():
    """The state half of removability. Track 1's only code-level mentions of legacy's files
    must be inside its own `LEGACY_PATHS` refusal list — naming a thing to guarantee you never
    write it is the opposite of depending on it."""
    import global_index.run_live_day_track1 as entry
    src = Path(entry.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    legacy_files = {"live_positions.json", "global_index/replay_checkpoint.json",
                    "global_index/live_state_data.js", "trade_log.jsonl"}
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value in legacy_files]
    assert hits, "the guard list is gone — nothing names the files Track 1 must never write"
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines, 1) if "LEGACY_PATHS" in l)
    end = next(i for i, l in enumerate(lines[start:], start + 1) if l.rstrip().endswith(")"))
    outside = [h for h in hits if not (start <= h <= end)]
    assert outside == [], f"legacy state named outside the refusal list at lines {outside}"
    for f in legacy_files:
        assert f in entry.LEGACY_PATHS


def test_the_remaining_legacy_dependency_is_the_safety_jobs_and_it_is_named():
    """The one true dependency left, asserted so it cannot be forgotten: the sweeps carry
    legacy's positions file on their argv. Stage 5O's work, recorded as a blocker."""
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append(list(args)) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_only=True)
        for j in sched.get_jobs():
            if j.id.startswith("stop_repair") or j.id == "maxhold_exit":
                j.func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    paths = {a[a.index("--positions-path") + 1] for a in seen if "--positions-path" in a}
    assert paths == {"live_positions.json"}, paths


# ══════════════════════════════════════════════════════════════════════════════
# 6. stale text guards
# ══════════════════════════════════════════════════════════════════════════════

OPERATOR_FACING = [Path("monitor/ops.py"), Path("global_index/run_scheduler.py"),
                   Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md")]

#: Text claiming the root switch turns legacy OFF / disables it / stops it running. Halting
#: entries is what it does, and text saying more than that is how an operator learns the
#: wrong model. History lines describing the misconception are allowed.
_SWITCH_MYTH = re.compile(
    r"STOP_TRADING[^.\n]{0,60}\b(turns?\s+off|disables?|stops?\s+legacy\s+(from\s+)?running"
    r"|shuts?\s+down)\b", re.IGNORECASE)


def test_no_operator_text_claims_stop_trading_turns_legacy_off():
    offenders = []
    for path in OPERATOR_FACING:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SWITCH_MYTH.search(line) and not re.search(
                    r"\b(not|does not|khong|myth|wrong|false|belief)\b", line, re.IGNORECASE):
                offenders.append(f"{path.name}:{n}: {line.strip()[:90]}")
    assert offenders == [], offenders


def test_the_myth_guard_would_catch_the_claim():
    assert _SWITCH_MYTH.search("STOP_TRADING turns off legacy")
    assert _SWITCH_MYTH.search("STOP_TRADING disables the legacy route")
    assert _SWITCH_MYTH.search("STOP_TRADING stops legacy from running")


_STALE_COUNT = re.compile(r"\b25\s+(?:Track\s*1\s+)?(?:slots?|jobs?)\b", re.IGNORECASE)


def test_no_hardcoded_slot_count_returned():
    offenders = []
    for path in OPERATOR_FACING:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _STALE_COUNT.search(line) and not re.search(
                    r"\b(said|was written|until Stage|used to)\b", line, re.IGNORECASE):
                offenders.append(f"{path.name}:{n}")
    assert offenders == [], offenders


def test_no_switch_or_state_file_was_touched():
    for name in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
                 "live_positions.track1.json"):
        assert not Path(name).exists(), name
