# Track 1 — Stage 3: shadow route build

**Date:** 2026-08-22 (host clock Calgary MDT; market times ET unless stated)
**Contract kept:** no scheduler or service started · no IBKR connection · no dashboard write ·
no order · nothing committed · legacy behaviour and legacy files unchanged.

---

## A. Verdict

**Shadow route build: PASS.**

The Track 1 route exists, runs, and reproduces the measured Track 1 book **event for event**
on all three windows. Its decision brain is production code, its identity is a hash, its
state is route-scoped, and it cannot place an order.

**Paper / live: STILL BLOCKED.** Three blockers are open and are carried in the code as data
(`run_live_day_track1.OPEN_ORDER_BLOCKERS`), so the order gate refuses by reading them rather
than by remembering them. Two of the three are the Stage 2D blockers that Stage 3 could not
close by building anything; the third is that no sleeve has a promoted live signal generator.

One Stage 2D blocker **is** closed by this build: **BLOCK-4, per-sleeve quantity.** Quantity
is now a property of the candidate, and MNQ = 1 under Normal beside MNQ = 7 under Stress is
expressible, tested and exercised on real measured rows.

---

## B. What the route actually is

```
scratch/track1_replay_source_20260822.py      candidates from the measured trade tables
        │                                     (the ONLY working source today)
        ▼
global_index/track1_signal_layer.py           the admission layer: caps, family cap,
        │                                     same-symbol invariant, Stress displacement,
        │                                     detection windows, per-candidate quantity
        ▼
global_index/run_live_day_track1.py           entry point — order gate, freshness gate,
        │                                     checkpoint report, shadow output
        ▼
scratch/track1_shadow/                        decisions · settlements · book state · summary
```

with three modules beside it:

| module | what it holds |
|---|---|
| `global_index/track1_params.py` | the route's declared identity per sleeve, in `route_params`' vocabulary; caps; per-sleeve quantity; detection windows; a source for every field |
| `global_index/track1_freshness.py` | the fail-closed data gate, encoding the D-1 13:45 ET contract |
| `global_index/track1_switch.py` | `close_then_open` — cancel-confirm, close-verify, then open. Never called live |
| `global_index/track1_sleeves.py` | the source boundary, and the named list of what must be promoted before a live source can exist |

**Legacy is untouched.** `signal_layer.py`, `run_live_day.py`, `runner.py`, `live_decision.py`,
`net_exposure_multi.py`, `replay_checkpoint.py`, `ibkr_broker.py`, `run_scheduler.py` and the
monitor backend were **not edited**. Section E proves it by hash.

---

## C. Files created and changed

### Created — production package

| file | lines | what it is |
|---|---|---|
| `global_index/track1_params.py` | 265 | route identity, caps, per-sleeve quantity, windows, per-field sources |
| `global_index/track1_signal_layer.py` | 483 | the admission layer; ported from the Stage 2C loop under an equivalence gate |
| `global_index/track1_sleeves.py` | 137 | source protocol; `LiveSleeveSource` refuses and names the promotion list |
| `global_index/track1_freshness.py` | 233 | fail-closed freshness gate |
| `global_index/track1_switch.py` | 224 | `close_then_open`, broker-agnostic, order-sending off by default |
| `global_index/run_live_day_track1.py` | 463 | the entry point |

### Created — scratch

| file | lines | what it is |
|---|---|---|
| `scratch/track1_replay_source_20260822.py` | 131 | candidates + early-exit valuer from the measured tables |
| `scratch/test_track1_stage3_route_20260822.py` | 619 | the Stage 3 gate, 42 tests |
| `scratch/_stage3_legacy_baseline.json` | — | the pre-build hash/mtime snapshot section E checks against |
| `scratch/track1_shadow/` | — | 8 output files from two shadow runs |

### Changed

| file | change |
|---|---|
| `scratch/track1_stage2d_full_production_route_audit_20260822.md` | **appended** ADDENDUM 1. Nothing above it was rewritten. |

**Nothing else.** No legacy production file was modified — including no "shared additive
utility", which section B of the task allowed if explained. None was needed.

---

## D. Tests run, and what they measured

### The Stage 3 gate

```
python -m pytest scratch/test_track1_stage3_route_20260822.py -q
→ 41 passed, 1 skipped in 36.07s
```

```
TRACK1_EQUIV_FLOOR=1 python -m pytest scratch/test_track1_stage3_route_20260822.py -q \
    -k "floor or test_1_"
→ 3 passed, 38 deselected in 142.26s
```

The skip is the floor window, which is opt-in because it costs two and a half minutes. It was
run separately, above, and passed.

