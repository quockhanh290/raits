"""Stage 5ZL — "I could not check" stops meaning "I checked and it was fine".

Nothing here writes into the runtime tree. Every verification record, CSV and status file is
under `tmp_path`, and the last part proves it by mtime.

What was wrong
--------------
`verify_regime_labels` returned a COUNT of drifted dates, and returned **0** from four places
that had verified nothing:

    cannot import futures._validated_core   -> 0
    could not load the CSVs                 -> 0
    label_regimes raised                    -> 0
    no overlapping dates to compare         -> 0, logged "HMM stable"

Zero is what a clean run returns. And the one call site discarded it, in a process whose
`__main__` called `main()` bare so the return value never reached the exit code, launched by a
scheduler that keeps only CRITICAL and ERROR from a child that exited 0. A drift of fifty
labels was invisible from end to end — in the check that guards which sleeve may trade.

The fourth path is the one worth naming. With no overlapping dates the old code took the INFO
branch and printed *"Regime labels unchanged (0 dates verified) — HMM stable"*: a statement
about nothing, phrased as reassurance.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import regime_verify as rv                   # noqa: E402
from global_index import track1_gates as gates                 # noqa: E402
from global_index import update_spy_csv as U                   # noqa: E402

REPO = Path(r"d:\raits")
_IMPORTED_AT = time.time()


# ══════════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════════

def a_csv(path: Path, *, days: int = 400, start: str = "2017-01-03",
          bump: float = 0.0, bump_at: int = -1) -> Path:
    import pandas as pd
    idx = pd.bdate_range(start, periods=days)
    close = [300.0 + i * 0.1 for i in range(days)]
    if bump_at >= 0:
        close[bump_at] += bump
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in idx],
                  "close": close}).to_csv(path, index=False)
    return path


def record_status(root: Path, status: str, code: str, *, detail: str = "d",
                  checked_at: str | None = None) -> Path:
    return rv.record(rv.VerifyResult(status=status, code=code, detail=detail,
                                     checked_at=checked_at or rv._now()),
                     root=root, source="test")


# ══════════════════════════════════════════════════════════════════════════════
# A. the contract
# ══════════════════════════════════════════════════════════════════════════════

def test_there_are_exactly_three_statuses():
    assert rv.STATUSES == ("PASS", "DRIFT", "UNKNOWN")


def test_every_code_belongs_to_exactly_one_status():
    """A code that could mean either is a code nobody can act on."""
    assert set(rv.CODE_STATUS.values()) == set(rv.STATUSES)
    assert rv.CODE_STATUS[rv.OK] == rv.PASS
    assert rv.CODE_STATUS[rv.LABELS_CHANGED] == rv.DRIFT
    for code in (rv.NO_ENGINE, rv.UNREADABLE, rv.LABELLING_FAILED, rv.NO_OVERLAP,
                 rv.NO_SNAPSHOT, rv.NO_RECORD, rv.RECORD_UNREADABLE, rv.RECORD_STALE):
        assert rv.CODE_STATUS[code] == rv.UNKNOWN, code


def test_a_result_cannot_carry_a_code_from_another_status():
    with pytest.raises(ValueError):
        rv.VerifyResult(status=rv.PASS, code=rv.LABELS_CHANGED)
    with pytest.raises(ValueError):
        rv.VerifyResult(status=rv.PASS, code=rv.NO_ENGINE)
    with pytest.raises(ValueError):
        rv.VerifyResult(status="FINE", code=rv.OK)


def test_unknown_is_not_ok_and_blocks_paper():
    for status, code in ((rv.PASS, rv.OK), (rv.DRIFT, rv.LABELS_CHANGED),
                         (rv.UNKNOWN, rv.NO_RECORD)):
        r = rv.VerifyResult(status=status, code=code)
        assert r.ok is (status == rv.PASS)
        assert r.blocks_paper is (status != rv.PASS)


def test_drift_and_unknown_are_distinguishable_in_every_surface():
    d = rv.VerifyResult(status=rv.DRIFT, code=rv.LABELS_CHANGED, detail="x")
    u = rv.VerifyResult(status=rv.UNKNOWN, code=rv.NO_ENGINE, detail="x")
    assert d.status != u.status and d.code != u.code
    assert d.one_line() != u.one_line()
    assert d.as_dict()["status"] != u.as_dict()["status"]


# ══════════════════════════════════════════════════════════════════════════════
# B. the four old collapses — each returns UNKNOWN, not PASS
# ══════════════════════════════════════════════════════════════════════════════

def test_3_a_missing_snapshot_is_unknown_not_pass(tmp_path):
    new = a_csv(tmp_path / "spy.csv")
    r = rv.verify_labels(tmp_path / "nope.csv", new)
    assert r.status == rv.UNKNOWN and r.code == rv.NO_SNAPSHOT, r
    assert r.status != rv.PASS


def test_5_a_missing_engine_is_unknown_not_pass(tmp_path, monkeypatch):
    """The old code returned 0 here and the caller read it as 'no drift'."""
    import builtins
    real = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "futures._validated_core":
            raise ImportError("no engine here")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", blocked)
    snap, new = a_csv(tmp_path / "snap.csv"), a_csv(tmp_path / "spy.csv")
    r = rv.verify_labels(snap, new)
    assert r.status == rv.UNKNOWN and r.code == rv.NO_ENGINE, r


def test_4_unreadable_inputs_are_unknown_not_pass(tmp_path, monkeypatch):
    monkeypatch.setattr("futures._validated_core.benchmark_daily",
                        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("not a csv")))
    snap, new = a_csv(tmp_path / "snap.csv"), a_csv(tmp_path / "spy.csv")
    r = rv.verify_labels(snap, new)
    assert r.status == rv.UNKNOWN and r.code == rv.UNREADABLE, r
    assert "not a csv" in r.detail


def test_5b_a_raising_labeller_is_unknown_not_pass(tmp_path, monkeypatch):
    monkeypatch.setattr("futures._validated_core.label_regimes",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("hmm blew up")))
    snap, new = a_csv(tmp_path / "snap.csv"), a_csv(tmp_path / "spy.csv")
    r = rv.verify_labels(snap, new)
    assert r.status == rv.UNKNOWN and r.code == rv.LABELLING_FAILED, r


def test_no_overlapping_dates_is_unknown_and_says_nothing_was_looked_at(tmp_path, monkeypatch):
    """The subtlest of the four: the old code took the INFO branch and printed 'HMM stable'."""
    import pandas as pd
    monkeypatch.setattr("futures._validated_core.benchmark_daily", lambda p: pd.DataFrame())
    monkeypatch.setattr("futures._validated_core.label_regimes",
                        lambda *_a, **_k: pd.Series(dtype=object,
                                                    index=pd.DatetimeIndex([])))
    snap, new = a_csv(tmp_path / "snap.csv"), a_csv(tmp_path / "spy.csv")
    r = rv.verify_labels(snap, new)
    assert r.status == rv.UNKNOWN and r.code == rv.NO_OVERLAP, r
    assert r.counts["compared"] == 0
    assert "nothing was looked at" in r.detail


# ══════════════════════════════════════════════════════════════════════════════
# C. PASS and DRIFT, with the engine stubbed so the outcome is chosen not hoped for
# ══════════════════════════════════════════════════════════════════════════════

def _labels(monkeypatch, old_seq, new_seq):
    import pandas as pd
    idx = pd.bdate_range("2018-01-02", periods=len(old_seq))
    calls = {"n": 0}

    def fake_labels(bench, *_a, **_k):
        calls["n"] += 1
        seq = old_seq if calls["n"] == 1 else new_seq
        return pd.Series(list(seq), index=idx)

    monkeypatch.setattr("futures._validated_core.benchmark_daily", lambda p: pd.DataFrame())
    monkeypatch.setattr("futures._validated_core.label_regimes", fake_labels)


def test_1_a_clean_comparison_is_pass(tmp_path, monkeypatch):
    _labels(monkeypatch, "CCNNSS", "CCNNSS")
    snap, new = a_csv(tmp_path / "snap.csv"), a_csv(tmp_path / "spy.csv")
    r = rv.verify_labels(snap, new)
    assert r.status == rv.PASS and r.code == rv.OK, r
    assert r.counts["compared"] == 6 and r.counts["changed"] == 0


def test_2_a_changed_label_is_drift_and_names_the_dates(tmp_path, monkeypatch):
    _labels(monkeypatch, "CCNNSS", "CCNNSC")
    snap, new = a_csv(tmp_path / "snap.csv"), a_csv(tmp_path / "spy.csv")
    r = rv.verify_labels(snap, new)
    assert r.status == rv.DRIFT and r.code == rv.LABELS_CHANGED, r
    assert r.counts["changed"] == 1
    assert len(r.counts["sample"]) == 1


# ══════════════════════════════════════════════════════════════════════════════
# D. the record — absence is never a pass
# ══════════════════════════════════════════════════════════════════════════════

def test_no_record_at_all_is_unknown(tmp_path):
    r = rv.latest(tmp_path)
    assert r.status == rv.UNKNOWN and r.code == rv.NO_RECORD, r


def test_the_newest_record_wins(tmp_path):
    record_status(tmp_path, rv.DRIFT, rv.LABELS_CHANGED, checked_at="2026-08-20T00:00:00+00:00")
    record_status(tmp_path, rv.PASS, rv.OK, checked_at="2026-08-26T00:00:00+00:00")
    assert rv.latest(tmp_path, now="2026-08-26T01:00:00+00:00").status == rv.PASS


def test_a_stale_record_is_unknown_not_the_status_it_carried(tmp_path):
    record_status(tmp_path, rv.PASS, rv.OK, checked_at="2026-07-01T00:00:00+00:00")
    r = rv.latest(tmp_path, now="2026-08-26T00:00:00+00:00")
    assert r.status == rv.UNKNOWN and r.code == rv.RECORD_STALE, r


def test_an_unreadable_record_is_unknown(tmp_path):
    p = rv.record_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ truncated\n", encoding="utf-8")
    r = rv.latest(tmp_path)
    assert r.status == rv.UNKNOWN and r.code == rv.RECORD_UNREADABLE, r


def test_a_record_with_a_foreign_status_is_unknown(tmp_path):
    p = rv.record_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"status": "FINE", "code": "ok",
                             "checked_at": rv._now()}) + "\n", encoding="utf-8")
    assert rv.latest(tmp_path).status == rv.UNKNOWN


# ══════════════════════════════════════════════════════════════════════════════
# E. the call site no longer discards the answer
# ══════════════════════════════════════════════════════════════════════════════

def test_6_the_call_site_keeps_the_result(tmp_path, monkeypatch):
    """`update_spy_csv` used to drop it on the floor. Checked by AST, not by reading."""
    import ast
    tree = ast.parse((REPO / "global_index" / "update_spy_csv.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "update_spy_csv")
    bare = [n for n in ast.walk(fn) if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", "") == "verify_regime_labels"]
    assert bare == [], "the verification result is discarded again"
    assigned = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Call)
                and getattr(n.value.func, "id", "") == "verify_regime_labels"]
    assert assigned, "verify_regime_labels is no longer called at all"


def test_the_outcome_carries_the_verification_and_still_counts_rows():
    o = U.UpdateOutcome(rows_added=0, verify=rv.VerifyResult(status=rv.DRIFT,
                                                             code=rv.LABELS_CHANGED))
    assert o == 0 and int(o) == 0, "existing callers compare the outcome to an int"
    assert o.verify.status == rv.DRIFT


def test_the_module_entry_point_propagates_the_exit_code():
    """`main()` bare threw the return value away; the process exited 0 whatever happened."""
    import ast
    tree = ast.parse((REPO / "global_index" / "update_spy_csv.py").read_text(encoding="utf-8"))
    guard = [n for n in tree.body if isinstance(n, ast.If)]
    src = "\n".join(ast.unparse(n) for n in guard)
    assert "sys.exit(main()" in src, src


# ══════════════════════════════════════════════════════════════════════════════
# F. the CLI — DRIFT and UNKNOWN exit non-zero only under --verify-strict
# ══════════════════════════════════════════════════════════════════════════════

def _cli(tmp_path, *, strict: bool, status: str, code: str, monkey_env=None):
    """Run the real CLI in a subprocess with the verification stubbed to a chosen answer."""
    stub = tmp_path / "stub.py"
    stub.write_text(
        "import sys\n"
        "sys.path.insert(0, r'd:\\\\raits')\n"
        "from global_index import regime_verify as rv, update_spy_csv as U\n"
        "from pathlib import Path\n"
        f"res = rv.VerifyResult(status={status!r}, code={code!r}, detail='stub',\n"
        "                      checked_at=rv._now())\n"
        "U.update_spy_csv = lambda *a, **k: U.UpdateOutcome(rows_added=1, verify=res)\n"
        "argv = ['--csv', 'x.csv', '--api-key', 'k']\n"
        + ("argv.append('--verify-strict')\n" if strict else "")
        + "sys.exit(U.main(argv) or 0)\n", encoding="utf-8")
    return subprocess.run([sys.executable, str(stub)], capture_output=True, text=True,
                          cwd=str(tmp_path), timeout=180)


def test_2b_drift_exits_nonzero_under_strict(tmp_path):
    r = _cli(tmp_path, strict=True, status=rv.DRIFT, code=rv.LABELS_CHANGED)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "DRIFT" in r.stdout


def test_unknown_exits_nonzero_under_strict(tmp_path):
    r = _cli(tmp_path, strict=True, status=rv.UNKNOWN, code=rv.NO_ENGINE)
    assert r.returncode != 0, r.stdout + r.stderr
    assert "not 'no drift'" in r.stdout, r.stdout


def test_pass_exits_zero_under_strict(tmp_path):
    r = _cli(tmp_path, strict=True, status=rv.PASS, code=rv.OK)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


@pytest.mark.parametrize("status,code", [(rv.DRIFT, rv.LABELS_CHANGED),
                                         (rv.UNKNOWN, rv.NO_ENGINE)])
def test_without_strict_the_exit_code_is_unchanged(tmp_path, status, code):
    """The pre-flight caller must not skip a trading day over a verification result."""
    r = _cli(tmp_path, strict=False, status=status, code=code)
    assert r.returncode == 0, r.stdout + r.stderr
    assert status in r.stdout, "the status must still be SAID, even when it does not fail"


# ══════════════════════════════════════════════════════════════════════════════
# G. the scheduler: which caller runs strict, and which deliberately does not
# ══════════════════════════════════════════════════════════════════════════════

def _fire(job_ids, tmp_path, **kw):
    """Fire named jobs with the subprocess runner replaced. Nothing executes.

    EVERY state path this can write is redirected into `tmp_path` first, and the reason is
    not hypothetical: the first version of this helper fired the pre-flight body without
    redirecting `_PREFLIGHT_STATE`, and the job did exactly what it is built to do — it wrote
    `{"2026-08-26": true}` over the REAL `global_index/preflight_state.json`, replacing seven
    days of recorded history with a clearance for a day nothing had checked. Caught by this
    file's own "no production file was written" test, which is the only reason it was noticed.

    A job body that persists state is not made safe by replacing the process runner. The
    persistence happens in the parent.
    """
    import logging, os
    from global_index import run_scheduler as rs
    os.environ.setdefault("PYTEST_CURRENT_TEST", "stage5zl")
    seen = []
    orig_run = rs._run
    orig_pre = rs._PREFLIGHT_STATE
    orig_mh, orig_mh1 = rs._MAXHOLD_STATE, rs._MAXHOLD_STATE_T1
    saved_pre = dict(rs._preflight_ok)
    lvl = logging.getLogger().manager.disable
    logging.disable(logging.CRITICAL)
    try:
        rs._PREFLIGHT_STATE = Path(tmp_path) / "preflight_state.json"
        rs._MAXHOLD_STATE = Path(tmp_path) / "maxhold_state.json"
        rs._MAXHOLD_STATE_T1 = Path(tmp_path) / "maxhold_state.track1.json"
        rs._run = lambda args, label, dry_run=False, timeout=None, route=None: (
            seen.append({"label": label, "args": list(args)}) or True)
        sched = rs.make_scheduler(port=4002, dry_run=True, **kw)
        for j in sched.get_jobs():
            if j.id in job_ids:
                j.func()
    finally:
        rs._run = orig_run
        rs._PREFLIGHT_STATE = orig_pre
        rs._MAXHOLD_STATE, rs._MAXHOLD_STATE_T1 = orig_mh, orig_mh1
        rs._preflight_ok.clear()
        rs._preflight_ok.update(saved_pre)
        rs._maxhold_done.clear()
        rs._maxhold_done_t1.clear()
        logging.disable(lvl)
    return seen


def test_the_post_close_refresh_runs_strict(tmp_path):
    seen = _fire({"spy_refresh_pm"}, tmp_path, track1_only=True)
    rows = [s for s in seen if "update_spy_csv" in " ".join(s["args"])]
    assert rows, "spy_refresh_pm did not launch update_spy_csv"
    for r in rows:
        assert "--verify-strict" in r["args"], r["args"]


def test_the_1345_preflight_does_not_run_strict(tmp_path):
    """Documented, not accidental: it gates the whole trading day."""
    seen = _fire({"preflight"}, tmp_path, track1_only=True)
    rows = [s for s in seen if "update_spy_csv" in " ".join(s["args"])]
    if not rows:
        pytest.skip("the pre-flight did not reach the SPY step in this environment")
    for r in rows:
        assert "--verify-strict" not in r["args"], r["args"]


def test_8_a_post_close_failure_does_not_mark_the_preflight_failed():
    """The two jobs are separate and must stay separate: the 16:20 refresh runs after
    everything today has finished, so marking the day failed would skip TOMORROW's slots."""
    import ast
    tree = ast.parse((REPO / "global_index" / "run_scheduler.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "job_spy_refresh_pm")
    src = ast.unparse(fn)
    assert "_preflight_ok" not in src, "the post-close refresh writes the pre-flight state"
    assert "_save_preflight_state" not in src


def test_the_post_close_success_line_verifies_what_it_claims(tmp_path):
    """Found live, not hypothesised.

    On 2026-08-25 the job logged *"OK — the daily series now covers 2026-08-25"* at 16:20 ET
    and the series ended on 2026-08-24. It printed the sentence on any exit-0 having checked
    nothing. Polygon's SPY daily aggregate is not always final at 16:20, so the run genuinely
    succeeded and genuinely added nothing — a success line asserting an unverified fact, one
    job over from the defect this stage exists to remove.
    """
    from global_index.run_scheduler import _spy_series_last_day
    csv = tmp_path / "spy.csv"
    csv.write_text("date,close\n2026-08-24,300.0\n", encoding="utf-8")
    assert _spy_series_last_day(str(csv)) == "2026-08-24"
    # unreadable means "could not tell", never "up to date"
    assert _spy_series_last_day(str(tmp_path / "nope.csv")) == ""
    assert _spy_series_last_day(str(tmp_path)) == ""


def test_the_post_close_branch_compares_the_series_against_today():
    import ast
    tree = ast.parse((REPO / "global_index" / "run_scheduler.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "job_spy_refresh_pm")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_spy_series_last_day"]
    assert calls, "the success branch still claims coverage without looking"


def test_the_post_close_failure_message_separates_drift_from_unknown():
    import ast
    tree = ast.parse((REPO / "global_index" / "run_scheduler.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "job_spy_refresh_pm")
    # structural: the failure branch reads the recorded status and has three arms
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "latest"]
    assert calls, "the failure branch does not read the recorded status"
    ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)]
    assert len(ifs) >= 3, "drift, unknown and 'series still short' are not told apart"


# ══════════════════════════════════════════════════════════════════════════════
# H. readiness
# ══════════════════════════════════════════════════════════════════════════════

def test_3b_the_gate_is_registered_and_blocks_orders():
    b = gates.BLOCKERS["REGIME_LABEL_VERIFICATION"]
    assert b.blocks_orders is True
    assert b.status == gates.MEASURED_GATE
    assert b.released_by_measurement == "regime_labels_verified"
    assert b.released_by == (), "no confirmation flag may wave this through"


@pytest.mark.parametrize("status,code,opens", [
    (rv.PASS, rv.OK, True),
    (rv.DRIFT, rv.LABELS_CHANGED, False),
    (rv.UNKNOWN, rv.NO_ENGINE, False),
])
def test_only_pass_opens_the_gate(tmp_path, status, code, opens):
    record_status(tmp_path, status, code)
    ok, detail = gates.MEASUREMENTS["regime_labels_verified"](tmp_path)
    assert ok is opens, (status, detail)
    assert status in detail, "the reason must name which of the three it was"


def test_no_record_holds_the_gate_shut(tmp_path):
    ok, detail = gates.MEASUREMENTS["regime_labels_verified"](tmp_path)
    assert ok is False
    assert "never ran is not a check that passed" in detail


def test_the_measurement_fails_closed_on_an_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(rv, "latest",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, detail = gates.MEASUREMENTS["regime_labels_verified"](tmp_path)
    assert ok is False and "failing closed" in detail


# ══════════════════════════════════════════════════════════════════════════════
# I. the dashboard renders the three distinctly
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("status,code,expect", [
    (rv.PASS, rv.OK, "none moved"),
    (rv.DRIFT, rv.LABELS_CHANGED, "MOVED"),
    (rv.UNKNOWN, rv.NO_ENGINE, "not 'no drift'"),
])
def test_7_the_panel_reads_differently_for_each_status(tmp_path, status, code, expect):
    from monitor.backend import track1_runtime_reader as trr
    record_status(tmp_path, status, code)
    block = trr.read_track1_runtime(tmp_path)["regime_verify"]
    assert block["status"] == status
    assert block["code"] == code
    assert expect in block["reading"], block
    assert block["blocks_paper"] is (status != rv.PASS)


def test_the_panel_does_not_collapse_missing_into_ok(tmp_path):
    from monitor.backend import track1_runtime_reader as trr
    block = trr.read_track1_runtime(tmp_path)["regime_verify"]
    assert block["present"] is False
    assert block["status"] == rv.UNKNOWN
    assert block["blocks_paper"] is True


# ══════════════════════════════════════════════════════════════════════════════
# J. the freshness gate was not touched
# ══════════════════════════════════════════════════════════════════════════════

def test_9_the_freshness_gate_still_asks_for_the_previous_trading_day():
    """It must not start demanding today's close before today's close exists."""
    from global_index import track1_freshness as fresh
    import ast
    src = (REPO / "global_index" / "track1_freshness.py").read_text(encoding="utf-8")
    assert "regime_verify" not in src, "this stage reached into the freshness gate"
    tree = ast.parse(src)
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "required_daily_close_through" in names or hasattr(
        fresh, "required_daily_close_through"), sorted(names)


def test_the_freshness_gate_does_not_import_the_verifier():
    import ast
    tree = ast.parse((REPO / "global_index" / "track1_freshness.py").read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any("regime_verify" in m for m in mods), sorted(mods)


# ══════════════════════════════════════════════════════════════════════════════
# K. legacy
# ══════════════════════════════════════════════════════════════════════════════

def test_10_the_legacy_preflight_exit_behaviour_is_unchanged():
    """The one place a non-zero exit would skip a trading day. It must not have gained one."""
    import ast
    tree = ast.parse((REPO / "global_index" / "run_scheduler.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "job_preflight")
    src = ast.unparse(fn)
    assert "--verify-strict" not in src, (
        "the pre-flight now runs strict, so a verification result can skip a trading day")


def test_the_verifier_writes_nothing_a_legacy_reader_consumes(tmp_path):
    """The record lands in its own directory, not into any file legacy reads."""
    record_status(tmp_path, rv.PASS, rv.OK)
    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written, "nothing was written at all"
    for p in written:
        assert rv.VERIFY_DIR.replace("/", "\\") in str(p) or rv.VERIFY_DIR in str(p), p


# ══════════════════════════════════════════════════════════════════════════════
# L. nothing real was written
# ══════════════════════════════════════════════════════════════════════════════

def test_no_production_file_was_written_by_this_run():
    for name in ("spy_daily_live.csv", "global_index/preflight_state.json",
                 "global_index/replay_checkpoint.track1.json", "live_positions.track1.json"):
        p = REPO / name
        if p.exists():
            assert p.stat().st_mtime < _IMPORTED_AT, name


def test_no_real_verification_record_was_created():
    d = REPO / rv.VERIFY_DIR
    if not d.exists():
        return
    stray = [str(p) for p in d.rglob("*")
             if p.is_file() and p.stat().st_mtime >= _IMPORTED_AT]
    assert stray == [], stray


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
