# Scheduler Slot Timing + Shadow-Resume Outcomes — measured — 2026-08-22

READ-ONLY. Nothing was started: no scheduler, no runner, no monitor backend, no broker, no IBKR
connection. Only production's own logs were parsed; only files under `scratch/` were written.

## Headline

The scheduler ran in **two clearly separated regimes**, and the numbers that decide Track 1's
scheduling risk come from the current one, not from the comment in the source.

| | before 2026-08-11 | from 2026-08-11 |
|---|---:|---:|
| live-day slot runs measured | 85 | **207** |
| median | 337 s | **191 s** |
| p75 | 347 s | 195 s |
| p90 | 369 s | **206 s** |
| p95 | 400 s | **216 s** |
| max | 538 s | **311 s** |
| runs over the 300 s slot spacing | 67 (79%) | **1 (0.5%)** |
| mutex skips actually logged | 11/day on 4 days | **zero** |

`run_scheduler.py:751` documents *"a run takes ~5.5 min"*. That was true of the old regime (330 s ≈
its median). **It is no longer the operating figure** — the current p95 is 216 s.

---

## 1. Where the evidence lives

| Artifact | Count / span | What it carries |
|---|---|---|
| `scheduler_*.log` | 22 files, **18 trading days**, 2026-07-31 → 2026-08-21 | APScheduler `Running job` / `executed successfully` pairs, misfire warnings, the mutex-skip line, pre-flight skips, and the exact child argv per slot |
| `live_day_*.log` | 18 files, 1.2–16.8 MB each | the `[shadow]` comparison verdicts |
| `global_index/runner_events_*.jsonl` | 8 files, 2026-08-12 → 2026-08-21, 911 events | `ts / level / category / message` only |
| `global_index/replay_checkpoint.json` | 960 B, last written 2026-08-21 12:06 | the resume checkpoint itself |
| `global_index/replay_checkpoint.py` | | checkpoint implementation |

Parser: `scratch/shadow_resume_timing_audit_20260822.py`. It found **968 completed run pairs**, 52
misfires, 44 mutex skips and 28 other skips.

### Two measurement-quality problems, caught and handled

1. **76 run pairs have ~0 s between `Running` and `executed`.** These are slots whose body returned
   immediately — pre-flight failure or the mutex — not runtimes. Left in, they drag the median toward
   zero. Excluded from every runtime figure: 23 on 2026-08-04 (pre-flight failed), 11 each on
   2026-08-05/06/07/10 (mutex), 9 on 2026-07-31.
2. **Three rows are longer than the parent's own kill ceiling** and therefore cannot be single child
   runs — see the addendum for the derived rule and the per-row mechanism. Reported and excluded; one
   `Running` line remains unpaired.

---

## 2. Measured production evidence

### Runtime by slot family (no-op runs and pairing artifacts excluded)

| Family | n | median | p90 | p95 | max | over 300 s |
|---|---:|---:|---:|---:|---:|---:|
| Continuous run (14:10–15:55) | 352 | 190 s | 340 s | 357 s | 538 s | 63 (17.9%) |
| Daily run (14:05) | 16 | 196 s | 341 s | 346 s | 363 s | 5 (31.2%) |
| NKD night run | 239 | 83 s | 148 s | 173 s | **532 s** | 3 (1.3%) |
| Pre-flight update (13:45) | 16 | 148 s | 248 s | 254 s | 273 s | 0 |
| Stop repair sweep | 87 | **11 s** | 17 s | 18 s | **19 s** | 0 |
| MAX_HOLD exit (09:31) | 10 | 12 s | 17 s | 18 s | 19 s | 0 |
| Heartbeat | 237 | 0 s | 0 s | 0 s | 0 s | 0 |

The two families Track 1 would sit beside are cheap: a stop-repair sweep costs **19 s at worst**, a
max-hold exit the same.

### Per day, live-day slots only

| Day | n | median | p90 | max | over 5 min |
|---|---:|---:|---:|---:|---:|
| 2026-07-31 | 14 | — | 463 s | 491 s | 7 |
| 2026-08-03 | 23 | 339 s | 345 s | 347 s | 12 (52%) |
| 2026-08-05 | 12 | 327 s | 334 s | 335 s | 12 |
| 2026-08-06 | 12 | 317 s | 321 s | 340 s | 12 |
| 2026-08-07 | 12 | 334 s | 347 s | 373 s | 12 |
| 2026-08-10 | 12 | 356 s | 363 s | **538 s** | 12 |
| **2026-08-11** | 23 | **205 s** | 207 s | 311 s | 1 |
| 2026-08-12 | 23 | 185 s | 187 s | 278 s | 0 |
| 2026-08-13 | 23 | 191 s | 194 s | 288 s | 0 |
| 2026-08-14 | 23 | 191 s | 193 s | 289 s | 0 |
| 2026-08-17 | 23 | 192 s | 195 s | 292 s | 0 |
| 2026-08-18 | 23 | 183 s | 184 s | 275 s | 0 |
| 2026-08-19 | 23 | 176 s | 177 s | 267 s | 0 |
| 2026-08-20 | 23 | 189 s | 192 s | 283 s | 0 |
| 2026-08-21 | 23 | 200 s | 217 s | 291 s | 0 |

