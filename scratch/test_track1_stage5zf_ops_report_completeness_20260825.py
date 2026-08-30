"""Stage 5ZF — ops/report completeness before paper.

Audit-driven. Two small reader fixes came out of it and are tested here; everything else is a
finding pinned so it cannot silently change, including the findings that are NEGATIVE — a
report saying "Track 1 P&L is not implemented" is only worth anything if a test fails when
somebody implements it and forgets to update the report.

Read-only. No orders, no broker, no runtime write, nothing restarted.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]


def _lits(rel: str, *, max_len: int = 60) -> list:
    """Short string LITERALS from a file. Short, so a docstring paragraph that merely mentions
    a path is not mistaken for code that reads one — the substring-over-prose trap, again."""
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8", errors="replace"))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and len(n.value) < max_len and "\n" not in n.value]


# ══════════════════════════════════════════════════════════════════════════════
# 1. job inventory
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def registry():
    import warnings
    warnings.filterwarnings("ignore")
    from global_index import run_scheduler as rs
    return rs.make_scheduler(port=4002, dry_run=True, track1_only=True).get_jobs()


def _classify(jid: str) -> str:
    from global_index import track1_slots as t1
    j = jid.lower()
    if j in {s.id.lower() for s in t1.TRACK1_SLOTS}:
        return "track1_strategy"
    if j.startswith("track1_audit"):
        return "track1_audit"
    if j.startswith("track1_"):
        return "track1_safety"
    if j in set(t1.SHARED_INFRA_JOBS):
        return "shared_infra"
    if j.startswith(("stop_repair", "maxhold_exit")):
        return "legacy_drain_safety"
    return "UNCLASSIFIED"


def test_1_the_inventory_has_nothing_unclassified(registry):
    """Stage 5ZZS. The counts are DERIVED now, not written down.

    This test used to pin three literals - 70 strategy slots, 4 shared-infra jobs, 101 in
    total - and every one of them went stale: the slot table declares 71, and Stages 5ZZC/5ZZD
    added three SPY-ladder jobs that nobody classified. Pinning a number a table already knows
    means the test fails whenever the table grows, which is the opposite of what it is for.

    What must NOT drift is the exhaustiveness: a job matching no rule is unclassified, and
    unclassified must be empty. That is the one assertion here that can catch a job nobody has
    thought about, and it is the one kept literal-free.
    """
    import collections
    from global_index import track1_slots as t1
    c = collections.Counter(_classify(j.id) for j in registry)
    assert c["UNCLASSIFIED"] == 0, [j.id for j in registry
                                    if _classify(j.id) == "UNCLASSIFIED"]
    assert c["track1_strategy"] == len(t1.TRACK1_SLOTS)
    assert c["shared_infra"] == len(t1.SHARED_INFRA_JOBS)
    assert len(registry) == sum(c.values())
    # and the buckets that are neither route still exist rather than having been emptied
    assert c["track1_safety"] > 0 and c["track1_audit"] > 0 and c["legacy_drain_safety"] > 0


def test_2_no_legacy_strategy_job_is_registered(registry):
    legacy = [j.id for j in registry
              if j.id.lower().startswith(("live_day", "nkd_night"))]
    assert legacy == [], legacy


def test_3_legacy_drain_safety_is_still_scheduled(registry):
    """Retiring legacy strategy must NOT retire the sweeps that unwind its book."""
    drain = sorted(j.id for j in registry if _classify(j.id) == "legacy_drain_safety")
    assert len(drain) == 11
    assert "maxhold_exit" in drain
    assert sum(1 for d in drain if d.startswith("stop_repair")) == 10


def test_4_the_shared_infra_jobs_are_exactly_the_declared_ones(registry):
    """Stage 5ZZS. Derived from the table, not from four names copied out of it.

    Both directions matter and both are asserted: a job registered and treated as shared
    infrastructure without being declared, and a job declared but never registered. Pinning the
    names caught neither once the table grew - it just went red.
    """
    from global_index import track1_slots as t1
    shared = sorted(j.id for j in registry if _classify(j.id) == "shared_infra")
    assert shared == sorted(t1.SHARED_INFRA_JOBS), (
        "the registry's shared-infra jobs and the declared table have drifted apart")
    assert all((t1.SHARED_INFRA_JOBS[j] or "").strip() for j in shared), (
        "a shared-infra job with no stated reason for being one")
    # Against the PRODUCTION classifier, not this file's local copy of the rules. A mutation
    # that made `_bucket_for` answer "shared_infra" for everything left the suite green: the
    # inventory test only asks whether anything is UNCLASSIFIED, which such a mutation makes
    # trivially true, and every other check here runs on `_classify` above. Membership has to
    # be exact in both directions or "classified" means nothing.
    for j in registry:
        assert (t1._bucket_for(j.id) == "shared_infra") == (j.id in t1.SHARED_INFRA_JOBS), (
            j.id, t1._bucket_for(j.id), "bucketed as shared infrastructure without being "
            "declared as such, or declared and not bucketed")


# ══════════════════════════════════════════════════════════════════════════════
# 2. SPY_REFRESH_PM
# ══════════════════════════════════════════════════════════════════════════════

def test_5_spy_refresh_pm_emits_normal_job_evidence():
    """It goes through `_run`, so it produces the same started/completed/failed lines every
    other job does. No separate evidence system was needed, and none was built."""
    # Stage 5ZZS. Stage 5ZZC moved the body into `_spy_refresh` and the label became a
    # parameter, so an AST search for the literal "SPY_REFRESH_PM" beside `_run` finds nothing
    # - which said "no evidence is emitted" when the truth was "it is emitted one call deeper".
    # A test that reads one function body cannot survive the body moving; this follows the
    # delegation, which is what the claim was always about.
    tree = ast.parse((REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    job = fns["job_spy_refresh_pm"]
    delegated = [n.func.id for n in ast.walk(job)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and any(isinstance(a, ast.Constant) and a.value == "SPY_REFRESH_PM"
                         for a in n.args)]
    assert delegated, "the 16:20 job no longer names its own label anywhere"
    target = fns[delegated[0]]
    runs = [n for n in ast.walk(target) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "_run"
            and any(k.arg == "label" for k in n.keywords)]
    assert len(runs) == 1, f"{len(runs)} labelled _run call sites in {delegated[0]}"


def test_6_it_is_typed_as_its_own_job_not_preflight_and_not_dropped():
    from monitor.backend.job_journal_reader import _job_type
    assert _job_type("SPY_REFRESH_PM") == "spy_refresh_pm"
    assert _job_type("SPY_REFRESH_PM") != "preflight"
    assert _job_type("SPY_REFRESH_PM") != "other", (
        "back in the catch-all bucket: its failure would read 'unclassified error'")


def test_7_it_does_not_write_preflight_state():
    """Two different jobs, two different records. If this one wrote the pre-flight record, a
    failed pre-flight could be masked by a later success from a job that checks nothing."""
    tree = ast.parse((REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "job_spy_refresh_pm")
    called = {getattr(x.func, "id", getattr(x.func, "attr", None))
              for x in ast.walk(fn) if isinstance(x, ast.Call)}
    assert "_save_preflight_state" not in called
    touches = [x for x in ast.walk(fn) if isinstance(x, ast.Subscript)
               and isinstance(x.value, ast.Name) and x.value.id == "_preflight_ok"]
    assert touches == []


@pytest.mark.parametrize("status", ["failed", "missed"])
def test_8_its_failure_states_the_consequence_it_actually_has(status):
    from monitor.backend.job_journal_reader import _annotate_impact_and_action, _job_type
    jobs = [{"job_id": "SPY_REFRESH_PM", "job_type": _job_type("SPY_REFRESH_PM"),
             "status": status, "started_at": "2026-08-25T20:20:00Z",
             "ended_at": "2026-08-25T20:20:05Z", "reason": "x", "events": [],
             "diagnostics": [], "failed_runs": 1, "launch_count": 1}]
    _annotate_impact_and_action(jobs)
    impact, action = jobs[0]["impact"], jobs[0]["action"]
    assert "unclassified" not in impact.lower(), impact
    assert "SPY" in impact and "day short" in impact
    assert "freshness" in impact.lower()
    assert "rerun" in action.lower()


def test_9_it_is_mirrored_in_schedule_status():
    from monitor.backend import schedule_status as ss
    ids = [row[0] for row in ss.PIPELINE_FIXED_SLOTS]
    assert "SPY_REFRESH_PM" in ids
    hour, minute = next((h, m) for i, h, m in ss.PIPELINE_FIXED_SLOTS
                        if i == "SPY_REFRESH_PM")
    assert (hour, minute) == (16, 20)


# ══════════════════════════════════════════════════════════════════════════════
# 3. the stale runner label
# ══════════════════════════════════════════════════════════════════════════════

STALE_SNAPSHOT = dt.datetime(2026, 8, 24, 7, 0, tzinfo=dt.timezone.utc)


def _status(monkeypatch, *, track1_only: bool):
    from monitor.backend.schedule_status import get_schedule_status
    if track1_only:
        monkeypatch.setenv("RAITS_TRACK1_ONLY", "1")
    else:
        monkeypatch.delenv("RAITS_TRACK1_ONLY", raising=False)
    return get_schedule_status(REPO, observed_at=STALE_SNAPSHOT)


def test_10_a_stale_legacy_snapshot_no_longer_decides_track1_route_health(monkeypatch):
    """The alarm that never turned off.

    In track1-only shadow the legacy strategy jobs are deliberately not registered, so nothing
    ever writes the legacy state file and its age grows without bound — which drove the rail
    to "scheduler attention required" for the entire shadow period.
    """
    out = _status(monkeypatch, track1_only=True)
    assert out["freshness"] != "stale", (
        "the legacy snapshot is still deciding the route's health")
    assert out["route_mode"] == "track1_only_shadow"


def test_11_outside_track1_only_the_old_behaviour_is_unchanged(monkeypatch):
    """A fix that changed the legacy route's own health reading would be a different bug."""
    out = _status(monkeypatch, track1_only=False)
    assert out["freshness"] == "stale"
    assert out["route_mode"] == "legacy"


