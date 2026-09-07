# Track 1 explainability — record model, rule map, and how it reaches the dashboard

**Session 2026-08-23 · Stage 5X Parts B, C and E**

Companion to `scratch/track1_dashboard_monitor_audit_20260823.md`, which measured what the
dashboard can currently see. This note says what a Track 1 record has to contain, which rules
exist and where they live, and the order in which any of it may reach a screen.

The machine-readable form of everything below is
`scratch/track1_explainability_schema_20260823.json`, and that file is **generated from the
code**, not written beside it. The rule sections in Part C are likewise rendered from the
registry by `scratch/gen_track1_rule_table_20260823.py`. A rule table typed by hand next to
the code is a description, and descriptions in this repository have a history of walking away
from the thing they describe.

---

## Part B — the record model

### Why records and not UI text

The shadow route already writes a decision line per candidate, carrying a verdict and a
free-text `detail` such as `family gross 5.31% > cap 5.00%`.

That sentence cannot be re-checked. It does not say which file computed 5.31%, it cannot be
filtered on, and the day the format changes every reader downstream quietly stops matching.
The dashboard is already living with the consequence of exactly this pattern: today the only
place a **live** rejection is visible at all is a regular expression run over a warning
sentence in the day log (audit §3.1).

So a record here is an event, not a caption. A rule that fires must carry three things a
sentence cannot fake:

1. the **value** that was measured,
2. the **threshold** it was compared against,
3. the **symbol** that made the comparison.

### Four record types, plus a fifth for silence

| Type | What it asserts |
|---|---|
| `SIGNAL` | A setup was looked for. It was found (`pass`), or a rule said no (`fail`). |
| `DECISION` | The admission verdict on one candidate: `accepted`, or `rejected` and by which gate. |
| `EXECUTION` | Order intent, fill, cancel or failure. Nothing on this route produces one yet — the order gate refuses while any blocker is open. |
| `NO_SIGNAL` | A window was watched and produced nothing. |
| `NO_ACTION` | Something was evaluated and deliberately left alone. |

`NO_SIGNAL` is not noise, and it is not emitted per bar. It is emitted **once per window**,
and it exists to keep apart two facts the window ledger already keeps apart: *the rule said
no* and *nobody looked*. The dashboard has been bitten by the second masquerading as the
first — a log that is empty because the window never ran reads exactly like a window that ran
and found nothing.

The statuses are constrained per type, deliberately. A `DECISION` may not say `pass`: `pass`
is what a check reports, `accepted` is what a candidate becomes, and letting one type say
both makes the stream unfilterable.

### The identifier

```
explain_id = "t1x_" + sha256(route | session_date | sleeve | instrument |
                             candidate_id | record_type | stage | sequence)[:32]
```

sha256, never Python's built-in `hash()` — that one is salted per interpreter process, so the
same record would get a different identifier on every run and nothing could be linked across
a restart. The route checkpoint's parameter hash documents the same trap for the same reason.

`stage` and `sequence` are what separate two records that are otherwise the same tuple. A
Stress candidate evaluated at 10:35 and again at 10:40 inside the same window is two
decisions, not one. There is a test per component asserting that changing it moves the id.

`parent_explain_id` links a decision to the signal it came from, and later an execution to its
decision.

### What every record carries

Twenty-one required fields. Absent is refused, never defaulted — the same rule the route
parameter set already enforces, and for the same reason: two records must not look alike
because one of them forgot to say.

- **identity**: `schema_version`, `explain_id`, `parent_explain_id`, `route`, `sleeve`,
  `instrument`, `session_date`, `candidate_id`, `record_type`, `stage`, `sequence`
- **time**: `decision_time` (when the verdict was taken), `data_time` (what the data was
  current as of), `bar_timestamps` (the bars the rules actually read)
