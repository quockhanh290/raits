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
import time
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import NamedTuple

_CWD = Path(__file__).parents[1]   # d:\raits
if not (_CWD / "global_index").is_dir() or not (_CWD / "futures").is_dir():
    sys.stderr.write(f"CWD guard FAIL — run from d:\\raits: {_CWD}\n")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_LOG_PREFIX = "scheduler_"


class DailyFileHandler(logging.FileHandler):
    """scheduler_<today>.log, reopened when the calendar day changes.

    The name used to be computed once at import. The scheduler runs for days, so a
    process started 2026-08-09 kept writing 08-10 into scheduler_0809.log: the NKD
    night slots and the 09:31 MAX_HOLD exit were all recorded, under a filename that
    said they belonged to the day before. Nothing was lost, but looking for last
    night's slots in last night's file found an empty one — and "the log is empty"
    is indistinguishable from "the window never ran", which is the exact failure the
    heartbeat exists to catch.

    Rolls on the HOST date, matching the timestamps in the lines themselves. Not the
    ET session date: a file whose name disagrees with its own contents is the thing
    being fixed.
    """

    def __init__(self, directory, prefix: str):
        self._dir = Path(directory)
        self._prefix = prefix
        self._day = _date.today()
        # delay=True: nothing is created until something is actually logged, so an
        # import that never logs leaves no file behind.
        super().__init__(self._path_for(self._day), mode="a",
                         encoding="utf-8", delay=True)

    def _path_for(self, day) -> str:
        return str(self._dir / f"{self._prefix}{day.strftime('%m%d')}.log")

    def emit(self, record: logging.LogRecord) -> None:
        today = _date.today()
        if today != self._day:
            self._day = today
            # Closed by hand rather than self.close(): Handler.close() also drops the
            # handler from logging's shutdown list, so the last lines of the day would
            # not be flushed at exit.
            if self.stream is not None:
                try:
                    self.stream.close()
                finally:
                    self.stream = None
            self.baseFilename = self._path_for(today)
        super().emit(record)


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


log = logging.getLogger("run_scheduler")


def attach_file_log() -> DailyFileHandler:
    """Attach the operator's log file. Called from main(), NOT at import.

    It used to run at import, on the ROOT logger. Every process that imported this
    module therefore redirected the whole application's logging into the operator's
    alert file — including pytest. The 2026-08-10 full-suite run put 1,215 lines into
    scheduler_0810.log, among them CRITICAL "position is UNPROTECTED" and "Roll OPEN
    FAILED ... position is FLAT IN IBKR" from injected-failure fixtures, with not one
    real scheduler line in the file.

    That is the failure this codebase keeps guarding against from the other side: a
    log full of fake CRITICALs teaches the operator to skim past the real one.
    """
    # pytest KHÔNG được ghi vào log production. `run_scheduler`/`run_live_day` gắn handler
    # vào root logger, nên bất kỳ test nào chạy tới đây sẽ đổ log kịch bản vào đúng file mà
    # người vận hành đọc — ngày 2026-08-10 file chứa vị thế MES không ai giữ, id `stp-xyz`,
    # `_RecordingMockBroker`, ngày 2024-06-17. Đọc lướt tưởng hệ thống hỏng nặng.
    #
    # Lọc lúc đọc chỉ bắt được cái đã thấy. Chặn ở đây là dứt điểm và đúng chỗ: một dòng log
    # kịch bản không có lý do gì tồn tại trong file production.
    import os
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None

    fh = DailyFileHandler(_CWD, _LOG_PREFIX)
    fh.setLevel(logging.INFO)
    fh.addFilter(HeartbeatNoiseFilter())
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(fh)
    log.info("Log file: %s (rolls at midnight)", fh.baseFilename)
    return fh

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

# Which days the 09:31 MAX_HOLD exit actually ran, so a scheduler started later can
# tell "already done" from "never happened".
#
# APScheduler computes the next fire time at startup: start at 09:43 and today's
# 09:31 is not late, it does not exist. No misfire, no error, nothing logged.
# That happened on 2026-08-05 (started 09:43) and 2026-08-06 (10:35). Neither cost
# anything only because no position had reached 5 days yet.
#
# It matters more than the silence suggests: MAX_HOLD exits are 15% of trades and
# average +$398.60 while chandelier exits are 79.5% and average -$48.84 — the whole
# edge leaves through this job. Backtest exits it at the 09:30 ET bar (INVARIANTS,
# the fix that moved baseline $41,266 → $40,919); missing the slot pushes the real
# exit to ~14:10 via run_live_day, 4h40 later than the convention every recorded
# number was produced under.
_maxhold_done: dict = {}
_MAXHOLD_STATE = Path("global_index/maxhold_state.json")
_PREFLIGHT_KEEP = 7          # days retained; keeps the file from growing without bound
_FAIL_TAIL_LINES = 25        # child output echoed on failure — enough for the traceback

# Serialises run_live_day across ALL slots — see _live_day_body. BlockingScheduler
# dispatches jobs on a thread pool, so a threading.Lock is the right primitive.
_slot_lock = threading.Lock()

# When the current holder took the lock, monotonic. A one-element list rather than a
# module global so the closure that sets it needs no `global` declaration; None when the
# lock is free. Read only for reporting, never to decide anything.
_slot_started_at: list = [None]

