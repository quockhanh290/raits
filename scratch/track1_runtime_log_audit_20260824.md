# Stage 5Q-LOG — the whole Track 1 day, read back from what it left behind

**2026-08-24, read at 19:46 ET.** Read-only throughout. Scheduler and backend **not** started,
stopped or restarted (pid 28696 and pid 11720, both unchanged since this morning) · **no IBKR
connection opened** · no order · no confirmation or order file created · **no parquet, CSV or
state file mutated** · no runtime evidence written or deleted · no audit run outside the
scheduler's own · no commit. The only files this session created are the two deliverables in
`scratch/`. **B1 held all day and holds now.**

**Three clocks.** Machine in Calgary (MDT), market on ET, and every scheduler log line is
stamped in **machine** time. **ET = log line + 2h.** Everything below is ET.

**Latest evidence:** ledger and timing both end **15:55:03**; audits end **16:15:02**.

---

## Verdict: **NOT_READY_NEW_RUNTIME_BLOCKER**

Today was a good day for the *machinery* and a blocked day for the *data*. Every audit fired,
every window that could open did open and close, refusals landed as named records instead of
silence, and telemetry started producing rows mid-morning. Three of the blockers named this
morning are now closed in code.

What stops a cleaner verdict is two things, one of them new:

- **B-5R-F stopped being a risk and became a rate.** Today's 13:45 append left a partial last
  bar on **three of five instruments**. That is not a Friday leftover — it is what one ordinary
  day costs, and the appender's strictly-newer rule guarantees none of the three is ever
  revisited.
- **Tomorrow morning is already blocked, and a scheduler restart tonight does not unblock it.**
  The daily series is one trading day short of what tomorrow requires, and every job that could
  fill it fires *after* the Calm and Stress windows. This is a sequencing consequence of
  B-5R-E's open half that the current handoff does not cover.

---

## 1. Processes

| | |
|---|---|
| Scheduler | **pid 28696**, started **09:25:31** |
| | `pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume --track1-only-shadow` |
| Backend | **pid 11720**, started **09:27:38** |
| | `python.exe monitor/start_backend.py --ibkr-port 4002 --api-port 5002` |
| Mode | **track1-only-shadow** — confirmed from the command line, from `ops.py status`, and from the job table itself |
| Broker | connected, fresh (5.4s) |
| Orders | **impossible** — `orders_possible=false`, blocking `B1` |

**Both processes are running code from before 12:24.** `stale_code: true` is not a warning to
dismiss: the scheduler's job table was frozen at 09:25:31, so anything added to the source at
12:24 is simply not in it. Child slot processes are spawned fresh every five minutes and *do*
pick up new code — which is why fixes landed mid-morning without a restart, and why the job
table did not.

### Job inventory — every expected count matches

| | expected | in the running scheduler |
|---|---|---|
| Track 1 strategy slots | 70 | **70** ✓ |
| Track 1 safety jobs | 11 | **11** ✓ |
| Track 1 audit jobs | 5 | **5** ✓ |
| Legacy drain safety jobs | 11 | **11** ✓ |
| Shared infra | 3 or 4 | **3** — `heartbeat`, `preflight`, `session_report_fallback` |
| Legacy strategy jobs | 0 | **0** ✓ (45 explicitly not scheduled) |
| | | **total 100** |

### SPY_REFRESH_PM

It is in the scheduler source (16:20 cron) and in the dashboard mirror's fixed-slot table. It
is in **neither running process**, because both started before those edits.

That is worth stating precisely, because the two halves of the answer point opposite ways: the
*files* have drifted apart from the *processes*, but the two processes agree with **each
other** — so the dashboard has not manufactured a phantom overdue row, and `unexplained_overdue`
is empty. The mirror only becomes a problem if the scheduler is restarted and the backend is
not.

The consequence is not cosmetic: **16:20 passed today with no SPY refresh.** See §4.

---

## 2. The day, in order

