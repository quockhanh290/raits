# Stage 4B — the fill law, and the join that has never happened

**2026-08-23 · offline · no scheduler started, no broker connected, no order sent, no
dashboard write, no commit, no confirmation file created, legacy untouched.**

---

## Verdict: **B**

One caveat closed. One did not, and it is now a gate that holds the order path shut and that
**no signature can open**.

> **"Only B1 remains" was true after Stage 4 and is not true now.** It is not claimed anywhere
> in the ledger, in the registry, or in what the command line prints. Two blockers hold the
> gate: the account decision, and the fact that nothing on this route has ever joined a
> partial trading session onto history.

---

## 1. The fill law — closed

**What was wrong.** The route declared that it filled gaps only after a fifteen-minute break
in trading. Every number the route has ever produced was generated under the other law, where
any bar can fill a gap. Nobody chose that; a literal was written once and the data came from
somewhere else.

**Why "the P&L difference is immaterial" is not an answer.** It is immaterial, and that is
precisely how the error survived. But the declared law is not a P&L estimate — it is part of
the fingerprint a saved position book is accepted or refused on when the engine restarts. A
fingerprint naming a law the run did not use will accept a book computed under different exit
rules and seed the day with a position the engine would never have held.

**What changed.** The law is now an argument that must be passed, with no default and no third
possible value. It travels into the fingerprint, into the saved checkpoint, and into what the
entry point reports. It is read from the sleeve that runs it, so there is no second copy to
drift — that second copy was the whole defect.

**Measured, both ways, on all three windows**, using the shipped generator rather than a
script written for the occasion:

| window | artifact law | production law | difference | rows that differ |
|---|---|---|---|---|
| vault2026 | $6,825.83 | $6,829.04 | **+$3.21** | 1 (Nikkei) |
| vault2025 | $10,953.98 | $10,953.98 | **$0.00** | none |
| floor (7 yr) | $31,609.66 | $31,615.23 | **+$5.57** | 5 (1 Russell, 4 Nikkei) |

Six differing exits out of 1,223 trades. Small — and **not zero**, which is the point: the two
laws genuinely produce different trades, so a fingerprint that cannot tell them apart is one
that will eventually accept the wrong book.

**Proven by tests that go red:** the two laws hash differently; omitting the law is an error
rather than a default; an invented law is refused; a checkpoint written under one law is
refused under the other **in both directions**, naming the stored and the requested value; and
the entry point reports the identity built from the law its sleeve actually runs.

---

## 2. The live frame — **not** closed, and now a gate

### What is missing

Every reproduction this route has ever run read a frame that was already **complete** — the
whole span, start to finish, out of a file. On a real trading day the frame is not complete: it
is yesterday's history with today's unfinished session joined onto the end — and **no code on the Track 1 route has ever performed that join.** Parsing every Track 1
module on disk finds no request for bars from anywhere. The route's only source is a replay of
windows that were measured months ago.

So the honest statement about all of Stage 4's exact reproductions is: they prove the sleeves
compute the right answer *from a complete frame*. They say nothing about the frame a live
route would hand them, because no such frame has ever been built.

### Why this is a gate and not a footnote

This repository has already paid for this exact join. Live Nikkei bars arrived stamped on the
New York clock and were joined onto history carried on the Tokyo clock — thirteen hours apart
in summer. **1,050 of the 1,590 live bars landed on timestamps history already owned. The join
keeps the newer one, so they overwrote settled prices by roughly 900 to 1,000 points**, right
across the recent window every signal is computed from.

Nothing raised an error. The frame was the right length, the timestamps were in order, and
every check that existed passed.

### What has been built

A join that cannot do that:

- Bars on a different clock are **refused, never converted.** Converting is exactly what makes
  a wrongly-stamped frame look plausible.
- A live bar carrying a timestamp history already owns is **dropped, not applied.** A
  mislabelled bar can lose; it can never rewrite.
- Duplicated timestamps, backwards steps and mismatched columns are refused outright.
- After every join, the historical half is compared against what went in, and the join fails
  if it moved at all. That is the line that would have failed on the Nikkei incident.

### What has been proven, offline

Cut a real frame at an instant, hand the tail back as though it were live, and the join must
give the original back bar for bar. It does — and the sleeves reach the **same decisions** on
the reconstructed frame as on the whole one.

