# Stage 4C — giving the guard something to guard

**2026-08-23 · offline · no scheduler started, no broker connected, no order sent, no
dashboard write, no commit, no confirmation file created, legacy untouched.**

---

## Verdict: **A**

`LIVE_FRAME_ADAPTER_VERIFICATION` is released by measurement and no longer holds the order
gate. **B1 is the only blocker left.**

> **This is not a statement that Track 1 can trade.** It says the live-bar path exists, that it
> is the only one, and that every branch of it ends in the checked join — all proved offline.
> No live day has been run and no broker has been connected. B1 is a real decision about which
> account holds which positions, and it is untouched.

---

## 1. What was actually missing

Stage 4B built a join that cannot corrupt history and then measured, honestly, that nothing on
the route could obtain a live bar to join. The guard guarded nothing. Every Track 1 number in
existence had come from a frame that was already complete, start to finish, out of a file.

Stage 4C built the other half: one place where live bars arrive, and no way around it.

---

## 2. The step the join refuses to take, and why that is right

The two halves are on different clocks, and not by accident — it is the contract on both sides:

- **History** is a parquet file whose stamps are UTC. It is read as UTC, converted to New York,
  and converted once more to Tokyo for the Nikkei sleeve, because that is the session it trades
  in.
- **Live** bars come back from the broker path already moved to New York and then *stripped of
  their zone* — naive wall-clock ET. That is what the existing `fetch_bars` produces today.

So something must convert, and the join deliberately refuses to be that something: a converter
inside it would make a wrongly-clocked frame look plausible, which is exactly how the original
corruption passed every check that existed. The conversion is therefore explicit, it happens in
one place, and it takes its target **from the frozen frame itself** rather than from a table
that could disagree with the file on disk.

The two spellings are one keystroke apart and mean opposite things:

```
tz_localize("Asia/Tokyo")                     asserts the ET reading was already Tokyo time
tz_localize("America/New_York")               says when the bar happened, then re-reads that
    .tz_convert("Asia/Tokyo")                 instant on Tokyo's clock
```

**And the thirteen hours are not thirteen hours.** Japan keeps no summer time and the United
States does, so the same mistake is worth **thirteen** hours from March to November and
**fourteen** for the rest of the year. Anything hard-coding thirteen — a check, a tolerance, a
test — would be right for about eight months a year and quietly wrong for the other four. Both
sides of that boundary are pinned. The first version of the test asserted thirteen, picked a
March window, and went red; that is how the fourteen was found.

---

## 3. Two failures the join alone could not catch

Both were found by pushing real bars through the thing, not by reading it. Neither was in the
plan for this stage.

### Backwards — silent, and the reason the original error ran so long

A mis-converted session lands on timestamps history already owns. The join handles that
correctly: it trims those bars away and keeps history. Safe — and **silent**. Nothing is
raised, nothing is counted, and a feed that is wrong every single day reports a clean join
every single day.

So the overlap is now **compared** instead of discarded. Where both halves describe the same
instant they must report the same price, because two readings of one instrument at one moment
cannot differ. There is no tolerance to tune: futures prices are exact decimals on both sides,
so anything past floating-point noise is real.

Reproducing the Nikkei error is refused, and the numbers match the shape of the real thing:
**707 of the 708 overlapping bars disagree, and the largest gap is 1,440 Nikkei points** —
the same order as the roughly 900-to-1,000-point errors the original corruption left behind.
Nearly-all rather than one is what the test asserts, because a check that fired on a single
outlier could not tell a clock error from a late correction to one print.

### Forwards — accepted outright, and nothing in the join can see it

The same clock error in the other direction puts every bar in empty space *past* the end of
history. Strictly newer, unique, in order, matching columns: **every rule the join has,
satisfied.** Measured before the fix: `code=ok`, 399 bars appended, and a frame that does not
equal the original. Reported as success.

What catches it is a fact about fetching rather than about prices: a fetch cannot return bars
from after the moment it was taken. So the last joined bar is checked against the instant it
was asked for. No threshold.

Stage 4B's report said the guard was "the line that would have failed on the Nikkei incident."
That was true for the direction the incident took. It was not true in general, and this stage
is where that got found.

### The limit, stated rather than hidden

A live half **several days long**, shifted forward by less than its own span, is caught by
neither check — most of its bars are before the fetch instant and past the end of history,
where neither check can see them. What makes that acceptable is the size of a real live half: a
session fetch is hours, and a whole-zone error is thirteen or fourteen, so any error big enough
to matter is larger than the span. A caller that starts handing over multi-day live halves is
outside what has been shown. That is written into the module and pinned by a test that says so
by name, so if it ever stops being true it fails somewhere visible.

