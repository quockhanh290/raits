# Stage 5X — dashboard audit and Track 1 explainability scaffold

**Session 2026-08-23 · read-only against the monitor · nothing committed**

---

## What was done

Two independent pieces of work, both finished.

**The audit.** Every backend reader, every endpoint and every page that consumes them was
read, and the claims about their behaviour were then *measured* by running the real readers
against real or constructed input rather than inferred from the code. Full write-up:
`scratch/track1_dashboard_monitor_audit_20260823.md`.

**The scaffold.** A record format, a rule registry, a validator and a bounded writer, with a
test suite that was mutation-checked. Design note:
`scratch/track1_explainability_design_20260823.md`. Machine-readable schema, generated from
the code: `scratch/track1_explainability_schema_20260823.json`. Module:
`global_index/track1_explain.py`. Tests: `scratch/test_track1_explain_20260823.py`.

---

## The three findings worth acting on

### 1. The dashboard's decision panel is empty by construction, and has been all along

The live runner builds its per-session snapshot with a decision block holding four fields —
entries taken, candidates rejected, entries halted, and a detail list per rejection. All four
are initialised empty and **nothing anywhere writes into them**.

Measured on what is on disk right now:

```
live snapshots on file                    10        of which carrying any rejection detail: 0
                                                    of which carrying any entry:            0
                                                    summed "taken" across clusters:         0
                                                    summed "rejected" across clusters:      0

backtest replay snapshots               1749        of which carrying a rejection detail: 648
```

The backtest fills this channel. The live path does not. That is the live-versus-backtest
split this project has already paid for twice, arriving in the telemetry layer instead of the
trading layer.

The front end therefore prints *"No decision evidence emitted"* every session — and that is
indistinguishable from *"no signal today"*, which is exactly the conflation the day-runner's
own code comment says must not be allowed to happen. The day-runner avoided it by writing the
rejection to the **log** as an English sentence, and two readers recover it with a regular
expression over that sentence. So today, the only way a live rejection reaches a screen at
all is a substring match on prose.

That works. It is also the precise failure family this system has been bitten by before,
when a "did a job just launch" check asked whether the word *python* appeared in a line and
every traceback frame — which quotes the interpreter path — became a phantom job launch.

**I did not conclude whether the empty block is a design decision or a wiring gap.** Nothing
I read states the intent either way, and the two answers lead to different fixes. That
question is open and it touches what Track 1 should do next, so it is flagged rather than
closed.

### 2. Enabling the Track 1 slot mirror changes exactly one caption

The dashboard can be told about Track 1's slots by setting one environment variable. I
compared the entire schedule-status payload with the flag off and on, on a pinned Monday at
four pinned instants:

| ET instant | fields of the payload that differ |
|---|---|
| 07:00 | none |
| 09:50 | the "next scheduled job" caption |
| 11:00 | the "next scheduled job" caption |
| 12:15 | the "next scheduled job" caption |

The reason is that there are two slot tables and the flag only feeds one of them. The
"what runs next" table grows by twenty-five Track 1 slots; the table that drives freshness,
lateness, evidence rows and incidents does not grow at all (forty-five slots either way).
The active-window band is also unchanged, so a Track 1 window at 10:35–12:30 sits inside a
period the dashboard still labels *not expected yet*.

So with the mirror on, a Track 1 slot that fails is invisible. With it off, a Track 1 slot
that fires manufactures a fake incident. Both directions are already documented inside the
mirror; what is new here is the measurement of how far the flag actually reaches.

### 3. Sharing the trade log would fold Track 1 into legacy's pass/fail gates

The paper-evidence reader opens the trade log at the repository root and aggregates the whole
file, splitting on nothing. Its output drives gates on fill quality, on reconciliation against
the broker's own statement, and on the clean-session streak. Track 1 rows in that file would
be graded as legacy's, with no way for any reader to tell them apart.

Separately, one reader is a strict allow-list: I fed the persisted-position reader a row
carrying `route` and `explain_id` and **both were dropped**. The event log, by contrast, is
fully tolerant — I fed it six keys it has never seen and all six came back.

---

## The scaffold, and what it refuses

`global_index/track1_explain.py`. Pure, offline, imports no broker and no scheduler, and
**writes nothing unless a caller explicitly asks**.

- **Five record types** — signal, decision, execution, and two for meaningful silence — with
  statuses constrained per type so the stream stays filterable.
- **A deterministic identifier**, sha256 over route, session date, sleeve, instrument,
  candidate, record type, stage and sequence. Never Python's built-in hash, which is salted
  per process and would give the same record a different id on every run.
- **Thirty-eight rules** across the five families the brief asked for. Every rule names the
  file and symbol it lives in and the test or report that proves it. **Measured: zero of the
  thirty-eight point at a file that does not exist, and zero cite a test or report that does
  not exist.**
- **Thirty-four reason codes, none of them typed twice** — the decision verbs are imported
  from the signal layer, the bar refusals from the intraday gate, the staleness statuses from
  the freshness gate. If the signal layer gains a verdict, this registry gains it without an
  edit.
