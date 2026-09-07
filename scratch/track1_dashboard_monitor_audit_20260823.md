# Track 1 — dashboard and monitor audit

**Session 2026-08-23 · read-only · Stage 5X Part A**

Nothing in the monitor was modified. No scheduler was started, no broker was contacted, no
dashboard file and no runtime state file was written. Every number below was produced by
running the real reader against real or constructed input, not by reading the code and
inferring what it would do.

---

## 1. How data reaches the screen

There is one Flask process. It serves four pages and thirteen JSON endpoints, and it holds
**no database** — every endpoint is a parse of a file on disk (or of the broker socket),
cached on the file's modification time.

### The chain, source to pixel

| Source on disk | Reader | Endpoint | Page that asks for it |
|---|---|---|---|
| IB Gateway socket (client id 99) | `ibkr_reader` | `/api/v1/broker`, `/api/all`, `/api/positions`, `/api/orders`, `/api/account`, `/api/connection` | Realtime, Reports |
| `global_index/live_state_data.js` | `runner_state_reader` | `/api/v1/runner-state` | Realtime |
| `live_positions.json` | `runner_positions_reader` | `/api/v1/runner-positions` | Realtime |
| `global_index/runner_events_YYYYMMDD.jsonl` | `runner_event_reader` | folded into `/api/v1/runner-state` | Realtime |
| `trade_log.jsonl` | `entry_time_reader` | folded into `/api/v1/runner-state` | Realtime |
| `scheduler_*.log` | `schedule_status` | `/api/v1/schedule-status` | Realtime |
| `scheduler_*.log` | `job_journal_reader` | `/api/v1/job-journal/<day>` | Realtime |
| `scheduler_*.log` + `live_day_*.log` | `session_event_reader` | `/api/v1/session-events/<day>` | Realtime |
| `trade_log.jsonl` + broker fills | `execution_quality_reader` | `/api/v1/execution-quality[/<day>]` | Realtime, Analytics |
| every log + `trade_log.jsonl` + `monitor/paper_pnl_compare.json` | `paper_evidence_reader` | `/api/v1/paper-evidence` | Paper |
| all of the above | `report_reader` | `/api/v1/reports/<day>` | Reports |
| several readers | `open_issue_reader` | `/api/v1/open-issues` | Realtime |

The Realtime page calls eight endpoints; Paper calls one; Analytics calls one; Reports calls
two.

### Route awareness

**There is none, with a single narrow exception.**

The word *route* appears in the monitor in only two meanings, and neither of them is Track 1:
the broker's execution venue on a fill, and an internal name for a stop-placement reconcile
lane. No reader filters on a route field, no endpoint takes a route parameter, and no page
has a concept of two trading systems running side by side.

The exception is the schedule mirror, which grows Track 1's slots when
`RAITS_TRACK1_SHADOW=1` is set in the backend's environment. **I measured what that flag
actually changes**, on a pinned Monday with a pinned clock, comparing the whole
`/api/v1/schedule-status` payload with the flag off and on:

| ET instant | Fields of the payload that differ |
|---|---|
| 07:00 | *(none)* |
| 09:50 | `next_scheduled_job` only |
| 11:00 | `next_scheduled_job` only |
| 12:15 | `next_scheduled_job` only |

The slot table used for the *health* signals is a different table from the one used for
"what runs next". Measured on the same Monday:

```
scheduled-job mirror   flag off: 57 slots    flag on: 81 slots   (+25 Track 1, −1 stop-repair)
state/freshness table  flag off: 45 slots    flag on: 45 slots   (+0)
```

So with the mirror enabled, Track 1 slots change the caption that says which job is next —
and nothing else. They contribute no evidence row, cannot raise an incident, cannot make the
freshness rail go late, and do not widen the active-window band (which is still the two
legacy bands, 01:10–02:55 and 14:05–15:55, so a Track 1 window at 10:35–12:30 sits inside a
period the dashboard labels "not expected yet").

This is not a defect in the mirror — it was written to keep the dashboard from manufacturing
a fake incident for an unknown slot, and it does that. It is a statement about how much of
Track 1 the dashboard can currently see: **the next-job caption, and nothing else.**

