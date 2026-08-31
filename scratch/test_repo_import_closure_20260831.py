"""Every internal import from a TRACKED file must resolve to a TRACKED file.

Stage 5ZZZ-BE. A repo where this is false does not run when it is cloned, and nothing in the
suite notices, because every developer's working tree has the missing files sitting on disk.

Measured on 2026-08-31 while planning a cleanup: 771 tracked `.py` files make 3,355 internal
imports, and **21** of them resolve to a file that is not in git. Two of those are load-bearing:

    global_index/window_ledger.py       25 tracked files import it, including
                                        `track1_shadow_acceptance` -- one of the three files
                                        that hold the reconstruction line
    global_index/route_checkpoint.py    17, including `run_live_day_track1`

and one is quietly worse than it looks:

    scratch/stress_open_search_20260821.py   imported by the Stress equivalence gate, the
                                             test that pins 57 trades across three windows.
                                             On a clean clone that GATE cannot run either

One of the 21 is not merely forgotten but actively hidden: `raits/data/raits_news.py` is
excluded by `.gitignore:225 data/`, a rule meant for the bar cache that also swallows a source
package. It never appears in `git status`, so a list assembled from `git status` cannot see it.
`git add -f` would fix today and let the rule swallow the next file added there; a narrow
`!raits/data/*.py` exception fixes it by construction.

WHY AN ALLOWLIST RATHER THAN A RED TEST
A test that is red on the day it is written is a test people learn to expect red, and this repo
has already paid for one of those: an alarm covering three files was left ringing for one, and
the other two stopped being checked at all. So the 21 known gaps are listed below with their
import counts, and there are two assertions:

    - nothing OUTSIDE the list may be missing -- catches the next one the day it appears
    - everything IN the list must STILL be missing -- forces the list to shrink as they are
      committed, so it cannot quietly become a place to park new debt

The list is a debt register with a date on it, not an exemption.
"""
from __future__ import annotations

import ast
import os
import subprocess
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: Directories that are importable as top-level packages from the repo root.
PKGS = ("global_index", "futures", "monitor", "raits", "orb_stocks", "scratch")

#: Measured 2026-08-31. Path -> how many tracked files import it at that time. The count is
#: recorded so a reader can tell a forgotten module from a stray probe without re-running.
KNOWN_UNTRACKED: dict[str, int] = {
    "global_index/window_ledger.py": 25,
    "global_index/route_checkpoint.py": 17,
    "global_index/regime_verify.py": 10,
    "global_index/route_params.py": 8,
    "global_index/slot_telemetry.py": 5,
    "global_index/safety_trade_log.py": 3,
    "raits/data/raits_news.py": 3,
    "scratch/track1_replay_source_20260822.py": 2,
    "scratch/directional_market_filter_probe.py": 2,
    "scratch/normal_promotion_variant_matrix_20260821.py": 2,
    "futures/stress_liquidation_1020.py": 1,
    "scratch/track1_bootstrap_checkpoint_20260822.py": 1,
    "scratch/track1_equivalence_harness_20260822.py": 1,
    "scratch/combined_repaired_replay_20260822.py": 1,
    "scratch/track1_stage2c_book_bootstrap_20260822.py": 1,
    "scratch/normal_sleeve_fill_audit.py": 1,
    "scratch/normal_promotion_filter_lib_20260821.py": 1,
    "scratch/stress_open_search_20260821.py": 1,
    "scratch/stress_switch_full_replay_20260822.py": 1,
    "global_index/b1_book_repair.py": 1,
    "scratch/track1_stage5zzzh_swing_d1_regen_20260829.py": 1,
}


def _tracked() -> set:
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    assert out.returncode == 0, out.stderr
    return set(out.stdout.splitlines())


def _resolve(dotted: str) -> "str | None":
    """A dotted name -> its repo-relative path, or None when it is not an internal module."""
    if not dotted:
        return None
    parts = dotted.split(".")
    if parts[0] not in PKGS:
        return None
    base = "/".join(parts)
    for cand in (base + ".py", base + "/__init__.py"):
        if (REPO / cand).exists():
            return cand
    return None


def _scan() -> tuple[int, int, dict]:
    """(files scanned, internal imports seen, {missing path -> importers})."""
    tracked = _tracked()
    py = sorted(f for f in tracked if f.endswith(".py"))
    seen = 0
    missing: dict = defaultdict(set)
    for f in py:
        try:
            tree = ast.parse((REPO / f).read_text(encoding="utf-8", errors="replace"),
                             filename=f)
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:            # relative -- resolved against its own package
                    continue
                mod = node.module or ""
                names = [mod] + [f"{mod}.{a.name}" for a in node.names]
            for n in names:
                p = _resolve(n)
                if p is None:
                    continue
                seen += 1
                if p not in tracked:
                    missing[p].add(f)
    return len(py), seen, dict(missing)


def test_the_scan_actually_walks_the_repo():
    """Guard the guard. An analyser that silently parses nothing passes every test below."""
    n_files, n_imports, _ = _scan()
    assert n_files > 500, f"only {n_files} tracked .py files -- the listing is wrong"
    assert n_imports > 1000, f"only {n_imports} internal imports -- the parser is wrong"


def test_no_tracked_file_imports_a_module_that_is_not_in_git():
    """The invariant. A clean clone must be able to import what the committed code imports."""
    _, _, missing = _scan()
    new = {p: sorted(u) for p, u in missing.items() if p not in KNOWN_UNTRACKED}
    assert not new, (
        "these modules are imported by tracked files but are not in git, and are not on the "
        "2026-08-31 debt register:\n"
        + "\n".join(f"  {p}\n      imported by {', '.join(u[:3])}" for p, u in sorted(new.items())))


def test_the_debt_register_only_shrinks():
    """Every listed gap must STILL be a gap.

    Without this the list becomes a place to park anything: an entry that has since been
    committed would sit there forever, and the next reader could not tell a real gap from a
    stale one. Removing a name from `KNOWN_UNTRACKED` is how a fix is recorded.
    """
    _, _, missing = _scan()
    fixed = sorted(p for p in KNOWN_UNTRACKED if p not in missing)
    assert not fixed, (
        "these are in git now -- delete them from KNOWN_UNTRACKED:\n  " + "\n  ".join(fixed))


def test_the_gitignore_rule_that_hides_a_source_package_is_named_here():
    """`raits/data/raits_news.py` is not merely forgotten -- it is excluded.

    It cannot appear in `git status`, so a cleanup list built from `git status` cannot see it.
    This test fails the day the exclusion is lifted, which is the day the entry above should
    also go.
    """
    out = subprocess.run(["git", "check-ignore", "-v", "raits/data/raits_news.py"],
                         cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    if out.returncode != 0:
        assert "raits/data/raits_news.py" not in KNOWN_UNTRACKED, (
            "the file is no longer ignored -- if it is now tracked, drop it from the register")
        return
    assert "data/" in out.stdout, out.stdout
    assert "raits/data/raits_news.py" in KNOWN_UNTRACKED
