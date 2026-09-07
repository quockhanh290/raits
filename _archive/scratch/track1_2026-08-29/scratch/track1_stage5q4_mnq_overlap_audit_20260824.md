# Stage 5Q-4 — the MNQ overlap mismatch, and the day the data can't cover

**2026-08-24 ·** scheduler **not** started, stopped or restarted (pid 28696, unchanged) ·
backend **not** restarted · **no IBKR connection made** · no order · no confirmation file · no
`live_positions` or checkpoint written · **no parquet mutated** — all five still carry their
Friday 13:45–13:47 ET mtimes and no `.bak` exists beside any of them · every test write went
to `tmp_path` · no commit · `_refuse_overlap_disagreement` **not** weakened.

---

## Verdict: **MNQ MISMATCH CONFIRMED — repair tool built, deliberately NOT applied. Two blockers named, one of them bigger than the bar.**

The parquet is the wrong side, with high confidence and for a reason that is directional
rather than a judgement call. But the repair is a one-way write to shared history, applying it
needs a broker connection that would contend with the running Stress slots, and repairing this
bar would fix today only — the same bar is written fresh at every 13:45. So: measured, tooled,
handed over.

---

## Part A — what was measured

### The disputed bar

| | |
|---|---|
| file | `data/cache/futures/NQ_continuous_1m_8y.parquet`, 3,355,780 rows |
| **last bar in the file** | **2026-08-21 13:45:00-04:00 — the disputed one, 0 bars from the end** |
| stored | `open 29404.50 · high 29408.00 · low 29400.25 · close 29404.50 · volume 1399` |
| live feed says | `low 29395.75` |
| gap | **4.50 points, in `low` only** |
| scope | **1 of 1186 shared timestamps** |
| file mtime | 2026-08-21 13:46:16 ET — Friday's 13:45 pre-flight |

**Twelve independent fetches agree.** Every Stress slot from 10:35 to 11:15 ET recorded the
identical detail — same timestamp, same stored value, same feed value, same 1-of-1186. That is
the "is the feed internally consistent across repeated reads" question answered without
connecting to anything: twelve separate broker fetches an hour apart, all saying the same
thing, already on disk in the window ledger.

### Two things make the parquet the wrong side

**Direction.** The feed's low is **lower** than the stored low. A bar captured while its minute
is still running can only have a low that is too HIGH — the minute has not finished falling.
The error points the one way a partial bar can point.

**Position.** It is the file's last bar, written by the fetch that ended the append.

And `open` and `high` **agreed exactly**: the guard compares `open, high, low, close` in that
order and raises on the first column that differs, so the two before `low` matched. `close`
was never reached, so its state is unknown — which matters below.

### The mechanism, proven by reading the code rather than inferred

`global_index/update_ibkr_daily.py:548`

```python
new_only = new_bars_adj[new_bars_adj.index > last_existing]
```

**Strictly newer.** The bar that was last in the file is never re-fetched, never compared,
never rewritten. The dedupe two lines later (`~updated.index.duplicated(keep="last")`) would
prefer the newer copy — but no duplicate ever reaches it, because `new_only` already excluded
that timestamp.

So a partial boundary bar is **permanent**, and tomorrow's 13:45 will create another one at
whatever minute it happens to stop on. This is not a Friday problem.

### Scope across instruments — and what could not be measured

| instrument | today's evidence |
|---|---|
| **MNQ** | **disagrees.** 1 bar, measured 12× |
| **MES** | **agrees.** The 10:00 ET Calm slot reached `splice` and died on the column mismatch — and the overlap check runs *before* the splice, over instruments in sorted order, so MES passed it |
| **MYM, M2K** | **not exercised today.** The Normal-R4 slots at 14:05 ET are the first to touch them |
| **MNKD** | **not exercised today.** The NKD slots at 01:10 ET tomorrow |

Their parquets end at 13:44 (MES), 13:46 (MYM), 13:46 (M2K) and 02:47 JST (MNKD) — each the
minute its own fetch stopped on, each a boundary-bar candidate by the same mechanism.

### A measurement that failed, reported as a failure

I tried to answer "is this systemic across history" offline, by finding partial bars from their
volume. **It does not work, and the numbers say so:**

