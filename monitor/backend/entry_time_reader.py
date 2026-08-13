"""Recover each open position's fill time from the runner's own trade log.

Why this module exists
----------------------
`runner.dump_state` emits `entry_time: None` for every open position — the field is
reserved in the snapshot contract but never wired (global_index/runner.py:2540). Two
links are missing upstream: `backtest_swing_tf` computes `entry_time=idx[n]`
(futures/_validated_core.py:423) but `SwingTFEngine.desired_position` returns only
direction/entry/stop/entry_day, so the bar time never reaches `OpenPos`; and
`entry_day` itself is normalised to midnight because it drives holding-day counts and
the stop-arming window, both of which are day-based.

The realtime dashboard already renders `runner.entry_time` and falls back to a
"not emitted" caption, so filling this field lights up an existing display.

Why not ask IBKR
----------------
`reqPositions`/`portfolio` — the call the monitor already makes — carries no timestamp
at all, only symbol, quantity and average cost. `reqExecutions` does carry a time but
IBKR serves it for the current day only; global_index/statement.py records that being
hit live on 2026-08-05 ("reqExecutions had dropped the fill a day later"). A position
opened two sessions ago is simply not answerable over the TWS socket. Full history
lives in an Activity Statement / Flex Web Service, which needs a token and is a
different transport.

`trade_log.jsonl` already carries a `ts` for every fill, keeps it forever, and the
monitor reads that file in two other readers. It is the better source and needs no
broker connection.

Trustworthiness of `ts`
-----------------------
The trade log is written by the runner, so it is only as right as the runner was.
Four of the records on file carry a `ts` at exactly midnight — all dated 2026-08-03,
matching the incident global_index/statement.py describes, where `send_order` misread
three filled OPENs as cancelled and the records were reconstructed afterwards from the
date alone. Midnight there is a placeholder, not an execution time, so this module
reports those as `day_only` and refuses to hand back a time. Rendering 00:00 as the
moment of entry would be inventing evidence.

Read-only: parses two files, opens no connection, writes nothing.
"""
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

# A fill price this far from the recorded entry price is treated as a different trade.
_PRICE_TOLERANCE = 1e-6


def _iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _day_key(value: Any) -> str | None:
    """Normalise both spellings of the entry day to YYYY-MM-DD.

    The trade log writes "2026-08-10"; live_positions.json writes
    "2026-08-10 00:00:00". Snapshot open_positions already carries the short form.
    """
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text.split("T")[0].split(" ")[0]


def _precision(stamp: str) -> str:
    """`exact` when the timestamp carries a real clock reading, else `day_only`.

    The reconstructed records sit at exactly 00:00:00 with no microseconds. A genuine
    fill landing on that instant is possible in principle and would be misreported
    here; at microsecond resolution it has not happened in the log and would cost only
    a caption, never a wrong time.
    """
    try:
        parsed = dt.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return "unknown"
    midnight = (parsed.hour, parsed.minute, parsed.second, parsed.microsecond)
    return "day_only" if midnight == (0, 0, 0, 0) else "exact"


def _build(path: Path) -> dict[str, dict[str, Any]]:
    """Index the OPEN records by (inst, cluster, entry_day).

    A torn or unparsable line is skipped rather than failing the whole index — the
    trade log is appended to live and the last line can be mid-write. Later records
    win, so a same-day re-entry reports the most recent fill.
    """
    index: dict[str, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "OPEN":
                continue
            day = _day_key(record.get("entry_day"))
            inst, cluster = record.get("inst"), record.get("cluster")
            stamp = record.get("ts")
            if not (day and inst and cluster and stamp):
                continue
            index[f"{inst}|{cluster}|{day}"] = {
                "entry_time": stamp,
                "precision": _precision(str(stamp)),
                "fill_price": record.get("fill_price"),
                "direction": record.get("direction"),
            }
    return index


def read_entry_times(root: Path) -> dict[str, Any]:
    """Server-stamped envelope around the OPEN index, re-parsed only on mtime change."""
    server_now = dt.datetime.now(dt.timezone.utc)
    path = Path(root) / "trade_log.jsonl"
    try:
        stat = path.stat()
    except OSError as exc:
        return {"source": "trade_log.jsonl", "observed_at": None,
                "server_now": _iso_utc(server_now), "entries": {}, "error": str(exc)}

    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    global _cache_key, _cache_value
    try:
        with _lock:
            if key != _cache_key or _cache_value is None:
                _cache_value = _build(path)
                _cache_key = key
            entries = copy.deepcopy(_cache_value)
    except OSError as exc:
        return {"source": "trade_log.jsonl", "observed_at": None,
                "server_now": _iso_utc(server_now), "entries": {}, "error": str(exc)}

    observed = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc)
    return {"source": "trade_log.jsonl", "observed_at": _iso_utc(observed),
            "server_now": _iso_utc(server_now), "entries": entries, "error": None}


def annotate_open_positions(payload: Any, index: dict[str, Any]) -> int:
    """Fill `entry_time` on every open position in a runner-state payload, in place.

    Only an exact timestamp is handed back. `entry_time_precision` always travels so
    the caller can tell "no record" from "record exists but carries no clock reading",
    and `entry_time_source` keeps the provenance visible next to runner-authored
    fields. Returns how many positions got a usable time.

    The price check is what makes the key safe: (inst, cluster, entry_day) would also
    match a different trade opened the same session on the same sleeve, and a wrong
    time presented confidently is worse than no time.
    """
    if not isinstance(payload, dict):
        return 0
    filled = 0
    for snapshot in payload.get("snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        for position in snapshot.get("open_positions") or []:
            if not isinstance(position, dict):
                continue
            day = _day_key(position.get("entry_day"))
            key = f"{position.get('inst')}|{position.get('cluster')}|{day}"
            record = index.get(key)
            if record is None:
                position["entry_time_precision"] = "no_record"
                position["entry_time_source"] = None
                continue

            recorded, logged = position.get("entry_price"), record.get("fill_price")
            if (recorded is not None and logged is not None
                    and abs(float(recorded) - float(logged)) > _PRICE_TOLERANCE):
                position["entry_time_precision"] = "price_mismatch"
                position["entry_time_source"] = None
                continue

            position["entry_time_precision"] = record["precision"]
            position["entry_time_source"] = "trade_log.jsonl"
            if record["precision"] == "exact":
                position["entry_time"] = record["entry_time"]
                filled += 1
    return filled