---

## 2. What the dashboard displays today

| Concept | Where it comes from | State |
|---|---|---|
| **Positions** | broker socket, plus the runner's own persisted book, plus the snapshot's open list; entry times recovered from the trade log | live and populated |
| **Entries / exits** | the snapshot's `decision.entries` / `decision.exits` | **structurally always empty — see §3.1** |
| **Rejected candidates** | the snapshot's `decision.rejected_detail`, plus a regex over a warning line in the day log | **snapshot channel dead; only the log-line regex works — see §3.1** |
| **Risk / caps** | equity, drawdown, drawdown limit, gross exposure, cluster exposure, stop coverage | live and populated |
| **Scheduler status** | log parse: which slots were due, which produced a closing line, which failed, which recovered | live and populated |
| **Runner events** | the append-only JSONL the runner emits | live and populated |
| **Paper P&L** | trade log reconciled against the broker's own statement | live and populated |
| **Model health** | the HMM fit diagnostic lifted out of the session events | live and populated |
| **Open issues** | aggregated across readers, with an open/recovered lifecycle | live and populated |

---

## 3. What Track 1 and explainability could break

### 3.1 The decision panel is already dead, and Track 1 would inherit the same hole

This is the finding worth acting on first, because it is not about Track 1 at all.

The runner builds its per-session snapshot with a decision block containing four fields —
counts taken, counts rejected, count halted, and a detail list. **All four are initialised
empty and nothing ever writes into them.** I searched the runner for any later assignment
into that block and found none.

Measured against the ten sessions currently on file in the live snapshot:

```
snapshots on file                                10
snapshots with a non-empty rejected detail        0
snapshots with a non-empty entries list           0
summed "taken today" across all clusters          0
summed "rejected today" across all clusters       0
```

Measured against the backtest replay snapshots, which are produced by a *different* file and
which the same page can display:

```
replay snapshots                               1749
with a non-empty rejected detail                648
example row: MYM LONG, roska4_swing, risk $964.02,
             reason cap_net, "roska4_swing net 5.0% > cap 4.4%"
```

So the backtest fills this channel and the live path does not. That is the same live-versus-
backtest split this project has already paid for twice, arriving in the telemetry layer
instead of the trading layer. The front end renders "No decision evidence emitted" every
session, and *no decision evidence* is indistinguishable from *no signal today* — precisely
the conflation the day-runner's own comment says must not be allowed to happen.

The day-runner avoided it by writing the rejection to the **log** as a sentence:

```
2026-08-10 13:41:00  WARNING  run_live_day -   REJECTED SHORT MNQ (roska4_swing)
                     risk_sized=$3340.54 — roska4_swing gross 10.9% > cap 5.0%
```

Two readers then recover it with a regular expression over that prose. That works today. It
is also the exact shape of failure this repo has been bitten by before — a live-job detector
that asked whether the word "python" appeared in a line turned every traceback frame into a
phantom job launch, because interpreter paths contain the word. Identifying a decision by
substring on free text is a bet on the sentence never changing.

**Consequence for Track 1:** if Track 1's decisions are surfaced the same way, they inherit a
channel that is empty by construction and a fallback that depends on nobody rewording a log
line. The explainability record replaces the sentence with a row: the value, the threshold,
and the symbol that compared them.

### 3.2 Sharing the trade log would silently fold Track 1 into legacy's gates

The paper-evidence reader opens `trade_log.jsonl` at the repository root and aggregates
**the whole file**. It splits on nothing — not on route, not on strategy, not on account.
Its output drives pass/fail gates on fill quality, on P&L reconciliation against the broker
statement, and on the clean-session streak.

If Track 1 writes trades into that file, legacy's fill-quality gate starts grading Track 1's
fills and legacy's P&L reconciliation starts including Track 1's P&L, with no way for a
reader to tell which rows are which. Track 1's own slot table already says as much and
prescribes a separate file; this audit confirms the reader behaves as that note claims.

### 3.3 Two slot-id namespaces, and Track 1 is in neither

The scheduler keys a job by its APScheduler id. The dashboard never sees APScheduler — it
parses the log and keys on the label the scheduler prints in brackets. For 56 of 58 timed
jobs the two strings coincide; two are aliased by hand.

