"""Stage 5ZZW mutation harness — can the mode and pruning tests turn red?

Two temptations here. Suppressing an alarm is easy to do too widely, so M3 and M4 break the
suppression in the permissive direction and the suite has to notice a real fault going quiet.
And hiding issues is easy to do too eagerly, so M6 and M7 retire things that are not retired.

Source-level edits in a subprocess, restored afterwards. The restore compares TEXT, not bytes:
the repo is CRLF and read_text/write_text translate on the way through.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzw_dashboard_track1_mode_hygiene_20260828.py"
SS = REPO / "monitor" / "backend" / "schedule_status.py"
OI = REPO / "monitor" / "backend" / "open_issue_reader.py"
JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pytest(specs):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
         "-p", "no:randomly", *specs],
        cwd=REPO, capture_output=True, text=True, timeout=1200)


def expect_red(name, edits, specs):
    base = _pytest(specs)
    if base.returncode != 0:
        tail = base.stdout.strip().splitlines()[-1] if base.stdout.strip() else base.stderr[-300:]
        print(f"  [HARNESS BROKEN] {name}: baseline not green — {tail}")
        return False
    originals = {}
    try:
        for path, old, new in edits:
            src = path.read_text(encoding="utf-8")
            originals.setdefault(path, src)
            n = src.count(old)
            if n != 1:
                print(f"  [HARNESS BROKEN] {name}: anchor matched {n}x in {path.name}")
                return False
            path.write_text(src.replace(old, new), encoding="utf-8")
        res = _pytest(specs)
    finally:
        for path, src in originals.items():
            path.write_text(src, encoding="utf-8")
            assert _digest(path.read_text(encoding="utf-8")) == _digest(src), f"restore: {path}"
    last = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
    ok = res.returncode != 0
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:60s} {last}")
    return ok


N = f"{TEST}::"

MUTATIONS = [
    # ── the mode source ───────────────────────────────────────────────────────────────────
    ("M1 the backend goes back to reading its own environment",
     [(SS, "    explicit = _os.environ.get(\"RAITS_TRACK1_ONLY\")\n"
           "    if explicit is not None:\n"
           "        return explicit == \"1\"\n"
           "    return scheduler_track1_only()",
           "    return _os.environ.get(\"RAITS_TRACK1_ONLY\") == \"1\"")],
     [N + "test_the_mode_is_resolved_from_the_scheduler_not_this_process",
      N + "test_an_unknown_mode_is_carried_as_unknown"]),

    ("M2 an unreadable scheduler is reported as legacy",
     [(SS, "    if status.get(\"track1_mode_source\") != \"process_table\":\n        return None",
           "    if status.get(\"track1_mode_source\") != \"process_table\":\n        return False")],
     [N + "test_the_resolver_refuses_a_scheduler_it_could_not_scan"]),

    ("M3 the legacy snapshot raises the route again",
     [(SS, "    legacy_inactive_by_design = resolved_track1_only is True",
           "    legacy_inactive_by_design = False")],
     [N + "test_a_stale_legacy_snapshot_does_not_make_the_route_stale",
      N + "test_track1_only_reports_its_route_and_says_where_that_came_from"]),

    ("M4 the suppression becomes unconditional, so a live legacy fault goes quiet",
     [(SS, "    legacy_inactive_by_design = resolved_track1_only is True",
           "    legacy_inactive_by_design = True")],
     [N + "test_the_same_snapshot_still_raises_the_route_when_legacy_is_live"]),

    ("M5 unknown collapses into track1-only",
     [(SS, '        "route_mode": ("track1_only_shadow" if resolved_track1_only is True\n'
           '                       else "legacy" if resolved_track1_only is False else "unknown"),',
           '        "route_mode": ("legacy" if resolved_track1_only is False '
           'else "track1_only_shadow"),')],
     [N + "test_an_unknown_mode_is_carried_as_unknown"]),

    # ── the pruning ───────────────────────────────────────────────────────────────────────
    ("M6 legacy issues are hidden without checking the confirmation",
     [(OI, "    retired = bool(confirmation and mode == \"compatible\" and jobs == 0)",
           "    retired = bool(mode == \"compatible\" and jobs == 0)")],
     [N + "test_legacy_is_retired_only_when_all_three_conditions_hold"]),

    ("M7 legacy issues are hidden even when the scheduler could not be read",
     [(OI, "    if status.get(\"track1_mode_source\") != \"process_table\":\n        return unknown",
           "    if False:\n        return unknown")],
     [N + "test_an_unreadable_scheduler_leaves_legacy_issues_counted"]),

    ("M8 retired issues are deleted from the payload instead of marked",
     [(OI, "    payload[\"active_count\"] = sum(1 for i in issues if i[\"counts_as_active\"])",
           "    payload[\"issues\"] = [i for i in issues if i[\"counts_as_active\"]]\n"
           "    payload[\"active_count\"] = len(payload[\"issues\"])")],
     [N + "test_retired_legacy_issues_leave_the_active_count_but_stay_in_the_payload"]),

    ("M9 the model debt is retired along with legacy",
     [(OI, '        retired_only = retirement["retired"] and item.get("route_scope") == SCOPE_LEGACY',
           '        retired_only = retirement["retired"] and item.get("route_scope") in '
           '(SCOPE_LEGACY, SCOPE_DEBT)')],
     [N + "test_the_hmm_known_debt_survives_the_retirement",
      N + "test_track1_shared_and_debt_issues_always_count"]),

    # Third target. The first moved the deepcopy, which still recomputed the answer on every
    # read - a mutation that did not reproduce the defect, and GREEN was the honest verdict.
    # The defect is the answer being FROZEN, so this freezes it.
    ("M10 the retirement answer is computed once and frozen",
     [(OI, "    retirement = legacy_retirement_state()",
           "    globals().setdefault('_frozen_retirement', legacy_retirement_state())\n"
           "    retirement = globals()['_frozen_retirement']")],
     [N + "test_the_retirement_is_recomputed_on_every_read_not_frozen_in_the_cache"]),

    # ── the page ──────────────────────────────────────────────────────────────────────────
    ("M11 carried debt goes back into the legacy group",
     [(JS, "    { key: 'model', label: 'Model / Regime',\n"
           "      note: 'carried model and regime debt — applies to Track 1 regardless of the legacy route',\n"
           "      has: sc => sc === 'known_debt' },\n"
           "    { key: 'legacy', label: 'Legacy / retired history',\n"
           "      note: 'reads legacy artefacts only — does not block Track 1 paper readiness',\n"
           "      has: sc => sc === 'legacy' }",
           "    { key: 'legacy', label: 'Legacy / retired history',\n"
           "      note: 'reads legacy artefacts only — does not block Track 1 paper readiness',\n"
           "      has: sc => sc === 'legacy' || sc === 'known_debt' }")],
     [N + "test_the_debt_group_is_its_own_and_is_not_called_legacy"]),

    ("M12 the headline count goes back to every issue",
     [(JS, "    const stripIssueCount = state.openIssues?.active_count\n"
           "      ?? (state.openIssues?.issues?.length || 0);",
           "    const stripIssueCount = state.openIssues?.issues?.length || 0;")],
     [N + "test_the_headline_count_is_the_active_one"]),

    ("M13 the rail calls a by-design stale snapshot a fault again",
     [(JS, "    if (legacyStaleByDesign) {\n"
           "      stripConditions.push('Legacy runner snapshot is stale because legacy entries are retired');\n"
           "    } else if",
           "    if (false) {\n"
           "      stripConditions.push('Legacy runner snapshot is stale because legacy entries are retired');\n"
           "    } else if")],
     [N + "test_the_rail_no_longer_calls_a_by_design_stale_snapshot_a_fault"]),

    ("M14 Model Inputs goes back to the legacy runner snapshot",
     [(JS, "    const t1Regime = state.marketView?.regime || null;",
           "    const t1Regime = null;")],
     [N + "test_model_inputs_reads_the_track1_regime_record"]),
]


def main() -> int:
    print(f"Stage 5ZZW mutations — {len(MUTATIONS)} claims\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
