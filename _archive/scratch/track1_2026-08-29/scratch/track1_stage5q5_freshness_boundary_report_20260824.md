# Stage 5Q-5 — the D-1 freshness contract, and the boundary bar the appender never revisited

**2026-08-24 ·** scheduler **not** started, stopped or restarted (pid 28696, unchanged) ·
backend **not** restarted · **no IBKR connection made** · no order · no confirmation file · no
`live_positions` or checkpoint written · **no parquet or CSV mutated** — all five parquets
still carry their Friday 13:45–13:47 ET mtimes, `spy_daily_live.csv` and
`preflight_state.json` are byte-identical · every test write went to `tmp_path` · no commit ·
`_refuse_overlap_disagreement` **not** weakened · MNQ repair **not** applied.

---

## Verdict: **NOT_READY for 5R — B-5R-E and B-5R-F are fixed in code, but neither is live, and B-5R-D is unrepaired**

Everything below is implemented, tested and mutation-checked. What stops a READY verdict is
sequencing, not design:

| | closed in code | live now | what it needs |
|---|---|---|---|
| **B-5R-E** requirement half | yes | **yes** — the next slot imports it | nothing |
| **B-5R-E** refresh half | yes | **no** | a scheduler restart |
| **B-5R-F** boundary appender | yes | **no** (off by default) | a scheduler edit + restart |
| **B-5R-D** the MNQ bar | tooled | **no** | one operator command, after approval |

---

## Part A — the freshness contract

### The diagnosis, restated precisely

**One requirement was being asked of two data sources with different availability.** That is
the whole of B-5R-E, and it has two independent halves.

`update_spy_csv` runs inside the 13:45 pre-flight and fetches through "today". SPY's daily bar
does not close until 16:00, so that fetch can never bring today's close. Asking the CSV for
today from 13:45 asks for a number that does not exist — **and the route does not need it**: a
session on day D trades the regime label of D−1, because `RegimeLabels.get` returns
`reg.asof(day - lag_days)` with `lag_days = 1`. Read from the code, not assumed.

The intraday parquets are a different question with a different answer. One-minute futures
bars for today DO exist at 13:45 and the pre-flight fetches them, so requiring today from
13:45 is right for them and always was.

### The design chosen — option 1, split the requirement

Of the three offered, this is the smallest that preserves causality and matches what the
backtest read:

```python
required_intraday_through(now)      # unchanged rule, for the parquets
required_daily_close_through(now)   # the last TRADING day before today, for the daily series
required_data_through(now)          # kept as a name, delegates to the intraday one
```

`required_data_through` keeps its name and its meaning because **every existing caller means
the intraday one**; renaming it would have moved the meaning of live call sites silently.

Option 3 (splitting `preflight_state.json` into per-source fields) was rejected: that file is
written by the SHARED 13:45 job and read by legacy too, so re-shaping it is a much wider blast
radius for the same information — which the new consistency check below already surfaces
without touching the file.

**Holiday-aware.** `prev_trading_day` uses `raits.live.trading_calendar` where importable and
reports which calendar it used. A weekday-only rule names the holiday itself on the day after
one — a close that no refresh can ever supply, so the gate would refuse for ever on a route
that was fine. Measured: the Monday after 2026-07-03/04 now asks for Thursday 2026-07-02.

### The contradiction, now named

A new `preflight_consistency` check. `preflight_state.json` says a day's 13:45 job succeeded;
it does **not** say which dates landed. On 2026-08-21 it said `true` while the CSV still ended
2026-08-20, and nothing named that. It does now:

```text
preflight_consistency  stale  the pre-flight record for 2026-08-21 says the 13:45 job
                              SUCCEEDED, and ['regime_csv'] still do not satisfy what the
                              gate asks of them. A successful refresh that leaves an input
                              short is not a failed job — it is a job that cannot supply what
                              is being asked for, which is a contract question, not a retry.
```

It stays silent when the pre-flight itself failed, because a retry and a contract question are
different problems with different owners.

### What the fix actually changes, measured