2026-08-04 is absent: all 23 slots ran with an empty body after the pre-flight failed.

### Slot-lock contention actually observed

44 mutex skips, and their shape is exact:

- **Slots hit:** `LIVE_DAY_1410, 1420, 1430, 1440, 1450, 1500, 1510, 1520, 1530, 1540, 1550` — the
  *alternate* slots, 4 times each.
- **Days:** 2026-08-05, 08-06, 08-07, 08-10 — 11 skips on each, and **no other day**.
- **Zero since 2026-08-11.**

That is perfect alternation: a run starting at 14:05 was still going at 14:10, so 14:10 skipped;
14:15 ran; still going at 14:20, skipped. Effective spacing became 10 minutes on those four days.

### Misfires

52 in total. **Not all on NKD night slots** — see the addendum: 43 are, 9 are not, and one of the
nine is a trading job. 33 of the 52 are covered by a machine-sleep stall. Median 3,651 s (~1 h),
worst 12,859 s (3.6 h). None is contention. No 14:05–15:55 day-window slot misfired.

### Other skips

| Reason | Count |
|---|---:|
| pre-flight failed for 2026-08-04 | 26 |
| pre-flight ran but FAILED for 2026-08-04 | 1 |
| no pre-flight record for 2026-07-31 (scheduler restart) | 1 |

### Shadow-resume outcomes

| | total |
|---|---:|
| comparison matched (`DOI CHIEU KHOP`) | **91** |
| comparison diverged (`DOI CHIEU LECH`) | **0** |
| no usable checkpoint, comparison skipped | 64 |
| checkpoint failed to advance | **0** |

Per day since 2026-08-17: 10, 10, 5, 5, 10 matches — **zero divergences on every tracked day**. The
resume path has never disagreed with the full replay in the recorded evidence.

Coverage grew over time: `--shadow-resume` appears on 12 slots on 08-07, 22 on 08-09 and 08-10, then
**45 per day** from 08-11 onward (day window + NKD night). `--shadow-verify` runs 1–2 times a day,
which matches the design: once a day on the last slot.

### 15:55 → 16:20 clearance — the "zero minutes" claim, measured

`run_scheduler.py:922-928` states `STOP_REPAIR_1620` has *"ZERO minutes of clearance"*. That was
computed against the worst *permitted* case (a 20-minute ceiling plus a 5-minute grace). Measured:

| Day | 15:55 runtime | clearance before 16:20 |
|---|---:|---:|
| 2026-08-10 | 538 s | **16.0 min** |
| 2026-08-11 | 311 s | 19.8 min |
| 2026-08-12 … 08-21 (9 days) | 267–292 s | **20.1 – 20.6 min** |

Worst observed clearance is **16 minutes**, on the worst-runtime day in the whole sample. The zero
figure is a bound, not an observation.

---

## 3. Static simulation

Driven by the measured sample, not by an assumption. The simulator replays the real rule — a slot
whose scheduled instant falls while a run is in flight is **skipped, not queued**
(`run_scheduler.py:235` `_run_guarded`) — and sweeps **every** possible starting index in the sample
so no arbitrary offset decides the answer.

> An earlier version of this simulator sorted the runtime sample and then consumed it in order, so
> it only ever drew from the smallest values and reported zero skips everywhere. The numbers below
> come from the chronological sample, which also preserves the within-day autocorrelation.

### It reproduces reality

Feeding the **pre-08-11** sample into the **current window alone** predicts **11 skipped slots of
23**. The logs recorded **exactly 11 mutex skips per day** on each of the four contended days. The
simulator is anchored to an observed number before being used to forecast anything.

### Forecast

