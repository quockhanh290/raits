"""Incremental, read-only extraction of operational session events from live logs."""
from __future__ import annotations

import copy
import datetime as dt
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Edmonton")
ET = ZoneInfo("America/New_York")
_LINE = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\S+\s+\S+\s+-\s+(?P<message>.*)$")
_ARMED = re.compile(
    r"place_stop: accepted (?P<direction>LONG|SHORT) (?P<inst>\w+) STP (?:×|Ã—)(?P<qty>[\d.]+) "
    r"@ (?P<price>[\d.]+) orderId=(?P<order_id>\d+) status=(?P<status>\w+) cluster=(?P<cluster>\S+)"
)
_DEFERRED = re.compile(r"B4: (?P<inst>\w+)/(?P<cluster>\S+) chua co STP .*cua so hoan")
_CLOSE_SENT = re.compile(
    r"send_order: placed CLOSE (?P<action>BUY|SELL) (?P<inst>\w+) (?:×|Ã—)(?P<qty>[\d.]+) cluster=(?P<cluster>\S+)"
)
_CLOSE_FILLED = re.compile(
    r"send_order: FILLED CLOSE (?P<inst>\w+) (?:×|Ã—)(?P<qty>[\d.]+) @ (?P<price>[\d.]+)"
)
_STOP_CANCELLED = re.compile(
    r"STP: cancelled GTC stop orderId=(?P<order_id>\d+) for closed (?P<inst>\w+)/(?P<cluster>\S+)"
)
_STOP_EXIT = re.compile(
    r"B3 STP EXIT: (?P<inst>\w+) (?P<direction>LONG|SHORT) stop orderId=(?P<order_id>\d+) filled @ (?P<price>[\d.]+)"
)

_lock = threading.Lock()
_cache: dict[str, dict[str, Any]] = {}


def _iso(stamp: str) -> tuple[str, str]:
    local = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)
    return local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"), str(local.astimezone(ET).date())


def _event(stamp: str, category: str, kind: str, message: str, **fields: Any) -> dict[str, Any]:
    timestamp, session_day = _iso(stamp)
    return {"ts": timestamp, "session_day": session_day, "category": category,
            "kind": kind, "level": "INFO", "message": message, **fields}


def _parse_line(line: str) -> dict[str, Any] | None:
    match = _LINE.match(line)
    if not match:
        return None
    stamp, message = match.group("stamp"), match.group("message")
    found = _ARMED.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "PROTECTION", "stop_armed",
                      f"Armed {item['inst']} {item['direction']} STP x{item['qty']} @ {item['price']} / "
                      f"#{item['order_id']} {item['status']}", **item)
    found = _DEFERRED.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "PROTECTION", "stop_deferred",
                      f"{item['inst']} stop remains deliberately deferred by session rule", **item)
    found = _CLOSE_SENT.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "EXEC", "market_close_submitted",
                      f"Submitted MARKET CLOSE {item['action']} {item['inst']} x{item['qty']}", **item)
    found = _CLOSE_FILLED.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "EXEC", "market_close_filled",
                      f"Filled MARKET CLOSE {item['inst']} x{item['qty']} @ {item['price']}", **item)
    found = _STOP_CANCELLED.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "PROTECTION", "stop_cancelled_after_close",
                      f"Cancelled unfilled GTC stop #{item['order_id']} after {item['inst']} close", **item)
    found = _STOP_EXIT.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "EXEC", "stop_filled",
                      f"Filled broker STP #{item['order_id']} for {item['inst']} {item['direction']} @ {item['price']}", **item)
    return None


def _log_path(day: str, root: Path) -> Path:
    parsed = dt.date.fromisoformat(day)
    return root / f"live_day_{parsed:%m%d}.log"


def _dedupe(events: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        if event["session_day"] != day:
            continue
        key = (event["kind"], str(event.get("inst", "")), str(event.get("order_id", "")))
        # Repeated deferred checks add no information; retain only the latest observation.
        selected[key] = event
    return sorted(selected.values(), key=lambda item: item["ts"])


def read_session_events(day: str, root: Path) -> dict[str, Any]:
    path = _log_path(day, root)
    try:
        stat = path.stat()
    except OSError as exc:
        return {"source": "live_log", "day": day, "observed_at": None,
                "events": [], "error": str(exc)}

    cache_key = str(path.resolve())
    with _lock:
        cached = _cache.get(cache_key)
        if cached is None or stat.st_size < cached["offset"]:
            cached = {"offset": 0, "events": [], "partial": ""}
        if stat.st_size > cached["offset"]:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(cached["offset"])
                chunk = cached["partial"] + handle.read()
                cached["offset"] = handle.tell()
            lines = chunk.splitlines(keepends=True)
            cached["partial"] = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                cached["partial"] = lines.pop()
            for line in lines:
                parsed = _parse_line(line.rstrip("\r\n"))
                if parsed is not None:
                    parsed["sequence"] = len(cached["events"])
                    cached["events"].append(parsed)
        _cache[cache_key] = cached
        events = _dedupe(cached["events"], day)

    observed = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
    return {"source": "live_log", "day": day,
            "observed_at": observed.isoformat().replace("+00:00", "Z"),
            "events": copy.deepcopy(events), "error": None}
