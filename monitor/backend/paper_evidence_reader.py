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

from monitor.backend import ibkr_reader
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
_STP_SYSTEM_PLACED = re.compile(
    r"(?:STP: placed\s+(?P<placed_inst>[A-Z0-9]+)\s+(?P<placed_direction>LONG|SHORT)\s+stop\s+@\s+(?P<placed_stop>[-\d.]+)\s+orderId=(?P<placed_order_id>\S+)\s+cluster=(?P<placed_cluster>\S+)"
    r"|B4 REPLACED:\s+(?P<b4_inst>[A-Z0-9]+)/(?P<b4_cluster>\S+)\s+was open with no stop order.*?re-placed\s+@\s+(?P<b4_stop>[-\d.]+)\s+orderId=(?P<b4_order_id>\S+))",
    re.IGNORECASE,
)
_STP_DEFERRED = re.compile(r"\bSTP HOAN:", re.IGNORECASE)
_STP_DEFER_REMINDER = re.compile(r"\bcua so hoan CO CHU DICH\b|\bstop_deferred\b", re.IGNORECASE)
_STP_DEFERRED_DETAIL = re.compile(
    r"(?:STP HOAN:|B4:)\s+(?P<inst>[A-Z0-9]+)(?:/(?P<b4_cluster>\S+)|\s+(?P<direction>LONG|SHORT))"
    r"(?:\s+@\s+(?P<stop>[-\d.]+))?.*?(?:cluster=(?P<cluster>\S+)|$)",
    re.IGNORECASE,
)
_REJECTED = re.compile(r"\bREJECTED\b.*\brisk_sized=", re.IGNORECASE)
_REJECTED_DETAIL = re.compile(
    r"REJECTED\s+(?P<direction>LONG|SHORT)\s+(?P<inst>[A-Z0-9]+)\s+\((?P<cluster>[^)]+)\)"
    r"\s+risk_sized=\$(?P<risk_sized>[-\d.,]+)\s+[—-]\s+(?P<reason>.+)$",
    re.IGNORECASE,
)
_CAP_REASON_DETAIL = re.compile(
    r"(?P<cluster>\S+)\s+(?P<cap_kind>gross|net)\s+(?P<projected_pct>[-\d.]+)%\s+>\s+cap\s+(?P<cap_pct>[-\d.]+)%",
    re.IGNORECASE,
)
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
        "JSON object with c1_spec, fill_quality_spec, stp_placement_spec, rejection_coverage_spec, paper_vs_backtest_spec, tws_restart_nights, manual_interventions, roll_slippage, paper_vs_backtest",
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
    "ibkr_contract_specs": _source(
        "/api/v1/broker payload.contract_specs",
        "monitor.backend.ibkr_reader reqContractDetails",
        "Read-only IBKR ContractDetails minTick + contract multiplier",
        "Cached by backend reader after IBKR connection",
        "Current backend process cache only",
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
    try:
        specs = ibkr_reader.get_cache().get("contract_specs") or {}
        encoded = json.dumps(specs, sort_keys=True).encode("utf-8")
        checksum = sum(encoded)
        values.append(("ibkr_contract_specs", len(encoded), checksum))
    except Exception:
        pass
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


def _parse_log_ts(value: Any) -> dt.datetime | None:
    if not value:
        return None
    text = str(value)[:19]
    try:
        parsed = dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=ZoneInfo("America/Edmonton")).astimezone(dt.timezone.utc)


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


def _local_contract_specs() -> dict[str, dict[str, Any]]:
    try:
        from futures.basket import BASKET
    except Exception:
        return {}
    specs: dict[str, dict[str, Any]] = {}
    for inst, contract in BASKET.items():
        point_value = _number(getattr(contract, "point_value", None))
        tick = _number(getattr(contract, "tick", None))
        specs[str(inst)] = {
            "point_value": point_value,
            "tick": tick,
            "tick_value": round(point_value * tick, 6) if point_value is not None and tick is not None else None,
        }
    return specs


def _close_enough(left: Any, right: Any, tolerance: float = 1e-6) -> bool:
    a = _number(left)
    b = _number(right)
    return a is not None and b is not None and abs(a - b) <= tolerance


