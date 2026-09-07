# Stage 5ZZK — the gate could not see the decision

**2026-08-27.** No orders · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no orders
directory · scheduler not restarted · no broker connection · no runtime trading file edited.

---

## Root cause, in one line

**`blocking()` defaulted to `NO_CONFIRMATIONS`, so with no argument it answered a question
nobody was asking: *what would still block if the operator had signed nothing?***

Not a schema mismatch. Not stale evidence. Not a hidden predicate inside B1. The confirmation
file was valid, was parsed correctly, and released the gate the moment it was actually passed —
and almost nothing passed it.

## Part A — reproduced before anything was touched

```text
confirmation           True
track1_blocking        ['B1_broker_account_or_legacy_retirement', 'PAPER_SHADOW_EVIDENCE']
orders_possible        False
B1 measurement         PASS (legacy_and_broker_flat)  observed 2026-08-27T16:04:17Z
paper baseline         PASS (account_flat_and_funded) observed 2026-08-27T11:29:47Z

sha256  track1_go_live_confirmation.json                   67504a1c8a31a6a4…
sha256  scratch/track1_b1_decision_candidate_20260827.json 67504a1c8a31a6a4…   identical

confirmation top-level keys:
  confirmed_at · confirmed_by · legacy_retired_confirmed · note · schema_version
```

## Part B — the trace, run against the real payload

```text
load_confirmations(CONFIRMATION_PATH)
    errors  []
    flags   {'legacy_retired_confirmed': True}
    by      kevindo290

BLOCKERS[B1].released(conf)          True      <- the gate agrees
BLOCKERS[B1].released(NO_CONFIRM)    False

blocking(conf)   ['PAPER_SHADOW_EVIDENCE']                              <- correct
blocking()       ['B1_…', 'PAPER_SHADOW_EVIDENCE']                      <- what everyone sees
```

The predicate was never the problem. The **argument** was.

### Who passed confirmations

Exactly one caller in the repository:

```text
run_live_day_track1.py:181   gates.blocking(self.confirmations)     <- the only one

monitor/ops.py:735           gates.blocking()
monitor/ops.py:774           gates.may_enable_orders()
track1_paper_readiness:442   g.blocking()
track1_runtime_reader:246    _g.blocking()
track1_paper_executor:188    G.may_enable_orders()
track1_gates.as_ledger       blocking()
```

So the status command, the readiness report, the dashboard, the ledger and the order executor
were all blind to anything the operator ever signed. **B1 could never be observed closing** by
any of them.

**Classification:** *another hidden predicate* — more precisely, **the reader never read the
file; a default argument stood in for a decision nobody loaded.** Same family as an empty list
standing in for an error, which this project has now met four times.

**It failed closed**, so nothing unsafe followed — the order executor also took the blind
default and would have refused. But a gate that cannot be seen to open is a gate nobody can
finish.

## Part C — the fix, and the strengthening that came with it

### 1. The default now reads the file

```python
def blocking(conf: "Confirmations | None" = None) -> list:
    if conf is None:
        conf = current_confirmations()
```

`current_confirmations` returns **nothing granted** on any parse failure, so an unreadable or
half-parsed file still holds every gated blocker shut. The unsigned view is still available —
`blocking(NO_CONFIRMATIONS)` — and the preview now asks for it by name.

### 2. B1 now checks what the decision actually claims

The decision does not merely assert "the account is flat". It asserts **this route owns this
login**. `also_requires_measurement` moved from `legacy_broker_flat` to a composite that
subsumes it:

```text
B1 audit        PASS, inside its own age policy
Track 1 book    stamped track1_candidate — read from the file the audit names
paper baseline  PASS, inside its own age policy
account         the baseline names one; compared with the audit's when the audit has one
```

Strictly stronger — every input the old measurement required is still required — and it adds
the two Part C.2 asked for that nothing had ever checked: the route stamp and the account
baseline.

### A check that could never fail, caught before it shipped

The first version of that function took the route and the account id **from the audit record**.
Neither field is recorded there. Both clauses were `if value and value != expected`, so both
were skipped every time — a check that never fires, appearing in the reasons list exactly like a
check that passed.

Caught by printing the detail and noticing two clauses had produced no words. Now the route is
read from the book file the audit names, and a missing or wrong stamp is a refusal.

One comparison is still not possible: the B1 audit records no account id, so the two records
cannot be cross-checked against each other. **That is reported as an unchecked clause, not
counted as a passing one:**

```text
B1 audit PASS (legacy_and_broker_flat); book route track1_candidate;
account baseline PASS (account_flat_and_funded); account DUR125337;
NOT CHECKED: the B1 audit records no account id, so the two records cannot be cross-checked
```

## Part D — verified

```text
track1_stop_trading=False  confirmation=True  track1_orders_approved=False
track1_blocking=['PAPER_SHADOW_EVIDENCE']  orders_possible=False
b1_legacy_flat=PASS (legacy_and_broker_flat)  legacy_book=0 track1_book=0
  broker_positions=0 working_orders=0 orphans=0
orders dir: ABSENT
```

Every expected value, exactly.

## Part E — tests

**28** in `scratch/test_track1_stage5zzk_b1_confirmation_recognition_20260827.py`, covering all
eleven items. The canonical fixture is the operator's real file read off disk, and one test
asserts it still matches — if the file changes, this suite stops testing a schema nobody uses.
Item 11 is shown rather than claimed: the preview parses through
`track1_gates.load_confirmations` and is asserted never to parse the confirmation itself, so
there is no second schema to drift.

