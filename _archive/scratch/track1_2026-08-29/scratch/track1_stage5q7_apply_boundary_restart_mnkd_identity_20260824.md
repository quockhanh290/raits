# Stage 5Q-7 — the repair applied, and the third name MNKD was always missing

**2026-08-24, 20:15–20:50 ET ·** all Track 1 windows closed, next is NKD at 01:10 ·
**parquets MNQ/MYM/M2K mutated through the approved appender**, snapshotted and verified ·
MNKD parquet **not** touched · MES **not** touched · no order · no confirmation file ·
`TRACK1_ORDERS_APPROVED` unset · B1 still blocking · overlap guard **not** weakened ·
no evidence row deleted or rewritten · **scheduler and backend NOT restarted — the command was
blocked by this environment's permission gate** · no commit.

---

## Verdict: **NOT_READY** — but the blocker that had no command now has none left

| what 5Q-6 left open | now |
|---|---|
| MNQ/MYM/M2K partial boundary bars | **repaired and verified** |
| **B-5R-G — MNKD, 1,052 bars disagreeing, cause unknown** | **CLOSED.** Wrong symbol. Fixed, tested, proven end to end |
| `spy_refresh_pm` not registered | still not — **the restart was blocked** |
| `--repair-boundary` not in the running argv | still not — same restart |
| — | **B-5R-H (new):** every append stores the in-progress minute, so the repair moves the bad bar rather than removing it |

One thing is better than any of this made likely: **tonight's NKD window is judgeable, with no
restart needed.** The scheduler spawns each slot as a fresh subprocess
(`run_scheduler.py:1281`), so the MNKD fix is live the moment 01:10 arrives.

---

## Part A — live state before anything was touched

```text
ET 20:17     every Track 1 window closed; next slot NKD 01:10; safe to write
scheduler    pid 28696  pythonw -m global_index.run_scheduler --port 4002
                        --shadow-resume --track1-only-shadow   started 09:25:31 ET
backend      pid 11720  monitor/start_backend.py --ibkr-port 4002 --api-port 5002
track1_mode  track1-only-shadow
blocking     ['B1_broker_account_or_legacy_retirement']   orders_possible=False
stop_trading False   confirmation False   track1_orders_approved False
```

Not inferred — read out of the running system:

```text
scheduler log 07:25:32       "Jobs (100):"        spy_refresh_pm occurs 0 times in the log
today's pre-flight argv       -m global_index.update_ibkr_daily --port 4002
                              ...no --repair-boundary. Source only.
backend mirror                SPY_REFRESH_PM present: False
```

Evidence, all durable and none of it touched by this stage:

```text
window_coverage_20260824.jsonl   52 rows   13:55 local
slot_timing_20260824.jsonl       42 rows   13:55 local
audits/track1_audit_20260824.jsonl  8 records  14:15 local
explanations/                    absent — every slot refused, so there was nothing to explain
```

---

## Part B — the repair, applied

Measurement first (the 5Q-6 dry run, re-read; parquets unchanged since 11:46 so the inputs had
not moved): exactly MNQ, MYM, M2K repairable, MES clean, `outside_window: []` on all four — the
final bar was the *only* disagreement anywhere.

```powershell
python -m global_index.update_ibkr_daily --repair-boundary --symbols MNQ MYM M2K
```

```text
MNQ   alignment over 2566 shared bars — median +0.0000, IQR 0.0000
      boundary bar 2026-08-24 17:45:00 — completed: ['close', 'high', 'volume']
      snapshot -> NQ_continuous_1m_8y.parquet.pre5q5-20260825T002116Z.bak
      replaced and verified by re-read   (3,357,495 bars, history-check OK)
MYM   completed: ['volume']              (3,314,375 bars, history-check OK)
M2K   completed: ['high', 'volume']      (2,951,381 bars, history-check OK)
exit 0
```

That alignment line is the strongest thing in this report: **median +0.0000 and IQR 0.0000 over
2,566 shared bars.** The feed and the file agree exactly everywhere except the one minute the
previous fetch stopped in.

Verified after, not assumed:

```text
NQ_continuous_1m_8y   d231a957... -> c0ae9d3c...   CHANGED
YM_continuous_1m_8y   bda0c1fb... -> 272003cd...   CHANGED
RTY_continuous_1m_8y  a4789be8... -> e4e2e1c4...   CHANGED
ES_continuous_1m_8y   99da6feb... -> 99da6feb...   untouched
NKD_continuous_1m_8y  a761a36b... -> a761a36b...   untouched
snapshots: exactly three, one per touched file
index tz: None (naive) on all three — the storage convention survived
columns:  open, high, low, close, volume — unchanged

MNQ 2026-08-24 17:45  open 29119.25  high 29125.0  low 29118.25  close 29125.0  vol 1801.0
MYM 2026-08-24 17:45  vol 182.0
M2K 2026-08-24 17:46  high 2997.7  vol 15.0
```

