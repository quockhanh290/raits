"""
global_index/verify_account_clean.py
=====================================
Verify paper account 4002 is clean: 0 positions + 0 open orders.
Uses retry-stable reads to avoid "not settled yet" false empty.

Usage:
    cd d:\\raits
    python -m global_index.verify_account_clean [--port 4002] [--positions-file live_positions.json]
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",            type=int, default=4002)
    ap.add_argument("--positions-file",  default="live_positions.json")
    a = ap.parse_args()

    print("=" * 60)
    print("ACCOUNT CLEAN VERIFY — paper port", a.port)
    print("=" * 60)

    # ── 1. connect ────────────────────────────────────────────────
    try:
        import ib_insync as ibi
    except ImportError:
        sys.exit("ib_insync not installed")

    ib = ibi.IB()
    ib.errorEvent.clear()

    def _on_error(reqId, errorCode, errorString, contract):
        if errorCode in (2104, 2106, 2108, 2158, 2119, 10182, 2100, 2109,
                         10197, 10183, 2103, 2107, 399, 2174, 2109):
            return   # informational
        print(f"  IB error {errorCode}: {errorString[:80]}")
    ib.errorEvent += _on_error

    print(f"\n[1] Connecting to 127.0.0.1:{a.port} ...")
    try:
        ib.connect("127.0.0.1", a.port, clientId=19, timeout=15)
    except Exception as e:
        sys.exit(f"  FAIL: {e}")

    time.sleep(10)   # subscription settling (same as run_live_day)
    print("  Connected OK")

    # ── 2. equity ─────────────────────────────────────────────────
    print("\n[2] get_equity (4 retries × 2-5s) ...")
    equity = 0.0
    for attempt in range(4):
        ib.sleep(2.0 if attempt == 0 else 3.0)
        vals = ib.accountValues()
        for v in vals:
            if v.tag == "NetLiquidation" and v.currency == "USD":
                equity = float(v.value)
                break
            if v.tag == "NetLiquidation":
                try:
                    equity = float(v.value)
                    break
                except ValueError:
                    pass
        if equity > 0:
            break
    print(f"  equity = ${equity:,.2f}  ({'OK - non-zero' if equity > 0 else 'WARN - zero or not loaded'})")

    # ── 3. positions — retry-until-stable (2 consecutive identical) ──
    print("\n[3] get_positions (retry-until-stable: 4 reads × 2s, need 2 identical) ...")
    reads = []
    for i in range(4):
        ib.sleep(2.0)
        raw = ib.positions()
        snap = [(p.contract.symbol, p.contract.secType, p.position) for p in raw]
        snap_sorted = sorted(snap)
        reads.append(snap_sorted)
        print(f"  read {i+1}: {snap_sorted if snap_sorted else '(empty)'}")
        if len(reads) >= 2 and reads[-1] == reads[-2]:
            print(f"  -> stable after {i+1} reads")
            break

    stable_positions = reads[-1]
    positions_clean = (stable_positions == [])

    # ── 4. open orders / openTrades ───────────────────────────────
    print("\n[4] openTrades() — pending + GTC orders ...")
    ib.sleep(1.0)
    trades = ib.openTrades()
    open_orders = []
    for t in trades:
        sym   = t.contract.symbol if t.contract else "?"
        otype = t.order.orderType if t.order else "?"
        side  = t.order.action   if t.order else "?"
        qty   = t.order.totalQuantity if t.order else "?"
        oid   = t.order.orderId  if t.order else "?"
        status = t.orderStatus.status if t.orderStatus else "?"
        open_orders.append((sym, otype, side, qty, oid, status))
        print(f"  ORDER: {sym} {otype} {side} qty={qty} ordId={oid} status={status}")

    orders_clean = (open_orders == [])
    if orders_clean:
        print("  (no open orders)")

    # ── 5. cross-check live_positions.json ────────────────────────
    print("\n[5] Cross-check live_positions.json ...")
    fp = Path(a.positions_file)
    file_positions = None
    if fp.exists():
        try:
            data = json.loads(fp.read_text())
            # file key is "positions" (schema_version 1); "open_positions" is in-memory only
            if isinstance(data, dict):
                file_positions = data.get("positions", data.get("open_positions", []))
            elif isinstance(data, list):
                file_positions = data   # legacy schema_version 0
            else:
                file_positions = []
            file_has = bool(file_positions)
            print(f"  {fp}: positions={file_positions}")
        except Exception as e:
            print(f"  {fp}: READ ERROR {e}")
            file_positions = None
            file_has = False
    else:
        print(f"  {fp}: NOT FOUND (OK for first run)")
        file_has = False

    # ── 6. disconnect ─────────────────────────────────────────────
    ib.disconnect()

    # ── 7. verdict ────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("VERDICT")
    print("=" * 60)
    pos_str   = "CLEAN (empty, stable)" if positions_clean else f"DIRTY ({len(stable_positions)} positions)"
    ord_str   = "CLEAN (no orders)"     if orders_clean    else f"DIRTY ({len(open_orders)} orders)"
    eq_str    = f"${equity:,.2f}"        if equity > 0      else "WARN (0 — check account)"

    print(f"  Positions : {pos_str}")
    print(f"  Orders    : {ord_str}")
    print(f"  Equity    : {eq_str}")

    # cross-check
    if file_has and positions_clean:
        print()
        print("  !! EMPTY-WARN: file has positions but broker empty.")
        print("     Could be not-settled or stale file. Investigate before P2.")
    elif not file_has and positions_clean:
        print("  File + broker both empty: CONFIRMED CLEAN")

    print()
    if positions_clean and orders_clean and equity > 0:
        print("  RESULT: ACCOUNT CLEAN — safe to enter P2 paper trading")
    else:
        problems = []
        if not positions_clean: problems.append("positions not empty")
        if not orders_clean:    problems.append("open orders present")
        if equity <= 0:         problems.append("equity=0 (wrong account?)")
        print(f"  RESULT: NOT CLEAN — {', '.join(problems)}")
        print("  Investigate before P2.")

    print("=" * 60)


if __name__ == "__main__":
    main()
