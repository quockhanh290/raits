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


def _key(p: dict) -> tuple:
    """Position identity: (inst, cluster) — the same key the runner uses.

    Not `inst`. Two sleeves can hold the same contract, and keying stop bookkeeping by
    instrument then writes one order id onto both positions. `runner.py` already keys
    its own book this way (`held_by_key`, `exit_keys`); this file was the odd one out.
    """
    return (p.get("inst"), p.get("cluster"))


def id_corrections(positions: list[dict], stops: dict, today=None) -> dict:
    """{(inst, cluster): order_id} where the recorded stop_order_id disagrees with reality.

    A position that is already protected still needs its recorded id kept true.
    Live 2026-08-05: MES carried the fabricated id 62 and a real working stop #9. The
    repair skipped it as already protected and left 62 on file, so when MES closed the
    next day the runner cancelled a ghost, raised STP ORPHAN naming 62, and left #9
    working with no position behind it — an order that would have opened a short.

    The id now comes from `classify`, which assigns each stop to ONE position. Reading
    `stops.get(inst)` directly — as this did — hands the same order id to every position
    on the symbol, which is worse than a stale id: `cancel_order(p.stop_order_id)` is one
    of the few checks that IS per-position, and it would then cancel the stop protecting
    the other position on the way out of this one.
    """
    out: dict = {}
    for verdict, _inst, _direction, detail, pos in classify(positions, stops, today=today):
        if verdict != "OK" or pos is None:
            continue
        true_id = str(detail.order_id)
        recorded = pos.get("stop_order_id")
        if recorded is None or str(recorded) != true_id:
            out[_key(pos)] = true_id
    return out


