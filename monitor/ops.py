"""One-command process launcher for RAITS paper operations.

This script intentionally lives outside the trading engine. It starts/stops the
long-running processes operators otherwise have to remember by hand:

  python monitor/ops.py up
  python monitor/ops.py restart
  python monitor/ops.py status
  python monitor/ops.py down

Assumption: IB Gateway is already open and logged in.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "monitor" / "logs"
DEFAULT_IBKR_PORT = 4002
DEFAULT_API_PORT = 5002


@dataclass(frozen=True)
class RunningProcess:
    pid: int
    command: str
    started: str


@dataclass(frozen=True)
class ProcessScan:
    """Three states, not two.

    `ok=False` means the probe itself failed and the host's real state is unknown. The
    previous code collapsed that into an empty list, so a PowerShell hiccup read as
    "nothing is running" and ops.py launched a second scheduler on top of a live one.
    """
    ok: bool
    processes: list[RunningProcess] = field(default_factory=list)
    error: str | None = None
    #: Stage 5ZZ. A short machine-readable reason when `ok` is False, "" when it is True.
    #: The prose in `error` is for a person; this is for anything that has to branch on the
    #: kind of failure without matching on English.
    code: str = ""

    @property
    def pids(self) -> list[int]:
        return sorted(item.pid for item in self.processes)


@dataclass(frozen=True)
class Decision:
    action: str                 # "start" | "kill_then_start" | "refuse"
    pids: list[int]
    reason: str | None = None


def plan_single_instance(
    scan: ProcessScan,
    *,
    assume_yes: bool,
    confirm: Callable[[ProcessScan], bool] | None = None,
) -> Decision:
    """Decide what to do before launching. Pure — no processes touched, so it is testable.

    Refusing is always safe: the operator loses a launch. Starting on a bad guess is not:
    two schedulers fire every slot twice and both write live_positions.json.
    """
    if not scan.ok:
        return Decision("refuse", [], f"cannot determine running processes ({scan.error})")
    if not scan.processes:
        return Decision("start", [])
    if assume_yes:
        return Decision("kill_then_start", scan.pids)
    if confirm is None:
        return Decision("refuse", scan.pids,
                        "already running and this run has no terminal to ask; "
                        "pass --yes to stop them automatically")
    if confirm(scan):
        return Decision("kill_then_start", scan.pids)
    return Decision("refuse", scan.pids, "operator declined to stop the running process(es)")


def _run(args: list[str], *, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def _pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else "pythonw"


#: Durable homes for Track 1 live-shadow evidence. NOT under `scratch/`: a shadow period is not
#: reproducible — nobody can re-observe a window that has closed — and `scratch/` is the
#: directory this project sweeps. Named here as well as in `run_live_day_track1` so the launcher
#: and the route cannot point at different directories; a test asserts they agree.
TRACK1_RUNTIME = ROOT / "global_index" / "track1_runtime"
TRACK1_LEDGER_DIR = TRACK1_RUNTIME / "window_coverage"
TRACK1_TELEMETRY_DIR = TRACK1_RUNTIME / "slot_timing"

#: The file that ARMS the Track 1 route, and the legacy kill switch.
TRACK1_CONFIRMATION = ROOT / "track1_go_live_confirmation.json"


def track1_slot_count() -> int:
    """How many Track 1 slots the flag adds, read from the slot table.

    Operator-facing text said "25" in three places until Stage 5M-C, and the number had been
    wrong since Stage 5M-B added the 23 Normal-R4 slots. Nobody was misled yet, but a help
    string that states a stale fact is the same defect class as a comment that does: it is a
    description that has drifted from the thing it describes, and the fix is to derive it.

    ROOT goes on `sys.path` first, and that is not defensiveness — it is a bug this function
    caused. Operators run `python monitor/ops.py ...`, which puts `monitor/` on the path and
    not the repo root, so `global_index` is not importable. Stage 5M-C put this call inside
    the argparse help string, and from that moment `python monitor/ops.py --help` died with a
    ModuleNotFoundError before printing anything. The Stage 5M-C tests imported `monitor.ops`
    as a module, with the root already on the path, and never ran it the way the runbook tells
    an operator to run it. Same shape as the `--sleeve` defect one stage earlier: both halves
    correct, the seam between them never crossed.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from global_index.track1_slots import TRACK1_SLOTS
    return len(TRACK1_SLOTS)


