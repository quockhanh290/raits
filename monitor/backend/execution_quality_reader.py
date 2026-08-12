"""Read-only execution-quality evidence from the durable paper trade log."""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import statistics
import threading
from pathlib import Path
from typing import Any


_TICKS = {"MES": 0.25, "MNQ": 0.25, "MYM": 1.0, "M2K": 0.1,
          "NKD": 5.0, "MNKD": 5.0}
_ASSUMED_SLIPPAGE_TICKS = 2.0
_lock = threading.Lock()
_cache: dict[tuple[str, int, int, str | None], dict[str, Any]] = {}


def _day(record: dict[str, Any]) -> str | None:
    key = "entry_day" if str(record.get("type", "")).upper() == "OPEN" else "exit_day"
    value = record.get(key)
    return str(value)[:10] if value else None


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _signed_stop_slippage(record: dict[str, Any], expected: float, actual: float) -> float:
    # Positive always means adverse. Closing LONG sells; closing SHORT buys.
    return expected - actual if str(record.get("direction", "")).upper() == "LONG" else actual - expected


def _normalise(record: dict[str, Any], index: int) -> dict[str, Any]:
    trade_type = str(record.get("type", "UNKNOWN")).upper()
    direction = str(record.get("direction", "UNKNOWN")).upper()
    exit_reason = str(record.get("exit_reason") or "").upper()
    actual = _number(record.get("fill_price"))
    tick = _TICKS.get(str(record.get("inst", "")).upper())
    expected_entry = _number(record.get("expected_entry"))
    stop_reference = _number(record.get("expected_stop"))
    raw_slip = _number(record.get("slip"))

    if trade_type == "OPEN":
        reference_type = "expected_entry"
        reference_price = expected_entry
        slippage_points = raw_slip
        metric_type = "execution_slippage"
    elif exit_reason == "STP":
        reference_type = "stop_trigger"
        reference_price = stop_reference
        slippage_points = raw_slip
        if slippage_points is None and reference_price is not None and actual is not None:
            slippage_points = _signed_stop_slippage(record, reference_price, actual)
        metric_type = "execution_slippage"
    elif stop_reference is not None:
        # The runner calls this C1 CLOSE slippage, but the submitted order is MARKET.
        # stop_ref is the protective risk level, not a decision-time expected quote.
        reference_type = "protective_stop_reference"
        reference_price = stop_reference
        slippage_points = None
        metric_type = "distance_to_stop"
    else:
        reference_type = "unavailable"
        reference_price = None
        slippage_points = None
        metric_type = "unavailable"

    reference_distance = raw_slip if metric_type == "distance_to_stop" else None
    slippage_ticks = slippage_points / tick if slippage_points is not None and tick else None
    distance_ticks = reference_distance / tick if reference_distance is not None and tick else None
    ordered = _number(record.get("contracts"))
    filled = _number(record.get("filled_qty"))
    if filled is None:
        filled = ordered
    status = str(record.get("status") or "UNKNOWN").upper()
    partial = bool(ordered is not None and filled is not None and filled < ordered)
    exception_reasons = []
    if status not in {"FILLED", "PARTIAL"}:
        exception_reasons.append(f"status {status}")
    if partial or status == "PARTIAL":
        exception_reasons.append("partial fill")
    if actual is None:
        exception_reasons.append("fill price missing")
    if slippage_ticks is not None and slippage_ticks > _ASSUMED_SLIPPAGE_TICKS:
        exception_reasons.append(f"adverse slippage {slippage_ticks:.2f} ticks exceeds 2-tick paper assumption")

    if trade_type == "OPEN":
        action = "BUY" if direction == "LONG" else "SELL"
    else:
        action = "SELL" if direction == "LONG" else "BUY"
    return {
        "key": f"{trade_type}:{record.get('inst', '?')}:{record.get('ts') or index}",
        "day": _day(record), "ts": record.get("ts"),
        "type": trade_type, "inst": record.get("inst"), "cluster": record.get("cluster"),
        "direction": direction, "action": action, "exit_reason": record.get("exit_reason"),
        "ordered_qty": ordered, "filled_qty": filled, "status": status, "partial": partial,
        "reference_type": reference_type, "reference_price": reference_price,
        "actual_price": actual, "metric_type": metric_type,
        "signed_slippage_points": slippage_points, "signed_slippage_ticks": slippage_ticks,
        "signed_distance_to_stop_points": reference_distance,
        "signed_distance_to_stop_ticks": distance_ticks,
        "adverse": slippage_ticks is not None and slippage_ticks > 0,
        "commission": _number(record.get("commission")),
        "route": record.get("route") or record.get("exchange"),
        "order_id": record.get("order_id"), "perm_id": record.get("perm_id"),
        "source": record.get("source") or "runner_trade_log",
        "exception": bool(exception_reasons), "exception_reasons": exception_reasons,
    }


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "worst": None,
                "adverse_count": 0, "over_assumption_count": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 3),
        "median": round(statistics.median(values), 3),
        "worst": round(max(values), 3),
        "adverse_count": sum(value > 0 for value in values),
        "over_assumption_count": sum(value > _ASSUMED_SLIPPAGE_TICKS for value in values),
    }


