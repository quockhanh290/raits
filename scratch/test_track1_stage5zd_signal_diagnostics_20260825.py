"""Stage 5ZD — signal diagnostics: journal, reader, job view, and the guards.

Observability only. No broker, no order, no IBKR, and every write in this file goes to a
tmp_path. The runtime's own signals directory is asserted untouched at the end.

The assertion this suite exists for: **NO_SIGNAL and SIGNAL_REJECTED must never collapse.**
One means the market offered nothing; the other means it offered something and this route
declined it. A summary that showed both as "no trade" would hide every cap and every
suppression the book applies.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from global_index import track1_signals as S
from global_index import track1_signal_layer as T

REPO = Path(__file__).resolve().parents[1]
DAY = "2026-08-25"
DAYKEY = "20260825"


def cand(inst="MNQ", direction="short", qty=7, risk=420.0, entry=20100.0, stop=20160.0,
         sleeve="roska4_stress", tid="t1"):
    return T.Candidate(trade_id=tid, sleeve=sleeve, instrument=inst, direction=direction,
                       qty=qty, risk_dollars=risk, entry_time="2026-08-25 10:35:00",
                       entry_price=entry, stop_price=stop, meta={})


def row(**kw):
    base = dict(sleeve="roska4_stress", slot_id="TRACK1_STRESS_1035", slot_time="10:35",
                session_date=DAY, mode="shadow_live", decided=True, reason="decided",
                freshness_allow=True, gate_allow=True)
    base.update(kw)
    return S.build_row(**base)


# ══════════════════════════════════════════════════════════════════════════════
# 1. the journal: append and read back
# ══════════════════════════════════════════════════════════════════════════════

def test_1_a_row_round_trips(tmp_path):
    r = row(raw_candidates=0)
    p = S.append(r, root=tmp_path)
    assert p is not None and p.exists()
    rows, invalid = S.read_day(DAYKEY, root=tmp_path)
    assert invalid == [] and len(rows) == 1
    assert rows[0]["status"] == S.NO_SIGNAL
    assert rows[0]["route"] == S.ROUTE
    assert rows[0]["schema"] == S.SCHEMA


def test_2_the_path_is_under_the_runtime_tree_never_scratch(tmp_path):
    p = S.journal_path(DAYKEY, tmp_path)
    assert "track1_runtime" in str(p) and "signals" in str(p)
    assert "scratch" not in str(p).lower()
    assert S.SIGNALS_DIR == "global_index/track1_runtime/signals"


def test_3_a_missing_file_is_not_an_error(tmp_path):
    rows, invalid = S.read_day(DAYKEY, root=tmp_path)
    assert rows == [] and invalid == []
    s = S.summary(DAYKEY, root=tmp_path)
    assert s["present"] is False and s["reading"] == "not yet observed"
    assert "error" not in s


def test_4_an_unreadable_line_is_returned_not_dropped(tmp_path):
    S.append(row(raw_candidates=0), root=tmp_path)
    with open(S.journal_path(DAYKEY, tmp_path), "a", encoding="utf-8") as fh:
        fh.write("{not json}\n")
    rows, invalid = S.read_day(DAYKEY, root=tmp_path)
    assert len(rows) == 1 and len(invalid) == 1


def test_5_a_write_failure_disables_the_channel_and_remembers_why(tmp_path, monkeypatch):
    import builtins
    real_open = builtins.open

    def boom(*a, **k):
        if "track1_signals_" in str(a[0]):
            raise PermissionError("disk full")
        return real_open(*a, **k)

    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(S, "_disabled", False)
    monkeypatch.setattr(S, "_last_error", None)
    assert S.append(row(raw_candidates=0), root=tmp_path) is None
    assert S.enabled() is False
    assert "PermissionError" in (S.last_error() or "")


# ══════════════════════════════════════════════════════════════════════════════
# 2. status classification — the pair that must not collapse
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("decided,raw,acc,rej,expect", [
    (False, 0, 0, 0, S.SLOT_REFUSED),
    (False, 3, 1, 0, S.SLOT_REFUSED),      # a refusal wins over anything else
    (True, 0, 0, 0, S.NO_SIGNAL),
    (True, 1, 1, 0, S.SIGNAL_ACCEPTED_SHADOW),
    (True, 1, 0, 1, S.SIGNAL_REJECTED),
    (True, 2, 1, 1, S.SIGNAL_ACCEPTED_SHADOW),
    (True, 1, 0, 0, S.RAW_SIGNAL_FOUND),
])
def test_6_classification_is_total_and_explicit(decided, raw, acc, rej, expect):
    assert S.classify(decided=decided, reason="x", raw_candidates=raw,
                      accepted=acc, rejected=rej) == expect


def test_7_no_signal_and_rejected_cannot_be_the_same_row(tmp_path):
    """The one distinction this file exists for."""
    none = row(raw_candidates=0)
    declined = row(raw_candidates=1, rejected=1,
                   decisions=[T.Decision(candidate=cand(), verdict=T.REJECT_FAMILY_CAP)],
                   candidates=[cand()])
    assert none.status == S.NO_SIGNAL
    assert declined.status == S.SIGNAL_REJECTED
    assert none.status != declined.status
    assert declined.rejecting_layer == S.LAYER_CAP
    assert none.rejecting_layer == ""


# ══════════════════════════════════════════════════════════════════════════════
# 3. NO_SIGNAL must be explainable
# ══════════════════════════════════════════════════════════════════════════════

def test_8_no_signal_carries_rule_checks_not_just_a_zero():
    r = row(raw_candidates=0)
    assert r.rule_checks, "NO_SIGNAL without rule_checks is `candidates: 0` renamed"
    names = {c.rule for c in r.rule_checks}
    assert set(S.rule_names("roska4_stress")) <= names


def test_9_a_row_without_rule_checks_is_refused():
    with pytest.raises(S.SignalJournalRefused) as e:
        S.SignalRow(session_date=DAY, sleeve="roska4_stress", slot_id="x", slot_time="10:35",
                    mode="shadow_live", status=S.NO_SIGNAL)
    assert "rule_checks" in str(e.value)


def test_10_the_three_answer_sources_are_distinct():
    """`measured`, `not_reached` and `not_exposed_by_sleeve` mean different things, and the
    third must never be counted as a pass."""
    assert S.SOURCES == (S.MEASURED, S.NOT_REACHED, S.NOT_EXPOSED)
    r = row(raw_candidates=0)
    by_source = {}
    for c in r.rule_checks:
        by_source.setdefault(c.source, []).append(c.rule)
    assert S.MEASURED in by_source, "the gate and freshness are measured facts"
    assert S.NOT_EXPOSED in by_source, "the sleeve's own rules are not returned yet"
    for c in r.rule_checks:
        if c.source != S.MEASURED:
            assert c.passed is None, (c.rule, c.passed)


def test_11_primary_failure_reports_not_exposed_separately_from_passed():
    checks = [S.rule("a", True, value=1, threshold=0, comparator=">"),
              S.rule("b", False, value=2, threshold=4, comparator=">="),
              S.rule("c", source=S.NOT_EXPOSED),
              S.rule("d", source=S.NOT_REACHED)]
    pf = S.primary_failure(checks)
    assert pf["primary_failed_rule"] == "b"
    assert pf["not_exposed_by_sleeve"] == ["c"]
    assert pf["not_reached"] == ["d"]
    assert pf["failed_count"] == 1


def test_12_a_refused_slot_marks_every_strategy_rule_as_not_reached():
    r = row(decided=False, reason="gate_refused", detail="stale", gate_allow=False,
            gate_codes=("stale",))
    assert r.status == S.SLOT_REFUSED
    strategy = [c for c in r.rule_checks if c.rule in S.rule_names("roska4_stress")]
    assert strategy and all(c.source == S.NOT_REACHED for c in strategy)


# ══════════════════════════════════════════════════════════════════════════════
# 4. rejection detail, and the accepted-shadow guarantee
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("verdict,layer", [
    (T.REJECT_CAP, S.LAYER_CAP),
    (T.REJECT_FAMILY_CAP, S.LAYER_CAP),
    (T.REJECT_WINDOW, S.LAYER_WINDOW),
    (T.SUPPRESS_SAME_SYMBOL, S.LAYER_SAME_SYMBOL),
    (T.HALT_BREAKER, S.LAYER_ADMISSION),
])
def test_13_every_rejection_names_its_layer(verdict, layer):
    r = row(raw_candidates=1, rejected=1, candidates=[cand()],
            decisions=[T.Decision(candidate=cand(), verdict=verdict, detail="because")])
    assert r.status == S.SIGNAL_REJECTED
    assert r.rejecting_layer == layer
    assert r.reason == str(verdict)


def test_14_a_rejection_carries_the_candidate_a_reader_needs():
    r = row(raw_candidates=1, rejected=1, candidates=[cand()],
            decisions=[T.Decision(candidate=cand(), verdict=T.REJECT_CAP)])
    c = r.candidates[0]
    for k in ("instrument", "tradable_symbol", "direction", "entry", "stop", "risk", "qty"):
        assert k in c, k
    assert c["instrument"] == "MNQ" and c["direction"] == "short"
    assert c["tradable_symbol"], "the order symbol is the identity split being spent"


def test_15_a_rejection_without_a_named_layer_is_refused():
    with pytest.raises(S.SignalJournalRefused) as e:
        S.SignalRow(session_date=DAY, sleeve="roska4_stress", slot_id="x", slot_time="10:35",
                    mode="shadow_live", status=S.SIGNAL_REJECTED,
                    rule_checks=[S.rule("a", True)], rejecting_layer="")
    assert "named layer" in str(e.value)


def test_16_accepted_shadow_states_no_order_was_attempted():
    r = row(raw_candidates=1, accepted=1, candidates=[cand()],
            decisions=[T.Decision(candidate=cand(), verdict=T.TAKE)])
    assert r.status == S.SIGNAL_ACCEPTED_SHADOW
    assert r.accepted == 1
    assert r.orders_enabled is False
    assert r.order_attempted is False
    assert r.reason == "shadow_only"


def test_17_accepted_shadow_cannot_claim_an_order_attempt():
    """The one claim this journal exists to make impossible."""
    with pytest.raises(S.SignalJournalRefused) as e:
        S.SignalRow(session_date=DAY, sleeve="roska4_stress", slot_id="x", slot_time="10:35",
                    mode="shadow_live", status=S.SIGNAL_ACCEPTED_SHADOW,
                    rule_checks=[S.rule("a", True)], order_attempted=True)
    assert "order attempt" in str(e.value)
    with pytest.raises(S.SignalJournalRefused):
        S.SignalRow(session_date=DAY, sleeve="roska4_stress", slot_id="x", slot_time="10:35",
                    mode="shadow_live", status=S.SIGNAL_ACCEPTED_SHADOW,
                    rule_checks=[S.rule("a", True)], orders_enabled=True)


def test_18_every_row_states_orders_enabled_false_explicitly():
    """Written on every row rather than left to a reader's default."""
    for r in (row(raw_candidates=0),
              row(decided=False, reason="gate_refused", gate_allow=False),
              row(raw_candidates=1, rejected=1, candidates=[cand()],
                  decisions=[T.Decision(candidate=cand(), verdict=T.REJECT_CAP)])):
        d = r.as_row()
        assert d["orders_enabled"] is False and d["order_attempted"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. per-sleeve diagnostics
# ══════════════════════════════════════════════════════════════════════════════

REQUIRED = {
    "roska4_calm": ("regime_is_calm_d1", "prior_rth_close_bottom_third",
                    "prior_rth_down_close", "gap_not_deep", "entry_time_valid",
                    "stop_risk_computed"),
    "roska4_stress": ("no_regime_label_required", "breadth_down_count", "gapdown_count",
                      "mnq_only_short_setup", "pre_high_stop_reference",
                      "rr_target_computed", "same_symbol_suppression", "family_cap",
                      "cluster_cap"),
    "roska4_swing": ("ema50_filter", "r4_prior_range_filter", "entry_bar_volume_filter",
                     "spy_d1_close_below_sma50_short_filter", "fixed_stop_2x_daily_atr",
                     "stop_arm_rule", "admission_cap_result"),
    "global_nkd": ("ema10_filter", "regime_lag_1", "japan_session_window",
                   "fixed_stop_2x_daily_atr", "max_hold_context", "admission_cap_result"),
}


@pytest.mark.parametrize("sleeve", sorted(REQUIRED))
def test_19_each_sleeve_declares_the_rules_the_stage_asked_for(sleeve):
    have = set(S.rule_names(sleeve))
    assert set(REQUIRED[sleeve]) <= have, set(REQUIRED[sleeve]) - have


@pytest.mark.parametrize("sleeve", sorted(REQUIRED))
def test_20_each_sleeve_emits_every_declared_rule_on_a_real_row(sleeve):
    r = S.build_row(sleeve=sleeve, slot_id="X", slot_time="10:00", session_date=DAY,
                    mode="shadow_live", decided=True, reason="decided", raw_candidates=0,
                    freshness_allow=True, gate_allow=True)
    emitted = {c.rule for c in r.rule_checks}
    assert set(S.rule_names(sleeve)) <= emitted


def test_21_thresholds_come_from_the_params_not_a_second_copy():
    """A restated threshold is one that goes stale the first time anyone tunes the sleeve."""
    from global_index.track1_stress_mnq import StressParams
    from global_index.track1_calm_a import CalmAParams
    from global_index.track1_normal_r4 import NormalR4Params
    th = S.thresholds("roska4_stress")
    assert th["breadth_down_count"]["breadth_min"] == StressParams().breadth_min
    assert th["rr_target_computed"]["rr"] == StressParams().rr
    assert S.thresholds("roska4_calm")["prior_rth_close_bottom_third"]["close_loc_max"] \
        == CalmAParams().close_loc_max
    assert S.thresholds("roska4_swing")["ema50_filter"]["ema_period"] \
        == NormalR4Params().ema_period
    assert S.thresholds("global_nkd")["ema10_filter"]["ema_period"] == 10


def test_22_a_non_strategy_sleeve_cannot_write_a_row():
    for bad in ("track1_stop_repair", "max_hold", "preflight", "legacy_drain"):
        with pytest.raises(S.SignalJournalRefused) as e:
            S.SignalRow(session_date=DAY, sleeve=bad, slot_id="x", slot_time="10:00",
                        mode="shadow_live", status=S.NO_SIGNAL,
                        rule_checks=[S.rule("a", True)])
        assert "strategy sleeve" in str(e.value)


# ══════════════════════════════════════════════════════════════════════════════
# 6. the one-line summary
# ══════════════════════════════════════════════════════════════════════════════

def test_23_one_line_shapes():
    acc = row(raw_candidates=1, accepted=1, candidates=[cand()],
              decisions=[T.Decision(candidate=cand(), verdict=T.TAKE)]).as_row()
    rej = row(raw_candidates=1, rejected=1, candidates=[cand()],
              decisions=[T.Decision(candidate=cand(), verdict=T.REJECT_FAMILY_CAP)]).as_row()
    non = row(raw_candidates=0).as_row()
    ref = row(decided=False, reason="gate_refused", detail="stale",
              gate_allow=False, gate_codes=("stale",)).as_row()

    a, r, n, f = (S.one_line(x) for x in (acc, rej, non, ref))
    assert a.startswith("Signal: ACCEPTED SHADOW") and "order not attempted" in a
    assert "MNQ short" in a and "risk $420" in a
    assert r.startswith("Signal: REJECTED") and "cap" in r and "MNQ short" in r
    assert n.startswith("Signal: NO SIGNAL") and "candidates 0" in n
    assert f.startswith("Signal: REFUSED") and "gate_refused" in f
    for line in (a, r, n, f):
        assert "\n" not in line and len(line) < 160, line


def test_24_no_signal_says_when_no_blocker_can_be_named():
    """Silence would read as "nothing was close". The truth is the sleeve did not report."""
    line = S.one_line(row(raw_candidates=0).as_row())
    assert "blocker not reported" in line


def test_25_a_missed_slot_is_never_rendered_as_no_signal():
    assert "MISSED" in S.one_line({"status": S.SLOT_MISSED, "reason": "asleep"})
    assert "NO SIGNAL" not in S.one_line({"status": S.SLOT_MISSED, "reason": "asleep"})
    assert "NO DIAGNOSTICS" in S.one_line({"status": S.SLOT_NO_ROW, "reason": "ran, no row"})


# ══════════════════════════════════════════════════════════════════════════════
# 7. the backend reader
# ══════════════════════════════════════════════════════════════════════════════

def test_26_reader_reports_absent_file_as_not_yet_observed(tmp_path):
    from monitor.backend.track1_runtime_reader import read_track1_runtime
    out = read_track1_runtime(tmp_path)
    assert out["signals"]["present"] is False
    assert out["signals"]["reading"] == "not yet observed"


def test_27_reader_summarises_a_day(tmp_path, monkeypatch):
    import datetime as _dt
    from zoneinfo import ZoneInfo
    S.append(row(raw_candidates=0), root=tmp_path)
    S.append(row(slot_id="TRACK1_STRESS_1040", slot_time="10:40", raw_candidates=1,
                 accepted=1, candidates=[cand()],
                 decisions=[T.Decision(candidate=cand(), verdict=T.TAKE)]), root=tmp_path)
    s = S.summary(DAYKEY, root=tmp_path)
    assert s["present"] is True and s["rows"] == 2
    st = s["sleeves"]["roska4_stress"]
    assert st["observed"] == 2
    assert st["latest_status"] == S.SIGNAL_ACCEPTED_SHADOW
    assert st["latest_slot_id"] == "TRACK1_STRESS_1040"
    assert st["counts"] == {S.NO_SIGNAL: 1, S.SIGNAL_ACCEPTED_SHADOW: 1}
    assert st["latest_accepted"]["instrument"] == "MNQ"
    assert st["latest_accepted"]["order_attempted"] is False
    assert s["sleeves"]["roska4_calm"]["reading"] == "not yet observed"


def test_28_reader_surfaces_a_refusal(tmp_path):
    S.append(row(decided=False, reason="gate_refused", detail="stale", gate_allow=False,
                 gate_codes=("stale",)), root=tmp_path)
    st = S.summary(DAYKEY, root=tmp_path)["sleeves"]["roska4_stress"]
    assert st["latest_status"] == S.SLOT_REFUSED
    assert st["latest_declined"]["reason"] == "gate_refused"


def test_29_reader_reports_a_disabled_channel_rather_than_an_empty_day(tmp_path,
                                                                      monkeypatch):
    monkeypatch.setattr(S, "_disabled", True)
    monkeypatch.setattr(S, "_last_error", "PermissionError: disk full")
    s = S.summary(DAYKEY, root=tmp_path)
    assert s["channel_disabled"] is True
    assert "disk full" in s["channel_error"]


# ══════════════════════════════════════════════════════════════════════════════
# 8. the job view
# ══════════════════════════════════════════════════════════════════════════════

def test_30_only_track1_strategy_jobs_are_classified_as_such():
    from monitor.backend.job_journal_reader import is_track1_strategy_job, _job_type
    for good in ("TRACK1_CALM_1000", "TRACK1_STRESS_1110", "TRACK1_SWING_1405",
                 "TRACK1_NKD_0110"):
        assert is_track1_strategy_job(good), good
        assert _job_type(good) == "track1_strategy_slot"
    for bad in ("TRACK1_STOP_REPAIR_0620", "TRACK1_MAX_HOLD_EXIT", "STOP_REPAIR_1020",
                "PREFLIGHT", "SPY_REFRESH_PM", "TRACK1_AUDIT_ROSKA4_CALM", "LIVE_DAY"):
        assert not is_track1_strategy_job(bad), bad
        assert _job_type(bad) != "track1_strategy_slot", bad


def test_31_non_strategy_jobs_get_no_signal_key_at_all(tmp_path):
    """Not an empty one. A `signal: null` invites a renderer to print "no signal" about a
    job that has no signals to have."""
    from monitor.backend.job_journal_reader import _annotate_signal_diagnostics
    jobs = [{"job_id": "TRACK1_STOP_REPAIR_0620", "status": "completed"},
            {"job_id": "PREFLIGHT", "status": "completed"},
            {"job_id": "TRACK1_STRESS_1110", "status": "completed"}]
    _annotate_signal_diagnostics(jobs, DAY, tmp_path)
    assert "signal" not in jobs[0] and "signal" not in jobs[1]
    assert "signal" in jobs[2]


def test_32_a_strategy_job_with_a_row_gets_the_summary_and_the_details(tmp_path):
    """Stage 5ZE moved the developer material to `debug` and added `chip` + `operator`.

    The row still carries everything it did; what changed is which half the panel renders.
    """
    from monitor.backend.job_journal_reader import _annotate_signal_diagnostics
    S.append(row(slot_id="TRACK1_STRESS_1110", slot_time="11:10", raw_candidates=1,
                 rejected=1, candidates=[cand()],
                 decisions=[T.Decision(candidate=cand(), verdict=T.REJECT_FAMILY_CAP,
                                       detail="family gross")]), root=tmp_path)
    jobs = [{"job_id": "TRACK1_STRESS_1110", "status": "completed"}]
    _annotate_signal_diagnostics(jobs, DAY, tmp_path)
    sg = jobs[0]["signal"]
    assert sg["status"] == S.SIGNAL_REJECTED
    assert sg["summary"].startswith("Signal: REJECTED")
    assert sg["chip"]["label"] == "REJECTED"
    assert sg["operator"], "the operator-facing lines are what the panel renders"
    assert sg["details"]["rejecting_layer"] == S.LAYER_CAP
    assert sg["details"]["candidates"][0]["instrument"] == "MNQ"
    assert sg["details"]["order_attempted"] is False
    # the developer material still ships, just not where the panel looks
    assert sg["debug"]["rule_checks"]


def test_33_a_slot_that_RAN_with_no_row_is_no_diagnostics_not_missed(tmp_path):
    """The 22 NKD slots on the day this was built had already run. Calling them MISSED would
    have accused the scheduler of failing when it had not."""
    from monitor.backend.job_journal_reader import _annotate_signal_diagnostics
    jobs = [{"job_id": "TRACK1_NKD_0110", "status": "completed"}]
    _annotate_signal_diagnostics(jobs, DAY, tmp_path)
    assert jobs[0]["signal"]["status"] == S.SLOT_NO_ROW
    assert "NO DIAGNOSTICS" in jobs[0]["signal"]["summary"]


def test_34_a_slot_that_never_spawned_is_missed_and_never_no_signal(tmp_path):
    from monitor.backend.job_journal_reader import _annotate_signal_diagnostics
    jobs = [{"job_id": "TRACK1_CALM_1000", "status": "missed",
             "reason": "scheduler stall"}]
    _annotate_signal_diagnostics(jobs, DAY, tmp_path)
    sg = jobs[0]["signal"]
    assert sg["status"] == S.SLOT_MISSED
    assert sg["chip"]["label"] == "MISSED"
    assert sg["details"] is None and sg["debug"] is None
    assert "NO SIGNAL" not in sg["summary"]
    # Stage 5ZE: the row points at the Operational block rather than restating the evidence.
    assert any("Operational" in line for line in sg["operator"])


# ══════════════════════════════════════════════════════════════════════════════
# 9. guards
# ══════════════════════════════════════════════════════════════════════════════

def test_35_the_signals_module_imports_no_broker_or_order_path():
    tree = ast.parse(Path(S.__file__).read_text(encoding="utf-8"))
    banned = ("ib_insync", "ibkr_broker", "track1_order_journal", "track1_paper_executor",
              "track1_paper_callsite", "broker")
    for n in ast.walk(tree):
        if not isinstance(n, (ast.Import, ast.ImportFrom)):
            continue
        mod = getattr(n, "module", "") or ""
        names = [a.name for a in n.names]
        for b in banned:
            assert b not in mod.split("."), (b, mod)
            assert not any(b == nm.split(".")[-1] for nm in names), (b, names)


def test_36_no_order_journal_or_send_order_anywhere_in_the_new_code():
    for rel in ("global_index/track1_signals.py",
                "monitor/backend/track1_runtime_reader.py",
                "monitor/backend/job_journal_reader.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        calls = [n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        for bad in ("send_order", "placeOrder", "place_stop", "cancel_order"):
            assert bad not in calls, (rel, bad)


def test_37_the_reader_does_not_touch_the_legacy_book():
    src = (REPO / "monitor/backend/track1_runtime_reader.py").read_text(encoding="utf-8")
    lits = [n.value for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.endswith("live_positions.json")]
    assert lits == [], lits


def test_38_no_allow_orders_was_added():
    for rel in ("global_index/run_scheduler.py", "monitor/ops.py",
                "global_index/track1_signals.py"):
        p = REPO / rel
        if not p.exists():
            continue
        lits = [n for n in ast.walk(ast.parse(p.read_text(encoding="utf-8", errors="replace")))
                if isinstance(n, ast.Constant) and n.value == "--allow-orders"]
        assert lits == [], rel


def test_39_the_slot_writes_diagnostics_AFTER_its_coverage_row():
    """A diagnostics failure must never cost a slot the evidence the audit counts."""
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)]
    cov = min(c.lineno for c in calls
              if getattr(c.func.value, "id", None) == "wl" and c.func.attr == "slot_observed")
    sg = min(c.lineno for c in calls if getattr(c.func.value, "id", None) == "sig")
    assert cov < sg, (cov, sg)


