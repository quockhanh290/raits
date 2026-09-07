# Stage 5ZO — proving a slot looked at data, not just that it decided

**2026-08-26, ET 02:20–04:20.** No orders · no confirmation file · `TRACK1_ORDERS_APPROVED`
unset · no `--allow-orders` · **I restarted nothing** · no runtime evidence written or edited ·
no old explanation row rewritten · no strategy, rule, cap or backtest-identity change · no
overlap, splice or freshness guard relaxed.

```text
UTC 2026-08-26 08:16 · ET 2026-08-26 04:16 EDT · Calgary 2026-08-26 02:16 MDT
```

---

## The ten answers

| | |
|---|---|
| 1. runtime/live file changed? | **no** — every evidence directory still at its baseline mtime |
| 2. where is the evidence written? | `global_index/track1_runtime/data_observation/data_observation_YYYYMMDD.jsonl` |
| 3. does every future decided slot require proof? | **yes**, once the stream exists for that day — WARN, not FAIL, and the reason is below |
| 4. what exactly is proven? | provider, three symbols, parquet identity, rows fetched/offered/kept, overlap count, splice code, frozen and final timestamps, frame size (§3) |
| 5. does it change decisions? | **no** — it reads what the join already recorded and computes nothing |
| 6. how are old slots treated? | `pre_observation_schema` — classified, never accused |
| 7. how does the dashboard show it? | one line in the existing Operational block, three shapes |
| 8. orders still impossible? | **yes** — three blockers |
| 9. next shadow window READY? | **yes** |
| 10. what remains before paper? | five items, none of them a design question |

---

## 1. The gap, found in the evidence rather than in the code

The 2026-08-26 night window passed its audit — twenty-two slots, all decided, no candidates,
p95 32.2 s. And the explanation row for its last slot said:

```text
TRACK1_NKD_0255   bar_timestamps: []   data_time: null
```

The ledger proved the slot **decided**. Nothing proved **what it looked at**. Those are
different claims, and on a route that has never traded they are indistinguishable: a slot that
fetched nothing, spliced nothing and found no candidate produces the same ledger row as one
that pulled a thousand bars and found no candidate.

One thing was already proven and is worth saying so it is not re-solved: `data_source_identity`
on that same row carries `<parquet path>:<sha256>`. The *history* side was provable. The
*live* side was not.

## 2. Nothing is recomputed

Every number in a row already existed on the objects the slot built while deciding.
`JoinedFrame` carries the provider, the rows offered, the rows kept, the overlap it checked and
the columns it dropped; the splice report inside it carries its own outcome code, the frozen
row count, the frozen last timestamp and the first live bar kept.

The writer reads those. It computes no feature, calls no detector and touches no rule — a
diagnostics path that recomputed anything would be a second implementation beside the one that
trades, and the two would disagree on exactly the day it mattered. Asserted by AST: the module
imports nothing whose name contains signal, detector, sleeve or params, and `instrument_row`
calls `as_dict` and no aggregation function at all.

## 3. What one row proves

```json
{"schema":"track1_data_observation/1","route":"track1_candidate","session_date":"…",
 "sleeve":"global_nkd","slot_id":"TRACK1_NKD_0255","mode":"shadow_live","provider":"ibkr",
 "outcome":"decided","decision_reached":true,"candidate_count":0,
 "instruments":[{
   "inst":"MNKD","history_symbol":"NKD","tradable_symbol":"MNK",
   "data_path":"…/NKD_continuous_1m_8y.parquet","data_identity":"…:334df407…",
   "live_rows_fetched":1186,"live_rows_offered":1200,"live_rows_appended":1186,
   "live_rows_offered_but_unused":0,"live_first_kept_ts":"…",
   "frozen_rows":2043688,"frozen_last_ts":"…",
   "overlap_checked_rows":37,"overlap_result":"ok","splice_result":"ok",
   "splice_notices":[],"dropped_columns":["average","barcount"],
   "dropped_open_final_bar":null,
   "dropped_open_final_bar_null_reason":"not_reported_by_the_join",
   "final_frame_first_ts":"…","final_frame_last_ts":"…","final_frame_rows":…}]}
```

**The three identities are kept apart** — runner name, history symbol, order symbol — because
they have already diverged once and a record printing one of the three and calling it *the
symbol* is the reason somebody would later compare the wrong two.

**One field is deliberately null.** Nothing in the chain records whether the provider's final
bar was still forming when it was handed over. The fetch is causal — it keeps bars at or before
the instant it was taken — but that is a different guarantee. So `dropped_open_final_bar` is
`null` with its reason beside it, never omitted and never guessed. It is a real residual gap
and it is named as one rather than filled in.

**No bar array, no prices.** A row that embedded bars would grow with the market and would put
price data into a stream whose purpose is provenance. A test walks the whole payload and fails
on any list longer than twenty items or any non-scalar leaf, and pins one row under 4 KB.

## 4. Where it is written, and where it is not

Appended to a dated file beside the other evidence streams, after the ledger row and wrapped —
the same two rules the signal diagnostics follow, and for the same reason: **the ledger row is
what the audit counts, and a diagnostics failure must never be the reason a slot loses it.**
Both asserted structurally: the observation call's line number is after the ledger call's, and
it sits inside a `try`.

Three cases, and the third is the one worth stating:

