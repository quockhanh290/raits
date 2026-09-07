# Track 1 Stage 2A/2B — equivalence harness + offline bootstrap — 2026-08-22

Offline only. No scheduler, runner, monitor backend or IBKR connection was started. No live
or paper order. No production path written. Nothing committed. None of the five legacy files
was edited.

**Result: both anchors hold, the bootstrap agrees with the live checkpoint on all five
instruments, 8 new tests green (152 across the four suites). Three parameter fields could
not be sourced and are carried as declared blockers rather than filled in.**

---

## 1. The equivalence harness

`scratch/track1_equivalence_harness_20260822.py`

### The published number is two numbers

The brief asked for *"91 matched / 0 diverged over 2026-08-10 → 2026-08-21"*. Re-derived
from the `live_day_*.log` files, those are two different figures:

| | matched | diverged | skipped |
|---|---|---|---|
| all days on record | **91** | 0 | 64 |
| 2026-08-10 → 2026-08-21 only | **85** | 0 | 0 |

91 is the all-days total. The window the brief names holds 85. The harness asserts **both,
separately**, so neither can be quietly substituted for the other. The 64 skips remain what
they were measured to be earlier: all of them on 2026-08-06 and 08-07, with full coverage
for the ten days since — not a coverage debt.

### What the harness can and cannot prove

The literal request — re-run the shadow comparison offline — is structurally impossible, and
production says so itself at `run_live_day.py:400-401`: the shadow compares against the
frames *"the path actually sees — which no offline check can reproduce, because those frames
carry IBKR bars that are never persisted."*

So the harness has two clearly separated anchors and does not let one borrow the other's
authority:

- **A1** reproduces the *record* from the logs. It re-derives the counts on every run.
- **A2** proves *resume-from-cut equals full replay* on parquet. This is labelled in the
  code as **not** a reproduction of the shadow. A2 does not run if A1 fails.

### A2 result — cut 2026-06-30, window 2026-01-01 → 2026-08-19, ema 30 / mult 2.5

| | full | after cut | resumed | trades | position |
|---|---|---|---|---|---|
| MES | 58 | 10 | 10 | exact | exact |
| MNQ | 55 | 10 | 10 | exact | exact |
| MYM | 68 | 10 | 10 | exact | exact |
| M2K | 70 | 13 | 13 | exact | exact |

Ordered-sequence comparison, no tolerance. Sequences rather than sets on purpose: once a cap
admits by priority, the same trades in a different order are a different book.

### It was broken in front of me before it was believed

| Mutation | Result |
|---|---|
| resume with the wrong carried position (`None`) | **detected** — diverges at trade 0 |
| resume from a cut three sessions earlier | **detected** — 12 trades where 10 were due |
| one cent added to one trade's P&L | **detected** — diverges at trade 0 |

One thing that fell out of this and matters downstream: in the first two mutations
`pos_match` stayed **True**. After two months of replay the open position converges whatever
the seed was. **The final position on its own does not catch a divergence — the trade
sequence does.** A check that compared only carried state would have passed all three.

---

## 2. The offline bootstrap

`scratch/track1_bootstrap_checkpoint_20260822.py` →
`scratch/replay_checkpoint.track1.bootstrap_20260822.json`

Mirrors `replay_checkpoint._bootstrap()` line for line — same loaders, same labels, same
costs, same "last complete session" rule — because a Track 1 checkpoint that disagrees with
the legacy one on the same day and the same parameters is a bug, not a route. It writes
schema v2, route `track1_candidate`, four sleeves:

| sleeve | instruments |
|---|---|
| `roska4_swing` | MES, MNQ, MYM, M2K — ema 30, arm 14:00 America/New_York, label lag 0 |
| `global_nkd` | MNKD — ema **10**, arm 14:00 Asia/Tokyo, label lag **1** |
| `roska4_calm` | empty on purpose — entry 10:00, exit 15:55, nothing crosses a day |
| `roska4_stress` | empty on purpose — entry 10:35–12:30, same-session |

### The anchor, and the axis it cannot reach

Cut at **2026-08-20**, the day the live checkpoint records — not at "the latest session".
Cutting at the latest session would compare two different days and pass by construction:
MNKD runs a Tokyo clock and had already rolled into 2026-08-21 while the ET instruments had
not.

