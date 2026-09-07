# Track 1 — Stage 1 implementation plan (resume-primary / replay-verified)

**2026-08-22 · plan and gates only.** No code was written, no production file was modified, no
scheduler / runner / monitor / IBKR connection was started, nothing was committed.

---

## Facts this plan is built on

Carried forward from `scratch/track1_checkpoint_resume_audit_20260822.md`, each measured:

- The **64 "no usable checkpoint"** rows are **not current coverage debt**. They fall entirely on
  2026-08-06 (16) and 2026-08-07 (48); 2026-08-10 → 2026-08-21 is **85 matched, 0 skipped, 100%
  coverage**. Root cause documented in `advance_day`'s own docstring and already fixed.
- The real blockers are: the **params-mismatch refusal has never fired in production**; params
  identity is **too narrow** for Track 1; the key space is **instrument-only**; `save()` **rewrites
  the whole dict**; and Stress / Calm A need **window-coverage records**, not historical checkpoints.
- **G3**: idle sleep is already disabled on this host (`STANDBYIDLE` = 0 on AC **and** DC). The
  failure class is manual / lid / button S3 suspend. `STANDBYIDLE 0` is **not** the fix here.
- **2026-08-04** `MAX_HOLD exit 09:31 ET` **did not run** — dropped beyond the 300 s grace. Startup
  catch-up closes the observed sequence; a running scheduler that sleeps through 09:31 without
  restart is still open.

## The one design rule the whole plan hangs on

Every Stage 1 artefact is a **new file**. Nothing in `runner.py`, `signal_layer.py`,
`replay_checkpoint.py`, `run_live_day.py` or `run_scheduler.py` is edited in Stage 1.

That is not caution for its own sake. Legacy's checkpoint is a live dependency of the only check that
closes the loop on live data; a Track 1 change that reaches into it puts the legacy evidence stream
at risk to buy nothing Stage 1 needs. Stage 1 ends with Track 1 provably correct **offline**, and
legacy byte-identical.

---

## Stage 1A — checkpoint schema v2 module

**Deliverable:** a new module, e.g. `global_index/route_checkpoint.py`, implementing v2 independently.
Not a subclass of, not an edit to, `replay_checkpoint.py`.

| | |
|---|---|
| **Files** | new: `global_index/route_checkpoint.py`. **Touched: none.** |
| **Isolation** | separate module, separate file path, separate `SCHEMA = 2`. `replay_checkpoint.load()` already refuses a schema it does not recognise (`:88`), so even a mis-pointed path fails closed rather than mixing |
| **Reuse** | `fingerprint()` is the one piece worth reusing verbatim — content-derived, tz-stripped, measured 0.54 s on 2.8 M rows, and its tz-stripping subtlety is hard-won. **Import it, do not copy it.** A copy would drift from the original exactly where the original's docstring says drift is fatal |
| **Tests** | round-trip save/load; schema-mismatch refusal; `pos` round-trip preserving `entry_day` / `entry_time` as `pd.Timestamp` (the shape `_pos_from_json` restores at `:69`) |
| **Rollback** | delete the file. Nothing imports it yet |
| **Gate** | v2 round-trips; a v1 file handed to the v2 loader is **refused**, and a v2 file handed to `replay_checkpoint.load()` is **refused**. Both directions asserted |

## Stage 1B — params hash builder + offline refusal tests

**This is the stage that closes the highest-value blocker.** The params-refusal branch has zero
production exercises; Stage 1B is where it is made to fire on purpose.

| | |
|---|---|
| **Files** | new: `global_index/route_params.py` (builder), `scratch/test_route_checkpoint_*.py` |
| **Isolation** | pure function of a config dict → `(readable_string, hash)`. No I/O, no engine import |
| **Tests** | one per field in §4: change exactly that field, assert the hash moves **and** the refusal reason is `params_mismatch`. Plus: identical config → identical hash across processes (no `PYTHONHASHSEED` dependence — use `hashlib`, never `hash()`) |
| **Rollback** | delete both files |
| **Gate** | **every field in the §4 list has a test that goes red when the field is removed from the hash input.** A field in the hash with no such test is a field nobody has proven is in it |

