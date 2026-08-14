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
from typing import Any, Callable

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


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    return env


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


def scan_processes(pattern: str) -> ProcessScan:
    """Enumerate matching processes, or report honestly that we could not.

    The script always prints a JSON array, so empty output can only mean the probe itself
    failed — there is no longer an innocent reading of silence.
    """
    script = (
        "$ErrorActionPreference='Stop'; "
        "try { $p = @(Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -match '{pattern}' }} | "
        "Select-Object ProcessId, CommandLine, "
        "@{n='Started';e={$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss')}}); "
        "ConvertTo-Json -Depth 3 -InputObject $p -Compress } "
        "catch { Write-Error $_.Exception.Message; exit 1 }"
    )
    try:
        result = _run(["powershell.exe", "-NoProfile", "-Command", script], timeout=20)
    except subprocess.TimeoutExpired:
        return ProcessScan(ok=False, error="process probe timed out after 20s")
    except OSError as exc:
        return ProcessScan(ok=False, error=f"process probe could not run ({exc})")
    if result.returncode != 0:
        return ProcessScan(ok=False, error=(result.stderr or "").strip()[:200] or
                           f"powershell exited {result.returncode}")
    text = result.stdout.strip()
    if not text:
        return ProcessScan(ok=False, error="process probe returned no output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ProcessScan(ok=False, error=f"process probe output was not JSON ({exc})")
    if isinstance(data, dict):
        data = [data]
    return ProcessScan(ok=True, processes=[
        RunningProcess(pid=int(item["ProcessId"]),
                       command=str(item.get("CommandLine") or ""),
                       started=str(item.get("Started") or "unknown"))
        for item in data if isinstance(item, dict) and item.get("ProcessId")
    ])


def scheduler_processes() -> list[dict[str, Any]]:
    scan = scan_processes(SCHEDULER_PATTERN)
    return [{"pid": item.pid, "command": item.command} for item in scan.processes]


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


def start_scheduler(ibkr_port: int, *, shadow_resume: bool, assume_preflight_ok: bool) -> int | None:
    existing = scheduler_processes()
    if existing:
        return None
    args = [_pythonw(), "-m", "global_index.run_scheduler", "--port", str(ibkr_port)]
    if shadow_resume:
        args.append("--shadow-resume")
    if assume_preflight_ok:
        args.append("--assume-preflight-ok")
    err = _open_log("ops_scheduler.err.log")
    proc = subprocess.Popen(
        args,
        cwd=str(ROOT),
        env=_env(),
        stdout=subprocess.DEVNULL,
        stderr=err,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    return proc.pid


def start_backend(ibkr_port: int, api_port: int) -> int:
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
        env=_env(),
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


def print_status(api_port: int) -> None:
    listeners = backend_listener_pids(api_port)
    connection = _get_json(f"http://127.0.0.1:{api_port}/api/connection")
    broker = _get_json(f"http://127.0.0.1:{api_port}/api/v1/broker")
    print(f"backend_port={api_port} listeners={listeners or 'none'}")
    for kind, pattern in (("scheduler", SCHEDULER_PATTERN), ("backend", BACKEND_PATTERN)):
        scan = scan_processes(pattern)
        if not scan.ok:
            print(f"{kind}_pids=UNKNOWN ({scan.error})")
        elif len(scan.processes) > 1:
            # Say it in the same words as the incident it causes, not as a bare count.
            print(f"{kind}_pids={scan.pids}  DUPLICATE - every slot fires once per process")
            print(_describe(scan))
        else:
            print(f"{kind}_pids={scan.pids or 'none'}")
    print(f"connection={json.dumps(connection, ensure_ascii=False) if connection else 'unavailable'}")
    if broker:
        print(f"broker_connected={broker.get('connected')} freshness={broker.get('freshness')} age_seconds={broker.get('age_seconds')}")


def cmd_up(args: argparse.Namespace) -> int:
    label = getattr(args, "label", "up")
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] RAITS ops {label}")
    assume_yes = getattr(args, "yes", False)

    # The scheduler is only replaced when explicitly asked. Leaving a healthy one alone is
    # the whole reason `up` is safe to run mid-session.
    if args.restart_scheduler:
        if not ensure_single("scheduler", SCHEDULER_PATTERN, assume_yes=assume_yes):
            return 2
        scheduler_pid = start_scheduler(
            args.ibkr_port,
            shadow_resume=not args.no_shadow_resume,
            assume_preflight_ok=args.assume_preflight_ok,
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
            print(f"scheduler=already running pid {scan.pids[0]}")
        else:
            scheduler_pid = start_scheduler(
                args.ibkr_port,
                shadow_resume=not args.no_shadow_resume,
                assume_preflight_ok=args.assume_preflight_ok,
            )
            print(f"scheduler=started pid {scheduler_pid}")

    if not ensure_single("backend", BACKEND_PATTERN, assume_yes=assume_yes):
        return 2
    backend_pid = start_backend(args.ibkr_port, args.api_port)
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
    up.set_defaults(func=cmd_up)

    restart = sub.add_parser("restart", help="replace backend; add --scheduler to also restart run_scheduler")
    restart.add_argument("--scheduler", dest="restart_scheduler", action="store_true", help="also stop and restart run_scheduler")
    restart.add_argument("--no-shadow-resume", action="store_true", help="start scheduler without --shadow-resume")
    restart.add_argument("--yes", action="store_true", help="stop running instances without asking (for unattended runs)")
    restart.add_argument("--assume-preflight-ok", action="store_true", help="pass through run_scheduler --assume-preflight-ok")
    restart.set_defaults(func=cmd_up, restart_scheduler=False, label="restart")

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
