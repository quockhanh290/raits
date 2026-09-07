# Stage 5ZZD — the last look, and the Monday nobody was covering

**2026-08-27, ET 06:35–06:50.** Scheduler and tests only. No orders · no confirmation file ·
**nothing restarted** · no runtime file touched · **production `spy_daily_live.csv` not touched**
(md5 `80f06253…` unchanged).

---

## Verdicts

| | |
|---|---|
| `pre_nkd_last_chance_built` | **YES** — `spy_last_chance_pre_nkd`, 00:45 ET mon–fri, 25 min before NKD |
| `required_date_logic` | **previous TRADING day, asked of the freshness module** — verified across weekends and Labor Day |
| `no_op_when_covered` | **YES** — returns before building a command; the launcher is never called |
| `final_missing_is_loud` | **YES** — logged at ERROR, names the file, the day, who it stops, and the command |
| `scheduler_restart_required` | **YES** — same restart 5ZZC already needs; one window covers both |
| `orders_possible` | **false**, blockers unchanged |
| `production_spy_csv_touched` | **NO** |
| `runtime_files_touched` | **NO** |

---

## 1. What day it needs, and the answer that justifies the job

The evening ladder asks for **the day that just closed**. This job asks a different question:
**the day the sleeves about to run will demand**. Measured across sixteen consecutive days, the
00:45 computation and what the 01:10 window actually requires agree on every one:

```text
day          dow  NKD 01:10 needs  00:45 computes   same?
2026-08-27  Thu  2026-08-26       2026-08-26       OK
2026-08-28  Fri  2026-08-27       2026-08-27       OK
2026-08-31  Mon  2026-08-28       2026-08-28       OK      <- the Friday
2026-09-08  Tue  2026-09-04       2026-09-04       OK      <- skips Labor Day 09-07
```

From Tuesday to Friday the two questions have the same answer, and **on a Monday they do not**.
On Monday the previous trading day is the Friday, and the last evening rung ran at 17:15 on
Friday — **thirty-one hours earlier**. Nothing between those two instants has ever looked.

That Monday gap is what this job is for. The weekday cases are cheap insurance; the Monday case
is the hole.

It protects more than the Nikkei window. **Everything that runs before the 13:45 pre-flight reads
this file** — the overnight window at 01:10 and both Calm phases at 09:32 and 10:02 — and all of
them refuse if it is short. That was yesterday's lesson and it is written into the failure
message.

## 2. Where it sits

```text
00:20 ET  stop_repair_0020 / track1_stop_repair_0020
00:45 ET  spy_last_chance_pre_nkd          <- new
01:10 ET  track1_nkd_0110                  <- the first freshness-bound slot
...
02:55 ET  track1_nkd_0255
```

25 minutes of clearance, and 00:45 was free. Measured from real construction, not read off a
list.

## 3. It asks the gate rather than restating the rule

```python
need = _fresh.required_daily_close_through(_pd.Timestamp(_et_today()))
```

Two deliberate choices, and both have a scar behind them:

- **`required_daily_close_through`, not a local calculation.** A second copy of "which day is
  needed" drifts from the gate that actually refuses, and then the job reports fine about a
  morning the gate is about to stop.
- **`_et_today()`, not `date.today()`.** That helper's own docstring records the measurement:
  *"on any machine west of ET the night slots (01:10–02:55 ET) land on the PREVIOUS local
  date"*, and it names the day in 2026-08 that cost. A job at a quarter to one in the morning is
  precisely where that bites, and it would ask for the wrong session by one day exactly when it
  matters most.

Both are pinned by a test that reads the job's source and fails if either is replaced.

## 4. The three things it can do

```text
already covered   nothing to do — the daily series covers 2026-08-26, which is what the
                  overnight window and both Calm phases will ask for.
                  -> the launcher is never called. No fetch, no API key, no failure possible.

it arrives now    RECOVERED at the last look — 2026-08-26 arrived after the evening ladder had
                  given up. The 17:15 rung is running before the provider is ready on at least
                  some days.
                  -> a WARNING, not a note: a last chance that keeps saving the evening is an
                     evening schedule that wants moving.

still missing     SPY daily file is missing 2026-08-26; NKD/Calm freshness-bound slots will
                  refuse unless manually refreshed. The series ends on 2026-08-25. This is the
                  LAST attempt before the overnight window at 01:10 — nothing else looks until
                  the 13:45 pre-flight, which is after both Calm phases. Re-run:
                  python -m global_index.update_spy_csv --csv spy_daily_live.csv
                       --verify-strict --require-through 2026-08-26
                  -> ERROR level, and it carries the command rather than describing it.
```

