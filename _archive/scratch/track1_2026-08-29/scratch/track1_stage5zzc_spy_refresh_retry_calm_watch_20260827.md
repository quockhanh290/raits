# Stage 5ZZC — a ladder, and the measurement that stopped it becoming an alarm nobody reads

**2026-08-27, ET 06:10–06:30.** Part A and B built and tested. **Part C is PENDING** — it is
06:24 ET and the phases run at 09:32 and 10:02. No orders · no confirmation file · **nothing
restarted** · no runtime trading file touched · **production `spy_daily_live.csv` not touched by
this stage**.

---

## Verdict

| | |
|---|---|
| `spy_daily_now_covers_required_day` | **YES** — `covers_required_day last=2026-08-26 required=2026-08-26` |
| `retry_schedule_built` | **YES** — 16:20 primary, 16:45 and 17:15 retries |
| `scheduler_restart_required` | **YES** — the running process started 04:08 ET and has the old single job |
| `calm_decide_observed` | **NO — PENDING**, 09:32 ET is 3h08m away |
| `calm_observe_observed` | **NO — PENDING**, 10:02 ET |
| `orders_possible` | **false**, blockers unchanged |
| `runtime_files_touched` | **NO** |
| `production_spy_csv_touched_by_stage` | **NO** — md5 `80f06253…` unchanged; the operator's manual refresh landed before this stage began |
| `next_action` | watch 09:32 and 10:02, then restart in the **12:40–13:45 ET** window |

---

## Part A — the ladder

### The measurement that shaped it, taken before any of it was written

A retry with nothing to do — the **successful** case, the one that happens on every good day —
**exits 1**:

```text
EXIT (already up-to-date, --verify-strict, coverage satisfied) = 1
  spy_daily.csv: already up-to-date
  regime verification: UNKNOWN (no_snapshot): the series already ends at 2026-08-27,
                       so nothing was fetched and no snapshot comparison was made
  FAILING: the regime labels could not be verified. This is not 'no drift' — nothing was proved.
```

The verification result is honest: nothing was fetched, so nothing could be compared, and that is
not a PASS. Strict mode fails on it — correctly, for the run it was written for.

But two retries a day, each reporting **FAILED on every day that went well**, is an alarm that
fires when nothing is wrong. This project's own record says what happens to those: people learn
to ignore them, and then the one real firing goes unread too. Building the ladder without noticing
this would have produced a worse system than the one it was fixing.

So a retry asks first and works second. `--skip-if-covered` short-circuits before the fetch,
before the API key is even used — proven with a deliberately invalid key:

```text
$ update_spy_csv ... --verify-strict --skip-if-covered --require-through 2026-08-26 \
                     --api-key NOT_A_REAL_KEY_zzz
EXIT = 0
coverage: covers_required_day — the series covers 2026-08-26
nothing to do: the day this run was sent for is already in the series.
```

It never reached the provider. A retry that is not needed costs nothing and cannot fail.

**Only the retries skip.** The 16:20 run does the verification even when the day is already
there, because checking the labels is part of what that run is for. A retry has nothing to verify
about a file it will not touch.

### The three rungs, and the argv they build

```text
SPY_REFRESH_PM     16:20 ET  --csv spy_daily_live.csv --verify-strict --require-through <today>
SPY_REFRESH_PM_R1  16:45 ET  ... --require-through <today> --skip-if-covered
SPY_REFRESH_PM_R2  17:15 ET  ... --require-through <today> --skip-if-covered
```

Read back from real scheduler construction with the launcher replaced. No rung carries
`--allow-orders`, and neither does any of the 71 Track 1 slots.

**Only the post-close ladder asks for day D.** No morning Track 1 slot fetches SPY; they read the
file, and the freshness gate refuses if it is short. That separation is unchanged.

### Four outcomes, four messages

The child now answers with three different noes and the wrapper reads the actual exit code rather
than a yes/no:

```text
16:20 lands it            OK — the daily series now covers <today>
a retry lands it          RECOVERED — <day> was missing when the earlier attempt ran and is
                          there now. The 16:20 refresh is running before the provider is ready;
                          if this keeps happening, move it later rather than relying on the ladder.
a retry has nothing to do nothing to do — <day> was already in the series when this rung ran
a middle rung is short    the daily series still ends on X, not Y ... Next attempt at 17:15 ET.
the LAST rung is short    LAST ATTEMPT — ... Tomorrow's Track 1 slots that run before the 13:45
                          pre-flight — the overnight NKD window and BOTH Calm phases — will
                          refuse on `regime_csv: stale`.
the run itself broke      FAILED, with drift / unverifiable / other told apart
```

The RECOVERED message is deliberately a warning rather than an info line. A ladder that quietly
rescues the same failure every day is a schedule that wants moving, not a schedule that is
working.

The last rung is the loud one because it is the one with no successor. That is held by a test
which mutates the successor map and demands the loud message disappear.

### A hole I made and closed in the same hour

`_run` reports a dry run as success without executing anything, so the series on disk is whatever
it already was — and my first version of the rung then judged itself against that and logged a
**FAILED refresh for a command that was never sent**. A false alarm invented by the mode whose
whole purpose is to avoid side effects. Caught by writing the test for it.

### Job inventory, measured

```text
                 before   after   spy rungs
legacy only        61       63        3
transitional      131      133        3
track1-only       102      104        3
```

Exactly +2 in every mode. The rungs are shared infrastructure, so they appear in the legacy
schedule too — the daily regime file is not Track 1's private input.

## Part B — status and dashboard

`ops.py status`, on the live system, right now:

