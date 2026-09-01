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
from monitor.backend.schedule_status import get_schedule_status, resolve_track1_only
from monitor.backend.session_event_reader import read_session_events
from monitor.backend.job_journal_reader import read_job_journal
from monitor.backend.open_issue_reader import read_open_issues
from monitor.backend.paper_evidence_reader import read_paper_evidence
from monitor.backend.execution_quality_reader import read_execution_quality

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════════════════
# Stage 5ZZX — console hygiene, IN THIS PROCESS ONLY
#
# Measured on the retained backend log before changing anything, 358,361 lines:
#
#     GET ... 200          337,972   94.3%   dashboard polling
#     GET ... 3xx            8,860
#     other                  8,036
#     WARNING / ERROR        2,806
#     "Adding job tentatively"  685           six distinct days, in bursts
#     "slots registered"           2
#
# So the flood is the access log, and it is not evidence of anything: a page polling every
# eight seconds writes ten thousand successful GETs a day whether the system is healthy or on
# fire. The APScheduler lines are not a flood at all — they arrive in bursts, and the burst
# dated today at 07:17:13 lands four minutes BEFORE this process logged "Starting Flask" at
# 07:21:12. They are `ops.py` constructing a scheduler object to enumerate it, with its console
# output going to the same file, not this backend serving a request.
#
# What is kept is everything that could ever be the first sign of a problem: startup lines,
# every WARNING and ERROR, tracebacks, and any request that did not succeed.
# ══════════════════════════════════════════════════════════════════════════════════════════

class _QuietSuccessfulRequests(logging.Filter):
    """Drop access-log lines for requests that succeeded; keep everything else.

    The status code is parsed out of the formatted message rather than read from a field,
    because that is all Werkzeug's access logger provides. Anything that does not parse is
    KEPT — an unrecognised line is not a line to throw away, and a filter that swallowed what
    it could not read would hide exactly the malformed cases worth seeing.
    """

    _OK = ("200", "204", "301", "302", "304")

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        message = record.getMessage()
        if '" ' not in message:
            return True
        status = message.rsplit('" ', 1)[-1].strip().split(" ")[0]
        return status not in self._OK