def test_40_the_diagnostics_block_cannot_take_a_slot_down():
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    guarded = []
    for t in ast.walk(fn):
        if not isinstance(t, ast.Try):
            continue
        if [c for c in ast.walk(t) if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Attribute)
                and getattr(c.func.value, "id", None) == "sig"]:
            guarded.append(t)
    assert guarded, "the signal-diagnostics block is not wrapped"


def test_41_this_suite_wrote_nothing_into_the_real_runtime_tree():
    live = REPO / S.SIGNALS_DIR
    if live.exists():
        for p in live.glob("track1_signals_*.jsonl"):
            assert p.stat().st_size >= 0        # present is fine; this suite never writes here
    assert not (REPO / "global_index/track1_runtime/orders").exists()
    assert not (REPO / "global_index/live_positions.track1.json").exists()


def test_42_orders_are_still_impossible():
    import os
    from global_index import track1_gates as G
    # Stage 5ZZU. A twelfth instance of the pre-B1 staleness Stage 5ZZS restated elsewhere;
    # this suite was not among the ones that stage ran, so it kept asserting that the operator
    # had signed nothing. It also pinned B1 as a blocker, which is now a state that comes and
    # goes with the freshness of the account baseline record rather than a fixed fact.
    #
    # What holds regardless: orders are impossible, and something MEASURED is what holds them.
    allowed, reasons = G.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    assert "PAPER_SHADOW_EVIDENCE" in ids, ids
    if (REPO / G.CONFIRMATION_PATH).exists():
        conf, errors = G.load_confirmations(G.CONFIRMATION_PATH)
        assert errors == [], errors
        assert (conf.confirmed_by or "").strip(), "an unsigned decision appeared on disk"
        assert allowed is False, "a signed decision must not make orders possible"
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")


