"""Stage 5Q-7 mutation harness — break the fix, prove the right test goes red, restore.

A test that has never been seen to fail has not been shown to check anything. Every
mutation here is applied IN PROCESS with `unittest.mock.patch`, so nothing is written to
disk and there is no restore to get wrong.

Run:  python scratch/track1_stage5q7_mutations_20260824.py
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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import test_track1_stage5q7_mnkd_identity_20260824 as T  # noqa: E402

RESULTS: list[dict] = []


def expect_red(label: str, what: str, patcher, test_fn, *args):
    """Apply one mutation, run one test, and require it to fail."""
    with patcher:
        try:
            with redirect_stdout(io.StringIO()):
                test_fn(*args)
        except AssertionError as exc:
            lines = str(exc).strip().splitlines()
            first = (lines[0][:110] if lines else "(bare assert)")
            RESULTS.append({"id": label, "mutation": what, "test": test_fn.__name__,
                            "outcome": "RED", "message": first})
            print(f"  [{label}] RED   {test_fn.__name__}\n         {first}")
            return True
        except Exception as exc:
            RESULTS.append({"id": label, "mutation": what, "test": test_fn.__name__,
                            "outcome": "ERROR", "message": f"{type(exc).__name__}: {exc}"})
            print(f"  [{label}] ERROR {test_fn.__name__}: {type(exc).__name__}: {exc}")
            return True
    RESULTS.append({"id": label, "mutation": what, "test": test_fn.__name__,
                    "outcome": "STILL GREEN", "message": ""})
    print(f"  [{label}] STILL GREEN  {test_fn.__name__}  <-- the test does not check this")
    return False


def main() -> int:
    import global_index.track1_live_source as src
    import global_index.update_ibkr_daily as U
    import global_index.ibkr_broker as B

    print("Stage 5Q-7 mutations\n" + "=" * 72)

    ok = True

    print("\nM1 — the provider stops translating and hands the runner name to fetch_bars")
    ok &= expect_red(
        "M1", "src.history_symbol -> identity",
        patch.object(src, "history_symbol", lambda inst: inst),
        T.test_the_live_provider_asks_the_broker_for_nkd_when_given_mnkd)

    print("\nM2 — history_ibkr_symbol answers with Contract.data_symbol (the file stem)")
    from futures.basket import BASKET
    from global_index import specs as gi_specs
    tbl = {**BASKET, **gi_specs.SPECS}
    ok &= expect_red(
        "M2", "history_ibkr_symbol -> data_symbol",
        patch.object(U, "history_ibkr_symbol",
                     lambda inst: getattr(tbl.get(inst), "data_symbol", inst)),
        T.test_the_four_basket_instruments_are_asked_for_unchanged, "MES")

    print("\nM3 — history_ibkr_symbol answers with the ORDER symbol (the collapse)")
    ok &= expect_red(
        "M3", "history_ibkr_symbol -> _RAITS_TO_IBKR",
        patch.object(U, "history_ibkr_symbol",
                     lambda inst: B._RAITS_TO_IBKR.get(inst, inst)),
        T.test_the_live_provider_asks_the_broker_for_nkd_when_given_mnkd)

    print("\nM4 — the order map loses MNKD, so orders fall back to the full-size contract")
    ok &= expect_red(
        "M4", "_RAITS_TO_IBKR -> {}",
        patch.object(B, "_RAITS_TO_IBKR", {}),
        T.test_the_order_symbol_for_mnkd_is_still_mnk)

    print("\nM5 — the two identities are made equal (either direction is a defect)")
    ok &= expect_red(
        "M5", "_RAITS_TO_IBKR['MNKD'] = 'NKD'",
        patch.dict(B._RAITS_TO_IBKR, {"MNKD": "NKD"}),
        T.test_the_two_identities_for_mnkd_are_different_strings)

    print("\nM6 — the job table stops being the authority (a second copy drifts)")
    ok &= expect_red(
        "M6", "_build_jobs -> a table that disagrees",
        patch.object(U, "_build_jobs",
                     lambda d, n: [{"name": "MNKD", "ibkr_symbol": "MNK", "parquet": n}]),
        T.test_history_symbol_is_derived_from_the_job_table_that_built_the_files)

    print("\nM7 — point_value is 'fixed' to make the prices line up (the forbidden fix)")
    from dataclasses import replace
    ok &= expect_red(
        "M7", "SPECS['MNKD'].point_value = 5.0",
        patch.dict(gi_specs.SPECS,
                   {"MNKD": replace(gi_specs.SPECS["MNKD"], point_value=5.0)}),
        T.test_point_value_still_describes_the_micro)

    print("\nM8 — the recorded evidence is emptied of one arm")
    p = Path(__file__).resolve().parent / "_track1_stage5q7_mnkd_identity.json"
    if p.exists():
        good = json.loads(p.read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(good))
        bad["arms"]["NKD"]["disagreeing_bars"] = 7
        ok &= expect_red(
            "M8", "report says the NKD arm also disagreed",
            patch.object(Path, "read_text",
                         lambda self, *a, **k: json.dumps(bad)
                         if self.name == p.name else Path.read_text.__wrapped__(self, *a, **k)
                         if hasattr(Path.read_text, "__wrapped__") else good),
            T.test_the_measured_evidence_is_recorded_next_to_the_fix)
    else:
        print("  [M8] SKIPPED — no probe report in this checkout")
        RESULTS.append({"id": "M8", "outcome": "SKIPPED",
                        "mutation": "report emptied", "test": "-", "message": "no report"})

    out = Path(__file__).resolve().parent / "_track1_stage5q7_mutations.json"
    out.write_text(json.dumps(RESULTS, indent=2), encoding="utf-8")
    red = sum(1 for r in RESULTS if r["outcome"] in ("RED", "ERROR"))
    green = sum(1 for r in RESULTS if r["outcome"] == "STILL GREEN")
    print("\n" + "=" * 72)
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
