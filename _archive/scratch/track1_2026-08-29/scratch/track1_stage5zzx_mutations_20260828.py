"""Stage 5ZZX mutation harness — can the console-hygiene tests turn red?

A filter that quietens a log is dangerous in exactly one direction: too much. So most of these
break it by widening it — dropping failed requests, dropping warnings, dropping a real scheduler
start — and the suite has to notice each one. Two go the other way and stop it filtering at all.

Source-level edits in a subprocess, restored afterwards. The restore compares TEXT, not bytes:
the repo is CRLF and read_text/write_text translate on the way through.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

REPO = Path(r"d:\raits")
TEST = REPO / "scratch" / "test_track1_stage5zzx_backend_console_noise_20260828.py"
APP = REPO / "monitor" / "backend" / "app.py"


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
    print(f"  {'RED  ' if ok else 'GREEN'}  {name:58s} {last}")
    return ok


N = f"{TEST}::"

MUTATIONS = [
    # ── widening: the dangerous direction ─────────────────────────────────────────────────
    ("M1 every access line is dropped, failures included",
     [(APP, "        if '\" ' not in message:\n            return True",
            "        return False\n        if '\" ' not in message:\n            return True")],
     [N + "test_every_failed_request_is_still_logged"]),

    ("M2 a 404 is treated as success",
     [(APP, '    _OK = ("200", "204", "301", "302", "304")',
            '    _OK = ("200", "204", "301", "302", "304", "404")')],
     [N + "test_every_failed_request_is_still_logged"]),

    ("M3 warnings stop bypassing the access filter",
     [(APP, "        if record.levelno >= logging.WARNING:\n            return True\n"
            "        message = record.getMessage()",
            "        message = record.getMessage()")],
     [N + "test_a_warning_survives_even_on_a_successful_request"]),

    ("M4 an unparseable line is thrown away instead of kept",
     [(APP, "        if '\" ' not in message:\n            return True",
            "        if '\" ' not in message:\n            return False")],
     [N + "test_a_line_the_filter_cannot_parse_is_kept"]),

    ("M5 all APScheduler INFO goes, including a real scheduler start",
     [(APP, '        return "Adding job tentatively" not in record.getMessage()',
            '        return False')],
     [N + "test_a_real_scheduler_starting_is_still_logged"]),

    ("M6 an APScheduler WARNING is dropped with the chatter",
     [(APP, "        if record.levelno >= logging.WARNING:\n            return True\n"
            '        return "Adding job tentatively" not in record.getMessage()',
            '        return "Adding job tentatively" not in record.getMessage()')],
     [N + "test_a_job_that_could_not_be_added_is_still_logged"]),

    # ── the other direction: it stops filtering ───────────────────────────────────────────
    ("M7 successful polling is logged again",
     [(APP, '    _OK = ("200", "204", "301", "302", "304")', '    _OK = ()')],
     [N + "test_successful_polling_is_not_logged"]),

    ("M8 the child logger loses its filter, so the line prints anyway",
     [(APP, '    logging.getLogger("apscheduler.scheduler").addFilter(_NoTentativeJobAdds())',
            '    pass')],
     [N + "test_the_filters_are_attached_to_both_apscheduler_loggers",
      N + "test_the_tentative_job_add_is_not_logged"]),

    # The bare name matches the `def` line as well as the call, so both anchors carry the
    # blank lines that precede the module-level invocation.
    ("M9 the filters are never installed",
     [(APP, "\n\n_quiet_backend_console()", "\n\npass  # not installed")],
     [N + "test_the_filters_are_attached_to_both_apscheduler_loggers"]),

    # ── the blunt instrument this stage deliberately did not use ──────────────────────────
    ("M10 the console is quietened with a global disable",
     [(APP, "\n\n_quiet_backend_console()",
            "\n\n_quiet_backend_console()\nlogging.disable(logging.INFO)")],
     [N + "test_nothing_global_was_disabled",
      N + "test_the_scheduler_log_file_is_untouched_by_this_stage"]),
]


def main() -> int:
    print(f"Stage 5ZZX mutations — {len(MUTATIONS)} claims\n")
    results = [expect_red(*m) for m in MUTATIONS]
    caught = sum(results)
    print(f"\n{caught}/{len(results)} mutations caught")
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
