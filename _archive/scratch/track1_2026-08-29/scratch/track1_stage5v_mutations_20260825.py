"""Stage 5V mutation harness — break the journal, prove the right test goes red, restore.

A fail-closed writer that has never been seen to fail open has not been shown to be fail-closed.
Each mutation is applied IN PROCESS with `unittest.mock.patch`, except the two that are facts
about the source text, which are served through a patched `Path.read_text` so nothing on disk
is edited.

Run:  python scratch/track1_stage5v_mutations_20260825.py
Exit code is non-zero if any mutation fails to turn its test red.
"""
from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scratch")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest  # noqa: E402

SUITE = "scratch/test_track1_stage5v_order_journal_20260825.py"
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
    """Serve mutated SOURCE for one module without touching the file on disk."""
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
    import global_index.track1_order_state as st

    print("Stage 5V mutations\n" + "=" * 74)
    ok = True

    print("\nM1 — the append swallows its write exception (fails OPEN)")
    real_append = j.append

    def swallowing_append(record, *, root=".", day=None):
        try:
            return real_append(record, root=root, day=day)
        except Exception:
            return None                     # the defect: pretends success
    ok &= expect_red("M1", "append catches and returns None",
                     patch.object(j, "append", swallowing_append),
                     "test_a_write_failure_raises_and_does_not_pretend_success")

    print("\nM1b — the same, seen through the source rather than the behaviour")
    ok &= expect_red(
        "M1b", "a try/except wrapped around append's write",
        _source_patch(j,
                      "    with open(target, \"a\", encoding=\"utf-8\") as fh:",
                      "    try:\n     with open(target, \"a\", encoding=\"utf-8\") as fh:"),
        "test_the_module_catches_nothing_around_its_write")

    print("\nM2 — INTENDED -> FILLED is allowed")
    mutated = dict(st.ALLOWED_TRANSITIONS)
    mutated[st.INTENDED] = frozenset(mutated[st.INTENDED] | {st.FILLED})
    ok &= expect_red("M2", "ALLOWED_TRANSITIONS[INTENDED] gains FILLED",
                     patch.object(st, "ALLOWED_TRANSITIONS", mutated),
                     "test_intended_to_filled_is_refused")

    print("\nM3 — the route stamp is no longer required")
    # A REAL in-process mutation. The first version patched the SOURCE TEXT, which cannot
    # change an already-imported `__post_init__` — it stayed green and proved nothing. An
    # unfaithful mutation is worse than no mutation: it reports a test as protective when it
    # has not been shown to be.
    def no_route_check(self):
        if self.state not in st.ORDER_STATES:
            raise j.OrderJournalRefused(j.BAD_RECORD, f"unknown state {self.state!r}")
        for name in ("idempotency_key", "ref_day", "sleeve", "instrument",
                     "tradable_symbol", "action", "candidate_id", "created_at"):
            if not str(getattr(self, name) or "").strip():
                raise j.OrderJournalRefused(j.BAD_RECORD, f"{name} is empty")
        # the route check is gone — that is the defect

    ok &= expect_red(
        "M3", "JournalRecord.__post_init__ stops checking the route stamp",
        patch.object(j.JournalRecord, "__post_init__", no_route_check),
        "test_a_record_without_the_route_stamp_is_refused")

    print("\nM4 — a day string may escape the journal directory")
    real_path = j.journal_path

    def loose_path(day, root="."):
        base = j.journal_dir(root)
        base.mkdir(parents=True, exist_ok=True)
        return (base / f"track1_orders_{day}.jsonl")
    ok &= expect_red("M4", "journal_path stops validating the day",
                     patch.object(j, "journal_path", loose_path),
                     "test_a_day_that_could_escape_the_journal_directory_is_refused")

    print("\nM5 — the reader silently drops what it cannot parse")
    real_read = j.read

    def quiet_read(*, root=".", day=None):
        recs, _invalid = real_read(root=root, day=day)
        return recs, []                     # the defect: corruption disappears
    ok &= expect_red("M5", "read() returns an empty invalid list",
                     patch.object(j, "read", quiet_read),
                     "test_a_corrupt_line_is_reported_by_the_reader")

    print("\nM5b — and the corrupt journal then authorises another order")
    ok &= expect_red("M5b", "read() returns an empty invalid list",
                     patch.object(j, "read", quiet_read),
                     "test_a_corrupt_journal_refuses_to_authorise_another_order")

    print("\nM5c — an impossible history already on disk is silently repaired")
    real_resolve_journal = st.resolve_journal

    def repairing(records):
        out = real_resolve_journal(records)
        out["impossible"] = []              # the defect
        return out
    ok &= expect_red("M5c", "resolve_journal hides impossible histories",
                     patch.object(st, "resolve_journal", repairing),
                     "test_an_impossible_history_already_on_disk_is_refused_not_repaired")

    print("\nM6 — the module imports a broker")
    ok &= expect_red(
        "M6", "an ib_insync import added to the journal",
        _source_patch(j, "import json\nimport os",
                      "import json\nimport os\nimport ib_insync"),
        "test_this_module_cannot_reach_a_broker")

    print("\nM7 — the write is no longer fsynced (durable in name only)")
    ok &= expect_red(
        "M7", "os.fsync removed from append",
        _source_patch(j, "        os.fsync(fh.fileno())", "        pass"),
        "test_the_write_is_flushed_and_fsynced")

    out = Path(__file__).resolve().parent / "_track1_stage5v_mutations.json"
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    red = sum(1 for r in RESULTS if r["outcome"] == "RED")
    green = sum(1 for r in RESULTS if r["outcome"] == "STILL GREEN")
    print("\n" + "=" * 74)
    print(f"{red} mutation(s) turned a test red, {green} did not")
    print(f"wrote {out}")
    return 0 if green == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
