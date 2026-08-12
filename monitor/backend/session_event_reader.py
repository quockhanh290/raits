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
_OPEN_SENT = re.compile(
    r"send_order: placed OPEN (?P<action>BUY|SELL) (?P<inst>\w+) (?:×|Ã—)(?P<qty>[\d.]+) cluster=(?P<cluster>\S+)"
)
_OPEN_FILLED = re.compile(
    r"send_order: FILLED OPEN (?P<inst>\w+) (?:×|Ã—)(?P<qty>[\d.]+) @ (?P<price>[\d.]+)"
)
_ENTRY_REJECTED = re.compile(
    r"REJECTED (?P<direction>LONG|SHORT) (?P<inst>\w+) \((?P<cluster>[^)]+)\) "
    r"risk_sized=\$(?P<risk_sized>[\d,.]+)\s+[^A-Za-z0-9$]+\s+(?P<reason>.+)$"
)
_LEDGER_CLOSE = re.compile(
    r"LEDGER: (?P<inst>\w+) (?P<direction>LONG|SHORT) x(?P<qty>[\d.]+) (?P<cluster>\S+) "
    r"(?P<entry_price>[\d.]+)\s+\S+\s+(?P<exit_price>[\d.]+) = (?P<pnl>[+-]?[\d.]+) "
    r"\((?P<exit_reason>[^)]+)\) \| sleeve equity (?P<sleeve_equity>[\d.]+)"
)
_STOP_CANCELLED = re.compile(
    r"STP: cancelled GTC stop orderId=(?P<order_id>\d+) for closed (?P<inst>\w+)/(?P<cluster>\S+)"
)
_STOP_EXIT = re.compile(
    r"B3 STP EXIT: (?P<inst>\w+) (?P<direction>LONG|SHORT) stop orderId=(?P<order_id>\d+) filled @ (?P<price>[\d.]+)"
)
_STOP_REPLACED = re.compile(
    r"B4 REPLACED: (?P<inst>\w+)/(?P<cluster>\S+) was open with no stop order\s+\S+\s+"
    r"re-placed @ (?P<price>[\d.]+) orderId=(?P<order_id>\d+)"
)
_B4_ID_DRIFT = re.compile(
    r"B4 STP ID DRIFT: (?P<direction>LONG|SHORT) (?P<inst>\w+) x(?P<qty>\d+) "
    r"\((?P<cluster>[^)]+)\) IS covered at the broker, but the recorded "
    r"stop_order_id=(?P<recorded_order_id>\S+) names no working order"
)
_B4_NAKED = re.compile(
    r"B4 NAKED: (?P<direction>LONG|SHORT) (?P<inst>\w+) x(?P<qty>\d+) "
    r"\((?P<cluster>[^)]+)\) open at IBKR with NO stop order "
    r"\(stop_price=(?P<stop_price>[^)]+)\)"
)
_RECONCILE_MISMATCH = re.compile(
    r"B3 MISMATCH: file has (?P<direction>LONG|SHORT) (?P<inst>\w+)\s+\S+(?P<file_qty>[\d.]+) "
    r"but IBKR shows\s+\S+(?P<broker_qty>[\d.]+)\s+\S+\s+(?P<detail>.+)$"
)
_RECONCILE_ORPHAN = re.compile(
    r"B3 ORPHAN: IBKR has (?P<direction>LONG|SHORT) (?P<inst>\w+)\s+\S+(?P<broker_qty>[\d.]+) "
    r"with no matching file entry\s+\S+\s+(?P<detail>.+)$"
)
_RECONCILE_MATCH = re.compile(r"B3: broker/file positions match \((?P<count>\d+) position\(s\)\)")
_IBKR_CONNECTIVITY = re.compile(
    r"IBKR code=(?P<code>1100|1101|1102|2103|2104|2105|2106|2157|2158) "
    r"reqId=[^:]+: (?P<detail>.+)$"
)
_HMM_LABELS = re.compile(r"\[hmm\]\s+fit_C labels \(hmm_fit_end=(?P<fit_end>\d{4}-\d{2}-\d{2})\)")
_HMM_STARTED = re.compile(
    r"HMM fit started: (?P<observations>\d+) price observations, "
    r"covariance=(?P<covariance>\w+), n_init=(?P<n_init>\d+)"
)
_HMM_NON_CONVERGENCE = re.compile(
    r"Model is not converging\.\s+Current: (?P<current>-?[\d.]+) is not greater than "
    r"(?P<previous>-?[\d.]+)\. Delta is (?P<delta>-?[\d.]+)"
)
_HMM_BEST = re.compile(
    r"Best initialisation: log-prob=(?P<best_log_prob>-?[\d.]+) "
    r"\(out of (?P<tries>\d+) tries\)"
)
_HMM_SUMMARY = re.compile(r"HMM Model Summary \(version: (?P<model_version>[^)]+)\)")
_HMM_STATE = re.compile(
    r"State (?P<state_index>\d+) \((?P<state_label>[^)]+)\): .*?"
    r"\[(?P<state_mean>[^]]+)\].*?var_trace=(?P<variance_trace>[\d.]+)"
)
_SPY_LABEL_DAYS = re.compile(r"(?P<spy_label_days>\d+) SPY label days")
_CONNECTIVITY_CODES = {
    "1100": ("tws", "down"), "1101": ("tws", "up"), "1102": ("tws", "up"),
    "2103": ("market_data", "down"), "2104": ("market_data", "up"),
    "2105": ("historical_data", "down"), "2106": ("historical_data", "up"),
    "2157": ("security_definition", "down"), "2158": ("security_definition", "up"),
}
_CONNECTIVITY_NAMES = {
    "tws": "TWS",
    "market_data": "Market data farm",
    "historical_data": "Historical data farm",
    "security_definition": "Security-definition farm",
}

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
    found = _HMM_LABELS.search(message)
    if found:
        return _event(stamp, "MODEL", "hmm_fit_config", message, **found.groupdict())
    found = _HMM_STARTED.search(message)
    if found:
        return _event(stamp, "MODEL", "hmm_fit_started", message, **found.groupdict())
    found = _HMM_NON_CONVERGENCE.search(message)
    if found:
        return _event(stamp, "MODEL", "hmm_non_convergence", message,
                      level="WARN", **found.groupdict())
    found = _HMM_BEST.search(message)
    if found:
        return _event(stamp, "MODEL", "hmm_best_initialisation", message, **found.groupdict())
    found = _HMM_SUMMARY.search(message)
    if found:
        return _event(stamp, "MODEL", "hmm_model_summary", message, **found.groupdict())
    found = _HMM_STATE.search(message)
    if found:
        return _event(stamp, "MODEL", "hmm_state_diagnostic", message, **found.groupdict())
    found = _SPY_LABEL_DAYS.search(message)
    if found:
        return _event(stamp, "MODEL", "hmm_label_coverage", message, **found.groupdict())
    found = _IBKR_CONNECTIVITY.search(message)
    if found:
        item = found.groupdict()
        service, transition = _CONNECTIVITY_CODES[item["code"]]
        return _event(stamp, "IBKR CONNECTIVITY", "connectivity_transition", message,
                      service=service, transition=transition, component="broker", **item)
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
    found = _OPEN_SENT.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "EXEC", "market_open_submitted",
                      f"Submitted MARKET OPEN {item['action']} {item['inst']} x{item['qty']}", **item)
    found = _OPEN_FILLED.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "EXEC", "market_open_filled",
                      f"Filled MARKET OPEN {item['inst']} x{item['qty']} @ {item['price']}", **item)
    found = _ENTRY_REJECTED.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "DECISION", "entry_rejected",
                      f"Rejected {item['direction']} {item['inst']}: {item['reason']}", **item)
    found = _LEDGER_CLOSE.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "DECISION", "trade_exit_decision",
                      f"Exited {item['inst']} {item['direction']} via {item['exit_reason']}: {item['pnl']}", **item)
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
    found = _STOP_REPLACED.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "PROTECTION", "stop_replaced",
                      f"Replaced missing {item['inst']} stop @ {item['price']} / #{item['order_id']}",
                      level="WARN", component="runner", **item)
    found = _B4_ID_DRIFT.search(message)
    if found:
        item = found.groupdict()
        return _event(
            stamp, "PROTECTION", "stop_id_drift",
            f"{item['inst']} is protected, but runner stop ID {item['recorded_order_id']} is not working",
            level="WARN", status="open", component="runner",
            title=f"{item['inst']} stop order ID drift",
            problem="The broker position is protected, but persisted runner state names a different or dead stop order.",
            impact="A later close may cancel a ghost ID and leave the real stop working without a position.",
            action="Reconcile the persisted stop ID with the live IBKR protective order using the approved repair workflow.",
            evidence=message, resolution="Open: persisted and live protective order IDs have not been reconciled.",
            **item,
        )
    found = _B4_NAKED.search(message)
    if found:
        item = found.groupdict()
        return _event(
            stamp, "PROTECTION", "stop_naked",
            f"{item['inst']} is open at IBKR with no protective stop",
            level="CRITICAL", status="open", component="broker",
            title=f"{item['inst']} position is unprotected",
            problem="Runner and broker agree the position is open, but IBKR has no working protective stop.",
            impact="The open position has no broker-side overnight loss protection.",
            action="Verify IBKR immediately and follow the approved manual protection or close procedure.",
            evidence=message, resolution="Open: no later accepted protective stop was observed.",
            **item,
        )
    found = _RECONCILE_MISMATCH.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "BROKER RECONCILE", "reconcile_transition", message,
                      transition="problem", reconcile_type="mismatch", component="runner", **item)
    found = _RECONCILE_ORPHAN.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "BROKER RECONCILE", "reconcile_transition", message,
                      transition="problem", reconcile_type="orphan", component="runner", **item)
    found = _RECONCILE_MATCH.search(message)
    if found:
        item = found.groupdict()
        return _event(stamp, "BROKER RECONCILE", "reconcile_transition",
                      f"Broker and runner positions matched ({item['count']})",
                      transition="matched", component="runner", **item)
    return None


