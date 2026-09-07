"""Stage 5Z mutation harness — break the dry run, prove the right test goes red.

The mutations that matter most here are the ones that make a rehearsal look like a PASS when
it never reached the wall, and the ones that let rehearsal rows land where a real reconcile
would read them. A dry run that quietly succeeds is worse than none: it certifies a path
nobody exercised.

Discipline carried forward, all of it learned the hard way in 5V / 5X / 5Y:

  * `expect_red` proves each test green BEFORE mutating — pytest exits non-zero on an unknown
    test id, so without this a renamed test reads as a successful mutation;
  * a test that asserts BEHAVIOUR needs the callable replaced. `_source_patch` only changes
    what `Path.read_text` returns and cannot touch an imported function;
  * a source patch must stay PARSEABLE, or a test that walks files will skip it.

Run:  python scratch/track1_stage5z_mutations_20260825.py
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scratch")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

SUITE = "scratch/test_track1_stage5z_callsite_dryrun_20260825.py"
RESULTS: list = []


def _run(test: str) -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        return int(pytest.main(["-q", "-p", "no:randomly", "-x", f"{SUITE}::{test}"]))


def expect_red(label: str, what: str, patcher, test: str) -> bool:
    if _run(test) != 0:
        RESULTS.append({"id": label, "mutation": what, "test": test,
                        "outcome": "BASELINE NOT GREEN"})
        print(f"  [{label}] BASELINE NOT GREEN {test}")
        return False
    with patcher:
        red = _run(test) != 0
    RESULTS.append({"id": label, "mutation": what, "test": test,
                    "outcome": "RED" if red else "STILL GREEN"})
    print(f"  [{label}] {'RED  ' if red else 'STILL GREEN'} {test}")
    if not red:
        print("         ^-- the test does not check this")
    return red


def _source_patch(module, replace_from: str, replace_to: str):
    real = Path.read_text
    original = Path(module.__file__).read_text(encoding="utf-8")
    assert replace_from in original, f"anchor not found in {module.__file__}"
    mutated = original.replace(replace_from, replace_to, 1)

    def read_text(self, *a, **kw):
        if Path(self) == Path(module.__file__):
            return mutated
        return real(self, *a, **kw)

    return patch.object(Path, "read_text", read_text)


def main() -> int:
    import global_index.run_live_day_track1 as rld
    import global_index.track1_paper_callsite as cs
    import global_index.track1_paper_executor as x
    import global_index.track1_slots as t1

    print("Stage 5Z mutations\n" + "=" * 74)
    ok = True

    # ══ 1. the seam ════════════════════════════════════════════════════════
    print("\nM1 - seam() names run_shadow again, as Stage 5W did")
    ok &= expect_red(
        "M1", "the wrong function reported as the call site",
        patch.object(cs, "seam", lambda root=".": {
            "file": "global_index/run_live_day_track1.py", "function": "run_shadow",
            "function_lines": [1053, 1212], "after_line": 1069,
            "anchor": "broker = NoOrderBroker()"}),
        "test_1_the_seam_is_in_observe_live_slot_not_run_shadow")

    print("\nM2 - seam() picks the first anchor instead of refusing an ambiguous one")

    def greedy_seam(root="."):
        import ast as _ast
        p = Path(root) / "global_index" / "run_live_day_track1.py"
        src = p.read_text(encoding="utf-8")
        fn = next(n for n in _ast.walk(_ast.parse(src))
                  if isinstance(n, _ast.FunctionDef) and n.name == "observe_live_slot")
        call = next(n for n in _ast.walk(fn) if isinstance(n, _ast.Call)
                    and isinstance(n.func, _ast.Name) and n.func.id == "run_candidates")
        return {"file": "x", "function": "observe_live_slot",
                "function_lines": [fn.lineno, fn.end_lineno], "after_line": call.lineno,
                "anchor": src.splitlines()[call.lineno - 1].strip()}

    ok &= expect_red("M2", "two seams answered as one",
                     patch.object(cs, "seam", greedy_seam),
                     "test_5_the_seam_refuses_to_guess_if_the_anchor_becomes_ambiguous")

    print("\nM3 - run_shadow starts handing its broker to something")
    ok &= expect_red(
        "M3", "the broker passed as an argument",
        _source_patch(rld, '"send_order_calls": sum(1 for c in broker.calls if c[0] == "send_order"),',
                      '"send_order_calls": len(list(broker.calls)) + len(str(broker)),'),
        "test_2_run_shadow_never_hands_its_broker_to_anything")

    print("\nM4 - the live slot path constructs a broker")
    ok &= expect_red(
        "M4", "a broker appears inside observe_live_slot",
        _source_patch(rld, "            settlements, decisions = run_candidates(found, book=book)",
                      "            _b = NoOrderBroker()\n"
                      "            settlements, decisions = run_candidates(found, book=book)"),
        "test_4_the_live_slot_path_still_has_no_broker_and_no_gate")

    # ══ 2. the wall ════════════════════════════════════════════════════════
    print("\nM5 - the wall returns a synthetic fill instead of refusing")

    def quiet_send(self, order, *, on_submit=None):
        from global_index.broker import Fill
        self.attempts.append(order)
        return Fill(order.inst, order.action, order.direction, order.contracts,
                    order.cluster, status="FILLED")

    ok &= expect_red("M5", "a rehearsal that silently produces fills",
                     patch.object(cs.RefusingBroker, "send_order", quiet_send),
                     "test_6_the_refusing_broker_cannot_send")

    print("\nM6 - the wall claims it can testify AND starts answering")
    # Patching CAN_TESTIFY alone stays green, and that is the code being right twice: the
    # wall both declines to testify and returns "cannot say" from every read. A faithful
    # mutation has to remove both, which is what a well-meaning "make the fake more useful"
    # change would look like.
    ok &= expect_red(
        "M6", "the wall testifies and answers concretely",
        patch.multiple(cs.RefusingBroker, CAN_TESTIFY=True,
                       get_positions=lambda self: [],
                       get_open_orders=lambda self: [],
                       get_order_status=lambda self, order_id: "PENDING",
                       find_execution=lambda self, order_id, inst=None: {"shares": 1}),
        "test_7_every_read_from_the_wall_is_cannot_say")

    print("\nM7 - a willing broker is accepted into the dry run")
    real_dry = cs.dry_run

    def no_wall_check(decisions, **kw):
        kw.setdefault("broker", None)
        b = kw.pop("broker")
        return real_dry(decisions, broker=cs.RefusingBroker() if b is None else None, **kw)

    ok &= expect_red("M7", "the supplied-broker check skipped",
                     patch.object(cs, "dry_run", no_wall_check),
                     "test_8_a_broker_that_would_accept_is_refused")

    # ══ 3. where a rehearsal may write ═════════════════════════════════════
    print("\nM8 - the production journal root is accepted")
    ok &= expect_red("M8", "rehearsal rows into the real journal",
                     patch.object(cs, "assert_dry_run_root",
                                  lambda candidate, *, production_root=".": Path(candidate)),
                     "test_10_the_production_journal_root_is_refused")

    print("\nM9 - only exact equality is checked, not containment")

    def equality_only(candidate, *, production_root="."):
        import global_index.track1_order_journal as j
        cand = Path(candidate).resolve()
        real = (Path(production_root) / j.ORDERS_DIR).resolve()
        if cand == real:
            raise cs.PaperCallsiteRefused(cs.PRODUCTION_ROOT, "same dir")
        return cand

    ok &= expect_red("M9", "a parent of the production root slips through",
                     patch.object(cs, "assert_dry_run_root", equality_only),
                     "test_11_a_parent_of_the_production_root_is_refused_too")
    ok &= expect_red("M9b", "a child of the production root slips through",
                     patch.object(cs, "assert_dry_run_root", equality_only),
                     "test_12_a_child_of_the_production_root_is_refused")

    # ══ 4. a rehearsal that looks like a pass ══════════════════════════════
    # NOTE. `ok` is guarded TWICE — the property requires `reached_boundary`, and the
    # boundary StageResult carries the same flag as its own `ok`. Mutating only the property
    # stays green, because `all(s.ok ...)` still fails on the boundary stage. That redundancy
    # is worth keeping and it means a faithful mutation has to remove BOTH guards, which is
    # exactly what "someone simplified this" would look like.
    real_dry = cs.dry_run

    def _forgiving(**force):
        def run(decisions, **kw):
            rep = real_dry(decisions, **kw)
            for st_ in rep.stages:
                if st_.name in force:
                    st_.ok = True
            return rep
        return run

    print("\nM10 - a rehearsal that never reached the wall reports success")
    with patch.object(cs.DryRunReport, "ok",
                      property(lambda self: all(s.ok for s in self.stages))):
        ok &= expect_red("M10", "both guards removed: boundary stage forced ok, property "
                                "no longer requires reached_boundary",
                         patch.object(cs, "dry_run", _forgiving(boundary=True)),
                         "test_24_a_run_that_never_reached_the_wall_is_NOT_ok")
        ok &= expect_red("M10b", "same mutation, against the empty-list case",
                         patch.object(cs, "dry_run", _forgiving(boundary=True)),
                         "test_25_an_empty_decision_list_is_not_a_successful_rehearsal")

    print("\nM11 - a mapping refusal no longer sinks the run")
    with patch.object(cs.DryRunReport, "ok",
                      property(lambda self: all(s.ok for s in self.stages))):
        ok &= expect_red("M11", "an unmapped order still reports a pass",
                         patch.object(cs, "dry_run",
                                      _forgiving(mapping=True, boundary=True)),
                         "test_26_a_mapping_refusal_is_captured_not_raised")

    print("\nM12 - the gate stage reports the SYNTHETIC answer")

    def synthetic_gate_report(root="."):
        return cs.DryRunGate()

    ok &= expect_red("M12", "the rehearsal's own gate reported as production's",
                     patch.object(x, "production_gate", synthetic_gate_report),
                     "test_16_the_gate_stage_reports_the_REAL_answer_not_the_synthetic_one")

    print("\nM13 - the precheck believes the wall's empty read")
    import global_index.track1_broker_read as brm
    ok &= expect_red(
        "M13", "'never asked' answered as 'flat'",
        patch.object(brm.Track1BrokerReader, "positions",
                     lambda self: brm.Answer(brm.KNOWN, [], "0 position(s)")),
        "test_18_the_precheck_says_entries_would_be_blocked")

    print("\nM14 - rejected decisions are mapped too")
    import global_index.track1_signal_layer as T
    ok &= expect_red("M14", "the cap gate's refusal ignored",
                     patch.object(T, "TAKE", "reject_cap"),
                     "test_20_a_rejected_decision_never_reaches_the_journal")

    # ══ 5. the coverage finding ════════════════════════════════════════════
    print("\nM15 - the safety jobs stop covering the Track 1 book")
    ok &= expect_red("M15", "the stub-scope finding invalidated",
                     patch.object(t1, "track1_safety_jobs", lambda: []),
                     "test_32_the_track1_safety_jobs_already_cover_stops_and_max_hold")

    print("\nM16 - the coverage table loses the switch finding")
    ok &= expect_red(
        "M16", "the one uncovered bypass goes unnamed",
        patch.object(cs, "COVERAGE",
                     tuple(c for c in cs.COVERAGE if c[0] != "switch_same_symbol")),
        "test_36_the_coverage_table_names_the_gap_it_found")

    print("\nM17 - the book file exists, so the safety jobs are already live")
    ok &= expect_red(
        "M17", "the no-op precondition gone",
        patch.object(Path, "exists", lambda self: True),
        "test_34_they_no_op_only_because_the_book_file_does_not_exist")

    # ══ 6. the walls around production ═════════════════════════════════════
    print("\nM18 - production imports the dry run")
    ok &= expect_red("M18", "an import added to a production module",
                     _source_patch(rld, "from __future__ import annotations",
                                   "from __future__ import annotations\n"
                                   "from global_index import track1_paper_callsite"),
                     "test_37_nothing_in_production_imports_the_dry_run_or_the_executor")

    print("\nM19 - the scheduler gains an arming flag")
    import global_index.run_scheduler as rs
    ok &= expect_red(
        "M19", "--allow-orders in a slot argv",
        _source_patch(rs, '"-m", "global_index.run_live_day_track1"',
                      '"-m", "global_index.run_live_day_track1", "--allow-orders"'),
        "test_38_no_scheduler_or_ops_path_can_trigger_a_send")

    print("\nM20 - the mode label reaches a second consumer")
    ok &= expect_red(
        "M20", "arming stops being only a label",
        _source_patch(rld, "root=root, mode=mode, as_of=now_et)",
                      "root=root, mode=mode, as_of=now_et)\n        _sink(mode=mode)"),
        "test_30_the_mode_label_still_reaches_only_the_explanation_writer")

    print("\nM21 - the evidence gate reports itself released")
    import global_index.track1_paper_readiness as pr
    ok &= expect_red("M21", "PAPER_SHADOW_EVIDENCE opened",
                     patch.object(pr, "gate_measurement", lambda root: (True, "5 days")),
                     "test_40_the_evidence_gate_still_blocks_and_reports_zero_days")

    print("\n" + "=" * 74)
    print("ALL MUTATIONS RED" if ok else "SOME MUTATIONS STAYED GREEN — tests do not bind")
    out = ROOT / "scratch" / "track1_stage5z_mutations_20260825.json"
    out.write_text(json.dumps({"all_red": bool(ok), "results": RESULTS}, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