- **verdict**: `status`, `reason_code`
- **why**: `rule_ids`, `code_refs`, `evidence_refs`, `feature_snapshot`, `thresholds`
- **context**: `inputs_summary` (bars / regime / checkpoint / freshness / window ledger),
  `outputs` (direction, quantity, entry basis, stop basis, risk, cap bucket), `rejection`
- **provenance**: `track1_params_hash`, `fill_law`, `data_source_identity`,
  `regime_csv_identity`, `git_commit`

Three details that are load-bearing:

**Code references are derived, never supplied — and re-derived at validation.** The caller
names a rule; the builder looks up where that rule lives. A caller that could hand in its own
pointer is a caller that can name a rule and point at the wrong file.

Deriving once is not enough, and the first version of this module made exactly that mistake.
A record travels: through JSON, into a file, back out, through an edit. After that, a derived
field is only a *copy sitting beside* the thing it claims to describe — which is the whole
defect family this registry exists to remove, arriving in the one place whose job is to catch
it. Measured on 2026-08-23, before the fix: swapping a reference's file for `wrong.py`,
swapping its symbol, appending a whole extra reference for a rule that never fired, forging an
evidence path, editing the session date or stage while keeping the old identifier, and
replacing the identifier with thirty-two zeros — **all ten cases validated clean**.

So the identifier, the code references and the evidence references are now **recomputed from
the record's own contents at validation time and compared**. The comparison is on content,
not order, because a record that reordered its own references on a round-trip is not a
tampered record and a guard that fired for it is a guard people learn to switch off.

The builder and the validator call **one** derivation function. Not two implementations that
agree today — a validator holding its own copy of the rule would be a second description of
the same thing, and this file exists because second descriptions drift.

**A line number is optional and is never the identifier.** Line numbers rot on the first edit
above them. A function or class name survives that edit.

**One field, one source.** The route reached the record from two places until 2026-08-23: the
builder's argument fed the identifier, and the provenance object's fields were merged in
afterwards and overwrote it. A record could therefore carry an identifier naming one route
and a field naming another and be internally inconsistent while passing every check —
measured directly. The provenance object no longer emits the route at all, and the builder
**refuses** a disagreement rather than resolving it, because picking a winner would hide
which caller was wrong.

The route is also checked against Track 1's own route at validation, and that check is
genuinely independent of the identifier check: a record built consistently for another route
produces an identifier that recomputes *correctly*, so only an explicit route rule refuses
it. This registry holds Track 1's sleeves and Track 1's rules, and it cannot vouch for a
record it does not govern.

**`git_commit` may be `null`, and `null` means "could not read it".** It must stay
distinguishable from a real hash. A status probe that answers "no" when it means "I do not
know" is the fail-open shape this project has already paid for once, when a duplicate-process
check returned an empty list for three different kinds of failure and an empty list meant
"nothing is running".

### The feature snapshot

Every entry is a value, a threshold, the comparison operator, and whether it passed:

```
prev_range_pct = 0.0311   <=  0.02652437134968455   ->  False
rvol           = 1.42     <=  2.0                   ->  True
```

`value = null` is legal and means the feature was **absent**. That is not a technicality: the
Normal-R4 context filter treats a missing feature as a **block**, counted separately from a
threshold breach, precisely so that "the filter worked" can never be confused with "the
feature was not there". A record has to be able to say the same thing, so `null` with
`passed: false` is a valid row and there is a test pinning it.

### What an accepted decision must prove

A decision that admitted a candidate without a cap number, a freshness verdict and a breaker
verdict is a decision nobody can audit. The three things that could have stopped it are
exactly the three things it has to show it checked, and the validator refuses an `accepted`
record that omits any of them.

A `rejected` record symmetrically must name a refusal reason from the registry **and** carry
the rejection detail. Fourteen refusal reasons round-trip today: cap, family cap, same-symbol
suppression, same-sleeve suppression, window, breaker halt, kill switch, order-gate refusal,
checkpoint refusal, freshness failure, intraday failure, live-frame refusal, no setup, and
filter block.

