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
from global_index.runner import FuturesRunner, STOP_FILE_NAME

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
    ap.add_argument("--stop-path",      default=STOP_FILE_NAME,
                    help="D5 kill switch: entries are skipped while this file exists. "
                         "This job takes no entries, but a path that ignores the switch "
                         "is the defect H2 describes — wire it everywhere (OPERATIONS.md:89)")
    ap.add_argument("--positions-path", default="live_positions.json",
                    help="JSON state file (same as run_live_day.py, default: live_positions.json)")
    ap.add_argument("--port",           type=int, default=4002,
                    help="IB Gateway port (default: 4002 paper)")
    # 1, KHÔNG phải 2. Job này huỷ STP do runner (clientId 1) đặt, và IBKR chỉ nhận lệnh
    # huỷ từ chính clientId đã đặt lệnh. Với id=2 thì `cancel_order` KHÔNG BAO GIỜ thành
    # công: mỗi lần MAX_HOLD đóng vị thế lại để lại một STP mồ côi, và một STP mồ côi khi
    # khớp sẽ MỞ vị thế ngược chiều. Xảy ra thật 2026-08-10 với MYM #12.
    #
    # Id riêng vốn để tránh đụng độ, nhưng 09:31 không trùng slot nào (live_day 14:05-15:55,
    # NKD 01:10-02:55, quét sửa ở phút :20 và không có slot 09:20), nên dùng chung là an toàn.
    ap.add_argument("--client-id",      type=int, default=1,
                    help="BAT BUOC trùng clientId của run_live_day (1). IBKR chỉ nhận lệnh huỷ "
                         "từ chính clientId đã đặt lệnh, nên một id khác KHÔNG BAO GIỜ huỷ "
                         "được STP do runner đặt — xem OPERATIONS.md muc 'clientId'.")
    ap.add_argument("--dry-run",        action="store_true",
                    help="Connect + check positions but emit no orders")
    a = ap.parse_args()

    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
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
            # Without this every _append_trade on this path returns without writing:
            # the exit books its P&L into the sleeve ledger and leaves no row behind.
            # Measured 2026-08-17 — M2K closed here, equity 50228.75 -> 50408.25, and
            # trade_log.jsonl untouched, so the day read as having no exit at all.
            trade_log_path=str(_CWD / "trade_log.jsonl"),
            stop_path=a.stop_path,        # D5 — see RUNNER_AUDIT.md H2
            # B4 runs inside __init__, so this job is what places a deferred STP —
            # 09:31 ET the morning after entry, not the 14:05 slot. Pass the session
            # date explicitly: the runner would otherwise read its own clock, and two
            # notions of "today" inside one run is how the window gets misjudged.
            today=today,
            now=pd.Timestamp.now(tz="America/New_York").tz_localize(None),
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
