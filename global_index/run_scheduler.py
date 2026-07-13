"""
global_index/run_scheduler.py — TZ-independent APScheduler cron
===============================================================
Thay thế Windows Task Scheduler thủ công. Chạy 24/7 (process hoặc Windows
Service), tự convert ET↔machine-TZ và tự handle US DST.

Ba jobs (thứ tự mỗi ngày Mon-Fri):
  09:31 ET → run_maxhold_exit    (MAX_HOLD close at RTH open)
  13:45 ET → PRE-FLIGHT          (update_ibkr_daily → update_spy_csv, blocking)
  14:05 ET → run_live_day        (daily signal + entry/exit, CHỈ nếu pre-flight OK)

Pre-flight fail-safe:
  Nếu update_ibkr_daily hoặc update_spy_csv thất bại (Gateway rớt, guard abort,
  API key thiếu), run_live_day bị SKIP ngày đó — không trade trên data stale.
  Flag _preflight_ok[date] chỉ set True khi cả hai bước thành công.

Machine TZ-independent: VN (UTC+7), MST (UTC-7), ET, cloud — đều đúng.
APScheduler timezone="America/New_York" là ET-native, DST tự động.

Polygon API key cho update_spy_csv:
  Truyền qua --polygon-api-key hoặc env var POLYGON_API_KEY.
  Nếu thiếu → update_spy_csv fail (returncode 1) → pre-flight fail → live_day skip.

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
import os
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

# Pre-flight state: keyed by date string (e.g. "2026-07-14").
# Set True only when BOTH update_ibkr_daily AND update_spy_csv succeed.
# WARNING: in-memory only — lost on scheduler restart. job_live_day uses 3-branch
# logic: flag=True → proceed; flag=False → skip (definitive); flag missing →
# fall back to parquet freshness check (source of truth, survives restart).
_preflight_ok: dict = {}


def _parquet_is_fresh(data_dir: str) -> tuple[bool, str]:
    """
    Check whether the MES parquet has bars from today (ET date).
    Returns (is_fresh, reason_msg).

    Use as fallback when _preflight_ok flag is absent (scheduler restarted
    between 13:45 and 14:05). Parquet persists across restarts; flag does not.
    """
    import pandas as pd
    from datetime import date as _date
    today_et = _date.today()
    p = _CWD / data_dir / "ES_continuous_1m_8y.parquet"
    if not p.exists():
        return False, f"MES parquet not found: {p}"
    df = pd.read_parquet(p, columns=["close"])
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    last_bar = df.index[-1]
    if last_bar.date() < today_et:
        return False, f"MES last bar {last_bar} is from {last_bar.date()}, not today {today_et} — data stale"
    return True, f"MES last bar {last_bar} ✓"


def _run(args: list[str], label: str, dry_run: bool) -> bool:
    """Run subprocess, return True on success (returncode==0)."""
    log.info("[%s] %s", label, " ".join(args))
    if dry_run:
        log.info("[%s] dry-run — command NOT executed (treating as success)", label)
        return True
    result = subprocess.run(args, cwd=str(_CWD))
    if result.returncode == 0:
        log.info("[%s] completed OK", label)
        return True
    log.error("[%s] exited with code %d", label, result.returncode)
    return False


def make_scheduler(port: int, dry_run: bool,
                   data_dir: str = "data/cache/futures",
                   nkd_parquet: str = "global_index/data/NKD_continuous_1m_8y.parquet",
                   regime_csv: str = "spy_daily_live.csv",
                   polygon_api_key: str = ""):
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

    # ── 13:45 ET Mon-Fri: pre-flight (update parquet + spy CSV) ─────────────
    # Runs BEFORE 14:05 run_live_day. Typical duration: ~20s for 5 instruments.
    # 20-min margin is sufficient. Fail-safe: any failure → live_day skipped today.
    @sched.scheduled_job("cron", day_of_week="mon-fri", hour=13, minute=45,
                         id="preflight", name="Pre-flight update 13:45 ET")
    def job_preflight():
        from datetime import date as _date
        today = _date.today().isoformat()
        log.info("[PRE-FLIGHT] Starting: update_ibkr_daily → update_spy_csv (%s)", today)

        ibkr_ok = _run(
            [sys.executable, "-m", "global_index.update_ibkr_daily", "--port", str(port)],
            label="IBKR_UPDATE", dry_run=dry_run,
        )
        if not ibkr_ok:
            _preflight_ok[today] = False
            log.error(
                "[PRE-FLIGHT] update_ibkr_daily FAILED — "
                "run_live_day WILL BE SKIPPED today (%s). Fix Gateway and re-run manually if needed.",
                today,
            )
            return

        spy_cmd = [sys.executable, "-m", "global_index.update_spy_csv", "--csv", regime_csv]
        if polygon_api_key:
            spy_cmd += ["--api-key", polygon_api_key]
        spy_ok = _run(spy_cmd, label="SPY_UPDATE", dry_run=dry_run)
        if not spy_ok:
            _preflight_ok[today] = False
            log.error(
                "[PRE-FLIGHT] update_spy_csv FAILED — "
                "run_live_day WILL BE SKIPPED today (%s). Check POLYGON_API_KEY.",
                today,
            )
            return

        _preflight_ok[today] = True
        log.info("[PRE-FLIGHT] OK — parquet + spy CSV fresh. run_live_day cleared for 14:05.")

    # ── 14:05 ET Mon-Fri: daily signal run (only if pre-flight OK) ───────────
    @sched.scheduled_job("cron", day_of_week="mon-fri", hour=14, minute=5,
                         id="live_day", name="Daily run 14:05 ET")
    def job_live_day():
        from datetime import date as _date
        today = _date.today().isoformat()
        flag = _preflight_ok.get(today)   # True / False / None (missing)

        if flag is True:
            # Normal path: pre-flight ran and succeeded in this process.
            pass

        elif flag is False:
            # Pre-flight ran and explicitly failed (Gateway down, guard abort, etc.).
            # Definitive failure — do not trade on stale data.
            log.error(
                "[LIVE_DAY] SKIPPED — pre-flight ran but FAILED for %s. "
                "Fix Gateway / API key and run update_ibkr_daily manually to recover.",
                today,
            )
            return

        else:
            # flag is None: pre-flight job never ran in this process (scheduler
            # restarted between 13:45 and 14:05, or started after 13:45).
            # Fall back to parquet freshness — the source of truth that survives restart.
            fresh, reason = _parquet_is_fresh(data_dir)
            if fresh:
                log.warning(
                    "[LIVE_DAY] pre-flight flag missing for %s (scheduler restart?). "
                    "Parquet freshness check: %s — proceeding.",
                    today, reason,
                )
            else:
                log.error(
                    "[LIVE_DAY] SKIPPED — pre-flight flag missing AND parquet stale for %s. "
                    "Reason: %s. Run update_ibkr_daily manually to recover.",
                    today, reason,
                )
                return

        _run([sys.executable, "-m", "global_index.run_live_day",
              "--data-dir",     data_dir,
              "--nkd-parquet",  nkd_parquet,
              "--regime-csv",   regime_csv,
              "--port",         str(port)],
             label="LIVE_DAY", dry_run=dry_run)

    return sched


def main():
    ap = argparse.ArgumentParser(description="TZ-independent APScheduler cron for RAITS")
    ap.add_argument("--port",             type=int, default=4002,
                    help="IB Gateway port (default: 4002 paper)")
    ap.add_argument("--dry-run",          action="store_true",
                    help="Log jobs but do not execute commands (pre-flight treated as success)")
    ap.add_argument("--data-dir",         default="data/cache/futures",
                    help="Parquet data directory (default: data/cache/futures)")
    ap.add_argument("--nkd-parquet",      default="global_index/data/NKD_continuous_1m_8y.parquet",
                    help="NKD parquet path")
    ap.add_argument("--regime-csv",       default="spy_daily_live.csv",
                    help="SPY regime CSV (default: spy_daily_live.csv)")
    ap.add_argument("--polygon-api-key",  default=os.environ.get("POLYGON_API_KEY", ""),
                    help="Polygon.io API key for update_spy_csv "
                         "(fallback: POLYGON_API_KEY env var)")
    a = ap.parse_args()

    sched = make_scheduler(
        port=a.port, dry_run=a.dry_run,
        data_dir=a.data_dir, nkd_parquet=a.nkd_parquet,
        regime_csv=a.regime_csv, polygon_api_key=a.polygon_api_key,
    )

    jobs = sched.get_jobs()
    log.info("Scheduler TZ: America/New_York (ET-native, DST auto)")
    log.info("Machine TZ:  %s", __import__("time").tzname)
    log.info("Port: %d  dry-run: %s", a.port, a.dry_run)
    log.info("Jobs (%d):", len(jobs))
    for j in jobs:
        _next = getattr(j, "next_run_time", "(start scheduler to compute)")
        log.info("  %-20s  next: %s", j.id, _next)
    log.info("Pre-flight fail-safe: update fail → live_day skipped (no stale-data trades)")
    log.info("Scheduler started. Ctrl-C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
