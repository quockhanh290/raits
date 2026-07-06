# RAITS Futures — Operational Failure Audit

> **Scope:** Live operational failures — what happens when the runner is RUNNING.
> This is NOT the divergence audit (logic correctness, closed 2026-07-05).
> This is: what breaks when the process crashes, orders fail, state is lost, or two
> instances run at once.
>
> Date: 2026-07-05 | Branch: future/incorporation
> Code base audited: runner.py, broker.py, ibkr_broker.py, signal_layer.py, live_decision.py
> Run after smoke test ALL PASS (net=$52,961.74, diff=$0.00).
>
> **Updated 2026-07-05** — session fixes: B1/C1/C2/C3/C4/E1/E3 + peak_equity implemented,
> 59/59 tests PASS, baseline $52,961.74 preserved. See "Fixed this session" section below.

---

## Classification Key

- **SILENT-WRONG** — runner continues, produces wrong result, no alert. Worst severity.
- **CRASH** — exception propagates, runner stops. Visible, but positions may not exit.
- **GRACEFUL** — handled correctly, exits still run.
- **NO HANDLING** — no try/except, no guard — will crash or silent-fail when first encountered.
- **FIXED** — addressed in code; test verified.
- **DEFERRED (IBKR)** — needs live Gateway to test/implement; cannot verify offline.

Priority = Likelihood × Severity. SILENT-WRONG > CRASH > GRACEFUL.

---

## A. ORDER FAILURES

| Failure | Likelihood | Current | Should | Priority |
|---|---|---|---|---|
| **A1 Order reject** (margin, invalid, market-closed) | Med | `send_order` live path raises `NotImplementedError` → **CRASH** (known, deferred) | Catch `IBKROrderRejectedError`; log + skip instrument for the day; alert. Do NOT retry blind. | DEFERRED (IBKR) |
| **A2 Partial fill** (2 contracts, 1 filled) | Med (thin NKD, limit-move days) | Live path not implemented. When implemented: no fill-qty check planned — runner assumes `contracts == filled` → **SILENT-WRONG** | Add `Fill.filled_contracts`; runner updates `OpenPos.contracts` from Fill (not Order). Risk$ re-computed on actual qty. | **HIGH — before live** |
| **A3 Fill price ≠ expected** | Low (micro futures, normal market) | Not handled. Realized PnL drifts from deploy_sim model → **SILENT-WRONG** (no alert, cumulative drift) | Log `fill_price` vs `order.entry` delta per trade; alert if > 3t. Paper phase will calibrate vs 2t assumption. | LOW |
| **A4 Order timeout** (sent, no ACK) | Med live (IBKR ACK delay) | Not implemented → **DEFERRED** | Timeout wrap in `send_order` (`ib_insync waitForFill`); after timeout: query positions to determine if filled. | DEFERRED (IBKR) |
| **A5 Duplicate order** (retry after crash) | Low | `reconcile_positions()` removes duplicates from runner state IF already there. But: crash after `broker.send_order(OPEN)` completes at IBKR before `decide_day` adds it to `state.open_positions` → restart sends OPEN again, runner thinks no position → **SILENT-WRONG** | `reconcile_positions()` must compare against IBKR actual position list (not just dedup runner state). Gate: check `get_positions()` before any OPEN order. | HIGH — before live |

---

## B. STATE FAILURES

