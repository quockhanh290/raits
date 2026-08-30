"""What would happen if this B1 decision were recorded — asked without recording it.

Stage 5ZQ measured the account flat and gave B1 a second half: it now opens on the operator's
recorded decision AND a passing measurement, rather than on the signature alone. This module
answers the question that sits between those two: *if I wrote this file, what would open?*

It is read-only in the strongest sense available — it has no code path that writes anything at
all, and a test asserts that by watching every file it opens. The confirmation file is written
by a person, never by a script, and that includes this one.

Why a preview is worth a module
-------------------------------
The confirmation file is a one-line commitment with a wide blast radius, and the operator
cannot see its effect until after writing it. Worse, the two decisions assert facts about the
world that the file then freezes:

    legacy_retired_confirmed      legacy has stopped trading; Track 1 is the sole route
    separate_account_confirmed    Track 1 runs on its own IBKR login

Measured on this machine, legacy is **dormant, not retired**: in `track1-only-shadow` the
scheduler registers zero legacy strategy jobs, and in the default mode it registers 45. The
difference is one command-line flag. So a recorded `legacy_retired_confirmed` is a claim that a
plain restart can falsify silently, while the gate goes on reading it as true.

This module says that out loud at the moment of decision, which is the only moment it helps.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from global_index import track1_b1 as _b1
from global_index import track1_gates as _g

SCHEMA = "track1_b1_decision/1"

#: The two mutually exclusive decisions. `b1_measurement_waived` is deliberately NOT here: it
#: is not a third decision, it is a way of taking one of these two without the proof.
DECISION_FLAGS = ("legacy_retired_confirmed", "separate_account_confirmed")

#: What the running scheduler can do about legacy entries. Three values, because "I could not
#: read the scheduler" must not read the same as "legacy cannot enter".
LEGACY_ENTRY_NONE = "none"
LEGACY_ENTRY_PRESENT = "present"
LEGACY_ENTRY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Preview:
    """What a decision file says, and what it would do, without it having been placed."""
    path: str
    exists: bool
    valid: bool
    errors: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    waiver: bool = False
    measurement_status: str = ""
    measurement_code: str = ""
    measurement_detail: str = ""
    measurement_checked_at: str = ""
    measurement_expires_at: str = ""
    would_release: list = field(default_factory=list)
    would_still_block: list = field(default_factory=list)
    would_orders_be_possible: bool = False
    legacy_entry_capability: str = LEGACY_ENTRY_UNKNOWN
    warnings: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"schema": SCHEMA, **asdict(self)}


def _legacy_entry_capability() -> tuple[str, str]:
    """Can the RUNNING scheduler open a legacy position? Three answers.

    Read from the running process's own command line rather than from a flag someone
    remembers passing — and `unknown` when the process list cannot be read, because a
    scheduler that cannot be seen is not a scheduler that is safe.
    """
    try:
        from monitor import ops

        procs = ops.scheduler_processes()
        if not procs:
            return LEGACY_ENTRY_UNKNOWN, ("no scheduler process could be read, so what it is "
                                          "registered to do cannot be established")
        cmdlines = ops.scheduler_command_lines(procs)
        if "--track1-only-shadow" in cmdlines:
            return LEGACY_ENTRY_NONE, ("the running scheduler is in track1-only-shadow, which "
                                       "registers no legacy strategy job")
        return LEGACY_ENTRY_PRESENT, ("the running scheduler is not in track1-only mode, so "
                                      "legacy entry jobs are registered")
    except Exception as exc:                                      # noqa: BLE001
        return LEGACY_ENTRY_UNKNOWN, f"the scheduler could not be inspected ({exc})"


def _expiry(checked_at: str, hours: int = _b1.MAX_RECORD_AGE_HOURS) -> str:
    try:
        when = _dt.datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    except Exception:                                             # noqa: BLE001
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    return (when + _dt.timedelta(hours=hours)).isoformat()


def preview(path: str | Path, root: str | Path = ".", *, now: Any = None) -> Preview:
    """Read a candidate decision file and report its effect. Writes nothing, anywhere."""
    p = Path(path)
    measurement = _b1.latest(root, now=now)
    expires = _expiry(measurement.checked_at)

    if not p.exists():
        return Preview(path=str(p), exists=False, valid=False,
                       errors=[f"{p} does not exist"],
                       measurement_status=measurement.status,
                       measurement_code=measurement.code,
                       measurement_detail=measurement.detail,
                       measurement_checked_at=measurement.checked_at,
                       measurement_expires_at=expires,
                       would_still_block=[b.id for b in _g.blocking(_g.NO_CONFIRMATIONS)],
                       legacy_entry_capability=_legacy_entry_capability()[0])

    conf, errors = _g.load_confirmations(p)
    decisions = [f for f in DECISION_FLAGS if conf.get(f)]
    waiver = conf.get("b1_measurement_waived")

    # Stage 5ZZK. The baseline is NOTHING SIGNED, stated explicitly.
    #
    # `blocking()` used to mean that implicitly; it now reads the confirmation file, so a
    # preview run while a valid decision is already in place compared the signed state
    # against itself and reported that the candidate would release nothing. The question a
    # preview answers is "what does THIS file grant", and that is measured from zero.
    blocking_now = [b.id for b in _g.blocking(_g.NO_CONFIRMATIONS)]
    blocking_after = [b.id for b in _g.blocking(conf)]
    released = [b for b in blocking_now if b not in blocking_after]

    warnings: list = []
    if errors:
        warnings.append("This file does not validate, so it grants NOTHING. A confirmation "
                        "that half-parses must never half-open a gate.")
    if len(decisions) > 1:
        warnings.append("Both decisions are set. They are mutually exclusive: either legacy "
                        "retires and Track 1 takes the existing account, or Track 1 gets its "
                        "own. Setting both says neither.")
    if not decisions and not errors:
        warnings.append("No decision is set, so B1 stays shut whatever the measurement says.")

    capability, capability_why = _legacy_entry_capability()
    if "legacy_retired_confirmed" in decisions:
        if capability == LEGACY_ENTRY_PRESENT:
            warnings.append("You are about to record that legacy has retired, and the running "
                            "scheduler still registers legacy entry jobs. " + capability_why)
        elif capability == LEGACY_ENTRY_NONE:
            warnings.append("Legacy is dormant because of a command-line flag, not because it "
                            "has been retired: a restart without --track1-only-shadow "
                            "registers its entry jobs again, and this recorded decision would "
                            "go on reading as true. Retiring legacy is the switch-over "
                            "runbook's ordered procedure, not this flag.")
        else:
            warnings.append("Whether legacy can still enter could not be established. "
                            + capability_why)
    if "separate_account_confirmed" in decisions:
        warnings.append("The account this system measures is the one the dashboard reader and "
                        "the safety jobs connect to. Nothing here has observed a SECOND "
                        "account, so this decision is not something the measurement can "
                        "corroborate.")
    if waiver and measurement.status == _b1.PASS:
        warnings.append("The waiver is set and the measurement passes, so the waiver is doing "
                        "nothing. Remove it rather than leaving a standing bypass in place.")
    if measurement.status != _b1.PASS and not waiver:
        warnings.append(f"The B1 measurement is {measurement.status}, so B1 stays shut even "
                        f"with a decision recorded. Re-run the audit.")

    return Preview(
        path=str(p), exists=True, valid=not errors, errors=list(errors),
        decisions=decisions, waiver=waiver,
        measurement_status=measurement.status, measurement_code=measurement.code,
        measurement_detail=measurement.detail,
        measurement_checked_at=measurement.checked_at, measurement_expires_at=expires,
        would_release=released, would_still_block=blocking_after,
        would_orders_be_possible=_g.may_enable_orders(conf)[0],
        legacy_entry_capability=capability, warnings=warnings)


def render(pv: Preview) -> str:
    """The preview as an operator reads it. Plain sentences; identifiers only where they are
    the thing being written into a file."""
    out = [f"B1 decision preview — {pv.path}", "=" * 72]
    if not pv.exists:
        out.append("  the file does not exist; nothing to preview")
    else:
        out.append(f"  validates      : {'yes' if pv.valid else 'NO — grants nothing'}")
        for e in pv.errors:
            out.append(f"                   - {e}")
        out.append(f"  decision       : {', '.join(pv.decisions) or 'none set'}")
        out.append(f"  waiver         : {'set' if pv.waiver else 'not set'}")
    out.append("")
    out.append(f"  B1 measurement : {pv.measurement_status} ({pv.measurement_code})")
    if pv.measurement_checked_at:
        out.append(f"                   observed {pv.measurement_checked_at}")
        out.append(f"                   counts until {pv.measurement_expires_at}")
    out.append(f"  legacy entries : {pv.legacy_entry_capability}")
    out.append("")
    out.append(f"  would release  : {', '.join(pv.would_release) or 'nothing'}")
    out.append(f"  would still block: {', '.join(pv.would_still_block) or 'nothing'}")
    out.append(f"  orders possible: {pv.would_orders_be_possible}")
    if pv.warnings:
        out.append("")
        out.append("  read before writing:")
        for w in pv.warnings:
            out.append(f"    * {w}")
    return "\n".join(out)


def build_parser():
    import argparse

    ap = argparse.ArgumentParser(
        description="Preview a B1 decision file without recording it. Writes nothing.")
    ap.add_argument("path", help="the candidate decision file (e.g. a scratch template)")
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    return ap


def main(argv: "list | None" = None) -> int:
    a = build_parser().parse_args(argv)
    pv = preview(a.path, a.root)
    print(render(pv))
    if a.json:
        print()
        print(json.dumps(pv.as_dict(), indent=1, default=str))
    # 0 when the file would do what a valid decision should; 1 when it grants nothing.
    return 0 if (pv.valid and pv.would_release) else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