# Wall-clock ceiling for one child process — see _run. A normal run_live_day is ~5.5 min
# and the two slots that also run a full shadow replay add ~5 more, so ~11 min is
# legitimate; this is roughly double that.
_SLOT_TIMEOUT_SECS = 20 * 60

# Longer than this and the mutex holder is not overlapping, it is stuck. Set above the
# subprocess ceiling on purpose: below it, a run that is about to be killed anyway would
# be reported as a dead session first, and the two messages would fight.
_INFLIGHT_STUCK_SECS = _SLOT_TIMEOUT_SECS + 5 * 60


def _run_guarded(slot_id: str, body) -> bool:
    """Run `body` holding the slot mutex. True if it ran, False if the slot was skipped.

    Module-level so the suite can drive the real guard. test_slot_overlap used to cover
    this through a "minimal stand-in… with the same semantics" — a second copy, which
    can only confirm that the copy behaves like itself; changing this function would not
    have turned it red. Same family as test_rollover asking the roll table with a key
    production never passes, which is how C1 survived a green suite.

    Skipping is the correct outcome, not a loss: diff_desired_vs_held is idempotent, so
    the next slot does whatever this one would have.
    """
    if not _slot_lock.acquire(blocking=False):
        # H5: say HOW LONG. Without it "still in flight" reads the same after 90
        # seconds and after an hour, and the second one means the session is dead.
        _since = _slot_started_at[0]
        _elapsed = (time.monotonic() - _since) if _since else 0.0
        _rep = _inflight_report(_elapsed)
        getattr(log, _rep.level)("[%s] %s", slot_id, _rep.message)
        return False
    _slot_started_at[0] = time.monotonic()
    try:
        body()
        return True
    finally:
        _slot_started_at[0] = None
        _slot_lock.release()


class _InflightReport(NamedTuple):
    level: str
    message: str


def _inflight_report(elapsed_secs: float) -> _InflightReport:
    """How to describe a slot that found the previous run still going.

    H5's second half, and the half a timeout alone does not fix. One slot overlapping
    the previous is routine — slots are 5 minutes apart and a run takes ~5.5 — so it
    must stay quiet. A run that has held the mutex far longer than any run legitimately
    takes is a different event and has to read differently, or the operator sees the
    same WARNING whether one slot slipped or the whole session died.

    Carrying the elapsed time is the point: it is the only number that separates the two,
    and the old message did not print it.

    A pure function so it can be tested for what it decides. test_slot_overlap tests the
    lock through a stand-in that re-implements the guard, which cannot catch a change to
    the real one.
    """
    mins = elapsed_secs / 60.0
    if elapsed_secs >= _INFLIGHT_STUCK_SECS:
        return _InflightReport(
            "critical",
            f"previous run has held the slot lock for {mins:.0f} min — that is not an "
            f"overlap, it is stuck. No slot can run until it exits. Expected ceiling is "
            f"{_SLOT_TIMEOUT_SECS / 60:.0f} min, so the kill did not take either: "
            f"check IB Gateway and the scheduler process.",
        )
    return _InflightReport(
        "warning",
        f"SKIPPED — previous run_live_day still in flight ({elapsed_secs:.0f}s, "
        f"{mins:.1f} min). Slots are 5 min apart and a run takes ~5.5 min; overlapping "
        f"children collide on IBKR clientId. Next slot picks it up.",
    )

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
# A stall has been reported and no healthy beat has been logged since. One-element dict
# for the same reason _last_beat is: the closure that sets it needs no `global`.
_stall_outstanding: dict = {"v": False}


def heartbeat_alive_is_worth_logging(minute: int, stall_outstanding: bool) -> bool:
    """Whether this healthy beat should reach the log at INFO.

    The beat runs every minute; writing it every minute is 2880 lines a day and makes
    the log unreadable, which is its own failure — a log nobody reads is the condition
    the heartbeat exists to remove. So an ordinary beat is throttled to the hour.

    But the throttle was also delaying the ONE line that says a stall is over. The
    journal reader marks recovery on "[HEARTBEAT] ALIVE", so after a stall the dashboard
    carried a critical incident for up to 59 more minutes while the scheduler was
    demonstrably beating again. Measured 2026-08-17: stall at 04:15 ET, healthy from
    04:22, earliest possible "recovered" 05:00; driving the closure at minute 55 emitted
    only a DEBUG line, which never reaches the file.

    An alarm whose off switch lags its on switch by an hour is one people learn to
    ignore, and this project has already paid for that once — six failed night slots
    kept a status bar red all day because nothing modelled "recovered".

    One extra line per stall is not noise. It is the most informative line in the file.
    """
    return minute == 0 or stall_outstanding

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


def _flex_to_date(today: _date) -> str:
    """Ngày cuối cùng xin được từ IBKR khi job 22:20 ET chạy vào `today`.

    Hàm riêng để kiểm được bằng phép tính chứ không bằng cách đọc mã nguồn: câu hỏi
    "job có bao giờ xin phiên hôm nay không" phải trả lời được bằng một con số.
    """
    return (today - _timedelta(days=1)).strftime("%Y%m%d")


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


def _load_maxhold_state() -> None:
    if not _MAXHOLD_STATE.exists():
        return
    try:
        with open(_MAXHOLD_STATE, encoding="utf-8") as fh:
            _maxhold_done.update({k: bool(v) for k, v in json.load(fh).items()})
    except Exception as exc:
        log.warning("[MAXHOLD] could not read %s (%s) — will treat today as not run",
                    _MAXHOLD_STATE, exc)