| Failure | Likelihood | Current | Should | Priority |
|---|---|---|---|---|
| **B1 Restart mid-day with OPEN position** | **HIGH** (crash, deploy, reboot, any failure) | ✅ **FIXED 2026-07-05** — `_persist_positions()` writes `live_positions.json` atomically (`.tmp` + `os.replace`) after every `run_day()`; `__init__` loads on startup with try/except corrupt → fresh start + warning. `exit_day` serialized: T6 confirms exit fires on correct day after restart. Ratchet non-issue: T7 confirms `stop` not in `OpenPos`, engine recomputes from bars. Layer 2 (cross-check vs IBKR `get_positions()`) → **deferred, see B3**. | Layer 2: implement `IBKRBroker.get_positions()`; cross-check `live_positions.json` vs broker on startup; alert mismatch. | **FIXED** (layer 1) / DEFERRED (layer 2, IBKR) |
| **B2 live_state.json corrupt/missing** | Low | Covered by B1 fix: `try/except` on load → corrupt → log + fresh start. T2 confirms no crash. | Already handled by B1 fix. | ✅ HANDLED by B1 |
| **B3 Position mismatch broker vs runner** | Med (reconnect, fill race) | `reconcile_positions()` in `IBKRBroker` only removes duplicates from `runner.state` — **does NOT fetch from IBKR or compare broker positions** (`get_positions()` raises `NotImplementedError`). Real mismatch → undetected → **SILENT-WRONG** | Implement `get_positions()`; build `(inst, cluster, direction)` set; compare to `runner.state.open_positions`; flag delta, alert. Use IBKR as truth for position count. | **CRITICAL — before live** |
| **B4 State write fail (disk full)** | Low | `_persist_positions` wraps write in `try/except` → logs error, continues. No crash. | Handled. Alert already logs `B1: position persist failed`. | ✅ HANDLED by B1 |

### B1 Persisted vs Lost State (detail)

| State | Persisted? | After restart | Exit impact? |
|-------|-----------|--------------|--------------|
| `open_positions` (8 fields: inst/direction/contracts/risk_dollars/cluster/entry_day/exit_day/pnl_sized) | ✅ B1 | Loaded from JSON | — |
| `equity` | Not persisted (recovered) | `broker.get_equity()` — IBKR = real equity | None |
| `taken`, `rejected`, `halted` counters | ✗ lost | Reset to 0 | None — per-day stats only |
| `cur_day` | ✗ lost | None → `start_day()` called at next `decide_day` | None |
| **`CircuitBreaker.peak_equity`** | **✗ LOST** | **Resets to `account` ($50k)** | **Entry risk only (not exits)** |
| `CircuitBreaker._day_start_equity` | ✗ lost | None → set to current equity at next `start_day()` | Entry risk only |

**`peak_equity` gap — FIXED 2026-07-05:** `peak_equity`, `_day_start_equity`, and `cur_day` are now persisted inside `live_positions.json` under a `"breaker"` key. On restart, runner restores these to the `CircuitBreaker` instance before first `run_day()`. T12 confirms round-trip (DD=12.7% preserved). T13 confirms HALT fires at 15% DD after restart.

---

## C. SIGNAL FAILURES

| Failure | Likelihood | Current | Should | Priority |
|---|---|---|---|---|
| **C1 Engine exception in generate_today_signals** | Low (data edge cases) | ✅ **FIXED 2026-07-05** — `signal_fn()` wrapped in try/except in `run_day()`. On exception: entries skipped for the day, exit_day-based exits still run, error logged. T3: injected throw → no crash, exit fires, entries=0. | No further change needed. | **FIXED** |
| **C2 HMM label missing today / stale guard throws** | Low (SPY CSV stale — G1 handles it) | ✅ **FIXED 2026-07-05** — `hmm_stale_guard.check_day()` now wrapped in try/except in `run_day()`. On exception: `entries_allowed=False` (conservative block), error logged, exits unaffected. T9: injected throw → no crash, entries blocked. | No further change needed. | **FIXED** |
| **C3 fetch_bars empty/malformed** | Med (IBKR feed gap, NKD off-hours) | ✅ **FIXED 2026-07-05** — After `fetch_bars()`, runner checks each instrument with an open position for empty bars → `logger.warning("C3: ...")` per unique instrument. Exit logic already bar-independent (exit_day-based). T10: empty broker + open position → C3 alert logged, exit still fires. | No further change needed. | **FIXED** |
| **C4 One cluster fails, others OK** | Low | ✅ **FIXED 2026-07-05** — `generate_today_signals()` now wraps each cluster (swing, NKD, stress) in individual try/except. Swing/NKD failure: clears partial state, injects "hold" dummy signals for all held positions → `diff_desired_vs_held` does NOT generate spurious exits. Stress failure: skips (event model, no held state). T4: injected swing throw → NKD engine still called, no crash, no wrong exits. | No further change needed. | **FIXED** |