Specifically, and this is where it stops: the trend sleeve is checked on the S&P frame **and on
the Nikkei frame**, which is the one that matters. The Nikkei frame is the one carried on the
Tokyo clock, the one the incident happened to, and the one running a different engine. Four of
its twenty-six trades in that window fall after the cut, so they exist only because the tail was
joined on correctly — and replacing the join with one that silently drops the tail changes the
answer to twenty-one trades. The check can fail, which is the only reason its passing means
anything.

Calm A is checked the same way on the S&P frame, and both same-session gates — Calm A's and the
Stress window's — are checked on spliced frames. The Stress sleeve's full entry rule is **not**
checked this way; its gate is. A session cut before its closing bar produces **no setup for that
day rather than a wrong one**. The Nikkei clock offset is now a test, and it is refused.

### What has not been proven, and cannot be here

That the join is correct on a real trading day. No live day has been run and no broker has
been connected — those were the constraints, and they are the right ones. So the gate does not
ask for a live day. It asks for something reachable and checkable today: **that the only way a
live bar can reach a sleeve is through the checked join.** Right now the answer is no, because
there is no way at all.

---

## 3. How the gate is enforced

The blocker registry had two statuses: closed with evidence, or waiting on a decision only the
project owner can make. This caveat fits neither. Nobody has to decide anything and nothing is
written down wrong — code is simply not connected yet. Filing it as a decision would have let
a signature close it, which is the prose-only outcome the registry exists to prevent.

So there is now a third kind of gate: **one released by a measurement taken on the spot, and by
nothing else.** The registry's own structural check refuses to let such a gate name a
confirmation flag, so it cannot quietly become signable later.

The measurement parses the route and asks two questions: does any module obtain live bars, and
does every module that does go through the guard. Three outcomes — no live path, an unguarded
fetch, a guarded fetch — and only the third opens it.

Two deliberate choices in how it looks:

**It reads parsed code, not file text.** A detector in this repository once asked whether a
line contained the word "python"; since every stack trace prints the interpreter's path, each
line of every crash became a phantom job launch. A comment is not a call, and this measurement
cannot be fooled by one — a test writes the trigger words into a docstring and a comment and
requires the answer to stay "nothing here fetches".

**It discovers the module list rather than carrying one.** A hand-kept list of "the modules
that make up the route" will one day be missing the file somebody just added, and the
measurement would report a clean route while that file fetched bars in the corner. This
repository has that scar too: a test runner with a hand-maintained list printed
"69 passed / 69 total" for a section it never called. The set comes from disk; the single
exclusion is the guard itself.

**It has been exercised in all four directions** — nothing fetching, fetching without the
guard, fetching through the guard, and the words appearing only in prose — and it answers
differently to each. A gate whose measurement can only say no is a sentence wearing a
function's clothes.

---

## 4. What this changed about arming the route

Stage 4 could say that a valid confirmation file plus the environment approval **armed** the
order gate, and that the confirmation file had become the safeguard.

That is no longer true, deliberately. A third factor now stands in front of the exchange and
it is not a person. A test asserts it directly: sign the file, set the environment variable,
and the gate still refuses — then answer the measurement in memory and it arms, so the refusal
is demonstrably that gate and not something unrelated blocking quietly.

Running the entry point with orders requested still exits 2, sends nothing, and now names both
blockers.

---

## 5. Corrections to earlier work

- **B1's own description said it was the only blocker left.** It said so in the registry, and
  the command line printed it. That sentence was true when written and became false in the
  same hour this stage added a gate — the same class of defect as the fill-law literal, which
  is worth naming rather than quietly fixing. It now says B1 is the only blocker a **person**
  can release.
- **The ledger's summary said "seven of eight closed; only B1 remains."** Rewritten to seven
  closed and two holding, with the new gate given its own section.
- **The splice equivalence check was proven in the easy place.** The first version compared
  sleeve decisions on the S&P frame only — which is the frame that never broke. The frame the
  incident happened to is the Nikkei one: different wall clock, different engine. The draft of
  this report claimed "all four sleeves"; the tests covered one instrument. Coverage was added
  rather than the sentence softened, and the sentence now says exactly which sleeves on which
  frames.
- **A defect in the splice guard, found by its own test.** A live half that was not a frame at
  all — an integer, say — was read as "no bars offered" and reported as a clean join, because
  the emptiness check ran before the type check and an integer has no index. The test asked
  for a refusal and did not get one. The two checks are now in the other order.

