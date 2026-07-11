"""
global_index/run_maxhold_exit.py
================================
09:31 ET cron — close any MAX_HOLD position at RTH open (Option B fix).

Design intent: backtest exits MAX_HOLD at "that day's open" = 09:30 ET RTH open
(stocks origin: first bar of RTH session). Live previously ran at 14:05 ET (14h lag).
This cron fires at 09:31 ET to match the backtest's intended milepost.

Wiring:
  - Runs BEFORE the 14:05 ET run_day() cron.
  - Closes positions whose hold = (today - entry_day).days >= max_hold_days.
  - Persists updated state to live_positions.json.
  - If CLOSE fails: marks exit_pending=True → _retry_pending_exits() at 14:05 retries.
  - 14:05 run_day() sees cleared positions → no double-close.

Usage:
    cd d:\\raits
    python -m global_index.run_maxhold_exit \\
        --positions-path live_positions.json \\
        [--port 4002] \\
        [--dry-run]

Schedule (Windows Task Scheduler or cron):
    09:31 ET Mon-Fri
"""
from __future__ import annotations
import argparse, logging, sys, time
from pathlib import Path

_CWD = Path.cwd()
_has_gi  = (_CWD / "global_index").is_dir()
_has_fut = (_CWD / "futures").is_dir()
if not (_has_gi and _has_fut):
    sys.stderr.write(
        f"CWD guard FAIL: got {_CWD}\n"
        f"  Expected d:\\raits. Fix: cd d:\\raits && python -m global_index.run_maxhold_exit ...\n"
    )
    sys.exit(1)

if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from futures.basket import SWING_TF_PARAM, RISK
from futures.circuit_breaker import CircuitBreaker
from global_index.ibkr_broker import IBKRBroker
from global_index.net_exposure_multi import MultiClusterGuard
from global_index.runner import FuturesRunner

MAX_HOLD_DAYS = int(SWING_TF_PARAM["max_hold_days"])
ACCOUNT       = float(RISK["account"])

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_maxhold_exit")


def main():
    ap = argparse.ArgumentParser(description="09:31 ET MAX_HOLD exit — close positions at RTH open")
    ap.add_argument("--positions-path", default="live_positions.json",
                    help="JSON state file (same as run_live_day.py, default: live_positions.json)")
    ap.add_argument("--port",           type=int, default=4002,
                    help="IB Gateway port (default: 4002 paper)")
    ap.add_argument("--client-id",      type=int, default=2,
                    help="IBKR client ID (default: 2 — distinct from 14:05 runner's ID=1)")
    ap.add_argument("--dry-run",        action="store_true",
                    help="Connect + check positions but emit no orders")
    a = ap.parse_args()

    today = pd.Timestamp.now().normalize()
    print("=" * 68)
    print("MAX_HOLD EXIT — 09:31 ET RTH open cron")
    print(f"  today:          {today.date()}")
    print(f"  max_hold_days:  {MAX_HOLD_DAYS}")
    print(f"  positions-path: {a.positions_path}")
    print(f"  port:           {a.port}  dry-run: {a.dry_run}")
    print("=" * 68)

    pos_path = Path(a.positions_path)
    if not pos_path.exists():
        log.info("No positions file found (%s) — nothing to exit.", pos_path)
        return

    log.info("[ibkr] Connecting → 127.0.0.1:%d clientId=%d ...", a.port, a.client_id)
    broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
    broker.connect()
    time.sleep(5)   # let IB Gateway farm connections stabilize
    log.info("       Connected.")

    try:
        # signal_fn is not used by run_maxhold_exit() but required by FuturesRunner
        runner = FuturesRunner(
            broker=broker,
            guard=MultiClusterGuard(account=ACCOUNT),
            contracts_by_inst={},         # unused — no entries here
            signal_fn=lambda d, b, h: ([], []),
            breaker=CircuitBreaker(account=ACCOUNT),
            positions_path=pos_path,
        )

        open_count = len(runner.state.open_positions)
        log.info("[check] %d open position(s) in state", open_count)
        for p in runner.state.open_positions:
            hold = (today - pd.Timestamp(p.entry_day).normalize()).days if p.entry_day else -1
            log.info(
                "  %s/%s  dir=%s  entry=%s  hold=%dd  max_hold=%d  -> %s",
                p.inst, p.cluster, p.direction,
                str(p.entry_day.date()) if p.entry_day else "?",
                hold, MAX_HOLD_DAYS,
                "CLOSE" if hold >= MAX_HOLD_DAYS else "keep",
            )

        if a.dry_run:
            log.info("[dry-run] No orders sent.")
            return

        closed = runner.run_maxhold_exit(today, max_hold_days=MAX_HOLD_DAYS)

        print()
        if closed:
            print(f"  Closed {len(closed)} MAX_HOLD position(s):")
            for inst, cluster in closed:
                print(f"    {inst}/{cluster}")
        else:
            log.info("No MAX_HOLD positions to close today.")

    finally:
        broker.disconnect()
        log.info("[ibkr] Disconnected.")

    print("=" * 68)
    print("MAX_HOLD EXIT COMPLETE")
    print(f"  closed: {len(closed) if 'closed' in dir() else 0} position(s)")
    print("=" * 68)


if __name__ == "__main__":
    main()
