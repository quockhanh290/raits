# Stage 5H — closeout

**2026-08-23 · verification only · no scheduler started or stopped, no IBKR connection, no
order, no dashboard runtime write, no `STOP_TRADING`, no confirmation file, no commit.**

---

## Stage 5H = **COMPLETE**

## Verdict = **NOT_READY_FOR_SHADOW_START**

---

## 1. Why this is not a failure of Stage 5H

Stage 5H was commissioned as a **pre-shadow / B1 preflight audit**. Its job was to establish
whether the route could be handed to an operator, and to name precisely what stands in the way if
not. It did exactly that.

A preflight that returns "not ready" has succeeded, provided the reason is specific, measured, and
actionable. This one is all three: it is a single missing CLI wire, found by running the exact
command a scheduler slot issues rather than by reading the code and forming an opinion.

The alternative — reporting "ready", letting an operator freeze legacy with `STOP_TRADING`, start
the scheduler, and discover a day later that every slot recorded `no_bar_provider` — is the
outcome this stage existed to prevent. **It prevented it.**

---

## 2. The exact blocker

> `main()`'s `live-shadow` branch calls `observe_live_slot(...)` **without a provider**, and the
> entry point has **no `--bar-provider` flag**. The factory Stage 5G moved into
> `track1_live_source.build_bar_provider` therefore has **no caller on the scheduler path**.

Verified three ways, not asserted:

- `main()` contains no call to `build_bar_provider` — checked by parsing the function's call
  graph, not by grepping text.
- The entry point's flags, parsed from its own `add_argument` lines, are exactly
  `--window · --source · --sleeve · --slot-id · --regime-csv · --out-dir · --as-of ·
  --persist-book · --allow-orders`. **No `--bar-provider`.**
- Running the slot command with a temporary ledger directory:

```
slot TRACK1_CALM_1000 seq=0  decided=False  reason=no_bar_provider
window closed: 0 of 1 decided (1 slots ran)
checkpoint: NOT written — the window did not complete
send_order calls: 0
ledger rows: window_open · slot_observed · window_closed   (outcome: incomplete)
```

**Therefore starting the shadow scheduler today would collect no coverage and write no
checkpoint.** Preconditions 5 and 6 would stay shut — correctly, and by design: the route records
that it collected nothing rather than pretending otherwise.

**The blocker is code, not an operator action.** No amount of operator care fixes it.

### A correction to my own probe

My first check of "does a `--bar-provider` flag exist" used a sloppy substring heuristic and
answered **True**. That was wrong — the probe, not the code. Re-checked by parsing the
`add_argument` lines, the answer is **False**, which matches the slot's actual behaviour. Recorded
because a preflight that quietly fixes its own bad measurement is not one you can trust.

---

## 3. Re-verified at closeout

### Gate

| check | result |
|---|---|
| `live_frame_wiring()` | **released** |
| `blocking()` | `['B1_broker_account_or_legacy_retirement']` |
| `self_check()` | `[]` |
| `--allow-orders` | **exit 2**, names B1 (×1) and the unset `TRACK1_ORDERS_APPROVED` (×1), names the closed live-frame blocker **0 times** |
| confirmation file | **absent** |

### Scheduler — built only, never started

| check | expected | measured |
|---|---|---|
| shadow OFF jobs | 60 | **60** |
| shadow ON jobs | 84 | **84** |
| Track 1 slots | 25 | **25** |
| Calm | 1 at 10:00 | **`track1_calm_1000`** |
| Stress | 24, 10:35→12:30 every 5 min | **24**, `track1_stress_1035`…`track1_stress_1230`, step verified |
| legacy entry slots under shadow | 23 | **23** |
| removed by shadow | only `stop_repair_1220` | **only `stop_repair_1220`** |
| dashboard parity OFF / ON | true / true | **true / true** |

### Slot argv

```
-m global_index.run_live_day_track1 --source live-shadow --sleeve <s> --slot-id <id> --regime-csv <csv>
```

Includes `--source live-shadow`, `--sleeve`, `--slot-id`, `--regime-csv`.
Excludes `--allow-orders`, `--window`, `--port`, **`--bar-provider`**.

---

## 4. What must happen next

1. **Stage 5H0 — missed-surfaces audit.** Before writing the provider wire, sweep for anything
   else on the shadow path that is present-but-uncalled, the same shape as this blocker and as the
   two that preceded it (`record_window_observation` and `track1_bootstrap.write`, both of which
   had zero callers until Stage 5D). Three instances of one pattern is a reason to look
   systematically rather than one at a time.
2. **Stage 5I — provider wiring.** Add `--bar-provider {none,ibkr}` to the entry point, call
   `build_bar_provider`, hand the result to `observe_live_slot`, and release the broker in a
   `finally`. Note there is **no disconnect path anywhere today**, because there is no caller — so
   the cleanup is part of that stage, not an afterthought.
3. Only then the operator sequence from Stage 5H: decide B1 → `STOP_TRADING` before any start →
   export `RAITS_WINDOW_LEDGER_DIR` **into the scheduler's environment** → start shadow → confirm
   ledger rows read `decided=true`.

## 5. What must NOT happen next

- **Do not start the shadow scheduler.** It would freeze legacy and collect nothing.
- **Do not write `track1_go_live_confirmation.json`.** B1 is a decision that is not made, and the
  file is the last thing to create, not the first.
- **Do not create `STOP_TRADING`** yet — it changes production behaviour to no purpose while the
  provider is unwired.
- **Do not set `TRACK1_ORDERS_APPROVED`.**
- **Do not treat this as ready for live orders.** It is not, and this stage is shadow-only.
- Do not add `--bar-provider` in this stage — that is Stage 5I, after the 5H0 sweep.

---

## 6. Checks run at closeout

All read-only or build-and-discard. No test suites were re-run in this closeout; the suites behind
these conclusions are recorded in the Stage 5H report (60 · 91+1skip · 154+1skip · 22 · 185+1
out-of-scope failure), and `global_index/test_event_playback.py` was not run there or here.

| group | result |
|---|---|
| 1. gate state | **all as expected** |
| 2. scheduler, built only | **all as expected**, parity true both modes |
| 3. slot argv | **all as expected**, `--bar-provider` absent |
| 4. blocker reproduced | **yes** — `no_bar_provider`, window `incomplete`, checkpoint not written |
| 5. Stage 5H conclusion | **stands** |
| 6. side effects | **none** |

The one known out-of-scope failure is unchanged and untouched:
`scratch/test_track1_explain_20260823.py::test_no_monitor_or_dashboard_file_mentions_the_module`,
caused by a `monitor/` file another session created.

---

## 7. No side effects

| | |
|---|---|
| scheduler processes | **0** — none started, none stopped |
| IBKR connection | **none** |
| orders sent | **none** (`send_order calls: 0`) |
| dashboard runtime write | **none** — `global_index/live_state_data.js` still 08-21 13:59 |
| legacy book | untouched — `live_positions.json` still 08-21 13:59 |
| `STOP_TRADING` / `STOP_TRADING.track1` | **absent** |
| `track1_go_live_confirmation.json` | **absent** |
| `live_positions.track1.json` / `runner.track1.pid` | **absent** |
| `TRACK1_ORDERS_APPROVED` | **unset** |
| commit | **none** — `HEAD` unchanged at `601970b` |

The only files written by this closeout are `scratch/track1_stage5h_closeout_20260823.md` and its
JSON companion. No production code, no scheduler file, no runbook change.

---

Stage 5H is closed. Proceed to Stage 5H0 missed-surfaces audit before Stage 5I provider wiring.