def test_12_the_staleness_is_demoted_not_hidden(monkeypatch):
    out = _status(monkeypatch, track1_only=True)
    lr = out["legacy_runner"]
    assert lr["inactive_by_design"] is True
    assert lr["state_stale"] is True, "the fact itself must still be reported"
    assert lr["state_age_seconds"] > 0
    assert "draining" in lr["reading"] or "inactive" in lr["reading"]
    assert lr["drain_safety_still_scheduled"] is True


def test_13_the_route_health_now_comes_from_track1_evidence(monkeypatch):
    """Not merely 'not stale' — it must be answering from the Track 1 slots.

    Today that answer is `late`, and it is correct: the machine slept through the 10:00 Calm
    slot and the first Stress slots, and they are named in `unexplained_overdue`.
    """
    from global_index import track1_slots as t1
    out = _status(monkeypatch, track1_only=True)
    # Stage 5ZZS: derived. The literal 70 was written when the table held 70; it holds 71 now,
    # and an earlier stage had already recorded the mismatch between what the running scheduler
    # logged and what the code declared. The claim is that the mirror tracks THE TRACK 1 SLOTS,
    # so it is asserted against the table rather than against a number copied out of it.
    assert out["state_slot_count"] == len(t1.TRACK1_SLOTS), (
        "the mirror should be tracking the Track 1 slots")
    overdue = out.get("unexplained_overdue") or []
    if overdue:
        assert any(str(o.get("slot_id", "")).startswith("TRACK1_") for o in overdue), overdue


