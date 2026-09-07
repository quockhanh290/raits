# Stage 5 — pre-switch audit for the B1 retirement path

**2026-08-23 · read-only / dry-run · no scheduler started, no IBKR connection, no order, no
dashboard write, no commit, no confirmation file, no `STOP_TRADING`, legacy untouched.**

---

## 1. Verdict: **READY_FOR_SHADOW_SCHEDULER_ONLY**

Not `NOT_READY` — nothing is broken, and the gate machinery is exactly where Stage 4C left it.
Not `READY_TO_BEGIN_RETIREMENT_DRAIN` either, and for a reason that is worth stating plainly
before anything else:

> **There is nothing to drain.** Legacy's book is already empty — `positions: []` — its
> scheduler is not running, and `runner.pid` is absent. The drain step assumes a live legacy
> route holding positions that must exit by their own rules. That is not the situation today.

So "begin the drain" is not a step that can be taken; it has, in effect, already happened —
though not deliberately, and that is the first thing to resolve. Two Track 1 preconditions also
have **no evidence at all**, and both can only be satisfied by running the shadow scheduler.
That is the work that is actually available now.

**Not claimed anywhere in this report:** that the system is ready for live orders, that legacy
is flat at the broker, or that Track 1 can produce a live decision today. None of those has
been established and one of them is forbidden to check here.

---

## 2. Runbook preconditions

| # | precondition | checkable read-only? | result | status |
|---|---|---|---|---|
| 1 | every blocker CLOSED or confirmed | yes | `False` — only `B1` | **FAIL by design** |
| 2 | the four sleeves can produce a live decision | yes | `blocked=[]` → reads PASS | **AMBIGUOUS** |
| 3 | Track 1 slots in scheduler **and** dashboard | yes | `in_parity` true, OFF and ON | **PASS** |
| 4 | `_ENTRY_WINDOWS` contains the Stress window | **no — check is unrunnable** | verified by effect | **PASS by effect** |
| 5 | Track 1 has run shadow for a measured period | yes | **no coverage file exists at all** | **FAIL** |
| 6 | the Track 1 checkpoint is bootstrapped | yes | `Refusal(no_entry)`, file absent | **FAIL** |
| 7 | legacy is flat | **half** | file: `positions: []`; broker: forbidden | **PARTIAL** |
| 8 | the route builds today's frame only through the guard | yes | `released=True` | **PASS** |

### The three that need explaining

**Precondition 2 is the dangerous one.** Its check returns green — `readiness()` reports every
sleeve live-ready and nothing blocked. But the code that would actually produce a live decision
still refuses: `load_source("live").candidates()` raises. The Stress sleeve's live chain runs
through **four** scratch modules and Calm A's through one, and the route's own prerequisite list
says what is missing — today's regime label, a cost object, and Calm A's true stop-risk sizing.

The check and the claim measure different things. Read at face value, this precondition says
"Track 1 can trade", and it cannot. This is the single most misleading line in the runbook.

**Precondition 4's check cannot be run.** `_ENTRY_WINDOWS` is a local variable inside
`make_scheduler`, not a module attribute, so the command as written raises `AttributeError`.
The condition itself holds, verified through its observable effect: turning shadow on drops the
12:20 stop-repair sweep (ten sweeps instead of eleven), and the two window constants — the
scheduler's and the slot table's — are equal.

**Precondition 5 has no evidence whatsoever.** There is no `window_coverage_*.jsonl` anywhere
in the repository. What exists in `scratch/track1_shadow/` is replay output for two measured
windows, and a replay cannot testify that a window was *watched* on a given day — which is
exactly and only what this precondition asks for. It is not "partially satisfied". It is
untouched.

---

## 3. Gate state

Everything Stage 4C left in place is still in place, verified without writing anything:

- `track1_go_live_confirmation.json` **does not exist**, and this audit did not create it.
- `self_check()` returns `[]`.
- The ledger on disk matches the registry exactly.
- `blocking()` returns exactly `B1_broker_account_or_legacy_retirement`.
- `--allow-orders` exits **2**, names B1 and the missing `TRACK1_ORDERS_APPROVED`, and does
  **not** mention `LIVE_FRAME_ADAPTER_VERIFICATION`.
- `live_frame_wiring()` still measures released.

### One defect that would fail at the moment of use

