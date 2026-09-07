# Stage 5C — should the shadow scheduler be started?

**2026-08-23 · read-only · no scheduler started or stopped, no IBKR connection, no order, no
dashboard write, no `STOP_TRADING`, no confirmation file, no commit.**

---

## Verdict: **NOT_READY_FOR_SHADOW_START**

Not because the state is wrong — the state is exactly what Stage 5B described. Because
**starting the shadow scheduler cannot produce the evidence it would be started to produce.**

Each Track 1 slot runs `run_live_day_track1` with only `--regime-csv`, so it takes the
defaults: `--source replay --window vault2026`. It **replays a historical window**, twenty-five
times a trading day. And the two functions that would record the evidence are never called:

- `record_window_observation` — defined at `run_live_day_track1.py:257`, **zero call sites**
- `track1_bootstrap.write` — **zero call sites** anywhere in `global_index/`

So no `window_coverage_*.jsonl` and no Track 1 checkpoint can be written by that path.
**Preconditions 5 and 6 cannot turn green by starting the scheduler.**

I verified this by execution, not by reading: I ran the exact argv a slot builds. It reported
`mode: shadow`, `source: replay window: vault2026`, `send_order calls: 0`, left the legacy
files byte-identical, and produced no coverage file. `run_shadow` says so about itself, in its
own output field — `window_ledger: "not driven: a replay cannot testify to observation"`.

### A correction I owe you

**Stage 5 concluded, and Stage 5B repeated, that starting the shadow scheduler is what moves
preconditions 5 and 6** — I wrote "starting is what fixes them", and put it in the runbook.
That was reasoned from the runbook's own framing and never checked against the call sites. It
is wrong. The wiring gap has to be closed first, and section 2 of the runbook now states the
opposite of what is true.

---

## 1. Measured state

| | value |
|---|---|
| scheduler running | **False** (0 processes; probe returned a real count, not a failure) |
| `runner.pid` | absent |
| `STOP_TRADING` | **absent** |
| `STOP_TRADING.track1` | absent |
| `track1_go_live_confirmation.json` | **absent** |
| `TRACK1_ORDERS_APPROVED` | **unset** |
| `blocking()` | `['B1_broker_account_or_legacy_retirement']` |
| `self_check()` | `[]` |
| orders possible | **False** |
| live-frame wiring | released |
| legacy `live_positions.json` | `positions: []`, `cur_day 2026-08-21` |
| window coverage files | **0** |
| Track 1 checkpoint | absent (`file_absent`) |

Clocks at the time of measurement: machine 08:23 Calgary, **10:23 ET Sunday 2026-08-23**.

---

## 2. The sequence, re-validated against the code

The runbook still says `STOP_TRADING` → start → watch, and that ordering is still necessary.
Re-measured rather than quoted:

| | jobs | Track 1 slots | legacy entry slots |
|---|---|---|---|
| shadow OFF | 60 | 0 | 23 |
| shadow ON | 84 | 25 | **23** |

Shadow adds 25 and removes exactly one (`stop_repair_1220`). **Every legacy entry slot
survives**, so a start without the kill switch resumes legacy entries.

Track 1 slots are shadow-only: the argv is `python -m global_index.run_live_day_track1
--regime-csv <csv>` — no `--allow-orders`, no broker port — and the order gate refuses anyway
while B1 is open and the environment approval is unset.

### One thing about starting that the runbook does not say

`_catch_up_maxhold` runs **before** `sched.start()`. On a weekday after 09:31 ET it immediately
runs the max-hold exit, which reads the **broker**. So a weekday start connects to IBKR at once,
and `STOP_TRADING` does not prevent it — D5 clears entries only, exits keep running, which is
the correct design during a drain but is not what "shadow mode" sounds like.

Today is Sunday ET, so it would not fire now. The Sunday 18:30 ET stop-repair sweep would.

---

## 3. What has to be built before a shadow start is worth doing

Five gaps, in the order they bite. None of them is a decision; all are code.

1. **Nothing calls `record_window_observation`.** It exists, it is tested, and no entry point
   reaches it. This is the same shape as the D5 kill switch that "stopped nothing while
   STATUS.md counted it among the grep-verified safety mechanisms" — a mechanism with code,
   docs and tests, wired to nothing.
