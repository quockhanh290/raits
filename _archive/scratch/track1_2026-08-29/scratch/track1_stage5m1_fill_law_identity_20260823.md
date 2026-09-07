# Stage 5M-1 — fill law identity cleanup

**2026-08-23 · no scheduler, backend, or dashboard started or stopped · no IBKR connection ·
no order · no `STOP_TRADING` or `STOP_TRADING.track1` touched · no confirmation file · no live
state file written · no commit.**

---

## Verdict: **READY_FOR_5M_NORMAL_R4_PROMOTION**

The live and shadow route now runs and records `production_gap_after_15min_break`, and
reproducing a committed artifact is an explicit request rather than a default nobody passed.

A static scan over **all 115 modules in `global_index/`** finds **zero** implicit reads of the
engine default and **zero** parameter objects built without naming a law.

---

## The one thing worth reading before the tables

The task listed four callsites. **There were five**, and the fifth is the only one where the
fill law changes behaviour rather than bookkeeping.

Four places in the route read `NormalR4Params().fill_law` to decide what string to record in
the identity hash. Those are bookkeeping: wrong, consequential for checkpoint acceptance, but
they do not change a trade.

The fifth is in the live sleeve source, and it looked like this:

```python
pr = params.get(inst) or NR.NormalR4Params(ema_period=10 if sleeve == "global_nkd" else 50)
```

No `fill_law` anywhere on that line. It took the dataclass default — the **artifact** law — and
handed it to the engine, where it decides which bars are gap-eligible and therefore **which
trades exist**. A search for `fill_law` walks straight past it. A search for
`NormalR4Params().fill_law` walks straight past it.

That is why the fix moved the **default** rather than patching callsites. Patching four sites
leaves the trap armed for the fifth, and the fifth was the expensive one.

The class's own docstring already had the principle, applied to everything except the law:

> *"Labels and costs are arguments with no defaults for the same reason the fill law is: this
> class picking a regime model for today would be a decision made in the last place anyone
> would look for it."*

---

## Callsites changed — exact

| File · line | What | From | To |
|---|---|---|---|
| `track1_normal_r4.py` | `NormalR4Params.fill_law` default | `FILL_ARTIFACT` | **`FILL_PRODUCTION`** |
| `track1_params.py` | new `LIVE_FILL_LAW` | *(did not exist)* | `FILL_PRODUCTION` |
| `run_live_day_track1.py:255` | `checkpoint_report` fallback | `NormalR4Params().fill_law` | `tp.LIVE_FILL_LAW` |
| `run_live_day_track1.py:470` | `emit_explanations(fill_law=)` | `NormalR4Params().fill_law` | `tp.LIVE_FILL_LAW` |
| `run_live_day_track1.py:554` | `checkpoint_entries(fill_law=)` | `NR.NormalR4Params().fill_law` | `tp.LIVE_FILL_LAW` |
| `run_live_day_track1.py:1037` | `run_shadow` single reading | `NormalR4Params().fill_law` | `tp.LIVE_FILL_LAW` |
| **`track1_sleeves.py:150`** | **engine params — behavioural** | `NormalR4Params(ema_period=…)` → artifact | `…, fill_law=tp.LIVE_FILL_LAW` |
| `test_…stage4_production_clean…py:100-101,157` | artifact reproduction | bare `NormalR4Params()` | `fill_law=NR.FILL_ARTIFACT` |
| `test_…stage4_production_clean…py:497` | `_run` stub signature | no `route` kwarg | `route=None` |

**Both belts, and both are tested.** The default is now the live law, *and* the route reads
`tp.LIVE_FILL_LAW` explicitly rather than the engine's default. Either alone would work today.
Together they survive the next person who moves the default for a reproduction run.

The last row is not a Stage 5M-1 defect. It is the stale stub I reported in Stage 5L: the real
`_run` grew a `route` parameter in Stage 5I and this test's lambda did not follow, so it raised
a `TypeError` from inside production code — which reads as though the production call is wrong.
It was in this stage's required-reading list, so leaving it red across a third stage was worse
than the ownership argument for leaving it alone.

## Callsites intentionally left on the artifact law

| Where | Law | Why |
|---|---|---|
| Stage 4 artifact reproduction | `FILL_ARTIFACT`, now **stated** | the committed rows were generated under it; reproducing them means asking for it by name |
| `track1_fill_shortgate_regen_20260822.py` | both, by name, in a policy matrix | the measurement that produced the policy; its `artifact_gate_on` variant is the anchor that must equal the committed artifact exactly |
| Stage 4B identity suite | both, explicitly | its subject is that the two laws hash differently and refuse each other's checkpoints |

Thirteen further scratch callsites still read the engine default. They are test-side identity
comparisons that read the **same** string on both sides of an assertion, so they were correct
before and are correct now — they simply resolve to the production law today. The AST scan
covers `global_index/` only, deliberately: a scratch test asking for either law is doing its
job, and a scan that forbade it would be a scan people turn off.

