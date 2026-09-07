# Stage 5V-1 / 5R-2 — the NKD gate was asking for bars from the future

**2026-08-25, 02:44–03:00 ET ·** the `global_nkd` window was open for most of it and was **not
disturbed**: no scheduler or backend restarted, no runtime file written, no ledger row edited,
nothing backfilled · two **read-only** IBKR fetches on client id 95, disclosed below · no order
· no confirmation file · `TRACK1_ORDERS_APPROVED` unset · no `--allow-orders` · no commit.

---

## Verdict: **READY_FOR_NEXT_JUDGEABLE_WINDOW**

Both refusal codes are fixed, and the fix was confirmed **live, in production, mid-window**.

---

## What was actually wrong — two bugs, one root cause

The prompt's hypothesis was right about `partial_coverage` and there was a second bug behind
`stale`. Both are the same mistake: **a grid-quantised frame compared against a continuous
instant.**

First, where the codes come from. `run_live_day_track1` builds the ledger `detail` as
`",".join(verdict.codes)` from `intra.validate` **and nothing else** — so both codes were the
intraday gate, not the SPY freshness gate. That mattered, because the obvious story was the
`spy_refresh_pm` staleness, and it was the wrong story: three slots ran *after* the CSV was
refreshed to 2026-08-24 and still said `partial_coverage,stale`, and `freshness.evaluate()` was
returning `allow=True` by then.

### Bug 1 — `partial_coverage`: the span demanded the end of the band

```python
_span_check("today_span", idx, day, req.today_from, req.today_to, ...)
```

`today_to` for `global_nkd` is **15:55** — the end of the scan. So a 14:10 slot required 105
minutes of bars that had not happened. Measured on the real live frame at 15:46 JST:

```text
today_span   partial_coverage   last bar in the span is 15:46, expected 15:55
```

…on a frame holding **107 contiguous bars** of the session.

### Bug 2 — `stale`: off by the slot's own three seconds

```python
horizon = min(now, latest)
if last + bar_minutes < horizon:  STALE
```

A slot fires about three seconds after its own minute. The newest *complete* five-minute bucket
is therefore exactly one bar back, and the test failed by those seconds:

```text
staleness   stale   last bar 15:45 is more than one 5-minute bar behind 15:50:03
```

`15:45 + 5min = 15:50:00 < 15:50:03`. Three seconds.

---

## The fix — one idea, used twice

```python
def _last_closed_bar(now, bar_minutes):
    """The newest grid point whose bar must CERTAINLY have finished by `now`."""
    n = pd.Timedelta(minutes=bar_minutes)
    return pd.Timestamp(now).floor(n) - n
```

Flooring alone is not enough: at 14:10:03 the 14:10 bar is the one still *open* — Stage 5R-0
drops it for exactly that reason. So the answer is one whole bar back from the floor.

It is used in **both** places, deliberately, so the span and the staleness rule cannot disagree
about which bar the frame owes. A test parses `validate` and requires exactly two call sites.

**The span bound is per-sleeve and declared, not blanket.** A new field
`today_to_follows_now` is `True` only for the two SCANNING sleeves:

| sleeve | `today_to` | what it is | follows the slot? |
|---|---|---|---|
| `roska4_calm` | 10:00 | **the entry bar itself** | no |
| `roska4_stress` | 10:30 | a level, and it sits *before* `decide_from` 10:35 | no |
| `roska4_swing` | 15:55 | where the scan **stops** | **yes** |
| `global_nkd` | 15:55 | where the scan **stops** | **yes** |

A blanket `min()` would have silently weakened Calm: at 10:00:03 its span would have shrunk to
09:30–09:55 and stopped demanding the 10:00 bar in the span. Declaring it per sleeve makes that
impossible and reviewable.

**Swing had the identical defect** and is fixed with it — measurement, not assumption: its
`today_to` is the same end-of-band shape. Its 14:00 low bound is untouched.

**Nothing was widened.** The span is still contiguous from `today_from`, a hole still refuses, a
frame starting late still refuses, and staleness still refuses a frame two bars behind.

---

## Live confirmation, in production, across the two edits

The window was open while the fix landed, and the ledger recorded the transition:

```text
02:45 ET   gate_refused   partial_coverage,stale   ← old code
02:50 ET   gate_refused   stale                    ← span fix live, staleness fix not yet
02:55 ET   gate_refused   too_late                 ← both live
```

Nothing was restarted; slot subprocesses import fresh, which is why this was observable at all.
And the real live frame, run through the fixed gate by hand at 15:50:52 JST:

```text
allow = True   codes = ()
   today_span   ok   22 bars 14:00-15:45 contiguous
   staleness    ok   last bar 15:50
```