---

## D. GUARD INTERACTIONS

| Failure | Likelihood | Current | Should | Priority |
|---|---|---|---|---|
| **D1 Breaker halt + G1 stale both fire** | Low | G1 runs first in `run_day()`: sets `entry_candidates=[]`. `decide_day()` finds no entries, breaker marks `halted=0`. Exits run in `decide_day` step 1 **before** any guard check. → **GRACEFUL, idempotent** | No change needed. Log both events clearly. | OK |
| **D2 Re-freeze fail + in trading hours** | Low | Re-freeze pipeline (`futures/refreeze.py`) is **separate** from runner. Runner loads production pkl at startup; refreeze failure sets `pending.json` flag but does NOT affect the running instance. Runner continues with last-good model. → **GRACEFUL** | No change needed. Pending flag re-alerted on next daily call. | OK |
| **D3 Guard fires, OPEN positions held** | Med (breaker can fire intraday) | `decide_day()` step 1 processes exits (`p.exit_day == day`) **before** step 2 (breaker check) or step 3 (entry guard). Exits always run regardless of any guard state. → **GRACEFUL** — by design, exit ordering is correct. | No change needed — the ordering (exits → breaker → entries) is correct. | OK |

---

## E. PROCESS / RESOURCE FAILURES

| Failure | Likelihood | Current | Should | Priority |
|---|---|---|---|---|
| **E1 Duplicate runner instance** | Med (restart misfire, cron double-fire) | ✅ **FIXED 2026-07-05** — PID lockfile (`lock_path=` param, optional/None for tests). `_acquire_lock()` checks if PID alive via `OpenProcess` (Windows) or `os.kill(pid,0)` (POSIX). Live instance → `RunnerLockError`. Dead PID (stale) → overwrite. `atexit.register(_release_lock)` on clean exit. T5: second instance refused; stale lock overwritten. **Windows bug fixed:** `os.kill(pid,0)` = `CTRL_C_EVENT` on Windows (signal 0 == `signal.CTRL_C_EVENT`) → switched to `ctypes.windll.kernel32.OpenProcess`. | No further change needed. | **FIXED** |
| **E2 Runner die without restart** | Med (unhandled exception, OOM, power) | No watchdog. IBKR holds positions, nobody sends CLOSE. → **SILENT-WRONG (orphan position)** | Systemd service with `Restart=on-failure`, or cron monitor. Out of scope for code — operational setup. | MEDIUM (ops) |
| **E3 Clock skew** | Low (VPS with NTP) | ✅ **FIXED 2026-07-05** — After `fetch_bars()`, runner computes latest bar date across all instruments. If `today - last_bar > 3 days`: `logger.error("E3: ...")` + `entry_candidates=[]`. signal_fn still called (for exits); entries discarded before decide_day. T11: bars dated 2024-01-05, today=2024-07-01 (177d) → E3 fires, entries discarded, no crash. | No further change needed. | **FIXED** |

---

## Fixed This Session (offline, 2026-07-05)

All four offline-fixable gaps from original audit implemented and tested.

**Files changed:** `global_index/runner.py`, `global_index/signal_layer.py`
**New test file:** `global_index/test_operational_fixes.py`
**Test results:** 59/59 PASS (T1–T13)
**Baseline:** smoke test `net=$52,961.74 diff=$0.00` — all fixes are no-ops on replay.