### The equivalence result, measured

The ported rule set was driven over the same measured windows as
`scratch/track1_stage2c_book_bootstrap_20260822.py::replay` (policy
`risk_clean_no_calm_nkd_family_cap_5_44`), and the **ordered settlement stream** compared
element for element — not counts, not sums, because two books that traded entirely
differently can carry the same total.

| window | events | ordered stream | net | taken/rejected per sleeve | branches exercised |
|---|---|---|---|---|---|
| vault2026 | 91 | **identical** | $8,259.85 both sides | identical | family cap ×10, same-symbol ×1, cap ×37 |
| vault2025 | 128 | **identical** | $13,236.11 both sides | identical | Stress displacement ×1, same-symbol ×4, family ×3 |
| floor 2018-2024 | 1,160 | **identical** | $64,902.91 both sides | identical | breaker halt ×2, displacement ×14, same-symbol ×22, family ×5 |

### The rules were then broken on purpose

A gate that only ever goes green has not been shown to check anything. Each rule was disabled
in-process — never by editing a file — and the stream required to diverge. The window is part
of each case because a rule can only be shown load-bearing where it binds, and each pairing
was chosen by **measuring** which windows the mutation moves:

| rule disabled | window | stream diverged |
|---|---|---|
| same-symbol suppression | vault2026 | yes |
| same-symbol suppression | vault2025 | yes |
| Stress displacement | vault2025 | yes |
| NKD cluster cap | vault2026 | yes |
| Normal+Calm family cap | vault2026 | yes |
| Normal+Calm family cap | vault2025 | yes |

### One measured finding that came out of that

**The Normal cluster cap is completely subsumed by the family cap.** Loosening
`cap_roska4_swing` from 5.0%/4.4% to 50%/44% changes **nothing**, on any window. The reason is
structural rather than accidental: the family cap carries the same two numbers over a strictly
larger book (Normal + Calm), so it is always at least as tight.

This is not a defect — belt and braces is fine — but it must not be folklore. It is now pinned
by `test_1e_the_normal_cluster_cap_is_subsumed_by_the_family_cap`, which asserts the two cap
sets are equal and asserts the loosening is inert. If the family cap is ever widened (7.5% was
one of the measured policies) that test goes red and tells the next reader that the Normal
cluster cap has just become load-bearing again.

### The rest of the gate

| # | test | measured outcome |
|---|---|---|
| T1c | the two rules that are NOT in the anchor are inert on it | `suppress_same_sleeve` and `reject_window` fire **zero** times on both default windows — so the equivalence above is not passing because the new rules happened to cancel out |
| T2 | at most one position per instrument, across all four sleeves | held instruments are unique after Normal, Calm, NKD and a displacing Stress entry; two same-symbol suppressions recorded |
| T2b | a second position in the SAME sleeve on the same instrument | refused with `suppress_same_sleeve` |
| T3 | quantity per candidate | MNQ Normal → 1 contract, MNQ Stress → 7; after the switch the book holds exactly `{roska4_stress: 7}` |
| T3b | the measured rows really carry 7 | every Stress row in vault2026 has `qty == 7`; every Normal MNQ row has `qty == 1` |
| T4 | SPY short gate causal at D-1 | multiplying SPY's close **at D** by ten leaves D's own verdict unchanged and moves only days **after** D. The test also asserts something changed, so it cannot pass by mutating nothing |
| T4b | the gate's identity travels | all four fields present, source identity is a full 64-hex sha256, and pointing at a different SPY file moves the params hash |
| T5 | a missed 10:00 Calm A | 10:00 → taken; 10:20 → `reject_window`, detail contains "one-shot" |
| T6 | the Stress window | 10:34 refused · 10:35 taken · 11:14 taken · 12:30 taken · 12:31 refused · 14:05 refused |
| T6b | windows match the ledger contract | `track1_params.WINDOWS_ET` equals `window_ledger.WINDOWS` start/end for both sleeves |
| T6c | the ledger records an incomplete window | 5 of 24 slots → `incomplete`, `usable_as_evidence=False`; a date nobody watched → `unobserved`, not "no signal" |
| T7 | no-order default | `send_order` called **0** times in a full shadow run; `NoOrderBroker.send_order` raises if ever reached |
| T7b | asking for orders | `--allow-orders` exits **2** and names every open blocker. With the out-of-band approval set it *still* refuses while a blocker is open — and with the blocker list emptied it would arm, so the refusal is the blockers talking, not a switch that can never move |
| T8 | no legacy write | every legacy artifact byte-identical and mtime-identical before and after a shadow run; no new `live_day_*.log` appeared. The test asserts at least one legacy artifact exists first, so it cannot pass on an empty set |
| T8c | persisting the book | writes the ROUTE's path, carries every value Stage 2C proved load-bearing, leaves legacy identical, and does not touch the default route path when redirected |
| T9 | checkpoint refusals surface as codes | every reported code is one of `route_checkpoint`'s seven, plus an explicit "identity matched, frame not loaded"; against the Stage 2B bootstrap the Normal sleeve refuses with `params_mismatch` and the detail carries both hashes |
| T9b | every param field has a source | `missing_source` / `source_for_unknown_field` / `unsourced` all empty; settled conflicts name their evidence |
| T10 | the switch primitive | five cases, below |
| T11 | freshness fails closed | six cases, below |
| T12 | the live source refuses | raises, and the message names all four sleeves and `model_sameday_stop` |

