# Legacy → Track 1: what still has to be promoted before legacy can be retired

**2026-08-23 · read-only audit.** No service started or stopped, no IBKR connection, no order,
no dashboard runtime write, no `STOP_TRADING`, no `STOP_TRADING.track1`, no confirmation file,
no production code edited, no commit.

---

## Verdict: **NOT_READY_BLOCKERS_FOUND**

Stage 5K ended with a true statement — an operator can now start the scheduler in Track 1
shadow mode — and that statement is being read as something it does not say.

**Track 1 shadow today measures two sleeves out of four.**

Calm and Stress have Track 1 slots. Normal-R4 and NKD do not. Their decisions are still made
by legacy jobs. And the switch an operator would place to stop legacy from trading —
`STOP_TRADING` at the repo root — is read by exactly those legacy jobs. So the operator has
two choices, and neither one produces the combined route:

- **Leave `STOP_TRADING` off:** legacy trades the 14:05–15:55 window and the overnight NKD
  slots. Track 1 shadows Calm and Stress only. The book is legacy's.
- **Place `STOP_TRADING`:** legacy stops — and Normal-R4 and NKD stop with it, because nothing
  else decides them. Track 1 still shadows Calm and Stress only, now against an emptier book.

A shadow period run either way is evidence about half the route. It is not evidence that the
combined, backtested Track 1 route runs.

---

## What I actually read and ran

Production files read in full or in the relevant region: `global_index/run_scheduler.py`
(job registry, `_track1_body`, `_live_day_body`, `_run`), `global_index/run_live_day.py`
(legacy cluster dispatch, swing parameters, NKD parameters), `global_index/run_live_day_track1.py`
(slot path, checkpoint, decision mode), `global_index/track1_params.py` (sleeve instruments,
quantities, caps, family limits), `global_index/track1_normal_r4.py` (`NormalR4Params`),
`global_index/track1_freshness.py` (`required_data_through`), `global_index/track1_signal_layer.py`
(guard construction), `monitor/ops.py` (`_env`, `start_scheduler`, `track1_shadow_blockers`,
`track1_status`), and `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md`.

Measurements run: the job registry built twice, once with the Track 1 flag off and once on, and
the two job sets differenced by id and trigger time; every job body parsed for the argv it
would actually spawn; `NormalR4Params()` and the legacy swing constants printed side by side;
`track1_freshness.required_data_through()` evaluated at each Track 1 slot time; and the on-disk
state files listed by presence.

Nothing here started a process, opened a socket, or wrote outside `scratch/`.

---

## 1. The job inventory, and who owns each job

Flag off: **60 jobs.** Flag on: **84 jobs.** The Track 1 flag adds **25** jobs and removes
exactly one (`stop_repair_1220`, displaced by a Track 1 slot at the same minute).

| Group | Count | What it is |
|---|---|---|
| Track 1 slots | 25 | `track1_calm_1000` at 10:00, plus 24 Stress slots every five minutes from 10:35 to 12:30 |
| Legacy entry | 23 | `live_day*`, 14:05 through 15:55 — this is the legacy swing window |
| Overnight and other | 22 | the NKD night slots from 01:10, plus assorted |
| Stop repair | 10 | safety |
| Max-hold exit | 1 | `maxhold_exit` at 09:31 |
| Pre-flight data | 1 | `preflight` at 13:45 |
| Heartbeat | 1 | infrastructure |
| Session report | 1 | reporting |

Classified by what has to happen to each one before legacy retires:

- **Shared infrastructure, keep as-is:** heartbeat, the 13:45 pre-flight, the session report.
  None of these decides a trade; both routes need them.
- **Legacy strategy, retire eventually:** the 23 `live_day` entry slots and the NKD night
  slots. These are the jobs that make trading decisions today.
- **Already owned by Track 1:** the Calm slot and the 24 Stress slots.
- **Owned by Track 1 in the backtest but missing from the scheduler:** Normal-R4 (14:05–15:55)
  and NKD (overnight). **This is the gap.**
- **Safety, needs to become route-aware:** the ten stop-repair jobs and the max-hold exit.
  They exist, they work, and they are pointed at the legacy book by name.

---

## 2. Strategy ownership — sleeve by sleeve

| Sleeve | Decided by | Book | Stop | Matches the Track 1 backtest? |
|---|---|---|---|---|
| Normal-R4 | **legacy** `run_live_day --clusters all`, 14:05–15:55 | `live_positions.json` | legacy chandelier, ratchet on | **No** |
| NKD | **legacy** `run_live_day --clusters nkd`, night slots | `live_positions.json` | chandelier 2.5, five-day max hold | **Yes** (strategy only) |
| Calm | Track 1 slot at 10:00 | window ledger + route checkpoint | ATR-based disaster stop | Yes |
| Stress | Track 1 slots 10:35–12:30 | window ledger + route checkpoint | prior high plus a pad, 1.5 R target | Yes |

Two of these rows deserve more than a checkmark.

