"""
global_index/runner.py — the futures live loop (orchestration)
==============================================================
One place that wires everything: each trading day →
    broker.fetch_bars → signal_layer.generate_today_signals → decide_day (risk brain)
    → broker.send_order (exits then entries) → state synced to broker.

The SAME runner drives MockBroker (offline verify vs deploy_sim) and IBKRBroker (live).
Swapping is one line: `FuturesRunner(broker=MockBroker(...))` → `broker=IBKRBroker(...)`.

OPERATIONAL CONSTRAINT — NKD timing:
  generate_today_signals uses today_norm (ET date) as the NKD "today" reference.
  This is valid only when the runner executes AFTER the NKD session closes (~02:30 ET).
  At US market open (09:30 ET) all NKD bars for the JST session are available and
  JST calendar date == ET calendar date. If the runner is ever rescheduled to run
  before ~02:30 ET (pre-market / overnight), the NKD date alignment must be revisited
  — today's NKD bars would be incomplete and the guard semantics change.
  See DIVERGENCE_SWEEP.md § "Operational constraint — NKD date alignment".

Decision correctness (signal+decide == deploy_sim) is already proven by the signal_layer
e2e test. This file adds ORCHESTRATION: order lifecycle, broker/state reconciliation,
exit-before-entry ordering. run_history() replays through a MockBroker to check that
orchestration reproduces deploy_sim's decision stream.

CWD + encoding guards below: code must run from repo root (raits package resolves there,
not from D:\\raits\\raits), and stdout must be UTF-8 (log lines contain non-ASCII like
"Rổ 4" — cp1252 console crashes mid-run otherwise).

Operational fixes (2026-07-05):
  B1 — atomic JSON persistence of open_positions after every run_day(); loaded on restart
       to prevent position orphans after crash / reboot.
  C1 — signal_fn() wrapped in try/except; engine failure skips entries for the day,
       held positions still exit normally via their exit_day.
  E1 — PID lockfile prevents duplicate runner instances from submitting double orders.
"""
from __future__ import annotations
import atexit
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# --- CWD / path guard: ensure repo root on path regardless of launch dir ---
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# --- encoding guard: non-ASCII log lines must not crash on Windows cp1252 ---
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from global_index.broker import Order
from global_index.live_decision import decide_day, DecisionState, OpenPos

# Engine day keys are ET. Every "which day is it" question in this file must be
# answered in ET, never on the host clock — the machine running this sits 11 hours
# ahead, so a local date silently names the wrong session for most of the day.
ET_TZ = "America/New_York"

# Clusters whose engine defers the stop to the next session — see _stop_deferred.
# Swing and NKD both run backtest_swing_tf and inherit its semantics. Stress is an
# event model that opens and closes inside one session; it is not covered by the
# measurement and is deliberately left alone.
_DEFERRED_STOP_CLUSTERS = frozenset({"roska4_swing", "global_nkd"})

# Gio vu trang stop: 14 gio sau ranh gioi ngay phien CUA CHINH SLEEVE DO.
#
# Mot hang so duy nhat, nhung moi sleeve mot dong ho — nen phai khai bang MUI GIO, khong
# phai bang gio ET co dinh:
#
#   roska4_swing  14:00 America/New_York
#   global_nkd    14:00 Asia/Tokyo
#
# Vi sao khong dung gio ET co dinh cho NKD: chenh lech ET<->JST DOI THEO DST (he 13h,
# dong 14h). Khai "01:00 ET" thi mua he dung 14:00 JST nhung mua dong thanh 15:00 JST —
# troi mot tieng khoi luat, moi nam hai lan, khong co gi bao.
#
# Con so 14h khong phai dinh cua mot bang: hai phep walk-forward DOC LAP (Ro 4 va MNKD,
# hai dong ho, hai bo du lieu) deu hoi tu ve no — Ro 4 h*=14h 6/7 nam, MNKD 7/7.
#
#   Ro 4  o 1,17h (truoc day): +$41.505 ngoai mau   |  o 14h: +$116.530
#   MNKD  o 14,17h (hien tai): +$35.458 ngoai mau   |  DA DUNG, khong doi
#
# KHONG vu trang tai ranh gioi phien. Nghi CME 17:00-18:00 ET: vu trang o 17-18h lam ty
# le thoat GAP vot tu 6% len 40% va P&L sup tu +$128.863 xuong -$1.091. Nghi NKD
# 06:00-08:45 JST co ho tuong tu. Ca 14:00 ET lan 14:00 JST deu giua phien.
_ARM_BY_CLUSTER = {"roska4_swing": ("America/New_York", 14, 0),
                   "global_nkd":   ("Asia/Tokyo", 14, 0)}


# fit_A degradation floor — the Calmar the live system is measured against. Single
# source of truth is INVARIANTS.md; keep this and generate_replay_snapshots.py in
# step with it. Re-derive after ANY change to engine, data, period or cluster caps:
#   deploy_sim --data-dir data/cache/futures/frozen_sim \
#     --nkd-parquet global_index/data/NKD_frozen_2024.parquet \
#     --regime-csv spy_daily_live.csv --end 2024-12-31 \
#     --hmm-fit-end 2022-12-31 --n-contracts 1 --slippage-ticks 2
# 1.65 (2026-08-04, global_nkd 6%). Superseded 1.57 (nkd cap 2%) and 1.53 (bar-0
# exit) — 1.53 was still hardcoded here long after INVARIANTS had deprecated it.
BACKTEST_CALMAR_FLOOR: float = 1.65


# ── E1: PID lockfile helpers ────────────────────────────────────────────────

class RunnerLockError(RuntimeError):
    """Raised when a second runner instance attempts to start with the same lock file."""


def _pid_alive(pid: int) -> bool:
    """Cross-platform process existence check.
    os.kill(pid, 0) is NOT used on Windows: signal value 0 == CTRL_C_EVENT there,
    so calling it with the current PID sends CTRL_C to the runner itself.
    Windows alternative: OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION."""
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


def _acquire_lock(lock_path: Path) -> None:
    """Write PID lockfile; raise RunnerLockError if another live instance holds it."""
    if lock_path.exists():
        try:
            pid = int(lock_path.read_text().strip())
            if pid == os.getpid():
                pass          # same process re-acquiring: run_live_day takes the lock
                              # before connecting to IBKR, then FuturesRunner takes it
                              # again. Treating that as a collision would make every
                              # run abort on itself.
            elif _pid_alive(pid):
                raise RunnerLockError(
                    f"Runner already running (PID {pid}, lock={lock_path}). "
                    f"Delete {lock_path} manually if stale."
                )
        except RunnerLockError:
            raise
        except Exception:
            pass                    # stale lock (parse error, OS error) → overwrite
    try:
        lock_path.write_text(str(os.getpid()))
    except OSError as exc:
        raise RunnerLockError(
            f"Cannot create lock file {lock_path}: {exc}. "
            f"Check directory permissions or choose a writable lock_path."
        ) from exc


def _release_lock(lock_path: Path) -> None:
    """Remove lockfile on clean exit. Safe to call even if file is missing."""
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


# ── B1: OpenPos serialisation helpers ──────────────────────────────────────

def _openpos_to_dict(p: OpenPos) -> dict:
    return {
        "inst":           p.inst,
        "direction":      p.direction,
        "contracts":      p.contracts,
        "risk_dollars":   p.risk_dollars,
        "cluster":        p.cluster,
        "entry_day":      str(p.entry_day) if p.entry_day is not None else None,
        "exit_day":       str(p.exit_day)  if p.exit_day  is not None else None,
        "pnl_sized":      p.pnl_sized,
        "exit_pending":   p.exit_pending,
        "stop_price":     p.stop_price,
        "stop_order_id":  p.stop_order_id,
        "entry_price":    p.entry_price,
    }


def _openpos_from_dict(d: dict) -> OpenPos:
    # Required fields use d["field"] — KeyError if missing → outer except → fresh start.
    # No sensible defaults exist for inst/direction/contracts/risk_dollars/cluster.
    # Future OpenPos fields MUST use d.get(field, default) to keep backward-compat.
    return OpenPos(
        inst=d["inst"],
        direction=d["direction"],
        contracts=int(d["contracts"]),
        risk_dollars=float(d["risk_dollars"]),
        cluster=d["cluster"],
        entry_day=pd.Timestamp(d["entry_day"]) if d.get("entry_day") else None,
        exit_day=pd.Timestamp(d["exit_day"])   if d.get("exit_day")  else None,
        pnl_sized=float(d.get("pnl_sized", 0.0)),
        exit_pending=bool(d.get("exit_pending", False)),
        stop_price=float(d["stop_price"]) if d.get("stop_price") is not None else None,
        stop_order_id=d.get("stop_order_id"),
        entry_price=float(d["entry_price"]) if d.get("entry_price") is not None else None,
    )


