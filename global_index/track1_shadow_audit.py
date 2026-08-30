"""global_index/track1_shadow_audit.py — the post-window Track 1 audit job. NEW FILE.

Stage 5Q. Read-only over the runtime evidence, write-only into its own audit directory.
It starts nothing, connects to nothing, sends no order, and imports no broker module.

What this replaces
------------------
Until now the only way to answer "did that window pass?" was to run a dated script in
`scratch` by hand. That has three problems and every one of them has already bitten this
project:

* it is dated, so it audits 2026-08-24 forever unless someone remembers to edit it;
* it lives in `scratch`, which ordinary cleanup deletes — the 5K0 lesson;
* it only runs when a human remembers, so the one morning nobody looks is the morning with
  no record of whether the night was judged at all.

So the audit becomes a scheduled job with a durable output, and "nobody ran the audit" turns
into an ABSENT RECORD that the dashboard names rather than into silence that reads as fine.

Where the rules live
--------------------
Not here. Every judgement comes from `global_index/track1_shadow_acceptance.py` — the gate
whose thresholds were committed before any shadow day existed. This module chooses WHICH day
and WHICH sleeve to ask about, stamps the answer with the route, and writes it down. A second
copy of "what counts as complete" is how two readers of one day come to quote two verdicts.

What it writes, and only what it writes
---------------------------------------
    global_index/track1_runtime/audits/track1_audit_YYYYMMDD.jsonl   one line per audit run

Append-only, beside the evidence and never inside it. The audit must not be able to touch
`window_coverage/`, `slot_timing/` or `shadow/` — a judge that can edit the exhibits is not a
judge. A source scan in the Stage 5Q tests holds that.

The scheduler-uptime question
-----------------------------
A window that closed before the scheduler existed produced no evidence and CANNOT be a
failure — nothing was ever asked to run. Measured case, 2026-08-24: the operator started the
track1-only session at 04:32 ET and the NKD window is 01:10-02:55 ET, so all 22 NKD slots had
already passed. That is `NOT_ENOUGH_DATA_YET`, and an audit that called it FAIL would teach
an operator to stop reading audits.

The start instant is resolved with THREE outcomes, never two:

    --scheduler-started   passed by the scheduler job itself, which knows its own start
    process table         `monitor.ops.scheduler_processes()`, best effort
    unknown               reported as unknown; a closed window with no evidence at all and
                          an unreadable start time is NOT_ENOUGH_DATA_YET, because "nothing
                          ran" and "nothing was asked to run" are not distinguishable then

Folding "could not read it" into "no scheduler" is the fail-open shape that once let a second
scheduler start, and two schedulers contending for one client id cost six entry slots.

Exit code
---------
`0` whenever the AUDIT ITSELF ran, whatever verdict it reached. A FAIL verdict is data and it
belongs in the record and on the dashboard; making the process exit non-zero would put
"the shadow window had a gap" and "the audit tool is broken" behind the same red light in the
scheduler log. `--exit-nonzero-on-fail` is available for a caller that wants the other
behaviour; the scheduler job does not pass it.

Usage
-----
    python -m global_index.track1_shadow_audit --latest --all
    python -m global_index.track1_shadow_audit --date 2026-08-25 --sleeve roska4_calm
    python -m global_index.track1_shadow_audit --date 2026-08-25 --all
    python -m global_index.track1_shadow_audit --from 2026-08-25 --to 2026-08-29
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from global_index import track1_shadow_acceptance as acc

#: Schema of an audit record. Bumped when a field changes meaning, never when one is added —
#: a reader that switches on this must be able to trust that `2` means what it meant.
SCHEMA = 1

AUDITS_DIR = acc.AUDITS_DIR
ROUTE = acc.AUDIT_ROUTE

#: How the start instant was obtained. Three values, because a reader has to be able to tell
#: "the scheduler told us" from "we guessed from the process table" from "we do not know".
SRC_ARGV = "argv"
SRC_PROCESS_TABLE = "process_table"
SRC_UNKNOWN = "unknown"


# ── the scheduler start instant, in ET, with three outcomes ──────────────────
def scheduler_start_et(explicit: "str | None" = None, *, probe: bool = True):
    """`(instant_or_None, source, note)`. Never raises, never guesses silently.

    The process table reports MACHINE-LOCAL time — this box runs Calgary, ET-2 — and every
    window in this project is ET. Comparing the two raw is a two-hour error that reads as
    "the scheduler was up for that window" when it was not, so the conversion happens here,
    once, and the offset is measured rather than assumed.
    """
    import pandas as pd

    if explicit:
        try:
            ts = pd.Timestamp(explicit)
            if ts.tzinfo is not None:
                ts = ts.tz_convert("America/New_York").tz_localize(None)
            return ts, SRC_ARGV, "start instant supplied by the caller"
        except Exception as exc:                           # noqa: BLE001
            # An unparseable value must NOT quietly become "no scheduler" — that is the
            # direction that turns a pre-start window into a manufactured failure.
            return None, SRC_UNKNOWN, "could not parse --scheduler-started %r: %s" % (
                explicit, exc)
    if not probe:
        return None, SRC_UNKNOWN, "process-table probe disabled"
    try:
        from monitor import ops
        procs = ops.scheduler_processes()
    except Exception as exc:                               # noqa: BLE001
        return None, SRC_UNKNOWN, "process table unreadable: %s" % exc
    if not procs:
        return None, SRC_UNKNOWN, ("no scheduler process found — this is 'not seen', not "
                                   "'not running': the scan fails to an empty list")
    started = procs[0].get("started")
    if not started:
        return None, SRC_UNKNOWN, "scheduler pid %s reports no start time" % procs[0].get("pid")
    try:
        local = pd.Timestamp(str(started))
        offset = (pd.Timestamp.now(tz="America/New_York").tz_localize(None)
                  - pd.Timestamp.now())
        return (local + offset), SRC_PROCESS_TABLE, "scheduler pid %s started %s local" % (
            procs[0].get("pid"), started)
    except Exception as exc:                               # noqa: BLE001
        return None, SRC_UNKNOWN, "start time %r unreadable: %s" % (started, exc)


# ── the day under audit ──────────────────────────────────────────────────────
def latest_session_day(root: str | Path = ".", now_et=None) -> str:
    """The most recent ET session day the evidence knows about, else today.

    Derived from the ledger rather than from the clock: an audit run at 03:05 ET is asking
    about the NKD window that closed ten minutes ago, and that window's ledger rows carry the
    session day the SLOT meant. Falling straight to `today` would still be right for every
    Track 1 window — all four close before 20:00 ET, so the ET day and the file day agree —
    but it would stop being right the first time a window crosses that line, and a fallback
    that is only accidentally correct is one nobody re-checks.
    """
    import pandas as pd

    now = (pd.Timestamp(now_et) if now_et is not None
           else pd.Timestamp.now(tz="America/New_York"))
    today = str((now.tz_convert("America/New_York") if now.tzinfo is not None else now).date())
    days = sorted(known_days(root))
    if not days:
        return today
    return days[-1] if days[-1] >= today else today


def known_days(root: str | Path = ".") -> list:
    """Every session day the window ledger has rows for."""
    d = Path(root) / acc.COVERAGE_DIR
    if not d.is_dir():
        return []
    out = set()
    for f in sorted(d.glob("window_coverage_*.jsonl")):
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("date"):
                    out.add(str(rec["date"]))
        except Exception:                                  # noqa: BLE001
            continue
    return sorted(out)


# ── writing the record ───────────────────────────────────────────────────────
def audit_path(day: str, root: str | Path = ".") -> Path:
    return Path(root) / AUDITS_DIR / ("track1_audit_%s.jsonl" % str(day).replace("-", ""))


def write_records(records: list, root: str | Path = ".") -> list:
    """Append each record to its day's audit file. Returns the paths written.

    Append, not overwrite. Auditing the Calm window at 10:10 and the Stress window at 12:40
    are two separate judgements of the same day, and a rewrite would leave only the last one
    — so the morning's record of whether Calm was ever judged would disappear at lunchtime.
    """
    written: list = []
    for rec in records:
        p = audit_path(rec["date"], root)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        if p not in written:
            written.append(p)
    return written


def read_records(day, root: str | Path = ".") -> list:
    p = audit_path(str(day), root)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except Exception:                                  # noqa: BLE001
            continue
    return out


def _stamp(rec: dict, *, start_source: str, start_note: str, trigger: str) -> dict:
    """Route-stamp and provenance. Every field here answers "who says so, and when".

    `route` is not decoration: `window_coverage` and `slot_timing` are shared files that both
    routes write into, and an audit record that does not name the route it judged will be
    read as judging whichever route the reader had in mind.
    """
    rec = dict(rec)
    rec.setdefault("route", ROUTE)
    rec["schema"] = SCHEMA
    rec["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec["audit_trigger"] = trigger
    rec["scheduler_start_source"] = start_source
    rec["scheduler_start_note"] = start_note
    rec["audit_pid"] = os.getpid()
    return rec


# ── the audit itself ─────────────────────────────────────────────────────────
def run_audit(*, days: list, sleeves: "list | None", root: str | Path = ".",
              now_et=None, scheduler_started=None, start_source: str = SRC_UNKNOWN,
              start_note: str = "", trigger: str = "manual") -> list:
    """Build the audit records. Pure apart from reading evidence — writing is the caller's.

    `sleeves=None` means the whole day: one record per sleeve PLUS one day roll-up, so a
    reader can answer both "did Stress pass?" and "did the day pass?" without recomputing.
    """
    out: list = []
    for day in days:
        if sleeves:
            for sleeve in sleeves:
                out.append(_stamp(
                    acc.evaluate_sleeve(day, sleeve, root, now_et=now_et,
                                        scheduler_started_et=scheduler_started),
                    start_source=start_source, start_note=start_note, trigger=trigger))
        else:
            from global_index.track1_params import WINDOWS_ET
            for sleeve in sorted(WINDOWS_ET):
                out.append(_stamp(
                    acc.evaluate_sleeve(day, sleeve, root, now_et=now_et,
                                        scheduler_started_et=scheduler_started),
                    start_source=start_source, start_note=start_note, trigger=trigger))
            out.append(_stamp(
                acc.evaluate_day_audit(day, root, now_et=now_et,
                                       scheduler_started_et=scheduler_started),
                start_source=start_source, start_note=start_note, trigger=trigger))
    return out


def _print_report(records: list, *, start_source: str, start_note: str) -> None:
    line = "=" * 74
    print(line)
    print("TRACK 1 SHADOW AUDIT — read-only, route=%s" % ROUTE)
    print(line)
    print("scheduler start: %s — %s" % (start_source, start_note))
    print()
    for rec in records:
        if rec.get("scope") == "sleeve":
            print("  %-14s %-9s %-22s expect %-3s observed %-3s p95 %-7s %s" % (
                rec.get("sleeve"),
                "-".join(rec.get("window_et") or []) or "--",
                rec.get("verdict"),
                rec.get("expected_slots"),
                rec.get("observed_slots"),
                rec.get("runtime_p95_s"),
                ",".join(rec.get("reasons") or []) or "-"))
            for d in rec.get("details") or []:
                print("      %s" % d)
        else:
            print()
            print("  DAY %s   verdict %s" % (rec.get("date"), rec.get("verdict")))
            print("      reasons: %s" % (", ".join(rec.get("reasons") or []) or "-"))
            gate = rec.get("acceptance_gate") or {}
            print("      committed daily acceptance gate: accepted=%s failed=%s" % (
                gate.get("accepted"), gate.get("failed")))
            if rec.get("pending_sleeves"):
                print("      pending (nothing to judge yet): %s"
                      % ", ".join(rec["pending_sleeves"]))
    print()


def build_parser() -> argparse.ArgumentParser:
    from global_index.track1_params import WINDOWS_ET

    ap = argparse.ArgumentParser(
        prog="python -m global_index.track1_shadow_audit",
        description="Post-window / daily audit of the Track 1 shadow runtime evidence. "
                    "Read-only over the evidence; writes only its own audit record.")
    ap.add_argument("--date", help="ET session day to audit, YYYY-MM-DD")
    ap.add_argument("--latest", action="store_true",
                    help="audit the most recent session day the evidence knows about")
    ap.add_argument("--sleeve", action="append", choices=sorted(WINDOWS_ET),
                    help="audit one sleeve's window; repeatable. Omit (or pass --all) for "
                         "every sleeve plus the day roll-up")
    ap.add_argument("--all", action="store_true",
                    help="every sleeve of the day, plus the day roll-up")
    ap.add_argument("--from", dest="date_from", help="first day of a period, YYYY-MM-DD")
    ap.add_argument("--to", dest="date_to", help="last day of a period, YYYY-MM-DD")
    ap.add_argument("--root", default=".", help="repository root (tests point this at a tmp tree)")
    ap.add_argument("--scheduler-started",
                    help="the scheduler's start instant in ET. The scheduler job passes its "
                         "own; omit it and the process table is probed instead")
    ap.add_argument("--no-process-probe", action="store_true",
                    help="do not probe the process table for the scheduler start")
    ap.add_argument("--now", help="override 'now' in ET — for tests and for re-auditing")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the audit without writing the record")
    ap.add_argument("--exit-nonzero-on-fail", action="store_true",
                    help="exit 2 when the audit verdict is FAIL. Off by default so that a "
                         "failing shadow window and a broken audit tool do not share one "
                         "red light in the scheduler log")
    return ap


def main(argv: "list | None" = None) -> int:
    import pandas as pd

    # A scheduled child writes into a PIPE, and on Windows a pipe takes the locale codepage
    # rather than UTF-8. The report carries em dashes and typographic quotes, and cp1252
    # cannot encode them: `deploy_sim` once ran a full simulation for 3m51s and then died on
    # its last print for exactly this reason. A verdict must never be lost to a dash.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:                                  # noqa: BLE001 — not worth failing on
            pass

    a = build_parser().parse_args(argv)
    root = Path(a.root)

    started, src, note = scheduler_start_et(a.scheduler_started,
                                            probe=not a.no_process_probe)
    now = pd.Timestamp(a.now) if a.now else None

    if a.date_from or a.date_to:
        if not (a.date_from and a.date_to):
            print("--from and --to must be given together", file=sys.stderr)
            return 2
        days = [str(d.date()) for d in pd.date_range(a.date_from, a.date_to, freq="D")]
    elif a.date:
        days = [str(pd.Timestamp(a.date).date())]
    else:
        days = [latest_session_day(root, now_et=now)]

    sleeves = None if a.all else (a.sleeve or None)

    records = run_audit(days=days, sleeves=sleeves, root=root, now_et=now,
                        scheduler_started=started, start_source=src, start_note=note,
                        trigger="cli")
    _print_report(records, start_source=src, start_note=note)

    if a.dry_run:
        print("--dry-run: no audit record written")
    else:
        for p in write_records(records, root):
            print("wrote %s" % p)

    # The line an operator reads first, so it must not be able to say PASS about a set of
    # records that judged nothing. The first draft seeded `worst` at PASS and skipped the
    # pending records, so a morning on which every window was still pending printed
    # "WORST VERDICT: PASS" under four NOT_ENOUGH_DATA_YET rows. Measured on the live tree
    # at 07:43 ET on 2026-08-24, which is exactly the state this stage exists to report
    # honestly.
    judged = [r.get("verdict") for r in records
              if r.get("verdict") != acc.AUDIT_NOT_ENOUGH_DATA_YET]
    if not judged:
        worst = acc.AUDIT_NOT_ENOUGH_DATA_YET
    else:
        worst = acc.AUDIT_PASS
        for v in judged:
            worst = acc._worse(worst, v)
    print("WORST VERDICT: %s" % worst)
    if worst == acc.AUDIT_NOT_ENOUGH_DATA_YET:
        print("  Nothing here has both closed and been covered by scheduler uptime. That is")
        print("  a statement about how far the session has got, NOT about the route's health.")
    if a.exit_nonzero_on_fail and worst == acc.AUDIT_FAIL:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
