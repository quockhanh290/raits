"""
p0c_overnight.py — P0c overnight runner (Vietnam timezone)
===========================================================
Chạy --print-signals mỗi 5 phút trong TF window 14:05-15:55 ET,
save output ra file p0c_signals_MMDD.txt để kiểm tra sáng hôm sau.

Schedule (ET / VN+7):
  13:45 ET / 00:45 VN → pre-flight (update_ibkr_daily + update_spy_csv)
  14:05–15:55 ET / 01:05–02:55 VN → --print-signals mỗi 5 phút

Usage:
    cd d:\\raits
    python p0c_overnight.py --port 4002 --polygon-api-key <key>
    # Chạy xong → Ctrl+C để stop (hoặc tự exit sau 15:55 ET)
"""
from __future__ import annotations
import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_CWD = Path(__file__).parent
OUT_FILE = _CWD / f"p0c_signals_{datetime.now().strftime('%m%d')}.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("p0c_overnight")

# Load Polygon key từ config_private.py nếu chưa có trong OS env
if not os.environ.get("POLYGON_API_KEY"):
    try:
        sys.path.insert(0, str(_CWD))
        import config_private  # type: ignore
        os.environ["POLYGON_API_KEY"] = str(config_private.POLYGON_API_KEY)
        log.info("POLYGON_API_KEY loaded from config_private.py")
    except Exception as _e:
        log.warning("config_private.py not found or missing POLYGON_API_KEY: %s", _e)

_preflight_ok = {}


def _run_capture(args: list[str], label: str) -> str:
    """Run subprocess, return stdout+stderr as string."""
    log.info("[%s] %s", label, " ".join(args))
    result = subprocess.run(args, cwd=str(_CWD), capture_output=True, text=True)
    out = result.stdout + result.stderr
    if result.returncode == 0:
        log.info("[%s] OK", label)
    else:
        log.error("[%s] exit=%d", label, result.returncode)
    return out


def _run(args: list[str], label: str) -> bool:
    log.info("[%s] %s", label, " ".join(args))
    result = subprocess.run(args, cwd=str(_CWD))
    ok = result.returncode == 0
    log.info("[%s] %s", label, "OK" if ok else f"FAILED exit={result.returncode}")
    return ok


def job_preflight(port: int, polygon_api_key: str, regime_csv: str) -> None:
    from datetime import date
    today = date.today().isoformat()
    log.info("[PRE-FLIGHT] Starting for %s", today)

    ibkr_ok = _run(
        [sys.executable, "-m", "global_index.update_ibkr_daily", "--port", str(port)],
        label="IBKR_UPDATE",
    )
    if not ibkr_ok:
        _preflight_ok[today] = False
        log.error("[PRE-FLIGHT] update_ibkr_daily FAILED — print-signals will be SKIPPED today")
        return

    spy_cmd = [sys.executable, "-m", "global_index.update_spy_csv", "--csv", regime_csv]
    if polygon_api_key:
        spy_cmd += ["--api-key", polygon_api_key]
    spy_ok = _run(spy_cmd, label="SPY_UPDATE")
    if not spy_ok:
        _preflight_ok[today] = False
        log.error("[PRE-FLIGHT] update_spy_csv FAILED — print-signals will be SKIPPED today")
        return

    _preflight_ok[today] = True
    log.info("[PRE-FLIGHT] OK — parquet + spy CSV fresh")


_SWING_INSTS = ("MES", "MNQ", "MYM", "M2K")


def _has_swing_entry(output: str) -> bool:
    """True if --print-signals output contains at least one swing TF ENTRY."""
    for line in output.splitlines():
        if "ENTRY" in line and any(inst in line for inst in _SWING_INSTS):
            return True
    return False


def _save_block(slot_id: str, ts: str, content: str) -> None:
    with open(OUT_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"[{slot_id}] {ts}\n")
        f.write(f"{'='*60}\n")
        f.write(content)
        f.write("\n")


def job_print_signals(slot_id: str, port: int,
                      data_dir: str, nkd_parquet: str, regime_csv: str) -> None:
    from datetime import date
    today = date.today().isoformat()

    if not _preflight_ok.get(today):
        log.warning("[%s] SKIPPED — pre-flight not OK for %s", slot_id, today)
        return

    out = _run_capture(
        [sys.executable, "-m", "global_index.run_live_day",
         "--data-dir",    data_dir,
         "--nkd-parquet", nkd_parquet,
         "--regime-csv",  regime_csv,
         "--port",        str(port),
         "--print-signals"],
        label=slot_id,
    )

    _save_block(slot_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), out)
    log.info("[%s] Output saved → %s", slot_id, OUT_FILE.name)

    # Print key lines to console
    for line in out.splitlines():
        if any(k in line for k in ("signal", "entry", "stop", "LONG", "SHORT",
                                    "desired", "regime", "Regime", "None", "ERROR")):
            log.info("[%s] >> %s", slot_id, line.strip())

    # P0c swing verify: if swing ENTRY detected, run p0c_verify_swing.py immediately
    # (must run within seconds of --print-signals to use the same live IBKR bars)
    if _has_swing_entry(out):
        verify_id = f"{slot_id}_VERIFY"
        log.info("[%s] Swing ENTRY detected — running p0c_verify_swing.py now...", verify_id)
        verify_out = _run_capture(
            [sys.executable, "p0c_verify_swing.py",
             "--port",      str(port),
             "--client-id", "92"],
            label=verify_id,
        )
        _save_block(verify_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), verify_out)
        log.info("[%s] Verify output saved → %s", verify_id, OUT_FILE.name)

        # Print comparison result to console
        for line in verify_out.splitlines():
            if any(k in line for k in ("PASS", "FAIL", "MISMATCH", "OK  ",
                                        "ENTRY TODAY", "BLOCKED", "entry_day")):
                log.info("[%s] >> %s", verify_id, line.strip())


