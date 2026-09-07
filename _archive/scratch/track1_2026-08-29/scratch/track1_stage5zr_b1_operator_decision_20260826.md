# Stage 5ZR — the decision is prepared, previewed, and deliberately not made

**2026-08-26, ET 08:20–09:00.** No orders · **no confirmation file created** ·
`TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no broker connection · **nothing
restarted** · no runtime file, book, trade log, checkpoint or audit record touched · legacy
drain safety left scheduled.

```text
UTC 2026-08-26 12:50 · ET 2026-08-26 08:50 EDT · Calgary 2026-08-26 06:50 MDT
```

---

## The ten answers

| | |
|---|---|
| 1. recorded or templated? | **templated only** — and the reason is measured, not cautious (§2) |
| 2. which decision type? | **neither can be recorded today** (§2) |
| 3. which measurement? | the 06:15:51 ET record, PASS, 2.2 h old, counts until 10:15 UTC tomorrow |
| 4. B1 released? | **pending** — measured half passes, decided half is empty |
| 5. the other two blockers? | **both still blocking**, and no decision file can reach them (§3) |
| 6. orders possible? | **false** — in every confirmation shape, simulated in memory |
| 7. broker/order action? | **none** — this stage opened no connection at all |
| 8. runtime/live file changed? | **no** |
| 9. legacy drain safety? | **still scheduled**, 11 jobs, and a decision cannot change that |
| 10. before a tiny paper probe? | five things; the fifth is still that the order path does not exist |

---

## 1. Baseline

```text
scheduler 18780   backend 48760   track1-only-shadow   orders_possible False
blocking  B1, PAPER_SHADOW_EVIDENCE, REGIME_LABEL_VERIFICATION
b1        PASS (legacy_and_broker_flat) — legacy 0, track1 0, broker 0, orders 0, orphans 0
          observed 2026-08-26 06:15:51 ET, 2.2 h old, limit 24 h
confirm   track1_go_live_confirmation.json — ABSENT
orders    global_index/track1_runtime/orders — ABSENT
env       TRACK1_ORDERS_APPROVED unset
```

## 2. Why Option 1, and it is not because the code might be unsafe

The stage offers Option 1 *"if unsure whether live confirmation can safely hold partial B1
decision"*. **It can.** Simulated in memory, writing nothing:

```text
nothing                     -> orders_possible=False  blocking=[B1, PAPER, REGIME]
legacy_retired_confirmed    -> orders_possible=False  blocking=[PAPER, REGIME]
separate_account_confirmed  -> orders_possible=False  blocking=[PAPER, REGIME]
decision + waiver           -> orders_possible=False  blocking=[PAPER, REGIME]
```

The mechanism is safe. The refusal is on the **merits: neither decision is true today.**

### `legacy_retired_confirmed` — legacy is dormant, not retired

Measured, by building the scheduler both ways without starting it:

| | track1-only-shadow | default mode |
|---|---:|---:|
| total jobs | 101 | 61 |
| Track 1 jobs | 86 | 0 |
| **legacy entry jobs** | **0** | **45** |
| legacy safety (drain) | 11 | 12 |

**The difference is one command-line flag.** `python monitor\ops.py restart --scheduler`
without `--track1-only-shadow` puts 45 legacy entry jobs back, and a recorded
`legacy_retired_confirmed` would go on reading as true through all of it.

Retiring legacy is the switch-over runbook's ordered procedure in §3. It has not been run, and
its eleven drain jobs are still scheduled — which this stage was explicitly told not to
disable. A route whose drain is still running has not retired.

### `separate_account_confirmed` — there is one account

Equity 996,883, and it is the account the dashboard reader, the safety jobs and yesterday's B1
probe all connect to. Nothing in this system has ever observed a second one, so the
measurement cannot corroborate this decision at all.

### And it is not mine to make

The runbook is explicit that the confirmation file is *written by a person, never by a script*.
That includes this one. What I can do is make the decision cheap to inspect and expensive to
make by accident, which is what was built.

## 3. What a decision file could and could not reach

Structural, not situational:

```text
B1                              USER_DECISION_GATE  released_by=(legacy_retired, separate_account)
                                                    also_requires=legacy_broker_flat
