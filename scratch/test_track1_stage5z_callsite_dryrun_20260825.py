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


def _orders_tree_listing():
    """Every file under the REAL order journal, with its size. Taken at import and again in
    test_41; a difference means this suite touched production evidence."""
    base = REPO / J.ORDERS_DIR
    if not base.exists():
        return frozenset()
    out = set()
    for f in sorted(base.rglob("*")):
        if f.is_file():
            out.add((str(f.relative_to(base)), f.stat().st_size))
    return frozenset(out)


_ORDERS_AT_IMPORT = _orders_tree_listing()


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
    """The point of the stage is in its name, and the point survives the world changing.

    The old form spelled the real answer out as False and named the two blockers holding it
    there. On 2026-09-24 the operator released B1 and overrode the evidence gate, so those
    three literals became a record of a past afternoon rather than an assertion.

    What the stage exists for is that the rehearsal must not report its own synthetic gate as
    if it were production's. So it is checked against the registry it claims to be quoting —
    which is stricter than the literal was, because it goes red both ways: if the stage starts
    echoing the synthetic answer, and if it starts caching a stale real one.
    """
    from global_index import track1_gates as G

    allowed, reasons = G.may_enable_orders()
    rep = CS.dry_run([took()], ref_day=DAY, root=tmp_path)
    gate = next(s for s in rep.stages if s.name == "gate")

    assert gate.data["production_allow_orders"] is bool(allowed), (
        "the gate stage says production allows %r while the registry says %r"
        % (gate.data["production_allow_orders"], allowed))
    assert sorted(r.split(":")[0] for r in gate.data["production_reasons"]) == \
        sorted(r.split(":")[0] for r in reasons), {
            "stage": gate.data["production_reasons"], "registry": reasons}


def test_17_the_synthetic_gate_is_a_different_type_from_the_production_one():
    """Two of these lines were always the test; the third was a snapshot of a Tuesday.

    `production_gate().allow_orders is False` described the world on 2026-08-25 and stopped
    being true on 2026-09-24. Replacing it with the registry's own answer keeps the type
    distinction — the part that cannot go stale — and keeps production honest about itself.
    """
    from global_index import track1_gates as G

    assert not isinstance(CS.DryRunGate(), X.ProductionGate)
    assert CS.DryRunGate().synthetic is True
    assert getattr(X.production_gate(), "synthetic", False) is False, (
        "the production gate marks itself synthetic; a rehearsal object has reached the "
        "production path")

    allowed, _reasons = G.may_enable_orders()
    assert bool(X.production_gate().allow_orders) is bool(allowed), (
        "the production gate carries its own opinion instead of the registry's")


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
    assert len(jobs) == 12            # + the 15:55 Calm clock exit (2026-10-05)
    kinds = {j.kind for j in jobs}
    assert kinds == {"maxhold", "stop_repair", "time_exit"}, kinds
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


def test_38_no_scheduler_or_ops_path_sends_on_its_own():
    """The old title was "can trigger a send", and it held because the flag existed nowhere.

    On 2026-09-24 the operator gave both files the flag on purpose, so the first of the three
    facts had to be restated rather than deleted. The other two are untouched and are the ones
    that matter more: neither file may reach a broker in its own process.

    What replaces the vanished fact is the thing it was protecting — nothing arms unless a
    person asked on that invocation. This machine now restarts itself on logon, so a flag
    produced outside a branch that tests for an explicit request would mean a route that comes
    back armed after a reboot with nobody present.
    """
    for rel in ("global_index/run_scheduler.py", "monitor/ops.py"):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        lines = [ln.split("#")[0] for ln in text.splitlines()]
        tree = ast.parse(text)

        # 1. the flag may be produced, and only from behind a branch
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Constant) and n.value == "--allow-orders"):
                continue
            ln = lines[n.lineno - 1]
            if "add_argument" in ln or "help=" in ln or " in cmdlines" in ln:
                continue                      # declared or read, not produced
            window = "\n".join(lines[max(0, n.lineno - 7):n.lineno])
            assert "allow_orders" in window and ("if " in window or "else" in window), (
                "%s line %d produces --allow-orders with no branch on an explicit request"
                % (rel, n.lineno))

        # 2. and 3. neither file reaches a broker itself
        assert [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "send_order"] == [], (
            "%s calls send_order; the gated send wire is the only place that may" % rel)
        assert [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in ("IBKRBroker", "Track1OrderExecutor")] == [], (
            "%s constructs a broker or an executor in its own process" % rel)


