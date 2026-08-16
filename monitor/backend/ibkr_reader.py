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
import datetime as dt
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
    "contract_specs": {},
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

            contract_specs = get_cache().get("contract_specs") or {}
            if not contract_specs:
                contract_specs = _read_contract_specs(ib, ibi)

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

            # Total unrealized = sum of the rows the panel actually renders.
            #
            # Not the account tag. IBKR reports it as "$LEDGER-UnrealizedPnL", which the
            # tag match above never hit (it looks for "UnrealizedPnL"), so the dashboard
            # showed a dash. Matching the real tag would still be wrong here: on this
            # CAD-based account $LEDGER-UnrealizedPnL/BASE is CAD 1,016.48 while the
            # position rows are USD and sum to 722.72, so the total would not equal the
            # column beneath it. Summing the rows cannot disagree with them.
            if positions:
                _u = [p["unrealized_pnl"] for p in positions if p["unrealized_pnl"] is not None]
                unrealized_pnl = round(sum(_u), 2) if _u else None

            # ── Open trades (STP GTC, pending) ───────────────────────────
            # reqAllOpenOrders fetches orders from ALL clients (clientId 0 = TWS UI,
            # clientId 1 = runner). Without this, openTrades() returns only clientId 99's own.
            #
            # Use what it RETURNS, not ib.openTrades(). openTrades() reads wrapper.trades,
            # a cache that accumulates and never evicts. IBKR pushes status updates only to
            # the client that OWNS an order, so a cross-client order that fills is never
            # marked done and stays there forever — this reader is a long-lived process, so
            # the ghost never clears. Live 2026-08-06: M2K stop #14 filled at 08:11 and this
            # panel still showed it PreSubmitted at 08:27. A naked position would render as
            # protected, which is the one thing this panel must never do.
            orders: list[dict] = []
            try:
                for t in ib.reqAllOpenOrders():
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
                "last_update": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                "account": {"equity": equity, "unrealized_pnl": unrealized_pnl},
                "positions": positions,
                "orders": orders,
                "contract_specs": contract_specs,
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


def _read_contract_specs(ib: Any, ibi: Any) -> dict[str, dict[str, Any]]:
    """Read exchange contract metadata from IBKR without touching orders/state.

    Covers BASKET and SPECS, not BASKET alone. Asking only about the four Rổ-4 futures
    is what let the MNKD routing defect run undetected: MNKD lives in SPECS, so the
    guard never requested its ContractDetails and never noticed that orders were being
    filled on a contract with ten times the multiplier local specs declare. A guard that
    skips an instrument cannot report it as unreconciled — it reports nothing at all.
    """
    try:
        from futures.basket import BASKET
        from global_index.ibkr_broker import ibkr_symbol_and_exchange, _current_front_month
    except Exception as exc:
        return {"_error": {"error": f"local spec import failed: {exc}"}}
    try:
        from global_index.specs import SPECS
    except Exception:
        SPECS = {}

    specs: dict[str, dict[str, Any]] = {}
    for inst in {**BASKET, **SPECS}:
        try:
            # One routing rule, asked once. This used to resolve the symbol here and
            # then ask _IBKR_EXCHANGE with the UNtranslated name, which returns the
            # default — right only while the single translated instrument (MNKD -> MNK)
            # happens to be on CME.
            symbol, exchange = ibkr_symbol_and_exchange(inst)
            # The `or _current_front_month(inst)` fallback that used to sit here was a
            # workaround for that lookup not translating either; it does now.
            month = _current_front_month(symbol)
            contract = ibi.Future(symbol, lastTradeDateOrContractMonth=month, exchange=exchange, currency="USD")
            details = ib.reqContractDetails(contract)
            if not details:
                specs[inst] = {"status": "MISSING", "error": "IBKR returned no contract details"}
                continue
            detail = details[0]
            c = detail.contract
            point_value = _safe_float(getattr(c, "multiplier", None))
            tick = _safe_float(getattr(detail, "minTick", None))
            specs[inst] = {
                "status": "OBSERVED",
                "symbol": getattr(c, "symbol", symbol),
                "local_symbol": getattr(c, "localSymbol", None),
                "exchange": getattr(c, "exchange", exchange),
                "con_id": getattr(c, "conId", None),
                "contract_month": getattr(c, "lastTradeDateOrContractMonth", month),
                "point_value": point_value,
                "tick": tick,
                "tick_value": round(point_value * tick, 6) if point_value is not None and tick is not None else None,
                "source": "IBKR reqContractDetails",
            }
        except Exception as exc:
            specs[inst] = {"status": "ERROR", "error": str(exc)}
    return specs


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
