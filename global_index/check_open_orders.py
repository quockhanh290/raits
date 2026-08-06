"""global_index/check_open_orders.py — verify every open position has a working stop.

This is the acceptance check for STP placement. It asks IBKR, not live_positions.json.

The criterion it replaces was `stop_price + stop_order_id != null`, which could never
fail: place_stop returned an order id that ib_insync had allocated client-side
(`ib.py:654`), so the field was always populated. On 2026-08-05 that criterion passed
while three positions sat overnight with no stop at IBKR at all.

Read-only. Places nothing, cancels nothing. Uses its own clientId so it cannot disturb
the runner (1), the dashboard reader (99), or TWS itself (0).

    python -X utf8 global_index/check_open_orders.py [--port 4002] [--client-id 88]

Exit code 0 = every position protected, 1 = at least one gap (usable as a gate).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# LONG is protected by a SELL stop, SHORT by a BUY stop. A stop on the wrong side does
# not close the position — it doubles it. Live 2026-08-05 carried exactly that: a SELL
# MYM stop against a SHORT MYM position, left over from an earlier LONG.
_PROTECTIVE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}

_DEAD_STATUS = ("Filled", "Cancelled", "ApiCancelled", "Inactive")


def _load_positions(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  (no {path.name} — treating as flat)")
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("positions", []) if isinstance(data, dict) else list(data)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=88,
                    help="must differ from the runner (1), reader (99) and TWS (0)")
    ap.add_argument("--positions-path", default=str(_ROOT / "live_positions.json"))
    a = ap.parse_args()

    from ib_insync import IB

    ib = IB()
    ib.connect(a.host, a.port, clientId=a.client_id, timeout=15)
    print(f"connected  {a.host}:{a.port}  clientId={a.client_id}\n")
    try:
        # Orders from other clientIds are only delivered after this request.
        ib.reqAllOpenOrders()
        ib.sleep(2.0)
        trades = ib.openTrades()

        print(f"{'ordId':>7} {'client':>6} {'symbol':<10} {'type':<5} {'act':<5} "
              f"{'qty':>4} {'stop':>12} {'tif':<4} {'status'}")
        print("-" * 78)
        stops: dict[str, list] = {}
        for t in trades:
            o, c, s = t.order, t.contract, t.orderStatus
            print(f"{o.orderId:>7} {getattr(o, 'clientId', -1):>6} "
                  f"{(c.localSymbol or c.symbol):<10} {o.orderType:<5} {o.action:<5} "
                  f"{float(o.totalQuantity):>4.0f} {float(o.auxPrice):>12.2f} "
                  f"{o.tif:<4} {s.status}")
            if o.orderType in ("STP", "STP LMT") and s.status not in _DEAD_STATUS:
                stops.setdefault(c.symbol, []).append((o.action, o.orderId, o.auxPrice))
        if not trades:
            print("  (no open orders)")

        positions = _load_positions(Path(a.positions_path))
        print(f"\npositions in {Path(a.positions_path).name}: {len(positions)}")
        print("-" * 78)

        gaps = 0
        for p in positions:
            inst, direction = p.get("inst"), p.get("direction")
            want = _PROTECTIVE_SIDE.get(direction)
            candidates = stops.get(inst, [])
            matching = [c for c in candidates if c[0] == want]
            if matching:
                action, oid, px = matching[0]
                print(f"  OK        {inst:<6} {direction:<5} → {action} STP "
                      f"orderId={oid} @ {px:.2f}")
                continue
            gaps += 1
            if candidates:
                wrong = ", ".join(f"{c[0]} #{c[1]} @{c[2]:.2f}" for c in candidates)
                print(f"  WRONG-WAY {inst:<6} {direction:<5} → needs {want} STP; "
                      f"broker has {wrong} — would ADD to the position, not close it")
            else:
                print(f"  NAKED     {inst:<6} {direction:<5} → no working stop "
                      f"(file records stop_order_id={p.get('stop_order_id')!r})")

        # A stop with no position behind it will open a new one when it fires.
        held = {p.get("inst") for p in positions}
        for inst, candidates in stops.items():
            if inst not in held:
                gaps += 1
                for action, oid, px in candidates:
                    print(f"  ORPHAN    {inst:<6} {'':<5} → {action} STP orderId={oid} "
                          f"@ {px:.2f} with no position — cancel it")

        print("-" * 78)
        if gaps == 0:
            print(f"PASS — {len(positions)} position(s), every one protected on the right side")
        else:
            print(f"FAIL — {gaps} gap(s). Fix in TWS before the next session.")
        return 1 if gaps else 0
    finally:
        ib.disconnect()
        print("\ndisconnected")


if __name__ == "__main__":
    sys.exit(main())