| Fix | What changed | Tests |
|-----|-------------|-------|
| **B1** `runner.py` | `_openpos_to/from_dict`, `_persist_positions` (atomic .tmp+replace), load in `__init__` with try/except corrupt | T1 persist+reload, T2 corrupt→fresh, T6 exit_day correct after restart, T7 ratchet non-issue, T8 atomic write |
| **C1** `runner.py` | `signal_fn()` wrapped in try/except in `run_day()`; throw → entries=[], exits via exit_day unaffected | T3 throw→no crash, exit fires, entries skipped |
| **C2** `runner.py` | `hmm_stale_guard.check_day()` wrapped in try/except; throw → entries_allowed=False (conservative), error logged | T9 guard throws→no crash, entries blocked |
| **C3** `runner.py` | After `fetch_bars()`, check each open-position instrument for empty bars → `logger.warning("C3: ...")` | T10 empty bars + open pos→C3 alert, exit still fires |
| **C4** `signal_layer.py` | Per-cluster try/except for swing, NKD, stress; swing/NKD failure injects "hold" dummies to prevent spurious exits | T4 swing fail→NKD still runs |
| **E1** `runner.py` | `_acquire_lock`/`_release_lock`, `RunnerLockError`; `lock_path=` param (None=disabled); Windows uses `OpenProcess` not `os.kill(pid,0)` | T5 second instance refused, stale lock overwritten |
| **E3** `runner.py` | After `fetch_bars()`, compute latest bar date; if today−last_bar > 3 days → `logger.error("E3: ...")` + entries discarded | T11 stale bars (177d gap)→E3 alert, entries discarded |
| **peak_equity** `runner.py` | `_persist_state()` writes `{"positions":[...], "breaker":{"peak_equity":..., "day_start_equity":..., "cur_day":...}}`; `__init__` restores all three to breaker+state on load | T12 DD=12.7% preserved after restart; T13 HALT fires at 15% DD |

---

## Priority Summary (updated)

### Fixed (offline)

| # | Item | Status |
|---|------|--------|
| ✅ **B1** | Position persistence — restart orphan | FIXED (layer 1) |
| ✅ **peak_equity** | CircuitBreaker.peak_equity + day_start + cur_day persisted | FIXED |
| ✅ **C1** | signal_fn() try/except | FIXED |
| ✅ **C2** | hmm_stale_guard.check_day() try/except | FIXED |
| ✅ **C3** | Empty fetch_bars alert for open positions | FIXED |
| ✅ **C4** | Per-cluster isolation in signal_layer | FIXED |
| ✅ **E1** | PID lockfile | FIXED |
| ✅ **E3** | Clock skew sanity check | FIXED |

### Must fix BEFORE live (remaining)

| # | Item | Why |
|---|------|-----|
| 🔴 **B3** | No real broker↔runner position reconciliation | Mismatch silent indefinitely; `get_positions()` → NotImplementedError |
| 🟠 **B1 layer 2** | B1 file not cross-checked vs IBKR on load | File may lag IBKR; needs `get_positions()` first |
| ✅ **peak_equity** | `CircuitBreaker.peak_equity` (+ day_start + cur_day) persisted in live_positions.json | FIXED — T12/T13 |
| 🟠 **A2** | Partial fill not handled | Risk sized on intended qty, not actual |
| 🟠 **A5** | Duplicate order on restart | Position at IBKR + fresh OPEN = double |

### Fix early in live (paper phase)

| # | Item | Why |
|---|------|-----|
| 🟡 **E2** | No watchdog | Process die = orphan until manual intervention |

### Offline-fixable (low priority, before live preferred)

| # | Item | Fix |
|---|------|-----|
| 🟡 **H2** | No bounds check on load — `contracts≤0` / `risk_dollars<0` load silently | Discard invalid positions after load loop in `__init__`; log warning |
| 🟡 **H3** | `benchmark_daily`: duplicate dates not deduped | Add `s = s[~s.index.duplicated(keep='last')]` after `sort_index()` |
| 🟡 **G1/B4** | Persist disk-fail: `logger.error()` only, not `notify()` | After Slack hook live: escalate to `notify("PERSIST FAIL", ...)` |
| 🟡 **J2** | `_SWING_CACHE` memory growth (unbounded, never evicted) | Verify `fetch_bars` returns new object each call; consider eviction policy for long runs |

