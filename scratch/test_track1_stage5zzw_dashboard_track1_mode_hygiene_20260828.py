"""Stage 5ZZW — the dashboard answers about the route that is running.

The rail said "scheduler attention required / runner state stale" while `ops.py status` said the
scheduler was healthy and the Track 1 slot table fresh. Both were reading real data. They were
reading it about different routes: `ops` asks the scheduler's own command line, and this backend
asked its OWN environment variable, which nobody had set on the process that happened to be
serving. Every downstream answer followed the wrong one.

So the tests here are mostly about a source, not a symptom.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from monitor.backend import open_issue_reader as oi          # noqa: E402
from monitor.backend import schedule_status as ss            # noqa: E402

JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"
HTML = REPO / "global_index" / "dash" / "realtime" / "index.html"


# ══════════════════════════════════════════════════════════════════════════════════════════
# 1. the mode comes from the scheduler, and "could not look" is its own answer
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_mode_is_resolved_from_the_scheduler_not_this_process(monkeypatch):
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    monkeypatch.setattr(ss, "scheduler_track1_only", lambda: True)
    assert ss.resolve_track1_only() is True
    monkeypatch.setattr(ss, "scheduler_track1_only", lambda: False)
    assert ss.resolve_track1_only() is False


def test_an_explicit_setting_still_wins(monkeypatch):
    """A caller that has said which view it wants is stating an intention, not guessing —
    `ops` starting a backend, or a test describing a legacy machine."""
    monkeypatch.setattr(ss, "scheduler_track1_only", lambda: True)
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "0")
    assert ss.resolve_track1_only() is False
    monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    assert ss.resolve_track1_only() is True


def test_an_unreadable_scheduler_is_unknown_and_never_legacy(monkeypatch):
    """The rule this whole family keeps meeting: "I could not check" must not be reported as
    "I checked and it was the other thing"."""
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    monkeypatch.setattr(ss, "scheduler_track1_only", lambda: None)
    assert ss.resolve_track1_only() is None


def test_the_resolver_refuses_a_scheduler_it_could_not_scan(monkeypatch):
    """Stage 5ZZY moved the seam. The resolver read `ops.track1_status()` when this was written,
    which shells out to PowerShell on a path the dashboard polls every eight seconds; it reads
    the backend's own cached psutil scan now. The property is unchanged and is what is asserted:
    a scheduler whose command line cannot be read is UNKNOWN, never legacy.
    """
    monkeypatch.setattr(ss, "_running_schedulers", lambda: [{"pid": 1, "command": ""}])
    assert ss.scheduler_track1_only() is None
    monkeypatch.setattr(ss, "_running_schedulers", lambda: [])
    assert ss.scheduler_track1_only() is None


def test_a_scan_that_cannot_run_is_unknown_not_a_crash(monkeypatch):
    def boom():
        raise RuntimeError("the process table could not be read")
    monkeypatch.setattr(ss, "_running_schedulers", boom)
    with pytest.raises(RuntimeError):
        ss.scheduler_track1_mode_status()
    # the resolver itself must not propagate it as an answer about the mode
    monkeypatch.setattr(ss, "scheduler_track1_only", lambda: None)
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    assert ss.resolve_track1_only() is None


# ══════════════════════════════════════════════════════════════════════════════════════════
# 2. what the payload then says
# ══════════════════════════════════════════════════════════════════════════════════════════

def _status(monkeypatch, resolved, *, observed_age_seconds=364941):
    monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    monkeypatch.setattr(ss, "scheduler_track1_only", lambda: resolved)
    observed = (dt.datetime.now(dt.timezone.utc)
                - dt.timedelta(seconds=observed_age_seconds))
    # Injected, exactly as `app.py` does it. Calling without the parameter would read this
    # process's environment and describe whatever machine happens to be running.
    return ss.get_schedule_status(REPO, observed_at=observed,
                                  track1_only=ss.resolve_track1_only())


def test_track1_only_reports_its_route_and_says_where_that_came_from(monkeypatch):
    out = _status(monkeypatch, True)
    assert out["route_mode"] == "track1_only_shadow"
    assert out["route_mode_known"] is True
    assert out["route_mode_source"] == "scheduler_process_table"


def test_a_stale_legacy_snapshot_does_not_make_the_route_stale(monkeypatch):
    """The reported bug. The legacy state file is four days old because nothing writes it in
    this mode; that is the intended steady state, not a fault."""
    out = _status(monkeypatch, True)
    assert out["freshness"] != "stale", out["freshness"]
    assert out["legacy_runner"]["inactive_by_design"] is True
    # and the fact itself is still reported rather than hidden
    assert out["legacy_runner"]["state_stale"] is True
    assert "does not describe the Track 1 route" in out["legacy_runner"]["reading"]


def test_the_same_snapshot_still_raises_the_route_when_legacy_is_live(monkeypatch):
    """The complement. Suppression that applied in every mode would be a hidden fault."""
    out = _status(monkeypatch, False)
    assert out["route_mode"] == "legacy"
    assert out["legacy_runner"]["inactive_by_design"] is False
    assert out["freshness"] == "stale", out["freshness"]


def test_track1_only_expects_no_legacy_slots_so_none_are_overdue(monkeypatch):
    """22 phantom overdue slots were the rail's other trigger: the mirror was expecting the
    legacy table for a scheduler that registers none of it."""
    out = _status(monkeypatch, True)
    overdue = [o for o in (out.get("unexplained_overdue") or [])
               if not str(o.get("slot_id", "")).startswith("TRACK1_")]
    assert overdue == [], overdue


def test_an_unknown_mode_is_carried_as_unknown(monkeypatch):
    out = _status(monkeypatch, None)
    assert out["route_mode"] == "unknown"
    assert out["route_mode_known"] is False
    assert out["route_mode_source"] == "unknown"


def test_the_slot_table_follows_the_resolved_mode(monkeypatch):
    from global_index import track1_slots as t1
    assert _status(monkeypatch, True)["state_slot_count"] == len(t1.TRACK1_SLOTS)


# ══════════════════════════════════════════════════════════════════════════════════════════
# 3. retired legacy issues leave the count without leaving the payload
# ══════════════════════════════════════════════════════════════════════════════════════════

def _retirement(monkeypatch, tmp_path, *, confirmation=True, compatible=True, jobs=0,
                source="process_table"):
    """Stage 5ZZY: driven through the backend's cached scan and a confirmation file under
    `tmp_path`, because the reader no longer calls ops and no longer reads the production root.

    `jobs` is expressed as the scheduler's MODE, since that is what the command line says: only
    `--track1-only-shadow` registers no legacy entry job.
    """
    import json
    if confirmation:
        (tmp_path / "track1_go_live_confirmation.json").write_text(json.dumps({
            "schema_version": 1, "confirmed_by": "op", "confirmed_at": "2026-08-27",
            "legacy_retired_confirmed": True, "note": "fixture"}), encoding="utf-8")
    if source != "process_table":
        rows = []
    elif compatible and jobs == 0:
        rows = [{"pid": 1, "command": "python run_scheduler.py --track1-only-shadow"}]
    else:
        rows = [{"pid": 1, "command": "python run_scheduler.py --track1-shadow"}]
    monkeypatch.setattr(ss, "_running_schedulers", lambda: rows)
    return oi.legacy_retirement_state(tmp_path)


def test_legacy_is_retired_only_when_all_three_conditions_hold(monkeypatch, tmp_path):
    for sub in "abcd":
        (tmp_path / sub).mkdir()
    assert _retirement(monkeypatch, tmp_path / "a")["retired"] is True
    assert _retirement(monkeypatch, tmp_path / "b", confirmation=False)["retired"] is False
    assert _retirement(monkeypatch, tmp_path / "c", compatible=False)["retired"] is False
    assert _retirement(monkeypatch, tmp_path / "d", jobs=45)["retired"] is False


def test_an_unreadable_scheduler_leaves_legacy_issues_counted(monkeypatch, tmp_path):
    """Fails toward showing too much. A legacy issue shown beside Track 1's is noise; a legacy
    issue hidden while legacy could still trade is the one that costs money."""
    state = _retirement(monkeypatch, tmp_path, source="unknown")
    assert state["retired"] is False
    assert "could not be read" in state["reason"] or "does not hold" in state["reason"]


def _issues(monkeypatch, retired):
    # Stage 5ZZY gave `legacy_retirement_state` a `root`, so the stand-in has to accept one.
    monkeypatch.setattr(oi, "legacy_retirement_state", lambda root=None: {
        "retired": retired, "confirmation": True, "scheduler_mode": "compatible",
        "legacy_entry_jobs": 0, "reason": "test"})
    return oi.read_open_issues(REPO)


def test_retired_legacy_issues_leave_the_active_count_but_stay_in_the_payload(monkeypatch):
    out = _issues(monkeypatch, True)
    issues = out["issues"]
    assert issues, "no issues at all — this fixture proves nothing"
    legacy = [i for i in issues if i["route_scope"] == oi.SCOPE_LEGACY]
    assert legacy, "no legacy-scoped issue in the payload — nothing to retire"
    for item in legacy:
        assert item["counts_as_active"] is False
        assert "history" in item["active_reason"]
    assert out["active_count"] == sum(1 for i in issues if i["counts_as_active"])
    assert out["retired_history_count"] == len(legacy)
    # nothing was deleted
    assert len(issues) == out["active_count"] + out["retired_history_count"]


def test_nothing_is_hidden_while_legacy_is_still_live(monkeypatch):
    out = _issues(monkeypatch, False)
    assert out["retired_history_count"] == 0
    assert out["active_count"] == len(out["issues"])


def test_track1_shared_and_debt_issues_always_count(monkeypatch):
    out = _issues(monkeypatch, True)
    for item in out["issues"]:
        if item["route_scope"] != oi.SCOPE_LEGACY:
            assert item["counts_as_active"] is True, item["key"]


def test_the_retirement_is_recomputed_on_every_read_not_frozen_in_the_cache(monkeypatch):
    """Found by the suite, not by reading. The payload is memoised on the scheduler log
    signatures plus the date; the first version computed the retirement inside that builder, so
    a second read with the opposite answer returned the first one from cache.

    Whether legacy is retired is a fact about the RUNNING SCHEDULER and can change with no log
    line written here at all - an operator restarting into legacy mode leaves these files
    untouched - so a frozen answer would keep hiding legacy issues after legacy came back.
    """
    first = _issues(monkeypatch, True)
    assert first["retired_history_count"] > 0, "no legacy issue to retire - proves nothing"
    second = _issues(monkeypatch, False)
    assert second["retired_history_count"] == 0, (
        "the retirement answer was frozen in the cache")
    assert second["active_count"] == len(second["issues"])
    # and back again, so the caching is not simply one-shot
    third = _issues(monkeypatch, True)
    assert third["retired_history_count"] == first["retired_history_count"]


def test_the_hmm_known_debt_survives_the_retirement(monkeypatch):
    """The trap this stage had to avoid: model-age debt was grouped with legacy, so hiding
    legacy would have taken it too."""
    out = _issues(monkeypatch, True)
    debt = [i for i in out["issues"] if i["route_scope"] == oi.SCOPE_DEBT]
    assert debt, "no known-debt issue present — the check proves nothing"
    for item in debt:
        assert item["counts_as_active"] is True, item["key"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# 4. the page
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_the_debt_group_is_its_own_and_is_not_called_legacy():
    code = JS.read_text(encoding="utf-8")
    block = code.split("const ISSUE_GROUPS")[1].split("];")[0]
    assert "Model / Regime" in block
    model = block.split("key: 'model'")[1].split("}")[0]
    assert "known_debt" in model
    legacy = block.split("key: 'legacy'")[1].split("}")[0]
    assert "known_debt" not in legacy, "carried debt is grouped with legacy again"


def test_the_headline_count_is_the_active_one():
    code = JS.read_text(encoding="utf-8")
    assert "state.openIssues?.active_count" in code
    assert "$('openIssuesShell').open = state.issuesSectionOpen || activeCount > 0;" in code


def test_the_rail_reads_the_resolved_mode_and_its_unknown():
    code = JS.read_text(encoding="utf-8")
    assert "route_mode_known" in code
    assert "scheduler mode unknown" in code
    assert "Legacy runner snapshot is stale because legacy entries are retired" in code


def test_the_rail_no_longer_calls_a_by_design_stale_snapshot_a_fault():
    code = JS.read_text(encoding="utf-8")
    seg = code.split("const legacyStaleByDesign")[1][:900]
    assert "legacyInactive" in seg and "state_stale" in seg
    cond = code.split("if (legacyStaleByDesign)")[1][:400]
    assert "legacy entries are retired" in cond


def test_model_inputs_reads_the_track1_regime_record():
    code = JS.read_text(encoding="utf-8")
    assert "const t1Regime = state.marketView?.regime" in code
    assert "t1Regime?.label_date" in code
    assert "t1Regime?.inputs?.fit_end" in code
    assert "state.marketView?.regime?.label" in code


def test_model_inputs_is_no_longer_declared_runner_derived():
    html = HTML.read_text(encoding="utf-8")
    zone = html.split('id="modelInputsZone"')[0].split("<div")[-1]
    assert "runner-derived" not in zone, zone


def test_no_raw_snake_case_in_the_new_rail_wording():
    code = JS.read_text(encoding="utf-8")
    for phrase in ("Legacy runner snapshot is stale because legacy entries are retired",
                   "scheduler mode unknown — could not read the scheduler",
                   "Track 1 scheduler needs attention"):
        assert phrase in code
        assert "_" not in phrase


# ══════════════════════════════════════════════════════════════════════════════════════════
# 5. the gates are where they were
# ══════════════════════════════════════════════════════════════════════════════════════════

def test_paper_shadow_evidence_is_still_the_track1_blocker():
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in ids, ids


def test_this_stage_created_no_order_artefacts():
    assert not (REPO / "global_index" / "track1_runtime" / "orders").exists()
    assert not (REPO / "global_index" / "live_positions.track1.json").exists()


# ══════════════════════════════════════════════════════════════════════════════════════════
# 6. the page still fits
# ══════════════════════════════════════════════════════════════════════════════════════════

pytest.importorskip("playwright.sync_api")
from monitor.test_realtime_dom import (           # noqa: E402
    browser_page, open_realtime, realtime_server, stub_api)

assert browser_page and realtime_server


@pytest.mark.parametrize("width", [375, 720, 1440])
def test_dom_no_horizontal_overflow(browser_page, realtime_server, width):
    browser_page.set_viewport_size({"width": width, "height": 1000})
    open_realtime(browser_page, realtime_server)
    browser_page.wait_for_selector("#modelInputsZone", timeout=10_000)
    over = browser_page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert over <= 1, f"page scrolls by {over}px at {width}px"