| | mine | legacy | position |
|---|---|---|---|
| MES · MNQ · MYM · M2K · MNKD | 2026-08-20 | 2026-08-20 | flat = flat |

Five of five agree. **But state this plainly: every position is flat today, so on the
position axis the anchor is comparing `None` with `None` — true by construction.** The day
axis is real; the position axis is not exercised. There is no historical checkpoint to
borrow one from: the file is untracked by git and has no backups.

The gap is covered by a separate positive control (test 7): an open position must survive
`make_entry → save_route → load → get_entry` field for field, and the control must be able
to tell an open position from a flat one. That is the failure a flat-day anchor cannot see.

The fingerprint is deliberately **not** compared — it pins parquet row count and content,
which move every time bars are appended, so comparing it would fail for a reason unrelated
to whether the replay agrees.

### A self-check that failed, and was tightened rather than relaxed

The first run went red on *"the four R4 instruments share one params hash"*. The file was
right and the check was wrong: `data_source_identity` pins each parquet separately, so four
different hashes is the correct outcome. Relaxing the check would have deleted the property.
It was replaced by two stricter ones:

- **SC4a** every instrument hash is **unique** — proof the per-file data pin actually
  reaches the hash;
- **SC4b** with that pin held constant, the four R4 configs collapse to **one** strategy
  identity and MNKD stays apart.

Test 4 then pins each of the three things that separate them — ema, arming clock, label lag —
and asserts each moves the hash on its own.

---

## 3. Parameters — 26 fields, every one sourced or declared

Sourced from the code that produced the artifacts, not from a tool's CLI defaults.

| field | value | source |
|---|---|---|
| `ema_period` | 30 R4 / **10** NKD | `SWING_TF_PARAM`; `--nkd-ema` default in the legacy bootstrap |
| `max_hold_days` | 5 | `SWING_TF_PARAM` |
| `stop_basis` / `stop_multiple` | chandelier ATR / 2.5 | `SWING_TF_PARAM` |
| `stop_anchor` | extreme through the **prior** bar | `_validated_core.py:359-366` — the stop in force at each bar's open ratchets from `run_prev` |
| `ratchet` | true | `_validated_core.py:301` |
| `arm_hour` / `arm_timezone` | 14:00 · New York (R4) / Tokyo (NKD) | `runner.py:144-145` `_ARM_BY_CLUSTER` |
| `r4_range_threshold` | 0.02652437134968455 | `normal_promotion_filter_lib_20260821.py:44`, p90 frozen on the floor window 2018-2024 |
| `r4_rel_volume_max` | 2.0 | same file, `VOL_LE` |
| `hmm_fit_end` | 2024-12-31 | `futures/basket.py REGIME` |
| `regime_csv_identity` | `spy_daily_live.csv:442ca90caf8479e8` | computed from the file's bytes |
| `label_lag_days` | 0 R4 / 1 NKD | legacy bootstrap: `RegimeLabels(..., lag_days=1)` for MNKD only |
| `calm_gate_definition` | PCLoc in the bottom third of the prior RTH range · prior RTH a down day · gap ≥ −1.0% · LONG · MES+MNQ · 10:00→15:55 · lag-1 Calm | `CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md` |
| caps | swing/calm 5.0%, stress 10%, NKD 6%, family Normal+Calm 5.0% | the committed Track 1 candidate |
| `slippage_ticks_per_side` | 2.0 | legacy bootstrap default **and** `generate_replay_snapshots.py SLIPPAGE = 2.0` |
| `data_source_identity` | per-instrument parquet name + sha256 | computed |

**One thing that looked like a conflict and is not.** The arming gate sits at 14:00 while
the codebase's prose says 14:05 in a dozen places. Both are right: `run_scheduler.py:875`
schedules a `live_day` job at exactly 14:05, and `_CONT_SLOTS` runs 14:10→15:55 after it.
The 14:00 gate is placed one beat **ahead** of the 14:05 slot so that slot sees stops already
armed. Nothing to reconcile.

---

## 4. UNKNOWN / BLOCKER — three fields, not filled

A default here would hash cleanly and silently claim a setting nobody chose. The script
carries a sentinel and refuses to write any non-scratch path while one is present.

