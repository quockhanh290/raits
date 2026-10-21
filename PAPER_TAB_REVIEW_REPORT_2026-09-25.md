# Paper Tab Read-Only Review — 2026-09-25

## ANCHORS

Re-taken with direct read-only reader calls because `127.0.0.1:5001` was unavailable. No service was restarted.

```text
paper source=paper_evidence
route=track1_candidate
observed_at=2026-09-25T19:07:02.722483Z
freshness=None

paper_duration       PENDING
regime_coverage      PENDING
exit_path_coverage   PENDING
c1_slippage          QUALITY_BREACH
b3_reconcile         NOT_WIRED
stp_verification     NOT_WIRED
tws_restart_nights   NOT_WIRED
not_wired count      15
```

These match section 2.

Execution-quality also matches:

```text
state=available
day=None
source=global_index/track1_runtime/trade_log.track1.jsonl
assumption_ticks=2.0
fills=4
exceptions=0
opens: n=4 mean=-6.0 median=-5.0 worst=1.0
       adverse_count=1 over_assumption_count=0
```

Drift exists inside paper evidence:

```text
c1 paper evidence: OPEN -7.67 ticks N=3
execution quality: OPEN -6.00 ticks N=4
fill_quality:      3 / 100
```

The fourth trade, MES, has `entry_day: "15:00"` rather than a date. Paper’s epoch comparison excludes it; execution-quality with `day=None` retains it.

## PER QUESTION

### 3.1 Fill quality and slippage

`monitor/backend/execution_quality_reader.py:50` defines positive slippage as adverse. OPEN uses the recorded signed `slip`; exceptions require `slippage_ticks > 2`. `global_index/dash/paper/paper.js:270` uses the same convention. I found no displayed sign inversion.

Raw fills:

```text
M2K  -9 ticks   adverse=false   over 2=false
MYM -15 ticks   adverse=false   over 2=false
MNKD +1 tick    adverse=true    over 2=false
MES   -1 tick   adverse=false   over 2=false
```

The gate breaches because `monitor/backend/paper_evidence_reader.py:1653` compares `abs(mean)` to three ticks. M2K and MYM therefore breach despite being economically favourable.

The active specification is `monitor/paper_inputs.json:11`:

```text
OPEN: per instrument, min_n_per_inst=20, max_mean_ticks=3
STP CLOSE: pooled, min_n=30, max_mean_ticks=3
use_absolute=true
```

Its threshold rationale is written in cost terms:

> “Each additional tick costs about $903/year against $6,794 of annual net — 13% of the modelled edge per tick… A 3-tick ceiling allows one tick of drift over the model, or 13%.”

Its absolute-value rationale switches to correspondence terms:

> “A mean is judged on its absolute size, so favourable slippage counts too… It is not an economic loss… but it is execution drift.”

Thus `QUALITY_BREACH` means expected-price correspondence breach, not excessive execution cost. The current label does not make that distinction read-proof.

`n=4` is not sufficient: OPEN requires 20 per instrument; STP requires 30 pooled. The detailed C1 panel exposes these targets, but the readiness card reads obsolete flat properties at `global_index/dash/paper/paper.js:441`, so it renders undefined targets and derives `PENDING` instead of the gate’s `QUALITY_BREACH`.

The payload also contains a stale requirement at `monitor/backend/paper_evidence_reader.py:3635`:

```text
Active paper_inputs spec: N>=100, abs mean <=5 ticks
```

That is the superseded specification, not the active one.

### 3.2 Account and book reconciliation

Read-only runtime output:

```text
order journal: sent=4, filled=4, filled_qty_zero=4
position book: present, 4 positions, qty=1 each
broker log:    4 positions and 4 STP orders, PreSubmitted, remaining=1
baseline:      PASS, USD 251,752.25, checked 2026-09-25T18:05:06Z
B1:            UNKNOWN / record_stale
```

Broker evidence is at `monitor/logs/ops_backend.err.log:586213`: MNK, MES, M2K, and MYM each had a `PreSubmitted` STP with remaining quantity one at 14:20:16 local time.

The paper tab does not display the order journal, B1, or account baseline. It therefore performs no four-way reconciliation.

Instead, “Current protection” reports:

```text
BREACH
0/4 persisted position(s) have stop_order_id
four rows status=UNPROTECTED
```

That is not a broker stop check. `monitor/backend/paper_evidence_reader.py:3083` only checks for a `stop_order_id` field in the persisted book. The four actual book rows have stop prices but do not carry that field. The displayed conclusion conflicts with the broker evidence.

The book schema also uses `instrument`, `sleeve`, and `qty`, while `monitor/backend/paper_evidence_reader.py:796` expects `inst`, `cluster`, and `contracts`; consequently all four displayed protection rows lose their instrument, cluster, and quantity.