Track 1's slot ids exist in the mirror only, and only behind the environment flag. The
journal's job classifier maps an unrecognised id to the bucket "other" (measured: a Track 1
calm slot and a Track 1 stress slot both classify as `other`, while a legacy afternoon slot
classifies as `live_day`), which is tolerant. But the journal's **name-to-id** mapper, which
is what recognises a *missed* job, returns nothing for a Track 1 job name (measured). A
Track 1 slot that never fires would therefore not be reported as missed.

### 3.4 One reader drops unknown fields on the floor

See §4. The persisted-positions reader is an allow-list, and a `route` field added to a
position row would be silently removed before it reached the page.

---

## 4. Which readers tolerate unknown fields

Measured by feeding each reader a record carrying two fields it has never seen — `route` and
`explain_id` — and reading back what survived.

| Reader | Behaviour | Measured |
|---|---|---|
| Runner events (JSONL) | **Tolerant.** Requires only a timestamp; the whole object is passed through untouched. | fed `{ts, kind, route, sleeve, explain_id, rule_ids}`, all six keys came back |
| Persisted positions | **NOT tolerant.** Nine-key allow-list; anything else is dropped. | `route` and `explain_id` both absent from the output |
| Runner state (the snapshot) | **Tolerant.** Parses the whole assignment as JSON and returns it. Extra keys inside a snapshot survive; the *front end* only renders what it knows. | by construction — no projection step exists |
| Job journal | **Tolerant on the id** (unknown ids classify as "other") but **not on the name** (an unknown job name maps to nothing, so a missed Track 1 job is not detected) | both directions measured, §3.3 |
| Schedule status | **Refuses unknown slots by design.** A slot in the log that the mirror does not know becomes a manufactured incident; that is why the mirror exists. | mirror comparison, §1 |
| Paper evidence | **Tolerant of unknown fields, blind to route.** Aggregates the whole trade log with no split. | §3.2 |
| Execution quality | Tolerant; already reads an optional `route` field, but that means the broker's venue | code read, no route semantics |

**The rule this produces for Track 1:** additive fields are safe on the event JSONL and on
the state snapshot, unsafe on the persisted-position file, and irrelevant on the paper
evidence path because the problem there is a missing *split*, not a rejected *field*.

---

## 5. Recommended integration path

Three steps, in this order, each provable before the next begins.

**Step 1 — side channel only.** Explanations go to
`scratch/track1_shadow/explanations_YYYYMMDD.jsonl`. No reader reads it, no endpoint serves
it, no page renders it. What this buys: the record format gets exercised against real
decisions and its gaps show up while nothing depends on it. The writer is bounded to that
one directory in code, not by convention — see the design note.

**Step 2 — a route-scoped endpoint of its own.** A new reader and a new endpoint that serve
only explanation records, filtered by route, sleeve, instrument, date and status. Nothing
existing is edited. A new endpoint cannot break an existing one, and a new reader that
crashes takes down one panel instead of the page.

**Step 3 — only then, if it is still wanted, a link from the existing panels.** A row in the
schedule journal or the decision panel gains a link to an explanation id. This is the only
step that edits a legacy path, and it should not be taken until steps 1 and 2 have produced
records from real sessions.

**What must not happen at any step:** widening an existing schema, changing what an existing
endpoint returns for a caller that did not ask for Track 1, or writing Track 1 rows into
`trade_log.jsonl`, `live_positions.json`, `live_state_data.js` or any `live_day_*.log`.

---

## 6. Two things this audit did not settle

- **Whether the empty decision block was designed that way.** The runner initialises those
  four fields and never fills them; the backtest generator fills all four. That could be a
  deliberate decision to route live rejections through the log instead, or it could be a
  wiring gap nobody has noticed. The distinction changes what the fix is, and I have not
  found anything that states the intent either way. Flagged, not concluded.

- **Whether the front end would survive an extra field it does not know.** The state reader
  passes unknown keys through, so they reach the browser. I did not run the page against a
  snapshot carrying them, because doing so means driving the real dashboard, which is
  outside the read-only contract this session was given. Unverified, not "safe".
