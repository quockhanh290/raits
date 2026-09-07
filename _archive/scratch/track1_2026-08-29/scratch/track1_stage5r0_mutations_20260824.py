"""Stage 5R-0 mutation harness — break the fix, prove the right test goes red, restore.

A test that has never been seen to fail has not been shown to check anything. Every mutation
is applied IN PROCESS with `unittest.mock.patch`, so nothing is written to disk and there is
no restore to get wrong.

Run:  python scratch/track1_stage5r0_mutations_20260824.py
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
for pth in (str(ROOT), str(ROOT / "scratch")):
    if pth not in sys.path:
        sys.path.insert(0, pth)

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

RESULTS: list[dict] = []
SUITE = "scratch/test_track1_stage5r0_boundary_tail_20260824.py"


def expect_red(label: str, what: str, patcher, test_name: str) -> bool:
    """Apply one mutation, run one test through pytest, and require it to FAIL.

    Run through pytest rather than by calling the function, because several of these tests
    take `tmp_path` and `monkeypatch` fixtures — reimplementing those here would be a second
    copy of pytest, and second copies are what this repo keeps getting caught by.
    """
    with patcher:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pytest.main(["-q", "-p", "no:randomly", "-x",
                                f"{SUITE}::{test_name}"])
    red = int(code) != 0
    RESULTS.append({"id": label, "mutation": what, "test": test_name,
                    "outcome": "RED" if red else "STILL GREEN"})
    print(f"  [{label}] {'RED  ' if red else 'STILL GREEN'} {test_name}")
    if not red:
        print("         ^-- the test does not check this")
    return red


def main() -> int:
    import global_index.track1_live_source as src
    import global_index.update_ibkr_daily as U

    print("Stage 5R-0 mutations\n" + "=" * 74)
    ok = True

    print("\nM1 — the final-tail drop is removed entirely (B-5R-H comes straight back)")
    ok &= expect_red(
        "M1", "drop_open_final_bar -> identity",
        patch.object(U, "drop_open_final_bar",
                     lambda df, *, observed_utc: (df, None, "mutated")),
        "test_1_a_fetch_ending_inside_the_final_minute_drops_that_bar")

    print("\nM1b — same mutation, seen through the REAL append instead of the pure function")
    ok &= expect_red(
        "M1b", "drop_open_final_bar -> identity",
        patch.object(U, "drop_open_final_bar",
                     lambda df, *, observed_utc: (df, None, "mutated")),
        "test_8_a_repair_run_no_longer_leaves_a_fresh_partial_tail")

    print("\nM2 — the final bar is dropped even when it has closed (data quietly lost)")
    ok &= expect_red(
        "M2", "drop_open_final_bar -> always drop the tail",
        patch.object(U, "drop_open_final_bar",
                     lambda df, *, observed_utc: (df.iloc[:-1], df.index[-1], "mutated")),
        "test_a_fetch_whose_last_bar_has_closed_appends_it")

    print("\nM2b — same, through the pure function's own contract")
    ok &= expect_red(
        "M2b", "drop_open_final_bar -> always drop the tail",
        patch.object(U, "drop_open_final_bar",
                     lambda df, *, observed_utc: (df.iloc[:-1], df.index[-1], "mutated")),
        "test_4_no_closed_bar_is_ever_dropped_however_late_the_observation")

    print("\nM3 — the boundary repair is skipped, so the PREVIOUS partial bar survives")
    ok &= expect_red(
        "M3", "boundary_replacement -> always (None, ...)",
        patch.object(U, "boundary_replacement",
                     lambda existing, fetched, *, last_existing: (None, "mutated: skipped")),
        "test_3_repair_boundary_repairs_the_previous_bar_and_appends_only_closed_ones")

    print("\nM4 — the parquet index is rewritten tz-AWARE (the 5Q-6 near miss)")
    _real_to_parquet = pd.DataFrame.to_parquet

    def _aware_to_parquet(self, *a, **kw):
        out = self.copy()
        idx = pd.DatetimeIndex(out.index)
        if idx.tz is None:
            out.index = idx.tz_localize("UTC").tz_convert("America/New_York")
        return _real_to_parquet(out, *a, **kw)

    ok &= expect_red(
        "M4", "DataFrame.to_parquet -> localise the index first",
        patch.object(pd.DataFrame, "to_parquet", _aware_to_parquet),
        "test_5c_the_written_parquet_stays_tz_naive_with_the_same_columns")

    print("\nM5 — the overlap guard is neutered")
    ok &= expect_red(
        "M5", "_refuse_overlap_disagreement -> no-op",
        patch.object(src, "_refuse_overlap_disagreement",
                     lambda inst, aligned, frozen: 0),
        "test_the_overlap_guard_still_refuses_a_disagreement")

    print("\nM6 — the clock is stamped AFTER the request instead of before")
    src_text = Path(U.__file__).read_text(encoding="utf-8")
    moved = src_text.replace(
        "    requested_at = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)\n"
        "    bars = ib.reqHistoricalData(",
        "    bars = ib.reqHistoricalData(")
    assert moved != src_text, "M6 could not find the stamp to move"

    _real_read_text = Path.read_text

    def _moved_read_text(self, *a, **kw):
        """Serve the mutated source to the AST test without touching the file on disk.

        A plain function, not a callable object: assigning an instance to a class attribute
        does not make it a bound method, so `self` never arrives.
        """
        if Path(self) == Path(U.__file__):
            return moved
        return _real_read_text(self, *a, **kw)

    ok &= expect_red(
        "M6", "requested_at stamped after reqHistoricalData",
        patch.object(Path, "read_text", _moved_read_text),
        "test_the_clock_is_stamped_BEFORE_the_request_goes_out")

    out = Path(__file__).resolve().parent / "_track1_stage5r0_mutations.json"
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