---

## 6. Where measurement stopped

Stated plainly, because these are the places a reader could over-read this report.

- **Verified, with numbers:** the fill-law delta on all three windows; identity moving with
  the law; cross-law checkpoint refusal in both directions; the splice round trip and the
  sleeve decision equivalence; the wiring measurement in four directions; the suites below.
- **Reasoned, not executed:** that routing a future live source through the guard will be
  sufficient. It is the strongest offline claim available, and it is not a claim about a live
  trading day.
- **Not examined:** whether a broker bar source, once written, delivers bars matching the
  convention the sleeves read from parquet. That comparison needs a broker and belongs to the
  stage that adds one.

---

## 7. Suites

Every one run at the end, after the last edit, not carried forward from an earlier pass.

| suite | result |
|---|---|
| this stage's own | **31 passed** |
| Stage 4 production-clean, default | **25 passed, 1 skipped** (6:41) |
| Stage 4 production-clean, all windows | **32 passed** (17:32) |
| Stage 3B blockers | **72 passed, 1 skipped** |
| Stage 3 route | **41 passed, 1 skipped** |
| the eight that must stay green | **156 passed** |

The three skips are pre-existing opt-ins and none was introduced here. They are three
different things, so naming them individually rather than as a count:

- Stage 3B holds back a regeneration through the shipped generator in a subprocess — about
  thirty-five seconds, opted into with its own switch.
- Stage 3 route holds back the seven-year floor equivalence, which is the two-minute anchor.
- Stage 4's default mode holds back the holiday case, because the day it turns on lives in the
  2025 window. That one is **not** skipped in the all-window run — it executes there. No test
  in this stage's set is skipped in both modes.

`global_index/test_event_playback.py` was **not run** — it is the known hang, excluded by
instruction.

Six tests in the older suites had to be moved rather than merely re-run, and it is worth saying
which and why, since a suite that is edited to go green proves nothing:

- Four were mechanical: calls that must now pass the fill law, which is the point of making it
  required — code that did not name a law stopped compiling, which is exactly the behaviour
  asked for.
- Two were substantive. One asserted that releasing B1 empties the blocker table; that is no
  longer true and it now asserts the true set. The other asserted that satisfying every
  confirmation flag opens the route; it now asserts the opposite — signatures alone must not be
  enough — and then proves the set is still satisfiable by answering the measurement in memory.
  Without that second half the test would have quietly become an assertion that the route can
  never open.

---

## 8. Files this stage touched

**New**

- `global_index/track1_live_frame.py` — the splice guard
- `scratch/test_track1_stage4b_identity_liveframe_20260823.py` — this stage's suite
- `scratch/track1_stage4b_identity_liveframe_20260823.json` — the machine-readable result
- this report

**Changed — the Track 1 package**

- `global_index/track1_params.py` — the fill law becomes a required argument
- `global_index/track1_normal_r4.py` — the law is validated where it is declared
- `global_index/track1_bootstrap.py` — the law travels with the checkpoint it writes
- `global_index/run_live_day_track1.py` — reports the identity under the law the sleeve runs
- `global_index/track1_gates.py` — the measured gate, the measurement, the discovered module
  set, and B1's corrected sentence

**Changed — tests, ledger, runbook**

- `scratch/test_track1_stage3_route_20260822.py`,
  `scratch/test_track1_stage3b_blockers_20260822.py`,
  `scratch/test_track1_stage4_production_clean_20260823.py` — the law threaded through, and the
  blocker assertions moved to the true state
- `scratch/track1_blocking_ledger_20260822.json` — regenerated from the registry
- `scratch/track1_blocking_ledger_20260822.md` — new section, corrected summary
- `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md` — precondition 8, which is not yet satisfiable

**Not touched, and not mine.** `global_index/deploy_sim.py` and `global_index/run_live_day.py`
were already modified when this session began; nothing here changed them.
`global_index/run_scheduler.py` carries Stage 4's shadow flag and was not changed in this
stage. `TASK.md` was likewise already modified before this session and was left alone rather
than written into blind — this report and the ledger are the record of the stage.

**The running scheduler is gone.** At the start of this work a scheduler process was running
from before Stage 4's edits. It is no longer running — the process table shows only the
monitor backend. Nothing here started or stopped it, and when or why it stopped was not
investigated.