PAPER_SHADOW_EVIDENCE           MEASURED_GATE       released_by=()
REGIME_LABEL_VERIFICATION       MEASURED_GATE       released_by=()
LIVE_FRAME_ADAPTER_VERIFICATION MEASURED_GATE       released_by=()
```

`self_check` refuses a `MEASURED_GATE` that any confirmation flag could open — enforced, not
merely intended. So a B1 decision reaches B1 and stops there.

## 4. The template, inert by construction

The realistic accident is not a misunderstanding; it is a **verbatim copy**. So the template
refuses by construction rather than by instruction, for two independent reasons:

```text
validates      : NO — grants nothing
                 - confirmed_by must be a non-empty string naming a person
                 - confirmed_at must be a non-empty ISO date string
                 - unknown key(s) ['_CHOOSE_ONE', '_HOW_TO_USE', ...] — refused rather
                   than ignored
```

Every explanatory key begins with an underscore, and an unknown key refuses the **whole** file
— a confirmation that half-parses must never half-open a gate. Delete them all, which is the
realistic edit, and the empty operator name still refuses it.

## 5. A previewer, so the effect is visible before the commitment

`python -m global_index.track1_b1_decision <candidate>` — read-only, and *strongly* so: it has
no code path that writes anything, asserted by watching every file opened for writing and
again by AST, and it never names the live confirmation path so a bare invocation cannot drift
into reading the real one.

Run against a filled candidate, in a temp directory, never at the live path:

```text
  validates      : yes
  decision       : legacy_retired_confirmed
  B1 measurement : PASS (legacy_and_broker_flat)
                   counts until 2026-08-27T10:15:51Z
  legacy entries : none

  would release  : B1_broker_account_or_legacy_retirement
  would still block: PAPER_SHADOW_EVIDENCE, REGIME_LABEL_VERIFICATION
  orders possible: False

  read before writing:
    * Legacy is dormant because of a command-line flag, not because it has been retired:
      a restart without --track1-only-shadow registers its entry jobs again, and this
      recorded decision would go on reading as true.
```

That last paragraph is the point of the module. The warning is raised at the moment of
decision, which is the only moment it helps — and it is **not** folded into the measurement's
PASS/FAIL, because for a *separate account* decision legacy entry jobs running is correct
rather than a fault. A gate that cannot tell those apart would be wrong half the time.

## 6. The readiness report was describing a gate it did not consult

Its closing paragraph said the order gate *"requires B1 released by a confirmation file"* —
true until Stage 5ZQ, and quietly wrong ever since. It now reports B1 as two halves, and says
what no gate can fix:

```text
  B1 — the two halves, and neither is the other:
    decision    : pending — no decision is recorded
    measurement : PASS (legacy_and_broker_flat)
                  Legacy book flat, Track 1 book flat, broker flat, no working orders.
                  observed 2026-08-26T10:15:51Z, counts for 24h
    B1 blocking now: True
    also blocking  : PAPER_SHADOW_EVIDENCE, REGIME_LABEL_VERIFICATION
    orders_possible: False
```

The evidence half, unchanged and unflattering: **2 judgeable days, both FAIL, no sleeve has
PASSED inside the window.** Five clean days are required.

## 7. Two of my own tests proved nothing, and the sweep caught both

**The template's "more than one reason" test** stripped the underscore keys and checked the
file still refused. Remove the underscore guard from the template itself and that test stays
**green** — because it removes the guard itself. A test that performs the mutation it is meant
to detect cannot detect it. It now works by **ablation**: each defence is removed in turn and
refusal must survive every removal, with a control that must validate so the ablations cannot
pass for a reason nobody has identified.

**The legacy-capability test** inventoried the constants returned anywhere in the function and
required all three. Change the no-scheduler branch from UNKNOWN to NONE and all three are
still present — the exception handler still returns UNKNOWN — so the function began reporting
*"legacy cannot enter"* about a scheduler it could not see, and the test stayed green. The
branch is now **exercised**, not inventoried: three parametrised cases drive the process
lookup and assert the answer.

Both are the same lesson in different clothes: a test that lists what exists is not a test of
what happens.

## 8. Tests

**30 tests**, structured payloads, AST and observed file access — no prose greps. All nine
required scenarios, plus the template's inertness, the previewer's silence, and an AST check
that the route still constructs `NoOrderBroker` and never `IBKRBroker`.

**Mutation sweep: 12 of 12 red** — after the two rewrites above. On the first sweep two came
back *still green*, which is why the sweep exists.

## 9. What remains before a tiny paper probe

| | item | class |
|---|---|---|
| 1 | the B1 decision — **and the state of the world that makes it true** | operator |
| 2 | five clean judgeable shadow days (today: 2, both FAIL) | time |
| 3 | the regime gate's first PASS | time |
| 4 | machine sleep | operator |
| 5 | **the order path** — `run_live_day_track1` constructs `NoOrderBroker` and never `IBKRBroker` | code, unwritten |

Item 1 has changed shape this stage. It is no longer *"sign the file"*: it is *decide which
route owns the login, and make that true* — either by running the switch-over procedure, or by
funding a second account. The file records the decision; it does not perform it.

### For the operator

```powershell
# preview any candidate before it goes anywhere. Writes nothing.
python -m global_index.track1_b1_decision scratch\track1_b1_decision_template_20260826.json

