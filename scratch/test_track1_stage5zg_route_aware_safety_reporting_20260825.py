"""Stage 5ZG — a Track 1 safety exit can no longer be recorded as a legacy close.

No scheduler started, no IBKR, no orders, no confirmation file, no switch file. Every
path either of these entry points is pointed at here lives under `tmp_path`; the argv
checks replace the subprocess runner so nothing executes, and the two `main()` tests
replace both the broker class and `FuturesRunner` before either is constructed.

What this stage closes
----------------------
Stage 5ZF's first-of-six finding. `run_stop_repair` and `run_maxhold_exit` both did:

    trade_log_path=str(_CWD / "trade_log.jsonl")

with no way to say otherwise, while the scheduler handed their Track 1 copies
`--positions-path live_positions.track1.json`. The first Track 1 fill either job ever
closed would have written a CLOSE row into legacy's log, in legacy's shape, carrying
nothing that said which route produced it — and `paper_evidence_reader` aggregates that
file whole, so the row would have entered legacy's fill-quality and P&L gates.

After 5ZG:

    no argument         -> trade_log.jsonl, byte for byte what it was
    --trade-log-path P  -> P, proven writable before the job does anything else
    --route R           -> every row carries route=R; refused without a path
    track1-only         -> the eleven Track 1 safety jobs pass both, from one constant

The two layers are tested separately and then composed: which destination the SCRIPT
chooses (Part C), and what the runner's real writer DOES with that destination (Part D).
Neither on its own is the claim.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import safety_trade_log as stl   # noqa: E402
from global_index import track1_slots as ts        # noqa: E402
from global_index.runner import FuturesRunner      # noqa: E402

REPO = Path(r"d:\raits")

#: Import time, i.e. before any test here ran. Used instead of asserting absence — the
#: production Track 1 trade log will legitimately be created by the first real sweep the
#: scheduler runs, and absence would then start failing for the right reason at the wrong
#: time. "Older than this process" says what is actually being guarded: no test wrote it.
_IMPORTED_AT = time.time()

#: Every production artefact this stage could plausibly touch.
_PRODUCTION_FILES = (
    "trade_log.jsonl",
    ts.TRACK1_TRADE_LOG_PATH,
    ts.TRACK1_POSITIONS_PATH,
    "live_positions.json",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SWING_PROVIDER", "RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY",
              "TRACK1_ORDERS_APPROVED"):
        monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# harness
# ══════════════════════════════════════════════════════════════════════════════

def _fire_safety(**kw):
    """Fire every safety job closure with the subprocess runner replaced."""
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5zg")
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args), "route": route}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, **kw)
        jobs = sched.get_jobs()
        for j in jobs:
            if j.id.startswith(("stop_repair", "maxhold_exit",
                                "track1_stop_repair", "track1_maxhold")):
                j.func()
    finally:
        rs._run = orig
        rs._maxhold_done.clear()
        rs._maxhold_done_t1.clear()
        logging.disable(lvl)
    assert seen, "no safety job fired — nothing was captured, so nothing below is a check"
    return seen, jobs


def _flag(args, name):
    return args[args.index(name) + 1] if name in args else None


def _t1(seen):
    rows = [s for s in seen if s["label"].startswith("TRACK1")]
    assert rows, "no Track 1 safety job fired"
    return rows


def _legacy(seen):
    rows = [s for s in seen if not s["label"].startswith("TRACK1")]
    assert rows, "no legacy safety job fired"
    return rows


class _FakeBroker:
    """Stands in for IBKRBroker. Nothing here can reach a socket or place an order."""

    def __init__(self, *a, **kw):
        self.calls = []

    def connect(self):
        self.calls.append("connect")

    def disconnect(self):
        self.calls.append("disconnect")

    def unprotected_positions(self):
        return []


class _RunnerSpy:
    """Captures the kwargs the script chose. Constructing it places nothing."""

    seen: list = []

    def __init__(self, **kw):
        type(self).seen.append(kw)
        self.state = type("S", (), {"open_positions": []})()
        self._b4_naked_stops = []

    def run_maxhold_exit(self, *a, **kw):     # pragma: no cover - never reached here
        raise AssertionError("a test reached the real exit path")


def _run_entry_point(mod_name, argv, monkeypatch, tmp_path):
    """Call the entry point's main() with the broker and the runner replaced.

    `_CWD` is repointed at tmp_path so a relative --trade-log-path resolves there and no
    production file is in reach. The lock is disabled with an empty --lock-path (the
    scripts treat it as falsy) so nothing registers an atexit release on a temp file.
    """
    import importlib
    mod = importlib.import_module(mod_name)
    monkeypatch.setattr(mod, "_CWD", tmp_path)
    monkeypatch.setattr(mod, "IBKRBroker", _FakeBroker)
    monkeypatch.setattr(mod, "FuturesRunner", _RunnerSpy)
    monkeypatch.setattr(mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(sys, "argv", [mod_name] + list(argv))
    _RunnerSpy.seen = []
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.ERROR - 1)   # keep ERROR visible, silence INFO/WARNING
    try:
        rc = mod.main()
    finally:
        logging.disable(lvl)
    return rc, list(_RunnerSpy.seen)


@pytest.fixture
def book(tmp_path):
    """A positions file that exists, so neither script takes its early return."""
    p = tmp_path / "book.json"
    p.write_text(json.dumps({"open_positions": [], "peak_equity": 0}), encoding="utf-8")
    return p


def _writer(dest, route):
    """The runner's REAL trade-row writer, bound to nothing else.

    `object.__new__` rather than a full FuturesRunner: constructing one runs B3 and B4,
    which is the part of the class this stage must not touch. The function under test is
    the one every close in the system goes through, not a copy of it.
    """
    obj = object.__new__(FuturesRunner)
    obj._trade_log_path = Path(dest)
    obj._trade_log_route = route
    return obj


# ══════════════════════════════════════════════════════════════════════════════
# A. the contract in isolation
# ══════════════════════════════════════════════════════════════════════════════

def test_no_argument_is_the_legacy_log(tmp_path):
    dest, route = stl.resolve(None, None, tmp_path)
    assert dest == tmp_path / "trade_log.jsonl"
    assert route is None


def test_the_default_path_is_not_probed_and_not_created(tmp_path):
    """Legacy behaviour is byte-for-byte: no mkdir, no touch, no refusal."""
    dest, _ = stl.resolve(None, None, tmp_path)
    assert not dest.exists(), "resolving the default created legacy's log — it never did"


def test_a_route_without_a_destination_is_refused(tmp_path):
    with pytest.raises(stl.TradeLogRefused) as exc:
        stl.resolve(None, ts.EVENT_ROUTE_VALUE, tmp_path)
    assert ts.EVENT_ROUTE_VALUE in str(exc.value)


def test_a_relative_destination_resolves_against_the_repo_root_not_the_process_cwd(tmp_path):
    dest, _ = stl.resolve("global_index/track1_runtime/t.jsonl", None, tmp_path)
    assert dest == tmp_path / "global_index" / "track1_runtime" / "t.jsonl"


def test_an_absolute_destination_is_taken_as_given(tmp_path):
    want = tmp_path / "elsewhere" / "t.jsonl"
    dest, _ = stl.resolve(str(want), None, tmp_path)
    assert dest == want


def test_the_probe_creates_the_file_so_never_ran_and_ran_empty_differ(tmp_path):
    dest, _ = stl.resolve("a/b/t.jsonl", None, tmp_path)
    assert dest.exists() and dest.stat().st_size == 0


def test_an_unwritable_destination_is_refused_not_silently_redirected(tmp_path):
    (tmp_path / "blocker").write_text("i am a file, not a directory", encoding="utf-8")
    with pytest.raises(stl.TradeLogRefused) as exc:
        stl.resolve("blocker/t.jsonl", ts.EVENT_ROUTE_VALUE, tmp_path)
    assert "trade_log.jsonl" in str(exc.value), (
        "the refusal must name what it is refusing to fall back to")
    assert not (tmp_path / "trade_log.jsonl").exists()


def test_the_probe_does_not_truncate_an_existing_log(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text('{"type":"CLOSE"}\n', encoding="utf-8")
    stl.resolve("t.jsonl", None, tmp_path)
    assert p.read_text(encoding="utf-8") == '{"type":"CLOSE"}\n', "append-open truncated"


# ══════════════════════════════════════════════════════════════════════════════
# B. the path itself
# ══════════════════════════════════════════════════════════════════════════════

def test_the_track1_log_is_a_separate_file_under_the_track1_runtime_root():
    p = ts.TRACK1_TRADE_LOG_PATH
    assert p != "trade_log.jsonl"
    assert Path(p).name != Path(stl.DEFAULT_TRADE_LOG).name
    assert p.startswith("global_index/track1_runtime/")


def test_the_documented_policy_names_the_real_path_and_the_real_tag():
    pol = ts.PAPER_OUTPUT_POLICY["trade_log"]
    assert ts.TRACK1_TRADE_LOG_PATH in pol
    assert f"{ts.EVENT_ROUTE_FIELD}={ts.EVENT_ROUTE_VALUE}" in pol


def test_the_route_tag_is_the_same_value_every_other_track1_artefact_carries():
    from global_index.track1_params import ROUTE
    assert ts.EVENT_ROUTE_VALUE == ROUTE == "track1_candidate"


# ══════════════════════════════════════════════════════════════════════════════
# C. what the scheduler passes, per mode
# ══════════════════════════════════════════════════════════════════════════════

def test_track1_stop_repair_argv_carries_the_book_the_log_the_lock_and_the_id():
    seen, _ = _fire_safety(track1_only=True)
    rows = [r for r in _t1(seen) if "run_stop_repair" in " ".join(r["args"])]
    assert rows, "no Track 1 stop-repair job fired"
    for r in rows:
        a = r["args"]
        assert _flag(a, "--positions-path") == ts.TRACK1_POSITIONS_PATH
        assert _flag(a, "--trade-log-path") == ts.TRACK1_TRADE_LOG_PATH
        assert _flag(a, "--route") == ts.EVENT_ROUTE_VALUE
        assert _flag(a, "--lock-path") == ts.TRACK1_LOCK_PATH
        assert _flag(a, "--client-id") == str(ts.TRACK1_SAFETY_CLIENT_ID)
        assert _flag(a, "--stop-path") == ts.TRACK1_STOP_PATH


def test_track1_maxhold_argv_carries_the_book_the_log_and_its_own_marker():
    from global_index import run_scheduler as rs
    seen, _ = _fire_safety(track1_only=True)
    rows = [r for r in _t1(seen) if "run_maxhold_exit" in " ".join(r["args"])]
    assert rows, "no Track 1 max-hold job fired"
    for r in rows:
        a = r["args"]
        assert _flag(a, "--positions-path") == ts.TRACK1_POSITIONS_PATH
        assert _flag(a, "--trade-log-path") == ts.TRACK1_TRADE_LOG_PATH
        assert _flag(a, "--route") == ts.EVENT_ROUTE_VALUE
        assert _flag(a, "--lock-path") == ts.TRACK1_LOCK_PATH
        assert _flag(a, "--client-id") == str(ts.TRACK1_SAFETY_CLIENT_ID)
    # unchanged by this stage, and the reason the two routes cannot suppress each other
    assert rs._MAXHOLD_STATE_T1 == Path(ts.TRACK1_MAXHOLD_STATE)
    assert rs._MAXHOLD_STATE != rs._MAXHOLD_STATE_T1


def test_the_legacy_drain_safety_never_touches_the_track1_log():
    seen, _ = _fire_safety(track1_only=True)
    for r in _legacy(seen):
        a = r["args"]
        assert _flag(a, "--positions-path") == "live_positions.json"
        assert "--trade-log-path" not in a, (
            f"{r['label']} was given a destination it never had")
        assert "--route" not in a
        assert ts.TRACK1_TRADE_LOG_PATH not in a


@pytest.mark.parametrize("kw", [{}, {"track1_shadow": True}])
def test_the_other_two_modes_pass_no_destination_at_all(kw):
    seen, _ = _fire_safety(**kw)
    assert not [r for r in seen if r["label"].startswith("TRACK1")], (
        "Track 1 safety is registered outside track1-only mode")
    for r in seen:
        assert "--trade-log-path" not in r["args"]
        assert "--route" not in r["args"]


def test_the_scheduler_reads_the_constant_rather_than_repeating_the_path():
    """Change the constant, and the argv must change with it."""
    original = ts.TRACK1_TRADE_LOG_PATH
    try:
        ts.TRACK1_TRADE_LOG_PATH = "global_index/track1_runtime/moved.jsonl"
        seen, _ = _fire_safety(track1_only=True)
        vals = {_flag(r["args"], "--trade-log-path") for r in _t1(seen)}
        assert vals == {"global_index/track1_runtime/moved.jsonl"}, (
            f"the path is hardcoded somewhere in the wiring: {vals}")
    finally:
        ts.TRACK1_TRADE_LOG_PATH = original


def test_the_job_inventory_did_not_move():
    counts = {}
    for kw, name in (({}, "default"), ({"track1_shadow": True}, "transitional"),
                     ({"track1_only": True}, "track1_only")):
        _, jobs = _fire_safety(**kw)
        counts[name] = len(jobs)
    assert counts["track1_only"] == 101, counts
    assert counts["default"] < counts["track1_only"] < counts["transitional"], counts


# ══════════════════════════════════════════════════════════════════════════════
# D. what the entry points DO with it
# ══════════════════════════════════════════════════════════════════════════════

def test_stop_repair_with_no_argument_still_targets_the_legacy_log(monkeypatch, tmp_path, book):
    rc, seen = _run_entry_point(
        "global_index.run_stop_repair",
        ["--positions-path", str(book), "--lock-path", ""],
        monkeypatch, tmp_path)
    assert rc == 0
    assert len(seen) == 1, "the runner was not constructed — nothing was measured"
    assert Path(seen[0]["trade_log_path"]) == tmp_path / "trade_log.jsonl"
    assert seen[0]["route"] is None


def test_maxhold_with_no_argument_still_targets_the_legacy_log(monkeypatch, tmp_path, book):
    rc, seen = _run_entry_point(
        "global_index.run_maxhold_exit",
        ["--positions-path", str(book), "--lock-path", "", "--dry-run"],
        monkeypatch, tmp_path)
    assert rc in (None, 0)
    assert len(seen) == 1, "the runner was not constructed — nothing was measured"
    assert Path(seen[0]["trade_log_path"]) == tmp_path / "trade_log.jsonl"
    assert seen[0]["route"] is None


@pytest.mark.parametrize("mod,extra", [
    ("global_index.run_stop_repair", []),
    ("global_index.run_maxhold_exit", ["--dry-run"]),
])
def test_both_entry_points_honour_the_track1_destination_and_tag(mod, extra,
                                                                 monkeypatch, tmp_path, book):
    rc, seen = _run_entry_point(
        mod,
        ["--positions-path", str(book), "--lock-path", "",
         "--trade-log-path", ts.TRACK1_TRADE_LOG_PATH,
         "--route", ts.EVENT_ROUTE_VALUE] + extra,
        monkeypatch, tmp_path)
    assert rc in (None, 0)
    assert len(seen) == 1
    assert Path(seen[0]["trade_log_path"]) == tmp_path / Path(ts.TRACK1_TRADE_LOG_PATH)
    assert seen[0]["route"] == ts.EVENT_ROUTE_VALUE
    assert not (tmp_path / "trade_log.jsonl").exists()


@pytest.mark.parametrize("mod,extra", [
    ("global_index.run_stop_repair", []),
    ("global_index.run_maxhold_exit", ["--dry-run"]),
])
def test_an_unwritable_destination_fails_the_job_before_it_connects(mod, extra,
                                                                    monkeypatch, tmp_path, book):
    (tmp_path / "blocker").write_text("file where a directory is needed", encoding="utf-8")
    rc, seen = _run_entry_point(
        mod,
        ["--positions-path", str(book), "--lock-path", "",
         "--trade-log-path", "blocker/t.jsonl",
         "--route", ts.EVENT_ROUTE_VALUE] + extra,
        monkeypatch, tmp_path)
    assert rc == 1, "the job did not fail — the scheduler would read this as completed OK"
    assert seen == [], "the runner was constructed anyway"
    assert not (tmp_path / "trade_log.jsonl").exists(), "it fell back to the legacy log"


@pytest.mark.parametrize("mod,extra", [
    ("global_index.run_stop_repair", []),
    ("global_index.run_maxhold_exit", ["--dry-run"]),
])
def test_a_route_without_a_destination_fails_the_job(mod, extra, monkeypatch, tmp_path, book):
    rc, seen = _run_entry_point(
        mod,
        ["--positions-path", str(book), "--lock-path", "",
         "--route", ts.EVENT_ROUTE_VALUE] + extra,
        monkeypatch, tmp_path)
    assert rc == 1
    assert seen == []
    assert not (tmp_path / "trade_log.jsonl").exists()


def test_the_check_runs_before_the_positions_file_is_even_looked_at(monkeypatch, tmp_path):
    """Through the whole shadow period there is no Track 1 book, so a check placed after
    the early return would never execute and a wrong path would surface at the first fill."""
    (tmp_path / "blocker").write_text("x", encoding="utf-8")
    rc, seen = _run_entry_point(
        "global_index.run_stop_repair",
        ["--positions-path", str(tmp_path / "does_not_exist.json"), "--lock-path", "",
         "--trade-log-path", "blocker/t.jsonl", "--route", ts.EVENT_ROUTE_VALUE],
        monkeypatch, tmp_path)
    assert rc == 1, "a missing book hid a broken destination"
    assert seen == []


# ══════════════════════════════════════════════════════════════════════════════
# E. the writer: destination chosen (C) + row written (here) = the claim
# ══════════════════════════════════════════════════════════════════════════════

def test_a_simulated_track1_stop_repair_close_lands_in_the_track1_log(monkeypatch, tmp_path, book):
    """The destination comes from the script, the write from the runner's real writer."""
    _, seen = _run_entry_point(
        "global_index.run_stop_repair",
        ["--positions-path", str(book), "--lock-path", "",
         "--trade-log-path", ts.TRACK1_TRADE_LOG_PATH,
         "--route", ts.EVENT_ROUTE_VALUE],
        monkeypatch, tmp_path)
    assert len(seen) == 1
    w = _writer(seen[0]["trade_log_path"], seen[0]["route"])
    w._append_trade({"type": "CLOSE", "inst": "MES", "cluster": "roska4_swing",
                     "exit_reason": "STOP_FILLED", "fill_price": 5000.0})

    t1_log = tmp_path / Path(ts.TRACK1_TRADE_LOG_PATH)
    rows = [json.loads(l) for l in t1_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["route"] == ts.EVENT_ROUTE_VALUE
    assert rows[0]["exit_reason"] == "STOP_FILLED"
    assert not (tmp_path / "trade_log.jsonl").exists(), "a legacy log was created"


def test_a_simulated_track1_maxhold_close_lands_in_the_track1_log(monkeypatch, tmp_path, book):
    _, seen = _run_entry_point(
        "global_index.run_maxhold_exit",
        ["--positions-path", str(book), "--lock-path", "", "--dry-run",
         "--trade-log-path", ts.TRACK1_TRADE_LOG_PATH,
         "--route", ts.EVENT_ROUTE_VALUE],
        monkeypatch, tmp_path)
    assert len(seen) == 1
    w = _writer(seen[0]["trade_log_path"], seen[0]["route"])
    w._append_trade({"type": "CLOSE", "inst": "MNQ", "cluster": "roska4_swing",
                     "exit_reason": "MAX_HOLD", "fill_price": 21000.0})

    t1_log = tmp_path / Path(ts.TRACK1_TRADE_LOG_PATH)
    rows = [json.loads(l) for l in t1_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["route"] == ts.EVENT_ROUTE_VALUE
    assert rows[0]["exit_reason"] == "MAX_HOLD"
    assert not (tmp_path / "trade_log.jsonl").exists()


def test_a_legacy_row_gains_no_route_key_at_all(tmp_path):
    legacy = tmp_path / "trade_log.jsonl"
    w = _writer(legacy, None)
    w._append_trade({"type": "CLOSE", "inst": "MES", "cluster": "roska4_swing",
                     "exit_reason": "MAX_HOLD", "fill_price": 5000.0})
    row = json.loads(legacy.read_text(encoding="utf-8").splitlines()[0])
    assert "route" not in row, "legacy rows changed shape"


def test_the_close_schema_is_unchanged_apart_from_the_tag(tmp_path):
    """The tag is additive: same keys as before, plus one, and only when asked."""
    a, b = tmp_path / "legacy.jsonl", tmp_path / "t1.jsonl"
    rec = {"type": "CLOSE", "inst": "MES", "cluster": "roska4_swing", "fill_price": 1.0}
    _writer(a, None)._append_trade(dict(rec))
    _writer(b, ts.EVENT_ROUTE_VALUE)._append_trade(dict(rec))
    ka = set(json.loads(a.read_text(encoding="utf-8").splitlines()[0]))
    kb = set(json.loads(b.read_text(encoding="utf-8").splitlines()[0]))
    assert kb - ka == {"route"}, kb - ka
    assert ka - kb == set()


def test_open_rows_are_tagged_too(tmp_path):
    """An OPEN row that cannot say which route opened it is the same defect one step earlier."""
    p = tmp_path / "t1.jsonl"
    _writer(p, ts.EVENT_ROUTE_VALUE)._append_trade({"type": "OPEN", "inst": "MES"})
    assert json.loads(p.read_text(encoding="utf-8").splitlines()[0])["route"] == \
        ts.EVENT_ROUTE_VALUE


def test_a_row_that_already_names_its_route_is_not_overruled(tmp_path):
    p = tmp_path / "t1.jsonl"
    _writer(p, ts.EVENT_ROUTE_VALUE)._append_trade({"type": "CLOSE", "route": "someone_else"})
    assert json.loads(p.read_text(encoding="utf-8").splitlines()[0])["route"] == "someone_else"


def test_the_runners_route_defaults_to_none_for_every_existing_caller():
    import inspect
    sig = inspect.signature(FuturesRunner.__init__)
    assert sig.parameters["route"].default is None
    # last in the signature: a positional caller written before this stage cannot land on it
    assert list(sig.parameters)[-1] == "route"


# ══════════════════════════════════════════════════════════════════════════════
# F. nothing in production was written
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name", _PRODUCTION_FILES)
def test_no_production_file_was_written_by_this_run(name):
    p = REPO / name
    if not p.exists():
        return
    assert p.stat().st_mtime < _IMPORTED_AT, (
        f"{name} was written DURING this test run — everything here runs under tmp_path")


def test_the_production_track1_log_was_not_created_by_the_tests():
    p = REPO / ts.TRACK1_TRADE_LOG_PATH
    if p.exists():
        assert p.stat().st_mtime < _IMPORTED_AT
        return
    assert True   # absent is fine; the first real sweep will create it


def test_no_order_switch_or_confirmation_file_appeared():
    # Stage 5ZZZ-A. The confirmation file leaves this list, for the reason Stage 5ZZS restated
    # it in four other suites and Stage 5ZZW in two more: the operator signed it deliberately on
    # 2026-08-27, and asserting its absence asserts that nobody decided anything.
    #
    # What still must not exist is anything that would ARM an order — the approval marker and
    # the order journal — and if a decision IS on disk it has to be a signed one, because an
    # unsigned file appearing here would be something a run had dropped.
    for name in ("TRACK1_ORDERS_APPROVED", "global_index/track1_runtime/orders"):
        assert not (REPO / name).exists(), f"{name} exists — orders must remain impossible"
    _conf = REPO / "track1_go_live_confirmation.json"
    if _conf.exists():
        import json as _json
        _d = _json.loads(_conf.read_text(encoding="utf-8"))
        assert (_d.get("confirmed_by") or "").strip(), "an unsigned decision appeared on disk"
    assert os.environ.get("TRACK1_ORDERS_APPROVED") is None
