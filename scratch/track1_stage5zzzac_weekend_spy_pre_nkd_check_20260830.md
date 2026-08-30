# Stage 5ZZZ-AC — a Sunday evening look at the SPY series

**Route:** `track1_candidate` · **Date:** 2026-08-30 · **Orders:** never enabled, still impossible

**Job added. Scheduler NOT restarted — so it is not live yet.** That is the one thing to act on.

---

## 1. The gap, and a live change to it

On Friday 2026-08-28 all three evening rungs ran and the provider still did not return that
day's close. Nothing looks again until Monday 00:45 — **fifty-five hours of silence**, ending
twenty-five minutes before the NKD window, in the middle of the night.

**The immediate gap closed while this stage was being written.** `spy_daily_live.csv` read
`2026-08-27` at 04:56 and `2026-08-28` afterwards; file mtime `05:11:31`, rows 2426 → 2427.

What it was **not**: the scheduler (today's log has heartbeats only, and the running scheduler
has no Sunday SPY job at all), `coverage_status` (read-only, checked in source), or my test runs
(the harness replaces the launcher so nothing spawns, and every regression ran *after* 05:11).
Most likely a manual run. Recorded as measured, **not guessed**.

So tonight's window has its data either way. What this stage fixes is the **structural** gap:
nothing automatic looks across the weekend.

## 2. Exact schedule added

```python
@sched.scheduled_job("cron", day_of_week="sun", hour=18, minute=0,
                     id="spy_weekend_pre_nkd_check",
                     name="SPY weekend pre-NKD check 18:00 ET (Sunday early warning)")
```

APScheduler is ET-native, so this is 18:00 **ET**. The repo already has a weekend job — the
Sunday 18:30 stop-repair sweep — registered the same way, so this follows the existing
convention rather than inventing one. **18:00 puts the data check half an hour before the
protection sweep**: one Sunday log that reads in order, *is the data there*, then *is the book
protected*.

## 3. Exact required-date logic

```python
need = _fresh.required_daily_close_through(_pd.Timestamp(_et_today()))
```

**Nothing is computed by hand.** It is the same function the 00:45 job and the freshness gate
call, which is what stops this job reporting fine about a day the gate is about to refuse.

| asked on | returns | |
|---|---|---|
| Sunday 2026-08-30 | **2026-08-28** (Friday) | exactly the day that was missing |
| Sunday 2026-09-06 | **2026-09-04** (Friday) | skips the Labor Day Monday — **no special case in the job**; the next session is the Tuesday and the function already knows |
| Monday 00:45 | 2026-08-28 | the two jobs agree, verified by test |

`_et_today()`, never `date.today()` — on a machine west of ET the 01:10 slots land on the
previous local date.

The test that pins this parses the job's code, **strips the docstring and blanks string
literals**, then scans for `weekday()` / `timedelta(` / `friday`. It is proven to catch a
hand-rolled version and to pass the real one.

## 4. Behaviour

| case | what happens |
|---|---|
| already covered | logs *nothing to do*, **calls no provider** |
| missing | `update_spy_csv --csv spy_daily_live.csv --verify-strict --require-through <day> --skip-if-covered` (+ api key) |
| recovered | **WARNING** — the Friday ladder was late, the weekend recovered it |
| still missing | **ERROR** naming the required day, the day it ends on, the 01:10 window, the remaining 00:45 attempt, and the manual command |
| provider fails | stays **fail-closed** — no RECOVERED, the shortfall is still reported |
| dry-run | invents no failure |

**It never writes `preflight_state.json`.** Pre-flight is a weekday 13:45 contract; a weekend
job stamping it would be claiming a check nobody ran.

## 5. The 00:45 job is untouched

Still `day_of_week="mon-fri"`, 00:45 ET, unmodified — and a test pins that, because the brief
was explicit and "I did not touch it" is worth more as an assertion than as a sentence.

## 6. Dashboard and journal

- **Schedule mirror**: `SUNDAY_SPY_PRE_NKD_SLOT = (6, 18, 0)`, mirrored the same way the Sunday
  sweep is. Without it the dashboard treats the slot as stray and invents an incident every
  week. Order verified: `SPY_WEEKEND_PRE_NKD_CHECK` 18:00 → `STOP_REPAIR_SUN_1830` 18:30.
- **Journal**: `job_type: spy_weekend_pre_nkd_check` — a **third** stream, separate from both
  `spy_refresh_pm` and `spy_last_chance_pre_nkd`.

Why separate matters: folding it into the ladder would let a Sunday success mark a **Friday**
rung recovered — the same fault Stage 5ZZT fixed when a stop-repair sweep was closing failed
refreshes. Folding it into the last-chance stream is subtler and still wrong: a Sunday failure
that Monday then fixes is a real two-event recovery story, not one.

## 7. ops.py status

When the file is short on a weekend it now names **which** automatic attempt is still ahead —
and always still names the Monday last chance:

```text
SPY daily file is missing 2026-08-28 — it ends on 2026-08-27. … Next automatic attempts:
SPY_WEEKEND_PRE_NKD_CHECK today 18:00 ET, then SPY_LAST_CHANCE_PRE_NKD Monday 00:45 ET
(25 min before NKD 01:10)
```

On a weekday it stays silent — the evening ladder speaks for itself.

## 8. Tests

**27 new, all passing. 351 regression passed, 3 failed — all three pre-existing** (the
confirmation-file assertion from 08-27, and two 71-vs-70 slot-count pins).

**Three tests I updated because my change made them wrong**, said plainly rather than folded
into a pass count:

- the SPY family is now **five** jobs, not four — the count in the name grew rather than the
  assertion being loosened to "at least four";
- Sunday now has **two** slots, and the **order** is part of the assertion;
- the first thing to look at the data after Friday's close is now this job — which is the point.

**A test of mine that was wrong.** My first *never writes preflight_state* check scanned raw
source and matched the **docstring**, which mentions `preflight_state.json` precisely to say it
does not write it. Rewritten as an AST walk with the docstring stripped. A stricter second pass
then flagged the word "Friday" in an honest log message, so string literals are blanked too —
a sentence is not a date calculation.

---

## 9. Answers

| question | answer |
|---|---|
| exact schedule | `day_of_week="sun", hour=18, minute=0` ET, id `spy_weekend_pre_nkd_check` |
| required-date logic | `track1_freshness.required_daily_close_through(_et_today())` — never computed here; holiday Mondays need no special case |
| 00:45 job remains | **Yes**, untouched and pinned by test |
| mirror/dashboard sees it | **Yes** — Sunday 18:00, before the 18:30 sweep; own journal stream |
| restart required | **Yes** — APScheduler reads cron only at startup |
| restart done | **No** — the brief said not to unless requested |
| current gap covered after restart | the immediate gap is already closed (§1). If restarted **before 18:00 ET today** the job runs tonight; otherwise the first automatic attempt is again Monday 00:45 |

**To make it live:** `python monitor/ops.py restart --scheduler --track1-only-shadow --yes` —
the job fires **Sunday 18:00 ET** (MT Sun 16:00 · VN Mon 05:00), about 10.8 hours after this
was written.

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             present, STILL GITIGNORED, sha16 67504a1c8a31a6a4
swing paper override     present, valid, grants nothing
broker calls             ZERO
scheduler / backend      NEITHER restarted
SPY csv written by this stage        NO       preflight_state written   NO
strategy logic · params · gates · regime/freshness requirements   unchanged
```
