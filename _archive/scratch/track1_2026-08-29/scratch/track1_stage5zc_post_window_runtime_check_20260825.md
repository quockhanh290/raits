# Stage 5ZC — the first judgeable windows after 5ZB, and why one of them never ran

**Checked 2026-08-25, ET 11:12–11:19** · read-only throughout · nothing restarted · no broker
call initiated · no order · no confirmation file · `TRACK1_ORDERS_APPROVED` unset · no
`--allow-orders` · **no runtime evidence written, moved or edited**.

```text
UTC     2026-08-25 15:19    ET      2026-08-25 11:19 EDT
Calgary 2026-08-25 09:19    Tokyo   2026-08-26 00:19 JST
```

Anchored with `zoneinfo`, per the runbook. The scheduler log stamps **Calgary**.

---

## Verdicts

| | |
|---|---|
| next shadow window | **READY** — the route itself is working; see the Stress rows |
| `global_nkd` 01:10–02:55 (closed) | **FAIL** — 22 slots, 0 decided, audited FAIL. Pre-fix window |
| `roska4_calm` 10:00 (closed) | **NOT_ENOUGH_DATA** — the slot never ran |
| `roska4_stress` 10:35–12:30 | **still OPEN**, not judgeable. 2 of 2 slots so far decided cleanly |
| `roska4_swing` 14:05–15:55 | ahead |
| PAPER readiness | **0 of 5** qualifying days (1 judgeable day on record, and it is a FAIL day) |
| operator action needed | **YES — one, and it is not code.** See §2 |

---

## 1. The Calm window did not run, and the cause is not Track 1

No `window_open`, no slot row, no `window_closed`. Yesterday it at least opened a window before
crashing; today there is nothing at all.

The scheduler's own instrumentation says why, in its own words:

```text
09:12:00  WARNING  [HEARTBEAT] STALLED 13020s (expected ~60s). The scheduler's wait timer
does not advance while Windows sleeps, so every job due in that window was missed and every
later one was pushed back by the same amount.
```

**The machine slept for 13,020 seconds — 3 h 37 m**, from roughly 07:35 to 11:12 ET. The
process survived; its timer did not. Everything due inside that window was missed and logged as
missed:

```text
Stop repair 08:20 ET                 missed by 2:51:35
MAX_HOLD exit 09:31 ET               missed by 1:40:35
Track1 roska4_calm 10:00 ET          missed by 1:11:35   <-- the window
Track 1 audit sleeve roska4_calm     missed by 1:01:35   <-- and its audit
Stress 10:35 / 10:40 / … / 11:05     all missed
Stress 11:10 ET                      RAN — the machine had woken
```

So `roska4_calm` is **NOT_ENOUGH_DATA**, not FAIL. Nothing about the sleeve, the gate, the
splice or the strategy was exercised. The dispatch grace, the `SpliceRefused` catch and the
column projection are all still unproven in production — they have simply never had a slot to
run in.

### My 5ZB "scheduler is healthy" call was correct when made

Worth stating, because I doubted it. The heartbeat is **hourly**; at the 5ZB check (Calgary
04:39) the last line was 04:20 and the last heartbeat 04:00 — 39 minutes on an hourly cadence,
which is normal. The sleep began after the 05:00 heartbeat, an hour later.

---

## 2. This is chronic, and it is the real blocker on paper evidence

Not a one-off. Every scheduler log that records a stall records at least one:

| | |
|---|---|
| log files containing a stall | **16 of 16** |
| stall events | **33** |
| total scheduler time lost | **79,620 s = 22.1 hours** |
| today | 13,020 s (3.62 h) — the second worst on record |
| worst | 2026-08-20, 13,080 s (3.63 h) |

**No amount of work on the strategy, the gate or the order path moves this number.** Judgeable
days need the scheduler awake at 10:00, 10:35–12:30 and 14:05–15:55 ET, and on this evidence it
is asleep for part of most days.

The remedy is printed in the log message itself. It is a **system power setting and an operator
action — I have not run it**:

```powershell
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0
powercfg /setactive SCHEME_CURRENT
```

The log only names the `dc` (battery) form; the `ac` form matters too if the machine is ever on
mains, and setting one without the other leaves half the problem. Worth confirming with
`powercfg /q SCHEME_CURRENT SUB_SLEEP STANDBYIDLE` afterwards.

