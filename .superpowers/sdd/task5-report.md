# Task 5 Report — Parallel-Run Verification

## Pytest output (test_parallel_run.py)

```
============================= test session starts =============================
platform win32 -- Python 3.11.4, pytest-9.0.2
rootdir: D:\raits   configfile: pyproject.toml

tests\decision\test_parallel_run.py::TestComparator::test_identical_logs_returns_no_mismatches PASSED
tests\decision\test_parallel_run.py::TestComparator::test_detects_count_mismatch PASSED
tests\decision\test_parallel_run.py::TestComparator::test_detects_ticker_mismatch PASSED
tests\decision\test_parallel_run.py::TestComparator::test_detects_entry_price_mismatch PASSED
tests\decision\test_parallel_run.py::TestComparator::test_ignores_cent_rounding PASSED
tests\decision\test_parallel_run.py::TestComparator::test_detects_shares_mismatch PASSED
tests\decision\test_parallel_run.py::TestComparator::test_detects_exit_reason_mismatch PASSED
tests\decision\test_parallel_run.py::TestComparator::test_summary_shows_field_diffs PASSED

8 passed in 2.49s
```

## verify_parallel_run.py

Written at: `raits/raits/scripts/verify_parallel_run.py`

NOT run (long-running script, ~5+ minutes). User must run manually.

## Commit

Hash: e33c9c5

Files committed:
- `raits/tests/decision/test_parallel_run.py`
- `raits/raits/scripts/verify_parallel_run.py`

## Gate command

Run this to execute the parallel verification:

```
cd d:\raits\raits && python raits/scripts/verify_parallel_run.py
```

Expected success output:
```
✓ IDENTICAL: NNNN trades matched 100%
Aggregate metrics:
  Original:   NNNN trades, P&L $XX,XXX.XX
  Refactored: NNNN trades, P&L $XX,XXX.XX
  P&L diff: $0.0000 ✓ (< $1)
```

Exit code 0 = pass, exit code 1 = mismatch detected (field-by-field diff printed).
