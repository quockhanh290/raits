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
            if _pid_alive(pid):
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
        "inst":         p.inst,
        "direction":    p.direction,
        "contracts":    p.contracts,
        "risk_dollars": p.risk_dollars,
        "cluster":      p.cluster,
        "entry_day":    str(p.entry_day) if p.entry_day is not None else None,
        "exit_day":     str(p.exit_day)  if p.exit_day  is not None else None,
        "pnl_sized":    p.pnl_sized,
        "exit_pending": p.exit_pending,
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
    )


class FuturesRunner:
    """Drives the daily loop through a Broker. In verify mode, entry candidates carry
    their ledger exit_day/pnl_sized so MockBroker realizes deploy_sim-equivalent pnl."""

    def __init__(self, broker, guard, contracts_by_inst, signal_fn, breaker,
                 hmm_stale_guard=None, positions_path=None, lock_path=None,
                 live_state_path=None, stop_path=None, max_contracts_per_order=10):
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

        # E1: acquire PID lock first — refuse second instance before any state is set up
        self._lock_path = Path(lock_path) if lock_path else None
        if self._lock_path is not None:
            _acquire_lock(self._lock_path)
            atexit.register(_release_lock, self._lock_path)

        # B1: load persisted positions + breaker state if path is supplied and file exists
        self._positions_path = Path(positions_path) if positions_path else None
        loaded_positions: list = []
        loaded_peak_equity = None
        loaded_day_start_equity = None
        loaded_cur_day = None
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
                    # Index broker positions by (inst, direction) for fast lookup.
                    broker_key = {(p.inst, p.direction): p.contracts for p in broker_pos}
                    file_key   = {}
                    for p in loaded_positions:
                        k = (p.inst, p.direction)
                        file_key[k] = file_key.get(k, 0) + p.contracts
                    mismatches = 0
                    for k, qty in file_key.items():
                        broker_qty = broker_key.get(k, 0)
                        if broker_qty != qty:
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
                    if mismatches == 0:
                        logger.info("B3: broker/file positions match (%d position(s))", len(broker_pos))
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

        # Operational event log + live state path
        self._events: list = []
        self._last_breaker_level: str = "OK"
        self._live_state_path = Path(live_state_path) if live_state_path else None

        # D5: kill-switch (STOP_FILE) + F3: fat-finger cap
        self._stop_path = Path(stop_path) if stop_path else None
        self._max_contracts = int(max_contracts_per_order)

        self.broker = broker
        self.guard = guard
        self.contracts = contracts_by_inst
        self.signal_fn = signal_fn
        self._hmm_stale_guard = hmm_stale_guard
        self.state = DecisionState(
            equity=broker.get_equity(),
            open_positions=loaded_positions,
            taken={c: 0 for c in guard.clusters},
            rejected={c: 0 for c in guard.clusters},
            breaker=breaker)

        # Restore breaker state — prevents peak_equity resetting to current on restart.
        # Without restore: peak=current → DD=0% even when real DD is 12%+ → HALT blind.
        if breaker is not None and loaded_peak_equity is not None:
            breaker.peak_equity = loaded_peak_equity
            _cur_eq = broker.get_equity()
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
                self.state.equity += p.pnl_sized  # verify mode: ledger pnl; live: H4 sync later
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

        to_remove = []
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
                to_remove.append(pos)
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

        for pos in to_remove:
            self.state.open_positions = [p for p in self.state.open_positions if p is not pos]

    # ── main daily loop ──────────────────────────────────────────────────────

    def run_day(self, day, _spy_last_date_override=None):
        """One trading day. Returns the DayDecision. Syncs broker to the brain's state.

        _spy_last_date_override: inject spy_last_date directly into HMMStaleGuard.check_day
        (skips CSV read). For offline testing only — not used in production."""
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

        # 1. fetch bars through today (per instrument) — causal
        insts = {p.inst for p in self.state.open_positions} | set(self.contracts)
        bars = {i: self.broker.fetch_bars(i, through=day) for i in insts}

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
            self.broker.send_order(Order(
                t["inst"], "OPEN", t["direction"], n, t["cluster"], day,
                exit_day=t.get("exit"), pnl_sized=t.get("pnl_sized", 0.0)))
            self.broker.send_order(Order(
                t["inst"], "CLOSE", t["direction"], n, t["cluster"], day,
                exit_day=day, pnl_sized=t.get("pnl_sized", 0.0)))

        # H4: sync state.equity from broker after ALL closes (multi-day exits + same-day
        # STRESS_MID). In live mode: captures real intraday pnl including STRESS_MID
        # same-session result → HALT_DAY can fire if that trade lost ≥4%.
        # In verify mode (MockBroker): both track the same ledger pnl → delta ≈ 0 → no-op.
        _h4_eq = self.broker.get_equity()
        if abs(_h4_eq - self.state.equity) > 0.01:
            logger.info("H4: equity sync state=%.2f → broker=%.2f (delta=%.2f)",
                        self.state.equity, _h4_eq, _h4_eq - self.state.equity)
            self.state.equity = _h4_eq
            if self.state.breaker is not None:
                self.state.breaker.update(self.state.equity)
                if not self.state.breaker.status(self.state.equity).get(
                        "allow_new_entries", True):
                    logger.warning(
                        "H4: %s after equity sync — blocking %d multi-day entries",
                        self.state.breaker.status(self.state.equity)["level"],
                        len(_multiday),
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
            self.broker.send_order(Order(
                t["inst"], "OPEN", t["direction"], n, t["cluster"], day,
                exit_day=t.get("exit"), pnl_sized=t.get("pnl_sized", 0.0)))

        # Detect breaker level transitions; emit once per level change
        if self.state.breaker is not None:
            _br_st = self.state.breaker.status(self.broker.get_equity())
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
        # Write live state to dashboard file (no-op if live_state_path is None)
        self.dump_state(day)

        return decision

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
                     halted=self.state.halted, final_equity=self.broker.get_equity()))

    # ── Operational event log ────────────────────────────────────────────────

    def _emit_event(self, level: str, category: str, message: str,
                    context: dict | None = None) -> None:
        """Append a structured event to self._events (bounded 500). Thread-safe only
        for single-threaded use (runner is single-threaded by design — J1)."""
        from datetime import datetime as _dt
        event: dict = {
            "ts": _dt.now().isoformat(timespec="seconds"),
            "level": level,
            "category": category,
            "message": message,
        }
        if context:
            event["context"] = context
        self._events.append(event)
        if len(self._events) > 500:
            self._events = self._events[-500:]

    # ── Live state snapshot ──────────────────────────────────────────────────

    def _build_operational_status(self, day) -> dict:
        """Build the 7-item operational_status dict from current runner state."""
        cur_eq = self.broker.get_equity()
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

    def dump_state(self, day) -> None:
        """Write live_state_data.js (window.LIVE_DATA) for dashboard live mode.
        Atomic write via .tmp → os.replace. No-op when live_state_path is None."""
        if self._live_state_path is None:
            return
        cur_eq = self.broker.get_equity()
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
                "entry_price": None,
                "entry_time": None,
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

        snap = {
            "date": str(today_ts.date()) if today_ts else None,
            "equity": cur_eq,
            "drawdown_pct": snap_dd_pct,
            "drawdown_dollars": snap_dd_dollars,
            "max_dd_dollars": snap_dd_dollars,
            "breaker_level": snap_breaker_level,
            "regime": "Unknown",
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
            "max_dd_dollars":   snap_dd_dollars,
            "max_dd_pct":       snap_dd_pct,
            "total_days":       1,
            "clusters": {
                "roska4_swing":  {"max_gross_pct": 0.05,  "max_net_pct": 0.044},
                "roska4_stress": {"max_gross_pct": 0.025, "max_net_pct": None},
                "global_nkd":    {"max_gross_pct": 0.02,  "max_net_pct": 0.02},
            },
            "breaker_events":    [],
            "backtest_calmar":   2.38,
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
            "snapshots":     [snap],
        }

        try:
            js = ("// Auto-generated by FuturesRunner.dump_state — DO NOT EDIT\n"
                  "window.LIVE_DATA = " + json.dumps(live_data, default=str) + ";\n")
            tmp = self._live_state_path.with_suffix(".tmp")
            tmp.write_text(js, encoding="utf-8")
            os.replace(str(tmp), str(self._live_state_path))
        except Exception as exc:
            logger.error("dump_state: failed to write %s: %s", self._live_state_path, exc)