> The mutation discipline matters here more than anywhere: a params hash that silently ignores one
> input is exactly "fast and wrong", which is the trade `usable()`'s docstring says it refuses.

## Stage 1C — route-specific path and key space

| | |
|---|---|
| **Files** | new: the path constant lives in `route_checkpoint.py`. **`run_live_day.py` is not edited** — it already has `--checkpoint-path` (`:179`), so Stage 2 passes a different value; Stage 1 uses it only from tests |
| **Path** | `global_index/replay_checkpoint.track1.json` |
| **Key** | `routes[route].sleeves[sleeve].instruments[inst]` — see §3 |
| **Isolation** | different file *and* different key space. Legacy cannot address a Track 1 entry even if pointed at it, because it looks for a top-level `instruments` map |
| **Lost-update fix** | see §3. Read-modify-write of the whole file is retained (it is atomic today via `.tmp` + `replace`, `:95`), but the **merge is explicit and per-key**, and a writer may only touch keys under its own `route` |
| **Tests** | writing route `track1_candidate` leaves a `legacy_shadow` route's entries byte-identical; two sleeves on the same instrument coexist; concurrent-writer simulation loses nothing |
| **Rollback** | delete the file; nothing reads it |
| **Gate** | the "does not clobber another route" test fails when the per-key merge is removed |

## Stage 1D — window-coverage ledger

| | |
|---|---|
| **Files** | new: `global_index/window_ledger.py`; records to `window_coverage_YYYYMMDD.jsonl` |
| **Isolation** | append-only JSONL, its own file, read by nobody in Stage 1. Same shape as `slot_telemetry` — off unless an env var names a directory, never raises, never decides |
| **Tests** | see §5 |
| **Rollback** | delete the file |
| **Gate** | a simulated suspend across a window yields `window_unobserved`, **and** a genuinely quiet window yields `no_signal`, and the two records are distinguishable without reading any other file |

## Stage 1E — resume-vs-full-replay equivalence harness

| | |
|---|---|
| **Files** | new: `scratch/track1_equivalence_harness_*.py` |
| **Isolation** | offline, parquet-only. **No IBKR, no live bars, no runner.** Drives the engine directly, the way `shadow_resume_timing_audit` drove the logs |
| **Anchor** | before comparing anything new, the harness must reproduce a number already published — the natural one is the existing shadow record: **91 matches, 0 divergences** over 2026-08-10 → 08-21. If it cannot reproduce that, it is not comparing what the shadow compared |
| **Tests** | see §6 |
| **Rollback** | scratch only |
| **Gate** | anchor reproduced; then a deliberately corrupted resume state is **detected** (the harness must be shown able to fail) |

## Stage 1F — telemetry phases for resume-primary

| | |
|---|---|
| **Files** | none in Stage 1. The phase names are *declared* here and implemented in Stage 2 alongside the route code that has the phases to time |
| **Phases** | `ckpt_load`, `ckpt_verify`, `bars_fetch_incremental`, `sleeve_update` (per sleeve), `ckpt_advance_write`, `oracle_replay` |
| **Isolation** | `slot_telemetry.split()` / `timer()` already exist and are inert unless `RAITS_TELEMETRY_DIR` is set. No new mechanism |
| **Key rule** | `oracle_replay` is timed **separately and excluded from the route's p95**, or the oracle's cost contaminates the number the gate is about |
| **Gate** | deferred to Stage 2 — R7, p95 < 300 s hard, < 240 s target |

## Stage 1G — scheduler catch-up / availability review

**Review and write-up only. No scheduler edit in Stage 1.**

| | |
|---|---|
| **Files** | none. Output is a section in the Stage 2 plan |
| **What to settle** | `_catch_up_maxhold` (`run_scheduler.py:1132`) is **startup-only**, called once at `:1243`. A running scheduler that sleeps through 09:31 and is not restarted gets neither the cron run (dropped past the 300 s grace) nor the catch-up |
| **Shape of the fix, for Stage 2** | the predicate is already correct — *past 09:31 ET, weekday, `_maxhold_done[today]` unset*. Evaluating it on the **heartbeat** as well as at startup closes the hole with **no new job, no new trigger, no argv change**. Note `_maxhold_done` is keyed by date only and persisted, so it must gain a route dimension before a second route runs in the same scheduler process |
| **Gate** | Stage 2 may not add a Track 1 window to the scheduler until this is either fixed or explicitly accepted in writing with the residual named |