```text
spy_daily_coverage=covers_required_day last=2026-08-26 required=2026-08-26
                   calendar=raits.live.trading_calendar
```

The dashboard gained its own row, deliberately apart from the audit verdicts:

```text
SPY daily     SPY daily file covers 2026-08-26
```

and when short:

```text
SPY daily     SPY daily file is missing 2026-08-26 — it ends on 2026-08-25. This is a stale
              daily-context warning, not a slot failure: sleeves that run before the 13:45
              pre-flight will refuse until the refresh is re-run
```

**It is not folded into the slot verdict, and that is the point.** On 2026-08-27 the overnight
window's own audit reads:

```text
global_nkd  PASS  22/22 slots observed  reasons: all_slots_observed_no_action  judgeable: true
```

while its per-slot diagnostics carried `freshness_allow=false`. Two true facts about different
things. Rendering the second as the first would send somebody to inspect a window that worked.
A test holds the wording to that, and a mutation that makes the block say "NKD failed" turns it
red.

The bidirectional fact pin caught the new row the moment it was added, exactly as it did for the
last one — it is now declared.

## Part C — PENDING, and not pretended otherwise

It is **06:24 ET**. The phases have not run.

**Recorded before the watch, so the after has something to be compared against:**

```text
recorded 2026-08-27 06:24:12 ET
  scheduler_pids=[5856] source=process_table
  spy_daily_coverage=covers_required_day last=2026-08-26 required=2026-08-26
  track1_slot_table=fresh source_slots=71 registered_slots=71
  track1_blocking=['B1_broker_account_or_legacy_retirement','PAPER_SHADOW_EVIDENCE']
  orders_possible=False   confirmation=False   track1_orders_approved=False

  track1_runtime/orders            ABSENT
  track1_runtime/shadow_intent     ABSENT      <- the phases have never run
  trade_log.track1.jsonl           08-26 00:20:01 ET   (0 rows)
  live_positions.track1.json       08-27 02:55:42 ET   (the NKD window close)
  replay_checkpoint.track1.json    08-27 02:55:42 ET
  track1_go_live_confirmation.json ABSENT

  spy_daily_live.csv               2026-08-26,766.08   md5 80f06253…
```

### The exact watch commands

After **09:32 ET**:

```powershell
Select-String -Path scheduler_0827.log -Pattern "TRACK1_CALM_DECIDE_0932" | Select-Object -Last 6
Get-Content global_index\track1_runtime\shadow_intent\shadow_intent_20260827.jsonl
python -c "from global_index import track1_shadow_intent as si; import json; rows=si.read_day('.','2026-08-27'); print(json.dumps(si.classify_day(rows),indent=2)); [print(r['phase'],r['status'],r['reason_code']) for r in rows]"
```

After **10:02 ET**, the same with `TRACK1_CALM_OBSERVE_1002`.

### What DECIDE must show

- an intent row if the setup exists, or an explicit `NO_SETUP / no_candidate` row if not —
  **silence is the one outcome that is not allowed**
- **no `entry_reference_price` and no `planned_stop`** — neither exists at half past nine
- freshness passed, or an explicit `REFUSED / freshness_refused` row
- `track1_runtime/orders` still absent, trade log still 0 rows, book and checkpoint unmoved

### What OBSERVE must show

- it reads the DECIDE rows for the same day, and refuses `no_decide_row_for_this_day` if there
  are none
- `entry_reference_price` equal to the real 10:00 open, and `planned_stop` computed **from** it
- still no orders

### And how to tell a real no-setup from a data problem

The distinction is in the row, not in the reader's judgement:

| row | means |
|---|---|
| `NO_SETUP / no_candidate` | the rule looked and said nothing today |
| `REFUSED / freshness_refused` | the inputs were stale; the rule was never asked |
| `REFUSED / gate_refused` | the causal gate refused; the rule was never asked |
| no rows at all | the phase did not run — the only outcome that is not evidence |

Today the daily file covers the required day, so a freshness refusal would be a surprise worth
investigating rather than the expected outcome it would have been before the manual refresh.

## The restart

**Required** for the ladder to become live. The running scheduler (PID 5856) started at 04:08 ET
and holds the old single-job schedule; the code is not the process.

Nothing is worse in the meantime — today's 16:20 refresh will behave exactly as it did
yesterday, and `status` will say whether it left the file short.

**Window: 12:40–13:45 ET**, a measured 65-minute gap after the Stress window's audit and before
the pre-flight — and after both Calm phases have been observed, which is the point of waiting for
it. The next-best gaps are 13:45→14:05 (20 min) and 10:20→10:35 (15 min).

```powershell
python monitor\ops.py restart --scheduler --track1-only-shadow --yes
```

Verified rather than assumed: `--shadow-resume` is the default on that path, so the new argv is
byte-identical to what PID 5856 is running today. **Not run — that is the operator's call.**

## Tests

**22** in `scratch/test_track1_stage5zzc_spy_retry_ladder_20260827.py`, no network, nothing
written outside `tmp_path`. Four mutations, all red: the retries losing their skip flag · a
covered retry reaching the provider · the skip flag passing a genuinely missing day · the last
rung claiming a successor so nothing says the day is lost · daily context rendered as a window
failure.

Two of yesterday's tests went red and were **rescoped, not loosened**: they asserted what the
16:20 job does, and the job is now a one-line delegator to a shared body. The property never
belonged to the decorated function; widened to the body, it now covers all three rungs at once.

Suites after: **185 passed** across the Track 1 and ops set, **220 passed** across the dashboard
contract and backend.
