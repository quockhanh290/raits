"""Stage 5ZZ — `ops.py status` must be a health check somebody can trust.

The defect this exists for, measured rather than described: when the process probe failed, the
reason recorded was `stderr[:200]`, and PowerShell's default error rendering ECHOES THE WHOLE
COMMAND before the message. On a deliberately broken probe the stderr was 692 characters, the
first 200 were entirely the script's own opening, and the words that mattered — "Invalid class"
— sat at the very end. So the operator saw `UNKNOWN (` followed by their own script, which is an
UNKNOWN with no reason wearing a costume.

Nothing here starts, kills, or connects to anything. Every probe is replaced.
"""
from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "monitor"))
import ops  # noqa: E402


class _Result:
    """What `subprocess.run` hands back, in the shape `scan_processes` reads."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _row(pid, cmd="pythonw.exe -m global_index.run_scheduler --track1-only-shadow"):
    return ('{"ProcessId": %d, "CommandLine": "%s", "Started": "2026-08-27 02:08:09"}'
            % (pid, cmd))


def _ok(*rows):
    return _Result(0, "[" + ",".join(rows) + "]", "")


# The real thing a failing PowerShell writes: the command, echoed, then the message.
POWERSHELL_ECHO_FAILURE = (
    "$ErrorActionPreference='Stop'; try { $p = @(Get-CimInstance Win32_Process | Where-Object "
    "{ $_.ProcessId -ne $PID -and $_.CommandLine -match 'global_index\\.run_scheduler' } | "
    "Select-Object ProcessId, CommandLine, @{n='Started';e={$_.CreationDate.ToString('yyyy-MM-"
    "dd HH:mm:ss')}}); ConvertTo-Json -Depth 3 -InputObject $p -Compress } catch { Write-Error "
    "$_.Exception.Message; exit 1 }\n : Access is denied."
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1-3  a scan that worked
# ═══════════════════════════════════════════════════════════════════════════════

def test_1_a_successful_scheduler_scan_reports_pids_and_its_source(monkeypatch):
    monkeypatch.setattr(ops, "_run", lambda *a, **k: _ok(_row(5856)))
    scan = ops.scheduler_scan()
    assert scan.ok and scan.pids == [5856] and scan.code == ops.SCAN_OK
    out = _status_text(monkeypatch, sched=_ok(_row(5856)), backend=_ok(_row(2108)))
    assert "scheduler_pids=[5856] source=process_table" in out
    assert "backend_pids=[2108] source=process_table" in out


def test_2_a_successful_empty_scan_is_none_not_unknown(monkeypatch):
    """An empty result from a probe that RAN is a real answer and must read as one."""
    monkeypatch.setattr(ops, "_run", lambda *a, **k: _Result(0, "[]", ""))
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    assert scan.ok and scan.pids == [] and scan.code == ops.SCAN_OK
    out = _status_text(monkeypatch, sched=_Result(0, "[]", ""), backend=_ok(_row(2108)))
    assert "scheduler_pids=none source=process_table" in out
    assert "unknown_due_to_process_scan_error" not in out


def test_3_duplicates_are_still_called_duplicates(monkeypatch):
    out = _status_text(monkeypatch, sched=_ok(_row(1), _row(2)), backend=_ok(_row(2108)))
    assert "DUPLICATE" in out and "source=process_table" in out


# ═══════════════════════════════════════════════════════════════════════════════
# 4-7  a scan that could not run
# ═══════════════════════════════════════════════════════════════════════════════

def test_4_the_recorded_reason_is_the_message_and_not_the_echoed_script(monkeypatch):
    """The whole defect, in one assertion."""
    monkeypatch.setattr(ops, "_run",
                        lambda *a, **k: _Result(1, "", POWERSHELL_ECHO_FAILURE))
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    assert not scan.ok
    assert scan.error == "Access is denied."
    assert "ErrorActionPreference" not in (scan.error or ""), \
        "the recorded reason is the script the probe echoed back, not what went wrong"
    assert scan.code == ops.SCAN_PERMISSION_DENIED


def test_5_the_marked_message_is_preferred_when_present(monkeypatch):
    marked = f"noise before\n{ops.SCAN_ERROR_MARKER}Invalid class\nnoise after"
    monkeypatch.setattr(ops, "_run", lambda *a, **k: _Result(1, "", marked))
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    assert scan.error == "Invalid class"
    assert scan.code == ops.SCAN_FAILED


#: Exactly what PowerShell writes, copied from a real failing probe on this host: the command
#: echoed and wrapped, the message split across two lines, then the position marker and the
#: decoration. The last line is the exception's CLASS NAME, which is why "take the last line"
#: is not good enough either.
REAL_POWERSHELL_STDERR = "\n".join([
    "$ErrorActionPreference='Stop'; try { $p = @(Get-CimInstance Win32_ProcessDoesNotExist "
    "| Where-Object { $_.ProcessId ",
    "-ne $PID }); ConvertTo-Json -InputObject $p -Compress } catch { Write-Error "
    "$_.Exception.Message; exit 1 } : Invalid ",
    "class ",
    "At line:1 char:181",
    "+ ... bject $p -Compress } catch { Write-Error $_.Exception.Message; exit 1 ...",
    "+                                  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~",
    "    + CategoryInfo          : NotSpecified: (:) [Write-Error], WriteErrorException",
    "    + FullyQualifiedErrorId : Microsoft.PowerShell.Commands.WriteErrorException",
    "",
])


def test_6b_the_real_wrapped_rendering_yields_the_message(monkeypatch):
    """The fallback path, against output copied from a genuine failing probe.

    Three wrong answers are available here and the test names all three: the first 200
    characters are the command, the last line is an exception class name, and the message
    itself is split across two lines by PowerShell's wrapping.
    """
    monkeypatch.setattr(ops, "_run", lambda *a, **k: _Result(1, "", REAL_POWERSHELL_STDERR))
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    assert not scan.ok
    assert scan.error == "Invalid class", scan.error
    assert "ErrorActionPreference" not in scan.error
    assert "WriteErrorException" not in scan.error


@pytest.mark.parametrize("result,code", [
    (_Result(0, "", ""), "probe_no_output"),
    (_Result(0, "not json at all", ""), "probe_not_json"),
])
def test_6_each_way_of_failing_gets_its_own_code(monkeypatch, result, code):
    monkeypatch.setattr(ops, "_run", lambda *a, **k: result)
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    assert not scan.ok and scan.code == code and scan.error


def test_7_a_raising_probe_is_unknown_and_not_empty(monkeypatch):
    """A timeout and an OSError are the two ways the probe never returns at all."""
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=20)
    monkeypatch.setattr(ops, "_run", _boom)
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    assert not scan.ok and scan.code == ops.SCAN_TIMEOUT and scan.processes == []

    def _oserr(*a, **k):
        raise OSError("powershell.exe not found")
    monkeypatch.setattr(ops, "_run", _oserr)
    scan = ops.scan_processes(ops.SCHEDULER_PATTERN)
    assert not scan.ok and scan.code == ops.SCAN_UNAVAILABLE


# ═══════════════════════════════════════════════════════════════════════════════
# 8-10  what status prints when it could not look
# ═══════════════════════════════════════════════════════════════════════════════

def test_8_status_never_prints_a_bare_unknown(monkeypatch):
    out = _status_text(monkeypatch,
                       sched=_Result(1, "", POWERSHELL_ECHO_FAILURE),
                       backend=_Result(1, "", POWERSHELL_ECHO_FAILURE))
    assert "scheduler_pids=unknown_due_to_process_scan_error" in out
    assert "backend_pids=unknown_due_to_process_scan_error" in out
    assert "scheduler_process_scan=permission_denied: Access is denied." in out
    assert "backend_process_scan=permission_denied: Access is denied." in out
    # and the old shape is gone in both directions
    for line in out.splitlines():
        if "_pids=" in line and "unknown" in line:
            assert "UNKNOWN" not in line, line
    # Scoped to the PROCESS lines, which is what this test is about. The first version banned
    # the string `UNKNOWN (` from the whole output, and Stage 5ZZE added a paper-account line
    # that legitimately uses that shape with a real reason code behind it. A check that forbids
    # a spelling rather than the defect fails for something it is not about, and this project
    # already knows what that teaches a reader.
    process_lines = [ln for ln in out.splitlines() if "_pids=" in ln]
    assert process_lines, "no process line at all — this assertion would pass on silence"
    for ln in process_lines:
        assert "UNKNOWN (" not in ln, ln


def test_9_the_scheduler_fallback_is_labelled_and_never_claims_running(monkeypatch, tmp_path):
    log = tmp_path / "sched.err.log"
    log.write_text("2026-08-27 02:08:11  INFO  run_scheduler - "
                   "Track 1 SHADOW slots registered: 71 (no orders)\n", encoding="utf-8")
    monkeypatch.setattr(ops, "SCHEDULER_LOG", log)
    ev = ops.scheduler_log_evidence()
    assert ev["source"] == "log" and ev["last_registered_slots"] == 71
    assert ev["proves_running"] is False, \
        "a log line is a history; only a pid or a listener is a status"

    out = _status_text(monkeypatch, sched=_Result(1, "", POWERSHELL_ECHO_FAILURE),
                       backend=_Result(1, "", POWERSHELL_ECHO_FAILURE))
    assert "scheduler_fallback=last_registered_71_slots" in out
    assert "source=log" in out and "proves_running=False" in out
    # the machine's clock is named, because it is two hours from the market's
    assert "machine-local" in out


def test_10_the_backend_fallback_is_the_listener_and_says_so(monkeypatch):
    out = _status_text(monkeypatch, sched=_ok(_row(5856)),
                       backend=_Result(1, "", POWERSHELL_ECHO_FAILURE),
                       listeners=[2108])
    assert "backend_fallback=listeners:[2108] source=port_listener proves_running=True" in out


# ═══════════════════════════════════════════════════════════════════════════════
# 11-13  the mode, and the stale table
# ═══════════════════════════════════════════════════════════════════════════════

def test_11_a_failed_scan_makes_the_mode_unknown_and_never_off(monkeypatch):
    """The collapse this closes: an empty list reaching the mode as 'Track 1 is not running'."""
    monkeypatch.setattr(ops, "_run",
                        lambda *a, **k: _Result(1, "", POWERSHELL_ECHO_FAILURE))
    t = ops.track1_status()
    assert t["scheduler_running"] is None, "a failed probe reported a definite answer"
    assert t["scheduler_scan_ok"] is False
    assert t["scheduler_track1_only"] is None
    assert t["safety_routes"] is None

    out = _status_text(monkeypatch, sched=_Result(1, "", POWERSHELL_ECHO_FAILURE),
                       backend=_ok(_row(2108)))
    assert "track1_mode=unknown" in out
    assert "track1_mode=n/a" not in out


def test_12_a_stale_slot_table_is_named_and_a_fresh_one_is_not(monkeypatch, tmp_path):
    """The 70-vs-71 case Stage 5ZY-PRE had to find by hand."""
    from global_index import track1_slots as t1

    n = len(t1.TRACK1_SLOTS)
    assert n > 0, "no slots at all — this test would pass on an empty table"

    stale = tmp_path / "stale.log"
    stale.write_text(f"2026-08-26 20:07:39  INFO  x - "
                     f"Track 1 SHADOW slots registered: {n - 1} (no orders)\n", encoding="utf-8")
    monkeypatch.setattr(ops, "SCHEDULER_LOG", stale)
    f = ops.slot_table_freshness()
    assert f["state"] == "stale"
    assert f["registered_slots"] == n - 1 and f["source_slots"] == n
    assert "restart" in f["detail"].lower()

    fresh = tmp_path / "fresh.log"
    fresh.write_text(f"2026-08-27 02:08:11  INFO  x - "
                     f"Track 1 SHADOW slots registered: {n} (no orders)\n", encoding="utf-8")
    monkeypatch.setattr(ops, "SCHEDULER_LOG", fresh)
    assert ops.slot_table_freshness()["state"] == "fresh"


def test_13_a_stale_table_reaches_the_printed_status(monkeypatch, tmp_path):
    from global_index import track1_slots as t1

    log = tmp_path / "stale.log"
    log.write_text(f"2026-08-26 20:07:39  INFO  x - Track 1 SHADOW slots registered: "
                   f"{len(t1.TRACK1_SLOTS) - 1}\n", encoding="utf-8")
    monkeypatch.setattr(ops, "SCHEDULER_LOG", log)
    out = _status_text(monkeypatch, sched=_ok(_row(5856)), backend=_ok(_row(2108)))
    assert "track1_slot_table=stale" in out
    assert "RESTART NEEDED" in out


def test_14_an_unreadable_log_is_unknown_not_fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(ops, "SCHEDULER_LOG", tmp_path / "does_not_exist.log")
    ev = ops.scheduler_log_evidence()
    assert ev["readable"] is False and ev["last_registered_slots"] is None
    f = ops.slot_table_freshness()
    assert f["state"] == "unknown", "an unreadable log was reported as agreement"
    assert f["state"] != "fresh"


def test_15_the_probe_does_not_count_itself(monkeypatch):
    """The pattern is embedded in the probe's own command line, so without an exclusion any
    pattern lacking a regex escape matches the process doing the searching — and
    `ensure_single` decides whether to KILL from this same scan."""
    import inspect

    src = inspect.getsource(ops.scan_processes)
    assert "$_.ProcessId -ne $PID" in src, "the probe can count itself"
    # and both production patterns are written so their own regex source cannot match them
    import re
    for name in ("SCHEDULER_PATTERN", "BACKEND_PATTERN", "RUNNER_PATTERN"):
        pat = getattr(ops, name)
        assert not re.search(pat, pat), \
            f"{name} matches its own source text; the probe would find whoever is searching"


# ═══════════════════════════════════════════════════════════════════════════════
# mutations
# ═══════════════════════════════════════════════════════════════════════════════

def _must_fail(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except AssertionError:
        return True
    return False


def test_M1_scan_raises_mutation(monkeypatch):
    """Collapse: an exception in the probe read as 'nothing is running'."""
    monkeypatch.setattr(ops, "scan_processes",
                        lambda pattern: ops.ProcessScan(ok=True, processes=[]))
    assert _must_fail(test_11_a_failed_scan_makes_the_mode_unknown_and_never_off,
                      monkeypatch), \
        "test_11 stayed green while a failed probe was reported as a definite empty scan"


def test_M2_bare_unknown_mutation(monkeypatch):
    """Collapse: the printer goes back to a bare UNKNOWN."""
    real = ops.print_status

    def _old_shape(api_port):
        print("scheduler_pids=UNKNOWN ()")
        print("backend_pids=UNKNOWN ()")
    monkeypatch.setattr(ops, "print_status", _old_shape)
    assert _must_fail(test_8_status_never_prints_a_bare_unknown, monkeypatch), \
        "test_8 stayed green while status printed a bare UNKNOWN"
    monkeypatch.setattr(ops, "print_status", real)


def test_M3_error_text_takes_the_script_again_mutation(monkeypatch):
    """Collapse: the reason reverts to the first 200 characters of stderr."""
    monkeypatch.setattr(ops, "_scan_error_text",
                        lambda stderr, rc: (stderr or "").strip()[:200])
    assert _must_fail(test_4_the_recorded_reason_is_the_message_and_not_the_echoed_script,
                      monkeypatch), \
        "test_4 stayed green while the reason was the echoed script again"


def test_M4_stale_table_reported_fresh_mutation(monkeypatch, tmp_path):
    """Collapse: source 71, log 70, reported as agreement."""
    monkeypatch.setattr(ops, "slot_table_freshness",
                        lambda *a, **k: {"state": "fresh", "source_slots": 71,
                                               "registered_slots": 70, "detail": "mutated"})
    assert _must_fail(test_13_a_stale_table_reaches_the_printed_status,
                      monkeypatch, tmp_path), \
        "test_13 stayed green while a 70-against-71 table was called fresh"


def test_M5_fallback_claims_running_mutation(monkeypatch, tmp_path):
    """Collapse: a log line promoted to proof that the scheduler is up."""
    real = ops.scheduler_log_evidence
    monkeypatch.setattr(ops, "scheduler_log_evidence",
                        lambda path=None: dict(real(path), proves_running=True))
    assert _must_fail(test_9_the_scheduler_fallback_is_labelled_and_never_claims_running,
                      monkeypatch, tmp_path), \
        "test_9 stayed green while a log line claimed the process was running"


# ═══════════════════════════════════════════════════════════════════════════════

def _status_text(monkeypatch, *, sched, backend, listeners=None):
    """`print_status` with every probe replaced. Connects to nothing."""
    calls = {"n": 0}

    def _fake_run(cmd, timeout=None):
        script = " ".join(cmd)
        return sched if ops.SCHEDULER_PATTERN in script else backend

    monkeypatch.setattr(ops, "_run", _fake_run)
    monkeypatch.setattr(ops, "backend_listener_pids", lambda port: listeners or [])
    monkeypatch.setattr(ops, "_get_json", lambda url: None)
    buf = io.StringIO()
    with redirect_stdout(buf):
        ops.print_status(5002)
    assert calls is not None
    text = buf.getvalue()
    assert text.strip(), "status printed nothing — this helper would pass on silence"
    return text