| instant | old | new |
|---|---|---|
| Fri 09:00 | allow | allow |
| **Fri 14:00 → Fri 23:59** | **REFUSE** (asked for a close two hours away) | **allow** |
| Mon 09:00 | refuse | **refuse — and correctly**: Monday needs Friday's close, the file holds Thursday's |
| Mon 14:00 | refuse | refuse, same reason |

So the requirement fix recovers roughly **ten hours of every trading day** that were being
refused for a reason that was not true. It does **not** unblock a morning, and that is the
second half.

### The half a requirement cannot fix — the post-close refresh

The CSV gains day D−1 at day D's 13:45 pre-flight, and the requirement on day D+1 is D. One
business day apart, permanently, because **the 13:45 pre-flight is the only data refresh in
the schedule** — confirmed by reading `run_scheduler`.

Widening the requirement to accept D−2 was rejected outright: it would trade a session on a
label the backtest never used, which is a rule change disguised as a threshold.

So: a new job.

```text
16:20 ET, mon-fri, id=spy_refresh_pm, "SPY daily refresh 16:20 ET (post-close)"
```

- **16:20, not 16:00** — Polygon's daily aggregate settles a few minutes after the close, and
  asking at 16:00 fetches the same short series the 13:45 run already has. Twenty minutes is
  the same order of margin the 13:45 job leaves before 14:05.
- **SPY only.** `update_ibkr_daily` is not re-run: the intraday parquets were already brought
  to today at 13:45, and a second IBKR fetch would open a second Gateway client for no gain.
- **It does not write `preflight_state.json`.** That record is about the 13:45 job; a second
  writer would make "did the pre-flight run" ambiguous. The evidence this job worked is the
  CSV's own last date, which the gate already reads.
- **A failure is not a pre-flight failure.** Nothing today depended on it, and marking the day
  failed here would skip tomorrow's slots for a job that ran after everything today finished.

**Inventory (Part D).** 60→**61**, 129→**130**, 100→**101**, in all three modes.
Scheduler/dashboard parity holds in all three, because the mirror got the row from the same
change. It is classified `shared_infra`, so a legacy retirement cannot take the refresher with
it — the property the Stage 5L table exists for.

---

## Part B — the boundary bar

### The rule needs no threshold to tune

A partial bar can only be **completed**, never contradicted. Over the rest of its minute:

```text
open    cannot change     it is fixed by the first tick
low     can only fall     more trades can only extend the range downward
high    can only rise
volume  can only grow
close   may move anywhere  it is simply the last tick so far
```

So "is this a completion of the same bar, or a disagreement about which bar it is?" is
decidable from the two rows alone. `boundary_replacement(existing, fetched, last_existing)` is
pure — two frames in, one row out, no IO, no broker, no clock — which is the only way a rule
that runs once a day at 13:45 against a live Gateway ever gets exercised. A test parses its
AST to keep it that way.

Anything violating the monotonicity is **refused by name**: `open_changed`, `low_rose`,
`high_fell`, `volume_shrank`. On top sits a cruder net, `moved_too_far` at 0.5% of the stored
close, for the case where every monotonic rule happens to hold but the bar is from a different
contract entirely. Nothing legitimate sits near that line — a real completion of one minute
moves a fraction of a percent.

Against the measured MNQ bar:

```text
stored  open 29404.50  high 29408.00  low 29400.25  close 29404.50  volume 1399
feed                                  low 29395.75
        -> completed: ['close', 'low', 'volume']
```

### Wiring, and what stays exactly as it was

- `new_only = new_bars_adj[new_bars_adj.index > last_existing]` **is untouched.** The boundary
  bar is the one exception, not a widening.
- The replacement is concatenated **between** history and the new bars, so the existing
  `~duplicated(keep="last")` prefers it — the mechanism the strictly-newer filter had been
  preventing from ever engaging.
- The history invariant still requires every other bar in the 200-bar tail to come out
  untouched; the boundary timestamp is excluded **by name**, not by relaxing the comparison.
- A replacement gets what an append does not need: a **snapshot** (`.pre5q5-<stamp>.bak`,
  refused if one already exists) and a **re-read** to prove the write landed. The repo has
  already lost a baseline to an in-place parquet write with neither.
- Every existing protection — roll identity, splice offsets, alignment drift, join jump, UTC
  convention — runs before any of this and is unchanged.

