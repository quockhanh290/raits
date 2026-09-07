"""global_index/slot_telemetry.py — runtime/slot/route observability. ADDITIVE ONLY.

Why this exists
---------------
The shadow-resume timing audit (2026-08-22) could only recover slot runtime by parsing
APScheduler's own INFO lines, and could not split a run into phases at all: there is no
timing marker anywhere in `live_day_*.log`. It also had to separate real runs from
no-op runs (pre-flight skip, mutex skip) by thresholding at ~0 seconds, because both
emit an identical Running/executed pair — 76 such pairs had to be filtered that way.
This module closes both gaps.

Design constraints it is built to satisfy
-----------------------------------------
* **Off by default.** Nothing is written unless `RAITS_TELEMETRY_DIR` is set in the
  environment. With it unset every function here is a no-op, so an unflagged run is
  byte-identical to before this module existed.
* **Never raises.** Every filesystem touch is wrapped. A telemetry failure disables the
  channel for the process and never propagates into a trading path.
* **Never decides anything.** Nothing here is read by the engine, the guard, the runner
  or the broker. It only measures.
* **One record per slot.** No per-bar or per-order lines. A full trading day writes
  roughly seventy lines.

Environment
-----------
`RAITS_TELEMETRY_DIR`  directory for `slot_timing_YYYYMMDD.jsonl`. Unset → disabled.
`RAITS_SLOT_ID`        e.g. `LIVE_DAY_1410`. Unset → `""`.
`RAITS_ROUTE`          e.g. `legacy`. Unset → `legacy`.

Record shape (one JSON object per line)
---------------------------------------
    ts            UTC ISO seconds, when the record was written
    route         "legacy" unless RAITS_ROUTE says otherwise
    slot_id       from RAITS_SLOT_ID
    pid
    outcome       "ok" | "error" | "dry_run" | "print_signals" | "lock_held"
                  | "incomplete" | "skipped_mutex" | "skipped_preflight"
    runtime_s     wall clock from begin() to emit(), measured by the process itself
    phases        {phase_name: seconds}, only phases that actually ran
    plus whatever mark() recorded (scalars only)
"""
from __future__ import annotations

import atexit
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

_ENV_DIR = "RAITS_TELEMETRY_DIR"
_ENV_SLOT = "RAITS_SLOT_ID"
_ENV_ROUTE = "RAITS_ROUTE"

_state: dict = {"t0": None, "last": None, "phases": {}, "marks": {},
                "outcome": "incomplete", "outcome_sticky": False, "emitted": False}
_disabled = False


def route() -> str:
    return os.environ.get(_ENV_ROUTE) or "legacy"


def slot_id() -> str:
    return os.environ.get(_ENV_SLOT) or ""


def _dir():
    d = os.environ.get(_ENV_DIR)
    if not d or _disabled:
        return None
    try:
        p = Path(d)
        return p if p.is_dir() else None
    except Exception:
        return None


def enabled() -> bool:
    return _dir() is not None


def begin() -> None:
    """Mark process start. Safe when disabled; safe to call twice.

    Registers an atexit net so a record is written on EVERY exit path, including ones
    that return early or raise. Without it the paths that matter most for diagnosing a
    slow day — the ones that failed — would be the ones with no record.
    """
    now = time.monotonic()
    _state["t0"] = now
    _state["last"] = now
    _state["phases"] = {}
    _state["marks"] = {}
    _state["outcome"] = "incomplete"
    _state["outcome_sticky"] = False
    _state["emitted"] = False
    try:
        atexit.register(_atexit_emit)
    except Exception:
        pass


def set_outcome(name: str, *, sticky: bool = False, force: bool = False) -> None:
    """Declare how this run ended. The atexit net writes whatever stands at exit.

    Three cases, because "last writer wins" gets two of them wrong:

    * plain — the ordinary success path. `ok` is set this way.
    * ``sticky=True`` — a MODE that later success must not erase. A dry run still
      executes run_day and would otherwise finish as `ok`, hiding that no order could
      ever have been sent. Same for `print_signals` and `lock_held`.
    * ``force=True`` — an error overrides anything, sticky included, because a run that
      raised did not end the way any earlier line claimed it would.
    """
    if _state.get("outcome_sticky") and not force:
        return
    _state["outcome"] = str(name)
    _state["outcome_sticky"] = bool(sticky) or bool(force)


def _atexit_emit() -> None:
    if not _state.get("emitted"):
        emit(str(_state.get("outcome") or "incomplete"))


def split(name: str) -> None:
    """Close the current phase and open the next.

    One added line per boundary, deliberately: a context manager would mean
    re-indenting existing blocks, and a telemetry change must not move trading code.
    """
    if _state["last"] is None:
        return
    now = time.monotonic()
    try:
        _state["phases"][name] = round(
            _state["phases"].get(name, 0.0) + (now - _state["last"]), 3)
    except Exception:
        pass
    _state["last"] = now


def add(name: str, seconds: float) -> None:
    """Accumulate into a phase measured by the caller — for work nested inside another
    phase, such as the shadow replay inside run_day."""
    try:
        _state["phases"][name] = round(
            _state["phases"].get(name, 0.0) + float(seconds), 3)
    except Exception:
        pass


class timer:
    """`with telemetry.timer("shadow"):` — accumulates into a named phase without
    disturbing the split() sequence around it."""

    def __init__(self, name: str):
        self.name = name
        self._t = None

    def __enter__(self):
        self._t = time.monotonic()
        return self

    def __exit__(self, *exc):
        if self._t is not None:
            add(self.name, time.monotonic() - self._t)
        return False


def mark(key: str, value) -> None:
    """Attach a scalar to the record (counts, flags, reasons)."""
    try:
        if isinstance(value, (str, int, float, bool)) or value is None:
            _state["marks"][key] = value
    except Exception:
        pass


def _base(outcome: str, slot: str, runtime) -> dict:
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "route": route(),
        "slot_id": slot,
        "pid": os.getpid(),
        "outcome": outcome,
        "runtime_s": runtime,
        "phases": {},
    }


def emit(outcome: str, **extra) -> None:
    """Write the single record for this process. Never raises."""
    t0 = _state.get("t0")
    runtime = round(time.monotonic() - t0, 3) if t0 is not None else None
    rec = _base(outcome, slot_id(), runtime)
    rec["phases"] = dict(_state.get("phases") or {})
    rec.update(_state.get("marks") or {})
    for k, v in extra.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            rec[k] = v
    _state["emitted"] = True
    _write(rec)


def record_skip(slot: str, outcome: str, **extra) -> None:
    """A slot that never spawned a child still has to be distinguishable from one that
    ran and did nothing. Called by the scheduler, the only place that knows."""
    rec = _base(outcome, slot or slot_id(), 0.0)
    for k, v in extra.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            rec[k] = v
    _write(rec)


def _write(rec: dict) -> None:
    global _disabled
    d = _dir()
    if d is None:
        return
    try:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        line = json.dumps(rec, default=str, ensure_ascii=False) + "\n"
        with open(d / f"slot_timing_{day}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        # One failure disables the channel for this process. It must never escape.
        _disabled = True
