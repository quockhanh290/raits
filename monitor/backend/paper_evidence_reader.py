"""Read-only paper evidence projection for the Paper dashboard."""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import threading
from pathlib import Path
from typing import Any

from monitor.backend.open_issue_reader import read_open_issues
from monitor.backend.runner_state_reader import read_runner_state

_lock = threading.Lock()
_cache: dict[tuple[str, tuple[tuple[str, int, int], ...]], dict[str, Any]] = {}

_B3_MATCH = re.compile(r"B3: broker/file positions match \((?P<count>\d+) position")
_B3_MISMATCH = re.compile(r"B3: (?P<count>\d+) mismatch\(es\)")
_COLD_START = re.compile(r"Runner started: loaded")
_STP_VERIFY = re.compile(r"B3 STP-VERIFY")
_STP_EXIT = re.compile(r"B3 STP EXIT")
_B3_HALT = re.compile(r"B3 HALT")
_STP_ACCEPTED = re.compile(r"place_stop: accepted")
_STP_FAILED = re.compile(r"STP: place_stop FAILED|place_stop\(.*failed", re.IGNORECASE)
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
        "JSON object with c1_spec, stp_verification, tws_restart_nights, manual_interventions, roll_slippage",
        "Updated manually or by monitoring-only tooling when evidence is reviewed",
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
        for line in lines:
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
            if _STP_FAILED.search(line):
                summary["stp_failed"] += 1
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
    return (
        status,
        f"{len(items)} structured STP check(s), false_halt {false_halts}, double_stp {double_stp}, unverified {unverified}",
        {"checks": len(items), "false_halts": false_halts, "double_stp": double_stp, "unverified": unverified},
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


def _coverage_items(root: Path, payload: dict[str, Any], history: dict[str, Any],
                    records: list[dict[str, Any]], logs: dict[str, Any],
                    epoch: str | None, paper_inputs: dict[str, Any]) -> list[dict[str, Any]]:
    latest = _latest_snapshot(payload)
    epoch_records = _epoch_records(records, epoch)
    pvb = latest.get("paper_vs_backtest") if isinstance(latest.get("paper_vs_backtest"), dict) else {}
    op_status = latest.get("operational_status") if isinstance(latest.get("operational_status"), dict) else {}
    fill_records = [r for r in epoch_records if str(r.get("type")).upper() in {"OPEN", "CLOSE"}]
    partials = sum(1 for r in fill_records if r.get("filled_qty") is not None and r.get("contracts") and float(r.get("filled_qty") or 0) < float(r.get("contracts") or 0))
    failed = sum(1 for r in fill_records if str(r.get("status") or "").upper() not in {"", "FILLED", "PARTIAL"})
    denominators = _trade_denominators(fill_records)
    duration = _same_day(fill_records)
    live_positions, live_positions_error = _read_json(root / "live_positions.json")
    positions = live_positions.get("positions") if isinstance(live_positions.get("positions"), list) else []
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
    pvb_observed = pvb.get("actual_equity") is not None or pvb.get("expected_equity") is not None

    return [
        _coverage(
            "paper_vs_backtest", "Paper P&L vs backtest",
            "OBSERVED" if pvb_observed else "MISSING",
            f"actual {pvb.get('actual_equity', '--')} | expected {pvb.get('expected_equity', '--')} | divergence {pvb.get('divergence_pct', '--')}",
            ["live_state", "paper_history"],
            pvb,
        ),
        _coverage(
            "fill_quality", "Fill quality",
            "BREACH" if failed else "OBSERVED" if fill_records else "MISSING",
            f"{len(fill_records)} fill record(s), {partials} partial, {failed} failed/cancelled",
            ["trade_log", "live_state"],
            {"fills": len(fill_records), "partials": partials, "failed_or_cancelled": failed},
        ),
        _coverage(
            "stp_placement", "STP placement after OPEN",
            "BREACH" if logs["stp_failed"] else "OBSERVED" if logs["stp_accepted"] else "MISSING",
            f"{logs['stp_accepted']} accepted STP log line(s), {logs['stp_failed']} failed STP log line(s)",
            ["logs"],
            {"accepted": logs["stp_accepted"], "failed": logs["stp_failed"]},
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
    logs = _log_summary(root, epoch)
    coverage = _coverage_items(root, payload, history, records, logs, epoch, paper_inputs)
    c1_status, c1_evidence, c1_metrics = _c1_status(
        slip, paper_inputs.get("c1_spec") if isinstance(paper_inputs.get("c1_spec"), dict) else {}
    )
    stp_status, stp_evidence, stp_metrics = _stp_input_status(
        _records(paper_inputs.get("stp_verification")), logs
    )
    tws_status, tws_evidence, tws_metrics = _tws_input_status(
        _records(paper_inputs.get("tws_restart_nights")),
        paper_inputs.get("tws_restart_spec") if isinstance(paper_inputs.get("tws_restart_spec"), dict) else {},
        logs,
    )
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
    gaps.extend([
        {
            "title": "TWS restart coverage",
            "detail": f"{logs['tws_restart_lines']} TWS/IBKR connectivity-restart candidate line(s) found across {len(logs['tws_restart_days'])} day(s); no numeric threshold or restart-proof artifact exists.",
        },
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
            {**c1_metrics, "slip_stats": slip_stats if not slip_error else None},
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
            stp_metrics,
        ),
        _gate(
            "tws_restart_nights", "TWS restart nights",
            tws_status,
            tws_evidence,
            "Many nights; minimum count is not quantified",
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
