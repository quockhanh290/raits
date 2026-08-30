"""Stage 5O — the safety net is route-aware, and track1-only stops depending on legacy's book.

No scheduler started, no real IBKR, no orders, no switch files, no live state written. Every
marker file these tests write goes under `tmp_path`; the argv checks replace the subprocess
runner so nothing executes.

What this stage closes
----------------------
Audit blocker L3, and the one dependency the 5M-D removability probe measured and refused to
wave through: every stop-repair sweep and the 09:31 max-hold exit carried
`--positions-path live_positions.json`. A Track 1 position would have had no stop repair and
no five-day exit — and the shared `maxhold_state.json` marker meant one route's "already ran
today" could silently suppress the other's sweep.

After 5O, in track1-only mode:

    legacy safety   still registered, still watching live_positions.json — DRAIN, classified,
                    not an oversight. Any legacy position still open keeps its protection.
    track1 safety   11 jobs (max-hold 09:31, nine weekday sweeps, Sunday 18:30) watching
                    live_positions.track1.json, kill switch STOP_TRADING.track1, lock
                    runner.track1.pid, client id 90, marker maxhold_state.track1.json.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_index import track1_slots as ts   # noqa: E402

NKD = "global_nkd"
LEGACY_MODULES = ("global_index.run_live_day",)


#: When this test module was imported — i.e. before any test in it ran. Used below instead of
#: asserting a file's ABSENCE. Measured 2026-08-24: the live scheduler's TRACK1_MAX_HOLD_EXIT
#: job ran at 07:31 local (09:31 ET) and wrote `global_index/maxhold_state.track1.json`
#: (`[TRACK1_MAX_HOLD_EXIT] completed OK` in scheduler_0824.log), which is exactly what Stage
#: 5O built that marker for. Absence had been standing in for "no test wrote it", and the
#: proxy broke the moment the running system started writing it legitimately. An mtime older
#: than this process is a stronger statement than absence ever was: it says no test in this
#: run touched it, which is the thing actually being guarded.
_IMPORTED_AT = __import__("time").time()


def _assert_not_written_by_this_run(name: str) -> None:
    p = Path(name)
    if not p.exists():
        return
    assert p.stat().st_mtime < _IMPORTED_AT, (
        f"{name} was written DURING this test run — everything here must run against "
        f"tmp_path")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SWING_PROVIDER", "RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY"):
        monkeypatch.delenv(k, raising=False)


def _sched(**kw):
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5o")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from global_index import run_scheduler as rs
        return rs.make_scheduler(port=4002, dry_run=True, **kw)
    finally:
        logging.disable(lvl)


def _fire_safety(**kw):
    """Fire every safety job closure with the runner replaced. Nothing executes."""
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args), "route": route}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, **kw)
        for j in sched.get_jobs():
            if j.id.startswith(("stop_repair", "maxhold_exit",
                                "track1_stop_repair", "track1_maxhold")):
                j.func()
    finally:
        rs._run = orig
        rs._maxhold_done.clear()
        rs._maxhold_done_t1.clear()
        logging.disable(lvl)
    assert seen, "no safety job fired — nothing was captured"
    return seen


def _flag(args, name):
    return args[args.index(name) + 1] if name in args else None


# ══════════════════════════════════════════════════════════════════════════════
# 1. inventory: the schedule per mode
# ══════════════════════════════════════════════════════════════════════════════

def test_track1_safety_exists_only_in_track1_only_mode():
    for kw, want in (({}, 0), ({"track1_shadow": True}, 0), ({"track1_only": True}, 11)):
        ids = {j.id for j in _sched(**kw).get_jobs()}
        got = [i for i in ids if i.startswith(("track1_stop_repair", "track1_maxhold"))]
        assert len(got) == want, (kw, sorted(got))


def test_the_default_schedule_is_still_60_jobs():
    assert len(_sched().get_jobs()) == 61  # Stage 5Q-5 added the 16:20 post-close SPY refresh (shared infra, all modes): 60->61, 129->130, 100->101


def test_legacy_safety_survives_in_track1_only_for_the_drain():
    """Deliberate, classified, and the reason this stage does not claim legacy DELETABLE:
    any position still open in legacy's book keeps its stop repair and its five-day exit."""
    ids = {j.id for j in _sched(track1_only=True).get_jobs()}
    assert "maxhold_exit" in ids
    assert any(i.startswith("stop_repair_") for i in ids)


