"""global_index/route_checkpoint.py — route-scoped replay checkpoint, schema 2. NEW FILE.

Stage 1A of the Track 1 resume-primary plan. Offline only: nothing here connects to a
broker, starts a service, or decides a trade.

Relationship to the legacy checkpoint
-------------------------------------
`global_index/replay_checkpoint.py` is **not modified and not subclassed**. It keeps its
own file, its own `SCHEMA = 1`, and its own instrument-only key space. This module is a
parallel implementation for a second route, and the two refuse each other by construction:
a v1 payload has no `routes` key, and `replay_checkpoint.load()` already discards any
payload whose `schema_version` is not 1.

What is reused, and why exactly that
------------------------------------
`fingerprint()` is **imported, never copied**. Its docstring records a subtlety paid for in
production — the same history arrives tz-aware from `load_parquet` and tz-naive from the
live path, so the tz is stripped before hashing or the two representations would never
match and the checkpoint would be discarded on every live run *while looking like it was
working*. A copy of that function would drift from the original at exactly the point the
original says drift is fatal.

`advance_day()` is likewise imported by callers rather than re-derived. It encodes the fix
for the 2026-08-07 incident (advancing over a parquet day only half held, so the next
13:45 ET append moved ~554 rows and every Ro 4 fingerprint stopped matching). Re-deriving
that rule here would be re-deriving a bug fix from memory.

Three things v1 could not do
----------------------------
1. **Key by route and sleeve.** v1 keys by instrument alone, so it cannot hold MES in both
   Normal-R4 and Calm A at once — which Track 1 requires.
2. **Say why it refused.** v1's `usable()` returns a bare `None` for four distinct
   conditions. Reconstructing which one fired meant string-diffing two hashes out of log
   lines. Here a refusal is a `Refusal` with a code.
3. **Survive a second writer.** v1's `save()` rewrites the whole dict, so two routes
   sharing a file is a lost update, not merely untidy. Here a writer may only author keys
   under its own route, a lock serialises read-modify-write, and the merge asserts every
   key outside that route is byte-identical to what it loaded.

Sleeves with no historical state
--------------------------------
`roska4_stress` and `roska4_calm` are same-session: their inputs are today's bars plus a
small D-1 context, so they need no historical checkpoint. They are still created, empty,
by `empty_payload()`. Present-but-empty says "this sleeve is accounted for"; absent would
say "nobody thought about it". Their coverage lives in `window_ledger`, not here.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, NamedTuple

import pandas as pd

# Imported, not copied — see the module docstring.
from global_index.replay_checkpoint import fingerprint

SCHEMA = 2
DEFAULT_PATH = "global_index/replay_checkpoint.track1.json"
DEFAULT_ROUTE = "track1_candidate"

#: Sleeves the route knows about. The two same-session ones are listed on purpose.
SLEEVES = ("roska4_swing", "global_nkd", "roska4_calm", "roska4_stress")

#: Sleeves that carry cross-day state and therefore a checkpoint entry at all.
CHECKPOINTED_SLEEVES = ("roska4_swing", "global_nkd")

# Refusal codes. One per distinct condition, because "it refused" is not a diagnosis.
NO_ENTRY = "no_entry"
BAD_LAST_DAY = "bad_last_day"
FINGERPRINT_ROWCOUNT = "fingerprint_rowcount"
FINGERPRINT_CONTENT = "fingerprint_content"
PARAMS_MISMATCH = "params_mismatch"
ROUTE_MISMATCH = "route_mismatch"
SCHEMA_MISMATCH = "schema_mismatch"

REASON_CODES = (NO_ENTRY, BAD_LAST_DAY, FINGERPRINT_ROWCOUNT, FINGERPRINT_CONTENT,
                PARAMS_MISMATCH, ROUTE_MISMATCH, SCHEMA_MISMATCH)

_LOCK_STALE_SECS = 60.0
_LOCK_WAIT_SECS = 10.0


class Refusal(NamedTuple):
    """Why a checkpoint could not be used. Never a bare None.

    `detail` carries the two sides of the comparison so a caller can log a sentence
    rather than "unusable".
    """
    code: str
    detail: str = ""

    def __bool__(self) -> bool:                    # `if resumed:` must be False here
        return False


class Resumed(NamedTuple):
    """A usable entry: where to resume from, and the position that stood there."""
    last_day: pd.Timestamp
    pos: dict | None

    def __bool__(self) -> bool:
        return True


class LockTimeout(RuntimeError):
    """Another writer held the lock past the wait budget.

    Raised rather than swallowed: a caller that cannot take the lock must not proceed to
    write, because the whole point of the lock is that the read it based its merge on is
    still current.
    """


# ---------------------------------------------------------------------------
# position serialisation — same semantics as v1, kept local rather than importing
# a private name across modules
# ---------------------------------------------------------------------------
def _pos_to_json(pos):
    if pos is None:
        return None
    return {k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in pos.items()}


def _pos_from_json(d):
    if d is None:
        return None
    out = dict(d)
    for k in ("entry_day", "entry_time"):
        if out.get(k):
            out[k] = pd.Timestamp(out[k])
    return out


# ---------------------------------------------------------------------------
# payload shape
# ---------------------------------------------------------------------------
def empty_payload(route: str = DEFAULT_ROUTE) -> dict:
    return {"schema_version": SCHEMA,
            "routes": {route: {"sleeves": {s: {"instruments": {}} for s in SLEEVES}}}}


def make_entry(df: pd.DataFrame, last_day, pos, *, route: str, sleeve: str,
               params: str, params_hash: str, data_source: str) -> dict:
    """One instrument's entry.

    `params` and `params_hash` both travel: the hash decides, the readable string lets a
    refusal name the setting that moved. `data_source` is separate from the fingerprint
    because the fingerprint pins *content* and two files can hold the same bars.
    """
    return {"route": route,
            "sleeve": sleeve,
            "last_day": str(pd.Timestamp(last_day).date()),
            "fingerprint": fingerprint(df, last_day),
            "params": params,
            "params_hash": params_hash,
            "data_source": data_source,
            "pos": _pos_to_json(pos)}


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------
def load(path: str = DEFAULT_PATH) -> dict:
    """Whole payload, or an empty one. A corrupt or foreign file is a slow run, never a
    wrong one — same stance as v1."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA:
        return {}
    if "routes" not in raw:                        # a v1 payload reaching a v2 reader
        return {}
    return raw