| Scenario | slots | skips: median / p90 / max | worst-case skip rate |
|---|---:|---|---:|
| **Current regime**, current window only | 23 | 0 / 1 / **1** | 4% |
| **Current regime**, Track 1 window alone (10:00 + 10:35–12:30) | 25 | 0 / 1 / **1** | 4% |
| **Current regime**, current + Track 1 | 48 | 0 / 1 / **1** | **2%** |
| **Current regime**, all windows incl. NKD night | 70 | 0 / 1 / **1** | 1% |
| Pre-08-11 regime, current window only | 23 | 11 / 11 / 11 | 48% |
| Pre-08-11 regime, current + Track 1 | 48 | 21 / 23 / 23 | 48% |

### Where the cliff is

Slot spacing is 300 s, so the behaviour is a step function at exactly that point:

| Fixed runtime for every slot | skipped of 48 |
|---|---:|
| 216 s (current p95) | **0** |
| 311 s (current max) | 23 (48%) |
| 400 s (pre-08-11 p95) | 23 (48%) |
| 330 s (the "~5.5 min" in the source) | 23 (48%) |

There is no gradual degradation. Below 300 s nothing is skipped; above it, every second slot is.
**Current headroom is 84 s at p95 (216 → 300) and 109 s at the median.**

---

## 4. Interpretation for Track 1

**The Stress window is empty time.** Existing entry windows are 01:00–02:55 and 14:00–15:55 ET
(`run_scheduler.py:917` `_ENTRY_WINDOWS`). Track 1's 10:00 and 10:35–12:30 do not overlap either, so
the 25 new slots contend with almost nothing — only `STOP_REPAIR_1220`, which falls inside the Stress
window and costs **19 s at worst**.

On the measured current regime, adding all 25 Track 1 slots costs **at most one skipped slot in 48,
in the worst of 207 tested phasings**. That is not a scheduling problem.

**But the headroom is thin and Track 1 spends it.** 84 s of margin at p95, while Track 1 adds two new
sleeves — Calm A and the Stress detector — to the same `run_live_day` process. Nobody has measured
what those cost per run. If they add ~85 s, the schedule falls off the cliff and lands back in the
pre-08-11 regime, where the same simulator says 48% of slots are lost.

### Recommendation

| Option | Verdict |
|---|---|
| **Share the existing scheduler** | **Yes.** No separate process or separate scheduler is justified by the measured evidence. |
| Separate scheduler/process | **Not needed for timing.** It is still needed for *broker* isolation (a second order-sending route needs its own account or Gateway — see the route audit), but that is a different problem from slot contention. |
| **Shadow-only slots first** | **Yes, and this is the load-bearing step.** Add the Track 1 slots in shadow mode, then re-run this audit to measure the new runtime distribution before anything trades. |
| Coarser spacing | **Not yet.** Only if the shadow measurement pushes p95 above 300 s. Note the trade: the Stress entry fires on a low break at an unknown minute, so 10-minute spacing halves the entry-timing resolution. That is a cost to measure, not to assume. |
| Runtime optimisation before expansion | **Only if the shadow measurement says so.** The current regime does not need it. |

Two prerequisites carried over from the route audit, both confirmed relevant by this data:

- Track 1's slots run **before the 13:45 pre-flight**, so they need `prev_preflight=True` or they are
  skipped every day. The 26 pre-flight skips on 2026-08-04 in this sample are what that failure looks
  like.
- `_ENTRY_WINDOWS` must gain `((10,35),(12,30))` so `STOP_REPAIR_1220` stops landing inside the Stress
  window.

---

## 5. What the logs cannot tell us, and what to add

### The 2026-08-11 change point is unexplained

Median runtime fell from 337 s to 191 s between 2026-08-10 and 2026-08-11, and the mutex skips
stopped entirely. `--shadow-resume` coverage expanded the same day (22 → 45 slots), but that is
**correlation, not cause** — shadow-resume *adds* a replay beside the trading one, so mechanically it
should make a run longer, not shorter. This audit cannot attribute the improvement, and it matters:
if the cause is something reversible, the headroom Track 1 is about to spend can vanish without
warning.

**Missing instrumentation, in priority order:**

1. **Per-stage timing inside a run.** `live_day_*.log` has no timing markers at all — no `[perf]`
   lines, no "took Ns". A run's 191 s cannot be split into connect / fetch / signal / decide / order /
   shadow. Without it neither the change point nor Track 1's added cost can be attributed. This is the
   single highest-value addition.
2. **Slot identity in the event stream.** All 911 records in `runner_events_*.jsonl` carry only
   `ts / level / category / message`; **`context` is empty in every one**. There is no slot id, no
   route, no runtime. Slot timing today is only recoverable by parsing APScheduler's own INFO lines,
   which means it depends on log level and on the two message strings staying byte-stable.
