# Stage 5H — B1 retirement / Track 1 shadow-start preflight

**2026-08-23 · audit only · no scheduler started, no IBKR connection, no order, no dashboard
write, no confirmation file, no `STOP_TRADING`, no commit.** One documentation correction was
appended to the runbook; no production behaviour was changed.

---

## Verdict: **NOT_READY_FOR_SHADOW_START**

Everything Stage 5G left in place is verified good. The blocker is small, precise, and it is
**code, not an operator step**:

> **`main()`'s `live-shadow` branch never builds a bar provider, and there is no
> `--bar-provider` flag.** The factory Stage 5G moved into `track1_live_source.build_bar_provider`
> has **no caller on the scheduler path**, so every Track 1 slot refuses with `no_bar_provider`.

Measured by running the exact command a slot issues, with a temporary ledger directory:

```
slot TRACK1_CALM_1000 seq=0  decided=False  reason=no_bar_provider
window closed: 0 of 1 decided (1 slots ran)
checkpoint: NOT written — the window did not complete
send_order calls: 0
```

Ledger rows written: `window_open` · `slot_observed (no_bar_provider)` · `window_closed
(incomplete)`.

Starting the shadow scheduler today would freeze legacy, run 25 slots a day, and write rows that
faithfully record that **nothing was collected**. Preconditions 5 and 6 stay shut — correctly.
That is not a reason to start.

**This is not a claim about live orders.** Orders remain impossible and this stage is shadow-only.

---

## [R] Read-only checks completed

### 1. Gate state — from code, not from the report

| check | result |
|---|---|
| `live_frame_wiring()` | **released=True** — `track1_live_source (IBKRBroker, fetch_bars, fetch_session_bars, ib_insync, reqHistoricalData)` |
| `blocking()` | `['B1_broker_account_or_legacy_retirement']` |
| `self_check()` | `[]` |
| confirmation file | **absent**, no parse errors |
| `may_enable_orders()` | **False** |
| `--allow-orders` | **exit 2**, names B1 + unset `TRACK1_ORDERS_APPROVED`, does not name the closed blocker |

### 2. Runbook — all seven points present

`STOP_TRADING` before **any** scheduler start · shadow still registers the legacy jobs and all
23 entry slots · do-not-write-the-confirmation-file-yet · `RAITS_WINDOW_LEDGER_DIR` named and
its refusal documented · Track 1 shadow uses `live-shadow`, not replay · no `--allow-orders` ·
dashboard/parity expectations · broker provider still untested.

**One gap, patched (docs only):** the runbook did not say the slot cannot obtain a provider
today. A Stage 5H correction was appended under precondition 8 with the measured output above.

### 3. Scheduler registration — built and discarded, never started

| | shadow OFF | shadow ON |
|---|---|---|
| jobs | 60 | 84 |
| Track 1 slots | 0 | **25** (1 Calm + 24 Stress, `track1_calm_1000` … `track1_stress_1230`) |
| legacy entry slots | 23 | **23 — unchanged** |
| removed by shadow | — | `stop_repair_1220` only |
| legacy jobs still present | — | 59 |

Track 1 slot argv:

```
-m global_index.run_live_day_track1 --source live-shadow --sleeve <s> --slot-id <id> --regime-csv <csv>
```

No `--allow-orders`. No `--port`. No `--window`, so a production shadow slot **cannot silently
replay vault2026**. The scheduler's Stress window and the slot table's required window are equal.

**Legacy jobs are still registered under shadow, so `STOP_TRADING` before any start remains
mandatory.**

### 4. Kill-switch semantics

Legacy reads `STOP_TRADING`; Track 1 reads `STOP_TRADING.track1` — **distinct, no cross-route
confusion.** Legacy's D5 clears `entry_candidates` and leaves exits untouched, which is what
makes a drain possible.

**One thing an operator must know before starting:** `_catch_up_maxhold(sched)` runs **before**
`sched.start()`. On a weekday after 09:31 ET it immediately runs a max-hold pass that **reads the
broker**, and `STOP_TRADING` does not prevent it — D5 governs entries, not exits, by design.
Today is Sunday ET, so a start right now would not trigger it; a weekday start connects at once.

### 5. Ledger and freshness

- `RAITS_WINDOW_LEDGER_DIR` **unset** → the slot raises `ledger_not_configured` **before anything
  else happens**, so a slot that could not record its own run never proceeds.
- With a temp dir → the slot runs and writes `window_open` / `slot_observed` / `window_closed`.
- **File-naming caveat, worth stating:** the coverage file is named by the **UTC write date**
  while the records carry the **ET session day**. A slot for session `2026-08-24` wrote
  `window_coverage_20260823.jsonl`. An operator looking for today's file by ET date may not find
  it; `window_ledger.read_day()` handles this by filtering on the record's own `date` field.
- Freshness binding for `live` / `live-shadow` is intact (Stage 5AB-G1 contract re-run green).