def track1_safety_count() -> int:
    """How many safety jobs Track 1 registers in track1-only mode. Derived, for the same
    reason the slot count is: an operator string that states a number states a fact that
    expires."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from global_index.track1_slots import track1_safety_jobs
    return len(track1_safety_jobs())


def _t1_safety():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from global_index.track1_slots import track1_safety_jobs
    return track1_safety_jobs()


def _t1_const(name: str):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from global_index import track1_slots as _ts
    return getattr(_ts, name)
LEGACY_STOP_FILE = ROOT / "STOP_TRADING"
TRACK1_ORDERS_ENV = "TRACK1_ORDERS_APPROVED"


def _env(*, track1_shadow: bool = False, track1_only: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    if track1_only:
        track1_shadow = True
        # The dashboard mirror has to know, or it expects the 45 legacy strategy slots the
        # scheduler is not registering and manufactures an incident for every one of them,
        # every day. One flag on the process, one on its child's environment, same fact.
        env["RAITS_TRACK1_ONLY"] = "1"
    if not track1_shadow:
        return env

    # Set for BOTH modes, not only track1-only. Until 2026-08-24 this line lived inside the
    # `track1_only` branch above, so a transitional `--track1-shadow` start gave its children
    # the ledger and telemetry homes but never the flag that names the mode. The scheduler did
    # not care — it reads `--track1-shadow` off its own argv — but the dashboard backend has
    # no argv to read, and the environment is the only channel it has. Result: transitional
    # mode mirrored legacy-only, silently.
    #
    # Safe for the scheduler child: `run_scheduler` never reads this variable. The only
    # consumer is `monitor/backend/schedule_status.py`, which uses it to pick a slot table.
    env["RAITS_TRACK1_SHADOW"] = "1"

    # Set, not merely recommended in a runbook. An operator who exports these by hand into the
    # wrong shell gets a scheduler whose slots hard-refuse with `ledger_not_configured`, and a
    # shadow day that records nothing. An explicit export still wins — this fills the gap, it
    # does not override a decision.
    env.setdefault("RAITS_WINDOW_LEDGER_DIR", str(TRACK1_LEDGER_DIR))
    env.setdefault("RAITS_TELEMETRY_DIR", str(TRACK1_TELEMETRY_DIR))

    # Removed from the CHILD, whatever the launching shell happens to carry. This is the second
    # of the two factors that arm Track 1, and a launcher must never be the thing that supplies
    # it — the first factor, the confirmation file, is refused outright below.
    env.pop(TRACK1_ORDERS_ENV, None)
    return env


def orders_would_be_possible() -> tuple:
    """`(possible, why)` from the gate registry. Stage 5ZZN.

    Asked of `track1_gates` rather than inferred from the confirmation file, because since
    Stage 5ZZK the registry reads that file itself AND the measurements behind each blocker.
    Fails CLOSED — an unreadable registry reports "possible", so a guard built on it refuses
    rather than waves a start through on a question it could not answer.
    """
    try:
        from global_index import track1_gates as gates

        possible, why = gates.may_enable_orders()
        return bool(possible), list(why)
    except Exception as exc:                                          # noqa: BLE001
        return True, [f"the gate registry could not be read ({type(exc).__name__}: {exc}); "
                      f"treating orders as possible so this refuses rather than assumes"]


def legacy_entry_start_blockers() -> list[str]:
    """Why a scheduler start that registers LEGACY ENTRY jobs must not happen. Stage 5ZZN.

    The inverse of the guard above, and the one that was missing. `track1_shadow_blockers`
    has always asked whether a Track 1 start is safe; nothing asked whether a LEGACY start is,
    and the answer stopped being "always" the moment an operator signed a decision saying this
    paper login belongs to Track 1.

    One IB Gateway login is one position book — that is the whole of B1. A legacy entry job and
    a Track 1 entry on the same login net against each other at the broker and reconcile as a
    phantom against two files. The signature says legacy has retired from this login; a start
    that registers its 45 entry jobs contradicts the signature while the gate goes on reading
    it as true.
    """
    if not TRACK1_CONFIRMATION.exists():
        return []
    try:
        from global_index import track1_gates as gates

        conf, errors = gates.load_confirmations(gates.CONFIRMATION_PATH)
        if errors:
            # A file that does not validate grants nothing, so it asserts nothing either.
            return []
        if not conf.get("legacy_retired_confirmed"):
            return []
    except Exception as exc:                                          # noqa: BLE001
        return [f"the B1 decision could not be read ({type(exc).__name__}: {exc}); refusing "
                f"rather than starting a mode that may contradict it"]
    return [
        f"{TRACK1_CONFIRMATION.name} records legacy_retired_confirmed — the operator has "
        f"decided that legacy is retired for this paper login.",
        f"this start would register {legacy_entry_job_count()} legacy entry job(s) on that "
        f"same login, which contradicts the decision the B1 gate is currently reading as true.",
        "start with --track1-only-shadow instead: it registers Track 1's slots and no legacy "
        "entry job, keeps legacy's safety sweeps draining the old book, and cannot send an "
        "order while PAPER_SHADOW_EVIDENCE is unsatisfied.",
        f"if legacy really must run entries again, retire the decision first — edit or remove "
        f"{TRACK1_CONFIRMATION.name} — rather than leaving a signature that says otherwise.",
    ]


def legacy_entry_job_count(port: int = DEFAULT_IBKR_PORT) -> int:
    """How many legacy ENTRY jobs a default start registers. From the route table that the
    retirement audit and the scheduler's own removal step already read — one table, three
    readers, so this cannot drift into a second definition of "legacy's jobs"."""
    try:
        from global_index import track1_slots as t1

        return len(t1.legacy_retirement_candidates(port, track1_shadow=True))
    except Exception:                                                 # noqa: BLE001
        return 0


def track1_shadow_blockers(*, track1_only: bool = False) -> list[str]:
    """Why a Track 1 shadow start must not happen right now. Empty means it may.

    Fail-closed on both counts, and neither is created here:

      * the route could actually SEND — the confirmation file is present AND the gate registry
        reports no blocker left. Starting a *shadow* session then is starting something nobody
        asked for.

        Stage 5ZZN narrowed this. It used to refuse on the FILE ALONE, and the sentence behind
        it — "that file arms the route" — was true when the signature was the only thing
        between this route and an order. It has not been true since Stage 5S added a measured
        evidence gate, and Stage 5ZZK gave B1 a measured half of its own. Measured on
        2026-08-27: the operator signed the B1 decision, `--track1-only-shadow` began refusing
        because of it, and the scheduler was restarted into the plain legacy mode instead —
        which registers 45 legacy entry jobs on the very login the signature had just declared
        retired. **The guard pushed the operator out of the only safe mode and into the unsafe
        one.** So it now asks the registry whether an order is actually possible, which is the
        thing that knows.
      * `STOP_TRADING` absent — `--track1-shadow` adds Track 1's slots and removes exactly one
        legacy job. **All 23 legacy entry slots survive.** Starting without the kill switch
        resumes legacy trading, which is the opposite of the intent and happens silently.

        Note what that switch does and does not do: it halts NEW ENTRIES. A legacy slot still
        spawns, connects on IBKR clientId 1, fetches bars, rolls contracts and runs the exit
        and reconcile checks. Freezing legacy removes the trading, not the load.
    """
    blockers = []
    if TRACK1_CONFIRMATION.exists() and orders_would_be_possible()[0]:
        blockers.append(
            f"{TRACK1_CONFIRMATION.name} exists AND every order blocker is clear, so this "
            f"route can send orders. A shadow start must not run while that is true; "
            f"resolve the intent before starting anything.")
    if track1_only:
        # No STOP_TRADING requirement here, and that is the point of the mode rather than a
        # relaxation of it: the legacy strategy jobs are not registered at all, so there is
        # nothing for the switch to halt. Requiring a kill switch for jobs that do not exist
        # would teach an operator that the switch is what stops legacy — which is the belief
        # this whole stage exists to correct.
        return blockers
    if not LEGACY_STOP_FILE.exists():
        blockers.append(
            f"{LEGACY_STOP_FILE.name} is missing — Track 1 shadow mode still registers 23 legacy "
            f"entry slots, so starting now would resume legacy trading. Create it first: "
            f"New-Item -ItemType File STOP_TRADING")
    return blockers


def backend_listener_pids(api_port: int = DEFAULT_API_PORT) -> list[int]:
    result = _run(["netstat", "-ano"], timeout=15)
    pids: set[int] = set()
    pattern = re.compile(rf"^\s*TCP\s+\S+:{api_port}\s+\S+\s+LISTENING\s+(\d+)\s*$")
    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if match:
            pids.add(int(match.group(1)))
    return sorted(pids)


def _powershell_json(script: str) -> Any:
    result = _run(["powershell.exe", "-NoProfile", "-Command", script], timeout=20)
    text = result.stdout.strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return []


SCHEDULER_PATTERN = r"global_index\.run_scheduler"
# Matched on the command line, not on the listening port. Yesterday's collision was two
# backends on 5001 and 5002 — different ports, same clientId=99, so a per-port check saw
# nothing wrong while IBKR refused the second one.
BACKEND_PATTERN = r"monitor[\\/]start_backend\.py|monitor\.backend\.app"
# run_live_day children the scheduler spawned. Killing the scheduler does not take them
# with it, and an orphan holds clientId=1 — the next slot then collides with a process
# nobody is watching. Live 2026-08-06 had clientIds 1, 77, 82 and 93 on one account.
RUNNER_PATTERN = r"global_index\.run_live_day"


#: Stage 5ZZ. The marker the probe writes its failure message behind.
#:
#: Without it the recorded reason was `stderr[:200]`, and PowerShell's default error rendering
#: ECHOES THE WHOLE COMMAND before the message. Measured on a deliberately broken probe: 692
#: characters of stderr, of which the first 200 were entirely the script's own opening and the
#: actual words — "Invalid class" — sat at the very end. So the operator was shown
#: `UNKNOWN ($ErrorActionPreference='Stop'; try { $p = @(Get-CimInstance ...` and had, in
#: practice, an UNKNOWN with no reason. The one recorded failure in this project's ops log,
#: from 2026-08-13, is truncated in exactly that way and says nothing about what went wrong.
SCAN_ERROR_MARKER = "OPSSCANERR:"

#: What kind of failure it was, for anything that must branch without matching on English.
SCAN_OK = ""
SCAN_PERMISSION_DENIED = "permission_denied"
SCAN_TIMEOUT = "probe_timeout"
SCAN_UNAVAILABLE = "probe_unavailable"
SCAN_FAILED = "probe_failed"
SCAN_NO_OUTPUT = "probe_no_output"
SCAN_NOT_JSON = "probe_not_json"


def _scan_error_text(stderr: str, returncode: int) -> str:
    """The probe's own message, never the command it echoed back.

    Three sources in order of trust: the marked line the script writes itself; failing that the
    LAST non-empty line, because PowerShell puts the message after the echo rather than before
    it; failing that the exit code, which at least says something true.
    """
    raw = (stderr or "").strip()
    for line in raw.splitlines():
        if SCAN_ERROR_MARKER in line:
            return line.split(SCAN_ERROR_MARKER, 1)[1].strip()[:200]
    # Measured against real PowerShell output rather than guessed at. It renders:
    #
    #     0 | <the whole command, echoed and WRAPPED>
    #     1 | ...rest of the command } : Invalid
    #     2 | class
    #     3 | At line:1 char:181
    #     6 |     + CategoryInfo          : NotSpecified: ...
    #     7 |     + FullyQualifiedErrorId : Microsoft.PowerShell.Commands.WriteErrorException
    #
    # So the message begins after the first " : " that is not part of the decoration, and it
    # CONTINUES onto the next lines until the position marker. Taking the last line gives the
    # exception's class name; taking the first 200 characters gives the command. Neither is
    # what went wrong, and "Invalid class" is.
    lines = [ln.rstrip() for ln in raw.splitlines()]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("+") or stripped.startswith("At line:"):
            continue
        if " : " not in line:
            continue
        parts = [line.split(" : ", 1)[1].strip()]
        for nxt in lines[i + 1:]:
            t = nxt.strip()
            if not t or t.startswith("+") or t.startswith("At line:"):
                break
            parts.append(t)
        msg = " ".join(x for x in parts if x).strip()
        if msg:
            return msg[:200]
    tail = next((ln.strip() for ln in reversed(lines) if ln.strip()), "")
    return (tail.lstrip(": ").strip()[:200] or f"powershell exited {returncode}")


def _classify_scan_error(message: str) -> str:
    low = (message or "").lower()
    if "access is denied" in low or "permission" in low or "unauthorized" in low:
        return SCAN_PERMISSION_DENIED
    if "not recognized" in low or "cannot find" in low or "no such file" in low:
        return SCAN_UNAVAILABLE
    return SCAN_FAILED


def scan_processes(pattern: str) -> ProcessScan:
    """Enumerate matching processes, or report honestly that we could not.

    The script always prints a JSON array, so empty output can only mean the probe itself
    failed — there is no longer an innocent reading of silence.

    Stage 5ZZ: the failure path now carries the probe's own message and a code. The whole-table
    query is kept: filtering it to python processes was measured at 0.65 s against 0.63 s for
    the full 471-process table, so the cost is PowerShell's startup and not the enumeration,
    and a narrower query would have bought nothing while quietly excluding a scheduler someone
    launched under a different interpreter name.
    """
    script = (
        "$ErrorActionPreference='Stop'; "
        "try { $p = @(Get-CimInstance Win32_Process | "
        # `-ne $PID` is not tidiness. The pattern is embedded verbatim in THIS command line,
        # so the probe's own powershell always contains the text it is searching for, and any
        # pattern without a regex escape matches itself. Both production patterns happen to be
        # immune because they escape their dots — an accident, and `ensure_single` decides
        # whether to KILL a process from this same scan, so an accident is not good enough.
        f"Where-Object {{ $_.ProcessId -ne $PID -and $_.CommandLine -match '{pattern}' }} | "
        "Select-Object ProcessId, CommandLine, "
        "@{n='Started';e={$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss')}}); "
        "ConvertTo-Json -Depth 3 -InputObject $p -Compress } "
        f"catch {{ [Console]::Error.WriteLine('{SCAN_ERROR_MARKER}' + $_.Exception.Message); "
        "exit 1 }"
    )
    try:
        result = _run(["powershell.exe", "-NoProfile", "-Command", script], timeout=20)
    except subprocess.TimeoutExpired:
        return ProcessScan(ok=False, code=SCAN_TIMEOUT,
                           error="process probe timed out after 20s")
    except OSError as exc:
        return ProcessScan(ok=False, code=SCAN_UNAVAILABLE,
                           error=f"process probe could not run ({exc})")
    if result.returncode != 0:
        msg = _scan_error_text(result.stderr, result.returncode)
        return ProcessScan(ok=False, code=_classify_scan_error(msg), error=msg)
    text = result.stdout.strip()
    if not text:
        return ProcessScan(ok=False, code=SCAN_NO_OUTPUT,
                           error="process probe returned no output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ProcessScan(ok=False, code=SCAN_NOT_JSON,
                           error=f"process probe output was not JSON ({exc})")
    if isinstance(data, dict):
        data = [data]
    return ProcessScan(ok=True, processes=[
        RunningProcess(pid=int(item["ProcessId"]),
                       command=str(item.get("CommandLine") or ""),
                       started=str(item.get("Started") or "unknown"))
        for item in data if isinstance(item, dict) and item.get("ProcessId")
    ])


def _age_seconds(started: str | None) -> int | None:
    """Seconds since `started` ("yyyy-MM-dd HH:mm:ss" from Win32_Process), or None."""
    try:
        return int((dt.datetime.now()
                    - dt.datetime.strptime(str(started), "%Y-%m-%d %H:%M:%S")).total_seconds())
    except (TypeError, ValueError):
        return None


def scheduler_scan() -> ProcessScan:
    """The scheduler scan WITH its third state intact. Stage 5ZZ.

    `scheduler_processes()` below returns a list, and a list cannot say "I could not look".
    `ProcessScan` was built with three states precisely so that could not happen, and then the
    very next function threw the third away — so a probe hiccup reached `track1_status` as an
    empty list and was reported as `track1_mode=n/a`, which reads as "the scheduler is not
    running Track 1". Same defect family as the one the dataclass was written to end, one
    function later.
    """
    return scan_processes(SCHEDULER_PATTERN)


def scheduler_processes() -> list[dict[str, Any]]:
    return _as_rows(scheduler_scan())


def _as_rows(scan: ProcessScan) -> list[dict[str, Any]]:
    return [{"pid": item.pid, "command": item.command,
             "started": item.started, "age_seconds": _age_seconds(item.started)}
            for item in scan.processes]


def process_command(proc: Mapping[str, Any]) -> str:
    """The command line of one process row, whichever key it arrived under.

    There is a RENAME BOUNDARY here and it has already cost a wrong answer. The PowerShell
    query selects `CommandLine`; `scan_processes` maps that field into a dataclass whose
    attribute is `command`; `scheduler_processes` then emits dicts keyed `command`. A reader
    that asks for `CommandLine` — the name on the far side of the boundary — gets nothing,
    and `nothing` parses as "no flags", which reads as "legacy-only".

    That is exactly what `track1_status` did: with a scheduler genuinely running
    `--track1-only-shadow`, `ops.py status` printed `track1_mode=legacy-only` and
    `track1_safety_routes=['legacy']`. Every field was individually right; the seam between
    two names for one thing was not — and the failure was silent because an empty string is
    a perfectly good string to search.

    `CommandLine` is kept as a fallback, not as an equal: a raw CIM row handed straight in by
    a caller or an older test still resolves.
    """
    return str(proc.get("command") or proc.get("CommandLine") or "")


def scheduler_command_lines(procs: "Sequence[Mapping[str, Any]] | None" = None) -> str:
    """Every scheduler process's command line, joined. One reader, so a second consumer
    cannot reintroduce the key mistake independently."""
    rows = scheduler_processes() if procs is None else procs
    return " ".join(process_command(p) for p in rows)


def _ops_log(message: str) -> None:
    """ops.py used to leave no trace of its own decisions.

    When two schedulers turned up on 2026-08-13 the logs could say which process started
    them but not why ops.py thought that was allowed, because the decision was only ever
    printed to a console nobody kept.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    with (LOG_DIR / "ops.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def _taskkill(pids: list[int]) -> list[int]:
    """Return the pids that did NOT die. The old version discarded taskkill's exit code,
    so an access-denied kill looked exactly like a successful one."""
    failed = []
    for pid in sorted(set(pids)):
        try:
            result = _run(["taskkill", "/PID", str(pid), "/F"], timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            failed.append(pid)
            continue
        if result.returncode != 0:
            failed.append(pid)
    return failed


def stop_backend(api_port: int = DEFAULT_API_PORT) -> list[int]:
    pids = backend_listener_pids(api_port)
    if pids:
        _taskkill(pids)
        time.sleep(1)
    return pids


def stop_scheduler() -> list[int]:
    pids = [item["pid"] for item in scheduler_processes()]
    if pids:
        _taskkill(pids)
        time.sleep(1)
    return pids


def stop_runners() -> list[int]:
    """Kill any run_live_day the scheduler left behind. Returns the pids it killed.

    Stopping the scheduler does not stop its children. An orphaned run_live_day keeps
    clientId=1 open, so the freshly started scheduler's next slot meets a competitor it
    has no record of.
    """
    scan = scan_processes(RUNNER_PATTERN)
    if not scan.ok or not scan.pids:
        return []
    _taskkill(scan.pids)
    time.sleep(1)
    return scan.pids


def _human_age(seconds: float | int | None) -> str:
    if not seconds or seconds < 0:
        return "unknown age"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3_600)
    minutes = rem // 60
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def describe_scheduler_state(processes: list[dict[str, Any]]) -> str:
    """One line saying the scheduler was NOT restarted, and how old it is.

    Printing nothing here is what let 21 backend restarts read as full restarts while a
    scheduler from three days earlier kept running a cron table that no longer matched
    the code. Age is the number that exposes it.
    """
    if not processes:
        return "scheduler=none running (nothing to leave alone)"
    parts = []
    for item in processes:
        age = _human_age(item.get("age_seconds"))
        started = item.get("started") or "unknown start"
        parts.append(f"pid {item.get('pid')} started {started} ({age} ago)")
    return ("scheduler=UNTOUCHED — " + "; ".join(parts)
            + ". Use `restart` (or `up --restart-scheduler`) to replace it.")


def _describe(scan: ProcessScan) -> str:
    return "\n".join(f"  PID {item.pid}  started {item.started}  {item.command[:90]}"
                     for item in scan.processes)


def ensure_single(kind: str, pattern: str, *, assume_yes: bool) -> bool:
    """Guarantee nothing matching `pattern` is running, so the caller can start exactly one.

    Returns False when the host must not be touched — either the probe failed, the operator
    declined, or something survived the kill. Every path is logged.
    """
    scan = scan_processes(pattern)

    def _ask(found: ProcessScan) -> bool:
        print(f"{kind}: {len(found.processes)} process(es) already running:")
        print(_describe(found))
        answer = input(f"Stop them and start one fresh {kind}? [y/N] ").strip().lower()
        return answer in {"y", "yes"}

    interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())
    decision = plan_single_instance(scan, assume_yes=assume_yes,
                                    confirm=_ask if interactive else None)
    _ops_log(f"{kind}: scan_ok={scan.ok} found={scan.pids} -> {decision.action}"
             + (f" ({decision.reason})" if decision.reason else ""))

    if decision.action == "refuse":
        print(f"{kind}: REFUSING to start - {decision.reason}")
        if decision.pids:
            print(_describe(scan))
        return False
    if decision.action == "start":
        return True

    survivors = _taskkill(decision.pids)
    if survivors:
        print(f"{kind}: taskkill could not stop {survivors} - not starting a second one")
        _ops_log(f"{kind}: taskkill failed for {survivors}")
        return False
    time.sleep(1.5)

    # Trust the recount, not the kill. taskkill returns before the process is reaped, and a
    # started-anyway launch is exactly the failure this function exists to prevent.
    after = scan_processes(pattern)
    if not after.ok:
        print(f"{kind}: cannot confirm the kill ({after.error}) - not starting")
        _ops_log(f"{kind}: post-kill scan failed ({after.error})")
        return False
    if after.processes:
        print(f"{kind}: still running after kill: {after.pids} - not starting")
        _ops_log(f"{kind}: survivors after kill {after.pids}")
        return False
    print(f"{kind}: stopped {decision.pids}")
    return True