def test_39_an_open_gate_still_says_how_it_opened():
    """This was the load-bearing one, and its old name — "orders are still impossible" — is why
    it had to be rewritten rather than patched. It asserted a world, not a rule.

    One clause was stale weeks before the rest: `not CONFIRMATION_PATH.exists()` went false on
    2026-08-27 when the operator signed the file.

    The rule underneath is that a gate never opens quietly. Each blocker is in exactly one of
    three states, and an override has to keep reading as an override — if a released blocker and
    an overridden one become indistinguishable on the record, nobody can tell later which
    evidence was produced and which was waived. That collapse is what this now catches.
    """
    import os

    from global_index import track1_gates as G

    allowed, reasons = G.may_enable_orders()
    conf = G.current_confirmations()

    if not allowed:
        # the original world: something is blocking, and it says so by name
        assert reasons, "orders are refused with no reason on the record"
        return

    # Opened. Then every blocker THAT HOLDS ORDERS is RELEASED or OVERRIDDEN, never silently
    # neither. The scope matters: eight of the twelve entries carry `blocks_orders=False` and
    # are unreleased on purpose — sleeve readiness, the bootstrap checkpoint, B3 freshness. A
    # first draft of this loop ran over all twelve and reported B3 as an unexplained hole,
    # which is the registry's deliberate fourth state and not a gate that opened quietly.
    overridden = dict((b.id, why) for b, why in G.overridden())
    holders = [b for b in G.BLOCKERS.values() if b.blocks_orders]
    assert holders, "no blocker holds orders at all; the registry has nothing to say yes about"
    for b in holders:
        rel = b.released(conf)
        if b.id in overridden:
            assert rel is False, (
                "%s reports itself released AND overridden; the record no longer tells "
                "produced evidence from waived evidence" % b.id)
            assert overridden[b.id], "%s is overridden with no reason recorded" % b.id
        else:
            assert rel is True, (
                "%s holds orders and is neither released nor overridden, yet orders are "
                "allowed" % b.id)

    # And an override is never silent in the other direction either: something that is waived
    # must appear in `overridden()` rather than only in somebody's memory of a decision.
    assert all(G.BLOCKERS[i].blocks_orders for i in overridden), (
        "overridden() names a blocker that never held orders; the report is describing a "
        "waiver of something that was not blocking")

    # And the second factor is never ambient: approval reaches a child because a launcher was
    # told to put it there, not because it was lying around in whatever shell ran things.
    assert os.environ.get("TRACK1_ORDERS_APPROVED") in (None, "", "0"), (
        "the approval is set in the test process's environment")


def test_40_the_evidence_gate_still_blocks_and_reports_zero_days():
    from global_index import track1_paper_readiness as pr
    released, detail = pr.gate_measurement(str(REPO))
    assert released is False
    assert detail


def test_41_this_suite_wrote_nothing_into_the_real_runtime_tree():
    """Absence was a usable proxy for "this suite wrote nothing" only while the directory had
    never existed. Production created it on 2026-09-24 by placing two orders that filled, so
    the old form would now fail for the one reason that is not a problem.

    Measured instead: the listing taken when this module was imported, against the listing now.
    That is what the test was always about, and it is sharper — it also catches a write into a
    directory that already exists, which absence could never see.
    """
    now = _orders_tree_listing()
    assert now == _ORDERS_AT_IMPORT, {
        "added": sorted(now - _ORDERS_AT_IMPORT),
        "removed": sorted(_ORDERS_AT_IMPORT - now),
        "why": "this suite changed the real order journal; every write here belongs in tmp_path",
    }
    # The rehearsal's own directory has never existed in the real tree and still must not.
    assert not (REPO / CS.DRY_RUN_DIRNAME).exists()


def test_42_the_dry_run_module_opens_no_connection():
    tree = ast.parse(Path(CS.__file__).read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, "module", "") or ""
            names = [a.name for a in n.names]
            for bad in ("ib_insync", "ibkr_broker", "socket"):
                assert bad not in mod and not any(bad in nm for nm in names), bad