### 6. Broker provider — fakes only, nothing connected

| call | result |
|---|---|
| `build_bar_provider("none")` | `(None, None)` — a manual run cannot dial out by accident |
| `build_bar_provider("ibkr", broker_cls=FakeBroker)` | builds `IBKRBarProvider`, calls `connect()` on the **fake** |
| real libraries imported | `ib_insync` **no**, `global_index.ibkr_broker` **no** |
| unknown kind | refused, `unknown_bar_provider` |

**Cleanup expectation for the real run, undocumented in code:** the factory returns
`(provider, broker)` precisely so the caller can `disconnect()` in a `finally`. Since no caller
exists yet, no disconnect path exists either — whoever wires `--bar-provider` owns that.

---

## [OP] Operator actions — **none performed**

Written for the day the blocker above is cleared. Nothing below was executed by this stage.

**0. First, close the code blocker (not an operator step).** Wire a `--bar-provider {none,ibkr}`
selector into the `live-shadow` branch so it calls `build_bar_provider` and passes the result to
`observe_live_slot`, with a `finally: broker.disconnect()`. Until then steps 4–5 collect nothing.

**1. Decide B1: retire legacy on the same account.** Not a separate account, unless you say
otherwise — path A is the stated end state and the cheaper of the two. Decide it; do not write
anything yet.

**2. Place the legacy kill switch before any scheduler start.**
```powershell
if (-not (Test-Path STOP_TRADING)) { New-Item -ItemType File STOP_TRADING }
```
Not before the final swap — before the **first** start of any kind. Shadow mode keeps all 23
legacy entry slots, so a start without it resumes legacy trading.

**3. Export the ledger directory.**
```powershell
$env:RAITS_WINDOW_LEDGER_DIR = "<dir>"
```
Unset means every live-shadow slot hard-refuses. This must be in the **scheduler's** environment,
not just the shell you test from.

**4. Start the scheduler in Track 1 shadow mode.**
```powershell
python -m global_index.run_scheduler --track1-shadow
```
On a weekday after 09:31 ET this immediately runs a max-hold pass against the broker. Starting on
a weekend or before 09:31 avoids that.

**5. Confirm the first window writes ledger rows.** Expect `window_open`, one `slot_observed` per
slot, and `window_closed`. With step 0 done these should read `decided=true`; without it they will
read `no_bar_provider` and the window will close `incomplete`.

**6. Confirm no orders.** `blocking()` still returns B1; no confirmation file; no Track 1 slot
carries `--allow-orders`; `--allow-orders` by hand still exits 2.

**7. Only after real shadow evidence** — coverage `complete` on every trading day of a measured
period, and a checkpoint `track1_bootstrap.accepts(...)` accepts — consider the B1 confirmation
and live-order approval. **That is a later stage, not this one.**

---

## Tests

| suite | result |
|---|---|
| Stage 5AB-G1 + 5G · 5C · 5D | **60 passed** |
| Stage 5E · 5F · slot telemetry · slot overlap | **91 passed, 1 skipped** |
| Stage 3B · 4C · scheduler-shadow-verify · heartbeat · dashboard-live-snapshot · log-hygiene | **154 passed, 1 skipped** |
| Stage 5B runbook fix (after the doc correction) | **22 passed** |
| Stage 5Y wiring · 5Z freshness/root · explain | **185 passed, 1 failed** |

`global_index/test_event_playback.py` was not run.

**The one failure is out of scope and pre-existing:**
`scratch/test_track1_explain_20260823.py::test_no_monitor_or_dashboard_file_mentions_the_module`
— `monitor/test_schedule_status_track1_20260823.py`, created by another session, mentions
`track1_explain` and trips that session's own guard. `monitor/` was not touched here.

---

## Confirmation of what did not happen

No scheduler started or stopped (0 `run_scheduler` processes). No IBKR connection — the provider
path was exercised with a fake broker class and neither `ib_insync` nor `global_index.ibkr_broker`
was imported. No order sent. No dashboard runtime write. No `STOP_TRADING`, no
`STOP_TRADING.track1`, no `track1_go_live_confirmation.json`. `TRACK1_ORDERS_APPROVED` unset. No
commit — `HEAD` is unchanged at `601970b`. The only write outside `scratch/` is a documentation
correction appended to the runbook.

---

## Remaining before a shadow scheduler

1. **`--bar-provider` wiring** — the named blocker. Code, small, and nothing collects without it.
2. **B1** — legacy retirement or a separate account. Still the only thing holding the order gate.
3. **Operator**: `STOP_TRADING` before any start; `RAITS_WINDOW_LEDGER_DIR` in the scheduler's
   environment.
4. **A real broker provider has still never been connected.** Stage 5G moved where it is
   constructed; whether it works against IBKR is untested and cannot be tested offline.

**Not claimed anywhere:** that Track 1 is ready for live orders.
