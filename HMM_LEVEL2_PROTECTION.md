# HMM Level-2 Protection: Stale SPY Data Halt

**Branch:** `future/incorporation`  
**Scope:** Equity live feed only — futures/global_index untouched.  
**Constraint:** No changes to `engine.py`, `decision_unit.py`, retrain logic, fit logic, or exit logic.

---

## Problem

`daily_data["SPY"]` passed to `LivePolygonFeed` is a static snapshot set at session startup.  
It is **never refreshed** from live WebSocket bars.  
If the snapshot grows stale (e.g. operator forgets to update it before a Monday session), the HMM retrain runs on old data and the regime model silently degrades.

The existing **Level-1** guard (>5 bdays stale) emitted a WARNING and skipped the weekly retrain.  
That was necessary but not sufficient: a silent skip means the operator doesn't know entries are now based on a stale regime model.

---

## Solution: Level-2 Hard-Stale Guard

Two thresholds:

| Threshold | Trigger | Action |
|---|---|---|
| **SOFT** (>5 bdays, Level 1 — existing) | warn + skip retrain | No halt |
| **HARD** (>10 bdays, Level 2 — new) | warn + skip retrain + **HALT NEW ENTRIES** + **NOTIFY** | Entries blocked |

---

## Files Changed

### `raits/live/notify.py` (new)

```
raits/live/notify.py
```

Operator notification module. `notify(level, message)` emits a prominent **boxed stderr alert** that is visible even when stdout is redirected. A `_PUSH_HOOK` callable can be registered to forward alerts to email/Slack/PagerDuty.

```python
from raits.live.notify import set_push_hook

def my_slack_handler(level: str, message: str) -> None:
    slack_client.chat_postMessage(channel="#trading-ops", text=f"[{level}] {message}")

set_push_hook(my_slack_handler)
```

### `raits/decision/types.py` (modified)

Added `regime_unreliable: bool = False` to `BarContext` (after `orb_signal_end`).

```python
# Regime reliability flag — set by the live feed when daily_data["SPY"] is
# hard-stale (> _HARD_STALE_SPY_BDAYS behind). When True, PaperTrader blocks
# new entries but keeps normal exit logic (stops/targets are pre-committed and
# HMM-independent). Always False in backtest / replay.
regime_unreliable: bool = False
```

Always `False` in `ReplayContextFeed` and backtest. Backwards-compatible (defaulted).

### `raits/live/context_feed.py` (modified)

- Added `_HARD_STALE_SPY_BDAYS = 10` constant.
- Extracted `_spy_gap_bdays(close, cur_day) -> int` helper (shared by `_iter_test` and `_iter_live`).
- Refactored `_check_stale_and_warn` to call `_spy_gap_bdays`.

**`_iter_test` (test-mode path):** staleness check runs at every day boundary using `self._daily["SPY"]` (not `mkt["SPY"]`). Sets `_regime_unreliable`, calls `notify()` on transition, passes flag to `_iter_test_day` → `BarContext`.

**`_iter_live` (real WebSocket path):** identical logic at day boundary. Also calls `notify("TRADING RESUMED", ...)` on recovery.

**Recovery condition:** `gap <= _STALE_SPY_BDAYS` (5 bdays, the soft threshold). This prevents oscillation if gap hovers near 10.

**`_iter_test_day`:** added `regime_unreliable: bool = False` parameter; propagated to every `BarContext(...)` yield.

### `raits/live/runner.py` (modified)

**`RunResult`:** added `entries_blocked_regime_unreliable: int = 0`.

**`PaperTrader.run()`:**

```python
_regime_unreliable_notified_today = False  # reset at each day boundary

# Step 4: Entries
if getattr(ctx, "regime_unreliable", False):
    n_blocked = len(decision.entries)
    if n_blocked:
        result.entries_blocked_regime_unreliable += n_blocked
        if not _regime_unreliable_notified_today:
            logger.warning("REGIME_UNRELIABLE halt: %d entry signal(s) BLOCKED ...", ...)
            _regime_unreliable_notified_today = True
else:
    for entry_intent in decision.entries:
        # normal entry processing
```