**No scheduler or backend restart is needed** — the process recovered on its own and is running
current code.

---

## 3. The route itself is working — the first decided slots on record

Two Stress slots ran after the machine woke, and both **decided**:

```text
15:11:55Z  TRACK1_STRESS_1110  decided=true  gate=true  freshness_allow=true  candidates=0
15:15:19Z  TRACK1_STRESS_1115  decided=true  gate=true  freshness_allow=true  candidates=0
```

These are the **first `decided` rows anywhere in the ledger**. They are the "legitimate
no-candidate / no-action" case: the intraday gate passed, freshness passed, the sleeve looked
and found nothing to take. That is a working shadow slot, and it is the first evidence that the
whole chain — live frame, splice, gate, freshness, sleeve, explanation — runs end to end on
live data.

`overlap_disagreement` did **not** appear. Yesterday it refused 46 of 47 Rổ 4 slots; today, on
repaired history, neither of the two slots hit it. Two slots is not a proof, but it is the first
counter-evidence.

### Explanations: present, and correctly empty

Both slots wrote a run-level record under
`shadow/explanations/live_2026-08-25/roska4_stress/TRACK1_STRESS_11{10,15}/`, carrying a
structural freshness proof:

```text
rule_id  CONTEXT.FRESHNESS_OBSERVED     decision_mode  shadow_live
data_source_identity  NQ_continuous_1m_8y.parquet:a13167b1…c7877c1
freshness_allow  passed=true
```

No candidate rows, because there were no candidates — and the ledger says so explicitly
(`candidates: 0, accepted: 0, explained: 0`). **Absence is recorded, not merely absent**, which
is the condition the runbook demands before calling this a pass.

---

## 4. `global_nkd` — closed, FAIL, and already explained

22 slots, 0 decided:

```text
partial_coverage,stale   20      hard refusal
stale                     1      hard refusal
too_late                  1      benign, window-shut
```

Audited at 03:05 ET: `FAIL`, reasons `[coverage_incomplete, slot_could_not_evaluate,
no_candidates_to_explain]`, and the audit itself records `judgeable: true` with the reason
*"window closed and the scheduler was up before it opened"*.

This is the **pre-fix** window — the Stage 5V-1 causality fix landed mid-window, between the
02:45 and 02:55 slots. The first NKD window that can be judged on the fixed gate is
**2026-08-26 01:10 ET**.

---

## 5. Timing — clean

| | |
|---|---|
| coverage slot rows | 24 |
| timing rows | 24 |
| coverage without timing | none |
| timing without coverage | none |
| p50 / p95 / max | 2.5 s / 18.7 s / **19.1 s** |
| any ≥ 300 s | **none** |

The 19.1 s maximum is `TRACK1_STRESS_1110` — 0.1 s setup, 19.0 s observe, which is the live
IBKR fetch on the first slot of a window. Every NKD slot ran in ~2.5 s.

---

## 6. A ledger asymmetry worth naming

`roska4_stress` has slot rows and **no `window_open`**, because `window_open` is written by the
window's first slot and that slot was eaten by the sleep. At 12:30 the last slot will write
`window_closed`, giving a window that closed without ever opening.

The runbook currently teaches the opposite case — *opened and never closed* — as the loud
signal. **Closed-without-open is the equally informative inverse: the window's first slot never
ran.** The audit should refuse to call such a window judgeable, and today's Stress window is the
first chance to check that it does. That check is at **12:40 ET**, ten minutes after the window
closes.

---

## 7. Dashboard — consistent, with one label collision

Read-only `GET /api/v1/schedule-status` and `/api/v1/track1-runtime`.

Consistent with the ledger on every point that matters:

```text
server_now         15:15:35Z            active_window       true
next_scheduled_job TRACK1_STRESS_1120   latest_expected_at  15:15Z
evidence           TRACK1_STRESS_1115 completed OK  (state: executed)
incidents          0                    open_incidents      []
scheduler_process  pid 48604 running, stale_code false
```

**No phantom overdue rows** for slots that ran, and no hidden dangling window. The Track 1
endpoint independently reports 2 explanation files for `roska4_stress` across 2 slots, the book
absent with the correct reading, both gate blockers, and
`not_audited_yet: [roska4_calm, roska4_stress, roska4_swing]` — Calm is *named as unaudited*
rather than silently missing, which is the right behaviour.

### The one discrepancy: two different fields called "freshness"