### It is OFF by default, and that is deliberate

`--repair-boundary`, absent from the scheduler's argv. It is the only path in that file that
rewrites a bar the parquet already has, and the job runs unattended at 13:45. Enabling it is a
scheduler edit plus a restart, which is the point: an operator decides, not a deploy.

**Today's 13:45 run therefore behaves byte-identically to yesterday's.** The new code is on
disk and will execute; the flag is not passed, so `boundary` is `None` and every path is the
one that ran before.

---

## Part C — sequencing the MNQ repair

**Not applied. No parquet was touched.**

Two tools can now do it, and they are for different moments:

**Measure first — writes nothing, one instrument, safe whenever the Stress window is closed
(after 12:30 ET):**

```powershell
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
```

**Then repair with the appender**, once the operator has read the measurement and approved it.
This is the recommended path rather than the scratch tool, because it is the same code that
will prevent recurrence when the flag is enabled in the scheduler — repairing with the tool
that will be doing this daily is one rule, not two:

```powershell
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ
```

It connects to IBKR on client id 2 — the updater's own, distinct from the Track 1 data client
89, the safety client 90 and legacy's 1 — snapshots before writing and verifies by re-reading.

**This requires manual approval.** It rewrites a bar in shared history, and the scratch tool's
`--expect <sha256>` guard is the stricter of the two if an explicit hash gate is wanted; the
appender's guard is the monotonic completion rule plus the snapshot.

Neither should run while the Stress window is open.

---

## Part D — runtime safety

- **Scheduler not restarted, not stopped.** pid 28696 throughout.
- **Live without a restart:** `track1_freshness.py`. Every slot spawns a fresh child that
  imports it, so the corrected requirement applies from the next slot — and from 13:45 today
  the gate stops refusing for a reason that was not true.
- **Not live without a restart:** the `spy_refresh_pm` job. Job definitions are fixed when
  `make_scheduler` builds the schedule, so today's scheduler has 100 jobs and will not run it.
- **Not live at all until enabled:** `--repair-boundary`, which needs a scheduler edit as well
  as a restart.
- **Backend:** the mirror gained a row, so `/api/v1/schedule-status` will not know about
  `SPY_REFRESH_PM` until the backend restarts. Until both restart, scheduler and mirror agree
  — because neither has it.
- No order path changed. **B1 remains blocking; orders remain impossible.**

---

## Part E — tests

| Suite | Result |
|---|---|
| **Stage 5Q-5** `test_track1_stage5q5_freshness_boundary_20260824.py` (new, 42) | **42 passed** |
| **Stage 5Q-5 mutation harness** (new, 16) | **16 / 16 detected**, four files restored byte-for-byte |
| Track 1 regression (14 files, 5Q-5 → 3B) | **572 passed, 1 skipped** |
| `monitor/` production suites (5 files) | **303 passed** |

The sixteen mutations. **P1, P6 and P9 are not inventions — they put back exactly what was on
disk this morning:**

```
P1   the daily series is asked for the intraday requirement again  -> Friday-afternoon test reds
P2   the daily requirement becomes today                           -> the instant table reds
P3   holidays stop being skipped                                   -> the post-holiday test reds
P4   a true pre-flight over short data is no longer named          -> the contradiction test reds
P5   a FAILED pre-flight is reported as a contradiction too        -> the silence test reds
P6   the post-close SPY refresh is removed                         -> the job test reds
P7   the SPY refresh is no longer shared infrastructure            -> the classification test reds
P8   the post-close job re-runs update_ibkr_daily too              -> the SPY-only test reds
P9   the boundary bar is never revisited                           -> the flag test reds
P10  a bar whose OPEN changed is accepted as a completion          -> open_changed reds
P11  a low that ROSE is accepted                                   -> low_rose reds
P12  a volume that SHRANK is accepted                              -> volume_shrank reds
P13  the percentage net is removed                                 -> moved_too_far reds
P14  the history invariant is skipped when a replacement happens   -> the exemption test reds
P15  a replacement writes with no snapshot and no verify           -> the snapshot test reds
P16  the strictly-newer filter is dropped for everything           -> the filter test reds
```