3. **An explicit runtime metric per slot**, emitted by the runner rather than inferred — so runtime
   survives a log-level change and can be charted.
4. **A no-op marker.** A slot whose body was skipped logs an identical `Running`/`executed` pair to a
   real run; only the ~0 s gap distinguishes them, which is why 76 pairs had to be filtered by a
   threshold rather than a flag.
5. **Checkpoint-coverage reason codes.** 64 of 155 shadow comparisons were skipped for "no usable
   checkpoint" and the logs do not say why, so shadow coverage cannot be driven to 100%.

### Coverage limits of this audit

- 18 trading days, of which only **10 are in the current regime**. The current-regime sample (n=207)
  has never seen a high-volatility session with many simultaneous entries; `send_order`'s own budget
  note (`ibkr_broker.py:730-737`) models a worst-case peak of 265 s of blocking on an all-cluster
  stress day, which alone would exceed the 84 s of headroom.
- `runner_events_*.jsonl` covers only 2026-08-12 → 08-21 and carries nothing about timing.
- Slot start times are APScheduler's, i.e. when the child was *spawned*; process start-up and
  interpreter import time are inside the measured runtime, which is correct for contention but does
  not separate fixed cost from per-sleeve cost.

---

## 6. Verdict

**Slot-lock contention is not a blocker for Track 1 on the current evidence** — at most 1 skipped
slot in 48, worst case, across every tested phasing. Track 1 should **share the existing scheduler**.

**The risk that matters is runtime growth, not slot count.** The margin is 84 s at p95, the behaviour
at the boundary is a step function rather than a slope, and Track 1 adds two unmeasured sleeves to
every run. The four contended days in this sample show exactly what the other side of that step looks
like: half the window's slots gone.

So the gate before adding Track 1 slots in anything but shadow mode is a number, not an argument:
**re-measure the live-day runtime distribution with Calm A and the Stress detector wired in, and
require p95 to stay under 300 s** — ideally under 240 s, to keep the margin that exists today.

## Artifacts

- `scratch/shadow_resume_timing_audit_20260822.py` — parser, distributions, anchored simulator
- `scratch/shadow_resume_timing_audit_20260822.json` — every figure above

---

## Addendum — corrections after review, 2026-08-22

A reviewer read the JSON against the report body and found two statements in section 2 that the data
does not support. Both were mine, both are corrected in place above, and the mechanism behind each is
below. **The Track 1 scheduling conclusion is unchanged** — that is measured, not assumed: the
live-day distributions the conclusion rests on are untouched by either correction (before 08-11
n=85, median 337 s, p95 400 s, max 538 s; from 08-11 n=207, median 191 s, p95 216 s, max 311 s).

### Correction 1 — misfires are not "all on NKD night slots"

| | count |
|---|---:|
| total misfires | 52 |
| on NKD night slots | **43** |
| on other jobs | **9** |
| covered by a machine-sleep stall | **33** |

The nine that are not NKD night:

| when | job | missed by | machine-sleep stall covering it |
|---|---|---:|---|
| 2026-08-04 08:12 | **MAX_HOLD exit 09:31 ET** | **2,476 s (41 min)** | **none** |
| 2026-08-11 21:34 | Stop repair sweep 22:20 ET | 4,475 s | 5,880 s |
| 2026-08-11 22:26 | Stop repair sweep 00:20 ET | 373 s | 1,080 s |
| 2026-08-19 06:29 | Stop repair sweep 08:20 ET | 597 s | 1,140 s |
| 2026-08-19 21:45 | Stop repair sweep 22:20 ET | 5,103 s | 5,460 s |
| 2026-08-20 01:29 | Bao cao phien 23:55 ET | 12,858 s | 13,080 s |
| 2026-08-20 01:29 | Stop repair sweep 00:20 ET | 11,358 s | 13,080 s |
| 2026-08-20 06:33 | Stop repair sweep 08:20 ET | 822 s | 1,380 s |
| 2026-08-20 22:01 | Bao cao phien 23:55 ET | 384 s | 1,320 s |

Eight of the nine are maintenance jobs and every one of those eight is explained by a machine-sleep
stall. **The ninth is not, and it matters:** the 09:31 max-hold close on 2026-08-04 was reported missed by
**41 minutes** and, being 8x past the 300 s misfire grace, **never ran at all** — no `Running job`
line, no `executed successfully` line. (An earlier version of this sentence said "fired 41 minutes
late"; that describes the warning, not the event. See
`scratch/maxhold_misfire_risk_log_20260822.md`.) That is a *trading*
job: a max-hold position was closed 41 minutes after the RTH open it is supposed to exit at. The
original wording ("all on NKD night slots… not contention… the machine being unavailable overnight")
buried a missed trading job inside a sentence about overnight maintenance.