class FuturesRunner:
    """Drives the daily loop through a Broker. In verify mode, entry candidates carry
    their ledger exit_day/pnl_sized so MockBroker realizes deploy_sim-equivalent pnl."""

    def __init__(self, broker, guard, contracts_by_inst, signal_fn, breaker,
                 hmm_stale_guard=None, positions_path=None, lock_path=None,
                 live_state_path=None, paper_history_path=None,
                 stop_path=None, max_contracts_per_order=10,
                 regime_fn=None, trade_log_path=None, today=None, now=None):
        """signal_fn(day, bars_by_inst, held) -> (entry_candidates, exit_positions)
        wraps signal_layer.generate_today_signals with the engines/labels/costs bound.
        Injecting it keeps the runner testable without real engines.

        breaker (required): a CircuitBreaker instance. No default — live runner must
        have a breaker; omitting it is a silent bypass of the 15% DD hard stop.
        Pass CircuitBreaker(account=account) at construction; do not set after the fact.

        hmm_stale_guard (optional): HMMStaleGuard instance (G1+G2). When provided,
        check_day() is called each trading day. If regime_unreliable, new entries are
        blocked; existing exit positions are unaffected and close normally.

        positions_path (optional, str|Path): path for atomic JSON persistence of open
        positions (B1 fix). Pass None (default) for offline/test use. In production
        set to e.g. Path("live_positions.json"). On startup with an existing file the
        positions are loaded back — enabling position recovery across restarts.
        TODO (B3 layer 2): once IBKRBroker.get_positions() is implemented, cross-check
        the loaded file against broker positions on startup and alert on mismatch.
        Until then the persisted file is the sole source of truth on restart.

        lock_path (optional, str|Path): path for PID lockfile (E1 fix). Pass None
        (default) for offline/test use. In production set to e.g. Path("runner.pid")
        to prevent duplicate runner instances from submitting double orders to IBKR."""

        self._regime_fn = regime_fn
        self._last_regime: str = "Unknown"
        self._trade_log_path = Path(trade_log_path) if trade_log_path else None
        # Initialised before anything can emit. B3's reconcile runs inside __init__ and
        # can report an unpriceable close, which happens well before the operational-log
        # section further down.
        self._events: list = []
        # Append-only telemetry is derived from the dashboard path so offline runners
        # without live_state_path remain write-free. It is never read by the engine.
        self._event_log_dir = Path(live_state_path).parent if live_state_path else None
        self._event_log_disabled = False

        # E1: acquire PID lock first — refuse second instance before any state is set up
        self._lock_path = Path(lock_path) if lock_path else None
        if self._lock_path is not None:
            _acquire_lock(self._lock_path)
            atexit.register(_release_lock, self._lock_path)

        # B3: halt new entries if broker/file mismatch detected on startup (set below)
        self._b3_halt_entries: bool = False
        # B4: positions confirmed open at the broker but carrying no stop order (set below)
        self._b4_naked_stops: list = []
        # The stop-free window is DELIBERATE — see _stop_deferred. Anchored in ET
        # because the engine's day keys are ET: at 09:00 in Hanoi it is 22:00 ET the
        # previous day, so a local-clock "today" would place stops a day early.
        # `now` la moc thoi gian ET; `today` chi la ngay phien. Truyen `today` ma
        # khong truyen `now` nghia la "coi nhu la ngay do" — lay nua dem ngay do, KHONG
        # lay dong ho that. Tron hai thu se lam hanh vi phu thuoc gio chay.
        if now is not None:
            self._now = pd.Timestamp(now)
        elif today is not None:
            self._now = pd.Timestamp(today).normalize()
        else:
            self._now = pd.Timestamp.now(tz=ET_TZ).tz_localize(None)
        self._today = (pd.Timestamp(today).normalize() if today is not None
                       else self._now.normalize())

        # B1: load persisted positions + breaker state if path is supplied and file exists
        self._positions_path = Path(positions_path) if positions_path else None
        # Stop exits found during B3 cannot be booked where they are found: B3 runs
        # here in __init__ and self.state is not built until much later, so calling
        # _book_realised at the discovery site raises AttributeError — which the
        # broad `except Exception` around the cross-check swallows as "B3: cross-check
        # failed", losing the booking with a message that says nothing about money.
        # That is why the NOT_FOUND branch's booking never actually ran either.
        # Queue them, drain after self.state exists.
        _pending_stop_exits: list = []
        loaded_positions: list = []
        loaded_peak_equity = None
        loaded_day_start_equity = None
        loaded_cur_day = None
        # Each cron slot is a fresh run-and-exit process, so the system ledger has to
        # survive on disk or it resets to base every five minutes.
        loaded_system_equity = None
        loaded_last_broker_equity = None
        # Epoch = the date the system ledger started counting. Without it, "net P&L
        # -$6" reads as "paper is flat" when the broker is thousands away from where
        # paper began — the ledger legitimately starts at its own epoch, but nothing
        # said so on screen.
        loaded_system_epoch = None
        loaded_paper_start = None
        if self._positions_path is not None and self._positions_path.exists():
            try:
                with open(self._positions_path, encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    # legacy format: plain list of positions (schema_version 0, no breaker state)
                    loaded_positions = [_openpos_from_dict(d) for d in raw]
                else:
                    sv = raw.get("schema_version", 0)
                    if sv not in (0, 1):
                        logger.warning(
                            "B1: unrecognised schema_version=%s in %s — proceeding anyway",
                            sv, self._positions_path,
                        )
                    loaded_positions = [_openpos_from_dict(d)
                                        for d in raw.get("positions", [])]
                    bkr = raw.get("breaker", {})
                    if bkr.get("peak_equity") is not None:
                        loaded_peak_equity = float(bkr["peak_equity"])
                    if bkr.get("day_start_equity") is not None:
                        loaded_day_start_equity = float(bkr["day_start_equity"])
                    if bkr.get("cur_day"):
                        loaded_cur_day = pd.Timestamp(bkr["cur_day"])
                    if bkr.get("system_equity") is not None:
                        loaded_system_equity = float(bkr["system_equity"])
                    if bkr.get("last_broker_equity") is not None:
                        loaded_last_broker_equity = float(bkr["last_broker_equity"])
                    if bkr.get("system_epoch"):
                        loaded_system_epoch = str(bkr["system_epoch"])
                    # Operator-recorded, never inferred: what the broker account held
                    # when paper trading began. The system ledger cannot derive it —
                    # it starts at ACCOUNT and knows nothing before its own epoch.
                    if isinstance(bkr.get("paper_start"), dict):
                        loaded_paper_start = dict(bkr["paper_start"])
                    # Files written before the system-equity fix carry a peak_equity
                    # taken from the broker balance ($995k on paper). Restoring it would
                    # keep the breaker on the wrong scale forever, so drop it and let the
                    # breaker re-peak from system equity.
                    if loaded_system_equity is None and loaded_peak_equity is not None \
                            and breaker is not None \
                            and loaded_peak_equity > breaker.account * 5:
                        logger.warning(
                            "B1: discarding persisted peak_equity=$%.2f — recorded against "
                            "broker balance, not the $%.0f system base. Breaker will "
                            "re-peak from system equity.",
                            loaded_peak_equity, breaker.account,
                        )
                        loaded_peak_equity = None
                        loaded_day_start_equity = None
                logger.info(
                    "B1: loaded %d persisted position(s) from %s",
                    len(loaded_positions), self._positions_path,
                )
                # B3: cross-check loaded positions against live broker state.
                # IBKR is the ground truth for what's actually open; the JSON
                # file is our metadata store (cluster, entry_day, pnl_sized).
                # Mismatch = potential orphan order from a prior crash → CRITICAL.
                try:
                    broker_pos = broker.get_positions()
                    # Even retry-until-stable inside get_positions() cannot guarantee
                    # true settlement if both reads landed before IB pushed data.
                    # When file says positions exist but broker shows none, surface it
                    # before the per-position mismatch loop — the loop will halt entries
                    # via STP-VERIFY if the fill cannot be confirmed, but this banner
                    # makes the ambiguity visible first so operators see it clearly.
                    if not broker_pos and loaded_positions:
                        logger.warning(
                            "B3 EMPTY-WARN: IBKR returned 0 positions but file has %d. "
                            "Possible subscription settle lag (retry-stable cannot guarantee "
                            "true settlement). Per-position check follows: entries HALT unless "
                            "STP fill is confirmed via reqExecutions (only confirmed exit resumes).",
                            len(loaded_positions),
                        )
                    # Index broker positions by (inst, direction) for fast lookup.
                    broker_key = {(p.inst, p.direction): p.contracts for p in broker_pos}
                    file_key   = {}
                    for p in loaded_positions:
                        k = (p.inst, p.direction)
                        file_key[k] = file_key.get(k, 0) + p.contracts
                    mismatches = 0
                    # Build lookup: (inst, direction) → list of loaded OpenPos
                    _file_pos_by_key: dict = {}
                    for _lp in loaded_positions:
                        _file_pos_by_key.setdefault((_lp.inst, _lp.direction), []).append(_lp)

                    for k, qty in file_key.items():
                        broker_qty = broker_key.get(k, 0)
                        if broker_qty != qty:
                            # B3 STP-aware: if the mismatched position has a stop_order_id,
                            # check whether it filled overnight (expected exit, not orphan).
                            _stp_cand = next(
                                (p for p in _file_pos_by_key.get(k, []) if p.stop_order_id),
                                None,
                            )
                            _stp_status = None
                            if _stp_cand is not None:
                                try:
                                    _stp_status = broker.get_order_status(_stp_cand.stop_order_id)
                                except Exception:
                                    pass

                            if _stp_status == "FILLED":
                                # STP triggered overnight — clean up state, no halt needed.
                                #
                                # This branch used to clear the position and nothing else,
                                # while the rarer NOT_FOUND fallback below booked the P&L
                                # and wrote the CLOSE record. That is backwards: a stop
                                # reporting FILLED is the COMMON exit — chandelier stops
                                # are ~79.5% of exits — so the ledger the circuit breaker
                                # reads never moved for most trades, and the trade log
                                # showed 13 OPEN against 6 CLOSE. _book_realised's own
                                # docstring warns about exactly that: an equity that never
                                # happened, with the breaker sizing risk against it.
                                _stp_fill = None
                                try:
                                    _stp_fill = broker.find_execution(_stp_cand.stop_order_id)
                                except Exception as _e:
                                    logger.error("B3 STP EXIT: find_execution(%s) raised: %s",
                                                 _stp_cand.stop_order_id, _e)
                                if _stp_fill:
                                    _stp_fill["_src"] = "B3_STP_EXIT"
                                    _pending_stop_exits.append((_stp_cand, _stp_fill))
                                    logger.info(
                                        "B3 STP EXIT: %s %s stop orderId=%s filled @ %.4f "
                                        "(dat @ %.4f, truot %.4f) — da ghi so",
                                        k[1], k[0], _stp_cand.stop_order_id,
                                        float(_stp_fill.get("price") or 0.0),
                                        _stp_cand.stop_price or 0.0,
                                        (float(_stp_fill.get("price") or 0.0)
                                         - (_stp_cand.stop_price or 0.0)),
                                    )
                                else:
                                    # IBKR says FILLED, so the position IS closed; leaving
                                    # the ledger untouched is wrong in the other direction.
                                    # Book at the level that was placed and SAY it is an
                                    # estimate — a silent approximation is how a ledger
                                    # drifts without anyone noticing.
                                    _pending_stop_exits.append((_stp_cand, None))
                                    logger.warning(
                                        "B3 STP EXIT: %s %s stop orderId=%s FILLED nhung "
                                        "khong lay duoc gia khop (reqExecutions quen sau "
                                        "~2 ngay). Ghi so theo muc DA DAT %.4f — la UOC "
                                        "LUONG, khong phai gia khop that.",
                                        k[1], k[0], _stp_cand.stop_order_id,
                                        _stp_cand.stop_price or 0.0,
                                    )
                                loaded_positions[:] = [
                                    p for p in loaded_positions if p is not _stp_cand]
                            elif _stp_cand is not None and _stp_status == "NOT_FOUND" and broker_qty == 0:
                                # NOT_FOUND + broker_qty==0: position gone, but cause unknown.
                                # Do NOT infer — multiple paths close a position besides STP:
                                #   manual close, margin liquidation, rollover, or a transient
                                #   get_positions() glitch (subscription not yet settled).
                                # Glitch is the worst case: we'd clean state while the position
                                # is still open → double-entry on next signal → uncontrolled risk.
                                # VERIFY via reqExecutions() (IB server history, survives restart).
                                _fill_verified = False
                                try:
                                    _fill_verified = broker.find_execution(_stp_cand.stop_order_id)
                                except Exception:
                                    pass

                                if _fill_verified:
                                    logger.info(
                                        "B3 STP-VERIFY: %s %s orderId=%s fill confirmed via "
                                        "reqExecutions — position cleared from state "
                                        "(stop_price=%.4f).",
                                        k[1], k[0], _stp_cand.stop_order_id,
                                        _stp_cand.stop_price or 0.0,
                                    )
                                    _pending_stop_exits.append((_stp_cand, _fill_verified))
                                    loaded_positions[:] = [
                                        p for p in loaded_positions if p is not _stp_cand]
                                else:
                                    logger.critical(
                                        "B3 HALT: %s %s IBKR ×0 + orderId=%s NOT_FOUND + "
                                        "no fill record in reqExecutions. Position gone for "
                                        "unknown reason (manual close / liquidation / rollover "
                                        "/ transient glitch). "
                                        "OPERATOR: check TWS executions; if STP filled, "
                                        "remove entry from live_positions.json and restart; "
                                        "if position still open, investigate. "
                                        "New entries disabled until resolved.",
                                        k[1], k[0], _stp_cand.stop_order_id,
                                    )
                                    mismatches += 1
                            elif _stp_cand is not None:
                                logger.critical(
                                    "B3 MISMATCH: file has %s %s ×%d but IBKR shows ×%d "
                                    "— stop orderId=%s status=%s; "
                                    "STP may have triggered overnight — check TWS executions. "
                                    "If STP filled: remove position from live_positions.json "
                                    "and restart. If not: investigate crash/orphan.",
                                    k[1], k[0], qty, broker_qty,
                                    _stp_cand.stop_order_id, _stp_status,
                                )
                                mismatches += 1
                            else:
                                logger.critical(
                                    "B3 MISMATCH: file has %s %s ×%d but IBKR shows ×%d "
                                    "— investigate before trading; file state will be used",
                                    k[1], k[0], qty, broker_qty,
                                )
                                mismatches += 1
                    for k, qty in broker_key.items():
                        if k not in file_key:
                            logger.critical(
                                "B3 ORPHAN: IBKR has %s %s ×%d with no matching file entry "
                                "— position opened outside this runner?",
                                k[1], k[0], qty,
                            )
                            mismatches += 1
                    # B4: naked-position check — position agrees on BOTH sides but has
                    # no stop order. B3 above compares only inst/direction/contracts, so
                    # an unprotected position passes it silently.
                    #
                    # Seen live 2026-08-03: send_order() misread three filled OPENs as
                    # status="Cancelled", so the STP block in run_day() (gated on
                    # FILLED/PARTIAL) never ran. Three positions carried overnight with
                    # no stop and no alert — the failure log lives *inside* that same
                    # gate, so nothing fired.
                    #
                    # Not a halt condition: state here is certain (both sides agree), and
                    # blocking entries would not protect the position that is already
                    # open. Alert loudly, re-place where provably safe, keep trading.
                    # A recorded stop_order_id is NOT evidence of a working stop.
                    # place_stop used to mint the id client-side, so on 2026-08-05
                    # three naked positions carried ids 62/66/70 and this guard —
                    # written for exactly that failure — stayed silent. Ask the broker.
                    # None from get_working_stops means "cannot say": fall back to the
                    # recorded field rather than calling every position naked (MockBroker
                    # answers None, which keeps reconcile behaviour unchanged).
                    try:
                        _working = broker.get_working_stops()
                    except (NotImplementedError, AttributeError):
                        _working = None
                    except Exception as _e:
                        _working = None
                        logger.error("B4: get_working_stops() failed: %s", _e)
                    # A position still inside its deliberate stop-free window is NOT
                    # naked — see _stop_deferred. Without this line B4 re-places the stop
                    # on the next slot, the window shrinks to ~5 minutes, and the fix
                    # above achieves nothing. The exclusion lapses on its own the moment
                    # the entry day passes, so the same loop is what finally places the
                    # stop: no new job, and a genuinely lost stop is still caught.
                    # The expiry-aware authority. has_working_stop matches on SYMBOL, so
                    # after a roll whose cancel failed it counts the dead contract's STP as
                    # protection for the position on the new contract — B4 then reports
                    # "covered" (STP ID DRIFT, a warning) about a position that is bare.
                    # unprotected_positions matches on (symbol, expiry, side) and sums
                    # contracts, so where the two disagree this one is right.
                    # None means the broker cannot say; then nothing is overridden and the
                    # symbol-level answer stands, which is what ran before.
                    try:
                        _unprot = broker.unprotected_positions()
                    except (NotImplementedError, AttributeError):
                        _unprot = None
                    except Exception as _e:
                        _unprot = None
                        logger.error("B4: unprotected_positions() failed: %s", _e)
                    _unprot_insts = (None if _unprot is None
                                     else {u["inst"] for u in _unprot})

                    _deferred = [p for p in loaded_positions if self._stop_deferred(p)]
                    for p in _deferred:
                        logger.info(
                            "B4: %s/%s chua co STP — dang trong cua so hoan CO CHU DICH "
                            "(vao ngay %s). Se dat o lan chay dau tien ngay ke tiep.",
                            p.inst, p.cluster,
                            pd.Timestamp(p.entry_day).date() if p.entry_day else "?",
                        )
                    # "Is the order THIS position recorded still working" — not "does a
                    # stop exist on this symbol". The symbol form marks a position
                    # protected by a stop belonging to another position on the same
                    # contract; the id form cannot. See OPERATIONS.md, "STRESS_MID".
                    _live_ids = (None if _working is None
                                 else {str(i) for v in _working.values() for i in v})
                    naked = [p for p in loaded_positions
                             if broker_key.get((p.inst, p.direction), 0) > 0
                             and not self._stop_deferred(p)
                             and (p.stop_order_id is None
                                  or (_live_ids is not None
                                      and str(p.stop_order_id) not in _live_ids))]
                    self._b4_naked_stops = [(p.inst, p.cluster) for p in naked]
                    for p in naked:
                        # Only re-place when the level is known AND this position is not
                        # already covered at the broker. Either unknown → alert, never
                        # guess: a duplicate STP would close the position twice and flip it.
                        _covered = None            # None = broker cannot say
                        try:
                            _covered = broker.has_working_stop(
                                p.inst, p.direction, p.contracts)
                        except (NotImplementedError, AttributeError):
                            logger.warning(
                                "B4: %s/%s — broker cannot report working stops; "
                                "not re-placing (duplicate-stop risk)", p.inst, p.cluster)
                        except Exception as _e:
                            logger.error("B4: has_working_stop(%s) failed: %s", p.inst, _e)

                        if _covered and _unprot_insts is not None and p.inst in _unprot_insts:
                            # Symbol-level says covered, contract-level says bare. Trust the
                            # contract: the stop it found belongs to another expiry.
                            logger.warning(
                                "B4: %s/%s — has_working_stop says covered but "
                                "unprotected_positions reports the contract bare (stop is on "
                                "another expiry). Treating as NAKED.", p.inst, p.cluster)
                            _covered = False

                        if _covered:
                            # Covered, but by an order this position does not name. That
                            # is drift, not nakedness, and the difference has to survive
                            # into the log: shouting NAKED at a protected position every
                            # slot is how the word stops being read, and the next alert
                            # that means it goes unnoticed.
                            #
                            # Worth its own line rather than silence — the old check
                            # (`p.inst in working`) said nothing here, and that silence is
                            # what let MES carry the fabricated id 62 beside working stop
                            # #9 on 2026-08-05 until the close cancelled a ghost and
                            # orphaned the live order.
                            logger.warning(
                                "B4 STP ID DRIFT: %s %s x%d (%s) IS covered at the broker, "
                                "but the recorded stop_order_id=%s names no working order. "
                                "Not re-placing (that would stack a duplicate). OPERATOR: "
                                "run repair_stops.py to correct the recorded id — on close "
                                "the runner would otherwise cancel a ghost and leave the "
                                "real stop working with no position behind it.",
                                p.direction, p.inst, p.contracts, p.cluster, p.stop_order_id,
                            )
                            continue

                        _can_replace = p.stop_price is not None and _covered is False
                        if _can_replace:
                            try:
                                _sid = broker.place_stop(p.inst, p.direction, p.contracts,
                                                         p.stop_price, p.cluster)
                            except Exception as _e:
                                _sid = ""
                                logger.error("B4: place_stop(%s/%s) raised: %s",
                                             p.inst, p.cluster, _e)
                            if _sid:
                                p.stop_order_id = _sid
                                logger.warning(
                                    "B4 REPLACED: %s/%s was open with no stop order "
                                    "— re-placed @ %.4f orderId=%s",
                                    p.inst, p.cluster, p.stop_price, _sid,
                                )
                                continue

                        logger.critical(
                            "B4 NAKED: %s %s x%d (%s) open at IBKR with NO stop order "
                            "(stop_price=%s). No overnight protection. OPERATOR: recompute "
                            "the chandelier level (p0c_verify_swing.py) and place the STP "
                            "manually in TWS, or close the position.",
                            p.direction, p.inst, p.contracts, p.cluster, p.stop_price,
                        )

                    if mismatches == 0:
                        logger.info("B3: broker/file positions match (%d position(s))", len(broker_pos))
                    else:
                        self._b3_halt_entries = True
                        logger.critical(
                            "B3: %d mismatch(es) — new entries HALTED until resolved. "
                            "Verify live_positions.json matches IBKR, then restart.",
                            mismatches,
                        )
                except NotImplementedError:
                    logger.info("B3: broker.get_positions() not available — skipping cross-check")
                except Exception as _exc:
                    logger.warning("B3: cross-check failed (%s) — proceeding with file state", _exc)
            except Exception as exc:
                logger.warning(
                    "B1: failed to load %s (%s) — fresh start; "
                    "manually verify broker has no orphaned positions",
                    self._positions_path, exc,
                )
                loaded_positions = []
                loaded_peak_equity = None
                loaded_day_start_equity = None
                loaded_cur_day = None

        # H2: discard positions with invalid values — contracts≤0 or risk_dollars<0
        # indicate file corruption; these would silently produce wrong pnl and
        # guard-cap calculations downstream.
        if loaded_positions:
            _valid = [p for p in loaded_positions
                      if p.contracts > 0 and p.risk_dollars >= 0]
            if len(_valid) < len(loaded_positions):
                for _p in loaded_positions:
                    if _p.contracts <= 0 or _p.risk_dollars < 0:
                        logger.warning(
                            "H2: discarding corrupt position %s/%s "
                            "(contracts=%s, risk_dollars=%s) — verify live_positions.json",
                            _p.inst, _p.cluster, _p.contracts, _p.risk_dollars,
                        )
                loaded_positions = _valid

        # Operational event log + live state path (_events initialised at the top of
        # __init__ — B3 can emit before this point)
        self._last_breaker_level: str = "OK"
        self._live_state_path = Path(live_state_path) if live_state_path else None
        # Accumulated daily equity marks — the live equity curve the metrics bar
        # needs. Defaults next to the state file so the two travel together.
        if paper_history_path:
            self._paper_history_path = Path(paper_history_path)
        elif self._live_state_path is not None:
            self._paper_history_path = self._live_state_path.with_name("paper_history.json")
        else:
            self._paper_history_path = None

        # D5: kill-switch (STOP_FILE) + F3: fat-finger cap
        self._stop_path = Path(stop_path) if stop_path else None
        self._max_contracts = int(max_contracts_per_order)

        # C1: cumulative signed slippage (persisted next to positions_path as slip_stats.json)
        self._slip_stats_path = (
            Path(positions_path).parent / "slip_stats.json" if positions_path else None
        )
        self._slip_open_sum: float = 0.0
        self._slip_open_n: int = 0
        self._slip_close_sum: float = 0.0
        self._slip_close_n: int = 0
        if self._slip_stats_path is not None and self._slip_stats_path.exists():
            try:
                with open(self._slip_stats_path, encoding="utf-8") as _f:
                    _ss = json.load(_f)
                self._slip_open_sum = float(_ss.get("open_sum", 0.0))
                self._slip_open_n   = int(_ss.get("open_n", 0))
                self._slip_close_sum = float(_ss.get("close_sum", 0.0))
                self._slip_close_n   = int(_ss.get("close_n", 0))
                logger.debug(
                    "C1: loaded slip_stats — OPEN mean=%+.4f N=%d  CLOSE mean=%+.4f N=%d",
                    self._slip_open_sum / self._slip_open_n if self._slip_open_n else 0.0,
                    self._slip_open_n,
                    self._slip_close_sum / self._slip_close_n if self._slip_close_n else 0.0,
                    self._slip_close_n,
                )
            except Exception as _exc:
                logger.warning("C1: could not load slip_stats.json: %s", _exc)

        self.broker = broker
        self.guard = guard
        self.contracts = contracts_by_inst
        self.signal_fn = signal_fn
        self._hmm_stale_guard = hmm_stale_guard
        # SYSTEM equity, not broker equity. The broker balance is whatever the account
        # happens to be funded with — on the paper account, $995k — while this system is
        # designed, backtested and sized for RISK["account"] ($50,000) at one micro
        # contract. Feeding the broker balance to the circuit breaker made every
        # protective threshold 20x too far away: losing the ENTIRE $50,000 design capital
        # registered as 5% drawdown, i.e. HALT_DAY instead of HALT, and the hard 15% stop
        # would have needed a $149,300 loss. Measured in scratchpad/sim_breaker_base.py.
        #
        # deploy_sim is the reference and does this correctly: equity starts at `account`
        # and accumulates realised P&L. The live path now matches, so breaker behaviour is
        # the same in backtest and live. The broker is still read every cycle — but only
        # for its DELTA (see H4) and for reconciliation, never as the risk denominator.
        _sys_eq = (loaded_system_equity if loaded_system_equity is not None
                   else float(breaker.account) if breaker is not None
                   else broker.get_equity())
        self._last_broker_equity = (loaded_last_broker_equity
                                    if loaded_last_broker_equity is not None
                                    else broker.get_equity())
        self._system_epoch = loaded_system_epoch
        self._paper_start = loaded_paper_start
        self.state = DecisionState(
            equity=_sys_eq,
            open_positions=loaded_positions,
            taken={c: 0 for c in guard.clusters},
            rejected={c: 0 for c in guard.clusters},
            breaker=breaker)
        # Drain the stop exits B3 found. Here, not there: self.state is what
        # _book_realised moves, and it did not exist while B3 was running.
        for _sp, _sf in _pending_stop_exits:
            try:
                if _sf:
                    self._book_realised(_sp, _sf.get("price"),
                                        int(_sf.get("shares") or 0) or None, why="stop")
                    self._record_stop_exit(_sp, _sf, source=_sf.get("_src")
                                           or "B3_STP_VERIFY")
                else:
                    # IBKR said FILLED but the fill record is gone; the position IS
                    # closed, so booking the placed level beats leaving the ledger
                    # stale. Already logged as an estimate at the discovery site.
                    self._book_realised(_sp, _sp.stop_price, why="stop")
            except Exception as _e:
                logger.error(
                    "B3: khong ghi so duoc lenh stop %s/%s (%s) — SO SLEECH LECH so voi "
                    "thuc te, breaker dang doc equity sai. Kiem tay.",
                    _sp.inst, _sp.cluster, _e)

        logger.info("B1: system equity=$%.2f (base=$%.0f) | broker=$%.2f — "
                    "risk thresholds measured against SYSTEM equity",
                    _sys_eq, float(breaker.account) if breaker is not None else 0.0,
                    self._last_broker_equity)

        # Restore breaker state — prevents peak_equity resetting to current on restart.
        # Without restore: peak=current → DD=0% even when real DD is 12%+ → HALT blind.
        if breaker is not None and loaded_peak_equity is not None:
            breaker.peak_equity = loaded_peak_equity
            _cur_eq = self.state.equity      # system equity — same scale as peak_equity
            _dd_pct = (loaded_peak_equity - _cur_eq) / loaded_peak_equity * 100
            logger.info(
                "B1: restored breaker peak_equity=$%.2f (current=$%.2f, DD=%.1f%% — "
                "HALT at %.0f%%)",
                loaded_peak_equity, _cur_eq, _dd_pct, breaker.hard_dd_pct * 100,
            )
        if breaker is not None and loaded_day_start_equity is not None:
            breaker._day_start_equity = loaded_day_start_equity
        if loaded_cur_day is not None:
            self.state.cur_day = loaded_cur_day

        self._emit_event(
            "INFO", "STATE",
            f"Runner started: loaded {len(self.state.open_positions)} position(s) "
            f"from {'persisted file' if self._positions_path and self.state.open_positions else 'fresh state'}",
        )

    # ── C1: slip stats persistence ──────────────────────────────────────────

    def _persist_slip_stats(self) -> None:
        if self._slip_stats_path is None:
            return
        try:
            _tmp = self._slip_stats_path.with_suffix(".tmp")
            with open(_tmp, "w", encoding="utf-8") as _f:
                json.dump({
                    "open_sum":  self._slip_open_sum,
                    "open_n":    self._slip_open_n,
                    "close_sum": self._slip_close_sum,
                    "close_n":   self._slip_close_n,
                }, _f)
            os.replace(str(_tmp), str(self._slip_stats_path))
        except Exception as _exc:
            logger.warning("C1: could not persist slip_stats.json: %s", _exc)

    def _book_realised(self, pos, exit_price: float, contracts: int | None = None,
                       *, why: str) -> float:
        """Add a live close's realised P&L to the sleeve ledger. Returns what it added.

        The ledger is the sleeve's own P&L and nothing else. It used to be moved by H4,
        which added the delta of the WHOLE account's NetLiquidation — measured
        2026-08-07, broker 997,756.40 − 997,395.69 = +360.71 against ledger
        52,212.33 − 51,851.62 = +360.71, identical. On a CAD account of ~$997k, twenty
        times the sleeve, that swept in a monthly interest credit of +1,374.32, the same
        size as the entire realised trading P&L for the week.

        Realised only, no mark-to-market, because deploy_sim.replay is
        `equity += t["pnl_sized"]` and every number in the IS baseline came from that.
        A live ledger on a different convention makes paper-vs-backtest a comparison of
        two different quantities and fires the breaker under conditions it was never
        validated against.

        A position with no entry_price cannot be valued. Booking zero would understate
        the move and leave the breaker reading an equity that never happened, so it is
        reported and skipped.
        """
        n = int(contracts or pos.contracts or 0)
        if pos.entry_price is None or not exit_price or n <= 0:
            logger.critical(
                "UNPRICEABLE CLOSE: %s/%s %s x%s (%s) — entry_price=%s exit=%s. Realised "
                "P&L not booked; the sleeve ledger is now short by this trade. Recover "
                "the fills with reconcile_statement.py and rebase.",
                pos.inst, pos.cluster, pos.direction, n, why, pos.entry_price, exit_price,
            )
            self._emit_event(
                "CRITICAL", "STATE",
                f"UNPRICEABLE CLOSE: {pos.inst}/{pos.cluster} — realised P&L not booked",
                {"inst": pos.inst, "cluster": pos.cluster,
                 "entry_price": pos.entry_price, "exit_price": exit_price},
            )
            return 0.0

        from global_index.statement import point_value
        pv = point_value(pos.inst)
        if not pv:
            logger.critical("UNPRICEABLE CLOSE: no point value on record for %s", pos.inst)
            return 0.0

        pnl = ((float(exit_price) - float(pos.entry_price)) * pv * n
               * (1 if pos.direction == "LONG" else -1))
        pos.pnl_sized = pnl
        self.state.equity += pnl
        if self.state.breaker is not None:
            self.state.breaker.update(self.state.equity)
        logger.info(
            "LEDGER: %s %s x%d %s %.4f → %.4f = %+.2f (%s) | sleeve equity %.2f",
            pos.inst, pos.direction, n, pos.cluster,
            pos.entry_price, exit_price, pnl, why, self.state.equity,
        )
        return pnl

    def _record_stop_exit(self, pos, fill: dict, source: str = "B3_STP_VERIFY") -> None:
        """Write the CLOSE record for a stop that fired at the broker.

        Nothing else writes one. The runner sends no order when a stop triggers, so the
        send_order path that logs every other fill never runs, and chandelier stops are
        79.5% of exits — this is the exit price for most trades.

        It has to happen here because this is the only moment both halves exist: IBKR
        has just handed back the fill (price, size, time, permId) and the runner is
        holding the position it belongs to (cluster, direction, entry_day, contracts),
        which IBKR knows nothing about. Measured 2026-08-07: reqExecutions served a fill
        on the day it happened and had forgotten it by the next.

        exit_day comes from the fill's own timestamp, not from now: a stop that fired
        overnight is noticed the next morning, and dating it to the reconcile would put
        the trade on the wrong day.

        Never raises. This runs inside startup reconcile; losing a log line must not
        stop the runner from clearing state and trading.
        """
        try:
            _t = str(fill.get("time") or "")
            _exit_day = None
            if _t:
                try:
                    _exit_day = str(pd.Timestamp(_t).date())
                except Exception:
                    _exit_day = _t[:10] or None
            self._append_trade({
                "type": "CLOSE",
                "inst": pos.inst,
                "cluster": pos.cluster,
                "direction": pos.direction,
                "contracts": pos.contracts,
                "entry_day": str(pd.Timestamp(pos.entry_day).date()) if pos.entry_day else None,
                "exit_day": _exit_day,
                "exit_reason": "STP",
                "expected_stop": pos.stop_price,
                "fill_price": fill.get("price"),
                "filled_qty": fill.get("shares"),
                "order_id": fill.get("order_id"),
                "perm_id": fill.get("perm_id"),
                "status": "FILLED",
                "source": source,
            })
            logger.info(
                "B3 STP-VERIFY: recorded stop exit %s/%s @ %.4f (permId=%s) — "
                "nothing else writes a trade record for a stop fill",
                pos.inst, pos.cluster, float(fill.get("price") or 0.0), fill.get("perm_id"),
            )
        except Exception as exc:
            logger.error("could not record stop exit for %s/%s: %s — the exit price is "
                         "lost once IBKR drops it from reqExecutions",
                         pos.inst, pos.cluster, exc)

    def _append_trade(self, record: dict) -> None:
        if self._trade_log_path is None:
            return
        record.setdefault("ts", pd.Timestamp.now("UTC").isoformat())
        try:
            with open(self._trade_log_path, "a", encoding="utf-8") as _f:
                _f.write(json.dumps(record) + "\n")
        except Exception as _exc:
            logger.warning("trade_log: could not append to %s: %s", self._trade_log_path, _exc)

    # ── B1: atomic state persistence ────────────────────────────────────────

    def _persist_state(self) -> None:
        """Atomically write open_positions + breaker state (peak_equity, day_start_equity,
        cur_day) to JSON. Restoring breaker state on restart prevents DD resetting to 0.
        write-to-.tmp + os.replace: atomic on POSIX; best-effort on Windows."""
        if self._positions_path is None:
            return
        positions_data = [_openpos_to_dict(p) for p in self.state.open_positions]
        breaker_data: dict = {}
        if self.state.breaker is not None:
            breaker_data["peak_equity"] = self.state.breaker.peak_equity
            if self.state.breaker._day_start_equity is not None:
                breaker_data["day_start_equity"] = self.state.breaker._day_start_equity
        if self.state.cur_day is not None:
            breaker_data["cur_day"] = str(pd.Timestamp(self.state.cur_day).date())
        # Every cron slot is a separate process, so the system ledger and the broker mark
        # it was last reconciled against must both survive on disk. Without them, equity
        # would reset to base each slot and H4 would re-book the same P&L every five
        # minutes.
        breaker_data["system_equity"] = self.state.equity
        breaker_data["last_broker_equity"] = self._last_broker_equity
        if self._system_epoch:
            breaker_data["system_epoch"] = self._system_epoch
        if self._paper_start:
            breaker_data["paper_start"] = self._paper_start
        payload = {"schema_version": 1, "positions": positions_data, "breaker": breaker_data}
        try:
            tmp = self._positions_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(str(tmp), str(self._positions_path))
        except Exception as exc:
            logger.error(
                "B1: state persist failed (%s) — state may not survive restart", exc
            )
            self._emit_event(
                "ALERT", "STATE",
                "B1: persist failed — state may not survive restart",
                {"error": str(exc)[:80]},
            )

    # ── retry pending exits ───────────────────────────────────────────────────

    def _retry_pending_exits(self, day) -> None:
        """Retry positions flagged exit_pending=True from a prior session's failed CLOSE.
        Called at the start of run_day() before decide_day so failed exits are retried
        before new decisions are made.

        Live: IBKRBroker.send_order(CLOSE) returns Fill.status indicating success/fail.
        Verify (MockBroker): all fills succeed (status="FILLED") → no exit_pending in
        practice → this method is a no-op in offline/test mode.
        """
        pending = [p for p in self.state.open_positions
                   if getattr(p, "exit_pending", False)]
        if not pending:
            return
        logger.warning(
            "_retry_pending_exits: %d position(s) exit_pending=True on %s",
            len(pending), pd.Timestamp(day).date(),
        )
        self._emit_event(
            "ALERT", "EXEC",
            f"retry_pending_exits: {len(pending)} CLOSE(s) retrying",
            {"count": len(pending), "day": str(pd.Timestamp(day).date())},
        )
        for p in list(pending):
            _f = self.broker.send_order(Order(
                p.inst, "CLOSE", p.direction, p.contracts, p.cluster, day,
                exit_day=day, pnl_sized=p.pnl_sized,
            ))
            if _f.status != "FAILED":
                p.exit_pending = False
                self.state.open_positions = [
                    x for x in self.state.open_positions if x is not p
                ]
                # Verify mode books the ledger's pnl_sized; live has 0.0 there and is
                # valued from the fill instead (MockBroker leaves avg_price at 0.0, so
                # only one of these two ever fires).
                self.state.equity += p.pnl_sized
                if _f.avg_price > 0:
                    self._book_realised(p, _f.avg_price, _f.filled_qty or p.contracts,
                                        why="retry exit")
                logger.info(
                    "_retry: CLOSE success %s/%s — exit_pending cleared", p.inst, p.cluster,
                )
            else:
                logger.error(
                    "_retry: CLOSE still FAILED %s/%s — manual intervention may be required",
                    p.inst, p.cluster,
                )
                self._emit_event(
                    "ALERT", "EXEC",
                    f"retry_pending_exits: CLOSE still FAILED {p.inst}/{p.cluster}",
                    {"inst": p.inst, "cluster": p.cluster, "error": _f.error_msg or ""},
                )

    def run_maxhold_exit(self, day, max_hold_days: int = 5) -> list:
        """09:30 ET cron: close any position that has reached max_hold_days at RTH open.

        Called from a separate 09:31 ET cron (run_maxhold_exit.py) BEFORE the main
        14:05 ET run_day(). Positions closed here are removed from state.open_positions
        so run_day() does not see them and will not attempt a second close.

        If a CLOSE fails, the position stays with exit_pending=True so _retry_pending_exits()
        at the next run_day() retries it (at 14:05 ET).

        Returns list of (inst, cluster) pairs that were successfully closed.
        """
        today = pd.Timestamp(day).normalize()
        closed = []
        for p in list(self.state.open_positions):
            if p.entry_day is None:
                continue
            hold = (today - pd.Timestamp(p.entry_day).normalize()).days
            if hold < max_hold_days:
                continue
            logger.info(
                "MAX_HOLD_EXIT: %s/%s held=%d days >= %d — closing at RTH open",
                p.inst, p.cluster, hold, max_hold_days,
            )
            _f = self.broker.send_order(Order(
                p.inst, "CLOSE", p.direction, p.contracts, p.cluster, day,
                exit_day=day, pnl_sized=p.pnl_sized,
            ))
            if _f.status != "FAILED":
                if p.stop_order_id is not None:
                    try:
                        # Returns False on failure; it does not raise. See
                        # _report_stop_cancel.
                        _cancelled = self.broker.cancel_order(p.stop_order_id)
                    except Exception as _e:
                        _cancelled = False
                        logger.error(
                            "MAX_HOLD_EXIT: cancel_order(%s) raised for %s/%s: %s",
                            p.stop_order_id, p.inst, p.cluster, _e,
                        )
                    self._report_stop_cancel(_cancelled, p)
                self.state.equity += p.pnl_sized
                if _f.avg_price > 0:
                    self._book_realised(p, _f.avg_price, _f.filled_qty or p.contracts,
                                        why="max hold")
                self.state.open_positions = [
                    x for x in self.state.open_positions if x is not p
                ]
                closed.append((p.inst, p.cluster))
                logger.info("MAX_HOLD_EXIT: closed %s/%s", p.inst, p.cluster)
            else:
                p.exit_pending = True
                logger.error(
                    "MAX_HOLD_EXIT: CLOSE FAILED %s/%s — exit_pending=True, "
                    "will retry at 14:05 ET run_day()",
                    p.inst, p.cluster,
                )
                self._emit_event(
                    "ALERT", "EXEC",
                    f"MAX_HOLD_EXIT: CLOSE FAILED {p.inst}/{p.cluster} — retry at 14:05",
                    {"inst": p.inst, "cluster": p.cluster, "hold_days": hold},
                )
        self._persist_state()
        return closed

    def _handle_rollover_if_needed(self, day) -> None:
        """C2: Roll open positions whose contract expires today (roll date per ROLL_SCHEDULE).

        Called at the start of run_day(), before fetch_bars, so the signal layer
        sees the new contract on its first bar.

        Delegates to broker._handle_rollover() — only IBKRBroker implements this;
        MockBroker has no such method so offline runs are no-ops.

        Fill outcome actions:
          (FILLED, FILLED) → log slippage, position continues unchanged.
          (FAILED, *)      → CLOSE did not execute; position stays in old contract;
                             log CRITICAL and leave state untouched (IBKR still holds it).
          (FILLED, FAILED) → CLOSE succeeded but OPEN timed out; position is NOW FLAT
                             in IBKR but still in runner state. Remove from state and
                             emit CRITICAL so operator can intervene manually.
        """
        _roll_fn = getattr(self.broker, "_handle_rollover", None)
        if _roll_fn is None:
            return  # MockBroker — rollover not applicable offline

        for pos in list(self.state.open_positions):
            result = _roll_fn(pos.inst, day, pos.direction, pos.contracts, pos.cluster)
            if result is None:
                continue  # not a roll date for this instrument

            close_fill, open_fill = result

            if close_fill.status != "FILLED":
                # CLOSE did not execute — position still in old contract in IBKR
                logger.critical(
                    "C2: Roll CLOSE FAILED %s %s — position unchanged. Error: %s",
                    pos.inst, pos.direction, close_fill.error_msg,
                )
                self._emit_event(
                    "CRITICAL", "ROLLOVER",
                    f"C2: Roll CLOSE failed {pos.inst} {pos.direction} ×{pos.contracts} — "
                    f"position unchanged. {close_fill.error_msg}",
                )
                continue

            if open_fill.status != "FILLED":
                # CLOSE OK but OPEN failed — position is FLAT in IBKR
                logger.critical(
                    "C2: Roll OPEN FAILED %s %s after CLOSE succeeded — "
                    "position is FLAT IN IBKR. Removing from runner state. "
                    "Manual verification required. Error: %s",
                    pos.inst, pos.direction, open_fill.error_msg,
                )
                self._emit_event(
                    "CRITICAL", "ROLLOVER",
                    f"C2: Roll OPEN failed {pos.inst} {pos.direction} ×{pos.contracts} "
                    f"AFTER CLOSE — position FLAT in IBKR. Removed from state. "
                    f"{open_fill.error_msg}",
                )
                # I5.13: persist immediately — front-month closed, OPEN failed, irreversible.
                # JSON must reflect flat truth before any crash-window; operator needs
                # accurate state now (B3 on restart catches JSON-vs-IBKR mismatch, but
                # a stale JSON "has position" confuses manual recovery when IBKR is flat).
                self.state.open_positions = [p for p in self.state.open_positions if p is not pos]
                self._persist_state()
                continue

            # Full success — log slippage
            roll_slippage = abs(open_fill.avg_price - close_fill.avg_price)
            logger.info(
                "C2: Roll complete %s %s ×%d: close@%.4f → open@%.4f  slippage=%.4f",
                pos.inst, pos.direction, pos.contracts,
                close_fill.avg_price, open_fill.avg_price, roll_slippage,
            )
            self._emit_event(
                "INFO", "ROLLOVER",
                f"C2: Roll {pos.inst} {pos.direction} ×{pos.contracts}: "
                f"close@{close_fill.avg_price:.2f} → open@{open_fill.avg_price:.2f}  "
                f"slippage={roll_slippage:.2f}",
            )

            # The position now lives on the next contract; the stop protecting it does
            # not. Left alone the old STP keeps working on a contract that is no longer
            # held — and an orphaned stop is not merely useless: a SELL STP with no long
            # behind it fills into a short nobody asked for, on an expiring contract.
            if pos.stop_order_id:
                try:
                    _ok = self.broker.cancel_order(pos.stop_order_id)
                except Exception as _e:
                    _ok = False
                    logger.error("C2: cancel_order(%s) raised for %s: %s",
                                 pos.stop_order_id, pos.inst, _e)
                if _ok:
                    logger.info("C2: cancelled old-contract stop orderId=%s for %s",
                                pos.stop_order_id, pos.inst)
                else:
                    logger.critical(
                        "C2: could NOT cancel old-contract stop orderId=%s for %s. It "
                        "may still be working on the expiring contract and can fill "
                        "into an unwanted position. OPERATOR: cancel it in TWS.",
                        pos.stop_order_id, pos.inst,
                    )
                pos.stop_order_id = None

            self._roll_stop(pos, open_fill.avg_price - close_fill.avg_price)
            self._persist_state()

    # ── main daily loop ──────────────────────────────────────────────────────

    def run_day(self, day, _spy_last_date_override=None):
        """One trading day. Returns the DayDecision. Syncs broker to the brain's state.

        _spy_last_date_override: inject spy_last_date directly into HMMStaleGuard.check_day
        (skips CSV read). For offline testing only — not used in production."""
        # Stamp the ledger's epoch on first use so the dashboard can say what the
        # net P&L is measured from. Set once, then carried in the state file.
        if self._system_epoch is None:
            self._system_epoch = str(pd.Timestamp(day).date())
            logger.info("Ledger epoch set to %s — net P&L is measured from here, "
                        "not from the start of paper trading", self._system_epoch)

        self._emit_event(
            "INFO", "STATE",
            f"Day started: {pd.Timestamp(day).date()}, "
            f"{len(self.state.open_positions)} position(s) open",
        )

        # Retry positions with exit_pending=True from a prior session's failed CLOSE.
        # Runs before decide_day so failed exits are resolved before new decisions are made.
        self._retry_pending_exits(day)

        # C2: roll any positions whose front-month contract expires today.
        # Must run before fetch_bars so the signal layer sees the new contract.
        self._handle_rollover_if_needed(day)

        # D5: kill-switch gate — operator creates STOP_FILE to halt new entries gracefully.
        #     Exits are NOT affected: existing positions still exit on their exit_day.
        #     To resume trading, delete the STOP_FILE. To force-close everything, kill PID.
        _stop_active = self._stop_path is not None and self._stop_path.exists()
        if _stop_active:
            logger.warning(
                "D5: STOP_FILE present (%s) on %s — new entries HALTED; "
                "existing exits proceed normally. Remove file to resume.",
                self._stop_path, pd.Timestamp(day).date(),
            )
            self._emit_event(
                "CRITICAL", "SYSTEM",
                f"STOP_FILE: entries halted for {pd.Timestamp(day).date()}. "
                f"Existing positions exit normally. "
                f"Remove {self._stop_path.name} to resume.",
            )

        # 1. fetch bars through end-of-day (per instrument) — causal.
        #    `day` = midnight (normalized). With through=midnight, IBKR "2 D" returns
        #    only yesterday's bars. Using end-of-day lets signal_fn see today's live bars
        #    (needed for generate_today_signals / Option C continuous runner).
        insts = {p.inst for p in self.state.open_positions} | set(self.contracts)
        _through = pd.Timestamp(day) + pd.Timedelta(hours=23, minutes=59)
        bars = {i: self.broker.fetch_bars(i, through=_through) for i in insts}

        # C3: alert on empty bars for instruments with open positions (feed gap → loud not silent).
        #     Exits are bar-independent (exit_day-based) and still run normally.
        _empty_insts = {p.inst for p in self.state.open_positions
                        if bars.get(p.inst, pd.DataFrame()).empty}
        for _inst in sorted(_empty_insts):
            logger.warning(
                "C3: fetch_bars empty for %s on %s — possible feed gap; "
                "exits are bar-independent and will still run",
                _inst, pd.Timestamp(day).date(),
            )
            self._emit_event(
                "WARN", "SIGNAL",
                f"C3: empty bars for {_inst} — possible feed gap; exits unaffected",
                {"inst": _inst, "day": str(pd.Timestamp(day).date())},
            )

        # E3: clock sanity — if today is >3 days ahead of latest bar, alert + skip entries.
        #     Skew > 3 days suggests wrong date context (NTP drift, wrong timezone, stale data).
        _e3_skip_entries = False
        _bar_dates = []
        for _df in bars.values():
            if _df is not None and not _df.empty:
                _ts = pd.Timestamp(_df.index[-1])
                _bar_dates.append(
                    _ts.tz_localize(None).normalize() if _ts.tzinfo else _ts.normalize()
                )
        if _bar_dates:
            _last_bar = max(_bar_dates)
            _today_ts = pd.Timestamp(day).normalize()
            _delta = (_today_ts - _last_bar).days
            if _delta > 3:
                _e3_skip_entries = True
                logger.error(
                    "E3: clock skew suspected — today=%s but last bar=%s (%d days gap). "
                    "Entries SKIPPED for today; exits unaffected.",
                    _today_ts.date(), _last_bar.date(), _delta,
                )
                self._emit_event(
                    "ALERT", "SIGNAL",
                    f"E3: clock skew — {_delta}d gap, entries skipped",
                    {"delta_days": _delta, "today": str(_today_ts.date()),
                     "last_bar": str(_last_bar.date())},
                )

        # 2. signals for today — C1: wrapped so an engine failure skips entries but keeps exits
        try:
            entry_candidates, exit_positions = self.signal_fn(
                day, bars, self.state.open_positions)
        except Exception as exc:
            logger.error(
                "C1: signal_fn FAILED on %s: %s — "
                "entries SKIPPED for today; held positions will exit normally via exit_day",
                pd.Timestamp(day).date(), exc,
            )
            self._emit_event(
                "ALERT", "SIGNAL",
                "C1: signal_fn failed — entries skipped for today",
                {"error": str(exc)[:120]},
            )
            entry_candidates, exit_positions = [], []

        # Observability: capture regime for dump_state (no logic effect)
        if self._regime_fn is not None:
            try:
                _r = self._regime_fn(day)
                self._last_regime = str(_r) if _r else "Unknown"
            except Exception:
                pass

        # J2: _SWING_CACHE in _validated_core.py keys by id(df). fetch_bars returns a
        # new slice (new object) each call → cache never hits across days but entries
        # accumulate indefinitely. Clear after signal generation to bound memory in
        # long-running processes; WFO batch path (no runner) is unaffected.
        try:
            from futures._validated_core import _SWING_CACHE as _swingtf_cache
            _swingtf_cache.clear()
        except Exception:
            pass

        # E3: discard entries if clock skew detected (signal_fn still ran for exits)
        if _e3_skip_entries:
            entry_candidates = []

        # D5: discard entries if STOP_FILE is present (exits unaffected)
        if _stop_active:
            entry_candidates = []

        # B3: halt entries if broker/file mismatch detected on startup (exits unaffected)
        if self._b3_halt_entries and entry_candidates:
            n = len(entry_candidates)
            logger.critical(
                "B3 HALT: %d entry signal(s) BLOCKED — broker/file mismatch on startup. "
                "Resolve mismatch and restart runner to re-enable entries.",
                n,
            )
            self._emit_event(
                "CRITICAL", "GUARD",
                f"B3 HALT: {n} entry signal(s) blocked — broker/file mismatch; restart required",
                {"count": n, "day": str(pd.Timestamp(day).date())},
            )
            entry_candidates = []

        # 2b. HMM stale guard — C2: wrapped in try/except; throw → block entries (conservative).
        #     Exits are determined by state.open_positions[*].exit_day (set in step 3)
        #     and are unaffected by this gate — held positions always exit normally.
        if self._hmm_stale_guard is not None:
            _g1_soft_pre = getattr(self._hmm_stale_guard, '_g1_soft_active', False)
            _ur_pre       = getattr(self._hmm_stale_guard, 'regime_unreliable', False)
            _g2_soft_pre = getattr(self._hmm_stale_guard, '_g2_soft_notified', False)
            _g2_hard_pre = getattr(self._hmm_stale_guard, '_g2_hard_notified', False)
            try:
                entries_allowed = self._hmm_stale_guard.check_day(
                    pd.Timestamp(day), spy_last_date_override=_spy_last_date_override)
            except Exception as exc:
                logger.error(
                    "C2: hmm_stale_guard.check_day FAILED on %s: %s — "
                    "entries BLOCKED (conservative); exits unaffected",
                    pd.Timestamp(day).date(), exc,
                )
                self._emit_event(
                    "ALERT", "GUARD",
                    "C2: stale_guard check failed — entries blocked (conservative)",
                    {"error": str(exc)[:120]},
                )
                entries_allowed = False
            # Detect G1 transitions: emit once per state change
            _ur_now       = getattr(self._hmm_stale_guard, 'regime_unreliable', False)
            _g1_soft_now  = getattr(self._hmm_stale_guard, '_g1_soft_active', False)
            _g2_soft_now  = getattr(self._hmm_stale_guard, '_g2_soft_notified', False)
            _g2_hard_now  = getattr(self._hmm_stale_guard, '_g2_hard_notified', False)
            if not _ur_pre and _ur_now:
                self._emit_event("CRITICAL", "GUARD",
                    "G1 HARD-STALE: entries HALTED — SPY CSV stale >5 bday")
            elif not _g1_soft_pre and _g1_soft_now and not _ur_now:
                self._emit_event("WARN", "GUARD",
                    "G1 SOFT-STALE: SPY CSV stale >2 bday — trading continues")
            elif _ur_pre and not _ur_now:
                self._emit_event("INFO", "GUARD",
                    "G1 RECOVERED: SPY CSV fresh — entry halt cleared")
            if not _g2_soft_pre and _g2_soft_now:
                self._emit_event("WARN", "GUARD",
                    "G2: model age WARN — plan annual re-freeze")
            if not _g2_hard_pre and _g2_hard_now:
                self._emit_event("ALERT", "GUARD",
                    "G2: model age URGENT — schedule re-freeze immediately")
            if not entries_allowed and entry_candidates:
                n = len(entry_candidates)
                self._hmm_stale_guard.entries_blocked += n
                logger.warning(
                    "REGIME_UNRELIABLE: %d entry signal(s) BLOCKED on %s — SPY CSV stale",
                    n, pd.Timestamp(day).date(),
                )
                self._emit_event(
                    "WARN", "GUARD",
                    f"REGIME_UNRELIABLE: {n} entry signal(s) blocked — SPY CSV stale",
                    {"count": n, "day": str(pd.Timestamp(day).date())},
                )
                entry_candidates = []

        # 3. mark exits so decide_day closes them today (live: signal sets exit_day)
        exit_keys = {(p.inst, p.cluster) for p in exit_positions}
        for p in self.state.open_positions:
            if (p.inst, p.cluster) in exit_keys:
                p.exit_day = day

        # 4. risk brain — same decide_day validated vs deploy_sim
        decision = decide_day(day, self.state, entry_candidates, self.guard, self.contracts)

        # 5. execute: CLOSE multi-day exits, then split entries into same-day / multi-day.
        for p in decision.exits:
            _f = self.broker.send_order(Order(
                p.inst, "CLOSE", p.direction, p.contracts, p.cluster, day,
                exit_day=day, pnl_sized=p.pnl_sized))
            # C1: fill quality — signed slippage (positive = adverse).
            # LONG CLOSE (selling): lower fill = adverse → slip = stop_ref - avg.
            # SHORT CLOSE (buying): higher fill = adverse → slip = avg - stop_ref.
            # stop_price = entry chandelier level (fixed stop, not ratcheted yet).
            # No stop_ref → market exit, log fill price only (no adverse/favorable).
            if _f.status in ("FILLED", "PARTIAL") and _f.avg_price > 0:
                self._book_realised(p, _f.avg_price, _f.filled_qty or p.contracts,
                                    why="signal exit")
                _slip_c = None
                if p.stop_price is not None:
                    _slip_c = (p.stop_price - _f.avg_price) if p.direction == "LONG" \
                              else (_f.avg_price - p.stop_price)
                    self._slip_close_sum += _slip_c
                    self._slip_close_n   += 1
                    self._persist_slip_stats()
                    logger.info(
                        "C1 CLOSE: %s %s avg=%+.4f stop_ref=%.4f slip=%+.4f (%s)"
                        " | close_mean=%+.4f N=%d",
                        p.inst, p.direction, _f.avg_price, p.stop_price, _slip_c,
                        "ADVERSE" if _slip_c > 0 else "favorable",
                        self._slip_close_sum / self._slip_close_n, self._slip_close_n,
                    )
                else:
                    logger.info(
                        "C1 CLOSE: %s %s avg=%.4f (market exit, no stop reference)",
                        p.inst, p.direction, _f.avg_price,
                    )
                self._append_trade({
                    "type": "CLOSE",
                    "inst": p.inst, "cluster": p.cluster,
                    "direction": p.direction, "contracts": p.contracts,
                    "entry_day": str(p.entry_day.date()) if p.entry_day else None,
                    "exit_day": str(day.date()) if hasattr(day, "date") else str(day),
                    "expected_stop": p.stop_price,
                    "fill_price": _f.avg_price,
                    "pnl_sized": p.pnl_sized,
                    "slip": _slip_c,
                    "filled_qty": _f.filled_qty or p.contracts,
                    "status": _f.status,
                    "regime": self._last_regime,
                })
                self._emit_event(
                    "INFO", "EXEC",
                    f"CLOSE {p.inst} {p.direction} ×{p.contracts} @{_f.avg_price:.4f}",
                    {"inst": p.inst, "direction": p.direction,
                     "contracts": p.contracts, "price": _f.avg_price, "cluster": p.cluster},
                )
            # I4.8: if CLOSE fails, restore position for retry next session.
            # decide_day already removed p from open_positions; add it back with
            # exit_pending=True so _retry_pending_exits() picks it up tomorrow.
            # Live: IBKRBroker returns Fill.status="FAILED" on reject/timeout.
            # Verify (MockBroker): status always "FILLED" → this branch never taken.
            if _f.status == "FAILED":
                p.exit_pending = True
                self.state.open_positions.append(p)
                logger.warning(
                    "I4.8: CLOSE FAILED %s/%s — exit_pending=True, restored for retry",
                    p.inst, p.cluster,
                )
                self._emit_event(
                    "ALERT", "EXEC",
                    f"I4.8: CLOSE FAILED {p.inst}/{p.cluster} — exit_pending=True",
                    {"inst": p.inst, "cluster": p.cluster},
                )
            else:
                # Cancel any GTC STP placed for this position so it doesn't
                # create an unintended position after the LONG/SHORT is gone.
                if p.stop_order_id is not None:
                    try:
                        # cancel_order reports failure by RETURNING False, not by
                        # raising — so the except below never fired and this logged
                        # "cancelled" unconditionally. Live 2026-08-05: stops 9 and 10
                        # stayed working at IBKR for days while the log said otherwise.
                        _cancelled = self.broker.cancel_order(p.stop_order_id)
                    except Exception as _e:
                        _cancelled = False
                        logger.error(
                            "STP: cancel_order(%s) raised for %s/%s: %s",
                            p.stop_order_id, p.inst, p.cluster, _e,
                        )
                    self._report_stop_cancel(_cancelled, p)

        # Split entries: same-day (e.g. STRESS_MID OPEN+CLOSE in one session) execute
        # BEFORE H4 equity sync so their pnl is included in the HALT_DAY check.
        # Multi-day entries execute AFTER and can be blocked if HALT_DAY fires.
        _sameday  = [t for t in decision.entries if t.get("exit") == day]
        _multiday = [t for t in decision.entries if t.get("exit") != day]

        # Pass 1: same-day entry+exit (STRESS_MID and similar)
        for t in _sameday:
            n = self.contracts.get(t["inst"], 1)
            if n > self._max_contracts:
                logger.error(
                    "F3: FAT_FINGER BLOCKED: %s ordered %d contracts (max_contracts_per_order=%d)"
                    " — order NOT sent to broker",
                    t["inst"], n, self._max_contracts,
                )
                self._emit_event(
                    "CRITICAL", "RISK",
                    f"FAT_FINGER BLOCKED: {t['inst']} {n} contracts > max {self._max_contracts}"
                    f" — order NOT sent",
                    {"inst": t["inst"], "ordered": n, "max": self._max_contracts},
                )
                continue
            _sd_open = self.broker.send_order(Order(
                t["inst"], "OPEN", t["direction"], n, t["cluster"], day,
                exit_day=t.get("exit"), pnl_sized=t.get("pnl_sized", 0.0)))
            _sd_close = self.broker.send_order(Order(
                t["inst"], "CLOSE", t["direction"], n, t["cluster"], day,
                exit_day=day, pnl_sized=t.get("pnl_sized", 0.0)))
            # A same-day trade never becomes an OpenPos, so it misses the exits loop
            # that books every other close. decide_day added its pnl_sized, which is
            # the ledger's own figure in verify mode and 0.0 in live — leaving a whole
            # cluster (STRESS_MID) contributing nothing to the sleeve ledger, and so
            # nothing to the daily brake either.
            if _sd_open.avg_price > 0 and _sd_close.avg_price > 0:
                _sd_pos = OpenPos(
                    inst=t["inst"], direction=t["direction"], contracts=n,
                    risk_dollars=t.get("risk_sized", 0.0), cluster=t["cluster"],
                    entry_day=day, entry_price=_sd_open.avg_price)
                self._book_realised(
                    _sd_pos, _sd_close.avg_price,
                    _sd_close.filled_qty or n, why="same-day")

        # H4: fold the broker's realised P&L into system equity after ALL closes
        # (multi-day exits + same-day STRESS_MID), so HALT_DAY can fire on a same-session
        # loss the ledger has not booked yet.
        #
        # Applies the broker's DELTA, not its absolute balance. Assigning the balance made
        # system equity jump to the account's funding level ($995k on paper) and put every
        # breaker threshold on that scale — losing the whole $50,000 design capital then
        # read as 5% drawdown. Delta keeps the real P&L while the base stays the system's.
        # Verify mode (MockBroker): broker and ledger move together → delta ≈ 0 → no-op.
        _h4_eq = self.broker.get_equity()
        _h4_delta = _h4_eq - self._last_broker_equity
        self._last_broker_equity = _h4_eq
        # The delta is NOT added to the ledger any more: it is the whole account's
        # NetLiquidation, which carries interest, FX and everything else in a CAD account
        # twenty times the size of the sleeve. Realised P&L is booked per close in
        # _book_realised. The line stays because a large unexplained move in the account
        # is still worth seeing.
        if abs(_h4_delta) > 0.01:
            logger.info("H4: broker delta %+.2f (balance %.2f) — logged, not booked; "
                        "sleeve ledger stands at %.2f",
                        _h4_delta, _h4_eq, self.state.equity)

        # Re-check the brake before the multi-day entries go out. decide_day admitted
        # them against the equity it saw BEFORE this run's closes were booked, so a day
        # that has since crossed -4% must not still open new risk.
        #
        # Deliberately not gated on the broker delta. That gate was correct while this
        # block read the broker; it now reads the ledger, and the two can move for
        # different reasons — a ledger that changed while the account happened not to
        # would have skipped the check entirely.
        if self.state.breaker is not None and _multiday:
            self.state.breaker.update(self.state.equity)
            if not self.state.breaker.status(self.state.equity).get(
                    "allow_new_entries", True):
                logger.warning(
                    "%s after realised P&L — blocking %d multi-day entries "
                    "(sleeve equity %.2f)",
                    self.state.breaker.status(self.state.equity)["level"],
                    len(_multiday), self.state.equity,
                )
                self._emit_event(
                    "CRITICAL", "GUARD",
                    f"{self.state.breaker.status(self.state.equity)['level']}: "
                    f"{len(_multiday)} multi-day entr"
                    f"{'y' if len(_multiday) == 1 else 'ies'} blocked after realised P&L",
                    {"level": self.state.breaker.status(self.state.equity)["level"],
                     "blocked": len(_multiday), "equity": round(self.state.equity, 2)},
                )
                _multiday.clear()

        # Pass 2: multi-day entries — OPEN only (exit on a future day)
        for t in _multiday:
            n = self.contracts.get(t["inst"], 1)
            # F3: fat-finger guard — block orders that exceed the per-order contract cap.
            #     Catches accidental contracts_by_inst changes (e.g. 1 → 100).
            #     Cap is intentionally generous (default 10) — raise only if scaling up deliberately.
            if n > self._max_contracts:
                logger.error(
                    "F3: FAT_FINGER BLOCKED: %s ordered %d contracts (max_contracts_per_order=%d)"
                    " — order NOT sent to broker",
                    t["inst"], n, self._max_contracts,
                )
                self._emit_event(
                    "CRITICAL", "RISK",
                    f"FAT_FINGER BLOCKED: {t['inst']} {n} contracts > max {self._max_contracts}"
                    f" — order NOT sent",
                    {"inst": t["inst"], "ordered": n, "max": self._max_contracts},
                )
                continue
            _open_fill = self.broker.send_order(Order(
                t["inst"], "OPEN", t["direction"], n, t["cluster"], day,
                exit_day=t.get("exit"), pnl_sized=t.get("pnl_sized", 0.0)))

            # C1: fill quality — signed slippage (positive = adverse).
            # LONG OPEN (buying): higher fill = adverse → slip = avg - expected.
            # SHORT OPEN (selling): lower fill = adverse → slip = expected - avg.
            # Dấu quan trọng cho bias hệ thống: %+.4f giữ dấu.
            # Realised P&L needs the price this actually filled at. In live pnl_sized
            # arrives as 0.0 — the backtest fills it from its ledger, a broker does not —
            # so without this the close has nothing to value itself against. Recorded on
            # every open, not just the ones that get a stop.
            if _open_fill.status in ("FILLED", "PARTIAL") and _open_fill.avg_price > 0:
                _opened = next(
                    (p for p in self.state.open_positions
                     if p.inst == t["inst"] and p.cluster == t["cluster"]
                     and p.entry_price is None),
                    None,
                )
                if _opened is not None:
                    _opened.entry_price = float(_open_fill.avg_price)

            _exp_entry = t.get("entry")
            _slip_o = None
            if _open_fill.status in ("FILLED", "PARTIAL") and _exp_entry and _open_fill.avg_price > 0:
                _slip_o = (_open_fill.avg_price - _exp_entry) if t["direction"] == "LONG" \
                          else (_exp_entry - _open_fill.avg_price)
                self._slip_open_sum += _slip_o
                self._slip_open_n   += 1
                self._persist_slip_stats()
                logger.info(
                    "C1 OPEN: %s %s avg=%.4f expected=%.4f slip=%+.4f (%s)"
                    " | open_mean=%+.4f N=%d",
                    t["inst"], t["direction"], _open_fill.avg_price, _exp_entry, _slip_o,
                    "ADVERSE" if _slip_o > 0 else "favorable",
                    self._slip_open_sum / self._slip_open_n, self._slip_open_n,
                )
            elif _open_fill.status == "FAILED":
                logger.error(
                    "C1 OPEN FAILED: %s %s — %s",
                    t["inst"], t["direction"], _open_fill.error_msg or "no detail",
                )

            if _open_fill.status in ("FILLED", "PARTIAL"):
                self._append_trade({
                    "type": "OPEN",
                    "inst": t["inst"], "cluster": t["cluster"],
                    "direction": t["direction"], "contracts": n,
                    "entry_day": str(day.date()) if hasattr(day, "date") else str(day),
                    "expected_entry": _exp_entry,
                    "fill_price": _open_fill.avg_price,
                    "slip": _slip_o,
                    # Ordered vs actually filled — the dashboard's fill-quality panel
                    # cannot tell a partial from a full fill without both.
                    "filled_qty": _open_fill.filled_qty or n,
                    "status": _open_fill.status,
                    "regime": self._last_regime,
                })
                self._emit_event(
                    "INFO", "EXEC",
                    f"OPEN {t['inst']} {t['direction']} ×{n} @{_open_fill.avg_price:.4f}",
                    {"inst": t["inst"], "direction": t["direction"],
                     "contracts": n, "price": _open_fill.avg_price, "cluster": t["cluster"]},
                )

            # STP: GTC stop for overnight protection once the position is a day old.
            # It used to go out 0-1 seconds after the fill; that is a stricter exit rule
            # than the validated one and it costs the whole edge — see _stop_deferred for
            # the measurement. Swing and NKD now defer to the next session; STRESS_MID
            # still gets its stop at the fill, being a same-session model.
            # Note: stop_price = entry chandelier level; ratchet updates are not yet
            # implemented (planned for a future phase — paper phase uses fixed entry-stop).
            #
            # STRESS_MID does not reach here today, but not for the reason the old
            # comment gave. Its candidates carry no "exit" key, so decide_day appends
            # them to open_positions like any other — they would reach this block. What
            # stops them is that the sleeve is not wired: run_live_day passes
            # stress_bars_1015={} and the scheduler has no ~10:15 ET slot, so the entry
            # branch never runs. Keeping stress out of the deferral set is right on the
            # rule, not just on the sleeve: StressMidAdapter tests the stop from the
            # entry bar onward ("exit first stop/target hit, else 14:00 close"), with no
            # next-day deferral anywhere in it. An immediate STP IS its validated rule.
            #
            # Wiring it will need more than a slot. The adapter has THREE exits and live
            # implements one:
            #   stop    — immediate STP, matches
            #   target  — entry - 2R; to_candidate keeps only entry and stop, so no
            #             order is ever placed for it
            #   14:00   — replaced by "closed on the next run": _mark_held_unchanged is
            #             never called for the stress cluster, so diff_desired_vs_held
            #             finds the key missing from `desired` and exits it. Minutes
            #             instead of the modelled 10:15-to-14:00 hold.
            # Same family of bug as the one this deferral fixes, costing nothing so far
            # only because the sleeve is off. reconcile_stress covers the ENTRY decision
            # (entry/stop/target agree with the adapter, 0 mismatches over 112 Stress
            # days) — the exit path has no equivalent check.
            if _open_fill.status in ("FILLED", "PARTIAL") and t.get("stop") is not None:
                _stp_pos = next(
                    (p for p in self.state.open_positions
                     if p.inst == t["inst"] and p.cluster == t["cluster"]
                     and p.stop_order_id is None),
                    None,
                )
                if _stp_pos is not None:
                    # The level is recorded EITHER WAY. Deferring only delays the order;
                    # without stop_price on file, B4 cannot place it tomorrow ("only
                    # re-place when the level is known") and the position would run
                    # naked for its whole life instead of one session.
                    _stp_pos.stop_price = float(t["stop"])

                if _stp_pos is not None and self._stop_deferred(_stp_pos):
                    logger.info(
                        "STP HOAN: %s %s @ %.4f cluster=%s — dat vao phien sau, dung "
                        "luat da kiem dinh (dat ngay: -$10,832 / dat sang ngay: "
                        "+$47,166 tren 2018-2026). B4 se dat o lan chay dau tien cua "
                        "ngay ke tiep.",
                        t["inst"], t["direction"], t["stop"], t["cluster"],
                    )
                    self._emit_event(
                        "INFO", "ORDER",
                        f"STP hoan sang phien sau {t['inst']} {t['direction']} "
                        f"@{t['stop']:.4f}",
                        {"inst": t["inst"], "direction": t["direction"],
                         "stop": t["stop"], "cluster": t["cluster"], "deferred": True},
                    )
                elif _stp_pos is not None:
                    _stp_id = self.broker.place_stop(
                        t["inst"], t["direction"], n, t["stop"], t["cluster"])
                    _stp_pos.stop_order_id = _stp_id if _stp_id else None
                    if _stp_id:
                        logger.info(
                            "STP: placed %s %s stop @ %.4f orderId=%s cluster=%s",
                            t["inst"], t["direction"], t["stop"], _stp_id, t["cluster"],
                        )
                        self._emit_event(
                            "INFO", "ORDER",
                            f"STP placed {t['inst']} {t['direction']} @{t['stop']:.4f}",
                            {"inst": t["inst"], "direction": t["direction"],
                             "stop": t["stop"], "order_id": _stp_id, "cluster": t["cluster"]},
                        )
                    else:
                        logger.error(
                            "STP: place_stop FAILED %s %s @ %.4f cluster=%s "
                            "— position open without overnight stop protection",
                            t["inst"], t["direction"], t["stop"], t["cluster"],
                        )
                        self._emit_event(
                            "ALERT", "EXEC",
                            f"STP: place_stop FAILED {t['inst']} {t['direction']}"
                            f" @ {t['stop']:.4f} — no overnight stop protection",
                            {"inst": t["inst"], "direction": t["direction"],
                             "stop": t["stop"], "cluster": t["cluster"]},
                        )

        # Detect breaker level transitions; emit once per level change
        if self.state.breaker is not None:
            _br_st = self.state.breaker.status(self.state.equity)
            _new_lvl = _br_st["level"]
            if _new_lvl != self._last_breaker_level:
                _dd_pct = round(_br_st["drawdown_pct"] * 100, 2)
                if _new_lvl == "HALT":
                    self._emit_event(
                        "CRITICAL", "GUARD",
                        f"BREAKER HALT: DD {_dd_pct}% — all new entries blocked",
                        {"level": _new_lvl, "dd_pct": _dd_pct},
                    )
                elif _new_lvl == "HALT_DAY":
                    _dl = round(_br_st.get("daily_loss_pct", 0) * 100, 2)
                    self._emit_event(
                        "ALERT", "GUARD",
                        f"BREAKER HALT_DAY: daily loss {_dl}% — entries blocked today",
                        {"level": _new_lvl, "dd_pct": _dd_pct, "day_loss_pct": _dl},
                    )
                elif _new_lvl == "WARN":
                    self._emit_event(
                        "WARN", "GUARD",
                        f"BREAKER WARN: DD {_dd_pct}% — approaching limit",
                        {"level": _new_lvl, "dd_pct": _dd_pct},
                    )
                elif self._last_breaker_level in ("HALT", "HALT_DAY", "WARN"):
                    self._emit_event(
                        "INFO", "GUARD",
                        f"BREAKER OK: recovered from {self._last_breaker_level}",
                        {"level": _new_lvl, "dd_pct": _dd_pct},
                    )
                self._last_breaker_level = _new_lvl

        # B1: persist positions + breaker state after decide_day updates both
        self._persist_state()
        # B5: last look before the session ends — every open position must have a stop
        # that the BROKER confirms. B4 only runs at startup, so without this a stop that
        # never reached IBKR goes unnoticed until the next slot, or overnight once the
        # scheduler is done for the day (live 2026-08-05: found by hand that evening).
        self._audit_working_stops(day)
        # Write live state to dashboard file (no-op if live_state_path is None)
        self.dump_state(day)

        return decision

    def _roll_stop(self, pos, shift: float) -> None:
        """Move a position's stop onto the contract it just rolled into.

        Split out of _handle_rollover so it can be driven directly. It was inline, and a
        test could only reach it by staging a whole rollover — so the two defects below
        went unnoticed, and a test written against a hand-copied version of the logic
        would only have proved the copy right.

        The recorded level belongs to the OLD contract's price scale. The two fills just
        measured what the contracts differ by, so shifting by that keeps the same distance
        to price on the new scale — a measured spread rather than a quoted one.
        """
        if pos.stop_price is None:
            logger.critical(
                "C2: %s %s rolled with no recorded stop level — the new contract "
                "is UNPROTECTED and no level is known to re-place. OPERATOR: "
                "recompute the chandelier level and place the STP in TWS.",
                pos.inst, pos.direction,
            )
            return

        _new_stop = pos.stop_price + shift
        # Record the shifted level BEFORE trying to place it, and keep it whatever
        # happens. It used to be written only when the order was accepted, so a refused
        # STP left the OLD contract's level on file — and B4, whose whole rule is "only
        # re-place when the level is known", would then place that stale level on the new
        # contract's price scale the next session. The two contracts differ by exactly the
        # shift just measured, so the wrong level is wrong by that much, quietly.
        pos.stop_price = _new_stop

        if self._stop_deferred(pos):
            # Rolled while still inside its deliberate stop-free window: entered the
            # previous session and the arm time has not come round yet. The roll does not
            # move entry_day, so the window is unchanged and the level is now recorded —
            # B4 places it at the arm time like any other deferred position. Placing here
            # would arm this one position early for no reason other than that its contract
            # happened to roll.
            pos.stop_order_id = None
            logger.info(
                "C2: %s stop level rolled to %.4f but NOT placed — vi the dang trong "
                "cua so hoan CO CHU DICH (vao ngay %s). B4 se dat dung gio vu trang "
                "cua sleeve.",
                pos.inst, _new_stop,
                pd.Timestamp(pos.entry_day).date() if pos.entry_day else "?",
            )
            return

        try:
            _sid = self.broker.place_stop(pos.inst, pos.direction, pos.contracts,
                                          _new_stop, pos.cluster)
        except Exception as _e:
            _sid = ""
            logger.error("C2: place_stop after roll raised for %s: %s", pos.inst, _e)
        if _sid:
            pos.stop_order_id = _sid
            logger.info("C2: stop rolled %s: %.4f → %.4f (shift %+.4f) orderId=%s",
                        pos.inst, _new_stop - shift, _new_stop, shift, _sid)
        else:
            logger.critical(
                "C2: %s %s rolled to the new contract but the replacement STP was NOT "
                "accepted (wanted %.4f). Position is UNPROTECTED. OPERATOR: place it "
                "in TWS or close the position.",
                pos.inst, pos.direction, _new_stop,
            )

    def _stop_deferred(self, p, now=None) -> bool:
        """True while a position is inside its DELIBERATE stop-free window.

        backtest_swing_tf checks the stop inside `if pos is not None`, which runs
        BEFORE the entry block in the same day iteration — so a position opened today
        is first tested for its stop tomorrow. Live used to place the STP 0-1 seconds
        after the fill, which is a different and much stricter rule than the one that
        was validated, and the difference is not small.

        Measured over 2018-2026 on Rổ 4 (model_sameday_stop.py / model_entry_latency.py,
        both gated on reproducing the engine trade-for-trade):

            STP placed at fill      -$10,832      60.8% of trades stopped on entry day
            STP from the next day   +$47,166      the rule the backtest actually runs

        Sweeping the activation delay gives a smooth rising curve that saturates around
        8 hours at 99% of the full figure — so this is a real market effect (noise
        around the entry needs time to settle), not an artifact of grouping bars by
        calendar day. The operative stop sits about 1/22 of the nominal chandelier band
        (mult x daily ATR) on all four instruments, which is why it cannot survive that
        noise. The choice here is the next session, matching the backtest exactly.

        The window is why B4 and B5 must ask this before calling a position naked: they
        exist to stop unprotected positions, and the validated rule requires exactly one
        such window per trade. Left unaware, B4 re-places the stop on the very next slot
        and the delay collapses to ~5 minutes — the worst column in the table.

        NKD runs the same engine and inherits the same semantics, so it is included; the
        DOLLAR magnitude for NKD has not been measured, only Rổ 4. STRESS_MID is a
        same-session event model and is excluded.
        """
        arm = _ARM_BY_CLUSTER.get(p.cluster)
        if arm is None:
            return False       # cluster khong thuoc dien hoan (STRESS_MID)
        if p.entry_day is None:
            return False       # khong ro ngay vao → bao ve, khong doan

        # Gio vu trang cua CHINH cluster nay, khong phai cua cluster khac. Truoc day vi
        # tu chi so `entry_day == today`, nen ca hai sleeve deu duoc dat stop o job dau
        # tien cua ngay ke tiep — tinh co la 01:10 ET, dung cho NKD (14h JST) nhung sai
        # cho Ro 4 (moi 1,17h sau ranh gioi ngay ET).
        # Dung gio dia phuong cua sleeve roi doi sang ET — khong cong gio ET truc tiep.
        _tz, _hh, _mm = arm
        _d = (pd.Timestamp(p.entry_day).normalize() + pd.Timedelta(days=1)).date()
        arm_at = (pd.Timestamp(f"{_d} {_hh:02d}:{_mm:02d}", tz=_tz)
                  .tz_convert(ET_TZ).tz_localize(None))
        ref = pd.Timestamp(now) if now is not None else self._now

        # Ngay vao lenh o TUONG LAI la trang thai hong, khong phai cua so. Hoan tiep se
        # de mot vi the tran vo thoi han — hong nang hon cai dang di sua.
        if pd.Timestamp(p.entry_day).normalize() > ref.normalize():
            return False
        return ref < arm_at

    def _audit_working_stops(self, today=None) -> None:
        """CRITICAL for any open position the broker holds no working stop for.

        Silent when the broker cannot report (returns None) — MockBroker keeps no order
        book, so verify/reconcile runs are unaffected. Never raises: this runs after
        orders are placed and persisted, and an observability failure must not take the
        session down with it.
        """
        # Prefer the contract-aware check. p.inst in working only asks whether a stop
        # exists for the symbol, which says nothing about the expiry the position is
        # actually on — after a rollover the old contract's STP keeps that answer True
        # while the new position carries nothing. Brokers without the method (MockBroker,
        # offline) fall through to the symbol check, which is what ran before.
        try:
            precise = self.broker.unprotected_positions()
        except (NotImplementedError, AttributeError):
            precise = None
        except Exception as exc:
            logger.error("B5: unprotected_positions() failed: %s", exc)
            precise = None

        # Positions inside the deliberate window are expected to have no stop; reporting
        # them CRITICAL every session would train the operator to ignore the one alert
        # that means a stop actually went missing.
        # Suppress only where EVERY position on the instrument is inside its window.
        # The set used to be "any deferred position's instrument", so one fresh stress
        # entry would silence the alert for a swing position on the same contract that
        # had genuinely lost its stop — the alert being suppressed by the very situation
        # that makes it worth having.
        _by_inst: dict = {}
        for p in self.state.open_positions:
            _by_inst.setdefault(p.inst, []).append(p)
        _defer_insts = {i for i, ps in _by_inst.items()
                        if all(self._stop_deferred(x) for x in ps)}
        if _defer_insts:
            logger.info("B5: bo qua %s — trong cua so hoan STP co chu dich",
                        ", ".join(sorted(_defer_insts)))

        if precise is not None:
            for u in precise:
                if u["inst"] in _defer_insts:
                    continue
                logger.critical(
                    "STP UNPROTECTED: %s x%+d on contract %s has no stop working on "
                    "that contract (stops seen on: %s). OPERATOR: place the STP "
                    "manually in TWS or close the position.",
                    u["inst"], u["qty"], u["expiry"],
                    ", ".join(u["stop_expiries"]) or "none",
                )
                self._emit_event(
                    "CRITICAL", "ORDER",
                    f"STP UNPROTECTED: {u['inst']} x{u['qty']:+d} on {u['expiry']} "
                    f"has no stop on that contract",
                    dict(u),
                )
            return

        try:
            working = self.broker.get_working_stops()
        except (NotImplementedError, AttributeError):
            return
        except Exception as exc:
            logger.error("B5: get_working_stops() failed: %s", exc)
            return
        if working is None:
            return
        _live_ids = {str(i) for v in working.values() for i in v}
        for p in self.state.open_positions:
            if str(p.stop_order_id) in _live_ids or self._stop_deferred(p):
                continue
            logger.critical(
                "STP UNPROTECTED: %s %s x%d (%s) is open with no working stop at the "
                "broker (recorded stop_order_id=%s, stop_price=%s). OPERATOR: place the "
                "STP manually in TWS or close the position.",
                p.direction, p.inst, p.contracts, p.cluster,
                p.stop_order_id, p.stop_price,
            )
            self._emit_event(
                "CRITICAL", "ORDER",
                f"STP UNPROTECTED: {p.inst} {p.direction} x{p.contracts} ({p.cluster}) "
                f"open with no working stop at broker",
                {"inst": p.inst, "direction": p.direction, "cluster": p.cluster,
                 "stop_order_id": p.stop_order_id, "stop_price": p.stop_price},
            )

    def run_history(self, days):
        """Replay a sequence of days through the broker. Returns realized-pnl series +
        taken/rejected — compare to deploy_sim for the orchestration proof."""
        import pandas as pd
        realized = {}
        for day in days:
            d = self.run_day(day)
            if d.realized:
                realized[day] = realized.get(day, 0.0) + d.realized
        return (pd.Series(realized).sort_index() if realized else pd.Series(dtype=float),
                dict(taken=self.state.taken, rejected=self.state.rejected,
                     halted=self.state.halted, final_equity=self.state.equity))

    # ── Operational event log ────────────────────────────────────────────────

    def _report_stop_cancel(self, cancelled: bool, p) -> None:
        """Log the outcome of cancelling a position's GTC stop — the real outcome.

        A stop that survives its position is not a bookkeeping detail: it is a live
        order that will open a NEW position in the opposite direction when it fires.
        Live 2026-08-05 carried two of these (orderId 9 and 10), one of which would
        have doubled a short rather than closing it.
        """
        if cancelled:
            logger.info("STP: cancelled GTC stop orderId=%s for closed %s/%s",
                        p.stop_order_id, p.inst, p.cluster)
            return
        logger.critical(
            "STP ORPHAN: cancel_order(%s) returned False for %s/%s — the stop is "
            "still working at the broker and will open an unintended position when "
            "it fires. OPERATOR: cancel orderId=%s manually in TWS.",
            p.stop_order_id, p.inst, p.cluster, p.stop_order_id,
        )
        self._emit_event(
            "CRITICAL", "ORDER",
            f"STP ORPHAN: {p.inst}/{p.cluster} stop orderId={p.stop_order_id} "
            f"NOT cancelled — still live at broker, cancel manually in TWS",
            {"inst": p.inst, "cluster": p.cluster, "order_id": p.stop_order_id},
        )

    def _emit_event(self, level: str, category: str, message: str,
                    context: dict | None = None) -> None:
        """Append a structured event to self._events (bounded 500). Thread-safe only
        for single-threaded use (runner is single-threaded by design — J1)."""
        from datetime import datetime as _dt, timezone
        event: dict = {
            "ts": _dt.now(timezone.utc).isoformat(timespec="seconds"),
            "level": level,
            "category": category,
            "message": message,
        }
        if context:
            event["context"] = context
        self._events.append(event)
        if len(self._events) > 500:
            self._events = self._events[-500:]
        self._append_event_log(event)

    def _append_event_log(self, event: dict) -> None:
        """Append one JSONL record without participating in trading state.

        O_APPEND protects all prior records. A short/failed write disables this
        telemetry channel for the current runner, but never escapes into the engine.
        Readers treat an incomplete final line as a reported telemetry gap.
        """
        if self._event_log_dir is None or self._event_log_disabled:
            return
        try:
            stamp = pd.Timestamp(event["ts"])
            if stamp.tzinfo is None:
                stamp = stamp.tz_localize("UTC")
            day = stamp.tz_convert(ET_TZ).strftime("%Y%m%d")
            path = self._event_log_dir / f"runner_events_{day}.jsonl"
            if path.exists() and path.stat().st_size:
                read_fd = os.open(path, os.O_RDONLY | (getattr(os, "O_BINARY", 0)))
                try:
                    os.lseek(read_fd, -1, os.SEEK_END)
                    if os.read(read_fd, 1) != b"\n":
                        raise OSError("event log has an incomplete final record")
                finally:
                    os.close(read_fd)
            payload = (json.dumps(event, ensure_ascii=False, separators=(",", ":"),
                                  default=str) + "\n").encode("utf-8")
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            fd = os.open(path, flags, 0o600)
            try:
                written = os.write(fd, payload)
                if written != len(payload):
                    raise OSError(f"short event-log write: {written}/{len(payload)} bytes")
            finally:
                os.close(fd)
        except Exception as exc:
            self._event_log_disabled = True
            logger.warning("event log disabled for this run after append failure: %s", exc)

    # ── Paper equity history ─────────────────────────────────────────────────

    def _record_paper_day(self, day, equity: float) -> dict:
        """Upsert one end-of-day system-equity mark and return the whole series.

        Live mode holds a single snapshot per run and every slot is a separate
        process, so without this there is no equity curve at all — which is why the
        dashboard's Calmar/Sharpe/MaxDD/Return bar rendered as dashes. The 22 slots
        in a day all write the same date; last write wins, so the closing mark is
        what survives.

        Keyed by date, not appended, so re-running a day cannot double-count it.
        """
        if self._paper_history_path is None or day is None:
            return {}
        key = str(pd.Timestamp(day).date())
        hist: dict = {}
        if self._paper_history_path.exists():
            try:
                with open(self._paper_history_path, encoding="utf-8") as fh:
                    hist = json.load(fh)
            except Exception as exc:
                logger.warning("paper history unreadable (%s) — starting fresh: %s",
                               self._paper_history_path, exc)
                hist = {}
        days = hist.get("days") or {}
        days[key] = round(float(equity), 2)
        hist = {
            "epoch": self._system_epoch,
            "account": float(self.state.breaker.account) if self.state.breaker else None,
            "days": days,
        }
        try:
            self._paper_history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._paper_history_path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(hist, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._paper_history_path)
        except Exception as exc:
            logger.error("could not persist paper history to %s: %s — the metrics bar "
                         "will stay empty", self._paper_history_path, exc)
        return hist

    def _running_metrics(self, hist: dict) -> dict:
        """Calmar / Sharpe / MaxDD / return from the live equity curve.

        Daily P&L is the day-over-day change in system equity, with the first day
        measured from ACCOUNT, so the series sums to exactly (equity - account).
        Uses deploy_sim.metrics — same formulas as the backtest, so a live Calmar can
        be compared with the 1.65 floor rather than to something computed differently.
        Imported lazily to keep deploy_sim off the live path's import cost.

        Fewer than two days returns nulls: Calmar over one point is not a number
        worth showing, and the dashboard already renders nulls as dashes.
        """
        empty = {"calmar": None, "sharpe": None, "max_dd": None, "total_return": None}
        days = (hist or {}).get("days") or {}
        account = (hist or {}).get("account")
        if len(days) < 2 or not account:
            return empty
        try:
            from global_index.deploy_sim import metrics as _metrics
            eq = pd.Series({pd.Timestamp(d): v for d, v in days.items()}).sort_index()
            daily = eq.diff()
            daily.iloc[0] = eq.iloc[0] - float(account)
            m = _metrics(daily)
            import math
            # calmar is inf when drawdown is still zero — a real state early in paper,
            # and not something to print as a number.
            _f = lambda v: (None if v is None or not math.isfinite(float(v))
                            else round(float(v), 4))
            return {"calmar": _f(m["calmar"]), "sharpe": _f(m["sharpe"]),
                    "max_dd": round(float(m["maxdd"]), 2),
                    "total_return": round(float(m["pnl"]) / float(account), 6)}
        except Exception as exc:
            logger.warning("running_metrics failed: %s", exc)
            return empty

    def _fill_diagnostics(self, day) -> tuple:
        """(slippage, fill_quality) for `day`, read back from the trade log.

        These two panels were the other half of the "not yet written" group. The
        runner already computes signed slippage per fill (C1) and knows ordered vs
        filled quantity — it just never surfaced either, so execution quality was
        invisible exactly where paper trading is supposed to measure it.

        Ticks rather than dollars: slippage is only comparable across instruments in
        ticks, and the backtest's assumption is stated in ticks (2/side).
        """
        slippage: list = []
        fill_quality: list = []
        if self._trade_log_path is None or not self._trade_log_path.exists() or day is None:
            return slippage, fill_quality

        key = str(pd.Timestamp(day).date())
        try:
            from global_index import specs as _specs
            from futures.basket import BASKET as _BASKET
        except Exception:
            _specs, _BASKET = None, {}

        def _tick(inst):
            c = _BASKET.get(inst)
            if c is not None and getattr(c, "tick", None):
                return float(c.tick)
            if _specs is not None and inst in getattr(_specs, "SPECS", {}):
                return float(_specs.SPECS[inst].tick)
            return None

        try:
            with open(self._trade_log_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except Exception:
                        continue          # a torn last line must not blank the panel
                    if (r.get("exit_day") or r.get("entry_day")) != key:
                        continue
                    ordered = r.get("contracts")
                    filled = r.get("filled_qty", ordered)
                    if ordered:
                        fill_quality.append({
                            "inst": r.get("inst"), "type": r.get("type"),
                            "ordered_qty": ordered, "filled_qty": filled,
                            "partial": bool(filled is not None and filled < ordered),
                            "status": r.get("status"),
                        })
                    slip = r.get("slip")
                    if slip is None:
                        continue
                    tk = _tick(r.get("inst"))
                    slippage.append({
                        "inst": r.get("inst"), "type": r.get("type"),
                        "expected_price": r.get("expected_entry") or r.get("expected_stop"),
                        "actual_price": r.get("fill_price"),
                        # signed: positive = adverse, matching the C1 convention
                        "ticks": round(slip / tk, 2) if tk else None,
                    })
        except Exception as exc:
            logger.warning("fill diagnostics unreadable (%s): %s", self._trade_log_path, exc)
        return slippage, fill_quality

    def _paper_vs_backtest(self, day, cur_eq: float, account: float) -> dict:
        """Live P&L against the backtest's P&L over the SAME window.

        Not equity against equity: the backtest curve has been compounding since 2018
        and stands near $109k, while the paper ledger starts fresh at ACCOUNT on its
        epoch. Comparing those levels would say nothing. Comparing what each made
        between the epoch and today is the question paper trading exists to answer.

        Reads backtest_curve.json (date → equity), written by
        generate_replay_snapshots.py. Absent or not yet covering these dates → nulls.
        """
        out = {"expected_equity": None, "actual_equity": round(float(cur_eq), 2),
               "divergence_pct": None, "epoch": self._system_epoch}
        if self._live_state_path is None or day is None or not self._system_epoch:
            return out
        curve_path = self._live_state_path.with_name("backtest_curve.json")
        if not curve_path.exists():
            return out
        try:
            with open(curve_path, encoding="utf-8") as fh:
                curve = json.load(fh).get("equity") or {}
            if not curve:
                return out
            # Backtest marks are per session; fall back to the latest mark at or
            # before each date so a paper day with no session still lines up.
            def _asof(d):
                ks = [k for k in curve if k <= d]
                return curve[max(ks)] if ks else None

            # The curve must actually reach this date. Without this guard _asof falls
            # back to the last mark for BOTH ends, expected == account, and the panel
            # reports the backtest as flat when the truth is that it has no data here
            # — a stale snapshot file would quietly become a "no divergence" verdict.
            _key = str(pd.Timestamp(day).date())
            _last = max(curve)
            if _last < _key:
                out["stale_through"] = _last
                logger.info("paper_vs_backtest: backtest curve ends %s, before %s — "
                            "re-run generate_replay_snapshots to compare", _last, _key)
                return out

            bt_now, bt_epoch = _asof(_key), _asof(self._system_epoch)
            if bt_now is None or bt_epoch is None:
                return out
            expected = float(account) + (float(bt_now) - float(bt_epoch))
            out["expected_equity"] = round(expected, 2)
            out["divergence_pct"] = round((float(cur_eq) - expected) / float(account), 6)
        except Exception as exc:
            logger.warning("paper_vs_backtest failed: %s", exc)
        return out

    # ── Live state snapshot ──────────────────────────────────────────────────

    def _build_operational_status(self, day) -> dict:
        """Build the 7-item operational_status dict from current runner state."""
        cur_eq = self.state.equity   # SYSTEM equity, not broker balance
        today_ts = pd.Timestamp(day).normalize() if day is not None else None

        # Runner
        runner_item = {
            "alive": True,
            "pid": os.getpid(),
            "last_run_day": str(today_ts.date()) if today_ts is not None else None,
        }

        # Breaker — calls status(cur_eq) which is a pure computation, no state mutation
        breaker_item: dict = {"level": "OK", "dd_pct": 0.0}
        if self.state.breaker is not None:
            st = self.state.breaker.status(cur_eq)
            breaker_item = {
                "level": st["level"],
                "dd_pct": round(st["drawdown_pct"] * 100, 4),
            }
            if st.get("daily_loss_pct") is not None:
                breaker_item["day_dd_pct"] = round(st["daily_loss_pct"] * 100, 4)

        # Regime freshness (G1) — read SPY CSV last date to compute bday_stale
        freshness_item = None
        if self._hmm_stale_guard is not None and today_ts is not None:
            g = self._hmm_stale_guard
            bday_stale = None
            last_spy_str = None
            try:
                from global_index.hmm_stale_guard import _read_spy_last_date, _spy_gap_bdays
                spy_last = _read_spy_last_date(g.regime_csv)
                bday_stale = _spy_gap_bdays(spy_last, today_ts)
                last_spy_str = str(spy_last.date())
            except Exception:
                pass
            if getattr(g, 'regime_unreliable', False):
                f_status = "HARD_BLOCK"
            elif getattr(g, '_g1_soft_active', False):
                f_status = "SOFT_WARN"
            else:
                f_status = "OK"
            freshness_item = {"status": f_status, "bday_stale": bday_stale}
            if last_spy_str:
                freshness_item["last_spy_date"] = last_spy_str

        # Model age (G2) — computed from fit_end
        model_age_item = None
        if self._hmm_stale_guard is not None and today_ts is not None:
            g = self._hmm_stale_guard
            try:
                months = max(0, (today_ts.year - g.fit_end.year) * 12
                             + (today_ts.month - g.fit_end.month))
            except Exception:
                months = None
            if getattr(g, '_g2_hard_notified', False):
                m_status = "URGENT"
            elif getattr(g, '_g2_soft_notified', False):
                m_status = "WARN"
            else:
                m_status = "OK"
            model_age_item = {
                "status": m_status,
                "months_old": months,
                "model_name": "fit_C",
            }

        # Positions — count in memory vs persisted file
        n_open = len(self.state.open_positions)
        persist_match = None
        if self._positions_path is not None and self._positions_path.exists():
            try:
                with open(self._positions_path, encoding="utf-8") as f:
                    _saved = json.load(f)
                _saved_n = len(
                    _saved.get("positions", []) if isinstance(_saved, dict) else _saved
                )
                persist_match = (_saved_n == n_open)
            except Exception:
                persist_match = False

        return {
            "runner": runner_item,
            "breaker": breaker_item,
            "regime_freshness": freshness_item,
            "model_age": model_age_item,
            "positions": {"count": n_open, "persist_match": persist_match},
            "refreeze": {"pending": False},
            "regime_unreliable": bool(
                getattr(self._hmm_stale_guard, "regime_unreliable", False)
            ) if self._hmm_stale_guard else False,
        }

    def _history_snapshots(self, today_snap: dict) -> list:
        """The full snapshot list: one per day of the equity curve, today's last.

        A single snapshot is why the dashboard's Closed Trades, Daily P&L, Per-Cluster
        P&L, Regime Attribution, Cluster Statistics and Holding Distribution were blank
        in live mode. The panels walk snapshots and stamp each exit with its snapshot's
        date, so one snapshot means one point on the equity chart and every trade dated
        today.

        Rebuilt each call from trade_log.jsonl and paper_history.json, both of which
        already exist and are already reconciled against IBKR's statement. No third
        store, so nothing new can drift out of step with them.

        Today's snapshot keeps the live fields the history cannot supply — open
        positions, cluster exposure, regime, breaker level — and takes its trades and
        analytics from the same history so the two cannot disagree.

        Never raises. Losing the dashboard's history must not take a trading slot down;
        the single snapshot is a correct, if bare, fallback.
        """
        try:
            from global_index.live_history import build_snapshots

            records = []
            if self._trade_log_path is not None and self._trade_log_path.exists():
                for line in self._trade_log_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except Exception:
                        continue          # a torn last line must not blank the history
            history = {}
            if self._paper_history_path is not None and self._paper_history_path.exists():
                with open(self._paper_history_path, encoding="utf-8") as fh:
                    history = json.load(fh)

            snaps = build_snapshots(records, history)
            if not snaps:
                return [today_snap]

            # Metrics as at each day, so scrubbing the slider back shows what the book
            # looked like then rather than dashes. Same _running_metrics the live
            # snapshot uses — one formula, fed a truncated curve.
            _all_days = (history or {}).get("days") or {}
            for _s in snaps:
                _upto = {d: v for d, v in _all_days.items() if d <= _s["date"]}
                _s["running_metrics"] = self._running_metrics(
                    {**history, "days": _upto})

            today = today_snap.get("date")
            merged = [s for s in snaps if s.get("date") != today]
            hist_today = next((s for s in snaps if s.get("date") == today), None)
            if hist_today is not None:
                today_snap = {**today_snap, **{k: v for k, v in hist_today.items()
                                               if k not in ("equity",)}}
            merged.append(today_snap)
            return merged
        except Exception as exc:
            logger.warning("dashboard history unavailable (%s) — falling back to the "
                           "current snapshot only", exc)
            return [today_snap]

    def dump_state(self, day) -> None:
        """Write live_state_data.js (window.LIVE_DATA) for dashboard live mode.
        Atomic write via .tmp → os.replace. No-op when live_state_path is None."""
        if self._live_state_path is None:
            return
        cur_eq = self.state.equity   # SYSTEM equity, not broker balance
        today_ts = pd.Timestamp(day).normalize() if day is not None else None
        br = self.state.breaker
        account = br.account if br else 50_000.0
        _cl_keys = ["roska4_swing", "roska4_stress", "global_nkd"]

        # Breaker-derived snapshot fields
        snap_dd_pct = 0.0
        snap_dd_dollars = 0.0
        snap_breaker_level = "OK"
        if br is not None:
            st = br.status(cur_eq)
            snap_breaker_level = st["level"]
            snap_dd_pct = st["drawdown_pct"]
            snap_dd_dollars = max(0.0, br.peak_equity - cur_eq)

        # Open positions for snapshot (display fields only — no sensitive prices)
        open_pos_snap = []
        for p in self.state.open_positions:
            days_held = 0
            if p.entry_day is not None and today_ts is not None:
                try:
                    days_held = max(0, (today_ts - pd.Timestamp(p.entry_day).normalize()).days)
                except Exception:
                    pass
            open_pos_snap.append({
                "inst": p.inst,
                "cluster": p.cluster,
                "direction": p.direction,
                "days_held": days_held,
                "risk_sized": p.risk_dollars,
                "entry_day": str(pd.Timestamp(p.entry_day).date()) if p.entry_day else None,
                "entry_price": p.entry_price,
                "entry_time": None,
                # Since the deferral fix, "no stop" means one of two opposite things:
                # inside the deliberate stop-free window, or genuinely unprotected. The
                # panel cannot tell them apart unless both travel, and a display that
                # cannot tell them apart teaches the operator to ignore the alarm — the
                # same trap check_open_orders had to be fixed for.
                #
                # stop_deferred asks the runner's own predicate rather than deriving it
                # from entry_day and cluster again. A second copy of that rule would
                # drift, and the drift would read as one surface calling a position safe
                # while another calls it naked.
                "stop_price": p.stop_price,
                "stop_order_id": p.stop_order_id,
                "stop_deferred": self._stop_deferred(p),
            })

        # Cluster gross/net exposure (simplified — risk_dollars / account)
        cluster_exposure = {cl: {"gross_pct": 0.0, "net_pct": 0.0} for cl in _cl_keys}
        for p in self.state.open_positions:
            cl = p.cluster
            if cl in cluster_exposure and account > 0:
                pct = p.risk_dollars / account
                cluster_exposure[cl]["gross_pct"] += pct
                cluster_exposure[cl]["net_pct"] += pct if p.direction == "LONG" else -pct

        ops_status = self._build_operational_status(day)
        # Emit persist_match mismatch if detected
        if ops_status["positions"]["persist_match"] is False:
            self._emit_event(
                "WARN", "STATE",
                "persist count mismatch — in-memory and saved file differ",
                {"in_memory": ops_status["positions"]["count"]},
            )

        _slip_diag, _fill_diag = self._fill_diagnostics(day)
        snap = {
            "date": str(today_ts.date()) if today_ts else None,
            "equity": cur_eq,
            "drawdown_pct": snap_dd_pct,
            "drawdown_dollars": snap_dd_dollars,
            "max_dd_dollars": snap_dd_dollars,
            "breaker_level": snap_breaker_level,
            "regime": self._last_regime,
            "open_positions": open_pos_snap,
            "cluster_exposure": cluster_exposure,
            "decision": {
                "realized_today": 0.0,
                "taken_today":    {cl: 0 for cl in _cl_keys},
                "rejected_today": {cl: 0 for cl in _cl_keys},
                "halted_today": 0,
                "entries": [], "exits": [], "rejected_detail": [],
            },
            "per_cluster_pnl":   {cl: 0.0 for cl in _cl_keys},
            "regime_attribution": {},
            "cluster_stats":      {},
            "running_metrics":    self._running_metrics(
                self._record_paper_day(day, cur_eq)),
            "slippage":           _slip_diag,
            "fill_quality":       _fill_diag,
            "paper_vs_backtest":  self._paper_vs_backtest(day, cur_eq, account),
            "operational_status": ops_status,
        }

        meta = {
            "account":          account,
            "hard_dd_pct":      br.hard_dd_pct      if br else 0.15,
            "target_dd_pct":    br.target_dd_pct    if br else 0.10,
            "daily_loss_pct":   br.daily_loss_pct   if br else 0.04,
            "n_contracts":      1,
            "final_equity":     cur_eq,
            "net_pnl":          cur_eq - account,
            # What the two numbers are measured from. The ledger starts at its own
            # epoch, so net_pnl is NOT P&L since paper trading began; broker_equity is
            # the raw account, which moves on FX and commissions the ledger never sees.
            # Labelling them is the whole point — an unlabelled -$6 next to a broker
            # thousands from its starting balance reads as "flat".
            "system_epoch":     self._system_epoch,
            "broker_equity":    self.broker.get_equity(),
            "paper_start":      self._paper_start,
            "max_dd_dollars":   snap_dd_dollars,
            "max_dd_pct":       snap_dd_pct,
            "total_days":       1,
            # Read the live guard rather than restating the caps. The literals here
            # had already drifted: global_nkd stayed at 2% after the sleeve moved to
            # 6%, so the dashboard would have reported a limit the guard no longer
            # enforced.
            "clusters": {
                name: {"max_gross_pct": cb.max_gross_pct,
                       "max_net_pct": cb.max_net_pct}
                for name, cb in self.guard.clusters.items()
            },
            "breaker_events":    [],
            # fit_A degradation floor — must match INVARIANTS.md. Was 1.53, which
            # INVARIANTS had already deprecated twice (bar-0 exit, then nkd cap 2%).
            "backtest_calmar":   BACKTEST_CALMAR_FLOOR,
            "operational_status": ops_status,
            "events":            list(self._events),
            "runner_health": {
                "last_heartbeat": str(today_ts.date()) if today_ts else None,
                "ibkr_connected": None,
            },
        }

        live_data = {
            "runner_health": meta["runner_health"],
            "meta":          meta,
            "snapshots":     self._history_snapshots(snap),
        }

        try:
            js = ("// Auto-generated by FuturesRunner.dump_state — DO NOT EDIT\n"
                  "window.LIVE_DATA = " + json.dumps(live_data, default=str) + ";\n")
            tmp = self._live_state_path.with_suffix(".tmp")
            tmp.write_text(js, encoding="utf-8")
            os.replace(str(tmp), str(self._live_state_path))
        except Exception as exc:
            logger.error("dump_state: failed to write %s: %s", self._live_state_path, exc)
