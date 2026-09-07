"""Stage 5ZH mutation harness — every branch of the new checkpoint rule can turn a test red.

Source-level edits applied to the real files and run in a SUBPROCESS. `expect_red` proves the
selected tests GREEN first: a pytest run that exits non-zero for a bad node id or an import
error is the harness lying, not a mutation being caught.

The restore compares TEXT, not bytes — this repo is CRLF throughout and `read_text` /
`write_text` normalise on the way in and translate on the way out, so a byte comparison fails
on a perfectly correct restore. That cost a whole sweep in Stage 5ZG.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zh_quiet_checkpoint_audit_20260825.py"
ACC = REPO / "global_index" / "track1_shadow_acceptance.py"
TRR = REPO / "monitor" / "backend" / "track1_runtime_reader.py"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pytest(node_ids):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
         *[f"{TEST}::{n}" for n in node_ids]],
        cwd=REPO, capture_output=True, text=True, timeout=600)


def expect_red(name, edits, node_ids):
    base = _pytest(node_ids)
    if base.returncode != 0:
        tail = base.stdout.strip().splitlines()[-1] if base.stdout.strip() else base.stderr[-200:]
        print(f"  [HARNESS BROKEN] {name}: baseline is not green — {tail}")
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
            assert _digest(path.read_text(encoding="utf-8")) == _digest(src), \
                f"restore failed: {path}"
    last = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    ok = res.returncode != 0
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:54s} {last}")
    return ok


MUTATIONS = [
    ("M1 back to the flat top-level route lookup",
     [(ACC, '    routes = payload.get("routes")\n',
       '    routes = {payload.get("route"): {"sleeves": payload.get("sleeves") or {}}}\n'
       '    routes = routes if payload.get("route") else payload.get("routes")\n')],
     ["test_schema_2_with_routes_track1_candidate_is_accepted",
      "test_the_flat_payload_three_suites_used_as_a_fixture_is_refused"]),

    ("M2 a foreign route passes",
     [(ACC, '    if AUDIT_ROUTE not in routes:\n', '    if False:\n')],
     ["test_a_checkpoint_for_another_route_still_fails",
      "test_the_same_window_with_a_foreign_route_checkpoint_fails"]),

    ("M3 an empty checkpoint passes without asking the book",
     [(ACC, '    # Quiet window: no entries, so no day on the checkpoint. Ask its companion book.\n'
            '    book = root / CHECKPOINT_BOOK_PATH\n',
       '    return _check("checkpoint", OK, "quiet", code=CK_OK, entries=False)\n'
       '    book = root / CHECKPOINT_BOOK_PATH\n')],
     ["test_empty_instruments_with_no_book_cannot_be_dated_and_fail",
      "test_empty_instruments_with_a_book_from_another_day_fail_as_wrong_day",
      "test_the_same_window_with_no_book_fails_as_unverifiable_not_as_ok"]),

    ("M4 a missing book is treated as fine rather than unverifiable",
     [(ACC, '    if not book.exists():\n        return _check("checkpoint", FAIL,',
       '    if not book.exists():\n        return _check("checkpoint", OK, "no book", code=CK_OK)\n'
       '    if False:\n        return _check("checkpoint", FAIL,')],
     ["test_empty_instruments_with_no_book_cannot_be_dated_and_fail",
      "test_the_same_window_with_no_book_fails_as_unverifiable_not_as_ok"]),

    ("M5 the book's day is not compared to the day under judgment",
     [(ACC, '    if cut != day:\n        return _check("checkpoint", FAIL,\n'
            '                      f"route present and empty, and the book it was written with is cut "',
       '    if False:\n        return _check("checkpoint", FAIL,\n'
            '                      f"route present and empty, and the book it was written with is cut "')],
     ["test_empty_instruments_with_a_book_from_another_day_fail_as_wrong_day",
      "test_the_same_window_with_yesterdays_book_fails_as_wrong_day"]),

    ("M6 entries' last_day is not compared to the day",
     [(ACC, '        if last_days != [day]:\n', '        if False:\n')],
     ["test_entries_cut_on_another_day_fail_even_if_the_book_says_today",
      "test_entries_spread_over_two_days_fail"]),

    ("M7 entries defer to the book instead of deciding for themselves",
     [(ACC, '    if last_days:\n', '    if False:\n')],
     ["test_entries_cut_today_pass_without_any_book",
      "test_entries_cut_on_another_day_fail_even_if_the_book_says_today"]),

    ("M8 a schema 1 payload is accepted",
     [(ACC, '    if schema != 2:\n', '    if False:\n')],
     ["test_a_routes_shaped_payload_of_another_schema_is_still_refused",
      "test_a_payload_of_the_wrong_shape_is_named_as_such_not_as_a_wrong_day"]),

    ("M9 every failure code collapses back into wrong_day",
     [(ACC, '            reasons.append(CHECKPOINT_REASON_BY_CODE.get(\n'
            '                ck_check.get("code"), R_CHECKPOINT_WRONG_DAY))\n',
       '            reasons.append(R_CHECKPOINT_WRONG_DAY)\n')],
     ["test_the_same_window_without_a_checkpoint_fails",
      "test_the_same_window_with_a_foreign_route_checkpoint_fails",
      "test_the_same_window_with_no_book_fails_as_unverifiable_not_as_ok",
      "test_rewording_a_detail_cannot_change_the_reason"]),

    ("M10 the checkpoint is demanded of an incomplete window too",
     [(ACC, '        if st["outcome"] == wl.COMPLETE and ck_check.get("status") == FAIL:\n',
       '        if ck_check.get("status") == FAIL:\n')],
     ["test_a_checkpoint_is_only_required_of_a_window_that_completed"]),

    ("M11 the code is dropped from the audit row",
     [(ACC, '                       "code": ck_check.get("code"),\n', '')],
     ["test_the_check_is_reported_with_its_code_on_the_audit_row"]),

    ("M12 the wrong-route failure stops naming what it found",
     [(ACC, '                      f"route {AUDIT_ROUTE!r} is not in the checkpoint; it holds "\n'
            '                      f"{sorted(routes)!r}",',
       '                      "the checkpoint does not name this route",')],
     ["test_a_checkpoint_for_another_route_still_fails"]),

    # ── the dashboard reader, the same defect read twice ─────────────────────
    ("M13 the panel goes back to the flat route lookup",
     [(TRR, '            "route": ROUTE if ROUTE in routes else None,\n',
       '            "route": p.get("route"),\n')],
     ["test_the_panel_names_the_route_the_checkpoint_actually_carries",
      "test_the_panel_reports_no_route_when_the_checkpoint_is_another_routes"]),

    ("M14 the panel goes back to the flat sleeve lookup",
     [(TRR, '        mine = (routes.get(ROUTE) or {}).get("sleeves") or {}\n',
       '        mine = p.get("sleeves") or {}\n')],
     ["test_the_panel_lists_the_sleeves_the_checkpoint_holds",
      "test_the_panel_counts_entries_and_reports_their_cut_day"]),

    ("M15 the panel invents a cut day when the entries disagree",
     [(TRR, '            "cut_instant": days[0] if len(days) == 1 else None,\n',
       '            "cut_instant": days[0] if days else str(_dt.date.today()),\n')],
     ["test_the_panel_says_no_day_rather_than_inventing_one_for_a_quiet_checkpoint"]),
]


def main() -> int:
    live = [m for m in MUTATIONS if m[2]]
    print(f"Stage 5ZH mutations — {len(live)} mutations\n")
    red, survivors = 0, []
    for name, edits, nodes in live:
        if expect_red(name, edits, nodes):
            red += 1
        else:
            survivors.append(name)
    print(f"\n{red}/{len(live)} red")
    if survivors:
        print("SURVIVORS (a test that cannot go red is not a test):")
        for s in survivors:
            print(f"  - {s}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
