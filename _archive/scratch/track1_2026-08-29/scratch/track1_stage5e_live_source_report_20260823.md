# Stage 5E — a live decision at one of the two windows

**2026-08-23 · no scheduler started, no IBKR connection, no order, no dashboard write, no
`STOP_TRADING`, no confirmation file, no repo checkpoint, no commit.**

---

## Verdict: **BLOCKED_BY_LIVE_SOURCE**

Precondition 2b is **closed for Calm A** and **still open for Stress**. The gap narrowed by one
sleeve; it did not close.

> **Not claimed:** that a broker provider works — every test injects `FrameBarProvider` and no
> IBKR object is ever constructed. Not claimed: that the Stress window can decide. Not claimed:
> that Track 1 can trade.

**Why the live source and not the broker is the binding gap.** Even handed a perfect bar
provider tomorrow, the Stress window — **24 of the 25 Track 1 slots** — would refuse every slot,
its window would close `incomplete` every day, and precondition 5 would never turn green. The
broker gap is real and second.

---

## 1. Which sleeves can be asked at all

Measured, not assumed — and this reframes the whole task:

| sleeve | Track 1 slot | intraday requirement | ledger window | live source |
|---|---|---|---|---|
| `roska4_calm` | 10:00 | yes | yes | **closed offline** |
| `roska4_stress` | 10:35–12:30 ×24 | yes | yes | **open — rule in scratch** |
| `roska4_swing` | **none** | none | none | n/a |
| `global_nkd` | **none** | none | none | n/a |

Normal-R4 decides between 14:00 and 15:55; NKD decides overnight. **Neither has a Track 1 slot,
an intraday requirement, or a ledger window.** A live source cannot be asked for them at any of
the 25 slots, and asking is a named refusal rather than an empty list. Two of the four sleeves in
this route are simply not part of the intraday shadow at all — that is worth knowing before
anyone reads "four sleeves" and expects four answers.

---

## 2. What Calm A needed, and what each piece cost

### The detector could not run at 10:00 at all