- **Code references are derived from the rule id, never supplied by the caller — and
  re-derived at validation.** A caller cannot name one rule and point at another file, and a
  record cannot be edited afterwards to say something the registry does not. The identifier
  and the evidence references are re-derived the same way. Builder and validator share one
  derivation function, so there is no second copy to drift. *(Added after review — see
  "Review round 1".)*
- **The route has exactly one source**, and the builder refuses a record whose identifier and
  route field disagree. *(Added after review.)*
- **A feature must carry its threshold**, and must say whether it passed. An absent value is
  legal and means *the feature was missing* — which for the context filter is a block, not a
  pass, and the record has to be able to say so.
- **An accepted decision must prove it checked the cap, the freshness gate and the breaker.**
  Omitting any of the three is refused.
- **A rejected decision must name a refusal reason and carry the detail.** All fourteen
  refusal reasons round-trip, including cap reject, family-cap reject, same-symbol suppress,
  breaker halt, freshness fail, intraday fail and no-setup.
- **The writer refuses any destination outside `scratch/track1_shadow`**, checked after path
  resolution so a relative escape cannot slip past, and it validates the whole batch before
  opening the file so a partial write cannot happen.

### The tests can go red

109 tests, all passing — which on its own proves nothing, so fourteen guards were broken in
process, one at a time, and the matching assertion checked. The first eight, from the
original build:

| Guard removed | Assertion that should fail | Result |
|---|---|---|
| the accepted-decision proof requirement | accepted decision must prove the cap gate | red |
| the per-rule required-feature list | a rule firing without its measured value | red |
| the identifier's hash function, swapped for Python's salted one | identifier stable across processes | red |
| the writer's path bound | writer refuses a legacy directory | red |
| the validator, made to always return "fine" | dropping a required field / unknown rule id / missing rejection detail | red (all three) |
| a rule pointed at a file that does not exist | every rule points at a real file | red |

Everything restored to green afterwards. The suite also asserts its own fixtures are
non-empty before iterating them, because a "check every rule" test passes silently on an
empty registry.

---

## Review round 1 — the validator was checking shape, not derivation

The owner's review found three gaps. All three reproduced. Probing the same family turned up
two more, and chasing the second of them turned up a defect in the **builder**, not the
validator.

### The three that were reported, and the two next to them

Every case below was measured to validate **clean** before the fix:

| What was tampered with | Old result |
|---|---|
| session date, stage or sequence edited after the build, identifier kept | accepted |
| identifier replaced with thirty-two zeros | accepted |
| route set to `legacy` | accepted |
| a code reference's file swapped for `wrong.py` | accepted |
| a code reference's symbol swapped | accepted |
| an **extra** code reference appended for a rule that never fired | accepted |
| an evidence path swapped for one that does not exist | accepted |

One root cause, not seven bugs. The builder derives the identifier, the code references and
the evidence references from the registry — and then **nothing ever re-derived them**. A
record travels: to JSON, into a file, back out, through an edit. After that, a derived field
is only a copy sitting beside the thing it claims to describe. That is the defect family this
whole registry exists to remove, and it had arrived in the one place whose job is to catch it.

### The builder defect the route finding exposed

Chasing the route case produced something neither the review nor I had named. The route
reached the record from **two sources**: the builder's `route=` argument fed the identifier,
and the provenance object's fields were merged in afterwards and silently overwrote the
field. Measured:

```
route argument passed to the builder : legacy
route field actually emitted         : track1_candidate
identifier built from                : the "legacy" spelling
```

A record whose identifier names one route and whose field names another, internally
inconsistent, passing every check. The provenance object no longer emits the route at all,
and the builder now **refuses** a disagreement instead of resolving it — picking a winner
would hide which caller was wrong.

This also settles a subtlety in the review's finding 2: the route check is **not** redundant
with the identifier check. A record built consistently for another route produces an
identifier that recomputes *correctly*, so only an explicit route rule refuses it. Both
checks are needed and they catch different things.

### What changed

- The identifier, the code references and the evidence references are **recomputed from the
  record's own contents at validation and compared**.
- The builder and the validator now call **one** derivation function. Not two
  implementations that agree today — a validator with its own copy of the rule is a second
  description, and second descriptions drift.
- The comparison is on **content, not order**. A record that reordered its own references on
  a round-trip is not tampered with, and a guard that fired for it is a guard people switch
  off. There is a test pinning that tolerance, and it goes red if someone "tightens" the
  comparison.
- The route must be Track 1's, checked explicitly.
- The route now has exactly one source, and a disagreement is refused at build time.

### The new guards were mutation-checked too

Six guards broken in process, one at a time; twelve assertions checked:

| Guard removed | Assertions that should fail | Result |
|---|---|---|
| identifier recompute | edited session date / edited stage / replaced identifier | red (3/3) |
| route rule | consistent foreign-route record | red |
| code-reference re-derivation | wrong file / wrong symbol / extra reference | red (3/3) |
| evidence re-derivation | forged evidence path | red |
| the route two-source bug, deliberately restored | route has exactly one source | red |
| order tolerance, deliberately removed | reordering references is not tampering | red |

All restored to green afterwards, including the round-trip and write-then-reread checks that
prove the new guards do not fire on honest records.

Suite: **89 → 109 tests**, all passing.

---

## Test results

```
BEFORE any of this work (baseline)
global_index/test_dashboard_live_snapshot.py
global_index/test_log_hygiene.py                     17 passed in 1.56s

AFTER the scaffold, BEFORE the review fix
  + scratch/test_track1_explain_20260823.py         106 passed in 5.14s   (89 new)

AFTER the review fix
  + scratch/test_track1_explain_20260823.py         126 passed in 3.83s  (109 new)

scratch/test_track1_stage3_route_20260822.py
scratch/test_track1_stage3b_blockers_20260822.py    113 passed, 2 skipped
                                                    (unchanged before and after)
```

The two required suites were also run **before** any of this work, as a baseline: 17 passed.
They still pass, unchanged.

`global_index/test_event_playback.py` was not run, as instructed.

---

## Constraints — every one held

| Constraint | Held | How it is known |
|---|---|---|
| no scheduler or service started | yes | nothing in this session launched a process; the schedule reader only enumerates |
| no IBKR connection | yes | the new module imports no broker; a test parses its imports and refuses a forbidden one |
| no live order | yes | no order path exists in anything written |
| no dashboard or runtime state write | yes | every monitor and runner file's modification time predates this session's start; the suite also fingerprints seven legacy artifacts plus every scheduler, day and event log before and after |
| no confirmation file | yes | none created; the order-gate confirmation path was read about, never written |
| no legacy retirement | yes | nothing removed |
| no commit | yes | working tree only |
| `test_event_playback.py` not run | yes | excluded from every invocation |
| legacy dashboard behaviour unchanged | yes | no monitor file touched; see the modification-time evidence above |

Three monitor files show as modified in the working tree. **None of them are mine** — all
three were already modified when this session began, and their modification times are from
2026-08-16, 2026-08-21 and 2026-08-23 00:52, all before this session started at 06:59.

Note also that another session is active in this repository: the Track 1 shadow output files
were rewritten at 07:01 today, two minutes into this session. Nothing here reads or writes
those files.

---

## Final verdict

**Dashboard audit complete?** Yes. Every backend reader, all thirteen endpoints and all four
pages mapped, with the tolerance of each reader measured rather than assumed.

**Explainability scaffold implemented?** Yes, and hardened once after review. Module,
schema, rule registry and 109 mutation-checked tests, none of it wired into anything. The
review found the validator was checking a record's *shape* but never re-deriving the fields
the builder had derived; seven tamper cases that validated clean now do not, and a
two-source route defect in the builder was found and closed in the process.

**Legacy dashboard behaviour changed?** No. No monitor file, no dashboard asset and no
runtime state file was written; the required dashboard suites pass at the same count as the
baseline taken before the work started.

**Ready to wire into the Track 1 shadow scheduler?** **Yes for the write path now — it was
not before the review, and the review was right to hold it.**

Wiring first and hardening later would have meant the first real explanations were written
by a validator that could not tell a tampered record from an honest one, and those rows would
then have been the reference set everything after was compared against. The writer is bounded
to the shadow directory in code, validates the whole batch before opening a file, re-derives
every derived field, and is proved by test to leave every legacy artifact byte-identical.

**Still no for the dashboard**, for the unchanged reason in finding 2: Track 1 slots are
invisible to every health signal, so a drawer would hang off a row that never appears.

Wiring it to a *screen* is not ready, for a reason that has nothing to do with this scaffold:
Track 1 slots are invisible to every health signal the dashboard has (finding 2), so an
explanation drawer would hang off a row that never appears. The slot table has to learn about
Track 1 first.

---

## Next step after Stage 5

In this order.

1. ~~Harden the validator.~~ **Done this round** — see "Review round 1".
2. **Settle finding 1.** Was the live decision block left empty on purpose, routing
   rejections through the log instead, or is it a wiring gap? Two different fixes follow, and
   the answer decides whether Track 1 should ever populate the existing decision panel or
   stay wholly in its own channel. This is a question for the project owner, not a
   measurement.
3. **Call the record builders from the shadow route** and write real explanations for a
   measured window. Then measure what a day actually produces — the volume estimate is
   deliberately absent from the design note because nobody has run it, and a plausible
   estimate presented as a measurement is a thing this project has been burned by.
4. **Teach the health slot table about Track 1**, gated behind the same environment flag the
   mirror already uses, so a Track 1 slot that fails can raise an incident. Until that exists,
   a Track 1 slot failing at 11:05 is silent.
5. **Then, and only then, the route-scoped endpoint** — new reader, new endpoint, no legacy
   schema touched.