### Namespaces are imported, not retyped

The decision verbs come from the signal layer, the bar-level refusals from the intraday gate,
the input-staleness statuses from the freshness gate, and the route and fill laws from the
parameter module. Thirty-four reason codes in total, none of them typed twice. If the signal
layer gains a verdict, this registry gains it without an edit — which is the property that
stops two copies of a list drifting apart, the same defect the Track 1 slot parity check was
built to catch.

---

## Part C — the rule map

Thirty-eight rules. Every one names where it lives and what proves it, and **every file and
every cited test or report was checked to exist** (measured: zero missing code files, zero
missing evidence files).

Distribution: Normal-R4 nine, Calm A eight, Stress-MNQ five, NKD four, shared gates twelve.

The `features` line under each rule is enforced, not advisory: a record citing that rule and
omitting one of those values is refused by the validator. That is the mechanism that stops a
row asserting "the range filter fired" without saying what the range was.

<!-- RULES:BEGIN -->

### 1. Normal-R4  (sleeve `roska4_swing` — MES, MNQ, MYM, M2K)

**`R4.ARM_1405`**  
The broker stop is armed at 14:05 America/New_York on the session AFTER the fill, not at the fill.

- lives in: `global_index/track1_params.py` → `sleeve_config`
- an explanation citing it must carry: `arm_hour`, `arm_timezone`
- proved by: test: `global_index/test_arm_time_per_sleeve.py` — per-sleeve arming times

**`R4.EMA50`**  
Normal-R4 trend filter runs at ema_period=50, not legacy's 10.

- lives in: `global_index/track1_normal_r4.py` → `NormalR4Params`
- an explanation citing it must carry: `ema_period`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py` — Normal-R4 rows reproduce the committed table exactly

**`R4.FILL_LAW`**  
Which fill law the run used. The promotion artifacts were produced with every bar gap-eligible; the production engine only fills at the open after a real >15-minute break. Same bars, different exits.

- lives in: `global_index/track1_params.py` → `_base`
- an explanation citing it must carry: `fill_law`
- proved by: report: `scratch/track1_three_blockers_report_20260822.md` — twelve regenerations, both laws, all three windows

**`R4.MAX_HOLD_5`**  
A position is closed once it has been held max_hold_days=5 sessions.

- lives in: `global_index/track1_normal_r4.py` → `NormalR4Params`
- an explanation citing it must carry: `max_hold_days`
- proved by: test: `global_index/test_maxhold.py`

**`R4.RANGE_P90`**  
Context filter: the PRIOR session's RTH range, as a fraction of its close, must be <= the p90 of the frozen 2018-2024 floor window. A MISSING value is a BLOCK, never a pass.

- lives in: `global_index/track1_normal_filters.py` → `R4ContextFilter.allow`
- an explanation citing it must carry: `prev_range_pct`
- proved by: report: `scratch/track1_three_blockers_report_20260822.md` — threshold frozen on the floor window

**`R4.RATCHET_OFF`**  
The stop never moves after the fill. Legacy ratchets it.

- lives in: `global_index/track1_params.py` → `sleeve_config`
- an explanation citing it must carry: `ratchet`
- proved by: test: `scratch/test_track1_route_checkpoint_stage1_20260822.py` — ratchet mutation moves the hash

**`R4.RVOL_MAX`**  
Context filter: slot-relative volume must be <= 2.0. A MISSING value is a BLOCK.

- lives in: `global_index/track1_normal_filters.py` → `R4ContextFilter.allow`
- an explanation citing it must carry: `rvol`
- proved by: report: `scratch/track1_three_blockers_report_20260822.md`

**`R4.SPY_SHORT_GATE`**  
A SHORT is permitted only on a session where SPY's D-1 close was BELOW its 50-day SMA (both shifted one day). Applied unconditionally, ahead of the context filter, exactly as the generator that wrote the promotion artifacts applied it.

- lives in: `global_index/track1_normal_filters.py` → `allowed_short_days`
- an explanation citing it must carry: `spy_below_sma50`, `direction`
- proved by: report: `scratch/track1_three_blockers_report_20260822.md` — removing the gate costs -11,663 to -14,143 at book level on the floor window and widens MaxDD by 31%

**`R4.STOP_FIXED_ATR2`**  
Stop is entry +/- 2.0 x DAILY ATR, anchored at the ENTRY price. Legacy anchors on the running extreme through the prior bar; the two put the same multiple in a different place.

- lives in: `global_index/track1_normal_r4.py` → `make_signal_fn`
- an explanation citing it must carry: `entry_price`, `daily_atr`, `stop_multiple`, `stop_price`
- proved by: test: `scratch/test_track1_route_checkpoint_stage1_20260822.py` — stop_basis / stop_multiple / stop_anchor each move the params hash when mutated


### 2. NKD / MNKD  (sleeve `global_nkd` — MNKD)

**`NKD.CHANDELIER_25`**  
Chandelier stop at 2.5 x ATR anchored on the extreme through the prior bar, ratchet ON. Kept as legacy has it: Track 1 adopts the sleeve as it stands rather than re-deriving it.

- lives in: `global_index/track1_params.py` → `sleeve_config`
- an explanation citing it must carry: `stop_multiple`, `stop_anchor`, `ratchet`
- proved by: test: `scratch/test_track1_route_checkpoint_stage1_20260822.py`

**`NKD.EMA10`**  
The promoted MNKD sleeve runs at ema_period=10, unchanged from legacy.

- lives in: `global_index/track1_params.py` → `sleeve_config`
- an explanation citing it must carry: `ema_period`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py` — MNKD rows reproduce exactly: 228 floor / 31 vault2025 / 26 vault2026

