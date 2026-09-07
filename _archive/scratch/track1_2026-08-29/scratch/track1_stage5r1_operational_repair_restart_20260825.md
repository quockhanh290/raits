# Stage 5R-1 — the one-time repair, the restart, and the first clean tail

**2026-08-24, 23:25–23:45 ET ·** every Track 1 window closed throughout · **the NKD window
opens at 01:10 ET, 1h25m after this stage ended** · parquets MNQ/MYM/M2K mutated through the
approved appender, snapshotted and verified · MES and MNKD untouched · scheduler and backend
restarted deliberately · no order · no confirmation file · `TRACK1_ORDERS_APPROVED` unset ·
B1 still blocking · no evidence row deleted or rewritten · no commit.

---

## Verdict: **READY_FOR_NEXT_JUDGEABLE_TRACK1_SHADOW_WINDOW**

### The direct answers

| question | answer |
|---|---|
| **Repair applied or refused?** | **Applied**, exit 0. All three boundary bars replaced and verified by re-read, `history-check OK` |
| **Which real data files changed?** | **Exactly three**: `NQ_`, `YM_`, `RTY_continuous_1m_8y.parquet`. MES, MNKD, `spy_daily_live.csv`, `preflight_state.json` and the splice sidecar are byte-identical |
| **Did the probes return `nothing_to_repair`?** | **Yes — all three**, with `shared_disagreements_total: 0` and nothing in or outside the window |
| **Is the scheduler running corrected Track1-only shadow?** | **Yes.** pid 45272, started 23:29:35 ET, **101 jobs**, `spy_refresh_pm` present, legacy strategy jobs 0 |
| **Is the backend mirror corrected?** | **Yes** — `SPY_REFRESH_PM at 2026-08-25 16:20:00-04:00` is in the scheduled slots. *(My Stage 5Q-6 claim that it was missing was a bad measurement — see below)* |
| **Are orders still impossible?** | **Yes.** `orders_possible=False`, `track1_blocking=['B1_broker_account_or_legacy_retirement']`, no confirmation file, env unset |
| **Next judgeable Track 1 window?** | **`global_nkd`, 01:10–02:55 ET on 2026-08-25** — 14:10–15:55 JST, covered end to end by a scheduler that has been up since 23:29:35 ET |

---

## Part A — before

```text
key        size        mtime                sha256[:24]              last bar             tz
MNQ        57,676,712  2026-08-24 18:21:17  c0ae9d3c3c7984f7731436be 2026-08-25 00:20:00  None
MYM        52,990,667  2026-08-24 18:21:42  272003cda1c17c83e105be32 2026-08-25 00:21:00  None
M2K        46,764,142  2026-08-24 18:22:05  e4e2e1c49606a36d1ed790e2 2026-08-25 00:21:00  None
MES        51,460,064  2026-08-24 11:45:24  99da6feb97ea1a28abb9ffae 2026-08-24 17:44:00  None
MNKD       28,134,902  2026-08-24 11:46:46  a761a36b2018f82f0869bfb9 2026-08-24 17:46:00  None
spy csv, preflight state, splice sidecar — all fingerprinted
```

All four windows closed at 23:25 ET; nothing was open at any point in this stage.

---

## Part B — the repair, and the first live proof of 5R-0

```powershell
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ MYM M2K
```

```text
MNQ  final-bar check — dropped: 2026-08-25 03:26:00 is still open at 03:26:0x
     alignment over 2902 shared bars — median +0.0000, IQR 0.0000
     boundary bar 2026-08-25 00:20:00 — completed: [...]
     snapshot -> NQ_…pre5q5-20260825T032631Z.bak
     replaced and verified by re-read   (3,357,680 bars, history-check OK)
MYM  dropped 03:26 · boundary 00:21 completed ['close','high','volume'] · +184 bars · OK
M2K  dropped 03:26 · boundary 00:21 completed ['close','high','volume'] · +184 bars · OK
exit 0
```

**This is Stage 5R-0 working on live data for the first time.** Each fetch reached 03:26 UTC,
and each stored only through **03:25** — the last *closed* minute. Twelve hours ago the same
command would have frozen three fresh partial bars; tonight it froze none.

### After

```text
MNQ   CHANGED  a13167b1fd502853…   last 2026-08-25 03:25:00   tz None
MYM   CHANGED  f2af776ad28eff78…   last 2026-08-25 03:25:00   tz None
M2K   CHANGED  86009f82160e9914…   last 2026-08-25 03:25:00   tz None
MES   same     99da6feb97ea1a28…   MNKD  same  a761a36b2018f82f…
spy csv, preflight state, splice sidecar — all same
```