---

## 4. What is wired

One module obtains live bars for the whole route. Every branch of it ends in the checked join —
**including the branches where the provider offers nothing at all**, which is not pedantry: an
early return on "no bars today" is precisely how an unchecked frame reaches a sleeve. A test
counts the calls rather than trusting the reading, and asserts the count rises on the empty and
the missing-instrument paths too.

Each sleeve is served from that one join. The S&P is read by two sleeves, and they receive the
**same object**, not two joins of one file — two frames of one instrument disagreeing inside a
single decision is the kind of difference nobody finds until it has already sized a position.

The broker boundary is real code, not a sketch: it delegates to the runner's existing broker
rather than opening a connection of its own, because one Gateway login is one session and a
module that dialled out on its own would be a second client competing for the same id — which
is B1, arrived at from the other side. It refuses when handed no broker. The broker library is
imported *inside* the method that needs it, and a test spawns a fresh interpreter to prove that
importing Track 1 does not pull it in.

**What still refuses:** producing candidates. What is missing there is no longer the sleeves —
Stage 4 promoted them — it is today's regime label, a cost object, and Calm A's true stop-risk
sizing. Those are inputs a live decision needs, and a source that quietly picked a regime for
today would be making that choice in the last place anyone would look for it.

---

## 5. The gate: released, not closed

The blocker stays a **measured gate** rather than being marked closed, and the difference is
the whole point. Closed would freeze a verdict about code that can change. Released means it is
re-measured on every read, so a fetch added tomorrow that skips the join shuts the route again
without anyone needing to remember that it should.

It also cannot become signable. A test holds the measurement shut and grants every confirmation
flag the file accepts — the most permissive state a signature can express — and requires the
gate to stay closed anyway.

Two things about the measurement changed here:

**It learned a new verb.** Stage 4C introduced `fetch_session_bars`, and the detector only knew
the broker's own spelling. That left a hole exactly the width of the new code: a module could
have called a provider straight and never counted as a fetcher. The name is now in the
vocabulary, and there is a test that writes a provider call into a fake route and requires it to
block.

**It reads parsed code, not text.** Unchanged from Stage 4B and worth restating, because a
detector in this repository once asked whether a line contained the word "python" and, since
every stack trace prints an interpreter path, turned each line of every crash into a phantom
job launch. A comment is not a call, and a test writes all the trigger words into a docstring
and requires the answer to stay "nothing here fetches".

---

## 6. Corrections to earlier work

- **B1's description said, again, what some other blocker was doing.** Stage 4B had it claim it
  was the only blocker; I fixed that to say it was the only one a *person* could release —
  which went stale the moment this stage released the other one. Twice is a pattern, so the
  cross-reference is gone entirely: B1 now describes B1, and says outright that the registry is
  the only thing that can answer what else is blocking without drifting.
- **The live sleeve prerequisite list still named solved problems.** It listed the root-level
  script, the scratch harness and the scratch filter library as things standing between Track 1
  and a live decision — all promoted into the package by Stage 4. A prerequisite list naming
  finished work is a list nobody trusts, and it hid how much of this was already done. Rewritten
  to what is actually left, and the test that pinned one of those strings now asserts the
  property instead: nothing on the list may name work that has since been built.
- **A test's ledger key was wrong.** The window-observation check reads `outcome`; my first
  version passed `status`, so the Stress gate refused for the right reason by accident. Caught
  because the test asserted a pass and got a refusal.
- **A test cut the basket at each instrument's own last bar** and then took the earliest of
  those as the fetch instant, which starved whichever instrument trades latest — it handed the
  S&P an empty live half while reporting a clean join. A live slot has one fetch instant, so
  the fixture now uses one.
- **A provider-clock bug that would have hit the real broker.** The provider's own causal trim
  compared a naive index against an aware instant and raised inside pandas. The legacy broker's
  `fetch_bars` trims exactly the same way, so the IBKR path would have hit it too — on the
  first live day, in the dark. Normalised in one place.

---

## 7. Where measurement stopped

- **Verified, with numbers:** the two clock contracts; the 13/14-hour split across the DST
  boundary; exact frame reconstruction for the S&P and the Nikkei; identical Normal-R4 and
  Calm A decisions on adapter-produced frames; both same-session gates on partial sessions;
  the overlap refusal at ~1,000+ points; the forward refusal, including proof the join alone
  accepted it; the wiring measurement in five directions; every suite below.