### Deferred (IBKR required)

| # | Item |
|---|------|
| **A1** | Order reject handling (NotImplementedError, known) |
| **A4** | Order timeout / retry |
| **A3** | Fill price delta logging |
| **B3** | Full reconcile needs `get_positions()` implemented |
| **B1 layer 2** | Cross-check `live_positions.json` vs `get_positions()` on startup; alert mismatch |
| **F1/F3** | Persist-after-order window → duplicate OPEN on restart; fix = idempotent A5 |
| **J1** | Re-assess threading when `ib_insync` async wired |

### No action needed (GRACEFUL by design)

| # | Item | Why OK |
|---|------|--------|
| ✅ D1 | Breaker + G1 both fire | Idempotent, exits unaffected |
| ✅ D2 | Re-freeze fail in trading | Runner unaffected, last-good pkl continues |
| ✅ D3 | Guard fires with held positions | Exits run before any guard check |
| ✅ C3 exits | Empty bars on held position | `exit_day`-based exit, bar-independent |
| ✅ B2 | `live_positions.json` corrupt | try/except on load → fresh start, handled by B1 |
| ✅ F2 | Atomic write correctness | `.tmp`+`os.replace` → no partial-write window |
| ✅ G2 | Persist read: permission/partial-read | `except Exception` + atomic write makes partial-read impossible |
| ✅ G3 | notify() push hook fail | Caught+suppressed by design; console always prints |
| ✅ G4b | Stale lock after SIGKILL | `_pid_alive` check → auto-overwrite on restart |
| ✅ I1 | position+peak_equity atomic? | All fields one `json.dump` one `os.replace` — no split-brain |
| ✅ I2 | Restart race / half-written file | E1 + atomic write → no race |
| ✅ I3 | Empty day (0 pos, 0 signals) | Writes `{"positions": []}` → loads correctly |
| ✅ J1 | Concurrency | Fully single-threaded, no race |

---

## Position Orphan Detail (B1 + E2)

**B1 layer 1 (FIXED):** `live_positions.json` written atomically after each `run_day()`. Loaded on startup. Corrupt → fresh start + warning. Test file: `global_index/test_operational_fixes.py` T1/T2/T6/T7/T8.

**B1 layer 2 (DEFERRED — IBKR required):** The loaded file is the sole source of truth on restart until `IBKRBroker.get_positions()` is implemented. On IBKR account go-live:
1. Load `live_positions.json` (layer 1 — already done)
2. Call `get_positions()` from IBKR
3. Compare: file has position IBKR doesn't (or vice versa) → alert + manual review
4. Source of truth = intersection(file, IBKR) or IBKR-wins with alert

**E2 (ops):** Watchdog (`systemd Restart=on-failure` or equivalent) ensures runner restarts and B1 layer 1 loads positions back within seconds of crash.

---

## F. PERSIST TIMING

> Audit 2026-07-05 (session 2). Separate from B4 (disk-fail). Questions: is the persist window safe? Does exit-before-entry ordering change anything?

