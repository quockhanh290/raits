"""Read persisted runner positions without importing or mutating the runner."""
from __future__ import annotations

import copy
import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_cache_key: tuple[str, int, int] | None = None
_cache_value: dict[str, Any] | None = None


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value.get("positions") if isinstance(value, dict) else value
    if not isinstance(rows, list):
        raise ValueError("persisted runner positions are not a list")
    positions = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        positions.append({
            key: row.get(key) for key in (
                "inst", "direction", "contracts", "cluster", "entry_day",
                "entry_price", "stop_price", "stop_order_id",
                # Which contract month the book thinks it holds. This projection is an
                # allow-list, so a key not named here is dropped — recording the month
                # in the file and then hiding it from the only page that shows positions
                # would leave the C1 blind spot half open. None for rows written before
                # the field existed.
                "contract_month",
            )
        })
    return {
        "schema_version": value.get("schema_version") if isinstance(value, dict) else None,
        "positions": positions,
    }


def read_runner_positions(path: Path) -> dict[str, Any]:
    """Return an mtime-cached, read-only projection of live_positions.json."""
    try:
        stat = path.stat()
    except OSError as exc:
        return {"source": "runner_persisted_positions", "observed_at": None,
                "payload": None, "error": str(exc)}

    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    global _cache_key, _cache_value
    try:
        with _lock:
            if key != _cache_key or _cache_value is None:
                _cache_value = _parse(path)
                _cache_key = key
            payload = copy.deepcopy(_cache_value)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"source": "runner_persisted_positions", "observed_at": None,
                "payload": None, "error": str(exc)}

    observed = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
    return {"source": "runner_persisted_positions", "observed_at": _iso(observed),
            "payload": payload, "error": None}
