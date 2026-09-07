# Stage 5ZZZ-E — Calm, observable without DECIDE learning what OBSERVE knows

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## The answers

| question | answer |
|---|---|
| **DECIDE** values now published | instrument, direction, causal daily ATR, **stop rule**, stop **distance**, risk if taken, entry reference **time** |
| **OBSERVE** values now published | instrument, entry reference **price**, **planned stop**, causal daily ATR, stop distance, risk — and only behind a matched DECIDE |
| Can an OBSERVE-only value leak into DECIDE? | **No**, and the split is derived from the detector's own dataclasses rather than a hand-kept list |
| Any decision / gate / order behaviour changed | **No.** This stage adds no runtime writer at all |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

---

## 1. The runtime half already existed

Reading the Calm path before building anything changed what this stage is. `_write_shadow_intent`
already appends a **DECIDE row at 09:32 and an OBSERVE row at 10:02, on every path including the
refusals** — its own docstring says *"silence is the one outcome that is not allowed"*. It already
carries `params_hash`, `data_identity`, the risk inputs and the refusal codes.

So the runtime half of this stage is a **reader**. A second writer would put two accounts of one
phase on disk, and the day they disagreed nobody could say which one was the slot. A test asserts
the Calm half of the new module contains no append call.

That also means **nothing in the live Calm path was touched** — no new failure mode was introduced
where a slot decides.

---

## 2. Where the line is, and why it is not a judgement call

```text
detect_entry_for_day  IS  detect_setup_before_entry  +  entry price  +  entry timestamp
```

Everything else on `CalmSetup` arrives from `CalmPreEntry`, which is fixed by 09:31. So:

- **DECIDE-knowable** ≡ the fields of `CalmPreEntry`
- **OBSERVE-only** ≡ what `CalmSetup` adds, plus what is derived from `entry` — the planned stop
  and the risk it implies

Both sets are computed **from the dataclasses**, so a field added to either lands on the correct
side without anyone remembering to update a list. A hand-kept list of forbidden fields is a list
that will one day be missing the field somebody just added.

`open_loc_prev_range` is the trap worth naming: it reads like a price feature and is computed
entirely from the 09:30 open, so it is DECIDE-knowable. The detector's own docstring flags it for
exactly this reason, and a test asserts it is **not** on the observe side.

### The stop, at DECIDE

Shown as its **rule**, never as a level:

```text
Stop rule       entry - 1.5 x daily_atr      known at 09:31
Stop distance   12.00                        a DISTANCE — it needs no entry price
Risk if taken   60.00                        that distance at this instrument's point value
Planned stop    — absent —                   the one thing this phase may not know
```

---

## 3. Which source answers, and when

```text
today, asked 09:00   DECIDE not_yet_run        OBSERVE not_yet_run
today, asked 09:45   DECIDE recorded_runtime   OBSERVE not_yet_run
today, asked 23:00   DECIDE recorded_runtime   OBSERVE recorded_runtime
a day with no rows   DECIDE reconstructed      OBSERVE reconstructed, and REFUSED
```

The instant is checked **before** the record, and that order is deliberate. A caller asking what
09:32 looked like at 09:00 is asking about a phase that had not run, and handing back the row it
wrote half an hour later would answer a different question with a real artefact — the most
convincing way to be wrong.

### Today's actual Calm

```text
DECIDE   NO_SETUP  no_candidate
OBSERVE  REFUSED   no_decide_row_for_this_day
```

That is the contract working, not a fault: DECIDE found no candidate, so OBSERVE has nothing to
match and says so. A reconstructed OBSERVE refuses the same way — a replay is not a licence to do
after the fact what the live path forbids.

---

## 4. On the page

Calm renders as **two cards**, outside the sleeve tabs. It is deliberately not added to `SLEEVES`:
every entry there is a continuous window on one instrument with a bar chart, and Calm is two
instants half an hour apart under a contract forbidding the first from seeing what the second
learns. One card is where the leak would live.