| ET | Job | Category | Outcome | Ledger | Timing | Expl. |
|---|---|---|---|---|---|---|
| 09:25:31 | scheduler start | infra | 100 jobs registered | — | — | — |
| 09:31 | `MAX_HOLD_EXIT` (legacy) | safety | ok, 10s | — | — | — |
| 09:31 | `TRACK1_MAX_HOLD_EXIT` | safety | ok, **1s** — no positions file, returns before the lock and before any connect | — | — | — |
| **10:00** | **`TRACK1_CALM_1000`** | strategy | **failed, exit 1** — column mismatch | **no** | no | no |
| 10:10 | `TRACK1_AUDIT_ROSKA4_CALM` | audit | ok — **FAIL** | — | — | — |
| 10:20 | `TRACK1_STOP_REPAIR_1020` | safety | ok | — | — | — |
| 10:35–10:55 | `TRACK1_STRESS_1035…1055` (5) | strategy | refused — `overlap_disagreement` (MNQ) | yes | **no** | no |
| 11:00–11:40 | `TRACK1_STRESS_1100…1140` (9) | strategy | refused — `overlap_disagreement` | yes | yes | no |
| **11:45** | **`TRACK1_STRESS_1145`** | strategy | refused — **`gate_refused: stale`** | yes | yes | no |
| 11:50–12:30 | `TRACK1_STRESS_1150…1230` (9) | strategy | refused — `overlap_disagreement` | yes | yes | no |
| 12:30 | window_closed stress | — | 24 ran, 0 decided, `no_signal` | — | — | — |
| 12:40 | `TRACK1_AUDIT_ROSKA4_STRESS` | audit | ok — **FAIL** | — | — | — |
| **13:45–13:47** | **`PRE-FLIGHT`** | infra | ok, 124s — **appended all five parquets** | — | — | — |
| 14:05–15:55 | `TRACK1_SWING_1405…1555` (23) | strategy | refused — `overlap_disagreement` (**M2K**) | yes | yes | no |
| 15:55 | window_closed swing | — | 23 ran, 0 decided, `no_signal` | — | — | — |
| 16:05 | `TRACK1_AUDIT_ROSKA4_SWING` | audit | ok — **FAIL** | — | — | — |
| 16:15 | `TRACK1_AUDIT_DAILY` | audit | ok — re-audited all four sleeves + day roll-up (5 rows) | — | — | — |
| **16:20** | **`SPY_REFRESH_PM`** | infra | **did not run — not registered** | — | — | — |

Two rows in that table are worth pausing on.

**11:45 is the only slot all day that got past the frame join.** It reached the intraday gate,
which refused it as `stale`. The shape fits an empty broker fetch exactly: with no live bars
the splice returns the frozen half unchanged, whose last bar was still Friday's, so the gate was
right to call it stale. It is a one-off, and it is the closest anything came to a decision today.

**13:45 changed the data underneath the day.** The Stress window ran entirely *before* the
append; the Swing window entirely *after*. That is why the two sleeves refuse on different
instruments, and it is the single most useful accident in today's evidence.

**Telemetry began working between 10:55 and 11:00** — measured, not inferred: the five slots
before that have ledger rows and no timing rows, and every slot from 11:00 on has both.

---

## 3. Coverage by sleeve

| | NKD | Calm | Stress | Swing |
|---|---|---|---|---|
| Window | 01:10–02:55 | 10:00 | 10:35–12:30 | 14:05–15:55 |
| Expected | 22 | 1 | 24 | 23 |
| Time passed | 22 | 1 | 24 | 23 |
| Ledger rows | 0 | **0** | **24** | **23** |
| Decided | 0 | 0 | 0 | 0 |
| Hard refusals | 0 | 0 | 24 | 23 |
| Crashes | 0 | **1** | 0 | 0 |
| Missing timing | 22 | 1 | **5** | 0 |
| Explanation rows | 0 | 0 | 0 | 0 |
| Window closed | — | **no** | yes | yes |
| Audit | **NOT_ENOUGH_DATA_YET** | FAIL | FAIL | FAIL |

**NKD — not a failure, and the audit says so.** The window closed at 02:55, six and a half
hours before the scheduler started. The pre-start rule fired and produced
`NOT_ENOUGH_DATA_YET` with the reason spelled out. This is the rule working exactly as
designed, on its first real opportunity.

**Calm — the day's only genuine silence, and it is a real failure.** The slot crashed on the
column mismatch and left a `window_open` line and nothing else. Both defects behind it were
fixed *after* it ran, so it stays failed for today and tells us nothing about the current code.

**Stress and Swing — evidence, not silence.** Every one of the 47 slots ran and left a *named*
refusal. Both windows closed cleanly with `slots_ran` equal to the full count. The FAIL verdicts
are the committed rule (only DECIDED slots count toward coverage) applied to a blocked data
path — correct as a verdict, and not the same thing as a broken route. Swing is the
best-instrumented sleeve of the day: 23 of 23 ledger rows, 23 of 23 timing rows.