**`NKD.PRODUCTION_ENGINE`**  
The sleeve is produced by the SAME generator as Normal-R4 at its own ema, with the R4 context filter OFF — that filter is an R4 rule and applying it to a Tokyo session would be inventing one. The SPY short gate DOES apply.

- lives in: `global_index/track1_normal_r4.py` → `run_instrument`
- an explanation citing it must carry: `ema_period`, `apply_context_filter`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py`

**`NKD.REGIME_LAG1`**  
Regime labels are read at lag 1 session, because the Tokyo power hour precedes the US close that produced the label.

- lives in: `global_index/regime.py` → `RegimeLabels`
- an explanation citing it must carry: `label_lag_days`, `regime_label`
- proved by: test: `scratch/test_track1_route_checkpoint_stage1_20260822.py` — label_lag_days mutation moves the hash


### 3. Calm A  (sleeve `roska4_calm` — MES, MNQ)

**`CALM.ATR15_DISASTER_STOP`**  
One disaster stop at entry - 1.5 x ATR15, placed at the fill and never moved. The cap denominator for this sleeve is the TRUE stop distance, not the mult x ATR x point-value proxy the other sleeves use.

- lives in: `global_index/track1_params.py` → `sleeve_config`
- an explanation citing it must carry: `atr15`, `stop_multiple`, `true_stop_risk_dollars`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py` — listed as the sleeve's remaining live prerequisite

**`CALM.D1_CALM_CAUSAL`**  
The PRIOR session's regime label must be Calm. Causal by construction: the label read is the one from a session strictly before the traded one.

- lives in: `global_index/track1_calm_a.py` → `detect`
- an explanation citing it must carry: `prev_regime_label`, `regime_lag_sessions`
- proved by: report: `docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md`

**`CALM.ENTRY_1000_OPEN`**  
Entry is the OPEN of the 10:00 ET bar. One-shot: a missed 10:00 is not entered late, because a 10:20 entry is a different trade at a price that has moved.

- lives in: `global_index/track1_signal_layer.py` → `window_verdict`
- an explanation citing it must carry: `entry_time`, `entry_price`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`CALM.EXIT_1555_OPEN`**  
Exit is the OPEN of the 15:55 ET bar, same session.