def get_entry(payload: Mapping[str, Any], route: str, sleeve: str, inst: str) -> dict:
    try:
        return payload["routes"][route]["sleeves"][sleeve]["instruments"][inst]
    except Exception:
        return {}


def usable(entry: Mapping[str, Any], df: pd.DataFrame, *, route: str,
           params_hash: str) -> "Resumed | Refusal":
    """`Resumed(last_day, pos)` if this entry still describes df's history, this engine
    and this route — otherwise a `Refusal` naming which of the checks failed.

    `pos=None` is returned as-is: a checkpoint recording that nothing was open is as valid
    as one recording a position, and treating it as a miss would replay in full on every
    flat day. That is v1's behaviour and it is deliberate.

    The fingerprint comparison is split into rowcount and content because in the recorded
    evidence those two had different causes — 48 of the 64 historical skips were a stale
    day (rowcount), 4 were bars rewritten underneath (content) — and one code for both
    forced this session to reconstruct the split by diffing hashes out of log lines.
    """
    if not entry:
        return Refusal(NO_ENTRY, "no entry at routes/%s/sleeves/*/instruments/*" % route)

    if entry.get("route") not in (None, route):
        return Refusal(ROUTE_MISMATCH,
                       f"entry route={entry.get('route')!r} caller route={route!r}")

    if "last_day" not in entry:
        return Refusal(BAD_LAST_DAY, "no last_day recorded")
    try:
        last_day = pd.Timestamp(entry["last_day"]).normalize()
    except Exception as exc:
        return Refusal(BAD_LAST_DAY, f"unparseable last_day {entry['last_day']!r}: {exc}")

    stored = entry.get("fingerprint")
    computed = fingerprint(df, last_day)
    if stored != computed:
        s_rows, c_rows = _rows(stored), _rows(computed)
        if s_rows is not None and c_rows is not None and s_rows != c_rows:
            return Refusal(FINGERPRINT_ROWCOUNT,
                           f"stored={stored} computed={computed} delta={s_rows - c_rows}")
        return Refusal(FINGERPRINT_CONTENT, f"stored={stored} computed={computed}")

    if entry.get("params_hash") != params_hash:
        return Refusal(PARAMS_MISMATCH,
                       f"stored={entry.get('params_hash')} caller={params_hash} "
                       f"stored_params={entry.get('params')!r}")

    return Resumed(last_day, _pos_from_json(entry.get("pos")))