### The eight suites that had to stay green

```
python -m pytest scratch/test_track1_stage2_equivalence_bootstrap_20260822.py \
  scratch/test_track1_route_checkpoint_stage1_20260822.py \
  scratch/test_slot_telemetry_20260822.py global_index/test_slot_overlap.py \
  global_index/test_log_hygiene.py global_index/test_scheduler_heartbeat.py \
  global_index/test_dashboard_live_snapshot.py global_index/test_scheduler_shadow_verify.py -q
→ 156 passed in 6.63s
```

Identical to the Stage 2D baseline (156 passed, 0 failed, 0 skipped). The Stage 2C bootstrap
suite is among them and is green.

`global_index/test_event_playback.py` was **not** run — known to hang.

---

## E. Were legacy paths and mtimes untouched?

**Yes — 20 of 20 artifacts identical, by content hash AND by mtime.**

The check is not a promise; a snapshot was taken **before** any file was written and compared
after everything had run:

| group | files | result |
|---|---|---|
| runtime state | `live_positions.json`, `slip_stats.json`, `trade_log.jsonl`, `global_index/replay_checkpoint.json`, `global_index/live_state_data.js`, `global_index/preflight_state.json`, `global_index/maxhold_state.json`, `global_index/paper_history.json` | unchanged |
| legacy code | `signal_layer.py`, `run_live_day.py`, `runner.py`, `run_scheduler.py`, `ibkr_broker.py`, `live_decision.py`, `net_exposure_multi.py`, `replay_checkpoint.py` | unchanged |
| dashboard | `monitor/backend/app.py`, `monitor/backend/schedule_status.py` | unchanged |
| absent and still absent | `runner.pid`, `STOP_TRADING` | still absent |

The newest `live_day_*.log` is `live_day_0821.log`, written by the real scheduler on Friday.
Nothing this build ran added one — which matters more than it sounds, because
`paper_evidence_reader` globs that pattern, and a `--dry-run` of the legacy runner once
manufactured a paper-evidence episode exactly that way.

The three files git reports as modified in `global_index/` — `deploy_sim.py`,
`run_live_day.py`, `run_scheduler.py` — were **already** modified before Stage 3 began (the
earlier slot-telemetry work). Their hashes are in the pre-build snapshot and are unchanged.

---

## F. Route state paths

| purpose | path | written today? |
|---|---|---|
| position book | `live_positions.track1.json` | only with `--persist-book`; off by default |
| PID lock | `runner.track1.pid` | no — the shadow route takes no lock because it touches no broker |
| route checkpoint | `global_index/replay_checkpoint.track1.json` | read only; schema 2, route-scoped, `_FileLock` + `ScopeViolation` |
| kill switch | `STOP_TRADING.track1` | read only, never written |
| window coverage | `window_coverage_*.jsonl`, `route=track1_candidate` | only when `RAITS_WINDOW_LEDGER_DIR` is set |
| shadow output | `scratch/track1_shadow/` | yes — 8 files |

`--persist-book` is off by default on purpose. A replay's end state is a book **as of the end
of a historical window**, and writing that to a path that reads like a live position file is
how a misleading artifact gets created and then believed.

The window ledger is deliberately **not** driven from a replay. Its whole contract is "did an
observation happen at all", and a replay knows only the days a trade existed — not the days
the window was watched and produced nothing. Emitting `window_closed` from a replay would
manufacture exactly the evidence the ledger exists to withhold. The live entry
(`record_window_observation`) is wired and tested directly instead.

---

## G. The freshness contract, and what it does not cover

Stage 2D offered two options. **Option 2 was taken: the D-1 13:45 ET contract is encoded
explicitly.** No pre-10:00 update job was added — that would be a new IBKR-touching job, and
this build does not touch IBKR.

