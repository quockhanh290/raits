"""Stage 5P — full four-sleeve shadow readiness, and the dashboard reads Track 1's own runtime.

No scheduler started, no real IBKR, no orders, no switch files, no live state written. The
synthetic shadow day is built entirely under `tmp_path`; the argv probes replace the
subprocess runner so nothing executes.

Two subjects
------------
**The acceptance gate.** `track1_shadow_acceptance.evaluate_day` is the judge a shadow day
will be graded by, committed BEFORE any shadow day exists so its thresholds cannot drift
toward whatever the first day produces. The tests here build one fully-green synthetic day
and then degrade it one dimension at a time, requiring a NAMED failure each time — a gate
that can only say yes is not a gate.

**The dashboard cutover.** Until this stage the dashboard had no Track 1 reader at all; its
positions endpoint serves legacy's book. The new reader reads Track 1 paths ONLY — asserted
by parsing its source — and the legacy endpoint now labels itself as the legacy route.
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

from global_index import track1_shadow_acceptance as acc   # noqa: E402
from global_index import track1_slots as ts                # noqa: E402
from global_index.track1_params import WINDOWS_ET          # noqa: E402
from monitor.backend import track1_runtime_reader as trr   # noqa: E402

DAY = "2026-08-20"
DAYC = DAY.replace("-", "")
LEGACY_MODULES = ("global_index.run_live_day",)


#: Module import time — before any test here ran. See the marker check below.
_IMPORTED_AT = __import__("time").time()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SWING_PROVIDER", "RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY",
              "RAITS_WINDOW_LEDGER_DIR", "RAITS_TELEMETRY_DIR"):
        monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# the synthetic full shadow day
# ══════════════════════════════════════════════════════════════════════════════

def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def build_green_day(root: Path, *, day: str = DAY) -> None:
    """One shadow day that passes every required check. Everything under `root`."""
    dayc = day.replace("-", "")
    # ledger: window_open, one slot_observed per registered slot, window_closed complete
    ledger_rows: list = []
    for sleeve, slots in _slots_by_sleeve().items():
        ledger_rows.append({"event": "window_open", "sleeve": sleeve, "date": day,
                            "route": "track1_candidate"})
        for s in slots:
            ledger_rows.append({"event": "slot_observed", "sleeve": sleeve, "date": day,
                                "slot_id": s.id, "decided": True,
                                "route": "track1_candidate"})
        ledger_rows.append({"event": "window_closed", "sleeve": sleeve, "date": day,
                            "outcome": "complete", "signal": "no_signal",
                            "observed_slots": len(slots), "expected_slots": len(slots),
                            "route": "track1_candidate"})
    _write_jsonl(root / acc.COVERAGE_DIR / f"window_coverage_{dayc}.jsonl", ledger_rows)

    # telemetry: one record per slot, runtimes well under target
    trows = [{"ts": f"{day}T15:00:00+00:00", "route": "track1_candidate", "slot_id": s.id,
              "outcome": "ok", "runtime_s": 45.0 + (i % 30), "phases": {}}
             for i, s in enumerate(ts.TRACK1_SLOTS)]
    _write_jsonl(root / acc.TIMING_DIR / f"slot_timing_{dayc}.jsonl", trows)

    # explanations: rows carrying a freshness proof
    erows = [{"trade_id": f"x{i}", "decision": "rejected", "sleeve": s.sleeve,
              "proofs": [{"name": "freshness_binding", "passed": True}]}
             for i, s in enumerate(ts.TRACK1_SLOTS[:5])]
    _write_jsonl(root / acc.SHADOW_DIR / "explanations" / f"explanations_{dayc}.jsonl", erows)

    # Stage 5ZH: through `route_checkpoint.save_route`, and with the companion book.
    # The literal that stood here invented a flat payload the writer has never produced and
    # `route_checkpoint.load` rejects outright; it agreed with the reader, not the writer,
    # and that is exactly why the reader's defect survived three suites.
    from global_index import route_checkpoint as _rc
    _rc.save_route({}, route="track1_candidate", path=str(root / acc.CHECKPOINT_PATH))
    _bk = root / acc.CHECKPOINT_BOOK_PATH
    _bk.parent.mkdir(parents=True, exist_ok=True)
    _bk.write_text(json.dumps({"schema_version": 2, "route": "track1_candidate",
                               "window": "live", "cut_instant": f"{day}T15:55:01-04:00",
                               "cur_day": day, "positions": []}), encoding="utf-8")


def _slots_by_sleeve() -> dict:
    out: dict = {}
    for s in ts.TRACK1_SLOTS:
        out.setdefault(s.sleeve, []).append(s)
    return out


@pytest.fixture
def green(tmp_path):
    build_green_day(tmp_path)
    return tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# 1. the acceptance gate
# ══════════════════════════════════════════════════════════════════════════════

def test_a_fully_green_day_is_accepted(green):
    v = acc.evaluate_day(DAY, root=green)
    assert v["accepted"], v["failed"]
    assert v["failed"] == []


def test_the_gate_judges_all_four_sleeves(green):
    v = acc.evaluate_day(DAY, root=green)
    judged = {c["name"] for c in v["checks"] if c["name"].startswith("coverage:")}
    assert judged == {f"coverage:{s}" for s in WINDOWS_ET}
    assert len(judged) == 4, "the gate is not judging four sleeves"


def test_expected_slot_counts_come_from_the_ledger_not_the_gate(green):
    """Calm 1, Stress 24, Normal-R4 23, NKD 22 — asserted here once, against the tables the
    gate reads, so this file is the place the numbers live for review."""
    import global_index.window_ledger as wl
    assert {s: wl.expected_slots(s) for s in WINDOWS_ET} == {
        "roska4_calm": 1, "roska4_stress": 24, "roska4_swing": 23, "global_nkd": 22}


def test_an_incomplete_sleeve_fails_by_name(green):
    """Coverage complete on three sleeves is not a shadow day; it is the pre-5N state."""
    f = green / acc.COVERAGE_DIR / f"window_coverage_{DAYC}.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if not (r.get("sleeve") == "global_nkd"
                                    and r.get("event") == "window_closed")]
    _write_jsonl(f, rows)
    v = acc.evaluate_day(DAY, root=green)
    assert not v["accepted"]
    assert "coverage:global_nkd" in v["failed"]


def test_a_missing_slot_row_fails_even_when_the_count_reads_complete(green):
    """The count check cannot see one slot silent and another counted twice; the id check
    can, and this is the case that proves they are different checks."""
    f = green / acc.COVERAGE_DIR / f"window_coverage_{DAYC}.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    out, dropped, doubled = [], False, False
    for r in rows:
        if (not dropped and r.get("event") == "slot_observed"
                and r.get("slot_id") == "TRACK1_STRESS_1100"):
            dropped = True
            continue
        out.append(r)
        if (not doubled and r.get("event") == "slot_observed"
                and r.get("slot_id") == "TRACK1_STRESS_1105"):
            out.append(dict(r))
            doubled = True
    _write_jsonl(f, out)
    v = acc.evaluate_day(DAY, root=green)
    assert "slot_gaps" in v["failed"], v["failed"]
    gap = next(c for c in v["checks"] if c["name"] == "slot_gaps")
    assert "TRACK1_STRESS_1100" in gap.get("missing", [])


def test_a_slow_p95_fails_and_a_missed_target_only_warns(green):
    f = green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        r["runtime_s"] = 250.0          # over the 240 target, under the 300 ceiling
    _write_jsonl(f, rows)
    v = acc.evaluate_day(DAY, root=green)
    assert v["accepted"], v["failed"]
    p95 = next(c for c in v["checks"] if c["name"] == "runtime_p95")
    assert p95["status"] == acc.WARN

    for r in rows:
        r["runtime_s"] = 310.0          # over the ceiling: slots overrun the cadence
    _write_jsonl(f, rows)
    v = acc.evaluate_day(DAY, root=green)
    assert not v["accepted"]
    assert "runtime_p95" in v["failed"] and "stalls" in v["failed"]


def test_a_single_stalled_slot_fails_even_with_a_healthy_p95(green):
    f = green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    rows[3]["runtime_s"] = 301.0
    _write_jsonl(f, rows)
    v = acc.evaluate_day(DAY, root=green)
    assert "stalls" in v["failed"]


def test_a_day_without_telemetry_cannot_be_judged_fast(green):
    """No timing evidence is a FAILURE, not a pass — a day nobody measured cannot be
    accepted as within budget."""
    (green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl").unlink()
    v = acc.evaluate_day(DAY, root=green)
    assert "runtime_p95" in v["failed"]


def test_an_order_mark_anywhere_fails_the_day(green):
    f = green / acc.TIMING_DIR / f"slot_timing_{DAYC}.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    rows[0]["order_submitted"] = True
    _write_jsonl(f, rows)
    v = acc.evaluate_day(DAY, root=green)
    assert "no_orders" in v["failed"]


def test_a_confirmation_file_fails_the_day(green):
    (green / acc.CONFIRMATION_PATH).write_text("{}", encoding="utf-8")
    v = acc.evaluate_day(DAY, root=green)
    assert "no_orders" in v["failed"]


def test_missing_freshness_proofs_fail(green):
    f = green / acc.SHADOW_DIR / "explanations" / f"explanations_{DAYC}.jsonl"
    rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        r.pop("proofs", None)
    _write_jsonl(f, rows)
    v = acc.evaluate_day(DAY, root=green)
    assert "freshness_proofs" in v["failed"]


def test_no_explanations_fails_twice(green):
    (green / acc.SHADOW_DIR / "explanations" / f"explanations_{DAYC}.jsonl").unlink()
    v = acc.evaluate_day(DAY, root=green)
    assert "explanations" in v["failed"] and "freshness_proofs" in v["failed"]


@pytest.mark.parametrize("break_it", ["foreign_route", "yesterdays_book", "no_book"])
def test_a_wrong_checkpoint_fails(green, break_it):
    """Stage 5ZH: these used to mutate top-level `route` / `cut_instant`, keys the writer
    has never produced. The three real ways this can be wrong are a file that does not hold
    this route, a companion book cut on another day, and no way to date it at all."""
    from global_index import route_checkpoint as _rc
    ck = green / acc.CHECKPOINT_PATH
    if break_it == "foreign_route":
        ck.unlink()
        _rc.save_route({}, route="legacy", path=str(ck))
    elif break_it == "yesterdays_book":
        (green / acc.CHECKPOINT_BOOK_PATH).write_text(
            json.dumps({"schema_version": 2, "route": "track1_candidate",
                        "cut_instant": "2026-08-19T15:55:01-04:00",
                        "cur_day": "2026-08-19", "positions": []}), encoding="utf-8")
    else:
        (green / acc.CHECKPOINT_BOOK_PATH).unlink()
    v = acc.evaluate_day(DAY, root=green)
    assert "checkpoint" in v["failed"]


def test_a_missing_checkpoint_fails(green):
    (green / acc.CHECKPOINT_PATH).unlink()
    v = acc.evaluate_day(DAY, root=green)
    assert "checkpoint" in v["failed"]


def test_identity_verification_is_named_as_not_checked(green):
    """The gate does not re-verify the params hashes and must SAY so, or a green day reads
    as having proven something it did not."""
    v = acc.evaluate_day(DAY, root=green)
    c = next(c for c in v["checks"] if c["name"] == "checkpoint_identity")
    assert c["status"] == acc.NOT_CHECKED
    assert v["accepted"], "NOT_CHECKED must not fail a day — it must only be visible"


def test_the_period_gate_requires_every_day(green):
    """One green day plus one day with no evidence at all: the period fails, and names the
    day. (The first version built the second day into the same tmp_path as the first —
    pytest hands one tmp_path per TEST, not per fixture use — and overwrote the checkpoint,
    breaking both days at once. The empty second day says the same thing more honestly.)"""
    v = acc.evaluate_period([DAY, "2026-08-21"], root=green)
    assert not v["accepted"]
    assert v["failed_days"] == ["2026-08-21"]
    v1 = acc.evaluate_period([DAY], root=green)
    assert v1["accepted"]


def test_the_real_writers_produce_what_the_gate_reads(tmp_path, monkeypatch):
    """Format-drift guard: one row written through the REAL window_ledger and slot_telemetry
    APIs must parse in the gate's readers. Without this the gate could judge a format the
    writers stopped producing."""
    led = tmp_path / acc.COVERAGE_DIR
    led.mkdir(parents=True)
    tel = tmp_path / acc.TIMING_DIR
    tel.mkdir(parents=True)
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(led))
    monkeypatch.setenv("RAITS_TELEMETRY_DIR", str(tel))
    import global_index.window_ledger as wl
    import global_index.slot_telemetry as tl
    importlib.reload(wl)
    importlib.reload(tl)
    try:
        wl.window_open("roska4_calm", DAY, route_hint="track1_candidate")
        wl.slot_observed("roska4_calm", DAY, "TRACK1_CALM_1000", decided=True,
                         route_hint="track1_candidate")
        tl.record_skip("TRACK1_CALM_1000", "ok")
        rows = acc._ledger_rows(tmp_path, DAY)
        assert any(r.get("event") == "slot_observed" for r in rows), rows
        files = list(tel.glob("slot_timing_*.jsonl")) if hasattr(tel, "glob") else []
        files = list((tmp_path / acc.TIMING_DIR).glob("slot_timing_*.jsonl"))
        assert files, "the real telemetry writer produced no file"
        parsed = [json.loads(l) for f in files
                  for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert parsed and "slot_id" in parsed[0] and "runtime_s" in parsed[0]
    finally:
        monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
        monkeypatch.delenv("RAITS_TELEMETRY_DIR", raising=False)
        importlib.reload(wl)
        importlib.reload(tl)


# ══════════════════════════════════════════════════════════════════════════════
# 2. the dashboard reader
# ══════════════════════════════════════════════════════════════════════════════

def test_the_reader_reports_a_green_day_from_track1_paths(green):
    r = trr.read_track1_runtime(green)
    assert r["route"] == "track1_candidate"
    # Stage 5ZH: the book is present now, because `track1_bootstrap.write` produces it in
    # the SAME call as the checkpoint and the fixture goes through that writer. A green day
    # that had a checkpoint and no book was never a state the system could reach.
    assert r["book"]["present"] is True
    assert r["checkpoint"]["present"] is True
    assert r["checkpoint"]["summary"]["route"] == "track1_candidate"
    assert r["checkpoint"]["summary"]["entry_count"] == 0
    cov = r["window_coverage"]
    assert cov["present"] and cov["days"] == [DAY]
    assert all(cov["latest"][s]["outcome"] == "complete" for s in WINDOWS_ET)
    tim = r["slot_timing"]["days"][DAYC]
    assert tim["records"] == len(ts.TRACK1_SLOTS)
    assert tim["runtime_p95_s"] < 240
    assert r["explanations"]["days"][DAYC] == 5
    assert r["gates"]["orders_possible"] is False
    assert r["safety"]["positions_path"] == "live_positions.track1.json"


def test_the_reader_handles_an_empty_root_without_inventing_state(tmp_path):
    r = trr.read_track1_runtime(tmp_path)
    assert r["book"]["present"] is False
    assert r["checkpoint"]["present"] is False
    assert r["window_coverage"]["present"] is False
    assert r["slot_timing"]["present"] is False


def test_the_reader_never_opens_the_legacy_book():
    """The cutover requirement, held at the source level: the module must not name
    live_positions.json at all except inside its own warning strings."""
    src = Path(trr.__file__).read_text(encoding="utf-8")
    import ast
    tree = ast.parse(src)
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value == "live_positions.json"]
    assert hits == [], f"the Track 1 reader names legacy's book at lines {hits}"
    assert trr.BOOK_PATH == "live_positions.track1.json"


def test_the_reader_paths_point_at_the_durable_runtime_not_scratch():
    """Stage 5K0's lesson, held: evidence a gate depends on must not live in scratch, where
    ordinary cleanup deletes it."""
    for const in (trr.COVERAGE_DIR, trr.TIMING_DIR, trr.SHADOW_DIR):
        assert const.startswith("global_index/track1_runtime/"), const
    for const in (acc.COVERAGE_DIR, acc.TIMING_DIR, acc.SHADOW_DIR):
        assert const.startswith("global_index/track1_runtime/"), const
        assert not const.startswith("scratch"), const


def test_the_reader_and_the_gate_read_the_same_paths():
    assert trr.COVERAGE_DIR == acc.COVERAGE_DIR
    assert trr.TIMING_DIR == acc.TIMING_DIR
    assert trr.SHADOW_DIR == acc.SHADOW_DIR
    assert trr.CHECKPOINT_PATH == acc.CHECKPOINT_PATH


def test_the_app_exposes_the_endpoint_and_labels_the_legacy_one():
    src = Path("monitor/backend/app.py").read_text(encoding="utf-8")
    assert '/api/v1/track1-runtime' in src
    assert 'read_track1_runtime' in src
    legacy_fn = src[src.index("def api_v1_runner_positions"):]
    legacy_fn = legacy_fn[:legacy_fn.index("@app.get")]
    assert '"route"] = "legacy"' in legacy_fn or "payload[\"route\"] = \"legacy\"" in legacy_fn
    assert "track1-runtime" in legacy_fn, "the legacy endpoint does not point at the Track 1 one"


def test_the_reader_is_read_only():
    """No write call anywhere in the module. Parsed, not grepped, so a comment cannot hide
    one and a string cannot fake one."""
    import ast
    src = Path(trr.__file__).read_text(encoding="utf-8")
    # `replace` is NOT on this list: the first version banned it and flagged two calls of
    # str.replace on file stems — a name-based scan cannot tell os.replace from str.replace,
    # and the honest response is to drop the ambiguous name and keep the unambiguous ones.
    # `open` is banned outright: the reader uses read_text only.
    banned = {"write_text", "write_bytes", "mkdir", "unlink", "rename", "dump", "open"}
    hits = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", getattr(n.func, "id", ""))
            if name in banned:
                hits.append((name, n.lineno))
    assert hits == [], hits


# ══════════════════════════════════════════════════════════════════════════════
# 3. the full inventory and the probe
# ══════════════════════════════════════════════════════════════════════════════

def _sched(**kw):
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5p")
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from global_index import run_scheduler as rs
        return rs.make_scheduler(port=4002, dry_run=True, **kw)
    finally:
        logging.disable(lvl)


def test_the_full_inventory_in_all_three_modes():
    assert len(_sched().get_jobs()) == 61  # Stage 5Q-5 added the 16:20 post-close SPY refresh (shared infra, all modes): 60->61, 129->130, 100->101
    ids = {j.id for j in _sched(track1_only=True).get_jobs()}
    strategy = [i for i in ids if i in {s.id.lower() for s in ts.TRACK1_SLOTS}]
    t1_safety = [i for i in ids if i.startswith(("track1_stop_repair", "track1_maxhold"))]
    legacy_safety = [i for i in ids if i.startswith("stop_repair") or i == "maxhold_exit"]
    shared = [i for i in ids if i in ("heartbeat", "preflight", "session_report_fallback",
                                      "spy_refresh_pm")]
    legacy_strategy = [i for i in ids if i.startswith(("live_day", "nkd_night"))]
    # Stage 5Q added the read-only post-window audit jobs. Counted from their own table
    # rather than written as a number, so the assertion moves with the table instead of
    # having to be remembered.
    t1_audit = [i for i in ids if i in {j.id for j in ts.track1_audit_jobs()}]
    assert len(strategy) == 70
    assert len(t1_safety) == 11
    assert len(legacy_safety) == 11
    assert len(shared) == 4
    assert len(t1_audit) == len(ts.track1_audit_jobs()) == 5
    assert legacy_strategy == []
    assert len(ids) == 96 + len(t1_audit)   # 95 + the 16:20 SPY refresh


@pytest.mark.parametrize("kw", [{}, {"track1_shadow": True}, {"track1_only": True}])
def test_parity_in_all_three_modes(kw):
    r = ts.parity_report(**kw)
    assert r["in_parity"], r


def test_every_track1_child_argv_and_env_in_track1_only():
    """All 81 Track 1 children (70 strategy + 11 safety): route stamped, no order flags on
    strategy slots, ibkr providers, safety on Track 1 paths."""
    from global_index import run_scheduler as rs
    seen = []
    orig = rs._run
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args), "route": route}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, track1_only=True)
        for j in sched.get_jobs():
            if j.id.startswith("track1_"):
                j.func()
    finally:
        rs._run = orig
        rs._maxhold_done_t1.clear()
        logging.disable(lvl)
    def _module(r):
        a = r["args"]
        return a[a.index("-m") + 1] if "-m" in a else ""

    assert len(seen) == 81 + len(ts.track1_audit_jobs()), len(seen)
    assert {r["route"] for r in seen} == {"track1_candidate"}
    # Keyed on the MODULE each child runs, not on a flag. `--sleeve` used to be the
    # discriminator and Stage 5Q's audit children carry it too, so the old classifier would
    # have counted four audits as strategy slots and still passed.
    strategy = [r for r in seen if _module(r) == "global_index.run_live_day_track1"]
    assert len(strategy) == 70
    for r in strategy:
        a = r["args"]
        assert a[a.index("--bar-provider") + 1] == "ibkr", r["label"]
        for nope in ("--allow-orders", "--port", "--window"):
            assert nope not in a, (r["label"], nope)
    safety = [r for r in seen if _module(r) in ("global_index.run_maxhold_exit",
                                                "global_index.run_stop_repair")]
    assert len(safety) == 11
    for r in safety:
        a = r["args"]
        assert a[a.index("--positions-path") + 1] == "live_positions.track1.json", r["label"]
        assert "--allow-orders" not in a
    audit = [r for r in seen if _module(r) == "global_index.track1_shadow_audit"]
    assert len(audit) == len(ts.track1_audit_jobs())
    for r in audit:
        a = r["args"]
        for nope in ("--allow-orders", "--bar-provider", "--port", "--window"):
            assert nope not in a, (r["label"], nope)


# ══════════════════════════════════════════════════════════════════════════════
# 4. legacy-removability, extended to the dashboard
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


def test_the_import_block_blocks():
    with _block_legacy():
        with pytest.raises(ImportError):
            importlib.import_module("global_index.run_live_day")


def test_scheduler_reader_and_gate_all_work_with_legacy_deleted(green):
    with _block_legacy():
        ids = {j.id for j in _sched(track1_only=True).get_jobs()}
        assert len(ids) == 96 + len(ts.track1_audit_jobs())
        r = trr.read_track1_runtime(green)
        assert r["window_coverage"]["latest"]["global_nkd"]["outcome"] == "complete"
        v = acc.evaluate_day(DAY, root=green)
        assert v["accepted"], v["failed"]


# ══════════════════════════════════════════════════════════════════════════════
# 5. ops and runbook
# ══════════════════════════════════════════════════════════════════════════════

def test_ops_start_path_sets_the_runtime_env():
    from monitor import ops
    env = ops._env(track1_only=True)
    assert env.get("RAITS_TRACK1_ONLY") == "1"
    assert "track1_runtime" in env.get("RAITS_WINDOW_LEDGER_DIR", "")
    assert "track1_runtime" in env.get("RAITS_TELEMETRY_DIR", "")
    assert ops.TRACK1_ORDERS_ENV not in env


def test_the_runbook_documents_the_operator_command_and_the_gate():
    doc = Path("docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md").read_text(encoding="utf-8")
    assert "restart --scheduler --track1-only-shadow" in doc
    assert "track1_shadow_acceptance" in doc, "the acceptance gate is not named in the runbook"
    assert "p95" in doc


def test_no_switch_or_state_file_was_created():
    # `global_index/maxhold_state.track1.json` came OFF this list on 2026-08-24 and the
    # reason is measured, not conceded: the live scheduler's TRACK1_MAX_HOLD_EXIT job ran at
    # 07:31 local (09:31 ET) and wrote it — `[TRACK1_MAX_HOLD_EXIT] completed OK` in
    # scheduler_0824.log — which is exactly what Stage 5O built that marker for. Once Track 1
    # safety is genuinely scheduled the marker exists every trading day, so asserting its
    # absence forbids the running system from doing its job.
    #
    # What this test still guards is unchanged and is the part that matters: no kill switch,
    # no confirmation file, no route BOOK and no lock file may be conjured by a test run.
    for name in ("STOP_TRADING", "STOP_TRADING.track1", "track1_go_live_confirmation.json",
                 "runner.track1.pid"):
        assert not Path(name).exists(), name
    # Stronger than the absence check it replaced: an mtime older than this process says no
    # test in this run touched it, which is the thing actually being guarded.
    #
    # `live_positions.track1.json` joined the marker on this list on 2026-08-25, for the same
    # measured reason. `track1_bootstrap.write` produces the route BOOK in the same call as
    # the checkpoint, and the 15:55 ET close of a complete Swing window is when it runs — it
    # first appeared at 15:56:19 ET that day, holding zero positions. Once the route's own
    # windows complete, the book exists every trading day, and asserting its absence forbids
    # the running system from doing exactly what Stage 5O and 5ZH built it to do.
    for name in ("global_index/maxhold_state.track1.json", "live_positions.track1.json"):
        p = Path(name)
        if p.exists():
            assert p.stat().st_mtime < _IMPORTED_AT, f"a test wrote the REAL {name}"