After 24 hours, the account-baseline reader refuses the stale value and returns UNKNOWN. B1 also refuses its stale stored record. Those refusals are correct, but the paper tab shows neither value nor refusal. A broker move after a B1 observation remains unknowable until another B1 measurement; the tab supplies no B1 age.

### 3.3 The NOT_WIRED rows

`monitor/backend/paper_evidence_reader.py:436` overwrites any affected row with `NOT_WIRED`, discarding metrics already calculated for that row.

| Row | Classification | Evidence |
|---|---|---|
| `b3_reconcile` | Source exists; nothing in paper evidence reads it | `TRACK1_*` B3 mismatches exist in `ops_scheduler.err.log`, including lines 135077, 135329 and 138167. |
| `data_freshness` | Genuine consolidated source missing | Route telemetry exists, but no Track 1 equivalent of the required freshness projection is published to this reader. |
| `log_hygiene` | Source exists; nothing reads it | Track 1 scheduler/backend logs exist; only legacy log patterns are scanned. |
| `manual_intervention` | Genuine structured source missing | Raw logs are not a complete intervention ledger. |
| `open_incidents` | Source exists, is read, then wiring discards it | `read_open_issues(root)` is called at line 3084 before `_track1_finish` replaces the result. |
| `paper_vs_backtest` | Genuine Track 1 source missing | `monitor/paper_pnl_compare.json` is explicitly legacy-only. |
| `pnl_thresholds` | Genuine source missing | Requires the absent Track 1 comparison series and Track 1 backtest identity. |
| `rejections` | Source exists and is read elsewhere; paper wiring is missing | The order journal has state/error fields and `/api/v1/track1-runtime` reads it; paper evidence does not. |
| `roll_slippage` | Genuine structured source missing | No Track 1 roll-slippage evidence artifact was found. |
| `runner_freshness` | Genuine consolidated source missing | Audit/slot artifacts exist, but no equivalent current runner-heartbeat measurement is supplied here. |
| `state_persist` | Source exists, is already read, wiring is broken | `live_positions.track1.json` feeds `current_protection`, yet this row is erased for lacking legacy `live_state`. |
| `stp_placement` | Source exists; nothing reads it | Track 1 stop-repair and broker-order lines exist in logs. |
| `stp_verification` | Source exists; nothing reads it for Track 1 | Broker acceptance lines exist; `paper_inputs.json` also has a verification record, but non-spec records are deliberately dropped. |
| `tws_restart` | Candidate source exists; nothing reads it | Track 1 logs exist, but are not scanned; they are not sufficient for proven-night status. |
| `tws_restart_nights` | Genuine structured proof missing | No set of Track 1 records proving restart, runner resume, and broker verification was found. |

The first priority is therefore not creating B3 evidence; that evidence already exists. It is connecting the existing Track 1 log evidence.

### 3.4 Absent numbers versus zero

The trade log contains four OPEN rows and no CLOSE rows.

- Epoch P&L renders unavailable, not `$0`; the readiness card says “No closed-trade P&L for the epoch yet.”
- Fill-row P&L renders `-`, with the qualifier “CLOSE only.”
- Sharpe and Calmar are not present on the paper tab.
- Realised drawdown is not displayed; only a NOT_WIRED backtest-threshold description mentions drawdown.

This avoids false zeroes. One ambiguity remains: `global_index/dash/paper/paper.js:154` maps both `null` and numeric zero to the same `-`, so a genuine zero and an absent value cannot be distinguished.

### 3.5 Execution-quality day

`monitor/backend/execution_quality_reader.py:151` intentionally returns `day=None` for the aggregate endpoint.

No in-scope downstream code compares the top-level `day` to a date:

- Analytics fetches the aggregate endpoint but filters each `fill.day` at `global_index/dash/analytics/analytics.js:99`.
- Reports call `read_execution_quality(root, day)` at `monitor/backend/report_reader.py:65`, producing a dated payload.
- The paper tab fetches only `/api/v1/paper-evidence` at `global_index/dash/paper/paper.js:2463`.

Therefore `day=None` causes no demonstrated in-scope user-visible failure.

### 3.6 Statements the tab cannot know

Measured cases:

```text
Current protection: BREACH, 0/4 “UNPROTECTED”
Broker log:         four working PreSubmitted STP orders

Overall status:     INSUFFICIENT DATA / “Pending evidence remains”
Gate state:         c1_slippage=QUALITY_BREACH
Coverage state:     current_protection=BREACH

Same-day/multi-day: OBSERVED
Actual CLOSE rows:  0
```

Specific causes:

