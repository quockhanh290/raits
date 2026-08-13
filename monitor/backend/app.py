"""
monitor/backend/app.py
========================
Flask read-only IBKR monitor backend.

Endpoints:
  GET /api/connection  → {connected, last_update, error}
  GET /api/account     → {connected, equity, unrealized_pnl, last_update}
  GET /api/positions   → {connected, positions: [...]}
  GET /api/orders      → {connected, orders: [...]}

SAFETY: No order placement.  No runner import.  client_id=99 (runner=1).

Start:
  cd d:\\raits
  python monitor/start_backend.py [--port 4002] [--api-port 5001]

Dependencies (if missing):
  pip install flask
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, send_from_directory

from monitor.backend import ibkr_reader
from monitor.backend.entry_time_reader import annotate_open_positions, read_entry_times
from monitor.backend.report_reader import read_report
from monitor.backend.runner_state_reader import read_runner_state
from monitor.backend.runner_event_reader import read_runner_events
from monitor.backend.runner_positions_reader import read_runner_positions
from monitor.backend.schedule_status import get_schedule_status
from monitor.backend.session_event_reader import read_session_events
from monitor.backend.job_journal_reader import read_job_journal
from monitor.backend.open_issue_reader import read_open_issues
from monitor.backend.paper_evidence_reader import read_paper_evidence
from monitor.backend.execution_quality_reader import read_execution_quality

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
ROOT = Path(__file__).resolve().parents[2]
DASH_ROOT = ROOT / "global_index" / "dash"
LIVE_STATE_PATH = ROOT / "global_index" / "live_state_data.js"
RUNNER_POSITIONS_PATH = ROOT / "live_positions.json"


@app.after_request
def _cors(response):
    # Allow dashboard served from file:// or any localhost origin
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/")
def dashboard_home():
    return send_from_directory(DASH_ROOT, "index.html")


@app.get("/realtime")
def dashboard_realtime():
    return send_from_directory(DASH_ROOT / "realtime", "index.html")


@app.get("/analytics")
def dashboard_analytics():
    return send_from_directory(DASH_ROOT / "analytics", "index.html")


@app.get("/paper")
def dashboard_paper():
    return send_from_directory(DASH_ROOT / "paper", "index.html")


@app.get("/reports")
def dashboard_reports():
    return send_from_directory(DASH_ROOT / "reports", "index.html")


@app.get("/dash/<path:filename>")
def dashboard_asset(filename: str):
    return send_from_directory(DASH_ROOT, filename)


@app.get("/live_state_data.js")
def legacy_live_state_asset():
    return send_from_directory(LIVE_STATE_PATH.parent, LIVE_STATE_PATH.name)


@app.get("/replay_snapshots_data.js")
def replay_snapshots_asset():
    return send_from_directory(ROOT / "global_index", "replay_snapshots_data.js")


@app.get("/dashboard")
def legacy_dashboard_redirect():
    return redirect("/realtime", code=302)


@app.get("/api/connection")
def api_connection():
    c = ibkr_reader.get_cache()
    return jsonify({
        "connected":   c["connected"],
        "last_update": c["last_update"],
        "error":       c.get("error"),
    })


@app.get("/api/account")
def api_account():
    c = ibkr_reader.get_cache()
    return jsonify({
        "connected":      c["connected"],
        "last_update":    c["last_update"],
        "equity":         c["account"]["equity"],
        "unrealized_pnl": c["account"]["unrealized_pnl"],
    })


@app.get("/api/positions")
def api_positions():
    c = ibkr_reader.get_cache()
    return jsonify({
        "connected": c["connected"],
        "positions": c["positions"],
    })


@app.get("/api/orders")
def api_orders():
    c = ibkr_reader.get_cache()
    return jsonify({
        "connected": c["connected"],
        "orders":    c["orders"],
    })


@app.get("/api/all")
def api_all():
    """Combined endpoint — one round-trip for the dashboard."""
    c = ibkr_reader.get_cache()
    return jsonify({
        "connected":      c["connected"],
        "last_update":    c["last_update"],
        "error":          c.get("error"),
        "equity":         c["account"]["equity"],
        "unrealized_pnl": c["account"]["unrealized_pnl"],
        "positions":      c["positions"],
        "orders":         c["orders"],
    })


@app.get("/api/v1/broker")
def api_v1_broker():
    c = ibkr_reader.get_cache()
    server_now = dt.datetime.now(dt.timezone.utc)
    observed = _parse_iso(c["last_update"])
    age_seconds = max(0, round((server_now - observed).total_seconds(), 3)) if observed else None
    fresh = bool(c["connected"] and age_seconds is not None and age_seconds <= 30)
    return jsonify({
        "source": "ibkr",
        "observed_at": c["last_update"],
        "server_now": server_now.isoformat().replace("+00:00", "Z"),
        "age_seconds": age_seconds,
        "freshness": "fresh" if fresh else "unknown",
        "connected": c["connected"],
        "error": c.get("error"),
        "payload": {
            "equity": c["account"]["equity"],
            "unrealized_pnl": c["account"]["unrealized_pnl"],
            "positions": c["positions"],
            "orders": c["orders"],
        },
    })


@app.get("/api/v1/runner-state")
def api_v1_runner_state():
    state = read_runner_state(LIVE_STATE_PATH)
    snapshots = (state.get("payload") or {}).get("snapshots", [])
    days = [str(snapshot.get("date")) for snapshot in snapshots if snapshot.get("date")]
    state["event_history"] = read_runner_events(max(days), ROOT) if days else None
    # The runner emits entry_time as a hardcoded None, so recover it from its own trade
    # log rather than leaving the panel captioned "not emitted" forever. read_runner_state
    # hands back a deepcopy, so annotating in place cannot leak into its cache.
    entry_times = read_entry_times(ROOT)
    state["entry_times"] = {"source": entry_times["source"],
                            "observed_at": entry_times["observed_at"],
                            "error": entry_times["error"],
                            "filled": annotate_open_positions(state.get("payload"),
                                                              entry_times["entries"])}
    observed = _parse_iso(state.get("observed_at"))
    schedule = get_schedule_status(ROOT, observed_at=observed)
    state["freshness"] = schedule["freshness"]
    state["expected_next_at"] = schedule["expected_next_at"]
    return jsonify(state)


@app.get("/api/v1/runner-positions")
def api_v1_runner_positions():
    return jsonify(read_runner_positions(RUNNER_POSITIONS_PATH))


@app.get("/api/v1/schedule-status")
def api_v1_schedule_status():
    state = read_runner_state(LIVE_STATE_PATH)
    observed = _parse_iso(state.get("observed_at"))
    return jsonify(get_schedule_status(ROOT, observed_at=observed))


@app.get("/api/v1/session-events/<day>")
def api_v1_session_events(day: str):
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        abort(400, description="date must use YYYY-MM-DD")
    return jsonify(read_session_events(day, ROOT))


@app.get("/api/v1/job-journal/<day>")
def api_v1_job_journal(day: str):
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        abort(400, description="date must use YYYY-MM-DD")
    return jsonify(read_job_journal(day, ROOT))


@app.get("/api/v1/open-issues")
def api_v1_open_issues():
    return jsonify(read_open_issues(ROOT))


@app.get("/api/v1/paper-evidence")
def api_v1_paper_evidence():
    return jsonify(read_paper_evidence(ROOT))


@app.get("/api/v1/execution-quality/<day>")
def api_v1_execution_quality(day: str):
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        abort(400, description="date must use YYYY-MM-DD")
    return jsonify(read_execution_quality(ROOT, day))


@app.get("/api/v1/execution-quality")
def api_v1_execution_quality_all():
    return jsonify(read_execution_quality(ROOT))


@app.get("/api/v1/reports/<day>")
def api_v1_report(day: str):
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        abort(400, description="date must use YYYY-MM-DD")
    return jsonify(read_report(day, ROOT))


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="RAITS IBKR monitor backend")
    ap.add_argument("--ibkr-port", type=int, default=4002,  help="IBKR Gateway port (paper=4002)")
    ap.add_argument("--client-id", type=int, default=99,    help="IB client ID (runner uses 1)")
    ap.add_argument("--api-port",  type=int, default=5001,  help="Flask listen port")
    ap.add_argument("--poll",      type=int, default=10,    help="IBKR poll interval (seconds)")
    ap.add_argument("--debug",     action="store_true")
    a = ap.parse_args()

    logger.info(f"Starting IBKR reader: Gateway port={a.ibkr_port}, client_id={a.client_id}")
    ibkr_reader.start(port=a.ibkr_port, client_id=a.client_id, poll_interval=a.poll)

    logger.info(f"Starting Flask on http://127.0.0.1:{a.api_port}")
    logger.info("Endpoints: /api/all  /api/account  /api/positions  /api/orders  /api/connection")
    app.run(host="127.0.0.1", port=a.api_port, debug=a.debug, use_reloader=False)


if __name__ == "__main__":
    main()