def test_14_the_rail_no_longer_fires_on_an_inactive_legacy_runner():
    js = (REPO / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    seg = js.split("const stripScheduleBad =")[1].split(";")[0]
    assert "legacyInactive" in seg
    assert "stripFreshness === 'stale' && !legacyInactive" in seg
    assert "stripFreshness === 'missing' && !legacyInactive" in seg
    # and a genuine late is still an alarm
    assert "stripFreshness === 'late'" in seg


# ══════════════════════════════════════════════════════════════════════════════
# 4. route-aware report / Flex / P&L — the NEGATIVE findings, pinned
# ══════════════════════════════════════════════════════════════════════════════
#
# These assert that Track 1 support is ABSENT. If someone implements it, they fail — which is
# the point: the report claims it is missing, and a claim nobody can falsify is not a finding.

@pytest.mark.parametrize("rel", ["global_index/session_report.py",
                                 "monitor/flex_pull.py"])
def test_15_the_report_and_flex_paths_are_still_not_route_aware(rel):
    """Stage 5ZM took `monitor/paper_pnl_compare.py` off this list.

    It does not READ Track 1 paths — it still reads only legacy's book and legacy's log — but
    it now EXCLUDES rows carrying another route's tag, so it names `track1_candidate` and the
    original assertion could not tell the two apart. The two that remain know nothing about
    the route at all, which is what this test was written to hold.
    """
    src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            imports.add(getattr(n, "module", "") or "")
            imports |= {a.name for a in n.names}
    track1_imports = sorted(m for m in imports if "track1" in (m or ""))
    track1_paths = sorted(l for l in _lits(rel) if "track1" in l)
    assert track1_imports == [], (
        f"{rel} now imports Track 1 modules — the Stage 5ZF report says it does not")
    assert track1_paths == [], (
        f"{rel} now reads Track 1 paths — the Stage 5ZF report says it does not")


def test_15b_the_pnl_report_excludes_foreign_rows_without_reading_track1_paths():
    """Stage 5ZM. The distinction the parametrized test above could not draw: a report that
    EXCLUDES another route's rows is not a report that READS that route's artefacts."""
    import monitor.paper_pnl_compare as ppc

    assert ppc.FOREIGN_ROUTES == ("track1_candidate",)
    paths = sorted(l for l in _lits("monitor/paper_pnl_compare.py")
                   if "track1" in l and (l.endswith(".json") or l.endswith(".jsonl")
                                         or "/" in l))
    assert paths == [], f"the legacy P&L report reads Track 1 artefacts: {paths}"


def test_16_the_pnl_comparison_reads_the_legacy_book_and_legacy_trade_log():
    lits = _lits("monitor/paper_pnl_compare.py")
    assert "live_positions.json" in lits
    assert "trade_log.jsonl" in lits
    assert not any("live_positions.track1.json" == l for l in lits)


def test_17_track1_safety_exits_no_longer_hardcode_the_legacy_trade_log():
    """CLOSED by Stage 5ZG — this test was the tripwire and it fired.

    As written on 2026-08-25 it asserted the opposite: both safety jobs ran against
    `live_positions.track1.json` and both hardcoded the legacy trade log, so the first
    Track 1 fill either of them closed would have left a CLOSE row in the legacy log,
    indistinguishable from a legacy row. It carried "if this becomes route-aware the
    report is stale", and hours later it did.

    Kept, inverted, rather than deleted: the shape of the defect is worth a permanent
    guard. What Stage 5ZG chose, and what the argv actually carries, is measured in
    `test_track1_stage5zg_route_aware_safety_reporting_20260825.py`.
    """
    for rel in ("global_index/run_maxhold_exit.py", "global_index/run_stop_repair.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        kw = [k for n in ast.walk(tree) if isinstance(n, ast.Call)
              for k in n.keywords if k.arg == "trade_log_path"]
        assert kw, f"{rel} no longer passes trade_log_path"
        rendered = ast.unparse(kw[0].value)
        assert "trade_log.jsonl" not in rendered, (
            f"{rel} went back to a hardcoded legacy destination: {rendered}")


def test_18_the_track1_entry_point_still_writes_no_legacy_path():
    """It guards them by name; the literal in that file is the guard list, not a write."""
    from global_index import run_live_day_track1 as R
    assert "trade_log.jsonl" in R.LEGACY_PATHS
    assert "live_positions.json" in R.LEGACY_PATHS


def test_19_there_is_still_no_track1_scoped_pnl_output():
    """Stage 5ZG gave the route its own trade log; it gave it no reader.

    The log is named by one constant and lives under the Track 1 runtime root, so the
    repo-root filename this test originally guessed at was never going to appear. The
    P&L side is the part still missing, and that is what is asserted now — the five
    remaining reporting pieces are unchanged.
    """
    from global_index import track1_slots as ts
    assert ts.TRACK1_TRADE_LOG_PATH.startswith("global_index/track1_runtime/")
    assert not (REPO / "trade_log.track1.jsonl").exists(), (
        "a second Track 1 trade log appeared at the repo root — there must be exactly one")
    assert not (REPO / "monitor/paper_pnl_compare.track1.json").exists()


# ══════════════════════════════════════════════════════════════════════════════
# 5. regime labels and the two SPY refreshes
# ══════════════════════════════════════════════════════════════════════════════

def test_20_the_spy_csv_is_a_close_series_only():
    head = (REPO / "spy_daily_live.csv").read_text(encoding="utf-8").splitlines()[0]
    assert head.strip() == "date,close"


def test_21_regime_labels_are_computed_on_read_and_never_persisted():
    """So there is no materialisation step that could lag behind a SPY update — which is the
    whole reason both refresh times are sufficient."""
    tree = ast.parse((REPO / "global_index/regime.py").read_text(encoding="utf-8"))
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("to_csv", "to_parquet", "write_text", "write_bytes", "dump")]
    assert writes == [], "labels are being persisted; both refreshes must now be re-checked"
    assert not list((REPO / "global_index").glob("*regime_label*"))


