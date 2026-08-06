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

from global_index.ibkr_broker import _IBKR_TO_RAITS

# LONG is protected by a SELL stop, SHORT by a BUY stop. A stop on the wrong side does
# not close the position — it doubles it. Live 2026-08-05 carried exactly that: a SELL
# MYM stop against a SHORT MYM position, left over from an earlier LONG.
PROTECTIVE_SIDE = {"LONG": "SELL", "SHORT": "BUY"}

# Only these mean IBKR is holding the order and it will fire. PendingSubmit is NOT
# one of them: it is ib_insync's own initial status (ib.py:673), and an order IBKR has
# rejected can sit there indefinitely. Counting it as protection is how a verify step
# reported "every position protected" moments after IBKR refused both stops
# (live 2026-08-06, code 110).
LIVE_STATUS = ("PreSubmitted", "Submitted")


def load_positions(path: Path, quiet: bool = False) -> list[dict]:
    if not path.exists():
        if not quiet:
            print(f"  (no {path.name} — treating as flat)")
        return []
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("positions", []) if isinstance(data, dict) else list(data)


def working_stops(ib) -> dict:
    """{runner_inst: [(action, order_id, stop_price), ...]} for live stops, all clients.

    Shared with repair_stops.py deliberately: two copies of this scan would be two
    chances to disagree about what "protected" means, which is the failure mode this
    whole tool exists to catch.
    """
    ib.reqAllOpenOrders()
    ib.sleep(2.0)
    out: dict = {}
    for t in ib.openTrades():
        o, s = t.order, t.orderStatus
        if o.orderType not in ("STP", "STP LMT") or s.status not in LIVE_STATUS:
            continue
        sym = t.contract.symbol
        inst = _IBKR_TO_RAITS.get(sym, sym)
        out.setdefault(inst, []).append((o.action, o.orderId, float(o.auxPrice)))
    return out


def classify(positions: list[dict], stops: dict) -> list[tuple]:
    """[(verdict, inst, direction, detail)] — verdict in OK/WRONG-WAY/NAKED/ORPHAN."""
    rows = []
    for p in positions:
        inst, direction = p.get("inst"), p.get("direction")
        want = PROTECTIVE_SIDE.get(direction)
        candidates = stops.get(inst, [])
        matching = [c for c in candidates if c[0] == want]
        if matching:
            rows.append(("OK", inst, direction, matching[0]))
            # Being protected does not make a wrong-side stop harmless. It is still
            # live, and firing it opens size in the direction the position already
            # holds. Live 2026-08-06 held both and the tool called it PASS.
            for c in candidates:
                if c[0] != want:
                    rows.append(("HAZARD", inst, direction, c))
        elif candidates:
            rows.append(("WRONG-WAY", inst, direction, candidates))
        else:
            rows.append(("NAKED", inst, direction, p.get("stop_price")))
    held = {p.get("inst") for p in positions}
    for inst, candidates in stops.items():
        if inst not in held:
            for c in candidates:
                rows.append(("ORPHAN", inst, None, c))
    return rows


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
        stops = working_stops(ib)
        positions = load_positions(Path(a.positions_path))

        print(f"{'inst':<7} {'action':<7} {'ordId':>7} {'stop':>12}")
        print("-" * 78)
        if not stops:
            print("  (no working stop orders)")
        for inst, candidates in sorted(stops.items()):
            for action, oid, px in candidates:
                print(f"{inst:<7} {action:<7} {oid:>7} {px:>12.2f}")

        print(f"\npositions in {Path(a.positions_path).name}: {len(positions)}")
        print("-" * 78)

        gaps = 0
        for verdict, inst, direction, detail in classify(positions, stops):
            if verdict == "OK":
                action, oid, px = detail
                print(f"  OK        {inst:<6} {direction:<5} → {action} STP "
                      f"orderId={oid} @ {px:.2f}")
                continue
            gaps += 1
            if verdict == "WRONG-WAY":
                wrong = ", ".join(f"{c[0]} #{c[1]} @{c[2]:.2f}" for c in detail)
                print(f"  WRONG-WAY {inst:<6} {direction:<5} → needs "
                      f"{PROTECTIVE_SIDE.get(direction)} STP; broker has {wrong} — "
                      f"would ADD to the position, not close it")
            elif verdict == "HAZARD":
                action, oid, px = detail
                print(f"  HAZARD    {inst:<6} {direction:<5} → {action} STP "
                      f"orderId={oid} @ {px:.2f} is on the WRONG side and still live — "
                      f"firing it would ADD to the position. Cancel it.")
            elif verdict == "NAKED":
                print(f"  NAKED     {inst:<6} {direction:<5} → no working stop "
                      f"(intended level {detail})")
            else:  # ORPHAN — will open a new position if it fires
                action, oid, px = detail
                print(f"  ORPHAN    {inst:<6} {'':<5} → {action} STP orderId={oid} "
                      f"@ {px:.2f} with no position — cancel it")

        print("-" * 78)
        if gaps == 0:
            print(f"PASS — {len(positions)} position(s), every one protected on the right side")
        else:
            print(f"FAIL — {gaps} gap(s). Run repair_stops.py, or fix in TWS.")
        return 1 if gaps else 0
    finally:
        ib.disconnect()
        print("\ndisconnected")


if __name__ == "__main__":
    sys.exit(main())
