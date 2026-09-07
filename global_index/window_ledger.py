"""global_index/window_ledger.py — did the window get observed at all? NEW FILE.

Stage 1D of the Track 1 resume-primary plan. Append-only JSONL. Off unless an env var
names an existing directory. Never raises. Decides nothing.

Why this is separate from the checkpoint
----------------------------------------
A checkpoint answers *"what state did the last observation leave?"*. This answers *"did an
observation happen at all?"*. Merging them lets a window nobody watched look like a flat
position, which is the failure this exists to prevent.

The distinction that has to survive
-----------------------------------
    complete + no_signal   the window WAS observed and produced nothing        — safe
    complete + entered     observed, traded
    incomplete             window_closed written, observed < expected slots
    unobserved             NO window_closed record exists for that date/sleeve

**Absence of `window_closed` is itself the signal.** That is what makes this fail closed: a
suspended host writes nothing, and nothing is exactly what the reader must treat as
failure. A ledger that required a positive "I was down" record would be silent in the one
case it is built for.

Why it matters more for Track 1 than for legacy
-----------------------------------------------
Normal-R4 and NKD tolerate a missed slot: the state model is idempotent, so the next slot
computes the same desired position and the cost is entry latency. Calm A is a single shot
at 10:00 ET. **Stress-MNQ is not recoverable at all** — its entry is the break of the
09:30-10:30 low between 10:35 and 12:30, and re-running later would enter at a price that
has already moved. That is the same one-shot-at-the-wrong-price failure that was ruled a
design error rather than a tolerance question, and the 2026-08-04 max-hold incident is the
precedent for what "no record" costs: nothing downstream could tell "no position was due"
from "we never looked".

Environment
-----------
`RAITS_WINDOW_LEDGER_DIR`  directory for `window_coverage_YYYYMMDD.jsonl`. Unset -> off.
`RAITS_ROUTE`              identity only; defaults to `legacy`. Does not enable writes.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

_ENV_DIR = "RAITS_WINDOW_LEDGER_DIR"
_ENV_ROUTE = "RAITS_ROUTE"

SCHEMA = 1

WINDOW_OPEN = "window_open"
SLOT_OBSERVED = "slot_observed"
WINDOW_CLOSED = "window_closed"

COMPLETE = "complete"
INCOMPLETE = "incomplete"
UNOBSERVED = "unobserved"

NO_SIGNAL = "no_signal"
ENTERED = "entered"

#: Declared shape of each Track 1 detection window. Expected slot counts are part of the
#: contract: without them "observed 9 slots" cannot be judged.
WINDOWS: dict[str, dict[str, Any]] = {
    "roska4_calm": {"label": "Calm A 10:00 ET", "expected_slots": 1,
                    "start_et": "10:00", "end_et": "10:00"},
    "roska4_stress": {"label": "Stress 10:35-12:30 ET, every 5 min",
                      "expected_slots": 24, "start_et": "10:35", "end_et": "12:30"},
    # Stage 5M-B. 23 slots: 14:05, then every five minutes through 15:55 — the legacy entry
    # cadence, mirrored exactly. Until this entry existed `expected_slots` returned None for
    # the sleeve, so a window could never be judged complete and the runbook precondition a
    # shadow period is measured against could never turn green.
    "roska4_swing": {"label": "Normal-R4 14:05-15:55 ET, every 5 min",
                     "expected_slots": 23, "start_et": "14:05", "end_et": "15:55"},
    # Stage 5N. 22 slots, the legacy nkd_night cadence mirrored. The date a window is keyed
    # by is the ET session date, and for this band (01:10-02:55 ET) the Tokyo calendar date
    # is the SAME date in both summer (14:10 JST) and winter (15:10 JST), so no
    # midnight-crossing rule is needed — measured, not assumed.
    "global_nkd": {"label": "MNKD 01:10-02:55 ET (Tokyo session), every 5 min",
                   "expected_slots": 22, "start_et": "01:10", "end_et": "02:55"},
}

_disabled = False


def route() -> str:
    return os.environ.get(_ENV_ROUTE) or "legacy"


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


def expected_slots(sleeve: str) -> "int | None":
    w = WINDOWS.get(sleeve)
    return w["expected_slots"] if w else None


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def _write(rec: dict) -> None:
    global _disabled
    d = _dir()
    if d is None:
        return
    try:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        line = json.dumps(rec, default=str, ensure_ascii=False) + "\n"
        with open(d / f"window_coverage_{day}.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        # One failure disables the channel for this process. It must never escape into a
        # trading path — the ledger records availability, it does not enforce it.
        _disabled = True


def _base(event: str, sleeve: str, date: str) -> dict:
    return {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "schema": SCHEMA, "route": route(), "sleeve": sleeve,
            "date": str(date), "event": event}


def window_open(sleeve: str, date, **extra) -> None:
    rec = _base(WINDOW_OPEN, sleeve, date)
    rec["expected_slots"] = expected_slots(sleeve)
    rec.update({k: v for k, v in extra.items()
                if isinstance(v, (str, int, float, bool)) or v is None})
    _write(rec)


def slot_observed(sleeve: str, date, slot_id: str, seq: "int | None" = None, **extra) -> None:
    rec = _base(SLOT_OBSERVED, sleeve, date)
    rec["slot_id"] = str(slot_id)
    if seq is not None:
        rec["seq"] = int(seq)
    rec.update({k: v for k, v in extra.items()
                if isinstance(v, (str, int, float, bool)) or v is None})
    _write(rec)


def window_closed(sleeve: str, date, observed_slots: int,
                  signal: str = NO_SIGNAL, **extra) -> None:
    """Close the window. `signal` says whether an observed window produced anything —
    it is NOT the same axis as whether the window was observed."""
    exp = expected_slots(sleeve)
    rec = _base(WINDOW_CLOSED, sleeve, date)
    rec["expected_slots"] = exp
    rec["observed_slots"] = int(observed_slots)
    rec["outcome"] = (COMPLETE if exp is not None and int(observed_slots) >= exp
                      else INCOMPLETE)
    rec["signal"] = signal
    rec.update({k: v for k, v in extra.items()
                if isinstance(v, (str, int, float, bool)) or v is None})
    _write(rec)


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def read(paths: Iterable[Path]) -> list[dict]:
    out: list[dict] = []
    for p in paths:
        try:
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        except Exception:
            continue
    return out


def files(day: "str | None" = None) -> list:
    """Coverage files in the configured directory, or just the one for `day`.

    Returns an empty list when the ledger is off, which is the same answer as "nothing has been
    written" — correct here, because a caller that wants to know whether writing is possible
    asks `enabled()`, and one that wants records is entitled to none either way.
    """
    d = _dir()
    if d is None:
        return []
    pat = f"window_coverage_{day}.jsonl" if day else "window_coverage_*.jsonl"
    return sorted(Path(d).glob(pat))


def read_day(date) -> list:
    """Every record written for one date, read back off disk.

    Each Track 1 slot is its own process, so the only thing that knows what a whole window did
    is the file the slots appended to. A caller that closes a window has to read rather than
    remember.

    The file is named for the UTC date the record was WRITTEN, while `date` is the ET session
    day, and those differ for anything after 20:00 ET. So both the session file and its
    neighbours are scanned and the records are filtered on their own `date` field, which is the
    session day the writer meant.
    """
    day = str(date)
    compact = day.replace("-", "")
    seen: dict = {}
    for f in files():
        seen[f.name] = f
    want = [f for n, f in seen.items() if compact in n] or list(seen.values())
    return [r for r in read(want) if str(r.get("date")) == day]


def status(records: Iterable[Mapping[str, Any]], sleeve: str, date) -> dict:
    """Coverage verdict for one sleeve on one date.

    The fail-closed rule lives here in one line: **no `window_closed` record means
    `unobserved`**, whatever else is or is not present. A window that opened and then
    vanished is not "in progress" after the fact — it is a window nobody can vouch for.
    """
    date = str(date)
    rows = [r for r in records
            if r.get("sleeve") == sleeve and str(r.get("date")) == date]
    closed = [r for r in rows if r.get("event") == WINDOW_CLOSED]
    exp = expected_slots(sleeve)
    if not closed:
        return {"sleeve": sleeve, "date": date, "outcome": UNOBSERVED,
                "signal": None, "expected_slots": exp,
                "observed_slots": sum(1 for r in rows if r.get("event") == SLOT_OBSERVED),
                "usable_as_evidence": False,
                "reason": "no window_closed record — absence is the signal"}
    last = closed[-1]
    outcome = last.get("outcome")
    return {"sleeve": sleeve, "date": date, "outcome": outcome,
            "signal": last.get("signal"), "expected_slots": last.get("expected_slots"),
            "observed_slots": last.get("observed_slots"),
            "usable_as_evidence": outcome == COMPLETE,
            "reason": "" if outcome == COMPLETE else
                      f"observed {last.get('observed_slots')} of {last.get('expected_slots')}"}