- the first probe compared each bar to its same-day neighbours and flagged 76–99 bars over
  29–34 days — two or three a day, every day, every instrument. That is the lunchtime lull,
  not a daily defect. A result that full should make you suspect the tool.
- the second controlled for time of day, comparing each bar to the **same clock-minute** on
  surrounding days. Better, and still not usable: 13:45 volume across the last twelve sessions
  runs 55–1137 (MES) and 545–2973 (MNQ). A 5–20× natural spread cannot resolve a partial bar.
- decisively: **the bar we KNOW is wrong is not flagged** (MNQ 13:45, ratio ≈0.9), while one
  that IS flagged — MYM 2026-08-21 13:46, 15 contracts against a usual 66, ratio 0.227, and it
  is that file's last bar — is not known to be wrong.

So volume is not the discriminator. **The historical frequency is unmeasured**, and the only
instrument that can measure it is a broker re-fetch of past windows compared bar by bar —
which is exactly what the tool below does in dry run.

What IS established: the *mechanism* is systemic and deterministic; the *observed corruption*
is one bar.

---

## Part B — the freshness gap, and it is worse than "morning D-1"

Measured, read-only:

```text
global_index/preflight_state.json   last day 2026-08-21 : true
spy_daily_live.csv                  last date 2026-08-20
required_data_through(Mon 11:30 ET) 2026-08-21
regime_csv                          stale — last date 2026-08-20 is before the required 2026-08-21
freshness allow                     False
```

**The 13:45 pre-flight marks a day `true` that its own SPY update cannot cover.**
`update_spy_csv` fetches `[fetch_from, today]` from Polygon at 13:45 ET; the day's daily bar
does not close until 16:00. So the CSV gains day **D−1** at day **D**'s pre-flight — while
`required_data_through` returns **D** from 13:45 onward. The requirement and the file are one
business day apart, and they stay one business day apart.

Grid, evaluated against the real gate:

```text
Fri 14:00  required 2026-08-21  regime_csv stale   allow=False
Mon 09:00  required 2026-08-21  regime_csv stale   allow=False
Mon 11:30  required 2026-08-21  regime_csv stale   allow=False
Mon 14:00  required 2026-08-24  regime_csv stale   allow=False
Tue 09:00  required 2026-08-24  regime_csv stale   allow=False
```

*(The grid's one `allow=True` row, Friday 12:00, is an artefact of testing a past instant
against today's file — on Friday at noon the CSV held Wednesday, not Thursday. Named rather
than reported as a passing window.)*

The 13:45 pre-flight is the **only** data refresh in the schedule — confirmed by reading the
scheduler, which runs `update_ibkr_daily → update_spy_csv` and nothing else. There is no later
job that could close the gap.

**Consequence.** `shadow_live` is a freshness-BINDING mode: an accepted admission with the gate
refused is refused outright. So no Track 1 candidate can be admitted at any instant, today or
any day, until this is resolved. Slots still observe, still record and still refuse by name —
which is why the audit machinery built over the last four stages is reporting rather than
hiding it.

Not implemented here, and not a small change: it needs either a second SPY refresh after the
close, or a requirement that asks for D−1 rather than D. Both are decisions about what the
route considers fresh. Named **B-5R-E**.

---

## Part C — the repair decision

**Option 2, built and not run.**

`scratch/track1_stage5q4_repair_boundary_bar_20260824.py` — dry run by default.

```powershell
# measures, writes nothing to the parquet
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ

# what an apply needs, and it is deliberately awkward
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ ^
    --apply --expect <sha256 printed by the dry run>
```

Every guard exists because the alternative has already cost this repo something:

| guard | what it stops |
|---|---|
| dry run by default | the only mode that runs without a second flag |
| `--expect <sha256>` | a repair measured against one version of the file landing on another |
| snapshot first, re-read and hash-checked | an in-place parquet write once made a `$52,936` baseline unreproducible, and the "frozen" copy taken afterwards was already contaminated |
| bounded window | a disagreement outside the last N minutes **refuses the whole run** — that is a different problem wearing a boundary bar's clothes |
| bounded count | more than `--max-bars` differing is a feed or contract question, not a boundary repair |
| index unchanged | a repair replaces bars; it may never add or remove one |
| verify by re-reading | a write that did not land is reported as a failure, not assumed |