2. **The window ledger is off unless `RAITS_WINDOW_LEDGER_DIR` is set.** Its own header says
   `Unset -> off`. Even once a caller exists, an unset variable means the writes are skipped
   silently, and a day with no records is indistinguishable from a day nobody watched — which
   is exactly what the ledger exists to distinguish.
3. **Nothing writes the Track 1 checkpoint.** `track1_bootstrap.write` has no call sites, so
   precondition 6 has no producer.
4. **The scheduler slot replays history.** It passes no `--source`, so every slot re-runs
   vault2026. Twenty-five identical replays a day is not observation of today.
5. **The live source cannot produce candidates anyway.** `load_source("live").candidates()`
   raises. Even with `--source live` wired into the slot, there is nothing behind it yet — this
   is precondition 2b, still failing.

Gaps 1–3 are small and mechanical. Gaps 4–5 are the real work, and they are the same work
precondition 2b names: today's regime label, a cost object, Calm A's stop-risk sizing.

---

## 4. The shadow collection gate, for when it can run

Stated now so the target is fixed before anyone starts collecting against it.

**Minimum period.** Enough consecutive trading days that both windows are exercised repeatedly
— Calm A's single 10:00 decision and the Stress window's 24 slots from 10:35 to 12:30. Ten
trading days is the smallest period that gives ten independent Calm observations, which is the
scarcer of the two; fewer than that and one bad morning is a tenth of the evidence.

**Per day, all of these or the day does not count:**

- `window_coverage_YYYYMMDD.jsonl` exists and `window_ledger.status(...)` reports
  `outcome == "complete"` for **both** `roska4_calm` and `roska4_stress`.
- Every expected slot in each window is recorded — a window that opened and vanished is
  `unobserved`, not "in progress after the fact".
- **No scheduler stall inside either window.** A slot that skipped on the mutex, misfired, or
  ran past its grace marks the day **invalid** rather than partial. Track 1's slots hold their
  own lock, so a long slot starves the next one.
- **Zero legacy entries while `STOP_TRADING` is present.** If a legacy entry appears, the kill
  switch was not in place and the day's premise is void.
- **Orders blocked throughout** — `blocking()` still returns B1, no confirmation file appears,
  `TRACK1_ORDERS_APPROVED` stays unset.
- If telemetry is on, p95 slot runtime stays inside its target; a slot that regularly runs long
  is one that will eventually collide with the next.

**At the end of the period:**

- `track1_bootstrap.accepts(...)` returns `Resumed`, not a `Refusal`, for every checkpointed
  sleeve and instrument.
- Coverage is `complete` on **every** trading day of the period, not most of them. A gate that
  tolerates gaps is measuring something other than reliability.

---

## 5. Operator checklist

**Nothing below was executed by this stage.** Read-only items are marked **[R]** and are safe on
a live machine at any time. Operational items are marked **[OP]** and change the running system.

Given the verdict, the `[OP]` items are written for completeness and for the day the wiring gaps
are closed — **not as a recommendation to run them today**.

### Before anything — one command **[R]**

```powershell
python scratch/track1_stage5c_shadow_readiness_probe_20260823.py
```

It re-measures everything in section 1 and prints `SAFE TO START SHADOW`. It starts nothing,
connects to nothing, and writes nothing. Prefer it over this document: a report goes stale, a
probe does not.

### a. Create the legacy kill switch **[OP]**

```powershell
if (-not (Test-Path STOP_TRADING)) { New-Item -ItemType File STOP_TRADING }
```

Do this **before** any scheduler start, not before the final swap. It freezes legacy entries
and leaves legacy exits, stop repairs and max-hold running — which is what you want during a
drain.

### b. Start the scheduler in Track 1 shadow mode **[OP]**

```powershell
python -m global_index.run_scheduler --track1-shadow
```

Add `--assume-preflight-ok` only after a manual `update_ibkr_daily` + `update_spy_csv`, and know
that on a weekday after 09:31 ET the start immediately runs a max-hold pass **against the
broker**.