**The five missing Stress timing rows are permanent.** They belong to slots that ran before
telemetry existed. Nothing should backfill them, and nothing has.

---

## 4. The blockers

### B1 — order gate · **OPEN, intentional, held all day**
`orders_possible=false`. No confirmation file. `TRACK1_ORDERS_APPROVED` unset. Every audit
row's order-gate section reads "no order marks". **Zero** occurrences of `order`, `send_order`
or `NoOrderBroker` anywhere in the scheduler log. No book, no checkpoint — both files absent
and the dashboard confirms it.

### B-5R-D — the MNQ bar · **OPEN, unrepaired**
23 of 24 Stress slots refused on it, with byte-identical detail every time: MNQ, 1 of 1186
shared timestamps, in `low`, at **2026-08-21 13:45:00**, history 29400.2500 versus feed
29395.7500, gap 4.5000.

New information: **today's 13:45 append did not fix it.** The MNQ file was rewritten (mtime now
`2026-08-24 13:45:48`) and the disputed Friday bar came through untouched — which is precisely
what the strictly-newer append rule predicts, and now it has been watched doing it.

### B-5R-F — the boundary appender · **OPEN, and it RECURRED today**

This is the finding that changes the shape of the problem. The fix exists
(`boundary_replacement()`, behind `--repair-boundary`) and today's pre-flight did not use it.

I can tell which of today's last bars are partial without a broker, from the bar's own
timestamp against the file's mtime — a bar written before its minute has finished is partial by
arithmetic:

| | last bar | file written | minute ends | partial? |
|---|---|---|---|---|
| MES | 13:44 | 13:45:24 | 13:45:00 | clean |
| MYM | 13:45 | 13:46:11 | 13:46:00 | clean |
| **MNQ** | 13:45 | 13:45:48 | 13:46:00 | **partial** |
| **M2K** | 13:46 | 13:46:31 | 13:47:00 | **partial** |
| **MNKD** | 13:46 | 13:46:46 | 13:47:00 | **partial** |

**Three of five, from one ordinary append.** And the Swing sleeve was already refusing on M2K
before I looked: `2 of 2567 shared timestamps` disagree in `high`, the **first** at
`2026-08-21 13:46:00` — Friday's boundary bar, still there, still wrong. The message does not
name the second one; that it is today's 13:46 bar is the natural reading and the mtime
arithmetic above supports it, but I did not prove it read-only and I am not claiming it.

Direction agrees with MNQ's: the feed's high is *higher* than history's, and a bar captured
mid-minute can only have a high that is too *low*. History is the partial side, on both
instruments, for the same reason.

### B-5R-E — the freshness contract · **half closed, half not, and not exercised**
The split (`required_intraday_through` / `required_daily_close_through`) is in the code and
both are used by `evaluate()`. Child processes import fresh, so it is live. But **no slot
reached the freshness gate today** — the overlap check refuses first — so the corrected
requirement has never actually run in production. The refresh half is not live at all.

### B-5R-C — NKD winter window · **OPEN but dormant**
Zero `TRACK1_NKD_` lines today. Nothing this session speaks to it either way, and nothing can
before 2026-11-01.

### Closed since this morning

| | status |
|---|---|
| **B-5R-A** column mismatch | **fixed in code** — `project_to_frozen_columns()` now runs before both the overlap check and the splice. Zero new `SpliceRefused` after 10:00. **Not re-exercised**: no post-fix slot reached the splice with live bars, so the fix is not yet proven by a real join. |
| **B-5R-B** uncaught refusal | **fixed in code** — `except SpliceRefused` now maps to `live_frame_refused`. Zero timing-rows-without-a-ledger-row all day, i.e. nothing started and died quietly. **Never had to fire.** |
| Track 1 slot telemetry | **fixed and proven live** — 42 rows, first at 11:00:03. This is the one I flagged this morning as pinning every audit to FAIL forever; it is closed. |

### NEW — tomorrow morning is already blocked

**A scheduler restart tonight does not fix it.** That is the part worth reading twice.

Measured by running the freshness functions read-only:

```
spy_daily_live.csv last date                          2026-08-21
required daily close, today 19:46                     2026-08-21   → ok
required daily close, TOMORROW 10:00                  2026-08-24   → stale, refuses
   "last date 2026-08-21 is before the required 2026-08-24"
```

`SPY_REFRESH_PM` would have closed this at 16:20 today. It is not registered, so it did not
run. Restarting the scheduler now registers it — but its next fire is **16:20 tomorrow**, after
Calm (10:00) and after the entire Stress window (10:35–12:30). Tomorrow's 13:45 pre-flight
would also fill the gap, and it is also after both windows.

The scheduler's own error message for that job says the same thing in its own words:
*"Tomorrow's Track 1 slots will refuse on `regime_csv: stale` until it is re-run."*

How it would surface: `fresh.evaluate()` returns a verdict rather than raising, so a slot with
no candidates records `decided=true` with `freshness_allow=false`, while a slot that wanted to
admit a candidate is refused outright. Either way tomorrow morning's evidence is not clean.

---

## 5. Log signatures

Whole of `scheduler_0824.log`:

| signature | count | |
|---|---|---|
| `TRACK1_CALM_1000` | 32 | the 10:00 traceback |
| `TRACK1_STRESS_` | 48 | 24 slots × 2 lines |
| `TRACK1_SWING_` | 46 | 23 slots × 2 lines |
| `TRACK1_NKD_` | **0** | window closed before start |
| `TRACK1_AUDIT_` | 8 | 4 jobs × 2 lines |
| `TRACK1_MAX_HOLD` | 2 | 09:31 |
| `TRACK1_STOP_REPAIR` | 12 | |
| `SPY_REFRESH_PM` | **0** | not registered |
| `SpliceRefused` | 2 | both from the single 10:00 traceback |
| `PRE-FLIGHT` | 7 | 5 start-up restores + today's real run |
| `checkpoint` | 1 | a path in a banner, not a write |
| `order` / `send_order` / `NoOrderBroker` | **0** | |
| `live_frame_refused`, `overlap_disagreement`, `freshness_refused`, `gate_refused`, `no_bar_provider`, `live_source_not_ready`, `no_timing_records`, `coverage_unobserved`, `missing_slot_ids`, `explanation` | **0** | see below |

**The zeros in that last row are expected and are not a gap.** A refusing slot exits 0, so the
scheduler logs only "completed OK". The refusal vocabulary lives in the window ledger, and it is
all there — 47 named rows. The two files answer different questions, and reading the scheduler
log for refusal codes finds nothing by design.

---

## 6. Runtime timing

42 rows, all route `track1_candidate`, all outcome `ok`.

| n | min | p50 | p90 | **p95** | max |
|---|---|---|---|---|---|
| 42 | 2.031 | 2.406 | 2.766 | **2.840** | 3.265 |

Per sleeve: Stress n=19, p50 2.671, max 3.265 · Swing n=23, p50 2.390, max 2.562.

- Slots ≥ 240s: **none**. Slots ≥ 300s: **none**.
- Ledger rows without timing: the five pre-telemetry Stress slots.
- Timing rows without a ledger row: **none** — nothing crashed after the fix.
- Every row carries `phases {setup, observe}`; setup is a steady 0.11–0.14s.

**The p95 gate cannot be judged yet, and 2.8s should not be read as passing it.** All 42 runs
are early refusals: join frames, get refused, write a row, exit. Not one ran the gate, the
candidate search, the admission layer or the explanation writer. **2.8s is the cost of
refusing, not the cost of deciding.** The 240s target and 300s ceiling stay unmeasured until a
slot completes the full path.

---

## 7. Explanations

`global_index/track1_runtime/shadow/explanations/` **does not exist**. Zero files, zero rows.

The per-sleeve/per-slot layout from 5Q-2, the truncation behaviour and the structural freshness
proof are therefore all **unverifiable today** — not disproved, just untested. Absence of
truncation across sleeves is not evidence the layout works when there is nothing to truncate.

The one thing that *is* verifiable is that this is consistent rather than a missing writer:
every audit row reports `expected_from_ledger: 0`. The ledger records no candidate anywhere all
day, so zero explanation rows is exactly right.

---

## 8. Audit records

Eight rows. Four of the five audit jobs fired; `track1_audit_global_nkd` (03:05) did not,
because the scheduler did not exist yet.

