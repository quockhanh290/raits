# `ops.py status` reported the wrong Track 1 mode — root cause and fix

**2026-08-24 ·** scheduler **not** restarted or stopped (pid 44904, unchanged) · no backend
started · no IBKR connection · no order · no `STOP_TRADING`, `STOP_TRADING.track1` or
confirmation file created or removed · no commit · **no route, scheduler or start/restart
logic changed**.

---

## Root cause: a rename boundary, one field wide

```
PowerShell query        selects   CommandLine
scan_processes          maps it → dataclass attribute `command`
scheduler_processes     emits   → dicts keyed `command`
track1_status           asked for CommandLine        ← the name on the FAR side
```

`p.get("CommandLine")` returned `None` → `""` → an empty string contains no flags → parsed as
legacy-only.

**Nothing raised, because searching an empty string is a perfectly successful operation.**
Every field was individually right; the seam between two names for one thing was not.

Measured before the fix, against the real running process:

```
pid 44904   started 2026-08-24 02:08:42
argv        pythonw.exe -m global_index.run_scheduler --port 4002 --shadow-resume --track1-only-shadow

what track1_status read:  ''            ← the whole bug
printed:                  track1_mode=legacy-only
                          track1_safety_routes=['legacy']
```

## Why no test caught it

The Stage 5K status test builds its fixture with the key **`CommandLine`** — the key the
*buggy reader* wanted, not the key the *producer* emits. **The test and the bug agreed with
each other, and production disagreed with both.** A fixture shaped to match the reader can
only ever confirm the reader.

So the new suite drives the **real `scheduler_processes()` shape** first, and keeps the old
shape working as an explicit, tested fallback rather than an accident.

## The fix

`monitor/ops.py` — status reading only:

* **`process_command(proc)`** — reads `command`, falls back to `CommandLine`. One home for the
  key, with the rename boundary written down where the next reader will hit it.
* **`scheduler_command_lines(procs=None)`** — the single joiner, so a second consumer cannot
  reintroduce the same mistake independently.
* `track1_status()` calls it.
* `typing` import extended with `Mapping`, `Sequence` (the annotations are evaluated at
  runtime; without this the module failed to import).

### A second wrong answer in the same payload

`scheduler_track1_shadow` answered *"is this literal flag on the argv"*. But `make_scheduler`
sets `track1_shadow = True` whenever `track1_only` is set — so for a scheduler demonstrably
running all 70 Track 1 slots, that field reported **False**. Same family, one field over.

It now answers *"are the Track 1 slots registered"*, and the literal flag stays available as
`scheduler_track1_shadow_flag`. (`--track1-only-shadow` does not contain `--track1-shadow` as a
substring — checked — so the two flag tests are genuinely independent and the OR is the mode
implication, not a string workaround.)

## Result

```
track1_mode=track1-only-shadow
track1_safety_routes=['legacy', 'track1']  (legacy safety watches live_positions.json;
                                            track1 safety watches live_positions.track1.json
                                            with its own max-hold marker)
track1_window_coverage=...\track1_runtime\window_coverage exists=True
track1_slot_timing=...\track1_runtime\slot_timing exists=True
track1_stop_trading=False confirmation=False track1_orders_approved=False
track1_blocking=['B1_broker_account_or_legacy_retirement'] orders_possible=False
scheduler_pids=[44904]
```

---

## A second finding, and it is mine

`global_index/track1_runtime/` was created at **00:28:17** — *before* the operator's scheduler
start at 02:08:42. It was created by **my own Stage 5O mutation harness**: the D4 mutation
deliberately neuters `cmd_up`'s both-flags refusal, and the un-refused `cmd_up` then ran
`TRACK1_LEDGER_DIR.mkdir(parents=True)` against the real tree.

The lesson generalises: **a test whose safety depends on the code under test taking an early
return leaks the day someone deliberately removes that return.** The refusal was the only thing
standing between that test and the real filesystem.

**State:** two empty directories. No test wrote evidence into them.

**Not deleted, deliberately.** The running track1-only scheduler now depends on them —
`window_ledger` refuses when its directory is not a directory, so removing them would make
every slot hard-refuse `ledger_not_configured` and destroy the live session's evidence
collection. Deleting to tidy up would cost more than the untidiness.

**Fixed at source:** the `cmd_up` test now redirects both runtime dirs to `tmp_path`, so even a
mutated `cmd_up` cannot reach the real ones.

**And one guard was legitimately expired:** the Stage 5K assertion `not
Path("global_index/track1_runtime").exists()` was written when no shadow session had ever run.
Once an operator starts one, that directory *should* exist — the assertion would fail on every
machine that has ever run the thing this project is building. Re-pointed at what it is actually
about; attribution of "a test wrote here" belongs to the `conftest` tripwire, which listens
per-operation and can name the culprit.

## Tests

| | Result |
|---|---|
| `test_track1_ops_status_mode_20260824.py` (new) | **13 passed** |
| Mutation check | **3 / 3 detected**, `ops.py` restored byte-for-byte |
| Sweep: status + 5P text + 5K + 5P readiness + 5O + 5M-D + `test_ops` + dashboard backend + mirror | **367 passed** |

`global_index/test_event_playback.py` **not run** — known hang.

**M1 reproduces the original bug exactly** (read `CommandLine` only) and the new test reds —
so this suite would have caught it. M2 drops the fallback; M3 reverts the second field.

## No side effects

Scheduler **pid 44904 unchanged**, still the process started at 02:08:42 with the correct
argv — nothing was restarted or stopped. No backend started, no IBKR connection, no order, no
switch or confirmation file, no commit. The only production change is how status *reads* a
dictionary key.
