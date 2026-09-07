# Stage 5ZZW — the dashboard was answering about the other route

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## 1. What caused "runner state stale"

Two facts, both true, measured from the live backend:

```text
ops.py status          track1_mode = track1-only-shadow   (source: process_table)
                       track1_slot_table = fresh, 71/71

/api/v1/schedule-status
                       route_mode          = legacy
                       freshness           = stale        (365 ks ≈ 4.2 days)
                       unexplained_overdue = 22
                       legacy_runner.inactive_by_design = false
                       state_slot_count    = 45
```

The stale source is the **legacy runner state file**, and it is stale because in track1-only
shadow nothing writes it. That was already understood — Stage 5ZF built the suppression for it.
The suppression never fired, because it is gated on `inactive_by_design`, and that came out
`false`.

**Root cause, one line apart:**

| | reads |
|---|---|
| `ops.py` | the **scheduler's** command line, from the process table |
| `schedule_status.track1_only_enabled()` | **this backend process's** `RAITS_TRACK1_ONLY` |

`ops.py` sets that variable on both processes when it starts them. The backend that was serving
had been started without it, so it answered `legacy` about a machine running track1-only. Every
downstream answer followed: the suppression stayed off, and the slot mirror expected the legacy
table for a scheduler that registers none of it — **22 phantom overdue slots**, the rail's second
trigger, entirely separate from the first.

`ops.py` carries a comment about this exact class of bug being fixed once already, for itself.

---

## 2. Why it was wrong in track1-only shadow

The legacy snapshot's age is not a fault in this mode — it is the intended steady state, and a
rail that reads "attention required" for the whole shadow period is a rail nobody reads by the
time something real happens. That is this project's recurring failure, and Stage 5ZF wrote it
down; the machinery was right and the input was wrong.

---

## 3. What the top rail uses now

The backend resolves the mode from **the scheduler**, and keeps three answers:

```text
route_mode           track1_only_shadow
route_mode_source    scheduler_process_table
route_mode_known     true
freshness            not_expected_yet     (was: stale)
unexplained_overdue  0                    (was: 22)
state_slot_count     71                   (was: 45)
legacy_runner.state_stale   true          — still reported, no longer route health
```

`None` — the scheduler could not be read — is carried as `unknown` and rendered as UNKNOWN. It
is never collapsed into `legacy`: "I could not check" is not "I checked and it was legacy", and a
mutation exists for each direction.

**Where the resolution happens matters.** The first version resolved it inside
`get_schedule_status`, which made the live payload right and **26 tests wrong** — every suite that
describes a machine by clearing the environment started reading the real process table. A test
that is not isolated is worse than no test. So the mode is a **parameter**: `app.py` passes the
resolved answer because the scheduler is the authority for the live page, and every other caller
keeps exactly the behaviour it had.

### Wording

- "Legacy runner snapshot is stale because legacy entries are retired" — a sentence, where
  `runner state stale (4d 5h)` used to sit.
- "Track 1 scheduler needs attention" rather than a bare "scheduler attention required", and the
  chip reads **Track 1 scheduler** in this mode.
- "scheduler mode unknown — could not read the scheduler" when nobody could look.

---

## 4. Which issues left the main count

The backend already labelled every issue with a `route_scope`; nothing needed inventing. What is
new is a measured answer to *is legacy actually retired on this login*, requiring all three:

```text
confirmation        True        the operator signed the B1 decision
scheduler_mode      compatible  the running mode agrees with it
legacy_entry_jobs   0           and it registers none
```

Any of them unreadable and the answer is **not retired**. A legacy issue shown beside Track 1's
is noise; a legacy issue hidden while legacy could still trade is the one that costs money, so
this fails toward showing too much.

```text
before   8 issues, all counted
after    6 issues → 3 active · 3 retired history
```

The three that left are `paper:lifecycle`, `paper:pnl:paper_flex_total_mismatch` and
`paper:decision_path` — scoped legacy because they compare the **legacy** paper ledger against
broker statements and read no Track 1 artefact. The count dropped 8 → 6 separately, because
Stage 5ZZU's stream fix merged the SPY retry rungs into one ladder issue.

**Nothing is deleted.** Every issue still travels in the payload with `counts_as_active` and a
reason beside it, and the rest sit under a **Legacy / retired history** group.

### A defect the tests found on the way