| # | ET | scope | sleeve | verdict | written by |
|---|---|---|---|---|---|
| 1 | 10:10:01 | sleeve | roska4_calm | FAIL | its own job |
| 2 | 12:40:00 | sleeve | roska4_stress | FAIL | its own job |
| 3 | 16:05:00 | sleeve | roska4_swing | FAIL | its own job |
| 4 | 16:15:00 | sleeve | global_nkd | **NOT_ENOUGH_DATA_YET** | daily roll-up |
| 5–7 | 16:15:01 | sleeve | calm / stress / swing | FAIL ×3 | daily roll-up |
| 8 | 16:15:02 | **day** | — | FAIL | daily roll-up |

The day gate refuses on: coverage for all four sleeves, `slot_gaps`, `explanations`,
`freshness_proofs`, `checkpoint`.

**Does FAIL mean real failure?** Only for Calm. Stress and Swing ran every slot they were meant
to and left a named reason for each; their FAIL is the committed rule — only DECIDED slots count
— applied to a blocked data path. NKD is correctly not called a failure at all.

**Consistency against the raw files.** I recomputed rather than trusted: stress 24 ledger / 19
timing with the five named gaps, swing 23 / 23, calm 0 / 0, nkd 0 / 0, and the per-sleeve p95
and max figures — all reproduce exactly from `window_coverage` and `slot_timing`. No duplicate
or unregistered slot ids. **No discrepancies.**

One nuance that is not a discrepancy: the sleeve audits report per-sleeve p95 (3.1 and 2.4)
while the dashboard reports a whole-day p95 of 2.8 across both sleeves. Different populations,
both correct.

---

## 9. Dashboard

Read by GET only, no side effects.

**The Track 1 Runtime block agrees with the files on every field I checked** — all four sleeve
verdicts, the day roll-up and its acceptance-gate list, `not_audited_yet` now empty, 42 timing
records with p50 2.4 / p95 2.8 / max 3.3, the four window-coverage outcomes, and `book`,
`checkpoint` and `explanations` all correctly absent. `state_slot_count` is 70, matching the
Track 1 slot table.

**One open incident:** `TRACK1_CALM_1000`, column mismatch, `recovered_by: null`. That is
correct and should stay open for today — the defect is fixed but the slot never re-ran, so
nothing recovered it.

**One field that reads worse than it is:** `freshness: "stale"` with a state age of ~17 hours.
That tracks the *legacy* slot-state file, which nothing updates in track1-only mode. The broker
feed is fresh at 5.4s. Worth knowing before someone reacts to the wrong number.

**Is the dashboard stale relative to the files? No.** A backend restart would only add the
`SPY_REFRESH_PM` mirror row, and doing that while the scheduler still lacks the job is how a
phantom overdue row gets manufactured. Restart both or neither.

---

## 10. What to do

**Before 10:00 ET tomorrow — the one thing that matters:**

```powershell
python -m global_index.update_spy_csv --csv spy_daily_live.csv
```

CLI verified with `--help` only: the module exists and accepts `--csv`, `--api-key` and
`--snapshot-dir`. It writes one CSV, needs no broker, and is the only action that closes
tomorrow morning's daily-close gap in time. No scheduled job will.

**Not recommended tonight: a scheduler restart on its own.** It costs nothing today — every
window is closed — but it does not fix tomorrow morning, which is the part that bites. If
`SPY_REFRESH_PM` and the mirror row are wanted, restart *both* scheduler and backend, and treat
that as additional to the command above, not a substitute for it.

**Still open and unowned:** the MNQ bar repair (tooled, not applied), `--repair-boundary` (not
wired into the pre-flight), and the NKD winter window.

---

## What today proved, and what it did not

**Proved:** the audit chain runs unattended and writes self-consistent verdicts · the pre-start
rule works, on its first real opportunity · telemetry is live and 42 rows deep · a refused slot
leaves a named durable record instead of silence · windows open and close correctly, twice · no
order was attempted, no book or checkpoint written, B1 held all day.

**Not proved:** that the column-mismatch fix survives a real join — nothing reached the splice
with live bars · that the `SpliceRefused` catch fires — it never had to · that the explanation
layout works — zero rows exist · that the p95 gate is passable — 2.8s is the cost of refusing ·
anything at all about the NKD sleeve.

Three sleeves are judgeable and were judged. None of them produced a decision. **Today says a
great deal about the plumbing and nothing whatever about the strategy.**