- lives in: `global_index/track1_calm_a.py` → `detect`
- an explanation citing it must carry: `exit_time`
- proved by: report: `docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md`

**`CALM.GAP_NOT_DEEP`**  
The gap from the prior RTH close to today's RTH open must be >= -1.0%. A deeper gap is a different setup and is not traded.

- lives in: `global_index/track1_calm_a.py` → `detect`
- an explanation citing it must carry: `gap_from_prev_rth_close`
- proved by: report: `docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md`

**`CALM.PCLOC_BOTTOM_THIRD`**  
The prior session's RTH close must sit in the bottom third of its own RTH range: (close - low) / (high - low) <= 1/3.

- lives in: `global_index/track1_calm_a.py` → `detect`
- an explanation citing it must carry: `prev_close_loc`
- proved by: report: `docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md`

**`CALM.PRIOR_FULL_RTH`**  
The session used as PRIOR must have run to the RTH end (15:59). Read off the record rather than assumed, so a half session cannot silently become the reference.

- lives in: `global_index/track1_calm_a.py` → `rth_sessions`
- an explanation citing it must carry: `prev_session_last_bar`
- proved by: report: `docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md`

**`CALM.PRIOR_RTH_DOWN`**  
The prior session's RTH return (close/open - 1) must be <= 0.

- lives in: `global_index/track1_calm_a.py` → `detect`
- an explanation citing it must carry: `prev_rth_ret`
- proved by: report: `docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md`


### 4. Stress-MNQ  (sleeve `roska4_stress` — MNQ)

**`STRESS.DETECTOR_0930_1030`**  
The low that must break is taken from the 09:30-10:30 ET pre-window. The intraday gate requires that whole span present before a decision is allowed.

- lives in: `global_index/track1_intraday.py` → `REQUIREMENTS`
- an explanation citing it must carry: `pre_window_low`, `today_from`, `today_to`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py`

**`STRESS.FORCE_CLOSE_ORDER`**  
A Stress entry may DISPLACE a Normal or Calm holder of the same symbol — but only after passing the cap gate against the book it would LEAVE BEHIND. Nothing is closed for an entry that is then refused.

- lives in: `global_index/track1_signal_layer.py` → `Track1Book.evaluate`
- an explanation citing it must carry: `displaced_trade_ids`, `cap_checked_against`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`STRESS.MNQ_ONLY_G3_Q7`**  
The committed scenario: MNQ only, quantity 7, minimum gap 3, R:R 1.5, on a break of the pre-window low. NOT futures/stress_liquidation_1020.py, which is a different 10:20 candidate that says of itself it is deliberately not wired.

- lives in: `global_index/track1_live_sleeves.py` → `SOURCES`
- an explanation citing it must carry: `qty`, `gap_min`, `rr`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py` — test_sleeves_stress_is_mnq_only_g3_q7_and_not_the_1020_candidate

**`STRESS.QTY_7`**  
Seven contracts, carried on the CANDIDATE. MNQ is 1 under Normal and 7 under Stress on the same day, which `contracts_by_inst[inst]` has no key to express.

- lives in: `global_index/track1_params.py` → `SLEEVE_QTY`
- an explanation citing it must carry: `qty`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`STRESS.WINDOW_1035_1230`**  
Entries are permitted only inside 10:35-12:30 ET inclusive. Inside it a missed slot costs nothing; outside it there is no entry at any price.