---

## 3. Checkpoint schema v2, in detail

```json
{
  "schema_version": 2,
  "routes": {
    "track1_candidate": {
      "sleeves": {
        "roska4_swing": {
          "instruments": {
            "MES": {
              "last_day": "2026-08-20",
              "fingerprint": "3367423:e36825ea00e221ae",
              "params": "arm_hour=14.0833;arm_tz='America/New_York';ema_period=50;...",
              "params_hash": "sha256:9f2c…",
              "data_source": "data/cache/futures/ES_continuous_1m_8y.parquet",
              "pos": null
            }
          }
        },
        "global_nkd":    {"instruments": {"MNKD": {"…": "…"}}},
        "roska4_calm":   {"instruments": {}},
        "roska4_stress": {"instruments": {}}
      }
    }
  }
}
```

`roska4_calm` and `roska4_stress` appear with empty maps **on purpose**: they are same-session sleeves
that need no historical checkpoint (§6 of the audit). Their coverage lives in the ledger, not here.
Present-but-empty says "this sleeve is accounted for"; absent would say "nobody thought about it".

### Fields

| field | notes |
|---|---|
| `last_day` | as v1 — `advance_day`'s rule (parquet's second-to-last session, on the parquet's own clock) is reused unchanged. It is the fix for the 2026-08-07 incident and must not be re-derived |
| `fingerprint` | `"<rowcount>:<content hash>"`, from the **imported** v1 `fingerprint()` |
| `params` | readable, sorted `k=v` string. Kept because `_param_id`'s docstring is right: a refusal has to be explainable, and eight hex digits explain nothing |
| `params_hash` | the thing that **decides**. §4 |
| `data_source` | which parquet the history came from. The fingerprint pins content, not provenance; two files can hold the same bars |
| `pos` | per **sleeve**, not per instrument — that is why the key space gained a level. Same serialisation as v1 (`entry_day` / `entry_time` as ISO strings, restored to `pd.Timestamp`) |

### Refusal reason codes

`usable()` in v2 returns `(last_day, pos)` **or** a reason, never a bare `None`:

| code | condition |
|---|---|
| `no_entry` | route / sleeve / instrument path absent |
| `bad_last_day` | `last_day` missing or unparseable |
| `fingerprint_rowcount` | row counts differ — **48 of the 64 historical skips were this** |
| `fingerprint_content` | row counts equal, hashes differ — **4 of the 64 were this** |
| `params_mismatch` | `params_hash` differs |
| `route_mismatch` | entry's `route` is not the caller's route |
| `schema_mismatch` | `schema_version` != 2 |

Splitting `fingerprint_rowcount` from `fingerprint_content` is not cosmetic: in the historical data
those two have different causes (a stale/half-held day versus bars rewritten under the entry), and
this session had to reconstruct the split by string-diffing two hashes out of log lines.

### Lost updates

Today `save()` writes the whole dict (`replay_checkpoint.py:95`). With one route that is safe; with
two it is a lost update — whichever writes last wins.

v2 keeps atomic whole-file write (`.tmp` → `replace`; do not weaken that) and adds:

1. **Read-modify-write under a lock file** (`replay_checkpoint.track1.json.lock`), so two processes
   cannot interleave.
2. **Per-key merge**: a writer loads the current file, replaces only keys under **its own** `route`,
   and writes back. It may not author keys under another route.
3. **A write-scope assertion**: after the merge, every key outside the writer's route must be
   byte-identical to what was loaded. This is the property Stage 1C's test asserts and the one that
   goes red if the merge is removed.

Cheaper alternative worth considering at Stage 2: **one file per route**. It removes the merge
problem entirely, at the cost of a second path to manage. If Stage 2 finds the lock adds latency
inside the runtime gate, take the per-file split instead — the schema is unchanged either way.

---

## 4. `params_hash` content for Track 1

Everything that changes which position the bars produce. Today's `params` covers three of these.