- `global_index/dash/paper/paper.js:2409` recognizes only literal `BREACH`; `QUALITY_BREACH` is omitted. Coverage breaches are not included in the overall calculation.
- `monitor/backend/paper_evidence_reader.py:3346` uses `any(duration.values())`. Descriptive strings and status rules make that true even when all three measured counts are zero.
- The page-wide `observed_at` is only the trade-log modification time, assigned at `monitor/backend/paper_evidence_reader.py:404`. It is displayed as the observation time for the whole tab even when other evidence is newer.
- The persisted-ID test is presented as current broker protection, which it cannot establish.
- The paper reader silently drops MES because its malformed `entry_day` fails the lexical epoch test at `monitor/backend/paper_evidence_reader.py:624`.

## FINDINGS

Ordered by how misleading the displayed result is:

1. **“0/4 … UNPROTECTED” is false as a statement about current broker protection.** Four broker STPs were `PreSubmitted` with remaining quantity one; the tab only measured missing persisted `stop_order_id` fields.
2. **Overall status hides measured breaches.** It says `INSUFFICIENT DATA / Pending evidence remains` despite `QUALITY_BREACH` and a coverage `BREACH`.
3. **The C1 readiness card contradicts the C1 detail.** It reads obsolete flat spec keys and derives `PENDING`; the actual gate is `QUALITY_BREACH`.
4. **Paper C1 claims three fills and mean −7.67 when execution-quality has four and mean −6.00.** MES is silently excluded because `entry_day` is `"15:00"`.
5. **The displayed C1 requirement is obsolete.** It says N≥100 and ≤5 ticks; the active specification is OPEN N≥20 per instrument and STP N≥30 pooled, both ≤3 ticks.
6. **`QUALITY_BREACH` reads as economic slippage failure but is actually an absolute expected-price correspondence failure.** Every observed fill is within the one-sided two-tick cost allowance.
7. **`OBSERVED` is shown for same-day/multi-day exits with 0/0/0 and no CLOSE rows.** Prose values make the branch truthy.
8. **Protection rows lose identity and size.** Four book rows render without instrument, cluster, or contracts because the reader uses the wrong field names.
9. **The tab’s observation timestamp is not the freshness of the tab.** It is solely the trade-log modification time.
10. **The order journal says all four orders are filled but also records `filled_qty=0` for all four.** The book says quantity one and broker evidence says quantity one; the paper tab omits this disagreement.
11. **A P&L dash conflates absent with genuine zero.** The current rows are correctly absent, but a future zero would render identically.

## NOT A DEFECT

- No realised P&L, Sharpe, Calmar, or drawdown is invented from four OPEN trades. Omitting them is the correct refusal.
- `paper_vs_backtest` does not borrow the legacy comparison file. Showing `NOT_WIRED` is safer than attaching another route’s P&L to Track 1.
- Positive slippage consistently means adverse; negative means favourable. No sign reversal was found.
- `day=None` is correct for an all-days execution-quality response.
- B1 and the account baseline fail closed after their 24-hour expiry rather than publishing stale broker/account facts.
- Missing Track 1 restart-night proof is correctly not inferred from connection-log candidates.
- The detailed C1 panel does expose the small sample and says sample collection is incomplete. The defect is the conflicting readiness card and label, not the refusal to certify the sample.
- The endpoint’s `freshness=None` is honest; it does not manufacture a freshness verdict.

## UNCHECKED

- The HTTP endpoints were unavailable on `127.0.0.1:5001`; readers were invoked directly with `python -B`. No backend was restarted.
- I did not connect to IBKR. Broker conclusions are bounded to the durable 14:20:16 log observation, not asserted as current after that timestamp.
- I did not perform browser visual/interaction testing.
- No test suite was run; the review used direct readers, source inspection, and retained evidence only.
- Per instruction, I did not inspect or report findings in `realtime.js`, `track1_market_view.py`, or `job_journal_reader.py`.
- No source or test files were changed.

## SPEC PROBLEMS

- The review brief says both endpoints feed the paper tab. In current code, the paper tab fetches only `/api/v1/paper-evidence`; `/api/v1/execution-quality` is not a paper-tab input.
- The brief’s account-baseline and B1 questions imply the tab displays those measurements. It does not; answering required inspecting the separate Track 1 runtime reader.
- The active C1 specification mixes two meanings. Its three-tick threshold is justified using economic cost and lost edge, while `use_absolute` judges favourable execution as correspondence error. Both can be useful, but one `QUALITY_BREACH` label cannot unambiguously mean both.
- The brief’s anchor values were otherwise valid. The only observed drift was the paper reader’s current three-fill/−7.67 result versus execution-quality’s four-fill/−6.00 result, caused by the malformed MES day.

---

## BATCH 2 IMPLEMENTATION — 2026-09-25

Batch 2 from `PLAN_ADDRESS_FINDINGS_2026-09-25.md` was implemented only in:

- `monitor/backend/paper_evidence_reader.py`
- `global_index/dash/paper/paper.js`
- new test file `monitor/test_paper_batch2_20260925.py`

