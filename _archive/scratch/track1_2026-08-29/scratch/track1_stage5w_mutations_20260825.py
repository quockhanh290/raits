"""Stage 5W mutation harness — break the executor, prove the right test goes red, restore.

Every mutation is applied IN PROCESS. The Stage 5V lesson is honoured here: patching a
module's SOURCE TEXT cannot change an already-imported method, so anything that must alter
behaviour replaces the real callable. The two mutations that are facts about the source text
are served through a patched `Path.read_text`, and they are marked as such.

Most of these do not remove a check — they make the module fail OPEN, which is the only
direction that matters for a file that could one day reach a broker.

Run:  python scratch/track1_stage5w_mutations_20260825.py
Exit code is non-zero if any mutation fails to turn its test red.
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

SUITE = "scratch/test_track1_stage5w_paper_executor_20260825.py"
RESULTS: list = []


def expect_red(label: str, what: str, patcher, test: str) -> bool:
    with patcher:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pytest.main(["-q", "-p", "no:randomly", "-x", f"{SUITE}::{test}"])
    red = int(code) != 0
    RESULTS.append({"id": label, "mutation": what, "test": test,
                    "outcome": "RED" if red else "STILL GREEN"})
    print(f"  [{label}] {'RED  ' if red else 'STILL GREEN'} {test}")
    if not red:
        print("         ^-- the test does not check this")
    return red


def _source_patch(module, replace_from: str, replace_to: str):
    """Serve mutated SOURCE for one module without touching the file on disk.

    Only valid for tests that READ the source. It cannot change behaviour — see Stage 5V M3.
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
    import global_index.track1_order_journal as j
    import global_index.track1_paper_executor as x

    print("Stage 5W mutations\n" + "=" * 74)
    ok = True

    # ── M1 ───────────────────────────────────────────────────────────────────
    print("\nM1 — the executor no longer demands an armed gate")

    def no_gate_check(self):
        pass

    ok &= expect_red("M1", "__post_init__ accepts any gate",
                     patch.object(x.Track1OrderExecutor, "__post_init__", no_gate_check),
                     "test_1_construction_refused_without_an_armed_gate")
    ok &= expect_red("M1b", "same mutation, against the REAL blocker table",
                     patch.object(x.Track1OrderExecutor, "__post_init__", no_gate_check),
                     "test_36_the_real_order_gate_still_refuses_to_arm")

    # ── M2 ───────────────────────────────────────────────────────────────────
    print("\nM2 — SUBMITTED is written AFTER the broker call instead of before")
    real_open = x.Track1OrderExecutor.open_position
    import global_index.track1_order_state as st
    import global_index.track1_paper_order as po

    def submit_late(self, decision, *, ref_day, slot_id=""):
        po.assert_admitted(decision)
        c = decision.candidate
        order = po.candidate_to_order(c, ref_day=ref_day, action="OPEN")
        key = j.idempotency_key(sleeve=order.cluster, instrument=order.inst,
                                ref_day=str(ref_day), action=order.action,
                                candidate_id=str(c.trade_id))
        common = dict(key=key, order=order, ref_day=ref_day, slot_id=slot_id,
                      candidate_id=c.trade_id)
        j.append(self._record(state=st.INTENDED, **common), root=self.journal_root)
        fill = self.broker.send_order(order)                       # <-- before the record
        j.append(self._record(state=st.SUBMITTED, **common), root=self.journal_root)
        j.append(self._record(state=self._classify(fill), **common), root=self.journal_root)
        return fill

    ok &= expect_red("M2", "send_order precedes the SUBMITTED record",
                     patch.object(x.Track1OrderExecutor, "open_position", submit_late),
                     "test_5_submitted_is_on_disk_BEFORE_the_broker_is_called")

    # ── M3 ───────────────────────────────────────────────────────────────────
    print("\nM3 — an unclassifiable broker answer is recorded as REJECTED")

    def classify_open(fill):
        s = str(getattr(fill, "status", "") or "").upper()
        return {"FILLED": st.FILLED, "PARTIAL": st.PARTIAL}.get(s, st.REJECTED)

    ok &= expect_red("M3", "unknown status folded into REJECTED",
                     patch.object(x.Track1OrderExecutor, "_classify",
                                  staticmethod(classify_open)),
                     "test_9_anything_unrecognised_is_UNKNOWN_never_REJECTED")

    # ── M4 ───────────────────────────────────────────────────────────────────
    print("\nM4 — a broker that raises is swallowed and the call returns None")

    def swallow(self, decision, *, ref_day, slot_id=""):
        try:
            return real_open(self, decision, ref_day=ref_day, slot_id=slot_id)
        except Exception:
            return None

    ok &= expect_red("M4", "the exception never reaches the caller",
                     patch.object(x.Track1OrderExecutor, "open_position", swallow),
                     "test_10_a_broker_that_raises_leaves_UNKNOWN_and_the_exception_propagates")

    # ── M5 ───────────────────────────────────────────────────────────────────
    print("\nM5 - the EXECUTOR swallows a failed journal write and sends anyway")
    # NOTE: patching j.append here would be unfaithful - the test patches the same object,
    # and its patch wins. The question is whether the EXECUTOR treats a refusal as fatal,
    # so the mutation goes on the executor.

    def open_best_effort(self, decision, *, ref_day, slot_id=""):
        po.assert_admitted(decision)
        c = decision.candidate
        order = po.candidate_to_order(c, ref_day=ref_day, action="OPEN")
        key = j.idempotency_key(sleeve=order.cluster, instrument=order.inst,
                                ref_day=str(ref_day), action=order.action,
                                candidate_id=str(c.trade_id))
        common = dict(key=key, order=order, ref_day=ref_day, slot_id=slot_id,
                      candidate_id=c.trade_id)
        for state in (st.INTENDED, st.SUBMITTED):
            try:
                j.append(self._record(state=state, **common), root=self.journal_root)
            except Exception:
                pass                                    # <-- the mutation
        fill = self.broker.send_order(order)
        try:
            j.append(self._record(state=self._classify(fill), **common),
                     root=self.journal_root)
        except Exception:
            pass
        return fill

    ok &= expect_red("M5", "the executor treats a journal refusal as best-effort",
                     patch.object(x.Track1OrderExecutor, "open_position", open_best_effort),
                     "test_6_a_journal_that_will_not_write_stops_the_order_reaching_the_broker")
    ok &= expect_red("M5b", "same mutation, against the SECOND write",
                     patch.object(x.Track1OrderExecutor, "open_position", open_best_effort),
                     "test_7_the_second_write_failing_also_stops_the_send")

    # ── M6 ───────────────────────────────────────────────────────────────────
    print("\nM6 — an unreadable book is answered as an empty book")

    def read_open(path=x.BOOK_PATH):
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            rows = raw.get("positions", raw) if isinstance(raw, dict) else raw
            return [st.Position(instrument=r["instrument"], direction=r["direction"],
                                contracts=int(r["contracts"])) for r in rows], "ok"
        except Exception:
            return [], "could not read"

    ok &= expect_red("M6", "read_book fails OPEN",
                     patch.object(x, "read_book", read_open),
                     "test_25_an_unreadable_book_is_NOT_an_empty_book")

    # ── M7 ───────────────────────────────────────────────────────────────────
    print("\nM7 — the executor advances the book itself after a fill")

    def open_and_write(self, decision, *, ref_day, slot_id=""):
        fill = real_open(self, decision, ref_day=ref_day, slot_id=slot_id)
        book = Path(self.journal_root) / x.BOOK_PATH
        book.parent.mkdir(parents=True, exist_ok=True)
        book.write_text(json.dumps({"positions": [
            {"instrument": fill.inst, "direction": fill.direction,
             "contracts": fill.contracts}]}), encoding="utf-8")
        return fill

    ok &= expect_red("M7", "live_positions.track1.json written by the executor",
                     patch.object(x.Track1OrderExecutor, "open_position", open_and_write),
                     "test_23_a_fill_does_not_create_or_change_the_book_file")

    print("     (and the same claim as a fact about the source, via read_text)")
    ok &= expect_red("M7b", "a writer appears in the module source",
                     _source_patch(x, "# ── the executor ─",
                                   "def _leak(p):\n    Path(p).write_text('')\n\n\n"
                                   "# ── the executor ─"),
                     "test_22_the_module_contains_no_write_to_the_track1_book")

    # ── M8 ───────────────────────────────────────────────────────────────────
    print("\nM8 — the journal records the HISTORY symbol instead of the order symbol")
    import global_index.track1_live_source as ls

    ok &= expect_red("M8", "tradable_symbol replaced by history_symbol",
                     patch.object(po, "tradable_symbol", ls.history_symbol),
                     "test_18_MNKD_journals_the_runner_name_and_the_ORDER_symbol_side_by_side")

    # -- M9 -------------------------------------------------------------------
    print("\nM9 - the executor recomputes the key for every record")
    # NOTE: patching j.idempotency_key would be UNFAITHFUL - the executor calls it once and
    # reuses the value, so a drifting stub changes nothing and the mutation stays green
    # while proving nothing. The break has to be in how the executor uses the key.

    def per_record_key(self, decision, *, ref_day, slot_id=""):
        po.assert_admitted(decision)
        c = decision.candidate
        order = po.candidate_to_order(c, ref_day=ref_day, action="OPEN")
        n = {"i": 0}

        def fresh():
            n["i"] += 1
            return j.idempotency_key(sleeve=order.cluster, instrument=order.inst,
                                     ref_day=str(ref_day), action=order.action,
                                     candidate_id=str(c.trade_id)) + f"-{n['i']}"

        def rec(state, **kw):
            return self._record(key=fresh(), state=state, order=order, ref_day=ref_day,
                                slot_id=slot_id, candidate_id=c.trade_id, **kw)

        j.append(rec(st.INTENDED), root=self.journal_root)
        j.append(rec(st.SUBMITTED), root=self.journal_root)
        fill = self.broker.send_order(order)
        j.append(rec(self._classify(fill)), root=self.journal_root)
        return fill

    ok &= expect_red("M9", "a fresh key on every record",
                     patch.object(x.Track1OrderExecutor, "open_position", per_record_key),
                     "test_19_the_idempotency_key_is_the_same_on_all_four_rows")

    # ── M10 ──────────────────────────────────────────────────────────────────
    print("\nM10 — reconcile drops the journal lines it could not parse")
    real_read = j.read

    ok &= expect_red("M10", "invalid lines silently discarded",
                     patch.object(j, "read", lambda **kw: (real_read(**kw)[0], [])),
                     "test_30_a_corrupt_journal_line_refuses_the_whole_reconcile")

    # ── M11 ──────────────────────────────────────────────────────────────────
    print("\nM11 — production imports the executor")
    import global_index.run_live_day_track1 as rld
    ok &= expect_red(
        "M11", "an import of track1_paper_executor added to a production module",
        _source_patch(rld,
                      "from __future__ import annotations",
                      "from __future__ import annotations\n"
                      "from global_index import track1_paper_executor"),
        "test_33_nothing_in_production_imports_the_executor")

    # ── M12 ──────────────────────────────────────────────────────────────────
    print("\nM12 — the scheduler starts passing --allow-orders")
    import global_index.run_scheduler as rs
    ok &= expect_red("M12", "the flag added to a slot argv",
                     _source_patch(rs, '"-m", "global_index.run_live_day_track1"',
                                   '"-m", "global_index.run_live_day_track1", "--allow-orders"'),
                     "test_38_no_caller_ever_passes_allow_orders")

    # -- M13 ------------------------------------------------------------------
    print("\nM13 - arming drops out of the freshness-binding set")
    import global_index.track1_explain as tx
    ok &= expect_red("M13", "ARMED no longer binds freshness",
                     patch.object(tx, "FRESHNESS_BINDING_MODES",
                                  frozenset({tx.SHADOW_LIVE})),
                     "test_40_arming_changes_only_the_recorded_mode_not_whether_freshness_binds")

    # -- M14 ------------------------------------------------------------------
    print("\nM14 - the mode label reaches a second consumer")
    ok &= expect_red("M14", "mode handed to a second call as well",
                     _source_patch(rld, "root=root, mode=mode, as_of=now_et)",
                                   "root=root, mode=mode, as_of=now_et)\n"
                                   "        _sink(mode=mode)"),
                     "test_41_the_mode_label_reaches_the_explanation_writer_and_nothing_else")

    # -- M15 ------------------------------------------------------------------
    print("\nM15 - a real broker is constructed on the run path")
    ok &= expect_red("M15", "NoOrderBroker replaced by IBKRBroker",
                     _source_patch(rld, "    broker = NoOrderBroker()",
                                   "    broker = IBKRBroker()"),
                     "test_42_the_broker_is_still_NoOrderBroker_on_the_run_path")

    print("\n" + "=" * 74)
    print("ALL MUTATIONS RED" if ok else "SOME MUTATIONS STAYED GREEN — tests do not bind")
    out = ROOT / "scratch" / "track1_stage5w_mutations_20260825.json"
    out.write_text(json.dumps({"all_red": bool(ok), "results": RESULTS}, indent=2),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
