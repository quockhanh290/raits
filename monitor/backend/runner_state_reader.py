"""Read the runner dashboard artifact without importing the trading runner."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import threading
from pathlib import Path
from typing import Any

#: Who writes `live_state_data.js`. There is exactly one writer and it belongs to the retired
#: route; the envelope says so rather than letting a reader assume the file describes today.
LEGACY_ERA = "legacy"
LEGACY_PRODUCER = ("FuturesRunner.dump_state — the legacy route's runner; legacy entries "
                   "retired 2026-08-27 and nothing on the Track 1 route writes this file")

#: Past this the payload is a record of the past, never a reading of the present. Twelve hours
#: because the legacy runner published every trading day: one missed publication is a
#: producer that has stopped, not one running late. The page has used the same figure since
#: Stage 5ZZH (`LEGACY_STALE_HOURS` in realtime.js); a test holds the two together.
LEGACY_STALE_AFTER_SECONDS = 12 * 3600

#: Envelope keys that describe the envelope itself rather than carry data from the file.
#: Everything else that leaves the endpoint must carry a `_provenance` stamp.
ENVELOPE_KEYS = frozenset({
    "source", "source_era", "producer", "observed_at", "server_now", "age_seconds",
    "freshness", "schedule_freshness", "expected_next_at", "error", "stale", "current",
    "provenance", "payload",
    # Plan stage 2: `payload` is Track 1's and declares each key's source in these two maps.
    "payload_era", "payload_sources", "payload_absent", "built_at",
})


def _tri_state(value: Any) -> str:
    """`ibkr_connected` as three answers. A boolean cannot say "nobody looked recently"."""
    if value is True:
        return "connected"
    if value is False:
        return "disconnected"
    return "unknown"


def declare_provenance(state: dict[str, Any],
                       stale_after_seconds: float = LEGACY_STALE_AFTER_SECONDS) -> dict[str, Any]:
    """Stamp every block that leaves `/api/v1/runner-state` with where it came from and
    whether it is current. Mutates and returns `state` — callers hand in the deepcopy that
    `read_runner_state` already made, so nothing leaks into the parse cache.

    Why this exists. Measured 2026-09-24: the endpoint served `broker_equity` 996,730.93
    (the account then held 251,341 — four times less) and `ibkr_connected: true` read from a
    heartbeat dated 2026-08-24, thirty-one days earlier, under `freshness: not_expected_yet`.
    That label comes from the schedule, and in track1-only mode the legacy runner is never
    due, so `expected_next_at` slides forward for ever and nothing calls the payload old. A
    freshness model that assumes its producer still runs cannot report one that has stopped.

    So age decides, not the schedule. Past the threshold:
      * `freshness` becomes `stale`; the schedule's own answer is kept as `schedule_freshness`
      * `runner_health.ibkr_connected` becomes `unknown` — a thirty-day-old `true` is a claim
        about the present that nobody can make — and the old value is kept beside it, named
      * every data block, and every snapshot, carries `_provenance` with `stale: true`
    Nothing is deleted: the figures are still history, and history is allowed on the page as
    long as it cannot be mistaken for the present.
    """
    age = state.get("age_seconds")
    stale = not isinstance(age, (int, float)) or age > stale_after_seconds
    stamp = {"era": LEGACY_ERA, "as_of": state.get("observed_at"), "age_seconds": age,
             "stale": stale, "current": not stale}
    state["source_era"] = LEGACY_ERA
    state["producer"] = LEGACY_PRODUCER
    state["stale"] = stale
    state["current"] = not stale
    state["provenance"] = {
        **stamp, "producer": LEGACY_PRODUCER, "stale_after_seconds": stale_after_seconds,
        "reading": ("a record of the legacy route as it last published — not a reading of "
                    "the present; Track 1's own state is served by /api/v1/track1-runtime"
                    if stale else
                    "the legacy runner published within the staleness window"),
    }
    payload = state.get("payload")
    if stale and payload is not None and state.get("freshness") != "missing":
        state["schedule_freshness"] = state.get("freshness")
        state["freshness"] = "stale"

    if isinstance(payload, dict):
        health = payload.get("runner_health")
        if isinstance(health, dict):
            reported = health.get("ibkr_connected")
            health["ibkr_connected_reported"] = reported
            health["ibkr_connected"] = "unknown" if stale else _tri_state(reported)
        for block in payload.values():
            if isinstance(block, dict):
                block["_provenance"] = dict(stamp)
            elif isinstance(block, list):
                for item in block:
                    if isinstance(item, dict):
                        item["_provenance"] = dict(stamp)

    # Blocks the endpoint derives FROM this payload inherit its era — `event_history` is the
    # legacy runner's event log for the newest legacy snapshot day, and `entry_times` is read
    # from the legacy trade log. Stamped here so a key added later without a stamp fails the
    # test that walks the response, instead of slipping out unlabelled.
    for key, value in list(state.items()):
        if key in ENVELOPE_KEYS:
            continue
        if isinstance(value, dict):
            value["_provenance"] = dict(stamp)
    return state


_ASSIGNMENT = re.compile(r"(?:^|\n)\s*window\.LIVE_DATA\s*=\s*", re.DOTALL)
_lock = threading.Lock()
_cache_key: tuple[str, int, int] | None = None
_cache_value: dict[str, Any] | None = None


def _iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(text: str) -> dict[str, Any]:
    source = text.lstrip("\ufeff")
    match = _ASSIGNMENT.search(source)
    if not match:
        raise ValueError("live state does not start with window.LIVE_DATA assignment")
    body = source[match.end():].strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("live state payload is not an object")
    return value


def read_runner_state(path: Path, now: dt.datetime | None = None) -> dict[str, Any]:
    """Return a server-stamped envelope, parsing again only when mtime changes."""
    server_now = now or dt.datetime.now(dt.timezone.utc)
    if server_now.tzinfo is None:
        server_now = server_now.replace(tzinfo=dt.timezone.utc)

    try:
        stat = path.stat()
    except OSError as exc:
        return {
            "source": "runner_state",
            "observed_at": None,
            "server_now": _iso_utc(server_now),
            "age_seconds": None,
            "freshness": "missing",
            "error": str(exc),
            "payload": None,
        }

    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    global _cache_key, _cache_value
    try:
        with _lock:
            if key != _cache_key or _cache_value is None:
                _cache_value = _parse(path.read_text(encoding="utf-8"))
                _cache_key = key
            payload = copy.deepcopy(_cache_value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "source": "runner_state",
            "observed_at": None,
            "server_now": _iso_utc(server_now),
            "age_seconds": None,
            "freshness": "missing",
            "error": str(exc),
            "payload": None,
        }

    observed = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
    return {
        # Stage 2026-09-24 (plan stage 0). Named at the source, not left to be inferred from
        # the path: this file has one producer, the legacy route's runner, and it has had no
        # other since legacy was retired on 2026-08-27.
        "source_era": LEGACY_ERA,
        "producer": LEGACY_PRODUCER,
        "source": "runner_state",
        "observed_at": _iso_utc(observed),
        "server_now": _iso_utc(server_now),
        "age_seconds": max(0, round((server_now - observed).total_seconds(), 3)),
        "freshness": "unknown",
        "error": None,
        "payload": payload,
    }
