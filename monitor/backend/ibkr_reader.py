"""
monitor/backend/ibkr_reader.py
================================
Background thread: connects to IBKR Gateway (paper 4002), polls every 10s,
caches account/positions/orders.  Flask reads only from the cache.

SAFETY: READ-ONLY queries only — no order placement, no state file writes.
Uses client_id 99 (separate from runner's client_id 1) to avoid session conflict.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_cache: dict[str, Any] = {
    "connected": False,
    "error": None,
    "last_update": None,
    "account": {"equity": None, "unrealized_pnl": None},
    "positions": [],
    "orders": [],
}
_cache_lock = threading.Lock()


def get_cache() -> dict[str, Any]:
    with _cache_lock:
        import copy
        return copy.deepcopy(_cache)


def _set(data: dict[str, Any]) -> None:
    with _cache_lock:
        _cache.update(data)


def _reader_thread(port: int, client_id: int, poll_interval: int) -> None:
    # Windows Python 3.10+ needs explicit event loop in non-main threads
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    except Exception:
        pass

    import ib_insync as ibi

    ib = ibi.IB()

    while True:
        try:
            if not ib.isConnected():
                logger.info(f"Connecting to IBKR 127.0.0.1:{port} clientId={client_id} ...")
                ib.connect("127.0.0.1", port, clientId=client_id, timeout=10)
                ib.sleep(2.0)  # wait for subscriptions to populate
                logger.info("IBKR connected OK")

            # ── Account values ───────────────────────────────────────────
            # Collect all NetLiquidation/UnrealizedPnL by currency; prefer
            # "BASE" (consolidated total) then "USD", then any (e.g. "CAD").
            nl: dict[str, float] = {}
            upnl: dict[str, float] = {}
            try:
                for v in ib.accountValues():
                    try:
                        if v.tag == "NetLiquidation":
                            nl[v.currency] = float(v.value)
                        elif v.tag in ("UnrealizedPnL", "UnrealizedPnl"):
                            upnl[v.currency] = float(v.value)
                    except (TypeError, ValueError):
                        pass
            except Exception as e:
                logger.warning(f"accountValues error: {e}")
            equity = nl.get("BASE") or nl.get("USD") or next(iter(nl.values()), None)
            unrealized_pnl = upnl.get("BASE") or upnl.get("USD") or next(iter(upnl.values()), None)
            if nl:
                chosen_ccy = "BASE" if "BASE" in nl else ("USD" if "USD" in nl else next(iter(nl)))
                logger.debug(f"NetLiquidation currencies: {list(nl.keys())} → using {chosen_ccy}={equity}")

            # ── Portfolio (per-position unrealized PNL, entry price proxy) ─
            positions: list[dict] = []
            try:
                for item in ib.portfolio():
                    c = item.contract
                    sym = (c.localSymbol or c.symbol) if c else "?"
                    positions.append({
                        "inst":          sym,
                        "sec_type":      c.secType if c else "?",
                        "position":      item.position,
                        "market_price":  _safe_float(item.marketPrice),
                        "market_value":  _safe_float(item.marketValue),
                        "avg_cost":      _safe_float(item.averageCost),  # entry proxy
                        "unrealized_pnl": _safe_float(item.unrealizedPNL),
                        "realized_pnl":  _safe_float(item.realizedPNL),
                    })
            except Exception as e:
                logger.warning(f"portfolio error: {e}")

            # ── Open trades (STP GTC, pending) ───────────────────────────
            # reqAllOpenOrders fetches orders from ALL clients (clientId 0 = TWS UI,
            # clientId 1 = runner). Without this, openTrades() returns only clientId 99's own.
            orders: list[dict] = []
            try:
                ib.reqAllOpenOrders()
                ib.sleep(1.0)  # allow order events to populate cache
                for t in ib.openTrades():
                    c = t.contract
                    o = t.order
                    s = t.orderStatus
                    sym = (c.localSymbol or c.symbol) if c else "?"
                    orders.append({
                        "inst":       sym,
                        "type":       o.orderType if o else "?",
                        "action":     o.action if o else "?",
                        "qty":        float(o.totalQuantity) if (o and o.totalQuantity) else None,
                        "lmt_price":  _safe_float(o.lmtPrice)  if o else None,
                        "aux_price":  _safe_float(o.auxPrice)   if o else None,
                        "order_id":   o.orderId if o else None,
                        "status":     s.status if s else "?",
                        "tif":        o.tif if o else None,
                    })
            except Exception as e:
                logger.warning(f"openTrades error: {e}")

            _set({
                "connected": True,
                "error": None,
                "last_update": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "account": {"equity": equity, "unrealized_pnl": unrealized_pnl},
                "positions": positions,
                "orders": orders,
            })

            ib.sleep(float(poll_interval))  # run event loop to receive updates

        except Exception as e:
            msg = str(e)
            logger.warning(f"IBKR reader error: {msg}")
            _set({"connected": False, "error": msg})
            try:
                ib.disconnect()
            except Exception:
                pass
            ib = ibi.IB()
            time.sleep(5)  # back-off before reconnect attempt


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        # IBKR returns 1.7976931348623157e+308 for "no value"
        return None if abs(f) > 1e30 else f
    except (TypeError, ValueError):
        return None


def start(port: int = 4002, client_id: int = 99, poll_interval: int = 10) -> None:
    """Start the background reader thread (daemon — dies with main process)."""
    t = threading.Thread(
        target=_reader_thread,
        args=(port, client_id, poll_interval),
        daemon=True,
        name="ibkr-reader",
    )
    t.start()
    logger.info(f"IBKR reader started: port={port} client_id={client_id} poll={poll_interval}s")