def read_execution_quality(root: Path, day: str | None = None) -> dict[str, Any]:
    path = root / "trade_log.jsonl"
    try:
        stat = path.stat()
    except OSError as exc:
        return {"source": "trade_log.jsonl", "day": day, "observed_at": None,
                "fills": [], "exceptions": [], "summary": {}, "coverage": {}, "error": str(exc)}
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size, day)
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return copy.deepcopy(cached)

    records = []
    malformed = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if isinstance(value, dict):
                    records.append(value)
    except OSError as exc:
        return {"source": path.name, "day": day, "observed_at": None,
                "fills": [], "exceptions": [], "summary": {}, "coverage": {}, "error": str(exc)}

    fills = [_normalise(record, index) for index, record in enumerate(records)
             if day is None or _day(record) == day]
    execution_ticks = [item["signed_slippage_ticks"] for item in fills
                       if item["signed_slippage_ticks"] is not None]
    open_ticks = [item["signed_slippage_ticks"] for item in fills
                  if item["type"] == "OPEN" and item["signed_slippage_ticks"] is not None]
    stop_ticks = [item["signed_slippage_ticks"] for item in fills
                  if item["reference_type"] == "stop_trigger" and item["signed_slippage_ticks"] is not None]
    signal_closes = [item for item in fills if item["type"] == "CLOSE"
                     and item["reference_type"] == "protective_stop_reference"]
    coverage = {
        "fill_records": len(fills),
        "execution_slippage_evaluable": len(execution_ticks),
        "signal_close_expected_price_missing": len(signal_closes),
        "commission_emitted": sum(item["commission"] is not None for item in fills),
        "route_emitted": sum(item["route"] is not None for item in fills),
        "stable_execution_id_emitted": sum(item["perm_id"] is not None for item in fills),
        "malformed_lines": malformed,
    }
    def _field_status(observed: int) -> str:
        if not fills:
            return "not_observed"
        return "available" if observed == len(fills) else "missing"
    result = {
        "source": path.name, "day": day,
        "observed_at": dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "assumption_ticks": _ASSUMED_SLIPPAGE_TICKS,
        "fills": fills,
        "exceptions": [item for item in fills if item["exception"]],
        "summary": {
            "all_evaluable": _distribution(execution_ticks),
            "opens": _distribution(open_ticks),
            "stop_fills": _distribution(stop_ticks),
            "signal_market_closes_not_evaluable": len(signal_closes),
        },
        "coverage": coverage,
        "gaps": [
            {"field": "signal_close_expected_price", "status": "missing" if signal_closes else "not_observed",
             "detail": "Signal exits log a protective stop reference, not a decision-time expected market price."},
            {"field": "commission", "status": _field_status(coverage["commission_emitted"]),
             "detail": f"Commission emitted for {coverage['commission_emitted']}/{len(fills)} retained fills."},
            {"field": "route", "status": _field_status(coverage["route_emitted"]),
             "detail": f"Execution route emitted for {coverage['route_emitted']}/{len(fills)} retained fills."},
        ],
        "error": None,
    }
    with _lock:
        _cache.clear()
        _cache[key] = copy.deepcopy(result)
    return result