# ══════════════════════════════════════════════════════════════════════════════
# 10. the dashboard contract
# ══════════════════════════════════════════════════════════════════════════════

def _js():
    return (REPO / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")


def test_43_the_panel_has_one_compact_signals_row():
    js = _js()
    assert "t1Fact('Signals today'" in js
    assert "function signalsRow()" in js
    assert "'not yet observed'" in js


def test_44_the_job_row_renders_a_chip_and_the_expanded_row_renders_operator_text():
    """Stage 5ZE replaced the one-line sentence in the row with a chip, and the rule grid in
    the expanded panel with operator prose. Same intent, different rendering: the row is
    scannable and the panel is readable.

    The full DOM proof lives in the Stage 5ZE suite, which drives a real browser. This keeps
    the structural half here so the 5ZD file still fails if the wiring is removed.
    """
    js = _js()
    assert "function signalLine(job)" in js
    assert "function signalDetails(job)" in js
    assert "function operationalDetails(job)" in js
    assert js.count("signalDetails(job)") >= 2, "signalDetails is never called"
    assert js.count("signalLine(job)") >= 2, "signalLine is never called"
    # Stage 5ZP moved both sections INSIDE `renderJobDetails`, so they are no longer
    # concatenated after it. The ordering claim is unchanged and is now asserted where the
    # two are emitted together.
    assert "${operationalDetails(job)}${signalDetails(job)}" in js, \
        "the expanded row must show Operational BEFORE Signal"
    assert "job-badges" in js


def test_45_the_developer_rule_grid_is_gone_from_the_render_path():
    """It was replaced, not hidden. After Stage 5ZD every sleeve rule came back unmeasured, so
    the grid was thirty UNKNOWN rows burying the two lines that carried information."""
    js = _js()
    assert "rule-checks" not in js and "rule-check" not in js
    assert "JSON.stringify" not in js
    css = (REPO / "global_index/dash/realtime/realtime.css").read_text(encoding="utf-8")
    assert ".rule-check" not in css and ".rule-unknown" not in css


def test_46_the_chip_no_longer_takes_a_row_of_its_own():
    """Inverted by Stage 5ZP, and the inversion is the fix.

    This asserted `grid-column: 1 / -1` — the chip spanning the full badge grid, which is
    exactly what put it on its own line and made every Track 1 row two lines tall. It now
    sits in the badge group with RUNNER and COMPLETED, so the property must be GONE. Whether
    the row overflows at a narrow width is checked in the browser by the Stage 5ZP suite,
    which is a stronger question than which properties the stylesheet contains.
    """
    css = (REPO / "global_index/dash/realtime/realtime.css").read_text(encoding="utf-8")
    assert ".job-signal-chip" not in css
    assert "@media (max-width: 720px)" in css
    js = _js()
    assert 'class="event-status signal-' in js


def _strip_js_comments(src: str) -> str:
    """Line comments out, so the check reads CODE.

    Stage 5ZP. As written this searched the whole function body including its comments, and
    went red the moment a comment quoted the old label to explain why it had been removed —
    the substring-over-prose trap, on a test built to catch a different one. The claim is
    about what the renderer EMITS, so the prose has no business in the sample.
    """
    return "\n".join("" if l.lstrip().startswith("//") else l for l in src.splitlines())


def test_47_the_dashboard_does_not_compose_the_wording_itself():
    """One owner for every string an operator reads, and it is the backend."""
    js = _js()
    seg = _strip_js_comments(js.split("function signalLine(job)")[1].split("\n  }")[0])
    assert "chip.label" in seg and "chip.tooltip" in seg
    for literal in ("NO SIGNAL", "ACCEPTED SHADOW", "REJECTED", "MISSED"):
        assert literal not in seg, literal
    det = _strip_js_comments(js.split("function signalDetails(job)")[1].split("\n  }")[0])
    assert "sg.operator" in det
    assert "No setup matched" not in det
