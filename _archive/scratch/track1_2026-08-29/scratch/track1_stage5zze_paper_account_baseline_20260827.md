# Stage 5ZZE — B1 was vouching for an account that no longer existed

**2026-08-27, ET 07:20–07:35.** A new account-baseline layer, a read-only broker reconcile, and
one runtime record written. No orders · no confirmation file · no order approval · no order path
· nothing restarted by this stage · **no shadow or dashboard evidence cleared**.

---

## Verdict

| | |
|---|---|
| `paper_account_baseline_recorded` | **YES** — `PASS (account_flat_and_funded)` |
| `account_currency` | **USD**, single-currency (`{'USD': 250817.91}`) |
| `account_equity` | **250,817.91** — 0.33% from the expected 250,000 |
| `broker_positions` | **0** |
| `broker_working_orders` | **0** |
| `legacy_book_flat` | **YES** — read, count 0 |
| `track1_book_flat` | **YES** — read, count 0, schema 2, route-stamped |
| `b1_evidence_fresh` | **YES** but it was vouching for the wrong account — see §1 |
| `readiness_gate_changed` | **YES** — `paper_account_baseline` added; only PASS satisfies it |
| `dashboard_updated` | **YES** — its own block and row, verified against the running backend |
| `orders_possible` | **false**, blockers unchanged |
| `runtime_files_touched` | **one**: `track1_runtime/account_baseline/account_baseline_20260827.jsonl` |
| `next_action` | Calm DECIDE at 09:32 ET, still pending; re-record the baseline within 24h |

---

## 1. The measurement that made this stage necessary

Taken before any code was written, against the live B1 record:

```text
B1 record        2026-08-26 11:34:28 ET
age              19.77 h   — inside its own 24-hour window, still PASS
recorded equity  996,875.91
currency         not recorded anywhere in the row
stated baseline  250,000
drift            299%
```

**B1 was passing on an account that had been replaced underneath it.** Its freshness window is
about *positions and orders*, and a reset changes neither — so the record went on saying "flat
and safe" about an account that no longer existed, and nothing in it could have said otherwise.

Both books were genuinely flat and valid, then and now:

```text
legacy   BookState(state='read', count=0, positions=[])
track1   BookState(state='read', count=0, positions=[])
```

So flatness was never the problem. **Identity was.**

## 2. Why `get_equity()` could not have closed the gap

Read from source rather than assumed. Its own docstring: *"Accept any currency (CAD/USD/BASE
accounts all work)"*, and the code prefers a `BASE` figure, then whichever of USD or CAD the
broker happens to list first, then anything at all — returning a bare float.

A baseline built on that would record "equity 250000" for an account holding two hundred and
fifty thousand Canadian dollars, and nobody could tell afterwards. So the probe reads
`accountValues()` and keeps **every** currency-tagged NetLiquidation, with the label attached to
the number all the way into the record.

## 3. What the broker actually reported

Read-only, client id **96** — stated before connecting, and distinct from legacy's 1, a slot
child's 89, the safety jobs' 90 and B1's 97:

```text
connecting read-only to 127.0.0.1:4002 on client id 96 — account values, positions and
working orders only

B1        : PASS (legacy_and_broker_flat)
BASELINE  : PASS (account_flat_and_funded): USD 250,817.91, no positions, no working orders,
            both books flat and route-stamped, read 0 minute(s) ago
currencies: {'USD': 250817.91}
account   : DUR125337
```

The reset landed. Single-currency USD, 817.91 above the expected figure — **0.33% drift**, well
inside the band. And it confirms §1 exactly: yesterday's record said 996,875.91; today the
account holds 250,817.91.

## 4. The contract, decided and written down

```text
currency != USD                          FAIL   every size, stop and cap on this route is a
                                                USD figure; another currency is not a smaller
                                                version of the same thing
equity <= 0                              FAIL
|equity - 250,000| / 250,000  >  25%     FAIL   at that distance it is a different account or
                                                a different currency being read — the reading
                                                that prompted this was 299% away
                              >   5%     WARN   plausible, not expected. The gate does not open
                              <=  5%     PASS   12,500 of headroom: wide enough for fees and
                                                marks, narrow enough to hide nothing
any of it unread                       UNKNOWN  never "flat", never "funded"
B1 not PASS                       FAIL/UNKNOWN  the books are consulted through B1, never
                                                re-implemented here
observation older than 30 min          UNKNOWN
record older than 24 h                 UNKNOWN
```

**Only PASS satisfies the gate.** WARN and FAIL both refuse; the difference between them is what
an operator does next, not what the gate does. A gate with a maybe in it is a gate somebody
argues with.

## 5. Where it lives, and what it never claims

`global_index/track1_runtime/account_baseline/account_baseline_YYYYMMDD.jsonl` — durable, beside
the rest of the route's runtime evidence, **not scratch**. A baseline that lives only in a report
is a baseline the gate cannot read. Append-only: a record that overwrote its predecessor would
make *"when did this account last look right"* unanswerable.

Every row carries the attribution caveat verbatim:

> zero positions is attributable to every route; a non-zero count is attributable to none

On a shared login, seeing nothing proves no route holds anything. Seeing three proves only that
the login holds three — whose they are is a question this evidence cannot answer, and the record
says so rather than implying an owner.