def test_22_the_1345_refresh_is_not_expected_to_carry_todays_close():
    """It runs before the close. A requirement that asked for today's bar at 13:45 could only
    be met by luck, and the gate deliberately does not."""
    from global_index.track1_freshness import required_daily_close_through
    at_1345 = pd.Timestamp("2026-08-25 13:45")
    need = required_daily_close_through(at_1345)
    assert need < at_1345.normalize(), (need, at_1345)


def test_23_after_the_1620_refresh_tomorrow_has_the_label_it_needs():
    from global_index.track1_freshness import required_daily_close_through
    # Tuesday's post-close refresh writes Tuesday's close; Wednesday morning needs exactly it.
    need_wed = required_daily_close_through(pd.Timestamp("2026-08-26 09:00"))
    assert str(need_wed.date()) == "2026-08-25"


def test_24_monday_reads_fridays_label_across_the_weekend():
    from global_index.regime import RegimeLabels
    s = pd.Series({pd.Timestamp("2026-08-20"): "Calm",
                   pd.Timestamp("2026-08-21"): "Normal"})
    labels = RegimeLabels(s, lag_days=1)
    assert labels.get(pd.Timestamp("2026-08-24")) == "Normal", "Monday must read Friday"
    from global_index.track1_freshness import required_daily_close_through
    assert str(required_daily_close_through(pd.Timestamp("2026-08-24 09:00")).date()) \
        == "2026-08-21"