The rule, stated so it can be tested:

> Every historical input a Track 1 sleeve reads must be no older than the most recent
> completed 13:45 ET pre-flight. On any instant before 13:45 ET that is the **previous
> business day's**. Anything older, missing, or unreadable is a refusal.

Measured behaviour:

| case | verdict |
|---|---|
| 11:00 ET Friday → requires 2026-08-20 | correct |
| 14:00 ET → requires the same day | correct |
| 09:00 ET Monday → requires the previous **Friday**, not Sunday | correct |
| SPY CSV last date before the requirement | refuses |
| SPY CSV missing | refuses |
| no pre-flight record for the required date | refuses |
| pre-flight record says the update FAILED | refuses |

**What it does not cover, and says so:** the intraday bars a same-session sleeve decides on
come from the broker at decision time, and this gate cannot see them. It reports
`intraday_source` as **UNVERIFIED** — neither a pass nor a failure — and that is one of the
three open order blockers. Reporting it as a pass would be the "silent pass conflates
unverified with verified OK" failure the frozen-manifest check already guards against.

---

## H. The switch primitive

`close_then_open` is implemented and tested against a fake broker. **It is not wired to
anything live and cannot send an order**: `allow_orders` defaults to False and it returns
without touching the broker.

Sequence, and each failure branch:

| case | measured |
|---|---|
| default (no `allow_orders`) | returns at `switch_requested`; **zero** broker calls |
| stop cancel fails | aborts at `stop_cancel_failed`; **no close was placed** — the old position stays intact and protected |
| close returns FAILED / CANCELLED / **PARTIAL** | aborts at `close_failed`; only a CLOSE was sent, never an OPEN. PARTIAL counts as failure: a partly-closed Normal leg plus a 7-lot Stress leg nets at the broker into a quantity neither sleeve believes it holds |
| open fails after the close filled | `open_failed_account_flat`, `account_flat=True`, and the `persist_flat` callback **was called** — the book is told before anything else happens |
| happy path | CLOSE then OPEN, open leg carries **7** contracts, and the six stages are emitted in order |
| cross-symbol legs | refused; no order sent |

Every stage emits **before** it acts, so a crash between two steps is attributable from the
log. Emitting afterwards would leave the most interesting case — the one that died halfway —
as the one with no record.

The admission layer already enforces the ordering the strategy requires: a Stress candidate is
checked against the cap **on the book it would leave behind**, and refused *before* anything is
closed. Nothing is ever closed for an entry that then gets rejected.

---

## I. Findings this build produced

**1. The existing Track 1 checkpoint cannot be resumed by this route, and that is correct.**
`scratch/replay_checkpoint.track1.bootstrap_20260822.json` was seeded under the **legacy**
engine identity. Diffed field by field against the Track 1 identity:

* **Normal sleeve — 5 genuine strategy differences**: `ema_period` 30 → 50, `stop_basis`
  chandelier → fixed-entry-ATR, `stop_multiple` 2.5 → 2.0, `stop_anchor` extreme-through-prior-bar
  → entry, `ratchet` True → False. Plus `arm_hour` 14:00 → 14:05. These are real: Track 1's
  Normal-R4 is a different engine, not a different parameterisation.
* **NKD sleeve — 0 strategy differences.** All four differences are **encoding**: the two
  producers render the same content differently — truncated 16-hex hash + basename versus full
  sha256 + path — and one wrote a different wording for the same Calm gate definition.

The wording was fixed here by adopting the audited sentence verbatim. The hash rendering was
**not** loosened to match the scratch truncation: a full sha256 and a real path are strictly
more informative, and shortening an identity to make a comparison pass is the opposite of what
the identity is for. The consequence is stated plainly: **the Stage 2B bootstrap must be
regenerated under `track1_params` before any Track 1 sleeve can resume.**

**2. `cap_roska4_swing` is inert.** See section D. Measured, asserted, and it will announce
itself if the family cap ever moves.

**3. Two rules exist in Track 1 that the anchor loop does not have** — the same-sleeve guard
and the detection-window gate — and both fire **zero** times on all three anchors. That is what
makes them safe to add: they change nothing about the measured result and they close a hole
that only exists live.

---

## J. Remaining blockers before paper or live

Carried in code at `run_live_day_track1.OPEN_ORDER_BLOCKERS`, so the gate reads them.