def test_the_safety_table_and_the_scheduler_agree():
    ids = {j.id for j in _sched(track1_only=True).get_jobs()}
    want = {sj.id for sj in ts.track1_safety_jobs()}
    assert want <= ids, sorted(want - ids)
    assert len(want) == 11


def test_the_sweep_hours_are_derived_from_track1s_own_windows():
    """No sweep inside any Track 1 entry window — the same rule legacy applies to its own.
    Checked against the window table, not a list, so a new window moves the sweeps."""
    hours = ts._track1_sweep_hours()
    for h in hours:
        for lo, hi in ts.REQUIRED_ENTRY_WINDOWS.values():
            assert not (lo <= (h, 20) <= hi), (h, lo, hi)
    assert 2 not in hours and 12 not in hours and 14 not in hours
    assert hours, "no sweep hours at all — the derivation collapsed"


# ══════════════════════════════════════════════════════════════════════════════
# 2. the argv: two routes, two books, nothing shared
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def fired():
    return _fire_safety(track1_only=True)


def test_track1_safety_watches_track1s_book_and_only_track1s(fired):
    mine = [r for r in fired if r["label"].startswith(("TRACK1_STOP_REPAIR", "TRACK1_MAX"))]
    assert len(mine) == 11, sorted(r["label"] for r in mine)
    for r in mine:
        a = r["args"]
        assert _flag(a, "--positions-path") == "live_positions.track1.json", r["label"]
        assert _flag(a, "--stop-path") == "STOP_TRADING.track1", r["label"]
        assert _flag(a, "--lock-path") == "runner.track1.pid", r["label"]
        assert _flag(a, "--client-id") == "90", r["label"]
        assert r["route"] == "track1_candidate", r["label"]
        assert "live_positions.json" not in a, r["label"]


def test_legacy_safety_still_watches_legacys_book(fired):
    theirs = [r for r in fired if not r["label"].startswith(("TRACK1_STOP", "TRACK1_MAX"))]
    assert theirs, "the legacy safety jobs did not fire — the drain is unprotected"
    for r in theirs:
        a = r["args"]
        assert _flag(a, "--positions-path") == "live_positions.json", r["label"]
        assert "live_positions.track1.json" not in a, r["label"]


def test_the_two_routes_share_no_lock_and_no_client_id(fired):
    """In track1-only mode both safety sets fire on the same minutes. A shared lock would
    make one skip; a shared client id would reproduce the 2026-08-13 double-dial."""
    locks, ids = {}, {}
    for r in fired:
        route = "track1" if r["label"].startswith("TRACK1_") else "legacy"
        locks.setdefault(route, set()).add(_flag(r["args"], "--lock-path") or "runner.pid")
        ids.setdefault(route, set()).add(_flag(r["args"], "--client-id") or "1")
    assert locks["track1"] == {"runner.track1.pid"}
    assert not (locks["track1"] & locks["legacy"]), locks
    assert ids["track1"] == {"90"}
    assert not (ids["track1"] & ids["legacy"]), ids
    assert "89" not in ids["track1"], "safety must not share the data slots' client id either"


def test_no_safety_job_carries_an_order_or_replay_flag(fired):
    for r in fired:
        for nope in ("--allow-orders", "--window"):
            assert nope not in r["args"], (r["label"], nope)


def test_the_paths_match_the_entry_points_own_constants():
    """Two declarations of the Track 1 paths exist — the entry point's and the safety
    table's. They must be the same strings or the safety net watches a book nobody writes."""
    import global_index.run_live_day_track1 as entry
    assert ts.TRACK1_POSITIONS_PATH == entry.POSITIONS_PATH
    assert ts.TRACK1_STOP_PATH == entry.STOP_FILE


# ══════════════════════════════════════════════════════════════════════════════
# 3. the max-hold marker: two files, neither suppresses the other
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def markers(tmp_path, monkeypatch):
    """Both marker files redirected into tmp_path; both dicts cleared before and after."""
    from global_index import run_scheduler as rs
    monkeypatch.setattr(rs, "_MAXHOLD_STATE", tmp_path / "maxhold_state.json")
    monkeypatch.setattr(rs, "_MAXHOLD_STATE_T1", tmp_path / "maxhold_state.track1.json")
    rs._maxhold_done.clear()
    rs._maxhold_done_t1.clear()
    yield rs, tmp_path
    rs._maxhold_done.clear()
    rs._maxhold_done_t1.clear()