# refresh the measurement — it expires 24h after 2026-08-26 10:15 UTC, on purpose
python -m global_index.b1_audit --broker ibkr --record
```

## 10. Regression, and the ledger it uncovered

**Targeted:** 407 passed, 4 failed — the four are the 5C slot-count family, measured
pre-existing during Stage 5ZQ's bisect.

**Across all 33 suites that touch the gate registry or the readiness report:** 1196 passed,
30 failed. Three of those thirty are in the **ledger** suites, which the 5ZQ bisect never
covered because they were not among the fourteen it ran. **One of the three is mine.**

### The one I caused, and the test was right to fire

`test_ledger_releasing_every_gate_would_open_the_route` asserts the blocker set is
*satisfiable* and *not by signatures alone*: hold each measurement shut in turn, and exactly
the gates that depend on it must be the ones still refusing.

Stage 5ZQ introduced a **second kind of measurement** and that loop only knew the first:

```text
released_by_measurement    an OR   — the measurement passing OPENS the gate
also_requires_measurement  an AND  — passing is REQUIRED even once the gate is signed
```

So `legacy_broker_flat` came back as *"releases no order-blocking gate"* — true, and beside
the point. Both kinds are covered now, with the same claim for each. For an AND-measurement it
is the **stronger** statement, because the gate refuses with every signature already granted.

And while I was in there it gained an assertion it did not have: granting **only** the waiver
flags, with every measurement held shut, must open nothing. The escape hatch built for *"the
broker could not be reached"* must never become a way in.

### The ledger had been stale for a whole stage

| | stale since | what it said |
|---|---|---|
| `track1_blocking_ledger_20260822.json` | 5ZL | `blocking_now` listed **2** blockers; there are 3 |
| `track1_blocking_ledger_20260822.md` | 5ZL | it did not mention `REGIME_LABEL_VERIFICATION` **at all** |

The markdown is the document an operator reads to know what is holding the route, and it
omitted a gate they are currently held by. That is worse than having no ledger, because it
reads as complete — the same reasoning that made the false *"a slot asks for orders"* alarm
worth fixing in the previous stage.

Both are repaired: the JSON regenerated from the registry, which is exactly what its own
failure message instructs; the markdown given the missing gate, written from the registry's own
text, plus a section recording that B1 now needs a decision **and** a proof.

**The process gap is left open and named.** `as_ledger()` has **no writer anywhere in the
repo**. "Generated from the registry" is true in intent and manual in practice, which is
precisely why it went a whole stage without being regenerated. A regeneration step belongs in
whatever stage next touches the registry; adding another module to a stage about the B1
decision is not the place for it.

### The other twenty-seven

Unchanged from the previous stage's bisect and not mine: roster pins stale since 5S and 5ZL,
absence proxies stale since 5ZN, slot-count pins stale since 5N, and five in 5ZO and the
freshness suite that were **not** traced — naming a cause for those would be a guess.

### After the fixes

```text
1201 passed, 25 failed, 3 skipped        (was 30 failed)
```

**All five that went green were ledger-parity tests** — three repaired by regenerating the
record and the document, one by teaching the satisfiability test the second kind of
measurement, and two more that were reading the same record.

The remaining twenty-five include four suites the previous stage's bisect never covered, so
they were checked individually here rather than assumed. All four land in the same two
families:

| | what it expects | why it is stale |
|---|---|---|
| the measured-gate set is one gate | `{LIVE_FRAME_ADAPTER_VERIFICATION}` alone | 5S and 5ZL each added one |
| the blocker roster | `{B1, PAPER_SHADOW_EVIDENCE}` | 5ZL added a third |
| no coverage ledger exists | no `window_coverage_*.jsonl` | the shadow route has written one every day since 2026-08-24 |
| shadow keeps every legacy entry slot | 25 slots, two windows | 5N gave the route all four sleeves |

Worth stating plainly, because it is the one that could have been mine: the measured-gate test
fails on the two gates added by earlier stages, and **`legacy_broker_flat` is not in that set
at all** — it is an AND-requirement on a decision gate, not a measured gate of its own.

