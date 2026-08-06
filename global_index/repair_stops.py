"""global_index/repair_stops.py — bring IBKR stop orders back in line with the book.

Fixes what check_open_orders.py reports:

  NAKED     → place the stop at the level recorded in live_positions.json
  WRONG-WAY → cancel the wrong-side stop, then place the correct one
  ORPHAN    → cancel a stop that has no position behind it

Dry run by default. Nothing is sent without --execute.

It goes through IBKRBroker.place_stop / cancel_order rather than raw ib_insync, so a
repair exercises the same verified path the runner uses — a stop that IBKR refuses is
reported here as refused, not logged as placed.

Two refusals are deliberate and not overridable:

  * A stop on the wrong side of the market is never sent. LONG needs stop < market and
    SHORT needs stop > market; anything else triggers the instant it arrives.
  * A second stop is never stacked on an instrument that already has a correct-side
    one working. Two stops on one contract both fire, closing the position twice and
    opening the reverse.

Stop levels come from live_positions.json. They are the chandelier levels computed at
entry, and the runner does not ratchet them (runner.py: "stop_price = entry chandelier
level ... not ratcheted yet"), so the recorded level is still the intended one. A
position whose stop_price is null cannot be repaired here — the level is unknown, and
guessing one is worse than reporting the gap.

    # look first
    python -X utf8 global_index/repair_stops.py
    # then act
    python -X utf8 global_index/repair_stops.py --execute

Stop the scheduler before running with --execute: run_live_day rewrites
live_positions.json at the end of every slot and would overwrite the ids written here.

Exit code 0 = nothing left to fix, 1 = gaps remain.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from global_index.check_open_orders import (
    PROTECTIVE_SIDE, classify, load_positions, working_stops,
)
from global_index.ibkr_broker import IBKRBroker


def _market_prices(ib) -> dict:
    """{runner_inst: market_price} from the portfolio feed."""
    from global_index.ibkr_broker import _IBKR_TO_RAITS
    out = {}
    for item in ib.portfolio():
        sym = item.contract.symbol
        out[_IBKR_TO_RAITS.get(sym, sym)] = float(item.marketPrice)
    return out


def _side_is_sane(direction: str, stop: float, market: float) -> tuple[bool, str]:
    """A stop on the wrong side of the market fires the moment it is accepted."""
    if market is None:
        return False, "no market price available to check against"
    if direction == "LONG" and not stop < market:
        return False, f"LONG stop {stop:.2f} is not below market {market:.2f}"
    if direction == "SHORT" and not stop > market:
        return False, f"SHORT stop {stop:.2f} is not above market {market:.2f}"
    return True, ""


def _write_positions(path: Path, new_ids: dict) -> None:
    """Persist the new stop_order_ids, keeping the rest of the file untouched.

    A stale id is not harmless: on close, cancel_order would fail against the dead id
    and raise a false orphan alert, while the stop actually working stays uncancelled.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for p in data.get("positions", []):
        if p.get("inst") in new_ids:
            p["stop_order_id"] = new_ids[p["inst"]]
    backup = path.with_suffix(".json.bak")
    shutil.copy2(path, backup)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    tmp.replace(path)
    print(f"\n  updated {path.name} (backup: {backup.name})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=86,
                    help="must differ from the runner (1), reader (99) and TWS (0)")
    ap.add_argument("--positions-path", default=str(_ROOT / "live_positions.json"))
    ap.add_argument("--execute", action="store_true",
                    help="send the orders; without it nothing is transmitted")
    a = ap.parse_args()

    pos_path = Path(a.positions_path)
    positions = load_positions(pos_path)
    if not positions:
        print("no positions on file — nothing to repair")
        return 0

    broker = IBKRBroker(host=a.host, port=a.port, client_id=a.client_id)
    broker.connect()
    print(f"connected  {a.host}:{a.port}  clientId={a.client_id}")
    print("MODE: " + ("EXECUTE — orders will be sent" if a.execute
                      else "DRY RUN — nothing will be sent"))
    try:
        ib = broker._ib          # ops tool: the raw handle is needed for the price feed
        stops = working_stops(ib)
        prices = _market_prices(ib)
        by_inst = {p.get("inst"): p for p in positions}

        plan: list[tuple] = []   # (kind, inst, payload)
        for verdict, inst, direction, detail in classify(positions, stops):
            if verdict == "OK":
                action, oid, px = detail
                print(f"  SKIP      {inst:<6} {direction:<5} already protected: "
                      f"{action} STP #{oid} @ {px:.2f}")
                # Protected is not the same as protected at the intended level. Not
                # repaired automatically: replacing a working stop means a window with
                # none at all, and the recorded level may be the stale one. Say it,
                # let the operator decide.
                want = by_inst[inst].get("stop_price")
                # Ignore sub-tick differences: place_stop snaps to the tick grid on
                # purpose, and warning about that on every position would drown the
                # case this line exists for — a stop at a genuinely different level.
                tick = IBKRBroker._tick_size(inst) or 0.0
                if want is not None and abs(float(want) - px) > tick + 1e-9:
                    # LONG stops sit below market, so a lower one risks more; SHORT
                    # stops sit above, so a higher one risks more.
                    wider = (px < float(want)) if direction == "LONG" else (px > float(want))
                    print(f"            ⚠ level differs — working {px:.2f} vs intended "
                          f"{float(want):.2f}; risk is "
                          f"{'WIDER' if wider else 'tighter'} than sized for. "
                          f"Replace manually if that matters.")
            elif verdict == "HAZARD":
                # Position is already protected; this extra stop is on the wrong side
                # and must go. Cancel only — never place, or we stack a duplicate.
                action, oid, px = detail
                plan.append(("cancel", inst,
                             (oid, f"wrong-side {action} STP @ {px:.2f} alongside a "
                                   f"correct one")))
            elif verdict == "ORPHAN":
                action, oid, px = detail
                plan.append(("cancel", inst, (oid, f"orphan {action} STP @ {px:.2f}")))
            elif verdict == "WRONG-WAY":
                for action, oid, px in detail:
                    plan.append(("cancel", inst,
                                 (oid, f"wrong-side {action} STP @ {px:.2f}")))
                plan.append(("place", inst, by_inst[inst]))
            else:  # NAKED
                plan.append(("place", inst, by_inst[inst]))

        if not plan:
            print("\nnothing to repair — every position is protected")
            return 0

        print("\nPLAN")
        print("-" * 78)
        new_ids: dict = {}
        remaining = 0
        for kind, inst, payload in plan:
            if kind == "cancel":
                oid, why = payload
                print(f"  CANCEL    {inst:<6} orderId={oid}  ({why})")
                if not a.execute:
                    continue
                if broker.cancel_order(str(oid)):
                    print(f"            → cancelled")
                else:
                    remaining += 1
                    print(f"            → FAILED, still live — cancel #{oid} in TWS")
                continue

            p = payload
            direction, stop = p.get("direction"), p.get("stop_price")
            contracts = int(p.get("contracts") or 0)
            if stop is None:
                remaining += 1
                print(f"  BLOCKED   {inst:<6} {direction:<5} stop_price is null — "
                      f"level unknown, recompute with p0c_verify_swing.py")
                continue
            sane, why = _side_is_sane(direction, float(stop), prices.get(inst))
            if not sane:
                remaining += 1
                print(f"  BLOCKED   {inst:<6} {direction:<5} {why} — would fire on arrival")
                continue

            mkt = prices.get(inst)
            print(f"  PLACE     {inst:<6} {direction:<5} "
                  f"{PROTECTIVE_SIDE[direction]} STP x{contracts} @ {float(stop):.2f} "
                  f"(market {mkt:.2f})")
            if not a.execute:
                continue
            oid = broker.place_stop(inst, direction, contracts, float(stop),
                                    p.get("cluster") or "")
            if oid:
                new_ids[inst] = oid
                print(f"            → accepted, orderId={oid}")
            else:
                remaining += 1
                print(f"            → REFUSED by IBKR (see log) — position still naked")

        if not a.execute:
            print("-" * 78)
            print("dry run — re-run with --execute to send the above")
            return 1

        if new_ids:
            _write_positions(pos_path, new_ids)

        print("\nVERIFY")
        print("-" * 78)
        after = working_stops(ib)
        gaps = 0
        for verdict, inst, direction, _ in classify(positions, after):
            if verdict == "OK":
                print(f"  OK        {inst:<6} {direction}")
            else:
                gaps += 1
                print(f"  {verdict:<9} {inst:<6} {direction} — still unresolved")
        print("-" * 78)
        print("PASS — every position protected" if gaps == 0
              else f"FAIL — {gaps} gap(s) remain, fix in TWS")
        return 1 if (gaps or remaining) else 0
    finally:
        broker.disconnect()
        print("\ndisconnected")


if __name__ == "__main__":
    sys.exit(main())
