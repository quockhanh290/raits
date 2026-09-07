"""Stage 5ZG mutation harness — every fix must be able to turn a named test red.

Source-level mutations applied to the real files and run in a SUBPROCESS. In-process
monkeypatching cannot express these: the scheduler wiring and the entry-point ordering are
not values you can patch, they are the shape of the code, and a patch that only replaces
`Path.read_text` changes nothing about an already-imported function. Six stages in a row
reported false GREEN that way.

Every mutation runs `expect_red`, which proves the selected tests GREEN first. A pytest run
that exits non-zero for a bad node id, an import error, or a collection failure is not a
mutation being caught — it is the harness lying, and that lie has been measured here before.

Nothing here touches runtime evidence: the only files edited are source files, each restored
and hash-verified before the next mutation runs.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zg_route_aware_safety_reporting_20260825.py"

STL = REPO / "global_index" / "safety_trade_log.py"
RUNNER = REPO / "global_index" / "runner.py"
SCHED = REPO / "global_index" / "run_scheduler.py"
REPAIR = REPO / "global_index" / "run_stop_repair.py"
MAXHOLD = REPO / "global_index" / "run_maxhold_exit.py"
SLOTS = REPO / "global_index" / "track1_slots.py"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pytest(node_ids):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
         *[f"{TEST}::{n}" for n in node_ids]],
        cwd=REPO, capture_output=True, text=True, timeout=600)


def expect_red(name, edits, node_ids):
    """edits: list of (path, old, new). All must apply exactly once."""
    base = _pytest(node_ids)
    if base.returncode != 0:
        print(f"  [HARNESS BROKEN] {name}: baseline is not green — "
              f"{base.stdout.strip().splitlines()[-1] if base.stdout.strip() else base.stderr[-300:]}")
        return False

    originals = {}
    try:
        for path, old, new in edits:
            src = path.read_text(encoding="utf-8")
            originals.setdefault(path, src)
            n = src.count(old)
            if n != 1:
                print(f"  [HARNESS BROKEN] {name}: anchor matched {n} times in {path.name}")
                return False
            path.write_text(src.replace(old, new), encoding="utf-8")
        res = _pytest(node_ids)
    finally:
        for path, src in originals.items():
            path.write_text(src, encoding="utf-8")
            # Compare the TEXT, not the bytes: this repo is CRLF throughout and
            # `read_text`/`write_text` normalise on the way in and translate on the way
            # out, so a byte comparison fails on a perfectly correct restore. The first
            # version of this line did exactly that and aborted the run mid-sweep.
            assert _digest(path.read_text(encoding="utf-8")) == _digest(src), \
                f"restore failed: {path}"

    last = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    ok = res.returncode != 0
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:52s} {last}")
    return ok


MUTATIONS = [
    # ── the contract module ──────────────────────────────────────────────────
    ("M1 destination ignored, always the legacy log",
     [(STL, '    dest = Path(trade_log_path)\n', '    dest = Path(DEFAULT_TRADE_LOG)\n')],
     ["test_a_relative_destination_resolves_against_the_repo_root_not_the_process_cwd",
      "test_an_absolute_destination_is_taken_as_given"]),

    ("M2 route without a destination is allowed",
     [(STL, '    if route is not None and trade_log_path is None:\n',
       '    if False:\n')],
     ["test_a_route_without_a_destination_is_refused",
      "test_a_route_without_a_destination_fails_the_job"]),

    ("M3 unwritable destination swallowed",
     [(STL, '    except OSError as exc:\n        raise TradeLogRefused(',
       '    except OSError as exc:\n        return dest, route\n    if False:\n        raise TradeLogRefused(')],
     ["test_an_unwritable_destination_is_refused_not_silently_redirected",
      "test_an_unwritable_destination_fails_the_job_before_it_connects"]),

    ("M4 probe truncates instead of appending",
     [(STL, '        with open(dest, "a", encoding="utf-8"):',
       '        with open(dest, "w", encoding="utf-8"):')],
     ["test_the_probe_does_not_truncate_an_existing_log"]),

    ("M5 default path probed and created like the rest",
     [(STL, '    if trade_log_path is None:\n        return (cwd / DEFAULT_TRADE_LOG), None\n',
       '    if trade_log_path is None:\n        (cwd / DEFAULT_TRADE_LOG).touch()\n'
       '        return (cwd / DEFAULT_TRADE_LOG), None\n')],
     ["test_the_default_path_is_not_probed_and_not_created"]),

    ("M6 refusal message no longer names the fallback",
     [(STL, 'f"sweep that closes a position and records it nowhere, or worse, into "\n'
            '            f"{DEFAULT_TRADE_LOG}.") from exc',
       'f"sweep that closes a position and records it nowhere.") from exc')],
     ["test_an_unwritable_destination_is_refused_not_silently_redirected"]),

    # ── the writer ───────────────────────────────────────────────────────────
    ("M7 route stamped even when nobody asked",
     [(RUNNER, '        if self._trade_log_route is not None:\n'
               '            record.setdefault("route", self._trade_log_route)\n',
       '        record.setdefault("route", self._trade_log_route)\n')],
     ["test_a_legacy_row_gains_no_route_key_at_all",
      "test_the_close_schema_is_unchanged_apart_from_the_tag"]),

    ("M8 route overwrites a row that already named one",
     [(RUNNER, '            record.setdefault("route", self._trade_log_route)\n',
       '            record["route"] = self._trade_log_route\n')],
     ["test_a_row_that_already_names_its_route_is_not_overruled"]),

    ("M9 route dropped entirely",
     [(RUNNER, '        if self._trade_log_route is not None:\n'
               '            record.setdefault("route", self._trade_log_route)\n', '')],
     ["test_a_simulated_track1_stop_repair_close_lands_in_the_track1_log",
      "test_a_simulated_track1_maxhold_close_lands_in_the_track1_log",
      "test_open_rows_are_tagged_too"]),

    ("M10 route is no longer last in the signature",
     [(RUNNER, '                 regime_fn=None, trade_log_path=None, today=None, now=None,\n'
               '                 route=None):',
       '                 regime_fn=None, trade_log_path=None, route=None, today=None,\n'
               '                 now=None):')],
     ["test_the_runners_route_defaults_to_none_for_every_existing_caller"]),

    # ── the two entry points ─────────────────────────────────────────────────
    ("M11 stop-repair back to the hardcoded legacy log",
     [(REPAIR, '            trade_log_path=str(trade_log_path),\n            route=trade_log_route,\n',
       '            trade_log_path=str(_CWD / "trade_log.jsonl"),\n')],
     ["test_both_entry_points_honour_the_track1_destination_and_tag",
      "test_a_simulated_track1_stop_repair_close_lands_in_the_track1_log"]),

    ("M12 max-hold back to the hardcoded legacy log",
     [(MAXHOLD, '            trade_log_path=str(trade_log_path),\n            route=trade_log_route,\n',
       '            trade_log_path=str(_CWD / "trade_log.jsonl"),\n')],
     ["test_both_entry_points_honour_the_track1_destination_and_tag",
      "test_a_simulated_track1_maxhold_close_lands_in_the_track1_log"]),

    ("M13 stop-repair keeps the destination, drops the tag",
     [(REPAIR, '            route=trade_log_route,\n', '            route=None,\n')],
     ["test_both_entry_points_honour_the_track1_destination_and_tag",
      "test_a_simulated_track1_stop_repair_close_lands_in_the_track1_log"]),

    ("M14 stop-repair checks the destination only after the positions check",
     [(REPAIR,
       '    try:\n        trade_log_path, trade_log_route = safety_trade_log.resolve(\n'
       '            a.trade_log_path, a.route, _CWD)\n'
       '    except safety_trade_log.TradeLogRefused as exc:\n'
       '        log.error("[trade-log] %s", exc)\n        return 1\n\n'
       '    pos_path = Path(a.positions_path)\n'
       '    if not pos_path.exists():\n'
       '        log.info("Không có %s — không có gì để sửa.", pos_path)\n        return 0\n',
       '    pos_path = Path(a.positions_path)\n'
       '    if not pos_path.exists():\n'
       '        log.info("Không có %s — không có gì để sửa.", pos_path)\n        return 0\n\n'
       '    try:\n        trade_log_path, trade_log_route = safety_trade_log.resolve(\n'
       '            a.trade_log_path, a.route, _CWD)\n'
       '    except safety_trade_log.TradeLogRefused as exc:\n'
       '        log.error("[trade-log] %s", exc)\n        return 1\n')],
     ["test_the_check_runs_before_the_positions_file_is_even_looked_at"]),

    ("M15 stop-repair refusal exits 0 instead of 1",
     [(REPAIR, '        log.error("[trade-log] %s", exc)\n        return 1\n',
       '        log.error("[trade-log] %s", exc)\n        return 0\n')],
     ["test_an_unwritable_destination_fails_the_job_before_it_connects",
      "test_a_route_without_a_destination_fails_the_job"]),

    ("M16 max-hold refusal exits 0 instead of 1",
     [(MAXHOLD, '        log.error("[trade-log] %s", exc)\n        return 1\n',
       '        log.error("[trade-log] %s", exc)\n        return 0\n')],
     ["test_an_unwritable_destination_fails_the_job_before_it_connects",
      "test_a_route_without_a_destination_fails_the_job"]),

    # ── the scheduler wiring ─────────────────────────────────────────────────
    ("M17 Track 1 stop-repair loses its destination",
     [(SCHED, '                  "--trade-log-path", _t1r.TRACK1_TRADE_LOG_PATH,\n'
              '                  "--route", _t1r.EVENT_ROUTE_VALUE,\n', '')],
     ["test_track1_stop_repair_argv_carries_the_book_the_log_the_lock_and_the_id",
      "test_the_scheduler_reads_the_constant_rather_than_repeating_the_path"]),

    ("M18 Track 1 max-hold loses its destination",
     [(SCHED, '                       "--trade-log-path", _t1r.TRACK1_TRADE_LOG_PATH,\n'
              '                       "--route", _t1r.EVENT_ROUTE_VALUE,\n', '')],
     ["test_track1_maxhold_argv_carries_the_book_the_log_and_its_own_marker",
      "test_the_scheduler_reads_the_constant_rather_than_repeating_the_path"]),

    ("M19 the path is repeated as a literal instead of read from the constant",
     [(SCHED, '\n                  "--trade-log-path", _t1r.TRACK1_TRADE_LOG_PATH,\n',
       '\n                  "--trade-log-path",\n'
       '                  "global_index/track1_runtime/trade_log.track1.jsonl",\n')],
     ["test_the_scheduler_reads_the_constant_rather_than_repeating_the_path"]),

    ("M20 the two-hourly legacy sweep is given the Track 1 log",
     [(SCHED,
       '                 "--positions-path", "live_positions.json", "--port", str(port)],',
       '                 "--positions-path", "live_positions.json",\n'
       '                 "--trade-log-path",\n'
       '                 "global_index/track1_runtime/trade_log.track1.jsonl",\n'
       '                 "--port", str(port)],')],
     ["test_the_legacy_drain_safety_never_touches_the_track1_log"]),

    ("M21 the Sunday legacy sweep starts passing a destination",
     [(SCHED,
       '\n             "--positions-path", "live_positions.json", "--port", str(port)],',
       '\n             "--positions-path", "live_positions.json",\n'
       '             "--trade-log-path", "x.jsonl", "--port", str(port)],')],
     ["test_the_other_two_modes_pass_no_destination_at_all",
      "test_the_legacy_drain_safety_never_touches_the_track1_log"]),

    # ── the constant ─────────────────────────────────────────────────────────
    ("M22 the Track 1 log collapses back onto the legacy filename",
     [(SLOTS, 'TRACK1_TRADE_LOG_PATH = "global_index/track1_runtime/trade_log.track1.jsonl"',
       'TRACK1_TRADE_LOG_PATH = "trade_log.jsonl"')],
     ["test_the_track1_log_is_a_separate_file_under_the_track1_runtime_root",
      "test_the_documented_policy_names_the_real_path_and_the_real_tag"]),

    ("M23 the tag stops matching every other Track 1 artefact",
     [(SLOTS, 'EVENT_ROUTE_VALUE = ROUTE', 'EVENT_ROUTE_VALUE = "track1"')],
     ["test_the_route_tag_is_the_same_value_every_other_track1_artefact_carries",
      "test_the_documented_policy_names_the_real_path_and_the_real_tag"]),

    ("M24 the documented policy stops naming the real destination",
     [(SLOTS, '    "trade_log": f"SEPARATE file {TRACK1_TRADE_LOG_PATH}, rows tagged {EVENT_ROUTE_FIELD}"',
       '    "trade_log": f"SEPARATE file, rows tagged {EVENT_ROUTE_FIELD}"')],
     ["test_the_documented_policy_names_the_real_path_and_the_real_tag"]),
]


def main() -> int:
    print(f"Stage 5ZG mutations — {len(MUTATIONS)} mutations\n")
    red = 0
    survivors = []
    for name, edits, nodes in MUTATIONS:
        if expect_red(name, edits, nodes):
            red += 1
        else:
            survivors.append(name)
    print(f"\n{red}/{len(MUTATIONS)} red")
    if survivors:
        print("SURVIVORS (a test that cannot go red is not a test):")
        for s in survivors:
            print(f"  - {s}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