Exits (Steps 1–3) are completely unchanged — they run before the entry check.

`getattr(ctx, "regime_unreliable", False)` — defensive access so `MockContextFeed` with old-style `BarContext` objects still works.

---

## Architecture

```
daily_data["SPY"] (static snapshot)
       │
       ▼
_spy_gap_bdays()          ← shared helper
       │
       ├─ gap > 10 → notify("TRADING HALTED") + _regime_unreliable = True
       ├─ gap > 5  → logger.warning (Level-1 soft stale, skip retrain)
       └─ gap ≤ 5  → (if was unreliable) notify("TRADING RESUMED") + clear
                      else: normal
       │
       ▼
BarContext(regime_unreliable=_regime_unreliable)
       │
       ▼
PaperTrader.run()
  ├─ exits  → always process (Steps 1-3, HMM-independent)
  └─ entries → BLOCKED if regime_unreliable=True (Step 4)
```

---

## Operator Runbook

When a **TRADING HALTED** alert fires:

1. **See the notification** — boxed alert on stderr (or email/Slack if push hook is registered).
2. **Check the gap** — the alert message shows the business-day gap, e.g. *"HMM regime data STALE 15 business days"*.
3. **Refresh `daily_data["SPY"]`** — fetch recent SPY daily closes and re-inject into the feed before the next session.
4. **Halt auto-clears** — at the next day boundary, when `gap <= 5`, the feed emits *"TRADING RESUMED"* and resumes entry signals automatically.

**Open positions are safe.** Existing stops/targets/MAX\_HOLD/EOD exits continue to fire normally — they are absolute price levels set at entry, not regime-dependent.

**TODO (live-prep):**
- Push notification (email/Slack) for unattended live sessions — wire via `set_push_hook`.
- Auto-refresh `daily_data["SPY"]` at session startup (REST fetch of recent SPY closes) so stale never happens.

---

## Note: Futures Staleness (do not implement here)

Futures uses a frozen 2024 model that silently decodes 2025+ bars with no weekly adaptation. It needs a **model-age staleness guard** (fit-date too far from current date), NOT a `daily_data["SPY"]` check. Design separately in the futures session. No futures code was changed in this task.

---

## Tests Added

### `raits/tests/live/test_context_builders.py`

| Test | What it verifies |
|---|---|
| `test_spy_gap_bdays_empty_returns_zero` | Empty series → 0 |
| `test_spy_gap_bdays_one_day` | 1-bday gap computed correctly |
| `test_spy_gap_bdays_hard_stale` | Large gap > `_HARD_STALE_SPY_BDAYS` |
| `test_hard_stale_daily_spy_sets_regime_unreliable` | >10 bday gap → all bars `regime_unreliable=True`, "TRADING HALTED" on stderr |
| `test_soft_stale_daily_spy_no_regime_unreliable` | 6–10 bday gap → `regime_unreliable=False` |
| `test_fresh_daily_spy_no_regime_unreliable` | 1 bday gap → `regime_unreliable=False` |

### `raits/tests/live/test_live_runner.py`

| Test | What it verifies |
|---|---|
| `test_regime_unreliable_blocks_entries` | `regime_unreliable=True` → entries blocked, counter increments |
| `test_regime_unreliable_exits_still_fire` | Existing position exits normally despite `regime_unreliable=True` |
| `test_regime_unreliable_recovery_resumes_entries` | After flag clears, entries resume, counter stays 0 |
| `test_notify_halt_format` | `notify()` emits boxed message with border on stderr |

**Suite result: 181/181 passed** (up from 171 before this session).

---

## What Was NOT Changed

- `engine.py` — untouched
- `decision_unit.py` — untouched
- `configs/final_params.yaml` — untouched (sealed Vault params)
- `config_private.py` — untouched (API key)
- Retrain logic, fit logic — untouched
- Exit logic (stop/target/MAX\_HOLD/EOD) — untouched
- `ReplayContextFeed` — untouched (`regime_unreliable` is always `False` in backtest)
- Futures / global\_index — untouched