The no-op path returns **before the command is built**, so a covered night cannot fail. That is
not decoration: the same short-circuit is what stopped the evening retries reporting a failure on
every good day, measured in the previous stage.

The comparison is `>=`, not `==`. A file that is already ahead of the requirement is not a file
that is short.

The failure carries its own label, `SPY_LAST_CHANCE_PRE_NKD`, distinct from `SPY_REFRESH_PM_R2`.
Same shortfall, two moments, two reactions: the evening rung says a morning is **at risk**; this
one says the morning is **lost unless somebody acts now**. A test asserts the two never wear each
other's name.

## 5. Status and dashboard already answer at this hour

Both compute the requirement from the same freshness module, so at 00:45 they name the same day
without any change here:

```text
ops.py status      spy_daily_coverage=covers_required_day last=2026-08-26 required=2026-08-26
dashboard row      SPY daily — SPY daily file covers 2026-08-26
```

and when short, the dashboard row still says *"This is a stale daily-context warning, **not a slot
failure**"* — kept apart from the window verdict, which on 2026-08-27 read PASS on 22 of 22 slots
while the diagnostics said the inputs were stale. Two true facts about different things.

## 6. Tests

**21**, in `scratch/test_track1_stage5zzd_pre_nkd_spy_refresh_20260827.py`. No network, nothing
written outside `tmp_path`, production series read but never modified.

Registration and clearance · the requirement is the previous **trading** day, checked on a
Thursday and on a Monday · Labor Day skipped · it asks the gate and uses the ET calendar · no-op
calls nothing · a series ahead of the requirement is also nothing to do · RECOVERED · the loud
final failure · the two labels never collide · dry-run invents no failure · argv carries
`--verify-strict --require-through --skip-if-covered` · no SPY job and no Track 1 slot can ask
for orders · orders still impossible.

**Two real mutations** — replacing the calendar so the requirement becomes the session's own day,
and so the holiday stops being skipped — both red.

**Two source guards, labelled as such rather than counted as mutations.** The branches they
protect live inside a closure that cannot be reached from outside to be broken, so they assert a
property of the source: that the final shortfall is still logged at ERROR, and that the no-op
comparison has not been inverted or narrowed to equality. A source guard catches an edit, not a
behaviour. It is weaker and it says so.

## 7. A pin I broke, and repaired in both places

Yesterday's stage asserted the scheduler's **total size** — 63, 133, 104 — and this stage broke
it by adding one job that has nothing to do with the ladder. That is the roster anti-pattern
already on this project's record: a pin that fails for something it is not about teaches whoever
reads it that the failure is noise.

Repaired as a **property**: the ladder is the three named rungs, in every mode. And the equivalent
test written for this stage was rewritten the same way before it could rot — the SPY family is
four named jobs, and an unrelated job added tomorrow leaves both alone.

## 8. Restart

**Required**, and it is the same restart Stage 5ZZC already needs — the running scheduler (PID
5856, started 04:08 ET) holds neither the retry rungs nor this job. One restart brings both live.

Nothing is worse meanwhile: tonight's 16:20 refresh behaves as it did yesterday, `ops.py status`
says whether the file is short, and today's daily file already covers what the morning asks for.

**Window: 12:40–13:45 ET** — the measured 65-minute gap after the Stress window's audit and
before the pre-flight, and after both Calm phases have been watched.

```powershell
python monitor\ops.py restart --scheduler --track1-only-shadow --yes
```

Verified rather than assumed: `--shadow-resume` is the default on that path, so the replacement
starts with argv byte-identical to what PID 5856 runs today. **Not run — the operator's call.**

## 9. What this does not change

The Calm watch from Stage 5ZZC is still pending: it is 06:49 ET and the phases run at 09:32 and
10:02. Nothing here touches Track 1 slot logic, the order gate, or the paper blockers, and the
baseline recorded this morning is unchanged — no order directory, no intent stream, the book and
checkpoint where the overnight window left them.