### `too_late` on the final slot is not a third bug

The 02:55 slot fires ~3 s after `decide_to` and can never decide. That is pre-existing and
benign: the acceptance gate classifies `too_late` as **`observed_window_shut`**, an OBSERVED
class — so it cannot make a window incomplete. `partial_coverage,stale` classified as
**`observed_hard_refusal`**, which is precisely why the other nineteen mattered. Both are now
pinned by test.

---

## The eight things the stage had to prove

| # | claim | how |
|---|---|---|
| 1 | a frame ending 14:35 passes a 14:35 slot | five slot times, and a walk of all 21 decidable slots |
| 2 | the same frame fails a later slot | three later slots, `stale` |
| 3 | a missing bar inside 14:00→now still refuses | `gap_in_coverage`; a late start still `partial_coverage` |
| 4 | a frame more than one bar behind still refuses stale | 1 / 2 / 6 bars behind — one back is *not* stale, two is |
| 5 | no slot before 15:55 needs a future bar | the 21-slot walk |
| 6 | the live rows are explained and untouched | a test reads the real ledger and asserts every refusal is one of the two codes, `decided=False`, nothing edited |
| 7 | artifact reproduction unchanged | Stage 4 three-window run (`TRACK1_STAGE4_ALL=1`): **32 passed**, 16m01s — Normal-R4 incl. MNKD 1,223/1,223, Calm A 421/421, Stress 50/3/4 |
| 8 | orders still impossible | B1 and PAPER_SHADOW_EVIDENCE both blocking, no confirmation file, env unset, no `--allow-orders` |

**31 tests**, and **9 mutations, all red**. Most of the mutations do not remove the fix — they
*overshoot* it, because the danger with a causality fix is that it widens something:

| | mutation | caught by |
|---|---|---|
| M1 | the fix removed | the slot-passes test |
| M2 | the LOW bound follows the slot too | a late-starting frame must still refuse |
| M3 | the gap check dropped | the hole test |
| M4 | staleness reaches back a whole day | a stale frame must still refuse |
| M5 | the horizon uses raw `now` again | the three-second case |
| M6 | Calm dragged into the dynamic bound | only-two-scanning-sleeves |
| M7 | Swing loses its 14:00 low bound | the swing test |
| M8 | the NKD requirement validated on ET | the 13-hour clock test |
| M9 | `too_late` removed from the clock codes | window-shut vs hard-refusal |

---

## Read-only broker use, disclosed

Two fetches on **client id 95** — deliberately clear of Track 1 data (89), Track 1 safety (90),
legacy (1) and the daily updater (2) — to build the real live frame and run the gate on it.
Nothing was written; no order; disconnected after each. This was the only way to see the actual
frame while the window was still open, and the data is gone now.

---

## What this window will be judged as

It will not PASS, and that is correct. Nineteen slots were hard-refused by the old code before
the fix landed, so the window closed `incomplete` with `observed_slots: 0` of 22. The audit at
03:05 ET will say so.

Nothing was backfilled and no row was edited. **The next NKD window, 2026-08-26 01:10 ET, is the
first that can be judged on the fixed gate.**

One thing to watch there: `spy_refresh_pm` fires for the first time today at 16:20 ET, so
Wednesday's freshness should pass — but that is a different gate from this one and it has not
yet been observed working.

---

## Files

```text
global_index/track1_intraday.py    + _last_closed_bar() and _as_hhmm()
                                   + Requirement.today_to_follows_now (swing, nkd only)
                                   today_span high bound follows the slot for scanning sleeves
                                   staleness horizon is the last closed bar, not raw `now`
scratch/test_track1_stage5v1_intraday_causality_20260825.py    31 tests
scratch/track1_stage5v1_mutations_20260825.py                  9 mutations, all red
scratch/test_track1_stage5f_stress_live_source_20260823.py     stale "B1 is the only blocker"
                                                               literal — the eighth and last
                                                               copy, left from before Stage 5S
```

No runtime evidence written, no ledger row edited, nothing backfilled.

---

## Regression, complete

| suite group | result |
|---|---|
| Stage 4 three-window reproduction (`TRACK1_STAGE4_ALL=1`) | **32 passed**, 16m01s |
| intraday / audit / identity / journal (9 files) | **368 passed, 2 skipped** + the one stale literal repaired |
| Stage 5V-1 | **31 passed** |
| Stage 5V-1 mutations | 9 red, 0 green |

The gate change touches what a slot is ALLOWED to decide on, not what the sleeves compute, so
the reproduction was the check that mattered most here — and the committed rows are unmoved.
