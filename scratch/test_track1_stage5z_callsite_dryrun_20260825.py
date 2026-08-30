"""Stage 5Z — the paper call-site dry run, and the wall it must stop at.

No broker, no connection, no order. The only broker in this file refuses by name.

The unusual assertion in here is that **a dry run succeeds by being stopped**. A rehearsal
that completes has not tested the thing it exists for, so `ok` requires `reached_boundary`
and several tests exist purely to prove that a run which never got there is not ok.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from global_index import track1_broker_read as BR
from global_index import track1_order_journal as J
from global_index import track1_paper_callsite as CS
from global_index import track1_paper_executor as X
from global_index import track1_signal_layer as T

REPO = Path(__file__).resolve().parents[1]
DAY = "2026-08-25"


def cand(inst="MNQ", sleeve="roska4_stress", qty=2, tid="t1"):
    return T.Candidate(trade_id=tid, sleeve=sleeve, instrument=inst, direction="long",
                       qty=qty, risk_dollars=250.0, entry_time="2026-08-25 10:35:00", meta={})


def took(c=None):
    return T.Decision(candidate=c or cand(), verdict=T.TAKE)


def rejected(c=None):
    return T.Decision(candidate=c or cand(), verdict=T.REJECT_CAP)


# ══════════════════════════════════════════════════════════════════════════════
# 1. where the seam is — derived, and Stage 5W's version was wrong
# ══════════════════════════════════════════════════════════════════════════════

def test_1_the_seam_is_in_observe_live_slot_not_run_shadow():
    s = CS.seam(REPO)
    assert s["function"] == "observe_live_slot"
    assert s["anchor"] == "settlements, decisions = run_candidates(found, book=book)"
    lo, hi = s["function_lines"]
    assert lo < s["after_line"] < hi


def test_2_run_shadow_never_hands_its_broker_to_anything():
    """Stage 5W called `NoOrderBroker()` in run_shadow 'the call site'. It is not one.

    The object is constructed and then read exactly once, for its call count, to prove
    nothing was sent. Replacing it with a real broker would change nothing, because no code
    passes it an order.
    """
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "run_shadow")
    loads = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "broker"
             and isinstance(n.ctx, ast.Load)]
    assert len(loads) == 1, f"run_shadow now uses `broker` at {len(loads)} places"
    # and that single use is an attribute read, not an argument to anything
    line = src.splitlines()[loads[0].lineno - 1]
    assert "broker.calls" in line, line


def test_3_the_scheduler_strategy_slot_runs_the_live_path():
    """The 70 strategy jobs invoke run_live_day_track1 with --sleeve/--slot-id, which
    main() dispatches to observe_live_slot — not to run_shadow."""
    sched = (REPO / "global_index/run_scheduler.py").read_text(encoding="utf-8")
    assert '"--sleeve", sleeve' in sched and '"--slot-id", slot_id' in sched
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name)}
    assert "observe_live_slot" in called and "run_shadow" in called


def test_4_the_live_slot_path_carries_a_gate_that_defaults_shut():
    """Stage 5ZZG. Was "the slot has no broker and no gate" — true while the SEND wire did not
    exist. It exists now, so the question changes from whether the arguments are there to
    whether they are SHUT unless somebody deliberately opens them, which is the property that
    was doing the work all along.
    """
    import inspect
    from global_index import run_live_day_track1 as R

    params = inspect.signature(R.observe_live_slot).parameters
    assert params["order_gate"].default is None
    assert params["broker"].default is None
    # and the slot builds a closed gate when handed nothing
    assert R.OrderGate(False).allow_orders is False
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    built = [n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id.endswith("Broker")]
    assert built == [], f"observe_live_slot now constructs {built}"


def test_5_the_seam_refuses_to_guess_if_the_anchor_becomes_ambiguous(tmp_path):
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    doubled = src.replace("settlements, decisions = run_candidates(found, book=book)",
                          "settlements, decisions = run_candidates(found, book=book)\n"
                          "            _x = run_candidates(found, book=book)", 1)
    d = tmp_path / "global_index"
    d.mkdir(parents=True)
    (d / "run_live_day_track1.py").write_text(doubled, encoding="utf-8")
    with pytest.raises(CS.PaperCallsiteRefused) as e:
        CS.seam(tmp_path)
    assert e.value.code == CS.NOT_A_DRY_RUN


# ══════════════════════════════════════════════════════════════════════════════
# 2. the wall
# ══════════════════════════════════════════════════════════════════════════════

def test_6_the_refusing_broker_cannot_send():
    from global_index.broker import Order
    o = Order(inst="MNQ", action="OPEN", direction="long", contracts=1,
              cluster="roska4_stress", ref_day=DAY)
    with pytest.raises(CS.PaperCallsiteRefused) as e:
        CS.RefusingBroker().send_order(o)
    assert e.value.code == CS.BOUNDARY_REACHED


def test_7_every_read_from_the_wall_is_cannot_say():
    r = BR.Track1BrokerReader(CS.RefusingBroker())
    for a in (r.positions(), r.open_orders(), r.order_status("55"), r.execution("55")):
        assert not a.known, a


def test_7b_the_wall_is_silent_in_TWO_independent_ways():
    """Found by mutation, like the double guard on `ok`.

    It declines to testify, AND every read returns a value the reader treats as "cannot
    say". Either alone would be enough; both together mean a fake made "more useful" by
    someone in a hurry still cannot make the rehearsal believe anything.
    """
    w = CS.RefusingBroker()
    assert w.CAN_TESTIFY is False
    assert w.get_positions() is None
    assert w.get_open_orders() is None
    assert w.find_execution("55") is None
    assert w.get_order_status("55") == BR.STATUS_NOT_FOUND


def test_8_a_broker_that_would_accept_is_refused(tmp_path):
    class Willing:
        CAN_TESTIFY = False

        def send_order(self, order, *, on_submit=None): return "sent"
        def get_positions(self): return None
        def get_order_status(self, o): return "NOT_FOUND"
        def cancel_order(self, o): return False
        def place_stop(self, *a, **k): return ""

    with pytest.raises(CS.PaperCallsiteRefused) as e:
        CS.dry_run([took()], ref_day=DAY, root=tmp_path, broker=Willing())
    assert e.value.code == CS.NOT_A_DRY_RUN


def test_9_a_broker_that_raises_the_wrong_thing_is_refused(tmp_path):
    class Sloppy:
        CAN_TESTIFY = False

        def send_order(self, order, *, on_submit=None): raise ValueError("nope")
        def get_positions(self): return None
        def get_order_status(self, o): return "NOT_FOUND"
        def cancel_order(self, o): return False
        def place_stop(self, *a, **k): return ""

    with pytest.raises(CS.PaperCallsiteRefused) as e:
        CS.dry_run([took()], ref_day=DAY, root=tmp_path, broker=Sloppy())
    assert e.value.code == CS.NOT_A_DRY_RUN
    assert "refuse by name" in e.value.detail


# ══════════════════════════════════════════════════════════════════════════════
# 3. where a rehearsal may write
# ══════════════════════════════════════════════════════════════════════════════

def test_10_the_production_journal_root_is_refused(tmp_path):
    with pytest.raises(CS.PaperCallsiteRefused) as e:
        CS.assert_dry_run_root(Path(tmp_path) / J.ORDERS_DIR, production_root=tmp_path)
    assert e.value.code == CS.PRODUCTION_ROOT


def test_11_a_parent_of_the_production_root_is_refused_too(tmp_path):
    """Pointing a dry run at the repo root would put its rows one directory above the real
    journal, and `read(day=None)` walks the whole tree."""
    with pytest.raises(CS.PaperCallsiteRefused):
        CS.assert_dry_run_root(tmp_path, production_root=tmp_path)


def test_12_a_child_of_the_production_root_is_refused(tmp_path):
    with pytest.raises(CS.PaperCallsiteRefused):
        CS.assert_dry_run_root(Path(tmp_path) / J.ORDERS_DIR / "sub",
                               production_root=tmp_path)


def test_13_the_default_root_is_accepted_and_is_not_production(tmp_path):
    ok = CS.assert_dry_run_root(CS.dry_run_root(tmp_path), production_root=tmp_path)
    assert CS.DRY_RUN_DIRNAME in str(ok)


def test_14_a_dry_run_writes_nothing_under_the_production_journal(tmp_path):
    CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    assert not (Path(tmp_path) / J.ORDERS_DIR).exists()
    assert (Path(tmp_path) / CS.DRY_RUN_DIRNAME).exists()


# ══════════════════════════════════════════════════════════════════════════════
# 4. the six stages
# ══════════════════════════════════════════════════════════════════════════════

def test_15_every_stage_runs_and_in_order(tmp_path):
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    assert [s.name for s in rep.stages] == list(CS.STAGES)


def test_16_the_gate_stage_reports_the_REAL_answer_not_the_synthetic_one(tmp_path):
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    gate = next(s for s in rep.stages if s.name == "gate")
    assert gate.data["production_allow_orders"] is False
    assert "B1_broker_account_or_legacy_retirement" in gate.data["production_reasons"]
    assert "PAPER_SHADOW_EVIDENCE" in gate.data["production_reasons"]


def test_17_the_synthetic_gate_is_a_different_type_from_the_production_one():
    assert not isinstance(CS.DryRunGate(), X.ProductionGate)
    assert CS.DryRunGate().synthetic is True
    assert X.production_gate().allow_orders is False


def test_18_the_precheck_says_entries_would_be_blocked(tmp_path):
    """The wall cannot testify, so a real restart against it could not enter. The rehearsal
    records that rather than proceeding as if the book were known."""
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    pre = next(s for s in rep.stages if s.name == "reconcile_precheck")
    assert pre.data["entries_would_be_blocked"] is True
    assert pre.data["broker_positions_known"] is False


def test_19_offered_admitted_and_mapped_are_three_different_numbers(tmp_path):
    rep = CS.dry_run([took(), took(cand(inst="MES", sleeve="roska4_swing", tid="t2")),
                      rejected()], ref_day=DAY, root=tmp_path)
    m = next(s for s in rep.stages if s.name == "mapping")
    assert (m.data["offered"], m.data["admitted"], m.data["mapped"]) == (3, 2, 2)


def test_20_a_rejected_decision_never_reaches_the_journal(tmp_path):
    CS.dry_run([rejected()], ref_day=DAY, root=tmp_path)
    rows, _ = J.read(root=CS.dry_run_root(tmp_path), day="20260825")
    assert rows == []


def test_21_the_journal_records_intended_submitted_then_unknown(tmp_path):
    """The crash-path rehearsal: we were about to send and could not see what happened."""
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    j = next(s for s in rep.stages if s.name == "journal")
    assert j.data["states"] == ["intended", "submitted", "unknown"]
    assert j.data["invalid"] == 0


def test_22_the_boundary_stage_counts_attempts_and_zero_sends(tmp_path):
    rep = CS.dry_run([took(), took(cand(inst="MES", sleeve="roska4_swing", tid="t2"))],
                     ref_day=DAY, root=tmp_path)
    b = next(s for s in rep.stages if s.name == "boundary")
    assert b.data == {"attempts": 2, "sent": 0}
    assert b.ok


# ══════════════════════════════════════════════════════════════════════════════
# 5. a dry run succeeds by being STOPPED
# ══════════════════════════════════════════════════════════════════════════════

def test_23_reaching_the_wall_is_the_success_condition(tmp_path):
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    assert rep.reached_boundary and rep.ok


def test_24_a_run_that_never_reached_the_wall_is_NOT_ok(tmp_path):
    """Nothing admitted means nothing was rehearsed. Every stage passing must not read as a
    successful rehearsal — that is the shape of a test suite that checks nothing."""
    rep = CS.dry_run([rejected()], ref_day=DAY, root=tmp_path)
    assert all(s.ok for s in rep.stages[:4])
    assert rep.reached_boundary is False
    assert rep.ok is False


def test_24b_reaching_the_wall_is_guarded_TWICE_and_that_is_deliberate(tmp_path):
    """Found by mutation: removing either guard alone changes nothing.

    `ok` requires `reached_boundary`, AND the boundary stage carries the same flag as its own
    `ok`, so `all(s.ok ...)` fails on it too. Two independent expressions of one rule is
    normally a smell; here it is the difference between a rehearsal that lies once and one
    that has to lie twice. Pinned so a tidy-up cannot quietly drop one.
    """
    rep = CS.dry_run([rejected()], ref_day=DAY, root=tmp_path)
    boundary = next(s for s in rep.stages if s.name == "boundary")
    assert boundary.ok is False
    assert rep.reached_boundary is False
    assert rep.ok is False
    # each guard, alone, is enough to fail the run
    for s in rep.stages:
        s.ok = True
    assert rep.ok is False, "the property no longer requires reached_boundary"


def test_25_an_empty_decision_list_is_not_a_successful_rehearsal(tmp_path):
    assert CS.dry_run([], ref_day=DAY, root=tmp_path).ok is False


def test_26_a_mapping_refusal_is_captured_not_raised(tmp_path, monkeypatch):
    from global_index import ibkr_broker
    monkeypatch.setattr(ibkr_broker, "ibkr_symbol_and_exchange", lambda i: ("NQ", "CME"))
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    assert rep.refusals and "order_identity_drift" in rep.refusals[0]
    assert rep.ok is False, "a rehearsal with an unmapped order is not a pass"


def test_27_a_zero_quantity_candidate_is_captured_not_raised(tmp_path):
    rep = CS.dry_run([took(cand(qty=0))], ref_day=DAY, root=tmp_path)
    assert rep.refusals and "order_quantity_invalid" in rep.refusals[0]
    assert rep.ok is False


def test_28_the_report_serialises(tmp_path):
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    assert json.loads(json.dumps(rep.as_dict()))["reached_boundary"] is True


# ══════════════════════════════════════════════════════════════════════════════
# 6. armed and shadow still decide the same thing
# ══════════════════════════════════════════════════════════════════════════════

def test_29_arming_still_changes_only_the_label():
    from global_index import run_live_day_track1 as R
    from global_index import track1_explain as tx

    class Armed:
        allow_orders = True

    class Shut:
        allow_orders = False

    assert R.decision_mode_for("live", Shut()) == tx.SHADOW_LIVE
    assert R.decision_mode_for("live", Armed()) == tx.ARMED
    assert {tx.SHADOW_LIVE, tx.ARMED} <= tx.FRESHNESS_BINDING_MODES


def test_30_the_mode_label_still_reaches_only_the_explanation_writer():
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "run_shadow")
    consumers = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and any(k.arg == "mode" and isinstance(k.value, ast.Name)
                         and k.value.id == "mode" for k in n.keywords)]
    names = [c.func.id if isinstance(c.func, ast.Name) else c.func.attr for c in consumers]
    assert names == ["emit_explanations"], names


def test_31_the_live_slot_records_shadow_live_unconditionally():
    """`observe_live_slot` has no gate, so it cannot record `armed` even by accident."""
    src = (REPO / "global_index/run_live_day_track1.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "observe_live_slot")
    modes = [ast.unparse(k.value) for n in ast.walk(fn) if isinstance(n, ast.Call)
             for k in n.keywords if k.arg == "mode"]
    # EVERY `mode=` in the live slot, not exactly one of them. Stage 5ZD added a second
    # (the signal-diagnostics row records the mode it decided under), and pinning the COUNT
    # would have made an honest addition look like a regression. What the docstring claims is
    # that the slot cannot record `armed` — which is a statement about every site, not one.
    assert modes, "the live slot no longer records a decision mode at all"
    assert set(modes) == {"tx.SHADOW_LIVE"}, modes


# ══════════════════════════════════════════════════════════════════════════════
# 7. what a real call site would still need — measured
# ══════════════════════════════════════════════════════════════════════════════

def test_32_the_track1_safety_jobs_already_cover_stops_and_max_hold():
    """The finding that decides the stub scope. Not a guess: the jobs are registered."""
    from global_index import track1_slots as t1
    jobs = t1.track1_safety_jobs()
    assert len(jobs) == 11
    kinds = {j.kind for j in jobs}
    assert kinds == {"maxhold", "stop_repair"}, kinds
    assert t1.TRACK1_POSITIONS_PATH == "live_positions.track1.json"


def test_33_those_jobs_place_stops_and_book_exits_through_FuturesRunner():
    for rel in ("global_index/run_stop_repair.py", "global_index/run_maxhold_exit.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert "FuturesRunner(" in src, rel
        assert "positions_path=pos_path" in src, rel


def test_34_they_no_op_only_because_the_book_file_does_not_exist():
    """Which is why the FIRST paper fill activates eleven jobs that have never run."""
    assert not (REPO / "global_index/live_positions.track1.json").exists()


def test_35_track1_switch_is_imported_by_nothing_so_it_cannot_bypass_the_journal():
    hits = []
    for d in ("global_index", "monitor", "futures"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.name == "track1_switch.py":
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                hits.append(f"{p.name}: UNPARSEABLE")
                continue
            for n in ast.walk(tree):
                if not isinstance(n, (ast.Import, ast.ImportFrom)):
                    continue
                mod = getattr(n, "module", "") or ""
                if "track1_switch" in mod or any("track1_switch" in a.name for a in n.names):
                    hits.append(p.name)
    assert hits == [], hits


def test_36_the_coverage_table_names_the_gap_it_found():
    ops = {c[0] for c in CS.COVERAGE}
    assert {"open_position", "place_protective_stop", "close_position (strategy exit)",
            "switch_same_symbol"} <= ops
    switch = next(c for c in CS.COVERAGE if c[0] == "switch_same_symbol")
    assert "imported by NOTHING" in switch[1]


# ══════════════════════════════════════════════════════════════════════════════
# 8. orders are still impossible
# ══════════════════════════════════════════════════════════════════════════════

def test_37_nothing_in_production_imports_the_dry_run_or_the_executor():
    targets = ("track1_paper_callsite", "track1_paper_executor", "track1_broker_read")
    hits = []
    for d in ("global_index", "monitor", "futures"):
        base = REPO / d
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if p.stem in targets:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                hits.append(f"{p.name}: UNPARSEABLE")
                continue
            for n in ast.walk(tree):
                if not isinstance(n, (ast.Import, ast.ImportFrom)):
                    continue
                mod = getattr(n, "module", "") or ""
                names = [a.name for a in n.names]
                for t in targets:
                    if t in mod or any(t in nm for nm in names):
                        hits.append(f"{p.name} -> {t}")
    # Stage 5ZZG. `track1_paper_send` is the gated seam and may name the executor; nothing
    # else new may. Restated rather than emptied — see the module note in the 5W suite.
    allowed = {"track1_paper_send.py -> track1_paper_executor"}
    unexpected = sorted(set(hits) - allowed)
    assert unexpected == [], unexpected


def test_38_no_scheduler_or_ops_path_can_trigger_a_send():
    """Three independent facts, all by AST: no arming flag in any argv, no broker
    construction in the slot path, and no send_order call reachable from either file."""
    for rel in ("global_index/run_scheduler.py", "monitor/ops.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8", errors="replace"))
        assert [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
                and n.value == "--allow-orders"] == [], rel
        assert [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "send_order"] == [], rel


def test_39_orders_are_still_impossible():
    import os
    from global_index import track1_gates as G
    allowed, reasons = G.may_enable_orders()
    ids = [r.split(":")[0] for r in reasons]
    assert allowed is False
    assert "B1_broker_account_or_legacy_retirement" in ids
    assert "PAPER_SHADOW_EVIDENCE" in ids
    assert not (REPO / G.CONFIRMATION_PATH).exists()
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0")


def test_40_the_evidence_gate_still_blocks_and_reports_zero_days():
    from global_index import track1_paper_readiness as pr
    released, detail = pr.gate_measurement(str(REPO))
    assert released is False
    assert detail


def test_41_this_suite_created_no_real_runtime_orders_directory():
    assert not (REPO / J.ORDERS_DIR).exists()
    assert not (REPO / CS.DRY_RUN_DIRNAME).exists()


def test_42_the_dry_run_module_opens_no_connection():
    tree = ast.parse(Path(CS.__file__).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, "module", "") or ""
            names = [a.name for a in n.names]
            for bad in ("ib_insync", "ibkr_broker", "socket"):
                assert bad not in mod and not any(bad in nm for nm in names), bad