def _open_log(name: str):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return (LOG_DIR / name).open("ab", buffering=0)


def start_scheduler(ibkr_port: int, *, shadow_resume: bool, assume_preflight_ok: bool,
                    track1_shadow: bool = False, track1_only: bool = False) -> int | None:
    """Start the scheduler.

    `track1_shadow` adds the Track 1 slots ALONGSIDE legacy — transitional, both routes run.
    `track1_only` (Stage 5M-D) adds them and does NOT register legacy strategy jobs; it is the
    clean validation path, and it implies `track1_shadow`.

    With neither flag this is byte-for-byte what it always was: the same argv, the same
    environment. Both Track 1 modes are strictly additive and gated on their flag.
    """
    if track1_only:
        track1_shadow = True
    existing = scheduler_processes()
    if existing:
        return None
    args = [_pythonw(), "-m", "global_index.run_scheduler", "--port", str(ibkr_port)]
    if shadow_resume:
        args.append("--shadow-resume")
    if assume_preflight_ok:
        args.append("--assume-preflight-ok")
    if track1_only:
        args.append("--track1-only-shadow")
    elif track1_shadow:
        args.append("--track1-shadow")
    err = _open_log("ops_scheduler.err.log")
    proc = subprocess.Popen(
        args,
        cwd=str(ROOT),
        env=_env(track1_shadow=track1_shadow, track1_only=track1_only),
        stdout=subprocess.DEVNULL,
        stderr=err,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    return proc.pid


def start_backend(ibkr_port: int, api_port: int, *,
                  track1_shadow: bool = False, track1_only: bool = False) -> int:
    """Start the read-only dashboard backend.

    The Track 1 flags are taken and PASSED ON, which they were not until 2026-08-24. The
    scheduler received `_env(track1_shadow=..., track1_only=...)` and the backend received a
    bare `_env()`, so the two children of the same `ops.py up` disagreed about which route
    was running. Measured on the live box: `ops.py status` reported
    `track1_mode=track1-only-shadow` from the scheduler's own command line while
    `/api/v1/schedule-status` served `state_slot_count=45` and a legacy `next_decision_job` —
    the operator's dashboard describing a system that was not the one running.

    The backend places no orders and reads no broker state it did not already read; these
    two variables only tell the schedule mirror which slot table to expect. `_env` still
    strips `TRACK1_ORDERS_APPROVED` from the child, so widening this cannot arm anything.
    """
    out = _open_log("ops_backend.out.log")
    err = _open_log("ops_backend.err.log")
    proc = subprocess.Popen(
        [
            sys.executable,
            "monitor/start_backend.py",
            "--ibkr-port",
            str(ibkr_port),
            "--api-port",
            str(api_port),
        ],
        cwd=str(ROOT),
        env=_env(track1_shadow=track1_shadow, track1_only=track1_only),
        stdout=out,
        stderr=err,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    return proc.pid


def _get_json(url: str, timeout: float = 3.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def wait_backend(api_port: int, seconds: int = 25) -> dict[str, Any] | None:
    deadline = time.time() + seconds
    url = f"http://127.0.0.1:{api_port}/api/connection"
    last = None
    while time.time() < deadline:
        last = _get_json(url)
        if last and last.get("connected") is True:
            return last
        time.sleep(1)
    return last


def track1_status() -> dict:
    """What an operator needs to see before and during a Track 1 shadow period.

    Read-only and import-safe: it creates nothing, connects to nothing, and never consults the
    broker. `scheduler_track1_shadow` is read from the RUNNING process's own command line rather
    than from a flag someone remembers passing — a scheduler started before the flag existed
    looks identical from the outside otherwise.
    """
    from global_index import track1_gates as gates

    # Stage 5ZZ. The scan is taken for its THIRD state; the rows still come through
    # `scheduler_processes`, which is the seam every caller and test already patches. Reading
    # the scan directly for both looked tidier and silently bypassed that seam: a test that
    # believed it had described a transitional scheduler was reading the real machine, and
    # passed or failed on whatever happened to be running. A test that is not isolated is
    # worse than no test, because it reports on the wrong system with full confidence.
    scan = scheduler_scan()
    procs = scheduler_processes()
    # `known` is the honest join of the two: rows are proof whatever the probe said, and only
    # "no rows AND the probe could not look" is genuinely unknown.
    known = scan.ok or bool(procs)
    cmdlines = scheduler_command_lines(procs)
    blockers = [b.id for b in gates.blocking()]
    track1_only = ("--track1-only-shadow" in cmdlines) if (known and procs) else None
    # `--track1-only-shadow` does NOT contain `--track1-shadow` as a substring, so the two
    # flag checks are genuinely independent; the OR below is the mode implication, not a
    # workaround for overlapping strings.
    return {
        # Stage 5ZZ. THREE states. `None` means the probe failed and nobody knows — which is
        # not the same answer as False, and printing it as False is how a status command comes
        # to say "Track 1 is not running" about a scheduler that is.
        "scheduler_running": (bool(procs) if known else None),
        "scheduler_scan_ok": scan.ok,
        "scheduler_scan_code": scan.code,
        "scheduler_scan_error": scan.error,
        # Where the mode below came from, said out loud rather than left to be assumed.
        "track1_mode_source": ("process_table" if known else "unknown"),
        # "are the Track 1 slots registered", not "is this one flag on the argv". In
        # track1-only mode `make_scheduler` sets `track1_shadow = True` itself, so a status
        # that answered the literal-flag question would report False for a scheduler that is
        # demonstrably running all 70 Track 1 slots — the same silent-wrong-answer family as
        # the key mismatch above, one field over. The literal flag stays available as
        # `scheduler_track1_shadow_flag` so nothing is lost.
        "scheduler_track1_shadow": ((("--track1-shadow" in cmdlines) or track1_only)
                                    if (known and procs) else None),
        "scheduler_track1_shadow_flag": (("--track1-shadow" in cmdlines)
                                         if (known and procs) else None),
        "scheduler_track1_only": track1_only,
        # Which route's SAFETY net is scheduled — Stage 5O. Legacy safety always runs (it
        # drains legacy's book); Track 1 safety exists only in track1-only mode, watching
        # live_positions.track1.json with its own max-hold marker.
        "safety_routes": ((["legacy", "track1"] if track1_only else ["legacy"])
                          if (known and procs) else None),
        "window_coverage_dir": str(TRACK1_LEDGER_DIR),
        "window_coverage_exists": TRACK1_LEDGER_DIR.exists(),
        "slot_timing_dir": str(TRACK1_TELEMETRY_DIR),
        "slot_timing_exists": TRACK1_TELEMETRY_DIR.exists(),
        "stop_trading_present": LEGACY_STOP_FILE.exists(),
        "confirmation_present": TRACK1_CONFIRMATION.exists(),
        "orders_env_present": os.environ.get(TRACK1_ORDERS_ENV) is not None,
        "blocking": blockers,
        "orders_possible": gates.may_enable_orders()[0],
        # Stage 5ZQ — B1's measured half, read from the recorded audit. Never opens a
        # connection: `python -m global_index.b1_audit --broker ibkr --record` asks the
        # account, this reads what it wrote. No record is UNKNOWN, never flat.
        "b1": _b1_status(),
        # Stage 5ZZN. Does the RUNNING scheduler's mode agree with the signed B1 decision?
        "scheduler_mode": _scheduler_mode_compatibility(track1_only, known and bool(procs)),
    }


def _scheduler_mode_compatibility(track1_only, mode_known: bool) -> dict:
    """Is the running scheduler's mode consistent with the signed B1 decision? Stage 5ZZN.

    Three answers, and the third is the point. `None` means the process table could not be
    read, so the mode is unknown — which is NOT the same as compatible, and a status line that
    printed it as compatible would be the exact fail-open this route keeps finding.
    """
    out = {"confirmation": TRACK1_CONFIRMATION.exists(),
           "legacy_retired_signed": False, "track1_only": track1_only,
           "legacy_entry_jobs": 0, "compatible": None, "detail": ""}
    if not out["confirmation"]:
        out.update(compatible=True,
                   detail="no B1 decision is recorded, so no mode contradicts one")
        return out
    out["legacy_retired_signed"] = bool(legacy_entry_start_blockers())
    if not out["legacy_retired_signed"]:
        out.update(compatible=True,
                   detail="a confirmation exists but does not record legacy_retired_confirmed")
        return out
    if not mode_known or track1_only is None:
        out["detail"] = ("the scheduler's mode could not be read, so whether it contradicts "
                         "the B1 decision is unknown")
        return out
    if track1_only:
        out.update(compatible=True,
                   detail="track1-only-shadow registers no legacy entry job, which is what "
                          "the B1 decision says")
        return out
    out["legacy_entry_jobs"] = legacy_entry_job_count()
    out.update(compatible=False,
               detail=f"the B1 decision says legacy is retired for this login, and the running "
                      f"scheduler registers {out['legacy_entry_jobs']} legacy entry job(s) on "
                      f"it")
    return out


def _b1_status() -> dict:
    """What the last B1 audit found. Fails to UNKNOWN, never to flat."""
    try:
        from global_index import track1_b1 as b1

        r = b1.latest(".")
        broker = (r.inputs or {}).get("broker") or {}
        legacy = (r.inputs or {}).get("legacy_book") or {}
        track1 = (r.inputs or {}).get("track1_book") or {}
        return {
            "status": r.status,
            "code": r.code,
            "checked_at": r.checked_at,
            "line": b1.operator_line(r),
            "legacy_book_positions": legacy.get("count"),
            "track1_book_positions": track1.get("count"),
            "broker_source": broker.get("source"),
            "broker_positions": (len(broker["positions"])
                                 if isinstance(broker.get("positions"), list) else None),
            "broker_working_orders": (len(broker["open_orders"])
                                      if isinstance(broker.get("open_orders"), list) else None),
            "orphan_orders": len((r.findings or {}).get("orphans") or []),
        }
    except Exception as exc:                                      # noqa: BLE001
        return {"status": "UNKNOWN", "code": "reader_failed",
                "line": f"the B1 audit record could not be read ({type(exc).__name__})"}


def _spy_next_automatic_attempt(now) -> str:
    """Which scheduled job will look at the SPY series next, in words with a time on it.

    Stage 5ZZZ-AC. Only interesting when the file is already short: an operator reading
    "missing 2026-08-28" on a Sunday morning needs to know whether anything is going to try
    before the overnight window, or whether they are the next attempt.

    Both weekend jobs are named when both are still ahead, because the Sunday one is the
    early warning and the Monday one is still the last chance - reporting only the nearer of
    them would hide whichever matters more.
    """
    try:
        wd = now.weekday()                       # 5=Sat 6=Sun
        hhmm = (now.hour, now.minute)
        if wd == 5:                              # Saturday: nothing runs today
            return ("Next automatic attempts: SPY_WEEKEND_PRE_NKD_CHECK Sunday 18:00 ET, then "
                    "SPY_LAST_CHANCE_PRE_NKD Monday 00:45 ET (25 min before NKD 01:10)")
        if wd == 6:                              # Sunday
            if hhmm < (18, 0):
                return ("Next automatic attempts: SPY_WEEKEND_PRE_NKD_CHECK today 18:00 ET, "
                        "then SPY_LAST_CHANCE_PRE_NKD Monday 00:45 ET (25 min before "
                        "NKD 01:10)")
            return ("SPY_WEEKEND_PRE_NKD_CHECK has already run today; the only remaining "
                    "automatic attempt is SPY_LAST_CHANCE_PRE_NKD Monday 00:45 ET (25 min "
                    "before NKD 01:10)")
        return ""                                # weekday: the evening ladder speaks for itself
    except Exception:                                                 # noqa: BLE001
        return ""


def spy_daily_coverage(regime_csv: str = "spy_daily_live.csv", now_et=None) -> dict:
    """Does the daily regime file reach the day the NEXT session will ask for? Stage 5ZZB.

    The gap this closes is not a missing check — it is a missing OWNER. The post-close refresh
    already notices when it leaves the series short, and warns in exactly the right words:
    "this is only a problem if it is still true tomorrow." Tomorrow came, the NKD window ran at
    ten past one in the morning, and nothing had looked. The warning named its own escalation
    condition and no reader existed for it.

    So this is that reader, in the one place an operator types by hand. It asks the freshness
    module for the requirement rather than restating it, because a second copy of "which day is
    needed" is a second copy that can drift from the gate that actually refuses.
    """
    out = {"required": None, "last": None, "state": "unknown", "line": "", "calendar": ""}
    try:
        import pandas as _pd

        from global_index import track1_freshness as _fresh
        from global_index import update_spy_csv as _spy

        import zoneinfo as _zi

        now = _pd.Timestamp(now_et) if now_et is not None else _pd.Timestamp(
            dt.datetime.now(_zi.ZoneInfo("America/New_York")).replace(tzinfo=None))
        need = _fresh.required_daily_close_through(now)
        cov = _spy.coverage_status(regime_csv, need.date())
        out.update(required=cov["required"], last=cov["last"], state=cov["state"],
                   calendar=_fresh.calendar_source())
    except Exception as exc:                                          # noqa: BLE001
        out["line"] = (f"could not be determined ({type(exc).__name__}: {exc}) — "
                       f"unknown is not covered")
        return out

    if out["state"] == _spy.COVERAGE_OK:
        out["line"] = f"covers {out['required']}, which is what the next session asks for"
    elif out["state"] == _spy.COVERAGE_SHORT:
        # Plain words on purpose. `freshness_allow=false` is true and tells an operator
        # nothing about what to do; a missing date names the thing and the day.
        out["line"] = (f"SPY daily file is missing {out['required']} — it ends on "
                       f"{out['last']}. Sleeves that run before the 13:45 pre-flight (the "
                       f"overnight NKD window) will refuse on stale daily context until the "
                       f"refresh is re-run")
        # Stage 5ZZZ-AC. On a weekend, say WHICH automatic attempt is still ahead. The
        # measured failure was a Friday where all three evening rungs ran and the provider
        # still had nothing: the operator's next signal would have been 00:45 Monday, 25
        # minutes before the window. Naming the Sunday job turns a 55-hour silence into
        # something with a time on it - and the 00:45 job is still named, because it is
        # still the last one.
        out["next_automatic"] = _spy_next_automatic_attempt(now)
        if out["next_automatic"]:
            out["line"] += f". {out['next_automatic']}"
    else:
        out["line"] = "could not be read — unknown is not covered"
    return out


def print_track1_status() -> None:
    # The trading-calendar module warns at IMPORT time that it is falling back to hardcoded
    # rules, and the first thing below pulls it in. The warning is real and the requirement
    # this status prints is computed from that very calendar — but as a stray line above the
    # status header it reads like the command the operator just typed had failed. Silenced for
    # the duration of this print and reported as a FIELD instead, so the information survives
    # where it belongs. The logger's name is capitalised; silencing the lowercase spelling
    # silences a logger nobody uses, which is how the first attempt at this changed nothing.
    import logging as _logging

    _cal_log = _logging.getLogger("RAITS.live.trading_calendar")
    _prev_level = _cal_log.level
    _cal_log.setLevel(_logging.ERROR)
    try:
        _print_track1_status()
    finally:
        _cal_log.setLevel(_prev_level)


def _print_track1_status() -> None:
    t = track1_status()
    # Stage 5ZZ. `scheduler_running` is now THREE-valued, and `None` may not fall into the
    # same branch as False. "the probe could not look" and "nothing is running" are different
    # facts, and only one of them means Track 1 is off.
    if t["scheduler_running"] is None:
        mode, source = "unknown", "none"
    elif not t["scheduler_running"]:
        mode, source = "n/a", "process_table"
    elif t["scheduler_track1_only"]:
        mode, source = "track1-only-shadow", "process_table"
    elif t["scheduler_track1_shadow"]:
        mode, source = "track1-shadow (transitional)", "process_table"
    else:
        mode, source = "legacy-only", "process_table"

    # Stage 5ZZN. The real caller supplies the running process's start, so a registration
    # line written by a scheduler that has since exited is not read as a statement about the
    # one running now.
    try:
        _procs = scheduler_processes()
        _started = str((_procs[0] or {}).get("started") or "") if _procs else None
    except Exception:                                                 # noqa: BLE001
        _started = None
    fresh = slot_table_freshness(process_started_at=_started)
    if source == "none":
        # No process to read, so the schedule's own log is the only witness left, and it is
        # named as such. It can still say what the running scheduler LOADED, which is the one
        # question a stale table turns on.
        if fresh.get("registered_slots") is not None:
            source = "log"
    print(f"track1_mode={mode} track1_mode_source={source}"
          + (f" ({t['scheduler_scan_code']}: {t['scheduler_scan_error']})"
             if not t["scheduler_scan_ok"] else ""))
    # The check Stage 5ZY-PRE had to run by hand: a scheduler builds its table once, at boot,
    # so every edit after that is a schedule the running process has never seen.
    # Stage 5ZZE. The paper account, on its own line and apart from everything else on this
    # panel. It answers "is the account safe to start from", which is not the same question as
    # "has the route watched enough mornings" and must not be able to stand in for it.
    try:
        from global_index import track1_account_baseline as _ab

        _base = _ab.latest(".")
        print(f"paper_account_baseline={_base.status} ({_base.code})")
        print(f"  {_ab.operator_line(_base)}")
    except Exception as _exc:                                         # noqa: BLE001
        print(f"paper_account_baseline=UNKNOWN (reader_failed: {type(_exc).__name__}) — "
              f"unknown is not a baseline")

    spy = spy_daily_coverage()
    print(f"spy_daily_coverage={spy['state']} last={spy['last']} required={spy['required']}"
          + (f" calendar={spy['calendar']}" if spy.get("calendar") else ""))
    if spy["state"] != "covers_required_day":
        print(f"  {spy['line']}")
    print(f"track1_slot_table={fresh['state']}"
          f" source_slots={fresh['source_slots']} registered_slots={fresh['registered_slots']}")
    if fresh["state"] == "stale":
        print(f"  RESTART NEEDED - {fresh['detail']}")
    print(f"track1_safety_routes={t['safety_routes'] or 'n/a'}  "
          f"(legacy safety watches live_positions.json; track1 safety watches "
          f"live_positions.track1.json with its own max-hold marker)")
    print(f"track1_window_coverage={t['window_coverage_dir']} exists={t['window_coverage_exists']}")
    print(f"track1_slot_timing={t['slot_timing_dir']} exists={t['slot_timing_exists']}")
    print(f"track1_stop_trading={t['stop_trading_present']} "
          f"confirmation={t['confirmation_present']} "
          f"{TRACK1_ORDERS_ENV.lower()}={t['orders_env_present']}")
    print(f"track1_blocking={t['blocking'] or 'none'} orders_possible={t['orders_possible']}")
    _m = t.get("scheduler_mode") or {}
    _compat = _m.get("compatible")
    print(f"track1_scheduler_mode={'compatible' if _compat else 'INCOMPATIBLE' if _compat is False else 'unknown'}"
          f" confirmation={_m.get('confirmation')} legacy_entry_jobs={_m.get('legacy_entry_jobs')}")
    if _compat is False:
        # Not a footnote. A signed decision and a running configuration that contradict each
        # other is the condition this line exists to make impossible to scroll past.
        print(f"  MODE CONFLICT - {_m.get('detail')}")
        print(f"  fix: python monitor/ops.py restart --scheduler --track1-only-shadow --yes")
    elif _compat is None and _m.get("confirmation"):
        print(f"  MODE UNKNOWN - {_m.get('detail')}")
    b = t.get("b1") or {}
    def _n(v):
        return "?" if v is None else v
    print(f"b1_legacy_flat={b.get('status', 'UNKNOWN')} ({b.get('code')})  "
          f"legacy_book={_n(b.get('legacy_book_positions'))} "
          f"track1_book={_n(b.get('track1_book_positions'))} "
          f"broker_positions={_n(b.get('broker_positions'))} "
          f"working_orders={_n(b.get('broker_working_orders'))} "
          f"orphans={b.get('orphan_orders', 0)}")
    print(f"  {b.get('line', 'B1 could not be established.')}"
          + (f"  [observed {b['checked_at']}]" if b.get("checked_at") else ""))


#: The scheduler's own stderr, which ops.py redirects when it starts one.
SCHEDULER_LOG = LOG_DIR / "ops_scheduler.err.log"

#: The line the scheduler prints once, at boot, when it registers the Track 1 slot table.
SLOTS_REGISTERED = "Track 1 SHADOW slots registered:"


def scheduler_log_evidence(path: Path | None = None) -> dict:
    """What the scheduler's own log can say when the process table cannot be read.

    Deliberately NOT a claim that anything is running. A log is a record of something that
    happened, and the most recent line in it is equally consistent with a process that is still
    going and one that died a minute later. Every field here is labelled `log`, and
    `proves_running` is False without exception — the caller may pair it with a live listener
    or a pid, and until it does it has a history, not a status.
    """
    log = Path(path) if path is not None else SCHEDULER_LOG
    out = {"source": "log", "path": str(log), "readable": False, "proves_running": False,
           "last_registered_slots": None, "last_registered_at_machine_local": None}
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["readable"] = True
    for line in reversed(text.splitlines()):
        if SLOTS_REGISTERED in line:
            tail = line.split(SLOTS_REGISTERED, 1)[1].strip()
            digits = ""
            for ch in tail:
                if ch.isdigit():
                    digits += ch
                elif digits:
                    break
            if digits:
                out["last_registered_slots"] = int(digits)
            # The timestamp the scheduler wrote, on the MACHINE's clock. Named that way in the
            # key rather than left to look like the ET this project reasons in — the machine
            # sits two hours west of the market and a naked stamp here has already invited one
            # wrong reading.
            out["last_registered_at_machine_local"] = line.split(" INFO")[0].strip()[:19]
            break
    return out


def slot_table_freshness(evidence: dict | None = None, *,
                         process_started_at: str | None = None) -> dict:
    """Does the schedule in memory still match the schedule on disk?

    This is the check that Stage 5ZY-PRE had to perform by hand. A scheduler builds its job
    table once, at boot, and holds it; every edit afterwards changes the code and not the
    running process. The log records what it registered, the package records what it declares,
    and when those two numbers part company the route is running a schedule nobody can read
    from the source any more.
    """
    ev = evidence if evidence is not None else scheduler_log_evidence()
    out = {"source_slots": None, "registered_slots": ev.get("last_registered_slots"),
           "state": "unknown", "detail": "", "logged_before_current_process": False}
    # Stage 5ZZN. Whose registration line is this? The log outlives the process that wrote it,
    # so a line from a scheduler that has since exited must not be read as a statement about
    # the one running now.
    #
    # `process_started_at` is passed IN rather than looked up here. Scanning the live process
    # table inside this function made it answer differently for a caller that had handed it a
    # fixture log — two unit tests about the COUNT comparison started failing because the real
    # scheduler outside had started after their fixture's timestamp. A function that reads
    # ambient state cannot be asked a hypothetical.
    stamp = str(ev.get("last_registered_at_machine_local") or "")
    if stamp and process_started_at:
        out["logged_before_current_process"] = stamp < str(process_started_at)
        out["registration_logged_at"] = stamp
        out["process_started_at"] = str(process_started_at)
    try:
        from global_index import track1_slots as t1

        out["source_slots"] = len(t1.TRACK1_SLOTS)
    except Exception as exc:                                          # noqa: BLE001
        out["detail"] = f"the slot table could not be imported ({type(exc).__name__}: {exc})"
        return out
    if out["registered_slots"] is None:
        out["detail"] = ("no registration line in the scheduler log, so what the running "
                         "process loaded cannot be compared with what the code declares")
        return out
    # Stage 5ZZN. The log line may belong to a process that is no longer running.
    #
    # Measured on 2026-08-27: status printed `track1_slot_table=fresh registered_slots=71`
    # while the scheduler in the process table had been started without any Track 1 flag and
    # had registered NONE. The number was true about a process that had already exited. A
    # freshness check that compares the code against a dead process's log is a check that
    # reports on the wrong system with full confidence.
    if out["registered_slots"] != out["source_slots"]:
        pass          # fall through to the count branches below — see the note above
    elif out.get("logged_before_current_process"):
        out["state"] = "stale_log"
        out["detail"] = ("the registration line predates the running scheduler, so it "
                         "describes a process that has already exited; what the current one "
                         "registered is not recorded")
        return out
    if out["registered_slots"] == out["source_slots"]:
        out["state"] = "fresh"
        out["detail"] = (f"the running scheduler registered {out['registered_slots']} slots "
                         f"and the code declares {out['source_slots']}")
        return out
    out["state"] = "stale"
    out["detail"] = (
        f"the running scheduler registered {out['registered_slots']} slots and the code now "
        f"declares {out['source_slots']}. It builds its table once at boot, so the difference "
        f"is edits it has never seen — restart it, or it will keep firing the old schedule")
    return out


def print_status(api_port: int) -> None:
    listeners = backend_listener_pids(api_port)
    connection = _get_json(f"http://127.0.0.1:{api_port}/api/connection")
    broker = _get_json(f"http://127.0.0.1:{api_port}/api/v1/broker")
    print(f"backend_port={api_port} listeners={listeners or 'none'}")
    # Stage 5ZZ. Three things travel with every line: the pids, WHERE they came from, and —
    # when they could not be read — a code and the probe's own words. The old form printed
    # `UNKNOWN (<reason>)`, and the reason was the first 200 characters of stderr, which
    # PowerShell fills with an echo of the command before it gets to the message. So the
    # reason was reliably the script and never the failure.
    scans = {}
    for kind, pattern in (("scheduler", SCHEDULER_PATTERN), ("backend", BACKEND_PATTERN)):
        scan = scan_processes(pattern)
        scans[kind] = scan
        if not scan.ok:
            print(f"{kind}_process_scan={scan.code}: {scan.error}")
            print(f"{kind}_pids=unknown_due_to_process_scan_error source=none")
        elif len(scan.processes) > 1:
            # Say it in the same words as the incident it causes, not as a bare count.
            print(f"{kind}_pids={scan.pids}  DUPLICATE - every slot fires once per process"
                  f"  source=process_table")
            print(_describe(scan))
        else:
            print(f"{kind}_pids={scan.pids or 'none'} source=process_table")

    # The fallback, and it is labelled rather than blended in. A listener on the port is a live
    # fact about the backend; the scheduler has no port, so its log can offer a history and
    # says so. Neither is allowed to read as process-table truth.
    if not scans["backend"].ok:
        print(f"backend_fallback=listeners:{listeners or 'none'} source=port_listener "
              f"proves_running={bool(listeners)}")
    if not scans["scheduler"].ok:
        ev = scheduler_log_evidence()
        if ev.get("readable") and ev.get("last_registered_slots") is not None:
            print(f"scheduler_fallback=last_registered_{ev['last_registered_slots']}_slots"
                  f" at {ev['last_registered_at_machine_local']} machine-local"
                  f" source=log proves_running=False")
        else:
            print(f"scheduler_fallback=none source=log "
                  f"({ev.get('error') or 'no registration line found'})")
    print(f"connection={json.dumps(connection, ensure_ascii=False) if connection else 'unavailable'}")
    if broker:
        print(f"broker_connected={broker.get('connected')} freshness={broker.get('freshness')} age_seconds={broker.get('age_seconds')}")
    print_track1_status()


def cmd_up(args: argparse.Namespace) -> int:
    label = getattr(args, "label", "up")
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] RAITS ops {label}")
    assume_yes = getattr(args, "yes", False)
    track1_only = bool(getattr(args, "track1_only_shadow", False))
    track1_shadow = bool(getattr(args, "track1_shadow", False)) or track1_only

    if bool(getattr(args, "track1_shadow", False)) and track1_only:
        print("REFUSING: --track1-shadow and --track1-only-shadow ask for different "
              "schedules. The first runs legacy AND Track 1; the second does not register "
              "legacy strategy jobs at all. Pick one.")
        _ops_log("track1: refused, both shadow flags given")
        return 2

    # Stage 5ZZN. A start that would register legacy ENTRY jobs, while the operator's signed
    # B1 decision says legacy has retired from this login, is refused before anything is
    # stopped or started.
    #
    # `track1_only` is the one mode that removes those jobs, so it is the one mode exempt.
    # `--track1-shadow` is NOT exempt: it adds Track 1's slots and keeps all 45 legacy entry
    # jobs, which is exactly the collision B1 exists to prevent.
    #
    # Stage 5ZZO made this conditional on a start being ASKED FOR. It ran unconditionally, so
    # `restart --no-scheduler` — the command whose entire meaning is *leave the scheduler
    # alone and rebuild the backend* — was refused with "this start would register 45 legacy
    # entry jobs", about a start nobody had requested. It was the only route to a backend
    # restart, and 5ZZN had just made that the documented way to pick up a new API route.
    #
    # A guard that fires where no start happens is not a stricter guard. It is a guard that
    # teaches an operator to work around it, and the workaround here would have been
    # `restart --scheduler` — restarting a live scheduler to rebuild a read-only backend,
    # which is the more dangerous of the two acts.
    def _refuse_legacy_start(mode: str) -> bool:
        """True when this start must not happen. Prints the reasons; stops nothing."""
        blockers = legacy_entry_start_blockers()
        if not blockers:
            return False
        print(f"{mode}: REFUSING to start")
        for b in blockers:
            print(f"  - {b}")
        _ops_log(f"{mode}: refused, would register legacy entry jobs against a signed "
                 f"B1 decision")
        return True

    # The explicit restart path: checked HERE, before `ensure_single` stops anything. A guard
    # that fired after the kill would leave the operator with no scheduler at all.
    if args.restart_scheduler and not track1_only:
        if _refuse_legacy_start("track1-shadow" if track1_shadow else "legacy/default"):
            return 2

    if track1_shadow:
        mode = "track1-only-shadow" if track1_only else "track1-shadow"
        blockers = track1_shadow_blockers(track1_only=track1_only)
        if blockers:
            print(f"{mode}: REFUSING to start")
            for b in blockers:
                print(f"  - {b}")
            _ops_log(f"{mode}: refused ({len(blockers)} blocker(s))")
            return 2
        TRACK1_LEDGER_DIR.mkdir(parents=True, exist_ok=True)
        TRACK1_TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
        print(f"{mode}: ON")
        print(f"  window coverage : {TRACK1_LEDGER_DIR}")
        print(f"  slot timing     : {TRACK1_TELEMETRY_DIR}")
        if track1_only:
            # Deliberately NOT "STOP_TRADING: present". Saying that here taught the reader
            # that the switch is what stops legacy, and it is not — it halts entries inside
            # the legacy runner, after the slot has spawned, connected and fetched.
            print("  legacy strategy : NOT SCHEDULED (45 jobs omitted, not merely halted)")
            # Stage 5O split the safety net; this line said "safety sweeps still run against
            # live_positions.json — Stage 5O" until 5P cleanup, which was true before 5O and
            # false after it. Unqualified "safety sweeps" is the whole defect: there are two
            # sets now, watching two books, and an operator who reads the old sentence
            # believes a Track 1 position would be unprotected.
            print(f"  track1 safety   : {track1_safety_count()} jobs watching "
                  f"{_t1_const('TRACK1_POSITIONS_PATH')}")
            print(f"                    (own lock {_t1_const('TRACK1_LOCK_PATH')}, own "
                  f"max-hold marker, clientId "
                  f"{_t1_const('TRACK1_SAFETY_CLIENT_ID')})")
            print("  legacy safety   : still scheduled, watching live_positions.json — the")
            print("                    DRAIN. It protects positions still open in the legacy")
            print("                    book; it is not Track 1's safety net.")
            print("  swing provider  : ibkr by default in this mode")
        else:
            print("  legacy strategy : STILL SCHEDULED. STOP_TRADING halts its ENTRIES only —")
            print("                    each slot still spawns, connects and fetches first.")
            print("                    For a clean session use --track1-only-shadow.")
        print(f"  {TRACK1_ORDERS_ENV:15s} : removed from the child environment")
        # Stage 5ZZN. This said "B1 open and no confirmation file", and after the operator
        # signed on 2026-08-27 both halves of that were false while it went on printing.
        # A sentence that names WHICH blockers is a sentence that goes stale every time one
        # closes; it now asks the registry, which is the only thing that can answer without
        # drifting.
        _possible, _why = orders_would_be_possible()
        if _possible:
            print("  orders          : POSSIBLE — every blocker is clear")
        else:
            _ids = ", ".join(w.split(":", 1)[0] for w in _why) or "unknown"
            print(f"  orders          : impossible — blocked by {_ids}")

    # `restart --no-scheduler` is the ONLY way an operator says "leave the scheduler running
    # and rebuild the backend". `up` also arrives here with restart_scheduler False, so the
    # subcommand label is what separates the two: under `up` the operator never said it, and
    # the Track 1 refusal below still has to fire.
    _explicit_no_scheduler = (getattr(args, "label", None) == "restart"
                              and not args.restart_scheduler)

    # The scheduler is only replaced when explicitly asked. Leaving a healthy one alone is
    # the whole reason `up` is safe to run mid-session.
    if args.restart_scheduler:
        if not ensure_single("scheduler", SCHEDULER_PATTERN, assume_yes=assume_yes):
            return 2
        # Children outlive the parent. An orphaned run_live_day keeps clientId=1, so the
        # scheduler we are about to start meets a competitor it has no record of.
        orphans = stop_runners()
        if orphans:
            print(f"runner: stopped orphaned run_live_day {orphans}")
            _ops_log(f"runner: stopped orphans {orphans}")
        scheduler_pid = start_scheduler(
            args.ibkr_port,
            shadow_resume=not args.no_shadow_resume,
            assume_preflight_ok=args.assume_preflight_ok,
            track1_shadow=track1_shadow,
            track1_only=track1_only,
        )
        print(f"scheduler=started pid {scheduler_pid}")
    else:
        scan = scan_processes(SCHEDULER_PATTERN)
        if not scan.ok:
            print(f"scheduler: REFUSING to start - cannot determine running processes ({scan.error})")
            _ops_log(f"scheduler: scan failed ({scan.error}) -> refuse")
            return 2
        if len(scan.processes) > 1:
            print(f"scheduler: {len(scan.processes)} processes already running - this is the "
                  "duplicate-slot condition; stop the extras with 'ops.py restart --scheduler'")
            print(_describe(scan))
            _ops_log(f"scheduler: found duplicates {scan.pids} -> refuse")
            return 2
        if scan.processes:
            # Say the age, not just "running". A scheduler older than the cron it is
            # meant to be running is invisible otherwise — that is exactly how the
            # Sunday sweep went missing for a week.
            print(describe_scheduler_state(scheduler_processes()))
            if track1_shadow and not _explicit_no_scheduler:
                # `up` leaves a healthy scheduler alone, which is what makes it safe to run
                # mid-session — but it means --track1-shadow would have printed its whole
                # banner and changed NOTHING, because the flag only reaches a scheduler that
                # is actually started. Refused rather than ignored: an operator who believes
                # the shadow route is collecting when it is not would wait days for evidence
                # that was never being written.
                #
                # `restart --no-scheduler` is the one case this must NOT refuse, and only
                # since 2026-08-24. The operator has said in as many words to leave the
                # scheduler alone, and the flag now has a real effect without it: it is what
                # tells the BACKEND which slot table to mirror. Refusing here left no way at
                # all to correct a dashboard that was mirroring the wrong route, short of
                # restarting a live scheduler — which is the more dangerous of the two acts.
                _flag = "--track1-only-shadow" if track1_only else "--track1-shadow"
                print(f"track1: REFUSING — a scheduler is already running and `up` does "
                      f"not replace it, so {_flag} would have had no effect.")
                print(f"  use: python monitor/ops.py restart --scheduler {_flag}")
                _ops_log("track1: refused, scheduler already running under `up`")
                return 2
        else:
            # The second place a scheduler is actually started, and it starts in legacy/default
            # mode — note the call below passes no Track 1 flag. `up` with nothing running
            # reaches here, and so does `restart --no-scheduler` when there is no scheduler to
            # leave alone. Both would register the 45 legacy entry jobs, so both are refused.
            #
            # Nothing has been stopped on this path, so checking here rather than earlier costs
            # the operator nothing.
            if _refuse_legacy_start("legacy/default"):
                return 2
            scheduler_pid = start_scheduler(
                args.ibkr_port,
                shadow_resume=not args.no_shadow_resume,
                assume_preflight_ok=args.assume_preflight_ok,
            )
            print(f"scheduler=started pid {scheduler_pid}")

    if not ensure_single("backend", BACKEND_PATTERN, assume_yes=assume_yes):
        return 2
    # The backend child must be told the SAME fact the scheduler was told, or the
    # dashboard mirrors a route that is not running. `track1_shadow` is already true
    # whenever `track1_only` is, so passing both is not a double negative.
    backend_pid = start_backend(args.ibkr_port, args.api_port,
                                track1_shadow=track1_shadow, track1_only=track1_only)
    print(f"backend=started pid {backend_pid}")
    connection = wait_backend(args.api_port)
    if connection and connection.get("connected") is True:
        print("broker=connected")
    else:
        print(f"broker=not ready yet ({json.dumps(connection, ensure_ascii=False) if connection else 'no response'})")
        print(f"check log: {LOG_DIR / 'ops_backend.out.log'}")
    print(f"realtime=http://127.0.0.1:{args.api_port}/realtime")
    print(f"paper=http://127.0.0.1:{args.api_port}/paper")
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    backend = stop_backend(args.api_port)
    scheduler = stop_scheduler() if args.scheduler else []
    print(f"stopped_backend={backend or 'none'}")
    if args.scheduler:
        print(f"stopped_scheduler={scheduler or 'none'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One-command RAITS paper ops launcher")
    parser.add_argument("--ibkr-port", type=int, default=DEFAULT_IBKR_PORT)
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="start scheduler if needed and replace backend")
    up.add_argument("--restart-scheduler", action="store_true", help="also stop and restart run_scheduler")
    up.add_argument("--no-shadow-resume", action="store_true", help="start scheduler without --shadow-resume")
    up.add_argument("--yes", action="store_true", help="stop running instances without asking (for unattended runs)")
    up.add_argument("--assume-preflight-ok", action="store_true", help="pass through run_scheduler --assume-preflight-ok")
    up.add_argument("--track1-shadow", action="store_true",
                    help=f"start the scheduler in Track 1 SHADOW mode: adds the {track1_slot_count()} Track 1 slots, points the window-ledger and telemetry at global_index/track1_runtime, and removes TRACK1_ORDERS_APPROVED from the child. Refuses unless STOP_TRADING exists and track1_go_live_confirmation.json does not. Places no orders.")
    up.add_argument("--track1-only-shadow", action="store_true",
                    help=f"start the scheduler in TRACK 1-ONLY shadow mode: the {track1_slot_count()} Track 1 slots (all four sleeves) are registered and the legacy STRATEGY jobs are NOT. This is the clean validation path. It does not require STOP_TRADING, because there are no legacy entry jobs for it to halt. Track 1 gets its OWN safety net ({track1_safety_count()} jobs on live_positions.track1.json); the legacy safety jobs stay registered on live_positions.json to drain any position still open in the legacy book. Places no orders.")
    up.set_defaults(func=cmd_up)

    # `restart` means restart. It used to default to backend-only, and the scheduler
    # half was so quiet that 21 restarts over three days all left a scheduler running
    # code from before the cron table changed. `up` keeps the safe behaviour.
    restart = sub.add_parser("restart", help="replace scheduler, its run_live_day children, and backend")
    restart.add_argument("--scheduler", dest="restart_scheduler", action="store_true",
                         help="(default) stop and restart run_scheduler")
    restart.add_argument("--no-scheduler", dest="restart_scheduler", action="store_false",
                         help="leave a running scheduler alone; its age is printed instead")
    restart.add_argument("--no-shadow-resume", action="store_true", help="start scheduler without --shadow-resume")
    restart.add_argument("--yes", action="store_true", help="stop running instances without asking (for unattended runs)")
    restart.add_argument("--assume-preflight-ok", action="store_true", help="pass through run_scheduler --assume-preflight-ok")
    restart.add_argument("--track1-shadow", action="store_true",
                    help=f"start the scheduler in Track 1 SHADOW mode: adds the {track1_slot_count()} Track 1 slots, points the window-ledger and telemetry at global_index/track1_runtime, and removes TRACK1_ORDERS_APPROVED from the child. Refuses unless STOP_TRADING exists and track1_go_live_confirmation.json does not. Places no orders.")
    restart.add_argument("--track1-only-shadow", action="store_true",
                    help=f"start the scheduler in TRACK 1-ONLY shadow mode: the {track1_slot_count()} Track 1 slots (all four sleeves) are registered and the legacy STRATEGY jobs are NOT. This is the clean validation path. It does not require STOP_TRADING, because there are no legacy entry jobs for it to halt. Track 1 gets its OWN safety net ({track1_safety_count()} jobs on live_positions.track1.json); the legacy safety jobs stay registered on live_positions.json to drain any position still open in the legacy book. Places no orders.")
    restart.set_defaults(func=cmd_up, restart_scheduler=True, label="restart")

    status = sub.add_parser("status", help="show scheduler/backend/API status")
    status.set_defaults(func=lambda args: (print_status(args.api_port), 0)[1])

    down = sub.add_parser("down", help="stop backend; add --scheduler to stop scheduler too")
    down.add_argument("--scheduler", action="store_true")
    down.set_defaults(func=cmd_down)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
