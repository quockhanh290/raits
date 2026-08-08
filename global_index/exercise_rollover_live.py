"""
global_index/exercise_rollover_live.py — roll a throwaway position, for real

Every piece of the rollover path has been checked on its own against live IBKR:
place_stop lands on the front month, cancel_order clears it, unprotected_positions
matches on (symbol, expiry). What has never run is the sequence — close the front
month, open the next, cancel the old stop, place a new one at the shifted level —
and sequencing is where this system has been bitten before. send_order once
reported Cancelled on an order that had filled; stop prices off the tick grid were
rejected and left three positions naked. Neither showed up in a unit test.

The next real roll is 2026-09-11. This exercises the same path today on a position
opened for the purpose, on an instrument the live system is not holding.

    python -m global_index.exercise_rollover_live              # checks only
    python -m global_index.exercise_rollover_live --apply

Run it with the market OPEN and the scheduler DOWN:
  - closed market: the market orders rest and can fill at the Sunday open, which
    would move a position hours later with nobody watching
  - scheduler up: a slot running concurrently collides on clientId, and B3 sees a
    position the state file does not have and halts entries

It refuses to start on either, refuses if the instrument already has a position or
a working order, and cleans up whatever it opened even when a step fails.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_CWD = Path.cwd()
if not ((_CWD / "global_index").is_dir() and (_CWD / "futures").is_dir()):
    sys.stderr.write("CWD guard FAIL: run from d:\\raits\n")
    sys.exit(1)
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

import pandas as pd

from global_index import ibkr_broker as ib_mod
from global_index.ibkr_broker import IBKRBroker, _current_front_month

TEST_INST = "MNQ"          # the live system holds MYM and nothing else today
TEST_EXCH = "CME"
CLUSTER = "roska4_swing"
STALE_BAR_MINS = 15        # a fresh bar this recent means the market is trading


def _fmt(x):
    return "None" if x is None else f"{x:,.2f}"


def _state(ib, inst):
    """(positions, working stop orders) for inst, straight from IBKR."""
    pos = [p for p in ib.positions() if p.contract.symbol == inst and p.position]
    ords = [t for t in ib.reqAllOpenOrders()
            if t.contract.symbol == inst
            and t.order.orderType in ("STP", "STP LMT")
            and t.orderStatus.status in ("PreSubmitted", "Submitted")]
    return pos, ords


def _show(ib, inst, label):
    pos, ords = _state(ib, inst)
    print(f"  {label}")
    for p in pos:
        print(f"    position  {p.contract.symbol} {p.contract.lastTradeDateOrContractMonth} "
              f"qty={p.position:+.0f}")
    for t in ords:
        print(f"    stop      {t.contract.symbol} {t.contract.lastTradeDateOrContractMonth} "
              f"{t.order.action} aux={t.order.auxPrice} id={t.order.orderId}")
    if not pos and not ords:
        print("    (nothing)")
    return pos, ords


def main() -> int:
    ap = argparse.ArgumentParser(description="live rollover exercise")
    ap.add_argument("--apply", action="store_true",
                    help="actually open, roll and close a throwaway position")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=61)
    ap.add_argument("--inst", default=TEST_INST)
    a = ap.parse_args()
    inst = a.inst

    import ib_insync as ibi

    # ── refuse to run alongside the scheduler ────────────────────────────────
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or "
             "Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like "
             "'*run_scheduler*' } | Measure-Object | Select-Object -Expand Count"],
            capture_output=True, text=True, timeout=60)
        if (out.stdout or "").strip() not in ("", "0"):
            print("REFUSING: run_scheduler is running. A slot firing mid-exercise "
                  "collides on clientId, and B3 will see a position the state file "
                  "does not have and halt entries. Stop it first.")
            return 1
    except Exception as exc:
        print(f"could not check for a running scheduler ({exc}) — stop it by hand")

    broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
    broker.connect()
    time.sleep(3)
    ib = broker._require_connection()
    opened = False
    stop_id = None

    try:
        front = _current_front_month(inst)
        roll = ib_mod.get_roll_event(inst, str(pd.Timestamp.now().date()))
        nxt = None
        for _d, _f, _n in ib_mod.ROLL_SCHEDULE.get(inst, []):
            if _f == front:
                nxt = _n
                break
        print("=" * 74)
        print(f"ROLLOVER EXERCISE — {inst}  {front} -> {nxt}")
        print("=" * 74)
        if nxt is None:
            print(f"no next contract for {inst} {front} in ROLL_SCHEDULE — cannot roll")
            return 1

        # ── market has to be trading ─────────────────────────────────────────
        bars = broker.fetch_bars(inst, through=pd.Timestamp.now())
        if bars is None or bars.empty:
            print("REFUSING: no bars returned")
            return 1
        age = (pd.Timestamp.now() - pd.Timestamp(bars.index[-1])).total_seconds() / 60
        print(f"  last bar {bars.index[-1]} — {age:.0f} min old")
        if age > STALE_BAR_MINS:
            print(f"REFUSING: market looks closed (last bar {age:.0f} min old). Market "
                  f"orders would rest and could fill at the next open, moving a "
                  f"position with nobody watching.")
            return 1
        px = float(bars['close'].iloc[-1])

        pos, ords = _show(ib, inst, "starting state:")
        if pos or ords:
            print(f"REFUSING: {inst} already has a position or a working stop. Pick an "
                  f"instrument the live system is not using.")
            return 1

        if not a.apply:
            print("\nchecks passed — re-run with --apply to open, roll and close")
            return 0

        # ── open a throwaway long, protect it well below the market ──────────
        from global_index.broker import Order
        print(f"\n1. OPEN {inst} LONG x1 @ market (~{_fmt(px)})")
        fill = broker.send_order(Order(inst=inst, action="OPEN", direction="LONG",
                                       contracts=1, cluster=CLUSTER))
        print(f"   {fill.status} @ {_fmt(fill.avg_price)}")
        if fill.status not in ("FILLED", "PARTIAL"):
            print("   open did not fill — nothing to clean up")
            return 1
        opened = True

        stop_px = round(fill.avg_price * 0.97, 2)
        print(f"\n2. STOP at {_fmt(stop_px)} (3% below, cannot trigger in a few minutes)")
        stop_id = broker.place_stop(inst, "LONG", 1, stop_px, CLUSTER)
        print(f"   orderId {stop_id or '(rejected)'}")
        time.sleep(2)
        _show(ib, inst, "after open + stop:")

        # ── force today to be a roll date and run the real path ──────────────
        print(f"\n3. ROLL — pretending today is the {front} -> {nxt} roll date")
        today = str(pd.Timestamp.now().date())
        saved = ib_mod.ROLL_SCHEDULE.get(inst, [])
        ib_mod.ROLL_SCHEDULE[inst] = [(today, front, nxt)] + list(saved)
        try:
            from futures.circuit_breaker import CircuitBreaker
            from global_index.live_decision import OpenPos
            from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard
            from global_index.runner import FuturesRunner

            runner = FuturesRunner(
                broker=broker,
                guard=MultiClusterGuard(account=50_000.0, clusters={
                    CLUSTER: ClusterBudget(CLUSTER, max_gross_pct=0.05,
                                           max_net_pct=0.044)}),
                contracts_by_inst={inst: 1},
                signal_fn=lambda d, b, h: ([], []),
                breaker=CircuitBreaker(account=50_000.0),
            )
            runner.state.open_positions.append(OpenPos(
                inst=inst, direction="LONG", contracts=1, risk_dollars=500.0,
                cluster=CLUSTER, entry_day=pd.Timestamp(today).normalize(),
                stop_price=stop_px, stop_order_id=stop_id))
            runner._handle_rollover_if_needed(pd.Timestamp(today))
            p = runner.state.open_positions[0] if runner.state.open_positions else None
            print(f"   runner state: "
                  f"{'(position removed)' if p is None else f'stop {_fmt(p.stop_price)} id {p.stop_order_id}'}")
        finally:
            ib_mod.ROLL_SCHEDULE[inst] = saved

        time.sleep(2)
        pos2, ords2 = _show(ib, inst, "\nafter roll:")

        print("\n4. VERDICT")
        on_next = [p for p in pos2 if p.contract.lastTradeDateOrContractMonth.startswith(nxt)]
        stop_next = [t for t in ords2
                     if t.contract.lastTradeDateOrContractMonth.startswith(nxt)]
        stop_old = [t for t in ords2
                    if t.contract.lastTradeDateOrContractMonth.startswith(front)]
        ok = True
        for label, cond, why in [
            ("position moved to the next contract", bool(on_next), "still on the old one"),
            ("old contract's stop cancelled", not stop_old,
             "ORPHAN — it can fill and open a position nobody asked for"),
            ("new contract has a stop", bool(stop_next), "UNPROTECTED"),
        ]:
            print(f"   [{'PASS' if cond else 'FAIL'}] {label}"
                  + ("" if cond else f" — {why}"))
            ok &= bool(cond)
        return 0 if ok else 1

    finally:
        print("\n5. CLEANUP")
        try:
            time.sleep(1)
            _, ords = _state(ib, inst)
            for t in ords:
                print(f"   cancelling stop id {t.order.orderId} "
                      f"({t.contract.lastTradeDateOrContractMonth})")
                broker.cancel_order(str(t.order.orderId))
            time.sleep(2)
            pos, _ = _state(ib, inst)
            for p in pos:
                side = "SELL" if p.position > 0 else "BUY"
                print(f"   closing {p.contract.lastTradeDateOrContractMonth} "
                      f"qty={p.position:+.0f} with {side}")
                c = ibi.Future(inst, lastTradeDateOrContractMonth=(
                    p.contract.lastTradeDateOrContractMonth), exchange=TEST_EXCH)
                ib.qualifyContracts(c)
                ib.placeOrder(c, ibi.MarketOrder(side, abs(int(p.position))))
                ib.sleep(3)
            time.sleep(2)
            pos, ords = _show(ib, inst, "final state:")
            if pos or ords:
                print("   *** NOT CLEAN — close the rest by hand in TWS ***")
        except Exception as exc:
            print(f"   cleanup failed: {exc}")
            print("   *** CHECK TWS BY HAND ***")
        broker.disconnect()


if __name__ == "__main__":
    sys.exit(main())