| Item | Finding | Priority |
|------|---------|---------|
| **F1 Persist after send_order** | `_persist_state()` is called AFTER all `broker.send_order()` calls in step 5 of `run_day()`. Window: crash after any `send_order()` completes but before `_persist_state()` returns → order at broker, file not updated → orphan state on restart. Root cause same as A5. **No offline fix** — requires A5 (idempotent check via `get_positions()` before OPEN). | DEFERRED (IBKR) |
| **F2 Atomic write correctness** | `.tmp` → `os.replace()` pattern ensures `.json` is always old-complete or new-complete. `os.replace` is POSIX-atomic; Windows NTFS near-atomic (MoveFileExW+REPLACE_EXISTING). Die during `json.dump`: `.json` unchanged. Die during `os.replace`: either state complete. No partial-write window. **CLEAN ✓** | None |
| **F3 Exit-entry die mid-step** | Die after CLOSE exits sent but before OPEN entries sent: broker has exits closed, file has pre-decide_day stale state. Restart: loads closed positions as open → re-submits duplicate CLOSE. Die mid-OPEN loop: some entries at broker, runner unaware → orphan entries. Ordering (exits-before-entries) is correct operationally but does not eliminate the persist-timing window. Same root cause as F1, same fix (A5). | DEFERRED (IBKR) |

---

## G. PERSIST I/O EDGE CASES

> Audit 2026-07-05 (session 2). G1 covered in original B4 (cross-reference). New: G2/G3/G4.

| Item | Finding | Priority |
|------|---------|---------|
| **G1 Disk-fail on write** | Already in B4: `_persist_state()` wraps write in `except Exception` → `logger.error()` + continue, no crash. Alert is log-only (not `notify()`). → After Slack hook live, escalate to `notify("PERSIST FAIL", ...)`. **HANDLED (log); TODO (notify)** | LOW |
| **G2 Permission/partial read on load** | `__init__` load block: `except Exception` catches all — `PermissionError`, `IOError`, partial-read. Partial-read impossible by construction (E1 prevents simultaneous writers; atomic write means `.json` always complete). `PermissionError` → fresh start + `logger.warning`. **CLEAN ✓** | None |
| **G3 notify() push hook failure** | `notify.py`: push hook wrapped in `try/except Exception: pass`. Hook failure (Slack down) → suppressed, console stderr always prints (`flush=True`). Correct design — hook failure must not affect trading. **CLEAN ✓** | None |
| **G4a Lock create permission-denied** | `_acquire_lock()`: write section (`lock_path.write_text(...)`) NOT in try/except. `PermissionError` propagates → constructor fails → runner refuses to start. Fail-safe. Error message is generic `PermissionError`, not runner-specific. **FAIL-SAFE; minor UX gap** | LOW |
| **G4b Stale lock (SIGKILL / no atexit)** | SIGKILL skips atexit → stale lock file. Next restart: `_pid_alive(old_pid)` → False (process gone) → falls through to overwrite. **Auto-recovers ✓** | None |
| **G4c PID reuse** | If stale PID was recycled to a different live process: `_pid_alive` → True → `RunnerLockError`. Manual fix: delete lock file. Documented in error message. Known limitation, low probability. | LOW (ops) |

---

## H. DATA INTEGRITY

> Audit 2026-07-05 (session 2). Schema backward-compat, load validation, CSV dirty data.

| Item | Finding | Priority |
|------|---------|---------|
| **H1 Schema backward-compat (file older than code)** | `_openpos_from_dict`: 5 required fields (`inst`, `direction`, `contracts`, `risk_dollars`, `cluster`) — `KeyError` if missing → caught by outer `except Exception` → fresh start + warning. Optional fields (`entry_day`, `exit_day`, `pnl_sized`) use `d.get()` with defaults. New field added to file (code is older): ignored. New field added to `OpenPos` (file is older) without `d.get()` default: `KeyError` → fresh start (graceful). **No current bug; maintenance discipline required**: future `OpenPos` additions must use `d.get(field, default)` in `_openpos_from_dict`. | LOW (maintenance) |
| **H2 No bounds validation on load** | `_openpos_from_dict` accepts any numeric value. `contracts=-1`, `risk_dollars=-500`: load silently → pnl and guard-cap computed wrong. JSON `null` → `int(None)` → `TypeError` → outer except → fresh start (graceful). Plausible-but-wrong values (numeric but out-of-range) reach `state.open_positions` unchecked. **Offline-fixable**: after load loop in `__init__`, discard any position with `contracts <= 0` or `risk_dollars < 0`, log warning. | **LOW (offline-fixable)** |
| **H3 Regime CSV — duplicate dates** | `_read_spy_last_date`: `.max(skipna=True)` handles NaN, NaT, empty correctly; missing "date" column → `ValueError` → C2 catches → entries blocked. `benchmark_daily`: `sort_index()` sorts but does NOT deduplicate. Duplicate-date rows stay → HMM training sees extra weight for that date, `asof()` picks last value. **Minor effect, no halt**. NaT in index (corrupt date cell): `dropna()` drops NaN in VALUES only; NaT-indexed rows with valid close survive but are excluded from training window by `daily[daily.index <= d]` comparison. **Effectively harmless**. Offline-fixable: add `s = s[~s.index.duplicated(keep='last')]` after `sort_index()` in `benchmark_daily`. | LOW (offline-fixable) |

