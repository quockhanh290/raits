# Prompt: Track 1 go-live gate review, before paper trade

Use this prompt to audit **the gate mechanism itself** — the thing that decides whether Track 1
may send an order — not whether the system is ready. Readiness is what the ledger answers. This
review asks a different question: **does the ledger's answer mean what it says?**

Every defect class below is backed by a case that already happened in this repository. They are
listed because each one survived a reading of the code and only fell to a number.

The measured starting state was taken on 2026-09-06 and is written down so the reviewer can tell
drift from disagreement. If any line below no longer reproduces, that is the first finding.

```text
You are working in D:\raits on the Track 1 futures go-live gate registry.

GOAL
Audit the mechanism that answers "may Track 1 send an order". A gate that says NO for a reason
that cannot go stale is doing its job. A gate that says YES because a probe could not measure
anything is worse than no gate at all: it is a green light nobody knows is broken.

You are NOT deciding whether to start paper trading. You are deciding whether the answer to
that question can be trusted.

SCOPE — the registry and everything that feeds or reads it
  global_index/track1_gates.py              the blocker registry (987 lines)
  global_index/track1_paper_readiness.py    evidence behind PAPER_SHADOW_EVIDENCE
  global_index/track1_paper_executor.py     calls may_enable_orders() at :188
  global_index/track1_b1_decision.py        calls may_enable_orders() at :184
  global_index/track1_paper_send.py         the send path
  global_index/run_live_day_track1.py       the entry point
  global_index/track1_account_baseline.py   the account baseline record
  global_index/track1_final_bar_observation.py
  global_index/track1_shadow_acceptance.py, track1_shadow_intent.py
  global_index/track1_live_sleeves.py, track1_audit_reinterpretation.py
  track1_go_live_confirmation.json          the confirmation flags on disk
  monitor/backend/track1_runtime_reader.py  how the dashboard reads gate state
  docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md, PAPER_ROUTE.md, INVARIANTS.md

MEASURED STARTING STATE — 2026-09-06, reproduce before you read anything
  python -c "import sys;sys.path.insert(0,'.');from global_index import track1_gates as g;
             print(g.may_enable_orders()); print(g.self_check())"

  may_enable_orders()  -> False
  blocking_now         -> B1_broker_account_or_legacy_retirement
                          FINAL_BAR_DIVERGENCE_OBSERVED
                          PAPER_SHADOW_EVIDENCE
  self_check()         -> []          (empty; see defect class 4)

  B1                   USER_DECISION_GATE, blocks_orders=True
                       required_measurement_now.satisfied = False
                       "B1 audit UNKNOWN (record_stale); the B1 audit names no Track 1 book
                        path; account baseline UNKNOWN (baseline_record_stale); account
                        DUR125337; NOT CHECKED: the B1 audit records no account id, so the
                        two records cannot be cross-checked"
                       waiver flag exists: b1_measurement_waived
  FINAL_BAR_DIVERGENCE MEASURED_GATE, NOT_OBSERVED: records exist, but no Normal session has
                       reached a final slot yet
  PAPER_SHADOW         MEASURED_GATE, 1 FAIL day in the qualifying window (0 allowed);
                       account baseline UNKNOWN, newest baseline 194.0h old against a 24h claim
  LIVE_FRAME_ADAPTER   MEASURED_GATE, released=True

HARD RULES
- READ ONLY on the runtime. Do not close a gate, do not set a confirmation flag, do not write
  track1_go_live_confirmation.json, do not touch anything under global_index/track1_runtime/,
  and do not delete or rewrite evidence files. Runtime evidence is append-only; corrections
  happen at read time, on copies.
- Never close a gate to make the report look finished. Several of these are USER_DECISION_GATE
  by design: code cannot decide them and neither can you.
- No finding without a measurement. "Looks like it fails open" is a hypothesis; the number that
  shows it failing open is a finding. Read the whole path that actually runs.
- Check the CALL SITE, not the implementation. A safety mechanism with full code, a runbook and
  a "grep-verified" note can still be wired into no entry point at all.
- Three labels, kept apart: verified / no evidence / nobody has checked. "Not proven" is not
  "false", and "could not measure" is not "measured and fine".
- Before calling any behaviour unmeasured or a bug, search this project's own audit documents
  (RUNNER_AUDIT.md, RUNNER_AUDIT_ROUND2.md, docs/futures/*_AUDIT.md, OPERATIONS.md,
  INVARIANTS.md, ISSUES_LOG.md, DECISIONS.md, OPEN_QUESTIONS.md) and ask which LAYER owns the
  question. The answer is usually one layer away and already written down.
- Any test you write must be shown to go red when the thing it guards is removed. Break it with
  an in-process monkeypatch, not by editing files on disk.

THE EIGHT DEFECT CLASSES TO HUNT, each with the case that produced it

1. A PROBE THAT FAILS OPEN.
   `scheduler_processes()` returned [] for an empty stdout, a script error, and non-JSON
   output alike -- and [] meant "no scheduler is running", which is what the anti-duplicate
   guard reads before starting a second one. Three malfunctions, one answer, and the answer
   was the permissive one. Two schedulers then fought over clientId=1 and six entry slots died.
   -> For EVERY probe in the registry -- live_frame_wiring, shadow_evidence,
      regime_labels_verified, legacy_broker_flat, b1_decision_evidence,
      final_bar_divergence_observed -- take each `except`, each early return, each missing
      file, each unparseable record, and ask: does this value read as "gate satisfied"?
      A probe must be able to say "I could not tell", and "I could not tell" must hold
      the gate.

2. THE GATE IS COMPUTED BUT NOT WIRED.
   STOP_TRADING was a literal written in three places until H2; the constant existed and the
   file was checked, but which entry points read it was a separate question with a separate
   answer. Separately, `track1_final_bar_observation.py:22` carries a note reading
   "track1_gates.py  1 mention  BROKEN" -- start there and find out whether it is stale.
   -> Name the exact line that refuses to send an order because may_enable_orders() said no.
      Two call sites are known (track1_paper_executor.py:188, track1_b1_decision.py:184).
      Is the executor the ONLY road to a broker order, or is there a second path -- a manual
      script, a scheduler job, a replay-turned-live -- that never asks? Grep every module that
      can reach the broker, not just the ones that import the registry.

3. A WAIVER THAT OUTRANKS A MEASUREMENT.
   The B1 blocker carries `also_requires_measurement: b1_decision_evidence` AND a waiver flag
   `b1_measurement_waived`, while the measurement currently reports UNKNOWN.
   -> Who can set that flag, what exactly does setting it release, and does anything downstream
      say "this gate was waived, not measured"? A waived gate that prints the same as a measured
      one on the dashboard is a gate that has quietly stopped existing. Check every
      confirmation flag in track1_go_live_confirmation.json the same way, including flags the
      file names but the registry no longer knows.

4. A SELF-CHECK THAT CANNOT SPEAK.
   self_check() returns [] today. This repo has shipped a harness where check() only printed
   and appended, with sys.exit(1) under `if __name__ == "__main__"` -- 122 real assertions that
   reported "31 passed" under pytest, and one run that reported "11 passed in 2152s" for
   thirty-six minutes that had no way to fail.
   -> Prove self_check() can return non-empty. Break one registry invariant in memory
      (a blocker with a released_by that no confirmation flag defines, a MEASUREMENT key with
      no probe, a status outside STATUSES) and confirm it speaks. If it cannot, an empty list
      is not evidence of health.

5. A GATE THAT ONLY MOVES ONE WAY.
   `stripScheduleBad` counted `incidents.length > 0`, so six NKD failures at 02:00-02:25 held
   the status bar red for the rest of the day even after 02:30 ran clean -- there was no
   concept of "recovered", though the journal reader already had one for another stream.
   PAPER_SHADOW_EVIDENCE claims the opposite discipline: it "opens when the evidence exists and
   closes again if it goes stale".
   -> Verify BOTH directions actually run. For each MEASURED_GATE: what makes it open, what
      makes it close again, and is there a test that exercises the closing direction? A gate
      that has never been observed to re-close has not been shown to re-close.

6. STALENESS COLLAPSED INTO PASS OR FAIL.
   The baseline record is 194.0h old against a 24h claim and correctly reads UNKNOWN, with the
   reason stated: an account can be reset or traded in between. That is the standard.
   -> Hold every other freshness read to it. Anywhere an age is compared to a window, check
      what an absent record, a future timestamp, and an unparseable one each produce. A stale
      record that reads PASS is the failure mode; a stale record that reads FAIL is a different
      failure mode -- it trains the operator to ignore the gate.

7. TWO RECORDS THAT CANNOT BE CROSS-CHECKED.
   The registry says so about itself: "the B1 audit records no account id, so the two records
   cannot be cross-checked". A comparison between two records that share no key cannot fail for
   the right reason, and may not be able to fail at all.
   -> For every gate that reconciles two sources, name the key they join on and prove a
      mismatch would be detected. If there is no key, the gate's status is "nobody has
      checked", whatever it currently prints.

8. THE DASHBOARD'S COPY DRIFTING FROM THE LEDGER.
   Five figures on the Book panel came from a retired runner's snapshot 289.8 hours old and
   rendered as current. Separately, a verdict recomputed in the display layer agreed with the
   real gate 52.7% of the time -- a coin flip, wrong in both directions.
   -> monitor/backend/track1_runtime_reader.py and the realtime page: does the operator see the
      registry's own answer, or a second implementation of it? Is a USER_DECISION_GATE visibly
      different from a MEASURED_GATE on screen? Does a blocker released by a waiver look
      different from one released by a measurement? If the page can show "orders possible"
      while may_enable_orders() says False -- or the reverse -- that is the finding.

DELIVERABLE
A report at docs/futures/PAPER_GATE_REVIEW_<date>.md containing:
  - the starting state you reproduced, and any line above that did not reproduce
  - one section per finding: what you measured, the command that measures it, which LAYER owns
    it, and a label of verified / no evidence / nobody has checked
  - a separate list of things you checked and found sound, so the next reader does not re-walk
    them
  - for anything you propose changing: the change, the gate that would catch a regression, and
    proof that gate goes red without the change
Do not change the registry's decisions. Where a gate needs a human decision, say which decision
and what it costs -- that is the owner's call, not the review's.
```

---

## Why this review, and why now

The dashboard work is finished: the panel now reports gate state, evidence provenance and
freshness honestly, and its claims are held by tests that have been shown to go red. That makes
the panel a trustworthy **window**. It says nothing about whether the **lock** behind the window
holds — and paper trade is the first time the lock carries weight.

Three gates block orders today, and all three block for reasons that are visible and stated.
The risk is not those three. The risk is a fourth that stopped blocking without anyone noticing,
because its probe answered "no problem" when it meant "I could not look".
