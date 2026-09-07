# Stage 5ZB — the negative audit for the causal guards, and what the runtime actually says

**2026-08-25, 06:10–06:45 ET** *(anchored with `zoneinfo`, see below — the shell lies on this
machine)* · read-only throughout · no scheduler or backend restarted · no IBKR connection ·
no order · no confirmation file · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` ·
**no runtime evidence file written, moved, or edited** · no commit.

---

## Verdicts

| | |
|---|---|
| next shadow window | **READY_FOR_NEXT_TRACK1_SHADOW_WINDOW_OPERATIONALLY_AUDITED** |
| paper | **PAPER_NOT_READY** — B1 open, `PAPER_SHADOW_EVIDENCE` at 0 of 5 |
| restart / operator action needed | **none** |
| live or runtime file touched | **none** — every runtime statement below is an inspection |

---

## The correction this stage owes first

**`TZ=America/New_York date` returns UTC in this shell.** I used it in Stages 5X, 5Y and 5Z and
in the first twenty minutes of this one. It cost an hour here: a window three and a half hours
in the *future* was read as four hours *overdue*, and I went looking for a hung scheduler that
was in perfect health.

The three affected report headers have been corrected in place — 5X, 5Y and 5Z each say four
hours earlier now, with a note saying why. No conclusion in any of them depended on the number;
the numbers themselves were simply wrong, and a wrong number left in a document is one the next
reader trusts.

The anchor, which is now the first section of the runbook:

```text
UTC 10:41  ·  ET 06:41 EDT  ·  Calgary 04:41 MDT  ·  Tokyo 19:41 JST
```

The scheduler log stamps **Calgary**. A line reading `04:20` beside a job named
`STOP_REPAIR_0620` is not a contradiction — 04:20 Calgary *is* 06:20 ET. I read that as a
contradiction too.

---

## 1. Re-verifying the 5ZA causal audit

All five claims hold, re-measured rather than re-read:

| claim | how |
|---|---|
| all 70 strategy slots covered | 1 Calm + 24 Stress + 23 Swing + 22 NKD, ids unique |
| each slot validates on data available only up to its own slot time | the 70-slot sweep, rebuilt so the fixture no longer reads the flag it tests — see below |
| no sleeve requires end-of-window data | Calm and Stress declare fixed spans ending ≤ 10:30; only Swing and NKD reach 15:55, and only through the dynamic bound |
| Calm grace bounded | allow at 0/1/3/30/59/60 s, refuse at 61/120/3600 s |
| strategy identity untouched | the gate module cannot import a sleeve rule module, so there is no expression it could change |

The last one is worth stating as *structure* rather than as a hash comparison. Comparing
identity hashes would only say the two agreed on the day the test ran; proving the gate cannot
reach a rule module says it on every day.

And the grace is on `Requirement`, not in `track1_params` — a test asserts the string never
appears in the module whose contents are hashed into identity.

### The fixture that followed the code

The first version of my 70-slot sweep built each slot's frame by reading
`today_to_follows_now` — **the very field the sweep exists to protect.** Mutation M6 flipped the
flag and the test stayed green: the fixture moved with the gate and the two agreed about the
wrong thing.

It now derives the bound from something the gate does not own — whether the sleeve's *declared*
end is still in the future at that slot. Flip the flag now and 22 NKD slots demand 15:55 against
a frame ending at the last closed bar, and the sweep goes red.

This is the "fixture must play the real data source" rule, in the one place where getting it
wrong makes the whole sweep decorative.

---

## 2. The mutation pass 5ZA left pending

**24 mutations, all red**, each with a proven-green baseline first.

| | mutation | caught by |
|---|---|---|
| M1 | the Calm grace removed | 3 s late reads as a missed entry |
| M2 / M2b | the grace becomes an amnesty (3600 s) | an hour late, and two minutes late |
| M3 | the grace edge drifts by one second | the 60/61 boundary |
| M4 | a non-Calm sleeve loses its grace | the per-sleeve declaration |
| M5 | Calm dragged into the dynamic bound | the 5V-1 blanket-`min` mistake |
| M6 | a scanning sleeve stops following the slot | the 70-slot sweep |
| M7 | Stress given an end-of-session span | the fixed-span rule |
| M8 | Stress stops narrowing its scan end | the AST structure test |
| M9 / M10 | Swing/NKD stop clipping to the frame clock, or compute the bound and never apply it | the two halves of the truncation |
| M11 | a sleeve fetches past its own slot | `through=now` on all four builders |
| M12 | Calm returns to the full-day replay detector | the entry-only check |
| M13 | the seam claims `run_shadow` again | the Stage 5W error |
| M14 / M14b | the slot inventory shrinks | the inventory and the sweep |
| M15 | the gate always allows | the sweep's own non-vacuity control |
| M16 / M17 | the gate imports a strategy / the grace leaks into the hashed params | the identity boundary |
| M18 / M19 | the slot stops catching `SpliceRefused` / the column projection removed | the 2026-08-24 crash |
| M20 | a dangling window becomes invisible | the ledger sweep |
| M21 / M22 | the runbook loses an artefact, or the clock anchor | the runbook tests |

### Why these targets and not 5ZA's own

Three of 5ZA's seam tests use `inspect.getsource` plus a substring. Measured: **neither probe
is satisfiable by prose today**, so 5ZA is not wrong — but `getsource` reads the *linecache*, so
a source-level mutation cannot reach those tests at all. They are unbreakable, and an
unbreakable test is one nobody can trust later.

The Stage 5ZB versions read the **file** and walk the **AST**: an assignment to `end` whose
value is a `min(...)` call; a `Compare` of `widx_naive <= now_ts` that is actually used to
subscript `win`. A rewrite that keeps the behaviour and changes the spelling still passes; one
that drops the narrowing does not.

### Two mutations found weak tests rather than weak code

M6 (above) and **M20** — my ledger sweep accepted an empty result, so hiding every ledger file
left it green. *"No dangling windows"* and *"I could not find the ledger"* were the same
answer: the exact defect this route has spent four stages removing from its broker reads, and I
reintroduced it in a test. It now refuses an empty sweep.

---

## 3. Runtime readiness — read-only

```text
scheduler pid 48604   pythonw -m global_index.run_scheduler --port 4002 --shadow-resume --track1-only-shadow
backend   pid 35352   port 5002, responding
track1_mode = track1-only-shadow
broker_connected = True   freshness = fresh (age 9 s)
track1_blocking = ['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
orders_possible = False   confirmation = False   track1_orders_approved = False
```

The scheduler is **healthy and current** — its last log line is 6 minutes old. I initially read
it as six hours stale; that was the clock error, not the scheduler.

Registered work: **70 strategy slots + 11 Track 1 safety jobs = 81**, plus 5 audit, 11 legacy
safety drain and 4 shared, giving the expected **101**. The running process was started at
01:07 ET today, *before* the 5ZA grace change landed at 04:18 — but slot children import fresh,
so every slot from here on runs the current code. **No restart is needed, and none is
recommended.**

---

## 4. What the ledger actually says — two days, and neither is judgeable

Only two days of window coverage exist.

**2026-08-25 (NKD, closed):** 22 slots, all `gate_refused` — 20 `partial_coverage,stale`, 1
`stale`, 1 `too_late`. That is the pre-fix distribution Stage 5V-1 documented; the fix landed
mid-window.

**2026-08-24 (Rổ 4):** 47 slots, and **46 of them refused `overlap_disagreement`** — not the
causal gate at all. The detail is precise:

```text
MNQ: the live half and history disagree on 1 of 1186 shared timestamps in 'low';
first at 2026-08-21 13:45:00-04:00, history says 29400.2500, the feed says 29395.7500
```

**13:45 ET is the daily append boundary.** This is a history-append artefact, and the scheduler
already knows: the pre-flight now runs `update_ibkr_daily --repair-boundary`, with a comment
recording that Friday's equivalents refused 46 slots that day (23 Stress + 23 Swing). The
manual Stage 5R-1 repair touched the parquets at **08-24 23:26 ET — 7½ hours after** the windows
that failed on them.

So the 46 refusals were measured on **pre-repair** history. Nothing about them predicts today.

**And `roska4_calm` opened a window on 08-24 that never closed.** The scheduler log gives the
cause outright: the slot died on an uncaught `SpliceRefused: column_mismatch` — the IBKR feed
hands back `average` and `barcount`, the frozen parquet does not have them. Both halves are
already fixed by another session (`except SpliceRefused` in the slot, and
`project_to_frozen_columns` in the live source), and Stage 5ZB pins both from the file so
neither can quietly come back.

---

## 5. Today's schedule, and what is genuinely new about it

At 06:41 ET, everything below is still ahead:

| ET | what | first time with |
|---|---|---|
| 10:00 | `roska4_calm`, one shot | the dispatch grace, the `SpliceRefused` catch, the column projection |
| 10:35–12:30 | `roska4_stress`, 24 slots | repaired history (manual, 08-24 23:26 ET) |
| 13:45 | pre-flight | **the first automatic `--repair-boundary` run** |
| 14:05–15:55 | `roska4_swing`, 23 slots | today's boundary repaired automatically |
| 16:20 | `spy_refresh_pm` | — |
| 01:10–02:55 (26th) | `global_nkd`, 22 slots | the 5V-1 causal fix, on a full window |

Earlier stage reports — mine included — said the next judgeable window was the NKD one on the
26th. That was true *for NKD* and I presented it as the general answer. **Four windows run
today, and the Calm slot at 10:00 ET is the next one.**

One measurement that looks alarming and is not: `preflight_state.json` records 2026-08-24 while
`spy_daily_live.csv` also ends 2026-08-24, and a live-invariant test in the 5Q4 suite expects
the pre-flight to be one business day ahead. It is not, **because today's pre-flight runs at
13:45 ET and it is 06:41.** Expected, not a defect — but it means that test asserts a condition
that is false for most of every trading day, which is worth someone's attention later.

---

## 6. Blocked by evidence vs blocked by code or a person

| item | blocked by | note |
|---|---|---|
| `PAPER_SHADOW_EVIDENCE` (0 of 5) | **evidence** | needs 5 judgeable days; the first candidate is today's Calm at 10:00 ET |
| `B1_broker_account_or_legacy_retirement` | **operator decision** | about the account, not code |
| paper executor + call site | **neither** | designed, rehearsed end to end, deliberately unwired |
| first-fill safety watch | **operator** | 11 jobs that have never protected a real book |
| stops/exits absent from the order journal | **code**, accepted for the first paper day | the safety jobs write `trade_log`, not the journal |

Nothing on that list is waiting on the order path. It is waiting on days and on one decision.

---

## 7. Tests run

| suite | result |
|---|---|
| Stage 5ZB | **32 passed** |
| Stage 5ZB mutations | **24 red, 0 green** |
| combined: 5ZB · 5ZA · 5V-1 · 5Q3 · 5Q4 · 5S · 5T · 5U · 5V · 5W · 5X · 5Y · 5Z · 5R-0 · schedule mirror (15 files) | **504 passed, 1 failed** |

The one failure is `test_the_live_invariant_holds_on_the_real_files_right_now` — §5 above. It is
a live-state assertion about the pre-flight that is false until 13:45 ET each day, not a
regression from this stage. **Left alone deliberately**: it is another session's test making a
claim about the runtime, and quietly loosening someone else's invariant to get a green run is
how a real signal gets removed.

---

## 8. Files

```text
docs/futures/TRACK1_SHADOW_WINDOW_RUNBOOK.md                  NEW — the post-window checklist
scratch/test_track1_stage5zb_operational_audit_20260825.py    32 tests
scratch/track1_stage5zb_mutations_20260825.py                 24 mutations, all red
scratch/track1_stage5x_broker_readside_20260825.md            clock corrected
scratch/track1_stage5y_order_id_writepath_20260825.md         clock corrected
scratch/track1_stage5z_callsite_dryrun_20260825.md            clock corrected
```

**No production file was modified by this stage.**