| where | value | what it measures |
|---|---|---|
| `monitor/ops.py status` | `fresh`, age 9 s | the **IBKR connection** |
| `/api/v1/schedule-status` | **`stale`**, age 32.3 h | the **legacy runner's state snapshot** |

Traced to source: `app.py` builds `observed_at` from `read_runner_state(LIVE_STATE_PATH)` —
the **legacy** route's state file. During a `track1-only-shadow` period the legacy runner never
runs, so that file is stale by design and will stay stale for as long as the shadow lasts.

**Classified as a dashboard-reader mismatch, not a runtime failure.** Runtime evidence does not
corroborate any staleness: the scheduler is current, the slots are running, and Track 1 has its
own endpoint. It raises no incident, so nothing is being masked — but a rail that reads "stale"
throughout a healthy shadow period is a rail an operator learns to ignore, which is the same
argument that produced `open_incidents` in the first place. **Left unchanged**; recorded for
whoever owns the reader.

---

## 8. Orders remain impossible

```text
orders_possible          False
blocking                 B1_broker_account_or_legacy_retirement, PAPER_SHADOW_EVIDENCE
confirmation file        absent
TRACK1_ORDERS_APPROVED   unset
--allow-orders in argv   no
order journal dir        absent
live_positions.track1    absent
track1_dry_run           absent
```

Scheduler argv: `--port 4002 --shadow-resume --track1-only-shadow`.

---

## 9. Paper readiness — measured, not estimated

`track1_paper_readiness.readiness()` against today:

```text
judgeable_days                    FAIL   1 on record, 5 required   (2026-08-24)
no_failing_days                   FAIL   1 FAIL day, at most 0 allowed
warn_days_within_allowance        ok     0 WARN days
evidence_is_recent                ok     newest qualifying day is 1 day old
every_sleeve_passed_at_least_once FAIL   never passed: all four sleeves
```

**PAPER_SHADOW_EVIDENCE: 0 of 5 qualifying days.** One day is judgeable and it failed; no sleeve
has ever recorded a PASS. Today is not counted — the day is not over.

---

## 10. The two pre-existing failures, classified

**`test_the_live_invariant_holds_on_the_real_files_right_now` (5Q4)** — still failing, checked
at 11:17 ET. The pre-flight runs at **13:45 ET**, so `preflight_state` (2026-08-24) is not yet
one business day ahead of the SPY csv (2026-08-24). **Time-dependent expected failure**, as
classified in 5ZB. Not touched, not loosened. Re-check after 13:45 ET.

**`test_the_live_ledger_rows_are_explained_and_untouched` (5V-1)** — this one was **mine, and it
was wrong.** In Stage 5W I pinned the NKD distribution by asserting the *day file* held exactly
22 rows, on the reasoning that the window had closed. The window had; the **file** had not — it
is one ledger per DAY, shared by every sleeve, and it broke the moment Stress wrote into it at
11:11 ET.

Same family as pinning a line count on a log that is still being appended to. Fixed by scoping
to `global_nkd`, which keeps the exact distribution — the durable fact — without pinning the
size of the file it happens to live in. A second test now pins the shared-file property itself
so the next person meets it as a stated fact rather than a surprise.

---

## 11. Tests run

| suite | result |
|---|---|
| 5ZB · 5ZA · 5V-1 · 5Q4 · 5S · 5Z · schedule mirror (7 files) | **198 passed, 1 failed** |
| the one failure | `5Q4::test_the_live_invariant…` — §10, time-dependent |

---

## 12. What to check next, and when

| ET | what |
|---|---|
| **12:40** | the Stress audit. Does a window that closed **without opening** get refused as unjudgeable? |
| **13:45** | the pre-flight — first automatic `--repair-boundary`; the 5Q4 invariant should pass after it |
| **14:05–15:55** | Swing, 23 slots, on today's repaired boundary |
| **16:20** | `spy_refresh_pm` |
| **01:10 (26th)** | the first NKD window on the fixed causal gate |

And before any of it matters: **the sleep setting**. On the current record the scheduler will be
asleep for part of tomorrow too.

---

## 13. Files

```text
scratch/track1_stage5zc_post_window_runtime_check_20260825.{md,json}   this report
scratch/test_track1_stage5v1_intraday_causality_20260825.py            over-narrow pin fixed
```

No production file was modified. No runtime evidence was written or edited.