No order-path, book, realtime-dashboard, runner, scheduler, or backend-service changes were made. No broker order was placed or cancelled. Nothing was staged or committed.

### B2.1 — Protection

Protection is now derived from readable broker positions and working protective STP orders, rather than from the persisted `stop_order_id` field. Only `PreSubmitted` and `Submitted` STPs count as working; `PendingSubmit` does not.

The three operational results are:

```text
PASS     broker positions/orders readable and every persisted position has a matching
         broker position plus sufficient working protective STP quantity
BREACH   broker evidence readable but at least one persisted position lacks its broker
         position or working protective STP
UNKNOWN  broker positions or open orders cannot be read
```

Synthetic reproduction of the observed broker state:

```text
PASS
4/4 persisted position(s) have a matching broker position and working STP
M2K  roska4_swing x1  PROTECTED  broker stop #8
MYM  roska4_swing x1  PROTECTED  broker stop #10
MNKD global_nkd    x1  PROTECTED  broker stop #12
MES  roska4_swing x1  PROTECTED  broker stop #14
```

With the current standalone reader process, whose broker cache has not been populated:

```text
UNKNOWN
UNKNOWN — broker positions/orders could not be read:
broker positions/orders have not been read successfully
```

This is intentional. An unreadable broker is neither proof of protection nor proof of a breach.

### B2.2 — Book dialect

Protection rows now accept both book dialects:

```text
Track 1: instrument, sleeve, qty
Legacy:  inst, cluster, contracts
```

The current Track 1 rows therefore retain instrument, cluster, and size instead of rendering them as absent.

### B2.3 and B2.4 — Evidence wiring

Track 1 scheduler/backend logs are now read by the existing evidence parser. Rows backed by those logs, plus the two previously computed-and-discarded rows, are no longer unconditionally overwritten with `NOT_WIRED`.

Current direct-reader output:

```text
b3_reconcile     BREACH   3 mismatch episodes, 7 positions affected
stp_verification MISSING  source read; no verification evidence measured
log_hygiene      OBSERVED noise filtering ran
rejections       MISSING  source read; no rejected-signal evidence in the epoch
stp_placement    MISSING  source read; no placement/defer evidence parsed in the epoch
tws_restart      MISSING  source read; no connectivity candidate evidence
open_incidents   BREACH   4 open issues; the reader-produced issue list is retained
state_persist    MISSING  persist_match unavailable; persisted book count and rows retained
```

Rows whose required Track 1 source genuinely does not exist remain `NOT_WIRED` and retain an explicit reason:

```text
data_freshness
manual_intervention
paper_vs_backtest
pnl_thresholds
roll_slippage
runner_freshness
tws_restart_nights
```

If the Track 1 log files themselves do not exist, log-dependent rows also remain `NOT_WIRED`; an absent source is not converted into a measured zero.

### B2.5 — C1 label

The C1 arithmetic was not changed. `use_absolute`, all thresholds, and the API status `QUALITY_BREACH` remain intact.

The visible wording now identifies the measurement as expected-price correspondence:

```text
C1 expected-price correspondence
CORRESPONDENCE BREACH
OPEN N=<observed> (need 20 per instrument), STP N=<observed>/30
```

The active requirement is generated from the nested specification rather than the superseded `N>=100, <=5 ticks` sentence. Favourable and adverse misses still count by absolute size, as required by the documented specification.

### B2.6 — Zero versus absent

P&L rendering now distinguishes the two states:

```text
null or absent   not measured
numeric zero     $0.00
```

### Batch 2 verification

Focused Batch 2 tests plus the existing Track 1 paper-evidence tests:

```text
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -q -p no:cacheprovider monitor/test_paper_batch2_20260925.py monitor/test_track1_paper_evidence_20260924.py
.................                                                        [100%]
17 passed in 6.51s
```

Existing focused C1 arithmetic tests:

```text
.....                                                                    [100%]
5 passed in 1.83s
```

JavaScript syntax and diff whitespace checks:

```text
node --check global_index\dash\paper\paper.js
git diff --check -- monitor/backend/paper_evidence_reader.py global_index/dash/paper/paper.js monitor/test_paper_batch2_20260925.py
Exit code: 0
```

Two focused Chromium checks produced one pass and one failure:

```text
.                                                                        C1 verdict check passed
F                                                                        legacy empty-book assertion failed
```

The failing pre-existing assertion changes protection counts while leaving the broker status `UNKNOWN`, then expects the former two-state `0/0 protected` result. Its actual result is `unknown protected`. That old expectation conflicts with B2.1’s required rule that an unreadable broker must render `UNKNOWN`. The existing test was not edited because Batch 2 permitted only new test files under `monitor/`.

No part of the Batch 2 plan was found to be wrong. In particular, the correction in section 0 is upheld: absolute C1 correspondence math is deliberate and remains unchanged; only its visible label was corrected.