- **Reasoned, not executed:** that `IBKRBarProvider` returns what the sleeves expect. It
  delegates to the broker method the runner already uses, which is the strongest available
  claim without a connection — and it has never been run.
- **Not examined:** whether a real IBKR session's bars agree with the parquet convention where
  they overlap. The check that would answer it now exists and runs on every join; it needs a
  broker to produce a verdict.

---

## 8. Suites

Every one run after the last edit, not carried forward from an earlier pass.

| suite | result |
|---|---|
| this stage's own | **46 passed** |
| Stage 4B identity + live frame | **30 passed** |
| Stage 4 production-clean, default | **25 passed, 1 skipped** (7:23) |
| Stage 4 production-clean, all windows | **32 passed** (18:47) |
| Stage 3B blockers | **72 passed, 1 skipped** |
| Stage 3 route | **41 passed, 1 skipped** |
| the eight that must stay green | **156 passed** |

The three skips are the same pre-existing opt-ins as before and none is new: a regeneration
through the shipped generator in a subprocess, the seven-year floor equivalence, and Stage 4's
holiday case, which lives in the 2025 window and does run in the all-window mode.

`global_index/test_event_playback.py` was **not run** — the known hang, excluded by instruction.

Five tests in the older suites moved, and it is worth saying which, because a suite edited to
go green proves nothing:

- Two in the Stage 4B suite pinned "the route has no live bar path". That claim is now false.
  One was replaced by its inverse — a path exists and is guarded — and the other, the one
  asserting no signature can open the gate, was rewritten to hold the measurement shut first.
  Left as it was, it would have passed from now on for the wrong reason, which is worse than
  failing.
- Two in the Stage 3B suite have now been rewritten in both directions across two stages,
  which is the tell that they were tracking the state instead of the property. Both now assert
  the release **and** the re-shut, so neither can go stale again.
- One in the Stage 3 suite pinned the string `model_sameday_stop` as a live-source
  prerequisite. Stage 4 promoted that work into the package, so the pin moved from the literal
  to the property that made it worth pinning: nothing on the prerequisite list may name work
  that has since been built.

---

## 9. Files this stage touched

**New**

- `global_index/track1_live_source.py` — the adapter: the provider interface, the two
  providers, the clock conversion, the two refusals, and the per-sleeve fan-out
- `scratch/test_track1_stage4c_live_source_20260823.py` — this stage's suite
- `scratch/track1_stage4c_live_frame_adapter_20260823.json` — the machine-readable result
- this report

**Changed — the Track 1 package**

- `global_index/track1_sleeves.py` — `LiveSleeveSource` gains `frames()` and `detect()`, both
  served from the adapter; the prerequisite list corrected to what is actually left
- `global_index/track1_gates.py` — the detector learned `fetch_session_bars`; the blocker's
  evidence rewritten to the measured present; the ledger now states `blocking_now` outright;
  B1's text no longer describes any other blocker

**Changed — tests, ledger, runbook**

- `scratch/test_track1_stage4b_identity_liveframe_20260823.py` — the two tests that pinned "no
  live path" moved to the new truth; the "no signature opens it" test now holds the measurement
  shut so it keeps testing that property instead of passing for the wrong reason
- `scratch/test_track1_stage3b_blockers_20260822.py` — the two blocker tests now assert **both**
  directions rather than whichever one is currently true
- `scratch/test_track1_stage3_route_20260822.py` — T12 pins the property instead of a literal
- `scratch/track1_blocking_ledger_20260822.json` — regenerated from the registry
- `scratch/track1_blocking_ledger_20260822.md` — header, summary, section 9 and the closing
  section rewritten
- `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md` — precondition 8 now met, with what it does and
  does not say

**Tests removed, and where the coverage went.** Two tests in the Stage 4B suite —
the four-direction wiring check and the prose-only check — were replaced when that section was
rewritten. Both are now in this stage's suite, alongside a fifth direction that did not exist
before (a fetch through a provider method). Coverage went up, not down; it is named here because
a deleted test should never be something a reader has to notice on their own.

**Not touched, and not mine.** `global_index/deploy_sim.py` and `global_index/run_live_day.py`
were already modified before this session began. `global_index/run_scheduler.py` carries Stage
4's shadow flag and was not changed in this stage. `TASK.md` was already modified before this
session and was left alone rather than written into blind.
