# Stage 5M-0 — state repair preflight

**2026-08-23 · no scheduler, backend, or dashboard started or stopped · no IBKR connection ·
no order · no `STOP_TRADING` or `STOP_TRADING.track1` created or removed · no confirmation
file · no commit · no live state file written.**

---

## Verdict: **REPAIR_RECOMMENDED_BEFORE_RESTART**

The evidence is sufficient — every day proposed for writing has a quoted success line, and
nothing is inferred. And the restart window is not theoretical: the first job that would suffer
runs in **2 hours 15 minutes**.

**I have not written anything.** The exact command is at the bottom for you to run.

One refinement to the Stage 5L report: **only the pre-flight file matters.** The max-hold file
turns out to be operationally inert, for a reason worth reading before deciding.

---

## 1. Current state — exact

Both files, verbatim:

```
global_index/preflight_state.json     {"2026-08-23": true}
global_index/maxhold_state.json       {"2026-08-23": true}
```

Both 26 bytes, both last written **2026-08-23 20:03:21 local** — the same second, which is the
signature of the single probe that damaged them.

**2026-08-23 is a Sunday.** Both jobs are `mon-fri`. Neither key can be genuine.

### Scheduler process — exact

Queried with `monitor.ops.scheduler_processes()`, the project's own function, which matches
both `python.exe` and `pythonw.exe`:

```
pid     : 36656
command : ...\pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume
started : 2026-08-20 06:35:53      (age 3d 14h)
```

**One process. Still running.** It read `preflight_state.json` once, at startup — the loader is
called only from `main()` — and the log line from that moment says what it got:

```
2026-08-20 06:35:53  INFO  run_scheduler — [PRE-FLIGHT] restored 7 day(s) of state
```

Seven days, in memory, untouched by what happened on disk three days later.

### Timing

Now: **Sunday 2026-08-23, 22:48 ET** (20:48 in Calgary; the machine's clock is ET−2, which is
why a 13:45 ET job appears at 11:45 in the logs).

| Next relevant event | ET | Away |
|---|---|---|
| NKD night slots | Mon 01:10–02:55 | **2h 15m** |
| max-hold exit | Mon 09:31 | 10h 42m |
| pre-flight — the file rewrites itself here | Mon 13:45 | 14h 56m |

---

## 2. Log evidence — what was found, and what was refused

Every pre-flight run in every scheduler log was paired with **its own** outcome line, stopping
at the next run's start so a success cannot be borrowed backwards by an unresolved one.

**Pre-flight: 16 runs found. 14 succeeded, 2 failed, 0 with no outcome.** Complete coverage —
nothing ambiguous.

The seven days that will be written, each with the line that attests it:

```
2026-08-13  scheduler_0813.log  11:47:35  [PRE-FLIGHT] OK — parquet + spy CSV fresh...
2026-08-14  scheduler_0814.log  11:47:25  [PRE-FLIGHT] OK — parquet + spy CSV fresh...
2026-08-17  scheduler_0817.log  11:47:32  [PRE-FLIGHT] OK — parquet + spy CSV fresh...
2026-08-18  scheduler_0818.log  11:47:23  [PRE-FLIGHT] OK — parquet + spy CSV fresh...
2026-08-19  scheduler_0819.log  11:47:19  [PRE-FLIGHT] OK — parquet + spy CSV fresh...
2026-08-20  scheduler_0820.log  11:47:28  [PRE-FLIGHT] OK — parquet + spy CSV fresh...
2026-08-21  scheduler_0821.log  11:48:01  [PRE-FLIGHT] OK — parquet + spy CSV fresh...
```

That `OK` line is not a summary someone wrote — it is emitted *only* after both
`update_ibkr_daily` and `update_spy_csv` returned success, on the line immediately before the
job records `true`. It is the same evidence the record was standing in for.

**Refused:** 2026-07-31 and 2026-08-04 both failed. They fall outside the seven-entry window
anyway, but the reconstructor would have written them as `false`, not dropped them — a recorded
failure is a real state and losing it is not the same as never having run.

**Max-hold: 15 runs found. 10 succeeded, 2 failed, 3 with no outcome line at all.**

```
2026-08-12  scheduler_0812.log  07:31:10  [MAX_HOLD_EXIT] completed OK
2026-08-14  scheduler_0814.log  07:31:19  [MAX_HOLD_EXIT] completed OK
2026-08-17  scheduler_0817.log  07:31:12  [MAX_HOLD_EXIT] completed OK
2026-08-18  scheduler_0818.log  07:31:11  [MAX_HOLD_EXIT] completed OK
2026-08-19  scheduler_0819.log  21:51:58  [MAX_HOLD_EXIT_CATCHUP] completed OK
2026-08-20  scheduler_0820.log  07:31:10  [MAX_HOLD_EXIT] completed OK
2026-08-21  scheduler_0821.log  07:31:10  [MAX_HOLD_EXIT] completed OK
```

**Refused, and this is the interesting one: 2026-08-13 is missing.** The max-hold job launched
**twice** that day — the two-scheduler incident already recorded in the scheduler's own
comments — and *neither* launch produced a completion line. One is unresolved, one exited with
an error.

So there is no honest way to say the max-hold sweep finished on 2026-08-13. "It launched, so it
probably ran" is exactly the inference this whole exercise exists to refuse, and it is the
expensive direction: MAX_HOLD exits average **+$398.60** and are where the edge leaves, so a
false "already done" is worse than a redundant re-run. 2026-08-07 is refused for the same
reason. Neither appears in the proposal.

---

## 3. Proposed content

**`global_index/preflight_state.json`**