It reuses `project_to_frozen_columns` from 5Q-3 rather than reimplementing the comparison: a
repair that compared on different columns from the ones the route joins on would be repairing
a different question.

### Why it was not applied

1. **Only `low` has been compared.** The guard stops at the first differing column, so `close`
   and `volume` on that bar are unmeasured. The tool would fetch and compare all five — but
   that needs a connection.
2. **Applying needs a broker**, and a manual fetch would open a second client while the Stress
   slots fetch on client id 89 every five minutes. Two clients contending for one id is a
   failure this project has already paid six entry slots for.
3. **It fixes today only.** Tomorrow's 13:45 writes a fresh boundary bar. The durable fix is in
   the appender, not in the file — named **B-5R-F** below.

Option 3 (dropping the final parquet bar at runtime) was **rejected**: it changes the frame
every sleeve reads, for every instrument, on every slot, to work around one bar — and it would
silently change what a frozen-window backtest computes on. The guard is right; the data is
wrong; the data is what should move.

---

## Part D — tests

| Suite | Result |
|---|---|
| **Stage 5Q-4** `test_track1_stage5q4_overlap_and_repair_20260824.py` (new, 26) | **26 passed** |
| **Stage 5Q-4 mutation harness** (new, 9) | **9 / 9 detected**, two files restored byte-for-byte |
| Regression (5Q-3, 5Q-2, 5Q-1, 5Q, 4B, 4C, 5E, 5F, 5Z, 5P) | **413 passed, 1 skipped** |
| Read-only probes | 2, output to `scratch/` only |

The nine mutations, each restoring a guard's absence:

```
N1  the overlap guard gains a price tolerance        -> the untouched-guard test reds
N2  the guard warns instead of refusing              -> the hard-refusal test reds
N3  the tool applies by default                      -> the CLI default test reds
N4  --apply no longer needs --expect to match        -> the hash-guard test reds
N5  a disagreement outside the window is repaired    -> the window-bound test reds
N6  any number of disagreeing bars is repaired       -> the count-bound test reds
N7  the repair writes without snapshotting           -> the snapshot test reds
N8  a dry run falls through into the apply path      -> the dry-run test reds
N9  the repair does not verify by re-reading         -> the injected-failure test reds
```

**N1 is the one that matters.** The tempting "fix" for today is a price tolerance wide enough
to swallow 4.5 points. That would make the route join a frame it knows is wrong, silently, for
ever — deleting the only thing that noticed.

### Three of my own instruments were wrong, and are recorded as such

- **the volume probe** (twice) — described above; a tool that flags the wrong bars and misses
  the right one is not a measurement, and I report no frequency because of it;
- **N8's first form** made the repair overwrite bars that already agreed. Undetected 0/0/0,
  because writing a value that is already there changes nothing. There was no guard to break;
- **N9's guard had no reachable failure** in the harness — in every ordinary case the write
  lands, so `remaining` is empty whether or not anything checks it. Fixed by adding a test that
  injects a write that does not land, which is what the branch exists for.

And once more, the substring-over-prose mistake: my first "the guard was not weakened" test
scanned the function's text for the word *tolerance* and went red on its own docstring
sentence *"No tolerance to tune"*. **Third time in these stages.** It now parses the function's
AST and asserts the set of numeric literals is `⊆ {0, 1, 1e-6}` — a check that can only fail
on a real new threshold.

---

## Blockers before Stage 5R

| id | what | state |
|---|---|---|
| **B-5R-D** | MNQ 2026-08-21 13:45 ET, `low` off by 4.5 pts. Refuses every Stress slot; MNQ is in the swing basket too | **open** — measured, tool ready, not applied |
| **B-5R-E** | the 13:45 pre-flight marks a day true before that day's SPY close exists, so the regime CSV is permanently one business day behind what the freshness gate requires. **No candidate can be admitted at any instant** | **open — the largest one** |
| **B-5R-F** *(new)* | `update_ibkr_daily` appends strictly-newer, so every 13:45 leaves a partial boundary bar that is never revisited. B-5R-D is one instance of it | **open** |
| **B-5R-C** | NKD after 2026-11-01: 12 of 22 ET slots outside the Tokyo decision band | open, reported as WARN |
| **B1** | the order gate | open by design; orders impossible |
| ~~B-5R-A/B~~ | live-frame schema, uncaught `SpliceRefused` | closed by 5Q-3 |

