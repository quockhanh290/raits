# Stage 5ZD — signal diagnostics, and the honest gap it exposed

**2026-08-25, ET 11:45–12:05.** Observability only · no order · no broker · no IBKR call · no
confirmation file · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · **no scheduler or
backend restart** · every test write under `tmp_path`.

```text
UTC 16:05 · ET 12:05 EDT · Calgary 10:05 MDT · Tokyo 01:05 JST (26th)
```

---

## Verdicts

| | |
|---|---|
| signal diagnostics | **READY — and already live** |
| dashboard integration | **READY** |
| paper | **still blocked** — B1 and `PAPER_SHADOW_EVIDENCE` unchanged |
| restart needed | **no** — see below |
| live/runtime file touched | **only by production itself**, writing its own new rows |

### It went live without a restart, and there is proof

Slot subprocesses import fresh — the Stage 5V-1 finding. So the writer became live the moment
the file was saved, and by 12:00 ET the running scheduler had produced three real rows:

```text
TRACK1_STRESS_1150  11:50  NO_SIGNAL  candidates 0
TRACK1_STRESS_1155  11:55  NO_SIGNAL  candidates 0
TRACK1_STRESS_1200  12:00  NO_SIGNAL  candidates 0
```

Written by production, into `global_index/track1_runtime/signals/`, with no restart and no
intervention. The reader and the job view were then checked against those rows rather than
against a fixture.

---

## What the first real row actually says

This is the whole point of the stage, so it is worth reading in full:

```text
gate_allow                    measured               passed=True
freshness_allow               measured               passed=True
no_regime_label_required      not_exposed_by_sleeve  passed=None
breadth_down_count            not_exposed_by_sleeve  passed=None
gapdown_count                 not_exposed_by_sleeve  passed=None
avg_gap                       not_exposed_by_sleeve  passed=None
mnq_only_short_setup          not_exposed_by_sleeve  passed=None
pre_high_stop_reference       not_exposed_by_sleeve  passed=None
stop_within_max_pct           not_exposed_by_sleeve  passed=None
rr_target_computed            not_exposed_by_sleeve  passed=None
same_symbol_suppression       not_reached            passed=None
family_cap                    not_reached            passed=None
cluster_cap                   not_reached            passed=None
```

**Two rules are measured. Eight are not.** The eight run *inside* the Stress detector, which
does not return their values, and the three admission rules were never reached because no
candidate got that far.

### Why they are not filled in, and why that is the right answer

The obvious way to give every row a number was to recompute breadth, the gap count and the
average gap here. I did not, because **a second implementation of a strategy rule is a second
answer to the same question**, and it disagrees with the one that trades on the day it matters.
This project has paid for that twice already.

So `RuleCheck` has three answer sources and all three are visible:

| source | meaning |
|---|---|
| `measured` | the slot computed it and `value` is real |
| `not_reached` | the sleeve stopped before this rule ran |
| `not_exposed_by_sleeve` | **the rule DID run, and the detector does not return its value** |

The third is the honest one, and it is deliberately not counted as a pass anywhere: not in
`primary_failure`, not in the summary, and not in the dashboard, where it renders as
`unknown` in the warning colour rather than the good one. A rule the sleeve did not report has
**not been shown to be fine**.

The one-line summary says so out loud rather than falling silent:

```text
Signal: NO SIGNAL · candidates 0 · blocker not reported (8 rules)
```

A line that named no blocker would read as *"nothing was close"*. The truth is *"the sleeve did
not tell us"*, and those are different days.

**The follow-up this makes obvious:** for the diagnostics to name a real blocker, the four
sleeve detectors must return their rule values. That is a change to the sleeves and belongs to
its own stage, with the reproduction re-run behind it. Recorded, not attempted here.

---

## The five statuses, and the pair that must not collapse