## 6. What changed for the gate, and what did not

```text
  [PASS] audit_records_readable
  [FAIL] judgeable_days                      3 of 5
  [FAIL] no_failing_days                     3 FAIL days in the window
  [PASS] warn_days_within_allowance
  [PASS] evidence_is_recent
  [FAIL] calm_decision_evidence              the phases have not run
  [PASS] paper_account_baseline              <- new
  [FAIL] every_sleeve_passed_at_least_once
```

`orders_possible` stays **false**, blocking on B1 and `PAPER_SHADOW_EVIDENCE`. **No confirmation
file was created, no approval flag set, and no order directory exists.**

**B1 is unchanged as a gate.** It remains an operator decision plus a measurement; it can now
cite fresher account evidence, but nothing here signs it and nothing auto-creates a retirement
confirmation.

## 7. The dashboard, verified against the process rather than the file

Its own block and its own row, separate from the shadow evidence and from the slot verdicts —
the third time this panel has needed that separation stated, and the reason is the same each
time: two true facts about different things, folded together, send a reader to inspect the wrong
one.

The bidirectional fact pin caught the new row the moment it was added, for the third time this
week. It is declared.

**And I nearly reported this wrong.** The scheduler and backend had been restarted at 07:08 ET —
by the operator, through `ops.py`, while this work was in progress — and every file this stage
touched was written 16–18 minutes *after* that. From the mtimes I concluded the running backend
could not be serving the new block. Asking it directly said otherwise:

```text
running backend serves paper_account: True
{"status": "PASS", "currency": "USD", "equity": 250817.91,
 "line": "Paper account baseline: USD 250,818 — broker reconcile flat",
 "separate_from_shadow_evidence": true}
```

An inference from file times is not a measurement of a process, and this project's own record
says so in the stage two before this one. **No backend restart is required.**

The same check confirms the historical evidence survived: audits, window coverage and signals all
still present in the payload.

## 8. The restart that had already happened

The scheduler now running is PID **14344**, started **07:08:32 ET**, and its log shows it
registered the retry ladder *and* the pre-NKD last-chance job:

```text
spy_refresh_pm_r1        registered
spy_refresh_pm_r2        registered
spy_last_chance_pre_nkd  registered
```

So the restart Stages 5ZZC and 5ZZD were both waiting for is **done**, and both are live.
Nothing in the present stage needs one.

## 9. Two things this stage got wrong and fixed

**`operator_line` crashed on a PASS with no account block** — it formatted the equity
unconditionally and raised `TypeError`, which would have taken the whole readiness call down with
it. A reporting function that can crash turns a mild problem into no report at all. Found by a
mutation test, not by reading.

**A constant that looked like a setting and was not.** `MAX_RECORD_AGE_HOURS` was written into
`latest()`'s signature as a default argument — evaluated once when the function is defined — so
patching the module constant changed nothing and a stale record still read back as a PASS. Found
by the mutation that patched it and watched the test stay green. It is resolved at call time now.

## 10. Tests

**36**, in `scratch/test_track1_stage5zze_paper_account_baseline_20260827.py`. Nothing connects;
every broker reply is a stub.

The happy account · the currency staying attached when two are reported · CAD failing · **the
996,875.91 that B1 actually recorded failing today** · the three-band equity contract across
seven values · WARN not opening the gate · unreachable broker, missing currency, stale reading
and absent B1 all UNKNOWN · the books consulted through B1 and never re-implemented · durable
append-only records · the attribution caveat in every row · stale and unreadable records never
reading as PASS · readiness refusing without one and one check not opening the whole gate ·
**recording a baseline clearing no shadow evidence** · a dashboard 0/0 snapshot not accepted as
a broker reconcile · the connecting tool outside the gate-scanned prefix with no order path and
its own client id.

Five mutations, all red: the currency discarded · WARN satisfying the gate · a stale record read
as PASS · unreadable flattened into absent · readiness accepting a baseline never recorded.

Suites after: **259 passed** across the Track 1 and ops set, **220 passed** across the dashboard
backend and realtime contract.

Two failures in the B1 decision suite are **pre-existing** — they pin a blocker roster that
included `REGIME_LABEL_VERIFICATION`, released on 2026-08-26. Confirmed against the recorded
failure list from two stages ago rather than assumed.

Three suites needed repair and none was loosened: the ops-status check banned the *string*
`UNKNOWN (` across the whole output and this stage added a line that legitimately uses that shape
with a real reason code, so it is now scoped to the process lines it is about; and the readiness
fixtures grew an account baseline, because that is now part of what a clean period means.

## 11. What remains

| | |
|---|---|
| Calm DECIDE / OBSERVE | **09:32 and 10:02 ET, still pending** — it is 07:35 |
| `PAPER_SHADOW_EVIDENCE` | 3 judgeable days of 5, 0 carrying Calm evidence, all three FAIL days |
| `B1` | no decision recorded; its own measurement expires 11:34 ET today |
| the SEND wire | does not exist |
| this baseline | expires **11:29 ET tomorrow**; re-record with `python -m global_index.account_baseline_audit --broker ibkr --record` |
