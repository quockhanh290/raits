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
from typing import NamedTuple

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# PROTECTIVE_SIDE is IMPORTED, never redefined. It used to be declared here and nowhere
# else, so the broker's own checks had no notion of side and counted a SELL stop as
# protection for a SHORT. Now the broker owns it and this tool follows.
from global_index.ibkr_broker import _IBKR_TO_RAITS, PROTECTIVE_SIDE

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


class Stop(NamedTuple):
    """One working stop order.

    `qty` is here because "protected" used to mean "a stop exists on this symbol", and
    that is not the same as "this position is covered". A 1-lot stop under a 2-lot
    position satisfied the old check. Carrying the quantity is what lets the check ask
    the question it was always meant to ask.
    """
    action: str
    order_id: int
    price: float
    qty: int


def working_stops(ib) -> dict:
    """{runner_inst: [Stop, ...]} for live stops, all clients.

    Shared with repair_stops.py deliberately: two copies of this scan would be two
    chances to disagree about what "protected" means, which is the failure mode this
    whole tool exists to catch.
    """
    # reqAllOpenOrders RETURNS the authoritative list. ib.openTrades() reads an
    # accumulating cache that never evicts orders IBKR stops reporting, so a filled
    # cross-client stop lingers there indefinitely.
    out: dict = {}
    for t in ib.reqAllOpenOrders():
        o, s = t.order, t.orderStatus
        if o.orderType not in ("STP", "STP LMT") or s.status not in LIVE_STATUS:
            continue
        sym = t.contract.symbol
        inst = _IBKR_TO_RAITS.get(sym, sym)
        out.setdefault(inst, []).append(
            Stop(o.action, o.orderId, float(o.auxPrice), int(o.totalQuantity or 0)))
    return out


def _deferred(p: dict, today) -> bool:
    """True while a position is inside its DELIBERATE stop-free window.

    The runner no longer places the STP at the fill for swing/NKD — the validated
    engine only tests the stop from the day AFTER entry, and placing it at once is a
    stricter rule that costs the whole edge (measured 2018-2026: -$10,832 placed at
    fill vs +$47,166 placed the next session). See runner._stop_deferred.

    Without this, classify calls every fresh position NAKED, main() prints FAIL and
    points the operator at repair_stops.py — which would place the very stop the
    runner deliberately withheld, silently undoing the fix. The report is the more
    dangerous half: a daily false NAKED teaches the operator to ignore the word, and
    then a genuinely unprotected position goes unnoticed.

    The cluster set is IMPORTED, never copied. Two copies drift, and the drift would
    show up as one tool protecting a position the other leaves naked.
    """
    from global_index.runner import _DEFERRED_STOP_CLUSTERS
    if p.get("cluster") not in _DEFERRED_STOP_CLUSTERS:
        return False
    ed = p.get("entry_day")
    if not ed:
        return False              # unknown entry day → treat as naked, never guess
    try:
        import pandas as pd
        return pd.Timestamp(ed).normalize() == pd.Timestamp(today).normalize()
    except Exception:
        return False


