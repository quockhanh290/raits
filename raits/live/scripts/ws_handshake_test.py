"""
ws_handshake_test.py  —  Step 1: Off-hours Polygon/Massive WebSocket handshake test.

Tests connection / auth / subscribe without needing live bar data.
Runnable any time of day.

Usage
-----
    POLYGON_API_KEY=xxx python raits/live/scripts/ws_handshake_test.py [--feed delayed.massive.com]

Exit 0 = all checks passed.
Exit 1 = any check failed or timed out.

Feed → plan mapping (massive.com):
  delayed.massive.com  →  Developer / Starter  (15-min delayed)
  socket.massive.com   →  Advanced / Business  (real-time)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading

_DEFAULT_FEED = "delayed.massive.com"
_TIMEOUT = 15.0


# ── Method A: raw websockets (shows exact server messages) ────────────────────

async def _run_raw(api_key: str, feed: str) -> list[tuple[str, bool]]:
    ws_url = f"wss://{feed}/stocks"
    checks: list[tuple[str, bool]] = [
        ("WS connection open",  False),
        ("connected status",    False),
        ("auth_success",        False),
        ("AM.SPY subscribed",   False),
        ("clean disconnect",    False),
    ]

    try:
        import websockets
    except ImportError:
        print("  ERROR: websockets not installed — pip install websockets")
        return checks

    async def _wait_status(ws, expected: str) -> bool:
        deadline = asyncio.get_event_loop().time() + _TIMEOUT
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                print(f"  TIMEOUT waiting for {expected!r}")
                return False
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                print(f"  TIMEOUT waiting for {expected!r}")
                return False
            try:
                msgs = json.loads(raw)
            except json.JSONDecodeError:
                print(f"  [raw] {raw[:200]}")
                continue
            if not isinstance(msgs, list):
                msgs = [msgs]
            for m in msgs:
                ev, status, msg = m.get("ev"), m.get("status"), m.get("message", "")
                print(f"  [msg] ev={ev!r} status={status!r} message={msg!r}")
                if ev == "status" and status == expected:
                    return True
                if ev == "status" and status in ("auth_failed", "not_authed", "error"):
                    return False

    try:
        async with websockets.connect(ws_url, ssl=True) as ws:
            checks[0] = ("WS connection open", True)
            if not await _wait_status(ws, "connected"):
                return checks
            checks[1] = ("connected status", True)

            await ws.send(json.dumps({"action": "auth", "params": api_key}))
            if not await _wait_status(ws, "auth_success"):
                return checks
            checks[2] = ("auth_success", True)

            await ws.send(json.dumps({"action": "subscribe", "params": "AM.SPY"}))
            if not await _wait_status(ws, "success"):
                return checks
            checks[3] = ("AM.SPY subscribed", True)

        checks[4] = ("clean disconnect", True)
    except OSError as exc:
        print(f"  Network error: {exc}")
    except Exception as exc:
        print(f"  Unexpected error: {exc}")

    return checks


# ── Method B: polygon-api-client (handles auth internally) ───────────────────

def _run_polygon_client(api_key: str, feed: str, timeout: float = 12.0) -> bool:
    """Connect via polygon WebSocketClient; return True if a bar or sub ACK arrives."""
    try:
        from polygon.websocket import WebSocketClient
        from polygon.websocket.models import Market
    except ImportError:
        print("  polygon-api-client not installed")
        return False

    got_message = threading.Event()
    error: list[str] = []

    def _handle(_msgs) -> None:
        got_message.set()

    client = WebSocketClient(
        api_key=api_key,
        feed=feed,
        market=Market.Stocks,
        subscriptions=["AM.SPY"],
    )

    def _run_thread():
        try:
            client.run(_handle)
        except Exception as exc:
            error.append(str(exc))
            got_message.set()

    t = threading.Thread(target=_run_thread, daemon=True)
    t.start()
    got_message.wait(timeout=timeout)

    try:
        client.close()
    except Exception:
        pass

    if error:
        print(f"  polygon client error: {error[0]}")
        return False
    if got_message.is_set() and not error:
        return True
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feed", default=_DEFAULT_FEED,
                        help=f"WebSocket feed domain (default: {_DEFAULT_FEED})")
    args = parser.parse_args()

    api_key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not api_key:
        print("ERROR: POLYGON_API_KEY not set.", file=sys.stderr)
        return 1

    print("Polygon/Massive WebSocket handshake test")
    print(f"  Feed   : {args.feed}")
    print(f"  Timeout: {_TIMEOUT}s per step")
    print()

    # Method A — raw websockets with debug output
    print("── Method A: raw websockets ──────────────────")
    checks = asyncio.run(_run_raw(api_key, args.feed))
    a_pass = all(p for _, p in checks)
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    print()

    # Method B — polygon client (only if Method A failed at auth)
    if not checks[2][1]:
        print("── Method B: polygon-api-client ──────────────")
        b_pass = _run_polygon_client(api_key, args.feed)
        print(f"  [{'PASS' if b_pass else 'FAIL'}] polygon client subscription received")
        print()
    else:
        b_pass = True

    overall = a_pass or b_pass
    print("RESULT:", "PASS" if overall else "FAIL")

    if not checks[2][1] and not b_pass:
        print()
        print("Auth failed on both methods. Possible causes:")
        print("  1. API key is invalid or expired — check massive.com dashboard")
        print("  2. Key is a Polygon.io key; try regenerating at massive.com")
        print(f"  3. Plan does not include WebSocket on feed={args.feed!r}")
        print(f"     Try: python ws_handshake_test.py --feed socket.massive.com")

    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
