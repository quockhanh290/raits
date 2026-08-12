"""Read the runner dashboard artifact without importing the trading runner."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import threading
from pathlib import Path
from typing import Any

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
        "source": "runner_state",
        "observed_at": _iso_utc(observed),
        "server_now": _iso_utc(server_now),
        "age_seconds": max(0, round((server_now - observed).total_seconds(), 3)),
        "freshness": "unknown",
        "error": None,
        "payload": payload,
    }
