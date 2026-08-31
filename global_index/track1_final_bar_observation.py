"""global_index/track1_final_bar_observation.py — what the LAST slot of a session saw. NEW FILE.

Stage 5ZZZ-BD. **Read-only for gates, write-only for slots.** Nothing here connects, starts or
arms anything. It answers one question:

    has a real Normal-regime session run to its final slot, and did that slot say whether the
    newest bar had closed?

Why this file exists, rather than the gate reading the diagnostics module
------------------------------------------------------------------------
`FINAL_BAR_DIVERGENCE_OBSERVED` first read the display-side diagnostics store directly, and
that broke a safety line the repo enforces the cheapest possible way:

    a reconstruction must never satisfy readiness, an audit or an order gate, and the way that
    is kept true is that neither the gate registry, nor the readiness check, nor the acceptance
    judge names the module holding reconstructions -- anywhere, comments included

The gate did filter reconstructions out and a test pinned it. But that trades a guarantee held
BY CONSTRUCTION for one held by remembering -- and worse, the test enforcing the line walks
those three files in order and stops at the first offender. Measured with the gate in place:

    1. track1_gates.py               1 mention   BROKEN
    2. track1_paper_readiness.py     0           no longer reached
    3. track1_shadow_acceptance.py   0           no longer reached

The alarm for three files had been left ringing for one, which is the same as switched off --
and the two files it stopped covering are the ones that grade shadow days and gather the
evidence, both of which run unattended every day.

So the evidence moves to its own ledger. The property that matters is not a filter, it is
SEPARATE STORAGE: reconstructions are written by a different function into a different file,
and nothing here can read that file. This module is one hop from a gate, so the same rule
binds it -- including this paragraph, which is why the store is described and not named.
A reconstruction cannot reach a gate because there is no path, not because a check refuses it.

Three answers, never two
------------------------
    OBSERVED       a real slot recorded what its final bar looked like
    NOT_OBSERVED   records exist, and none is a Normal final slot carrying an answer
    UNKNOWN        nothing recorded, or the ledger could not be read

`UNKNOWN` is not a pass and never collapses into `NOT_OBSERVED`: "nobody looked" and "we
looked and the session never came" are different facts about the route, and a gate that
confuses them reports progress that has not happened.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

OBSERVED = "OBSERVED"
NOT_OBSERVED = "NOT_OBSERVED"
UNKNOWN = "UNKNOWN"
STATUSES = (OBSERVED, NOT_OBSERVED, UNKNOWN)

#: The slot ids that END a family's window. Each family's last slot fires at :55 on the session
#: clock, which is the moment the window's final bar OPENS -- the whole reason this ledger
#: exists. Suffixes rather than whole ids, because the family prefix differs per route.
FINAL_SLOT_SUFFIXES = ("1555", "0255")

DIRNAME = "final_bar_observation"


@dataclass(frozen=True)
class Observation:
    """One slot's account of its own final bar. Every field is measured, none is derived."""

    status: str
    session_date: str = ""
    sleeve: str = ""
    slot_id: str = ""
    regime: str = ""
    #: True, False, or None when the slot did not measure it. Never guessed.
    last_bar_complete: Any = None
    bars_evaluated: Any = None
    surge_reached: Any = None
    surge_passed: Any = None
    detail: str = ""
    at: str = ""

    def is_final_slot(self) -> bool:
        return str(self.slot_id).endswith(FINAL_SLOT_SUFFIXES)


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def path_for(root: str | Path = ".", day: str = "") -> Path:
    d = "".join(ch for ch in str(day) if ch.isdigit())[:8] or "unknown"
    return (Path(root) / "global_index" / "track1_runtime" / DIRNAME
            / f"track1_final_bar_{d}.jsonl")


def record(*, root: str | Path = ".", session_date: str, sleeve: str, slot_id: str,
           regime: str, last_bar_complete: Any, bars_evaluated: Any = None,
           surge_reached: Any = None, surge_passed: Any = None) -> "Path | None":
    """Append one slot's observation. Called ONLY from the live slot path.

    Returns the path written, or None when there was nothing to record. Refuses silently
    rather than raising: this runs beside a sleeve looking for its entries, and a bookkeeping
    failure must not be the reason one is lost.

    Nothing derived is stored. `last_bar_complete` is whatever the slot measured, including
    `None` for "did not measure", because a ledger that turns a missing measurement into a
    False is a ledger reporting an observation nobody made.
    """
    try:
        if not str(slot_id).endswith(FINAL_SLOT_SUFFIXES):
            return None
        p = path_for(root, session_date)
        p.parent.mkdir(parents=True, exist_ok=True)
        row = asdict(Observation(
            status=OBSERVED, session_date=str(session_date)[:10], sleeve=str(sleeve),
            slot_id=str(slot_id), regime=str(regime or ""),
            last_bar_complete=last_bar_complete, bars_evaluated=bars_evaluated,
            surge_reached=surge_reached, surge_passed=surge_passed, at=_now()))
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")
        return p
    except Exception:                                              # noqa: BLE001
        return None


def _read_dir(root: str | Path) -> list:
    folder = path_for(root, "20000101").parent
    if not folder.exists():
        return []
    out = []
    for f in sorted(folder.glob("*.jsonl"), reverse=True):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:                                      # noqa: BLE001
                continue
    return out


def latest(root: str | Path = ".", *, regime: str = "Normal") -> Observation:
    """The most recent qualifying observation, or why there is none.

    Qualifying means: a final slot, of a session in `regime`, that answered whether its newest
    bar had closed. A row missing that answer is not an observation -- it is a slot that ran
    without measuring, and counting it would let the gate open on silence.
    """
    try:
        rows = _read_dir(root)
    except Exception as exc:                                       # noqa: BLE001
        return Observation(status=UNKNOWN,
                           detail=f"the ledger could not be read ({type(exc).__name__}: "
                                  f"{exc}) -- failing closed")
    if not rows:
        return Observation(status=UNKNOWN,
                           detail="nothing has been recorded yet -- UNKNOWN, not a pass")
    seen = 0
    for r in rows:
        if str(r.get("regime")) != regime:
            continue
        if not str(r.get("slot_id", "")).endswith(FINAL_SLOT_SUFFIXES):
            continue
        seen += 1
        if r.get("last_bar_complete") is None:
            continue
        return Observation(
            status=OBSERVED, session_date=str(r.get("session_date") or ""),
            sleeve=str(r.get("sleeve") or ""), slot_id=str(r.get("slot_id") or ""),
            regime=str(r.get("regime") or ""),
            last_bar_complete=r.get("last_bar_complete"),
            bars_evaluated=r.get("bars_evaluated"),
            surge_reached=r.get("surge_reached"), surge_passed=r.get("surge_passed"),
            at=str(r.get("at") or ""),
            detail=("%s %s on %s: newest bar closed=%s, %s bars walked"
                    % (r.get("sleeve"), r.get("slot_id"), r.get("session_date"),
                       r.get("last_bar_complete"), r.get("bars_evaluated"))))
    if seen:
        return Observation(
            status=NOT_OBSERVED,
            detail=("%d %s final-slot record(s) found, none of which answered whether its "
                    "newest bar had closed" % (seen, regime)))
    return Observation(
        status=NOT_OBSERVED,
        detail=("records exist, but no %s session has reached a final slot yet" % regime))