- lives in: `global_index/track1_signal_layer.py` → `window_verdict`
- an explanation citing it must carry: `decision_hhmm`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`


### 5. Shared gates (every sleeve)

**`GATE.B1_ORDER`**  
No order may be sent while any Stage 2D blocker is open. Arming needs BOTH an on-disk confirmation that schema-checks and TRACK1_ORDERS_APPROVED=1 in the environment; one flag on a command line is never enough to reach an exchange.

- lives in: `global_index/run_live_day_track1.py` → `OrderGate`
- an explanation citing it must carry: `open_blockers`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`GATE.BREAKER`**  
The circuit breaker is marked at every instant and its verdict decides whether NEW risk is allowed. Marked AFTER this instant's closes are booked, which is the ordering every measured Track 1 figure was produced under.

- lives in: `global_index/track1_signal_layer.py` → `Track1Book.begin_instant`
- an explanation citing it must carry: `allow_new_entries`
- proved by: test: `global_index/test_kill_switch.py`

**`GATE.CAP_CLUSTER`**  
A candidate's risk must fit its cluster's gross (and where declared, net) budget as a fraction of the account.

- lives in: `global_index/net_exposure_multi.py` → `MultiClusterGuard.admits`
- an explanation citing it must carry: `cluster_gross_after`
- proved by: test: `global_index/test_cluster_gate.py`

**`GATE.CAP_FAMILY`**  
Normal and Calm share ONE combined budget on top of their own, because Calm A is long MES/MNQ into the same session Normal is trend-following. No production equivalent exists: MultiClusterGuard checks a candidate against its own cluster only.

- lives in: `global_index/track1_signal_layer.py` → `family_verdict`
- an explanation citing it must carry: `family_gross`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`GATE.CHECKPOINT`**  
A resumed position is accepted only when route, sleeve, instrument, schema, params hash and the frame fingerprint all match. Unknown is NOT equal: a missing field is a refusal, never a default.

- lives in: `global_index/route_checkpoint.py` → `usable`
- an explanation citing it must carry: `checkpoint_accepted`
- proved by: test: `scratch/test_track1_route_checkpoint_stage1_20260822.py`

**`GATE.FRESHNESS`**  
Daily inputs (pre-flight record, regime CSV, each parquet) must already cover the required session. Fails CLOSED. `unverified` is a third state and is never reported as either a pass or a failure.

- lives in: `global_index/track1_freshness.py` → `evaluate`
- an explanation citing it must carry: `freshness_allow`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`GATE.INTRADAY`**  
The same-session sleeves need this morning's bars: the contiguous span the decision reads, the decision bar itself, staleness against the decision instant, and the prior RTH where the rule reads it.

- lives in: `global_index/track1_intraday.py` → `validate`
- an explanation citing it must carry: `intraday_allow`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py`

**`GATE.LIVE_FRAME`**  
Today's bars are joined onto the frozen history through ONE splice, which refuses a tz mismatch, duplicate or out-of-order timestamps, a column mismatch, and any mutation of the frozen history.

