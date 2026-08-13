"""Read-only paper evidence projection for the Paper dashboard."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import threading
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from monitor.backend.open_issue_reader import read_open_issues
from monitor.backend.runner_state_reader import read_runner_state

_lock = threading.Lock()
_cache: dict[tuple[str, tuple[tuple[str, int, int], ...]], dict[str, Any]] = {}

_STP_ARM_BY_CLUSTER = {
    "roska4_swing": ("America/New_York", 14, 0),
    "global_nkd": ("Asia/Tokyo", 14, 0),
}

_B3_MATCH = re.compile(r"B3: broker/file positions match \((?P<count>\d+) position")
_B3_MISMATCH = re.compile(r"B3: (?P<count>\d+) mismatch\(es\)")
_COLD_START = re.compile(r"Runner started: loaded")
_STP_VERIFY = re.compile(r"B3 STP-VERIFY")
_STP_EXIT = re.compile(r"B3 STP EXIT")
_B3_HALT = re.compile(r"B3 HALT")
_STP_ACCEPTED = re.compile(r"place_stop: accepted")
_STP_ACCEPTED_DETAIL = re.compile(
    r"place_stop: accepted\s+(?P<direction>LONG|SHORT)\s+(?P<inst>[A-Z0-9]+)\s+STP\s+[x×](?P<qty>\d+)"
    r"\s+@\s+(?P<stop>[-\d.]+)\s+orderId=(?P<order_id>\S+)\s+status=(?P<order_status>\S+)"
    r"\s+cluster=(?P<cluster>\S+)",
    re.IGNORECASE,
)
_STP_FAILED = re.compile(r"STP: place_stop FAILED|place_stop\(.*failed", re.IGNORECASE)
_STP_FAILED_DETAIL = re.compile(
    r"STP: place_stop FAILED\s+(?P<inst>[A-Z0-9]+)\s+(?P<direction>LONG|SHORT)\s+@\s+(?P<stop>[-\d.]+)"
    r"\s+cluster=(?P<cluster>\S+)",
    re.IGNORECASE,
)
_STP_DEFERRED = re.compile(r"\bSTP HOAN:", re.IGNORECASE)
_STP_DEFER_REMINDER = re.compile(r"\bcua so hoan CO CHU DICH\b|\bstop_deferred\b", re.IGNORECASE)
_STP_DEFERRED_DETAIL = re.compile(
    r"(?:STP HOAN:|B4:)\s+(?P<inst>[A-Z0-9]+)(?:/(?P<b4_cluster>\S+)|\s+(?P<direction>LONG|SHORT))"
    r"(?:\s+@\s+(?P<stop>[-\d.]+))?.*?(?:cluster=(?P<cluster>\S+)|$)",
    re.IGNORECASE,
)
_REJECTED = re.compile(r"REJECTED .* risk_sized=.*")
_ROLL_SLIP = re.compile(r"C2: Roll .* slippage=|C2: Roll complete .* slippage=")
_MANUAL_INTERVENTION = re.compile(r"\b(manual|intervention|operator|override)\b", re.IGNORECASE)
_TWS_RESTART = re.compile(
    r"\b(TWS|Gateway|IBKR)\b.*\b(restart|restarted|reconnect|reconnected|disconnect|disconnected|connection lost)\b",
    re.IGNORECASE,
)

_TEST_MARKERS = (
    "pytest-of-", "pytest-", "\\Temp\\tmp", "/tmp/", "injected ",
    "orderId=stp-", "orderId=mock-", "(stp-", "(mock-", "stp-MES-",
    "_RecordingMockBroker", "_naked_broker", "<locals>", "test_spy.csv",
    "ibkr-456", "ibkr-789",
)


def _source(path: str, process: str, fmt: str, cadence: str, retention: str) -> dict[str, str]:
    return {
        "path": path,
        "process": process,
        "format": fmt,
        "cadence": cadence,
        "retention": retention,
    }


SOURCES = {
    "live_state": _source(
        "global_index/live_state_data.js",
        "FuturesRunner.dump_state()",
        "JavaScript assignment: window.LIVE_DATA = JSON",
        "Every runner decision slot that reaches dump_state(); file is overwritten atomically",
        "No code-level retention; latest file only",
    ),
    "paper_history": _source(
        "global_index/paper_history.json",
        "FuturesRunner._record_paper_day()",
        "JSON object with epoch/account/days",
        "Upsert once per dump_state() call; same date is last-write-wins",
        "No code-level deletion or rotation observed",
    ),
    "trade_log": _source(
        "trade_log.jsonl",
        "FuturesRunner._append_trade()",
        "Append-only JSONL, one fill per line",
        "Each OPEN/CLOSE fill",
        "No code-level deletion or rotation observed",
    ),
    "slip_stats": _source(
        "slip_stats.json",
        "FuturesRunner._persist_slip_stats()",
        "JSON cumulative raw slip sums and sample counts",
        "Each C1 OPEN/CLOSE fill with measurable slip",
        "Overwritten atomically; no code-level deletion observed",
    ),
    "logs": _source(
        "scheduler_*.log and live_day_*.log",
        "global_index.run_scheduler and global_index.run_live_day logging",
        "Plain text logs",
        "Every scheduler/runner log line",
        "Daily filenames; no code-level deletion or rotation observed",
    ),
    "live_positions": _source(
        "live_positions.json",
        "FuturesRunner._persist_state()",
        "JSON current persisted positions and breaker state",
        "After state-changing runner decisions",
        "Overwritten atomically; current state only",
    ),
    "open_issues": _source(
        "/api/v1/open-issues from scheduler logs",
        "monitor.backend.open_issue_reader",
        "Read-only JSON projection",
        "On dashboard request from existing logs",
        "Derived from retained scheduler logs",
    ),
    "paper_inputs": _source(
        "monitor/paper_inputs.json",
        "monitor/operator maintained data input",
        "JSON object with c1_spec, stp_verification, tws_restart_nights, manual_interventions, roll_slippage, paper_vs_backtest",
        "Updated manually or by monitoring-only tooling when evidence is reviewed",
        "No code-level deletion or rotation observed",
    ),
    "paper_pnl_compare": _source(
        "monitor/paper_pnl_compare.json",
        "monitor/paper_pnl_compare.py",
        "JSON audit report with daily equity windows and classified paper/backtest trade matches",
        "Generated on demand by read-only monitoring audit",
        "No code-level deletion or rotation observed",
    ),
}


def _signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    paths = [
        root / "global_index" / "live_state_data.js",
        root / "global_index" / "paper_history.json",
        root / "trade_log.jsonl",
        root / "slip_stats.json",
        root / "live_positions.json",
        root / "monitor" / "paper_inputs.json",
        root / "monitor" / "paper_pnl_compare.json",
        *sorted(root.glob("scheduler_*.log")),
        *sorted(root.glob("live_day_*.log")),
    ]
    values = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        values.append((str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    return tuple(values)


def _read_json(path: Path) -> tuple[dict[str, Any], str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return {}, str(exc)
    except json.JSONDecodeError as exc:
        return {}, f"malformed JSON: {exc}"
    return value if isinstance(value, dict) else {}, None


def _read_optional_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, None
    return _read_json(path)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _parse_ts(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _fmt_ts(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _bool(value: Any) -> bool:
    return value is True


def _records(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _trade_records(path: Path) -> tuple[list[dict[str, Any]], int, str | None]:
    records: list[dict[str, Any]] = []
    malformed = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return records, malformed, str(exc)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            malformed += 1
    return records, malformed, None


def _date(value: Any) -> str | None:
    if not value:
        return None
    return str(value)[:10]


def _in_epoch(day: str | None, epoch: str | None) -> bool:
    return bool(day and (not epoch or day >= epoch))


def _normalize_exit(value: Any) -> str | None:
    reason = str(value or "").upper()
    if "MAX_HOLD" in reason:
        return "MAX_HOLD"
    if "CHANDELIER" in reason:
        return "CHANDELIER"
    if reason == "STOP" or "STP" in reason:
        return "STP"
    return None


def _tick(inst: Any) -> float | None:
    try:
        from futures.basket import BASKET
        from global_index.specs import SPECS
    except Exception:
        BASKET, SPECS = {}, {}
    contract = BASKET.get(str(inst)) or SPECS.get(str(inst))
    tick = getattr(contract, "tick", None)
    return float(tick) if tick else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _gate(key: str, title: str, status: str, evidence: str, requirement: str,
          sources: list[str], metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "evidence": evidence,
        "requirement": requirement,
        "sources": [SOURCES[name] for name in sources],
        "metrics": metrics or {},
    }


def _coverage(key: str, title: str, status: str, evidence: str,
              sources: list[str], metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "status": status,
        "evidence": evidence,
        "sources": [SOURCES[name] for name in sources],
        "metrics": metrics or {},
    }


def _slippage(records: list[dict[str, Any]], epoch: str | None) -> dict[str, Any]:
    open_ticks: list[float] = []
    stp_close_ticks: list[float] = []
    signal_close_with_stop_ref = 0
    unknown_tick = 0
    for record in records:
        day = _date(record.get("entry_day") if record.get("type") == "OPEN" else record.get("exit_day"))
        if not _in_epoch(day, epoch) or record.get("slip") is None:
            continue
        tick = _tick(record.get("inst"))
        if not tick:
            unknown_tick += 1
            continue
        ticks = float(record["slip"]) / tick
        if str(record.get("type")).upper() == "OPEN":
            open_ticks.append(ticks)
        elif str(record.get("type")).upper() == "CLOSE":
            reason = str(record.get("exit_reason") or "").upper()
            source = str(record.get("source") or "").upper()
            if reason == "STP" or source == "B3_STP_EXIT":
                stp_close_ticks.append(ticks)
            else:
                signal_close_with_stop_ref += 1
    return {
        "open_mean": _mean(open_ticks),
        "close_mean": _mean(stp_close_ticks),
        "open_n": len(open_ticks),
        "close_n": len(stp_close_ticks),
        "stp_close_mean": _mean(stp_close_ticks),
        "stp_close_n": len(stp_close_ticks),
        "signal_close_with_stop_ref": signal_close_with_stop_ref,
        "unknown_tick_records": unknown_tick,
    }


def _c1_trade_details(records: list[dict[str, Any]], epoch: str | None, limit: int = 24) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    total = 0
    for record in records:
        trade_type = str(record.get("type") or "").upper()
        if trade_type not in {"OPEN", "CLOSE"} or record.get("slip") is None:
            continue
        day = _date(record.get("entry_day") if trade_type == "OPEN" else record.get("exit_day"))
        if not _in_epoch(day, epoch):
            continue
        tick = _tick(record.get("inst"))
        slip = _number(record.get("slip"))
        ticks = slip / tick if tick and slip is not None else None
        reason = str(record.get("exit_reason") or "").upper()
        source = str(record.get("source") or "").upper()
        if trade_type == "OPEN":
            c1_scope = "OPEN"
            reference_type = "expected_entry"
            reference_price = record.get("expected_entry")
        elif reason == "STP" or source == "B3_STP_EXIT":
            c1_scope = "STP_CLOSE"
            reference_type = "expected_stop"
            reference_price = record.get("expected_stop")
        else:
            c1_scope = "EXCLUDED_CLOSE"
            reference_type = "protective_stop_reference" if record.get("expected_stop") is not None else "missing_expected_close"
            reference_price = record.get("expected_stop")
        rows.append({
            "scope": c1_scope,
            "type": trade_type,
            "inst": record.get("inst"),
            "cluster": record.get("cluster"),
            "direction": record.get("direction"),
            "entry_day": _date(record.get("entry_day")),
            "exit_day": _date(record.get("exit_day")),
            "ts": record.get("ts"),
            "status": record.get("status"),
            "contracts": record.get("contracts"),
            "filled_qty": record.get("filled_qty"),
            "reference_type": reference_type,
            "reference_price": reference_price,
            "fill_price": record.get("fill_price"),
            "slip_points": slip,
            "slip_ticks": ticks,
            "exit_reason": record.get("exit_reason"),
            "source": record.get("source"),
        })
        total += 1
    shown = rows[-limit:]
    return {"total": total, "shown": len(shown), "limit": limit, "rows": shown}


def _stp_trade_details(records: list[dict[str, Any]], epoch: str | None,
                       positions: list[dict[str, Any]], limit: int = 24) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for pos in positions:
        rows.append({
            "scope": "OPEN_POSITION",
            "inst": pos.get("inst"),
            "cluster": pos.get("cluster"),
            "direction": pos.get("direction"),
            "contracts": pos.get("contracts"),
            "entry_day": _date(pos.get("entry_day")),
            "exit_day": None,
            "entry_price": pos.get("entry_price"),
            "stop_price": pos.get("stop_price"),
            "stop_order_id": pos.get("stop_order_id"),
            "exit_pending": pos.get("exit_pending"),
            "status": "PROTECTED" if pos.get("stop_order_id") else "UNPROTECTED",
        })
    for record in records:
        if str(record.get("type")).upper() != "CLOSE":
            continue
        if not _in_epoch(_date(record.get("exit_day")), epoch):
            continue
        has_stop_ref = record.get("expected_stop") is not None
        reason = str(record.get("exit_reason") or "").upper()
        source = str(record.get("source") or "").upper()
        if reason != "STP" and source != "B3_STP_EXIT" and not has_stop_ref:
            continue
        tick = _tick(record.get("inst"))
        slip = _number(record.get("slip"))
        rows.append({
            "scope": "STP_CLOSE" if reason == "STP" or source == "B3_STP_EXIT" else "STOP_REF_CLOSE",
            "inst": record.get("inst"),
            "cluster": record.get("cluster"),
            "direction": record.get("direction"),
            "contracts": record.get("contracts"),
            "entry_day": _date(record.get("entry_day")),
            "exit_day": _date(record.get("exit_day")),
            "expected_stop": record.get("expected_stop"),
            "fill_price": record.get("fill_price"),
            "slip_ticks": slip / tick if tick and slip is not None else None,
            "order_id": record.get("order_id"),
            "perm_id": record.get("perm_id"),
            "status": record.get("status"),
            "source": record.get("source"),
            "exit_reason": record.get("exit_reason"),
        })
    shown = rows[-limit:]
    return {"total": len(rows), "shown": len(shown), "limit": limit, "rows": shown}


def _stp_log_row(kind: str, path: Path, line_no: int, day: str | None, line: str) -> dict[str, Any]:
    accepted = _STP_ACCEPTED_DETAIL.search(line)
    failed = _STP_FAILED_DETAIL.search(line)
    deferred = _STP_DEFERRED_DETAIL.search(line)
    match = accepted or failed or deferred
    groups = match.groupdict() if match else {}
    cluster = groups.get("cluster") or groups.get("b4_cluster")
    if isinstance(cluster, str):
        cluster = cluster.rstrip(")")
    reason = {
        "ACCEPTED": "Broker accepted protective STP after the defer window was no longer active.",
        "FAILED": "Broker did not accept the STP; position may be unprotected after the allowed defer window.",
        "DEFERRED": "Runner deliberately withheld same-day/too-early STP to match the validated backtest stop semantics.",
    }.get(kind, "Raw STP placement evidence.")
    return {
        "kind": kind,
        "day": day,
        "ts": line[:19] if len(line) >= 19 and line[:4].isdigit() else None,
        "path": path.name,
        "line_no": line_no,
        "inst": groups.get("inst"),
        "direction": groups.get("direction"),
        "cluster": cluster,
        "qty": int(groups["qty"]) if groups.get("qty") and str(groups["qty"]).isdigit() else None,
        "stop_price": _number(groups.get("stop")),
        "order_id": groups.get("order_id"),
        "order_status": groups.get("order_status"),
        "reason": reason,
        "raw": line[:260],
    }


def _log_summary(root: Path, epoch: str | None) -> dict[str, Any]:
    summary = {
        "cold_starts": 0,
        "b3_matches": 0,
        "b3_mismatches": 0,
        "stp_verify_lines": 0,
        "stp_exit_lines": 0,
        "b3_halt_lines": 0,
        "stp_accepted": 0,
        "stp_failed": 0,
        "stp_deferred": 0,
        "stp_defer_reminders": 0,
        "stp_placement_rows": [],
        "rejections": 0,
        "roll_slippage_lines": 0,
        "manual_intervention_lines": 0,
        "manual_intervention_days": set(),
        "tws_restart_lines": 0,
        "tws_restart_days": set(),
        "dropped_test_lines": 0,
    }
    for path in [*sorted(root.glob("scheduler_*.log")), *sorted(root.glob("live_day_*.log"))]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            day = line[:10] if len(line) >= 10 and line[:4].isdigit() else None
            if not _in_epoch(day, epoch):
                continue
            if any(marker in line for marker in _TEST_MARKERS):
                summary["dropped_test_lines"] += 1
                continue
            if _COLD_START.search(line):
                summary["cold_starts"] += 1
            if _B3_MATCH.search(line):
                summary["b3_matches"] += 1
            mismatch = _B3_MISMATCH.search(line)
            if mismatch:
                summary["b3_mismatches"] += int(mismatch.group("count"))
            if _STP_VERIFY.search(line):
                summary["stp_verify_lines"] += 1
            if _STP_EXIT.search(line):
                summary["stp_exit_lines"] += 1
            if _B3_HALT.search(line):
                summary["b3_halt_lines"] += 1
            if _STP_ACCEPTED.search(line):
                summary["stp_accepted"] += 1
                summary["stp_placement_rows"].append(_stp_log_row("ACCEPTED", path, idx, day, line))
            if _STP_FAILED.search(line):
                summary["stp_failed"] += 1
                summary["stp_placement_rows"].append(_stp_log_row("FAILED", path, idx, day, line))
            if _STP_DEFERRED.search(line):
                summary["stp_deferred"] += 1
                summary["stp_placement_rows"].append(_stp_log_row("DEFERRED", path, idx, day, line))
            elif _STP_DEFER_REMINDER.search(line):
                summary["stp_defer_reminders"] += 1
            if _REJECTED.search(line):
                summary["rejections"] += 1
            if _ROLL_SLIP.search(line):
                summary["roll_slippage_lines"] += 1
            if _MANUAL_INTERVENTION.search(line):
                summary["manual_intervention_lines"] += 1
                if day:
                    summary["manual_intervention_days"].add(day)
            if _TWS_RESTART.search(line):
                summary["tws_restart_lines"] += 1
                if day:
                    summary["tws_restart_days"].add(day)
    summary["manual_intervention_days"] = sorted(summary["manual_intervention_days"])
    summary["tws_restart_days"] = sorted(summary["tws_restart_days"])
    return summary


def _epoch_records(records: list[dict[str, Any]], epoch: str | None) -> list[dict[str, Any]]:
    return [
        record for record in records
        if _in_epoch(_date(record.get("entry_day") or record.get("exit_day")), epoch)
    ]


def _latest_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshots = payload.get("snapshots") if isinstance(payload.get("snapshots"), list) else []
    return snapshots[-1] if snapshots and isinstance(snapshots[-1], dict) else {}


def _trade_denominators(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_inst: dict[str, int] = {}
    by_cluster: dict[str, int] = {}
    for record in records:
        inst = str(record.get("inst") or "UNKNOWN")
        cluster = str(record.get("cluster") or "UNKNOWN")
        by_inst[inst] = by_inst.get(inst, 0) + 1
        by_cluster[cluster] = by_cluster.get(cluster, 0) + 1
    return {"by_inst": dict(sorted(by_inst.items())), "by_cluster": dict(sorted(by_cluster.items()))}


def _same_day(records: list[dict[str, Any]]) -> dict[str, int]:
    same_day = 0
    multi_day = 0
    unknown = 0
    for record in records:
        if str(record.get("type")).upper() != "CLOSE":
            continue
        entry_day, exit_day = _date(record.get("entry_day")), _date(record.get("exit_day"))
        if not entry_day or not exit_day:
            unknown += 1
        elif entry_day == exit_day:
            same_day += 1
        else:
            multi_day += 1
    return {"same_day": same_day, "multi_day": multi_day, "unknown": unknown}


def _c1_status(slip: dict[str, Any], spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    min_n = int(spec.get("min_n") or 0) if isinstance(spec.get("min_n"), int) else None
    max_mean = _number(spec.get("max_mean_ticks"))
    scope = str(spec.get("scope") or "").lower()
    close_scope = str(spec.get("close_scope") or "stp_only").lower()
    use_abs = spec.get("use_absolute") is not False
    metrics = {**slip, "spec": spec if spec else None}
    base = (
        f"OPEN {_fmt_mean(slip['open_mean'])} N={slip['open_n']} | "
        f"STP CLOSE {_fmt_mean(slip['stp_close_mean'])} N={slip['stp_close_n']} | "
        f"signal/market CLOSE excluded {slip['signal_close_with_stop_ref']}"
    )

    if slip["open_n"] == 0 and slip["stp_close_n"] == 0:
        return "MISSING", base, metrics
    if not min_n or max_mean is None or scope not in {"separate", "combined"} or close_scope != "stp_only":
        return "SPEC_GAP", base, metrics

    values: list[float] = []
    if slip["open_mean"] is not None:
        values.append(abs(slip["open_mean"]) if use_abs else slip["open_mean"])
    if slip["stp_close_mean"] is not None:
        values.append(abs(slip["stp_close_mean"]) if use_abs else slip["stp_close_mean"])

    if scope == "separate":
        enough = slip["open_n"] >= min_n and slip["stp_close_n"] >= min_n
        passes = enough and all(value <= max_mean for value in values)
    else:
        total_n = slip["open_n"] + slip["stp_close_n"]
        enough = total_n >= min_n
        combined = _mean([value for value in values if value is not None])
        metrics["combined_mean"] = combined
        passes = enough and combined is not None and combined <= max_mean

    if not enough:
        return "PENDING", f"{base} | need N>={min_n} ({scope})", metrics
    return ("PASS" if passes else "BREACH", f"{base} | limit {max_mean:g} ticks ({scope})", metrics)


def _stp_input_status(items: list[dict[str, Any]], logs: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if not items:
        return (
            "SPEC_GAP" if logs["stp_verify_lines"] or logs["stp_exit_lines"] or logs["b3_halt_lines"] else "MISSING",
            f"STP-VERIFY {logs['stp_verify_lines']} | STP EXIT {logs['stp_exit_lines']} | B3 HALT {logs['b3_halt_lines']} | placement accepted {logs['stp_accepted']} failed {logs['stp_failed']}",
            {
                "stp_verify_lines": logs["stp_verify_lines"],
                "stp_exit_lines": logs["stp_exit_lines"],
                "b3_halt_lines": logs["b3_halt_lines"],
                "stp_accepted": logs["stp_accepted"],
                "stp_failed": logs["stp_failed"],
            },
        )
    false_halts = sum(1 for item in items if _bool(item.get("false_halt")))
    double_stp = sum(1 for item in items if _bool(item.get("double_stp")))
    unverified = sum(1 for item in items if item.get("verified") is not True)
    status = "BREACH" if false_halts or double_stp or unverified else "PASS"
    records = [{
        "date": item.get("date"),
        "verified": item.get("verified") is True,
        "false_halt": _bool(item.get("false_halt")),
        "double_stp": _bool(item.get("double_stp")),
        "evidence": item.get("evidence"),
    } for item in items]
    return (
        status,
        f"{len(items)} structured STP check(s), false_halt {false_halts}, double_stp {double_stp}, unverified {unverified}",
        {"checks": len(items), "false_halts": false_halts, "double_stp": double_stp, "unverified": unverified,
         "records": records},
    )


def _tws_input_status(items: list[dict[str, Any]], spec: dict[str, Any], logs: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    min_nights = int(spec.get("min_nights") or 0) if isinstance(spec.get("min_nights"), int) else None
    proven = [
        item for item in items
        if _bool(item.get("restart_proven")) and _bool(item.get("runner_resumed")) and _bool(item.get("broker_verified"))
    ]
    metrics = {
        "restart_nights": len(proven),
        "required_nights": min_nights,
        "records": len(items),
        "candidate_log_lines": logs["tws_restart_lines"],
        "candidate_days": logs["tws_restart_days"],
    }
    if not min_nights:
        return (
            "SPEC_GAP",
            f"{len(proven)} proven restart night(s), {logs['tws_restart_lines']} connectivity-restart candidate line(s); required nights not specified",
            metrics,
        )
    status = "PASS" if len(proven) >= min_nights else "PENDING"
    return status, f"{len(proven)} / {min_nights} proven restart night(s)", metrics


def _manual_input_status(items: list[dict[str, Any]], logs: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if not items:
        return (
            "NEEDS_DECISION",
            f"{logs['manual_intervention_lines']} operator-action candidate line(s) across {len(logs['manual_intervention_days'])} day(s); no structured ledger is defined",
            {"candidate_log_lines": logs["manual_intervention_lines"], "candidate_days": logs["manual_intervention_days"]},
        )
    unresolved = sum(1 for item in items if item.get("resolution_status") != "resolved" or item.get("post_action_verified") is not True)
    return (
        "BREACH" if unresolved else "OBSERVED",
        f"{len(items)} manual action record(s), {unresolved} unresolved/unverified",
        {"records": len(items), "unresolved": unresolved},
    )


def _roll_input_status(items: list[dict[str, Any]], logs: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    ticks = [_number(item.get("ticks")) for item in items]
    ticks = [tick for tick in ticks if tick is not None]
    if not items:
        return "MISSING", f"{logs['roll_slippage_lines']} roll slippage log line(s)", {"roll_slippage_lines": logs["roll_slippage_lines"]}
    return "OBSERVED", f"{len(items)} structured roll slippage record(s), mean {_fmt_mean(_mean(ticks))}", {"records": len(items), "mean_ticks": _mean(ticks)}


def _required_fill_fields(record: dict[str, Any]) -> set[str]:
    required = {"type", "inst", "cluster", "direction", "contracts", "filled_qty", "status", "fill_price", "ts"}
    if str(record.get("type")).upper() == "OPEN":
        required.update({"entry_day", "expected_entry"})
    elif str(record.get("type")).upper() == "CLOSE":
        required.update({"entry_day", "exit_day", "pnl_sized"})
    return required


def _missing_fill_fields_for(record: dict[str, Any]) -> list[str]:
    return sorted(key for key in _required_fill_fields(record) if record.get(key) in {None, ""})


def _missing_fill_fields(records: list[dict[str, Any]]) -> int:
    return sum(1 for record in records if _missing_fill_fields_for(record))


def _fill_quality_trade_rows(records: list[dict[str, Any]], limit: int = 30) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for record in records:
        contracts = _number(record.get("contracts"))
        filled_qty = _number(record.get("filled_qty"))
        partial = filled_qty is not None and contracts not in {None, 0} and filled_qty < contracts
        status = str(record.get("status") or "").upper() or "UNKNOWN"
        failed = status not in {"UNKNOWN", "FILLED", "PARTIAL"}
        tick = _tick(record.get("inst"))
        slip = _number(record.get("slip"))
        trade_type = str(record.get("type") or "").upper()
        reference_price = record.get("expected_entry") if trade_type == "OPEN" else record.get("expected_stop")
        rows.append({
            "type": trade_type,
            "inst": record.get("inst"),
            "cluster": record.get("cluster"),
            "direction": record.get("direction"),
            "entry_day": _date(record.get("entry_day")),
            "exit_day": _date(record.get("exit_day")),
            "contracts": contracts,
            "filled_qty": filled_qty,
            "status": status,
            "partial": partial,
            "failed_or_cancelled": failed,
            "missing_fields": _missing_fill_fields_for(record),
            "fill_price": record.get("fill_price"),
            "reference_price": reference_price,
            "reference_type": "expected_entry" if trade_type == "OPEN" else "expected_stop",
            "slip_points": slip,
            "slip_ticks": slip / tick if tick and slip is not None else None,
            "pnl_sized": record.get("pnl_sized"),
            "ts": record.get("ts"),
        })
    shown = rows[-limit:]
    return {"total": len(rows), "shown": len(shown), "limit": limit, "rows": shown}


def _fill_quality_status(records: list[dict[str, Any]], malformed: int,
                         spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    fills = len(records)
    partials = sum(
        1 for record in records
        if record.get("filled_qty") is not None and record.get("contracts")
        and float(record.get("filled_qty") or 0) < float(record.get("contracts") or 0)
    )
    failed = sum(1 for record in records if str(record.get("status") or "").upper() not in {"", "FILLED", "PARTIAL"})
    missing_fields = _missing_fill_fields(records)
    max_contracts = max([float(record.get("contracts") or 0) for record in records] or [0.0])
    min_fills = int(spec.get("min_fills") or 0) if isinstance(spec.get("min_fills"), int) else None
    max_partial_rate = _number(spec.get("max_partial_rate"))
    max_failed = int(spec.get("max_failed_or_cancelled") or 0) if isinstance(spec.get("max_failed_or_cancelled"), int) else None
    require_complete = spec.get("require_complete_fields") is True
    max_contracts_tested = _number(spec.get("max_contracts_tested"))
    retest_when_contracts_gt = _number(spec.get("retest_when_contracts_gt"))
    partial_rate = partials / fills if fills else None
    metrics = {
        "fills": fills,
        "partials": partials,
        "partial_rate": partial_rate,
        "failed_or_cancelled": failed,
        "malformed_trade_log_lines": malformed,
        "missing_required_field_rows": missing_fields,
        "max_contracts_observed": max_contracts,
        "max_contracts_tested": max_contracts_tested,
        "retest_when_contracts_gt": retest_when_contracts_gt,
        "spec": spec if spec else None,
        "trade_samples": _fill_quality_trade_rows(records),
        "description": (
            "Fill quality validates broker execution history recorded in trade_log.jsonl. "
            "It is meaningful only after enough real OPEN/CLOSE fill history exists."
        ),
        "metric_descriptions": {
            "fills": "Count of OPEN/CLOSE fill records in the active paper epoch.",
            "partials": "Records where filled_qty is lower than requested contracts.",
            "partial_rate": "partials / fills; with current quantity=1 this mostly proves single-contract behavior only.",
            "failed_or_cancelled": "Fill records whose status is not FILLED/PARTIAL/blank.",
            "malformed_trade_log_lines": "JSONL lines that could not be parsed as retained fill history.",
            "missing_required_field_rows": "Fill records missing fields needed for later audit, including identity, size, fill price, timestamp, and exit P&L for CLOSE rows.",
            "max_contracts_observed": "Largest contracts value seen in the paper-epoch fill records.",
        },
        "status_rules": [
            "MISSING: no OPEN/CLOSE fill history exists in the paper epoch.",
            "SPEC_GAP: fill_quality_spec is absent or lacks min_fills/max_partial_rate/max_failed_or_cancelled.",
            "PENDING: fill history exists and has no breach, but sample count is below min_fills.",
            "PASS: fills >= min_fills, failed/cancelled <= limit, partial_rate <= limit, malformed lines = 0, and required fields are complete when enabled.",
            "BREACH: failed/cancelled exceeds limit, partial_rate exceeds limit, malformed lines exist, or required fields are missing when enabled.",
        ],
        "scale_note": (
            "Current paper history is limited to contracts/quantity=1. Fill quality must be retested before this evidence is reused at larger size."
        ),
    }
    if not fills:
        return "MISSING", "No fill history in paper epoch", metrics
    if not spec or min_fills is None or max_partial_rate is None or max_failed is None:
        return "SPEC_GAP", f"{fills} fill record(s), {partials} partial, {failed} failed/cancelled; fill_quality_spec missing", metrics
    breaches = []
    if failed > max_failed:
        breaches.append(f"failed/cancelled {failed}>{max_failed}")
    if partial_rate is not None and partial_rate > max_partial_rate:
        breaches.append(f"partial_rate {partial_rate:.4f}>{max_partial_rate:g}")
    if malformed:
        breaches.append(f"malformed lines {malformed}")
    if require_complete and missing_fields:
        breaches.append(f"missing required fields {missing_fields}")
    if breaches:
        return "BREACH", f"{fills} fill record(s); " + " | ".join(breaches), metrics
    if fills < min_fills:
        return "PENDING", f"{fills} / {min_fills} fill record(s), {partials} partial, {failed} failed/cancelled", metrics
    return "PASS", f"{fills} / {min_fills} fill record(s), {partials} partial, {failed} failed/cancelled", metrics


def _stp_trade_identity(record: dict[str, Any], stop_price: float | None = None) -> str:
    stop = _number(stop_price if stop_price is not None else record.get("expected_stop") or record.get("stop_price"))
    stop_part = f"{stop:.2f}" if stop is not None else "no-stop"
    return ":".join(str(part or "?") for part in [
        _date(record.get("entry_day")), record.get("inst"), record.get("cluster"), record.get("direction"), stop_part
    ])


def _stp_arm_at(trade: dict[str, Any]) -> dt.datetime | None:
    entry_day = _date(trade.get("entry_day"))
    arm = _STP_ARM_BY_CLUSTER.get(str(trade.get("cluster") or ""))
    if not entry_day or not arm:
        return None
    tz_name, hour, minute = arm
    try:
        day = dt.date.fromisoformat(entry_day) + dt.timedelta(days=1)
        local = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=ZoneInfo(tz_name))
    except ValueError:
        return None
    return local.astimezone(dt.timezone.utc)


def _stp_close_timing(trade: dict[str, Any]) -> dict[str, Any]:
    close_at = _parse_ts(trade.get("close_ts"))
    arm_at = _stp_arm_at(trade)
    hours_before = None
    relation = None
    if close_at is not None and arm_at is not None:
        hours_before = (arm_at - close_at).total_seconds() / 3600
        relation = "BEFORE_ARM" if hours_before > 0 else "AFTER_ARM"
    return {
        "arm_at": _fmt_ts(arm_at),
        "close_at": _fmt_ts(close_at),
        "hours_before_arm": hours_before,
        "arm_relation": relation,
    }


def _stp_reference_trades(records: list[dict[str, Any]], positions: list[dict[str, Any]],
                          epoch: str | None) -> list[dict[str, Any]]:
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        if str(record.get("type")).upper() != "OPEN" or not _in_epoch(_date(record.get("entry_day")), epoch):
            continue
        key = (_date(record.get("entry_day")), record.get("inst"), record.get("cluster"), record.get("direction"))
        by_key[key] = {
            "entry_day": key[0],
            "inst": key[1],
            "cluster": key[2],
            "direction": key[3],
            "contracts": record.get("contracts"),
            "filled_qty": record.get("filled_qty"),
            "open_ts": record.get("ts"),
            "open_status": record.get("status"),
            "expected_stop": None,
            "exit_day": None,
            "close_ts": None,
            "close_status": None,
            "close_reason": None,
        }
    for record in records:
        if str(record.get("type")).upper() != "CLOSE" or not _in_epoch(_date(record.get("entry_day")), epoch):
            continue
        key = (_date(record.get("entry_day")), record.get("inst"), record.get("cluster"), record.get("direction"))
        item = by_key.get(key)
        if not item:
            continue
        if record.get("expected_stop") is not None:
            item["expected_stop"] = _number(record.get("expected_stop"))
        item["exit_day"] = _date(record.get("exit_day"))
        item["close_ts"] = record.get("ts")
        item["close_status"] = record.get("status")
        item["close_reason"] = record.get("exit_reason") or record.get("source") or "signal/market close (trade_log has no exit_reason)"
    for pos in positions:
        key = (_date(pos.get("entry_day")), pos.get("inst"), pos.get("cluster"), pos.get("direction"))
        item = by_key.get(key)
        if item and item.get("expected_stop") is None and pos.get("stop_price") is not None:
            item["expected_stop"] = _number(pos.get("stop_price"))
    return list(by_key.values())


def _stop_match(row: dict[str, Any], trade: dict[str, Any]) -> bool:
    if row.get("inst") != trade.get("inst") or row.get("cluster") != trade.get("cluster"):
        return False
    if row.get("direction") and row.get("direction") != trade.get("direction"):
        return False
    row_stop = _number(row.get("stop_price"))
    trade_stop = _number(trade.get("expected_stop"))
    if row_stop is None or trade_stop is None:
        return True
    tolerance = max((_tick(row.get("inst")) or 0.01) * 1.1, 0.05)
    return abs(row_stop - trade_stop) <= tolerance


def _match_stp_trade(row: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [trade for trade in trades if _stop_match(row, trade)]
    if row.get("day"):
        same_or_near = [
            trade for trade in candidates
            if trade.get("entry_day") == row.get("day") or abs((dt.date.fromisoformat(trade["entry_day"]) - dt.date.fromisoformat(row["day"])).days) <= 1
        ]
        if same_or_near:
            candidates = same_or_near
    return candidates[0] if len(candidates) == 1 else None


def _enrich_stp_rows(rows: list[dict[str, Any]], trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        enriched = dict(row)
        trade = _match_stp_trade(row, trades)
        if trade:
            enriched["trade_id"] = _stp_trade_identity(trade, trade.get("expected_stop") or row.get("stop_price"))
            enriched["entry_day"] = trade.get("entry_day")
            enriched["exit_day"] = trade.get("exit_day")
            enriched["contracts"] = trade.get("contracts")
            enriched["filled_qty"] = trade.get("filled_qty")
            if enriched.get("qty") is None:
                enriched["qty"] = trade.get("filled_qty") or trade.get("contracts")
            enriched["match_status"] = "MATCHED_TRADE"
        else:
            enriched["trade_id"] = None
            enriched["match_status"] = "UNMATCHED_TO_PAPER_OPEN"
        out.append(enriched)
    return out


def _stp_route_reconcile(rows: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    deferred = [row for row in rows if row.get("kind") == "DEFERRED"]
    accepted = [row for row in rows if row.get("kind") == "ACCEPTED"]
    failed = [row for row in rows if row.get("kind") == "FAILED"]
    reconciled = []
    counts: dict[str, int] = {}
    for row in deferred:
        trade = _match_stp_trade(row, trades)
        trade_id = row.get("trade_id") or (_stp_trade_identity(trade, trade.get("expected_stop") or row.get("stop_price")) if trade else None)
        matching_accepted = [
            item for item in accepted
            if trade_id and item.get("trade_id") == trade_id
        ]
        matching_failed = [
            item for item in failed
            if trade_id and item.get("trade_id") == trade_id
        ]
        timing = _stp_close_timing(trade) if trade else {}
        if matching_accepted:
            outcome = "ACCEPTED_AFTER_DEFER"
            detail = f"accepted {matching_accepted[0].get('path')}:{matching_accepted[0].get('line_no')}"
        elif matching_failed:
            outcome = "FAILED_AFTER_DEFER"
            detail = f"failed {matching_failed[0].get('path')}:{matching_failed[0].get('line_no')}"
        elif trade and trade.get("exit_day") and timing.get("arm_relation") == "BEFORE_ARM":
            outcome = "CLOSED_BEFORE_ARM"
            hours = _number(timing.get("hours_before_arm"))
            when = timing.get("close_at") or trade.get("exit_day")
            delta = f"{hours:.2f}h before arm" if hours is not None else "before arm"
            detail = f"closed {when} ({delta}); reason: {trade.get('close_reason')}"
        else:
            outcome = "NO_ACCEPT_FOUND"
            detail = "no accepted STP or close record matched this deferred route"
        counts[outcome] = counts.get(outcome, 0) + 1
        reconciled.append({
            "trade_id": trade_id,
            "inst": row.get("inst"),
            "cluster": row.get("cluster"),
            "direction": row.get("direction"),
            "entry_day": trade.get("entry_day") if trade else row.get("day"),
            "exit_day": trade.get("exit_day") if trade else None,
            "close_at": timing.get("close_at"),
            "arm_at": timing.get("arm_at"),
            "hours_before_arm": timing.get("hours_before_arm"),
            "arm_relation": timing.get("arm_relation"),
            "close_reason": trade.get("close_reason") if trade else None,
            "qty": row.get("qty") or (trade.get("filled_qty") if trade else None) or (trade.get("contracts") if trade else None),
            "stop_price": row.get("stop_price"),
            "deferred_at": f"{row.get('path')}:{row.get('line_no')}",
            "outcome": outcome,
            "detail": detail,
        })
    unmatched_failed = [row for row in failed if not row.get("trade_id")]
    return {
        "counts": counts,
        "rows": reconciled,
        "unmatched_failed": unmatched_failed,
    }


def _stp_placement_status(logs: dict[str, Any], spec: dict[str, Any],
                          records: list[dict[str, Any]], positions: list[dict[str, Any]],
                          epoch: str | None) -> tuple[str, str, dict[str, Any]]:
    accepted = int(logs.get("stp_accepted") or 0)
    failed = int(logs.get("stp_failed") or 0)
    deferred = int(logs.get("stp_deferred") or 0)
    defer_reminders = int(logs.get("stp_defer_reminders") or 0)
    rows = logs.get("stp_placement_rows") if isinstance(logs.get("stp_placement_rows"), list) else []
    trades = _stp_reference_trades(records, positions, epoch)
    enriched_rows = _enrich_stp_rows(rows, trades)
    reconcile = _stp_route_reconcile(enriched_rows, trades)
    matched_failed = sum(1 for row in enriched_rows if row.get("kind") == "FAILED" and row.get("trade_id"))
    unmatched_failed = sum(1 for row in enriched_rows if row.get("kind") == "FAILED" and not row.get("trade_id"))
    min_accepted = int(spec.get("min_accepted") or 0) if isinstance(spec.get("min_accepted"), int) else None
    max_failed = int(spec.get("max_failed") or 0) if isinstance(spec.get("max_failed"), int) else None
    require_defer_rule = spec.get("require_defer_rule") is True
    defer_rule = spec.get("defer_rule") if isinstance(spec.get("defer_rule"), str) else (
        "Deferred stop clusters arm 14 hours after the next session boundary in that sleeve's own timezone."
    )
    metrics = {
        "accepted": accepted,
        "failed": failed,
        "failed_matched_to_trade": matched_failed,
        "failed_unmatched_to_trade": unmatched_failed,
        "deferred": deferred,
        "defer_reminders": defer_reminders,
        "min_accepted": min_accepted,
        "max_failed": max_failed,
        "spec": spec if spec else None,
        "route_reconcile": reconcile,
        "placement_samples": {
            "total": len(enriched_rows),
            "shown": min(len(enriched_rows), 30),
            "limit": 30,
            "rows": enriched_rows[-30:],
        },
        "description": (
            "Stop placement validates whether paper/live records the protective STP lifecycle after an OPEN: "
            "intentional defer first, then broker acceptance after the defer window, with any broker rejection treated as a breach."
        ),
        "backtest_divergence": (
            "Validated backtest stop logic does not stop a new swing/NKD entry on the entry day. "
            "Paper/live therefore deliberately withholds same-day/too-early broker STP placement; immediate STP after OPEN "
            "would be a stricter live path and a known divergence from the tested engine."
        ),
        "defer_rule": defer_rule,
        "arm_times": [
            "roska4_swing: arm at 14:00 America/New_York on the day after entry; first trading slot is normally 14:05 ET.",
            "global_nkd: arm at 14:00 Asia/Tokyo on the day after entry; this maps around 01:00 ET in summer and 00:00 ET in winter.",
            "roska4_stress: not deferred; same-session event model, so missing stop is not hidden as expected defer.",
        ],
        "metric_descriptions": {
            "accepted": "Log lines where IBKR accepted a protective STP order.",
            "failed": "Log lines where stop placement failed after the runner attempted to arm protection; dashboard also marks whether each line matches a paper trade id.",
            "deferred": "STP HOAN route-decision lines emitted after an OPEN fill whose broker stop is intentionally deferred.",
            "defer_reminders": "B4 reminder/reconcile lines while a previously deferred position is still inside the stop-free window; not counted as deferred opens.",
            "defer_rule": "The stop-free window used to keep paper/live aligned with backtest stop semantics.",
            "backtest_divergence": "Why 'no immediate STP after OPEN' is expected for swing/NKD and must be shown separately from failures.",
        },
        "status_rules": [
            "MISSING: no accepted, failed, or deferred STP placement evidence exists in the paper epoch.",
            "SPEC_GAP: stp_placement_spec is absent or lacks min_accepted/max_failed/defer-rule confirmation.",
            "PENDING: placement/defer evidence exists and no failure breached limits, but accepted samples are below min_accepted.",
            "PASS: accepted >= min_accepted, failed <= max_failed, and the active spec confirms the 14h per-sleeve defer rule.",
            "BREACH: trade-matched failed placement exceeds max_failed, or a non-deferred position is missing protection after its arm window.",
        ],
    }
    if not rows and not accepted and not failed and not deferred:
        return "MISSING", "No STP placement/defer evidence in paper epoch", metrics
    if not spec or min_accepted is None or max_failed is None or not require_defer_rule:
        return "SPEC_GAP", (
            f"{accepted} accepted, {failed} failed, {deferred} deferred; stp_placement_spec missing or incomplete"
        ), metrics
    if matched_failed > max_failed:
        return "BREACH", f"{accepted} accepted, {matched_failed}>{max_failed} trade-matched failed STP placement line(s), {deferred} deferred", metrics
    if accepted < min_accepted:
        suffix = f", {unmatched_failed} unmatched failed log line(s)" if unmatched_failed else ""
        return "PENDING", f"{accepted} / {min_accepted} accepted STP line(s), {matched_failed} matched failed, {deferred} deferred{suffix}", metrics
    suffix = f", {unmatched_failed} unmatched failed log line(s)" if unmatched_failed else ""
    return "PASS", f"{accepted} / {min_accepted} accepted STP line(s), {matched_failed} matched failed, {deferred} deferred{suffix}", metrics


def _divergence_pct(actual: float | None, expected: float | None, account: float | None = None) -> float | None:
    denom = account if account not in {None, 0} else expected
    if actual is None or expected is None or denom in {None, 0}:
        return None
    return (actual - expected) / denom


def _trade_compare_summary(compare: dict[str, Any]) -> dict[str, Any] | None:
    trade_filter = compare.get("trade_filter") if isinstance(compare.get("trade_filter"), dict) else {}
    classified = trade_filter.get("classified") if isinstance(trade_filter.get("classified"), dict) else {}
    rows = classified.get("rows") if isinstance(classified.get("rows"), list) else []
    counts = classified.get("counts") if isinstance(classified.get("counts"), dict) else {}
    if not rows and not counts:
        return None
    return {
        "counts": counts,
        "unresolved": int(classified.get("unresolved") or 0),
        "shown": min(len(rows), 24),
        "total": len(rows),
        "rows": rows[:24],
        "curve_generated": (compare.get("convention") or {}).get("curve_generated") if isinstance(compare.get("convention"), dict) else None,
        "daily": compare.get("daily") if isinstance(compare.get("daily"), list) else [],
        "notes": compare.get("notes") if isinstance(compare.get("notes"), list) else [],
    }


def _paper_vs_backtest_status(live_pvb: dict[str, Any], items: list[dict[str, Any]],
                              account: float | None, compare: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    trade_compare = _trade_compare_summary(compare)
    complete_items = []
    for item in items:
        actual = _number(item.get("actual_equity"))
        expected = _number(item.get("expected_equity"))
        if actual is None or expected is None:
            continue
        complete_items.append({
            "date": _date(item.get("date")),
            "actual_equity": actual,
            "expected_equity": expected,
            "divergence_pct": _number(item.get("divergence_pct")) if item.get("divergence_pct") is not None else _divergence_pct(actual, expected, account),
            "evidence": item.get("evidence"),
        })
    if complete_items:
        latest = complete_items[-1]
        timing = (trade_compare or {}).get("counts", {}).get("KNOWN_EXIT_TIMING_DRIFT", 0)
        unresolved = (trade_compare or {}).get("unresolved", 0)
        suffix = f"; trade compare timing_drift {timing} unresolved {unresolved}" if trade_compare else ""
        return (
            "OBSERVED",
            f"structured daily compare {len(complete_items)} record(s); latest actual {latest['actual_equity']} expected {latest['expected_equity']} divergence {latest['divergence_pct']}{suffix}",
            {"source_kind": "paper_inputs", "records": complete_items, "latest": latest, "trade_compare": trade_compare},
        )

    actual = _number(live_pvb.get("actual_equity"))
    expected = _number(live_pvb.get("expected_equity"))
    if actual is not None and expected is not None:
        metrics = dict(live_pvb)
        metrics["divergence_pct"] = _number(live_pvb.get("divergence_pct")) if live_pvb.get("divergence_pct") is not None else _divergence_pct(actual, expected, account)
        metrics["source_kind"] = "live_state"
        metrics["trade_compare"] = trade_compare
        return (
            "OBSERVED",
            f"actual {actual} | expected {expected} | divergence {metrics.get('divergence_pct')}",
            metrics,
        )
    if actual is not None or expected is not None:
        metrics = dict(live_pvb)
        metrics["source_kind"] = "live_state_incomplete"
        metrics["structured_records"] = len(items)
        metrics["trade_compare"] = trade_compare
        return (
            "NEEDS_DECISION",
            f"actual {actual if actual is not None else '--'} | expected {expected if expected is not None else '--'} | structured compare missing",
            metrics,
        )
    return (
        "MISSING",
        "No complete paper-vs-backtest comparison source",
        {"source_kind": "missing", "structured_records": len(items), "live_state": live_pvb, "trade_compare": trade_compare},
    )


def _coverage_items(root: Path, payload: dict[str, Any], history: dict[str, Any],
                    records: list[dict[str, Any]], logs: dict[str, Any],
                    epoch: str | None, paper_inputs: dict[str, Any], paper_compare: dict[str, Any],
                    malformed_trades: int) -> list[dict[str, Any]]:
    latest = _latest_snapshot(payload)
    epoch_records = _epoch_records(records, epoch)
    pvb = latest.get("paper_vs_backtest") if isinstance(latest.get("paper_vs_backtest"), dict) else {}
    op_status = latest.get("operational_status") if isinstance(latest.get("operational_status"), dict) else {}
    fill_records = [r for r in epoch_records if str(r.get("type")).upper() in {"OPEN", "CLOSE"}]
    fill_status, fill_evidence, fill_metrics = _fill_quality_status(
        fill_records,
        malformed_trades,
        paper_inputs.get("fill_quality_spec") if isinstance(paper_inputs.get("fill_quality_spec"), dict) else {},
    )
    denominators = _trade_denominators(fill_records)
    duration = _same_day(fill_records)
    live_positions, live_positions_error = _read_json(root / "live_positions.json")
    positions = live_positions.get("positions") if isinstance(live_positions.get("positions"), list) else []
    stp_status, stp_evidence, stp_metrics = _stp_placement_status(
        logs,
        paper_inputs.get("stp_placement_spec") if isinstance(paper_inputs.get("stp_placement_spec"), dict) else {},
        epoch_records,
        positions,
        epoch,
    )
    protected = sum(1 for pos in positions if pos.get("stop_order_id"))
    open_issues = read_open_issues(root)
    issues = open_issues.get("issues") if isinstance(open_issues.get("issues"), list) else []
    manual_status, manual_evidence, manual_metrics = _manual_input_status(
        _records(paper_inputs.get("manual_interventions")), logs
    )
    roll_status, roll_evidence, roll_metrics = _roll_input_status(
        _records(paper_inputs.get("roll_slippage")), logs
    )
    regime_freshness = op_status.get("regime_freshness") if isinstance(op_status.get("regime_freshness"), dict) else {}
    model_age = op_status.get("model_age") if isinstance(op_status.get("model_age"), dict) else {}
    refreeze = op_status.get("refreeze") if isinstance(op_status.get("refreeze"), dict) else {}
    positions_status = op_status.get("positions") if isinstance(op_status.get("positions"), dict) else {}
    pvb_status, pvb_evidence, pvb_metrics = _paper_vs_backtest_status(
        pvb, _records(paper_inputs.get("paper_vs_backtest")), _number(history.get("account")), paper_compare
    )

    return [
        _coverage(
            "paper_vs_backtest", "Paper P&L vs backtest",
            pvb_status,
            pvb_evidence,
            ["live_state", "paper_history", "paper_inputs", "paper_pnl_compare"],
            pvb_metrics,
        ),
        _coverage(
            "fill_quality", "Fill quality",
            fill_status,
            fill_evidence,
            ["trade_log", "live_state"],
            fill_metrics,
        ),
        _coverage(
            "stp_placement", "STP placement after OPEN",
            stp_status,
            stp_evidence,
            ["logs", "paper_inputs"],
            stp_metrics,
        ),
        _coverage(
            "state_persist", "State persist after decisions",
            "BREACH" if positions_status.get("persist_match") is False else "OBSERVED" if positions_status else "MISSING",
            f"persist_match={positions_status.get('persist_match', '--')} | live_positions count={len(positions)}",
            ["live_state", "live_positions"],
            {"operational_positions": positions_status, "live_positions_error": live_positions_error},
        ),
        _coverage(
            "rejections", "Rejected signals and cap blocks",
            "OBSERVED" if logs["rejections"] else "MISSING",
            f"{logs['rejections']} rejection log line(s) in paper epoch",
            ["logs", "live_state"],
            {"rejections": logs["rejections"]},
        ),
        _coverage(
            "runner_freshness", "Runner evidence freshness",
            "OBSERVED" if payload.get("snapshots") else "MISSING",
            f"{len(payload.get('snapshots') or [])} runner-state snapshot(s) projected",
            ["live_state"],
            {"snapshot_count": len(payload.get("snapshots") or [])},
        ),
        _coverage(
            "data_freshness", "Data freshness gates",
            "BREACH" if model_age.get("status") in {"URGENT", "HARD"} or regime_freshness.get("status") not in {None, "OK"} else "OBSERVED",
            f"regime={regime_freshness.get('status', '--')} | model={model_age.get('status', '--')} | refreeze_pending={refreeze.get('pending', '--')}",
            ["live_state"],
            {"regime_freshness": regime_freshness, "model_age": model_age, "refreeze": refreeze},
        ),
        _coverage(
            "current_protection", "Current position protection",
            "BREACH" if positions and protected < len(positions) else "OBSERVED" if positions else "MISSING",
            f"{protected}/{len(positions)} persisted position(s) have stop_order_id",
            ["live_positions"],
            {"positions": len(positions), "protected": protected, "live_positions_error": live_positions_error},
        ),
        _coverage(
            "open_incidents", "Operational blockers from open issues",
            "BREACH" if issues else "OBSERVED",
            f"{len(issues)} open issue(s)",
            ["open_issues", "logs"],
            {"issue_keys": [issue.get("key") for issue in issues]},
        ),
        _coverage(
            "roll_slippage", "Roll / C2 slippage",
            roll_status,
            roll_evidence,
            ["logs", "paper_inputs"],
            roll_metrics,
        ),
        _coverage(
            "manual_intervention", "Manual intervention evidence",
            manual_status,
            manual_evidence,
            ["logs", "live_positions", "paper_inputs"],
            manual_metrics,
        ),
        _coverage(
            "sample_denominators", "Samples by instrument and cluster",
            "OBSERVED" if fill_records else "MISSING",
            f"{len(fill_records)} fill sample(s) across {len(denominators['by_inst'])} instrument(s) and {len(denominators['by_cluster'])} cluster(s)",
            ["trade_log"],
            denominators,
        ),
        _coverage(
            "same_day_multi_day", "Same-day vs multi-day exits",
            "OBSERVED" if any(duration.values()) else "MISSING",
            f"same-day {duration['same_day']} | multi-day {duration['multi_day']} | unknown {duration['unknown']}",
            ["trade_log"],
            duration,
        ),
        _coverage(
            "log_hygiene", "Production-log hygiene",
            "OBSERVED",
            f"{logs['dropped_test_lines']} test/noise line(s) filtered from paper evidence",
            ["logs"],
            {"dropped_test_lines": logs["dropped_test_lines"]},
        ),
    ]


def read_paper_evidence(root: Path) -> dict[str, Any]:
    signature = _signature(root)
    key = (str(root.resolve()), signature)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)

    state = read_runner_state(root / "global_index" / "live_state_data.js")
    payload = state.get("payload") or {}
    meta = payload.get("meta") or {}
    history, history_error = _read_json(root / "global_index" / "paper_history.json")
    slip_stats, slip_error = _read_json(root / "slip_stats.json")
    paper_inputs, paper_inputs_error = _read_optional_json(root / "monitor" / "paper_inputs.json")
    paper_compare, paper_compare_error = _read_optional_json(root / "monitor" / "paper_pnl_compare.json")
    records, malformed_trades, trade_error = _trade_records(root / "trade_log.jsonl")

    epoch = str(meta.get("system_epoch") or history.get("epoch") or "") or None
    history_days = sorted(day for day in (history.get("days") or {}) if _in_epoch(day, epoch))

    regimes = sorted({
        str(record.get("regime"))
        for record in records
        if record.get("regime") in {"Normal", "Stress"}
        and _in_epoch(_date(record.get("entry_day") or record.get("exit_day")), epoch)
    })

    exits = {"CHANDELIER": 0, "MAX_HOLD": 0, "STP": 0}
    for record in records:
        if str(record.get("type")).upper() != "CLOSE":
            continue
        if not _in_epoch(_date(record.get("exit_day")), epoch):
            continue
        key_exit = _normalize_exit(record.get("exit_reason"))
        if key_exit:
            exits[key_exit] += 1

    slip = _slippage(records, epoch)
    c1_trades = _c1_trade_details(records, epoch)
    logs = _log_summary(root, epoch)
    live_positions, _live_positions_error = _read_json(root / "live_positions.json")
    positions = live_positions.get("positions") if isinstance(live_positions.get("positions"), list) else []
    stp_trades = _stp_trade_details(records, epoch, positions)
    coverage = _coverage_items(root, payload, history, records, logs, epoch, paper_inputs, paper_compare, malformed_trades)
    c1_status, c1_evidence, c1_metrics = _c1_status(
        slip, paper_inputs.get("c1_spec") if isinstance(paper_inputs.get("c1_spec"), dict) else {}
    )
    stp_status, stp_evidence, stp_metrics = _stp_input_status(
        _records(paper_inputs.get("stp_verification")), logs
    )
    tws_items = _records(paper_inputs.get("tws_restart_nights"))
    tws_spec = paper_inputs.get("tws_restart_spec") if isinstance(paper_inputs.get("tws_restart_spec"), dict) else {}
    tws_status, tws_evidence, tws_metrics = _tws_input_status(
        tws_items,
        tws_spec,
        logs,
    )
    coverage_by_key = {item["key"]: item for item in coverage}
    gaps = []
    if c1_status == "SPEC_GAP":
        gaps.append({"title": "C1 gate definition", "detail": "Minimum N and OPEN/STP-close gate scope are not quantified."})
    if slip["signal_close_with_stop_ref"]:
        gaps.append({
            "title": "Signal close slippage reference",
            "detail": (
                f"{slip['signal_close_with_stop_ref']} signal/market CLOSE record(s) have stop_ref-derived slip; "
                "they are excluded from C1 and covered by Paper P&L vs backtest instead."
            ),
        })
    min_nights = int(tws_spec.get("min_nights") or 0) if isinstance(tws_spec.get("min_nights"), int) else None
    if tws_status != "PASS":
        if min_nights:
            tws_detail = (
                f"{logs['tws_restart_lines']} TWS/IBKR connectivity-restart candidate line(s) found across "
                f"{len(logs['tws_restart_days'])} day(s); {len(tws_items)} structured proof record(s), "
                f"need {min_nights} proven restart night(s)."
            )
        else:
            tws_detail = (
                f"{logs['tws_restart_lines']} TWS/IBKR connectivity-restart candidate line(s) found across "
                f"{len(logs['tws_restart_days'])} day(s); no numeric threshold or restart-proof artifact exists."
            )
        gaps.append({"title": "TWS restart coverage", "detail": tws_detail})
    pvb_coverage = coverage_by_key.get("paper_vs_backtest", {})
    if pvb_coverage.get("status") != "OBSERVED":
        gaps.append({
            "title": "Paper P&L vs backtest source",
            "detail": (
                "A complete daily compare needs both expected_equity and actual_equity. "
                "The live-state artifact currently has actual-only context unless a structured "
                "monitor/paper_inputs.json paper_vs_backtest record supplies the expected backtest value."
            ),
        })
    gaps.extend([
        {
            "title": "STP false halt",
            "detail": "Logs expose raw B3/STP placement evidence, but false-halt classification is not structured.",
        },
        {
            "title": "Manual intervention ledger",
            "detail": f"{logs['manual_intervention_lines']} operator-action candidate line(s) found across {len(logs['manual_intervention_days'])} day(s); no structured operator-action ledger exists.",
        },
    ])

    gates = [
        _gate(
            "paper_duration", "Paper duration",
            "PASS" if len(history_days) >= 60 else "PENDING",
            f"{len(history_days)} paper day(s) in paper_history.json",
            "60 days (UI uses conservative end of documented 30-60 day minimum)",
            ["paper_history", "live_state"],
            {"observed": len(history_days), "target": 60, "days": history_days},
        ),
        _gate(
            "regime_coverage", "Regime coverage",
            "PASS" if {"Normal", "Stress"}.issubset(set(regimes)) else "PENDING",
            " + ".join(regimes) if regimes else "No Normal/Stress trade-log regime observed",
            "Normal and Stress must both be observed",
            ["trade_log"],
            {"regimes": regimes},
        ),
        _gate(
            "exit_path_coverage", "Exit path coverage",
            "PASS" if all(count >= 3 for count in exits.values()) else "PENDING",
            f"Chandelier {exits['CHANDELIER']} | MAX_HOLD {exits['MAX_HOLD']} | STP {exits['STP']}",
            "Each path several times; monitor interprets several as 3",
            ["trade_log"],
            {"exits": exits, "target_each": 3},
        ),
        _gate(
            "c1_slippage", "C1 slippage",
            c1_status,
            c1_evidence,
            "Active paper_inputs spec: N>=100, abs mean <=5 ticks, OPEN and STP CLOSE separate",
            ["trade_log", "slip_stats", "paper_inputs"],
            {**c1_metrics, "slip_stats": slip_stats if not slip_error else None, "trade_samples": c1_trades},
        ),
        _gate(
            "b3_reconcile", "B3 cold-start reconcile",
            "BREACH" if logs["b3_mismatches"] else "PASS" if logs["b3_matches"] else "MISSING",
            f"{logs['b3_matches']} match observation(s), {logs['b3_mismatches']} mismatch(es)",
            "0 mismatches on every cold start",
            ["logs"],
            {"matches": logs["b3_matches"], "mismatches": logs["b3_mismatches"], "cold_starts": logs["cold_starts"]},
        ),
        _gate(
            "stp_verification", "STP verification",
            stp_status,
            stp_evidence,
            "No false halt; false-halt classification is not defined in structured evidence",
            ["logs", "paper_inputs"],
            {**stp_metrics, "trade_details": stp_trades},
        ),
        _gate(
            "tws_restart_nights", "TWS restart nights",
            tws_status,
            tws_evidence,
            "Active paper_inputs spec: 10 proven TWS restart nights",
            ["logs", "live_state", "paper_inputs"],
            tws_metrics,
        ),
    ]

    result = {
        "source": "paper_evidence",
        "observed_at": state.get("observed_at"),
        "freshness": state.get("freshness"),
        "error": None,
        "payload": {
            "epoch": epoch,
            "gates": gates,
            "coverage": coverage,
            "summary": {
                "days": len(history_days),
                "regimes": regimes,
                "exit_paths_complete": sum(1 for count in exits.values() if count >= 3),
                "c1_open_mean": slip["open_mean"],
                "c1_close_mean": slip["close_mean"],
                "c1_open_n": slip["open_n"],
                "c1_close_n": slip["close_n"],
            },
            "gaps": gaps,
            "diagnostics": {
                "history_error": history_error,
                "trade_log_error": trade_error,
                "trade_log_malformed_lines": malformed_trades,
                "slip_stats_error": slip_error,
                "paper_inputs_error": paper_inputs_error,
                "paper_pnl_compare_error": paper_compare_error,
                "dropped_test_log_lines": logs["dropped_test_lines"],
                "manual_intervention_candidate_lines": logs["manual_intervention_lines"],
                "manual_intervention_candidate_days": logs["manual_intervention_days"],
                "tws_restart_candidate_lines": logs["tws_restart_lines"],
                "tws_restart_candidate_days": logs["tws_restart_days"],
            },
        },
    }
    with _lock:
        _cache.clear()
        _cache[key] = copy.deepcopy(result)
    return result


def _fmt_mean(value: float | None) -> str:
    if value is None:
        return "--"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f} ticks"
