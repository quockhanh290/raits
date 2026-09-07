# Stage 5O — the safety net is route-aware

**2026-08-24 ·** no scheduler started or stopped · no real IBKR · no order · no
`STOP_TRADING`, `STOP_TRADING.track1` or confirmation file touched · no live state written —
`maxhold_state.track1.json` does **not** exist on disk; every marker test ran against
`tmp_path` · no commit.

---

## Verdict: **READY_FOR_5P_FULL_FOUR_SLEEVE_SHADOW**

The exact claim, no wider: **Track 1-only mode is legacy-independent at strategy + safety
scheduler wiring level.**

Not claimed: paper/live readiness; safe-to-delete-legacy before 5P's shadow period passes; and
**not** broker-flat or orphan-STP cleanliness — those are statements about the *account*, and
nothing in this stage consulted the broker.

This closes audit blocker **L3** — the one dependency the 5M-D removability probe measured,
named, and refused to wave through.

---

## What was true before, measured

Every safety job in every mode carried `--positions-path live_positions.json`: the ten
weekday stop-repair sweeps, the Sunday 18:30 sweep, and the 09:31 max-hold exit, plus a
catch-up that fires when the scheduler starts after 09:31. A Track 1 position would have had
**no stop repair and no five-day exit** — and the max-hold marker was one shared file, so the
first route to run would mark the day done and the second would silently skip.

## What track1-only mode schedules now

| | Legacy safety (**drain**) | Track 1 safety (**new**) |
|---|---|---|
| jobs | max-hold + sweeps, unchanged | **11**: max-hold 09:31 · 9 weekday sweeps · Sunday 18:30 |
| positions | `live_positions.json` | `live_positions.track1.json` |
| kill switch | `STOP_TRADING` | `STOP_TRADING.track1` |
| lock | `runner.pid` | `runner.track1.pid` |
| client id | 1 | **90** |
| max-hold marker | `maxhold_state.json` | `maxhold_state.track1.json` |

**Legacy safety stays deliberately.** It is in the safety bucket, not the retirement set: any
position still open in legacy's book keeps its protection while it drains. Removing it is part
of deleting legacy, which is gated on 5P.

**Client id 90, not 89.** Legacy safety dials 1; Track 1's data slots dial 89 — and a sweep at
10:20 can fire while the 10:00 Calm slot still holds its connection. Three actors, three ids.

**The sweep hours are derived, not listed** — from `REQUIRED_ENTRY_WINDOWS`, the same
no-sweep-inside-an-entry-window rule legacy applies to its own windows. Hours 2 (NKD band),
12 (Stress) and 14 (swing) fall out; nine remain, and a mutation that forces a sweep into the
swing window turns the derivation test red.

**Shadow cost is one process per job.** `run_maxhold_exit` returns *before connecting* when
its positions file does not exist — measured in its source, not assumed — so during a pure
shadow period the Track 1 safety net opens nothing.

**The paths cannot drift from the route.** `TRACK1_POSITIONS_PATH` and `TRACK1_STOP_PATH` are
asserted equal to the entry point's own `POSITIONS_PATH` / `STOP_FILE` constants, so the
safety net cannot end up watching a book nobody writes.

## The marker split — the silent failure, closed both ways

Two files, two in-memory dicts, two catch-ups. Proven, not asserted:

* a Track 1 max-hold run records into **its own** file and leaves legacy's untouched;
* the legacy marker **cannot** suppress the Track 1 catch-up — the exact restart-after-09:31
  scenario where the shared file would have left a five-day Track 1 position open;
* the Track 1 marker **does** suppress its own catch-up (a marker that suppresses nothing
  re-runs the exit on every restart);
* outside track1-only the Track 1 catch-up is a no-op, not an error.

## Inventory and parity

Jobs: 60 default · 129 transitional · **95 track1-only** (70 strategy slots + 11 Track 1
safety + 11 legacy safety drain + 3 shared infra). Dashboard mirror reads the **same**
`track1_safety_jobs()` table the scheduler registers from — parity true in all three modes
(60/58, 129/127, 95/93), including the Sunday sweep row on Sundays. `ops.py status` now
prints `track1_safety_routes` and distinguishes `track1-only-shadow` from the transitional
mode by reading the running process's own command line.

Legacy-removability extends to the safety net: with `global_index.run_live_day` made
unimportable, all 11 Track 1 safety jobs still build and fire against Track 1 paths.

---

## A harness defect worth recording

The first mutation run reported **4/8 detected** — and all four misses were the on-disk
mutations of `run_scheduler.py`. The harness ran `pytest.main` in-process, the mutated module
was already cached in `sys.modules`, and the tests kept exercising pre-mutation code while
the disk said otherwise. **The mutations were unfaithful, not the tests** — the fourth
instance of the both-halves-correct-seam-never-crossed family in five stages.

On-disk mutations now run pytest in a **fresh subprocess**, as an operator's pytest would;
in-process monkeypatch mutations keep `pytest.main`, because a subprocess would never see
them. After the split: **8/8 detected**, `run_scheduler.py` restored byte-for-byte.

```
S1  Track 1 stop repair points at legacy's book     → the book test reds
S2  Track 1 max-hold writes the shared marker       → the own-file test reds
S3  the legacy marker suppresses the T1 catch-up    → the suppression test reds
S4  the route env vanishes from safety children     → the route test reds
S5  the Track 1 safety jobs are not registered      → the inventory test reds
S6  a legacy strategy job survives track1-only      → the absence test reds (5M-D carried)
S7  a hardcoded '== 11' returns to the wiring       → the derived-count guard reds
S8  a sweep lands inside a Track 1 entry window     → the derivation test reds
```

## Test results

| Suite | Result |
|---|---|
| **Stage 5O** `test_track1_stage5o_route_aware_safety_20260824.py` | **26 passed** |
| **Mutation harness** | **8/8 detected**, production file restored byte-for-byte |
| Full sweep (5O + 5N + 5M-B/C/D + 5L + 3B + ops + mirror) | **324 passed, 1 skipped** |

`global_index/test_event_playback.py` **not run** — still the known hang. Five 5M-D assertions
were scoped to strategy slots (the safety argv is a different contract — no `--sleeve`, and
`--port` is legitimate there) and its bucket/mirror counts extended by the safety jobs; the
intended-change family, updated to derive.

Runbook gained section 11: the two safety sets, the marker split, the costs, and the claim
limits.

---

## What is still not true

* **Paper/live readiness** — B1 still blocks orders; nothing here changes it.
* **Safe to delete legacy** — the drain jobs and 5P's full-shadow evidence come first.
* **Broker-flat / orphan-STP clean** — account-level, unmeasured against IBKR.
* **Runtime cost of two safety sets on the same minutes** — two short-lived children per
  sweep in track1-only mode, different locks and ids, never measured against a live Gateway.
  A 5P measurement item, alongside the slot runtimes.

**Next: Stage 5P** — the full four-sleeve shadow period: coverage complete every trading day,
all four sleeves, checkpoint accepted, and the runtime measurements nobody has.