Every value is exactly what the measurement predicted, and `open`/`low` are untouched.

### The change I have to declare, because I caused it

The updater is an appender. Running it at 20:20 ET did the repair **and** advanced each file by
~335 bars to now — its ordinary function, stated before I ran it. And the fetch stopped mid-minute,
so each file now ends on a **fresh partial bar**:

```text
MNQ  2026-08-24 20:20   high 29033.75 stored vs 29034.50 feed
MYM  2026-08-24 20:21   high 53467.0  stored vs 53469.0  feed
M2K  2026-08-24 20:21   high 2998.5   stored vs 2998.6   feed
```

Measured through the real guard, not reasoned about:

```text
MES   OK        asks MES   overlap 1185   appended 346
MNQ   REFUSED   overlap_disagreement — 1 of 1521, at 2026-08-24 20:20
MYM   REFUSED   overlap_disagreement — 1 of 1522, at 2026-08-24 20:21
M2K   REFUSED   overlap_disagreement — 1 of 1522, at 2026-08-24 20:21
MNKD  OK        asks NKD   overlap 1186   appended 341
```

The 13:45 bars are clean. The refusal moved to 20:20. **That is B-5R-H, and it is the real
shape of B-5R-F** — see below. What the repair did buy is permanent: today's 13:45 bars are now
correct in history, and they were days away from leaving the fetch overlap and becoming
unrepairable, exactly as Friday's did.

---

## Part C — B-5R-G: MNKD was being asked for the wrong contract

### The three names, each read from the layer that owns it

```text
runner name      MNKD    what this system calls it internally
history symbol   NKD     what the parquet was fetched under   (update_ibkr_daily._build_jobs)
order symbol     MNK     what goes on an IBKR order           (_RAITS_TO_IBKR)
```

Two of those were separated in August 2026, after live orders for the $0.50 micro were routed
to the $5 full-size contract and ran at **ten times** the intended size for four days —
−$1,400 at the broker against −$140 in the ledger, exactly 10.0000×.

The third was never separated. `IBKRBroker.fetch_bars` resolves whatever it is handed through
the **order** map, so the Track 1 live provider asked for MNK and compared the answer against
NKD history.

### The measurement, two arms, one variable

Read-only, client id 95, both arms travelling the same `on_frozen_clock` conversion keyed on
MNKD so the clock is held fixed. Same 1,186 shared minutes:

```text
fetch as MNK   1155 of 1186 disagree   worst gap 375.0   median gap where bad 25.0
fetch as NKD      0 of 1186 disagree   worst gap  0.0000
```

**The clock explanation was tested, not waved away.** `_refuse_overlap_disagreement`'s own
docstring records an earlier incident of **1,050** disagreeing Nikkei bars from a thirteen-hour
error with gaps of 900–1,000 points, and 5Q-6 measured 1,052 — close enough to be worth ruling
out properly. It is ruled out: the **signed** close difference has median **0.0**, and the
median gap where bad is 25 points, one tick on a 5-point grid. A clock error is a large
persistent offset in one direction. This is two order books on one index, symmetric.

*(5Q-6 counted 1,052 and this counts 1,155. Same phenomenon, different overlap: the parquet and
the fetch window both moved in between. The count was never the discriminating number.)*

### The fix, and the trap on the way to it

The obvious fix is to use `Contract.data_symbol`. **That would have been wrong on four of five
instruments:**

```text
inst   data_symbol   actually fetched as   file
MES    ES            MES                   ES_continuous_1m_8y.parquet
MNQ    NQ            MNQ                   NQ_continuous_1m_8y.parquet
MYM    YM            MYM                   YM_continuous_1m_8y.parquet
M2K    RTY           M2K                   RTY_continuous_1m_8y.parquet
MNKD   NKD           NKD                   NKD_continuous_1m_8y.parquet
```

`data_symbol` is the **file stem**. Reaching for it would have sent all four basket instruments
at the full-size E-mini contracts to repair the one that needed repairing — the same defect as
the original incident, in reverse and four times over.

The only truthful answer to "what was this history fetched as" is the code that fetched it. So
`update_ibkr_daily.history_ibkr_symbol()` is **derived from `_build_jobs`**, the job table that
built the files, and `track1_live_source.history_symbol()` delegates to it rather than keeping
a table of its own. Two tables is how MNKD reached the full-size contract to begin with.

```text
inst   BARS fetched as   ORDER routed to
MES    MES               MES
MNQ    MNQ               MNQ
MYM    MYM               MYM
M2K    M2K               M2K
MNKD   NKD               MNK      <- the split, explicit
```