2026-08-04 was the same day the pre-flight failed and all 23 day-window slots were skipped. That day
was broken end to end, not in one place.

**Still true, and re-verified:** no 14:05–15:55 day-window slot misfired, and no misfire is contention.

### Correction 2 — the NKD night maximum

The report's family table carried `~180 s` as the NKD maximum. That was the p95 rounded up, written
into a max column — a figure I approximated instead of reading. The measured maximum was **2,174 s**,
with four runs over 300 s.

Investigated rather than excluded on size:

| run | duration | what it actually is |
|---|---:|---|
| NKD 02:55, 2026-08-21 | 306 s | **real** |
| NKD 02:55, 2026-08-11 | 402 s | **real** |
| NKD 02:55, 2026-08-12 | 532 s | **real** |
| NKD 02:40, 2026-08-19 | 2,174 s | **machine sleep** |

The three real ones are all the **02:55 slot** — the last night slot, the one that carries
`--shadow-verify` (`run_scheduler.py:988`, `verify=((_h,_m) == _NKD_LAST)`). The scheduler's own
comment budgets ~5 extra minutes for that replay, and 306–532 s is exactly that. They belong in the
distribution.

The 2,174 s one does not. At 2026-08-19 01:16 the scheduler logged
`[HEARTBEAT] STALLED 2160s … the scheduler's wait timer does not advance while Windows sleeps`. The
child was spawned at 00:40 and the machine suspended; 2,174 s is wall clock across an OS suspend, not
work. The three misfires logged in the same second (NKD 02:45/02:50/02:55, missed by 30/25/20 min)
are the same event.

Corrected NKD night family: **n=239, median 83 s, p90 148 s, p95 173 s, max 532 s, 3 over 300 s.**

### Correction 3 — the exclusion rule was arbitrary, and one of its labels was wrong

The original script dropped rows over **3,600 s** and called them all "pairing artifacts". Two
problems: 3,600 s is a round number with nothing behind it, and it let the 2,174 s row through.

The rule is now **derived**: `run_scheduler.py:231` sets `_SLOT_TIMEOUT_SECS = 20*60` and `_run` kills
the child at that ceiling, so a `Running`→`executed` gap longer than **1,200 s cannot be one child
run**. Each excluded row is then labelled by mechanism, and the label has to earn itself — a stall is
only accepted as the explanation when it accounts for **at least half** the gap, because a 24-hour gap
contains some stall almost by construction:

| run | gap | stall inside it | share | mechanism |
|---|---:|---:|---:|---|
| NKD 01:10, 08-17 → 08-18 | 86,490 s | 1,380 s | 1.6% | **pairing artifact** (unmatched across a scheduler restart) |
| NKD 02:40, 2026-08-19 | 2,174 s | 2,160 s | **99.4%** | **machine sleep** |
| NKD 01:10, 08-18 → 08-20 | 172,879 s | 13,080 s | 7.6% | **pairing artifact** |

### The finding neither correction was looking for

Chasing the stalls surfaced something the original report missed entirely: **the machine sleeps on
most days.** 28 `HEARTBEAT STALLED` events across 13 of the 18 days, **61,920 s — 17.2 hours — of
stalled scheduler time in total**, worst single stall 13,080 s (3.6 h).

Every stall lands outside the 14:05–15:55 window in this sample, which is why none of the day-window
slots misfired and why the Track 1 conclusion is unaffected. But nothing makes that structural: the
same suspend during a trading window would skip slots for a reason no runtime budget can absorb, and
later G1/G3 preparation showed the scheduler's printed idle-sleep remedy is already applied on this
host. The actual failure class is manual/lid/button-triggered S3 suspend, not idle timeout. Track 1
would add a second window, 10:35–12:30, to a machine that suspends on 72% of days unless the operator
practice changes or the scheduler moves to an always-on host.

### Does the Track 1 scheduler conclusion change?

**No — and the corrected numbers are what says so, not the original ones.**

- The live-day distributions are unchanged by both corrections: no live-day row was excluded, no
  live-day misfire existed to reclassify.
- The simulation input is the live-day sample only, so every forecast in section 3 stands: at most
  **1 skipped slot in 48** across all 207 tested phasings.
- The gate is unchanged: **p95 < 300 s hard, target < 240 s**, measured after Track 1 shadow.

One item is added to the risk list rather than the conclusion: machine sleep is now a named,
quantified operational hazard, and it should be fixed before a second continuous window is added, not
after.