Each card carries its own source badge — RECORDED / RECONSTRUCTED / NOT YET — and the page decides
nothing: it prints the rows the backend put in each phase. Tests assert it computes no strategy
value and never falls back to the other phase for a missing one.

Browser tests pass at 375 / 720 / 1440 with no overflow, and one checks the leak **where a reader
would actually meet it**: the rendered DECIDE card contains no planned stop and no entry reference.

---

## 5. What a green mutation found

Six mutations, each restored byte-identical. Five went red on the first run. **M2 came back
GREEN honestly**, and the reason is the finding of this stage.

The DECIDE card carried no price level — every test agreed. But it carried none because a
DECIDE row on disk *happens* never to have an `after_reference` block. The level was built from
whatever the row contained:

```python
levels=([{"kind": "stop", "label": "Planned stop", "price": ...}]
        if ar.get("planned_stop") is not None else [])      # no mention of the phase
```

**The leak was being held off by the data, not by the code.** One malformed DECIDE row — a
crash between the two writes, a future change to the intent schema — and the 09:32 card prints
a stop price. The gate now names the phase, and a test feeds exactly that poisoned row to prove
the phase is what refuses it, not the row's contents.

| | |
|---|---|
| M1 a distance renamed into a level at DECIDE | RED |
| M2 the level attaches to the row's contents, not to the phase | **RED after the fix** |
| M3 the instant stops being checked at all | RED |
| M4 a replayed OBSERVE stops refusing without a DECIDE | RED |
| M5 the page falls back across the line to fill a gap | RED |
| M6 the market view stops publishing the phases | RED |

The first M2 was aimed at the wrong line — `not_yet_run_block`, which a test asking at 23:00
never reaches. It was a mutation of unreachable code, and it is recorded here because asking
*why* a mutation survived is what produced the fix; treating the green as a pass would have
left the real defect in place.

---

## 6. Two more defects found while building

**A `NameError` in the reconstruction** — `Path` used without being imported, so every replay
returned "could not be replayed". Caught by exercising a day with no rows rather than by reading.

**`not_yet_run` never fired.** The record was preferred *before* the time check, so a phase that
had not been reached as of the asked instant still reported as recorded. Reordering the two is
what makes the brief's "future phase ⇒ `not_yet_run`" true rather than merely intended.

And one in the page: `state.marketView` holds the whole response `{market_view, regime}`, so the
Calm block sits one level down. The first version read it a level too high and rendered an empty
div — which the DOM tests then waited on, a test failing because its fixture never described the
thing it was checking.

---

## 7. Results

| | |
|---|---|
| New suite | **33 passed** (including browser at 375/720/1440) |
| Calm contract + diagnostics suites | **123 passed** |
| Runtime writers added | **none** |
| Mutation harness | **6/6 red**, files restored byte-identical |

Four adjacent tests were restated — the pre-B1 blocker-roster family, for the fourth time. Three
asserted the confirmation file does not exist; one named B1 in the blocker set, which now opens
and shuts with the age of the account baseline record. Each keeps its property: a decision on disk
must be signed, and whatever is blocking comes from the registry.

### Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
track1_runtime/orders ABSENT · live_positions.track1.json ABSENT · TRACK1_ORDERS_APPROVED unset
confirmation file intact · shadow-intent digests unchanged by reading
gates · schedules · thresholds · strategy decisions — untouched
```

A test asserts by import graph that no gate can reach the diagnostics module, and another that
reading Calm diagnostics leaves the intent stream byte-identical.

---

## 8. Still open

- **The reconstruction's DECIDE risk inputs are empty.** A replay knows the setup formed and can
  name the rule, but the point value and the causal ATR the live slot recorded are not
  recomputed — they would be a second implementation of the sizing, and this stage's whole
  premise is that a second implementation proves nothing. Recorded blocks carry them in full.
- **Neither reconstruction path has met a Calm day that actually set up.** The last such day is
  outside the retained bar window, so the setup branch is exercised by unit paths rather than by
  a real session.