The retirement was first computed inside `_build`, which is memoised on the scheduler log
signatures plus the date. A second read with the opposite answer returned the first from cache.
Whether legacy is retired is a fact about the **running scheduler** and can change with no log
line written here at all — an operator restarting into legacy mode leaves these files untouched —
so the answer would have stayed frozen while legacy came back. It is applied per read now,
outside the cache. The comment on the roll-schedule cache key, two lines above, records the same
trap.

---

## 5. Which HMM / regime issues stay visible

`known_debt:model_age` remains **active** and always counts.

It was grouped under **Legacy** — survivable while both were shown, and a real hazard the moment
the legacy group stopped counting: the model-age debt would have gone quiet along with it. It now
has its own **Model / Regime** group, and the chip reads `MODEL` rather than `DEBT`. Two tests and
a mutation hold it there; the 5ZZH test that asserted it lands under Legacy is superseded and now
asserts the opposite.

Regime verification failures and unknowns are untouched — `track1_window_audit` failures and the
regime record's own `verification` block are both unchanged by this stage.

---

## 6. Model Inputs

It read the legacy runner snapshot. In track1-only shadow nothing writes that file, so the panel
was showing a Regime label from whenever legacy last ran, presented as today's.

| Field | now reads |
|---|---|
| Regime | `marketView.regime.label` — the Track 1 regime record |
| SPY data | `regime.label_date` — the session the published label belongs to |
| Fit end | `regime.inputs.fit_end` |
| label check | `regime.verification.status`, in the Fit end tooltip |

`Fit end` had **no setter at all** — a dead field showing `--` since it was added. It is wired now.

The legacy reading survives as a fallback so a machine with no Track 1 record reads exactly as
before, and when neither is available the panel says "Track 1 record unavailable" rather than
reporting a stale legacy value as current. The panel is no longer marked `runner-derived`.

---

## 7–8. Gates

`PAPER_SHADOW_EVIDENCE` is **the only Track 1 blocker**, and `orders_possible` is `False`.

No gate, schedule, strategy or order behaviour changed. This stage edited two monitor backend
readers, the dashboard script and its HTML.

*(B1 was blocking for part of the morning — the account baseline record had passed its 24-hour
freshness policy, as recorded in Stage 5ZZU. The operator refreshed it; B1 is closed again. Not
this stage's doing, and it is why two tests here assert `PAPER_SHADOW_EVIDENCE in blockers`
rather than pinning the exact list.)*

---

## 9. Tests

| | |
|---|---|
| New suite | **30 passed** |
| Adjacent backend / dashboard / ops suites | **698 passed**, 6 failed |
| Mutations | **14/14 caught** |

Mutations break the suppression in **both** directions on purpose — one that stops it firing, one
that makes it unconditional so a live legacy fault would go quiet — and the retirement in both,
one that hides too little and one that hides too much.

M10 came back green twice before it was right. The first version moved a deep copy while still
recomputing the answer each read, so it never reproduced the defect; green was the honest verdict
until the mutation actually froze the answer.

Six adjacent tests were updated, five of them deliberate supersessions of things this stage
changed (the debt group, the group headings, the group list) and one a thirteenth instance of the
pre-B1 staleness family Stage 5ZZS restated elsewhere. One genuinely pre-existing failure was
fixed while passing: a pinned-fact list had been missing `Blockers come from` since Stage 5ZZK.

The 6 remaining failures are pre-existing and previously measured: three expect a Calm slot from
before Calm became two phases, two are a rule grid and a `JSON.stringify` in the market-view
render path from 5ZZL/5ZZR, and one is the intermittent DOM test recorded in Stage 5ZZU.

---

## 10. Backend restart

**Required.** `schedule_status.py`, `open_issue_reader.py` and `app.py` are imported once per
process, and the running backend (pid 20212) started at 03:13 — before any of this. It will keep
serving `route_mode: legacy` until restarted. `realtime.js` and `index.html` are static and a
browser reload picks them up, but they read fields only the new backend emits.

Not done here. A backend-only restart does not disturb the scheduler.

### Verified through the endpoints after the change

```text
/api/v1/schedule-status   route_mode track1_only_shadow · known true · source scheduler_process_table
                          freshness not_expected_yet · overdue 0 · slots 71
                          legacy_runner.state_stale still true, reported as its own line
/api/v1/open-issues       6 total · 3 active · 3 retired history · retired true
```

---

## 11. Still open

- The three Calm-band tests and two render-path assertions above.
- `ops.py` still propagates `RAITS_TRACK1_ONLY` to the backends it starts. That is now a
  convenience rather than the source of truth, and the two can no longer disagree on the live
  page — but a backend started by hand still answers from the environment for any caller that
  does not inject the mode.
