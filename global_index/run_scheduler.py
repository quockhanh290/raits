"""
global_index/run_scheduler.py — TZ-independent APScheduler cron
===============================================================
Thay thế Windows Task Scheduler thủ công. Chạy 24/7 (process hoặc Windows
Service), tự convert ET↔machine-TZ và tự handle US DST.

Hai jobs:
  09:31 ET Mon-Fri → run_maxhold_exit  (MAX_HOLD close at RTH open)
  14:05 ET Mon-Fri → run_live_day      (daily signal + entry/exit)

Machine TZ-independent: VN (UTC+7), MST (UTC-7), ET, cloud — đều đúng.
APScheduler timezone="America/New_York" là ET-native, DST tự động.

Usage:
    cd d:\\raits
    python -m global_index.run_scheduler [--port 4002] [--dry-run]
    # Để background (Windows):
    pythonw -m global_index.run_scheduler --port 4002

Requirements:
    pip install apscheduler>=3.10
"""
from __future__ import annotations
import argparse
import logging
import subprocess
import sys
from pathlib import Path

_CWD = Path(__file__).parents[1]   # d:\raits
if not (_CWD / "global_index").is_dir() or not (_CWD / "futures").is_dir():
    sys.stderr.write(f"CWD guard FAIL — run from d:\\raits: {_CWD}\n")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_scheduler")


def _run(args: list[str], label: str, dry_run: bool) -> None:
    log.info("[%s] %s", label, " ".join(args))
    if dry_run:
        log.info("[%s] dry-run — command NOT executed", label)
        return
    result = subprocess.run(args, cwd=str(_CWD))
    if result.returncode != 0:
        log.error("[%s] exited with code %d", label, result.returncode)
    else:
        log.info("[%s] completed OK", label)


def make_scheduler(port: int, dry_run: bool,
                   data_dir: str = "data/cache/futures",
                   nkd_parquet: str = "global_index/data/NKD_continuous_1m_8y.parquet",
                   regime_csv: str = "spy_daily_live.csv"):
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        sys.exit("apscheduler not installed: pip install apscheduler>=3.10")

    sched = BlockingScheduler(timezone="America/New_York")   # ET-native

    # ── 09:31 ET Mon-Fri: MAX_HOLD exit at RTH open ──────────────────────────
    @sched.scheduled_job("cron", day_of_week="mon-fri", hour=9, minute=31,
                         id="maxhold_exit", name="MAX_HOLD exit 09:31 ET")
    def job_maxhold():
        _run([sys.executable, "-m", "global_index.run_maxhold_exit",
              "--positions-path", "live_positions.json",
              "--port", str(port)],
             label="MAX_HOLD_EXIT", dry_run=dry_run)

    # ── 14:05 ET Mon-Fri: daily signal run ───────────────────────────────────
    @sched.scheduled_job("cron", day_of_week="mon-fri", hour=14, minute=5,
                         id="live_day", name="Daily run 14:05 ET")
    def job_live_day():
        _run([sys.executable, "-m", "global_index.run_live_day",
              "--data-dir",     data_dir,
              "--nkd-parquet",  nkd_parquet,
              "--regime-csv",   regime_csv,
              "--port",         str(port)],
             label="LIVE_DAY", dry_run=dry_run)

    return sched


def main():
    ap = argparse.ArgumentParser(description="TZ-independent APScheduler cron for RAITS")
    ap.add_argument("--port",        type=int, default=4002,
                    help="IB Gateway port (default: 4002 paper)")
    ap.add_argument("--dry-run",     action="store_true",
                    help="Log jobs but do not execute commands")
    ap.add_argument("--data-dir",    default="data/cache/futures",
                    help="Parquet data directory (default: data/cache/futures)")
    ap.add_argument("--nkd-parquet", default="global_index/data/NKD_continuous_1m_8y.parquet",
                    help="NKD parquet path")
    ap.add_argument("--regime-csv",  default="spy_daily_live.csv",
                    help="SPY regime CSV (default: spy_daily_live.csv)")
    a = ap.parse_args()

    sched = make_scheduler(port=a.port, dry_run=a.dry_run,
                           data_dir=a.data_dir, nkd_parquet=a.nkd_parquet,
                           regime_csv=a.regime_csv)

    jobs = sched.get_jobs()
    log.info("Scheduler TZ: America/New_York (ET-native, DST auto)")
    log.info("Machine TZ: %s", __import__("time").tzname)
    log.info("Port: %d  dry-run: %s", a.port, a.dry_run)
    for j in jobs:
        _next = getattr(j, "next_run_time", "(start scheduler to compute)")
        log.info("  job %-20s  next: %s", j.id, _next)

    log.info("Scheduler started. Ctrl-C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