def _write_positions(path: Path, new_ids: dict) -> None:
    """Persist the new stop_order_ids, keeping the rest of the file untouched.

    A stale id is not harmless: on close, cancel_order would fail against the dead id
    and raise a false orphan alert, while the stop actually working stays uncancelled.

    Keyed by (inst, cluster). It used to match on `inst` alone, so this loop stamped ONE
    order id onto EVERY position holding that contract — a false record written into the
    ledger the working checks trust. That is a heavier failure than the missed checks it
    sat next to: those merely fail to notice a gap, this one manufactures evidence that
    there is none.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for p in data.get("positions", []):
        k = _key(p)
        if k in new_ids:
            p["stop_order_id"] = new_ids[k]
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
        # No {inst: position} lookup here. `classify` hands back the position it judged,
        # so a second position on the same contract cannot be shadowed by the first —
        # which is what a dict keyed on `inst` did, silently, while this file went on to
        # place the survivor's level and stamp its order id onto both.
        by_key = {_key(p): p for p in positions}

        plan: list[tuple] = []   # (kind, inst, payload)
        for verdict, inst, direction, detail, pos in classify(positions, stops):
            if verdict == "OK":
                action, oid, px = detail.action, detail.order_id, detail.price
                print(f"  SKIP      {inst:<6} {direction:<5} already protected: "
                      f"{action} STP #{oid} @ {px:.2f} x{detail.qty}")
                # Protected is not the same as protected at the intended level. Not
                # repaired automatically: replacing a working stop means a window with
                # none at all, and the recorded level may be the stale one. Say it,
                # let the operator decide.
                want = pos.get("stop_price")
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
                # An unclaimed stop on an instrument that IS held — either the wrong side,
                # or a surplus correct-side one no position needs. Cancel only, never
                # place: the positions here already have what they claimed.
                plan.append(("cancel", inst,
                             (detail.order_id,
                              f"unclaimed {detail.action} STP @ {detail.price:.2f} "
                              f"x{detail.qty} on a held instrument")))
            elif verdict == "ORPHAN":
                plan.append(("cancel", inst,
                             (detail.order_id, f"orphan {detail.action} STP "
                                               f"@ {detail.price:.2f} x{detail.qty}")))
            elif verdict == "WRONG-WAY":
                for c in detail:
                    plan.append(("cancel", inst,
                                 (c.order_id,
                                  f"wrong-side {c.action} STP @ {c.price:.2f}")))
                plan.append(("place", inst, pos))
            elif verdict == "PARTIAL":
                # Covered, but not for its full size. NOT auto-repaired: topping up means
                # deciding why the shortfall exists, and every explanation implies a
                # different fix. A stop that shrank means contracts moved somewhere this
                # tool cannot see; placing the difference would paper over that.
                mine, got, need = detail
                ids = ", ".join(f"#{c.order_id} x{c.qty}" for c in mine)
                print(f"  REPORT    {inst:<6} {direction:<5} stop chi phu {got}/{need} "
                      f"hop dong ({ids}) — khong tu dong va, xem vi sao thieu truoc")
            elif verdict == "DEFERRED":
                # The runner withheld this stop on purpose — swing/NKD positions get
                # theirs on the first run of the NEXT session, because the validated
                # engine only tests the stop from the day after entry. Placing it here
                # restores the rule that measured -$10,832 instead of +$47,166.
                # See runner._stop_deferred and check_open_orders._deferred.
                print(f"  {inst:<6} bo qua — dang trong cua so hoan CO CHU DICH, "
                      f"B4 se dat o phien sau")
            elif verdict == "NAKED":
                plan.append(("place", inst, pos))
            else:
                # Never fall through to "place". A verdict added to classify() later
                # would otherwise inherit the most destructive action in this file by
                # default — which is exactly how DEFERRED would have silently undone
                # the deferral had this stayed `else: # NAKED`.
                print(f"  {inst:<6} verdict {verdict!r} khong biet xu ly — bo qua, "
                      f"khong tu dong lam gi")

        # A position can be fully protected and still carry a wrong recorded id. Left
        # alone it makes the runner cancel a ghost on exit and orphan the real stop, so
        # correct it whether or not there is anything else to repair.
        drift = id_corrections(positions, stops)
        if drift:
            print("\nRECORDED ID DRIFT (file says one thing, broker holds another)")
            print("-" * 78)
            for k, true_id in drift.items():
                _i, _c = k
                print(f"  {_i:<6} [{_c}] stop_order_id "
                      f"{by_key[k].get('stop_order_id')!r} → {true_id!r}")

        if not plan and not drift:
            print("\nnothing to repair — every position is protected")
            return 0

        new_ids: dict = dict(drift)
        remaining = 0
        if not a.execute and drift:
            print("\n  (dry run — ids not written)")

        print("\nPLAN")
        print("-" * 78)
        if not plan:
            print("  (no orders to send)")
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
                    # Nguyên nhân gần như luôn là sai chủ: IBKR chỉ nhận lệnh huỷ từ chính
                    # clientId đã đặt lệnh. cancel_order đã ghi ra id chủ sở hữu trong log;
                    # đưa luôn lệnh chạy lại để người vận hành không phải tự ghép.
                    print(f"            → FAILED, still live. Gan nhu chac chan la SAI CHU: "
                          f"IBKR chi nhan lenh huy tu clientId da dat lenh. Xem dong "
                          f"'placed by clientId=N' o tren roi chay lai:")
                    print(f"              python -X utf8 global_index/repair_stops.py "
                          f"--client-id N --execute")
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
                new_ids[_key(p)] = oid
                print(f"            → accepted, orderId={oid}")
            else:
                remaining += 1
                print(f"            → REFUSED by IBKR (see log) — position still naked")

        if not a.execute:
            print("-" * 78)
            print("dry run — re-run with --execute to apply the above")
            return 1

        if new_ids:
            _write_positions(pos_path, new_ids)

        print("\nVERIFY")
        print("-" * 78)
        after = working_stops(ib)
        gaps = 0
        for verdict, inst, direction, _d, _p in classify(positions, after):
            if verdict == "OK":
                print(f"  OK        {inst:<6} {direction}")
            elif verdict == "DEFERRED":
                # KHÔNG phải gap. check_open_orders.main() đã loại DEFERRED khỏi bộ đếm từ
                # đầu; khối VERIFY này thì chưa, nên một lần sửa thành công vẫn in "FAIL —
                # 1 gap(s) remain" chỉ vì có một vị thế đang trong cửa sổ hoãn có chủ đích.
                # Đúng loại cảnh báo giả mà chính verdict DEFERRED sinh ra để dập.
                print(f"  DEFERRED  {inst:<6} {direction} — cua so hoan CO CHU DICH, "
                      f"khong phai thieu sot")
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