| group | fields |
|---|---|
| signal | `ema_period`, `max_hold_days` |
| stop | `stop_basis`, `stop_multiple` / `chandelier_atr_mult`, `stop_anchor` (entry vs bar extreme), `ratchet` on/off |
| arming | `arm_hour`, `arm_timezone` |
| filters | R4 context filter identity — `range_p90` threshold **and the window it was derived from** — plus `rel_volume_max`; SPY short filter (`below_sma50`, its lookback) |
| regime | `hmm_fit_end`, regime CSV identity (path + content hash), label lag (`lag_days`), the Calm gate definition |
| caps | `roska4_swing`, `roska4_calm`, `roska4_stress`, `global_nkd` gross/net, **and the Normal+Calm family cap** — they change which trades are *admitted*, so a stored admitted position depends on them |
| cost | `slippage_ticks_per_side`, commission basis |
| data | `data_source` identity per instrument, and the fill law in force (the artifacts were built with every bar gap-eligible; production's engine uses the >15-minute rule) |

**Rules.**

- `hashlib.sha256` over a canonical sorted rendering. **Never** Python's `hash()` — it is salted per
  process and would make the same config hash differently on every run.
- Floats rendered at fixed precision, so `2.5` and `2.50` cannot disagree.
- **A field that cannot be tested is not added.** Every entry above owes Stage 1B a mutation test.
- Thresholds derived from a window carry the window, not just the value: `range_p90 = 0.0123` is a
  different thing when derived from a different fit period.

---

## 5. Window-coverage ledger

**Separate from the checkpoint, on purpose.** A checkpoint answers *"what state did the last
observation leave?"*; the ledger answers *"did an observation happen at all?"*. Merging them would let
a missing observation look like a flat position.

### Windows

| sleeve | window | expected slots |
|---|---|---:|
| Calm A | 10:00 ET, single shot | 1 |
| Stress-MNQ | 10:35 → 12:30 ET, every 5 min | 24 |

### Records

```
{"ts":"…Z","route":"track1_candidate","sleeve":"roska4_stress","date":"2026-08-25",
 "event":"window_open","expected_slots":24}
{"ts":"…Z", … ,"event":"slot_observed","slot_id":"T1_STRESS_1105","seq":7}
{"ts":"…Z", … ,"event":"window_closed","expected_slots":24,"observed_slots":24,
 "outcome":"complete","signal":"no_signal"}
```

### The distinction that must survive

| outcome | meaning |
|---|---|
| `complete` + `signal: no_signal` | the window **was** observed and produced nothing. Safe |
| `complete` + `signal: entered` | observed, traded |
| `incomplete` | `window_closed` written, but `observed_slots < expected_slots` |
| **`unobserved`** | **no `window_closed` record exists for that date/sleeve at all** |

**Absence of `window_closed` is itself the signal**, which is what makes this fail closed: a suspended
host writes nothing, and nothing is precisely what the reader must treat as failure. A day whose
Stress window is `unobserved` or `incomplete` is **not usable as evidence** for that sleeve, and under
resume-primary it must also block a late entry — the entry price has moved, which is the same class
of error as the 2026-08-04 max-hold.

### Cross-checks

1. **Scheduler `HEARTBEAT STALLED`** — measured this session to match a real OS suspend **28 of 28**.
   A stall overlapping a window marks it unobserved. Costs nothing; the evidence is already written.
2. **Windows Power-Troubleshooter log** — authoritative where the scheduler is not: it recorded **39
   suspends** in the audit window against the scheduler's 28, because a suspend while the scheduler is
   down leaves no stall line. Optional, and the only source that catches that case.

---

## 6. Equivalence harness

**Compare:** resume-primary state against a full replay over the same window, per route / sleeve /
instrument.

**Open position** — `instrument · sleeve · direction · qty · entry_day · entry_time · entry_price ·
stop · target (Stress) · extreme/ratchet state`.

**Every trade closing after `last_day`** — `instrument · sleeve · direction · qty · entry_day ·
entry_time · entry_price · exit_day · exit_time · exit_price · exit_reason · points · pnl ·
hold_days`, compared **as an ordered sequence**, not a set: once a cap admits by priority, the same
trades in a different order are a different book.

**Tolerance: exact** to the stored rounding. No epsilon. The existing shadow achieves 91/91 exact;
introducing a tolerance now could only hide a regression from that standard.

**Promotion accounting:**

- **100% comparison coverage** over the declared window.
- **A skipped comparison is a failed day, not neutral.** This is the R1 wording that replaced "skips
  need reason codes" — and it is what would have caught 2026-08-06, a day with zero comparisons that
  the old phrasing would have read as "no divergence".
- **One divergence resets the promotion counter to zero** and blocks until the cause is named.
- The oracle keeps running after promotion (R8). A post-promotion divergence is a **rollback**
  trigger, not a ticket.

---

## 7. Deliberate offline tests

All offline, parquet-only, no broker, no scheduler. Each must be **mutation-checked**: break the
guard, confirm the right test goes red, restore.

| # | Test | Passes when |
|---|---|---|
| T1 | params mismatch refuses | changing any one §4 field → `params_mismatch`, and the readable string names the moved setting |
| T2 | route mismatch refuses | entry written under `legacy_shadow`, read as `track1_candidate` → `route_mismatch` |
| T3 | sleeve mismatch refuses | `roska4_swing` entry read as `roska4_calm` → `no_entry` (distinct key), never a silent hit |
| T4 | rowcount vs content categorised | append bars → `fingerprint_rowcount`; rewrite a middle bar keeping length → `fingerprint_content` |
| T5 | missing checkpoint fails closed | no entry → refusal, **no entries proposed**, distinct outcome recorded; explicitly **not** a silent full replay |
| T6 | stale checkpoint fails closed | `last_day` older than the declared max age → refusal even when the fingerprint matches |
| T7 | save preserves other routes/sleeves | write route A; every key under route B byte-identical; and the reverse |
| T8 | concurrent writers lose nothing | two writers interleaved under the lock → both sets of keys survive |
| T9 | schema cross-refusal | v1 file → v2 loader refuses; v2 file → `replay_checkpoint.load()` refuses |
| T10 | ledger distinguishes the two zeros | suspend simulation → `unobserved`; quiet window → `complete` + `no_signal` |
| T11 | hash is process-stable | same config, two processes, same `params_hash` |

T1 and T5 are the two that matter most: T1 is the branch that has **never fired in production**, and
T5 is the one that decides whether resume-primary can trade on a state it cannot prove.

---

## 8. Stage 1 exit criteria

Stage 1 is done — and Stage 2 may begin — when **all** hold:

1. Every test in §7 passes, and each has been shown to go red on its own mutation.
2. The equivalence harness reproduces the existing shadow record (91 matched / 0 diverged,
   2026-08-10 → 08-21) **before** being used to judge anything new.
3. `params_hash` covers every field in §4, each with its own mutation test.
4. The ledger distinguishes `unobserved` from `no_signal` without consulting any other file.
5. **Legacy is byte-identical**: no edit to `runner.py`, `signal_layer.py`, `replay_checkpoint.py`,
   `run_live_day.py`, `run_scheduler.py`; the artifact sha256 reproduction still matches; the
   scheduler job-table and per-slot argv diffs are empty; the five baseline test files still show
   44 passed.
6. Stage 1G's scheduler review is written down, with the residual heartbeat-catch-up hole either
   scheduled for Stage 2 or accepted in writing.

**Not in Stage 1, deliberately:** any scheduler job, any live or paper order, any monitor/dashboard
change, any edit to the five legacy files, and the runtime gate itself (R7 belongs to Stage 2, where
there is a route to time).

---

## 9. What this plan does not settle

- **R0 host availability is unchanged and still governs.** Nothing in Stage 1 makes a suspended host
  observe a window. Measured: 8 of the 9 most recent trading days had an S3 suspend, and the idle
  timer is already off, so `STANDBYIDLE 0` is not the remedy for this host.
- **The `run_day` cost of Track 1's two same-session sleeves is unmeasured.** Stage 1 is offline, so
  it produces no p95. The margin at stake is 84 s.
- **`_maxhold_done` and `_preflight_ok` are keyed by date only** and persisted. Before any second
  route runs inside the same scheduler process they need a route dimension, or Track 1's max-hold run
  will mark the day done and suppress legacy's.

## Artifacts

- this plan, and `scratch/track1_resume_primary_stage1_implementation_plan_20260822.json`