`detect()` fills `exit` from the **15:55 open** and only considers sessions that reached their own
close. At a 10:00 slot today is not in the session table and the exit is six hours away — so it
returns nothing for today, which my own Stage 4C test had already pinned ("a session cut before
15:55 yields no setup").

The fix was **not** a second detector. The entry test — prior-session close-location, prior-session
return, gap from prior close — is now one function, `entry_conditions`, called by both the
historical detector and the new `detect_entry_for_day`. Only the prices differ. A second copy of a
decision rule is the thing this route has been burned by repeatedly, and the Stage 4 reproduction
is what proves the extraction did not change the rule.

### The regime label had to be causal

`causal_regime_label` takes the last label **strictly before** the day. Not `asof(day)` — that
returns today's own row when today has one, and today's row is computed from today's close. A
morning slot reading it would be reading six hours of the future, and nothing would look wrong.

Tested in both directions, because one direction proves nothing:

- mutating **today's** label does not move the decision
- mutating **yesterday's** label does

### The ATR had the same trap, and a consequence worth stating

`daily_atr_series` builds one row per session from that session's own high, low and close. The
measured artifacts size from `asof(day)`, which takes today's row when it exists — defensible in a
backtest that books the whole session at once, **and lookahead at 10:00**.

So the live path uses the last daily ATR strictly before today, and **a live risk figure can
differ slightly from the artifact's for the same day.** That difference is real, it is in the
causal direction, and it is written into the code and the runbook rather than reconciled away.

### The risk is the stop distance, not a multiple

Calm A's disaster stop is `entry − 1.5 × ATR`, LONG only, and the risk the cap gate reads is:

```
risk_dollars = abs(entry − disaster_stop) × point_value × qty
```

Taking the stop **price** rather than the ATR and the multiple is the whole point. A formula
reading `mult × atr × pv` returns the same number wherever the stop actually sits; this one does
not. Measured: widening the multiple from 1.5 to 3.0 moves the stop down and roughly doubles the
risk, and MES and MNQ come out at $16.07 and $6.43 on the same stop distance — the ratio of their
point values, exactly.

There is a test that writes the proxy formula out and shows it cannot tell two different stops
apart, so the distinction is checkable rather than asserted.

### Costs

One explicit object per instrument at **2 ticks a side** — the slippage every measured Track 1
row was built under, not the entry point's CLI default. Nothing asks a broker: a live commission
lookup would make the risk a slot computes depend on when it ran. A missing instrument is a named
refusal, not a zero.

---

## 3. Refusal versus empty list

The distinction the whole vocabulary exists for. An **empty list** means the rule ran and today
does not set up — a real observation. Every one of these means the rule **did not run**, and a
window full of them must not close as a clean day with no signals:

`no_bar_provider` · `regime_unavailable` · `cost_missing` · `stop_risk_unavailable` ·
`sleeve_not_live` · `stress_rule_not_in_package` · `no_sleeve_at_this_instant`

The slot records the source's own code rather than flattening everything to
`live_source_not_ready`, because "no label before today" and "the rule is in scratch" are
different problems with different owners.

---

## 4. End to end, with a stub provider

| step | result |
|---|---|
| `load_source("live-shadow").candidates(10:00)` | **2 candidates** (MES, MNQ) |
| risk basis | `true_stop_distance` |
| slot | `decided=True`, `candidates=2`, gate allowed |
| window | **`complete 1/1`** |
| checkpoint | written to a temp path and **accepted** by `track1_bootstrap.accepts` |
| repo route state | **none created** |
| Stress window at 11:00 | refused, `stress_rule_not_in_package` |
| replay with the ledger on | **zero** coverage files |

---

## 5. Two defects found by running it

**The gate and the frame disagreed about bar size.** `track1_intraday` declares 5-minute bars per
sleeve; the joined frame the detectors read is 1-minute. Stage 5D handed the gate the raw frame,
so every slot would have refused with `gate_refused` for a reason that had nothing to do with the
market. The slot now resamples to the size the requirement names, derived from the requirement
rather than hard-coded.

**Two session-end conventions.** The intraday gate wants the prior session through **16:00**;
Calm A's `rth_end` is **15:59**. Real frames carry both bars so both are satisfiable, but a
fixture that stopped at 15:59 made the gate refuse with `partial_coverage` — which is how the
difference surfaced. Not changed, because both are correct for their own purpose and Stage 4
established the 15:59 boundary deliberately; recorded here because two constants describing one
session boundary is a place where drift lives.

---

## 6. A superseded test, re-pointed rather than deleted

Stage 5D asserted that the Calm slot records `live_source_not_ready`. That is exactly what this
stage changed, so the test failed — correctly. Asserting the old reason would have pinned the gap
in place. It now asserts that the Calm slot **decides**, and checks the refusal that genuinely
remains: the Stress window's.

---

## 7. Runbook

Precondition 2b is now **PARTIAL**, with the caveat stated in the row itself: Calm A closed
**offline**, Stress still in scratch. The check command names `live-shadow` and a slot instant,
and requires a list for **both** windows. The paragraph beneath spells out that every test injects
`FrameBarProvider`, that no broker provider has been constructed, and that the honest statement
remains "Calm A is answerable offline" — never "Track 1 can trade today".

The causal-ATR consequence is recorded there too, so the first person to compare a live risk
figure against the artifact's is not surprised by it.

---

## 8. Tests

| suite | result |
|---|---|
| Stage 5E live source (new) | **30 passed** |
| Stage 5D shadow-live wiring | **18 passed** |
| Stage 5C shadow readiness | **11 passed** |
| Stage 5B runbook fix | **22 passed** |
| Stage 4C live source | **46 passed** |
| Stage 3B blockers | **72 passed, 1 skipped** |
| Stage 4 production-clean, all windows | **32 passed** (17:06) |

`global_index/test_event_playback.py` was not run.

**The all-window Stage 4 run was repeated on purpose this time.** Stage 5D did not need it;
Stage 5E refactored `track1_calm_a.detect()` to share its condition test with the new 10:00 path,
and the only thing that proves that refactor did not change the rule is the 421-of-421 Calm A
reproduction across all three windows.

---

## 9. What remains for 2b

1. **The Stress rule** — promoted out of `scratch/`, or a decision that Track 1 does not run that
   sleeve. It is 24 of the 25 slots, so this is the larger half.
2. **A real bar provider** — `IBKRBarProvider` wrapping the runner's existing broker. Never
   constructed here, so nothing in this stage says a live feed produces these candidates.

Orders remain impossible throughout: `blocking()` returns `B1` alone, no confirmation file exists,
and `TRACK1_ORDERS_APPROVED` is unset.