**Normal-R4 is not a wiring job — it is a different strategy.** The legacy swing runs a
30-period trend filter with a chandelier trailing stop that ratchets. Track 1's Normal-R4 runs
a 50-period filter, a stop anchored at entry at twice the daily range, no ratchet, and arms the
stop only after the position survives into the next session at 14:05. The Track 1 module exists
and reproduces its backtest rows exactly; what it does not have is a slot. Running the legacy
job and calling the result "Track 1's Normal sleeve" would be false, and the code already knows
it: `run_live_day_track1.py` documents the checkpoint parameter mismatch between the two as the
*correct* outcome, not a defect to paper over.

**NKD genuinely does match.** Ten-period filter, chandelier at 2.5, five-day max hold, regime
labels lagged one day — the same numbers on both sides. So promoting NKD is an ownership and
plumbing job, not a strategy port. That makes it the cheaper of the two promotions, and it
should not be confused with the harder one.

---

## 3. Pre-flight

There is one pre-flight job, at 13:45 ET. It refreshes the daily instrument data and the SPY
regime file, and writes a small state file recording that it ran.

Track 1 depends on this. Its freshness rule encodes the same contract: before 13:45, the most
recent data a route may claim is the previous business day's.

Every Track 1 slot that exists today — Calm at 10:00, Stress from 10:35 to 12:30 — fires
**before** 13:45. So they all decide on the previous day's stored bars plus whatever of today's
live bars the provider supplies intraday. **That is the designed contract, not a defect**, and
I want it stated plainly rather than discovered later and mistaken for one. A pre-market data
refresh would change the contract; adding one is a decision, not a fix.

What does need doing: the pre-flight job currently sits inside the legacy job set. When legacy
retires, this job must survive. Promote it to a shared job owned by neither route.

---

## 4. State and checkpoints

| Kind | Files |
|---|---|
| Legacy only | the legacy positions file, the legacy replay checkpoint, the runner pid file, the trade log, the dashboard live-state file |
| Track 1 only | the Track 1 positions file, the Track 1 replay checkpoint, the Track 1 pid file, `STOP_TRADING.track1`, and everything under the Track 1 runtime directory |
| Shared, must stay single | the pre-flight state file, the SPY regime file, the futures bar store |
| **Shared and dangerous** | the max-hold state file |

The max-hold state file is a single file recording "the max-hold sweep already ran today". Two
routes writing it would overwrite each other's marker, and the failure is silent: the second
route sees a marker it did not write, concludes the sweep already ran, and skips it. Positions
that should have been closed at the five-day limit stay open. This has to be split before both
routes run at once.

On disk right now: the legacy positions file, the legacy replay checkpoint, the pre-flight
state, and the max-hold state all exist. Every `.track1` file is absent, and so is the runner
pid file.

---

## 5. Safety gates

Three groups, and the distinction between them matters more than the list.

**Cannot be split per route, because the broker does not know about routes.** The broker/file
reconcile asks the account for its positions and gets the account's positions — unfiltered. The
account-level breaker watches account liquidation value. An orphaned working stop order carries
no route tag. These are properties of the *account*, and they are why one login is one book.

**Must become route-aware before both routes run.** The ten stop-repair jobs and the max-hold
exit are each launched with the legacy positions file named explicitly on the command line.
They will repair legacy stops and sweep legacy positions and be entirely blind to a Track 1
position sitting next to them.

**Already route-scoped inside Track 1.** Cluster and family caps, same-symbol suppression, the
Stress displacement rule, the window ledger, the route checkpoint. These work — but only for
sleeves the Track 1 slots actually decide, which today is two of four.

**Not yet ported at all:** stop arming (14:05 for the swing sleeve, 01:10 for NKD), contract
rollover, and the ordering rule that cancels a stop before a close.

---

## 6. Execution semantics vs the backtest

The caps and quantities are declared in Track 1's parameters — per-sleeve contract counts, a
per-sleeve exposure cap, and a family-wide gross and net limit. They are enforced by Track 1's
signal layer, which only the Track 1 slots reach.

Legacy enforces its own multi-cluster guard inside its own entry path.

So while Normal-R4 and NKD are decided by legacy, **the combined book is capped by legacy's
guard, not Track 1's**, and the two have never been reconciled against each other. This is
exactly the shape of divergence that has cost this project money before: two paths doing the
same job, no comparison between them, and both looking healthy in isolation.

Whichever route owns a sleeve must own its cap. Mixing them without a reconcile is how the
combined exposure ends up governed by neither of the two designs that were tested.

---

## 7. Dashboard and monitor

The ops layer can now start the scheduler in Track 1 shadow mode, with a fail-closed preflight
that refuses to start when its conditions are not met, and a status view that reports what the
Track 1 side is doing. The runtime directory for Track 1 evidence is separate from `scratch/`,
so ordinary scratch cleanup cannot destroy the evidence a gate depends on.

