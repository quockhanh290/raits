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
import logging

from flask import Flask, jsonify

from monitor.backend import ibkr_reader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.after_request
def _cors(response):
    # Allow dashboard served from file:// or any localhost origin
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


# ── API endpoints ─────────────────────────────────────────────────────────────

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