def startup_check(port: int, polygon_api_key: str,
                  data_dir: str, nkd_parquet: str, regime_csv: str) -> None:
    """Run before scheduler starts. Fail fast with clear messages instead of
    silently skipping all jobs at 01:xx VN."""
    issues: list[str] = []

    # 1. Polygon key
    if not polygon_api_key:
        issues.append("POLYGON_API_KEY missing — update_spy_csv will fail at pre-flight\n"
                      "       Fix: ensure config_private.py exists in d:\\raits with POLYGON_API_KEY='...'")
    else:
        log.info("[check] Polygon key: OK (len=%d)", len(polygon_api_key))

    # 2. Required files
    for path, desc in [
        (nkd_parquet,        "NKD parquet"),
        (regime_csv,         "spy_daily_live.csv"),
        ("p0c_verify_swing.py", "p0c_verify_swing.py"),
    ]:
        if Path(path).exists():
            log.info("[check] %s: OK", desc)
        else:
            issues.append(f"{desc} not found: {path}")

    # 3. Swing parquets
    try:
        sys.path.insert(0, str(_CWD))
        from futures.basket import BASKET, data_filename  # type: ignore
        for n, c in BASKET.items():
            p = Path(data_dir) / data_filename(c)
            if p.exists():
                log.info("[check] %s parquet: OK", n)
            else:
                issues.append(f"Swing parquet missing: {p}")
    except Exception as e:
        issues.append(f"Cannot import futures.basket: {e}")

    # 4. IBKR port reachable (quick connect/disconnect, client_id=99)
    try:
        from global_index.ibkr_broker import IBKRBroker  # type: ignore
        broker = IBKRBroker(host="127.0.0.1", port=port, client_id=99)
        broker.connect()
        broker.disconnect()
        log.info("[check] IBKR port=%d: OK", port)
    except Exception as e:
        issues.append(f"IBKR port={port} unreachable: {e}\n"
                      f"       Fix: ensure IB Gateway is running on port {port}")

    if issues:
        log.error("=" * 60)
        log.error("STARTUP CHECK FAILED — %d issue(s):", len(issues))
        for i, iss in enumerate(issues, 1):
            log.error("  [%d] %s", i, iss)
        log.error("=" * 60)
        sys.exit("Fix the issues above before starting overnight runner.")

    log.info("[check] All startup checks passed — scheduler starting")


def main():
    ap = argparse.ArgumentParser(description="P0c overnight --print-signals runner")
    ap.add_argument("--port",            type=int, default=4002)
    ap.add_argument("--polygon-api-key", default=os.environ.get("POLYGON_API_KEY", ""))
    ap.add_argument("--data-dir",        default="data/cache/futures")
    ap.add_argument("--nkd-parquet",     default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--regime-csv",      default="spy_daily_live.csv")
    a = ap.parse_args()

    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        sys.exit("apscheduler not installed: pip install apscheduler>=3.10")

    # ── Startup self-check: fail fast before scheduler sleeps until 00:45 VN ──
    startup_check(a.port, a.polygon_api_key, a.data_dir, a.nkd_parquet, a.regime_csv)

    sched = BlockingScheduler(timezone="America/New_York")

    # 13:45 ET: pre-flight
    @sched.scheduled_job("cron", day_of_week="mon-fri", hour=13, minute=45,
                         id="preflight", name="Pre-flight 13:45 ET")
    def _preflight():
        job_preflight(a.port, a.polygon_api_key, a.regime_csv)

    # 14:05–15:55 ET: --print-signals mỗi 5 phút
    _SLOTS = (
        [(14, m) for m in range(5, 60, 5)] +   # 14:05 → 14:55
        [(15, m) for m in range(0, 60, 5)]      # 15:00 → 15:55
    )
    for _h, _m in _SLOTS:
        _sid = f"P0C_{_h:02d}{_m:02d}"
        sched.add_job(
            lambda sid=_sid: job_print_signals(
                sid, a.port, a.data_dir, a.nkd_parquet, a.regime_csv),
            "cron", day_of_week="mon-fri", hour=_h, minute=_m,
            id=_sid.lower(), name=f"print-signals {_h:02d}:{_m:02d} ET",
        )

    log.info("P0c overnight runner started")
    log.info("Output file: %s", OUT_FILE)
    log.info("Pre-flight:  13:45 ET (00:45 VN)")
    log.info("Signals:     14:05–15:55 ET (01:05–02:55 VN), mỗi 5 phút")
    log.info("Ctrl+C để stop")

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Stopped.")


if __name__ == "__main__":
    main()