### c. Confirm the scheduler is running **[R]**

```powershell
@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run_scheduler*' }).Count
```

Expect `1`. `0` means it is not up; anything above `1` is the failure mode that once cost six
entry slots to a client-id collision. The startup banner also lists the job count — **84** with
shadow on, 60 with it off.

### d. Confirm legacy entries are frozen **[R]**

```powershell
Select-String -Path (Get-ChildItem live_day_*.log | Sort-Object LastWriteTime | Select-Object -Last 1) -Pattern "D5: STOP_FILE present"
```

One match per legacy slot run. No match means the kill switch is not being seen.

### e. Confirm the Track 1 slots are registered **[R]**

```powershell
python -c "import logging; logging.disable(logging.CRITICAL); from global_index import run_scheduler as rs; j=[x.id for x in rs.make_scheduler(port=4002, dry_run=True, track1_shadow=True).get_jobs()]; t=[i for i in j if i.startswith('track1_')]; print(len(j), len(t), min(t), max(t))"
```

Expect `84 25 track1_calm_1000 track1_stress_1230`. This builds a scheduler object and throws it
away — it starts nothing.

### f. Inspect window coverage **[R]**

```powershell
Get-ChildItem -Recurse -Filter "window_coverage_*.jsonl" | Select-Object FullName, Length, LastWriteTime
```

**Today this returns nothing, and will keep returning nothing until gap 1 and gap 2 above are
closed.** The directory is chosen by `RAITS_WINDOW_LEDGER_DIR`; unset means the ledger is off.

### g. Inspect the Track 1 checkpoint **[R]**

```powershell
python -c "import sys; sys.path.insert(0,'.'); import importlib; p=importlib.import_module('scratch.track1_stage5c_shadow_readiness_probe_20260823'); print(p.checkpoint_state())"
```

Expect `{'present': False, 'accepted': False, 'code': 'file_absent'}` today.

### h. Verify orders remain impossible **[R]**

```powershell
python -m global_index.run_live_day_track1 --allow-orders --window vault2026
```

Expect exit code **2**, `mode: armed_but_refused`, and exactly two reasons: `B1_broker_account_or_legacy_retirement`
and the unset `TRACK1_ORDERS_APPROVED`. This asks for orders and is refused; it sends nothing.

```powershell
python -c "import sys; sys.path.insert(0,'.'); from global_index import track1_gates as g; print([b.id for b in g.blocking()], g.may_enable_orders(g.load_confirmations()[0])[0])"
```

Expect `['B1_broker_account_or_legacy_retirement'] False`.

---

## 6. Tests

| suite | result |
|---|---|
| Stage 5C shadow readiness (new) | **11 passed** |
| Stage 5B runbook fix | **22 passed** |

The Stage 5C suite pins the probe against the filesystem, requires its process check to be able
to answer "I do not know" rather than folding a failed query into "nothing is running", proves
the verdict can turn green (by creating `STOP_TRADING` inside pytest's temp directory and
pointing the probe there — the repo root is asserted untouched afterwards), re-measures the 23
legacy entry slots, and reads the slot's argv out of the shipped scheduler source to confirm no
`--allow-orders` and no port.

`global_index/test_event_playback.py` was not run.

---

## 7. Recommended next action

**Do not start the shadow scheduler yet.** It would resume nothing useful and collect nothing.

1. Answer the still-open question from Stage 5: **why is the scheduler down?** If accidental,
   the system has been silently not trading since 2026-08-21.
2. Close the three mechanical wiring gaps — call `record_window_observation` from the live
   slot path, require `RAITS_WINDOW_LEDGER_DIR` rather than defaulting to silence, and write
   the Track 1 checkpoint at the end of a real slot.
3. Then decide what a Track 1 slot should actually *do* on a live day, since today it replays
   history. That is the same work precondition 2b names.
4. Correct section 2 of the runbook, which currently says preconditions 5 and 6 turn green by
   starting — measured here as false.
5. Only then: `STOP_TRADING`, start, watch, and collect against the gate in section 4.

**Not claimed:** that Track 1 is ready to trade, that legacy is flat at the broker, or that any
of the wiring gaps above is merely cosmetic.
