"""Stage 5ZZZ-C mutation harness — can the reinterpretation tests turn red?

A module that tells a reader "discount that failure, the rule is gone" is dangerous in exactly
one direction, so most of these widen it: register a live reason as stale, dismiss a
re-evaluation that was entitled to speak, or wire the classification into the gate.

Two go the other way and make it dismiss nothing, because a classifier that never classifies
would satisfy every safety test in the file and be useless.

Source-level edits in a subprocess, restored afterwards. The restore compares TEXT, not bytes:
the repo is CRLF and read_text/write_text translate on the way through.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzzc_shadow_evidence_real_failures_20260828.py"
RI = REPO / "global_index" / "track1_audit_reinterpretation.py"
SA = REPO / "global_index" / "track1_shadow_acceptance.py"
PR = REPO / "global_index" / "track1_paper_readiness.py"


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
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:62s} {last}")
    return ok


N = f"{TEST}::"

MUTATIONS = [
    # ── the classifier dismisses something it should not ──────────────────────────────────
    ("M1 a live reason is registered as stale",
     [(RI, "STALE_REASONS: dict = {",
           'STALE_REASONS: dict = {\n    acc.R_ORDER_MARK: "wrongly registered",')],
     [N + "test_a_reason_that_is_still_produced_is_not_registered_as_stale",
      N + "test_every_stale_reason_is_really_gone_from_the_code"]),

    ("M2 the stale registry stops being checked against the code",
     [(SA, "    if order_check.get(\"status\") == FAIL:\n"
           "        d = str(order_check.get(\"detail\", \"\"))",
           "    if order_check.get(\"status\") == FAIL:\n"
           "        d = str(order_check.get(\"detail\", \"\"))\n"
           "        if False:\n"
           "            reasons.append(R_CONFIRMATION_FILE)")],
     [N + "test_every_stale_reason_is_really_gone_from_the_code"]),

    ("M3 everything is treated as solely stale",
     [(RI, "        \"solely_stale\": bool(stale) and not standing,",
           "        \"solely_stale\": True,")],
     [N + "test_classification_separates_stale_from_standing",
      N + "test_a_row_with_no_stale_reason_is_not_marked_stale"]),

    # ── the re-evaluation authority is widened or narrowed ────────────────────────────────
    ("M4 every re-evaluation is called authoritative",
     [(RI, '        "authoritative": not artefacts,', '        "authoritative": True,')],
     [N + "test_a_checkpoint_wrong_day_from_a_reevaluation_is_not_authoritative",
      N + "test_nkd_and_swing_cannot_be_rejudged_because_of_the_live_book"]),

    ("M5 no re-evaluation is ever authoritative, so real failures get dismissed too",
     [(RI, '        "authoritative": not artefacts,', '        "authoritative": False,')],
     [N + "test_a_reevaluation_without_artefact_reasons_is_authoritative",
      N + "test_calm_and_stress_failed_for_real_and_the_reevaluation_may_say_so",
      N + "test_the_day_still_contains_real_failures_so_it_is_not_a_clean_day"]),

    ("M6 the checkpoint reason is no longer treated as a live-artefact read",
     # The first version wrote `{} or {...}`, which Python evaluates to the non-empty dict -
     # a no-op, and GREEN was the honest verdict. This empties it for real.
     [(RI, "def reevaluation_authority(reasons) -> dict[str, Any]:",
           "LIVE_ARTEFACT_REASONS = {}\n\n\ndef reevaluation_authority(reasons) -> dict[str, Any]:")],
     [N + "test_a_checkpoint_wrong_day_from_a_reevaluation_is_not_authoritative",
      N + "test_nkd_and_swing_cannot_be_rejudged_because_of_the_live_book"]),

    # ── the safety property: it must not reach the gate, and must not write ───────────────
    ("M7 the readiness reader starts consuming the reinterpretation",
     [(PR, "def audit_records(root: str | Path = \".\") -> list:",
           "from global_index import track1_audit_reinterpretation  # noqa: F401\n\n\n"
           "def audit_records(root: str | Path = \".\") -> list:")],
     [N + "test_the_order_gate_does_not_read_this_module"]),

    ("M8 the module gains a write",
     [(RI, "    root = Path(root)\n    if records is None:",
           "    root = Path(root)\n"
           "    (root / '_reinterpretation.tmp').write_text('x', encoding='utf-8')\n"
           "    if records is None:")],
     [N + "test_the_module_contains_no_write_call"]),

    # ── the day's real failures ───────────────────────────────────────────────────────────
    ("M9 the day is reported as containing no real failure",
     [(RI, '            reeval = {"verdict": fresh.get("verdict"), "reasons": fresh_reasons,',
           '            reeval = {"verdict": "PASS", "reasons": fresh_reasons,')],
     [N + "test_calm_and_stress_failed_for_real_and_the_reevaluation_may_say_so",
      N + "test_the_day_still_contains_real_failures_so_it_is_not_a_clean_day"]),

    ("M10 the stored row is quietly replaced by the re-evaluated one",
     [(RI, '            "stored": {"verdict": rec.get("verdict"), "reasons": stored_reasons,',
           '            "stored": {"verdict": reeval.get("verdict"), "reasons": stored_reasons,')],
     # Retargeted: both verdicts are FAIL on this day, so the substitution was invisible to a
     # test that only read the reasons. The new test pins the stored verdict verbatim.
     [N + "test_the_stored_verdict_is_reported_verbatim_from_the_record"]),
]


def main() -> int:
    print(f"Stage 5ZZZ-C mutations — {len(MUTATIONS)} claims\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
