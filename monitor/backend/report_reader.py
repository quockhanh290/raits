"""On-demand, mtime-cached session reports for the Reports module only."""
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from global_index.session_report import collect_session_report

_lock = threading.Lock()
_cache: dict[tuple[str, str, tuple[tuple[str, int, int], ...]], dict[str, Any]] = {}


def _signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    values = []
    for pattern in ("scheduler_*.log", "live_day_*.log"):
        for path in sorted(root.glob(pattern)):
            try:
                stat = path.stat()
            except OSError:
                continue
            values.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    positions_path = root / "live_positions.json"
    try:
        stat = positions_path.stat()
        values.append((str(positions_path.resolve()), stat.st_mtime_ns, stat.st_size))
    except OSError:
        pass
    return tuple(values)


def read_report(day: str, root: Path) -> dict[str, Any]:
    key = (str(root.resolve()), day, _signature(root))
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)
    report = collect_session_report(day, root)
    # Raw log lines are working material for the collector, not dashboard data.
    # Returning them makes a normal report several megabytes without adding UI evidence.
    report.pop("lines", None)
    with _lock:
        _cache.clear()
        _cache[key] = copy.deepcopy(report)
    return report