```text
SLOT_REFUSED            the gate or live source said no; the sleeve never ran
NO_SIGNAL               the sleeve ran, looked, nothing produced a candidate
RAW_SIGNAL_FOUND        a candidate exists, not yet through admission
SIGNAL_REJECTED         a candidate existed and a NAMED layer refused it
SIGNAL_ACCEPTED_SHADOW  the book admitted it, and no order was attempted
```

**`NO_SIGNAL` and `SIGNAL_REJECTED` must never be the same row.** One means the market offered
nothing; the other means it offered something and this route declined it. A summary showing
both as "no trade" would hide every cap, every family limit and every suppression. `classify()`
is a separate pure function precisely so a test can drive every combination directly, and two
mutations exist to collapse it.

Rejections carry a **named layer** — `freshness`, `admission`, `cap`, `same_symbol`, `window`,
`route_switch` — mapped by an explicit table, not a `startswith("reject_")` that would flatten
`reject_cap` and `reject_family_cap` into one.

Accepted-shadow rows carry `accepted=true`, `orders_enabled=false`, `order_attempted=false`,
`reason=shadow_only`, and the row **refuses to be constructed** if it claims otherwise. That is
the one claim this journal exists to make impossible.

---

## A missed slot is not a row

If a slot never spawned, nothing is written. Manufacturing a `NO_SIGNAL` would turn *"the
machine was asleep"* into *"the strategy looked and declined"* — and yesterday the machine slept
through the whole Calm window, so this is not hypothetical.

A third reading was needed within an hour of building it. The 22 NKD slots and 11 Stress slots
that ran **before** the journal existed are not missed either:

| reading | means |
|---|---|
| `SLOT_MISSED` | never spawned — operations health, from schedule-status and the audit |
| `SLOT_NO_ROW` | **ran and left no row** — predates the journal, or the channel was disabled |

The job view picks between them from the job's *own* status. Rendering those 33 as MISSED would
have accused the scheduler of failing when it had not.

---

## Scope: 70 strategy slots, nothing else

Enforced in two independent places, and a test asserts each:

- `SignalRow.__post_init__` refuses any sleeve outside the four strategy sleeves;
- the job view types Track 1 strategy slots by prefix — checked **before** the legacy
  prefixes, so `TRACK1_STOP_REPAIR_*` is not mistyped as a `stop_repair` job — and attaches no
  `signal` key at all to anything else. Not an empty one: a `signal: null` on a stop-repair row
  invites a renderer to print "no signal" about a job that has no signals to have.

Verified against the real log: **33 strategy jobs carry the key, 10 non-strategy jobs do not.**

---

## Dashboard — two layers, no new card

**Track 1 Runtime panel:** one compact row, `Signals today`, in the existing fact-row style.
Per sleeve: latest status, latest slot time, today's counts, and the latest accepted signal if
any — stated *with* "no order attempted" so nobody reads an admission as a trade. No per-slot
detail here; duplicating it would give the operator two places to read the same thing and two
places for them to disagree.

**Job view:** one sentence under the existing status line, on strategy slots only:

```text
Signal: NO SIGNAL · candidates 0 · blocker not reported (8 rules)
Signal: ACCEPTED SHADOW · MNQ short · risk $420 · order not attempted
Signal: REJECTED · cap · MNQ short · risk $420
Signal: REFUSED · gate_refused · stale
Signal: NO DIAGNOSTICS · slot ran, no diagnostics row
```

**The sentence is composed by the backend**, not the browser. One owner for the phrasing means
a test can assert it and the two cannot drift. `rule_checks` and candidate detail appear only
when the row is expanded.

The line sits inside the existing job row at `grid-column: 1 / -1` with `overflow-wrap:
anywhere` — it wraps rather than widening the table, and the rule grid collapses to two columns
under 720px.

Absent file renders **"not yet observed"**, never an error. A disabled channel renders as
disabled with its reason, never as a quiet day.

---

## Tests and mutations

**68 tests. 30 mutations, all red**, each with a proven-green baseline.

The last five tests are the ones that matter most — they drive the **real** `observe_live_slot`
through the real frame path:

| | |
|---|---|
| 48 | a decided slot writes exactly one row, with the sleeve's rules on it |
| 49 | a **refused** slot still writes its row — the refusals are the days worth explaining |
| 50 | the row lands under the runtime tree, not scratch |
| 51 | a diagnostics failure does not cost the slot its coverage row |
| 52 | the slot's own decision is **identical** with the journal on and off |

A journal nobody calls is a journal that does not exist, and this project has already shipped a
safety mechanism with code, docs and a "grep-verified" note that was wired into no entry point.

Mutations cover every negative the stage named: the classification collapsing, `rule_checks`
omitted, an unexposed rule flattened into a pass, accepted-shadow claiming an order, an absent
file becoming an error, a missed slot faked as `NO_SIGNAL`, a non-strategy job annotated,
thresholds becoming a second hardcoded copy, the diagnostics written *before* the coverage row,
and four on the dashboard including *"an unreported rule coloured like a pass"*.

### My own fixture was wrong first

The end-to-end frames I hand-rolled were refused with `frozen_clock`. Rather than patch around
it I imported the Stage 5Q3 helpers, which already encode the clock contract. A fixture that
does not play the real data source is a fixture that tests itself.

---

## Two tests I had to correct, both mine to fix

**`5Z::test_31`** pinned *exactly one* `mode=tx.SHADOW_LIVE` in the live slot. The diagnostics
row records the mode it decided under, making two — an honest addition that read as a
regression. It now asserts **every** `mode=` is `SHADOW_LIVE`, which is what its own docstring
always claimed and is strictly stronger.

**`5Q3::test_this_suite_never_wrote_into_the_real_runtime_tree`** asserted *"no `.jsonl`
anywhere under the real shadow tree"*. That said what it meant only while the route had never
written an explanation — and at 11:10 ET today the first Stress slots decided and wrote theirs.
Same family as pinning a row count on a ledger still being appended to.

A before/after snapshot was not the fix either: the live route writes into that tree every five
minutes during a window and would be blamed on the suite. So the durable property is asserted
directly — the shadow directory is a **relative** constant and the fixture hands the slot a tmp
root, which is what structurally prevents this suite writing there — with a snapshot kept for
anything landing outside the live-explanations path, which only a leak would produce.

---

## Regression

| | result |
|---|---|
| Stage 5ZD | **68 passed** |
| Stage 5ZD mutations | **30 red, 0 green** |
| combined: 5ZD · 5ZB · 5ZA · 5V-1 · 5Q3 · 5Z · 5Y · 5X · 5W · 5S · 5R-0 + dashboard/backend/DOM/contract suites (15 files) | see below |

---

## Files

```text
global_index/track1_signals.py                  NEW — journal, statuses, rule catalogue, summary
global_index/run_live_day_track1.py             + the diagnostics row, AFTER the coverage row
monitor/backend/track1_runtime_reader.py        + the compact signals summary
monitor/backend/job_journal_reader.py           + per-strategy-job signal line and details
global_index/dash/realtime/realtime.js          + one panel row, one job line, expanded checks
global_index/dash/realtime/realtime.css         + the styles, wrapping not widening
scratch/test_track1_stage5zd_signal_diagnostics_20260825.py   68 tests
scratch/track1_stage5zd_mutations_20260825.py                 30 mutations, all red
scratch/test_track1_stage5z_callsite_dryrun_20260825.py       mode assertion strengthened
scratch/test_track1_stage5q3_live_frame_splice_20260824.py    tree guard made structural
```

---

## What this does not do

It does not enable orders, and it cannot: the module imports no broker, no executor and no
order journal, asserted by AST. Every row states `orders_enabled=false` and
`order_attempted=false` explicitly rather than leaving a future reader to assume a default.

`orders_possible=False`; `B1_broker_account_or_legacy_retirement` and `PAPER_SHADOW_EVIDENCE`
both still blocking; no confirmation file; env unset; no `--allow-orders` anywhere.