def test_the_track1_maxhold_records_into_its_own_file(markers):
    rs, tmp = markers
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append(label) or True)
        sched = rs.make_scheduler(port=4002, dry_run=False, track1_only=True)
        jobs = {j.id: j for j in sched.get_jobs()}
        jobs["track1_maxhold_exit"].func()
    finally:
        rs._run = orig
        logging.disable(lvl)
    t1 = tmp / "maxhold_state.track1.json"
    assert t1.exists(), "the Track 1 run recorded nothing"
    assert all(v is True for v in json.loads(t1.read_text(encoding="utf-8")).values())
    legacy = tmp / "maxhold_state.json"
    assert not legacy.exists() or json.loads(legacy.read_text(encoding="utf-8")) == {}, (
        "the Track 1 run wrote into LEGACY's marker file")


def test_legacy_marker_does_not_suppress_the_track1_catchup(markers, monkeypatch):
    """The exact silent failure the shared file would have caused: legacy already ran today,
    so a restarted scheduler skips the Track 1 catch-up and a five-day Track 1 position
    stays open. The legacy marker must be invisible to the Track 1 check."""
    rs, _tmp = markers
    today = rs._et_today().isoformat()
    rs._maxhold_done[today] = True            # legacy ran
    fired = []
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_only=True)
        job = sched.get_job("track1_maxhold_exit")
        monkeypatch.setattr(job, "func", lambda label=None: fired.append(label) or True)
        import datetime as dt
        import zoneinfo

        class _Now(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                base = dt.datetime.strptime(f"{today} 10:00", "%Y-%m-%d %H:%M")
                if base.weekday() >= 5:       # a weekend "today" would early-return
                    base -= dt.timedelta(days=base.weekday() - 4)
                return base.replace(tzinfo=tz) if tz else base

        import global_index.run_scheduler as rs2
        monkeypatch.setattr("global_index.run_scheduler._dt_for_test", _Now, raising=False)
        # _catch_up_maxhold_track1 imports datetime locally; patch the module it reads
        real_dt = dt.datetime
        monkeypatch.setattr(dt, "datetime", _Now)
        try:
            rs._catch_up_maxhold_track1(sched)
        finally:
            monkeypatch.setattr(dt, "datetime", real_dt)
    finally:
        logging.disable(lvl)
    assert fired, ("the legacy marker suppressed the Track 1 catch-up — the shared-marker "
                   "failure is back")


def test_the_track1_marker_does_suppress_its_own_catchup(markers, monkeypatch):
    """The marker must still do its own job, or every restart re-runs the exit."""
    rs, _tmp = markers
    today = rs._et_today().isoformat()
    rs._maxhold_done_t1[today] = True
    fired = []
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_only=True)
        job = sched.get_job("track1_maxhold_exit")
        monkeypatch.setattr(job, "func", lambda label=None: fired.append(label) or True)
        import datetime as dt

        class _Now(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                base = dt.datetime.strptime(f"{today} 10:00", "%Y-%m-%d %H:%M")
                if base.weekday() >= 5:
                    base -= dt.timedelta(days=base.weekday() - 4)
                return base.replace(tzinfo=tz) if tz else base

        real_dt = dt.datetime
        monkeypatch.setattr(dt, "datetime", _Now)
        try:
            rs._catch_up_maxhold_track1(sched)
        finally:
            monkeypatch.setattr(dt, "datetime", real_dt)
    finally:
        logging.disable(lvl)
    assert fired == [], "the Track 1 marker did not suppress its own catch-up"


def test_the_catchup_is_absent_outside_track1_only(markers):
    """No job, no catch-up — and no error either."""
    rs, _tmp = markers
    sched = _sched(track1_shadow=True)
    rs._catch_up_maxhold_track1(sched)        # must simply return


def test_the_real_marker_files_were_never_touched():
    legacy = Path("global_index/maxhold_state.json")
    assert legacy.exists(), "precondition: the legacy marker exists on this machine"
    _assert_not_written_by_this_run("global_index/maxhold_state.track1.json")
    _assert_not_written_by_this_run("global_index/maxhold_state.json")


# ══════════════════════════════════════════════════════════════════════════════
# 4. legacy-removability, extended to the safety net
# ══════════════════════════════════════════════════════════════════════════════

class _block_legacy:
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


def test_track1_safety_builds_and_fires_with_legacy_deleted():
    with _block_legacy():
        rows = _fire_safety(track1_only=True)
        mine = [r for r in rows if r["label"].startswith("TRACK1_")]
        assert len(mine) == 11
        for r in mine:
            assert _flag(r["args"], "--positions-path") == "live_positions.track1.json"


def test_the_import_block_still_blocks():
    with _block_legacy():
        with pytest.raises(ImportError):
            importlib.import_module("global_index.run_live_day")


def test_no_legacy_strategy_job_in_track1_only():
    ids = {j.id for j in _sched(track1_only=True).get_jobs()}
    assert not [i for i in ids if i.startswith(("live_day", "nkd_night"))], sorted(ids)


def test_safety_targets_run_their_own_modules_not_the_legacy_entrypoint(fired):
    """The safety jobs spawn run_stop_repair / run_maxhold_exit — never run_live_day."""
    for r in fired:
        mods = [r["args"][i + 1] for i, x in enumerate(r["args"]) if x == "-m"]
        assert mods and mods[0] in ("global_index.run_stop_repair",
                                    "global_index.run_maxhold_exit"), (r["label"], mods)
        assert "global_index.run_live_day" not in mods


# ══════════════════════════════════════════════════════════════════════════════
# 5. dashboard, ops, counts
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kw", [{}, {"track1_shadow": True}, {"track1_only": True}])
def test_parity_in_all_three_modes(kw):
    r = ts.parity_report(**kw)
    assert r["in_parity"], r


def test_the_mirror_carries_the_safety_rows_in_track1_only(monkeypatch):
    import datetime as dt
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    from monitor.backend import schedule_status as ss
    importlib.reload(ss)
    try:
        weekday = {s["id"] for s in ss._scheduled_slots_for(dt.date(2026, 8, 24))}
        want = {sj.id.upper() for sj in ts.track1_safety_jobs() if sj.day_of_week != "sun"}
        assert want <= weekday, sorted(want - weekday)
        sunday = {s["id"] for s in ss._scheduled_slots_for(dt.date(2026, 8, 30))}
        assert "TRACK1_STOP_REPAIR_SUN_1830" in sunday
    finally:
        monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
        importlib.reload(ss)


def test_ops_status_names_the_active_safety_routes(monkeypatch):
    from monitor import ops
    monkeypatch.setattr(ops, "scheduler_processes",
                        lambda: [{"pid": 1, "CommandLine":
                                  "pythonw -m global_index.run_scheduler "
                                  "--track1-only-shadow"}])
    t = ops.track1_status()
    assert t["scheduler_track1_only"] is True
    assert t["safety_routes"] == ["legacy", "track1"]
    monkeypatch.setattr(ops, "scheduler_processes",
                        lambda: [{"pid": 1, "CommandLine":
                                  "pythonw -m global_index.run_scheduler --shadow-resume"}])
    t = ops.track1_status()
    assert t["safety_routes"] == ["legacy"]


def test_no_hardcoded_job_count_in_the_new_wiring():
    """The registration loop and the mirror both read `track1_safety_jobs()`; neither may
    carry its own count."""
    src = Path("global_index/run_scheduler.py").read_text(encoding="utf-8")
    block = src[src.index("Stage 5O: Track 1's own safety net"):]
    block = block[:block.index("return sched")]
    assert not re.search(r"\brange\(11\)|== 11\b", block)
    assert "track1_safety_jobs()" in block


def test_no_switch_or_state_file_was_created():
    for name in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
                 "runner.track1.pid"):
        assert not Path(name).exists(), name
    # The max-hold marker is the route's own safety job doing its job every trading day, so
    # its ABSENCE is no longer the right question — see `_assert_not_written_by_this_run`.
    #
    # Stage 5ZJ: `live_positions.track1.json` moved here for the same measured reason, and
    # it is this suite's own subject. `track1_bootstrap.write` produces the route BOOK in the
    # same call as the checkpoint, and the 15:55 ET close of a complete Swing window is when
    # it runs — it first appeared 2026-08-25 at 15:56:19 ET holding zero positions. Once the
    # route's windows complete, the book exists every trading day, and asserting its absence
    # forbids the running system from doing exactly what Stage 5O built the safety net to
    # watch. The same repair was applied to Stage 5P on 2026-08-25.
    for name in ("global_index/maxhold_state.track1.json", "live_positions.track1.json"):
        _assert_not_written_by_this_run(name)