def _contract_spec_guard(ibkr_cache: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    local = _local_contract_specs()
    ibkr_specs = ibkr_cache.get("contract_specs") if isinstance(ibkr_cache.get("contract_specs"), dict) else {}
    rows: list[dict[str, Any]] = []
    mismatches = 0
    missing = 0
    for inst, local_spec in local.items():
        ibkr_spec = ibkr_specs.get(inst) if isinstance(ibkr_specs.get(inst), dict) else {}
        checks = {
            "point_value": _close_enough(local_spec.get("point_value"), ibkr_spec.get("point_value")),
            "tick": _close_enough(local_spec.get("tick"), ibkr_spec.get("tick")),
            "tick_value": _close_enough(local_spec.get("tick_value"), ibkr_spec.get("tick_value")),
        }
        if not ibkr_spec or ibkr_spec.get("status") in {"MISSING", "ERROR"}:
            status = "MISSING"
            missing += 1
        elif all(checks.values()):
            status = "PASS"
        else:
            status = "BREACH"
            mismatches += 1
        rows.append({
            "inst": inst,
            "status": status,
            "local": local_spec,
            "ibkr": ibkr_spec,
            "checks": checks,
            "contract": {
                "symbol": ibkr_spec.get("symbol"),
                "local_symbol": ibkr_spec.get("local_symbol"),
                "contract_month": ibkr_spec.get("contract_month"),
                "exchange": ibkr_spec.get("exchange"),
                "con_id": ibkr_spec.get("con_id"),
            },
        })
    if mismatches:
        status = "BREACH"
    elif missing or not ibkr_specs:
        status = "MISSING"
    else:
        status = "OBSERVED"
    evidence = (
        f"{len(local) - mismatches - missing}/{len(local)} local contract spec(s) reconciled to IBKR; "
        f"{mismatches} mismatch(es), {missing} missing"
    )
    return status, evidence, {
        "description": "Guards P&L conversion by reconciling local point_value/tick/tick_value against IBKR ContractDetails.",
        "local_source": "futures.basket.BASKET",
        "ibkr_connected": bool(ibkr_cache.get("connected")),
        "ibkr_observed_at": ibkr_cache.get("last_update"),
        "rows": rows,
        "mismatches": mismatches,
        "missing": missing,
        "status_rules": [
            "OBSERVED: every local basket instrument has IBKR ContractDetails and point_value/tick/tick_value match within tolerance.",
            "BREACH: any IBKR multiplier/minTick-derived value differs from the local basket value.",
            "MISSING: IBKR is disconnected or ContractDetails are not available yet; P&L conversion cannot be independently audited.",
        ],
    }


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


def _position_rows(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        stop_order_id = pos.get("stop_order_id")
        rows.append({
            "inst": pos.get("inst"),
            "cluster": pos.get("cluster"),
            "direction": pos.get("direction") or pos.get("dir"),
            "contracts": pos.get("contracts"),
            "entry_day": _date(pos.get("entry_day") or pos.get("entry_time")),
            "entry_price": pos.get("entry_price"),
            "stop_price": pos.get("stop_price"),
            "stop_order_id": stop_order_id,
            "risk_dollars": pos.get("risk_dollars") or pos.get("risk_sized"),
            "exit_pending": bool(pos.get("exit_pending")),
            "status": "PROTECTED" if stop_order_id else "UNPROTECTED",
        })
    return rows


def _snapshot_rows(payload: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    snapshots = payload.get("snapshots") if isinstance(payload.get("snapshots"), list) else []
    rows: list[dict[str, Any]] = []
    for snap in snapshots[-limit:]:
        if not isinstance(snap, dict):
            continue
        decision = snap.get("decision") if isinstance(snap.get("decision"), dict) else {}
        open_positions = snap.get("open_positions") if isinstance(snap.get("open_positions"), list) else []
        op = snap.get("operational_status") if isinstance(snap.get("operational_status"), dict) else {}
        runner = op.get("runner") if isinstance(op.get("runner"), dict) else {}
        breaker = op.get("breaker") if isinstance(op.get("breaker"), dict) else {}
        rows.append({
            "date": snap.get("date"),
            "equity": snap.get("equity"),
            "realized_today": decision.get("realized_today"),
            "entries": len(decision.get("entries") or []),
            "exits": len(decision.get("exits") or []),
            "rejected": len(decision.get("rejected_detail") or []),
            "open_positions": len(open_positions),
            "breaker_level": snap.get("breaker_level") or breaker.get("level"),
            "runner_alive": runner.get("alive"),
            "runner_pid": runner.get("pid"),
        })
    return rows


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
    system_placed = _STP_SYSTEM_PLACED.search(line)
    deferred = _STP_DEFERRED_DETAIL.search(line)
    match = accepted or failed or system_placed or deferred
    groups = match.groupdict() if match else {}
    cluster = groups.get("cluster") or groups.get("placed_cluster") or groups.get("b4_cluster")
    if isinstance(cluster, str):
        cluster = cluster.rstrip(")")
    ts = line[:19] if len(line) >= 19 and line[:4].isdigit() else None
    reason = {
        "ACCEPTED": "Broker accepted protective STP after the defer window was no longer active.",
        "FAILED": "Broker did not accept the STP; position may be unprotected after the allowed defer window.",
        "SYSTEM_PLACED": "Runner/system logged the stop placement or B4 replacement with the broker order id.",
        "DEFERRED": "Runner deliberately withheld same-day/too-early STP to match the validated backtest stop semantics.",
    }.get(kind, "Raw STP placement evidence.")
    return {
        "kind": kind,
        "day": day,
        "ts": ts,
        "ts_utc": _fmt_ts(_parse_log_ts(ts)),
        "path": path.name,
        "line_no": line_no,
        "inst": groups.get("inst") or groups.get("placed_inst") or groups.get("b4_inst"),
        "direction": groups.get("direction") or groups.get("placed_direction"),
        "cluster": cluster,
        "qty": int(groups["qty"]) if groups.get("qty") and str(groups["qty"]).isdigit() else None,
        "stop_price": _number(groups.get("stop") or groups.get("placed_stop") or groups.get("b4_stop")),
        "order_id": groups.get("order_id") or groups.get("placed_order_id") or groups.get("b4_order_id"),
        "order_status": groups.get("order_status"),
        "reason": reason,
        "raw": line[:260],
    }


def _rejection_class(reason: str | None) -> str:
    text = (reason or "").lower()
    if "gross" in text and "cap" in text:
        return "cap_gross"
    if "net" in text and "cap" in text:
        return "cap_net"
    if "cap" in text:
        return "cap_block"
    if "halt" in text or "breaker" in text:
        return "breaker"
    if "refreeze" in text:
        return "refreeze"
    if "regime" in text:
        return "regime"
    if "risk" in text:
        return "risk_guard"
    return "unclassified"


def _rejection_log_row(path: Path, line_no: int, day: str | None, line: str) -> dict[str, Any]:
    ts = line[:19] if len(line) >= 19 and line[:4].isdigit() else None
    match = _REJECTED_DETAIL.search(line)
    groups = match.groupdict() if match else {}
    reason = groups.get("reason")
    cap_match = _CAP_REASON_DETAIL.search(reason or "")
    cap_groups = cap_match.groupdict() if cap_match else {}
    klass = _rejection_class(reason)
    return {
        "day": day,
        "ts": ts,
        "ts_utc": _fmt_ts(_parse_log_ts(ts)),
        "path": path.name,
        "line_no": line_no,
        "inst": groups.get("inst"),
        "direction": groups.get("direction"),
        "cluster": groups.get("cluster"),
        "risk_sized": _number((groups.get("risk_sized") or "").replace(",", "")),
        "reason": reason,
        "class": klass,
        "cap_kind": cap_groups.get("cap_kind"),
        "projected_pct": _number(cap_groups.get("projected_pct")),
        "cap_pct": _number(cap_groups.get("cap_pct")),
        "raw": line[:320],
        "parsed": bool(match),
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
        "stp_system_placed": 0,
        "stp_deferred": 0,
        "stp_defer_reminders": 0,
        "stp_placement_rows": [],
        "rejections": 0,
        "rejection_rows": [],
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
            if _STP_SYSTEM_PLACED.search(line):
                summary["stp_system_placed"] += 1
                summary["stp_placement_rows"].append(_stp_log_row("SYSTEM_PLACED", path, idx, day, line))
            if _STP_DEFERRED.search(line):
                summary["stp_deferred"] += 1
                summary["stp_placement_rows"].append(_stp_log_row("DEFERRED", path, idx, day, line))
            elif _STP_DEFER_REMINDER.search(line):
                summary["stp_defer_reminders"] += 1
            if _REJECTED.search(line):
                summary["rejections"] += 1
                summary["rejection_rows"].append(_rejection_log_row(path, idx, day, line))
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
    system_rows = [row for row in rows if row.get("kind") == "SYSTEM_PLACED"]
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
        matching_system = [
            item for item in system_rows
            if item.get("order_id") and any(item.get("order_id") == accepted_item.get("order_id") for accepted_item in matching_accepted)
        ]
        timing = _stp_close_timing(trade) if trade else {}
        if matching_accepted:
            accepted_row = matching_accepted[0]
            accepted_at = _parse_ts(accepted_row.get("ts_utc"))
            arm_at = _stp_arm_at(trade) if trade else None
            after_arm = accepted_at is not None and arm_at is not None and accepted_at >= arm_at
            if not after_arm:
                outcome = "ACCEPTED_BEFORE_ARM"
                detail = f"accepted {accepted_row.get('path')}:{accepted_row.get('line_no')} before defer arm"
            elif not matching_system:
                outcome = "ACCEPTED_MISSING_SYSTEM_LOG"
                detail = f"IBKR accepted {accepted_row.get('path')}:{accepted_row.get('line_no')} but matching runner/B4 system log is missing"
            else:
                outcome = "ACCEPTED_AFTER_ARM"
                detail = f"IBKR {accepted_row.get('path')}:{accepted_row.get('line_no')} + system {matching_system[0].get('path')}:{matching_system[0].get('line_no')}"
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
            "accepted_at": _fmt_ts(_parse_ts(matching_accepted[0].get("ts_utc"))) if matching_accepted else None,
            "accepted_evidence": f"{matching_accepted[0].get('path')}:{matching_accepted[0].get('line_no')}" if matching_accepted else None,
            "system_evidence": f"{matching_system[0].get('path')}:{matching_system[0].get('line_no')}" if matching_system else None,
            "outcome": outcome,
            "detail": detail,
        })
    unmatched_failed = [row for row in failed if not row.get("trade_id")]
    return {
        "counts": counts,
        "rows": reconciled,
        "unmatched_failed": unmatched_failed,
    }


def _stp_session_streak(reconcile: dict[str, Any], required_sessions: int | None) -> dict[str, Any]:
    rows = reconcile.get("rows") if isinstance(reconcile.get("rows"), list) else []
    by_day: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        day = _date(row.get("entry_day"))
        if day:
            by_day.setdefault(day, []).append(row)
    session_rows = []
    pass_outcomes = {"ACCEPTED_AFTER_ARM", "CLOSED_BEFORE_ARM"}
    for day in sorted(by_day):
        items = by_day[day]
        failures = [item for item in items if item.get("outcome") not in pass_outcomes]
        status = "PASS" if not failures else "FAIL"
        session_rows.append({
            "session": day,
            "status": status,
            "routes": len(items),
            "accepted_after_arm": sum(1 for item in items if item.get("outcome") == "ACCEPTED_AFTER_ARM"),
            "closed_before_arm": sum(1 for item in items if item.get("outcome") == "CLOSED_BEFORE_ARM"),
            "failures": len(failures),
            "failure_reasons": [item.get("outcome") for item in failures],
        })
    streak = 0
    for session in session_rows:
        if session["status"] == "PASS":
            streak += 1
        else:
            streak = 0
    latest_failure = next((session for session in reversed(session_rows) if session["status"] == "FAIL"), None)
    return {
        "required": required_sessions,
        "current": streak,
        "sessions": session_rows,
        "latest_failure": latest_failure,
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
    required_sessions = int(spec.get("required_continuous_sessions") or 0) if isinstance(spec.get("required_continuous_sessions"), int) else None
    max_failed = int(spec.get("max_trade_matched_failed") or 0) if isinstance(spec.get("max_trade_matched_failed"), int) else None
    require_defer_rule = spec.get("require_defer_rule") is True
    require_system_log = spec.get("require_system_log") is True
    require_ibkr_accept_log = spec.get("require_ibkr_accept_log") is True
    session_streak = _stp_session_streak(reconcile, required_sessions)
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
        "required_continuous_sessions": required_sessions,
        "continuous_session_streak": session_streak.get("current"),
        "session_streak": session_streak,
        "max_failed": max_failed,
        "require_system_log": require_system_log,
        "require_ibkr_accept_log": require_ibkr_accept_log,
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
            "intentional defer first, then accepted broker stops after the arm time for every trade still open."
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
            "SPEC_GAP: stp_placement_spec is absent or lacks required_continuous_sessions/max_trade_matched_failed/defer-rule/system-log/IBKR-log confirmation.",
            "PENDING: no route failed, but the clean continuous-session streak is below required_continuous_sessions.",
            "PASS: for required_continuous_sessions consecutive sessions, every deferred trade either closed before arm or has a corresponding STP accepted after arm and logged by both IBKR and the runner/system.",
            "BREACH: any session has a trade still open after arm without accepted IBKR + system stop evidence, a stop accepted before arm, or trade-matched failed placement. A failed session resets the streak.",
        ],
    }
    if not rows and not accepted and not failed and not deferred:
        return "MISSING", "No STP placement/defer evidence in paper epoch", metrics
    if not spec or required_sessions is None or max_failed is None or not require_defer_rule or not require_system_log or not require_ibkr_accept_log:
        return "SPEC_GAP", (
            f"{accepted} accepted, {failed} failed, {deferred} deferred; stp_placement_spec missing or incomplete"
        ), metrics
    if matched_failed > max_failed:
        return "BREACH", f"{accepted} accepted, {matched_failed}>{max_failed} trade-matched failed STP placement line(s), {deferred} deferred", metrics
    failing_sessions = [session for session in session_streak.get("sessions", []) if session.get("status") == "FAIL"]
    if failing_sessions:
        latest = failing_sessions[-1]
        return "BREACH", f"session {latest['session']} failed stop-placement reconcile; streak reset to 0", metrics
    if (session_streak.get("current") or 0) < required_sessions:
        suffix = f", {unmatched_failed} unmatched failed log line(s)" if unmatched_failed else ""
        return "PENDING", f"{session_streak.get('current') or 0} / {required_sessions} clean continuous session(s), {deferred} deferred route(s){suffix}", metrics
    suffix = f", {unmatched_failed} unmatched failed log line(s)" if unmatched_failed else ""
    return "PASS", f"{session_streak.get('current') or 0} / {required_sessions} clean continuous session(s), {deferred} deferred route(s){suffix}", metrics


def _enrich_rejection_rows(rows: list[dict[str, Any]], account: float | None) -> list[dict[str, Any]]:
    enriched = []
    for row in rows:
        item = dict(row)
        candidate_risk = _number(item.get("risk_sized"))
        projected_pct = _number(item.get("projected_pct"))
        cap_pct = _number(item.get("cap_pct"))
        if account not in {None, 0} and projected_pct is not None:
            projected_risk = account * projected_pct / 100
            item["account_base"] = account
            item["projected_risk_sized"] = round(projected_risk, 2)
            if candidate_risk is not None:
                item["candidate_risk_sized"] = candidate_risk
                item["existing_risk_sized"] = round(projected_risk - candidate_risk, 2)
                item["existing_pct"] = round(((projected_risk - candidate_risk) / account) * 100, 4)
            if cap_pct is not None:
                item["cap_risk_sized"] = round(account * cap_pct / 100, 2)
                item["over_cap_risk_sized"] = round(projected_risk - (account * cap_pct / 100), 2)
                item["over_cap_pct"] = round(projected_pct - cap_pct, 4)
        enriched.append(item)
    return enriched


def _rejection_coverage_status(logs: dict[str, Any], spec: dict[str, Any],
                               account: float | None) -> tuple[str, str, dict[str, Any]]:
    raw_rows = logs.get("rejection_rows") if isinstance(logs.get("rejection_rows"), list) else []
    rows = _enrich_rejection_rows(raw_rows, account)
    total = int(logs.get("rejections") or len(rows) or 0)
    parsed = sum(1 for row in rows if row.get("parsed"))
    missing_identity = sum(
        1 for row in rows
        if not row.get("inst") or not row.get("direction") or not row.get("cluster")
    )
    missing_reason = sum(1 for row in rows if not row.get("reason"))
    unclassified = sum(1 for row in rows if row.get("class") == "unclassified")
    cap_blocks = sum(1 for row in rows if str(row.get("class") or "").startswith("cap"))
    by_class: dict[str, int] = {}
    by_cluster: dict[str, int] = {}
    for row in rows:
        klass = str(row.get("class") or "unclassified")
        by_class[klass] = by_class.get(klass, 0) + 1
        cluster = str(row.get("cluster") or "unknown")
        by_cluster[cluster] = by_cluster.get(cluster, 0) + 1
    required_records = int(spec.get("required_records") or 0) if isinstance(spec.get("required_records"), int) else None
    max_unclassified = int(spec.get("max_unclassified") or 0) if isinstance(spec.get("max_unclassified"), int) else None
    require_identity = spec.get("require_candidate_identity") is True
    require_reason = spec.get("require_reason") is True
    require_cap_classification = spec.get("require_cap_classification") is True
    metrics = {
        "rejections": total,
        "parsed": parsed,
        "classified": total - unclassified,
        "cap_blocks": cap_blocks,
        "other_rejections": max(total - cap_blocks, 0),
        "missing_identity": missing_identity,
        "missing_reason": missing_reason,
        "unclassified": unclassified,
        "required_records": required_records,
        "max_unclassified": max_unclassified,
        "require_candidate_identity": require_identity,
        "require_reason": require_reason,
        "require_cap_classification": require_cap_classification,
        "account_base": account,
        "by_class": by_class,
        "by_cluster": by_cluster,
        "spec": spec if spec else None,
        "samples": {
            "total": len(rows),
            "shown": min(len(rows), 30),
            "limit": 30,
            "rows": rows[-30:],
        },
        "description": (
            "Rejected signals and cap blocks validates that paper/live guard decisions leave structured evidence for every "
            "candidate that was intentionally not sent as an order: candidate identity, risk size, guard class, and raw reason."
        ),
        "metric_descriptions": {
            "rejections": "Rejected candidate log lines in the active paper epoch.",
            "parsed": "Rows parsed into direction, instrument, cluster, risk_sized, and reason.",
            "cap_blocks": "Rows classified as exposure/risk cap blocks, such as gross or net cap.",
            "existing_risk_sized": "Estimated open-book risk before the rejected candidate, computed from projected cap percentage minus candidate risk.",
            "candidate_risk_sized": "Risk contribution of the new rejected candidate from the log's risk_sized field.",
            "projected_risk_sized": "Estimated open-book risk after adding the rejected candidate, derived from projected percentage times account base.",
            "missing_identity": "Rows without candidate identity fields needed for trade-by-trade audit.",
            "missing_reason": "Rows without a guard reason explaining why the candidate was blocked.",
            "unclassified": "Rows with a reason that could not be mapped to a guard class.",
        },
        "status_rules": [
            "MISSING: no rejected-signal or cap-block log evidence exists in the paper epoch.",
            "SPEC_GAP: rejection_coverage_spec is absent or lacks required_records/max_unclassified/required field flags.",
            "PENDING: structured rejection evidence exists and has no breach, but sample count is below required_records.",
            "PASS: rejections >= required_records, every row has candidate identity and reason when required, and unclassified rows are within max_unclassified.",
            "BREACH: required identity/reason fields are missing, unclassified rows exceed max_unclassified, or cap-block classification is required but no cap block is observed.",
        ],
    }
    if not total:
        return "MISSING", "No rejected-signal/cap-block log evidence in paper epoch", metrics
    if (
        not spec
        or required_records is None
        or max_unclassified is None
        or not require_identity
        or not require_reason
        or not require_cap_classification
    ):
        return "SPEC_GAP", f"{total} rejection log line(s); rejection_coverage_spec missing or incomplete", metrics
    breaches = []
    if require_identity and missing_identity:
        breaches.append(f"{missing_identity} row(s) missing candidate identity")
    if require_reason and missing_reason:
        breaches.append(f"{missing_reason} row(s) missing reason")
    if unclassified > max_unclassified:
        breaches.append(f"{unclassified}>{max_unclassified} unclassified row(s)")
    if require_cap_classification and cap_blocks == 0:
        breaches.append("cap-block classification required but none observed")
    if breaches:
        return "BREACH", f"{total} rejection log line(s); " + " | ".join(breaches), metrics
    if total < required_records:
        return "PENDING", f"{total} / {required_records} structured rejection/cap-block row(s), {cap_blocks} cap block(s)", metrics
    return "PASS", f"{total} / {required_records} structured rejection/cap-block row(s), {cap_blocks} cap block(s)", metrics


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
    daily = compare.get("daily") if isinstance(compare.get("daily"), list) else []
    convention = compare.get("convention") if isinstance(compare.get("convention"), dict) else {}
    pnl_reconcile = compare.get("pnl_reconcile") if isinstance(compare.get("pnl_reconcile"), dict) else {}
    open_position_parity = compare.get("open_position_parity") if isinstance(compare.get("open_position_parity"), dict) else {}
    signal_compare = compare.get("signal_compare") if isinstance(compare.get("signal_compare"), dict) else {}
    signal_classified = signal_compare.get("classified") if isinstance(signal_compare.get("classified"), dict) else {}
    signal_rows = signal_classified.get("rows") if isinstance(signal_classified.get("rows"), list) else []
    signal_counts = signal_classified.get("counts") if isinstance(signal_classified.get("counts"), dict) else {}
    entry_compare = compare.get("entry_compare") if isinstance(compare.get("entry_compare"), dict) else {}
    entry_rows = entry_compare.get("rows") if isinstance(entry_compare.get("rows"), list) else []
    entry_counts = entry_compare.get("counts") if isinstance(entry_compare.get("counts"), dict) else {}
    lifecycle_compare = compare.get("lifecycle_compare") if isinstance(compare.get("lifecycle_compare"), dict) else {}
    lifecycle_rows = lifecycle_compare.get("rows") if isinstance(lifecycle_compare.get("rows"), list) else []
    lifecycle_counts = lifecycle_compare.get("counts") if isinstance(lifecycle_compare.get("counts"), dict) else {}
    signal_path_audit = compare.get("signal_path_audit") if isinstance(compare.get("signal_path_audit"), dict) else {}
    backtest_artifact_audit = compare.get("backtest_artifact_audit") if isinstance(compare.get("backtest_artifact_audit"), dict) else {}
    statement_pnl_compare = compare.get("statement_pnl_compare") if isinstance(compare.get("statement_pnl_compare"), dict) else {}
    ibkr_statement = compare.get("ibkr_statement") if isinstance(compare.get("ibkr_statement"), dict) else {}
    verdicts = compare.get("verdicts") if isinstance(compare.get("verdicts"), dict) else {}
    if not rows and not counts and not daily:
        return None
    covered_daily = [row for row in daily if isinstance(row, dict) and row.get("curve_status") == "covered"]
    stale_daily = [row for row in daily if isinstance(row, dict) and str(row.get("curve_status") or "").startswith("stale")]
    return {
        "counts": counts,
        "unresolved": int(classified.get("unresolved") or 0),
        "shown": min(len(rows), 24),
        "total": len(rows),
        "rows": rows[:24],
        "curve_generated": convention.get("curve_generated"),
        "convention": convention,
        "daily": daily,
        "signal_compare": {
            "counts": signal_counts,
            "unresolved": int(signal_classified.get("unresolved") or 0),
            "shown": min(len(signal_rows), 30),
            "total": len(signal_rows),
            "rows": signal_rows[:30],
        },
        "entry_compare": {
            "counts": entry_counts,
            "unresolved": int(entry_compare.get("unresolved") or 0),
            "shown": min(len(entry_rows), 30),
            "total": len(entry_rows),
            "rows": entry_rows[:30],
        },
        "lifecycle_compare": {
            "counts": lifecycle_counts,
            "unresolved": int(lifecycle_compare.get("unresolved") or 0),
            "paper_minus_backtest_sum": lifecycle_compare.get("paper_minus_backtest_sum"),
            "paper_minus_flex_sum": lifecycle_compare.get("paper_minus_flex_sum"),
            "shown": min(len(lifecycle_rows), 30),
            "total": len(lifecycle_rows),
            "rows": lifecycle_rows[:30],
        },
        "signal_path_audit": signal_path_audit,
        "backtest_artifact_audit": backtest_artifact_audit,
        "statement_pnl_compare": statement_pnl_compare,
        "verdicts": verdicts,
        "ibkr_statement": ibkr_statement,
        "pnl_reconcile": pnl_reconcile,
        "open_position_parity": open_position_parity,
        "covered_daily_count": len(covered_daily),
        "stale_daily_count": len(stale_daily),
        "latest_covered_daily": covered_daily[-1] if covered_daily else None,
        "latest_daily": daily[-1] if daily else None,
        "notes": compare.get("notes") if isinstance(compare.get("notes"), list) else [],
    }


def _pvb_base_audit(account: float | None, items: list[dict[str, Any]],
                    compare: dict[str, Any], trade_compare: dict[str, Any] | None) -> dict[str, Any]:
    convention = (trade_compare or {}).get("convention") if isinstance((trade_compare or {}).get("convention"), dict) else {}
    daily = (trade_compare or {}).get("daily") if isinstance((trade_compare or {}).get("daily"), list) else []
    epoch = convention.get("epoch")
    convention_account = _number(convention.get("account"))
    first_item = next((item for item in items if _number(item.get("actual_equity")) is not None), None)
    first_daily = next((row for row in daily if isinstance(row, dict) and _number(row.get("actual_equity")) is not None), None)
    first_actual = first_item or first_daily or {}
    first_actual_equity = _number(first_actual.get("actual_equity"))
    first_expected = _number(first_actual.get("expected_equity") or first_actual.get("expected_equity_account_window"))
    backtest_reset = first_expected == account if first_expected is not None and account is not None else None
    return {
        "epoch": epoch,
        "paper_account_base": account,
        "compare_account_base": convention_account,
        "base_accounts_match": (
            account == convention_account if account is not None and convention_account is not None else None
        ),
        "first_actual_date": _date(first_actual.get("date")),
        "first_actual_equity": first_actual_equity,
        "first_actual_vs_base": (
            round(first_actual_equity - account, 2) if first_actual_equity is not None and account is not None else None
        ),
        "first_expected_equity": first_expected,
        "backtest_reset_to_account": backtest_reset,
        "trade_filter_zero_position_base": bool(convention.get("formula_trade_filter")),
        "actual_equity_source": convention.get("actual_equity_source"),
        "actual_equity_note": convention.get("actual_equity_note"),
        "account_window_formula": convention.get("formula_account_window"),
        "trade_filter_formula": convention.get("formula_trade_filter"),
        "paper_trade_filter_formula": convention.get("formula_paper_trade_filter"),
        "curve_generated": convention.get("curve_generated"),
    }


def _divergence_side(value: float | None) -> str | None:
    if value is None:
        return None
    if value > 0:
        return "FAVORABLE"
    if value < 0:
        return "ADVERSE"
    return "FLAT"


def _pvb_daily_timeline(trade_compare: dict[str, Any] | None, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    daily = (trade_compare or {}).get("daily") if isinstance((trade_compare or {}).get("daily"), list) else []
    if not daily:
        daily = items
    rows = []
    for row in daily:
        if not isinstance(row, dict):
            continue
        trade_diff = _number(row.get("trade_filter_realized_diff"))
        account_diff = _number(row.get("account_window_diff"))
        actual = _number(row.get("actual_equity"))
        expected = _number(
            row.get("expected_equity_trade_filter")
            or row.get("expected_equity")
            or row.get("expected_equity_account_window")
        )
        rows.append({
            "date": _date(row.get("date")),
            "actual_equity": actual,
            "actual_equity_source": row.get("actual_equity_source"),
            "expected_equity": expected,
            "paper_trade_filter_equity": _number(row.get("paper_trade_filter_equity")),
            "account_window_diff": account_diff,
            "trade_filter_realized_diff": trade_diff,
            "system_ledger_vs_trade_filter": _number(row.get("system_ledger_vs_trade_filter")),
            "paper_trade_realized_cum": _number(row.get("paper_trade_realized_cum")),
            "backtest_trade_realized_cum": _number(row.get("backtest_trade_realized_cum")),
            "divergence_side": _divergence_side(trade_diff if trade_diff is not None else account_diff),
            "curve_status": row.get("curve_status") or ("covered" if expected is not None else "missing"),
        })
    return rows


def _paper_vs_backtest_status(live_pvb: dict[str, Any], items: list[dict[str, Any]],
                              account: float | None, compare: dict[str, Any],
                              spec: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    trade_compare = _trade_compare_summary(compare)
    base_audit = _pvb_base_audit(account, items, compare, trade_compare)
    timeline = _pvb_daily_timeline(trade_compare, items)
    unresolved = (trade_compare or {}).get("unresolved", 0)
    stale_daily = (trade_compare or {}).get("stale_daily_count", 0)
    covered_daily = (trade_compare or {}).get("covered_daily_count", 0)
    max_unresolved = int(spec.get("max_unresolved_trades") or 0) if isinstance(spec.get("max_unresolved_trades"), int) else None
    max_unresolved_signals = int(spec.get("max_unresolved_signals") or 0) if isinstance(spec.get("max_unresolved_signals"), int) else None
    max_unresolved_entries = int(spec.get("max_unresolved_entries") or 0) if isinstance(spec.get("max_unresolved_entries"), int) else None
    require_base = spec.get("require_base_alignment") is True
    require_trade_classification = spec.get("require_trade_level_classification") is True
    require_signal_classification = spec.get("require_signal_level_classification") is True
    require_current_curve = spec.get("require_current_curve") is True
    signal_unresolved = ((trade_compare or {}).get("signal_compare") or {}).get("unresolved", 0)
    entry_unresolved = ((trade_compare or {}).get("entry_compare") or {}).get("unresolved", 0)
    pnl_reconcile = (trade_compare or {}).get("pnl_reconcile") if isinstance((trade_compare or {}).get("pnl_reconcile"), dict) else {}
    open_position_parity = (trade_compare or {}).get("open_position_parity") if isinstance((trade_compare or {}).get("open_position_parity"), dict) else {}
    status_rules = [
        "MISSING: no complete paper-vs-backtest source exists.",
        "SPEC_GAP: paper_vs_backtest_spec is absent or lacks base/signal/trade/freshness rules.",
        "PENDING: base plus signal/entry/trade classification are usable, but the latest backtest curve is stale or not all required daily rows are eligible.",
        "PASS: paper and backtest share the same account base, backtest is reset to that base, curve coverage is current when required, and every signal/entry/trade-level divergence is classified within spec limits.",
        "BREACH: account base mismatches, backtest is not reset to the paper base, unresolved signal/entry divergence exceeds spec, or unresolved trade divergence exceeds max_unresolved_trades.",
    ]
    common_metrics = {
        "base_audit": base_audit,
        "timeline": timeline,
        "spec": spec if spec else None,
        "covered_daily_count": covered_daily,
        "stale_daily_count": stale_daily,
        "max_unresolved_trades": max_unresolved,
        "max_unresolved_signals": max_unresolved_signals,
        "max_unresolved_entries": max_unresolved_entries,
        "require_base_alignment": require_base,
        "require_trade_level_classification": require_trade_classification,
        "require_signal_level_classification": require_signal_classification,
        "require_current_curve": require_current_curve,
        "description": (
            "Paper P&L vs backtest/Flex validates the paper epoch from three comparable views: paper closed trades, "
            "replay closed trades reset to the same base, and IBKR Flex fills rebuilt from a zero-position epoch base. "
            "The goal is to explain where P&L variance starts: signal parity, entry fill parity, lifecycle/open-position "
            "parity, or known live-path timing drift. Realtime system ledger P&L is shown only as a ledger check and is "
            "not IBKR NetLiquidation."
        ),
        "curve_status_rule": (
            "curve_status is a freshness/eligibility check for a daily row, not a standalone P&L pass/fail verdict. "
            "A stale curve blocks new daily conclusions; covered rows can still be audited."
        ),
        "status_rules": status_rules,
        "pnl_reconcile": pnl_reconcile,
        "open_position_parity": open_position_parity,
    }
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
        suffix = f"; trade compare timing_drift {timing} unresolved {unresolved}" if trade_compare else ""
        metrics = {
            **common_metrics,
            "source_kind": "paper_inputs",
            "records": complete_items,
            "latest": latest,
            "trade_compare": trade_compare,
        }
        if (
            not spec
            or max_unresolved is None
            or max_unresolved_signals is None
            or max_unresolved_entries is None
            or not require_base
            or not require_trade_classification
            or not require_signal_classification
        ):
            return (
                "SPEC_GAP",
                f"structured daily compare {len(complete_items)} record(s); paper_vs_backtest_spec missing or incomplete",
                metrics,
            )
        if require_base and (
            base_audit.get("base_accounts_match") is False
            or base_audit.get("backtest_reset_to_account") is False
        ):
            return (
                "BREACH",
                "paper/backtest base alignment failed",
                metrics,
            )
        if unresolved > max_unresolved:
            return (
                "BREACH",
                f"{unresolved}>{max_unresolved} unresolved trade-level divergence(s)",
                metrics,
            )
        if signal_unresolved > max_unresolved_signals:
            return (
                "BREACH",
                f"{signal_unresolved}>{max_unresolved_signals} unresolved signal-level divergence(s)",
                metrics,
            )
        if entry_unresolved > max_unresolved_entries:
            return (
                "BREACH",
                f"{entry_unresolved}>{max_unresolved_entries} unresolved entry-level divergence(s)",
                metrics,
            )
        if require_current_curve and stale_daily:
            return (
                "PENDING",
                f"structured daily compare {len(complete_items)} record(s); latest curve stale for {stale_daily} row(s){suffix}",
                metrics,
            )
        return (
            "PASS",
            f"structured daily compare {len(complete_items)} record(s); latest actual {latest['actual_equity']} expected {latest['expected_equity']} divergence {latest['divergence_pct']}{suffix}",
            metrics,
        )

    actual = _number(live_pvb.get("actual_equity"))
    expected = _number(live_pvb.get("expected_equity"))
    if actual is not None and expected is not None:
        metrics = dict(live_pvb)
        metrics.update(common_metrics)
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
        metrics.update(common_metrics)
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
        {**common_metrics, "source_kind": "missing", "structured_records": len(items), "live_state": live_pvb, "trade_compare": trade_compare},
    )


def _coverage_items(root: Path, state: dict[str, Any], payload: dict[str, Any], history: dict[str, Any],
                    records: list[dict[str, Any]], logs: dict[str, Any],
                    epoch: str | None, paper_inputs: dict[str, Any], paper_compare: dict[str, Any],
                    malformed_trades: int, ibkr_cache: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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
    rejection_status, rejection_evidence, rejection_metrics = _rejection_coverage_status(
        logs,
        paper_inputs.get("rejection_coverage_spec") if isinstance(paper_inputs.get("rejection_coverage_spec"), dict) else {},
        _number(history.get("account")),
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
    position_rows = _position_rows(positions)
    unprotected = sum(1 for row in position_rows if row.get("status") != "PROTECTED")
    snapshot_rows = _snapshot_rows(payload)
    pvb_status, pvb_evidence, pvb_metrics = _paper_vs_backtest_status(
        pvb,
        _records(paper_inputs.get("paper_vs_backtest")),
        _number(history.get("account")),
        paper_compare,
        paper_inputs.get("paper_vs_backtest_spec") if isinstance(paper_inputs.get("paper_vs_backtest_spec"), dict) else {},
    )
    contract_status, contract_evidence, contract_metrics = _contract_spec_guard(ibkr_cache or {})

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
            {
                "description": "State persist checks whether the runner's latest projected open-position count agrees with the persisted live_positions.json file after state-changing decisions.",
                "operational_positions": positions_status,
                "live_positions_error": live_positions_error,
                "position_rows": position_rows,
                "status_rules": [
                    "PASS: persist_match is true and live_positions.json is readable.",
                    "BREACH: persist_match is false because runner state and persisted file disagree.",
                    "MISSING: runner operational position status or live_positions.json evidence is unavailable.",
                ],
            },
        ),
        _coverage(
            "rejections", "Rejected signals and cap blocks",
            rejection_status,
            rejection_evidence,
            ["logs", "paper_inputs"],
            rejection_metrics,
        ),
        _coverage(
            "runner_freshness", "Runner evidence freshness",
            "OBSERVED" if payload.get("snapshots") else "MISSING",
            f"{len(payload.get('snapshots') or [])} runner-state snapshot(s) projected",
            ["live_state"],
            {
                "description": "Runner freshness checks that the dashboard is reading a current live_state_data.js projection and that recent runner-state snapshots are available for paper evidence.",
                "snapshot_count": len(payload.get("snapshots") or []),
                "observed_at": state.get("observed_at"),
                "server_now": state.get("server_now"),
                "age_seconds": state.get("age_seconds"),
                "freshness": state.get("freshness"),
                "error": state.get("error"),
                "snapshot_rows": snapshot_rows,
                "latest_snapshot": snapshot_rows[-1] if snapshot_rows else {},
                "status_rules": [
                    "PASS: live_state_data.js is readable, has snapshots, and age threshold is explicitly satisfied.",
                    "OBSERVED: snapshots exist, but no hard freshness threshold is defined for this paper audit panel.",
                    "MISSING: live_state_data.js cannot be parsed or contains no runner snapshots.",
                ],
            },
        ),
        _coverage(
            "data_freshness", "Data freshness gates",
            "BREACH" if model_age.get("status") in {"URGENT", "HARD"} or regime_freshness.get("status") not in {None, "OK"} else "OBSERVED",
            f"regime={regime_freshness.get('status', '--')} | model={model_age.get('status', '--')} | refreeze_pending={refreeze.get('pending', '--')}",
            ["live_state"],
            {"regime_freshness": regime_freshness, "model_age": model_age, "refreeze": refreeze},
        ),
        _coverage(
            "contract_spec_guard", "Contract spec guard",
            contract_status,
            contract_evidence,
            ["ibkr_contract_specs"],
            contract_metrics,
        ),
        _coverage(
            "current_protection", "Current position protection",
            "BREACH" if positions and protected < len(positions) else "OBSERVED" if positions else "MISSING",
            f"{protected}/{len(positions)} persisted position(s) have stop_order_id",
            ["live_positions"],
            {
                "description": "Current protection checks the persisted open book right now. Every open position must carry a stop_order_id; historical stop timing is audited separately in STP placement.",
                "positions": len(positions),
                "protected": protected,
                "unprotected": unprotected,
                "live_positions_error": live_positions_error,
                "position_rows": position_rows,
                "status_rules": [
                    "PASS: every current persisted open position has stop_order_id.",
                    "BREACH: at least one current persisted open position lacks stop_order_id.",
                    "MISSING: no persisted live position file or no current open-position evidence is available.",
                ],
            },
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
    ibkr_cache = ibkr_reader.get_cache()
    coverage = _coverage_items(root, state, payload, history, records, logs, epoch, paper_inputs, paper_compare, malformed_trades, ibkr_cache)
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