`point_value` was not touched: MNKD stays $0.50, NKD stays $5.00. A multiplier drives sizing,
risk and realised P&L; it has never been able to move the price of a bar, and "fixing" prices
with it is pinned as a failing test.

### Proven at the call site, end to end

```text
live_frame("MNKD")  ->  code: ok   overlap_checked: 1186   live_rows_appended: 341
                        provider asked for: NKD
```

The first MNKD live frame that has ever been built in this sequence.

### Tests

16 new tests, and **8 of 8 mutations turned the right one red** — applied in process with
`unittest.mock.patch`, so nothing was written to disk and there is no restore to get wrong:

| | mutation | test that went red |
|---|---|---|
| M1 | the provider stops translating | provider asks for NKD |
| M2 | answer with `data_symbol` | the four basket instruments unchanged |
| M3 | answer with the order symbol | provider asks for NKD |
| M4 | order map loses MNKD | orders still go to MNK |
| M5 | the two identities made equal | they must differ |
| M6 | job table stops being the authority | derivation follows `_build_jobs` |
| M7 | `point_value` "fixed" to 5.0 | point_value describes the micro |
| M8 | the recorded evidence loses an arm | evidence sits beside the fix |

### One thing this stage did not fix, and names instead

`runner.py:1592` and `run_live_day.py:677` also call `broker.fetch_bars(inst)` with runner
names, and `run_live_day.py:88` sets `NKD_INST = "MNKD"`. **The legacy route has the same
defect.** It is not fixed here: that path is not what this stage was scoped to, legacy strategy
jobs are not registered in track1-only mode, and B1 blocks orders regardless. It should be
closed before legacy is ever run against Nikkei again.

---

## Part D — the restart: **blocked, not skipped**

```powershell
python monitor\ops.py restart --scheduler --track1-only-shadow --yes
```

Refused by this environment's permission gate. It stops and starts live processes, so that is
the gate working. It was not worked around. `restart --help` re-verified: there is no
`--backend` flag; backend-only is `--no-scheduler`.

Consequently `spy_refresh_pm` and `--repair-boundary` are still source-only, and the running
scheduler still reports **100 jobs**. The backend mirror also lacks the row, so the two agree —
they should agree again at **101** after both restarts, and disagreeing in between is the thing
to watch.

**Still the right moment: tonight, before 01:10 ET.** Today's windows have all closed *and been
audited*; the eight records are written. A scheduler started this evening covers the NKD window
completely. The cost is unchanged and already accepted: any future audit of 2026-08-24 will read
its closed windows as `window_closed_before_scheduler_start`, so read today's verdicts from the
records already written rather than re-deriving them. Nothing is deleted.

---

## Part E — the audit, read-only

`--dry-run`, wrote nothing; the eight records still stand at 8 rows, mtime 14:15 local:

```text
global_nkd     NOT_ENOUGH_DATA_YET  window_closed_before_scheduler_start
roska4_calm    FAIL   coverage_unobserved, missing_slot_ids, no_timing_records
roska4_stress  FAIL   p95 3.1   24 slots (gate_refused:stale, overlap_disagreement)
roska4_swing   FAIL   p95 2.4   23 slots (overlap_disagreement)
DAY 2026-08-24 FAIL   + the committed gate verbatim
```

Unchanged, and correctly so: this is a record of what happened today, and nothing done tonight
can or should alter it.

---

## Part F — tests

| | result |
|---|---|
| 16 suites incl. the new MNKD identity file | **540 passed, 0 failed** |
| Stage 5Q-7 mutations | 8 red, 0 still green |

**Three stale tests repaired, each for a stated reason** — none of them a regression from this
stage's code:

1. `test_no_snapshot_appeared_beside_a_real_parquet` asserted no `.pre5q5-*.bak` may exist
   anywhere. An **approved** repair legitimately created three. A guard that reads "none may
   exist" cannot tell that from "this suite made one", so it is now anchored to the set present
   at import: the suite must add none. Still falsifiable, no longer wrong.
2. Three 5Q-3 tests read `window_coverage_20260824.jsonl` while the ledger had written
   `..._20260825.jsonl`. `window_ledger` names its file by **UTC date**
   (`window_ledger.py:121`) and it was 00:36 UTC. The reader now derives the stem by the
   ledger's own rule — derived, not globbed, so it still asserts that the row landed where the
   reader will look. The one line that writes a *fixture* for the audit stays on the session
   day, which is what the audit reads.
3. Stage 5N pinned the default schedule at 60 jobs. Stage 5Q-5 deliberately made it 61. Pinned
   again at 61, plus an assertion that the new job is the reason.

Finding 2 is worth keeping: **the ledger names files by UTC date and the audit reads by session
date.** They agree except between 20:00 ET and midnight ET. No Track 1 window falls in that
band, so production is unaffected today — but a window that ever moved there would write its
rows into a file the audit does not open.

---

## Blockers before 5R