def _rows(fp) -> "int | None":
    try:
        return int(str(fp).split(":", 1)[0])
    except Exception:
        return None


def stale(entry: Mapping[str, Any], today, max_age_days: int) -> bool:
    """True when `last_day` is older than the caller's declared limit.

    Separate from `usable()` on purpose: a stale entry can still have a matching
    fingerprint — the history just stopped growing — and that is precisely the case a
    fingerprint check cannot see.
    """
    try:
        last = pd.Timestamp(entry["last_day"]).normalize()
    except Exception:
        return True
    return (pd.Timestamp(today).normalize() - last).days > int(max_age_days)


# ---------------------------------------------------------------------------
# write — lock, scoped merge, scope assertion, atomic replace
# ---------------------------------------------------------------------------
class _FileLock:
    """Cheap cross-process lock: O_EXCL create, delete on release.

    A lock older than `_LOCK_STALE_SECS` is broken rather than waited on — a crashed
    writer must not wedge the route forever, and every write here is idempotent
    (read-modify-write of a whole file), so re-doing one is safe.
    """

    def __init__(self, target: Path, wait: float = _LOCK_WAIT_SECS):
        self.path = target.with_suffix(target.suffix + ".lock")
        self.wait = wait
        self._fd = None

    def __enter__(self):
        deadline = time.monotonic() + self.wait
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                    if age > _LOCK_STALE_SECS:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise LockTimeout(f"{self.path} held longer than {self.wait}s")
                time.sleep(0.02)

    def __exit__(self, *exc):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
        self.path.unlink(missing_ok=True)
        return False


class ScopeViolation(RuntimeError):
    """The merge would have changed a key outside the writer's own route.

    This is the assertion that makes the per-key merge provable rather than intended: it
    is what goes red if the scoping is removed.
    """


def _write_atomic(path: Path, payload: dict) -> None:
    """`.tmp` then replace — a run killed mid-write must not leave a half-parsed file.
    Same guarantee v1 gives, kept rather than weakened."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def save_route(entries_by_sleeve: Mapping[str, Mapping[str, dict]], *,
               route: str = DEFAULT_ROUTE, path: str = DEFAULT_PATH) -> dict:
    """Replace this route's entries; leave every other route byte-identical.

    Read-modify-write under a lock, because the merge is only correct if the payload it
    merges into is still the one on disk when it writes back.

    Returns the payload written, so a caller can assert on it without re-reading.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _FileLock(p):
        current = load(path) or {"schema_version": SCHEMA, "routes": {}}
        before_others = json.dumps(
            {r: v for r, v in current.get("routes", {}).items() if r != route},
            sort_keys=True)

        merged = json.loads(json.dumps(current))          # deep copy, no aliasing
        merged["schema_version"] = SCHEMA
        merged.setdefault("routes", {})
        sleeves = {s: {"instruments": {}} for s in SLEEVES}
        for sleeve, insts in entries_by_sleeve.items():
            sleeves.setdefault(sleeve, {"instruments": {}})
            sleeves[sleeve]["instruments"] = {i: dict(e) for i, e in insts.items()}
        merged["routes"][route] = {"sleeves": sleeves}

        after_others = json.dumps(
            {r: v for r, v in merged.get("routes", {}).items() if r != route},
            sort_keys=True)
        if after_others != before_others:
            raise ScopeViolation(
                f"save_route({route!r}) would have altered another route's keys — "
                f"the merge is not scoped and this write was refused")

        _write_atomic(p, merged)
        return merged
