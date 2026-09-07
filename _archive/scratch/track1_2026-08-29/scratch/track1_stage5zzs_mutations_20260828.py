"""Stage 5ZZS mutation harness — can the repaired ops invariants still turn red?

The risk this stage carries is specific. Every repair here REMOVED an assertion that used to
fail, so the cheapest way to make ten tests green would have been to assert less. These
mutations exist to show that did not happen: each one breaks a safety property that the OLD
tests could not have caught, and the NEW test must go red on it.

Source-level edits, applied to the real files in a subprocess and restored. `expect_red` proves
the selected tests green FIRST — a run that exits non-zero for a bad node id or an import error
is the harness lying, not a mutation being caught. The restore compares TEXT rather than bytes:
the repo is CRLF and read_text/write_text translate on the way through.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
T_5K = REPO / "scratch" / "test_track1_stage5k_ops_startup_20260823.py"
T_5ZF = REPO / "scratch" / "test_track1_stage5zf_ops_report_completeness_20260825.py"
T_MODE = REPO / "scratch" / "test_track1_ops_status_mode_20260824.py"
T_5L = REPO / "scratch" / "test_track1_stage5l_shared_preflight_20260823.py"
OPS = REPO / "monitor" / "ops.py"
GATES = REPO / "global_index" / "track1_gates.py"
SLOTS = REPO / "global_index" / "track1_slots.py"


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


N5K = f"{T_5K}::"
N5ZF = f"{T_5ZF}::"
NMODE = f"{T_MODE}::"

MUTATIONS = [
    # ── the invariant that replaced "B1 blocks": B1 must be closed by a MEASUREMENT ────────
    # Retargeted after the first attempt came back GREEN. Waiving `b1_decision_evidence` itself
    # could not be caught, because the suite only ever asserted that the SIGNATURE is necessary
    # - take it away and B1 returns - and never that the MEASUREMENT is. That was one half of
    # the rule asserted twice. `test_28b` now makes the other half, and this breaks the place
    # where a signed gate consults the measurement it additionally requires.
    ("M1 a signed gate stops consulting its required measurement",
     [(GATES, '        if not self.also_requires_measurement:\n            return True, ""',
              '        if True:\n            return True, ""')],
     [N5ZF + "test_28b_b1_reopens_when_the_measurement_fails_even_though_it_is_signed"]),

    # ── the shadow refusal Stage 5ZZN narrowed - BOTH halves must still hold ───────────────
    ("M2 the shadow start stops refusing when orders ARE possible",
     [(OPS, "    if TRACK1_CONFIRMATION.exists() and orders_would_be_possible()[0]:",
            "    if False:")],
     [N5K + "test_the_confirmation_file_alone_no_longer_refuses_a_shadow_start"]),

    ("M3 the shadow start refuses on the FILE ALONE again (the 5ZZN regression)",
     [(OPS, "    if TRACK1_CONFIRMATION.exists() and orders_would_be_possible()[0]:",
            "    if TRACK1_CONFIRMATION.exists():")],
     [N5K + "test_the_confirmation_file_alone_no_longer_refuses_a_shadow_start"]),

    # ── the guard that must NOT be lost when the one above is narrowed ─────────────────────
    ("M4 a legacy entry start is no longer refused after the decision",
     [(OPS, '''    if not conf.get("legacy_retired_confirmed"):
            return []''',
            '''    if True:
            return []''')],
     [N5K + "test_a_legacy_start_is_refused_once_the_decision_says_legacy_retired"]),

    ("M5 the refusal stops naming the mode that IS allowed",
     [(OPS, '''        "start with --track1-only-shadow instead: it registers Track 1's slots and no legacy "
        "entry job, keeps legacy's safety sweeps draining the old book, and cannot send an "
        "order while PAPER_SHADOW_EVIDENCE is unsatisfied.",''',
            '''        "refusing.",''')],
     [N5K + "test_a_legacy_start_is_refused_once_the_decision_says_legacy_retired"]),

    # ── orders_possible must stay false, and status must report it honestly ────────────────
    ("M6 the approval variable alone opens orders",
     [(GATES, '''def may_enable_orders(conf: "Confirmations | None" = None) -> tuple[bool, list]:''',
       '''def may_enable_orders(conf: "Confirmations | None" = None) -> tuple[bool, list]:
    import os
    if os.environ.get("TRACK1_ORDERS_APPROVED"):
        return True, []''')],
     [N5ZF + "test_28c_no_signature_or_variable_can_release_what_is_holding_orders"]),

    # ── the exhaustiveness that the derived counts must not have given away ───────────────
    # Also retargeted. The first version broke `_bucket_for` and expected the 5ZF inventory
    # test to notice - but that suite carries its OWN `_classify` and never calls the production
    # one. A mutation aimed at code the selected tests do not execute proves nothing about
    # either. The production classifier is guarded by the 5L suite, so that is where it goes.
    # Third target for this one, and the first two are worth recording because both came back
    # GREEN honestly. Mutating the `unclassified` fallback proves nothing TODAY: once the three
    # SPY rungs were declared, no registered job reaches that line at all, so the edit is to
    # unreachable code. A mutation on a path the tests do not execute is not a test failure, it
    # is a mutation that never ran - and the harness saying GREEN was correct both times.
    # M7b already covers the fallback by making a declared job fall through to it. What was
    # still unguarded is the opposite direction: a job bucketed as shared without being declared.
    ("M7 every job is bucketed as shared infrastructure, declared or not",
     [(SLOTS, "    if job_id in SHARED_INFRA_JOBS:", "    if True:")],
     [N5ZF + "test_4_the_shared_infra_jobs_are_exactly_the_declared_ones"]),

    ("M7b a declared shared-infra job is dropped from the table",
     [(SLOTS, '    "preflight": "the 13:45 data refresh',
              '    "_preflight": "the 13:45 data refresh')],
     [f"{T_5L}::test_the_shared_infra_table_covers_exactly_the_jobs_that_must_survive",
      f"{T_5L}::test_shared_infra_survives_the_retirement_of_every_legacy_entry_job"]),

    ("M8 a shared-infra job is declared with no stated reason",
     [(SLOTS, '    "heartbeat": "liveness measurement, every minute all week; decides nothing",',
              '    "heartbeat": "",')],
     [N5ZF + "test_4_the_shared_infra_jobs_are_exactly_the_declared_ones"]),

]

# ── the two delegated call sites, mutated on a COPY ────────────────────────────────────────
#
# M9 and M10 break `run_scheduler.py`, which is the file the live scheduler runs. Stage 5ZZS is
# forbidden from editing runtime trading files, and "it is restored a few seconds later" is not
# an answer: a killed process would leave the scheduler's own module broken on disk. So these
# two build a temp tree holding a mutated COPY, point the test module's REPO at it, and call
# the test function directly. Nothing real is written at any point.
COPY_MUTATIONS = [
    ("M9 the post-close refresh drops --verify-strict",
     '''        cmd = [sys.executable, "-m", "global_index.update_spy_csv", "--csv", regime_csv,
               "--verify-strict", "--require-through", today]''',
     '''        cmd = [sys.executable, "-m", "global_index.update_spy_csv", "--csv", regime_csv,
               "--require-through", today]''',
     "test_27_a_label_drift_is_now_visible_as_a_job_failure"),

    ("M10 the refresh stops emitting normal job evidence",
     # That `_run` line appears TWICE in the file; anchoring on it alone matched both and the
     # harness refused rather than mutating a place it had not chosen. Anchored on the block
     # that is unique to `_spy_refresh`.
     '''            cmd += ["--skip-if-covered"]
        if polygon_api_key:
            cmd += ["--api-key", polygon_api_key]

        rc: list = []
        ok = _run(cmd, label=label, dry_run=dry_run, rc_out=rc)''',
     '''            cmd += ["--skip-if-covered"]
        if polygon_api_key:
            cmd += ["--api-key", polygon_api_key]

        rc: list = []
        ok = _run(cmd, dry_run=dry_run, rc_out=rc)''',
     "test_5_spy_refresh_pm_emits_normal_job_evidence"),
]


def expect_red_on_copy(name, old, new, test_name):
    """Run one AST test against a mutated copy of run_scheduler.py, touching nothing real."""
    import importlib.util
    import shutil
    import tempfile

    real = REPO / "global_index" / "run_scheduler.py"
    before = _digest(real.read_text(encoding="utf-8"))

    spec = importlib.util.spec_from_file_location("t5zf_copy", T_5ZF)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(REPO / "scratch"))
    spec.loader.exec_module(mod)
    fn = getattr(mod, test_name)

    try:
        fn()                                   # green against the real tree first
    except Exception as exc:                                          # noqa: BLE001
        print(f"  [HARNESS BROKEN] {name}: baseline not green — {exc}")
        return False

    with tempfile.TemporaryDirectory() as td:
        fake = Path(td)
        (fake / "global_index").mkdir(parents=True)
        src = real.read_text(encoding="utf-8")
        if src.count(old) != 1:
            print(f"  [HARNESS BROKEN] {name}: anchor matched {src.count(old)}x")
            return False
        (fake / "global_index" / "run_scheduler.py").write_text(
            src.replace(old, new), encoding="utf-8")
        real_repo = mod.REPO
        mod.REPO = fake
        try:
            fn()
            caught = False
        except AssertionError:
            caught = True
        except Exception as exc:                                      # noqa: BLE001
            print(f"  [HARNESS BROKEN] {name}: raised {type(exc).__name__}: {exc}")
            return False
        finally:
            mod.REPO = real_repo

    assert _digest(real.read_text(encoding="utf-8")) == before, "the real file was touched"
    print(f"  {'RED  ' if caught else 'GREEN'}  {name:60s} (on a copy)")
    return caught


def main() -> int:
    total = len(MUTATIONS) + len(COPY_MUTATIONS)
    print(f"Stage 5ZZS mutations — {total} invariants\n")
    results = [expect_red(*m) for m in MUTATIONS]
    results += [expect_red_on_copy(*m) for m in COPY_MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