class _NoTentativeJobAdds(logging.Filter):
    """Drop APScheduler's per-job INFO chatter from building a scheduler for inspection.

    The mirror deliberately builds a real scheduler object and enumerates it rather than
    keeping a hand-written slot list — the comment on `scheduler_slot_ids` records why, and a
    second list is how the two drift apart. Nothing is started: `sched.start()` appears exactly
    once in the tree, in the scheduler's own main. So these lines describe an object being
    inspected, and a reader cannot tell them from a scheduler doing work.

    WARNING and above still pass, which is the half that matters: a job that cannot be added at
    all is not an INFO line.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        return "Adding job tentatively" not in record.getMessage()


def _quiet_backend_console() -> None:
    """Applied to THIS process. The scheduler's own log is untouched — it is a different
    process with its own handlers, and its INFO lines are the record of work actually done."""
    logging.getLogger("werkzeug").addFilter(_QuietSuccessfulRequests())
    logging.getLogger("apscheduler").addFilter(_NoTentativeJobAdds())
    # `apscheduler.scheduler` is where the line is emitted; a filter on the parent is not
    # consulted for a record made by a child logger, so it is attached at both levels.
    logging.getLogger("apscheduler.scheduler").addFilter(_NoTentativeJobAdds())


_quiet_backend_console()

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


@app.get("/realtime-next")
def dashboard_realtime_next():
    # Bản nháp thiết kế lại của /realtime. Tồn tại để sửa giao diện mà không đụng
    # vào route đang dùng thật. Nó nạp CHUNG realtime.css và realtime.js, chỉ thêm
    # một lớp CSS đè riêng — nên không có bản sao nào của nền để trôi khỏi bản gốc.
    return send_from_directory(DASH_ROOT / "realtime-next", "index.html")


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


@app.get("/favicon.ico")
def favicon():
    # Trình duyệt luôn xin favicon. Một 404 thường trực trong console làm lu mờ
    # lỗi thật, và console sạch là điều kiện để smoke test nói được điều gì.
    return "", 204


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
        "contract_specs":  c.get("contract_specs", {}),
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
            # Whether each list is an ANSWER or an artefact of a swallowed exception. The
            # collector builds both inside try/except blocks that leave the list empty, so
            # without these an empty list means either "holds nothing" or "the call raised".
            # B1 reads these and treats a missing flag as UNKNOWN, never as flat.
            "positions_ok": c.get("positions_ok", False),
            "positions_error": c.get("positions_error"),
            "orders": c["orders"],
            "orders_ok": c.get("orders_ok", False),
            "orders_error": c.get("orders_error"),
            "contract_specs": c.get("contract_specs", {}),
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
    # Stage 5ZZW. The live dashboard asks the SCHEDULER which mode it is in, rather than
    # inferring it from how this backend process happened to be started. A backend launched by
    # hand, or one that outlived a mode change, used to answer `legacy` for a machine running
    # track1-only — and then reported a legacy snapshot's staleness as the route's health.
    schedule = get_schedule_status(ROOT, observed_at=observed,
                                   track1_only=resolve_track1_only())
    state["freshness"] = schedule["freshness"]
    state["expected_next_at"] = schedule["expected_next_at"]
    return jsonify(state)


@app.get("/api/v1/track1-market-view")
def api_v1_track1_market_view():
    # Stage 5ZZL. Its OWN endpoint rather than a block on /track1-runtime: this one slices
    # instrument stores, and the runtime endpoint is polled on a short interval by a page
    # that needs it to stay cheap. Read-only, offline, and it never opens a connection --
    # bars come from the persisted store, never from the broker.
    #
    # Stage 5ZZZ-BQ. `build` has always taken a day; this endpoint pinned it to today, so the
    # panel could only ever describe the session in progress. A rejected `day` is answered
    # with today rather than an error: this endpoint feeds a page that must keep rendering.
    import re

    from flask import request

    from monitor.backend.track1_market_view import available_sessions, build, regime

    asked = (request.args.get("day") or "").strip()
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", asked):
        asked = ""
    payload = build(ROOT, day=asked or None)
    return jsonify({"market_view": payload, "regime": regime(ROOT),
                    "sessions": available_sessions(ROOT, today=payload.get("today_et")),
                    "requested_day": asked or None})


@app.get("/api/v1/runner-positions")
def api_v1_runner_positions():
    # Stage 5P: labelled at the SOURCE. This is the LEGACY route's book — during a Track 1
    # shadow period it is the draining legacy state, and a panel that presented it as "the
    # system's positions" would be presenting the wrong route. Track 1's own state is served
    # by /api/v1/track1-runtime, which reads only Track 1 paths.
    payload = read_runner_positions(RUNNER_POSITIONS_PATH)
    payload["route"] = "legacy"
    payload["route_note"] = ("legacy book (draining during Track 1 shadow); Track 1 state "
                             "is at /api/v1/track1-runtime")
    return jsonify(payload)


@app.get("/api/v1/track1-runtime")
def api_v1_track1_runtime():
    # Additive, read-only, Track 1 paths only — see track1_runtime_reader's module docstring.
    from monitor.backend.track1_runtime_reader import read_track1_runtime
    return jsonify(read_track1_runtime(ROOT))


@app.get("/api/v1/schedule-status")
def api_v1_schedule_status():
    state = read_runner_state(LIVE_STATE_PATH)
    observed = _parse_iso(state.get("observed_at"))
    return jsonify(get_schedule_status(ROOT, observed_at=observed,
                                       track1_only=resolve_track1_only()))


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

def _warm_paper_evidence() -> None:
    """Build the paper-evidence cache off the request path, in the background.

    The first request after a restart scans every scheduler/live-day log to rebuild this
    cache. Measured cold: 30.5s on 2026-08-14, 41.7s later that day, 59.4s on 2026-08-15
    -- it grows with the logs. Warm requests return in ~0.03s. So the cost fell on
    whoever loaded the page first, and past ~30s they were told "Paper evidence
    unavailable" by a backend that was working fine.

    Two details this got wrong on the first attempt, both measured:

    - Warming inline held the listening port shut for 40.5s. A monitor that cannot be
      reached is worse than one that answers slowly, so it runs on a thread now.
    - Warming immediately achieved nothing: ibkr_reader.start() returns before its first
      poll lands, and contract_specs is part of the cache key (_signature). Warming
      against an empty specs dict built an entry under a key no request would ever ask
      for -- the first real request still paid 84s. So wait for the specs first.

    Never fatal, and never blocking: on any failure the next request simply pays the
    scan it would have paid anyway.
    """
    import threading
    import time

    def _run() -> None:
        from monitor.backend.paper_evidence_reader import read_paper_evidence

        # Bounded wait. If IBKR never connects the specs stay empty, which is itself a
        # stable key -- warm that one rather than never warming at all.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                if ibkr_reader.get_cache().get("contract_specs"):
                    break
            except Exception:
                pass
            time.sleep(2)
        started = time.monotonic()
        try:
            read_paper_evidence(ROOT)
        except Exception as exc:
            logger.warning("paper-evidence warm-up failed (%s) — the next request pays the scan", exc)
            return
        logger.info("paper-evidence cache warm in %.1fs", time.monotonic() - started)

    threading.Thread(target=_run, name="paper-evidence-warm", daemon=True).start()


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

    _warm_paper_evidence()

    logger.info(f"Starting Flask on http://127.0.0.1:{a.api_port}")
    logger.info("Endpoints: /api/all  /api/account  /api/positions  /api/orders  /api/connection")
    app.run(host="127.0.0.1", port=a.api_port, debug=a.debug, use_reloader=False)


if __name__ == "__main__":
    main()