- lives in: `global_index/track1_live_frame.py` → `splice`
- an explanation citing it must carry: `frozen_rows`, `live_rows`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py`

**`GATE.SAME_SLEEVE`**  
One sleeve may not hold the same instrument twice.

- lives in: `global_index/track1_signal_layer.py` → `Track1Book.evaluate`
- an explanation citing it must carry: `held_by_same_sleeve`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`GATE.SAME_SYMBOL`**  
A Normal or Calm candidate is suppressed when another sleeve already holds the same instrument. Stress is deliberately absent from this table: it displaces a holder rather than deferring to one.

- lives in: `global_index/track1_signal_layer.py` → `SAME_SYMBOL_BLOCKERS`
- an explanation citing it must carry: `held_by_clusters`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`GATE.WINDOW`**  
The instant must sit inside the sleeve's declared detection window. Sleeves with no declared window (Normal, NKD) are always inside one — bounding them here would be inventing a rule.

- lives in: `global_index/track1_signal_layer.py` → `window_verdict`
- an explanation citing it must carry: `decision_hhmm`
- proved by: test: `scratch/test_track1_stage3_route_20260822.py`

**`GATE.WINDOW_LEDGER`**  
Whether the window was WATCHED at all, which is a different fact from whether it produced a signal. Absence of a complete observation is itself the signal.

- lives in: `global_index/window_ledger.py` → `status`
- an explanation citing it must carry: `observed_slots`
- proved by: test: `scratch/test_track1_stage3b_blockers_20260822.py`


<!-- RULES:END -->

---

## Part E — how this reaches the dashboard, and in what order

### Storage

**Now (shadow):** `scratch/track1_shadow/explanations_YYYYMMDD.jsonl`, one JSON object per
line, appended.

The writer refuses any destination outside that directory, and the refusal is enforced after
path resolution so a relative escape cannot slip past it. This is not fastidiousness. A
`--dry-run` of the legacy runner once wrote a `live_day_*.log`, which the paper-evidence
reader globs, and it manufactured a paper-evidence episode that was then attributed to a
different session. A writer that can be aimed at a legacy path will one day be aimed at one.

Validation runs over the **whole batch before the file is opened**. A partly written batch is
a file whose tail nobody can trust, and the caller would have no way to tell which rows
landed.

**Later (production):** `global_index/track1_explanations_YYYYMMDD.jsonl`, same format. The
move is a path change and a schema-version bump if anything changed, nothing more.

### Backend reader

A **new** reader and a **new** endpoint. Not a widening of an existing one.

- Route-aware: filters on route, sleeve, instrument, session date and status.
- Schema-version tolerant: a row whose `schema_version` the reader does not recognise is
  returned marked *unknown version*, never dropped silently and never parsed as if it were
  the current version. Dropping it would make a format change look like a quiet day.
- Modification-time cached, matching every other reader in the monitor.
- Read-only, like the rest of the backend.

The reason for a separate endpoint rather than an extra field on an existing one is measured
rather than aesthetic: the persisted-position reader is a nine-key allow-list and silently
drops anything else (audit §4), and the paper-evidence reader aggregates the whole trade log
with no route split (audit §3.2). Adding Track 1 to either would either lose the field or
fold Track 1's numbers into legacy's gates.

### UI

An explanation drawer, opened from a row rather than shown by default. Five tabs, matching
the record's own shape:

| Tab | Content |
|---|---|
| Signal | what was detected, and the rules that decided it |
| Decision | the verdict, and for a rejection the gate that refused it and by how much |
| Execution | order intent and fill, once orders exist |
| Data | which bars, which regime label, which checkpoint, which freshness verdict, which window-ledger status; the parameter hash and fill law |
| Code refs | file and symbol per rule, and the test or report that proves each one |

Entry points: a schedule-journal row for a Track 1 slot, a candidate row, and a trade row —
each linking by explanation id.

### Safety rules for the wiring, in the order they must hold

1. Legacy readers are not edited. A new reader that crashes takes down one panel; an edited
   legacy reader takes down the page.
2. Unknown fields are tolerated everywhere Track 1 writes. Where a reader is an allow-list,
   Track 1 writes to its own file instead of arguing with it.
3. A route-specific endpoint ships before any legacy endpoint is touched.
4. Track 1 rows never enter `trade_log.jsonl`, `live_positions.json`, `live_state_data.js` or
   any `live_day_*.log`.
5. Before Track 1 slots are allowed to show as *incidents* rather than merely as *next job*,
   the health slot table has to learn about them — otherwise a Track 1 slot that fails is
   invisible, and a slot the mirror has not been taught about manufactures a fake incident.
   Those are the two failure directions and both are already documented in the mirror itself.

### What this design does not yet answer

- **Volume.** A Stress window is twenty-five slots. If every slot emits a record for every
  instrument, a quiet day still produces rows. The per-window `NO_SIGNAL` design bounds it in
  principle; nobody has measured a real day's output because the route has never run live.
  Estimate deliberately withheld — the honest label is *unmeasured*, and this project has
  been bitten by a plausible estimate presented as a measurement.
- **Whether the empty live decision block is a design choice or a wiring gap** (audit §6).
  The answer changes whether Track 1 should populate the existing decision panel at all, or
  stay entirely in its own channel.