```json
{
  "2026-08-13": true, "2026-08-14": true, "2026-08-17": true, "2026-08-18": true,
  "2026-08-19": true, "2026-08-20": true, "2026-08-21": true
}
```

**`global_index/maxhold_state.json`**

```json
{
  "2026-08-12": true, "2026-08-14": true, "2026-08-17": true, "2026-08-18": true,
  "2026-08-19": true, "2026-08-20": true, "2026-08-21": true
}
```

Seven entries each, because the scheduler's own writer keeps the newest seven by date. The
reconstruction is the file the scheduler would have written, not a longer one containing it.

**A consistency check that had to pass and did:** the running process logged "restored 7 day(s)"
at startup on 2026-08-20, before that day's own run. Replaying the writer's prune rule forward
across the 08-20 and 08-21 runs lands on exactly the seven dates above. The reconstruction and
the process's own count agree independently.

The bogus `2026-08-23` is dropped from both.

---

## 4. What happens if nothing is repaired

**The two files are not in the same situation.** Stage 5L treated them together; that was too
coarse.

### The pre-flight file — this is the one that matters

*If the scheduler is left running until Monday 13:45 ET:* nothing bad happens. The live process
still holds all seven days in memory, and at Monday 13:45 it writes that dictionary back out
with 2026-08-24 added. **The file repairs itself** and the damage never surfaces.

*If the scheduler is restarted before Monday 13:45:* it reloads the damaged file, and
`2026-08-21` — the day Monday's night slots depend on — is gone for good.

The concrete cost, restart before **Monday 02:55 ET**: the NKD night slots at 01:10–02:55 read
the previous business day's flag, find nothing, and **fail closed. Every night slot skipped.**
That is the safe direction, and it is silent — a skipped slot exits 0 and the log says the job
completed.

A restart between 02:55 and 13:45 costs nothing on the legacy side, because the 14:05 slots read
*today's* flag and Monday's pre-flight will have written it by then. The damage window closes
at Monday 13:45 either way.

### The max-hold file — inert, and here is why

I expected this to need repairing and it does not. `_catch_up_maxhold` checks **only today's
key**, and returns early on a weekend before it looks at anything:

- Today is Sunday, so the bogus key is never even read.
- On Monday the key checked is `2026-08-24`, which is absent under any scenario — so a restart
  after 09:31 runs the catch-up, and a restart before it lets the cron fire. Correct either way.
- Historical keys are never consulted for anything.

The function's own docstring says the rest: *"Re-running is safe… The state file only avoids a
pointless duplicate on every restart."* The worst case from leaving this file alone is one
redundant, harmless sweep.

**So repairing max-hold is tidying, not a fix.** It is included in the command below because
repairing both in one atomic step is simpler to reason about than repairing one — not because
leaving it would cost anything.

---

## 5. Live files touched: **none**

The tooling is dry-run by default and I ran it dry. Both files were hashed before and after
every test and every mutation in this stage, including a full `--apply` exercise pointed at
temporary targets, and came back identical each time.

---

## 6. Tests

| Suite | Result |
|---|---|
| `scratch/test_track1_stage5m0_state_repair_20260823.py` | **19 passed** |
| `scratch/track1_stage5m0_mutations_20260823.py` | **8 / 8 mutations detected** |
| operator state files unchanged across the whole harness | **verified by hash** |

Every test builds its own log text and its own state files under a temporary directory. The
fixture lines are copied in shape from `scheduler_0821.log`, so the parser is not being checked
against a format invented to suit it.

The mutations turn each refusal back into an inference and confirm the matching test goes red:

```
N1  an unresolved launch counted as completed        → the 2026-08-13 test reds
N2  a failed pre-flight recorded as True             → the failure test reds
N3  an outcome line borrowed by the previous run     → the pairing test reds
N4  ET day taken from the raw local stamp            → the 22:30 rollover test reds
N5  the seven-entry prune removed                    → the prune test reds
N6  an unattested key preserved through the repair   → the Sunday-strip test reds
N7  the dry-run default writes anyway                → the default test reds
N8  the expect-current guard ignored                 → the refusal test reds
```

N4 is worth one sentence: log stamps are machine-local and the keys are ET session dates, so a
22:30 local line is already the next ET day. Slicing the date off the front of the line is the
obvious shortcut and it is wrong twice a day — the 2026-08-19 recovery ran at 21:51 local, close
enough to that boundary to matter.

---

## 7. The command, for you to run

**Only if the scheduler is going to be restarted before Monday 2026-08-24 13:45 ET.** If it is
left alone, do nothing — the file heals itself at 13:45 and running this would replace a
healthy file with an older reconstruction.

Dry run first — it prints the diff and writes nothing:

```powershell
cd d:\raits
python scratch\track1_stage5m0_state_repair_20260823.py
```

Then, to write:

```powershell
python scratch\track1_stage5m0_state_repair_20260823.py --apply --expect-current "{\"2026-08-23\": true}"
```

`--expect-current` is not decoration. If the file has already healed — or anything else has
written to it since this plan was made — the write is **refused** with exit code 2 rather than
overwriting it. Re-plan in that case; do not force it.

Safe to run while the scheduler is up: the process does not re-read this file, and when it
writes at Monday 13:45 it writes its own good in-memory copy over the top. The order that
matters is **repair, then restart** — not the reverse.

---

## 8. Next

Stage 5M — promote Normal-R4 into Track 1 slots at 14:05–15:55. Nothing in this stage blocks
it: the damaged file affects a legacy runtime path, not any code 5M would touch. Decide the
restart question first only because the answer expires at Monday 13:45.
