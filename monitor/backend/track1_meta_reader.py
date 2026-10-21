"""The runner-state payload, rebuilt from Track 1 sources only. Plan stage 2.

Until 2026-09-24 `/api/v1/runner-state` served `live_state_data.js` as its payload — the legacy
route's file, 31 days old that evening, carrying a broker equity four times the real account.
Stage 0 labelled it; this replaces it. The rule:

    every key is EITHER sourced from Track 1 OR absent.

No legacy value survives in `payload`. The legacy file is still served, stamped stale, under
`legacy_payload`, because it is history and the page has uses for history — just never as the
present.

Every key's origin is declared in `payload_sources`, keyed by dotted path, and a test walks the
payload and refuses any key without an entry there. Absence is also declared, in
`payload_absent`, with the reason: a field that is missing because nobody could find a Track 1
source is a different fact from one that was forgotten, and only a declared absence can be
told apart from a bug.

Read-only in every branch. It never opens a broker connection — the connection state is read
from the backend's existing reader cache, which is its own process-local thread.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Any, Callable

#: Where the scheduler writes its log. A heartbeat line lands every minute.
SCHEDULER_LOG = "monitor/logs/ops_scheduler.err.log"

#: How much of the log's tail is read to find the newest heartbeat. The heartbeat writes a
#: "Running job" and an "executed successfully" line every 60 s, plus every other job's
#: chatter; 256 KB held 2,300+ lines on 2026-09-24, many minutes of beats.
_TAIL_BYTES = 256 * 1024

#: Past this, the backend's IBKR reader is not a reading of the present. It polls every 10 s.
IBKR_READING_MAX_AGE_SECONDS = 120

_HEARTBEAT = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s.*Job \"Heartbeat 60s .*executed successfully")

#: Fields the legacy payload carried that have NO Track 1 source today — declared, not dropped
#: silently. Each reason says what was searched, so the next person does not search again.
ABSENT = {
    "meta.net_pnl": ("the realised series is in `snapshots[].cumulative_realised_pnl`; a single "
                     "net figure is not published while it could hide a refused day"),
    "meta.final_equity": ("no Track 1 equity curve exists — the book's equity is 0.0 because no "
                          "P&L is booked, and the broker account is not attributable per route"),
    "meta.max_dd_pct": "needs an equity curve (see final_equity)",
    "meta.max_dd_dollars": "needs an equity curve (see final_equity)",
    "meta.system_epoch": "legacy's own epoch; Track 1's start is `paper_start`",
    "meta.backtest_calmar": ("no Track 1 artefact publishes one — searched track1_params, "
                             "track1_gates, track1_report, track1_slots on 2026-09-24"),
    "meta.target_dd_pct": "no Track 1 drawdown target is published anywhere (same search)",
    "meta.hard_dd_pct": ("15% is the legacy futures RISK config; not measured to apply to "
                         "this route (realtime.js Stage 5ZZZ-CG says the same)"),
    "meta.daily_loss_pct": "legacy RISK config; no Track 1 equivalent published",
    "meta.n_contracts": "Track 1 sizes per sleeve (`SLEEVE_QTY`), not one global count",
    "meta.operational_status": ("PARTIAL at best: Track1Book's breaker reads equity 0.0 because "
                                "no P&L is booked — a breaker on a zero curve is not a reading"),
    "meta.breaker_events": "same as operational_status",
    "meta.events": "the legacy runner's event list; Track 1 events are in the job journal",
}


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _tail(path: Path, nbytes: int = _TAIL_BYTES) -> str:
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - nbytes))
        return fh.read().decode("utf-8", errors="replace")


def last_heartbeat(root: Path) -> dict:
    """The newest scheduler heartbeat in the log, or why there is none.

    The log stamps machine-local time with no offset (Calgary on this machine; the ET clock is
    in the same line's "next run at … EDT"). Converted here with the machine's own zone,
    which is the zone that wrote it — the backend runs on the same host as the scheduler."""
    p = root / SCHEDULER_LOG
    try:
        text = _tail(p)
    except OSError as exc:
        return {"at": None, "state": "unknown", "error": f"{type(exc).__name__}: {exc}"}
    for line in reversed(text.splitlines()):
        m = _HEARTBEAT.match(line)
        if m:
            local = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").astimezone()
            return {"at": _iso(local), "state": "observed", "error": None}
    return {"at": None, "state": "unknown",
            "error": f"no heartbeat in the last {_TAIL_BYTES // 1024} KB of the scheduler log"}


def ibkr_connection(cache: dict, now: dt.datetime) -> dict:
    """Three states. `connected` only if the reader said so within the last two minutes."""
    last = cache.get("last_update")
    age = None
    if last:
        try:
            seen = dt.datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            age = max(0.0, (now - seen).total_seconds())
        except ValueError:
            age = None
    if age is None or age > IBKR_READING_MAX_AGE_SECONDS:
        state = "unknown"
    else:
        state = "connected" if cache.get("connected") else "disconnected"
    return {"state": state, "as_of": last, "age_seconds": age}


def _audit_days(root: Path) -> list:
    from monitor.backend.track1_runtime_reader import AUDITS_DIR
    d = root / AUDITS_DIR
    days = []
    for f in sorted(d.glob("track1_audit_*.jsonl")) if d.is_dir() else []:
        m = re.fullmatch(r"track1_audit_(\d{8})\.jsonl", f.name)
        if m:
            days.append(f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}")
    return days


def _paper_start(root: Path) -> "dict | None":
    """The FIRST passing paper-account baseline: the account this route was funded to."""
    import json
    d = root / "global_index" / "track1_runtime" / "account_baseline"
    for f in sorted(d.glob("account_baseline_*.jsonl")) if d.is_dir() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            acc = (r.get("inputs") or {}).get("account") or {}
            if r.get("status") == "PASS" and isinstance(acc.get("equity"), (int, float)):
                return {"date": str(r.get("checked_at") or "")[:10], "equity": acc["equity"],
                        "currency": acc.get("currency"), "checked_at": r.get("checked_at"),
                        "record": f"global_index/track1_runtime/account_baseline/{f.name}"}
    return None


def build(root: "str | Path", *, ibkr_cache: dict,
          now: "dt.datetime | None" = None,
          b1_latest: "Callable[[Path], Any] | None" = None) -> dict:
    """`{"payload", "payload_sources", "payload_absent"}` — Track 1 sources only."""
    from global_index import track1_params as P

    root = Path(root)
    now = now or dt.datetime.now(dt.timezone.utc)
    meta: dict = {}
    health: dict = {}
    src: dict = {}

    meta["account"] = float(P.ACCOUNT)
    src["meta.account"] = {"source": "global_index/track1_params.py ACCOUNT", "as_of": None}

    meta["clusters"] = {s: {"max_gross_pct": g, "max_net_pct": n}
                        for s, (g, n) in sorted(P.CAPS.items())}
    src["meta.clusters"] = {"source": "global_index/track1_params.py CAPS", "as_of": None}

    days = _audit_days(root)
    meta["total_days"] = len(days)
    src["meta.total_days"] = {
        "source": "global_index/track1_runtime/audits — one post-window audit file per day",
        "as_of": days[-1] if days else None,
        "reading": "days the route was audited, not days it traded"}

    start = _paper_start(root)
    if start is not None:
        meta["paper_start"] = start
        src["meta.paper_start"] = {"source": start["record"] + " (first PASS baseline)",
                                   "as_of": start["checked_at"]}

    try:
        if b1_latest is None:
            from global_index import track1_b1 as _b1m
            b1_latest = _b1m.latest
        r = b1_latest(root)
        broker = (getattr(r, "inputs", None) or {}).get("broker") or {}
        eq = broker.get("equity")
        if isinstance(eq, (int, float)) and eq == eq:
            meta["broker_equity"] = float(eq)
            src["meta.broker_equity"] = {
                "source": "global_index/track1_b1 — the newest B1 broker measurement",
                "as_of": getattr(r, "checked_at", None), "status": getattr(r, "status", None)}
    except Exception as exc:                                   # noqa: BLE001
        src["meta.broker_equity"] = {"source": None, "error": f"{type(exc).__name__}: {exc}"}

    conn = ibkr_connection(ibkr_cache or {}, now)
    health["ibkr_connected"] = conn["state"]
    src["runner_health.ibkr_connected"] = {
        "source": "monitor backend IBKR reader cache (read-only connection, polls every 10 s)",
        "as_of": conn["as_of"], "age_seconds": conn["age_seconds"]}

    beat = last_heartbeat(root)
    if beat["at"] is not None:
        health["last_heartbeat"] = beat["at"]
        src["runner_health.last_heartbeat"] = {
            "source": f"{SCHEDULER_LOG} — newest 'Heartbeat 60s … executed successfully' line",
            "as_of": beat["at"]}

    # Plan stage 3: the per-day series, built from Track 1 evidence, refusing days it cannot
    # prove rather than zero-filling them. Its shape is Track 1's own — see track1_series_reader.
    from monitor.backend.track1_series_reader import build_series
    try:
        series = build_series(root)
    except Exception as exc:                                   # noqa: BLE001
        series = {"days": [], "status": "reader_failed", "reading": f"{type(exc).__name__}: {exc}"}
    payload = {"meta": meta, "runner_health": health, "snapshots": series["days"]}
    src["snapshots"] = {
        "source": ("monitor/backend/track1_series_reader.py over global_index/track1_runtime "
                   "audits + window_coverage + regime_label + trade_log.track1.jsonl"),
        "as_of": series.get("epoch"), "status": series.get("status"),
        "reading": series.get("reading"), "pnl_basis": series.get("pnl_basis"),
        "refused_days": [d["date"] for d in series["days"] if d["status"] == "refused"]}
    # A field with a declared absence must not also be present, and the reverse; the absent
    # table is a promise about the payload, and this keeps the promise checkable at build time.
    absent = dict(ABSENT)
    for k in list(absent):
        top, _, leaf = k.partition(".")
        if leaf and leaf in (payload.get(top) or {}):
            absent.pop(k)
    if "meta.broker_equity" not in {f"meta.{k}" for k in meta}:
        absent["meta.broker_equity"] = src.get("meta.broker_equity", {}).get(
            "error", "no B1 measurement carries a broker equity")
    if "paper_start" not in meta:
        absent["meta.paper_start"] = "no PASS account baseline on disk"
    if "last_heartbeat" not in health:
        absent["runner_health.last_heartbeat"] = beat["error"]
    return {"payload": payload, "payload_era": "track1", "payload_sources": src,
            "payload_absent": absent, "built_at": _iso(now)}