The runbook's **step S4 gives a confirmation template that the schema refuses.** It still lists
`scheduler_wiring_approved`, `normal_generator_isolation_accepted` and
`calm_a_detector_accepted_frozen` — three flags Stage 4 removed when it closed the blockers they
existed to release. The file refuses unknown keys *whole* rather than honouring the parts that
parse, which is the correct behaviour and exactly what makes this dangerous: an operator who
copies the template gets **zero flags granted**, the gate stays shut, and it looks like a code
fault at the worst possible moment.

Measured, on a copy written to a temporary directory rather than the repo path:

```
runbook S4 template as written -> REFUSED
  unknown key(s) ['calm_a_detector_accepted_frozen',
                  'normal_generator_isolation_accepted',
                  'scheduler_wiring_approved']
  flags granted: {}
```

The template that works is the one already in the ledger: `schema_version`, `confirmed_by`,
`confirmed_at`, `legacy_retired_confirmed`, and optionally `note`.

---

## 4. Scheduler and dashboard, construction only

No scheduler was started. Both variants were built and inspected, then discarded.

| | shadow OFF | shadow ON |
|---|---|---|
| total jobs | **60** | **84** |
| Track 1 slots | 0 | **25** (`track1_calm_1000` … `track1_stress_1230`) |
| `stop_repair_1220` | present | **excluded** |
| stop-repair sweeps | 11 | 10 |
| dashboard parity | **in parity** | **in parity** |

Turning shadow on adds exactly 25 jobs and removes exactly one. Every Track 1 slot runs
`python -m global_index.run_live_day_track1 --regime-csv <csv>` — **no `--allow-orders`, no
broker port.** The scheduler's Stress window and the slot table's required window are equal, so
a drift between them fails the parity check rather than passing silently.

### The finding that changes the order of operations

**`--track1-shadow` does not isolate Track 1.** With it on, the scheduler still registers
**59 legacy jobs, including 23 legacy `live_day` entry slots.** Starting the scheduler in shadow
mode therefore *resumes legacy trading* — it does not merely add a watching route.

The runbook places the legacy kill switch at S1 and the scheduler change at S5, which reads as
though S1 only needs to precede S5. It does not. **S1 must precede any scheduler start at all**,
including the shadow-only one, or the first thing that happens is legacy taking entries again
while nobody is expecting it to.

---

## 5. Route state isolation

**Every Track 1 state file is absent** — the position book, the pid file, the checkpoint, and
the route's own kill switch. Track 1 has never held state on this machine.

| legacy file | present | last written |
|---|---|---|
| `live_positions.json` | yes | 2026-08-21 13:59 |
| `global_index/replay_checkpoint.json` | yes | 2026-08-21 12:06 |
| `global_index/live_state_data.js` | yes | 2026-08-21 13:59 |
| `trade_log.jsonl` | yes | 2026-08-15 10:11 |
| `runner.pid` | **no** | — |
| `STOP_TRADING` | **no** | — |

The shadow dry-run was executed and the four legacy files were checksummed before and after:
**all four identical.** The run reported `send_order calls: 0`, wrote only into
`scratch/track1_shadow/`, and created no Track 1 state file. Its summary: 139 candidates, 91
settlements, net 8,259.85 over 65 days on the vault2026 replay.

The kill switches are genuinely separate — legacy reads `STOP_TRADING`, Track 1 reads
`STOP_TRADING.track1` — and legacy's D5 gate is wired for real: `--stop-path` defaults to the
file name, the runner holds it, and when present it clears entry candidates while leaving exits
untouched. That is the mechanism step S1 depends on, and it works.

---

## 6. Legacy local state

**Flat, and idle.**

- `positions: []` — zero rows, so no instruments, no clusters, nothing exit-pending, no stop
  order ids to cancel.
- No `STOP_TRADING` file.
- No scheduler process (verified against a process listing that returned real data, so the zero
  is a zero and not a failed probe).
- Last activity 2026-08-21; system epoch 2026-08-10.
- Book equity 50,408.25 against a last-seen broker net liquidation of 996,708.81 — the account
  holds far more than this system's allocation, which matters for reading any broker screen
  during the drain.

The last trading day's event log holds 135 rows, **no mismatch, no critical, no halt**, and one
repeated alert:

> `G2: model age URGENT — schedule re-freeze immediately`