---

## Reproducibility is intact

`test_a_normal_r4_reproduces_the_committed_rows_exactly` **still passes**, now asking for the
artifact law by name. Nothing about how those rows were generated changed; only the request for
them became explicit — which is the right way round. The live law is the default; reproducing
history is the special case.

---

## Why an immaterial delta was worth a stage

The three-blockers report measured the difference at **$0 to +$6** at book level across floor,
vault2025 and vault2026, against a book netting $75,288. That number has not moved, and this
was never about P&L. The production law is the *more permissive* of the two, so the published
Track 1 numbers were measured under the more conservative one — nothing needs re-rating.

The fill law is hashed into `params_hash`, and a route checkpoint is **accepted or refused** on
that hash. A route whose identity names a law it did not run would accept state computed under
the other one — a position seeded into a live book by an engine that would never have held it.

Stage 4B removed exactly this defect when the law was a hard-coded literal. It came straight
back as a dataclass default, and survived Stage 4B because **a default does not look like a
decision**.

---

## Test results

| Suite | Result |
|---|---|
| **Stage 5M-1** `test_track1_stage5m1_fill_law_identity_20260823.py` | **18 passed** |
| **Stage 5M-1 mutation harness** | **6 / 6 detected** |
| `test_track1_stage4_production_clean_20260823.py` + `…stage4b_identity_liveframe…` | 54 passed, 1 skipped, then the stale stub fixed → **all green** |
| `…stage3_route…` + `…stage3b_blockers…` + `…explain_wiring…` + `…stage5l_shared_preflight…` | **192 passed, 2 skipped** |
| `…stage4c_live_source…` + `…stage5d…` + `…stage5e…` + `…stage5f…` + `…stage5i…` | **143 passed, 1 skipped** |
| static scan, 115 production modules | 0 implicit reads · 0 unnamed constructions |

`global_index/test_event_playback.py` was **not run** — still the known hang.

### The mutations

Each puts the artifact law back on the live path one way at a time:

```
F1  LIVE_FILL_LAW flipped back to artifact          → the constant test reds
F2  the engine dataclass default flipped back       → the default test reds
F3  checkpoint_report defaults to artifact          → the identity test reds
F4  the live sleeve source runs artifact            → the fifth-callsite test reds
F5  the checkpoint accepts the other law            → the cross-law refusal test reds
F6  the law stops reaching the identity hash        → the identity test reds
```

F4 is the one that matters most, because it is the mutation that changes trades rather than
strings, and the one no `fill_law` search would have found.

One test in this suite failed on its first run and the failure was mine, not the code's: it
asserted the production cache hands back the source's gap arrays by **object identity**, but
`_swing_cache` memoises on `id(df)`, so that assertion was testing the memo rather than the
law. Rewritten to compare by value, plus an explicit check that the two laws actually produce
different flags on the frame used — otherwise every other test in the file would be asserting
about a string with nothing behind it.

---

## Documentation

`scratch/track1_three_blockers_report_20260822.md` gained an **append-only** addendum. Nothing
above it was rewritten. It records that §2's recommendation was, until today, a recommendation
the code did not follow; that the published artifacts were reproduced under the artifact law;
that Track 1's live identity is the production law; and that the delta stays immaterial while
the identity is mandatory.

---

## No side effects

No scheduler, backend, or dashboard started or stopped. No IBKR connection. No order. No
`STOP_TRADING`, `STOP_TRADING.track1`, or confirmation file created or removed. **No live state
file written by this stage.** No commit.

### The two state files changed during this stage — not by it

At **20:58:38** both `preflight_state.json` and `maxhold_state.json` stopped holding the damaged
Sunday key and began holding seven attested days each. Their contents now match the Stage 5M-0
proposal **byte for byte**, including the deliberate absence of 2026-08-13 from the max-hold
record — the day the double-launch left unresolved.

I did not write them, and I am not going to guess who did. What I can state from measurement:

* the content is exactly what `--apply` produces, which is consistent with the repair command
  from Stage 5M-0 having been run;
* nothing in Stage 5M-1 opens either file, and the Stage 5L guard test — which fires both job
  bodies with their write paths redirected and hashes the real files around it — passes, with
  both mtimes unchanged across the run;
* `2026-08-21` is present, which is the entry Monday's NKD night slots read. The restart hazard
  described in Stage 5M-0 is therefore closed on the evidence now on disk.

If this was not a deliberate repair, it is worth finding out what wrote them before Monday.

---

## Next

Stage 5M — promote Normal-R4 into Track 1 slots covering 14:05–15:55. This stage was a
precondition for it: 5M lights up the sleeve whose engine was taking the artifact law by
default, so promoting it first would have shipped the wrong law into the one place it changes
which trades exist.

Still open from 5M-0: whether to repair `preflight_state.json` before any scheduler restart.
That decision expires at Monday 13:45 ET.