def test_25_holidays_use_the_same_trading_calendar_as_the_requirement():
    import inspect
    from global_index import track1_freshness as fresh
    src = inspect.getsource(fresh.required_daily_close_through)
    assert "prev_trading_day" in src
    assert callable(getattr(fresh, "prev_trading_day", None))


def test_26_label_verification_is_currently_only_a_warning():
    """Pinned as a FINDING, not endorsed.

    CLOSED by Stage 5ZL — this test was the tripwire and it fired.

    As written on 2026-08-25 it asserted the defect: every failure path in
    `verify_regime_labels` returned 0 and logged a warning, including the paths where it could
    not verify at all, so "verified, no drift" and "could not check" produced the same value.
    It carried "if this now raises, the Stage 5ZF finding is closed and the report needs
    updating", and a day later it did.

    Kept, inverted, rather than deleted: the shape of the defect is worth a permanent guard.
    What Stage 5ZL built, and what each of the old collapse paths returns now, is measured in
    `test_track1_stage5zl_regime_tristate_20260826.py`.
    """
    from global_index.update_spy_csv import verify_regime_labels
    from global_index import regime_verify as rv
    import inspect

    src = inspect.getsource(verify_regime_labels)
    tree = ast.parse(src)
    fn = tree.body[0]
    zero_returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)
                    and isinstance(n.value, ast.Constant) and n.value.value == 0]
    assert zero_returns == [], (
        "the verification returns a bare 0 again — 'could not check' and 'no drift' are the "
        "same number once more")
    # and the three answers exist where a count used to be
    assert rv.STATUSES == ("PASS", "DRIFT", "UNKNOWN")
    assert rv.CODE_STATUS[rv.NO_ENGINE] == rv.UNKNOWN


