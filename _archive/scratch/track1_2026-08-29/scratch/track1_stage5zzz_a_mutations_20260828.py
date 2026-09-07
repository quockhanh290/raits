"""Stage 5ZZZ-A mutation harness — can the order-gate tests turn red?

This stage removed a FAIL. That is the one shape of change where the tests must be shown to
still catch the thing the FAIL existed for, so most of these re-arm the route in a different way
and the suite has to notice each: orders genuinely possible, the out-of-band approval set, an
order journal on disk, an order mark on a record.

Two go the other way and make the audit fail on the signature again, which is the stale policy
returning.

Source-level edits in a subprocess, restored afterwards. The restore compares TEXT, not bytes:
the repo is CRLF and read_text/write_text translate on the way through.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzz_a_shadow_audit_confirmation_20260828.py"
SA = REPO / "global_index" / "track1_shadow_acceptance.py"


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
    # ── the route is armed some other way, and the audit must still fail ──────────────────
    ("M1 orders being possible stops failing the audit",
     [(SA, "    elif possible or not blocking:", "    elif False:")],
     [N + "test_orders_actually_possible_during_shadow_still_fails",
      N + "test_a_confirmation_plus_orders_possible_still_fails",
      N + "test_the_gate_registry_is_what_decides"]),

    # Retargeted. The first version pointed at a test whose fixture flips BOTH facts together,
    # so dropping one of them changed nothing and GREEN was the honest verdict. The two are
    # coupled in practice - the gate reports possible only when nothing is blocking - so the
    # mutation is only visible against a registry that disagrees with itself, which is exactly
    # the case the belt-and-braces `or` is there for.
    ("M2 the gate is asked only for its blocker list, not whether orders are possible",
     [(SA, "    elif possible or not blocking:", "    elif not blocking:")],
     [N + "test_either_half_of_the_gate_saying_orders_are_possible_fails"]),

    ("M3 the out-of-band approval stops failing",
     [(SA, '    approved = bool(_os.environ.get("TRACK1_ORDERS_APPROVED"))',
           "    approved = False")],
     [N + "test_the_out_of_band_approval_fails_hard"]),

    ("M4 an order journal on disk stops failing",
     [(SA, '    orders_dir = (root / "global_index" / "track1_runtime" / "orders").exists()',
           "    orders_dir = False")],
     [N + "test_an_order_journal_directory_fails_hard"]),

    ("M5 an order mark no longer outranks everything else",
     [(SA, "    if order_marks:\n        checks.append(_check(\"no_orders\", FAIL,\n"
           "                             f\"{len(order_marks)} record(s) carry an order mark\"))",
           "    if False:\n        checks.append(_check(\"no_orders\", FAIL,\n"
           "                             f\"{len(order_marks)} record(s) carry an order mark\"))")],
     [N + "test_an_order_mark_on_a_record_still_fails_first"]),

    # ── the stale policy comes back ───────────────────────────────────────────────────────
    ("M6 the signature fails the audit again",
     [(SA, '        checks.append(_check("no_orders", OK,\n'
           '                             f"no order marks; B1 confirmation present; orders remain blocked "\n'
           '                             f"by {\', \'.join(blocking)}"))',
           '        checks.append(_check("no_orders", FAIL,\n'
           '                             "the confirmation file exists during a shadow period"))')],
     [N + "test_a_signed_confirmation_does_not_fail_the_order_gate",
      N + "test_no_code_path_treats_the_confirmation_file_as_armed_orders",
      N + "test_todays_closed_sleeves_are_not_failed_by_the_order_gate"]),

    ("M7 the detail stops naming what is actually holding orders",
     [(SA, '                             f"no order marks; B1 confirmation present; orders remain blocked "\n'
           '                             f"by {\', \'.join(blocking)}"))',
           '                             "no order marks"))')],
     [N + "test_the_detail_says_the_file_is_there_and_why_it_does_not_matter"]),

    # ── the audit stops being able to fail at all ─────────────────────────────────────────
    ("M8 every order-gate branch passes",
     [(SA, "    if order_marks:", "    if False and order_marks:")],
     [N + "test_an_order_mark_on_a_record_still_fails_first"]),

    ("M9 a window that has not run yet is reported as passing",
     # Third target. `code = R_WINDOW_NOT_CLOSED` appears twice, and the second is an `else`
     # fallback producing the SAME code — so forcing the first branch false changed nothing and
     # GREEN was the honest verdict. The judgeability block as a whole is what has to go.
     [(SA, "    if not judgeable:", "    if False:")],
     [N + "test_the_windows_that_have_not_run_yet_say_so_rather_than_passing"]),
]


def main() -> int:
    print(f"Stage 5ZZZ-A mutations — {len(MUTATIONS)} claims\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
