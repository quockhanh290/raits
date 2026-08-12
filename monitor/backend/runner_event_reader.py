"""Read append-only runner JSONL telemetry without importing the runner."""
from __future__ import annotations

import copy
import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_cache: dict[tuple[str, int, int], dict[str, Any]] = {}


def read_runner_events(day: str, root: Path) -> dict[str, Any]:
    parsed_day = dt.date.fromisoformat(day)
    path = root / "global_index" / f"runner_events_{parsed_day:%Y%m%d}.jsonl"
    try:
        stat = path.stat()
    except OSError as exc:
        return {
            "source": "runner_event_jsonl", "day": day, "observed_at": None,
            "coverage_started_at": None, "complete": False, "events": [],
            "malformed_lines": 0, "error": str(exc),
        }

    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    with _lock:
        cached = _cache.get(key)
        if cached is None:
            events: list[dict[str, Any]] = []
            malformed = 0
            lines = path.read_bytes().splitlines()
            for raw_line in lines:
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    malformed += 1
                    continue
                if isinstance(event, dict) and event.get("ts"):
                    events.append(event)
                else:
                    malformed += 1
            events.sort(key=lambda event: str(event["ts"]))
            observed = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
            cached = {
                "source": "runner_event_jsonl", "day": day,
                "observed_at": observed.isoformat().replace("+00:00", "Z"),
                "coverage_started_at": events[0]["ts"] if events else None,
                "complete": False, "events": events, "malformed_lines": malformed,
                "error": "malformed JSONL record(s) ignored" if malformed else None,
            }
            _cache.clear()
            _cache[key] = cached
        return copy.deepcopy(cached)
