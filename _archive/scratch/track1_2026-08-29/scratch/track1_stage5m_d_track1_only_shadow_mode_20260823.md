# Stage 5M-D — Track 1-only shadow mode, and the legacy-removability audit

**2026-08-24 ·** no scheduler started or stopped · no real IBKR connection · no order · no
`STOP_TRADING`, `STOP_TRADING.track1` or confirmation file touched · no live state written ·
no commit.

---

## Verdict: **READY_FOR_5N_NKD_TRACK1_OWNERSHIP**

The exact claim, no wider: **Track 1-only shadow mode exists for the current Track 1 sleeves;
legacy strategy jobs can be omitted; the Normal-R4 provider collision with legacy is resolved
structurally. NKD and route-aware safety are still pending.**

Not claimed: full route (NKD has no slot — in this mode the overnight sleeve is not traded by
anyone), legacy independence (the safety sweeps still point at legacy's book), live or paper
readiness. Legacy may be moved or deleted only after 5N + 5O + 5P.

---

## The mode

| Mode | Jobs | legacy entry | safety | shared infra | Track 1 | swing provider |
|---|---|---|---|---|---|---|
| (default) | 60 | 45 | 12 | 3 | 0 | — |
| `--track1-shadow` | 107 | 45 | 11 | 3 | 48 | `none` |
| **`--track1-only-shadow`** | **62** | **0** | 11 | 3 | 48 | **`ibkr`** |

The first two rows are asserted unchanged — this stage is additive.

**How the removal works, and why that way.** The schedule is built whole and the legacy
strategy jobs are then removed **by id**, the set coming from
`track1_slots.legacy_retirement_candidates()` — the same table the Stage 5L classification and
the retirement audit read. Guarding four registration sites with `if not track1_only` would
have created a second definition of "which jobs are legacy's", and two definitions drift. One
table, three readers. And `remove_job` raises on a missing id, so a job renamed in one place
stops the scheduler from building instead of quietly surviving into a mode whose whole point is
that none do. A test pins the removed set to be *exactly* the retirement candidates.

**Why the switch could never do this.** `STOP_TRADING` halts entries inside `runner.run_day` —
after the legacy slot has spawned, connected on clientId 1, fetched every instrument, rolled
contracts and run exits and reconcile. The scheduler and job execution are untouched by it.
"Turn off legacy" means *do not schedule the jobs*, and that is what this mode does.

**The provider follows the reason, not the stage.** 5M-C staged the swing provider because the
swing minutes were occupied by connected legacy children. In this mode those jobs do not exist,
so the swing slots default to `ibkr` — and in the transitional mode they still default to
`none`, because there the reason still holds. The env var overrides in both directions; a typo
still refuses at build time.

---

## The legacy-removability audit — measured, not asserted

Method: `global_index.run_live_day` is made unimportable by a **meta-path finder** — not a
`builtins.__import__` wrapper, and that distinction was found the hard way: the suite's own
"prove the block blocks" self-check failed against the wrapper, because `importlib.import_module`
walks `sys.meta_path` directly and never touches `__import__`. The finder catches both routes,
and the self-check now passes.

With the legacy entrypoint deleted-by-simulation:

| Probe | Result |
|---|---|
| scheduler builds, all three modes | **yes** — 60 / 107 / 62 jobs, 0 legacy entry in the new mode |
| all 48 Track 1 slot closures fire | **yes** — providers `ibkr` across all three sleeves, route `track1_candidate`, no order flags |
| dashboard mirror builds | **yes** — 48 Track 1 rows, **0** legacy rows, pre-flight and max-hold present |
| any Track 1 module imports legacy | **no** — AST scan over every `track1_*.py` |

**The state question has the right answer for the right reason.** Track 1's only code-level
mentions of `live_positions.json`, `replay_checkpoint.json`, `live_state_data.js` and
`trade_log.jsonl` are inside `run_live_day_track1.LEGACY_PATHS` — the route's own
*must-never-write* refusal list. Naming a file to guarantee you never write it is the opposite
of depending on it. A test asserts those mentions exist **and** that they occur nowhere else in
the module.

**The one true remaining dependency, classified as a blocker and not accepted:** the 11 safety
jobs — stop repair ×10 and the 09:31 max-hold exit — carry `--positions-path
live_positions.json` on their argv, measured by firing all of them. They stay registered
deliberately: any position still open in legacy's book needs its stop repaired and its five-day
exit, and removing the sweeps would strand it. But it means this mode is *legacy-removable*
(the route runs with legacy's code gone) and **not yet legacy-independent** (legacy's book is
still what the safety net watches). That is Stage 5O, named in the code comment, the runbook,
and a test that will go red when 5O fixes it.

---

## A defect this stage found: `python monitor/ops.py --help` crashed

Introduced by **Stage 5M-C — by me.** `track1_slot_count()` was placed inside an argparse help
string, so it runs at parser build; operators run `ops.py` as a script, which puts `monitor/`
on `sys.path` and not the repo root, so `from global_index...` raised `ModuleNotFoundError`
before any output. Every operator invocation of `ops.py` was broken.

5M-C's tests missed it because they imported `monitor.ops` as a module — with the root already
on the path — and never ran it the way the runbook tells an operator to. Both halves correct,
the seam never crossed: the third instance of this shape in three stages (`_run`'s stub, the
`--sleeve` choices, now this). The fix puts the root on `sys.path` inside the function, and a
new test runs `ops.py up --help` **as a subprocess**.

## Ops

* `--track1-only-shadow` on `up` and `restart`; `restart --scheduler --track1-only-shadow` is
  the operator path.
* `--track1-shadow --track1-only-shadow` together → **refused, exit 2** — they ask for
  different schedules.
* Track 1-only does **not** require `STOP_TRADING`: there are no legacy entry jobs for it to
  halt, and demanding it would teach the operator that the switch is what stops legacy. The
  transitional mode still requires it — asserted in both directions.
* The old banner line `STOP_TRADING: present (legacy entries frozen)` is gone from the new
  mode's output; it printed the myth. The transitional mode's banner now states the truth:
  legacy is *still scheduled* and the switch halts entries only.
* The child environment carries `RAITS_TRACK1_ONLY=1` and `RAITS_TRACK1_SHADOW=1`, and
  `TRACK1_ORDERS_APPROVED` is stripped, as before.

## Dashboard

`schedule_status.track1_only_enabled()` (env `RAITS_TRACK1_ONLY`) omits the 45 legacy strategy
rows from the mirror — without it the dashboard would manufacture an incident for every
expected-but-absent legacy slot, 45 a day. It implies the shadow mirror, so one env var cannot
disagree with the other. **Parity is true in all three modes: 60/58, 107/105, 62/60.**

## Stale-text guards

A regex guard over `ops.py`, `run_scheduler.py` and the runbook fails on any text claiming
`STOP_TRADING` *turns off / disables / stops legacy running* — history lines describing the
misconception are allowed, and the guard is itself tested against strings that must trip it.
The hardcoded-slot-count guard from 5M-C is carried forward.

## Runbook

Section 9: the three modes, the precise statement of what the switch does, why the provider
default differs by mode, the start command, what stays scheduled and why, the removability
evidence, and the claim limits — legacy moves or deletes only after 5N + 5O + 5P.

---

## Test results

| Suite | Result |
|---|---|
| **Stage 5M-D** `test_track1_stage5m_d_track1_only_shadow_20260823.py` | **35 passed** |
| **Mutation harness** | **8 / 8 detected**; three on-disk mutations restored byte-for-byte |
| 5M-C + 5M-B + 5L + 3B + ops + mirror | **232 passed, 1 skipped** |
| 5M-D + 5I + 5D + 5E + 5M-1 sweep | **119 passed** |

`global_index/test_event_playback.py` **not run** — still the known hang.

```
D1  a legacy job survives into track1-only            → the central-claim test reds
D2  swing defaults to ibkr in TRANSITIONAL mode       → the collision test reds
D3  track1-only loses its ibkr default                → the provider test reds
D4  ops silently resolves the contradictory flags     → the refusal test reds
D5  track1-only demands STOP_TRADING after all        → the wrong-model test reds
D6  a Track 1 module imports the legacy entrypoint    → the removability scan reds
D7  the kill-switch myth returns to operator text     → the myth guard reds
D8  the mirror ignores track1-only                    → the mirror test reds
```

Two mutations were unfaithful on their first attempt and were fixed rather than their tests
weakened: the import block that `importlib` walked straight past (now a meta-path finder), and
D8 as an in-process patch that the guard test's own `reload` erased (now on disk, where a real
regression lives).

---

## No side effects

No scheduler, backend, or dashboard started or stopped — pid 36656 untouched. No real IBKR
(fake broker only, and in this stage not even that — the provider path was proved in 5M-C). No
order. No switch or confirmation file. No live state written. No commit.

---

## Next

**Stage 5N — NKD Track 1 ownership.** The strategy already matches legacy's (ema 10,
chandelier 2.5, five-day hold, lag 1), so it is plumbing rather than a port — and it is what
decides whether a Track 1-only session leaves the overnight sleeve untraded. After that,
**5O** (route-aware safety — the one remaining legacy dependency this stage measured) and
**5P** (full four-sleeve shadow). Legacy moves out of the production path after those three,
not before.