### Five older tests changed meaning, and none is weakened

- **`test_the_preflight_marks_a_day_true_that_the_spy_csv_cannot_yet_cover` (5Q-4, mine)**
  asserted the OLD behaviour: Friday 13:46 must be stale. It now asserts the corrected
  requirement passes there **and** that Monday morning still refuses — the defect test became a
  fix test with the remaining gap attached, which is what the brief asked for.
- **The 5Z fresh/stale fixtures** produced their refusing run with the CLOCK: at 15:00 the gate
  asked the daily series for today's close and refused. **That refusal was the bug.** The
  property 5Z exists for — a replay decision must not cite a gate whose reading moves while the
  decision does not — is untouched; the refusing run now comes from genuinely short data, which
  is the honest way to produce it. Its test was renamed from `..._two_clocks_...` accordingly.
- **Six inventory assertions** across 5L, 5M-D, 5O, 5P ×2 and 5Q moved 60→61, 129→130,
  100→101, and the shared-infra tables gained `spy_refresh_pm`. All are the intended change.

### And once more, my own instrument was wrong

The purity test for `boundary_replacement` scanned the function's text for `"fetch"` and went
red on its own refusal message *"not_offered: the fetch does not cover..."*. That is the
**fourth** substring-over-prose test across these stages and the fourth time it failed on a
sentence rather than on code. It now parses the AST and asserts the set of called names is
disjoint from the IO names, with no imports inside the function.

---

## Files

**Changed (production)**

```text
global_index/track1_freshness.py     + required_intraday_through / required_daily_close_through
                                     + prev_trading_day / calendar_source
                                     + check_preflight_consistency; evaluate uses both
global_index/update_ibkr_daily.py    + boundary_replacement (pure) and --repair-boundary (OFF)
                                     + snapshot and post-write verify on a replacement
global_index/run_scheduler.py        + the 16:20 spy_refresh_pm job
global_index/track1_slots.py         + spy_refresh_pm in SHARED_INFRA_JOBS
monitor/backend/schedule_status.py   + SPY_REFRESH_PM in PIPELINE_FIXED_SLOTS
```

**Added**

```text
scratch/test_track1_stage5q5_freshness_boundary_20260824.py   42 tests
scratch/track1_stage5q5_mutations_20260824.py                 16 mutations
scratch/track1_stage5q5_freshness_boundary_report_20260824.md   this report
scratch/track1_stage5q5_freshness_boundary_report_20260824.json
```

**Unchanged on purpose:** `track1_live_source.py` (the overlap guard), `track1_live_frame.py`,
`track1_shadow_acceptance.py`, every order path.

---

## Remaining blockers before 5R

| id | what | state |
|---|---|---|
| **B-5R-E** | the freshness contract | **code fixed.** Requirement half is live; the 16:20 refresh needs a restart |
| **B-5R-F** | the boundary appender | **code fixed, OFF.** Needs a scheduler edit + restart to engage |
| **B-5R-D** | the MNQ bar | **unrepaired.** Measure, then one approved command |
| **B-5R-C** | NKD after 2026-11-01 | open, reported as WARN |
| **B1** | the order gate | open by design; orders impossible |

---

## Operator page

Nothing is required today. When you want the fixes live, in this order:

```powershell
# 1. measure the MNQ bar. Writes nothing. Safe after 12:30 ET.
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ

# 2. repair it, only after reading step 1. Snapshots and verifies.
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ

# 3. bring the 16:20 SPY refresh and the corrected mirror online.
python monitor\ops.py restart --scheduler --track1-only-shadow
python monitor\ops.py restart --no-scheduler --track1-only-shadow
```

*(`restart --help` verified: there is no `--backend` flag; backend-only is `--no-scheduler`.)*

**Step 3 costs the current day's judgement** — every window that already closed reads as
pre-start on a new process — so prefer it before 10:00 ET or after 16:00 ET.

To make the boundary repair permanent rather than manual, the scheduler's pre-flight argv
needs `--repair-boundary` added. That is a code change plus the same restart, and it is left
for a decision rather than made here: it is the only path in the updater that rewrites a bar
the parquet already has.
