"""Backend Track 1 env, dashboard runtime visibility, and the live shadow audit. 2026-08-24.

Read-only against the operator's world: no scheduler or backend is started or stopped, no
broker is opened, no order is possible, and every file these tests write goes under
`tmp_path`. The one `start_backend` exercise replaces `subprocess.Popen` with a recorder.

The defect this suite pins
--------------------------
`ops.py up` starts two children from one command. The scheduler was given
`_env(track1_shadow=..., track1_only=...)`; the backend was given a bare `_env()`. So on the
live box `ops.py status` reported `track1_mode=track1-only-shadow` — read from the
scheduler's own command line — while `/api/v1/schedule-status` served `state_slot_count=45`
and a legacy `next_decision_job`. **The operator's dashboard was describing a system that was
not the one running**, and both halves were internally consistent, which is why neither
looked wrong.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")

from global_index import track1_shadow_acceptance as acc   # noqa: E402
from global_index import track1_slots as ts                # noqa: E402
from monitor import ops                                    # noqa: E402

JS = Path("global_index/dash/realtime/realtime.js")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY"):
        monkeypatch.delenv(k, raising=False)


# ══════════════════════════════════════════════════════════════════════════════
# A. the backend child gets the same fact the scheduler got
# ══════════════════════════════════════════════════════════════════════════════

def _backend_env(**kw) -> dict:
    """Start the backend with Popen replaced, and return the env it would have been given."""
    seen = {}

    class _P:
        pid = 9999

    real_popen = ops.subprocess.Popen
    ops.subprocess.Popen = lambda args, **k: (seen.update(k) or _P())
    real_log = ops._open_log
    ops._open_log = lambda name: None
    try:
        ops.start_backend(4002, 5002, **kw)
    finally:
        ops.subprocess.Popen = real_popen
        ops._open_log = real_log
    assert "env" in seen, "start_backend did not pass an env at all"
    return seen["env"]


def test_default_backend_env_stays_legacy():
    env = _backend_env()
    assert "RAITS_TRACK1_SHADOW" not in env
    assert "RAITS_TRACK1_ONLY" not in env


def test_transitional_backend_env_carries_the_shadow_flag():
    env = _backend_env(track1_shadow=True)
    assert env.get("RAITS_TRACK1_SHADOW") == "1"
    assert "RAITS_TRACK1_ONLY" not in env


def test_track1_only_backend_env_carries_both_flags():
    env = _backend_env(track1_only=True)
    assert env.get("RAITS_TRACK1_ONLY") == "1"
    assert env.get("RAITS_TRACK1_SHADOW") == "1", (
        "track1-only implies the slots are registered; the mirror needs both")


def test_the_backend_env_can_never_arm_orders():
    """Widening what the backend is told must not widen what it may do."""
    for kw in ({}, {"track1_shadow": True}, {"track1_only": True}):
        assert ops.TRACK1_ORDERS_ENV not in _backend_env(**kw), kw


def test_both_children_of_one_up_are_told_the_same_thing(monkeypatch):
    """The actual defect: two children, one command, two different beliefs."""
    seen = {}
    monkeypatch.setattr(ops, "scheduler_processes", lambda: [])
    monkeypatch.setattr(ops, "_open_log", lambda name: None)

    class _P:
        pid = 1

    def _popen(args, **k):
        who = "scheduler" if any("run_scheduler" in str(a) for a in args) else "backend"
        seen[who] = k.get("env", {})
        return _P()

    monkeypatch.setattr(ops.subprocess, "Popen", _popen)
    ops.start_scheduler(4002, shadow_resume=True, assume_preflight_ok=False,
                        track1_only=True)
    ops.start_backend(4002, 5002, track1_shadow=True, track1_only=True)
    assert seen["scheduler"].get("RAITS_TRACK1_ONLY") == "1"
    assert seen["backend"].get("RAITS_TRACK1_ONLY") == "1"
    assert seen["scheduler"].get("RAITS_TRACK1_ONLY") == seen["backend"].get("RAITS_TRACK1_ONLY")


# ══════════════════════════════════════════════════════════════════════════════
# A2. the schedule mirror really follows those variables
# ══════════════════════════════════════════════════════════════════════════════

def _table_size(**env) -> int:
    for k in ("RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY"):
        os.environ.pop(k, None)
    os.environ.update(env)
    try:
        from monitor.backend import schedule_status as ss
        importlib.reload(ss)
        return ss._state_slot_table_size()
    finally:
        for k in ("RAITS_TRACK1_SHADOW", "RAITS_TRACK1_ONLY"):
            os.environ.pop(k, None)
        from monitor.backend import schedule_status as ss2
        importlib.reload(ss2)


def test_the_mirror_is_45_in_legacy_mode():
    assert _table_size() == 45


def test_the_mirror_adds_track1_in_the_transitional_mode():
    assert _table_size(RAITS_TRACK1_SHADOW="1") == 45 + len(ts.TRACK1_SLOTS)


def test_the_mirror_replaces_legacy_in_track1_only_mode():
    """NOT 45 + 70. In track1-only the 45 legacy strategy slots are deliberately NOT
    registered, so the state table is the 70 Track 1 slots alone — which is the entire point
    of the mode. A mirror showing 115 here would be inventing 45 slots the scheduler does
    not have, and manufacturing an incident for each of them every day."""
    assert _table_size(RAITS_TRACK1_SHADOW="1", RAITS_TRACK1_ONLY="1") == len(ts.TRACK1_SLOTS)
    assert _table_size(RAITS_TRACK1_SHADOW="1", RAITS_TRACK1_ONLY="1") != 45


# ══════════════════════════════════════════════════════════════════════════════
# B. the dashboard shows Track 1's own runtime, and says so when it is empty
# ══════════════════════════════════════════════════════════════════════════════

def test_the_frontend_fetches_the_track1_endpoint():
    assert "/api/v1/track1-runtime" in JS.read_text(encoding="utf-8")


#: "Blocking gate" was pinned here on 2026-08-24 and the panel renders "Blocking gates".
#: Which stage pluralised it cannot be dated — the whole panel is uncommitted work on this
#: branch, so there is no earlier revision to compare against, and I am not going to guess.
#: What IS measurable is that this suite was not in the regression set any stage ran, so
#: whichever stage renamed the label, nothing was watching. The list below is now checked for
#: completeness as well as presence, which is the half that was missing: pinning ten labels
#: while the panel renders thirteen would let three facts disappear unnoticed.
REQUIRED_FACTS = ["Route", "Orders possible", "Blocking gates", "Window coverage",
                  "Slot timing", "Explanations",
                  # Stage 5ZX. Calm's two shadow phases. Declared here because this pin is
                  # bidirectional and caught the row the moment it was added without being
                  # declared — which is the pin doing its job, not the pin being stale.
                  # Stage 5ZZC. The daily regime file, declared here for the same reason the
                  # row above was: this pin fails in both directions and caught it at once.
                  # Stage 5ZZE. Declared for the same reason as the two rows before it: this
                  # pin fails in both directions and caught it the moment it was added.
                  "Paper account",
                  "SPY daily",
                  "Calm phases",
                  "Book", "Checkpoint", "Signals today",
                  "Audit verdict", "Audit reasons", "Safety positions", "Safety client id",
                  # Added by Stage 5ZZK and never pinned here, so this list had been reporting
                  # the panel as broken for days. Pre-existing; noticed while running the
                  # adjacent suites in Stage 5ZZW and fixed rather than left ringing.
                  "Blockers come from"]


@pytest.mark.parametrize("fact", REQUIRED_FACTS)
def test_every_required_fact_is_rendered(fact):
    block = _render_block()
    assert f"t1Fact('{fact}'" in block, f"{fact} is not displayed"


def test_the_panel_renders_no_fact_this_list_does_not_know_about():
    """The other direction. A label that drifts now fails on BOTH sides — one of them saying
    the pin is stale rather than the panel being broken."""
    import re

    rendered = set(re.findall(r"t1Fact\('([^']+)'", _render_block()))
    assert rendered, "no facts were found at all — the renderer moved"
    assert rendered == set(REQUIRED_FACTS), {
        "rendered but not pinned": sorted(rendered - set(REQUIRED_FACTS)),
        "pinned but not rendered": sorted(set(REQUIRED_FACTS) - rendered)}


def _render_block() -> str:
    src = JS.read_text(encoding="utf-8")
    i = src.index("function renderTrack1()")
    return src[i:src.index("function renderPositions()", i)]


def test_absence_is_stated_explicitly_not_left_blank():
    block = _render_block()
    assert "Track 1 runtime not yet observed" in block
    assert "expected state before the first slot" in block


def test_an_unreachable_endpoint_is_a_different_message_from_an_empty_route():
    """Three states, never two: cannot ask / nothing to show / running."""
    block = _render_block()
    assert "Track 1 runtime unavailable" in block
    assert "could not ask" in block


def test_the_coverage_row_reads_the_sleeve_keyed_latest():
    """`latest` is {sleeve: status}, not an object with `.date`. The first version read
    `cov.latest?.date` — a field that does not exist — so the row printed 'latest --' even
    on a fully covered day."""
    # Comment lines are stripped first: the fix's OWN comment quotes the removed expression
    # to explain it, and a bare substring check trips on its own explanation. Checking code
    # rather than prose is the point — a guard that cannot survive being documented is a
    # guard that discourages documenting.
    code = " ".join(l for l in _render_block().splitlines()
                    if not l.strip().startswith("//"))
    assert "cov.latest?.date" not in code, "the non-existent field is back"
    assert "sleeves complete" in code


def test_the_reader_payload_really_is_sleeve_keyed():
    """The claim above, checked against the producer rather than assumed."""
    from monitor.backend import track1_runtime_reader as trr
    cov = trr.read_track1_runtime(".")["window_coverage"]
    assert "latest" in cov and isinstance(cov["latest"], dict)
    assert "date" not in cov


def test_the_legacy_positions_endpoint_stays_labelled():
    app_src = Path("monitor/backend/app.py").read_text(encoding="utf-8")
    fn = app_src[app_src.index("def api_v1_runner_positions"):]
    fn = fn[:fn.index("@app.get", 10)]
    assert '"legacy"' in fn and "track1-runtime" in fn


# ══════════════════════════════════════════════════════════════════════════════
# C. the live audit and its three verdicts
# ══════════════════════════════════════════════════════════════════════════════

def test_the_verdict_vocabulary_is_distinct_from_the_check_status():
    """`FAIL` is the CHECK status "fail"; the verdict is "FAIL". Binding one name to both
    would have made every `c["status"] == FAIL` comparison in evaluate_day compare against a
    word no check emits, and every coverage failure would have stopped being seen."""
    assert acc.FAIL == "fail"
    assert acc.VERDICT_FAIL == "FAIL"
    assert acc.NOT_ENOUGH_DATA_YET == "NOT_ENOUGH_DATA_YET"
    assert acc.SHADOW_DAY_PASS == "SHADOW_DAY_PASS"


def test_a_window_that_closed_before_the_scheduler_started_is_pending_not_failed():
    """The live case: the scheduler came up at 04:32 ET and NKD closes at 02:55."""
    w = acc.windows_status("2026-08-24 05:00", scheduler_started_et="2026-08-24 04:32")
    nkd = w["global_nkd"]
    assert nkd["closed"] is True
    assert nkd["judgeable"] is False
    assert "AFTER the window closed" in nkd["reason"]


def test_a_window_that_has_not_closed_says_so_rather_than_citing_uptime():
    w = acc.windows_status("2026-08-24 05:00", scheduler_started_et="2026-08-24 04:32")
    assert w["roska4_calm"]["closed"] is False
    assert "has not closed yet" in w["roska4_calm"]["reason"]


def test_a_window_the_scheduler_joined_midway_is_pending():
    w = acc.windows_status("2026-08-24 13:00", scheduler_started_et="2026-08-24 11:00")
    st = w["roska4_stress"]
    assert st["closed"] is True and st["judgeable"] is False
    assert "inside the window" in st["reason"]


def test_a_fully_covered_closed_window_is_judgeable():
    w = acc.windows_status("2026-08-24 13:00", scheduler_started_et="2026-08-24 09:00")
    assert w["roska4_stress"]["judgeable"] is True


def test_nothing_judgeable_yet_is_not_enough_data_not_fail(tmp_path):
    """The requirement stated plainly: an audit run before the windows have been reached must
    not read as a broken route."""
    r = acc.audit_now(root=tmp_path, now_et="2026-08-24 05:00",
                      scheduler_started_et="2026-08-24 04:32")
    assert r["verdict"] == acc.NOT_ENOUGH_DATA_YET
    assert r["judgeable_sleeves"] == []
    assert set(r["coverage_pending"]) == {"roska4_calm", "roska4_stress", "roska4_swing",
                                          "global_nkd"}
    assert r["coverage_failed"] == []


def test_a_judgeable_window_with_no_coverage_is_a_fail(tmp_path):
    """The other side: once a window is judgeable, silence IS a failure — otherwise the
    audit could never say no."""
    r = acc.audit_now(root=tmp_path, now_et="2026-08-24 13:00",
                      scheduler_started_et="2026-08-24 09:00")
    assert r["verdict"] == acc.VERDICT_FAIL
    assert "roska4_stress" in r["coverage_failed"]


def test_an_order_mark_fails_regardless_of_how_far_the_day_got(tmp_path):
    """Hard failures are not deferred by 'not enough data'. An order in a shadow period is
    wrong at 05:00 exactly as much as at 16:00."""
    (tmp_path / acc.CONFIRMATION_PATH).write_text("{}", encoding="utf-8")
    r = acc.audit_now(root=tmp_path, now_et="2026-08-24 05:00",
                      scheduler_started_et="2026-08-24 04:32")
    assert r["verdict"] == acc.VERDICT_FAIL
    assert "no_orders" in r["hard_failures"]


def test_the_audit_writes_nothing_outside_scratch():
    import ast
    src = Path("scratch/track1_shadow_audit_20260824.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            name = getattr(n.func, "attr", getattr(n.func, "id", ""))
            if name in ("write_text", "write_bytes", "mkdir", "unlink"):
                seg = ast.get_source_segment(src, n) or ""
                assert "scratch/" in seg, f"writes outside scratch at line {n.lineno}"


# ══════════════════════════════════════════════════════════════════════════════
# D. orders stay impossible
# ══════════════════════════════════════════════════════════════════════════════

def test_orders_remain_blocked_and_nothing_arming_exists():
    from global_index import track1_gates as g
    # This pinned the exact roster — first one blocker, then two after Stage 5S added
    # PAPER_SHADOW_EVIDENCE — and went red when Stage 5ZL added a third. Pinning the roster is
    # how a dozen unrelated suites came to be red: every new blocker breaks every test that
    # listed the old set, and none of those tests is about the roster. The claim this test's
    # NAME makes is that orders are impossible and that B1 is one of the reasons; that is what
    # it now asserts. A blocker being ADDED is not a regression — a blocker disappearing is,
    # and that is still caught.
    #
    # Stage 5ZZW: a thirteenth instance of the same family, and the comment above already
    # explains it. B1 is CLOSED now, and it opens and closes with the age of the account
    # baseline record - it was blocking again for ninety minutes this morning purely because
    # that record passed its 24-hour policy. Naming it here pins a state that changes on a
    # timer. What the test is actually about is that orders are impossible and that something
    # MEASURED is holding them.
    blocking = g.as_ledger()["blocking_now"]
    assert "PAPER_SHADOW_EVIDENCE" in blocking, blocking
    assert g.may_enable_orders()[0] is False
    assert os.environ.get("TRACK1_ORDERS_APPROVED") is None
    # Stage 5ZZW. The confirmation file leaves this list for the reason Stage 5ZZS restated it
    # in four other suites: the operator signed it deliberately on 2026-08-27, and asserting
    # its absence asserts that nobody decided anything. The kill switch stays - nothing here
    # may create one - and a decision on disk must still be a SIGNED one.
    assert not Path("STOP_TRADING.track1").exists()
    conf = Path("track1_go_live_confirmation.json")
    if conf.exists():
        import json
        assert (json.loads(conf.read_text(encoding="utf-8")).get("confirmed_by") or "").strip(),             "an unsigned decision appeared on disk"
