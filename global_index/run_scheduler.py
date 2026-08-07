"""
global_index/run_scheduler.py — TZ-independent APScheduler cron
===============================================================
Thay thế Windows Task Scheduler thủ công. Chạy 24/7 (process hoặc Windows
Service), tự convert ET↔machine-TZ và tự handle US DST.

Jobs mỗi ngày Mon-Fri (thứ tự):
  09:31 ET → run_maxhold_exit    (MAX_HOLD close at RTH open)
  13:45 ET → PRE-FLIGHT          (update_ibkr_daily → update_spy_csv, blocking)
  14:05 ET → run_live_day        (initial signal run — xem continuous runner bên dưới)
  14:10 ET  ┐
  14:15 ET  │ Continuous runner — TF entry capture (xem lý do bên dưới)
  ...        │ Mỗi 5 phút đến 15:55 ET (22 slots)
  15:55 ET  ┘

── Continuous runner (14:10–15:55) — lý do tồn tại ─────────────────────────
  backtest_swing_tf() cần ≥2 bars trong window 14:00–15:55 ET để generate signal
  (loop: for n in range(1, len(idx))). Tại 14:05 ET, IBKR chỉ trả bars đến
  ~14:04 → resample_5m cho 1 bar → 0 iterations → desired_position() = None
  → 0% same-day TF entry capture tại slot đầu tiên.

  Nếu chỉ fire 1 lần lúc 14:05, TF entries chỉ được execute qua rollover path
  (force_entries, D+1 14:05) với slippage overnight thực tế: median $14, std $276
  — gấp 10–30× so với 2-tick assumption trong backtest.

  Chạy mỗi 5 phút giải quyết: signal được generate trong vòng 5 phút sau khi
  resume bar đóng (same-day, same-guard passes), slippage ≈ 2-tick assumption.

  STATE model (diff_desired_vs_held) idempotent: position đã held → cur ≠ None
  → skip re-entry. Mỗi run là run-and-exit process riêng → không có concurrency.

  Đo lường (check_resumebar_timing.py, 2017 trades, 4 instruments):
    Single fire 14:05 → 0%  |  +14:10 → 22%  |  +14:30 → 50%  |  +15:55 → 100%

── Pre-flight fail-safe ─────────────────────────────────────────────────────
  Nếu update_ibkr_daily hoặc update_spy_csv thất bại (Gateway rớt, guard abort,
  API key thiếu), TẤT CẢ slots 14:05–15:55 bị SKIP ngày đó — không trade trên
  data stale. Flag _preflight_ok[date] chỉ set True khi cả hai bước thành công.

Machine TZ-independent: VN (UTC+7), MST (UTC-7), ET, cloud — đều đúng.
APScheduler timezone="America/New_York" là ET-native, DST tự động.

Polygon API key cho update_spy_csv:
  Truyền qua --polygon-api-key hoặc env var POLYGON_API_KEY.
  Nếu thiếu → update_spy_csv fail (returncode 1) → pre-flight fail → tất cả skip.

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
import json
import logging
import os
import subprocess
import sys
import threading
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
_LOG_FILE = _CWD / f"scheduler_{__import__('datetime').date.today().strftime('%m%d')}.log"
class HeartbeatNoiseFilter(logging.Filter):
    """Drop APScheduler's dispatch chatter for the heartbeat job only.

    APScheduler logs every dispatch at INFO, so one beat a minute is 2880 lines a day
    of "Heartbeat 60s ... executed successfully". Measured at 22% of the log within
    hours of switching it on, with the slot events sandwiched between them. A log
    nobody reads is the condition that let the original stall run three nights, so a
    watchdog that buries the log defeats its own purpose.

    Only the dispatch lines go. The hourly "[HEARTBEAT] alive" beat and the STALLED
    warning come from run_scheduler's own logger and carry no job repr, so they pass.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "Heartbeat 60s" not in record.getMessage()


_fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.INFO)
_fh.addFilter(HeartbeatNoiseFilter())
_fh.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.getLogger().addHandler(_fh)
log = logging.getLogger("run_scheduler")
log.info("Log file: %s", _LOG_FILE)

# Pre-flight state: keyed by date string (e.g. "2026-07-14").
# Set True only when BOTH update_ibkr_daily AND update_spy_csv succeed.
# flag missing (None) or False → always skip (fail-closed, no data-freshness guess).
#
# Persisted to disk. It used to be in-memory only, which was survivable while every
# consumer ran at 14:05-15:55 ET — the same process lifetime as the 13:45 pre-flight.
# The NKD night slots (01:10-02:55 ET) read the PREVIOUS business day's flag, so a
# memory-only dict would be empty at every scheduler restart and the night slots would
# fail-closed forever — a feature that looks wired but can never fire.
#
# Persisting is a record of something that happened, not a guess: entries stay keyed
# by date, so a stale file cannot authorise a day it does not name.
_preflight_ok: dict = {}
_PREFLIGHT_STATE = Path("global_index/preflight_state.json")
_PREFLIGHT_KEEP = 7          # days retained; keeps the file from growing without bound
_FAIL_TAIL_LINES = 25        # child output echoed on failure — enough for the traceback

# Serialises run_live_day across ALL slots — see _live_day_body. BlockingScheduler
# dispatches jobs on a thread pool, so a threading.Lock is the right primitive.
_slot_lock = threading.Lock()

# ── Heartbeat: cap the wait, and measure the stall ────────────────────────────
#
# BlockingScheduler._main_loop does Event.wait(seconds_until_next_job). On Windows that
# timeout counts on a clock that does NOT advance while the machine sleeps, so every
# second asleep pushes the deadline back a second — long after the machine is awake.
#
# Measured 2026-08-06. Night of 04→05: 1:27:37 of sleep, predicted wake 23:10:00 +
# 1:27:37 = 00:37:37, APScheduler actually ran at 00:37:22 — 15s out. Night of 05→06:
# 2:51:27 + 0:42:21 of sleep pushed the 23:10 deadline to 02:43, past the end of the
# NKD window at 00:55. Nothing ran and NOTHING WAS LOGGED: no misfire, no error, the
# process idle and healthy. The night window degraded 22 slots → 4 → 0 over three
# nights before anyone looked.
#
# A job every minute bounds that wait to 60s, so after a resume the scheduler
# re-evaluates within a minute rather than hours. The beat also times ITSELF on the
# wall clock, which does advance during sleep, so the gap between beats is the stall —
# reported as a number instead of as silence.
#
# This does not make jobs run while the machine is asleep. Nothing can. Keep the box
# awake (powercfg SUB_SLEEP STANDBYIDLE 0) — this only stops one sleep from disabling
# every later job.
HEARTBEAT_SECS = 60
_HEARTBEAT_TOLERANCE = 30    # cron drift + a slow beat; below this it is not a stall
_last_beat: dict = {"t": None}

# How late a slot may be and still be worth running. APScheduler's default is 1 second,
# which silently drops any slot that arrives even slightly behind — the state the night
# window was in. Slots are 5 minutes apart and diff_desired_vs_held is idempotent, so a
# slot a few minutes late does what the missed one would have. Past that the next slot
# has already covered it, and firing a slot whose window has closed is worse than
# skipping: an NKD entry would land hours from its signal bar.
SLOT_MISFIRE_GRACE_SECS = 300


def heartbeat_gap(prev, now) -> "float | None":
    """Seconds lost since the previous beat, or None if the beat arrived on time.

    prev is None on the first beat — nothing to compare against yet.
    """
    if prev is None:
        return None
    gap = (now - prev).total_seconds()
    if gap <= HEARTBEAT_SECS + _HEARTBEAT_TOLERANCE:
        return None
    return gap

# Slots whose fail-closed skip has already been reported, keyed by (date, slot).
# Keeps the "no pre-flight record" banner loud once and quiet afterwards.
_skip_warned: set = set()