def _save_maxhold_state() -> None:
    """Atomic. A torn file reads as 'not run', which re-runs a job that is
    idempotent — the safe direction to fail in."""
    try:
        keep = dict(sorted(_maxhold_done.items())[-_PREFLIGHT_KEEP:])
        _maxhold_done.clear()
        _maxhold_done.update(keep)
        _MAXHOLD_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _MAXHOLD_STATE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(keep, fh, indent=2)
        os.replace(tmp, _MAXHOLD_STATE)
    except Exception as exc:
        log.error("[MAXHOLD] could not persist state to %s: %s", _MAXHOLD_STATE, exc)


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


def _run(args: list[str], label: str, dry_run: bool, timeout: float | None = None) -> bool:
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
    # H5. Without a ceiling here a child that never returns is waited on forever, and it
    # is holding _slot_lock: every remaining slot in the session then logs only
    # "SKIPPED — previous run_live_day still in flight", at WARNING, which is exactly
    # what an ordinary overlap logs. The session dies and the log reads normal.
    #
    # The broker's own waits are all bounded (send_order 30/120s, get_equity ~14s,
    # get_positions ~8s, _await_stop_accepted 5s, cancel_order 5s). The synchronous
    # ib_insync calls are not — qualifyContracts, reqAllOpenOrders, reqExecutions,
    # reqHistoricalData take no timeout — so the only place left to cut is the parent.
    #
    # Ceiling, not a target: a normal run is ~5.5 min and the two slots that also do a
    # full shadow replay add ~5 more, so ~11 min is legitimate. 20 min is roughly double
    # the longest honest run and still frees the session with most of a 1h50m window
    # left. Losing four slots beats losing every remaining one.
    try:
        result = subprocess.run(args, cwd=str(_CWD), capture_output=True,
                                text=True, errors="replace",
                                timeout=timeout or _SLOT_TIMEOUT_SECS)
    except subprocess.TimeoutExpired as _to:
        # subprocess.run has already killed the child before re-raising.
        log.critical(
            "[%s] TIMEOUT after %.0fs — child killed. This is NOT an overlapping slot: "
            "the process stopped responding and would otherwise have held the slot lock "
            "for the rest of the session. Check IB Gateway; the unbounded waits are the "
            "synchronous ib_insync calls.",
            label, float(getattr(_to, "timeout", 0) or 0),
        )
        for _stream, _name in ((getattr(_to, "stdout", None), "stdout"),
                               (getattr(_to, "stderr", None), "stderr")):
            _txt = _stream.decode("utf-8", "replace") if isinstance(_stream, bytes) else _stream
            _lines = [ln for ln in (_txt or "").splitlines() if ln.strip()]
            for ln in _lines[-_FAIL_TAIL_LINES:]:
                log.error("[%s] %s (%s before the kill)", label, ln.strip(), _name)
        return False
    if result.returncode == 0:
        # Mã thoát 0 KHÔNG có nghĩa là không có gì hỏng. 2026-08-10: MAX_HOLD đóng MYM
        # thành công (nên thoát 0) nhưng `cancel_order(12)` thất bại, và runner đã kêu
        # CRITICAL "STP ORPHAN ... will open an unintended position when it fires".
        # Dòng đó nằm trong output của tiến trình con, bị bắt ở đây rồi vứt đi vì
        # returncode == 0. Lệnh BUY STP mồ côi treo trên sàn suốt buổi và không log nào
        # nhắc tới nó — phát hiện được chỉ vì có người đi hỏi thẳng IBKR.
        #
        # Lọc theo mức độ, không theo mã thoát: một tiến trình con đã kêu CRITICAL/ERROR
        # thì không bao giờ được im lặng, dù nó kết thúc "thành công". Chỉ lấy các dòng đó
        # nên không làm ngập log — các child in rất nhiều khi chạy trơn.
        # Một lần đóng vị thế cũng không được phép biến mất. MAX_HOLD và STOP_REPAIR
        # không có tệp log riêng như run_live_day — chúng ghi ra stderr, bị bắt ở đây,
        # rồi bị bộ lọc dưới vứt, vì dòng của chúng là INFO. Sáng 2026-08-17 MAX_HOLD
        # đóng M2K và ghi có $179.50 vào sổ; dòng duy nhất kể lại việc đó nằm trong
        # output bị vứt, nên giá khớp và giờ khớp giờ chỉ còn ở phía broker. Con số
        # $179.50 dựng lại được từ chênh lệch equity, nhưng giá khớp thì không —
        # và suy ngược nó từ P&L sẽ cho ra đúng một giá trị lệch giá bằng 0, tức là
        # bịa một số 0 vào chính cái cổng chất lượng khớp lệnh.
        #
        # Lọc theo mức độ không bao giờ thấy được việc này: một lần đóng chạy trơn là
        # INFO, đúng như nó phải thế. Nên nhãn [BOOKED] là một giao kèo, không phải bắt
        # chữ trong câu văn: bên con dán nhãn vào đúng dòng ghi lại một thay đổi đã
        # động tới tiền hoặc tới lệnh trên sàn, bên cha không bao giờ vứt dòng đó.
        for _b in (ln for stream in (result.stdout, result.stderr)
                   for ln in (stream or "").splitlines() if "[BOOKED]" in ln):
            log.info("[%s] %s", label, _b.strip())
        _loud = [ln for stream in (result.stdout, result.stderr)
                 for ln in (stream or "").splitlines()
                 if "CRITICAL" in ln or "ERROR" in ln]
        if _loud:
            log.error("[%s] thoat OK nhung da ghi %d dong CRITICAL/ERROR — KHONG bo qua:",
                      label, len(_loud))
            for ln in _loud[-_FAIL_TAIL_LINES:]:
                log.error("[%s] %s", label, ln.strip())
            return True
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
                   live_state_path: str = "global_index/live_state_data.js",
                   shadow_resume: bool = False):
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
            #
            # Plus the first healthy beat after a stall, whatever the minute: that line
            # is what the journal reader turns into "recovered", and holding it back to
            # the next whole hour left the incident on screen long after it was over.
            if heartbeat_alive_is_worth_logging(now.minute, _stall_outstanding["v"]):
                log.info("[HEARTBEAT] alive")
                _stall_outstanding["v"] = False
            else:
                log.debug("[HEARTBEAT] ok")
            return
        _stall_outstanding["v"] = True
        log.warning(
            "[HEARTBEAT] STALLED %.0fs (expected ~%ds). The scheduler's wait timer does "
            "not advance while Windows sleeps, so every job due in that window was "
            "missed and every later one was pushed back by the same amount. Check "
            "Power-Troubleshooter events, and keep the machine awake "
            "(powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0).",
            gap, HEARTBEAT_SECS,
        )

    # ── 09:31 ET Mon-Fri: MAX_HOLD exit at RTH open ──────────────────────────
    # CỐ Ý không bọc trong _run_guarded, và lý do phải nằm ở đây vì nếu không thì lần
    # sau sẽ có người "sửa" nó — tôi suýt làm đúng thế.
    #
    # _run_guarded giành khoá không được thì BỎ QUA, và docstring của nó tự biện minh:
    # "diff_desired_vs_held is idempotent, so the next slot does whatever this one would
    # have". Đúng cho live_day (5 phút một lần) và cho quét sửa stop (2 tiếng một lần).
    # KHÔNG đúng ở đây: job này chạy MỘT LẦN MỘT NGÀY. Không có slot kế tiếp, nên bỏ qua
    # nghĩa là hôm đó vị thế tới hạn ở lại qua đêm.
    #
    # Và nó cũng không phải cái khoá cần: sự cố đo được ngày 2026-08-13 là HAI TIẾN
    # TRÌNH scheduler cùng bắn slot này trong một giây. _slot_lock là threading.Lock —
    # hai tiến trình thì hai khoá, không ai thấy ai. Bảo vệ nằm ở khoá tệp PID (E1),
    # nay đã được run_maxhold_exit giành TRƯỚC khi nối IBKR.
    @sched.scheduled_job("cron", day_of_week="mon-fri", hour=9, minute=31,
                         id="maxhold_exit", name="MAX_HOLD exit 09:31 ET")
    def job_maxhold(label: str = "MAX_HOLD_EXIT"):
        ok = _run([sys.executable, "-m", "global_index.run_maxhold_exit",
                   "--positions-path", "live_positions.json",
                   "--port", str(port)],
                  label=label, dry_run=dry_run)
        # Only a real run counts. _run returns True under --dry-run without
        # executing anything, so recording it would mark the day done when nothing
        # closed — and the next real scheduler would skip the catch-up. A dry-run
        # that disables the safeguard it is testing is worse than no safeguard.
        if ok and not dry_run:
            _maxhold_done[_et_today().isoformat()] = True
            _save_maxhold_state()
        return ok

    # ── 10:20 ET Mon-Fri: STRESS_MID entry ───────────────────────────────────
    # Sleeve vào lệnh tại đóng cửa bar 10:15 ET. Chạy 10:20 để bar đó đã đóng hẳn.
    #
    # prev_preflight=True vì cùng lý do slot đêm NKD dùng: job 13:45 chưa chạy lúc
    # 10:20, nên cờ của hôm nay luôn None và fail-closed sẽ bỏ qua vĩnh viễn. Bản
    # cập nhật dữ liệu mới nhất tồn tại ở thời điểm này là 13:45 hôm trước.
    #
    # ⚠️ BẤT BIẾN — KHÔNG được thêm slot nào gọi run_live_day giữa 10:20 và 14:05 ET.
    # `_mark_held_unchanged` không gọi cho cluster stress, nên `diff_desired_vs_held`
    # thấy khoá (inst, roska4_stress) vắng trong `desired` và đóng vị thế ở LẦN CHẠY
    # KẾ TIẾP. Với lịch hiện tại lần đó là 14:05 — gần đúng mốc 14:00 của adapter, và
    # đó là lý do sleeve giữ được ~91% luật đã kiểm định. Thêm một slot xen giữa thì
    # vị thế bị đóng sau vài phút: +$12.850 tụt xuống −$450, im lặng, không guard nào
    # kêu. Job 09:31 (run_maxhold_exit) và 13:45 (pre-flight) KHÔNG gọi
    # generate_today_signals nên an toàn.
    #
    # Sửa bằng cách thêm `_mark_held_unchanged` cho stress là SAI: khi đó không gì
    # đóng vị thế nữa và nó qua đêm. Stress cần một luật thoát tường minh, không phải
    # nhánh dự phòng của diff.
    # 🔴 TAT — KHONG dang ky job nay. Xem docs/futures/OPERATIONS.md muc "STRESS_MID:
    # tai sao cron 10:20 bi tat".
    #
    # STRESS_MID dung DUNG BON MA cua Ro 4 va LUON SHORT. Tang broker khong phan biet
    # duoc hai vi the cung ma khac cluster:
    #
    #   1. BU TRU RONG. get_positions() tra vi the RONG co dau cho moi hop dong. MES
    #      swing LONG 1 + MES stress SHORT 1 => IBKR bao net 0. File co hai vi the,
    #      broker khong co dong nao -> B3 MISMATCH -> HALT toan bo entry.
    #      `held_stress` chi chan khi da co vi the STRESS cung ma, khong chan khi co
    #      vi the SWING.
    #
    #   2. STOP KHONG PHAN BIET DUOC VI THE. Cung chieu thi khong bu tru, nhung
    #      has_working_stop(inst) khoa theo SYMBOL: stress dat stop truoc => B4 tu choi
    #      dat stop cho swing ("tranh xep chong"), va unprotected_positions() thay co
    #      stop tren expiry do nen bao AN TOAN. Mot hop dong tran vinh vien, im lang.
    #
    # Bat lai chi sau khi tang theo doi stop khoa theo VI THE thay vi theo MA, va sau
    # khi quyet duoc chuyen bu tru rong. Co --stress-entry cua run_live_day van con,
    # de chay tay khi kiem thu.
    if False:   # noqa: SIM108 — giu code de bat lai, xem ghi chu tren
        @sched.scheduled_job("cron", day_of_week="mon-fri", hour=10, minute=20,
                             id="stress_mid", name="STRESS_MID entry 10:20 ET",
                             misfire_grace_time=SLOT_MISFIRE_GRACE_SECS)
        def job_stress_mid():
            _live_day_body("STRESS_MID_1020", clusters="stress",
                           prev_preflight=True, stress_entry=True)

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
                       clusters: str = "all", prev_preflight: bool = False,
                       verify: bool = False, stress_entry: bool = False) -> None:
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
        # The mutex lives in _run_guarded so the suite drives the same code this does.
        _run_guarded(slot_id, lambda: _live_day_body_inner(
            slot_id, first_slot=first_slot, clusters=clusters,
            prev_preflight=prev_preflight, verify=verify, stress_entry=stress_entry))

    # ── Shared runner body (all 14:05–15:55 slots) ───────────────────────────
    def _live_day_body_inner(slot_id: str, *, first_slot: bool = False,
                             clusters: str = "all", prev_preflight: bool = False,
                             verify: bool = False, stress_entry: bool = False) -> None:
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
              "--port",            str(port)]
             # Logs a checkpoint-resumed target beside the one that trades, so the
             # two can be compared on live data. Decides nothing; see run_live_day
             # --shadow-resume. Measured ~11s per instrument on the day's first slot
             # (one replay for the target, one to advance the checkpoint) and ~5s
             # after, against a ~5.5 min run — the skip pattern does not change.
             + (["--shadow-resume"] if shadow_resume else [])
             # --shadow-verify replays the frame in full to compare, which is the
             # ~5 minutes the checkpoint exists to avoid. On every slot it would
             # push a run past 13 min and skip two slots in three, making entry
             # latency worse to prove it could be better. Once a day is enough:
             # if the two paths disagree they disagree all day, and on the last
             # slot the session is over so the extra minutes cost nothing.
             + (["--shadow-verify"] if (shadow_resume and verify) else [])
             # STRESS_MID vào lệnh lúc 10:15 ET. Cờ này CHỈ slot sáng được truyền —
             # slot chiều chạy sau đó ~4 tiếng, dùng cùng tín hiệu sẽ vào ở giá đã
             # trôi, đúng hình dạng đã làm hỏng sleeve swing.
             + (["--stress-entry"] if stress_entry else []),
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
    _LAST_SLOT = _CONT_SLOTS[-1]
    for _h, _m in _CONT_SLOTS:
        _slot_id = f"LIVE_DAY_{_h:02d}{_m:02d}"
        _verify = ((_h, _m) == _LAST_SLOT)
        sched.add_job(
            lambda sid=_slot_id, v=_verify: _live_day_body(sid, verify=v),
            "cron", day_of_week="mon-fri", hour=_h, minute=_m,
            id=_slot_id.lower(),
            name=f"Continuous run {_h:02d}:{_m:02d} ET",
            misfire_grace_time=SLOT_MISFIRE_GRACE_SECS,
        )

    # ── Quét sửa stop trong ba khoảng trống ──────────────────────────────────
    # Lịch slot ở trên được dựng cho việc VÀO LỆNH: 14:00-15:55 ET (Rổ 4), 14:00-15:55 JST
    # (NKD, = 01:10-02:55 ET), cộng 09:31 cho MAX_HOLD. Việc SỬA CHỮA stop chỉ đi ké chúng,
    # nên nó thừa hưởng ba khoảng trống mà không ai chọn:
    #
    #     15:55 -> 01:10   9h15   <- tệ nhất, và đúng cái đêm stop sinh ra để bảo vệ
    #     02:55 -> 09:31   6h36
    #     09:31 -> 14:05   4h34
    #
    # run_stop_repair dựng runner với signal_fn rỗng: không entry, không exit, chỉ B1-B5.
    # `_stop_deferred` vẫn chặn, nên một lần chạy lúc 20:00 ET KHÔNG vũ trang sớm vị thế
    # Rổ 4 mở cùng ngày — job này chỉ chạm vế sửa chữa của B4.
    #
    # Chỉ đặt trong ba khoảng trống, không chen vào cửa sổ vào lệnh: mỗi lần chạy là thêm
    # một lượt B3, tức thêm cơ hội halt entry vì mismatch giả. Ngoài cửa sổ thì halt không
    # tốn gì (`_b3_halt_entries` không ghi xuống đĩa và mỗi lần chạy là tiến trình riêng).
    # Cứ ~2 tiếng một lượt, ở phút :20 — BỎ QUA lượt nào rơi vào cửa sổ vào lệnh.
    #
    # Trong hai cửa sổ đó (01:00-02:55 và 14:00-15:55 ET) đã có slot chạy mỗi 5 phút, mà
    # mỗi slot đều dựng runner nên B4/B5 vẫn chạy — thêm một lượt quét vào giữa chỉ là một
    # lượt B3 thừa, tức một cơ hội thừa dính mismatch giả và halt entry đúng lúc cửa sổ
    # đang làm việc của nó.
    #
    # Bỏ 02:20 và 14:20 để lại hai khoảng 4 tiếng trên giấy, nhưng khoảng thật sự không ai
    # nhìn thì ngắn hơn nhiều vì cửa sổ nằm giữa chúng:
    #     00:20 -> 01:10 (50p)  ·  02:55 -> 04:20 (1h25)
    #     12:20 -> 14:05 (1h45) ·  15:55 -> 16:20 (25p)
    #
    # Trước đó tôi để 19 lượt mỗi tiếng (lấy "lấp kín khoảng trống" làm mục tiêu thay vì
    # "giảm thời gian không ai nhìn"), rồi cắt xuống 3. Cả hai đều là lập luận suông. Mốc
    # 2 tiếng là do người vận hành chốt.
    _ENTRY_WINDOWS = [((1, 0), (2, 55)), ((14, 0), (15, 55))]
    _REPAIR_SLOTS = [
        (h, 20) for h in range(0, 24, 2)
        if not any(lo <= (h, 20) <= hi for lo, hi in _ENTRY_WINDOWS)
    ]
    for _h, _m in _REPAIR_SLOTS:
        sched.add_job(
            # Same mutex the live_day slots hold. All three entry points connect on
            # clientId 1 — the guard's own message names that collision — and the
            # schedule margin is not what it looks like: measured against the worst
            # case a slot is allowed (20-minute ceiling + 5-minute grace after a 15:55
            # start), STOP_REPAIR_1620 has ZERO minutes of clearance, and 15:55 is the
            # slot that also runs a full shadow replay. Skipping a sweep costs nothing:
            # they run every two hours and the repair is idempotent.
            lambda lbl=f"STOP_REPAIR_{_h:02d}{_m:02d}": _run_guarded(lbl, lambda: _run(
                [sys.executable, "-m", "global_index.run_stop_repair",
                 "--positions-path", "live_positions.json", "--port", str(port)],
                label=lbl, dry_run=dry_run)),
            "cron", day_of_week="mon-fri", hour=_h, minute=_m,
            id=f"stop_repair_{_h:02d}{_m:02d}",
            name=f"Stop repair sweep {_h:02d}:{_m:02d} ET",
            misfire_grace_time=SLOT_MISFIRE_GRACE_SECS,
        )

    # ── Chủ nhật 18:30 ET: bịt khoảng hở giữa lúc CME mở lại và sweep mon-fri đầu tiên ──
    # CME mở lại 18:00 ET Chủ nhật, nhưng slot mon-fri sớm nhất là STOP_REPAIR_0020 sáng
    # thứ Hai. Ở giữa là 6 tiếng rưỡi thị trường ĐANG CHẠY mà không lượt nào kiểm rằng
    # stop bảo vệ còn sống. Nếu một lần TWS restart cuối tuần làm mất GTC stop — đúng
    # kịch bản Fix 1 sinh ra để chống — thì không ai biết cho tới sáng thứ Hai.
    #
    # Cùng lập luận dòng 402 dùng để CỐ Ý không gate heartbeat theo mon-fri: một sự cố
    # bắt đầu cuối tuần phải nhìn thấy được TRƯỚC slot đầu tiên của thứ Hai, không phải sau.
    #
    # KHÔNG mở sweep cho cả cuối tuần: từ 17:00 ET thứ Sáu tới 18:00 ET Chủ nhật thị
    # trường đóng, không có giá để trigger stop. Quét lúc đó là quét vào chỗ trống.
    # 18:30 (mở cửa + 30 phút) cho phiên ổn định trước khi đọc trạng thái lệnh.
    sched.add_job(
        lambda lbl="STOP_REPAIR_SUN_1830": _run_guarded(lbl, lambda: _run(
            [sys.executable, "-m", "global_index.run_stop_repair",
             "--positions-path", "live_positions.json", "--port", str(port)],
            label=lbl, dry_run=dry_run)),
        "cron", day_of_week="sun", hour=18, minute=30,
        id="stop_repair_sun_1830",
        name="Stop repair sweep 18:30 ET (Sunday reopen)",
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

    # The last night slot also runs --shadow-verify, for the same reason the day's
    # 15:55 slot does: by then NKD's entry window is closed, so the ~5 min full
    # replay cannot cost an entry.
    #
    # Without this the night path was never compared at all. MNKD *is* verified on
    # the 15:55 ET slot, but that is a different frame — the night run passes
    # --clusters nkd and splices live bars through _splice_nkd_live, and it is the
    # night run that actually places NKD orders. verify_resume covers MNKD 14/14
    # offline, so the engine's resume is settled; what was untested is resume on
    # the night slot's live-spliced frame.
    _NKD_LAST = _NKD_SLOTS[-1]
    for _h, _m in _NKD_SLOTS:
        _slot_id = f"NKD_NIGHT_{_h:02d}{_m:02d}"
        sched.add_job(
            lambda sid=_slot_id, v=((_h, _m) == _NKD_LAST): _live_day_body(
                sid, clusters="nkd", prev_preflight=True, verify=v),
            "cron", day_of_week="mon-fri", hour=_h, minute=_m,
            id=_slot_id.lower(),
            name=f"NKD night run {_h:02d}:{_m:02d} ET",
            misfire_grace_time=SLOT_MISFIRE_GRACE_SECS,
        )

    # ── Báo cáo phiên: chạy KHI VIỆC CUỐI CÙNG TRONG NGÀY XONG ───────────────
    # Không hẹn giờ cố định. Bản đầu tôi đặt cron 16:00, rồi 23:50 — cả hai đều là ĐOÁN:
    # 16:00 bỏ trắng 8 việc chạy sau đó (tới 23:20), còn 23:50 vẫn ra trước nếu lượt quét
    # 23:20 chạy quá 30 phút. Báo cáo đọc log theo NGÀY LỊCH, nên phần bị bỏ sót không bao
    # giờ được bản hôm sau phủ — nó chỉ đọc dòng mang ngày hôm sau.
    #
    # APScheduler không có sự kiện "đã chạy hết", nhưng nó có sự kiện "một việc vừa xong".
    # Nên: xác định việc có giờ muộn nhất trong ngày, rồi bám vào sự kiện của chính nó.
    # Việc cuối là gì thì TÍNH RA từ lịch, không viết cứng — thêm một việc muộn hơn thì
    # báo cáo tự dời theo, không phải nhớ sửa ở hai chỗ.
    #
    # Nghe cả EXECUTED lẫn ERROR: một việc cuối bị lỗi thì càng cần báo cáo, không phải
    # càng ít.
    _fixed = []
    for _j in sched.get_jobs():
        if _j.id == "heartbeat":
            continue
        _f = {str(x.name): str(x) for x in _j.trigger.fields}
        try:
            _fixed.append((int(_f["hour"]), int(_f["minute"]), _j.id))
        except (KeyError, ValueError):
            continue
    _LAST_JOB_ID = sorted(_fixed)[-1][2] if _fixed else None
    _report_done: dict = {}

    def _refresh_paper_evidence() -> None:
        """Kéo sao kê broker rồi dựng lại phần đối chiếu P&L của bảng Paper Evidence.

        Chạy ngay sau báo cáo phiên: tới lúc đó dữ liệu trong ngày đã đủ, và đây là chỗ
        duy nhất trong lịch vốn đã dành cho việc báo cáo chứ không phải giao dịch.

        Trước 2026-08-15 hai việc này chạy tay. Bảng đọc từ một tệp sinh sẵn, nên mỗi
        lệnh mới làm phần P&L cũ đi mà KHÔNG có dấu hiệu nào.

        CỐ Ý KHÔNG có ở đây:
          · sinh lại baseline backtest — đó là MỐC SO SÁNH, và 21 band ngưỡng chặn
            go-live đóng băng từ chính đường cong đó. Nó tự đổi thì đích so sánh tự
            dịch chuyển trong khi band vẫn tính trên đường cong cũ. Phải là hành động
            có chủ đích, kèm bước tính lại band và duyệt lại.
          · monitor/paper_inputs.json — trong đó là LỜI CHỨNG THỰC của con người
            ("đêm này đã chứng minh khởi động lại thành công"), không phải dữ liệu.
            Tự động hoá nó là tự ký vào bằng chứng của chính mình — đúng lỗi C2.

        Không bao giờ được làm hỏng ngày giao dịch: mọi lỗi chỉ ghi log. Bảng giữ số cũ
        và tự khai là cũ qua dấu vân tay dữ liệu.
        """
        try:
            # Xin tới HÔM QUA, không phải hôm nay. Khoảng ngày mặc định của Flex Query
            # bao gồm phiên đang chạy, mà IBKR chưa chốt sổ phiên đó lúc 22:20 ET —
            # đo được ngày 2026-08-18: gọi đúng câu lệnh này lúc 00:05 ET, tức hơn 6
            # tiếng sau giờ đóng cửa và gần 2 tiếng sau khung chạy, vẫn nhận
            # `code=1004 Statement is incomplete at this time`. Cùng lúc đó, xin tới
            # hôm trước thì về 35KB bình thường.
            #
            # Nên độ trễ một phiên ở phía broker là bản chất, không phải lựa chọn: sổ
            # của IBKR cho hôm nay chưa tồn tại vào lúc job chạy. Ghim nó tường minh
            # còn hơn để khoảng mặc định của query quyết định — bảng khi đó nói rõ
            # được nó đang phủ tới đâu.
            #
            # Chưa chứng minh: liệu IBKR có luôn xong phiên D-1 trước 22:20 ET ngày D
            # hay không. Mới có một quan sát thành công. Nếu hụt, `flex_pull` sẽ nói
            # code 1004 chứ không im, và dời khung chạy muộn hơn là cách chữa.
            if not _run([sys.executable, "-m", "monitor.flex_pull",
                         "--to-date", _flex_to_date(_et_today())],
                        label="FLEX_PULL", dry_run=dry_run):
                log.warning("[FLEX_PULL] that bai — van dung sao ke cu; doi chieu P&L "
                            "se tinh tren du lieu broker cu")
            if not _run([sys.executable, "-m", "monitor.paper_pnl_compare"],
                        label="PAPER_PNL", dry_run=dry_run):
                log.warning("[PAPER_PNL] that bai — bang Paper Evidence giu so cu; "
                            "dau van tay du lieu se bao STALE")
        except Exception:
            log.exception("[PAPER_REFRESH] loi ngoai du kien — bo qua, "
                          "khong anh huong giao dich")

    def _emit_report(why: str) -> None:
        _d = _et_today().isoformat()
        if _report_done.get(_d):
            return
        _report_done[_d] = True
        log.info("[SESSION_REPORT] dung %s — viec cuoi cung trong ngay da xong", why)
        _run([sys.executable, "-m", "global_index.session_report",
              "--out", f"bao_cao_{_et_today().strftime('%m%d')}.txt"],
             label="SESSION_REPORT", dry_run=dry_run)
        _refresh_paper_evidence()

    if _LAST_JOB_ID:
        from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

        def _on_job_done(event) -> None:
            if event.job_id == _LAST_JOB_ID:
                _emit_report(_LAST_JOB_ID)

        sched.add_listener(_on_job_done, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        log.info("Bao cao phien se chay ngay sau viec cuoi cung trong ngay: %s",
                 _LAST_JOB_ID)

        # Lưới an toàn. Nếu việc cuối KHÔNG chạy — scheduler lên sau giờ của nó, hoặc nó
        # bị lỡ — thì sự kiện không bao giờ tới và ngày đó không có báo cáo nào. Đúng loại
        # im lặng mà báo cáo sinh ra để chống, nên nó không được tự dính vào.
        # Cron này chỉ chạy khi cờ trong ngày chưa được đặt, tức chỉ khi đường chính hỏng.
        @sched.scheduled_job("cron", day_of_week="mon-fri", hour=23, minute=55,
                             id="session_report_fallback",
                             name="Bao cao phien (luoi an toan 23:55 ET)",
                             misfire_grace_time=SLOT_MISFIRE_GRACE_SECS)
        def job_report_fallback():
            if _report_done.get(_et_today().isoformat()):
                return
            log.warning("[SESSION_REPORT] viec cuoi (%s) khong chay — dung luoi an toan",
                        _LAST_JOB_ID)
            _emit_report("luoi an toan 23:55")

    return sched


def _catch_up_maxhold(sched) -> None:
    """Run today's 09:31 MAX_HOLD exit if the scheduler came up after it.

    APScheduler schedules the NEXT occurrence at startup, so a scheduler started
    at 09:43 does not have a late 09:31 job — it has no 09:31 job at all. Nothing
    misfires, nothing is logged, and the positions that carry the system's entire
    edge exit hours later through run_live_day instead.

    Re-running is safe: run_maxhold_exit closes positions at hold >= max_hold_days
    and does nothing when there are none, and it reads live_positions.json plus the
    broker rather than the parquet, so it does not depend on the 13:45 pre-flight.
    The state file only avoids a pointless duplicate on every restart.

    Takes no dry_run of its own: it calls the same closure the cron calls, which
    already captured it. A second copy of that flag is a second thing to keep in
    step.
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    now = _dt.now(ZoneInfo("America/New_York"))
    today = now.date().isoformat()
    if now.weekday() >= 5:
        return
    if now.hour * 60 + now.minute < 9 * 60 + 31:
        return                                  # the cron will fire it normally
    if _maxhold_done.get(today):
        log.info("[MAXHOLD] da chay hom nay (%s) — bo qua catch-up", today)
        return

    job = sched.get_job("maxhold_exit")
    if job is None:
        log.error("[MAXHOLD] khong tim thay job maxhold_exit — khong catch-up duoc")
        return

    log.warning("[MAXHOLD] CATCH-UP: khoi dong luc %s ET, sau moc 09:31, va job hom "
                "nay chua chay. Chay ngay bay gio.", now.strftime("%H:%M"))
    ok = job.func(label="MAX_HOLD_EXIT_CATCHUP")
    if not ok:
        log.critical("[MAXHOLD] CATCH-UP THAT BAI — vi the du 5 ngay co the chua duoc "
                     "dong. Kiem live_positions.json va chay tay: python -m "
                     "global_index.run_maxhold_exit --positions-path "
                     "live_positions.json --port <port>")


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
    ap.add_argument("--shadow-resume",    action="store_true",
                    help="pass --shadow-resume to run_live_day: log a "
                         "checkpoint-resumed target for comparison, without "
                         "trading off it")
    ap.add_argument("--assume-preflight-ok", action="store_true",
                    help="Mark today's pre-flight as passed on startup (use after manual update_ibkr_daily + update_spy_csv)")
    a = ap.parse_args()
    attach_file_log()

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
    _load_maxhold_state()

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
        shadow_resume=a.shadow_resume,
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
    _catch_up_maxhold(sched)

    log.info("Scheduler started. Ctrl-C to stop.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