That is correct and expected: the model's `fit_end` is 2024-12-31, which is **19.7 months** old
against a hard threshold of 18. It is **warn-only by design** and halts nothing — the guard's own
documentation says age is not evidence the model is wrong, and asks for two measurements rather
than a reflexive re-freeze. It does not block the switch-over. It is stated here because every
Track 1 sleeve reads regime labels, so retiring one route onto another while the shared regime
model is overdue is a decision worth making knowingly rather than by omission.

The SPY CSV is **clean today** — last row 2026-08-20, one business day back, well inside both
thresholds. But nothing refreshes it while the scheduler is down, and at more than five business
days the G1 hard gate blocks new entries. There is a clock running on that.

### An open question this audit cannot answer

The scheduler was running when this work began several days ago and is not running now. Nothing
in this session started or stopped it. Whether it was stopped deliberately — and if so, whether
that stop was the beginning of the retirement — is not recorded anywhere I can read, and it
changes what the next step means.

---

## 7. Broker checks not performed

Forbidden by this task, and therefore genuinely unknown rather than assumed good:

- **Whether IBKR reports any open position.** Precondition 7 requires the file *and* the broker
  to agree, and only the file half was checked. **Legacy cannot be declared flat.**
- **Whether any working STP order remains** with no position behind it. Step S3 exists because
  such an order fills into a position nobody asked for. Not checked.
- **Whether the account holds positions from anything other than this system.** The equity gap
  above makes that a real question, not a rhetorical one.

---

## 8. Tests run

Every one re-run in this session, on the code as it stands.

| suite | result |
|---|---|
| Stage 4C live source | **46 passed** |
| Stage 4B identity + live frame | **30 passed** |
| Stage 4 production-clean, default | **25 passed, 1 skipped** (7:00) |
| Stage 3B blockers | **72 passed, 1 skipped** |
| Stage 3 route | **41 passed, 1 skipped** |
| the eight that must stay green | **156 passed** |

`global_index/test_event_playback.py` was **not run** — the known hang, excluded by instruction.

**The all-window Stage 4 suite was deliberately not re-run.** It takes about nineteen minutes,
and Stage 4C ran it to 32 passed after the last code change. This stage changed no code at all —
it is read-only — so a re-run could only reproduce that result. If any code had been touched
here, it would have been re-run and this paragraph would say so instead.

The three skips are the same pre-existing opt-ins as in earlier stages, none introduced here.

---

## 9. Exact next action recommended

Nothing here executes the switch-over, and the first two items are not code.

**1 — Answer why the scheduler is down.** It was running days ago and is not now. Everything
below reads differently depending on whether that was deliberate. If it was an accident, the
system has been silently not trading since 2026-08-21, and that is its own incident.

**2 — Decide B1 explicitly, before any file is written.** Path A retires legacy; path B funds a
second account. The audit assumes A, as stated, but the confirmation file records a decision and
should follow one.

**3 — Create `STOP_TRADING` *before* starting any scheduler.** Not before S5 — before any start
at all. Otherwise the first scheduler start resumes 23 legacy entry slots. Legacy is already
flat, so this costs nothing and removes the only way the next step can surprise anyone.

**4 — Then start the scheduler with `--track1-shadow`, and let it run.** This is the only work
that moves preconditions 5 and 6, and neither can be moved any other way:

- every shadow day writes window-coverage records, which is the *only* thing that can satisfy
  precondition 5;
- the first shadow day gives the checkpoint something to bootstrap from, which satisfies 6.

Orders stay impossible throughout: B1 still blocks, `TRACK1_ORDERS_APPROVED` is unset, and no
Track 1 slot passes `--allow-orders`.

**5 — In parallel, fix the three runbook defects**, since each fails at the moment of use:
the S4 template that the schema refuses, precondition 2's check that measures the wrong thing,
and the S1-before-any-start ordering. Precondition 4's unrunnable check is worth fixing too,
though it is the least dangerous of the four.

**6 — Only then revisit the drain and the broker checks.** With legacy frozen and Track 1
accumulating shadow evidence, the remaining questions are the broker ones this task forbids:
is the account flat, and are there working stops to cancel.

### What would change the verdict

`READY_TO_BEGIN_RETIREMENT_DRAIN` becomes the right answer when preconditions 5 and 6 hold and
precondition 2 either passes honestly or is rewritten to say what it actually measures. At that
point the only thing left unchecked is the broker, which is checked at execution time by
design — and that is the shape the task described.