def _et_today():
    """ET calendar date — the trading date every job is scheduled against.

    NOT date.today(): that is the machine's local date. APScheduler fires on ET, so
    on any machine west of ET the night slots (01:10-02:55 ET) land on the PREVIOUS
    local date — measured 2026-08-03 on Mountain time, 01:10 ET Aug 4 = 23:10 MDT
    Aug 3, so prev_bday() asked for Jul 31 instead of Aug 3, found no flag and
    skipped the whole window. The day slots never exposed this because 13:45 and
    14:05 ET fall on the same local date in MDT.
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    return _dt.now(ZoneInfo("America/New_York")).date()


def _load_preflight_state() -> None:
    if not _PREFLIGHT_STATE.exists():
        return
    try:
        with open(_PREFLIGHT_STATE, encoding="utf-8") as fh:
            _preflight_ok.update({k: bool(v) for k, v in json.load(fh).items()})
        log.info("[PRE-FLIGHT] restored %d day(s) of state from %s",
                 len(_preflight_ok), _PREFLIGHT_STATE)
    except Exception as exc:
        log.warning("[PRE-FLIGHT] could not read %s (%s) — starting empty (fail-closed)",
                    _PREFLIGHT_STATE, exc)


def _save_preflight_state() -> None:
    """Atomic write: a torn file would read as 'no record' and skip every slot."""
    try:
        keep = dict(sorted(_preflight_ok.items())[-_PREFLIGHT_KEEP:])
        _preflight_ok.clear()
        _preflight_ok.update(keep)
        _PREFLIGHT_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PREFLIGHT_STATE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(keep, fh, indent=2)
        os.replace(tmp, _PREFLIGHT_STATE)
    except Exception as exc:
        log.error("[PRE-FLIGHT] could not persist state to %s: %s — night slots will "
                  "fail-closed after a restart", _PREFLIGHT_STATE, exc)


def _run(args: list[str], label: str, dry_run: bool) -> bool:
    """Run subprocess, return True on success (returncode==0)."""
    log.info("[%s] %s", label, " ".join(args))
    if dry_run:
        log.info("[%s] dry-run — command NOT executed (treating as success)", label)
        return True
    # Capture the child's output so a failure says WHY. Uncaptured, it went to
    # whatever console the scheduler was launched from and was gone: on 2026-08-04
    # the 13:45 pre-flight failed on MES and skipped the entire trading day, and the
    # log held nothing but "exited with code 1". A re-run later succeeded, so the
    # cause is still unknown.
    result = subprocess.run(args, cwd=str(_CWD), capture_output=True,
                            text=True, errors="replace")
    if result.returncode == 0:
        log.info("[%s] completed OK", label)
        return True

    log.error("[%s] exited with code %d", label, result.returncode)
    for stream, name in ((result.stdout, "stdout"), (result.stderr, "stderr")):
        lines = [ln for ln in (stream or "").splitlines() if ln.strip()]
        if not lines:
            continue
        # Tail only — these children print a lot on success and the failure is at
        # the end. Enough to identify the instrument and the exception.
        for ln in lines[-_FAIL_TAIL_LINES:]:
            log.error("[%s] %s: %s", label, name, ln)
    return False


def make_scheduler(port: int, dry_run: bool,
                   data_dir: str = "data/cache/futures",
                   nkd_parquet: str = "global_index/data/NKD_continuous_1m_8y.parquet",
                   regime_csv: str = "spy_daily_live.csv",
                   polygon_api_key: str = "",
                   live_state_path: str = "global_index/live_state_data.js"):
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        sys.exit("apscheduler not installed: pip install apscheduler>=3.10")

    sched = BlockingScheduler(timezone="America/New_York")   # ET-native

    # ── Every minute, all week: bound the wait and measure any stall ─────────
    # Not day_of_week="mon-fri": a stall that starts on Friday evening has to be
    # visible before Monday's first slot, not after it.
    @sched.scheduled_job("cron", minute="*", id="heartbeat", name="Heartbeat 60s")
    def job_heartbeat():
        from datetime import datetime as _dt, timezone as _tz
        now = _dt.now(_tz.utc)
        gap = heartbeat_gap(_last_beat["t"], now)
        _last_beat["t"] = now
        if gap is None:
            # One INFO line an hour, not one a minute. Enough that "the log has been
            # quiet" stops being ambiguous — the state this whole fix exists to remove —
            # without the 2880 lines a day that would make the log unreadable.
            if now.minute == 0:
                log.info("[HEARTBEAT] alive")
            else:
                log.debug("[HEARTBEAT] ok")
            return
        log.warning(
            "[HEARTBEAT] STALLED %.0fs (expected ~%ds). The scheduler's wait timer does "
            "not advance while Windows sleeps, so every job due in that window was "
            "missed and every later one was pushed back by the same amount. Check "
            "Power-Troubleshooter events, and keep the machine awake "
            "(powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0).",
            gap, HEARTBEAT_SECS,
        )

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
        today = _et_today().isoformat()
        log.info("[PRE-FLIGHT] Starting: update_ibkr_daily -> update_spy_csv (%s)", today)

        ibkr_ok = _run(
            [sys.executable, "-m", "global_index.update_ibkr_daily", "--port", str(port)],
            label="IBKR_UPDATE", dry_run=dry_run,
        )
        if not ibkr_ok:
            _preflight_ok[today] = False
            _save_preflight_state()
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
            _save_preflight_state()
            log.error(
                "[PRE-FLIGHT] update_spy_csv FAILED — "
                "run_live_day WILL BE SKIPPED today (%s). Check POLYGON_API_KEY.",
                today,
            )
            return

        _preflight_ok[today] = True
        _save_preflight_state()
        log.info("[PRE-FLIGHT] OK — parquet + spy CSV fresh. run_live_day cleared for 14:05.")

    def _prev_bday(d):
        """Previous weekday. Night NKD slots run before their own day's pre-flight."""
        from datetime import timedelta as _td
        x = d - _td(days=1)
        while x.weekday() >= 5:      # 5=Sat 6=Sun
            x -= _td(days=1)
        return x

    def _live_day_body(slot_id: str, *, first_slot: bool = False,
                       clusters: str = "all", prev_preflight: bool = False) -> None:
        """Serialise slots: never two run_live_day processes at once.

        Slots are 5 minutes apart and a run takes ~5.5 (measured 2026-08-03:
        connect 12:35:16 → disconnect 12:40:44), so firings overlap. Both children
        connect on clientId=1 and collide at IBKR — the P0C_1440/1450 failures.

        max_instances would not help: APScheduler applies it per job id, and each
        slot is its own job. A scheduler-process mutex covers every slot, day and
        night, and any slot added later.

        Skipping is the correct outcome, not a loss. diff_desired_vs_held is
        idempotent — a held position yields cur != None and no re-entry — so the
        next slot does whatever this one would have.
        """
        if not _slot_lock.acquire(blocking=False):
            log.warning("[%s] SKIPPED — previous run_live_day still in flight. "
                        "Slots are 5 min apart, a run takes ~5.5 min; overlapping "
                        "children collide on IBKR clientId. Next slot picks it up.",
                        slot_id)
            return
        try:
            _live_day_body_inner(slot_id, first_slot=first_slot,
                                 clusters=clusters, prev_preflight=prev_preflight)
        finally:
            _slot_lock.release()

    # ── Shared runner body (all 14:05–15:55 slots) ───────────────────────────
    def _live_day_body_inner(slot_id: str, *, first_slot: bool = False,
                             clusters: str = "all", prev_preflight: bool = False) -> None:
        """Run run_live_day for one slot, guarded by pre-flight flag.

        first_slot=True (14:05) logs at ERROR on failure; subsequent slots log
        at WARNING/DEBUG to avoid repeating the same alert 22 times.

        clusters: forwarded to run_live_day --clusters. The night NKD slots pass
        "nkd" so Rổ 4 positions are marked unchanged rather than exited.

        prev_preflight: the night slots (01:10-02:55 ET) run BEFORE that day's own
        13:45 ET pre-flight, so today's flag is always None and fail-closed would
        skip them forever. They check the previous business day's pre-flight instead
        — that run (13:45 ET the day before, ~11h earlier) is the freshest data
        update that exists at 01:10 ET, and run_live_day fetches live IBKR bars on
        top of it anyway.
        """
        _t = _et_today()
        today = (_prev_bday(_t) if prev_preflight else _t).isoformat()
        flag = _preflight_ok.get(today)

        if flag is True:
            pass  # pre-flight succeeded in this process lifetime

        elif flag is False:
            # Pre-flight ran and explicitly failed. Only the first slot errors;
            # subsequent slots warn (operator already saw the 14:05 ERROR).
            if first_slot:
                log.error(
                    "[%s] SKIPPED — pre-flight ran but FAILED for %s. "
                    "Fix Gateway / API key and run update_ibkr_daily manually to recover.",
                    slot_id, today,
                )
            else:
                log.warning("[%s] SKIPPED — pre-flight failed for %s.", slot_id, today)
            return

        else:
            # flag is None: no pre-flight record (scheduler restart or missed 13:45).
            # Cannot verify ibkr_daily + spy_csv are both fresh. Fail-closed.
            # Recover: restart scheduler before 13:45, OR run updates manually.
            #
            # Loud once per (date, slot family), quiet after. This branch used to log
            # at DEBUG for every non-first slot, and logging is configured at INFO —
            # so on 2026-08-03 the entire NKD night window was skipped without
            # emitting a single line. A window that trades nothing must say so.
            _fam = slot_id.rsplit("_", 1)[0]          # LIVE_DAY / NKD_NIGHT
            if first_slot or (today, _fam) not in _skip_warned:
                _skip_warned.add((today, _fam))
                log.error(
                    "[%s] SKIPPED — no pre-flight record for %s "
                    "(scheduler restart or missed 13:45 job). "
                    "Cannot confirm ibkr_daily + spy_csv both fresh. "
                    "Restart scheduler before 13:45 or run updates manually. "
                    "Further %s slots today will log this at DEBUG only.",
                    slot_id, today, _fam,
                )
            else:
                log.debug("[%s] SKIPPED — no pre-flight record for %s.", slot_id, today)
            return

        _run([sys.executable, "-m", "global_index.run_live_day",
              "--data-dir",        data_dir,
              "--nkd-parquet",     nkd_parquet,
              "--regime-csv",      regime_csv,
              "--live-state-path", live_state_path,
              "--clusters",        clusters,
              "--port",            str(port)],
             label=slot_id, dry_run=dry_run)

    # ── 14:05 ET Mon-Fri: initial signal run ─────────────────────────────────
    @sched.scheduled_job("cron", day_of_week="mon-fri", hour=14, minute=5,
                         id="live_day", name="Daily run 14:05 ET",
                         misfire_grace_time=SLOT_MISFIRE_GRACE_SECS)
    def job_live_day():
        _live_day_body("LIVE_DAY_1405", first_slot=True)

    # ── 14:10–15:55 ET Mon-Fri: continuous runner (every 5 min) ──────────────
    # See module docstring for full rationale.
    # Capture rate: 14:10→22%, 14:30→50%, 15:55→100% (vs 0% at 14:05 alone).
    _CONT_SLOTS = (
        [(14, m) for m in range(10, 60, 5)] +   # 14:10 → 14:55 (10 slots)
        [(15, m) for m in range(0,  60, 5)]      # 15:00 → 15:55 (12 slots)
    )
    for _h, _m in _CONT_SLOTS:
        _slot_id = f"LIVE_DAY_{_h:02d}{_m:02d}"
        sched.add_job(
            lambda sid=_slot_id: _live_day_body(sid),
            "cron", day_of_week="mon-fri", hour=_h, minute=_m,
            id=_slot_id.lower(),
            name=f"Continuous run {_h:02d}:{_m:02d} ET",
            misfire_grace_time=SLOT_MISFIRE_GRACE_SECS,
        )

    # ── 01:10–02:55 ET Mon-Fri: NKD night slots ──────────────────────────────
    # NKD's entry window is between_time("14:00","15:55") on its session clock,
    # and specs.MNKD.session_tz is Asia/Tokyo → 14:00-15:55 JST = 01:00-02:55 ET.
    # The 14:05-15:55 ET slots see that window only after it has been closed for
    # ~11 hours, so an NKD entry there fills 11h away from its signal bar. For
    # scale: the Option C audit measured -$9,112 (-20.2%) from a 13-105 minute gap.
    #
    # Start at 01:10, not 01:00 — backtest_swing_tf needs >=2 bars inside the
    # window, exactly why Rổ 4 starts at 14:10 rather than 14:05.
    #
    # --clusters nkd: Rổ 4 positions are marked unchanged, never exited. Without
    # it, every night slot would close them (signal_layer.py:110-112).
    # The 14:05-15:55 slots keep NKD active so its exits still run during the day.
    _NKD_SLOTS = ([(1, m) for m in range(10, 60, 5)] +    # 01:10 → 01:55
                  [(2, m) for m in range(0,  60, 5)])      # 02:00 → 02:55
    for _h, _m in _NKD_SLOTS:
        _slot_id = f"NKD_NIGHT_{_h:02d}{_m:02d}"
        sched.add_job(
            lambda sid=_slot_id: _live_day_body(sid, clusters="nkd",
                                                prev_preflight=True),
            "cron", day_of_week="mon-fri", hour=_h, minute=_m,
            id=_slot_id.lower(),
            name=f"NKD night run {_h:02d}:{_m:02d} ET",
            misfire_grace_time=SLOT_MISFIRE_GRACE_SECS,
        )

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
    ap.add_argument("--live-state-path",  default="global_index/live_state_data.js",
                    help="Path to write live_state_data.js for dashboard (default: global_index/live_state_data.js)")
    ap.add_argument("--assume-preflight-ok", action="store_true",
                    help="Mark today's pre-flight as passed on startup (use after manual update_ibkr_daily + update_spy_csv)")
    a = ap.parse_args()

    if not a.polygon_api_key:
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location("config_private", _CWD / "config_private.py")
            _cp = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_cp)
            a.polygon_api_key = getattr(_cp, "POLYGON_API_KEY", "")
            if a.polygon_api_key:
                log.info("Polygon API key loaded from config_private.py")
        except Exception as _e:
            log.warning("Could not load POLYGON_API_KEY from config_private.py: %s", _e)

    # Restore persisted pre-flight state BEFORE any flag is set, so a restart does
    # not blank out yesterday's record — the NKD night slots read it.
    _load_preflight_state()

    if a.assume_preflight_ok:
        from datetime import date as _d
        _preflight_ok[_et_today().isoformat()] = True
        _save_preflight_state()
        log.warning("--assume-preflight-ok: pre-flight flag set for ET date %s — skipping 13:45 gate", _et_today())

    sched = make_scheduler(
        port=a.port, dry_run=a.dry_run,
        data_dir=a.data_dir, nkd_parquet=a.nkd_parquet,
        regime_csv=a.regime_csv, polygon_api_key=a.polygon_api_key,
        live_state_path=a.live_state_path,
    )

    jobs = sched.get_jobs()
    log.info("Scheduler TZ: America/New_York (ET-native, DST auto)")
    log.info("Machine TZ:  %s", __import__("time").tzname)
    log.info("Port: %d  dry-run: %s", a.port, a.dry_run)
    log.info("Jobs (%d):", len(jobs))
    for j in jobs:
        _next = getattr(j, "next_run_time", "(start scheduler to compute)")
        log.info("  %-20s  next: %s", j.id, _next)
    log.info("Pre-flight fail-safe: update fail -> live_day skipped (no stale-data trades)")
    log.info("Scheduler started. Ctrl-C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