| field | why it is blocked | who decides |
|---|---|---|
| `spy_short_filter` | **No such filter exists anywhere in the repo.** The only occurrences of the name are in `global_index/route_params.py` itself — a field *this session* declared in Stage 1 with no counterpart on the other side. Either the Track 1 spec means a filter nobody has written, or the field is surplus and should come out of the contract. | project owner |
| `spy_short_lookback` | Same — no definition but the field list. | project owner |
| `fill_law` | Two laws are both live. The promotion artifacts were built with **every bar gap-eligible**; the production engine fills at the open only after a real break of more than 15 minutes. Measured cost of the production law on the NKD sleeve: floor −$5.36, 2025 $0, 2026 −$3.21. Small, but it is a different exit rule and the route cannot claim both. | project owner |

The first two are worth naming for what they are: **a contract I wrote in Stage 1 asked for
two values that nothing in the system can supply.** That is a defect in the contract, not a
missing measurement, and it will not fix itself by being carried forward.

---

## 5. Tests

| suite | result |
|---|---|
| `scratch/test_track1_stage2_equivalence_bootstrap_20260822.py` | **8 passed** |
| `scratch/test_track1_route_checkpoint_stage1_20260822.py` | 77 passed |
| `scratch/test_slot_telemetry_20260822.py` | 23 passed |
| the five baseline files | 44 passed |
| | **152 total** |

Two of the eight exist only to prove the other six can fail — the comparison mutation
(test 2) and the anchor mutation (test 8, which is shown going red on a wrong day, a wrong
position, **and** a missing instrument). The pinned lists (`EXPECTED_ALL_DAYS`,
`EXPECTED_PARAM_FIELDS`) are literals in the test file, independent of the modules under
test, because a parametrisation that reads its expectations from the thing it tests shrinks
instead of failing — which already happened once in this project.

**Test 2 failed on its first run and the fixture was at fault**, not the harness: synthetic
trades carried a float `exit_day`, which `compare()` filters on, so the expected list came
out empty and the control passed on nothing at all. The fixture now uses real dates and
asserts `trades_expected == 3` before believing any "match".

`global_index/test_event_playback.py` deliberately not run — pre-existing hang.

## 6. Legacy files

`runner.py`, `signal_layer.py`, `replay_checkpoint.py` show no diff. `run_live_day.py` and
`run_scheduler.py` carry **only** the previously approved telemetry patch — still exactly
39 insertions / 2 deletions, and filtering the diff for any non-telemetry line leaves only
that patch's own comments and the `_shadow(...)` re-indent. Nothing in this pass touched any
of the five.

## 7. What remains

| | |
|---|---|
| **the three blocked fields** | a decision, not a measurement — see §4 |
| **position-axis anchor** | still unexercised against live evidence; it will exercise itself the first time the book is not flat at a cut |
| **1F telemetry phases** | `ckpt_load`, `ckpt_verify`, `bars_fetch_incremental`, `sleeve_update`, `ckpt_advance_write`, `oracle_replay`; belongs with the route code that has phases to time, and `oracle_replay` must stay out of the route p95 |
| **1G scheduler** | `_catch_up_maxhold` is startup-only; `_maxhold_done` / `_preflight_ok` are date-keyed and need a route dimension before a second route shares the process |
| **R0 host availability** | unchanged and still governing — 8 of the 9 most recent trading days had an S3 suspend, and the idle timer is already off, so `STANDBYIDLE 0` is not the remedy on this host |

## 8. Commands, as run

```
python scratch/track1_equivalence_harness_20260822.py
python scratch/track1_bootstrap_checkpoint_20260822.py
python -m pytest scratch/test_track1_stage2_equivalence_bootstrap_20260822.py -q   -> 8 passed
python -m pytest scratch/test_track1_route_checkpoint_stage1_20260822.py \
                scratch/test_slot_telemetry_20260822.py -q                        -> 100 passed
python -m pytest global_index/test_slot_overlap.py global_index/test_log_hygiene.py \
                global_index/test_scheduler_heartbeat.py \
                global_index/test_dashboard_live_snapshot.py \
                global_index/test_scheduler_shadow_verify.py -q                   -> 44 passed
```