def classify(positions: list[dict], stops: dict, today=None) -> list[tuple]:
    """[(verdict, inst, direction, detail, position)] for every position and every stop.

    Verdicts: OK / PARTIAL / WRONG-WAY / DEFERRED / NAKED / HAZARD / ORPHAN.

    Each stop is CLAIMED by at most one position. The old version asked
    `matching = [c for c in stops.get(inst, []) if c[0] == want]` per position and took
    `matching[0]`, so one working stop marked every position on that symbol as
    protected. With one position per instrument that was invisible; it stops being
    invisible the moment a second sleeve trades the same contract, which is what
    STRESS_MID would have done (see OPERATIONS.md, "STRESS_MID: tại sao cron 10:20 bị
    TẮT"). Claiming also fixes the reverse misreading: a BUY stop protecting a SHORT was
    reported as a HAZARD against a LONG on the same symbol, when in fact each side had
    its own correct stop.

    A position is OK only when the stops it claimed cover its full size. Short of that
    it is PARTIAL — reported, never auto-repaired, because topping up means guessing how
    the shortfall arose.

    The fifth element is the position dict itself. Callers used to re-derive it with
    `{p["inst"]: p for p in positions}`, a lookup that silently dropped one of two
    positions sharing an instrument and then repaired the survivor's level onto both.

    today: session date in ET. None reads it from the clock — in ET, not the host's,
    which sits 11 hours ahead and names the previous session for most of the day.
    """
    if today is None:
        import pandas as pd
        from global_index.runner import ET_TZ
        today = pd.Timestamp.now(tz=ET_TZ).normalize().tz_localize(None)

    pool = {inst: list(cands) for inst, cands in stops.items()}

    # Pass 1 — every position claims stops on ITS protective side, up to its own size.
    #
    # Its OWN recorded order id goes first. Side and size alone cannot separate two
    # stops on one symbol, and after a rollover there are two: C2 cancels the expiring
    # contract's STP and places a fresh one, but when the cancel FAILS (it logs CRITICAL
    # and carries on) both stay live on the same symbol with different expiries. Claiming
    # by side alone would then hand the position whichever came back first — possibly the
    # dead contract's — and report the real stop as a surplus for repair_stops to cancel.
    #
    # Expiry would be the natural key, but live_positions.json does not record one. The
    # order id is the identity that IS on file, so it is the one to trust first.
    claims: dict = {}
    for i, p in enumerate(positions):
        want = PROTECTIVE_SIDE.get(p.get("direction"))
        need = int(p.get("contracts") or 0)
        cands = pool.get(p.get("inst"), [])
        mine, got = [], 0
        _rec = p.get("stop_order_id")
        if _rec is not None:
            # Only if it is on the protective side. A recorded id pointing at a wrong-side
            # order is not protection — that is the MYM shape from 2026-08-05, where a SELL
            # STP sat under a SHORT and would have doubled it.
            _own = next((c for c in cands
                         if str(c.order_id) == str(_rec) and c.action == want), None)
            if _own is not None:
                cands.remove(_own)
                mine.append(_own)
                got += _own.qty
        for c in list(cands):
            if need > 0 and got >= need:
                break
            if c.action != want:
                continue
            cands.remove(c)
            mine.append(c)
            got += c.qty
            # need <= 0 means the file does not record a size. Claim exactly one and
            # stop — the old behaviour. Reporting PARTIAL on missing metadata would be
            # a false alarm, and a daily false alarm is how a real one gets ignored.
            if need <= 0 or got >= need:
                break
        claims[i] = (mine, got, need)

    # Pass 2 — each position is judged on what IT holds, not on what exists.
    rows = []
    for i, p in enumerate(positions):
        inst, direction = p.get("inst"), p.get("direction")
        mine, got, need = claims[i]
        if mine and (need <= 0 or got >= need):
            rows.append(("OK", inst, direction, mine[0], p))
        elif mine:
            rows.append(("PARTIAL", inst, direction, (mine, got, need), p))
        elif pool.get(inst):
            # Nothing on the protective side, but stops exist here — the WRONG-WAY case.
            # Consume them so pass 3 does not report the same orders a second time.
            wrong = list(pool[inst])
            pool[inst] = []
            rows.append(("WRONG-WAY", inst, direction, wrong, p))
        elif _deferred(p, today):
            rows.append(("DEFERRED", inst, direction, p.get("stop_price"), p))
        else:
            rows.append(("NAKED", inst, direction, p.get("stop_price"), p))

    # Pass 3 — anything unclaimed. On a held instrument that is a surplus stop: firing it
    # closes size nobody asked to close and opens the reverse. On an instrument with no
    # position it is an orphan. Both are cancels; the wording differs so the operator can
    # tell which mistake happened.
    dir_by_inst = {p.get("inst"): p.get("direction") for p in positions}
    for inst, left in pool.items():
        for c in left:
            if inst in dir_by_inst:
                rows.append(("HAZARD", inst, dir_by_inst[inst], c, None))
            else:
                rows.append(("ORPHAN", inst, None, c, None))
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
            for c in candidates:
                print(f"{inst:<7} {c.action:<7} {c.order_id:>7} {c.price:>12.2f} "
                      f"x{c.qty}")

        print(f"\npositions in {Path(a.positions_path).name}: {len(positions)}")
        print("-" * 78)

        gaps = 0
        for verdict, inst, direction, detail, _pos in classify(positions, stops):
            if verdict == "OK":
                print(f"  OK        {inst:<6} {direction:<5} → {detail.action} STP "
                      f"orderId={detail.order_id} @ {detail.price:.2f} x{detail.qty}")
                continue
            if verdict == "DEFERRED":
                # Not a gap: the runner withheld this stop on purpose and B4 places it
                # on the first run of the next session. Counting it would print FAIL
                # every day a position opens and send the operator to repair_stops.py,
                # which would undo the fix.
                print(f"  DEFERRED  {inst:<6} {direction:<5} → chua co stop, dang trong "
                      f"cua so hoan CO CHU DICH (muc {detail}); B4 dat o phien sau. "
                      f"KHONG chay repair_stops cho dong nay.")
                continue
            gaps += 1
            if verdict == "PARTIAL":
                # Under-covered, not unprotected. Kept apart from NAKED because the
                # repair differs: a naked position needs a stop, this one needs the
                # shortfall explained first — a stop that shrank means something else
                # already moved contracts.
                mine, got, need = detail
                ids = ", ".join(f"#{c.order_id} x{c.qty}" for c in mine)
                print(f"  PARTIAL   {inst:<6} {direction:<5} → stop chi phu {got}/{need} "
                      f"hop dong ({ids}) — KHONG tu dong va, tim vi sao thieu truoc")
            elif verdict == "WRONG-WAY":
                wrong = ", ".join(f"{c.action} #{c.order_id} @{c.price:.2f}" for c in detail)
                print(f"  WRONG-WAY {inst:<6} {direction:<5} → needs "
                      f"{PROTECTIVE_SIDE.get(direction)} STP; broker has {wrong} — "
                      f"would ADD to the position, not close it")
            elif verdict == "HAZARD":
                # Unclaimed on an instrument that IS held: either the wrong side (firing
                # doubles the position) or a surplus correct-side stop (firing closes
                # size nobody asked to close, then opens the reverse). Both are cancels.
                side = "WRONG side" if detail.action != PROTECTIVE_SIDE.get(direction)                     else "correct side but SURPLUS — no position needs it"
                print(f"  HAZARD    {inst:<6} {direction:<5} → {detail.action} STP "
                      f"orderId={detail.order_id} @ {detail.price:.2f} x{detail.qty} is "
                      f"{side} and still live. Cancel it.")
            elif verdict == "NAKED":
                print(f"  NAKED     {inst:<6} {direction:<5} → no working stop "
                      f"(intended level {detail})")
            else:  # ORPHAN — will open a new position if it fires
                print(f"  ORPHAN    {inst:<6} {'':<5} → {detail.action} STP "
                      f"orderId={detail.order_id} @ {detail.price:.2f} x{detail.qty} "
                      f"with no position — cancel it")

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
