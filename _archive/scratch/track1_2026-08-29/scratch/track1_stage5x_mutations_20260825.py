"""Stage 5X mutation harness — make the read side fail OPEN, prove the right test goes red.

Every mutation here has the same shape: collapse "I do not know" back into "nothing". That is
the only direction that matters for this module, because the whole module exists to keep those
two apart.

Applied IN PROCESS. The Stage 5V/5W lessons hold: a mutation that patches the same object a
test patches, or that patches something the code calls once and reuses, stays green while
proving nothing. Anything that must change behaviour replaces the real callable.

Run:  python scratch/track1_stage5x_mutations_20260825.py
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

SUITE = "scratch/test_track1_stage5x_broker_readside_20260825.py"
RESULTS: list = []


def _run(test: str) -> int:
    buf = io.StringIO()
    with redirect_stdout(buf):
        return int(pytest.main(["-q", "-p", "no:randomly", "-x", f"{SUITE}::{test}"]))


def expect_red(label: str, what: str, patcher, test: str) -> bool:
    """Mutate, and require THIS test to go red - having first proved it was green.

    The baseline run is not ceremony. pytest exits non-zero when a test id does not exist,
    so a harness without it reports a renamed test as a passing mutation. That happened here:
    M13 read RED against a test name that had been changed one edit earlier, and the mutation
    was never exercised at all.
    """
    if _run(test) != 0:
        RESULTS.append({"id": label, "mutation": what, "test": test,
                        "outcome": "BASELINE NOT GREEN"})
        print(f"  [{label}] BASELINE NOT GREEN {test}")
        print("         ^-- the test is failing or does not exist; the mutation proves nothing")
        return False
    with patcher:
        code = _run(test)
    red = code != 0
    RESULTS.append({"id": label, "mutation": what, "test": test,
                    "outcome": "RED" if red else "STILL GREEN"})
    print(f"  [{label}] {'RED  ' if red else 'STILL GREEN'} {test}")
    if not red:
        print("         ^-- the test does not check this")
    return red


def _source_patch(module, replace_from: str, replace_to: str):
    """Serve mutated SOURCE for one module. Only valid for tests that READ the source."""
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
    import global_index.track1_broker_read as br
    import global_index.ibkr_broker as ib
    import global_index.run_live_day_track1 as rld

    print("Stage 5X mutations\n" + "=" * 74)
    ok = True

    # ── the reads collapse back ──────────────────────────────────────────────
    print("\nM1 - positions() believes a broker that cannot testify")

    def believe_anyone(self):
        try:
            return br.Answer(br.KNOWN, list(self.broker.get_positions()), "trusted")
        except Exception:
            return br.Answer(br.KNOWN, [], "trusted")

    ok &= expect_red("M1", "CAN_TESTIFY ignored",
                     patch.object(br.Track1BrokerReader, "positions", believe_anyone),
                     "test_2_an_empty_position_list_from_a_broker_that_cannot_testify_is_UNKNOWN")

    print("\nM2 - a raising read is answered as empty")
    ok &= expect_red("M2", "exception swallowed into []",
                     patch.object(br.Track1BrokerReader, "positions", believe_anyone),
                     "test_3_a_raising_read_is_UNKNOWN_not_empty")

    print("\nM3 - one unreadable position row is dropped instead of refusing the read")

    def drop_bad_rows(self):
        import global_index.track1_order_state as st
        if not bool(getattr(self.broker, "CAN_TESTIFY", True)):
            return br.Answer.unknown(br.CANNOT_TESTIFY, "")
        out = []
        for p in self.broker.get_positions() or []:
            try:
                out.append(st.Position(instrument=str(p.inst),
                                       direction=str(p.direction).lower(),
                                       contracts=int(abs(int(p.contracts)))))
            except Exception:
                continue                                   # <-- the mutation
        return br.Answer(br.KNOWN, out, f"{len(out)} position(s)")

    ok &= expect_red("M3", "a partly readable book answered as a book",
                     patch.object(br.Track1BrokerReader, "positions", drop_bad_rows),
                     "test_7_one_unreadable_position_row_makes_the_whole_read_UNKNOWN")

    print("\nM4 - None from get_open_orders read as 'nothing working'")

    def none_is_empty(self):
        raw = self.broker.get_open_orders()
        return br.Answer(br.KNOWN, list(raw or []), "")

    ok &= expect_red("M4", "the get_working_stops convention abandoned",
                     patch.object(br.Track1BrokerReader, "open_orders", none_is_empty),
                     "test_10_None_from_get_open_orders_is_UNKNOWN_offline")

    print("\nM5 - NOT_FOUND accepted as a definite answer")

    def status_is_gospel(self, order_id):
        return br.Answer(br.KNOWN, str(self.broker.get_order_status(str(order_id)) or ""), "")

    ok &= expect_red("M5", "NOT_FOUND treated as 'the order does not exist'",
                     patch.object(br.Track1BrokerReader, "order_status", status_is_gospel),
                     "test_12_NOT_FOUND_is_UNKNOWN_because_the_broker_also_says_it_on_error")

    print("\nM6 - None from find_execution read as 'no fill happened'")

    def none_is_no_fill(self, order_id, inst=None):
        return br.Answer(br.KNOWN, self.broker.find_execution(str(order_id), inst), "")

    ok &= expect_red("M6", "three meanings folded into one",
                     patch.object(br.Track1BrokerReader, "execution", none_is_no_fill),
                     "test_16_None_from_find_execution_is_UNKNOWN_never_no_fill_happened")

    # ── the resolution collapses ─────────────────────────────────────────────
    print("\nM7 - an unresolvable order is called REJECTED")
    real_resolve = br.resolve_submitted

    def silence_is_rejection(record, reader, *, order_id=""):
        v = real_resolve(record, reader, order_id=order_id)
        if v.resolution == br.RESOLVED_UNKNOWN:
            return br.SubmittedVerdict(br.RESOLVED_REJECTED, False, (), v.detail, v.evidence)
        return v

    ok &= expect_red("M7", "silence promoted to a broker statement",
                     patch.object(br, "resolve_submitted", silence_is_rejection),
                     "test_21_SUBMITTED_no_open_order_no_execution_positions_unchanged_is_UNKNOWN")
    ok &= expect_red("M7b", "same mutation, across every silent shape",
                     patch.object(br, "resolve_submitted", silence_is_rejection),
                     "test_27_silence_is_never_rejection_across_every_silent_shape")

    print("\nM8 - a partial fill is reported as a full fill")

    def partial_is_full(record, reader, *, order_id=""):
        v = real_resolve(record, reader, order_id=order_id)
        if v.resolution == br.RESOLVED_PARTIAL:
            return br.SubmittedVerdict(br.RESOLVED_FILLED, False, (), v.detail, v.evidence)
        return v

    ok &= expect_red("M8", "the remainder forgotten",
                     patch.object(br, "resolve_submitted", partial_is_full),
                     "test_23_a_partial_fill_stays_PARTIAL_and_keeps_blocking")

    print("\nM9 - FILLED with no execution record is accepted as FILLED")

    def filled_on_a_word(record, reader, *, order_id=""):
        v = real_resolve(record, reader, order_id=order_id)
        if "filled_without_execution_record" in v.reasons:
            return br.SubmittedVerdict(br.RESOLVED_FILLED, False, (), v.detail, v.evidence)
        return v

    ok &= expect_red("M9", "a book advanced on a size nobody stated",
                     patch.object(br, "resolve_submitted", filled_on_a_word),
                     "test_24_FILLED_without_an_execution_record_is_UNKNOWN_not_FILLED")

    print("\nM10 - a working order is matched on instrument alone")

    def match_on_instrument(order, record, order_id):
        get = order.get if isinstance(order, dict) else (
            lambda k, d=None: getattr(order, k, d))
        return str(get("instrument", "") or "") == str(
            getattr(record, "instrument", "") or "")

    ok &= expect_red("M10", "a stop on the same contract claimed as our entry",
                     patch.object(br, "_matches", match_on_instrument),
                     "test_20_a_stop_working_on_the_same_contract_is_not_our_entry")

    # ── what the route may still do ──────────────────────────────────────────
    print("\nM11 - an exit is allowed whether or not it reduces exposure")
    ok &= expect_red("M11", "reduces_exposure ignored",
                     patch.object(br, "exit_allowed",
                                  lambda **kw: (True, "allowed")),
                     "test_32_an_exit_that_does_not_reduce_exposure_is_refused_under_UNKNOWN")

    print("\nM12 - entries allowed while a row is still unresolved")
    ok &= expect_red("M12", "blocking rows not counted",
                     patch.object(br, "entries_allowed", lambda vs: (True, [])),
                     "test_30_entries_are_blocked_if_any_row_is_unresolved")

    # ── the broker-side additions ────────────────────────────────────────────
    print("\nM13 - get_open_orders returns [] offline instead of None")
    ok &= expect_red("M13", "'nothing working' and 'cannot say' collapse at the source",
                     _source_patch(ib, "            return None  # offline / test mode — cannot testify\n\n        ib = self._require_connection()\n        out: list = []",
                                   "            return []  # offline / test mode\n\n        ib = self._require_connection()\n        out: list = []"),
                     "test_40_get_open_orders_returns_None_offline_never_an_empty_list")

    print("\nM14 - NoOrderBroker loses its marker")
    ok &= expect_red("M14", "the shadow broker claims it can testify",
                     patch.object(rld.NoOrderBroker, "CAN_TESTIFY", True),
                     "test_43_NoOrderBroker_is_marked_as_unable_to_testify")

    print("\nM15 - a legacy reader is 'fixed' underneath the legacy route")
    ok &= expect_red("M15", "get_order_status stops returning NOT_FOUND on error",
                     _source_patch(ib, '            log.error("get_order_status(orderId=%s) failed: %s", order_id, exc)\n            return "NOT_FOUND"',
                                   '            log.error("get_order_status(orderId=%s) failed: %s", order_id, exc)\n            raise'),
                     "test_42_the_three_legacy_readers_were_not_modified")

    print("\nM16 - production imports the read module")
    ok &= expect_red("M16", "an import added to a production module",
                     _source_patch(rld, "from __future__ import annotations",
                                   "from __future__ import annotations\n"
                                   "from global_index import track1_broker_read"),
                     "test_45_nothing_in_production_imports_the_read_module_or_the_executor")

    print("\nM17 - the legacy route starts calling the new method")
    ok &= expect_red("M17", "get_open_orders wired into the runner",
                     _source_patch(rld, "    broker = NoOrderBroker()",
                                   "    broker = NoOrderBroker()\n"
                                   "    _ = broker.get_open_orders()"),
                     "test_41_get_open_orders_is_CALLED_by_nothing_in_the_legacy_route")

    print("\nM18 - the read module reaches for the LEGACY book")
    ok &= expect_red("M18", "live_positions.json path added to the read side",
                     _source_patch(br, 'STATUS_NOT_FOUND = "NOT_FOUND"',
                                   'STATUS_NOT_FOUND = "NOT_FOUND"\n'
                                   'LEGACY = "global_index/live_positions.json"'),
                     "test_49_neither_new_module_reads_or_writes_the_LEGACY_book")

    print("\nM19 - legacy loses its unsettled-positions banner")
    import global_index.runner as rn
    ok &= expect_red("M19", "runner.py's own compensation removed",
                     _source_patch(rn, "if not broker_pos and loaded_positions:",
                                   "if False and loaded_positions:"),
                     "test_50_the_legacy_route_compensates_at_the_call_site_and_still_does")

    print("\n" + "=" * 74)
    print("ALL MUTATIONS RED" if ok else "SOME MUTATIONS STAYED GREEN — tests do not bind")
    out = ROOT / "scratch" / "track1_stage5x_mutations_20260825.json"
    out.write_text(json.dumps({"all_red": bool(ok), "results": RESULTS}, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