def test_27_a_label_drift_is_now_visible_as_a_job_failure():
    """Also inverted by Stage 5ZL. The result is kept, and one caller exits non-zero on it.

    Not both callers: the 13:45 pre-flight gates the whole trading day and a verification that
    could not run must not skip every slot, so only the 16:20 post-close refresh — which gates
    nothing — runs strict. That split is deliberate and is asserted in the 5ZL suite.
    """
    import ast as _ast
    from global_index import update_spy_csv as u
    import inspect

    tree = _ast.parse(inspect.getsource(u))
    fn = next(n for n in _ast.walk(tree)
              if isinstance(n, _ast.FunctionDef) and n.name == "update_spy_csv")
    discarded = [n for n in _ast.walk(fn) if isinstance(n, _ast.Expr)
                 and isinstance(n.value, _ast.Call)
                 and getattr(n.value.func, "id", "") == "verify_regime_labels"]
    assert discarded == [], "the verification result is discarded again"

    # Stage 5ZZS. `--verify-strict` did not disappear - Stage 5ZZC moved it out of the job
    # body and into `_spy_refresh`, which builds the command for every rung. Reading only the
    # job body reported the flag as GONE, which would have been a serious finding had it been
    # true. Follow the delegation and assert on the code that actually builds the command.
    sched = _ast.parse((REPO / "global_index" / "run_scheduler.py").read_text(encoding="utf-8"))
    sfns = {n.name: n for n in _ast.walk(sched) if isinstance(n, _ast.FunctionDef)}
    pm = sfns["job_spy_refresh_pm"]
    reached = _ast.unparse(pm) + "".join(
        _ast.unparse(sfns[n.func.id]) for n in _ast.walk(pm)
        if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name) and n.func.id in sfns)
    assert "--verify-strict" in reached, (
        "the post-close refresh no longer runs strict, so a drift exits 0 again")
    # The 16:20 rung must NOT skip when the day is already covered - checking the labels is
    # part of what that run is for, and skipping would make the strict flag unreachable.
    assert "attempt=1" in _ast.unparse(pm), "the 16:20 rung is no longer the first attempt"


# ══════════════════════════════════════════════════════════════════════════════
# 6. nothing was armed, nothing was written
# ══════════════════════════════════════════════════════════════════════════════

def test_28_orders_are_still_impossible():
    """Stage 5ZZS - restated for the post-B1 world, and deliberately not weakened.

    B1 is closed, so "B1 blocks" is no longer the invariant. Two stronger ones replace it:
    orders remain impossible with PAPER_SHADOW_EVIDENCE holding, and B1 closed because a
    MEASUREMENT passed and not because a file was signed. Take the signature away and B1 must
    come back - that is the assertion a signature alone could never satisfy.
    """
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in ids

    # unsigned, B1 returns - the gate is not taking the file's word for it
    unsigned = [b.id for b in G.blocking(G.NO_CONFIRMATIONS)]
    assert "B1_broker_account_or_legacy_retirement" in unsigned
    assert "PAPER_SHADOW_EVIDENCE" in unsigned

    # The measured half of B1 is CONSULTED - not necessarily passing right now.
    #
    # Stage 5ZZU had to correct this. It was written as `assert ok is True`, which pinned the
    # state of a live, ageing record as though it were an invariant, and it went red nineteen
    # hours later: measured 2026-08-28T11:31:07Z, the account baseline record passed its
    # 24-hour freshness policy 81 seconds earlier and B1 reopened. That is the gate working,
    # and `test_28b` is the test that says so. What belongs here is that the measurement is a
    # real two-valued answer with a reason attached, whichever way it currently reads.
    ok, why = G.b1_decision_evidence(".")
    assert isinstance(ok, bool), why
    assert (why or "").strip(), "a measurement that gives no reason cannot be acted on"

    # a valid confirmation on disk is expected now; what it must NOT do is imply an order
    conf, errors = G.load_confirmations(G.CONFIRMATION_PATH)
    if (REPO / G.CONFIRMATION_PATH).exists():
        assert errors == [], errors
        assert conf.get("legacy_retired_confirmed") is True
    assert allowed is False, "a signed confirmation must not open orders on its own"
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")


