"""Stage 5Y mutation harness — break the order-id write path, prove the right test goes red.

Two families here, and they pull in opposite directions:

  * the id is LOST, or never recorded early enough to survive the fill poll;
  * the id is FABRICATED, or one order's id is allowed to answer for another.

The second family is the dangerous one. A missing id degrades to the Stage 5X fallback and
says so; a wrong id is believed.

`expect_red` proves each test green BEFORE mutating — the Stage 5X lesson, where a renamed
test read as a successful mutation because pytest exits non-zero on an unknown id.

Run:  python scratch/track1_stage5y_mutations_20260825.py
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

SUITE = "scratch/test_track1_stage5y_order_id_writepath_20260825.py"
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
        print("         ^-- failing or absent; the mutation proves nothing")
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
    """Serve mutated SOURCE for one module. Only valid for tests that READ the file.

    Stage 5X: a test using `inspect.getsource` reads the linecache and cannot be broken this
    way. Every test targeted below reads through `Path.read_text`.
    """
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
    import global_index.broker as b
    import global_index.ibkr_broker as ib
    import global_index.track1_broker_read as br
    import global_index.track1_order_journal as j
    import global_index.track1_order_state as st
    import global_index.track1_paper_executor as x

    print("Stage 5Y mutations\n" + "=" * 74)
    ok = True

    # ══ family 1: the id is lost ═══════════════════════════════════════════
    print("\nM1 - the executor stops asking for a receipt")
    ok &= expect_red("M1", "accepts_receipt always False",
                     patch.object(x, "accepts_receipt", lambda broker: False),
                     "test_15_a_fill_journals_intended_submitted_amended_then_filled")
    ok &= expect_red("M1b", "same mutation, against the in-flight proof",
                     patch.object(x, "accepts_receipt", lambda broker: False),
                     "test_17_the_amendment_is_written_while_send_order_is_still_in_flight")

    print("\nM2 - the receipt fires AFTER the fill poll instead of before")
    ok &= expect_red(
        "M2", "OrderReceipt moved below the poll loop",
        _source_patch(ib, "            if on_submit is not None:\n"
                          "                try:\n"
                          "                    on_submit(OrderReceipt(",
                      "            if on_submit is not None and not trade.isDone():\n"
                      "                while not trade.isDone():\n"
                      "                    pass\n"
                      "                try:\n"
                      "                    on_submit(OrderReceipt("),
        "test_11_the_receipt_fires_BEFORE_the_fill_poll")

    # ── a real replacement for `open_position`, parameterised ────────────────
    # M3, M7 and M13 were all written as source patches first and all three stayed green:
    # `_source_patch` changes what `Path.read_text` returns and nothing else, so it can never
    # alter an already-imported function. Third time in this file. The rule that actually
    # works: if the test asserts BEHAVIOUR, the mutation must replace the callable.
    def _executor_variant(*, outcome_id=None, missing_id="", guard_empty=True):
        def run(self, decision, *, ref_day, slot_id=""):
            import global_index.track1_paper_order as po
            po.assert_admitted(decision)
            c = decision.candidate
            order = po.candidate_to_order(c, ref_day=ref_day, action="OPEN")
            key = j.idempotency_key(sleeve=order.cluster, instrument=order.inst,
                                    ref_day=str(ref_day), action=order.action,
                                    candidate_id=str(c.trade_id))
            common = dict(key=key, order=order, ref_day=ref_day, slot_id=slot_id,
                          candidate_id=c.trade_id)
            seen: dict = {}

            def _receipt(r):
                oid = str(getattr(r, "order_id", "") or "")
                if guard_empty and not oid:
                    return
                seen["order_id"] = oid
                j.append(self._record(state=st.SUBMITTED, order_id=oid, **common),
                         root=self.journal_root)

            j.append(self._record(state=st.INTENDED, **common), root=self.journal_root)
            j.append(self._record(state=st.SUBMITTED, **common), root=self.journal_root)
            kw = {x.SUBMIT_CALLBACK: _receipt} if x.accepts_receipt(self.broker) else {}
            try:
                fill = self.broker.send_order(order, **kw)
            except BaseException as exc:
                j.append(self._record(state=st.UNKNOWN,
                                      error=f"{type(exc).__name__}: {exc}",
                                      order_id=seen.get("order_id", missing_id), **common),
                         root=self.journal_root)
                raise
            oid = str(getattr(fill, "order_id", "") or "")
            if outcome_id == "no_fallback":
                final = oid                       # <-- the receipt's answer discarded
            else:
                final = oid or seen.get("order_id", "")
            j.append(self._record(state=self._classify(fill), order_id=final, **common),
                     root=self.journal_root)
            return fill
        return run

    print("\nM3 - the outcome row forgets the id the receipt already reported")
    ok &= expect_red(
        "M3", "outcome_id falls back to nothing",
        patch.object(x.Track1OrderExecutor, "open_position",
                     _executor_variant(outcome_id="no_fallback")),
        "test_30_the_receipt_id_survives_a_Fill_that_forgot_it")

    print("\nM4 - a post-placement Fill stops carrying the id")
    ok &= expect_red(
        "M4", "the FILLED return drops order_id",
        _source_patch(ib, 'commission=commission, order_id=_oid,',
                      'commission=commission,'),
        "test_9_every_post_placement_Fill_carries_the_order_id")

    print("\nM5 - order_id is no longer the last field on Fill")
    # The test does `from global_index.broker import Fill`, so the name is bound in the test
    # module and patching `broker.Fill` never reaches it. `dataclasses.fields()` reads
    # `__dataclass_fields__` in insertion order, so reordering that dict is the mutation
    # that actually lands.
    _reordered = dict(b.Fill.__dataclass_fields__)
    _oid_field = _reordered.pop("order_id")
    _reordered["order_id"] = _oid_field
    _keys = list(_reordered)
    _keys.insert(_keys.index("contract_month"), _keys.pop(_keys.index("order_id")))
    ok &= expect_red(
        "M5", "order_id moved ahead of contract_month",
        patch.object(b.Fill, "__dataclass_fields__",
                     {k: _reordered[k] for k in _keys}),
        "test_1_order_id_is_the_LAST_field_and_defaults_to_None")

    # ══ family 2: the id is fabricated, or answers for the wrong order ══════
    print("\nM6 - test mode invents an order id")
    ok &= expect_red(
        "M6", "a fabricated identifier enters the journal",
        _source_patch(ib, """            return Fill(order.inst, order.action, order.direction,
                        order.contracts, order.cluster, order.pnl_sized)""",
                      """            return Fill(order.inst, order.action, order.direction,
                        order.contracts, order.cluster, order.pnl_sized,
                        order_id="test-1")"""),
        "test_10_test_mode_invents_no_id_and_fires_no_receipt")

    print("\nM7 - an exception BEFORE placement fabricates an id anyway")
    ok &= expect_red(
        "M7", "the missing id defaulted to a placeholder instead of empty",
        patch.object(x.Track1OrderExecutor, "open_position",
                     _executor_variant(missing_id="unknown-0")),
        "test_27_an_exception_BEFORE_the_receipt_records_UNKNOWN_with_NO_id")

    print("\nM8 - a working order with a DIFFERENT id is claimed by the weaker match")

    def fall_through(order, record, order_id):
        get = order.get if isinstance(order, dict) else (
            lambda k, d=None: getattr(order, k, d))
        theirs = str(get("order_id", "") or "")
        if order_id and theirs and theirs == order_id:
            return True, br.BY_ORDER_ID
        if str(get("instrument", "") or "") != str(getattr(record, "instrument", "") or ""):
            return False, br.NOT_MATCHED
        ra = str(getattr(record, "action", "") or "").upper()
        oa = str(get("action", "") or "").upper()
        return (bool(ra) and ra == oa), br.BY_INSTRUMENT_ACTION      # <-- the mutation

    ok &= expect_red("M8", "instrument+action consulted after an id mismatch",
                     patch.object(br, "_matches", fall_through),
                     "test_33_a_DIFFERENT_id_is_not_ours_and_the_weaker_match_is_not_consulted")

    # NOTE on M9-M11 and M13: these were written as source patches first and all four
    # stayed green. `_source_patch` only changes what `Path.read_text` returns; it cannot
    # change an already-imported function. That is the Stage 5V M3 lesson, repeated here in
    # the same session it was written down. Behaviour mutations replace the callable.

    print("\nM9 - the journal lets one id be replaced by another")

    def allow_replacement(previous, record):
        if not str(record.order_id or ""):
            raise j.OrderJournalRefused(j.BAD_AMENDMENT, "adds no id")
        return                                      # <-- the replacement guard is gone

    ok &= expect_red("M9", "two ids under one key accepted",
                     patch.object(j, "_check_amendment", allow_replacement),
                     "test_19_an_id_may_never_be_replaced")

    print("\nM10 - a second SUBMITTED row that adds nothing is accepted")

    def allow_empty(previous, record):
        if previous.order_id:
            raise j.OrderJournalRefused(j.BAD_AMENDMENT, "two orders")
        return                                      # <-- the adds-nothing guard is gone

    ok &= expect_red("M10", "a duplicate send looks like a legal history",
                     patch.object(j, "_check_amendment", allow_empty),
                     "test_18_an_amendment_that_adds_no_id_is_refused")

    print("\nM11 - an amendment may move the instrument")

    def allow_drift(previous, record):
        if previous.order_id:
            raise j.OrderJournalRefused(j.BAD_AMENDMENT, "two orders")
        if not str(record.order_id or ""):
            raise j.OrderJournalRefused(j.BAD_AMENDMENT, "adds no id")
        return                                      # <-- the field-drift guard is gone

    ok &= expect_red("M11", "a different order wearing a borrowed key",
                     patch.object(j, "_check_amendment", allow_drift),
                     "test_20_an_amendment_may_not_move_anything_else")

    print("\nM12 - SUBMITTED -> SUBMITTED opened in the state machine itself")
    ok &= expect_red(
        "M12", "the amendment turned into a real transition",
        patch.dict(st.ALLOWED_TRANSITIONS,
                   {st.SUBMITTED: frozenset({st.SUBMITTED, st.FILLED, st.PARTIAL,
                                             st.REJECTED, st.UNKNOWN})}),
        "test_21_the_state_machine_still_forbids_submitted_to_submitted")

    print("\nM13 - the executor writes an amendment it knows is unlawful")
    ok &= expect_red("M13", "an empty receipt id still writes a row",
                     patch.object(x.Track1OrderExecutor, "open_position",
                                  _executor_variant(guard_empty=False)),
                     "test_31_an_empty_receipt_id_writes_no_amendment")

    # ══ family 3: a live order reported as cancelled ════════════════════════
    print("\nM14 - a refused receipt is swallowed into Fill(status=CANCELLED)")
    ok &= expect_red(
        "M14", "OrderReceiptRefused caught by the broad handler",
        _source_patch(ib, "        except (IBKRConnectionError, OrderReceiptRefused):",
                      "        except IBKRConnectionError:"),
        "test_12_a_refused_receipt_is_re_raised_not_turned_into_a_cancelled_fill")

    print("\nM15 - the except path stops distinguishing placed from never-placed")
    ok &= expect_red(
        "M15", "live exposure and no exposure reported identically",
        _source_patch(ib, "            placed = trade is not None",
                      "            placed = False  # collapsed"),
        "test_13_the_except_path_separates_placed_from_never_placed")

    # ══ family 4: legacy moved ══════════════════════════════════════════════
    print("\nM16 - on_submit made positional, so every legacy caller shifts")

    def positional(self, order, on_submit=None):
        return None

    ok &= expect_red("M16", "the keyword-only marker removed",
                     patch.object(b.Broker, "send_order", positional),
                     "test_4_on_submit_is_keyword_only_with_a_default_everywhere")

    print("\nM17 - the legacy runner starts passing the new keyword")
    import global_index.runner as rn
    # The mutation must remain PARSEABLE. The first version produced
    # `send_order(on_submit=None, Order(...))` - positional after keyword, a SyntaxError -
    # and test_43 skipped the unparseable file and passed. That skip was a real hole and is
    # now a failure in its own right; the mutation here is valid Python.
    ok &= expect_red(
        "M17", "a legacy call site changed",
        _source_patch(rn, "_f = self.broker.send_order(Order(",
                      "_f = self.broker.send_order(on_submit=None, order=Order("),
        "test_43_no_legacy_caller_passes_the_new_keyword")

    print("\nM18 - MockBroker stops recording its fills")
    real_mock_send = b.MockBroker.send_order

    def forgetful(self, order, *, on_submit=None):
        f = real_mock_send(self, order, on_submit=on_submit)
        self.fills.clear()                            # <-- the verify path's record gone
        return f

    ok &= expect_red("M18", "the verify path's fills list broken",
                     patch.object(b.MockBroker, "send_order", forgetful),
                     "test_6_MockBroker_still_returns_a_Fill_and_now_names_it")

    print("\nM19 - the exit rule loses its exposure check")
    ok &= expect_red("M19", "an oversized close allowed under UNKNOWN",
                     patch.object(br, "exit_allowed", lambda **kw: (True, "allowed")),
                     "test_41_an_oversized_close_is_still_blocked")

    print("\nM20 - production imports the executor")
    import global_index.run_live_day_track1 as rld
    ok &= expect_red("M20", "an import added to a production module",
                     _source_patch(rld, "from __future__ import annotations",
                                   "from __future__ import annotations\n"
                                   "from global_index import track1_paper_executor"),
                     "test_47_the_executor_is_still_imported_by_nothing")

    # ══ family 5: the amendment must survive READ-BACK ══════════════════════
    # This family exists because the stage shipped broken once: `append` accepted the
    # amendment and `resolve` called the resulting journal impossible, so every order that
    # got an id made that day's journal unreadable. Fifty-two tests passed over it.
    print("\nM21 - resolve_journal stops recognising the amendment")
    ok &= expect_red("M21", "the writer and the reader disagree again",
                     patch.object(st, "is_amendment", lambda prev, rec: False),
                     "test_52_a_journal_containing_an_amendment_still_resolves")

    print("\nM22 - is_amendment accepts ANY repeated SUBMITTED row")
    ok &= expect_red("M22", "a duplicate send reads as lawful on read-back",
                     patch.object(st, "is_amendment", lambda prev, rec: True),
                     "test_57_a_hand_written_double_submitted_with_no_id_is_still_impossible")

    print("\nM23 - is_amendment lets one id be replaced by another")

    def loose(previous, record):
        if previous is None:
            return False
        return (getattr(previous, "state", None) == st.SUBMITTED
                and getattr(record, "state", None) == st.SUBMITTED)

    ok &= expect_red("M23", "two ids under one key accepted by the shared rule",
                     patch.object(st, "is_amendment", loose),
                     "test_56_is_amendment_refuses_everything_that_is_not_one")

    print("\n" + "=" * 74)
    print("ALL MUTATIONS RED" if ok else "SOME MUTATIONS STAYED GREEN — tests do not bind")
    out = ROOT / "scratch" / "track1_stage5y_mutations_20260825.json"
    out.write_text(json.dumps({"all_red": bool(ok), "results": RESULTS}, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