def _log_paths(day: str, root: Path) -> list[Path]:
    parsed = dt.date.fromisoformat(day)
    # ET midnight occurs on the previous Edmonton date. Read both possible local
    # files, then filter parsed events by their ET session date.
    return [root / f"live_day_{value:%m%d}.log" for value in (parsed - dt.timedelta(days=1), parsed)]


def _seconds_between(start: str, end: str) -> int:
    return max(0, round((dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
                         - dt.datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()))


def _service_connectivity_lifecycles(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_outages: dict[str, dict[str, Any]] = {}
    lifecycles: list[dict[str, Any]] = []
    for event in sorted((item for item in events if item["kind"] == "connectivity_transition"),
                        key=lambda item: item["ts"]):
        service = event["service"]
        if event["transition"] == "down":
            outage = open_outages.setdefault(service, {"first": event, "observations": []})
            outage["observations"].append(event)
            continue
        outage = open_outages.pop(service, None)
        if outage is None:
            continue
        first = outage["first"]
        name = _CONNECTIVITY_NAMES[service]
        duration = _seconds_between(first["ts"], event["ts"])
        evidence = " | ".join(
            f"{item['code']}: {item['detail']}" for item in [*outage["observations"], event]
        )
        lifecycles.append({
            **event,
            "kind": "connectivity_outage",
            "status": "recovered",
            "level": "WARN",
            "title": f"{name} connectivity recovered",
            "message": f"{name} was unavailable for {duration}s and recovered.",
            "started_at": first["ts"],
            "incurred_at": first["ts"],
            "recovered_at": event["ts"],
            "duration_seconds": duration,
            "down_code": first["code"],
            "recovery_code": event["code"],
            "problem": f"{name} connectivity was reported unavailable by IBKR.",
            "impact": ("Broker connectivity and current order/position visibility may have been stale during this interval."
                       if service == "tws" else f"The IBKR {name.lower()} service was unavailable during this interval."),
            "action": "No immediate action after recovery. Review if outages recur or overlap a trading decision.",
            "evidence": evidence,
            "resolution": f"Recovered via IBKR code {event['code']} after {duration}s.",
        })
    for service, outage in open_outages.items():
        first = outage["first"]
        name = _CONNECTIVITY_NAMES[service]
        evidence = " | ".join(f"{item['code']}: {item['detail']}" for item in outage["observations"])
        lifecycles.append({
            **first,
            "kind": "connectivity_outage",
            "status": "open",
            "level": "CRITICAL" if service == "tws" else "WARN",
            "title": f"{name} connectivity unavailable",
            "message": f"{name} reported unavailable with no recovery evidence in the retained session log.",
            "started_at": first["ts"],
            "incurred_at": first["ts"],
            "recovered_at": None,
            "duration_seconds": None,
            "down_code": first["code"],
            "recovery_code": None,
            "problem": f"{name} connectivity was reported unavailable by IBKR and has no logged recovery.",
            "impact": ("Current broker order/position visibility cannot be assumed reliable."
                       if service == "tws" else f"The IBKR {name.lower()} service may still be unavailable."),
            "action": "Check IBKR/TWS connectivity and verify current broker state now.",
            "evidence": evidence,
            "resolution": "Open: no matching IBKR recovery code was observed.",
        })
    return lifecycles


def _as_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _connectivity_episodes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lifecycles = sorted(_service_connectivity_lifecycles(events), key=lambda item: item["started_at"])
    groups: list[list[dict[str, Any]]] = []
    for lifecycle in lifecycles:
        start = _as_datetime(lifecycle["started_at"])
        group = groups[-1] if groups else []
        if group:
            group_start = _as_datetime(group[0]["started_at"])
            recovered = [item.get("recovered_at") for item in group]
            group_end = max((_as_datetime(value) for value in recovered if value), default=start)
            services = {item["service"] for item in group}
            correlated = (lifecycle["service"] not in services
                          and start <= group_end
                          and (start - group_start).total_seconds() <= 30)
        else:
            correlated = False
        if correlated:
            group.append(lifecycle)
        else:
            groups.append([lifecycle])

    episodes = []
    for group in groups:
        first = min(group, key=lambda item: item["started_at"])
        open_services = [item for item in group if item["status"] == "open"]
        recovered_at = None if open_services else max(item["recovered_at"] for item in group)
        duration = _seconds_between(first["started_at"], recovered_at) if recovered_at else None
        affected = [item["service"] for item in group]
        names = [_CONNECTIVITY_NAMES[service] for service in affected]
        plural = len(group) > 1
        status = "open" if open_services else "recovered"
        evidence = " | ".join(
            f"{_CONNECTIVITY_NAMES[item['service']]} [{item['down_code']} -> {item.get('recovery_code') or 'no recovery'}]: "
            f"{item['evidence']}" for item in group
        )
        if plural:
            title = f"IBKR connectivity {'unavailable' if open_services else 'recovered'}"
            message = (f"{len(group)} correlated IBKR services were unavailable"
                       + ("; at least one has no recovery evidence."
                          if open_services else f" for up to {duration}s and recovered."))
            problem = f"Correlated connectivity loss affected {', '.join(names)}."
        else:
            title = first["title"]
            message = first["message"]
            problem = first["problem"]
        episodes.append({
            **first,
            "ts": recovered_at or first["started_at"],
            "kind": "connectivity_outage",
            "status": status,
            "level": "CRITICAL" if open_services else "WARN",
            "title": title,
            "message": message,
            "problem": problem,
            "service": affected[0] if not plural else "multiple",
            "affected_services": affected,
            "services": [{
                "service": item["service"], "status": item["status"],
                "started_at": item["started_at"], "recovered_at": item.get("recovered_at"),
                "duration_seconds": item.get("duration_seconds"),
                "down_code": item["down_code"], "recovery_code": item.get("recovery_code"),
                "evidence": item["evidence"],
            } for item in group],
            "started_at": first["started_at"],
            "incurred_at": first["started_at"],
            "recovered_at": recovered_at,
            "duration_seconds": duration,
            "impact": ("Broker connectivity and current order/position visibility may have been stale during this interval."
                       if "tws" in affected else "The affected IBKR data services were unavailable during this interval."),
            "action": ("Check IBKR/TWS connectivity and verify current broker state now."
                       if open_services else "No immediate action after recovery. Review if outages recur or overlap a trading decision."),
            "evidence": evidence,
            "resolution": (first["resolution"] if not plural else
                           ("Open: " + ", ".join(_CONNECTIVITY_NAMES[item["service"]] for item in open_services)
                            + " has no matching recovery code."
                            if open_services else f"All affected services recovered; last recovery after {duration}s.")),
        })
    return episodes


def _reconcile_episodes(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for event in sorted((item for item in events if item["kind"] == "reconcile_transition"),
                        key=lambda item: item["ts"]):
        if event["transition"] == "problem":
            if current is None:
                current = {"first": event, "observations": []}
            current["observations"].append(event)
            continue
        if current is None:
            continue
        first = current["first"]
        observations = current["observations"]
        duration = _seconds_between(first["ts"], event["ts"])
        types = sorted({item["reconcile_type"] for item in observations})
        instruments = sorted({item.get("inst", "?") for item in observations})
        evidence = " | ".join(dict.fromkeys(item["message"] for item in observations))
        episodes.append({
            **event,
            "kind": "broker_reconcile_incident",
            "status": "recovered",
            "level": "WARN",
            "title": "Broker/runner position mismatch recovered",
            "message": (f"Broker reconciliation reported {', '.join(types)} for "
                        f"{', '.join(instruments)}; a later runner check matched after {duration}s."),
            "started_at": first["ts"], "incurred_at": first["ts"],
            "recovered_at": event["ts"], "duration_seconds": duration,
            "occurrences": len(observations), "reconcile_types": types,
            "instruments": instruments,
            "problem": "Runner persisted positions and IBKR positions did not reconcile.",
            "impact": "Entry decisions during the mismatch could rely on runner file state rather than confirmed broker state.",
            "action": "No immediate action after recovery. Investigate symbol normalization or external positions if this recurs.",
            "evidence": evidence,
            "resolution": f"Recovered when a runner check reported {event['count']} matched position(s) after {duration}s.",
        })
        current = None
    if current is not None:
        first = current["first"]
        observations = current["observations"]
        types = sorted({item["reconcile_type"] for item in observations})
        instruments = sorted({item.get("inst", "?") for item in observations})
        episodes.append({
            **first,
            "kind": "broker_reconcile_incident",
            "status": "open",
            "level": "CRITICAL",
            "title": "Broker/runner positions do not reconcile",
            "message": f"Open {', '.join(types)} affecting {', '.join(instruments)}.",
            "started_at": first["ts"], "incurred_at": first["ts"],
            "recovered_at": None, "duration_seconds": None,
            "occurrences": len(observations), "reconcile_types": types,
            "instruments": instruments,
            "problem": "Runner persisted positions and IBKR positions do not reconcile.",
            "impact": "Current broker exposure cannot be inferred safely from runner state alone.",
            "action": "Reconcile current IBKR positions, working stops, and runner persisted positions now.",
            "evidence": " | ".join(dict.fromkeys(item["message"] for item in observations)),
            "resolution": "Open: no later broker/file match was observed in the retained session log.",
        })
    return episodes


def _collapse_stop_lifecycle(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(events, key=lambda item: item["ts"])
    deferred: dict[tuple[str, str], dict[str, Any]] = {}
    accepted_by_order = {
        str(item["order_id"]): item for item in ordered
        if item["kind"] == "stop_armed" and item.get("order_id")
    }
    replacement_orders = {
        str(item["order_id"]) for item in ordered
        if item["kind"] == "stop_replaced" and item.get("order_id")
    }
    collapsed = []
    for event in ordered:
        key = (str(event.get("inst", "")), str(event.get("cluster", "")))
        if event["kind"] == "stop_deferred":
            deferred[key] = event
        if event["kind"] == "stop_armed" and str(event.get("order_id")) in replacement_orders:
            continue
        if event["kind"] == "stop_replaced":
            accepted = accepted_by_order.get(str(event.get("order_id")))
            was_deferred = key in deferred and deferred[key]["ts"] <= event["ts"]
            event.update({field: accepted[field] for field in
                          ("direction", "qty", "status") if accepted and field in accepted})
            event["accepted_price"] = accepted.get("price") if accepted else None
            event["kind"] = "stop_armed_after_deferral" if was_deferred else "stop_repaired"
            event["title"] = (f"{event['inst']} stop armed after deliberate deferral" if was_deferred
                              else f"{event['inst']} missing stop repaired")
            event["message"] = (f"Armed {event['inst']} stop #{event['order_id']} after the deliberate stop-free window"
                                if was_deferred else
                                f"B4 repaired missing {event['inst']} stop with order #{event['order_id']}")
            event["status"] = "info" if was_deferred else "recovered"
            event["level"] = "INFO" if was_deferred else "WARN"
            event["started_at"] = event["ts"]
            event["recovered_at"] = None if was_deferred else event["ts"]
            event["problem"] = ("The position was intentionally unprotected during its documented deferral window."
                                if was_deferred else "B4 observed an open position missing its expected working stop.")
            event["impact"] = ("No incident: the absence of a stop was expected until this arming point."
                               if was_deferred else "The position was unprotected until B4 successfully placed this order.")
            event["action"] = "No action; verify current IBKR protection through Realtime."
            event["evidence"] = ((accepted.get("message", "") + " | ") if accepted else "") + event["message"]
            event["resolution"] = f"IBKR accepted working stop #{event['order_id']}."
        collapsed.append(event)

    protective = [item for item in collapsed if item["kind"] in {
        "stop_armed", "stop_armed_after_deferral", "stop_repaired"
    }]
    for issue in collapsed:
        if issue["kind"] not in {"stop_id_drift", "stop_naked"}:
            continue
        recovery = next((item for item in protective
                         if item.get("inst") == issue.get("inst")
                         and item.get("cluster") == issue.get("cluster")
                         and item["ts"] > issue["ts"]), None)
        if recovery:
            issue["status"] = "recovered"
            issue["recovered_at"] = recovery["ts"]
            issue["resolution"] = f"Recovered when IBKR accepted stop #{recovery.get('order_id', '--')}."
    return sorted(collapsed, key=lambda item: item["ts"])


def _hmm_fit_diagnostic(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    model_events = sorted(
        (item for item in events if item["kind"].startswith("hmm_")),
        key=lambda item: item["ts"],
    )
    starts = [item for item in model_events if item["kind"] == "hmm_fit_started"]
    if not starts:
        return None
    warnings = [item for item in model_events if item["kind"] == "hmm_non_convergence"]
    best = [item for item in model_events if item["kind"] == "hmm_best_initialisation"]
    summaries = [item for item in model_events if item["kind"] == "hmm_model_summary"]
    configs = [item for item in model_events if item["kind"] == "hmm_fit_config"]
    coverage = [item for item in model_events if item["kind"] == "hmm_label_coverage"]
    latest_summary = summaries[-1] if summaries else None
    latest_best = best[-1] if best else None
    latest_warning = warnings[-1] if warnings else None
    latest_start = starts[-1]
    latest_config = configs[-1] if configs else None
    latest_coverage = coverage[-1] if coverage else None
    latest_states: dict[str, dict[str, Any]] = {}
    for item in (entry for entry in model_events if entry["kind"] == "hmm_state_diagnostic"):
        latest_states[item["state_label"]] = {
            "index": int(item["state_index"]),
            "label": item["state_label"],
            "mean": [float(value) for value in item["state_mean"].split()],
            "variance_trace": float(item["variance_trace"]),
        }
    attempts = len(starts)
    completed = len(summaries)
    warning_count = len(warnings)
    latest = model_events[-1]
    completion = (f"{completed}/{attempts} fits emitted a model summary"
                  if completed != attempts else f"all {attempts} fits emitted a model summary")
    warning_text = (f"convergence warning observed on {warning_count}/{attempts} fits"
                    if warning_count else "no convergence warning observed")
    evidence = [
        f"{attempts} fit attempts; {completion}; {warning_text}.",
        (f"Latest best initialisation log-prob={latest_best['best_log_prob']} "
         f"from {latest_best['tries']} tries." if latest_best else
         "No best-initialisation line was retained."),
        (f"Latest model summary version={latest_summary['model_version']}." if latest_summary else
         "No model-summary line was retained."),
    ]
    if latest_states:
        evidence.append("Fitted states: " + "; ".join(
            f"{item['label']} mean={item['mean']} var_trace={item['variance_trace']:.6f}"
            for item in sorted(latest_states.values(), key=lambda value: value["index"])
        ) + ".")
    return {
        **latest,
        "kind": "hmm_fit_diagnostic",
        "category": "MODEL / HMM FIT",
        "status": "diagnostic",
        "level": "WARN" if warning_count else "INFO",
        "component": "runner",
        "title": "HMM fit completed with recurring convergence warning" if warning_count else "HMM fit completed",
        "message": f"{completion.capitalize()}; {warning_text}.",
        "started_at": starts[0]["ts"],
        "first_ts": starts[0]["ts"],
        "occurrences": attempts,
        "attempts": attempts,
        "completed_fits": completed,
        "non_convergence_count": warning_count,
        "fit_end": latest_config.get("fit_end") if latest_config else None,
        "observations": int(latest_start["observations"]),
        "covariance": latest_start["covariance"],
        "n_init": int(latest_start["n_init"]),
        "best_log_prob": float(latest_best["best_log_prob"]) if latest_best else None,
        "latest_delta": float(latest_warning["delta"]) if latest_warning else None,
        "model_version": latest_summary.get("model_version") if latest_summary else None,
        "spy_label_days": int(latest_coverage["spy_label_days"]) if latest_coverage else None,
        "states": sorted(latest_states.values(), key=lambda item: item["index"]),
        "problem": "The optimizer emitted a non-convergence warning during one or more HMM fits.",
        "impact": ("Diagnostic only: the retained log still shows best-initialisation selection and a complete "
                   "model summary; no documented decision gate failure was emitted."),
        "action": "No immediate operational action. Review convergence quality during scheduled model maintenance.",
        "evidence": " ".join(evidence),
        "resolution": "Latest fit selected its best initialisation and emitted fitted-state diagnostics.",
    }


def _dedupe(events: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}
    session_events = [event for event in events if event["session_day"] == day]
    for event in session_events:
        if event["kind"] in {"connectivity_transition", "reconcile_transition"} or event["kind"].startswith("hmm_"):
            continue
        if event["kind"] in {"stop_deferred", "entry_rejected"}:
            identity = event.get("cluster") or ""
        elif event.get("order_id"):
            identity = event["order_id"]
        else:
            # Separate executions of the same instrument are distinct daily activity.
            identity = event["ts"]
        key = (event["kind"], str(event.get("inst", "")), str(identity))
        # Repeated deferred checks add no information; retain only the latest observation.
        previous = selected.get(key)
        if previous is not None:
            event["first_ts"] = previous.get("first_ts", previous["ts"])
            event["occurrences"] = int(previous.get("occurrences", 1)) + 1
        else:
            event["first_ts"] = event["ts"]
            event["occurrences"] = 1
        selected[key] = event
    # Lifecycle normalization mutates records to attach recovery context. Work on
    # copies so repeated API reads cannot alter the incremental raw-event cache.
    hmm_diagnostic = _hmm_fit_diagnostic(session_events)
    normalized_input = copy.deepcopy([
        *selected.values(), *_connectivity_episodes(session_events), *_reconcile_episodes(session_events),
        *([hmm_diagnostic] if hmm_diagnostic else []),
    ])
    return _collapse_stop_lifecycle(normalized_input)


def read_session_events(day: str, root: Path) -> dict[str, Any]:
    available: list[tuple[Path, Any]] = []
    errors = []
    for path in _log_paths(day, root):
        try:
            available.append((path, path.stat()))
        except OSError as exc:
            errors.append(str(exc))
    if not available:
        return {"source": "live_log", "day": day, "observed_at": None,
                "events": [], "error": "; ".join(errors)}

    with _lock:
        all_events = []
        for path, stat in available:
            cache_key = str(path.resolve())
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
            all_events.extend(cached["events"])
        events = _dedupe(all_events, day)

    observed = dt.datetime.fromtimestamp(max(stat.st_mtime for _path, stat in available), tz=dt.timezone.utc)
    return {"source": "live_log", "day": day,
            "observed_at": observed.isoformat().replace("+00:00", "Z"),
            "events": copy.deepcopy(events), "error": None}