What the dashboard does **not** yet do is show a reader which sleeves are being decided by
which route. Today that answer is "Calm and Stress by Track 1, Normal and NKD by legacy", and
it is not visible anywhere on screen. Anyone reading the dashboard during a shadow period will
see Track 1 activity and legacy activity side by side with nothing saying that they cover
different sleeves. Add that before the first shadow period, or the first person to read it will
draw the same wrong conclusion this audit exists to prevent.

---

## 8. Staged plan to retire legacy

Each stage has a gate that can fail and a rollback that is one action.

| Stage | What it does | Gate that must pass | Rollback |
|---|---|---|---|
| **5L** Shared pre-flight | make the 13:45 job route-neutral | both routes read the same pre-flight state | rename the job back; the body is unchanged |
| **5M** Promote Normal-R4 | Track 1 slots covering 14:05–15:55, running the Track 1 rule | shadow rows for the swing window match the measured backtest day by day | drop the slots; legacy keeps running the window |
| **5N** Own NKD | Track 1 night slots; the strategy already matches | NKD shadow decisions match legacy's on the same nights | drop the slots |
| **5O** Route-aware safety | per-route stop repair and max-hold; split the max-hold state | a Track 1 position gets a stop repaired and a max-hold exit in a dry run | legacy paths untouched; the Track 1 pair is purely additive |
| **5P** Full shadow | all four sleeves shadowed together | complete window coverage every trading day, all four sleeves, checkpoint accepted | stop the Track 1 slots |
| **5Q** Retire legacy jobs | remove the legacy entry slots, keep shared infrastructure | the single-book constraint recorded as resolved; legacy flat at the broker; no orphan stop orders | restore the legacy slots from git |
| **5R** Paper, then live | arm Track 1 | the eight preconditions in the switch-over runbook | remove the confirmation file |

Note the ordering constraint that is easy to get wrong: **5O must come before 5P**, not after.
The moment both routes hold positions at once, the shared max-hold state file becomes a silent
failure, and a shadow period run before that split would be running with a known hole in the
safety net.

---

## 9. Blockers

| # | Blocker | Why it blocks | shadow / paper / live / retire |
|---|---|---|---|
| **L1** | Track 1's Normal-R4 has no slot, and legacy's swing is a different strategy | the 23 entry slots produce the legacy rule, not Track 1's. Track 1's largest sleeve has no live path at all | partial / yes / yes / **yes** |
| **L2** | `STOP_TRADING` freezes two of Track 1's four sleeves | the only switch that stops legacy also stops Normal-R4 and NKD, because legacy is what decides them | **yes** / yes / yes / yes |
| **L3** | Safety jobs are hard-wired to the legacy positions file | stop repair and max-hold cannot see a Track 1 position; the shared max-hold marker fails silently | partial / yes / yes / yes |
| **L4** | One broker login is one position book | reconcile, breaker, and orphan-stop detection are account-level and cannot be split | no / yes / yes / **yes** |
| **L5** | Track 1's caps are not applied to the legacy-run sleeves | the combined book is governed by legacy's guard; the two guards have never been reconciled | partial / yes / yes / yes |
| **L6** | Pre-flight is a legacy job that Track 1 depends on | retiring legacy naively takes the data refresh with it | no / no / yes / yes |
| **L7** | Morning Track 1 slots decide on previous-day data | **designed, not a defect** — recorded so it is not later mistaken for one | no / no / no / no |
| **L8** | The running scheduler predates all Track 1 work | it was started on 2026-08-20 and holds none of the Track 1 code; a restart is required, not a start | **yes** / yes / yes / yes |

Five of the eight block legacy retirement. Two block a meaningful shadow period. One (L7) is
documentation of an intentional contract and blocks nothing.

---

## Correction, added 2026-08-23 (Stage 5L): this audit DID have side effects

The no-side-effects statement at the top of this document is wrong, and Stage 5L found out how.

A probe run for section 5 of this audit fired the pre-flight and max-hold job bodies to capture
the exact commands they spawn. It patched out the subprocess runner, so no child process ever
started — but patching the runner does not stop a job's success path from writing its own state
file, and those two jobs are the only ones that write state.

`global_index/preflight_state.json` and `global_index/maxhold_state.json` were both overwritten
at 20:03:21, each reduced to a single key for 2026-08-23 — a Sunday, a day neither job runs.
The real weekday records were lost.

Live impact today is none: the running scheduler read the file once at startup and holds the
full record in memory, and it writes that back out at Monday 13:45. The exception is a restart
before then, which would reload the damaged file and fail-close Monday's NKD night slots.

Full account, evidence, and the guard that now prevents it:
`scratch/track1_stage5l_shared_preflight_20260823.md`.

---

## What this audit does not claim

It does not claim Stage 5K was wrong. The ops integration works, the preflight is fail-closed,
and an operator can start the scheduler in Track 1 shadow mode today.

It claims something narrower and more important: **starting is not covering.** A shadow period
started under the current wiring produces evidence about Calm and Stress. The gate it would be
used to pass is a gate about the combined route. Those are different claims, and the first
cannot be used to satisfy the second.

The next piece of work is 5L, and the one that actually costs something is 5M.