### Two bugs in my own fix, both found by tests

**`path: str | Path = CONFIRMATION_PATH` bound the constant at definition time.** Patching
`CONFIRMATION_PATH` changed nothing while appearing to, so three refusal tests were quietly
reading the *production* file and passing for the wrong reason. Resolved at call time now. This
is the identical trap that cost Stage 5ZZE two days ago in `track1_account_baseline`.

**A test read prose instead of behaviour.** "The gate registry must not read the approval
variable" searched the source for `TRACK1_ORDERS_APPROVED` — which appears in the registry's own
evidence text describing what that variable is. Rewritten behaviourally: set the variable, assert
the blockers do not move.

### Ten tests that had stopped testing their own names

Widening B1's required measurement meant `monkeypatch.setitem(MEASUREMENTS,
"legacy_broker_flat", …)` no longer reached the gate — the patch sat there while the gate
consulted the real evidence past it. **Ten seams across 5ZR and 5ZQ**, plus the whole 5ZZJ
fixture, were repointed at the measurement the gate now asks for. Without that, five tests named
"a decision without a usable measurement still blocks" would have gone on passing for reasons
they had not chosen.

### Five tests restated because the world changed

Not weakened — the operator signed, and B1 genuinely closed:

| test | was | now |
|---|---|---|
| 5ZR 23 | no confirmation file exists | *this stage* created none; if one exists it must validate |
| 5ZR 24 | orders impossible **and B1 blocks** | orders impossible, and the evidence gate is why |
| 5ZQ 32 | ledger publishes `legacy_broker_flat` | publishes the composite, and the name resolves |
| 5ZQ 35 | orders impossible, no confirmation file | orders impossible; that never depended on the file's absence |
| 5ZQ 36 | **B1 still blocks today** | B1 is closed — *and never by a signature alone*: remove the measurement and it returns |

The last one is a better test than the one it replaced. "B1 still blocks" was true only while
nobody had decided; what is worth guarding is *why* it opened.

### Mutations — 8/8 RED

```text
the default stops reading the signed file (the original bug)   30 failed
B1 goes back to asking only whether the account is flat        12 failed
a book stamped with another route is tolerated                  2 failed
the account baseline's status stops mattering                   2 failed
a baseline naming no account is tolerated                       1 failed
an account mismatch between the two records is tolerated        1 failed
an unreadable confirmation file grants its flags anyway         1 failed
the preview baselines against the already-signed state again    1 failed
```

The seventh came back **GREEN** on the first run, and the reason is worth recording because it
is not the usual one. That mutation rewrites the body of an `except` inside
`current_confirmations` — and that `except` never fires: `load_confirmations` answers bad JSON
by returning nothing-granted rather than by raising. So the mutation was rewriting
**unreachable** code and could not have changed any outcome.

An unreachable guard is not a sleeping guard; it is worse. It looks like a safety net in the
source, and a real failure later finds nothing underneath it. The fix was not to retarget the
mutation but to make the guard reachable on purpose: a test now forces the loader itself to
raise — an unreadable mode, a path that explodes on `exists()` — and asserts the gate still
grants nothing. With that test in place the original mutation turns red, because there is
finally a path that runs it.

### Suites

```text
5ZZK + 5ZZJ + 5ZR + 5ZQ + ops + ops-status + dashboard backend + realtime contract   379 passed
```

**Pre-existing failures: none.** The ten seam repoints and five restatements were all caused by
this stage's own change and are itemised above; nothing was left red.

## Part F — safety, before and after

```text
track1_runtime/orders          ABSENT           (before and after)
TRACK1_ORDERS_APPROVED         unset            (and setting it moves no blocker — tested)
--allow-orders                 absent from run_scheduler.py and monitor/ops.py
scheduler restarts             0
broker connections             0
runtime trading files edited   none — the confirmation was placed by the operator in 5ZZJ
orders_possible                False            (before and after)
```

Reading a confirmation makes a signed decision **visible**. It cannot make it **sufficient**:
orders additionally require the approval variable out of band, `--allow-orders` on the command
line, and `PAPER_SHADOW_EVIDENCE`, which is measured and cannot be signed for.

---

## Final report

| | |
|---|---|
| **Root cause** | `blocking()` defaulted to `NO_CONFIRMATIONS` and never read the signed file; one caller of seven passed confirmations |
| **Before blockers** | `B1_broker_account_or_legacy_retirement`, `PAPER_SHADOW_EVIDENCE` |
| **After blockers** | `PAPER_SHADOW_EVIDENCE` |
| **Schema accepted** | v1: `schema_version`, `confirmed_by`, `confirmed_at`, `legacy_retired_confirmed`, `note` — unchanged, and unchanged deliberately: the operator's file is valid and re-signing was never necessary |
| **Schema rejected** | wrong `schema_version`, missing/blank `confirmed_by` or `confirmed_at`, unknown or misspelled keys, non-boolean flags, a waiver with no reason — any error yields **no** confirmations at all |
| **B1 closed** | **Yes** — by a decision **and** a passing composite measurement |
| **Orders still impossible** | **Yes** — `PAPER_SHADOW_EVIDENCE` holds, approval unset, no order path activated |