tz-naive on all three, columns `open,high,low,close,volume` unchanged. Snapshots taken **only**
for the three touched files (`…pre5q5-20260825T0326/0327…Z.bak`), alongside last night's three.

### The probes

```text
MNQ   shared_disagreements_total: 0   in_window: []   outside_window: []   nothing_to_repair
MYM   shared_disagreements_total: 0   in_window: []   outside_window: []   nothing_to_repair
M2K   shared_disagreements_total: 0   in_window: []   outside_window: []   nothing_to_repair
```

**Zero disagreements anywhere.** This is the first repair run in the entire sequence to leave a
clean tail, and it is the observation that closes B-5R-H on the live files rather than only in
the code.

---

## Part C — the restart, and something the log told me I had not known

The scheduler restart worked, but the pids it stopped were **16752 / 35088**, not the
28696 / 11720 I had recorded. `monitor/logs/ops.log` explains it:

```text
2026-08-24T21:15:26  scheduler: found=[28696] -> kill_then_start
2026-08-24T21:15:31  backend:   found=[11720] -> kill_then_start
2026-08-24T21:29:32  scheduler: found=[16752] -> kill_then_start      <- this stage
2026-08-24T21:29:36  backend:   found=[35088] -> kill_then_start      <- this stage
```

**The operator had already run the restart at 21:15 local (23:15 ET)** — the action outstanding
since Stage 5Q-7 — about ten minutes before this stage began. Mine at 21:29 superseded it. Both
brought up **101 jobs**, so the state is the same either way, and every window was closed
between 23:15 and 23:29, so nothing was interrupted.

Worth stating plainly rather than glossing: I restarted a process I had not established was
still the one I recorded. It cost nothing here because the windows were shut, but the check
belongs *before* the command, not in the log afterwards.

### Post-restart verification

```text
scheduler   pid 45272   started 2026-08-24 23:29:35 ET
            pythonw -m global_index.run_scheduler --port 4002 --shadow-resume --track1-only-shadow
backend     pid 27540   started 23:29:38 ET
track1_mode                     track1-only-shadow
Jobs                            101
  Track 1 strategy slots        70
  Track 1 safety                11   (track1_maxhold_exit + 10 track1_stop_repair_*)
  Track 1 audit                 5
  legacy safety (the drain)     11
  shared                        4    (heartbeat, preflight, session_report_fallback,
                                      spy_refresh_pm)
  legacy STRATEGY jobs          0
spy_refresh_pm                  present, 16:20 ET
--repair-boundary               in the 13:45 pre-flight argv (run_scheduler.py:879)
backend mirror                  SPY_REFRESH_PM at 2026-08-25 16:20:00-04:00
scheduler_process (backend)     stale_code: False
orders_possible                 False   blocking ['B1_broker_account_or_legacy_retirement']
```

### A correction to my own earlier measurement

In Stage 5Q-6 and again in 5Q-7 I reported "the backend mirror lacks `SPY_REFRESH_PM`", tested
by checking whether that string appeared in the `/api/v1/schedule-status` JSON. **That endpoint
never enumerates slots** — its keys are `active_window`, `freshness`, `next_scheduled_job` and
so on. The string was absent because no slot list is returned, not because the row was missing.

Measured properly, by calling `_scheduled_slots_for` for the day, the row is present and at the
right time. The mirror may well have been correct since the moment the code landed. What was
wrong was the instrument: a substring search over a payload that could not contain the answer
either way.

---

## Part D — the cost of the restart, paid and visible

```text
global_nkd     NOT_ENOUGH_DATA_YET   window_closed_before_scheduler_start
roska4_calm    NOT_ENOUGH_DATA_YET   scheduler started 23:29:34 — AFTER the window closed
roska4_stress  NOT_ENOUGH_DATA_YET   …
roska4_swing   NOT_ENOUGH_DATA_YET   …
DAY 2026-08-24 NOT_ENOUGH_DATA_YET
  "Nothing here has both closed and been covered by scheduler uptime. That is a statement
   about how far the session has got, NOT about the route's health."
```

Exactly the cost recorded in Stage 5Q-6 and accepted then: a re-derived audit of 2026-08-24
now reads every window as pre-start. **The eight audit records written during the day remain
the truth for that day** — the file still holds 8 rows and was not touched.