def test_28b_b1_reopens_when_the_measurement_fails_even_though_it_is_signed():
    """Stage 5ZZS. The other half of "closed by a decision AND a measurement".

    `test_28` shows the SIGNATURE is necessary: take it away and B1 returns. This shows the
    MEASUREMENT is necessary: leave the signature in place, make the composite fail, and B1
    must return anyway. Written because a mutation that waived the measurement entirely left
    every test in this suite green - the suite was asserting one half of the rule twice.
    """
    from global_index import track1_gates as G

    conf = G.current_confirmations()
    assert conf.get("legacy_retired_confirmed") is True, "precondition: the decision is signed"

    # Stage 5ZZU: BOTH directions are driven here rather than one being read off today's
    # records. The original version asserted "B1 is closed right now" as its precondition and
    # went red when the account baseline aged past its 24-hour policy overnight - a true fact
    # about the day, and no kind of statement about the rule.
    real = G.MEASUREMENTS["b1_decision_evidence"]
    B1 = "B1_broker_account_or_legacy_retirement"
    try:
        G.MEASUREMENTS["b1_decision_evidence"] = lambda: (True, "measurement passing")
        assert B1 not in [b.id for b in G.blocking(conf)], (
            "a signed decision with a PASSING measurement must close B1")

        G.MEASUREMENTS["b1_decision_evidence"] = lambda: (False, "the account is not flat")
        assert B1 in [b.id for b in G.blocking(conf)], (
            "a signed decision closed B1 while its measurement was failing")
    finally:
        G.MEASUREMENTS["b1_decision_evidence"] = real

    # and the restore worked, so this test leaves the registry as it found it
    assert G.MEASUREMENTS["b1_decision_evidence"] is real


def test_28c_no_signature_or_variable_can_release_what_is_holding_orders():
    """Stage 5ZZS. "The approval variable alone must not open orders", made falsifiable.

    Written because a mutation that made `may_enable_orders` return True whenever
    TRACK1_ORDERS_APPROVED is set stayed GREEN across this whole suite: every test asserted the
    variable was UNSET, and none asserted what would happen if it were. An assertion about the
    environment is not an assertion about the gate.

    Nothing here sets the variable. The claim is structural and therefore stronger: whatever is
    currently holding orders shut is held by a MEASUREMENT that no confirmation flag lists, and
    the registry does not consult the environment on its way to that answer.
    """
    import inspect
    from global_index import track1_gates as G

    allowed, reasons = G.may_enable_orders()
    assert allowed is False
    held = [G.BLOCKERS[r.split(":")[0]] for r in reasons]
    assert held, reasons

    for b in held:
        assert b.blocks_orders is True, b.id
        if b.status == "MEASURED_GATE":
            assert b.released_by == (), (b.id, "a measured gate a signature could release")
            assert b.released_by_measurement, (b.id, "a measured gate with no measurement")
        else:
            assert b.also_requires_measurement, (
                b.id, "a decision gate a signature alone could open")

    src = inspect.getsource(G.may_enable_orders) + inspect.getsource(G.blocking)
    assert "environ" not in src and "getenv" not in src, (
        "the order gate reads the environment; an out-of-band approval is not a release")


def test_29_this_stage_added_no_arming_flag():
    for rel in ("global_index/run_scheduler.py", "monitor/ops.py",
                "monitor/backend/schedule_status.py",
                "monitor/backend/job_journal_reader.py"):
        lits = [n for n in ast.walk(ast.parse(
                    (REPO / rel).read_text(encoding="utf-8", errors="replace")))
                if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
        assert lits == [], rel


def test_30_no_order_journal_or_book_exists():
    """Stage 5ZZS. The confirmation file is no longer among the things that must be absent.

    Stage 5ZZJ placed it as a deliberate operator decision, so asserting its absence asserted
    that the operator had not decided - a claim this suite has no business making. The order
    ARTEFACTS are a different matter: nothing may have written an order journal or a Track 1
    position book, and those assertions stand untouched.
    """
    assert not (REPO / "global_index/track1_runtime/orders").exists()
    assert not (REPO / "global_index/live_positions.track1.json").exists()
    # If the decision is on disk it must be the operator's signed one, not something a run
    # dropped there: unreadable or unsigned, it would grant nothing and hide that it had.
    conf_path = REPO / "track1_go_live_confirmation.json"
    if conf_path.exists():
        from global_index import track1_gates as G
        conf, errors = G.load_confirmations(G.CONFIRMATION_PATH)
        assert errors == [], errors
        assert (conf.confirmed_by or "").strip(), "a decision with no signatory"
        assert (conf.confirmed_at or "").strip(), "a decision with no date"
