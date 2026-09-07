# Track 1 dashboard wiring, and the shadow acceptance audit

**2026-08-24 ·** scheduler **not** restarted or stopped (pid 33868, unchanged) · backend **not**
restarted — the restart it needs is *reported*, not performed · no IBKR connection · no order ·
no confirmation file · `TRACK1_ORDERS_APPROVED` not set · no `--allow-orders` · no commit.

---

## Shadow verdict right now: **`NOT_ENOUGH_DATA_YET`**

Not a health statement — a statement about how far the session has got. **No Track 1 slot has
been due yet.** The scheduler started at **04:32 ET** and the only window that has closed today
is NKD (01:10–02:55 ET), which closed *before the process existed*. The next window is Calm at
10:00 ET.

Empty coverage is the correct state, and a naive gate would have called it four failed sleeves.

---

## A — the backend env

**Already implemented before this turn, by a parallel session.** I verified it rather than
writing it: `start_backend` takes `track1_shadow`/`track1_only` and passes
`_env(track1_shadow=…, track1_only=…)`; `cmd_up` passes both through. The root cause the brief
identified is confirmed exactly — the scheduler got `_env(flags)` and the backend a bare
`_env()`, so **two children of one `ops.py up` disagreed about which route was running**, each
internally consistent, which is why neither looked wrong.

My contribution here is the **11 tests** that pin it, including the one that starts both
children and requires them to be told the same thing.

**Measured, by driving the real mirror:**

| mode | `_state_slot_table_size()` |
|---|---|
| legacy | 45 |
| `--track1-shadow` | **115** = 45 + 70 |
| `--track1-only-shadow` | **70** |

**A correction to the brief:** it expected track1-only to show `45 + len(TRACK1_SLOTS)`. It
shows **70, not 115** — in track1-only the 45 legacy strategy slots are deliberately *not*
registered. 115 is the transitional number. A mirror showing 115 in track1-only would invent 45
slots the scheduler does not have and manufacture an incident for each of them, every day.

### The running backend must be restarted to apply — reported, not done

| | |
|---|---|
| backend pid 14684 started | **02:32:24** |
| `ops.py` fix landed | **02:50:51** |

The running backend **predates the fix**, which is why `/api/v1/schedule-status` still serves
`state_slot_count=45`. I queried it and it still does — **I did not fake the corrected result.**

```powershell
python monitor/ops.py restart --backend
```

That is the operator's call. The scheduler must not be restarted; it is already correct.

## B — dashboard Track 1 visibility

The fetch and `renderTrack1()` **already existed** (same parallel session). Two real gaps found
and fixed:

1. **`Explanations` was in the payload and never displayed.** Added.
2. **The coverage row read `cov.latest?.date` — a field that does not exist.** `latest` is
   keyed *by sleeve* (`{roska4_calm: {...}, …}`), so the row printed `latest --` on every day,
   **including a fully covered one**. It now reads the sleeve-keyed dict and shows
   `N/M sleeves complete`, the latest day, and the p95 from slot timing. Verified against the
   live payload, which returns `latest={}` keyed by sleeve.

Absence handling was already right and is now tested: **three states, never two** — endpoint
unreachable / route not yet observed / running. `/api/v1/runner-positions` keeps `route=legacy`
and points at the Track 1 endpoint.

## C — the shadow acceptance audit

`global_index/track1_shadow_acceptance.py` gained `windows_status()` and `audit_now()`;
`scratch/track1_shadow_audit_20260824.py` runs it read-only.

**The design decision that matters:** a window is *judgeable* only when it has **closed** AND
the scheduler was up for **all** of it. Three states, not two:

| sleeve | window ET | today |
|---|---|---|
| global_nkd | 01:10–02:55 | closed, **pending** — scheduler started 04:32, after it closed; no slot was ever due |
| roska4_calm | 10:00 | not closed yet |
| roska4_stress | 10:35–12:30 | not closed yet |
| roska4_swing | 14:05–15:55 | not closed yet |

Evidence checks (informational until a window is judgeable): 70 slots wrote no ledger row, no
telemetry, no explanations, no checkpoint — all consistent with "nothing has run yet".
**`no_orders: ok`** and **`safety_paths: ok`** are the two that hold regardless, and both pass.

Hard failures are *not* deferred by "not enough data": an order mark or a confirmation file
fails at 05:00 exactly as it would at 16:00 — tested.

### A defect in my own work, caught before shipping

The verdict constant `FAIL` would have **shadowed the check-status constant** `FAIL = "fail"`
at module scope. Every `c["status"] == FAIL` comparison in `evaluate_day` would then have
compared against `"FAIL"`, which no check emits — **every coverage failure would have stopped
being seen, silently.** The verdict is now `VERDICT_FAIL`; two vocabularies, two names, both
pinned by a test.

## D — what would be required to enable paper orders

**Current evidence is not enough. Nothing was enabled.**

| Requirement | Status |
|---|---|
| B1 resolved — legacy retired, or a dedicated IBKR account funded and confirmed | **open** |
| ≥1 `SHADOW_DAY_PASS`: all four windows judgeable and complete (1/24/23/22), no slot gaps, p95 < 300 s with no slot ≥ 300 s, explanations with freshness proofs, accepted checkpoint | **zero shadow days so far** |
| Checkpoint **identity** verified — the gate reports `not_checked_here`; params-hash acceptance needs the frames (`route_checkpoint.usable` per sleeve) | not done |
| Account-level: broker-flat, no orphan working STPs, legacy book actually drained | not measured — this audit does not answer them |
| Real slot runtimes against a live Gateway, three client ids in play (legacy drain 1, Track 1 data 89, Track 1 safety 90) | never measured |

Deliberately not done: no `track1_go_live_confirmation.json`, `TRACK1_ORDERS_APPROVED` unset,
no `--allow-orders` anywhere.

## Tests

| | Result |
|---|---|
| `test_track1_dashboard_runtime_wiring_20260824.py` (new) | **34 passed** |
| Sweep: wiring + ops status + 5P readiness + 5P text + 5O + `test_ops` + dashboard backend + mirror | **361 passed** |

`global_index/test_event_playback.py` **not run** — known hang.

One of my own tests failed first: the guard for the removed `cov.latest?.date` tripped on the
fix's **own explanatory comment**. It now strips comment lines and checks code — a guard that
cannot survive being documented is a guard that discourages documenting.

## Note on the scheduler PID

It is **33868**, started 02:32:24 local — not the 44904 from the previous turn. The **operator**
restarted it; nothing in this work touched the scheduler.

## Next check

Re-run the audit after 10:00 ET (Calm), and again after 15:55 ET, when windows start becoming
judgeable:

```powershell
python scratch\track1_shadow_audit_20260824.py
```