| id | what | state |
|---|---|---|
| ~~B-5R-G~~ | MNKD fetched the wrong contract | **CLOSED** — measured, fixed, 16 tests, 8 mutations |
| ~~B-5R-D~~ | today's three partial boundary bars | **CLOSED** — repaired and verified |
| **B-5R-H** *(new)* | the appender stores the in-progress minute, so every run leaves a fresh partial bar; `--repair-boundary` fixes the *previous* one | **open** |
| B-5R-E | `spy_refresh_pm` registered | open — needs the restart |
| B-5R-F | `--repair-boundary` in the running argv | open — same restart |
| B-5R-I | legacy `fetch_bars("MNKD")` has the same symbol defect | open, out of scope here |
| B-5R-C | NKD after 2026-11-01 | open, reported as WARN |
| B1 | the order gate | open by design; orders remain impossible |

### B-5R-H, stated properly, because it changes what the restart can promise

`update_ibkr_daily` appends `new_bars[new_bars.index > last_existing]` and the fetch always ends
inside an open minute while the market trades. So **every run stores one partial bar**, and
`--repair-boundary` repairs the *previous* one at the *next* run. Today's evidence shows both
halves of that: the morning slots refused on Friday 13:45, and the swing slots — which ran after
the 13:45 pre-flight — refused on Friday 13:46, an interior bar nothing had repaired.

With `--repair-boundary` live, a bad bar poisons the two-day overlap for about one day instead
of two. It does not reach zero. The cure is one step earlier: **do not store the in-progress
minute** — drop the final bar when its minute has not closed. That is a behaviour change to the
shared 13:45 job that also writes legacy's data, so it is named here with its measurement rather
than slipped in tonight. It needs its own stage: measure what dropping the last minute costs the
route, then change it.

Until then, expect exactly **one** refusing bar per basket instrument per morning. MNKD is not
affected — NKD's own boundary bar was last written at 13:46 ET and the current fetch agrees with
it on all 1,186 shared minutes.

---

## Files

**Production**

```text
global_index/update_ibkr_daily.py     + history_ibkr_symbol(), derived from _build_jobs
global_index/track1_live_source.py    + history_symbol(); IBKRBarProvider now fetches the
                                        HISTORY symbol instead of the runner name
```

**Production data — changed, deliberately, with approval**

```text
data/cache/futures/NQ_continuous_1m_8y.parquet    boundary bar repaired + 335 bars appended
data/cache/futures/YM_continuous_1m_8y.parquet    boundary bar repaired + 336 bars appended
data/cache/futures/RTY_continuous_1m_8y.parquet   boundary bar repaired + 335 bars appended
  each snapshotted to *.pre5q5-<stamp>.bak first, and verified by re-reading after
```

**Scratch**

```text
scratch/track1_stage5q7_mnkd_identity_probe_20260824.py    the two-arm measurement (read-only)
scratch/test_track1_stage5q7_mnkd_identity_20260824.py     16 tests
scratch/track1_stage5q7_mutations_20260824.py              8 mutations, all red
scratch/_track1_stage5q7_mnkd_identity.json                the measured evidence
scratch/test_track1_stage5q5_freshness_boundary_20260824.py    snapshot guard anchored
scratch/test_track1_stage5q3_live_frame_splice_20260824.py     ledger stem derived
scratch/test_track1_stage5n_nkd_track1_ownership_20260824.py   inventory pin 60 -> 61
```

No runtime evidence row was deleted or rewritten. MES and MNKD parquets are byte-identical.

---

## Operator page — the exact next commands

```powershell
# 1. Bring the corrected scheduler up. TONIGHT, before the 01:10 ET NKD window.
python monitor\ops.py restart --scheduler --track1-only-shadow

# 2. Let the dashboard learn about the new job.
python monitor\ops.py restart --no-scheduler --track1-only-shadow

# 3. Confirm.
python monitor\ops.py status
```

**After step 1, check:** job count **101** in track1-only mode · `spy_refresh_pm` at 16:20 ET ·
`SPY_REFRESH_PM` in the dashboard mirror · `--repair-boundary` in the 13:45 pre-flight argv ·
legacy strategy jobs **0** · Track 1 strategy/safety/audit **70 / 11 / 5** ·
`orders_possible=False` with `B1_broker_account_or_legacy_retirement` still blocking.

**Tomorrow morning, after the 10:00 and 10:35 windows**, read the audit and expect the basket
sleeves to refuse on exactly **one** bar each — 2026-08-24 20:20/20:21. That is B-5R-H, it is
predicted, and it is not a new fault. **NKD should be clean.**

```powershell
python -m global_index.track1_shadow_audit --latest --all --dry-run
```

**Do not** run `update_ibkr_daily` outside its 13:45 slot to try to clear that bar: while the
market trades, every run stores a new one a minute later.