**B-5R-E outranks B-5R-D.** Repairing the MNQ bar would let the Stress window join — and the
freshness gate would still refuse every admission. The shadow period cannot produce an accepted
decision until the regime CSV question is settled.

---

## Files

**Added** — all in `scratch/`, none is production code:

```text
scratch/track1_stage5q4_probe_parquet_tail_20260824.py       read-only probe A
scratch/track1_stage5q4_probe_boundary_bars_20260824.py      read-only probe B (failed instrument)
scratch/track1_stage5q4_repair_boundary_bar_20260824.py      the repair tool, dry run by default
scratch/test_track1_stage5q4_overlap_and_repair_20260824.py  26 tests
scratch/track1_stage5q4_mutations_20260824.py                9 mutations
scratch/track1_stage5q4_mnq_overlap_audit_20260824.md        this report
scratch/track1_stage5q4_mnq_overlap_audit_20260824.json      the same, machine-readable
```

**Changed:** the two docs below. **No production module was modified by this stage.**

The tool stays in `scratch/` because the case for promoting it is not made yet: it earns a
place in `global_index/` only once B-5R-F is decided, since the right answer may be that the
appender stops creating the problem and no repair tool is needed at all.

---

## Operator action

**Nothing to run, and one thing not to do.**

- **Do not apply the repair yet.** It needs a broker fetch that would open a second client
  beside the running Stress slots, and it would fix one day of one instrument while B-5R-F
  keeps writing new boundary bars.
- **Do not widen the overlap guard.** It is the only thing that noticed.
- **No scheduler or backend restart.** Nothing in this stage changed a production module.

**Two things worth watching without touching anything**, both of which are measurements this
route now takes by itself:

```text
14:05 ET today   the Normal-R4 slots are the first to touch MYM and M2K
01:10 ET tomorrow the NKD slots are the first to touch MNKD
```

If either sleeve reports `overlap_disagreement`, the mechanism is confirmed on a second and
third instrument; if they join cleanly, MNQ is the only file carrying a bad boundary bar today.
Either way the answer arrives in the window ledger without anyone connecting to anything.

When a repair is wanted, the measurement step is safe to run at any moment the Stress window is
closed — after 12:30 ET — and writes nothing:

```powershell
python scratch\track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ
```

---

## Follow-up (appended 2026-08-24, Stage 5Q-5)

Nothing above is rewritten.

**B-5R-E is fixed in code, in two halves.** The requirement was being asked of two data sources
with different availability. It is now split — `required_intraday_through` for the parquets and
`required_daily_close_through` (the last TRADING day before today) for the daily series, which
is what `RegimeLabels(lag_days=1)` actually reads. That half is LIVE: slots import it fresh.
The second half — a refresh that runs after the close — is a new 16:20 ET job, `spy_refresh_pm`,
and it is NOT live until the scheduler restarts.

One correction to this report's grid: it recorded `Fri 14:00 -> allow=False` as the true state.
Under the corrected contract that instant ALLOWS, and the old refusal was the bug. About ten
hours of every trading day were being refused for a reason that was not true.

**B-5R-F is fixed in code and OFF by default.** `update_ibkr_daily --repair-boundary` re-fetches
and replaces the final stored bar, but only when the feed's version is a COMPLETION of it —
open unchanged, low no higher, high no lower, volume no smaller. Anything else refuses by name.
It snapshots before writing and verifies by re-reading. The flag is absent from the scheduler's
argv, so today's 13:45 run is byte-identical to yesterday's.

**B-5R-D is still unrepaired.** The dry-run measurement in this report is still the first step;
the recommended repair is now `python -m global_index.update_ibkr_daily --repair-boundary
--symbols MNQ`, because it is the same code that prevents recurrence once enabled.

Full detail: `scratch/track1_stage5q5_freshness_boundary_report_20260824.md`.