The audit did not turn a restart into a false FAIL. It said what it could and could not judge,
and why.

---

## Tests

**213 passed** across nine suites (5R-0, 5Q-9, 5Q-8, 5Q-5, 5Q-4, 5N, ops-status-mode,
schedule-status-track1, ops). 5R-0 mutations: **8 red, 0 green**. `test_event_playback.py` not
run.

Two tests failed first and both were **my own tests coupling to things that move**, not
production defects:

1. **`test_7b` pinned the full `sleeve_identity` hash.** It went red the moment the repair
   appended bars — correctly, because `data_source_identity` is a sha256 of the parquet and the
   entire point of it being in the hash is that it moves when the file does. A full-hash pin
   therefore expires every trading day. Rewritten to pin the **strategy half** (content-hash
   fields normalised to a constant), plus a companion `test_7c` proving the data pin still
   reaches the hash — so the normalisation cannot quietly turn 7b into a test that would pass
   on a route reading the wrong file. This is the same defect I criticised in Stage 2's log
   anchor, in a test I had written the day before.

2. **`monitor/test_schedule_status_track1` read the real scheduler's start time.**
   `get_schedule_status` uses `started_at` to decide whether a slot is judgeable at all — a
   slot that fell before the process existed is pre-start, not overdue. Correct production
   behaviour, and the same rule the Track 1 audit applies. But it meant every test in that file
   depended on when the machine was last restarted. With the old 09:25 start,
   `TRACK1_STRESS_1035` was overdue; after tonight's 23:29 restart it is pre-start, and a test
   about lateness reddened for a reason that had nothing to do with lateness. Verified by
   patching three different start instants and watching the result flip. Now pinned by an
   autouse fixture.

**And one correction to a claim I made in the Stage 5R-0 report.** I wrote that the end-of-run
`IN-PROGRESS FINAL MINUTES NOT STORED` block existed; it did not. The `str.replace` that was
supposed to add it silently matched nothing — a heredoc had mangled the doubled backslashes in
the pattern — and I printed "patched" without asserting the replacement had applied. The
per-instrument `final-bar check` log line *was* real and is what the operator saw tonight. The
summary block is now genuinely present, added with an assertion. The 5R-0 report's header date
was also wrong by a day and has been corrected in place.

---

## Files

**Production, this stage**

```text
global_index/update_ibkr_daily.py   the end-of-run dropped-tail summary block (5R-0's, finally applied)
```

**Production data, deliberately, with approval**

```text
data/cache/futures/NQ_continuous_1m_8y.parquet    boundary 00:20 repaired, +185 closed bars
data/cache/futures/YM_continuous_1m_8y.parquet    boundary 00:21 repaired, +184 closed bars
data/cache/futures/RTY_continuous_1m_8y.parquet   boundary 00:21 repaired, +184 closed bars
  each snapshotted to *.pre5q5-20260825T03…Z.bak and verified by re-reading
```

**Tests**

```text
scratch/test_track1_stage5r0_boundary_tail_20260824.py   test_7b rewritten, test_7c added
monitor/test_schedule_status_track1_20260823.py          autouse fixture pinning started_at
```

No strategy rule, identity field, sizing basis, cap, overlap guard or order gate changed.
`live_positions.json`, `live_positions.track1.json` and `replay_checkpoint.track1.json` do not
exist, so nothing durable was disturbed.

---

## What happens next, and when

| ET | what |
|---|---|
| **01:10–02:55** | **`global_nkd` — the next judgeable window.** 14:10–15:55 JST, MNKD bars fetched as NKD, orders would route to MNK but B1 blocks them |
| 09:31 | `MAX_HOLD_EXIT` |
| 10:00 | `roska4_calm` one-shot |
| 10:35–12:30 | `roska4_stress` |
| 13:45 | pre-flight — first run with `--repair-boundary` **and** 5R-0 live |
| 14:05–15:55 | `roska4_swing` |
| 16:20 | `spy_refresh_pm` — the post-close SPY refresh that makes Wednesday morning's freshness pass |

**What to check in the morning.** The 13:45 log should carry a `final-bar check` line per
instrument and, because it runs while the market trades, an `IN-PROGRESS FINAL MINUTES NOT
STORED` block. `--repair-boundary` should find **nothing to repair** — if it reports a
replacement, something wrote a partial bar and that is worth stopping for.

And the morning windows should now be judgeable on their data: the three bars that would have
refused them are gone.

```powershell
python -m global_index.track1_shadow_audit --latest --all --dry-run
```