---

## I. STATE CONSISTENCY

> Audit 2026-07-05 (session 2). Atomicity of persist, restart race, empty-day handling.

| Item | Finding | Priority |
|------|---------|---------|
| **I1 positions + peak_equity atomic?** | **YES — ATOMIC.** `_persist_state()` builds one `payload = {"positions": [...], "breaker": {"peak_equity": ..., "day_start_equity": ..., "cur_day": ...}}` dict, one `json.dump()`, one `os.replace()`. All four fields written in a single atomic replace. Die during `json.dump`: `.json` has prior complete state. Die during `os.replace`: either old or new complete state. **No split-brain window. CLEAN ✓** | None |
| **I2 Restart race / file half-written** | E1 (PID lock) prevents two simultaneous runners → no concurrent write. Crash-loop (sequential restarts): each restart reads last good `.json`. Atomic write ensures file is always a complete snapshot. `.tmp` never read. **CLEAN ✓** | None |
| **I3 Empty day (0 positions, 0 signals)** | `_persist_state()` writes `{"positions": [], "breaker": {"peak_equity": ..., ...}}`. On reload: `loaded_positions = []` (valid empty list), breaker state restored. **CLEAN ✓** | None |

---

## J. ENGINE / THREADING

> Audit 2026-07-05 (session 2). Concurrency model, engine-level global state.

| Item | Finding | Priority |
|------|---------|---------|
| **J1 Concurrency** | Runner is fully **single-threaded**. No `import threading`, `import asyncio`, no `async def`, no `await` anywhere in `runner.py`. `run_history()` is a plain `for day in days:` loop. **No race conditions possible in current implementation. CLEAN ✓**. Note: when `ib_insync` (async event loop) is wired, runner threading model must be reassessed — order callbacks and `run_day()` may execute on different event-loop threads. **Defer to IBKR wiring.** | DEFERRED (IBKR async) |
| **J2 `_SWING_CACHE` module-level mutable dict** | `_validated_core.py` L197: `_SWING_CACHE = {}` — module-level mutable dict. `_swing_cache(df)` keys by `id(df)`. **Single-threaded: no race.** Live daily use: safe if `broker.fetch_bars()` returns a new object each call (cache miss each day → fresh compute → correct). **Unsafe if df is extended in-place** (same `id()` → stale cache hit → precomputed daily arrays missing new bars). Memory: one cache entry per unique df object, **never evicted** — unbounded growth in a long-running process (252 days/yr × full swing arrays). **Action: (1) verify `fetch_bars` returns new object; (2) note memory growth for long-running deployment.** | **MEDIUM (verify before live)** |

---

## What This Audit Does NOT Cover

- Logic correctness (divergence audit, closed 2026-07-05 — all reconcile PASS)
- HMM model quality (trust audit 2026-07-05 — STRESS_MID/scaling/fit_C confirmed)
- Backtest validity (vault 2023-2024 locked, OOS +$7,404 Sharpe=0.88)
- Live slippage realism (paper phase measures this)