| id | blocker | closed by |
|---|---|---|
| **BLOCK-1** | One IB Gateway login is one position book. `IBKRBroker` has no account dimension; `get_positions()` and `get_equity()` read the whole login. Two routes on one account net at the broker and both halt on the resulting mismatch. | a decision: a dedicated account for Track 1, **or** retiring legacy first — which is the stated end state, and is the cheaper of the two |
| **BLOCK-3** | Calm A (10:00) and Stress (10:35–12:30) open before the day's own 13:45 pre-flight. The D-1 contract is now encoded and tested, but the **intraday** source a same-session sleeve decides on is unverified by any gate. | either a pre-10:00 freshness job, or an in-window bar-quality check that can fail closed |
| **LIVE_SLEEVE_SOURCE** | No sleeve has a promoted live signal generator. The Normal sleeve alone runs through `model_sameday_stop.run_loop`, `scratch/harness.Cfg/patched_engine`, a doubly-wrapped `TrendFollowStrategy`, `force_all_bars_gappable`, and two scratch filter modules — with `futures/_validated_core.backtest_swing_tf` monkeypatched out of the way. | promoting each generator **with its own equivalence proof**. The full list is in `global_index/track1_sleeves.LIVE_SOURCE_PREREQUISITES` |

**BLOCK-2** (the 10:20→14:05 scheduler invariant) is not on this list because this build's
answer to it is structural: Track 1 has its own entry point and its own signal layer, so it
never calls `run_live_day` and cannot breach the invariant. It becomes a scheduling question
again only when Track 1 slots are added to the scheduler, which Stage 3 did not do.

**BLOCK-4** (per-sleeve quantity) is **closed**.

### Also required before paper, and not built here

* Track 1 slots in the scheduler, mirrored in `monitor/backend/schedule_status.py` **in the
  same change** — that file keeps a hand-written copy of the slot table and its own comment
  says an unmirrored slot becomes a fake incident every day.
* `((10,35),(12,30))` added to `_ENTRY_WINDOWS` so the 12:20 stop-repair sweep does not land
  inside the Stress window.
* A `route` field on runner events, and a decision about whether Track 1 shares
  `trade_log.jsonl` — if it does, `paper_evidence_reader` must be taught to split on it, or
  Track 1 rows will be folded into legacy's fill-quality and P&L gates.
* The Stage 2B bootstrap regenerated under `track1_params` (finding 1).

---

## K. How to reproduce everything in this report

```powershell
cd d:\raits

# the Stage 3 gate (fast)
python -m pytest scratch/test_track1_stage3_route_20260822.py -q

# the floor-window equivalence gate (~2.5 min)
$env:TRACK1_EQUIV_FLOOR="1"; python -m pytest scratch/test_track1_stage3_route_20260822.py -q
Remove-Item Env:\TRACK1_EQUIV_FLOOR

# a shadow pass
python -m global_index.run_live_day_track1 --window vault2026 --as-of "2026-08-21 11:00"
python -m global_index.run_live_day_track1 --window vault2025 --as-of "2026-08-21 11:00"

# the order gate refusing (exits 2, sends nothing)
python -m global_index.run_live_day_track1 --allow-orders --window vault2026

# the eight suites that must stay green
python -m pytest scratch/test_track1_stage2_equivalence_bootstrap_20260822.py scratch/test_track1_route_checkpoint_stage1_20260822.py scratch/test_slot_telemetry_20260822.py global_index/test_slot_overlap.py global_index/test_log_hygiene.py global_index/test_scheduler_heartbeat.py global_index/test_dashboard_live_snapshot.py global_index/test_scheduler_shadow_verify.py -q
```

---

## L. Confidence labels

**Verified — reproduced, with a number:** the three-window ordered-event equivalence; the six
mutations that diverge and the one that does not; 41+1 Stage 3 tests; 156 unchanged in the
eight suites; 20 of 20 legacy artifacts unchanged by hash and mtime; zero `send_order` calls;
the field-by-field identity diff against the Stage 2B bootstrap.

**Reasoned from reading the code path, not executed:** that the switch sequence behaves the
same way against a real IBKR broker as against the fake. The fake reproduces the `Fill` shape
and the status vocabulary, but it does not reproduce ib_insync's client-side `Cancelled`
mutation, partial-fill timing, or a cancel refused because it came from the wrong `clientId`.
Those are the three things that have actually gone wrong on this path before.

**Not examined:** whether the Track 1 replay's fill law matches what live `send_order` would
achieve — the three-blockers report measured both laws offline; no live-fill comparison
exists. Also untouched: the dashboard's reaction to a Track 1 slot, since no slot was added.

**Explicitly out of scope, and not started:** retiring legacy. Nothing in this build changes
what the running scheduler does, and the live scheduler was not restarted, stopped or
reconfigured.