| the slot | writes |
|---|---|
| built a frame and decided | a full row |
| was refused before deciding | a refusal row naming the code — *nobody looked* and *we looked and were refused* call for different actions |
| never reached either | **nothing** — a row claiming an observation nobody made is worse than no row |

## 5. The audit — classify, do not accuse

A day with **no observation stream at all** is a day whose slots ran under an earlier version
of the writer. That is a fact about the software, not about the window, and it is recorded as
`pre_observation_schema`. Once the stream exists for a day, every decided slot in it is
expected to appear, and a missing one raises `decided_without_data_observation`.

**WARN, not FAIL**, and the justification is short. The ledger row already proves the slot ran
and decided; the observation row proves what it observed. A missing observation *weakens* the
evidence without contradicting it. Making it fatal would fail every window recorded before this
stage existed — which is not a finding about those windows. It stops being tolerable the day a
paper order is sent on a decision nobody can show the data for, and the readiness gate is where
that belongs.

Measured against the real evidence, read-only:

```text
global_nkd 2026-08-26 → PASS  (unchanged)
  data_observation: schema_state pre_observation_schema, records 0,
                    decided_slots 22, slots_without_data_observation []
```

Twenty-two decided slots, no stream, **no accusation and no downgrade.** The audit row also now
carries the provider counts, the refusals by reason, the splice results and the total live rows
fetched.

## 6. The dashboard

One line, inside the Operational block, beside the other runtime facts. Not a new section: the
panel already has a health block and a signal chip, and a third heading for a single sentence
would cost more attention than it returns.

```text
Data: IBKR · NKD · 1186 live bars checked · last 02:55 ET · splice OK
Data proof: not recorded by this slot version
Data refused: overlap mismatch
```

Three shapes because there are three states an operator acts on differently. No variable names,
no JSON, no thresholds — asserted, along with a length cap so it cannot wrap to three lines on
a phone and push the block past the fold.

## 7. Something happened mid-stage that I did not do

The scheduler and backend pids changed: **18096 → 18780 at 02:09:03**, and **30604 → 48760 at
02:09:16**, both Calgary. I restarted nothing. The operator did.

I checked rather than assumed, because a process table that disagrees with what I did is a
reason to stop. The restart was clean and in the same mode: same argv, `45 legacy strategy jobs
not scheduled`, 11 safety, 5 audit, 70 shadow slots, and **the seven pre-flight days restored**
— your repair survived it intact.

It also settles the liveness question, and in the opposite direction from what I first
assumed. My edits landed at 02:03–02:06; the restart came at 02:09. So the new processes picked
up everything, verified against the live API rather than reasoned about:

```text
5ZL regime_verify block   present
5ZM reporting block       present
5ZO data line on a job    "Data proof: not recorded by this slot version"
scheduler spy_refresh_pm  now carries --verify-strict
```

**Everything through this stage is live**, including 5ZL's strict post-close verification. The
slot writer needs no restart at all — slots run as fresh subprocesses — so the first Track 1
window after this will produce real observation rows.

## 8. Tests

**34 tests**, `scratch/test_track1_stage5zo_live_bar_pull_proof_20260826.py`. All ten items the
brief lists, plus the branches the code suggested: a join that cannot describe itself is
recorded as such; a refusal summary counts by reason; the writer records the provider the join
reported rather than a guess.

Three worth naming. The **end-to-end wiring test** — I added a `root` parameter to the slot
writer purely so one could exist, because a mechanism nobody has watched run is a trap this
project has already paid for twice. The **ordering test**, which reads line numbers out of the
AST to prove the observation row is written after the ledger row. And the **payload walk**,
which fails on any list long enough to be bar data rather than trusting a sentence that says
there is none.

## 9. Regression

**709 passed, 0 failed** — 5ZO, 5ZN, 5ZM, 5ZK, 5ZH, 5ZE, 5ZD, 5Q, 5Q1, 5P, the dashboard
backend and the realtime contract.

## 10. Files changed

| file | change |
|---|---|
| `global_index/track1_data_observation.py` | **new** — schema, writer, reader, summary, operator line |
| `global_index/run_live_day_track1.py` | captures the join, remembers refusals, writes the row after the ledger row |
| `global_index/track1_shadow_acceptance.py` | reads the stream, one WARN reason, summary fields, `pre_observation_schema` |
| `monitor/backend/job_journal_reader.py` | one line in the Operational block |
| `scratch/test_track1_stage5zo_…py` | new, 34 tests |

**No runtime file was written or edited.** `window_coverage`, `slot_timing`, `signals`,
`shadow/explanations` and `audits` all carry their baseline mtimes; the checkpoint and book
carry 00:55 from the live NKD close; `data_observation/` does not exist yet and will be created
by the first slot that runs. No old explanation row was touched, and nothing was backfilled for
2026-08-26 — that window remains, correctly, a pre-schema day.

## 11. What remains before paper

| | item | class |
|---|---|---|
| 1 | machine sleep | **operator** |
| 2 | B1 — separate account, or a proven-flat legacy book | **operator decision** |
| 3 | five clean judgeable days | **time**, once 1 is fixed |
| 4 | the regime gate's first PASS | **time** — and `--verify-strict` is now live, so the 16:20 job will record one |
| 5 | broker stop proof, partial fills, an order in flight across a restart | **paper only** |

Plus the residual named in §3: nothing records whether the provider's last bar was still open.
It is written as an explicit unknown rather than guessed, and closing it means asking the
provider layer a question it does not currently answer — a small stage, not a blocker.
